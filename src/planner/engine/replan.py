"""Utilities for constrained replanning and stability metrics."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class ReplanWindow:
    from_date: date | None


def read_replan_window(payload: dict[str, Any]) -> ReplanWindow:
    """Read replan_context.from_date if available."""
    plan_request = payload.get("plan_request", {}) if isinstance(payload, dict) else {}
    replan_context = plan_request.get("replan_context", {}) if isinstance(plan_request, dict) else {}
    raw = replan_context.get("from_date") if isinstance(replan_context, dict) else None
    if isinstance(raw, str):
        try:
            return ReplanWindow(from_date=date.fromisoformat(raw))
        except ValueError:
            return ReplanWindow(from_date=None)
    return ReplanWindow(from_date=None)


def split_previous_plan(previous_allocations: list[dict[str, Any]], from_date: date | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split previous plan in preserved (< from_date) and replannable (>= from_date)."""
    if from_date is None:
        return [], previous_allocations

    preserved: list[dict[str, Any]] = []
    replannable: list[dict[str, Any]] = []
    for item in previous_allocations:
        raw = item.get("date")
        if not isinstance(raw, str):
            replannable.append(item)
            continue
        try:
            day = date.fromisoformat(raw)
        except ValueError:
            replannable.append(item)
            continue

        if day < from_date:
            preserved.append(item)
        else:
            replannable.append(item)

    return preserved, replannable


def compute_manual_progress(manual_sessions: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Compute effective_done_minutes and related status counters by subject."""
    result: dict[str, dict[str, int]] = defaultdict(lambda: {
        "effective_done_minutes": 0,
        "planned_minutes": 0,
        "skipped_minutes": 0,
        "skipped_sessions": 0,
    })

    for session in manual_sessions:
        sid = str(session.get("subject_id", ""))
        if not sid:
            continue
        planned = int(session.get("planned_minutes", 0) or 0)
        actual = int(session.get("actual_minutes_done", 0) or 0)
        status = session.get("status")

        if status == "done":
            done = max(planned, actual)
        elif status == "partial":
            done = min(planned, max(0, actual))
        else:
            done = 0

        result[sid]["effective_done_minutes"] += done
        result[sid]["planned_minutes"] += max(0, planned)
        if status == "skipped":
            result[sid]["skipped_minutes"] += max(0, planned)
            result[sid]["skipped_sessions"] += 1

    return dict(result)


def extract_locked_manual_allocations(manual_sessions: list[dict[str, Any]], from_date: date | None) -> list[dict[str, Any]]:
    """Return manual sessions that act as non-reallocable constraints."""
    locked: list[dict[str, Any]] = []
    for idx, session in enumerate(manual_sessions):
        status = session.get("status")
        if status == "skipped":
            continue
        is_locked = bool(session.get("locked_by_user", False) or session.get("pinned", False))
        if not is_locked:
            continue

        raw_date = session.get("date")
        if not isinstance(raw_date, str):
            continue
        try:
            day = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if from_date is not None and day < from_date:
            continue

        locked.append(
            {
                "slot_id": f"manual-{raw_date}",
                "date": raw_date,
                "subject_id": str(session.get("subject_id", "")),
                "minutes": int(session.get("planned_minutes", 0) or 0),
                "bucket": "manual_locked",
                "manual_session_id": session.get("session_id") or f"manual-{idx}",
            }
        )

    return locked


def apply_locked_constraints_to_slots(slots: list[dict[str, Any]], locked_allocations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce slot capacities with locked manual allocations."""
    locked_by_date: dict[str, int] = defaultdict(int)
    for alloc in locked_allocations:
        locked_by_date[str(alloc.get("date", ""))] += int(alloc.get("minutes", 0) or 0)

    out: list[dict[str, Any]] = []
    for slot in slots:
        date_key = str(slot.get("date", ""))
        locked_minutes = max(0, locked_by_date.get(date_key, 0))
        max_minutes = max(0, int(slot.get("max_minutes", 0)) - locked_minutes)
        cap_minutes = min(max_minutes, int(slot.get("cap_minutes", 0)))
        tolerance_minutes = max(0, max_minutes - cap_minutes)
        out.append(
            {
                **slot,
                "cap_minutes": cap_minutes,
                "tolerance_minutes": tolerance_minutes,
                "max_minutes": max_minutes,
                "locked_minutes": locked_minutes,
            }
        )
    return out


def compute_reallocation_metrics(previous_horizon: list[dict[str, Any]], new_horizon: list[dict[str, Any]]) -> dict[str, float]:
    """Compare old/new horizon and compute reallocated_ratio + stability_score."""

    def _key(item: dict[str, Any]) -> tuple[str, str, int]:
        return (
            str(item.get("date", "")),
            str(item.get("subject_id", "")),
            int(item.get("minutes", 0) or 0),
        )

    old_counter = Counter(_key(item) for item in previous_horizon)
    new_counter = Counter(_key(item) for item in new_horizon)

    unchanged = sum((old_counter & new_counter).values())
    old_total = sum(old_counter.values())

    if old_total <= 0:
        return {"reallocated_ratio": 0.0, "stability_score": 1.0}

    reallocated_ratio = max(0.0, min(1.0, 1.0 - (unchanged / old_total)))
    return {
        "reallocated_ratio": reallocated_ratio,
        "stability_score": max(0.0, min(1.0, 1.0 - reallocated_ratio)),
    }


def build_critical_warnings(
    *,
    manual_sessions: list[dict[str, Any]],
    slots_in_window: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Emit critical warning for all-skipped + no new slot capacity scenario."""
    if not manual_sessions:
        return []

    statuses = [session.get("status") for session in manual_sessions if isinstance(session, dict)]
    only_skipped = bool(statuses) and all(status == "skipped" for status in statuses)
    has_new_capacity = any(int(slot.get("max_minutes", 0)) > 0 for slot in slots_in_window)

    if only_skipped and not has_new_capacity:
        return [
            {
                "code": "CRITICAL_ONLY_SKIPPED_AND_NO_NEW_SLOTS",
                "severity": "critical",
                "message": "Solo sessioni skipped e nessuno slot nuovo disponibile nel periodo di replan.",
            }
        ]
    return []
