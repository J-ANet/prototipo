"""Minimal metrics collector."""

from __future__ import annotations

from typing import Any


def collect_metrics(result: dict[str, Any]) -> dict[str, Any]:
    """Attach placeholder metrics."""
    return {"confidence_score": 0.0, "confidence_level": "low", "plan_size": len(result.get("plan", []))}
