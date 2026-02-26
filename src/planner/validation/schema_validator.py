"""JSON schema validation for planner inputs."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .errors import ValidationReport

_SCHEMA_BY_PAYLOAD = {
    "plan_request": "planner_plan_request.schema.json",
    "global_config": "planner_global_config.schema.json",
    "subjects": "planner_subjects.schema.json",
    "manual_sessions": "planner_manual_sessions.schema.json",
}


def validate_inputs_with_schema(payloads: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    schema_dir = Path(__file__).resolve().parents[3] / "schema"

    for payload_name, schema_file in _SCHEMA_BY_PAYLOAD.items():
        if payload_name not in payloads:
            continue
        schema = json.loads((schema_dir / schema_file).read_text(encoding="utf-8"))
        _validate_node(
            value=payloads[payload_name],
            schema=schema,
            path=f"$.{payload_name}",
            report=report,
        )

    return report


def _validate_node(*, value: Any, schema: dict[str, Any], path: str, report: ValidationReport) -> None:
    expected_type = schema.get("type")
    if expected_type:
        if not _matches_type(value, expected_type):
            report.add_error(
                code="INVALID_TYPE",
                message=f"Expected type {expected_type}, got {type(value).__name__}",
                field_path=path,
            )
            return

    if "enum" in schema and value not in schema["enum"]:
        report.add_error(
            code="INVALID_ENUM_VALUE",
            message=f"Value {value!r} not in enum",
            field_path=path,
        )

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                report.add_error(
                    code="MISSING_REQUIRED_FIELD",
                    message=f"Missing required field: {key}",
                    field_path=f"{path}.{key}",
                )

        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    report.add_error(
                        code="INVALID_OVERRIDE_KEY" if key not in properties else "INVALID_TYPE",
                        message=f"Unknown field: {key}",
                        field_path=f"{path}.{key}",
                        suggested_fix="Remove unsupported key or use one of schema-defined fields.",
                    )

        property_names = schema.get("propertyNames")
        if isinstance(property_names, dict) and "enum" in property_names:
            allowed_names = set(property_names["enum"])
            for key in value:
                if key not in allowed_names:
                    report.add_error(
                        code="INVALID_OVERRIDE_KEY",
                        message=f"Override key {key!r} is not allowed",
                        field_path=f"{path}.{key}",
                        suggested_fix=f"Use one of: {', '.join(sorted(allowed_names))}",
                    )

        for key, prop_schema in properties.items():
            if key in value:
                _validate_node(value=value[key], schema=prop_schema, path=f"{path}.{key}", report=report)

    elif isinstance(value, list):
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            report.add_error(
                code="EMPTY_ARRAY_NOT_ALLOWED",
                message=f"Array must have at least {min_items} items",
                field_path=path,
            )
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for idx, item in enumerate(value):
                _validate_node(value=item, schema=items_schema, path=f"{path}[{idx}]", report=report)

    elif isinstance(value, str):
        min_len = schema.get("minLength")
        if min_len is not None and len(value) < min_len:
            report.add_error(
                code="MISSING_REQUIRED_FIELD",
                message="String cannot be empty",
                field_path=path,
            )
        data_format = schema.get("format")
        if data_format == "date" and not _is_date(value):
            report.add_error(code="INVALID_DATE_FORMAT", message="Invalid date format", field_path=path)
        if data_format == "date-time" and not _is_datetime(value):
            report.add_error(code="INVALID_DATE_FORMAT", message="Invalid datetime format", field_path=path)

    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            report.add_error(code="OUT_OF_RANGE", message=f"Value must be >= {minimum}", field_path=path)
        exclusive_min = schema.get("exclusiveMinimum")
        if exclusive_min is not None and value <= exclusive_min:
            report.add_error(code="OUT_OF_RANGE", message=f"Value must be > {exclusive_min}", field_path=path)
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            report.add_error(code="OUT_OF_RANGE", message=f"Value must be <= {maximum}", field_path=path)
        multiple_of = schema.get("multipleOf")
        if multiple_of is not None and value % multiple_of != 0:
            report.add_error(
                code="INVALID_STEP_VALUE",
                message=f"Value must be multiple of {multiple_of}",
                field_path=path,
            )


def _matches_type(value: Any, expected_type: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }.get(expected_type, True)


def _is_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True
