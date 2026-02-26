"""Workload formulas for base/buffer/target hours."""

from __future__ import annotations

from typing import Any

DEFAULT_ATTENDANCE_HOURS_PER_CFU = 6.0


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_subject_workload(
    subject: dict[str, Any],
    *,
    subject_buffer_percent: float,
    attended_calendar_hours: float | None = None,
) -> dict[str, float]:
    """Compute official workload formulas with attendance correction.

    Formulas:
    - hours_theoretical = cfu * 25
    - hours_base = max(0, (hours_theoretical - attendance_discount_hours) * difficulty_coeff * prep_gap_coeff)
    - hours_buffer = hours_base * subject_buffer_percent
    - hours_target = hours_base + hours_buffer
    """

    cfu = _as_float(subject.get("cfu"), 0.0)
    difficulty_coeff = _as_float(subject.get("difficulty_coeff"), 1.0)
    completion_initial = _as_float(subject.get("completion_initial"), 0.0)
    completion_initial = min(1.0, max(0.0, completion_initial))

    attending = bool(subject.get("attending", False))
    attendance_discount_hours = 0.0
    if attending:
        if attended_calendar_hours is not None:
            attendance_discount_hours = max(0.0, float(attended_calendar_hours))
        else:
            attendance_hours_per_cfu = _as_float(
                subject.get("attendance_hours_per_cfu"), DEFAULT_ATTENDANCE_HOURS_PER_CFU
            )
            attendance_discount_hours = max(0.0, cfu * attendance_hours_per_cfu)

    hours_theoretical = cfu * 25.0
    prep_gap_coeff = 1.0 + (1.0 - completion_initial)
    hours_base = max(
        0.0,
        (hours_theoretical - attendance_discount_hours) * difficulty_coeff * prep_gap_coeff,
    )
    hours_buffer = max(0.0, hours_base * float(subject_buffer_percent))
    hours_target = hours_base + hours_buffer

    return {
        "hours_theoretical": hours_theoretical,
        "attendance_discount_hours": attendance_discount_hours,
        "prep_gap_coeff": prep_gap_coeff,
        "hours_base": hours_base,
        "hours_buffer": hours_buffer,
        "hours_target": hours_target,
    }
