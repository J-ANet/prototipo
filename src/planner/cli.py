"""CLI entrypoint for planner."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from planner.engine import run_planner
from planner.io import read_json, write_json
from planner.metrics import collect_metrics
from planner.normalization import normalize_request, resolve_effective_config
from planner.reporting import (
    build_error_report,
    build_error_report_with_validation,
    build_success_report,
)
from planner.validation import (
    ValidationError,
    ValidationReport,
    validate_domain_inputs,
    validate_inputs_with_schema,
    validate_plan_request,
)


def _resolve_input_path(request_file: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (request_file.parent / path).resolve()


def _load_referenced_inputs(request_file: Path, request: dict[str, Any]) -> tuple[dict[str, Any], list[ValidationError]]:
    loaded = dict(request)
    errors: list[ValidationError] = []

    mapping = {
        "global_config_path": "global_config",
        "subjects_path": "subjects",
        "calendar_constraints_path": "calendar_constraints",
        "manual_sessions_path": "manual_sessions",
    }

    for path_field, target_field in mapping.items():
        resolved = _resolve_input_path(request_file, request[path_field])
        try:
            loaded[target_field] = read_json(resolved)
        except FileNotFoundError:
            errors.append(
                ValidationError(
                    code="file_not_found",
                    message=f"Referenced file not found: {resolved}",
                    path=f"$.{path_field}",
                )
            )
        except ValueError as exc:
            errors.append(
                ValidationError(
                    code="invalid_json",
                    message=str(exc),
                    path=f"$.{path_field}",
                )
            )

    return loaded, errors


def run_plan_command(request_path: str, output_path: str) -> int:
    validation_report = ValidationReport()

    try:
        request_payload = read_json(request_path)
    except Exception as exc:  # noqa: BLE001
        error = build_error_report(
            [ValidationError(code="invalid_request", message=str(exc), path="$.request")],
            code="request_read_error",
        )
        write_json(output_path, error)
        return 2

    request_payload = normalize_request(request_payload)
    errors = validate_plan_request(request_payload)

    if errors:
        write_json(output_path, build_error_report(errors))
        return 2

    loaded_request, load_errors = _load_referenced_inputs(Path(request_path), request_payload)
    if load_errors:
        write_json(
            output_path,
            build_error_report_with_validation(
                load_errors,
                validation_report=validation_report,
                code="input_load_error",
            ),
        )
        return 2

    loaded_request["plan_request"] = request_payload
    loaded_request["effective_config"] = resolve_effective_config(loaded_request, validation_report)
    if isinstance(loaded_request.get("global_config"), dict):
        loaded_request["global_config"]["stability_vs_recovery"] = loaded_request["effective_config"]["global"]["stability_vs_recovery"]

    domain_report = validate_domain_inputs(loaded_request)
    schema_report = validate_inputs_with_schema(loaded_request)
    validation_report.extend(domain_report)
    validation_report.extend(schema_report)

    if validation_report.errors:
        errors = [
            ValidationError(
                code=issue.code,
                message=issue.message,
                path=issue.field_path,
            )
            for issue in validation_report.errors
        ]
        write_json(
            output_path,
            build_error_report_with_validation(
                errors,
                validation_report=validation_report,
                code="validation_error",
            ),
        )
        return 2

    result = run_planner(loaded_request)
    metrics = collect_metrics(result)
    write_json(output_path, build_success_report(result, metrics, validation_report))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="planner", description="Adaptive study planner CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Generate a plan from plan_request JSON")
    plan_parser.add_argument("--request", required=True, help="Path to plan_request.json")
    plan_parser.add_argument("--output", required=True, help="Path to plan_output.json")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "plan":
        return run_plan_command(args.request, args.output)

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
