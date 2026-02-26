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
