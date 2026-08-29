#!/usr/bin/env python3
"""Run the local observability control plane and emit an actionable snapshot."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from observability.anomaly import detect_anomaly
from observability.distribution import detect_categorical_shift, detect_distribution_shift
from observability.health import incident_decision, signal
from observability.lineage import get_column_downstream, get_downstream_assets
from observability.rag_metrics import detect_text_length_shift
from observability.slo import calculate_slo, evaluate_slo_history
from src.contract_validator import failed_issues, load_contract, validate_dataframe
from src.io_utils import load_jsonl

RUNBOOK = "docs/OBSERVABILITY_RUNBOOK.md"
RUN_HISTORY = ROOT / "reports" / "monitoring_history.jsonl"


def _failed_check(issues: list[dict[str, Any]], check: str) -> dict[str, Any] | None:
    return next((item for item in issues if item.get("check") == check and not item.get("passed")), None)


def _read_run_history() -> list[dict[str, Any]]:
    if not RUN_HISTORY.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in RUN_HISTORY.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("slis"), dict):
            rows.append(payload)
    return rows[-199:]


def _write_run_history(rows: list[dict[str, Any]]) -> None:
    RUN_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    rendered = "\n".join(json.dumps(row, sort_keys=True) for row in rows[-200:]) + "\n"
    RUN_HISTORY.write_text(rendered, encoding="utf-8")


def _kb_version_rollbacks(current_docs: list[dict[str, Any]], baseline_docs: list[dict[str, Any]]) -> list[str]:
    baseline_versions = {str(doc.get("doc_id")): doc.get("version") for doc in baseline_docs}
    rollback_ids: list[str] = []
    for doc in current_docs:
        doc_id, version = str(doc.get("doc_id")), doc.get("version")
        baseline_version = baseline_versions.get(doc_id)
        try:
            if baseline_version is not None and int(version) < int(baseline_version):
                rollback_ids.append(doc_id)
        except (TypeError, ValueError):
            continue
    return sorted(set(rollback_ids))


def main() -> None:
    now = datetime.now(timezone.utc)
    config = load_contract(ROOT / "lab_config.yaml")
    orders = pd.read_csv(ROOT / "data" / "incoming" / "orders.csv")
    customers = pd.read_csv(ROOT / "data" / "incoming" / "customers.csv")
    baseline_orders = pd.read_csv(ROOT / "data" / "baseline" / "orders.csv")
    metric_history = pd.read_csv(ROOT / "data" / "history" / "metrics_history.csv")

    orders_contract = load_contract(ROOT / "contracts" / "orders_contract.yaml")
    order_issues = validate_dataframe(orders, orders_contract)
    order_failed = failed_issues(order_issues)
    order_critical_failed = failed_issues(order_issues, min_severity="critical")
    order_freshness_failure = _failed_check(order_issues, "freshness")

    timestamps = pd.to_datetime(orders.get("updated_at"), utc=True, errors="coerce")
    latest_timestamp = timestamps.max()
    freshness_minutes = None if pd.isna(latest_timestamp) else (
        pd.Timestamp(now) - latest_timestamp
    ).total_seconds() / 60.0

    current_dow = now.weekday()
    segment = metric_history.loc[metric_history["day_of_week"] == current_dow, "row_count"].tail(8).tolist()
    row_result = detect_anomaly(
        len(orders),
        metric_history["row_count"].tail(30).tolist(),
        method="auto",
        context={"metric_name": "row_count", "day_of_week": current_dow, "same_segment_history": segment},
    )
    amount_distribution = detect_distribution_shift(
        orders.get("amount", pd.Series(dtype=float)), baseline_orders.get("amount", pd.Series(dtype=float))
    )
    status_distribution = detect_categorical_shift(
        orders.get("status", pd.Series(dtype=str)), baseline_orders.get("status", pd.Series(dtype=str))
    )
    observed_columns = [name for name in orders_contract.get("columns", {}) if name in orders.columns]
    null_rate = 0.0 if not observed_columns or orders.empty else float(orders[observed_columns].isna().sum().sum()) / (
        len(orders) * len(observed_columns)
    )
    null_rate_signal = detect_anomaly(
        null_rate, metric_history["null_rate"].tail(30).tolist(), method="auto", context={"metric_name": "null_rate"}
    )

    active_mask = customers.get("is_active", pd.Series(False, index=customers.index)).astype(str).str.lower().eq("true")
    active_counts = customers.loc[active_mask].groupby("customer_id").size() if "customer_id" in customers else pd.Series(dtype=int)
    duplicate_active_customers = sorted(map(str, active_counts[active_counts > 1].index.tolist()))
    customer_ids = set(customers.get("customer_id", pd.Series(dtype=str)).dropna().astype(str))
    order_customer_ids = set(orders.get("customer_id", pd.Series(dtype=str)).dropna().astype(str))
    orphan_customer_ids = sorted(order_customer_ids - customer_ids)

    docs = load_jsonl(ROOT / "data" / "incoming" / "kb_documents.jsonl")
    baseline_docs = load_jsonl(ROOT / "data" / "baseline" / "kb_documents.jsonl")
    kb_contract = load_contract(ROOT / "contracts" / "kb_contract.yaml")
    kb_issues = validate_dataframe(pd.DataFrame(docs), kb_contract)
    kb_failed = failed_issues(kb_issues)
    kb_critical_failed = failed_issues(kb_issues, min_severity="critical")
    kb_freshness_failure = _failed_check(kb_issues, "freshness")
    kb_text_result = detect_text_length_shift(
        [str(doc.get("content", "")) for doc in docs], metric_history["mean_text_length"].tail(14).tolist()
    )
    rollback_ids = _kb_version_rollbacks(docs, baseline_docs)

    with open(ROOT / "data" / "baseline" / "lineage_graph.json", "r", encoding="utf-8") as handle:
        lineage_payload = json.load(handle)
    dataset_lineage = lineage_payload["dataset_lineage"]
    column_lineage = lineage_payload.get("column_lineage", {})

    signals = [
        signal("orders_contract_critical", domain="orders", fired=bool(order_critical_failed), severity="critical",
               action="block", owner="commerce-data", summary="Critical orders contract violation",
               evidence={"failed_checks": order_critical_failed}, source_asset="raw_orders", runbook=RUNBOOK),
        signal("orders_freshness", domain="orders", fired=order_freshness_failure is not None, severity="warning",
               action="quarantine", owner="commerce-data", summary="Orders batch exceeded the 30-minute freshness SLO",
               evidence={"freshness_minutes": freshness_minutes, "failure": order_freshness_failure},
               source_asset="raw_orders", runbook=RUNBOOK),
        signal("orders_volume", domain="orders", fired=row_result["is_anomaly"], severity="warning",
               action="quarantine", owner="commerce-data", summary="Seasonality-aware order volume anomaly",
               evidence=row_result, source_asset="raw_orders", runbook=RUNBOOK),
        signal("orders_amount_distribution", domain="orders", fired=amount_distribution["is_anomaly"], severity="warning",
               action="quarantine", owner="commerce-data", summary="Order amount distribution drift",
               evidence=amount_distribution, source_asset="raw_orders", runbook=RUNBOOK),
        signal("orders_status_mix", domain="orders", fired=status_distribution["is_anomaly"], severity="warning",
               action="investigate", owner="commerce-data", summary="Order status mix drift",
               evidence=status_distribution, source_asset="raw_orders", runbook=RUNBOOK),
        signal("orders_null_rate", domain="orders", fired=null_rate_signal["is_anomaly"], severity="warning",
               action="quarantine", owner="commerce-data", summary="Null-rate anomaly",
               evidence={**null_rate_signal, "current_null_rate": null_rate}, source_asset="raw_orders", runbook=RUNBOOK),
        signal("customer_scd_overlap", domain="customers", fired=bool(duplicate_active_customers), severity="critical",
               action="block", owner="commerce-data", summary="Multiple active SCD rows can inflate revenue",
               evidence={"customer_ids": duplicate_active_customers, "count": len(duplicate_active_customers)},
               source_asset="raw_customers", runbook=RUNBOOK),
        signal("orders_orphan_customer", domain="customers", fired=bool(orphan_customer_ids), severity="critical",
               action="block", owner="commerce-data", summary="Orders reference missing customers",
               evidence={"customer_ids": orphan_customer_ids[:20], "count": len(orphan_customer_ids)},
               source_asset="raw_orders", runbook=RUNBOOK),
        signal("kb_contract_critical", domain="rag", fired=bool(kb_critical_failed), severity="critical",
               action="block", owner="support-ai", summary="Critical knowledge-base contract violation",
               evidence={"failed_checks": kb_critical_failed}, source_asset="kb_documents", runbook=RUNBOOK),
        signal("kb_freshness", domain="rag", fired=kb_freshness_failure is not None, severity="warning",
               action="quarantine", owner="support-ai", summary="Knowledge base exceeded its 60-minute freshness SLO",
               evidence={"failure": kb_freshness_failure}, source_asset="kb_documents", runbook=RUNBOOK),
        signal("kb_text_length", domain="rag", fired=kb_text_result["is_anomaly"], severity="warning",
               action="quarantine", owner="support-ai", summary="Knowledge-base content length collapsed or drifted",
               evidence=kb_text_result, source_asset="kb_documents", runbook=RUNBOOK),
        signal("kb_version_rollback", domain="rag", fired=bool(rollback_ids), severity="critical",
               action="block", owner="support-ai", summary="Knowledge-base document version regressed",
               evidence={"doc_ids": rollback_ids, "count": len(rollback_ids)}, source_asset="kb_documents", runbook=RUNBOOK),
    ]

    current_slis = {
        "critical_contract_pass": not bool(order_critical_failed or kb_critical_failed),
        "revenue_freshness": order_freshness_failure is None,
        "rag_index_freshness": kb_freshness_failure is None,
    }
    run_history = _read_run_history()
    run_history.append({"timestamp": now.isoformat(), "slis": current_slis})
    _write_run_history(run_history)
    slo_config = config.get("slo", {})
    targets = {
        "critical_contract_pass": float(slo_config.get("critical_contract_pass", {}).get("target", 0.999)),
        "revenue_freshness": float(slo_config.get("revenue_freshness", {}).get("target", 0.995)),
        "rag_index_freshness": float(slo_config.get("rag_index_freshness", {}).get("target", 0.99)),
    }
    alerting = config.get("alerting", {})
    short_window = int(alerting.get("short_window_checks", 5))
    long_window = int(alerting.get("long_window_checks", 30))
    slo_windows = {
        name: evaluate_slo_history(
            [bool(item["slis"].get(name, True)) for item in run_history],
            target=target,
            short_window=short_window,
            long_window=long_window,
        )
        for name, target in targets.items()
    }
    for name, status in slo_windows.items():
        signals.append(signal(
            f"{name}_fast_burn", domain="slo", fired=bool(status["alert"]["page"]), severity="critical",
            action="page", owner="data-reliability", summary=f"Sustained multi-window error-budget burn: {name}",
            evidence=status, runbook=RUNBOOK,
        ))

    decision = incident_decision(signals, dataset_lineage)
    contract_slo = calculate_slo(
        targets["critical_contract_pass"],
        bad_events=0 if current_slis["critical_contract_pass"] else 1,
        total_events=1,
    )
    report = {
        "schema_version": 2,
        "timestamp": now.isoformat(),
        "system_status": decision,
        "signals": signals,
        "slis": current_slis,
        "slo_windows": slo_windows,
        "telemetry_coverage": {
            "embedding_norm_current_batch": {
                "status": "not_instrumented",
                "impact": "Embedding-model drift cannot be verified from the supplied current dataset",
                "action": "Export current embedding norms and call rag_embedding_shift",
                "owner": "support-ai",
            }
        },
        "orders_rows": int(len(orders)),
        "failed_contract_checks": len(order_failed),
        "critical_contract_failures": len(order_critical_failed),
        "order_contract_results": order_issues,
        "row_count_anomaly": row_result,
        "amount_distribution_signal": amount_distribution,
        "status_distribution_signal": status_distribution,
        "null_rate_signal": {**null_rate_signal, "current_null_rate": null_rate},
        "freshness_minutes": freshness_minutes,
        "customer_integrity": {
            "duplicate_active_customer_ids": duplicate_active_customers,
            "orphan_customer_ids": orphan_customer_ids,
        },
        "kb_failed_contract_checks": len(kb_failed),
        "kb_critical_contract_failures": len(kb_critical_failed),
        "kb_contract_results": kb_issues,
        "kb_text_length_signal": kb_text_result,
        "kb_version_rollback_ids": rollback_ids,
        "contract_slo": contract_slo,
        "sample_blast_radius_from_stg_orders": get_downstream_assets(dataset_lineage, "stg_orders"),
        "column_blast_radius_from_order_amount": get_column_downstream(column_lineage, "raw_orders.amount"),
    }
    out = ROOT / "reports" / "latest_metrics.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("=== DATA RELIABILITY CONTROL PLANE ===")
    print(f"status / severity         : {decision['status']} / {decision['severity']}")
    print(f"publish downstream        : {decision['publish_downstream']}")
    print(f"active signals            : {decision['active_signal_count']}")
    print(f"orders / contract fails   : {len(orders)} / {len(order_failed)}")
    print(f"row-count anomaly         : {row_result['is_anomaly']} ({row_result['method']}, score={row_result['score']:.2f})")
    print(f"freshness minutes         : {freshness_minutes if freshness_minutes is not None else 'unknown'}")
    print(f"KB contract failures      : {len(kb_failed)}")
    print(f"blast radius              : {', '.join(decision['affected_assets']) or 'none'}")
    print(f"report                    : {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
