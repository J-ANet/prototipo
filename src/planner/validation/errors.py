"""Validation models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ValidationError:
    """Represents one validation issue."""

    code: str
    message: str
    path: str


@dataclass(slots=True)
class ValidationIssue:
    """Structured validation issue for report export."""

    code: str
    message: str
    field_path: str
    suggested_fix: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "field_path": self.field_path,
        }
        if self.suggested_fix:
            payload["suggested_fix"] = self.suggested_fix
        payload.update(self.extra)
        return payload


@dataclass(slots=True)
class ValidationReport:
    """Aggregated report with errors and infos (no short-circuit)."""

    errors: list[ValidationIssue] = field(default_factory=list)
    infos: list[ValidationIssue] = field(default_factory=list)

    def add_error(
        self,
        *,
        code: str,
        message: str,
        field_path: str,
        suggested_fix: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.errors.append(
            ValidationIssue(
                code=code,
                message=message,
                field_path=field_path,
                suggested_fix=suggested_fix,
                extra=extra or {},
            )
        )

    def add_info(
        self,
        *,
        code: str,
        message: str,
        field_path: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.infos.append(
            ValidationIssue(
                code=code,
                message=message,
                field_path=field_path,
                extra=extra or {},
            )
        )

    def extend(self, other: "ValidationReport") -> None:
        self.errors.extend(other.errors)
        self.infos.extend(other.infos)

    def as_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "errors": [issue.as_dict() for issue in self.errors],
            "infos": [issue.as_dict() for issue in self.infos],
        }
