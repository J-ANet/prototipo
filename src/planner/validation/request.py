"""Validation for plan request payload."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError

_REQUIRED_PATH_FIELDS = (
    "global_config_path",
    "subjects_path",
    "calendar_constraints_path",
    "manual_sessions_path",
)


def validate_plan_request(payload: dict[str, Any]) -> list[ValidationError]:
    """Validate plan_request with basic shape checks."""
    errors: list[ValidationError] = []

    for field in _REQUIRED_PATH_FIELDS:
        value = payload.get(field)
        if value is None:
            errors.append(
                ValidationError(
                    code="missing_field",
                    message=f"Missing required field: {field}",
                    path=f"$.{field}",
                )
            )
        elif not isinstance(value, str) or not value.strip():
            errors.append(
                ValidationError(
                    code="invalid_type",
                    message=f"Field must be a non-empty string path: {field}",
                    path=f"$.{field}",
                )
            )

    return errors
