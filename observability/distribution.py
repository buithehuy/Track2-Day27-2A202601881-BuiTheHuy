from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

import numpy as np


def _numeric_values(values: Iterable[float]) -> np.ndarray:
    parsed: list[float] = []
    for value in values:
        try:
            parsed.append(float(value))
        except (TypeError, ValueError):
            continue
    result = np.asarray(parsed, dtype=float)
    return result[np.isfinite(result)]


def detect_distribution_shift(current_values: Iterable[float], baseline_values: Iterable[float], *,
                              ratio_threshold: float = 3.0) -> dict[str, Any]:
    """Detect location and shape drift with a scale-normalized quantile distance.

    Unlike a mean ratio, this detects spread/tail shifts even when two batches
    have the same mean. The score is expressed in baseline IQR units.
    """
    cur, base = _numeric_values(current_values), _numeric_values(baseline_values)
    if base.size == 0:
        return {"is_anomaly": False, "score": 0.0, "method": "quantile_shift", "reason": "insufficient_baseline"}
    if cur.size == 0:
        return {"is_anomaly": True, "score": float("inf"), "method": "quantile_shift", "reason": "current_batch_empty"}
    quantiles = np.linspace(0.05, 0.95, 19)
    base_q, cur_q = np.quantile(base, quantiles), np.quantile(cur, quantiles)
    base_iqr = float(np.subtract(*np.quantile(base, [0.75, 0.25])))
    fallback_scale = max(abs(float(np.median(base))) * 0.05, float(np.std(base)), 1e-9)
    scale = base_iqr if base_iqr > 1e-9 else fallback_scale
    location_shape_score = float(np.mean(np.abs(cur_q - base_q)) / scale)
    cur_iqr = float(np.subtract(*np.quantile(cur, [0.75, 0.25])))
    spread_score = abs(float(np.log((cur_iqr + 1e-9) / (base_iqr + 1e-9))))
    score = max(location_shape_score, spread_score)
    return {"is_anomaly": bool(score >= ratio_threshold), "score": float(score), "method": "quantile_shift",
            "reason": (f"baseline_median={np.median(base):.3f}, current_median={np.median(cur):.3f}, "
                       f"baseline_iqr={base_iqr:.3f}, current_iqr={cur_iqr:.3f}, threshold={ratio_threshold}")}


def detect_categorical_shift(
    current_values: Iterable[Any], baseline_values: Iterable[Any], *, threshold: float = 0.25
) -> dict[str, Any]:
    """Detect category-mix drift using total variation distance (0..1)."""
    current, baseline = list(current_values), list(baseline_values)
    if not baseline:
        return {"is_anomaly": False, "score": 0.0, "method": "categorical_tvd", "reason": "insufficient_baseline"}
    if not current:
        return {"is_anomaly": True, "score": 1.0, "method": "categorical_tvd", "reason": "current_batch_empty"}
    cur_counts, base_counts = Counter(map(str, current)), Counter(map(str, baseline))
    categories = sorted(set(cur_counts) | set(base_counts))
    score = 0.5 * sum(
        abs(cur_counts[key] / len(current) - base_counts[key] / len(baseline)) for key in categories
    )
    return {
        "is_anomaly": bool(score >= threshold),
        "score": float(score),
        "method": "categorical_tvd",
        "reason": f"total_variation_distance={score:.4f}; threshold={threshold}; categories={categories}",
    }
