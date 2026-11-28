"""Typed errors and semantic exit codes for the agent-first CLI contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

import click
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


def _forbidden_hint(message: str, target: str | None) -> str:
    is_cloud = bool(target and "weaviate.cloud" in target.lower())
    if is_cloud and "backup" in message.lower():
        return (
            "Manual backups are unavailable on Weaviate Cloud free-tier clusters and "
            "require manage_backups/read_backups RBAC permissions on supported tiers."
        )
    return "Use an API key or role with sufficient RBAC permissions for this command."


def _classify_exception_inner(
    exc: Exception,
    *,
    target: str | None = None,
    config_source: str | None = None,
) -> CLIError | None:
    if isinstance(exc, CLIError):
        return exc

    if isinstance(exc, click.UsageError):
        return CLIError(
            code="USAGE_ERROR",
            message=exc.format_message(),
            exit_code=ExitCode.USAGE,
        )

    if isinstance(exc, ValueError):
        return CLIError(
            code="INVALID_INPUT",
            message=str(exc) or "Invalid input.",
            exit_code=ExitCode.USAGE,
        )

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
        msg = str(exc) or "Insufficient permissions for this operation."
        return CLIError(
            code="FORBIDDEN",
            message=msg,
            exit_code=ExitCode.AUTH,
            hint=_forbidden_hint(msg, target),
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
                hint=_forbidden_hint(message, target),
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
            lower_msg = message.lower()
            is_missing_module = (
                "module is not enabled" in lower_msg
                or "no module with name" in lower_msg
                or ("module" in lower_msg and "not enabled" in lower_msg)
            )
            if is_missing_module:
                return CLIError(
                    code="MODULE_NOT_ENABLED",
                    message=message,
                    exit_code=ExitCode.RUNTIME,
                    hint=(
                        "Enable the required module on your Weaviate cluster "
                        "(run 'weaviate-cli status' to see currently enabled modules)."
                    ),
                    details={"status_code": status_code},
                )
            return CLIError(
                code="SERVER_VALIDATION_ERROR",
                message=message,
                exit_code=ExitCode.USAGE,
                hint="Inspect the server message above and verify your input or schema JSON.",
            )
        if status_code == 501:
            return CLIError(
                code="NOT_IMPLEMENTED",
                message=message,
                exit_code=ExitCode.RUNTIME,
                hint="This endpoint is not enabled or supported on the target Weaviate server.",
                details={"status_code": 501},
            )
        if status_code == 429:
            is_usage_limit = "usage_limit_exceeded" in message.lower()
            hint = (
                "Weaviate Cloud tier limit reached (free tier allows 1 collection, "
                "3 tenants/collection, and 100,000 objects). Delete an unused collection "
                "or upgrade your cluster tier at https://console.weaviate.cloud."
                if is_usage_limit
                else "Request was rate-limited or exceeded a server quota. Retry after backing off or check cluster limits."
            )
            return CLIError(
                code="USAGE_LIMIT_EXCEEDED" if is_usage_limit else "RATE_LIMITED",
                message=message,
                exit_code=ExitCode.RUNTIME,
                hint=hint,
                details={"status_code": 429},
            )
        return CLIError(
            code="SERVER_ERROR",
            message=message,
            exit_code=ExitCode.RUNTIME,
            details={"status_code": status_code} if status_code is not None else None,
        )

    return None


def classify_exception(
    exc: Exception,
    *,
    target: str | None = None,
    config_source: str | None = None,
) -> CLIError:
    """Translate arbitrary runtime or Weaviate SDK exceptions into a CLIError."""
    direct = _classify_exception_inner(exc, target=target, config_source=config_source)
    if direct is not None:
        return direct

    # Unwrap chained causes (e.g. legacy managers wrapping SDK errors with `from e`).
    cause = exc.__cause__
    if isinstance(cause, Exception):
        classified_cause = _classify_exception_inner(
            cause, target=target, config_source=config_source
        )
        if classified_cause is not None:
            return CLIError(
                code=classified_cause.code,
                message=str(exc) or classified_cause.message,
                exit_code=classified_cause.exit_code,
                hint=classified_cause.hint,
                issues=classified_cause.issues,
                details=classified_cause.details,
            )

    if isinstance(exc, click.ClickException):
        return CLIError(
            code="CLI_ERROR",
            message=exc.format_message(),
            exit_code=ExitCode.RUNTIME,
        )

    return CLIError(
        code="RUNTIME_ERROR",
        message=str(exc) or exc.__class__.__name__,
        exit_code=ExitCode.RUNTIME,
    )
