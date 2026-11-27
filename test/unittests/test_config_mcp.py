"""Unit tests for `weaviate-cli config show` and `weaviate-cli mcp config`."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from cli import main


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


def test_config_show_default_localhost_no_network_and_redacted(cli_runner, tmp_path):
    with patch.dict("os.environ", {"HOME": str(tmp_path)}, clear=True):
        result = cli_runner.invoke(main, ["config", "show"])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["error"] is None
    assert payload["metadata"]["command"] == "config show"
    data = payload["data"]
    assert data["target"] == "localhost:8080"
    assert data["rest_url"] == "http://localhost:8080"
    assert data["mcp_endpoint"] == "http://localhost:8080/v1/mcp"
    assert data["grpc"] == {"host": "localhost", "port": 50051, "secure": False}
    assert data["source"] == "default_localhost"
    assert data["env_file"] is None
    assert data["config_file"] is None
    assert data["auth"] == {"configured": False, "type": "none", "api_key": None}


def test_config_show_env_file_redacts_api_key_and_resolves_wcd_grpc(
    cli_runner, tmp_path
):
    env_file = tmp_path / ".env.cloud"
    env_file.write_text(
        "WEAVIATE_URL=https://demo.c0.eu-central-1.aws.weaviate.cloud\n"
        "WEAVIATE_API_KEY=super-secret-wcd-key-999\n",
        encoding="utf-8",
    )
    with patch.dict("os.environ", {"HOME": str(tmp_path)}, clear=True):
        json_res = cli_runner.invoke(
            main, ["--env-file", str(env_file), "config", "show"]
        )
        text_res = cli_runner.invoke(
            main, ["--no-json", "--env-file", str(env_file), "config", "show"]
        )

    assert json_res.exit_code == 0, json_res.stderr
    assert "super-secret-wcd-key-999" not in json_res.stdout
    assert "super-secret-wcd-key-999" not in text_res.stdout

    data = json.loads(json_res.stdout)["data"]
    assert data["source"] == "env_file"
    assert data["env_file"] == str(env_file)
    assert data["rest_url"] == "https://demo.c0.eu-central-1.aws.weaviate.cloud"
    assert data["grpc"] == {
        "host": "grpc-demo.c0.eu-central-1.aws.weaviate.cloud",
        "port": 443,
        "secure": True,
    }
    assert data["auth"] == {
        "configured": True,
        "type": "api_key",
        "api_key": "***REDACTED***",
    }

    assert text_res.exit_code == 0
    assert "***REDACTED***" in text_res.stdout
    assert "grpcs://grpc-demo.c0.eu-central-1.aws.weaviate.cloud:443" in text_res.stdout


def test_config_show_config_file_user_auth_lists_users_without_keys(
    cli_runner, tmp_path
):
    cfg_file = tmp_path / "rbac.json"
    cfg_file.write_text(
        json.dumps(
            {
                "host": "http://127.0.0.1:18080",
                "grpc_host": "127.0.0.1",
                "grpc_port": 51051,
                "auth": {
                    "type": "user",
                    "admin": "admin-secret-key",
                    "reader": "reader-secret-key",
                },
                "headers": {"X-OpenAI-Api-Key": "sk-secret"},
            }
        ),
        encoding="utf-8",
    )
    with patch.dict("os.environ", {"HOME": str(tmp_path)}, clear=True):
        result = cli_runner.invoke(
            main,
            ["--config-file", str(cfg_file), "--user", "admin", "config", "show"],
        )

    assert result.exit_code == 0, result.stderr
    assert "admin-secret-key" not in result.stdout
    assert "reader-secret-key" not in result.stdout
    assert "sk-secret" not in result.stdout

    data = json.loads(result.stdout)["data"]
    assert data["source"] == "config_file"
    assert data["config_file"] == str(cfg_file)
    assert data["grpc"] == {"host": "127.0.0.1", "port": 51051, "secure": False}
    assert data["auth"]["configured"] is True
    assert data["auth"]["type"] == "user"
    assert data["auth"]["user"] == "admin"
    assert data["auth"]["available_users"] == ["admin", "reader"]
    assert data["auth"]["api_key"] == "***REDACTED***"
    assert data["header_names"] == ["X-OpenAI-Api-Key"]


def test_mcp_config_generic_local_no_auth(cli_runner, tmp_path):
    with patch.dict("os.environ", {"HOME": str(tmp_path)}, clear=True):
        result = cli_runner.invoke(main, ["mcp", "config"])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["metadata"]["command"] == "mcp config"
    data = payload["data"]
    assert data["client"] == "generic"
    assert data["endpoint"] == "http://localhost:8080/v1/mcp"
    assert data["transport"] == "streamable-http"
    assert data["auth_mode"] == "none"
    assert data["config"] == {
        "mcpServers": {
            "weaviate": {
                "type": "http",
                "url": "http://localhost:8080/v1/mcp",
            }
        }
    }
    assert data["cli_command"] is None


@pytest.mark.parametrize(
    ("client_name", "expected_root_key", "expected_auth_header", "expected_file"),
    [
        (
            "claude-code",
            "mcpServers",
            "Bearer ${WEAVIATE_API_KEY}",
            ".mcp.json",
        ),
        (
            "cursor",
            "mcpServers",
            "Bearer ${WEAVIATE_API_KEY}",
            ".cursor/mcp.json",
        ),
        (
            "vscode",
            "servers",
            "Bearer ${env:WEAVIATE_API_KEY}",
            ".vscode/mcp.json",
        ),
    ],
)
def test_mcp_config_client_formats_use_env_placeholder_by_default(
    cli_runner,
    tmp_path,
    client_name: str,
    expected_root_key: str,
    expected_auth_header: str,
    expected_file: str,
):
    with patch.dict(
        "os.environ",
        {
            "HOME": str(tmp_path),
            "WEAVIATE_URL": "https://demo.weaviate.cloud",
            "WEAVIATE_API_KEY": "my-secret-api-key",
        },
        clear=True,
    ):
        result = cli_runner.invoke(
            main,
            [
                "mcp",
                "config",
                "--client",
                client_name,
                "--server-name",
                "weaviate-prod",
            ],
        )

    assert result.exit_code == 0, result.stderr
    assert "my-secret-api-key" not in result.stdout
    data = json.loads(result.stdout)["data"]
    assert data["auth_mode"] == "env_placeholder"
    assert data["config_file_hint"] == expected_file
    entry = data["config"][expected_root_key]["weaviate-prod"]
    assert entry["url"] == "https://demo.weaviate.cloud/v1/mcp"
    assert entry["headers"] == {"Authorization": expected_auth_header}
    if client_name == "claude-code":
        assert "claude mcp add --transport http weaviate-prod" in data["cli_command"]
        assert "${WEAVIATE_API_KEY}" in data["cli_command"]
        assert "my-secret-api-key" not in data["cli_command"]


def test_mcp_config_include_key_embeds_key_and_warns_to_stderr(cli_runner, tmp_path):
    with patch.dict(
        "os.environ",
        {
            "HOME": str(tmp_path),
            "WEAVIATE_URL": "https://demo.weaviate.cloud",
            "WEAVIATE_API_KEY": "inline-secret-123",
        },
        clear=True,
    ):
        result = cli_runner.invoke(
            main,
            ["mcp", "config", "--client", "claude-code", "--include-key"],
        )

    assert result.exit_code == 0, result.stderr
    assert "plaintext Weaviate API key" in result.stderr
    data = json.loads(result.stdout)["data"]
    assert data["auth_mode"] == "inline_key"
    assert (
        data["config"]["mcpServers"]["weaviate"]["headers"]["Authorization"]
        == "Bearer inline-secret-123"
    )
    assert "inline-secret-123" in data["cli_command"]


def test_mcp_config_check_success_and_unavailable_exit_5(cli_runner, tmp_path):
    with (
        patch.dict("os.environ", {"HOME": str(tmp_path)}, clear=True),
        patch(
            "weaviate_cli.commands.mcp.probe_mcp_endpoint",
            return_value={
                "endpoint": "http://localhost:8080/v1/mcp",
                "available": True,
            },
        ) as mock_probe,
    ):
        ok_res = cli_runner.invoke(main, ["mcp", "config", "--check"])

    assert ok_res.exit_code == 0, ok_res.stderr
    mock_probe.assert_called_once_with("http://localhost:8080", None)
    assert json.loads(ok_res.stdout)["data"]["probe"]["available"] is True

    with (
        patch.dict("os.environ", {"HOME": str(tmp_path)}, clear=True),
        patch(
            "weaviate_cli.commands.mcp.probe_mcp_endpoint",
            return_value={
                "endpoint": "http://localhost:8080/v1/mcp",
                "available": False,
            },
        ),
    ):
        fail_res = cli_runner.invoke(main, ["mcp", "config", "--check"])

    assert fail_res.exit_code == 5
    payload = json.loads(fail_res.stdout)
    assert payload["error"]["code"] == "MCP_UNAVAILABLE"
    assert "MCP_SERVER_ENABLED=true" in payload["error"]["hint"]


def test_mcp_config_text_mode_renders_snippet_and_guide_topic(cli_runner, tmp_path):
    with patch.dict("os.environ", {"HOME": str(tmp_path)}, clear=True):
        text_res = cli_runner.invoke(
            main, ["--no-json", "mcp", "config", "--client", "claude-code"]
        )
        guide_res = cli_runner.invoke(main, ["guide", "mcp"])

    assert text_res.exit_code == 0, text_res.stderr
    assert '"mcpServers"' in text_res.stdout
    assert "claude mcp add --transport http weaviate" in text_res.stdout

    assert guide_res.exit_code == 0, guide_res.stderr
    assert "weaviate-collections-get-config" in guide_res.stdout
    assert "weaviate-cli mcp config" in guide_res.stdout
