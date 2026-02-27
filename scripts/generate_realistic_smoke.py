from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from planner.cli import run_plan_command

OUT = ROOT / "results" / "realistic_smoke" / "realism_checks.json"



def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")



def _run_case(tmp_dir: Path, case: dict) -> dict:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    request = tmp_dir / "plan_request.json"
    gc = tmp_dir / "global_config.json"
    sj = tmp_dir / "subjects.json"
    cc = tmp_dir / "calendar_constraints.json"
    ms = tmp_dir / "manual_sessions.json"
    output = tmp_dir / "plan_output.json"

    _write(gc, case["global_config"])
    _write(sj, case["subjects"])
    _write(cc, {"constraints": []})
    _write(ms, {"schema_version": "1.0", "manual_sessions": []})
    _write(
        request,
        {
            "schema_version": "1.0",
            "request_id": f"realistic-{case['name']}",
            "generated_at": "2026-01-01T00:00:00Z",
            "global_config_path": gc.name,
            "subjects_path": sj.name,
            "calendar_constraints_path": cc.name,
            "manual_sessions_path": ms.name,
        },
    )

    exit_code = run_plan_command(str(request), str(output))
    payload = json.loads(output.read_text(encoding="utf-8"))
    metrics = payload.get("metrics", {})

    humanity_score = float(metrics.get("humanity_score", 0.0) or 0.0)
    mono_day_ratio = float(metrics.get("mono_day_ratio", 1.0) or 1.0)
    switch_rate = float(metrics.get("switch_rate", 0.0) or 0.0)
    max_streak_days = float(metrics.get("max_same_subject_streak_days", 0.0) or 0.0)
    subject_variety_index = float(metrics.get("subject_variety_index", 0.0) or 0.0)

    checks = {
        "exit_code": {"value": exit_code, "expected": 0, "status": "pass" if exit_code == 0 else "fail"},
        "humanity_score": {
            "value": round(humanity_score, 4),
            "threshold_min": case["min_humanity_score"],
            "status": "pass" if humanity_score >= case["min_humanity_score"] else "fail",
        },
        "mono_day_ratio": {
            "value": round(mono_day_ratio, 4),
            "threshold_max": case["max_mono_day_ratio"],
            "status": "pass" if mono_day_ratio <= case["max_mono_day_ratio"] else "fail",
        },
        "switch_rate": {
            "value": round(switch_rate, 4),
            "threshold_min": case["min_switch_rate"],
            "status": "pass" if switch_rate >= case["min_switch_rate"] else "fail",
        },
        "max_same_subject_streak_days": {
            "value": round(max_streak_days, 4),
            "threshold_max": case.get("max_same_subject_streak_days_target", 99),
            "status": "pass"
            if max_streak_days <= case.get("max_same_subject_streak_days_target", 99)
            else "fail",
        },
        "subject_variety_index": {
            "value": round(subject_variety_index, 4),
            "threshold_min": case.get("min_subject_variety_index", 0.0),
            "status": "pass"
            if subject_variety_index >= case.get("min_subject_variety_index", 0.0)
            else "fail",
        },
    }

    return {
        "scenario": case["name"],
        "mode": case["global_config"].get("human_distribution_mode", "off"),
        "metrics": {
            "confidence_score": round(float(metrics.get("confidence_score", 0.0) or 0.0), 4),
            "humanity_score": round(humanity_score, 4),
            "mono_day_ratio": round(mono_day_ratio, 4),
            "max_same_subject_streak_days": round(max_streak_days, 4),
            "switch_rate": round(switch_rate, 4),
            "subject_variety_index": round(subject_variety_index, 4),
        },
        "checks": checks,
        "status": "pass" if all(item["status"] == "pass" for item in checks.values()) else "fail",
    }



def main() -> None:
    cases = [
        {
            "name": "off_monotone",
            "global_config": {
                "schema_version": "1.0",
                "daily_cap_minutes": 240,
                "daily_cap_tolerance_minutes": 0,
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
                "human_distribution_mode": "off",
                "target_daily_subject_variety": 2,
            },
            "subjects": {
                "schema_version": "1.0",
                "subjects": [
                    {"subject_id": "s1", "name": "Core", "cfu": 2.0, "difficulty_coeff": 1, "priority": 3, "completion_initial": 0, "attending": False, "exam_dates": ["2026-01-04"], "selected_exam_date": "2026-01-04", "start_at": "2026-01-01", "end_by": "2026-01-04"},
                    {"subject_id": "s2", "name": "Secondary", "cfu": 0.6, "difficulty_coeff": 1, "priority": 1, "completion_initial": 0, "attending": False, "exam_dates": ["2026-01-04"], "selected_exam_date": "2026-01-04", "start_at": "2026-01-01", "end_by": "2026-01-04"},
                ],
            },
            "min_humanity_score": 0.30,
            "max_mono_day_ratio": 1.0,
            "min_switch_rate": 0.05,
            "max_same_subject_streak_days_target": 99,
            "min_subject_variety_index": 0.3,
        },
        {
            "name": "balanced_diffuse",
            "global_config": {
                "schema_version": "1.0",
                "daily_cap_minutes": 240,
                "daily_cap_tolerance_minutes": 0,
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
                "human_distribution_mode": "balanced",
                "concentration_mode": "diffuse",
                "target_daily_subject_variety": 2,
                "max_same_subject_streak_days": 2,
                "max_same_subject_streak_days_target": 2,
                "max_same_subject_consecutive_blocks": 2,
                "human_distribution_strength": 0.35,
            },
            "subjects": {
                "schema_version": "1.0",
                "subjects": [
                    {"subject_id": "s1", "name": "Core", "cfu": 2.0, "difficulty_coeff": 1, "priority": 3, "completion_initial": 0, "attending": False, "exam_dates": ["2026-01-04"], "selected_exam_date": "2026-01-04", "start_at": "2026-01-01", "end_by": "2026-01-04"},
                    {"subject_id": "s2", "name": "Secondary", "cfu": 0.6, "difficulty_coeff": 1, "priority": 1, "completion_initial": 0, "attending": False, "exam_dates": ["2026-01-04"], "selected_exam_date": "2026-01-04", "start_at": "2026-01-01", "end_by": "2026-01-04"},
                ],
            },
            "min_humanity_score": 0.55,
            "max_mono_day_ratio": 1.0,
            "min_switch_rate": 0.10,
            "max_same_subject_streak_days_target": 2,
            "min_subject_variety_index": 0.6,
        },
    ]

    scenarios = []
    with TemporaryDirectory() as td:
        base = Path(td)
        for case in cases:
            scenarios.append(_run_case(base / case["name"], case))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"scenarios": scenarios}, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
