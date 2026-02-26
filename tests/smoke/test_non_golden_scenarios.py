from __future__ import annotations

import json
from pathlib import Path

from planner.cli import run_plan_command
from planner.engine import run_planner
from planner.metrics import collect_metrics
from planner.normalization import resolve_effective_config
from planner.validation import ValidationReport, validate_plan_output_with_schema


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _global_config(**overrides: object) -> dict:
    payload = {
        "schema_version": "1.0",
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
    }
    payload.update(overrides)
    return payload


def _run_cli(tmp_path: Path, *, global_config: dict, subjects: dict, constraints: dict, manual_sessions: dict, request_extra: dict | None = None) -> dict:
    request = tmp_path / "plan_request.json"
    gc = tmp_path / "global_config.json"
    sj = tmp_path / "subjects.json"
    cc = tmp_path / "calendar_constraints.json"
    ms = tmp_path / "manual_sessions.json"
    output = tmp_path / "plan_output.json"

    _write(gc, global_config)
    _write(sj, subjects)
    _write(cc, constraints)
    _write(ms, manual_sessions)

    req = {
        "schema_version": "1.0",
        "request_id": "smoke",
        "generated_at": "2026-01-01T00:00:00Z",
        "global_config_path": gc.name,
        "subjects_path": sj.name,
        "calendar_constraints_path": cc.name,
        "manual_sessions_path": ms.name,
    }
    if request_extra:
        req.update(request_extra)
    _write(request, req)

    code = run_plan_command(str(request), str(output))
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["_exit_code"] = code
    return payload


def test_smoke_scenario_1_base_plan_feasible(tmp_path: Path) -> None:
    payload = _run_cli(
        tmp_path,
        global_config=_global_config(),
        subjects={
            "schema_version": "1.0",
            "subjects": [
                {
                    "subject_id": "s1", "name": "S1", "cfu": 0.01, "difficulty_coeff": 1, "priority": 2,
                    "completion_initial": 0, "attending": False,
                    "exam_dates": ["2026-01-04"], "selected_exam_date": "2026-01-04", "start_at": "2026-01-01", "end_by": "2026-01-04"
                }
            ],
        },
        constraints={"constraints": []},
        manual_sessions={"schema_version": "1.0", "manual_sessions": []},
    )
    assert payload["_exit_code"] == 0
    schema_report = validate_plan_output_with_schema(payload["plan_output"])
    assert schema_report.errors == []

    day_caps = {d["date"]: sum(a["minutes"] for a in d["allocations"] if a["subject_id"] != "__slack__") for d in payload["result"]["daily_plan"]}
    slot_max = {s["date"]: s["cap_minutes"] + s["tolerance_minutes"] for s in payload["result"]["slots_in_window"]}
    assert all(day_caps[d] <= slot_max[d] for d in day_caps)
    assert 0.0 <= payload["metrics"]["confidence_score"] <= 1.0
    assert payload["plan_output"]["validation_report"]["errors"] == []


def test_smoke_scenario_2_buffer_not_allocable_warning(tmp_path: Path) -> None:
    payload = _run_cli(
        tmp_path,
        global_config=_global_config(daily_cap_minutes=30, daily_cap_tolerance_minutes=0, subject_buffer_percent=0.5),
        subjects={
            "schema_version": "1.0",
            "subjects": [
                {
                    "subject_id": "s1", "name": "S1", "cfu": 0.01, "difficulty_coeff": 1, "priority": 2,
                    "completion_initial": 0, "attending": False,
                    "exam_dates": ["2026-01-01"], "selected_exam_date": "2026-01-01", "start_at": "2026-01-01", "end_by": "2026-01-01"
                }
            ],
        },
        constraints={"constraints": []},
        manual_sessions={"schema_version": "1.0", "manual_sessions": []},
    )
    assert payload["_exit_code"] == 0
    warning_codes = {w["code"] for w in payload["plan_output"]["warnings"]}
    assert "WARN_BUFFER_NOT_ALLOCABLE" in warning_codes
    assert payload["metrics"]["coverage_subject"] >= payload["plan_output"]["effective_config"]["global"]["critical_but_possible_threshold"]
    assert payload["metrics"]["buffer_coverage_subject"] < 1.0


def test_smoke_scenario_3_invalid_override_key(tmp_path: Path) -> None:
    payload = _run_cli(
        tmp_path,
        global_config=_global_config(),
        subjects={
            "schema_version": "1.0",
            "subjects": [
                {
                    "subject_id": "s1", "name": "S1", "cfu": 1, "difficulty_coeff": 1, "priority": 2,
                    "completion_initial": 0, "attending": False,
                    "exam_dates": ["2026-01-03"], "selected_exam_date": "2026-01-03", "overrides": {"bad": 1}
                }
            ],
        },
        constraints={"constraints": []},
        manual_sessions={"schema_version": "1.0", "manual_sessions": []},
    )
    assert payload["_exit_code"] == 2
    errors = payload["validation_report"]["errors"]
    assert any(e["code"] == "INVALID_OVERRIDE_KEY" and e.get("field_path") and e.get("suggested_fix") for e in errors)


def test_smoke_scenario_4_invalid_pomodoro(tmp_path: Path) -> None:
    payload = _run_cli(
        tmp_path,
        global_config=_global_config(pomodoro_work_minutes=10),
        subjects={
            "schema_version": "1.0",
            "subjects": [
                {
                    "subject_id": "s1", "name": "S1", "cfu": 1, "difficulty_coeff": 1, "priority": 2,
                    "completion_initial": 0, "attending": False,
                    "exam_dates": ["2026-01-03"], "selected_exam_date": "2026-01-03"
                }
            ],
        },
        constraints={"constraints": []},
        manual_sessions={"schema_version": "1.0", "manual_sessions": []},
    )
    assert payload["_exit_code"] == 2
    assert any(e["code"] == "INVALID_POMODORO_CONFIG" for e in payload["validation_report"]["errors"])


def test_smoke_scenario_5_replan_with_skipped(tmp_path: Path) -> None:
    loaded = {
        "plan_request": {
            "schema_version": "1.0",
            "request_id": "r5",
            "generated_at": "2026-01-01T00:00:00Z",
            "replan_context": {
                "previous_plan_id": "p0",
                "previous_generated_at": "2026-01-01T00:00:00Z",
                "replan_reason": "sessions_updated",
                "from_date": "2026-01-03",
            },
        },
        "global_config": _global_config(),
        "subjects": {
            "schema_version": "1.0",
            "subjects": [
                {
                    "subject_id": "s1", "name": "S1", "cfu": 2, "difficulty_coeff": 1, "priority": 2,
                    "completion_initial": 0, "attending": False,
                    "exam_dates": ["2026-01-07"], "selected_exam_date": "2026-01-07", "start_at": "2026-01-01", "end_by": "2026-01-07"
                }
            ],
        },
        "calendar_constraints": {"constraints": []},
        "manual_sessions": {
            "schema_version": "1.0",
            "manual_sessions": [
                {"subject_id": "s1", "date": "2026-01-03", "planned_minutes": 30, "actual_minutes_done": 0, "status": "skipped", "locked_by_user": True}
            ],
        },
        "previous_plan": {
            "plan": [
                {"slot_id": "old-past", "date": "2026-01-02", "subject_id": "s1", "minutes": 30, "bucket": "base"},
                {"slot_id": "old-future", "date": "2026-01-04", "subject_id": "s1", "minutes": 30, "bucket": "base"},
            ]
        },
    }
    loaded["effective_config"] = resolve_effective_config(loaded, ValidationReport())

    result = run_planner(loaded)
    metrics = collect_metrics(result)

    assert any(x["slot_id"] == "old-past" for x in result["plan"])
    assert not any(x["slot_id"] == "old-future" for x in result["plan"])
    assert 0.0 <= metrics["stability_score"] <= 1.0
    assert len(result["decision_trace"]) > 0


def test_smoke_scenario_6_monotony_improves_with_balanced_mode(tmp_path: Path) -> None:
    base_subjects = {
        "schema_version": "1.0",
        "subjects": [
            {
                "subject_id": "s1", "name": "Core", "cfu": 2.0, "difficulty_coeff": 1, "priority": 3,
                "completion_initial": 0, "attending": False,
                "exam_dates": ["2026-01-04"], "selected_exam_date": "2026-01-04", "start_at": "2026-01-01", "end_by": "2026-01-04"
            },
            {
                "subject_id": "s2", "name": "Secondary", "cfu": 0.6, "difficulty_coeff": 1, "priority": 1,
                "completion_initial": 0, "attending": False,
                "exam_dates": ["2026-01-04"], "selected_exam_date": "2026-01-04", "start_at": "2026-01-01", "end_by": "2026-01-04"
            },
        ],
    }

    off_dir = tmp_path / "off"
    balanced_dir = tmp_path / "balanced"
    off_dir.mkdir()
    balanced_dir.mkdir()

    off_payload = _run_cli(
        off_dir,
        global_config=_global_config(
            daily_cap_minutes=240,
            daily_cap_tolerance_minutes=0,
            human_distribution_mode="off",
            target_daily_subject_variety=2,
        ),
        subjects=base_subjects,
        constraints={"constraints": []},
        manual_sessions={"schema_version": "1.0", "manual_sessions": []},
    )
    balanced_payload = _run_cli(
        balanced_dir,
        global_config=_global_config(
            daily_cap_minutes=240,
            daily_cap_tolerance_minutes=0,
            human_distribution_mode="balanced",
            target_daily_subject_variety=2,
            max_same_subject_streak_days=2,
            max_same_subject_consecutive_blocks=2,
        ),
        subjects=base_subjects,
        constraints={"constraints": []},
        manual_sessions={"schema_version": "1.0", "manual_sessions": []},
    )

    assert off_payload["_exit_code"] == 0
    assert balanced_payload["_exit_code"] == 0

    assert 0.0 <= off_payload["metrics"]["humanity_score"] <= 1.0
    assert 0.0 <= balanced_payload["metrics"]["humanity_score"] <= 1.0
    assert balanced_payload["metrics"]["humanity_score"] > off_payload["metrics"]["humanity_score"]

    off_warnings = {item["code"] for item in off_payload["plan_output"]["warnings"]}
    balanced_warnings = {item["code"] for item in balanced_payload["plan_output"]["warnings"]}
    assert "WARN_PLAN_MONOTONOUS" in off_warnings
    assert "WARN_PLAN_MONOTONOUS" not in balanced_warnings

    off_suggestion_messages = [item.get("message", "") for item in off_payload["plan_output"]["suggestions"]]
    assert any("Anticipa 1-2 blocchi di materia secondaria" in message for message in off_suggestion_messages)
