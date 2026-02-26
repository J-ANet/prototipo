"""Decision trace utilities for allocator runtime events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(slots=True)
class DecisionTraceCollector:
    """Collect allocation decisions while allocator phases are executed."""

    start_timestamp: datetime
    _sequence: int = 0
    _items: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.start_timestamp.tzinfo is None:
            self.start_timestamp = self.start_timestamp.replace(tzinfo=timezone.utc)

    def record(
        self,
        *,
        slot_id: str,
        candidate_subjects: list[str],
        scores_by_subject: dict[str, float],
        selected_subject_id: str,
        applied_rules: list[str],
        blocked_constraints: list[str],
        tradeoff_note: str,
        confidence_impact: float,
    ) -> None:
        self._sequence += 1
        timestamp = self.start_timestamp + timedelta(seconds=self._sequence)
        self._items.append(
            {
                "decision_id": f"d-{self._sequence:06d}",
                "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                "slot_id": slot_id,
                "candidate_subjects": sorted(candidate_subjects),
                "scores_by_subject": {sid: float(scores_by_subject[sid]) for sid in sorted(scores_by_subject)},
                "selected_subject_id": selected_subject_id,
                "applied_rules": applied_rules,
                "blocked_constraints": blocked_constraints,
                "tradeoff_note": tradeoff_note,
                "confidence_impact": float(confidence_impact),
            }
        )

    def as_list(self) -> list[dict[str, Any]]:
        """Return trace sorted in deterministic chronological order."""
        return sorted(self._items, key=lambda item: (str(item["timestamp"]), str(item["decision_id"])))
