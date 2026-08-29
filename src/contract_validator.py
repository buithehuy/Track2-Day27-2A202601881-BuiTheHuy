"""Contract validation with deterministic checks and operational actions."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

_SEVERITY_ACTION = {"critical": "block", "warning": "quarantine", "info": "warn"}
_SUPPORTED_TYPES = {"integer", "int", "number", "float", "decimal", "datetime", "timestamp", "date", "string", "str"}


def _issue(check: str, *, column: str | None, severity: str, passed: bool, details: str) -> dict[str, Any]:
    """Return the stable result shape, enriched with the operational action."""
    severity = severity if severity in _SEVERITY_ACTION else "warning"
    return {"check": check, "column": column, "severity": severity,
            "action": _SEVERITY_ACTION[severity], "passed": bool(passed), "details": details}


def load_contract(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _type_invalid_mask(series: pd.Series, expected: str) -> pd.Series:
    """Check ingestible types; numeric/date strings are valid when read from CSV."""
    non_null = series.notna()
    expected = expected.lower()
    if expected in {"integer", "int"}:
        numeric = pd.to_numeric(series, errors="coerce")
        bool_values = series.map(lambda value: isinstance(value, (bool,))).astype(bool)
        return non_null & (numeric.isna() | ((numeric % 1) != 0) | bool_values)
    if expected in {"number", "float", "decimal"}:
        return non_null & pd.to_numeric(series, errors="coerce").isna()
    if expected in {"datetime", "timestamp", "date"}:
        return non_null & pd.to_datetime(series, utc=True, errors="coerce").isna()
    if expected in {"string", "str"}:
        return non_null & series.map(lambda value: not isinstance(value, str)).astype(bool)
    return non_null


def _validation_clock(freshness: dict[str, Any]) -> pd.Timestamp:
    """Return an injectable UTC clock so freshness tests do not depend on wall time."""
    reference = freshness.get("reference_time")
    if reference is None:
        return pd.Timestamp(datetime.now(timezone.utc))
    parsed = pd.to_datetime(reference, utc=True, errors="coerce")
    if pd.isna(parsed):
        raise ValueError("freshness.reference_time must be a valid timestamp")
    return pd.Timestamp(parsed)


def _validate_freshness(
    df: pd.DataFrame, contract: dict[str, Any], reference_time: Any | None = None
) -> list[dict[str, Any]]:
    freshness = dict(contract.get("freshness") or {})
    if reference_time is not None:
        freshness["reference_time"] = reference_time
    if not freshness:
        return []
    column, severity = freshness.get("column"), freshness.get("severity", "warning")
    max_delay = freshness.get("max_delay_minutes")
    if not column or max_delay is None:
        return [_issue("freshness", column=column, severity=severity, passed=False,
                       details="freshness requires column and max_delay_minutes")]
    if column not in df.columns:
        return [_issue("freshness", column=column, severity=severity, passed=False,
                       details=f"Freshness column is missing: {column}")]
    try:
        max_delay_value = float(max_delay)
        max_future_minutes = float(freshness.get("max_future_minutes", 5))
        now = _validation_clock(freshness)
    except (TypeError, ValueError) as exc:
        return [_issue("freshness", column=column, severity=severity, passed=False,
                       details=f"Invalid freshness configuration: {exc}")]
    if max_delay_value < 0 or max_future_minutes < 0:
        return [_issue("freshness", column=column, severity=severity, passed=False,
                       details="Freshness thresholds must be non-negative")]

    timestamps = pd.to_datetime(df[column], utc=True, errors="coerce")
    latest = timestamps.max()
    if pd.isna(latest):
        return [_issue("freshness", column=column, severity=severity, passed=False,
                       details="No valid timestamp available for freshness")]
    age_minutes = (now - latest).total_seconds() / 60.0
    future_skew = age_minutes < -max_future_minutes
    passed = not future_skew and age_minutes <= max_delay_value
    condition = "future_timestamp" if future_skew else ("fresh" if passed else "stale")
    return [_issue("freshness", column=column, severity=severity,
                   passed=passed,
                   details=(f"condition={condition}; freshness_minutes={age_minutes:.2f}; "
                            f"max_delay_minutes={max_delay_value:g}; latest_timestamp={latest.isoformat()}; "
                            f"evaluated_at={now.isoformat()}"))]


def validate_dataframe(
    df: pd.DataFrame, contract: dict[str, Any], *, reference_time: Any | None = None
) -> list[dict[str, Any]]:
    """Validate a dataframe against either ``columns`` or KB-style ``fields`` rules."""
    issues: list[dict[str, Any]] = []
    columns = contract.get("columns") or contract.get("fields") or {}
    for column, rules in columns.items():
        severity, required = rules.get("severity", "warning"), bool(rules.get("required", False))
        if column not in df.columns:
            if required:
                issues.append(_issue("required_column", column=column, severity=severity,
                                     passed=False, details=f"Missing required column: {column}"))
            continue
        series = df[column]
        if required:
            null_count = int(series.isna().sum())
            issues.append(_issue("not_null", column=column, severity=severity,
                                 passed=null_count == 0, details=f"null_count={null_count}"))
        if rules.get("type"):
            expected_type = str(rules["type"]).lower()
            invalid_count = int(_type_invalid_mask(series, expected_type).sum())
            issues.append(_issue("type", column=column, severity=severity, passed=invalid_count == 0,
                                 details=(f"expected_type={rules['type']}; invalid_count={invalid_count}; "
                                          f"supported={expected_type in _SUPPORTED_TYPES}")))
        if rules.get("unique"):
            duplicate_count = int(series.dropna().duplicated(keep=False).sum())
            issues.append(_issue("unique", column=column, severity=severity, passed=duplicate_count == 0,
                                 details=f"duplicate_rows={duplicate_count}"))
        accepted = rules.get("accepted_values")
        if accepted is not None:
            invalid_count = int((series.notna() & ~series.isin(accepted)).sum())
            issues.append(_issue("accepted_values", column=column, severity=severity, passed=invalid_count == 0,
                                 details=f"invalid_count={invalid_count}; accepted={accepted}"))
        if "min" in rules or "max" in rules:
            numeric = pd.to_numeric(series, errors="coerce")
            invalid = series.notna() & numeric.isna()
            if "min" in rules:
                invalid |= numeric < rules["min"]
            if "max" in rules:
                invalid |= numeric > rules["max"]
            invalid = invalid.fillna(False)
            issues.append(_issue("range", column=column, severity=severity, passed=not bool(invalid.any()),
                                 details=f"invalid_count={int(invalid.sum())}"))
        if "min_length" in rules:
            invalid_count = int((series.dropna().astype(str).str.len() < int(rules["min_length"])).sum())
            issues.append(_issue("min_length", column=column, severity=severity, passed=invalid_count == 0,
                                 details=f"invalid_count={invalid_count}; min_length={rules['min_length']}"))
    issues.extend(_validate_freshness(df, contract, reference_time))
    return issues


def failed_issues(issues: list[dict[str, Any]], min_severity: str | None = None) -> list[dict[str, Any]]:
    failed = [issue for issue in issues if not issue.get("passed", False)]
    if min_severity is None:
        return failed
    order = {"info": 0, "warning": 1, "critical": 2}
    threshold = order.get(min_severity, 1)
    return [issue for issue in failed if order.get(issue.get("severity", "warning"), 1) >= threshold]
