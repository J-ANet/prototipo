"""Post-allocation deterministic rebalancing swaps."""

from __future__ import annotations

from datetime import date
from typing import Any

from planner.metrics.collector import compute_humanity_metrics
from planner.reporting.decision_trace import DecisionTraceCollector


def _parse_date(raw: Any) -> date | None:
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _subject_deadline(subject: dict[str, Any]) -> date | None:
    candidates: list[date] = []
    for key in ("end_by", "selected_exam_date"):
        parsed = _parse_date(subject.get(key))
        if parsed is not None:
            candidates.append(parsed)
    exam_dates = subject.get("exam_dates", [])
    if isinstance(exam_dates, list):
        for value in exam_dates:
            parsed = _parse_date(value)
            if parsed is not None:
                candidates.append(parsed)
    if not candidates:
        return None
    return min(candidates)


def _is_locked_or_past(allocation: dict[str, Any], *, past_cutoff: date | None) -> bool:
    bucket = str(allocation.get("bucket", ""))
    slot_id = str(allocation.get("slot_id", ""))
    alloc_day = _parse_date(allocation.get("date"))
    if bucket == "manual_locked" or slot_id.startswith("manual-"):
        return True
    if bool(allocation.get("locked_by_user", False) or allocation.get("pinned", False)):
        return True
    if past_cutoff is not None and alloc_day is not None and alloc_day < past_cutoff:
        return True
    return False


def _daily_subject_count(allocations: list[dict[str, Any]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for item in allocations:
        sid = str(item.get("subject_id", ""))
        if sid == "__slack__":
            continue
        day = str(item.get("date", ""))
        out.setdefault(day, set()).add(sid)
    return out


def _constraint_violations(
    allocations: list[dict[str, Any]],
    *,
    max_subjects_per_day: int,
    subject_deadline: dict[str, date | None],
) -> int:
    violations = 0
    day_subjects = _daily_subject_count(allocations)
    for subjects in day_subjects.values():
        if len(subjects) > max_subjects_per_day:
            violations += 1

    for item in allocations:
        sid = str(item.get("subject_id", ""))
        if sid == "__slack__":
            continue
        alloc_day = _parse_date(item.get("date"))
        deadline = subject_deadline.get(sid)
        if alloc_day is not None and deadline is not None and alloc_day > deadline:
            violations += 1
    return violations


def _delta_humanity(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> float:
    before_metrics = compute_humanity_metrics(before)
    after_metrics = compute_humanity_metrics(after)
    before_score = 0.5 * (
        float(before_metrics.get("daily_monotony_score", 0.0)) + float(before_metrics.get("streak_burden_score", 0.0))
    )
    after_score = 0.5 * (
        float(after_metrics.get("daily_monotony_score", 0.0)) + float(after_metrics.get("streak_burden_score", 0.0))
    )
    return after_score - before_score


def rebalance_allocations(
    *,
    allocations: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    subjects: list[dict[str, Any]],
    global_config: dict[str, Any],
    config_by_subject: dict[str, dict[str, Any]] | None = None,
    decision_trace: DecisionTraceCollector | None = None,
    past_cutoff: date | None = None,
    max_swaps: int = 100,
    near_days_window: int = 2,
    feasibility_regression_tolerance: int = 0,
) -> list[dict[str, Any]]:
    """Apply deterministic local swaps improving humanity without feasibility regressions."""

    del slots, config_by_subject  # reserved for future constraints extension

    working = [dict(item) for item in allocations]
    if len(working) < 2:
        return working

    subject_deadline = {str(subject.get("subject_id", "")): _subject_deadline(subject) for subject in subjects}
    max_subjects_per_day = int(global_config.get("max_subjects_per_day", 3) or 3)

    accepted = 0
    while accepted < max_swaps:
        current_violations = _constraint_violations(
            working,
            max_subjects_per_day=max_subjects_per_day,
            subject_deadline=subject_deadline,
        )

        candidates: list[tuple[tuple[str, str, str, str, str, str], int, int]] = []
        for idx_a, alloc_a in enumerate(working):
            sid_a = str(alloc_a.get("subject_id", ""))
            if sid_a in {"", "__slack__"}:
                continue
            if _is_locked_or_past(alloc_a, past_cutoff=past_cutoff):
                continue
            date_a = _parse_date(alloc_a.get("date"))
            if date_a is None:
                continue
            minutes_a = int(alloc_a.get("minutes", 0) or 0)
            if minutes_a <= 0:
                continue

            for idx_b in range(idx_a + 1, len(working)):
                alloc_b = working[idx_b]
                sid_b = str(alloc_b.get("subject_id", ""))
                if sid_b in {"", "__slack__"} or sid_b == sid_a:
                    continue
                if _is_locked_or_past(alloc_b, past_cutoff=past_cutoff):
                    continue
                date_b = _parse_date(alloc_b.get("date"))
                if date_b is None:
                    continue
                if abs((date_a - date_b).days) > near_days_window:
                    continue
                minutes_b = int(alloc_b.get("minutes", 0) or 0)
                if minutes_a != minutes_b or minutes_b <= 0:
                    continue

                key = (
                    str(alloc_a.get("date", "")),
                    str(alloc_a.get("subject_id", "")),
                    str(alloc_a.get("slot_id", "")),
                    str(alloc_b.get("date", "")),
                    str(alloc_b.get("subject_id", "")),
                    str(alloc_b.get("slot_id", "")),
                )
                candidates.append((key, idx_a, idx_b))

        if not candidates:
            break

        improved = False
        for _, idx_a, idx_b in sorted(candidates, key=lambda item: item[0]):
            base = working
            proposal = [dict(item) for item in base]
            sid_a = str(proposal[idx_a].get("subject_id", ""))
            sid_b = str(proposal[idx_b].get("subject_id", ""))
            proposal[idx_a]["subject_id"] = sid_b
            proposal[idx_b]["subject_id"] = sid_a

            delta_humanity = _delta_humanity(base, proposal)
            if delta_humanity <= 0:
                continue

            proposed_violations = _constraint_violations(
                proposal,
                max_subjects_per_day=max_subjects_per_day,
                subject_deadline=subject_deadline,
            )
            if proposed_violations - current_violations > feasibility_regression_tolerance:
                continue

            working = proposal
            accepted += 1
            improved = True
            if decision_trace is not None:
                decision_trace.record(
                    slot_id=f"{working[idx_a].get('slot_id', '')}|{working[idx_b].get('slot_id', '')}",
                    candidate_subjects=[sid_a, sid_b],
                    scores_by_subject={sid_a: 0.0, sid_b: 0.0},
                    selected_subject_id=f"swap:{sid_a}<->{sid_b}",
                    applied_rules=["RULE_REBALANCE_SWAP"],
                    blocked_constraints=[],
                    tradeoff_note=(
                        f"Swap accettato: {sid_a}↔{sid_b}; delta_humanity={delta_humanity:.4f}; "
                        f"feasibility_delta={proposed_violations - current_violations}."
                    ),
                    confidence_impact=0.003,
                )
            break

        if not improved:
            break

    return sorted(working, key=lambda item: (str(item.get("date", "")), str(item.get("slot_id", "")), str(item.get("subject_id", ""))))
