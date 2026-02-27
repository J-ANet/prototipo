"""Warning and suggestion generation for planning output."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from planner.metrics.collector import compute_humanity_metrics


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _to_date(value: Any, fallback: date) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return fallback
    return fallback


def _days_to_exam(reference: date, subject: dict[str, Any]) -> int:
    exams = subject.get("exam_dates", []) if isinstance(subject.get("exam_dates"), list) else []
    selected = subject.get("selected_exam_date")
    raw = selected if isinstance(selected, str) else (exams[0] if exams else reference.isoformat())
    exam_day = _to_date(raw, reference)
    return max(1, (exam_day - reference).days)


def _risk_threshold(days_to_exam: int) -> float:
    if days_to_exam > 30:
        return 0.60
    if days_to_exam > 14:
        return 0.45
    return 0.30


def build_warnings_and_suggestions(
    *,
    subjects: list[dict[str, Any]],
    manual_sessions: list[dict[str, Any]],
    slots_in_window: list[dict[str, Any]],
    allocations: list[dict[str, Any]],
    workload_by_subject: dict[str, dict[str, Any]],
    remaining_base_minutes: dict[str, int],
    remaining_buffer_minutes: dict[str, int],
    humanity_score: float | None = None,
    humanity_threshold: float | None = 0.45,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate mandatory warnings (spec section 15) and coherent suggestions."""
    warnings: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []

    ordered_dates = sorted(_to_date(slot.get("date"), date.today()) for slot in slots_in_window)
    reference_day = ordered_dates[0] if ordered_dates else date.today()

    capacity_by_day: dict[date, int] = {}
    for slot in slots_in_window:
        day = _to_date(slot.get("date"), reference_day)
        capacity_by_day[day] = capacity_by_day.get(day, 0) + int(slot.get("max_minutes", 0) or 0)

    planned_by_subject: dict[str, int] = defaultdict(int)
    for alloc in allocations:
        sid = str(alloc.get("subject_id", ""))
        if sid and sid != "__slack__":
            planned_by_subject[sid] += int(alloc.get("minutes", 0) or 0)

    computed_humanity = (
        _clamp01(humanity_score)
        if humanity_score is not None
        else float(compute_humanity_metrics(allocations).get("humanity_score", 1.0))
    )

    # (1) Manual sessions compressing future capacity.
    next_7_days = {reference_day.fromordinal(reference_day.toordinal() + i) for i in range(7)}
    cap_next_7 = sum(minutes for day, minutes in capacity_by_day.items() if day in next_7_days)
    manual_locked_next_7 = sum(
        int(s.get("planned_minutes", 0) or 0)
        for s in manual_sessions
        if bool(s.get("locked_by_user", False) or s.get("pinned", False))
        and _to_date(s.get("date"), reference_day) in next_7_days
    )
    compression_ratio = manual_locked_next_7 / max(1, cap_next_7)
    if compression_ratio >= 0.35:
        warnings.append(
            {
                "code": "WARN_MANUAL_COMPRESSES_CAPACITY",
                "severity": "warning",
                "message": "Le sessioni manuali bloccate comprimono la capacità futura disponibile.",
                "compression_ratio": round(_clamp01(compression_ratio), 4),
            }
        )
        suggestions.append(
            {
                "code": "SUGGEST_MOVE_MANUAL_SESSIONS",
                "message": "Spostare o sbloccare parte delle sessioni manuali nei prossimi 7 giorni.",
            }
        )

    # (2) Manual sessions over subject target.
    manual_by_subject: dict[str, int] = defaultdict(int)
    for session in manual_sessions:
        sid = str(session.get("subject_id", ""))
        manual_by_subject[sid] += max(0, int(session.get("planned_minutes", 0) or 0))

    for sid, manual_minutes in manual_by_subject.items():
        target = int(round(float(workload_by_subject.get(sid, {}).get("hours_target", 0.0)) * 60))
        if manual_minutes > target > 0:
            warnings.append(
                {
                    "code": "WARN_MANUAL_OVER_TARGET",
                    "severity": "warning",
                    "subject_id": sid,
                    "message": "Sessioni manuali superiori al fabbisogno target della materia.",
                }
            )
            suggestions.append(
                {
                    "code": "SUGGEST_MOVE_MANUAL_SESSIONS",
                    "subject_id": sid,
                    "message": "Spostare sessioni manuali in eccesso su materie con deficit.",
                }
            )

    # (3) Impossibility to meet end_by.
    for subject in subjects:
        sid = str(subject.get("subject_id", ""))
        end_by = _to_date(subject.get("end_by"), reference_day)
        allocable_until_end = sum(minutes for day, minutes in capacity_by_day.items() if day <= end_by)
        if remaining_base_minutes.get(sid, 0) > allocable_until_end:
            warnings.append(
                {
                    "code": "WARN_END_BY_NOT_FEASIBLE",
                    "severity": "warning",
                    "subject_id": sid,
                    "message": "Impossibile rispettare la data end_by con la capacità disponibile.",
                }
            )
            suggestions.append(
                {
                    "code": "SUGGEST_REVIEW_CAP",
                    "subject_id": sid,
                    "message": "Aumentare cap/tolleranza giornaliera o anticipare sessioni per rispettare end_by.",
                }
            )

    # (4) Consecutive weekly saturation.
    weekly_used: dict[tuple[int, int], int] = defaultdict(int)
    weekly_cap: dict[tuple[int, int], int] = defaultdict(int)
    used_by_day: dict[date, int] = defaultdict(int)
    for alloc in allocations:
        if alloc.get("subject_id") == "__slack__":
            continue
        day = _to_date(alloc.get("date"), reference_day)
        used_by_day[day] += int(alloc.get("minutes", 0) or 0)
    for day, cap in capacity_by_day.items():
        key = day.isocalendar()[:2]
        weekly_cap[key] += cap
        weekly_used[key] += used_by_day.get(day, 0)

    weeks = sorted(weekly_cap.keys())
    consecutive_high = 0
    for key in weeks:
        saturation = weekly_used.get(key, 0) / max(1, weekly_cap.get(key, 0))
        if saturation > 1.0:
            consecutive_high += 1
            if consecutive_high >= 2:
                warnings.append(
                    {
                        "code": "WARN_CONSECUTIVE_WEEKLY_SATURATION",
                        "severity": "warning",
                        "message": "Saturazione settimanale elevata su settimane consecutive.",
                    }
                )
                suggestions.append(
                    {
                        "code": "SUGGEST_REDUCE_BUFFER",
                        "message": "Ridurre buffer percentuale nelle materie meno rischiose per abbassare la saturazione.",
                    }
                )
                break
        else:
            consecutive_high = 0

    # (5) Base completable but buffer not allocable.
    for sid, rem_base in remaining_base_minutes.items():
        rem_buffer = max(0, int(remaining_buffer_minutes.get(sid, 0)))
        if rem_base == 0 and rem_buffer > 0:
            warnings.append(
                {
                    "code": "WARN_BUFFER_NOT_ALLOCABLE",
                    "severity": "warning",
                    "subject_id": sid,
                    "message": "Studio base completabile ma buffer non allocabile per mancanza slot utili.",
                }
            )
            suggestions.append(
                {
                    "code": "SUGGEST_REDUCE_BUFFER",
                    "subject_id": sid,
                    "message": "Ridurre buffer della materia o aumentare capacità nei giorni pre-esame.",
                }
            )

    # Dynamic exam risk warnings.
    for subject in subjects:
        sid = str(subject.get("subject_id", ""))
        days_to_exam = _days_to_exam(reference_day, subject)
        deficit_ratio = max(0, int(remaining_base_minutes.get(sid, 0))) / max(
            1, planned_by_subject.get(sid, 0) + int(remaining_base_minutes.get(sid, 0))
        )
        time_pressure = 1.0 / (max(1, days_to_exam) ** 0.5)
        risk_exam = _clamp01(0.7 * deficit_ratio + 0.3 * time_pressure)
        if risk_exam >= _risk_threshold(days_to_exam):
            warnings.append(
                {
                    "code": "WARN_RISK_EXAM_DYNAMIC",
                    "severity": "warning",
                    "subject_id": sid,
                    "risk_exam": round(risk_exam, 4),
                    "days_to_exam": days_to_exam,
                    "message": "Rischio esame elevato rispetto alla soglia dinamica.",
                }
            )
            suggestions.append(
                {
                    "code": "SUGGEST_REVIEW_CAP",
                    "subject_id": sid,
                    "message": "Rivedere cap giornaliero e priorità materia per ridurre il rischio esame.",
                }
            )

    threshold = _clamp01(0.45 if humanity_threshold is None else humanity_threshold)

    if computed_humanity < threshold:
        warnings.append(
            {
                "code": "WARN_PLAN_MONOTONOUS",
                "severity": "warning",
                "humanity_score": round(computed_humanity, 4),
                "threshold": round(threshold, 4),
                "message": "Distribuzione piano troppo monotona rispetto alla soglia di varietà umana.",
            }
        )
        suggestions.append(
            {
                "code": "SUGGEST_INCREASE_VARIETY",
                "message": "Anticipa 1-2 blocchi di materia secondaria nei giorni più concentrati per migliorare varietà e ritmo.",
            }
        )

    unique_suggestions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in suggestions:
        key = (str(item.get("code", "")), str(item.get("subject_id", "*")))
        if key in seen:
            continue
        seen.add(key)
        unique_suggestions.append(item)

    return warnings, unique_suggestions
