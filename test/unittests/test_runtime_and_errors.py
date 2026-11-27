"""Unit tests for weaviate_cli.errors and weaviate_cli.runtime."""

import json

import httpx
import pytest
from weaviate.exceptions import (
    AuthenticationFailedError,
    InsufficientPermissionsError,
    UnexpectedStatusCodeError,
    WeaviateConnectionError,
)

from weaviate_cli.errors import (
    CLIError,
    ExitCode,
    ValidationIssue,
    classify_exception,
)
from weaviate_cli.runtime import (
    RuntimeContext,
    emit_error,
    emit_success,
    emit_warning,
)


def test_classify_auth_and_permission_errors():
    auth_err = classify_exception(AuthenticationFailedError("bad key"))
    assert auth_err.exit_code == ExitCode.AUTH
    assert auth_err.code == "AUTH_FAILED"
    assert auth_err.hint and "WEAVIATE_API_KEY" in auth_err.hint

    perm_err = classify_exception(
        InsufficientPermissionsError(
            httpx.Response(403, json={"error": [{"message": "denied"}]})
        )
    )
    assert perm_err.exit_code == ExitCode.AUTH
    assert perm_err.code == "FORBIDDEN"


def test_classify_connection_error_hints():
    default_err = classify_exception(
        WeaviateConnectionError("refused"),
        target="localhost:8080",
        config_source="default_localhost",
    )
    assert default_err.exit_code == ExitCode.CONNECTIVITY
    assert default_err.code == "CONNECTION_FAILED"
    assert default_err.hint and "WEAVIATE_URL" in default_err.hint
    assert "defaulted to localhost:8080" in default_err.hint

    cloud_err = classify_exception(
        WeaviateConnectionError("dns failed"),
        target="https://demo.weaviate.cloud",
        config_source="env",
    )
    assert cloud_err.exit_code == ExitCode.CONNECTIVITY
    assert cloud_err.hint and "https://demo.weaviate.cloud" in cloud_err.hint


@pytest.mark.parametrize(
    ("status_code", "expected_exit", "expected_code"),
    [
        (401, ExitCode.AUTH, "AUTH_FAILED"),
        (403, ExitCode.AUTH, "FORBIDDEN"),
        (404, ExitCode.NOT_FOUND, "NOT_FOUND"),
        (409, ExitCode.NOT_FOUND, "CONFLICT"),
        (422, ExitCode.USAGE, "SERVER_VALIDATION_ERROR"),
        (500, ExitCode.RUNTIME, "SERVER_ERROR"),
    ],
)
def test_classify_unexpected_status_codes(status_code, expected_exit, expected_code):
    response = httpx.Response(
        status_code, json={"error": [{"message": "server message"}]}
    )
    exc = UnexpectedStatusCodeError("Create collection", response)

    classified = classify_exception(exc)
    assert classified.exit_code == expected_exit
    assert classified.code == expected_code


def test_emit_success_json_envelope_and_stderr_warnings(capsys):
    runtime = RuntimeContext(json_output=True)
    emit_warning(runtime, "deprecated option")
    emit_success(runtime, {"collection": "Articles"}, command="collection create")

    captured = capsys.readouterr()
    assert "Warning: deprecated option" in captured.err
    payload = json.loads(captured.out)
    assert payload["data"] == {"collection": "Articles"}
    assert payload["error"] is None
    assert payload["metadata"]["command"] == "collection create"
    assert payload["metadata"]["exit_code"] == 0
    assert payload["metadata"]["warnings"] == ["deprecated option"]


def test_emit_error_json_mode_writes_envelope_to_stdout(capsys):
    runtime = RuntimeContext(json_output=True)
    err = CLIError(
        code="INVALID_COLLECTION_SPEC",
        message="Schema failed",
        exit_code=ExitCode.USAGE,
        issues=[
            ValidationIssue(
                path="properties[0].dataType",
                code="INVALID_TYPE",
                message="Expected list",
                hint='Use ["text"]',
            )
        ],
        hint="Run --template",
    )
    with pytest.raises(SystemExit) as exc_info:
        emit_error(runtime, err, command="collection create")

    assert exc_info.value.code == int(ExitCode.USAGE)
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["data"] is None
    assert payload["error"]["code"] == "INVALID_COLLECTION_SPEC"
    assert payload["error"]["issues"][0]["path"] == "properties[0].dataType"
    assert payload["metadata"]["exit_code"] == 2


def test_emit_error_text_mode_writes_strictly_to_stderr(capsys):
    runtime = RuntimeContext(json_output=False)
    err = CLIError(
        code="CONNECTION_FAILED",
        message="Could not reach Weaviate",
        exit_code=ExitCode.CONNECTIVITY,
        hint="Set WEAVIATE_URL",
    )
    with pytest.raises(SystemExit) as exc_info:
        emit_error(runtime, err, command="collection list")

    assert exc_info.value.code == int(ExitCode.CONNECTIVITY)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Error [CONNECTION_FAILED]: Could not reach Weaviate" in captured.err
    assert "Hint: Set WEAVIATE_URL" in captured.err
