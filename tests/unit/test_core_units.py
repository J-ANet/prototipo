from __future__ import annotations

from planner.engine.scoring import compute_score, deterministic_tie_breaker_key
from planner.engine.workload import compute_subject_workload
from planner.metrics.collector import collect_metrics
from planner.normalization.config_resolver import resolve_effective_config, resolve_sleep_hours
from planner.validation import ValidationReport, validate_domain_inputs, validate_inputs_with_schema


def test_schema_and_domain_validation_reports_multiple_errors() -> None:
    payloads = {
        "global_config": {"schema_version": "1.0"},
        "subjects": {
            "schema_version": "1.0",
            "subjects": [
                {
                    "subject_id": "math",
                    "name": "Math",
                    "cfu": 6,
                    "difficulty_coeff": 1.2,
                    "priority": 2,
                    "completion_initial": 0.1,
                    "attending": False,
                    "exam_dates": ["2026-01-20"],
                    "selected_exam_date": "2026-01-19",
                    "start_at": "2026-01-21",
                    "end_by": "2026-01-20",
                }
            ],
        },
        "manual_sessions": {
            "schema_version": "1.0",
            "manual_sessions": [
                {
                    "subject_id": "math",
                    "date": "2026-01-02",
                    "planned_minutes": 60,
                    "actual_minutes_done": 90,
                    "status": "skipped",
                    "locked_by_user": True,
                }
            ],
        },
    }

    schema_report = validate_inputs_with_schema(payloads)
    assert len(schema_report.errors) >= 3

    domain_report = validate_domain_inputs(payloads)
    codes = {err.code for err in domain_report.errors}
    assert "INVALID_SELECTED_EXAM_DATE" in codes
    assert "INVALID_DATE_WINDOW" in codes
    assert "INVALID_STATUS_MINUTES_COMBINATION" in codes


def test_normalization_precedence_defaults_and_invalid_overrides() -> None:
    vr = ValidationReport()
    loaded = {
        "global_config": {
            "daily_cap_minutes": 210,
            "stability_vs_recovery": 2.5,
            "sleep_hours_per_day": 8,
            "sleep_overrides_by_weekday": {"mon": 7},
            "sleep_overrides_by_date": {"2026-01-05": 6},
        },
        "subjects": {
            "subjects": [
                {
                    "subject_id": "s1",
                    "overrides": {
                        "strategy_mode": "forward",
                        "unexpected": True,
                    },
                }
            ]
        },
    }

    effective = resolve_effective_config(loaded, vr)
    assert effective["global"]["daily_cap_minutes"] == 210
    assert effective["global"]["stability_vs_recovery"] == 1.0
    assert effective["by_subject"]["s1"]["strategy_mode"] == "forward"
    assert "unexpected" not in effective["by_subject"]["s1"]
    assert any(err.code == "INVALID_OVERRIDE_KEY" for err in vr.errors)

    assert resolve_sleep_hours(effective["global"], "2026-01-05") == 6.0
    assert resolve_sleep_hours(effective["global"], "2026-01-12") == 7.0
    assert resolve_sleep_hours(effective["global"], "2026-01-13") == 8.0


def test_workload_formula_and_attendance_discount() -> None:
    subject = {
        "cfu": 6,
        "difficulty_coeff": 1.2,
        "completion_initial": 0.25,
        "attending": True,
        "attendance_hours_per_cfu": 5,
    }

    workload = compute_subject_workload(subject, subject_buffer_percent=0.10)

    assert workload["hours_theoretical"] == 150.0
    assert workload["attendance_discount_hours"] == 30.0
    assert workload["prep_gap_coeff"] == 1.75
    assert round(workload["hours_base"], 2) == 252.0
    assert round(workload["hours_buffer"], 2) == 25.2
    assert round(workload["hours_target"], 2) == 277.2


def test_metrics_clipped_and_confidence_in_range() -> None:
    result = {
        "plan": [
            {"slot_id": "d1", "date": "2026-01-01", "subject_id": "math", "minutes": 300, "bucket": "base"},
            {"slot_id": "d2", "date": "2026-01-02", "subject_id": "physics", "minutes": 45, "bucket": "buffer"},
        ],
        "slots_in_window": [
            {"slot_id": "d1", "date": "2026-01-01", "cap_minutes": 180, "tolerance_minutes": 30},
            {"slot_id": "d2", "date": "2026-01-02", "cap_minutes": 180, "tolerance_minutes": 30},
        ],
        "subjects": [
            {"subject_id": "math", "exam_dates": ["2026-01-10"]},
            {"subject_id": "physics", "exam_dates": ["2026-01-15"]},
        ],
        "workload_by_subject": {
            "math": {"hours_base": 2, "hours_buffer": 1},
            "physics": {"hours_base": 2, "hours_buffer": 1},
        },
        "remaining_base_minutes": {"math": 0, "physics": 30},
        "remaining_buffer_minutes": {"math": 0, "physics": 120},
        "reallocated_ratio": 1.5,
        "stability_score": -0.2,
    }

    metrics = collect_metrics(result)
    for key, value in metrics.items():
        if isinstance(value, float):
            assert 0.0 <= value <= 1.0 or key == "recovery_days"
    assert 0.0 <= metrics["confidence_score"] <= 1.0


def test_scoring_and_tie_breaker_order() -> None:
    features = {
        "urgency": 1,
        "priority": 0.5,
        "completion_gap": 0.8,
        "difficulty": 0.3,
        "window_pressure": 0.6,
        "mode_alignment": 1,
        "concentration_penalty": 0.2,
    }
    score = compute_score(features)
    assert round(score, 4) == 0.7

    ref = "2026-01-01"
    a = {"subject_id": "a", "priority": 1, "exam_dates": ["2026-01-10"]}
    b = {"subject_id": "b", "priority": 3, "exam_dates": ["2026-01-10"]}
    c = {"subject_id": "c", "priority": 1, "exam_dates": ["2026-01-05"]}

    ordered = sorted([a, b, c], key=lambda s: deterministic_tie_breaker_key(s, reference_day=ref))
    assert [x["subject_id"] for x in ordered] == ["c", "b", "a"]
