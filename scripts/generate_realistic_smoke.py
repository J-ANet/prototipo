from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from planner.engine import run_planner
from planner.metrics import collect_metrics
from planner.normalization import resolve_effective_config
from planner.validation import ValidationReport

OUT = ROOT / "results" / "realistic_smoke" / "realism_checks.json"


def _evaluate_metrics(case: dict, metrics: dict) -> tuple[dict, dict]:
    humanity_score = float(metrics.get("humanity_score", 0.0) or 0.0)
    mono_day_ratio = float(metrics.get("mono_day_ratio", 1.0) or 1.0)
    switch_rate = float(metrics.get("switch_rate", 0.0) or 0.0)
    max_streak_days = float(metrics.get("max_same_subject_streak_days", 0.0) or 0.0)
    subject_variety_index = float(metrics.get("subject_variety_index", 0.0) or 0.0)

    checks = {
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
            "status": "pass" if max_streak_days <= case.get("max_same_subject_streak_days_target", 99) else "fail",
        },
        "subject_variety_index": {
            "value": round(subject_variety_index, 4),
            "threshold_min": case.get("min_subject_variety_index", 0.0),
            "status": "pass" if subject_variety_index >= case.get("min_subject_variety_index", 0.0) else "fail",
        },
    }

    compact = {
        "confidence_score": round(float(metrics.get("confidence_score", 0.0) or 0.0), 4),
        "humanity_score": round(humanity_score, 4),
        "mono_day_ratio": round(mono_day_ratio, 4),
        "max_same_subject_streak_days": round(max_streak_days, 4),
        "switch_rate": round(switch_rate, 4),
        "subject_variety_index": round(subject_variety_index, 4),
    }
    return compact, checks


def _run_single(case: dict, *, rebalance_max_swaps: int) -> dict:
    loaded = {
        "plan_request": {
            "schema_version": "1.0",
            "request_id": f"realistic-{case['name']}-{rebalance_max_swaps}",
            "generated_at": "2026-01-01T00:00:00Z",
        },
        "global_config": deepcopy(case["global_config"]),
        "subjects": deepcopy(case["subjects"]),
        "calendar_constraints": {"constraints": []},
        "manual_sessions": {"schema_version": "1.0", "manual_sessions": []},
    }
    loaded["global_config"]["rebalance_max_swaps"] = rebalance_max_swaps
    loaded["effective_config"] = resolve_effective_config(loaded, ValidationReport())

    result = run_planner(loaded)
    metrics = collect_metrics(result)
    compact, checks = _evaluate_metrics(case, metrics)

    return {
        "rebalance_max_swaps": rebalance_max_swaps,
        "accepted_swaps": len(result.get("rebalanced_swaps", [])),
        "metrics": compact,
        "checks": checks,
        "status": "pass" if all(item["status"] == "pass" for item in checks.values()) else "fail",
    }


def _run_case(case: dict) -> dict:
    pre = _run_single(case, rebalance_max_swaps=0)
    post = _run_single(case, rebalance_max_swaps=int(case.get("rebalance_max_swaps", 100)))

    return {
        "scenario": case["name"],
        "mode": case["global_config"].get("human_distribution_mode", "off"),
        "pre_rebalance": pre,
        "post_rebalance": post,
        "comparison": {
            "humanity_delta": round(post["metrics"]["humanity_score"] - pre["metrics"]["humanity_score"], 4),
            "max_same_subject_streak_days_delta": round(
                post["metrics"]["max_same_subject_streak_days"] - pre["metrics"]["max_same_subject_streak_days"], 4
            ),
            "mono_day_ratio_delta": round(post["metrics"]["mono_day_ratio"] - pre["metrics"]["mono_day_ratio"], 4),
        },
        "status": "pass" if pre["status"] == "pass" and post["status"] == "pass" else "fail",
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
            "rebalance_max_swaps": 20,
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
            "rebalance_max_swaps": 20,
        },
    ]

    scenarios = [_run_case(case) for case in cases]
    report = {
        "scenarios": scenarios,
        "summary": {
            "humanity_delta": round(sum(item["comparison"]["humanity_delta"] for item in scenarios), 4),
            "status": "pass" if all(item["status"] == "pass" for item in scenarios) else "fail",
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")

    if report["summary"]["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
