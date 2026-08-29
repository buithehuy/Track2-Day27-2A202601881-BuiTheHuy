#!/usr/bin/env python3
"""Reusable GX suite, validation definition, checkpoint and quarantine action."""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Union

import pandas as pd
from typing_extensions import override

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import great_expectations as gx
    from great_expectations.checkpoint import ActionContext, CheckpointResult, ValidationAction
except ImportError as exc:
    raise SystemExit("great_expectations is not installed. Run: pip install -r requirements.txt") from exc


class QuarantineOnFailure(ValidationAction):
    """Persist a rejected batch; the contract control plane decides block severity."""

    type: Literal["quarantine_on_critical_failure"] = "quarantine_on_critical_failure"
    quarantine_dir: str
    source_path: str

    @override
    def run(self, checkpoint_result: CheckpointResult,
            action_context: Union[ActionContext, None]) -> dict:
        target = Path(self.quarantine_dir)
        target.mkdir(parents=True, exist_ok=True)
        failed = checkpoint_result.success is False
        quarantine_path = None
        if failed:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            quarantine_path = target / f"orders-{stamp}.csv"
            shutil.copy2(self.source_path, quarantine_path)
        payload = {"checkpoint_success": checkpoint_result.success,
                   "action": "quarantine" if failed else "allow",
                   "reason": "orders_suite_failure" if failed else "all_suite_checks_passed",
                   "quarantine_path": str(quarantine_path) if quarantine_path else None}
        (target / "latest_gx_action.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


def main() -> None:
    df = pd.read_csv(ROOT / "data" / "incoming" / "orders.csv")
    context = gx.get_context()
    data_source = context.data_sources.add_pandas("orders_pandas")
    asset = data_source.add_dataframe_asset(name="orders_dataframe")
    batch_definition = asset.add_batch_definition_whole_dataframe("whole_orders")

    suite = context.suites.add(gx.ExpectationSuite(name="orders_contract_suite"))
    for expectation in [
        gx.expectations.ExpectTableColumnsToMatchSet(
            column_set=["order_id", "customer_id", "amount", "currency", "status", "created_at", "updated_at"],
            exact_match=True,
            severity="critical",
        ),
        gx.expectations.ExpectColumnValuesToNotBeNull(column="order_id", severity="critical"),
        gx.expectations.ExpectColumnValuesToBeUnique(column="order_id", severity="critical"),
        gx.expectations.ExpectColumnValuesToNotBeNull(column="customer_id", severity="critical"),
        gx.expectations.ExpectColumnValuesToBeBetween(column="amount", min_value=0, severity="critical"),
        gx.expectations.ExpectColumnValuesToBeInSet(column="currency", value_set=["USD", "VND"], severity="critical"),
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="status", value_set=["pending", "completed", "refunded", "cancelled"], severity="warning"
        ),
    ]:
        suite.add_expectation(expectation)

    validation_definition = context.validation_definitions.add(
        gx.ValidationDefinition(name="orders_contract_validation", data=batch_definition, suite=suite)
    )
    checkpoint = context.checkpoints.add(gx.Checkpoint(
        name="orders_contract_checkpoint",
        validation_definitions=[validation_definition],
        actions=[QuarantineOnFailure(
            name="quarantine_critical_orders",
            quarantine_dir=str(ROOT / "reports" / "quarantine"),
            source_path=str(ROOT / "data" / "incoming" / "orders.csv"),
        )],
        result_format={"result_format": "SUMMARY"},
    ))
    result = checkpoint.run(batch_parameters={"dataframe": df})
    print(result.describe())
    print("GX decision: allow" if result.success else "GX decision: quarantine (control plane sets block severity)")


if __name__ == "__main__":
    main()
