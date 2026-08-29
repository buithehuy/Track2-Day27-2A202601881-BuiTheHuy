from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def detect_distribution_shift(
    current_values: Iterable[float],
    baseline_values: Iterable[float],
    *,
    ratio_threshold: float = 3.0,
) -> dict[str, Any]:
    """Very small starter detector using mean ratio.

    This is intentionally not a full distribution test. Students are encouraged
    to try KS test, PSI, quantile drift, robust ratios, or domain-specific checks.
    """
    cur = np.asarray(list(current_values), dtype=float)
    base = np.asarray(list(baseline_values), dtype=float)
    cur = cur[np.isfinite(cur)]
    base = base[np.isfinite(base)]
    if cur.size == 0 or base.size == 0:
        return {"is_anomaly": False, "score": 0.0, "method": "mean_ratio", "reason": "empty_input"}
    cur_mean = float(np.mean(cur))
    base_mean = float(np.mean(base))
    cur_q = np.quantile(cur, [0.1, 0.5, 0.9])
    base_q = np.quantile(base, [0.1, 0.5, 0.9])
    scale = max(float(np.std(base)), abs(base_mean) * 0.01, 1e-12)
    quantile_score = float(np.max(np.abs(cur_q - base_q)) / scale)
    combined = np.sort(np.concatenate([cur, base]))
    ks_score = max(
        abs(float(np.mean(base <= point)) - float(np.mean(cur <= point)))
        for point in combined
    ) * 4.0
    if base_mean == 0:
        mean_score = float("inf") if cur_mean != 0 else 0.0
    else:
        mean_score = abs(cur_mean - base_mean) / max(abs(base_mean), 1e-12)
    score = max(quantile_score, mean_score, ks_score)
    return {
        "is_anomaly": bool(score >= ratio_threshold),
        "score": float(score),
        "method": "quantile_mean_shift",
        "reason": f"baseline_mean={base_mean:.3f}, current_mean={cur_mean:.3f}; quantile_score={quantile_score:.3f}; ks_score={ks_score:.3f}",
    }
