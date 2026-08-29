"""Robust, context-aware anomaly detectors used through the stable student API."""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def _values(history: Iterable[float]) -> np.ndarray:
    parsed: list[float] = []
    for value in history:
        try:
            parsed.append(float(value))
        except (TypeError, ValueError):
            continue
    values = np.asarray(parsed, dtype=float)
    return values[np.isfinite(values)]


def _current_value(current: float) -> float | None:
    try:
        value = float(current)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def zscore_detector(current: float, history: Iterable[float], threshold: float = 3.0) -> dict[str, Any]:
    current_value = _current_value(current)
    if current_value is None:
        return {"is_anomaly": True, "score": float("inf"), "method": "zscore", "reason": "current_not_finite"}
    values = _values(history)
    if values.size < 3:
        return {"is_anomaly": False, "score": 0.0, "method": "zscore", "reason": "insufficient_history"}
    mean, std = float(np.mean(values)), float(np.std(values))
    score = float("inf") if std == 0 and current_value != mean else (0.0 if std == 0 else abs(current_value - mean) / std)
    return {"is_anomaly": bool(score > threshold), "score": float(score), "method": "zscore",
            "reason": f"mean={mean:.3f}, std={std:.3f}, threshold={threshold}"}


def mad_detector(current: float, history: Iterable[float], threshold: float = 3.5) -> dict[str, Any]:
    current_value = _current_value(current)
    if current_value is None:
        return {"is_anomaly": True, "score": float("inf"), "method": "mad", "reason": "current_not_finite"}
    values = _values(history)
    if values.size < 5:
        return {"is_anomaly": False, "score": 0.0, "method": "mad", "reason": "insufficient_history"}
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    score = float("inf") if mad == 0 and current_value != median else (0.0 if mad == 0 else 0.6745 * abs(current_value - median) / mad)
    return {"is_anomaly": bool(score > threshold), "score": float(score), "method": "mad",
            "reason": f"median={median:.3f}, mad={mad:.3f}, threshold={threshold}"}


def detect_anomaly(current: float, history: Iterable[float], *, method: str = "auto", threshold: float = 3.0,
                   context: dict[str, Any] | None = None) -> dict[str, Any]:
    if _current_value(current) is None:
        return {"is_anomaly": True, "score": float("inf"), "method": method, "reason": "current_not_finite"}
    if method == "zscore":
        return zscore_detector(current, history, threshold)
    if method == "mad":
        return mad_detector(current, history, threshold=max(threshold, 3.5))
    if method != "auto":
        raise ValueError(f"Unsupported method: {method}")

    context = context or {}
    if context.get("known_event"):
        return {"is_anomaly": False, "score": 0.0, "method": "auto:known_event",
                "reason": f"suppressed_for_known_event={context['known_event']}"}
    segment = context.get("same_segment_history")
    if segment is not None:
        segment_values = _values(segment)
        if segment_values.size >= 5:
            result = mad_detector(current, segment_values, threshold=max(threshold, 3.5))
            result["method"] = "auto:seasonal_mad"
            result["reason"] += f"; segment_size={segment_values.size}"
            return result
        if segment_values.size >= 3:
            result = zscore_detector(current, segment_values, threshold)
            result["method"] = "auto:seasonal_zscore"
            result["reason"] += f"; segment_size={segment_values.size}"
            return result
    values = _values(history)
    if values.size >= 5:
        result = mad_detector(current, values, threshold=max(threshold, 3.5))
        result["method"] = "auto:mad"
        return result
    result = zscore_detector(current, values, threshold)
    result["method"] = "auto:zscore"
    return result
