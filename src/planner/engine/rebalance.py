"""Post-allocation deterministic rebalancing swaps."""

from __future__ import annotations

from datetime import date
from typing import Any

from planner.metrics.collector import compute_humanity_metrics


RULE_REBALANCE_SWAP = "RULE_REBALANCE_SWAP"


def _parse_date(raw: Any) -> date | None:
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _extract_subject_windows(workload: list[dict[str, Any]]) -> dict[str, tuple[date | None, date | None]]:
    windows: dict[str, tuple[date | None, date | None]] = {}
    for subject in workload:
        sid = str(subject.get("subject_id", ""))
        if not sid:
            continue
        start_at = _parse_date(subject.get("start_at"))
        end_candidates: list[date] = []
        for key in ("end_by", "selected_exam_date"):
            parsed = _parse_date(subject.get(key))
            if parsed is not None:
                end_candidates.append(parsed)
        exam_dates = subject.get("exam_dates", [])
        if isinstance(exam_dates, list):
            for raw in exam_dates:
                parsed = _parse_date(raw)
                if parsed is not None:
                    end_candidates.append(parsed)
        windows[sid] = (start_at, min(end_candidates) if end_candidates else None)
    return windows


def _is_locked_manual_or_past(
    allocation: dict[str, Any],
    *,
    locked_slot_ids: set[str],
    locked_dates: set[str],
    from_date: date | None,
) -> bool:
    slot_id = str(allocation.get("slot_id", ""))
    alloc_date = str(allocation.get("date", ""))
    bucket = str(allocation.get("bucket", ""))

    if slot_id in locked_slot_ids or alloc_date in locked_dates:
        return True
    if bucket == "manual_locked" or slot_id.startswith("manual-"):
        return True
    if bool(allocation.get("locked_by_user", False) or allocation.get("pinned", False)):
        return True

    parsed_date = _parse_date(alloc_date)
    if from_date is not None and parsed_date is not None and parsed_date < from_date:
        return True
    return False


def _compute_hard_violations(
    allocations: list[dict[str, Any]],
    *,
    slots: list[dict[str, Any]],
    subject_windows: dict[str, tuple[date | None, date | None]],
) -> int:
    violations = 0

    allowed_by_day: dict[str, int] = {}
    for slot in slots:
        day = str(slot.get("date", ""))
        if not day:
            continue
        cap = max(0, int(slot.get("cap_minutes", 0) or 0))
        tol = max(0, int(slot.get("tolerance_minutes", 0) or 0))
        allowed_by_day[day] = allowed_by_day.get(day, 0) + cap + tol

    used_by_day: dict[str, int] = {}
    for alloc in allocations:
        sid = str(alloc.get("subject_id", ""))
        if sid == "__slack__":
            continue
        day = str(alloc.get("date", ""))
        used_by_day[day] = used_by_day.get(day, 0) + max(0, int(alloc.get("minutes", 0) or 0))

        alloc_day = _parse_date(day)
        start_at, end_by = subject_windows.get(sid, (None, None))
        if alloc_day is not None and start_at is not None and alloc_day < start_at:
            violations += 1
        if alloc_day is not None and end_by is not None and alloc_day > end_by:
            violations += 1

    for day, used in used_by_day.items():
        if used > allowed_by_day.get(day, 0):
            violations += 1

    per_subject = sorted(
        [a for a in allocations if str(a.get("subject_id", "")) not in {"", "__slack__"}],
        key=lambda x: (str(x.get("subject_id", "")), str(x.get("date", "")), str(x.get("slot_id", ""))),
    )
    seen_buffer: set[str] = set()
    for alloc in per_subject:
        sid = str(alloc.get("subject_id", ""))
        bucket = str(alloc.get("bucket", ""))
        if bucket == "buffer":
            seen_buffer.add(sid)
        if bucket == "base" and sid in seen_buffer:
            violations += 1

    return violations


def _humanity_improved(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> bool:
    before_m = compute_humanity_metrics(before)
    after_m = compute_humanity_metrics(after)
    mono_improved = float(after_m.get("mono_day_ratio", 1.0)) < float(before_m.get("mono_day_ratio", 1.0))
    streak_improved = float(after_m.get("max_same_subject_streak_days", 10**9)) < float(
        before_m.get("max_same_subject_streak_days", 10**9)
    )
    return mono_improved or streak_improved


def rebalance_plan(
    allocations: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    workload: list[dict[str, Any]],
    config: dict[str, Any],
    locked_allocations: list[dict[str, Any]],
    replan_window: Any,
) -> dict[str, Any]:
    """Deterministic local-swap rebalancing with feasibility preservation."""
    working = [dict(item) for item in allocations]
    if len(working) < 2:
        return {"allocations": working, "swaps": []}

    allow_fragmentation = bool(config.get("allow_session_fragmentation", False))
    max_swaps = int(config.get("rebalance_max_swaps", 100) or 100)
    near_days_window = int(config.get("rebalance_near_days_window", 2) or 2)

    locked_slot_ids = {str(item.get("slot_id", "")) for item in locked_allocations}
    locked_dates = {str(item.get("date", "")) for item in locked_allocations if str(item.get("slot_id", "")).startswith("manual-")}
    from_date = getattr(replan_window, "from_date", None)
    subject_windows = _extract_subject_windows(workload)

    accepted_swaps: list[dict[str, Any]] = []
    accepted = 0
    while accepted < max_swaps:
        base_violations = _compute_hard_violations(working, slots=slots, subject_windows=subject_windows)

        candidates: list[tuple[tuple[str, str, str, str, str, str], int, int]] = []
        for idx_a, alloc_a in enumerate(working):
            sid_a = str(alloc_a.get("subject_id", ""))
            if sid_a in {"", "__slack__"}:
                continue
            if _is_locked_manual_or_past(
                alloc_a,
                locked_slot_ids=locked_slot_ids,
                locked_dates=locked_dates,
                from_date=from_date,
            ):
                continue
            day_a = _parse_date(alloc_a.get("date"))
            if day_a is None:
                continue
            minutes_a = max(0, int(alloc_a.get("minutes", 0) or 0))
            if minutes_a <= 0:
                continue

            for idx_b in range(idx_a + 1, len(working)):
                alloc_b = working[idx_b]
                sid_b = str(alloc_b.get("subject_id", ""))
                if sid_b in {"", "__slack__"} or sid_b == sid_a:
                    continue
                if _is_locked_manual_or_past(
                    alloc_b,
                    locked_slot_ids=locked_slot_ids,
                    locked_dates=locked_dates,
                    from_date=from_date,
                ):
                    continue
                day_b = _parse_date(alloc_b.get("date"))
                if day_b is None:
                    continue
                if abs((day_a - day_b).days) > near_days_window:
                    continue
                minutes_b = max(0, int(alloc_b.get("minutes", 0) or 0))
                if minutes_b <= 0:
                    continue
                if not allow_fragmentation and minutes_a != minutes_b:
                    continue
                if str(alloc_a.get("bucket", "")) != str(alloc_b.get("bucket", "")):
                    continue

                key = (
                    str(alloc_a.get("date", "")),
                    sid_a,
                    str(alloc_a.get("slot_id", "")),
                    str(alloc_b.get("date", "")),
                    sid_b,
                    str(alloc_b.get("slot_id", "")),
                )
                candidates.append((key, idx_a, idx_b))

        if not candidates:
            break

        improved = False
        for _, idx_a, idx_b in sorted(candidates, key=lambda x: x[0]):
            proposal = [dict(item) for item in working]
            sid_a = str(proposal[idx_a].get("subject_id", ""))
            sid_b = str(proposal[idx_b].get("subject_id", ""))
            proposal[idx_a]["subject_id"] = sid_b
            proposal[idx_b]["subject_id"] = sid_a

            proposed_violations = _compute_hard_violations(proposal, slots=slots, subject_windows=subject_windows)
            if proposed_violations > base_violations:
                continue
            if not _humanity_improved(working, proposal):
                continue

            working = proposal
            accepted += 1
            improved = True
            accepted_swaps.append(
                {
                    "slot_a": str(working[idx_a].get("slot_id", "")),
                    "slot_b": str(working[idx_b].get("slot_id", "")),
                    "subject_a": sid_a,
                    "subject_b": sid_b,
                }
            )
            break

        if not improved:
            break

    return {
        "allocations": sorted(
            working,
            key=lambda item: (str(item.get("date", "")), str(item.get("slot_id", "")), str(item.get("subject_id", ""))),
        ),
        "swaps": accepted_swaps,
    }


def rebalance_allocations(
    *,
    allocations: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    subjects: list[dict[str, Any]],
    global_config: dict[str, Any],
    config_by_subject: dict[str, dict[str, Any]] | None = None,
    decision_trace: Any | None = None,
    past_cutoff: date | None = None,
    max_swaps: int = 100,
    near_days_window: int = 2,
    feasibility_regression_tolerance: int = 0,
) -> list[dict[str, Any]]:
    """Backward-compatible wrapper around rebalance_plan."""
    del config_by_subject, feasibility_regression_tolerance
    payload = rebalance_plan(
        allocations=allocations,
        slots=slots,
        workload=subjects,
        config={**global_config, "rebalance_max_swaps": max_swaps, "rebalance_near_days_window": near_days_window},
        locked_allocations=[],
        replan_window=type("Window", (), {"from_date": past_cutoff})(),
    )
    if decision_trace is not None:
        for swap in payload["swaps"]:
            decision_trace.record(
                slot_id=f"{swap['slot_a']}|{swap['slot_b']}",
                candidate_subjects=[swap["subject_a"], swap["subject_b"]],
                scores_by_subject={swap["subject_a"]: 0.0, swap["subject_b"]: 0.0},
                selected_subject_id=f"swap:{swap['subject_a']}<->{swap['subject_b']}",
                applied_rules=[RULE_REBALANCE_SWAP],
                blocked_constraints=[],
                tradeoff_note="Swap rebalancing accettato.",
                confidence_impact=0.003,
            )
    return payload["allocations"]
