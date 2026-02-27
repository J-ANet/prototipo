from __future__ import annotations

from datetime import date

from planner.engine.allocator import allocate_plan, strategy_bias
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


def test_allocator_records_tradeoff_note_when_consecutive_limit_has_no_alternative() -> None:
    from datetime import datetime, timezone

    from planner.reporting.decision_trace import DecisionTraceCollector

    slots = [{"slot_id": "d1", "date": "2026-01-01", "max_minutes": 90}]
    subjects = [{"subject_id": "math", "priority": 1, "exam_dates": ["2026-03-01"]}]
    workload = {"math": {"hours_base": 2.0, "hours_buffer": 0.0}}
    trace = DecisionTraceCollector(start_timestamp=datetime.now(timezone.utc))

    allocate_plan(
        slots=slots,
        subjects=subjects,
        workload_by_subject=workload,
        session_minutes=30,
        distribution_config={
            "human_distribution_mode": "strict",
            "max_same_subject_streak_days": 3,
            "max_same_subject_consecutive_blocks": 1,
            "target_daily_subject_variety": 2,
        },
        decision_trace=trace,
    )

    notes = [item["tradeoff_note"] for item in trace.as_list()]
    assert any("Eccezione limite blocchi consecutivi" in note for note in notes)


def test_strategy_mode_changes_temporal_distribution_for_same_subject_inputs() -> None:
    slots = [
        {"slot_id": "d1", "date": "2026-01-01", "max_minutes": 60},
        {"slot_id": "d2", "date": "2026-01-02", "max_minutes": 60},
        {"slot_id": "d3", "date": "2026-01-03", "max_minutes": 60},
        {"slot_id": "d4", "date": "2026-01-04", "max_minutes": 60},
    ]
    subjects = [
        {"subject_id": "target", "priority": 2, "exam_dates": ["2026-01-05"], "selected_exam_date": "2026-01-05"},
        {"subject_id": "peer", "priority": 2, "exam_dates": ["2026-01-05"], "selected_exam_date": "2026-01-05"},
    ]
    workload = {
        "target": {"hours_base": 2.0, "hours_buffer": 0.0},
        "peer": {"hours_base": 2.0, "hours_buffer": 0.0},
    }
    features = {"target": {"urgency": 1.0}, "peer": {"urgency": 1.0}}

    def _avg_day_index(result: dict[str, object], sid: str) -> float:
        plan = result["allocations"]
        weighted_sum = 0
        total = 0
        for item in plan:
            if item.get("subject_id") != sid or item.get("bucket") != "base":
                continue
            idx = int(str(item["date"]).split("-")[-1])
            mins = int(item.get("minutes", 0) or 0)
            weighted_sum += idx * mins
            total += mins
        assert total > 0
        return weighted_sum / total

    forward = allocate_plan(
        slots=slots,
        subjects=subjects,
        workload_by_subject=workload,
        session_minutes=30,
        score_features_by_subject=features,
        distribution_config={"default_strategy_mode": "hybrid"},
        config_by_subject={"target": {"strategy_mode": "forward"}},
    )
    backward = allocate_plan(
        slots=slots,
        subjects=subjects,
        workload_by_subject=workload,
        session_minutes=30,
        score_features_by_subject=features,
        distribution_config={"default_strategy_mode": "hybrid"},
        config_by_subject={"target": {"strategy_mode": "backward"}},
    )

    assert _avg_day_index(forward, "target") > _avg_day_index(backward, "target")
    assert strategy_bias("target", "2026-01-01", date(2026, 1, 5), "forward") > strategy_bias(
        "target", "2026-01-04", date(2026, 1, 5), "forward"
    )
    assert strategy_bias("target", "2026-01-01", date(2026, 1, 5), "backward") < strategy_bias(
        "target", "2026-01-04", date(2026, 1, 5), "backward"
    )



def test_allocator_mix_override_concentration_modes_changes_allocation_pattern() -> None:
    slots = [
        {"slot_id": "d1", "date": "2026-01-01", "max_minutes": 60},
        {"slot_id": "d2", "date": "2026-01-02", "max_minutes": 60},
        {"slot_id": "d3", "date": "2026-01-03", "max_minutes": 60},
        {"slot_id": "d4", "date": "2026-01-04", "max_minutes": 60},
    ]
    subjects = [
        {"subject_id": "alpha", "priority": 2, "exam_dates": ["2026-01-05"], "selected_exam_date": "2026-01-05"},
        {"subject_id": "beta", "priority": 2, "exam_dates": ["2026-01-05"], "selected_exam_date": "2026-01-05"},
    ]
    workload = {
        "alpha": {"hours_base": 2.0, "hours_buffer": 0.0},
        "beta": {"hours_base": 2.0, "hours_buffer": 0.0},
    }
    features = {"alpha": {"urgency": 1.0}, "beta": {"urgency": 1.0}}

    alpha_concentrated = allocate_plan(
        slots=slots,
        subjects=subjects,
        workload_by_subject=workload,
        session_minutes=30,
        score_features_by_subject=features,
        subject_concentration_mode_by_subject={"alpha": "concentrated", "beta": "diffuse"},
    )
    alpha_diffuse = allocate_plan(
        slots=slots,
        subjects=subjects,
        workload_by_subject=workload,
        session_minutes=30,
        score_features_by_subject=features,
        subject_concentration_mode_by_subject={"alpha": "diffuse", "beta": "concentrated"},
    )

    def _avg_day_index(result: dict[str, object], sid: str) -> float:
        weighted_sum = 0
        total = 0
        for item in result["allocations"]:
            if item.get("subject_id") != sid or item.get("bucket") != "base":
                continue
            idx = int(str(item["date"]).split("-")[-1])
            mins = int(item.get("minutes", 0) or 0)
            weighted_sum += idx * mins
            total += mins
        assert total > 0
        return weighted_sum / total

    assert _avg_day_index(alpha_concentrated, "alpha") < _avg_day_index(alpha_diffuse, "alpha")
    assert _avg_day_index(alpha_concentrated, "beta") > _avg_day_index(alpha_diffuse, "beta")


def test_allocator_concentration_fallbacks_are_traced_deterministically() -> None:
    from datetime import datetime, timezone

    from planner.reporting.decision_trace import DecisionTraceCollector

    slot = [{"slot_id": "d1", "date": "2026-01-01", "max_minutes": 30}]

    def _run_trace(mode_map: dict[str, str]) -> list[dict[str, object]]:
        trace = DecisionTraceCollector(start_timestamp=datetime.now(timezone.utc))
        allocate_plan(
            slots=slot,
            subjects=[{"subject_id": "sid", "priority": 1, "exam_dates": ["2026-03-01"]}],
            workload_by_subject={"sid": {"hours_base": 1.0, "hours_buffer": 0.0}},
            session_minutes=30,
            subject_concentration_mode_by_subject=mode_map,
            decision_trace=trace,
        )
        return trace.as_list()

    explicit = _run_trace({"sid": "diffuse"})
    missing = _run_trace({})
    invalid = _run_trace({"sid": "not-valid"})

    assert any("RULE_CONCENTRATION_MODE_PER_SUBJECT" in item["applied_rules"] for item in explicit)
    assert any("RULE_CONCENTRATION_MODE_FALLBACK_MISSING" in item["applied_rules"] for item in missing)
    assert any("RULE_CONCENTRATION_MODE_FALLBACK_INVALID" in item["applied_rules"] for item in invalid)
