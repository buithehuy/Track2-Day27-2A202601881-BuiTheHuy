"""Simple contract validator used as the starter baseline.

The implementation intentionally covers only common deterministic checks.
Students are expected to extend it with:
- stronger type validation/coercion rules,
- freshness checks,
- cross-field/cross-table assertions,
- severity-aware actions (block/quarantine/warn),
- richer observability metadata.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml


_SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


def _action_for_severity(severity: str) -> str:
    """Map contract severity to a safe default operational action."""
    return {"critical": "block", "warning": "warn", "info": "log"}.get(
        severity, "warn"
    )


def _issue(
    check: str,
    *,
    column: str | None,
    severity: str,
    passed: bool,
    details: str,
) -> dict[str, Any]:
    return {
        "check": check,
        "column": column,
        "severity": severity,
        "action": _action_for_severity(severity),
        "passed": bool(passed),
        "details": details,
    }


def _type_failure_mask(series: pd.Series, declared_type: str) -> pd.Series:
    """Return rows that violate a declared contract type without coercing data."""
    non_null = series.notna()
    if declared_type == "string":
        return non_null & ~series.map(lambda value: isinstance(value, str))
    if declared_type == "integer":
        numeric = pd.to_numeric(series, errors="coerce")
        return non_null & (numeric.isna() | (numeric % 1 != 0))
    if declared_type == "number":
        numeric = pd.to_numeric(series, errors="coerce")
        return non_null & numeric.isna()
    if declared_type == "datetime":
        parsed = pd.to_datetime(series, errors="coerce", utc=True)
        return non_null & parsed.isna()
    return pd.Series(False, index=series.index)


def load_contract(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_dataframe(df: pd.DataFrame, contract: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    columns = contract.get("columns", {})

    for column, rules in columns.items():
        severity = rules.get("severity", "warning")
        required = bool(rules.get("required", False))

        if column not in df.columns:
            if required:
                issues.append(
                    _issue(
                        "required_column",
                        column=column,
                        severity=severity,
                        passed=False,
                        details=f"Missing required column: {column}",
                    )
                )
            continue

        series = df[column]

        declared_type = rules.get("type")
        if declared_type:
            invalid_type = _type_failure_mask(series, str(declared_type))
            invalid_count = int(invalid_type.sum())
            issues.append(
                _issue(
                    "type",
                    column=column,
                    severity=severity,
                    passed=(invalid_count == 0),
                    details=f"declared={declared_type}; invalid_count={invalid_count}",
                )
            )

        if required:
            null_count = int(series.isna().sum())
            issues.append(
                _issue(
                    "not_null",
                    column=column,
                    severity=severity,
                    passed=(null_count == 0),
                    details=f"null_count={null_count}",
                )
            )

        if rules.get("unique"):
            duplicate_count = int(series.duplicated(keep=False).sum())
            issues.append(
                _issue(
                    "unique",
                    column=column,
                    severity=severity,
                    passed=(duplicate_count == 0),
                    details=f"duplicate_rows={duplicate_count}",
                )
            )

        accepted = rules.get("accepted_values")
        if accepted is not None:
            invalid_mask = series.notna() & ~series.isin(accepted)
            invalid_count = int(invalid_mask.sum())
            issues.append(
                _issue(
                    "accepted_values",
                    column=column,
                    severity=severity,
                    passed=(invalid_count == 0),
                    details=f"invalid_count={invalid_count}; accepted={accepted}",
                )
            )

        # Starter numeric range support. Type validation is intentionally minimal.
        if "min" in rules or "max" in rules:
            numeric = pd.to_numeric(series, errors="coerce")
            invalid = pd.Series(False, index=series.index)
            if "min" in rules:
                invalid |= numeric < rules["min"]
            if "max" in rules:
                invalid |= numeric > rules["max"]
            # Values rejected by type validation are not range violations.
            invalid &= numeric.notna()
            invalid_count = int(invalid.fillna(False).sum())
            issues.append(
                _issue(
                    "range",
                    column=column,
                    severity=severity,
                    passed=(invalid_count == 0),
                    details=f"invalid_count={invalid_count}",
                )
            )

    return issues


def failed_issues(issues: list[dict[str, Any]], min_severity: str | None = None) -> list[dict[str, Any]]:
    failed = [i for i in issues if not i.get("passed", False)]
    if min_severity is None:
        return failed
    threshold = _SEVERITY_ORDER[min_severity]
    return [
        i
        for i in failed
        if _SEVERITY_ORDER.get(i.get("severity", "warning"), 1) >= threshold
    ]
