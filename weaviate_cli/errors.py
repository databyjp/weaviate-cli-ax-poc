"""Typed errors and semantic exit codes for the agent-first CLI contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from weaviate.exceptions import (
    AuthenticationFailedError,
    InsufficientPermissionsError,
    MissingScopeError,
    UnexpectedStatusCodeError,
    WeaviateConnectionError,
    WeaviateGRPCUnavailableError,
    WeaviateStartUpError,
    WeaviateTimeoutError,
)


class ExitCode(IntEnum):
    """Semantic exit codes shared across all CLI commands."""

    OK = 0
    RUNTIME = 1
    USAGE = 2
    AUTH = 3
    NOT_FOUND = 4
    CONNECTIVITY = 5


@dataclass(frozen=True)
class ValidationIssue:
    """Single field-level validation finding returned as neutral evidence."""

    path: str
    code: str
    message: str
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "code": self.code,
            "message": self.message,
        }
        if self.hint:
            payload["hint"] = self.hint
        return payload


class CLIError(Exception):
    """Structured error carrying a stable code, semantic exit code, and fix hint."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        exit_code: ExitCode = ExitCode.RUNTIME,
        hint: str | None = None,
        issues: list[ValidationIssue] | tuple[ValidationIssue, ...] = (),
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.hint = hint
        self.issues = tuple(issues)
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.issues:
            payload["issues"] = [issue.to_dict() for issue in self.issues]
        if self.hint:
            payload["hint"] = self.hint
        if self.details:
            payload["details"] = self.details
        return payload


def _connection_hint(target: str | None, config_source: str | None) -> str:
    if config_source == "default_localhost":
        return (
            "No Weaviate target was configured, so the CLI defaulted to localhost:8080. "
            "Set WEAVIATE_URL and WEAVIATE_API_KEY, pass --url/--api-key, "
            "or pass --config-file <path>."
        )
    target_label = f" ({target})" if target else ""
    return (
        f"Verify that Weaviate{target_label} is reachable and that WEAVIATE_URL, "
        "WEAVIATE_GRPC_URL, or --config-file points to the right cluster."
    )


def classify_exception(
    exc: Exception,
    *,
    target: str | None = None,
    config_source: str | None = None,
) -> CLIError:
    """Translate arbitrary runtime or Weaviate SDK exceptions into a CLIError."""
    if isinstance(exc, CLIError):
        return exc

    if isinstance(exc, AuthenticationFailedError):
        return CLIError(
            code="AUTH_FAILED",
            message=str(exc) or "Authentication with Weaviate failed.",
            exit_code=ExitCode.AUTH,
            hint=(
                "Check WEAVIATE_API_KEY, --api-key, or the 'auth' section of your config file."
            ),
        )

    if isinstance(exc, (InsufficientPermissionsError, MissingScopeError)):
        return CLIError(
            code="FORBIDDEN",
            message=str(exc) or "Insufficient permissions for this operation.",
            exit_code=ExitCode.AUTH,
            hint="Use an API key or role with sufficient RBAC permissions for this command.",
        )

    if isinstance(
        exc,
        (
            WeaviateConnectionError,
            WeaviateStartUpError,
            WeaviateTimeoutError,
            WeaviateGRPCUnavailableError,
        ),
    ):
        return CLIError(
            code="CONNECTION_FAILED",
            message=str(exc) or "Failed to connect to Weaviate.",
            exit_code=ExitCode.CONNECTIVITY,
            hint=_connection_hint(target, config_source),
        )

    if isinstance(exc, UnexpectedStatusCodeError):
        status_code = getattr(exc, "status_code", None)
        message = str(exc)
        if status_code == 401:
            return CLIError(
                code="AUTH_FAILED",
                message=message,
                exit_code=ExitCode.AUTH,
                hint=(
                    "Check WEAVIATE_API_KEY, --api-key, or the 'auth' section of your config file."
                ),
            )
        if status_code == 403:
            return CLIError(
                code="FORBIDDEN",
                message=message,
                exit_code=ExitCode.AUTH,
                hint="Check that your API key has RBAC permission for this operation.",
            )
        if status_code == 404:
            return CLIError(
                code="NOT_FOUND",
                message=message,
                exit_code=ExitCode.NOT_FOUND,
            )
        if status_code == 409:
            return CLIError(
                code="CONFLICT",
                message=message,
                exit_code=ExitCode.NOT_FOUND,
            )
        if status_code in (400, 422):
            return CLIError(
                code="SERVER_VALIDATION_ERROR",
                message=message,
                exit_code=ExitCode.USAGE,
                hint="Inspect the server message above and verify your input or schema JSON.",
            )
        return CLIError(
            code="SERVER_ERROR",
            message=message,
            exit_code=ExitCode.RUNTIME,
            details={"status_code": status_code} if status_code is not None else None,
        )

    return CLIError(
        code="RUNTIME_ERROR",
        message=str(exc) or exc.__class__.__name__,
        exit_code=ExitCode.RUNTIME,
    )
