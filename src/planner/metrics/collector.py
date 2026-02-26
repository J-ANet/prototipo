"""Planning metrics collector (spec section 16)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import mean, pstdev
from typing import Any


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _confidence_level(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def collect_metrics(result: dict[str, Any]) -> dict[str, Any]:
    """Compute normalized metrics with clamp in [0,1]."""
    allocations = [item for item in result.get("plan", []) if isinstance(item, dict)]
    slots = [item for item in result.get("slots_in_window", []) if isinstance(item, dict)]
    subjects = [item for item in result.get("subjects", []) if isinstance(item, dict)]
    workload = result.get("workload_by_subject", {}) if isinstance(result.get("workload_by_subject"), dict) else {}
    rem_base = result.get("remaining_base_minutes", {}) if isinstance(result.get("remaining_base_minutes"), dict) else {}
    rem_buffer = result.get("remaining_buffer_minutes", {}) if isinstance(result.get("remaining_buffer_minutes"), dict) else {}

    used_by_day: dict[str, int] = defaultdict(int)
    used_by_subject: dict[str, dict[str, int]] = defaultdict(lambda: {"base": 0, "buffer": 0, "total": 0})
    used_total = 0
    tolerance_used = 0

    slot_by_day: dict[str, dict[str, Any]] = {}
    for slot in slots:
        day = str(slot.get("date", ""))
        slot_by_day[day] = slot

    day_subject_totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for alloc in allocations:
        sid = str(alloc.get("subject_id", ""))
        if sid == "__slack__":
            continue
        minutes = max(0, int(alloc.get("minutes", 0) or 0))
        day = str(alloc.get("date", ""))
        bucket = str(alloc.get("bucket", ""))

        used_total += minutes
        used_by_day[day] += minutes
        day_subject_totals[day][sid] += minutes
        used_by_subject[sid]["total"] += minutes
        if bucket == "base":
            used_by_subject[sid]["base"] += minutes
        elif bucket == "buffer":
            used_by_subject[sid]["buffer"] += minutes

    sat_day_values: list[float] = []
    weekly_used: dict[tuple[int, int], int] = defaultdict(int)
    weekly_cap: dict[tuple[int, int], int] = defaultdict(int)
    free_by_day: dict[str, int] = {}
    over_capacity_minutes_total = 0

    for day, slot in slot_by_day.items():
        cap = max(0, int(slot.get("cap_minutes", 0) or 0))
        tol = max(0, int(slot.get("tolerance_minutes", 0) or 0))
        denom = max(1, cap + tol)
        used = used_by_day.get(day, 0)
        sat_day_values.append(_clamp01(used / denom))

        day_date = date.fromisoformat(day)
        wk = day_date.isocalendar()[:2]
        weekly_used[wk] += used
        weekly_cap[wk] += denom

        tolerance_used += max(0, used - cap)
        free_by_day[day] = max(0, denom - used)
        over_capacity_minutes_total += max(0, used - denom)

    weekly_saturation_values: list[float] = []
    for wk, cap in weekly_cap.items():
        weekly_saturation_values.append(weekly_used[wk] / max(1, cap))

    subject_ids = [str(s.get("subject_id", "")) for s in subjects if s.get("subject_id")]
    coverage_values: list[float] = []
    buffer_coverage_values: list[float] = []
    risk_values: list[float] = []

    sorted_days = sorted(slot_by_day.keys())
    reference_day = date.fromisoformat(sorted_days[0]) if sorted_days else date.today()

    for sid in subject_ids:
        req_base = max(1, int(round(float(workload.get(sid, {}).get("hours_base", 0.0)) * 60)))
        req_buffer = max(1, int(round(float(workload.get(sid, {}).get("hours_buffer", 0.0)) * 60)))
        planned_base = used_by_subject[sid]["base"]
        planned_buffer = used_by_subject[sid]["buffer"]

        coverage_values.append(_clamp01(planned_base / req_base))
        buffer_coverage_values.append(_clamp01(planned_buffer / req_buffer))

        days_to_exam = 30
        subject = next((sub for sub in subjects if str(sub.get("subject_id", "")) == sid), None)
        if isinstance(subject, dict):
            raw = subject.get("selected_exam_date") or (subject.get("exam_dates", [None])[0])
            if isinstance(raw, str):
                try:
                    exam_day = date.fromisoformat(raw)
                    days_to_exam = max(1, (exam_day - reference_day).days)
                except ValueError:
                    days_to_exam = 30

        deficit_ratio = max(0, int(rem_base.get(sid, 0) or 0)) / max(1, req_base)
        time_pressure = 1.0 / (max(1, days_to_exam) ** 0.5)
        risk_values.append(_clamp01(0.7 * deficit_ratio + 0.3 * time_pressure))

    coverage_subject = _clamp01(mean(coverage_values) if coverage_values else 1.0)
    buffer_coverage_subject = _clamp01(mean(buffer_coverage_values) if buffer_coverage_values else 1.0)
    feasibility = _clamp01(1.0 - (over_capacity_minutes_total / max(1, used_total)))

    sat_day = _clamp01(mean(sat_day_values) if sat_day_values else 0.0)
    weekly_saturation = max(weekly_saturation_values) if weekly_saturation_values else 0.0
    saturation_excess = [max(0.0, item - 1.0) for item in weekly_saturation_values]
    saturation_score = _clamp01(1.0 - min(1.0, (mean(saturation_excess) if saturation_excess else 0.0)))

    risk_exam = _clamp01(mean(risk_values) if risk_values else 0.0)
    risk_exam_score = _clamp01(1.0 - risk_exam)

    daily_minutes = list(used_by_day.values())
    avg_daily = mean(daily_minutes) if daily_minutes else 0.0
    cv = (pstdev(daily_minutes) / max(1.0, avg_daily)) if daily_minutes else 0.0
    balance_score = _clamp01(1.0 - min(1.0, cv))

    next_7 = sorted_days[:7]
    free_next_7 = sum(free_by_day.get(day, 0) for day in next_7)
    req_next_7 = 0
    for sid in subject_ids:
        req_next_7 += min(int(rem_base.get(sid, 0) or 0), int(round(max(0, int(rem_base.get(sid, 0) or 0)) * (7 / 30))))
    robustness = _clamp01(free_next_7 / max(1, req_next_7))

    backlog_minutes = sum(max(0, int(rem_base.get(sid, 0) or 0)) + max(0, int(rem_buffer.get(sid, 0) or 0)) for sid in subject_ids)
    avg_free = mean(list(free_by_day.values())) if free_by_day else 0.0
    recovery_days = backlog_minutes / max(1.0, avg_free)
    recovery_score = _clamp01(1.0 - min(1.0, recovery_days / 14.0))

    tolerance_dependency = _clamp01(tolerance_used / max(1, used_total))
    tolerance_dependency_score = _clamp01(1.0 - tolerance_dependency)

    concentration_values = []
    for _, sub_totals in day_subject_totals.items():
        day_total = sum(sub_totals.values())
        concentration_values.append(max(sub_totals.values()) / max(1, day_total))
    subject_concentration = mean(concentration_values) if concentration_values else 0.0
    concentration_score = _clamp01(1.0 - min(1.0, subject_concentration))

    reallocated_ratio = _clamp01(float(result.get("reallocated_ratio", 0.0) or 0.0))
    stability_score = _clamp01(float(result.get("stability_score", 1.0) or 1.0))

    confidence_score = _clamp01(
        (0.28 * coverage_subject)
        + (0.22 * risk_exam_score)
        + (0.12 * feasibility)
        + (0.10 * stability_score)
        + (0.08 * robustness)
        + (0.06 * balance_score)
        + (0.05 * saturation_score)
        + (0.04 * recovery_score)
        + (0.03 * tolerance_dependency_score)
        + (0.02 * concentration_score)
    )

    return {
        "coverage_subject": coverage_subject,
        "buffer_coverage_subject": buffer_coverage_subject,
        "feasibility": feasibility,
        "sat_day": sat_day,
        "weekly_saturation": _clamp01(weekly_saturation),
        "saturation_score": saturation_score,
        "risk_exam": risk_exam,
        "risk_exam_score": risk_exam_score,
        "cv": _clamp01(cv),
        "balance_score": balance_score,
        "robustness": robustness,
        "recovery_days": recovery_days,
        "recovery_score": recovery_score,
        "tolerance_dependency": tolerance_dependency,
        "tolerance_dependency_score": tolerance_dependency_score,
        "subject_concentration": _clamp01(subject_concentration),
        "concentration_score": concentration_score,
        "reallocated_ratio": reallocated_ratio,
        "stability_score": stability_score,
        "confidence_score": confidence_score,
        "confidence_level": _confidence_level(confidence_score),
        "plan_size": len(allocations),
    }
