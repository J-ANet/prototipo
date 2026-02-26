"""Minimal planner engine stub."""

from __future__ import annotations

from typing import Any


def run_planner(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the planning engine.

    For now this returns a deterministic minimal output that includes loaded inputs.
    """
    return {
        "status": "ok",
        "plan": [],
        "inputs_loaded": {
            "global_config": payload["global_config"],
            "subjects": payload["subjects"],
            "calendar_constraints": payload["calendar_constraints"],
            "manual_sessions": payload["manual_sessions"],
        },
    }
