"""Resolve effective planner configuration from layered inputs."""

from __future__ import annotations

from datetime import date
from typing import Any

from planner.validation import ValidationReport

DEFAULT_GLOBAL_CONFIG: dict[str, Any] = {
    "daily_cap_minutes": 180,
    "daily_cap_tolerance_minutes": 30,
    "subject_buffer_percent": 0.10,
    "critical_but_possible_threshold": 0.80,
    "study_on_exam_day": False,
    "max_subjects_per_day": 3,
    "sleep_hours_per_day": 8,
    "session_duration_minutes": 30,
    "pomodoro_enabled": True,
    "pomodoro_count_breaks_in_capacity": True,
    "default_strategy_mode": "hybrid",
    "stability_vs_recovery": 0.4,
    "human_distribution_mode": "off",
    "max_same_subject_streak_days": 3,
    "max_same_subject_consecutive_blocks": 3,
    "target_daily_subject_variety": 2,
}

_ALLOWED_OVERRIDE_KEYS = {
    "subject_buffer_percent",
    "critical_but_possible_threshold",
    "strategy_mode",
    "stability_vs_recovery",
    "start_at",
    "end_by",
    "max_subjects_per_day",
    "pomodoro_enabled",
    "pomodoro_work_minutes",
    "pomodoro_short_break_minutes",
    "pomodoro_long_break_minutes",
    "pomodoro_long_break_every",
    "pomodoro_count_breaks_in_capacity",
    "human_distribution_mode",
    "max_same_subject_streak_days",
    "max_same_subject_consecutive_blocks",
}


def resolve_effective_config(loaded_payload: dict[str, Any], validation_report: ValidationReport) -> dict[str, Any]:
    """Build an ordered, engine-ready effective configuration payload."""
    global_source = loaded_payload.get("global_config", {})
    global_config = _resolve_global_config(global_source, validation_report)

    subjects_root = loaded_payload.get("subjects", {})
    subjects = subjects_root.get("subjects", []) if isinstance(subjects_root, dict) else []

    by_subject: dict[str, dict[str, Any]] = {}
    for idx, subject in enumerate(subjects):
        if not isinstance(subject, dict):
            continue

        subject_id = subject.get("subject_id")
        if not isinstance(subject_id, str) or not subject_id:
            continue

        overrides = subject.get("overrides") if isinstance(subject.get("overrides"), dict) else {}
        valid_overrides = _filter_allowed_overrides(overrides, idx, validation_report)

        # Ordered merge: global resolved config first, then per-subject overrides.
        by_subject[subject_id] = {**global_config, **valid_overrides}

    return {
        "global": global_config,
        "by_subject": by_subject,
    }


def resolve_sleep_hours(global_config: dict[str, Any], day: str | date) -> float:
    """Resolve sleep hours precedence for a given day.

    Precedence: by-date > by-weekday > base sleep_hours_per_day.
    """
    target_date = day if isinstance(day, date) else date.fromisoformat(day)
    by_date = global_config.get("sleep_overrides_by_date")
    if isinstance(by_date, dict):
        specific = by_date.get(target_date.isoformat())
        if isinstance(specific, (int, float)) and not isinstance(specific, bool):
            return float(specific)

    by_weekday = global_config.get("sleep_overrides_by_weekday")
    if isinstance(by_weekday, dict):
        weekday = target_date.strftime("%a").lower()[:3]
        specific = by_weekday.get(weekday)
        if isinstance(specific, (int, float)) and not isinstance(specific, bool):
            return float(specific)

    fallback = global_config.get("sleep_hours_per_day", DEFAULT_GLOBAL_CONFIG["sleep_hours_per_day"])
    if isinstance(fallback, (int, float)) and not isinstance(fallback, bool):
        return float(fallback)

    return float(DEFAULT_GLOBAL_CONFIG["sleep_hours_per_day"])


def _resolve_global_config(source: Any, validation_report: ValidationReport) -> dict[str, Any]:
    global_config = dict(DEFAULT_GLOBAL_CONFIG)
    if isinstance(source, dict):
        global_config.update(source)

    stability = global_config.get("stability_vs_recovery")
    if isinstance(stability, (int, float)) and not isinstance(stability, bool):
        clamped = min(1.0, max(0.0, float(stability)))
        if clamped != stability:
            global_config["stability_vs_recovery"] = clamped
            validation_report.add_info(
                code="INFO_CLAMP_STABILITY_APPLIED",
                message="stability_vs_recovery was clamped into [0,1]",
                field_path="$.global_config.stability_vs_recovery",
                extra={"applied_value": clamped},
            )

    return global_config


def _filter_allowed_overrides(
    overrides: dict[str, Any],
    subject_index: int,
    validation_report: ValidationReport,
) -> dict[str, Any]:
    filtered: dict[str, Any] = {}
    for key, value in overrides.items():
        if key in _ALLOWED_OVERRIDE_KEYS:
            filtered[key] = value
            continue

        validation_report.add_error(
            code="INVALID_OVERRIDE_KEY",
            message=f"Override key {key!r} is not allowed",
            field_path=f"$.subjects.subjects[{subject_index}].overrides.{key}",
            suggested_fix=f"Use one of: {', '.join(sorted(_ALLOWED_OVERRIDE_KEYS))}",
        )

    return filtered
