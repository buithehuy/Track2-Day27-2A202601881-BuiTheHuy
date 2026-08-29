from pathlib import Path

import pandas as pd

from student_api import (
    column_downstream,
    detect_distribution,
    detect_metric,
    multiwindow_burn,
    rag_embedding_shift,
    slo_status,
    validate_orders,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "orders_contract.yaml"


def test_type_drift_is_not_hidden_by_numeric_coercion():
    frame = pd.DataFrame({"order_id": ["bad"], "amount": ["oops"]})
    issues = validate_orders(frame, CONTRACT)
    assert any(i["check"] == "type" and not i["passed"] for i in issues)


def test_freshness_uses_explicit_reference_time():
    frame = pd.DataFrame({"updated_at": ["2026-08-28T10:00:00Z"]})
    issues = validate_orders(
        frame, CONTRACT, reference_time="2026-08-28T11:00:00Z"
    )
    freshness = [i for i in issues if i["check"] == "freshness"]
    assert freshness and freshness[0]["passed"] is False


def test_auto_uses_same_segment_and_handles_constant_mad():
    result = detect_metric(
        70,
        [100, 100, 100, 100, 100],
        method="auto",
        context={"same_segment_history": [100, 100, 100, 100, 100]},
    )
    assert result["is_anomaly"] is True


def test_distribution_detects_shape_change_with_similar_mean():
    baseline = [0, 0, 0, 100]
    current = [25, 25, 25, 25]
    assert detect_distribution(current, baseline)["is_anomaly"] is True


def test_column_lineage_is_transitive():
    graph = {"a": ["b"], "b": ["c"], "c": ["d"]}
    assert column_downstream(graph, "a") == ["b", "c", "d"]


def test_multiwindow_distinguishes_spike_from_sustained_burn():
    assert multiwindow_burn(30, 0.5)["page"] is False
    assert multiwindow_burn(30, 10)["page"] is True


def test_embedding_norm_shift_is_detected():
    result = rag_embedding_shift([0.2, 0.21, 0.19], [1.0, 1.01, 0.99, 1.0])
    assert result["is_anomaly"] is True


def test_slo_zero_events_is_safe():
    assert slo_status(0.99, 0, 0)["breached"] is False
