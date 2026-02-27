"""Post-allocation deterministic rebalancing swaps."""

from __future__ import annotations

from collections import defaultdict
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


def _subject_windows(subjects: list[dict[str, Any]]) -> dict[str, dict[str, date | None]]:
    windows: dict[str, dict[str, date | None]] = {}
    for subject in subjects:
        sid = str(subject.get("subject_id", ""))
        if not sid:
            continue
        exams: list[date] = []
        selected = _parse_date(subject.get("selected_exam_date"))
        if selected is not None:
            exams.append(selected)
        for raw in subject.get("exam_dates", []) if isinstance(subject.get("exam_dates"), list) else []:
            parsed = _parse_date(raw)
            if parsed is not None:
                exams.append(parsed)

        end_by = _parse_date(subject.get("end_by"))
        exam_date = min(exams) if exams else None
        windows[sid] = {
            "start_at": _parse_date(subject.get("start_at")),
            "end_by": min([d for d in [end_by, exam_date] if d is not None], default=None),
            "exam_date": exam_date,
        }
    return windows


def _is_immutable(
    allocation: dict[str, Any],
    *,
    locked_slot_ids: set[str],
    locked_dates: set[str],
    past_cutoff: date | None,
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
    parsed = _parse_date(alloc_date)
    return past_cutoff is not None and parsed is not None and parsed < past_cutoff


def _allowed_by_day(slots: list[dict[str, Any]]) -> dict[str, int]:
    allowed: dict[str, int] = defaultdict(int)
    for slot in slots:
        day = str(slot.get("date", ""))
        if not day:
            continue
        cap = max(0, int(slot.get("cap_minutes", 0) or 0))
        tol = max(0, int(slot.get("tolerance_minutes", 0) or 0))
        allowed[day] += cap + tol
    return dict(allowed)


def _feasibility_score(
    allocations: list[dict[str, Any]],
    *,
    allowed_minutes_by_day: dict[str, int],
    subject_windows: dict[str, dict[str, date | None]],
) -> float:
    violations = 0
    used_by_day: dict[str, int] = defaultdict(int)

    for alloc in allocations:
        sid = str(alloc.get("subject_id", ""))
        if sid in {"", "__slack__"}:
            continue
        day_str = str(alloc.get("date", ""))
        used_by_day[day_str] += max(0, int(alloc.get("minutes", 0) or 0))
        alloc_day = _parse_date(day_str)
        window = subject_windows.get(sid, {})
        start_at = window.get("start_at")
        end_by = window.get("end_by")
        exam_date = window.get("exam_date")
        if alloc_day is not None and start_at is not None and alloc_day < start_at:
            violations += 1
        if alloc_day is not None and end_by is not None and alloc_day > end_by:
            violations += 1
        if alloc_day is not None and exam_date is not None and alloc_day > exam_date:
            violations += 1

    for day, used in used_by_day.items():
        if used > allowed_minutes_by_day.get(day, 0):
            violations += 1

    return 1.0 / (1.0 + float(violations))


def _respects_max_subjects_per_day(allocations: list[dict[str, Any]], max_subjects_per_day: int) -> bool:
    per_day_subjects: dict[str, set[str]] = defaultdict(set)
    for alloc in allocations:
        sid = str(alloc.get("subject_id", ""))
        if sid in {"", "__slack__"}:
            continue
        per_day_subjects[str(alloc.get("date", ""))].add(sid)
    return all(len(subjects) <= max_subjects_per_day for subjects in per_day_subjects.values())


def _humanity_vector(allocations: list[dict[str, Any]]) -> dict[str, float]:
    metrics = compute_humanity_metrics(allocations)
    return {
        "mono_day_ratio": float(metrics.get("mono_day_ratio", 1.0)),
        "streak_days": float(metrics.get("max_same_subject_streak_days", 10**9)),
        "subject_variety": float(metrics.get("subject_variety_index", 0.0)),
    }


def _humanity_improves(before: dict[str, float], after: dict[str, float]) -> tuple[bool, str]:
    improvements: list[str] = []
    if after["mono_day_ratio"] < before["mono_day_ratio"]:
        improvements.append("mono_day_ratio")
    if after["streak_days"] < before["streak_days"]:
        improvements.append("streak_days")
    if after["subject_variety"] > before["subject_variety"]:
        improvements.append("subject_variety")
    return (len(improvements) > 0, ", ".join(improvements))




def _strategy_mode_by_subject(
    subjects: list[dict[str, Any]],
    global_config: dict[str, Any],
    config_by_subject: dict[str, dict[str, Any]] | None,
) -> dict[str, str]:
    default_mode = str(global_config.get("default_strategy_mode", "hybrid")).lower()
    cfg = config_by_subject if isinstance(config_by_subject, dict) else {}
    modes: dict[str, str] = {}
    for subject in subjects:
        sid = str(subject.get("subject_id", ""))
        if not sid:
            continue
        subject_cfg = cfg.get(sid, {})
        if not isinstance(subject_cfg, dict):
            subject_cfg = {}
        modes[sid] = str(subject_cfg.get("strategy_mode", default_mode)).lower()
    return modes

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
    feasibility_regression_tolerance: float = 0.0,
    locked_allocations: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Rebalance using deterministic compatible swaps preserving feasibility."""
    working = [dict(item) for item in allocations]
    if len(working) < 2:
        return working

    max_subjects_per_day = max(1, int(global_config.get("max_subjects_per_day", 10**9) or 10**9))
    configured_max_swaps = int(global_config.get("rebalance_max_swaps", max_swaps) or max_swaps)
    configured_max_iterations = int(global_config.get("rebalance_max_iterations", configured_max_swaps) or configured_max_swaps)
    max_swaps = max(0, min(max_swaps, configured_max_swaps))
    max_iterations = max(0, configured_max_iterations)
    near_days_window = max(0, int(global_config.get("rebalance_near_days_window", near_days_window) or near_days_window))

    locked = locked_allocations if isinstance(locked_allocations, list) else []
    locked_slot_ids = {str(item.get("slot_id", "")) for item in locked}
    locked_dates = {str(item.get("date", "")) for item in locked if str(item.get("slot_id", "")).startswith("manual-")}
    windows = _subject_windows(subjects)
    allowed = _allowed_by_day(slots)
    strategy_modes = _strategy_mode_by_subject(subjects, global_config, config_by_subject)

    accepted = 0
    iterations = 0
    while accepted < max_swaps and iterations < max_iterations:
        iterations += 1
        base_feasibility = _feasibility_score(working, allowed_minutes_by_day=allowed, subject_windows=windows)
        before_h = _humanity_vector(working)

        candidates: list[tuple[tuple[str, str, str, str, str, str], int, int]] = []
        for idx_a, alloc_a in enumerate(working):
            sid_a = str(alloc_a.get("subject_id", ""))
            if sid_a in {"", "__slack__"}:
                continue
            if _is_immutable(alloc_a, locked_slot_ids=locked_slot_ids, locked_dates=locked_dates, past_cutoff=past_cutoff):
                continue
            day_a = _parse_date(alloc_a.get("date"))
            if day_a is None:
                continue
            for idx_b in range(idx_a + 1, len(working)):
                alloc_b = working[idx_b]
                sid_b = str(alloc_b.get("subject_id", ""))
                if sid_b in {"", "__slack__"} or sid_a == sid_b:
                    continue
                if strategy_modes.get(sid_a, "hybrid") != strategy_modes.get(sid_b, "hybrid"):
                    continue
                if _is_immutable(alloc_b, locked_slot_ids=locked_slot_ids, locked_dates=locked_dates, past_cutoff=past_cutoff):
                    continue
                day_b = _parse_date(alloc_b.get("date"))
                if day_b is None or abs((day_a - day_b).days) > near_days_window:
                    continue
                if str(alloc_a.get("bucket", "")) != str(alloc_b.get("bucket", "")):
                    continue

                # Respect time windows and exam proximity after the swap.
                a_on_b = windows.get(sid_a, {})
                b_on_a = windows.get(sid_b, {})
                if a_on_b.get("start_at") is not None and day_b < a_on_b["start_at"]:
                    continue
                if a_on_b.get("end_by") is not None and day_b > a_on_b["end_by"]:
                    continue
                if a_on_b.get("exam_date") is not None and day_b > a_on_b["exam_date"]:
                    continue
                if b_on_a.get("start_at") is not None and day_a < b_on_a["start_at"]:
                    continue
                if b_on_a.get("end_by") is not None and day_a > b_on_a["end_by"]:
                    continue
                if b_on_a.get("exam_date") is not None and day_a > b_on_a["exam_date"]:
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
            subject_a = str(proposal[idx_a].get("subject_id", ""))
            subject_b = str(proposal[idx_b].get("subject_id", ""))
            proposal[idx_a]["subject_id"] = subject_b
            proposal[idx_b]["subject_id"] = subject_a

            if not _respects_max_subjects_per_day(proposal, max_subjects_per_day=max_subjects_per_day):
                continue

            proposal_feasibility = _feasibility_score(proposal, allowed_minutes_by_day=allowed, subject_windows=windows)
            if proposal_feasibility + feasibility_regression_tolerance < base_feasibility:
                continue

            after_h = _humanity_vector(proposal)
            improves, improved_metrics = _humanity_improves(before_h, after_h)
            if not improves:
                continue

            working = proposal
            accepted += 1
            improved = True
            if decision_trace is not None:
                decision_trace.record(
                    slot_id=f"{working[idx_a].get('slot_id', '')}|{working[idx_b].get('slot_id', '')}",
                    candidate_subjects=[subject_a, subject_b],
                    scores_by_subject={subject_a: 0.0, subject_b: 0.0},
                    selected_subject_id=f"swap:{subject_a}<->{subject_b}",
                    applied_rules=[RULE_REBALANCE_SWAP],
                    blocked_constraints=[],
                    tradeoff_note=(
                        f"Swap accepted: improves {improved_metrics}; "
                        f"feasibility {base_feasibility:.3f}->{proposal_feasibility:.3f}."
                    ),
                    confidence_impact=0.002 if proposal_feasibility == base_feasibility else 0.003,
                )
            break

        if not improved:
            break

    return sorted(
        working,
        key=lambda item: (str(item.get("date", "")), str(item.get("slot_id", "")), str(item.get("subject_id", ""))),
    )
