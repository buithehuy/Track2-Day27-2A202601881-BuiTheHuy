#!/usr/bin/env python3
"""Small Great Expectations Core 1.21 example.

This file demonstrates the modern dataframe flow with a few expectations.
Students should extend it into a reusable Expectation Suite / Validation
Definition / Checkpoint and design actions based on severity.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import great_expectations as gx
except ImportError as exc:  # friendlier classroom failure
    raise SystemExit("great_expectations is not installed. Run: pip install -r requirements.txt") from exc


def main() -> None:
    df = pd.read_csv(ROOT / "data" / "incoming" / "orders.csv")
    context = gx.get_context()

    # Use unique names so re-running inside an ephemeral context is simple.
    data_source = context.data_sources.add_pandas("orders_pandas")
    asset = data_source.add_dataframe_asset(name="orders_dataframe")
    batch_definition = asset.add_batch_definition_whole_dataframe("whole_orders")
    batch = batch_definition.get_batch(batch_parameters={"dataframe": df})

    expectations = [
        gx.expectations.ExpectColumnValuesToNotBeNull(
            column="order_id", severity="critical"
        ),
        gx.expectations.ExpectColumnValuesToBeUnique(
            column="order_id", severity="critical"
        ),
        gx.expectations.ExpectColumnValuesToBeBetween(
            column="amount", min_value=0, severity="critical"
        ),
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="currency", value_set=["USD", "VND"], severity="critical"
        ),
    ]

    suite = context.suites.add(gx.core.expectation_suite.ExpectationSuite(name="orders_suite"))
    for expectation in expectations:
        suite.add_expectation(expectation)
    validation_definition = context.validation_definitions.add(
        gx.core.validation_definition.ValidationDefinition(
            name="orders_validation", data=batch_definition, suite=suite
        )
    )
    checkpoint = context.checkpoints.add(
        gx.Checkpoint(
            name="orders_checkpoint",
            validation_definitions=[validation_definition],
            result_format="SUMMARY",
        )
    )
    result = checkpoint.run(batch_parameters={"dataframe": df})
    print("\nGX checkpoint result:", "PASS" if result.success else "FAIL")
    print("Validation definitions:", len(result.run_results))


if __name__ == "__main__":
    main()
