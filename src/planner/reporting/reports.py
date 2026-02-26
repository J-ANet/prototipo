"""Build CLI reports."""

from __future__ import annotations

from typing import Any

from planner.validation import ValidationError


def build_error_report(errors: list[ValidationError], code: str = "validation_error") -> dict[str, Any]:
    """Return a JSON-serializable error report."""
    return {
        "status": "error",
        "error": {
            "code": code,
            "count": len(errors),
            "details": [
                {"code": err.code, "message": err.message, "path": err.path}
                for err in errors
            ],
        },
    }


def build_success_report(result: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable success report."""
    return {"status": "ok", "result": result, "metrics": metrics}
