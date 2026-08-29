from __future__ import annotations

from math import isfinite
from typing import Any, Iterable


def calculate_slo(target: float, bad_events: int, total_events: int) -> dict[str, Any]:
    if not 0 < target < 1:
        raise ValueError("target must be between 0 and 1 (exclusive)")
    if bad_events < 0 or total_events < 0 or bad_events > total_events:
        raise ValueError("invalid event counts")
    allowed_bad_rate = 1.0 - target
    actual_bad_rate = 0.0 if total_events == 0 else bad_events / total_events
    burn_rate = actual_bad_rate / allowed_bad_rate
    return {"target": target, "actual_bad_rate": actual_bad_rate, "allowed_bad_rate": allowed_bad_rate,
            "burn_rate": burn_rate, "remaining_error_budget_fraction": max(0.0, 1.0 - burn_rate),
            "breached": bool(actual_bad_rate > allowed_bad_rate)}


def evaluate_multiwindow_burn(*, short_window_burn: float, long_window_burn: float,
                              policy: str = "default") -> dict[str, Any]:
    """Page only on sustained burn: a high short window alone is a transient spike."""
    short, long = float(short_window_burn), float(long_window_burn)
    if not isfinite(short) or not isfinite(long) or short < 0 or long < 0:
        raise ValueError("burn rates must be finite non-negative numbers")
    if short >= 14.4 and long >= 6.0:
        page, severity, reason = True, "critical", "sustained_fast_burn"
    elif short >= 6.0 and long >= 3.0:
        page, severity, reason = True, "warning", "sustained_elevated_burn"
    elif short >= 6.0:
        page, severity, reason = False, "info", "transient_short_window_spike"
    else:
        page, severity, reason = False, "info", "within_burn_policy"
    return {"page": page, "severity": severity, "reason": reason, "policy": policy,
            "short_window_burn": short, "long_window_burn": long,
            "thresholds": {"critical": {"short": 14.4, "long": 6.0}, "warning": {"short": 6.0, "long": 3.0}}}


def evaluate_slo_history(
    good_events: Iterable[bool],
    *,
    target: float,
    short_window: int = 5,
    long_window: int = 30,
    min_short_samples: int = 3,
    min_long_samples: int = 5,
) -> dict[str, Any]:
    """Calculate burn windows while avoiding pages from a single cold-start sample."""
    events = [bool(value) for value in good_events]
    short = events[-short_window:]
    long = events[-long_window:]
    short_status = calculate_slo(target, short.count(False), len(short))
    long_status = calculate_slo(target, long.count(False), len(long))
    enough_data = len(short) >= min_short_samples and len(long) >= min_long_samples
    policy = evaluate_multiwindow_burn(
        short_window_burn=short_status["burn_rate"],
        long_window_burn=long_status["burn_rate"],
    )
    if not enough_data:
        policy = {**policy, "page": False, "severity": "info", "reason": "insufficient_window_history"}
    return {
        "target": target,
        "sample_count": len(events),
        "short_window": {**short_status, "samples": len(short)},
        "long_window": {**long_status, "samples": len(long)},
        "alert": policy,
    }
