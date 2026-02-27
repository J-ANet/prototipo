from __future__ import annotations

from copy import deepcopy

from planner.engine import run_planner
from planner.metrics import collect_metrics
from planner.normalization import resolve_effective_config
from planner.validation import ValidationReport, validate_domain_inputs


def _payload() -> dict:
    loaded = {
        "plan_request": {
            "schema_version": "1.0",
            "request_id": "p1",
            "generated_at": "2026-01-01T00:00:00Z",
        },
        "global_config": {
            "daily_cap_minutes": 180,
            "daily_cap_tolerance_minutes": 30,
            "subject_buffer_percent": 0.1,
            "critical_but_possible_threshold": 0.8,
            "study_on_exam_day": False,
            "max_subjects_per_day": 3,
            "session_duration_minutes": 30,
            "sleep_hours_per_day": 8,
            "pomodoro_enabled": True,
            "pomodoro_work_minutes": 25,
            "pomodoro_short_break_minutes": 5,
            "pomodoro_long_break_minutes": 15,
            "pomodoro_long_break_every": 4,
            "pomodoro_count_breaks_in_capacity": True,
            "stability_vs_recovery": 0.4,
            "default_strategy_mode": "hybrid",
        },
        "subjects": {
            "schema_version": "1.0",
            "subjects": [
                {
                    "subject_id": "s1",
                    "name": "S1",
                    "cfu": 2,
                    "difficulty_coeff": 1,
                    "priority": 2,
                    "completion_initial": 0.1,
                    "attending": False,
                    "exam_dates": ["2026-01-07"],
                    "selected_exam_date": "2026-01-07",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-07",
                }
            ],
        },
        "calendar_constraints": {"constraints": []},
        "manual_sessions": {"schema_version": "1.0", "manual_sessions": []},
    }
    loaded["effective_config"] = resolve_effective_config(loaded, ValidationReport())
    return loaded


def test_determinism_same_input_same_output() -> None:
    payload = _payload()
    result1 = run_planner(deepcopy(payload))
    result2 = run_planner(deepcopy(payload))
    assert result1["plan"] == result2["plan"]


def test_metrics_are_clipped_in_0_1() -> None:
    metrics = collect_metrics(run_planner(_payload()))
    for key, value in metrics.items():
        if isinstance(value, float) and key not in {"recovery_days", "max_same_subject_streak_days"}:
            assert 0.0 <= value <= 1.0


def test_hard_constraints_no_allocation_over_slot_max() -> None:
    result = run_planner(_payload())
    by_day: dict[str, int] = {}
    for item in result["plan"]:
        if item.get("subject_id") == "__slack__":
            continue
        by_day[item["date"]] = by_day.get(item["date"], 0) + int(item["minutes"])

    caps = {slot["date"]: int(slot["max_minutes"]) for slot in result["slots_in_window"]}
    assert all(minutes <= caps[day] for day, minutes in by_day.items())


def test_error_aggregation_not_fail_fast() -> None:
    loaded = _payload()
    loaded["subjects"]["subjects"][0]["selected_exam_date"] = "2026-01-20"
    loaded["subjects"]["subjects"][0]["start_at"] = "2026-01-10"
    loaded["subjects"]["subjects"][0]["end_by"] = "2026-01-01"
    loaded["manual_sessions"]["manual_sessions"] = [
        {
            "subject_id": "s1",
            "date": "2026-01-01",
            "planned_minutes": 30,
            "actual_minutes_done": 20,
            "status": "done",
            "locked_by_user": True,
        }
    ]

    report = validate_domain_inputs(loaded)
    assert len(report.errors) >= 3


def test_session_status_coherence() -> None:
    loaded = _payload()
    loaded["manual_sessions"]["manual_sessions"] = [
        {"subject_id": "s1", "date": "2026-01-01", "planned_minutes": 30, "actual_minutes_done": 0, "status": "skipped", "locked_by_user": True},
        {"subject_id": "s1", "date": "2026-01-02", "planned_minutes": 30, "actual_minutes_done": 30, "status": "done", "locked_by_user": True},
        {"subject_id": "s1", "date": "2026-01-03", "planned_minutes": 30, "actual_minutes_done": 15, "status": "partial", "locked_by_user": True},
    ]
    report = validate_domain_inputs(loaded)
    assert report.errors == []
