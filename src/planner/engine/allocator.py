"""Deterministic allocation pipeline.

Phases:
1) forward allocation,
2) pre-exam refinement,
3) gap filling.

Rule preserved: never allocate buffer for a subject while that same subject still has base minutes remaining.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .scoring import compute_score, deterministic_tie_breaker_key


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


def allocate_plan(
    *,
    slots: list[dict[str, Any]],
    subjects: list[dict[str, Any]],
    workload_by_subject: dict[str, dict[str, Any]],
    session_minutes: int = 30,
    score_features_by_subject: dict[str, dict[str, float]] | None = None,
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

    # Phase 1: forward assignment with score + deterministic tie-break.
    for slot in ordered_slots:
        available = int(slot.get("max_minutes", 0))
        day_subjects = _subject_order(ordered_subjects, slot["date"])

        while available >= session_minutes:
            candidates: list[tuple[float, tuple[int, int, str], dict[str, Any]]] = []
            for subject in day_subjects:
                sid = str(subject["subject_id"])
                if remaining_base[sid] <= 0:
                    continue
                features = (score_features_by_subject or {}).get(sid, {})
                score = compute_score(features)
                tie = deterministic_tie_breaker_key(subject, reference_day=slot["date"])
                candidates.append((score, tie, subject))

            if not candidates:
                break

            candidates.sort(key=lambda item: (-item[0], item[1]))
            chosen = candidates[0][2]
            sid = str(chosen["subject_id"])
            chunk = min(session_minutes, available, remaining_base[sid])
            _alloc_chunk(subject_id=sid, slot=slot, minutes=chunk, bucket="base", out=allocations)
            remaining_base[sid] -= chunk
            available -= chunk

        slack_by_slot[slot["slot_id"]] = available

    # Phase 2: pre-exam refinement, prioritize nearest exam with completed base.
    for slot in ordered_slots:
        free_minutes = slack_by_slot.get(slot["slot_id"], 0)
        if free_minutes < session_minutes:
            continue
        day = _to_date(slot["date"])

        candidates: list[dict[str, Any]] = []
        for subject in _subject_order(ordered_subjects, slot["date"]):
            sid = str(subject["subject_id"])
            if remaining_base[sid] > 0:  # never invert base -> buffer
                continue
            if remaining_buffer[sid] <= 0:
                continue
            if day > exam_day_by_subject[sid]:
                continue
            candidates.append(subject)

        for subject in candidates:
            sid = str(subject["subject_id"])
            if free_minutes < session_minutes:
                break
            chunk = min(session_minutes, free_minutes, remaining_buffer[sid])
            _alloc_chunk(subject_id=sid, slot=slot, minutes=chunk, bucket="buffer", out=allocations)
            remaining_buffer[sid] -= chunk
            free_minutes -= chunk

        slack_by_slot[slot["slot_id"]] = free_minutes

    # Phase 3: fill gaps (buffer first, then explicit slack).
    for slot in ordered_slots:
        free_minutes = slack_by_slot.get(slot["slot_id"], 0)
        if free_minutes <= 0:
            continue

        for subject in _subject_order(ordered_subjects, slot["date"]):
            sid = str(subject["subject_id"])
            if remaining_base[sid] > 0:  # never invert base -> buffer
                continue
            if remaining_buffer[sid] <= 0 or free_minutes < session_minutes:
                continue
            chunk = min(session_minutes, free_minutes, remaining_buffer[sid])
            _alloc_chunk(subject_id=sid, slot=slot, minutes=chunk, bucket="buffer", out=allocations)
            remaining_buffer[sid] -= chunk
            free_minutes -= chunk

        if free_minutes > 0:
            _alloc_chunk(subject_id="__slack__", slot=slot, minutes=free_minutes, bucket="slack", out=allocations)

    return {
        "allocations": allocations,
        "remaining_base_minutes": remaining_base,
        "remaining_buffer_minutes": remaining_buffer,
    }
