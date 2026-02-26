"""Build CLI reports."""

from __future__ import annotations

from datetime import datetime, timezone
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
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    plan_id = f"plan-{generated_at.replace(':', '').replace('-', '').replace('T', '-').replace('Z', '')}"
    plan_output = {
        "schema_version": "1.0.0",
        "plan_id": plan_id,
        "generated_at": generated_at,
        "plan_summary": result.get("plan_summary", {}),
        "daily_plan": result.get("daily_plan", []),
        "metrics": metrics,
        "warnings": result.get("warnings", []),
        "suggestions": result.get("suggestions", []),
        "decision_trace": result.get("decision_trace", []),
        "effective_config": result.get("effective_config", {}),
        "validation_report": validation_report.as_dict(),
    }
    return {
        "status": "ok",
        "result": result,
        "metrics": metrics,
        "plan_output": plan_output,
    }
