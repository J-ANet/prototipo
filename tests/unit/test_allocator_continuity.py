from __future__ import annotations

from datetime import date

from planner.engine.allocator import allocate_plan
from planner.engine.scoring import compute_recent_continuity_penalty


def test_recent_continuity_penalty_applies_streak_and_rolling_share() -> None:
    minutes_by_day = {
        date(2026, 1, 1): {"math": 60},
        date(2026, 1, 2): {"math": 60},
        date(2026, 1, 3): {"math": 60, "physics": 30},
    }
    total_minutes_by_day = {
        date(2026, 1, 1): 60,
        date(2026, 1, 2): 60,
        date(2026, 1, 3): 90,
    }

    penalty = compute_recent_continuity_penalty(
        subject_id="math",
        reference_day="2026-01-04",
        minutes_by_day=minutes_by_day,
        total_minutes_by_day=total_minutes_by_day,
        config={
            "lookback_days": 5,
            "rolling_window_days": 3,
            "streak_threshold_days": 2,
            "rolling_share_threshold": 0.65,
            "streak_penalty_factor": 0.25,
            "rolling_penalty_factor": 1.0,
        },
    )

    # streak=3 -> +0.25; rolling share=180/210=0.857.. -> +0.207..
    assert round(penalty, 3) == 0.457


def test_allocator_alternates_more_when_continuity_penalty_is_enabled() -> None:
    slots = [
        {"slot_id": "d1", "date": "2026-01-01", "max_minutes": 60},
        {"slot_id": "d2", "date": "2026-01-02", "max_minutes": 60},
        {"slot_id": "d3", "date": "2026-01-03", "max_minutes": 60},
        {"slot_id": "d4", "date": "2026-01-04", "max_minutes": 60},
        {"slot_id": "d5", "date": "2026-01-05", "max_minutes": 60},
    ]
    subjects = [
        {"subject_id": "math", "priority": 1, "exam_dates": ["2026-03-01"]},
        {"subject_id": "physics", "priority": 1, "exam_dates": ["2026-03-01"]},
    ]
    workload = {
        "math": {"hours_base": 10.0, "hours_buffer": 0.0},
        "physics": {"hours_base": 10.0, "hours_buffer": 0.0},
    }
    features = {
        "math": {"urgency": 1.0},
        "physics": {"urgency": 1.0},
    }

    without_penalty = allocate_plan(
        slots=slots,
        subjects=subjects,
        workload_by_subject=workload,
        session_minutes=60,
        score_features_by_subject=features,
        continuity_config={"enabled": False},
    )
    with_penalty = allocate_plan(
        slots=slots,
        subjects=subjects,
        workload_by_subject=workload,
        session_minutes=60,
        score_features_by_subject=features,
        continuity_config={
            "enabled": True,
            "streak_threshold_days": 2,
            "rolling_share_threshold": 0.65,
            "rolling_window_days": 4,
        },
    )

    subjects_without = [item["subject_id"] for item in without_penalty["allocations"] if item["bucket"] == "base"]
    subjects_with = [item["subject_id"] for item in with_penalty["allocations"] if item["bucket"] == "base"]

    assert subjects_without == ["math", "math", "math", "math", "math"]
    assert len(set(subjects_with)) > len(set(subjects_without))


def test_allocator_strict_distribution_caps_streak_days() -> None:
    slots = [
        {"slot_id": "d1", "date": "2026-01-01", "max_minutes": 60},
        {"slot_id": "d2", "date": "2026-01-02", "max_minutes": 60},
        {"slot_id": "d3", "date": "2026-01-03", "max_minutes": 60},
    ]
    subjects = [
        {"subject_id": "math", "priority": 1, "exam_dates": ["2026-03-01"]},
        {"subject_id": "physics", "priority": 1, "exam_dates": ["2026-03-01"]},
    ]
    workload = {
        "math": {"hours_base": 10.0, "hours_buffer": 0.0},
        "physics": {"hours_base": 10.0, "hours_buffer": 0.0},
    }
    features = {
        "math": {"urgency": 1.0},
        "physics": {"urgency": 0.1},
    }

    strict = allocate_plan(
        slots=slots,
        subjects=subjects,
        workload_by_subject=workload,
        session_minutes=60,
        score_features_by_subject=features,
        distribution_config={
            "human_distribution_mode": "strict",
            "max_same_subject_streak_days": 1,
            "target_daily_subject_variety": 2,
        },
    )

    subjects_strict = [item["subject_id"] for item in strict["allocations"] if item["bucket"] == "base"]
    assert subjects_strict[:3] == ["math", "physics", "math"]
