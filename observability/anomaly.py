"""Anomaly detection starter.

Z-score is deliberately the default baseline. Students should improve `auto`
mode for seasonality/outliers rather than deleting the simple implementation.
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def zscore_detector(current: float, history: Iterable[float], threshold: float = 3.0) -> dict[str, Any]:
    if not np.isfinite(float(current)):
        return {"is_anomaly": True, "score": float("inf"), "method": "zscore", "reason": "current_nonfinite"}
    values = np.asarray(list(history), dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 3:
        return {"is_anomaly": False, "score": 0.0, "method": "zscore", "reason": "insufficient_history"}
    mean = float(np.mean(values))
    std = float(np.std(values))
    if std == 0:
        score = float("inf") if float(current) != mean else 0.0
    else:
        score = abs(float(current) - mean) / std
    return {
        "is_anomaly": bool(score > threshold),
        "score": float(score),
        "method": "zscore",
        "reason": f"mean={mean:.3f}, std={std:.3f}, threshold={threshold}",
    }


def mad_detector(current: float, history: Iterable[float], threshold: float = 3.5) -> dict[str, Any]:
    """Robust example, intentionally incomplete around zero-MAD edge cases.

    Students may improve this function and/or use it from auto mode.
    """
    if not np.isfinite(float(current)):
        return {"is_anomaly": True, "score": float("inf"), "method": "mad", "reason": "current_nonfinite"}
    values = np.asarray(list(history), dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 5:
        return {"is_anomaly": False, "score": 0.0, "method": "mad", "reason": "insufficient_history"}
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    if mad == 0:
        different = float(current) != median
        return {
            "is_anomaly": different,
            "score": float("inf") if different else 0.0,
            "method": "mad",
            "reason": f"median={median:.3f}, mad=0; constant_baseline={not different}",
        }
    modified_z = 0.6745 * abs(float(current) - median) / mad
    return {
        "is_anomaly": bool(modified_z > threshold),
        "score": float(modified_z),
        "method": "mad",
        "reason": f"median={median:.3f}, mad={mad:.3f}, threshold={threshold}",
    }


def detect_anomaly(
    current: float,
    history: Iterable[float],
    *,
    method: str = "auto",
    threshold: float = 3.0,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stable lab API.

    Current starter behavior:
    - `zscore`: basic z-score.
    - `mad`: MAD example.
    - `auto`: still uses naive z-score and ignores context.

    ``auto`` uses same-segment history when supplied and otherwise falls back
    to a robust MAD baseline or z-score when history is too short.
    """
    if method == "mad":
        return mad_detector(current, history)
    if method == "auto":
        ctx = context or {}
        segment = ctx.get("same_segment_history")
        chosen_history = segment if segment is not None else history
        values = np.asarray(list(chosen_history), dtype=float)
        values = values[np.isfinite(values)]
        if values.size >= 5:
            result = mad_detector(current, values, threshold=max(3.5, threshold))
            result["method"] = "auto:mad" if segment is None else "auto:same_segment_mad"
            if ctx.get("known_event"):
                result["reason"] += "; known_event=true"
            return result
        result = zscore_detector(current, values, threshold=threshold)
        result["method"] = "auto:zscore" if segment is None else "auto:same_segment_zscore"
        return result
    if method == "zscore":
        result = zscore_detector(current, history, threshold=threshold)
        return result
    raise ValueError(f"Unsupported method: {method}")
