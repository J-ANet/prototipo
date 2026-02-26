"""Domain-level cross-file validation rules."""

from __future__ import annotations

from datetime import date
from typing import Any

from .errors import ValidationReport

def validate_domain_inputs(loaded_payload: dict[str, Any]) -> ValidationReport:
    """Validate cross-file coherence and non-schema rules."""
    report = ValidationReport()

    global_config = loaded_payload.get("global_config", {})
    subjects_payload = loaded_payload.get("subjects", {})
    manual_payload = loaded_payload.get("manual_sessions", {})

    _clamp_stability(global_config, report)
    _validate_pomodoro_config(global_config, "$.global_config", report)

    subjects = subjects_payload.get("subjects", []) if isinstance(subjects_payload, dict) else []
    subject_ids: set[str] = set()
    for idx, subject in enumerate(subjects):
        if not isinstance(subject, dict):
            continue
        subject_id = subject.get("subject_id")
        if isinstance(subject_id, str):
            if subject_id in subject_ids:
                report.add_error(
                    code="DUPLICATE_SUBJECT_ID",
                    message=f"Duplicate subject_id: {subject_id}",
                    field_path=f"$.subjects.subjects[{idx}].subject_id",
                )
            subject_ids.add(subject_id)

        selected_exam_date = subject.get("selected_exam_date")
        exam_dates = subject.get("exam_dates", [])
        if selected_exam_date and isinstance(exam_dates, list) and selected_exam_date not in exam_dates:
            report.add_error(
                code="INVALID_SELECTED_EXAM_DATE",
                message="selected_exam_date must exist in exam_dates",
                field_path=f"$.subjects.subjects[{idx}].selected_exam_date",
            )

        start_at = subject.get("start_at")
        end_by = subject.get("end_by")
        if isinstance(start_at, str) and isinstance(end_by, str):
            if _parse_date(start_at) and _parse_date(end_by) and _parse_date(start_at) > _parse_date(end_by):
                report.add_error(
                    code="INVALID_DATE_WINDOW",
                    message="start_at must be <= end_by",
                    field_path=f"$.subjects.subjects[{idx}]",
                    suggested_fix="Swap the dates or adjust the study window.",
                )

        overrides = subject.get("overrides")
        if isinstance(overrides, dict):
            _validate_pomodoro_config(overrides, f"$.subjects.subjects[{idx}].overrides", report)

    manual_sessions = manual_payload.get("manual_sessions", []) if isinstance(manual_payload, dict) else []
    for idx, session in enumerate(manual_sessions):
        if not isinstance(session, dict):
            continue
        session_subject = session.get("subject_id")
        if isinstance(session_subject, str) and session_subject not in subject_ids:
            report.add_error(
                code="UNKNOWN_SUBJECT_REFERENCE",
                message=f"Unknown subject_id reference: {session_subject}",
                field_path=f"$.manual_sessions.manual_sessions[{idx}].subject_id",
            )

        _validate_session_status(session, idx, report)

    return report


def _clamp_stability(global_config: dict[str, Any], report: ValidationReport) -> None:
    stability = global_config.get("stability_vs_recovery")
    if not isinstance(stability, (int, float)) or isinstance(stability, bool):
        return
    clamped = min(1.0, max(0.0, float(stability)))
    if clamped != stability:
        global_config["stability_vs_recovery"] = clamped
        report.add_info(
            code="INFO_CLAMP_STABILITY_APPLIED",
            message="stability_vs_recovery was clamped into [0,1]",
            field_path="$.global_config.stability_vs_recovery",
            extra={"applied_value": clamped},
        )


def _validate_pomodoro_config(source: dict[str, Any], path: str, report: ValidationReport) -> None:
    if not isinstance(source, dict):
        return
    enabled = source.get("pomodoro_enabled", True)
    if enabled is False:
        return

    work = source.get("pomodoro_work_minutes")
    short = source.get("pomodoro_short_break_minutes")
    long_break = source.get("pomodoro_long_break_minutes")
    long_every = source.get("pomodoro_long_break_every")
    if work is not None and isinstance(work, int) and work < 15:
        report.add_error(
            code="INVALID_POMODORO_CONFIG",
            message="pomodoro_work_minutes must be >= 15",
            field_path=f"{path}.pomodoro_work_minutes",
        )
    if short is not None and isinstance(short, int) and short < 0:
        report.add_error(
            code="INVALID_POMODORO_CONFIG",
            message="pomodoro_short_break_minutes must be >= 0",
            field_path=f"{path}.pomodoro_short_break_minutes",
        )
    if long_break is not None and isinstance(long_break, int) and long_break < 0:
        report.add_error(
            code="INVALID_POMODORO_CONFIG",
            message="pomodoro_long_break_minutes must be >= 0",
            field_path=f"{path}.pomodoro_long_break_minutes",
        )
    if long_every is not None and isinstance(long_every, int) and long_every < 2:
        report.add_error(
            code="INVALID_POMODORO_CONFIG",
            message="pomodoro_long_break_every must be >= 2",
            field_path=f"{path}.pomodoro_long_break_every",
        )


def _validate_session_status(session: dict[str, Any], idx: int, report: ValidationReport) -> None:
    status = session.get("status")
    planned = session.get("planned_minutes")
    actual = session.get("actual_minutes_done")
    path = f"$.manual_sessions.manual_sessions[{idx}]"

    if status == "skipped" and actual not in (0, None):
        report.add_error(
            code="INVALID_STATUS_MINUTES_COMBINATION",
            message="Skipped sessions must have actual_minutes_done = 0",
            field_path=f"{path}.actual_minutes_done",
        )
    elif status == "done" and isinstance(actual, int) and isinstance(planned, int) and actual < planned:
        report.add_error(
            code="INVALID_STATUS_MINUTES_COMBINATION",
            message="Done sessions require actual_minutes_done >= planned_minutes",
            field_path=f"{path}.actual_minutes_done",
        )
    elif status == "partial":
        if not (isinstance(actual, int) and isinstance(planned, int) and 0 < actual < planned):
            report.add_error(
                code="INVALID_STATUS_MINUTES_COMBINATION",
                message="Partial sessions require 0 < actual_minutes_done < planned_minutes",
                field_path=f"{path}.actual_minutes_done",
            )


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None
