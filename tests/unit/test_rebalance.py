from __future__ import annotations

from datetime import date, datetime, timezone

from planner.engine.rebalance import rebalance_allocations
from planner.metrics.collector import compute_humanity_metrics
from planner.reporting.decision_trace import DecisionTraceCollector


def test_rebalance_accepts_humanity_improving_swap_and_logs_trace() -> None:
    allocations = [
        {"slot_id": "slot-2026-01-01", "date": "2026-01-01", "subject_id": "math", "minutes": 60, "bucket": "base"},
        {"slot_id": "slot-2026-01-02", "date": "2026-01-02", "subject_id": "math", "minutes": 60, "bucket": "base"},
        {"slot_id": "slot-2026-01-03", "date": "2026-01-03", "subject_id": "math", "minutes": 60, "bucket": "base"},
        {"slot_id": "slot-2026-01-04", "date": "2026-01-04", "subject_id": "physics", "minutes": 60, "bucket": "base"},
    ]
    trace = DecisionTraceCollector(start_timestamp=datetime.now(timezone.utc))

    rebalanced = rebalance_allocations(
        allocations=allocations,
        slots=[],
        subjects=[
            {"subject_id": "math", "end_by": "2026-01-10", "exam_dates": ["2026-01-12"]},
            {"subject_id": "physics", "end_by": "2026-01-10", "exam_dates": ["2026-01-12"]},
        ],
        global_config={"max_subjects_per_day": 3},
        decision_trace=trace,
        near_days_window=2,
    )

    by_day = {item["date"]: item["subject_id"] for item in rebalanced}
    assert by_day["2026-01-04"] == "math"
    assert any(by_day[day] == "physics" for day in ("2026-01-02", "2026-01-03"))
    assert any("RULE_REBALANCE_SWAP" in item["applied_rules"] for item in trace.as_list())


def test_rebalance_does_not_swap_when_it_would_break_deadline_or_locked_session() -> None:
    allocations = [
        {"slot_id": "slot-2026-01-01", "date": "2026-01-01", "subject_id": "math", "minutes": 60, "bucket": "base"},
        {"slot_id": "slot-2026-01-02", "date": "2026-01-02", "subject_id": "physics", "minutes": 60, "bucket": "manual_locked"},
    ]

    rebalanced = rebalance_allocations(
        allocations=allocations,
        slots=[],
        subjects=[
            {"subject_id": "math", "end_by": "2026-01-01", "exam_dates": ["2026-01-01"]},
            {"subject_id": "physics", "end_by": "2026-01-10", "exam_dates": ["2026-01-12"]},
        ],
        global_config={"max_subjects_per_day": 3},
        past_cutoff=date(2026, 1, 1),
        near_days_window=2,
    )

    assert rebalanced == allocations


def test_rebalance_accepts_deterministic_fallback_swap_when_strict_humanity_improvement_missing() -> None:
    allocations = [
        {"slot_id": "slot-2026-01-01", "date": "2026-01-01", "subject_id": "math", "minutes": 60, "bucket": "base"},
        {"slot_id": "slot-2026-01-02", "date": "2026-01-02", "subject_id": "physics", "minutes": 60, "bucket": "base"},
    ]
    trace = DecisionTraceCollector(start_timestamp=datetime.now(timezone.utc))

    rebalanced = rebalance_allocations(
        allocations=allocations,
        slots=[],
        subjects=[
            {"subject_id": "math", "end_by": "2026-01-10", "exam_dates": ["2026-01-12"]},
            {"subject_id": "physics", "end_by": "2026-01-10", "exam_dates": ["2026-01-12"]},
        ],
        global_config={"max_subjects_per_day": 3, "rebalance_max_swaps": 1},
        decision_trace=trace,
        near_days_window=5,
    )

    pre_humanity = compute_humanity_metrics(allocations)["humanity_score"]
    post_humanity = compute_humanity_metrics(rebalanced)["humanity_score"]
    accepted_swaps = sum(1 for item in trace.as_list() if "RULE_REBALANCE_FALLBACK_SWAP" in item["applied_rules"])

    assert rebalanced != allocations
    assert accepted_swaps >= 1
    assert post_humanity >= pre_humanity
