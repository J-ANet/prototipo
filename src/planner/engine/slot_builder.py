"""Build deterministic daily capacity slots.

This module computes day-level capacities from:
- global cap/tolerance,
- sleep configuration,
- calendar constraints (blocked/cap_override).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from planner.normalization.config_resolver import resolve_sleep_hours

_WEEKDAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _to_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def _iter_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _applies_to_day(constraint: dict[str, Any], day: date) -> bool:
    day_str = day.isoformat()
    if constraint.get("date") == day_str:
        return True
    weekday = constraint.get("weekday")
    return isinstance(weekday, str) and weekday == _WEEKDAY_NAMES[day.weekday()]


def build_daily_slots(
    *,
    start_date: str | date,
    end_date: str | date,
    global_config: dict[str, Any],
    calendar_constraints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build day slots with cap, tolerance, sleep and constraints.

    Deterministic behaviour:
    - days are iterated in ascending date order,
    - constraints are pre-sorted by (constraint_id, type, date, weekday).
    """

    start = _to_date(start_date)
    end = _to_date(end_date)
    ordered_constraints = sorted(
        calendar_constraints,
        key=lambda c: (
            str(c.get("constraint_id", "")),
            str(c.get("type", "")),
            str(c.get("date", "")),
            str(c.get("weekday", "")),
        ),
    )

    base_cap = int(global_config.get("daily_cap_minutes", 0))
    base_tolerance = int(global_config.get("daily_cap_tolerance_minutes", 0))

    slots: list[dict[str, Any]] = []
    for day in _iter_days(start, end):
        sleep_hours = float(resolve_sleep_hours(global_config, day))
        awake_minutes = max(0, int(round((24 - sleep_hours) * 60)))

        cap_override_values: list[int] = []
        blocked_minutes = 0
        blocked_ids: list[str] = []

        for constraint in ordered_constraints:
            if not _applies_to_day(constraint, day):
                continue
            c_type = constraint.get("type")
            if c_type == "cap_override":
                cap_override_values.append(int(constraint.get("cap_override_minutes", 0)))
            elif c_type == "blocked":
                blocked_minutes += int(constraint.get("blocked_minutes", 0))
                blocked_ids.append(str(constraint.get("constraint_id", "")))

        cap_pre_sleep = min(cap_override_values) if cap_override_values else base_cap
        cap_with_sleep = max(0, min(cap_pre_sleep, awake_minutes))
        total_with_tolerance = max(0, min(cap_pre_sleep + base_tolerance, awake_minutes))

        effective_cap = max(0, cap_with_sleep - blocked_minutes)
        effective_total = max(0, total_with_tolerance - blocked_minutes)
        effective_tolerance = max(0, effective_total - effective_cap)

        slots.append(
            {
                "slot_id": f"slot-{day.isoformat()}",
                "date": day.isoformat(),
                "cap_minutes": effective_cap,
                "tolerance_minutes": effective_tolerance,
                "max_minutes": effective_cap + effective_tolerance,
                "sleep_hours": sleep_hours,
                "blocked_minutes": blocked_minutes,
                "blocked_constraints": blocked_ids,
                "cap_override_minutes": min(cap_override_values) if cap_override_values else None,
            }
        )

    return slots
