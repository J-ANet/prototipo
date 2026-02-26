"""Scoring and deterministic tie-breakers for candidate selection."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "w_urgency": 0.35,
    "w_priority": 0.20,
    "w_gap": 0.15,
    "w_difficulty": 0.10,
    "w_window": 0.10,
    "w_mode": 0.05,
    "w_concentration": 0.05,
    "w_streak": 0.15,
}

DEFAULT_CONTINUITY_CONFIG: dict[str, float | int | bool] = {
    "enabled": True,
    "lookback_days": 5,
    "rolling_window_days": 4,
    "streak_threshold_days": 2,
    "rolling_share_threshold": 0.65,
    "streak_penalty_factor": 0.25,
    "rolling_penalty_factor": 1.0,
    "max_penalty": 1.0,
}


def _to_date(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def compute_score(
    features: dict[str, float],
    weights: dict[str, float] | None = None,
) -> float:
    """Compute the default weighted score formula."""

    w = DEFAULT_SCORE_WEIGHTS if weights is None else weights
    urgency = float(features.get("urgency", 0.0))
    priority = float(features.get("priority", 0.0))
    completion_gap = float(features.get("completion_gap", 0.0))
    difficulty = float(features.get("difficulty", 0.0))
    window_pressure = float(features.get("window_pressure", 0.0))
    mode_alignment = float(features.get("mode_alignment", 0.0))
    concentration_penalty = float(features.get("concentration_penalty", 0.0))
    streak_penalty = float(features.get("streak_penalty", 0.0))

    return (
        float(w.get("w_urgency", 0.0)) * urgency
        + float(w.get("w_priority", 0.0)) * priority
        + float(w.get("w_gap", 0.0)) * completion_gap
        + float(w.get("w_difficulty", 0.0)) * difficulty
        + float(w.get("w_window", 0.0)) * window_pressure
        + float(w.get("w_mode", 0.0)) * mode_alignment
        - float(w.get("w_concentration", 0.0)) * concentration_penalty
        - float(w.get("w_streak", 0.0)) * streak_penalty
    )


def compute_recent_continuity_penalty(
    *,
    subject_id: str,
    reference_day: str | date,
    minutes_by_day: dict[date, dict[str, int]],
    total_minutes_by_day: dict[date, int],
    config: dict[str, float | int | bool] | None = None,
) -> float:
    """Compute continuity penalty from recent allocation history.

    Penalizes a subject when both of these become too persistent:
    - consecutive days with at least one assignment,
    - rolling minutes share in recent days.
    """

    cfg = DEFAULT_CONTINUITY_CONFIG if config is None else {**DEFAULT_CONTINUITY_CONFIG, **config}
    if not bool(cfg.get("enabled", True)):
        return 0.0

    ref_day = _to_date(reference_day)
    assert ref_day is not None

    lookback_days = max(1, int(cfg.get("lookback_days", 5)))
    rolling_window_days = max(1, int(cfg.get("rolling_window_days", 4)))
    streak_threshold = max(0, int(cfg.get("streak_threshold_days", 2)))
    rolling_share_threshold = max(0.0, min(1.0, float(cfg.get("rolling_share_threshold", 0.65))))
    streak_factor = max(0.0, float(cfg.get("streak_penalty_factor", 0.25)))
    rolling_factor = max(0.0, float(cfg.get("rolling_penalty_factor", 1.0)))
    max_penalty = max(0.0, float(cfg.get("max_penalty", 1.0)))

    streak_days = 0
    for offset in range(1, lookback_days + 1):
        day = ref_day - timedelta(days=offset)
        if minutes_by_day.get(day, {}).get(subject_id, 0) > 0:
            streak_days += 1
            continue
        break

    rolling_subject_minutes = 0
    rolling_total_minutes = 0
    for offset in range(1, rolling_window_days + 1):
        day = ref_day - timedelta(days=offset)
        rolling_subject_minutes += int(minutes_by_day.get(day, {}).get(subject_id, 0))
        rolling_total_minutes += int(total_minutes_by_day.get(day, 0))

    rolling_share = (
        float(rolling_subject_minutes) / float(rolling_total_minutes)
        if rolling_total_minutes > 0
        else 0.0
    )

    penalty = 0.0
    if streak_days > streak_threshold:
        penalty += (streak_days - streak_threshold) * streak_factor
    if rolling_share > rolling_share_threshold:
        penalty += (rolling_share - rolling_share_threshold) * rolling_factor

    return min(max_penalty, penalty)


def deterministic_tie_breaker_key(
    subject: dict[str, Any], *,
    reference_day: str | date,
) -> tuple[int, int, str]:
    """Return deterministic tie-break key.

    Order:
    1) nearest exam date (ascending)
    2) higher priority first
    3) subject_id lexicographic
    """

    ref_day = _to_date(reference_day)
    assert ref_day is not None

    exam_dates = []
    for raw in subject.get("exam_dates", []):
        parsed = _to_date(raw)
        if parsed is not None:
            exam_dates.append(parsed)
    if not exam_dates and subject.get("selected_exam_date"):
        fallback = _to_date(subject.get("selected_exam_date"))
        if fallback is not None:
            exam_dates.append(fallback)

    if exam_dates:
        nearest = min(exam_dates)
        days_to_exam = max(0, (nearest - ref_day).days)
    else:
        days_to_exam = 10**9

    priority = int(subject.get("priority", 0))
    subject_id = str(subject.get("subject_id", ""))
    return (days_to_exam, -priority, subject_id)
