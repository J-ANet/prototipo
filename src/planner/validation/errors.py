"""Validation errors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ValidationError:
    """Represents one validation issue."""

    code: str
    message: str
    path: str
