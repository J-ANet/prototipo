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
    assert json.dumps(payload["plan_output"]["decision_trace"])


def test_plan_command_emits_decision_trace_allocation_metadata(tmp_path: Path) -> None:
    request, _, _, _, _ = _base_files(tmp_path)
    output = tmp_path / "plan_output.json"

    exit_code = run_plan_command(str(request), str(output))
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["_exit_code"] = exit_code

    assert payload["_exit_code"] == 0
    trace = payload.get("plan_output", {}).get("decision_trace", [])
    assert any(isinstance(item.get("allocation_metadata"), dict) for item in trace)


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


def _subject_distribution_stats(plan: list[dict], subject_id: str) -> dict[str, float]:
    base_items = [item for item in plan if item.get("subject_id") == subject_id and item.get("bucket") == "base"]
    daily_minutes: dict[str, int] = {}
    max_block_minutes = 0
    for item in base_items:
        day = str(item.get("date"))
        minutes = int(item.get("minutes", 0) or 0)
        daily_minutes[day] = daily_minutes.get(day, 0) + minutes
        max_block_minutes = max(max_block_minutes, minutes)

    longest_day_streak = 0
    current_streak = 0
    previous_day_num = None
    for day in sorted(daily_minutes):
        day_num = int(day.split("-")[-1])
        if previous_day_num is not None and day_num == previous_day_num + 1:
            current_streak += 1
        else:
            current_streak = 1
        longest_day_streak = max(longest_day_streak, current_streak)
        previous_day_num = day_num

    return {
        "avg_day_index": _avg_base_day_index(plan, subject_id),
        "active_days": float(len(daily_minutes)),
        "longest_day_streak": float(longest_day_streak),
        "max_block_minutes": float(max_block_minutes),
    }


def _daily_base_minutes(plan: list[dict], subject_id: str) -> dict[str, int]:
    daily: dict[str, int] = {}
    for item in plan:
        if item.get("subject_id") != subject_id or item.get("bucket") != "base":
            continue
        day = str(item.get("date"))
        daily[day] = daily.get(day, 0) + int(item.get("minutes", 0) or 0)
    return daily


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

    concentrated_avg = _avg_base_day_index(result["plan"], "chem")
    diffuse_avg = _avg_base_day_index(result["plan"], "bio")
    assert concentrated_avg < diffuse_avg
    assert any(
        "concentrazione per-materia" in str(item.get("tradeoff_note", ""))
        for item in result["decision_trace"]
    )


def test_mixed_subject_concentration_modes_create_distinct_patterns_in_same_plan() -> None:
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
                "focused_subject": {"subject_concentration_mode": "concentrated"},
                "spread_subject": {"subject_concentration_mode": "diffuse"},
            },
        },
        "subjects": {
            "subjects": [
                {
                    "subject_id": "focused_subject",
                    "priority": 4,
                    "cfu": 1.0,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-06"],
                    "selected_exam_date": "2026-01-06",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-06",
                },
                {
                    "subject_id": "spread_subject",
                    "priority": 5,
                    "cfu": 1.0,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-06"],
                    "selected_exam_date": "2026-01-06",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-06",
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

    focused_stats = _subject_distribution_stats(result["plan"], "focused_subject")
    spread_stats = _subject_distribution_stats(result["plan"], "spread_subject")

    assert focused_stats["avg_day_index"] < spread_stats["avg_day_index"]
    assert spread_stats["active_days"] >= focused_stats["active_days"]



def test_subject_concentration_mixed_overrides_emit_trace_metadata_and_distinct_clustering() -> None:
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
                "algebra": {"subject_concentration_mode": "concentrated"},
                "history": {"subject_concentration_mode": "diffuse"},
                "biology": {"subject_concentration_mode": "diffuse"},
            },
        },
        "subjects": {
            "subjects": [
                {
                    "subject_id": "algebra",
                    "priority": 1,
                    "cfu": 0.1,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-06"],
                    "selected_exam_date": "2026-01-06",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-06",
                },

                {
                    "subject_id": "history",
                    "priority": 5,
                    "cfu": 1.0,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-06"],
                    "selected_exam_date": "2026-01-06",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-06",
                },

                {
                    "subject_id": "biology",
                    "priority": 1,
                    "cfu": 0.1,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-06"],
                    "selected_exam_date": "2026-01-06",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-06",
                },
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

    result = run_planner(payload)

    stats_by_subject = {
        sid: _subject_distribution_stats(result["plan"], sid)
        for sid in ["algebra", "history", "biology"]
        if any(item.get("subject_id") == sid and item.get("bucket") == "base" for item in result["plan"])
    }
    algebra_stats = stats_by_subject["algebra"]
    trace_by_subject = {
        sid: [
            item
            for item in result["decision_trace"]
            if item.get("selected_subject_id") == sid and item.get("allocation_metadata", {}).get("phase") == "base"
        ]
        for sid in ["algebra", "history", "biology"]
    }

    assert trace_by_subject["algebra"]
    assert trace_by_subject["history"]

    for sid, expected_mode in {
        "algebra": "concentrated",
        "history": "diffuse",
    }.items():
        assert all(
            item.get("allocation_metadata", {}).get("concentration_mode") == expected_mode
            for item in trace_by_subject[sid]
        )
        assert all(
            item.get("allocation_metadata", {}).get("concentration_origin") == "subject_override"
            for item in trace_by_subject[sid]
        )

    assert algebra_stats["avg_day_index"] <= stats_by_subject["history"]["avg_day_index"]
    assert algebra_stats["max_block_minutes"] >= stats_by_subject["history"]["max_block_minutes"]


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


def test_strategy_mode_per_subject_changes_plan_for_same_inputs() -> None:
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
                "stability_vs_recovery": 0.4,
                "default_strategy_mode": "hybrid",
                "human_distribution_mode": "off",
            },
            "by_subject": {"target": {"strategy_mode": "forward"}},
        },
        "subjects": {
            "subjects": [
                {
                    "subject_id": "target",
                    "priority": 2,
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
                    "subject_id": "peer",
                    "priority": 2,
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
            "default_strategy_mode": "hybrid",
        },
        "calendar_constraints": {"constraints": []},
        "manual_sessions": {"manual_sessions": []},
    }

    forward_result = run_planner(payload)

    payload["effective_config"]["by_subject"]["target"]["strategy_mode"] = "backward"
    backward_result = run_planner(payload)

    assert _avg_base_day_index(forward_result["plan"], "target") < _avg_base_day_index(backward_result["plan"], "target")
    assert any("RULE_STRATEGY_FORWARD" in item.get("applied_rules", []) for item in forward_result["decision_trace"])
    assert any("RULE_STRATEGY_BACKWARD" in item.get("applied_rules", []) for item in backward_result["decision_trace"])


def test_strategy_mode_global_forward_vs_backward_produces_measurable_shift() -> None:
    payload = {
        "effective_config": {
            "global": {
                "daily_cap_minutes": 120,
                "daily_cap_tolerance_minutes": 0,
                "subject_buffer_percent": 0.2,
                "critical_but_possible_threshold": 0.8,
                "study_on_exam_day": True,
                "max_subjects_per_day": 2,
                "session_duration_minutes": 30,
                "sleep_hours_per_day": 8,
                "pomodoro_enabled": False,
                "stability_vs_recovery": 0.4,
                "default_strategy_mode": "forward",
                "human_distribution_mode": "off",
            },
            "by_subject": {},
        },
        "subjects": {
            "subjects": [
                {
                    "subject_id": "target",
                    "priority": 2,
                    "cfu": 0.24,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-07"],
                    "selected_exam_date": "2026-01-07",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-07",
                },
                {
                    "subject_id": "peer",
                    "priority": 2,
                    "cfu": 0.24,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-04"],
                    "selected_exam_date": "2026-01-04",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-04",
                },
            ]
        },
        "global_config": {
            "daily_cap_minutes": 120,
            "daily_cap_tolerance_minutes": 0,
            "subject_buffer_percent": 0.2,
            "session_duration_minutes": 30,
            "default_strategy_mode": "forward",
        },
        "calendar_constraints": {"constraints": []},
        "manual_sessions": {"manual_sessions": []},
    }

    forward_result = run_planner(payload)

    payload["effective_config"]["global"]["default_strategy_mode"] = "backward"
    payload["global_config"]["default_strategy_mode"] = "backward"
    backward_result = run_planner(payload)

    forward_base_avg = _avg_base_day_index(forward_result["plan"], "target")
    backward_base_avg = _avg_base_day_index(backward_result["plan"], "target")
    assert forward_base_avg < backward_base_avg

    assert any("RULE_STRATEGY_FORWARD" in item.get("applied_rules", []) for item in forward_result["decision_trace"])
    assert any("RULE_STRATEGY_BACKWARD" in item.get("applied_rules", []) for item in backward_result["decision_trace"])


def test_concentrated_vs_diffuse_has_quantitative_distribution_differences() -> None:
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
            },
            "by_subject": {},
        },
        "subjects": {
            "subjects": [
                {
                    "subject_id": "target",
                    "priority": 3,
                    "cfu": 0.24,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-06"],
                    "selected_exam_date": "2026-01-06",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-06",
                },
                {
                    "subject_id": "peer",
                    "priority": 3,
                    "cfu": 0.24,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-06"],
                    "selected_exam_date": "2026-01-06",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-06",
                },
            ]
        },
        "global_config": {
            "daily_cap_minutes": 180,
            "daily_cap_tolerance_minutes": 0,
            "subject_buffer_percent": 0.1,
            "session_duration_minutes": 30,
        },
        "calendar_constraints": {"constraints": []},
        "manual_sessions": {"manual_sessions": []},
    }

    payload["effective_config"]["by_subject"] = {"target": {"subject_concentration_mode": "concentrated"}}
    concentrated = run_planner(payload)

    payload["effective_config"]["by_subject"] = {"target": {"subject_concentration_mode": "diffuse"}}
    diffuse = run_planner(payload)

    concentrated_stats = _subject_distribution_stats(concentrated["plan"], "target")
    diffuse_stats = _subject_distribution_stats(diffuse["plan"], "target")

    assert concentrated_stats["avg_day_index"] <= diffuse_stats["avg_day_index"]
    assert concentrated_stats["active_days"] <= diffuse_stats["active_days"]
    assert concentrated_stats["longest_day_streak"] >= diffuse_stats["longest_day_streak"]
    assert concentrated_stats != diffuse_stats


def test_forward_vs_backward_has_quantitative_monotonicity_and_streak_differences() -> None:
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
                "stability_vs_recovery": 0.4,
                "default_strategy_mode": "hybrid",
                "human_distribution_mode": "off",
            },
            "by_subject": {"target": {"strategy_mode": "forward"}},
        },
        "subjects": {
            "subjects": [
                {
                    "subject_id": "target",
                    "priority": 2,
                    "cfu": 0.24,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-06"],
                    "selected_exam_date": "2026-01-06",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-06",
                },
                {
                    "subject_id": "peer",
                    "priority": 2,
                    "cfu": 0.24,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-06"],
                    "selected_exam_date": "2026-01-06",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-06",
                },
            ]
        },
        "global_config": {
            "daily_cap_minutes": 180,
            "daily_cap_tolerance_minutes": 0,
            "subject_buffer_percent": 0.2,
            "session_duration_minutes": 30,
            "default_strategy_mode": "hybrid",
        },
        "calendar_constraints": {"constraints": []},
        "manual_sessions": {"manual_sessions": []},
    }

    forward = run_planner(payload)
    payload["effective_config"]["by_subject"]["target"]["strategy_mode"] = "backward"
    backward = run_planner(payload)

    forward_stats = _subject_distribution_stats(forward["plan"], "target")
    backward_stats = _subject_distribution_stats(backward["plan"], "target")

    assert forward_stats["longest_day_streak"] <= backward_stats["longest_day_streak"]
    assert forward_stats["max_block_minutes"] == backward_stats["max_block_minutes"]


def test_phase1_forward_vs_backward_changes_candidate_timing_with_same_input() -> None:
    payload = {
        "effective_config": {
            "global": {
                "daily_cap_minutes": 120,
                "daily_cap_tolerance_minutes": 0,
                "subject_buffer_percent": 0.2,
                "critical_but_possible_threshold": 0.8,
                "study_on_exam_day": True,
                "max_subjects_per_day": 2,
                "session_duration_minutes": 30,
                "sleep_hours_per_day": 8,
                "pomodoro_enabled": False,
                "stability_vs_recovery": 0.4,
                "default_strategy_mode": "hybrid",
                "human_distribution_mode": "off",
            },
            "by_subject": {
                "target": {"strategy_mode": "forward"},
                "peer": {"strategy_mode": "hybrid"},
            },
        },
        "subjects": {
            "subjects": [
                {
                    "subject_id": "target",
                    "priority": 2,
                    "cfu": 0.24,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-07"],
                    "selected_exam_date": "2026-01-07",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-07",
                },
                {
                    "subject_id": "peer",
                    "priority": 2,
                    "cfu": 0.24,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-07"],
                    "selected_exam_date": "2026-01-07",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-07",
                },
            ]
        },
        "global_config": {
            "daily_cap_minutes": 120,
            "daily_cap_tolerance_minutes": 0,
            "subject_buffer_percent": 0.2,
            "session_duration_minutes": 30,
            "default_strategy_mode": "hybrid",
        },
        "calendar_constraints": {"constraints": []},
        "manual_sessions": {"manual_sessions": []},
    }

    forward_result = run_planner(payload)

    payload["effective_config"]["by_subject"]["target"]["strategy_mode"] = "backward"
    backward_result = run_planner(payload)

    assert forward_result["plan"] != backward_result["plan"]
    assert _avg_base_day_index(forward_result["plan"], "target") < _avg_base_day_index(backward_result["plan"], "target")

    forward_daily = _daily_base_minutes(forward_result["plan"], "target")
    backward_daily = _daily_base_minutes(backward_result["plan"], "target")
    assert forward_daily.get("2026-01-01", 0) > backward_daily.get("2026-01-01", 0)
    assert forward_daily.get("2026-01-07", 0) < backward_daily.get("2026-01-07", 0)

    assert any("RULE_STRATEGY_FORWARD" in item.get("applied_rules", []) for item in forward_result["decision_trace"])
    assert any("RULE_STRATEGY_BACKWARD" in item.get("applied_rules", []) for item in backward_result["decision_trace"])


def test_rebalance_enabled_produces_at_least_one_accepted_swap() -> None:
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
                "default_strategy_mode": "hybrid",
                "rebalance_max_swaps": 1,
                "rebalance_near_days_window": 10,
                "rebalance_enforce_near_days_window": False,
                "rebalance_require_strategy_mode_match": False,
            },
            "by_subject": {},
        },
        "subjects": {
            "subjects": [
                {
                    "subject_id": "math",
                    "priority": 2,
                    "cfu": 1,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-04"],
                    "selected_exam_date": "2026-01-04",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-04",
                },
                {
                    "subject_id": "physics",
                    "priority": 2,
                    "cfu": 1,
                    "difficulty_coeff": 1,
                    "completion_initial": 0,
                    "attending": False,
                    "exam_dates": ["2026-01-04"],
                    "selected_exam_date": "2026-01-04",
                    "start_at": "2026-01-01",
                    "end_by": "2026-01-04",
                },
            ]
        },
        "global_config": {
            "daily_cap_minutes": 180,
            "daily_cap_tolerance_minutes": 0,
            "subject_buffer_percent": 0.1,
            "critical_but_possible_threshold": 0.8,
            "study_on_exam_day": True,
            "max_subjects_per_day": 3,
            "session_duration_minutes": 30,
            "sleep_hours_per_day": 8,
            "pomodoro_enabled": False,
            "default_strategy_mode": "hybrid",
            "rebalance_max_swaps": 1,
            "rebalance_near_days_window": 10,
            "rebalance_enforce_near_days_window": False,
            "rebalance_require_strategy_mode_match": False,
        },
        "calendar_constraints": {"constraints": []},
        "manual_sessions": {"manual_sessions": []},
    }

    result = run_planner(payload)
    accepted_swaps = sum(
        1
        for item in result["decision_trace"]
        if "RULE_REBALANCE_SWAP" in item.get("applied_rules", [])
        or "RULE_REBALANCE_FALLBACK_SWAP" in item.get("applied_rules", [])
    )

    assert accepted_swaps > 0
