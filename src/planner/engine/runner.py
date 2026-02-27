"""Planning engine runner."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from .allocator import allocate_plan
from .rebalance import rebalance_allocations
from .replan import (
    apply_locked_constraints_to_slots,
    build_critical_warnings,
    compute_manual_progress,
    compute_reallocation_metrics,
    extract_locked_manual_allocations,
    read_replan_window,
    split_previous_plan,
)
from planner.reporting.decision_trace import DecisionTraceCollector
from planner.reporting.warnings import build_warnings_and_suggestions
from planner.metrics.collector import compute_humanity_metrics
from .slot_builder import build_daily_slots
from .workload import compute_subject_workload


_DEF_START = date(2026, 1, 1)
_DEF_END = date(2026, 1, 7)


def _parse_date(raw: Any, fallback: date) -> date:
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return fallback
    return fallback


def _extract_subjects(payload: dict[str, Any]) -> list[dict[str, Any]]:
    root = payload.get("subjects", {})
    if isinstance(root, dict):
        items = root.get("subjects", [])
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _extract_calendar_constraints(payload: dict[str, Any]) -> list[dict[str, Any]]:
    root = payload.get("calendar_constraints", {})
    if isinstance(root, dict):
        items = root.get("constraints", [])
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _extract_manual_sessions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    root = payload.get("manual_sessions", {})
    if isinstance(root, dict):
        items = root.get("manual_sessions", [])
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _extract_previous_allocations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    prev = payload.get("previous_plan", {})
    if isinstance(prev, dict):
        plan = prev.get("plan")
        if isinstance(plan, list):
            return [item for item in plan if isinstance(item, dict)]
    return []


def _derive_horizon(subjects: list[dict[str, Any]]) -> tuple[date, date]:
    starts: list[date] = []
    ends: list[date] = []
    for subject in subjects:
        starts.append(_parse_date(subject.get("start_at"), _DEF_START))
        candidates = [
            _parse_date(subject.get("end_by"), _DEF_END),
            _parse_date(subject.get("selected_exam_date"), _DEF_END),
        ]
        exam_dates = subject.get("exam_dates", [])
        if isinstance(exam_dates, list):
            candidates.extend(_parse_date(raw, _DEF_END) for raw in exam_dates)
        ends.append(max(candidates))

    if not starts or not ends:
        return _DEF_START, _DEF_END
    return min(starts), max(ends)


def run_planner(payload: dict[str, Any]) -> dict[str, Any]:
    """Run planner with replan constraints and manual-session integration."""
    effective_config = payload.get("effective_config", {}) if isinstance(payload.get("effective_config"), dict) else {}
    global_config = effective_config.get("global", payload.get("global_config", {}))
    config_by_subject = effective_config.get("by_subject", {}) if isinstance(effective_config.get("by_subject"), dict) else {}
    default_subject_concentration_mode = (
        global_config.get("subject_concentration_mode", global_config.get("concentration_mode", "concentrated"))
        if isinstance(global_config, dict)
        else "concentrated"
    )
    subject_concentration_mode_by_subject = {
        sid: cfg.get(
            "subject_concentration_mode",
            cfg.get("concentration_mode", default_subject_concentration_mode),
        )
        for sid, cfg in config_by_subject.items()
        if isinstance(sid, str) and isinstance(cfg, dict)
    }
    subjects = _extract_subjects(payload)
    manual_sessions = _extract_manual_sessions(payload)
    constraints = _extract_calendar_constraints(payload)
    previous_allocations = _extract_previous_allocations(payload)

    horizon_start, horizon_end = _derive_horizon(subjects)
    window = read_replan_window(payload)

    slots = build_daily_slots(
        start_date=horizon_start,
        end_date=horizon_end,
        global_config=global_config,
        calendar_constraints=constraints,
    )

    manual_progress = compute_manual_progress(manual_sessions)

    workload_by_subject: dict[str, dict[str, Any]] = {}
    remaining_minutes: dict[str, int] = {}
    effective_done_minutes: dict[str, int] = {}
    for subject in subjects:
        sid = str(subject.get("subject_id", ""))
        workload = compute_subject_workload(
            subject,
            subject_buffer_percent=float(global_config.get("subject_buffer_percent", 0.10)),
        )
        done = int(manual_progress.get(sid, {}).get("effective_done_minutes", 0))
        base_minutes = max(0, int(round(float(workload.get("hours_base", 0.0)) * 60)))
        adjusted_base_minutes = max(0, base_minutes - done)
        workload["hours_base"] = adjusted_base_minutes / 60.0

        effective_done_minutes[sid] = done
        remaining_minutes[sid] = adjusted_base_minutes
        workload_by_subject[sid] = workload

    preserved_previous, previous_horizon = split_previous_plan(previous_allocations, window.from_date)

    locked_allocations = extract_locked_manual_allocations(manual_sessions, window.from_date)

    slots_in_window = []
    for slot in slots:
        if window.from_date is None:
            slots_in_window.append(slot)
            continue
        slot_day = _parse_date(slot.get("date"), _DEF_END)
        if slot_day >= window.from_date:
            slots_in_window.append(slot)

    constrained_slots = apply_locked_constraints_to_slots(slots_in_window, locked_allocations)

    decision_trace = DecisionTraceCollector(start_timestamp=datetime.now(timezone.utc))
    allocation_result = allocate_plan(
        slots=constrained_slots,
        subjects=subjects,
        workload_by_subject=workload_by_subject,
        session_minutes=int(global_config.get("session_duration_minutes", 30)),
        distribution_config={
            "human_distribution_mode": global_config.get("human_distribution_mode", "off"),
            "max_same_subject_streak_days": global_config.get("max_same_subject_streak_days", 3),
            "max_same_subject_streak_days_target": global_config.get("max_same_subject_streak_days_target", 2),
            "max_same_subject_consecutive_blocks": global_config.get("max_same_subject_consecutive_blocks", 3),
            "target_daily_subject_variety": global_config.get("target_daily_subject_variety", 2),
            "human_distribution_strength": global_config.get("human_distribution_strength", 0.3),
        },
        config_by_subject=config_by_subject,
        subject_concentration_mode_by_subject=subject_concentration_mode_by_subject,
        decision_trace=decision_trace,
    )

    new_horizon = rebalance_allocations(
        allocations=allocation_result["allocations"],
        slots=constrained_slots,
        subjects=subjects,
        global_config=global_config if isinstance(global_config, dict) else {},
        config_by_subject=config_by_subject,
        decision_trace=decision_trace,
        past_cutoff=window.from_date,
    )
    metrics = compute_reallocation_metrics(previous_horizon, new_horizon)
    humanity_metrics = compute_humanity_metrics(new_horizon)
    warnings, suggestions = build_warnings_and_suggestions(
        subjects=subjects,
        manual_sessions=manual_sessions,
        slots_in_window=constrained_slots,
        allocations=new_horizon,
        workload_by_subject=workload_by_subject,
        remaining_base_minutes=allocation_result["remaining_base_minutes"],
        remaining_buffer_minutes=allocation_result["remaining_buffer_minutes"],
        humanity_score=humanity_metrics["humanity_score"],
        humanity_threshold=float(global_config.get("humanity_warning_threshold", 0.45) or 0.45),
    )
    warnings.extend(build_critical_warnings(manual_sessions=manual_sessions, slots_in_window=constrained_slots))

    final_plan = [*preserved_previous, *locked_allocations, *new_horizon]

    daily_plan_map: dict[str, list[dict[str, Any]]] = {}
    for item in final_plan:
        day = str(item.get("date", ""))
        daily_plan_map.setdefault(day, []).append(item)
    daily_plan = [
        {"date": day, "allocations": sorted(items, key=lambda x: str(x.get("slot_id", "")))}
        for day, items in sorted(daily_plan_map.items(), key=lambda entry: entry[0])
    ]

    total_planned_minutes = sum(int(item.get("minutes", 0) or 0) for item in final_plan if item.get("subject_id") != "__slack__")
    humanity_tip = ""
    humanity_threshold = float(global_config.get("humanity_warning_threshold", 0.45) or 0.45)
    if humanity_metrics["humanity_score"] < humanity_threshold:
        humanity_tip = "Anticipa 1-2 blocchi di materia secondaria nei giorni più concentrati."

    return {
        "status": "ok",
        "plan": final_plan,
        "daily_plan": daily_plan,
        "plan_summary": {
            "subjects_count": len(subjects),
            "total_planned_minutes": total_planned_minutes,
            "horizon_start": horizon_start.isoformat(),
            "horizon_end": horizon_end.isoformat(),
            "humanity_score": round(float(humanity_metrics["humanity_score"]), 4),
            "humanity_tip": humanity_tip,
        },
        "warnings": warnings,
        "suggestions": suggestions,
        "effective_done_minutes": effective_done_minutes,
        "remaining_minutes": remaining_minutes,
        "reallocated_ratio": metrics["reallocated_ratio"],
        "stability_score": metrics["stability_score"],
        "effective_config": payload.get("effective_config", {}),
        "slots_in_window": constrained_slots,
        "subjects": subjects,
        "remaining_base_minutes": allocation_result["remaining_base_minutes"],
        "remaining_buffer_minutes": allocation_result["remaining_buffer_minutes"],
        "workload_by_subject": workload_by_subject,
        "decision_trace": decision_trace.as_list(),
    }
