"""Deterministic allocation pipeline.

Phases:
1) forward allocation,
2) pre-exam refinement,
3) gap filling.

Rule preserved: never allocate buffer for a subject while that same subject still has base minutes remaining.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from planner.reporting.decision_trace import DecisionTraceCollector

from .scoring import (
    DEFAULT_CONTINUITY_CONFIG,
    compute_recent_continuity_penalty,
    compute_score,
    deterministic_tie_breaker_key,
)


def _to_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def _subject_order(subjects: list[dict[str, Any]], day: str | date) -> list[dict[str, Any]]:
    return sorted(
        subjects,
        key=lambda s: deterministic_tie_breaker_key(s, reference_day=day),
    )


def _alloc_chunk(
    *,
    subject_id: str,
    slot: dict[str, Any],
    minutes: int,
    bucket: str,
    out: list[dict[str, Any]],
) -> None:
    if minutes <= 0:
        return
    out.append(
        {
            "slot_id": slot["slot_id"],
            "date": slot["date"],
            "subject_id": subject_id,
            "minutes": minutes,
            "bucket": bucket,
        }
    )




def _distribution_limits_for_mode(mode: str) -> dict[str, Any]:
    if mode == "strict":
        return {
            "penalty_multiplier": 2.0,
            "default_max_streak": 2,
            "default_max_same_day_blocks": 2,
            "min_variety": 3,
        }
    if mode == "balanced":
        return {
            "penalty_multiplier": 1.0,
            "default_max_streak": 3,
            "default_max_same_day_blocks": 3,
            "min_variety": 2,
        }
    return {
        "penalty_multiplier": 0.0,
        "default_max_streak": 10**6,
        "default_max_same_day_blocks": 10**6,
        "min_variety": 1,
    }


def _resolve_subject_distribution(
    subject_id: str,
    global_distribution: dict[str, Any],
    config_by_subject: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    merged = {**global_distribution, **(config_by_subject.get(subject_id, {}))}
    mode = str(merged.get("human_distribution_mode", "off")).lower()
    if mode not in {"off", "balanced", "strict"}:
        mode = "off"
    limits = _distribution_limits_for_mode(mode)
    max_streak = int(merged.get("max_same_subject_streak_days", limits["default_max_streak"]))
    max_same_day_blocks = int(
        merged.get("max_same_subject_consecutive_blocks", limits["default_max_same_day_blocks"])
    )
    target_variety = int(merged.get("target_daily_subject_variety", limits["min_variety"]))
    return {
        "mode": mode,
        "penalty_multiplier": float(limits["penalty_multiplier"]),
        "max_streak_days": max(1, max_streak),
        "max_same_day_blocks": max(1, max_same_day_blocks),
        "target_daily_subject_variety": max(1, target_variety),
    }


def _current_streak_days(subject_id: str, day: str | date, minutes_by_day: dict[date, dict[str, int]]) -> int:
    reference_day = _to_date(day)
    streak = 0
    cursor = reference_day
    while True:
        previous = cursor.fromordinal(cursor.toordinal() - 1)
        if minutes_by_day.get(previous, {}).get(subject_id, 0) > 0:
            streak += 1
            cursor = previous
            continue
        return streak


def _strategy_weight(subject_id: str, slot_date: str | date, exam_day: date, mode: str) -> float:
    """Return multiplicative weight from strategy mode and temporal distance to exam."""
    _ = subject_id
    day = _to_date(slot_date)
    days_to_exam = max(0, (exam_day - day).days)
    distance = float(days_to_exam)
    near_ratio = 1.0 / (1.0 + distance)
    far_ratio = distance / (distance + 2.0)

    normalized_mode = str(mode or "hybrid").lower()
    if normalized_mode == "forward":
        # More bonus when far from exam.
        return 1.0 + 0.40 * far_ratio
    if normalized_mode == "backward":
        # More bonus when close to exam.
        return 1.0 + 0.45 * near_ratio
    # Hybrid: mostly neutral, slight acceleration close to exam.
    return 1.0 + 0.15 * near_ratio


def _strategy_rule(mode: str) -> str:
    normalized_mode = str(mode or "hybrid").lower()
    if normalized_mode == "forward":
        return "RULE_STRATEGY_MODE_FORWARD"
    if normalized_mode == "backward":
        return "RULE_STRATEGY_MODE_BACKWARD"
    return "RULE_STRATEGY_MODE_HYBRID"



def _normalize_concentration_mode(raw_mode: Any, fallback: str = "diffuse") -> str:
    mode = str(raw_mode or "").lower()
    if mode in {"diffuse", "concentrated"}:
        return mode
    return fallback


def _concentration_multiplier(mode: str) -> float:
    if mode == "concentrated":
        return 1.03
    return 1.0


def _concentration_bias(mode: str) -> float:
    if mode == "concentrated":
        return 0.01
    return 0.0


def _concentration_adjusted_features(features: dict[str, float], mode: str) -> dict[str, float]:
    adjusted = dict(features)
    concentration_penalty = float(adjusted.get("concentration_penalty", 0.0))
    if mode == "concentrated":
        adjusted["concentration_penalty"] = concentration_penalty * 0.5
        return adjusted
    adjusted["concentration_penalty"] = concentration_penalty
    return adjusted


def allocate_plan(
    *,
    slots: list[dict[str, Any]],
    subjects: list[dict[str, Any]],
    workload_by_subject: dict[str, dict[str, Any]],
    session_minutes: int = 30,
    score_features_by_subject: dict[str, dict[str, float]] | None = None,
    continuity_config: dict[str, float | int | bool] | None = None,
    distribution_config: dict[str, Any] | None = None,
    config_by_subject: dict[str, dict[str, Any]] | None = None,
    concentration_mode_by_subject: dict[str, str] | None = None,
    global_concentration_mode: str = "diffuse",
    decision_trace: DecisionTraceCollector | None = None,
) -> dict[str, Any]:
    """Allocate minutes with deterministic iteration and tie-breaks."""

    ordered_slots = sorted(slots, key=lambda s: (str(s.get("date", "")), str(s.get("slot_id", ""))))
    ordered_subjects = sorted(subjects, key=lambda s: str(s.get("subject_id", "")))

    remaining_base: dict[str, int] = {}
    remaining_buffer: dict[str, int] = {}
    exam_day_by_subject: dict[str, date] = {}

    for subject in ordered_subjects:
        sid = str(subject["subject_id"])
        workload = workload_by_subject.get(sid, {})
        remaining_base[sid] = max(0, int(round(float(workload.get("hours_base", 0.0)) * 60)))
        remaining_buffer[sid] = max(0, int(round(float(workload.get("hours_buffer", 0.0)) * 60)))
        exams = sorted(subject.get("exam_dates", []))
        selected = subject.get("selected_exam_date")
        exam_value = selected if selected else (exams[0] if exams else "9999-12-31")
        exam_day_by_subject[sid] = _to_date(exam_value)

    allocations: list[dict[str, Any]] = []
    slack_by_slot: dict[str, int] = {}
    history_minutes_by_day: dict[date, dict[str, int]] = {}
    history_total_minutes_by_day: dict[date, int] = {}
    effective_continuity = (
        DEFAULT_CONTINUITY_CONFIG if continuity_config is None else {**DEFAULT_CONTINUITY_CONFIG, **continuity_config}
    )
    global_distribution = distribution_config or {}
    per_subject_distribution = {
        str(subject.get("subject_id", "")): _resolve_subject_distribution(
            str(subject.get("subject_id", "")),
            global_distribution,
            config_by_subject or {},
        )
        for subject in ordered_subjects
    }
    strategy_mode_by_subject = {
        str(subject.get("subject_id", "")): str(
            (config_by_subject or {}).get(str(subject.get("subject_id", "")), {}).get("strategy_mode", "hybrid")
        ).lower()
        for subject in ordered_subjects
    }
    normalized_global_concentration_mode = _normalize_concentration_mode(global_concentration_mode)
    per_subject_concentration_mode: dict[str, str] = {}
    concentration_mode_source: dict[str, str] = {}
    for subject in ordered_subjects:
        sid = str(subject.get("subject_id", ""))
        explicit_mode = (concentration_mode_by_subject or {}).get(sid)
        if explicit_mode is None:
            explicit_mode = (config_by_subject or {}).get(sid, {}).get("concentration_mode")
        if explicit_mode is None:
            per_subject_concentration_mode[sid] = normalized_global_concentration_mode
            concentration_mode_source[sid] = "global_fallback"
            continue
        per_subject_concentration_mode[sid] = _normalize_concentration_mode(
            explicit_mode,
            fallback=normalized_global_concentration_mode,
        )
        concentration_mode_source[sid] = "subject"
    day_subject_set: dict[date, set[str]] = defaultdict(set)
    day_last_subject: dict[date, str] = {}
    day_consecutive_blocks: dict[date, int] = defaultdict(int)

    def _register_history(day_value: str | date, sid: str, minutes: int) -> None:
        if sid == "__slack__" or minutes <= 0:
            return
        day = _to_date(day_value)
        day_history = history_minutes_by_day.setdefault(day, {})
        day_history[sid] = day_history.get(sid, 0) + minutes
        day_subject_set[day].add(sid)
        history_total_minutes_by_day[day] = history_total_minutes_by_day.get(day, 0) + minutes
        if day_last_subject.get(day) == sid:
            day_consecutive_blocks[day] += 1
        else:
            day_last_subject[day] = sid
            day_consecutive_blocks[day] = 1

    def _is_same_day_block_limit_exceeded(sid: str, day: date) -> bool:
        dist_cfg = per_subject_distribution.get(sid, _distribution_limits_for_mode("off"))
        if str(dist_cfg.get("mode", "off")) == "off":
            return False
        if day_last_subject.get(day) != sid:
            return False
        next_streak = day_consecutive_blocks.get(day, 0) + 1
        return next_streak > int(dist_cfg.get("max_same_day_blocks", 10**6))

    # Phase 1: forward assignment with score + deterministic tie-break.
    for slot in ordered_slots:
        available = int(slot.get("max_minutes", 0))
        day_subjects = _subject_order(ordered_subjects, slot["date"])

        while available >= session_minutes:
            candidates: list[tuple[float, tuple[int, int, str], dict[str, Any]]] = []
            concentration_influence_by_subject: dict[str, bool] = {}
            for subject in day_subjects:
                sid = str(subject["subject_id"])
                if remaining_base[sid] <= 0:
                    continue
                features = (score_features_by_subject or {}).get(sid, {})
                continuity_penalty = compute_recent_continuity_penalty(
                    subject_id=sid,
                    reference_day=slot["date"],
                    minutes_by_day=history_minutes_by_day,
                    total_minutes_by_day=history_total_minutes_by_day,
                    config=effective_continuity,
                )
                dist_cfg = per_subject_distribution.get(sid, _distribution_limits_for_mode("off"))
                mode = str(dist_cfg.get("mode", "off"))
                day = _to_date(slot["date"])
                streak_days = _current_streak_days(sid, day, history_minutes_by_day)
                if mode in {"balanced", "strict"} and streak_days >= int(dist_cfg.get("max_streak_days", 10**6)):
                    continue

                unique_subjects_today = day_subject_set.get(day, set())
                variety_missing = max(
                    0,
                    int(dist_cfg.get("target_daily_subject_variety", 1))
                    - len(unique_subjects_today | {sid}),
                )
                soft_penalty = float(dist_cfg.get("penalty_multiplier", 0.0)) * float(variety_missing) * 0.25
                concentration_mode = per_subject_concentration_mode.get(sid, normalized_global_concentration_mode)
                adjusted_features = _concentration_adjusted_features(features, concentration_mode)
                base_score = compute_score({**adjusted_features, "streak_penalty": continuity_penalty + soft_penalty})
                strategy_mode = strategy_mode_by_subject.get(sid, "hybrid")
                strategy_weight = _strategy_weight(
                    subject_id=sid,
                    slot_date=slot["date"],
                    exam_day=exam_day_by_subject[sid],
                    mode=strategy_mode,
                )
                # Keep Phase 1 mostly neutral for hybrid.
                if strategy_mode == "hybrid":
                    strategy_weight = 1.0 + (strategy_weight - 1.0) * 0.25
                concentration_multiplier = _concentration_multiplier(concentration_mode)
                score = (base_score + _concentration_bias(concentration_mode)) * strategy_weight * concentration_multiplier
                tie = deterministic_tie_breaker_key(subject, reference_day=slot["date"])
                candidates.append((score, tie, subject))
                concentration_influence_by_subject[sid] = concentration_mode_source.get(sid) == "subject"

            if not candidates:
                break

            candidates.sort(key=lambda item: (-item[0], item[1]))
            chosen = candidates[0][2]
            day = _to_date(slot["date"])
            forced_second_choice = False
            tradeoff_note = "Selezione con punteggio massimo e tie-break deterministico."

            if _is_same_day_block_limit_exceeded(str(chosen["subject_id"]), day):
                for candidate in candidates[1:]:
                    candidate_subject = candidate[2]
                    if not _is_same_day_block_limit_exceeded(str(candidate_subject["subject_id"]), day):
                        chosen = candidate_subject
                        forced_second_choice = True
                        tradeoff_note = (
                            "Limite blocchi consecutivi stessa materia superato: applicata seconda scelta valida."
                        )
                        break
                else:
                    tradeoff_note = (
                        "Eccezione limite blocchi consecutivi: nessuna alternativa valida senza violare hard constraints."
                    )

            sid = str(chosen["subject_id"])
            concentration_mode_impacted_choice = concentration_influence_by_subject.get(sid, False)
            if concentration_mode_impacted_choice:
                tradeoff_note = f"{tradeoff_note} Modalità concentrazione per-materia applicata alla valutazione candidati."
            chunk = min(session_minutes, available, remaining_base[sid])
            _alloc_chunk(subject_id=sid, slot=slot, minutes=chunk, bucket="base", out=allocations)
            if decision_trace is not None:
                applied_rules = ["RULE_BASE_BEFORE_BUFFER", "RULE_SCORE_ORDER", "RULE_TIE_BREAK_DETERMINISTIC"]
                applied_rules.append(_strategy_rule(strategy_mode_by_subject.get(sid, "hybrid")))
                if forced_second_choice:
                    applied_rules.append("RULE_LIMIT_CONSECUTIVE_BLOCKS")
                if concentration_mode_impacted_choice:
                    applied_rules.append("RULE_CONCENTRATION_MODE_PER_SUBJECT")
                decision_trace.record(
                    slot_id=str(slot["slot_id"]),
                    candidate_subjects=[str(item[2]["subject_id"]) for item in candidates],
                    scores_by_subject={str(item[2]["subject_id"]): float(item[0]) for item in candidates},
                    selected_subject_id=sid,
                    applied_rules=applied_rules,
                    blocked_constraints=[],
                    tradeoff_note=tradeoff_note,
                    confidence_impact=0.01,
                )
            remaining_base[sid] -= chunk
            available -= chunk
            _register_history(slot["date"], sid, chunk)

        slack_by_slot[slot["slot_id"]] = available

    # Phase 2: pre-exam refinement, prioritize nearest exam with completed base.
    for slot in ordered_slots:
        free_minutes = slack_by_slot.get(slot["slot_id"], 0)
        if free_minutes < session_minutes:
            continue
        day = _to_date(slot["date"])

        candidates: list[tuple[float, tuple[int, int, str], dict[str, Any]]] = []
        for subject in _subject_order(ordered_subjects, slot["date"]):
            sid = str(subject["subject_id"])
            if remaining_base[sid] > 0:  # never invert base -> buffer
                continue
            if remaining_buffer[sid] <= 0:
                continue
            if day > exam_day_by_subject[sid]:
                continue
            strategy_mode = strategy_mode_by_subject.get(sid, "hybrid")
            strategy_weight = _strategy_weight(
                subject_id=sid,
                slot_date=slot["date"],
                exam_day=exam_day_by_subject[sid],
                mode=strategy_mode,
            )
            tie = deterministic_tie_breaker_key(subject, reference_day=slot["date"])
            candidates.append((strategy_weight, tie, subject))

        candidates.sort(key=lambda item: (-item[0], item[1]))

        for weighted_candidate in candidates:
            subject = weighted_candidate[2]
            sid = str(subject["subject_id"])
            if free_minutes < session_minutes:
                break
            chunk = min(session_minutes, free_minutes, remaining_buffer[sid])
            _alloc_chunk(subject_id=sid, slot=slot, minutes=chunk, bucket="buffer", out=allocations)
            if decision_trace is not None:
                decision_trace.record(
                    slot_id=str(slot["slot_id"]),
                    candidate_subjects=[str(item[2]["subject_id"]) for item in candidates],
                    scores_by_subject={str(item[2]["subject_id"]): float(item[0]) for item in candidates},
                    selected_subject_id=sid,
                    applied_rules=[
                        "RULE_PRE_EXAM_BUFFER",
                        "RULE_BASE_BEFORE_BUFFER",
                        _strategy_rule(strategy_mode_by_subject.get(sid, "hybrid")),
                    ],
                    blocked_constraints=[],
                    tradeoff_note="Allocato buffer su materia con base completata e prima dell'esame.",
                    confidence_impact=0.005,
                )
            remaining_buffer[sid] -= chunk
            free_minutes -= chunk
            _register_history(slot["date"], sid, chunk)

        slack_by_slot[slot["slot_id"]] = free_minutes

    # Phase 3: fill gaps (buffer first, then explicit slack).
    for slot in ordered_slots:
        free_minutes = slack_by_slot.get(slot["slot_id"], 0)
        if free_minutes <= 0:
            continue

        candidates: list[tuple[float, tuple[int, int, str], dict[str, Any]]] = []
        for subject in _subject_order(ordered_subjects, slot["date"]):
            sid = str(subject["subject_id"])
            if remaining_base[sid] > 0:  # never invert base -> buffer
                continue
            if remaining_buffer[sid] <= 0 or free_minutes < session_minutes:
                continue
            strategy_mode = strategy_mode_by_subject.get(sid, "hybrid")
            strategy_weight = _strategy_weight(
                subject_id=sid,
                slot_date=slot["date"],
                exam_day=exam_day_by_subject[sid],
                mode=strategy_mode,
            )
            tie = deterministic_tie_breaker_key(subject, reference_day=slot["date"])
            candidates.append((strategy_weight, tie, subject))

        candidates.sort(key=lambda item: (-item[0], item[1]))

        for weighted_candidate in candidates:
            subject = weighted_candidate[2]
            sid = str(subject["subject_id"])
            if free_minutes < session_minutes:
                continue
            chunk = min(session_minutes, free_minutes, remaining_buffer[sid])
            _alloc_chunk(subject_id=sid, slot=slot, minutes=chunk, bucket="buffer", out=allocations)
            if decision_trace is not None:
                decision_trace.record(
                    slot_id=str(slot["slot_id"]),
                    candidate_subjects=[str(item[2].get("subject_id", "")) for item in candidates],
                    scores_by_subject={str(item[2].get("subject_id", "")): float(item[0]) for item in candidates},
                    selected_subject_id=sid,
                    applied_rules=[
                        "RULE_GAP_FILL_BUFFER",
                        "RULE_BASE_BEFORE_BUFFER",
                        _strategy_rule(strategy_mode_by_subject.get(sid, "hybrid")),
                    ],
                    blocked_constraints=[],
                    tradeoff_note="Riempimento gap con buffer disponibile.",
                    confidence_impact=0.002,
                )
            remaining_buffer[sid] -= chunk
            free_minutes -= chunk
            _register_history(slot["date"], sid, chunk)

        if free_minutes > 0:
            _alloc_chunk(subject_id="__slack__", slot=slot, minutes=free_minutes, bucket="slack", out=allocations)
            if decision_trace is not None:
                decision_trace.record(
                    slot_id=str(slot["slot_id"]),
                    candidate_subjects=[],
                    scores_by_subject={},
                    selected_subject_id="__slack__",
                    applied_rules=["RULE_GAP_FILL_SLACK"],
                    blocked_constraints=["NO_ELIGIBLE_SUBJECT"],
                    tradeoff_note="Minuti residui marcati come slack esplicito.",
                    confidence_impact=-0.01,
                )

    return {
        "allocations": allocations,
        "remaining_base_minutes": remaining_base,
        "remaining_buffer_minutes": remaining_buffer,
    }
