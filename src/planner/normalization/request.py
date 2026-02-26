"""Normalization for incoming request payloads."""

from __future__ import annotations

from typing import Any


def normalize_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized copy of input request."""
    normalized = dict(payload)
    if "schema_version" not in normalized:
        normalized["schema_version"] = "1.0"
    return normalized
