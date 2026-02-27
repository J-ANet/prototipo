from __future__ import annotations

import json
from pathlib import Path

from planner.cli import run_plan_command
from planner.engine import run_planner
from planner.metrics import collect_metrics
from planner.normalization import resolve_effective_config
from planner.validation import ValidationReport


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _base_files(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    request = tmp_path / "plan_request.json"
    global_config = tmp_path / "global_config.json"
    subjects = tmp_path / "subjects.json"
    constraints = tmp_path / "calendar_constraints.json"
    manual = tmp_path / "manual_sessions.json"

    _write(
        global_config,
        {
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
        },
    )
    _write(
        subjects,
        {
            "schema_version": "1.0",
            "subjects": [
                {
                    "subject_id": "math",
                    "name": "Math",
                    "cfu": 1,
                    "difficulty_coeff": 1,
                    "priority": 2,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-04"],
                    "selected_exam_date": "2026-01-04",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-04",
                }
            ],
        },
    )
    _write(constraints, {"constraints": []})
    _write(manual, {"schema_version": "1.0", "manual_sessions": []})

    _write(
        request,
        {
            "schema_version": "1.0",
            "request_id": "req-1",
            "generated_at": "2026-01-01T08:00:00Z",
            "global_config_path": global_config.name,
            "subjects_path": subjects.name,
            "calendar_constraints_path": constraints.name,
            "manual_sessions_path": manual.name,
        },
    )

    return request, global_config, subjects, constraints, manual


def test_end_to_end_pipeline_plan_request_to_plan_output(tmp_path: Path) -> None:
    request, _, _, _, _ = _base_files(tmp_path)
    output = tmp_path / "plan_output.json"

    code = run_plan_command(str(request), str(output))
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["status"] == "ok"
    assert "plan_output" in payload
    assert payload["plan_output"]["validation_report"]["errors"] == []


def test_replan_with_manual_sessions_updates_future_only(tmp_path: Path) -> None:
    request, global_config, subjects, constraints, manual = _base_files(tmp_path)

    previous_plan = {
        "plan": [
            {"slot_id": "old-1", "date": "2026-01-01", "subject_id": "math", "minutes": 30, "bucket": "base"},
            {"slot_id": "old-2", "date": "2026-01-03", "subject_id": "math", "minutes": 30, "bucket": "base"},
        ]
    }
    _write(
        manual,
        {
            "schema_version": "1.0",
            "manual_sessions": [
                {
                    "session_id": "m1",
                    "subject_id": "math",
                    "date": "2026-01-03",
                    "planned_minutes": 60,
                    "actual_minutes_done": 0,
                    "status": "planned",
                    "locked_by_user": True,
                }
            ],
        },
    )
    req_obj = json.loads(request.read_text(encoding="utf-8"))
    req_obj["replan_context"] = {
        "previous_plan_id": "p-0",
        "previous_generated_at": "2026-01-01T00:00:00Z",
        "replan_reason": "sessions_updated",
        "from_date": "2026-01-02",
    }

    loaded = {
        "plan_request": req_obj,
        "global_config": json.loads(global_config.read_text(encoding="utf-8")),
        "subjects": json.loads(subjects.read_text(encoding="utf-8")),
        "calendar_constraints": json.loads(constraints.read_text(encoding="utf-8")),
        "manual_sessions": json.loads(manual.read_text(encoding="utf-8")),
        "previous_plan": previous_plan,
    }
    loaded["effective_config"] = resolve_effective_config(loaded, ValidationReport())

    result = run_planner(loaded)
    _ = collect_metrics(result)

    plan = result["plan"]
    assert any(item.get("slot_id") == "old-1" for item in plan)
    assert not any(item.get("slot_id") == "old-2" for item in plan)
    assert any(item.get("manual_session_id") == "m1" for item in plan)


def _longest_monotone_run(plan: list[dict], target_day: str) -> int:
    run = 0
    best = 0
    prev = None
    for item in sorted((x for x in plan if x.get("date") == target_day and x.get("bucket") == "base"), key=lambda x: str(x.get("slot_id", ""))):
        sid = item.get("subject_id")
        if sid == prev:
            run += 1
        else:
            prev = sid
            run = 1
        best = max(best, run)
    return best


def test_distribution_limit_reduces_same_day_monotone_sequences_without_losing_feasibility() -> None:
    payload = {
        "effective_config": {
            "global": {
                "daily_cap_minutes": 240,
                "daily_cap_tolerance_minutes": 0,
                "subject_buffer_percent": 0.1,
                "critical_but_possible_threshold": 0.8,
                "study_on_exam_day": True,
                "max_subjects_per_day": 3,
                "session_duration_minutes": 30,
                "sleep_hours_per_day": 8,
                "pomodoro_enabled": False,
                "pomodoro_work_minutes": 25,
                "pomodoro_short_break_minutes": 5,
                "pomodoro_long_break_minutes": 15,
                "pomodoro_long_break_every": 4,
                "pomodoro_count_breaks_in_capacity": True,
                "stability_vs_recovery": 0.4,
                "default_strategy_mode": "hybrid",
                "human_distribution_mode": "off",
                "max_same_subject_streak_days": 5,
                "max_same_subject_consecutive_blocks": 3,
                "target_daily_subject_variety": 2,
            },
            "by_subject": {},
        },
        "subjects": {
            "subjects": [
                {
                    "subject_id": "math",
                    "priority": 5,
                    "cfu": 1,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-03"],
                    "selected_exam_date": "2026-01-03",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-03",
                },
                {
                    "subject_id": "physics",
                    "priority": 1,
                    "cfu": 1,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-03"],
                    "selected_exam_date": "2026-01-03",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-03",
                },
            ]
        },
        "global_config": {
            "daily_cap_minutes": 240,
            "daily_cap_tolerance_minutes": 0,
            "subject_buffer_percent": 0.1,
            "critical_but_possible_threshold": 0.8,
            "study_on_exam_day": True,
            "max_subjects_per_day": 3,
            "session_duration_minutes": 30,
            "sleep_hours_per_day": 8,
            "pomodoro_enabled": False,
            "pomodoro_work_minutes": 25,
            "pomodoro_short_break_minutes": 5,
            "pomodoro_long_break_minutes": 15,
            "pomodoro_long_break_every": 4,
            "pomodoro_count_breaks_in_capacity": True,
            "stability_vs_recovery": 0.4,
            "default_strategy_mode": "hybrid",
            "human_distribution_mode": "off",
            "max_same_subject_streak_days": 5,
            "max_same_subject_consecutive_blocks": 3,
            "target_daily_subject_variety": 2,
        },
        "calendar_constraints": {"constraints": []},
        "manual_sessions": {"manual_sessions": []},
    }

    without_limit = run_planner(payload)

    payload["effective_config"]["global"]["human_distribution_mode"] = "strict"
    payload["effective_config"]["global"]["max_same_subject_consecutive_blocks"] = 2
    payload["global_config"]["human_distribution_mode"] = "strict"
    payload["global_config"]["max_same_subject_consecutive_blocks"] = 2
    with_limit = run_planner(payload)

    day = "2026-01-01"
    no_limit_run = _longest_monotone_run(without_limit["plan"], day)
    with_limit_run = _longest_monotone_run(with_limit["plan"], day)

    limit_rule_hits = sum(
        1
        for item in with_limit["decision_trace"]
        if "RULE_LIMIT_CONSECUTIVE_BLOCKS" in item.get("applied_rules", [])
    )

    assert with_limit_run < no_limit_run or limit_rule_hits > 0
    assert without_limit["plan_summary"]["total_planned_minutes"] == with_limit["plan_summary"]["total_planned_minutes"]
    assert sum(without_limit["remaining_base_minutes"].values()) == sum(with_limit["remaining_base_minutes"].values())


def test_strategy_mode_changes_temporal_pattern_deterministically() -> None:
    payload = {
        "effective_config": {
            "global": {
                "daily_cap_minutes": 180,
                "daily_cap_tolerance_minutes": 0,
                "subject_buffer_percent": 0.2,
                "critical_but_possible_threshold": 0.8,
                "study_on_exam_day": True,
                "max_subjects_per_day": 3,
                "session_duration_minutes": 30,
                "sleep_hours_per_day": 8,
                "pomodoro_enabled": False,
                "pomodoro_work_minutes": 25,
                "pomodoro_short_break_minutes": 5,
                "pomodoro_long_break_minutes": 15,
                "pomodoro_long_break_every": 4,
                "pomodoro_count_breaks_in_capacity": True,
                "stability_vs_recovery": 0.4,
                "default_strategy_mode": "hybrid",
                "human_distribution_mode": "off",
            },
            "by_subject": {
                "a_forward_subject": {"strategy_mode": "forward"},
                "z_backward_subject": {"strategy_mode": "backward"},
            },
        },
        "subjects": {
            "subjects": [
                {
                    "subject_id": "a_forward_subject",
                    "priority": 3,
                    "cfu": 0.16,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-05"],
                    "selected_exam_date": "2026-01-05",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-05",
                },
                {
                    "subject_id": "z_backward_subject",
                    "priority": 3,
                    "cfu": 0.16,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-05"],
                    "selected_exam_date": "2026-01-05",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-05",
                },
            ]
        },
        "global_config": {
            "daily_cap_minutes": 180,
            "daily_cap_tolerance_minutes": 0,
            "subject_buffer_percent": 0.2,
            "session_duration_minutes": 30,
        },
        "calendar_constraints": {"constraints": []},
        "manual_sessions": {"manual_sessions": []},
    }

    first = run_planner(payload)
    second = run_planner(payload)

    assert first["plan"] == second["plan"]

    def _avg_base_day_index(plan: list[dict], subject_id: str) -> float:
        weighted_sum = 0.0
        total_minutes = 0
        for item in plan:
            if item.get("subject_id") != subject_id or item.get("bucket") != "base":
                continue
            day_idx = int(str(item.get("date")).split("-")[-1])
            minutes = int(item.get("minutes", 0) or 0)
            weighted_sum += float(day_idx * minutes)
            total_minutes += minutes
        assert total_minutes > 0
        return weighted_sum / float(total_minutes)

    forward_avg = _avg_base_day_index(first["plan"], "a_forward_subject")
    backward_avg = _avg_base_day_index(first["plan"], "z_backward_subject")
    assert forward_avg < backward_avg


def test_subject_concentration_mode_by_subject_changes_selection_and_traces_tradeoff_note() -> None:
    payload = {
        "effective_config": {
            "global": {
                "daily_cap_minutes": 180,
                "daily_cap_tolerance_minutes": 0,
                "subject_buffer_percent": 0.1,
                "critical_but_possible_threshold": 0.8,
                "study_on_exam_day": True,
                "max_subjects_per_day": 3,
                "session_duration_minutes": 30,
                "sleep_hours_per_day": 8,
                "pomodoro_enabled": False,
                "stability_vs_recovery": 0.4,
                "default_strategy_mode": "hybrid",
                "human_distribution_mode": "off",
                "subject_concentration_mode": "diffuse",
            },
            "by_subject": {
                "chem": {"subject_concentration_mode": "concentrated"},
                "bio": {"subject_concentration_mode": "diffuse"},
            },
        },
        "subjects": {
            "subjects": [
                {
                    "subject_id": "chem",
                    "priority": 3,
                    "cfu": 0.16,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-05"],
                    "selected_exam_date": "2026-01-05",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-05",
                },
                {
                    "subject_id": "bio",
                    "priority": 3,
                    "cfu": 0.16,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-05"],
                    "selected_exam_date": "2026-01-05",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-05",
                },
            ]
        },
        "global_config": {
            "daily_cap_minutes": 180,
            "daily_cap_tolerance_minutes": 0,
            "subject_buffer_percent": 0.1,
            "session_duration_minutes": 30,
            "subject_concentration_mode": "diffuse",
        },
        "calendar_constraints": {"constraints": []},
        "manual_sessions": {"manual_sessions": []},
    }

    result = run_planner(payload)

    def _avg_base_day_index(plan: list[dict], subject_id: str) -> float:
        weighted_sum = 0.0
        total_minutes = 0
        for item in plan:
            if item.get("subject_id") != subject_id or item.get("bucket") != "base":
                continue
            day_idx = int(str(item.get("date")).split("-")[-1])
            minutes = int(item.get("minutes", 0) or 0)
            weighted_sum += float(day_idx * minutes)
            total_minutes += minutes
        assert total_minutes > 0
        return weighted_sum / float(total_minutes)

    concentrated_avg = _avg_base_day_index(result["plan"], "chem")
    diffuse_avg = _avg_base_day_index(result["plan"], "bio")
    assert concentrated_avg < diffuse_avg
    assert any(
        "concentrazione per-materia" in str(item.get("tradeoff_note", ""))
        for item in result["decision_trace"]
    )


def test_concentration_mode_invalid_override_uses_concentrated_deterministic_fallback() -> None:
    payload = {
        "effective_config": {
            "global": {
                "daily_cap_minutes": 180,
                "daily_cap_tolerance_minutes": 0,
                "subject_buffer_percent": 0.1,
                "critical_but_possible_threshold": 0.8,
                "study_on_exam_day": True,
                "max_subjects_per_day": 3,
                "session_duration_minutes": 30,
                "sleep_hours_per_day": 8,
                "pomodoro_enabled": False,
                "stability_vs_recovery": 0.4,
                "default_strategy_mode": "hybrid",
                "human_distribution_mode": "off",
                "subject_concentration_mode": "concentrated",
            },
            "by_subject": {
                "hist": {"subject_concentration_mode": "not-valid"},
            },
        },
        "subjects": {
            "subjects": [
                {
                    "subject_id": "hist",
                    "priority": 3,
                    "cfu": 0.16,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-03"],
                    "selected_exam_date": "2026-01-03",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-03",
                }
            ]
        },
        "global_config": {
            "daily_cap_minutes": 180,
            "daily_cap_tolerance_minutes": 0,
            "subject_buffer_percent": 0.1,
            "session_duration_minutes": 30,
            "subject_concentration_mode": "concentrated",
        },
        "calendar_constraints": {"constraints": []},
        "manual_sessions": {"manual_sessions": []},
    }

    with_invalid = run_planner(payload)
    payload["effective_config"]["by_subject"]["hist"] = {}
    with_missing = run_planner(payload)

    assert with_invalid["plan"] == with_missing["plan"]
