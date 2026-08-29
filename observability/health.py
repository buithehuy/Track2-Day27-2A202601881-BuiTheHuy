"""Turn low-level data signals into an actionable incident decision."""
from __future__ import annotations

from typing import Any, Iterable

from observability.lineage import get_downstream_assets

_RANK = {"info": 0, "warning": 1, "critical": 2}


def signal(
    signal_id: str,
    *,
    domain: str,
    fired: bool,
    severity: str,
    action: str,
    owner: str,
    summary: str,
    evidence: dict[str, Any] | None = None,
    source_asset: str | None = None,
    runbook: str | None = None,
) -> dict[str, Any]:
    """Create a stable, JSON-serializable monitoring signal."""
    return {
        "id": signal_id,
        "domain": domain,
        "fired": bool(fired),
        "severity": severity if severity in _RANK else "warning",
        "action": action,
        "owner": owner,
        "summary": summary,
        "evidence": evidence or {},
        "source_asset": source_asset,
        "runbook": runbook,
    }


def incident_decision(
    signals: Iterable[dict[str, Any]],
    lineage_graph: dict[str, list[str]],
) -> dict[str, Any]:
    """Correlate signals, choose severity/action, and calculate blast radius."""
    all_signals = list(signals)
    active = [item for item in all_signals if item.get("fired")]
    active.sort(key=lambda item: (-_RANK.get(str(item.get("severity")), 1), str(item.get("id"))))

    affected: list[str] = []
    seen: set[str] = set()
    for item in active:
        source = item.get("source_asset")
        if not source:
            continue
        for asset in [source, *get_downstream_assets(lineage_graph, str(source))]:
            if asset not in seen:
                seen.add(asset)
                affected.append(asset)

    critical = [item for item in active if item.get("severity") == "critical"]
    containment = [item for item in active if item.get("action") in {"block", "quarantine"}]
    domains = {str(item.get("domain")) for item in active}
    corroborated = len(active) >= 2 and len(domains) >= 1

    if critical:
        status, severity, publish = "incident", "P1", False
    elif containment or corroborated:
        status, severity, publish = "incident", "P2", False
    elif active:
        status, severity, publish = "degraded", "P3", True
    else:
        status, severity, publish = "healthy", "none", True

    actions: list[str] = []
    for item in active:
        action = str(item.get("action", "investigate"))
        owner = str(item.get("owner", "unassigned"))
        rendered = f"{action}: {item.get('id')} ({owner})"
        if rendered not in actions:
            actions.append(rendered)

    return {
        "status": status,
        "severity": severity,
        "publish_downstream": publish,
        "active_signal_count": len(active),
        "corroborated": corroborated,
        "active_signals": active,
        "affected_assets": affected,
        "recommended_actions": actions,
    }

