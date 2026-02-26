"""Build CLI reports."""

from __future__ import annotations

from typing import Any

from planner.validation import ValidationError, ValidationReport


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


def build_error_report_with_validation(
    errors: list[ValidationError],
    validation_report: ValidationReport,
    code: str = "validation_error",
) -> dict[str, Any]:
    payload = build_error_report(errors, code=code)
    payload["validation_report"] = validation_report.as_dict()
    return payload


def build_success_report(
    result: dict[str, Any], metrics: dict[str, Any], validation_report: ValidationReport
) -> dict[str, Any]:
    """Return a JSON-serializable success report."""
    return {
        "status": "ok",
        "result": result,
        "metrics": metrics,
        "plan_output": {"validation_report": validation_report.as_dict()},
    }
