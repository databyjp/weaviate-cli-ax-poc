"""Unit tests for `weaviate-cli status` and `weaviate-cli guide`."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner
from weaviate.exceptions import (
    AuthenticationFailedError,
    InsufficientPermissionsError,
    WeaviateConnectionError,
)

from cli import main
from weaviate_cli.managers.status_manager import StatusManager, probe_mcp_endpoint


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


def _mock_client(
    *,
    live: bool = True,
    ready: bool = True,
    version: str = "1.37.2",
    modules: dict | None = None,
    collections: dict | None = None,
    nodes: list | None = None,
    user: object | None = None,
) -> MagicMock:
    client = MagicMock()
    client.is_live.return_value = live
    client.is_ready.return_value = ready
    client.get_meta.return_value = {
        "version": version,
        "hostname": "http://[::]:8080",
        "modules": (
            {"text2vec-weaviate": {}, "generative-anthropic": {}}
            if modules is None
            else modules
        ),
    }
    client.collections.list_all.return_value = (
        {"Articles": MagicMock()} if collections is None else collections
    )
    client.cluster.nodes.return_value = (
        [SimpleNamespace(name="node-0", status="HEALTHY", version=version)]
        if nodes is None
        else nodes
    )
    if user is None:
        client.users.get_my_user.return_value = SimpleNamespace(
            user_id="agent1",
            roles={"admin": MagicMock()},
        )
    else:
        client.users.get_my_user.return_value = user
    return client


def test_status_manager_full_access():
    client = _mock_client()
    manager = StatusManager(
        client,
        target="https://demo.weaviate.cloud",
        config_source="env_file",
        rest_base_url="https://demo.weaviate.cloud",
        mcp_probe=lambda url, key: {"endpoint": f"{url}/v1/mcp", "available": True},
    )
    status = manager.get_status()

    assert status["target"] == "https://demo.weaviate.cloud"
    assert status["config_source"] == "env_file"
    assert status["live"] is True
    assert status["ready"] is True
    assert status["version"] == "1.37.2"
    assert status["user"] == {"user_id": "agent1", "roles": ["admin"]}
    assert status["collections"] == {
        "accessible": True,
        "count": 1,
        "names": ["Articles"],
    }
    assert status["nodes"] == {
        "accessible": True,
        "count": 1,
        "healthy": 1,
        "nodes": [{"name": "node-0", "status": "HEALTHY", "version": "1.37.2"}],
    }
    assert status["vectorizers"] == ["text2vec-weaviate"]
    assert status["modules"] == ["generative-anthropic", "text2vec-weaviate"]
    assert status["mcp"] == {
        "endpoint": "https://demo.weaviate.cloud/v1/mcp",
        "available": True,
    }
    assert status["warnings"] == []


def test_status_manager_degrades_gracefully_on_forbidden_nodes_and_collections():
    client = _mock_client()
    forbidden = InsufficientPermissionsError(
        httpx.Response(403, json={"error": [{"message": "forbidden"}]})
    )
    client.cluster.nodes.side_effect = forbidden
    client.collections.list_all.side_effect = forbidden

    manager = StatusManager(
        client,
        target="https://demo.weaviate.cloud",
        config_source="env",
        rest_base_url="https://demo.weaviate.cloud",
        mcp_probe=lambda url, key: {"endpoint": f"{url}/v1/mcp", "available": False},
    )
    status = manager.get_status()

    assert status["live"] is True
    assert status["collections"]["accessible"] is False
    assert status["nodes"]["accessible"] is False
    assert len(status["warnings"]) == 2


def test_status_manager_handles_anonymous_cluster_without_user():
    client = _mock_client()
    client.users.get_my_user.side_effect = AuthenticationFailedError("not enabled")

    manager = StatusManager(
        client,
        target="localhost:8080",
        config_source="default_localhost",
        rest_base_url="http://localhost:8080",
        mcp_probe=lambda url, key: {"endpoint": f"{url}/v1/mcp", "available": False},
    )
    status = manager.get_status()
    assert status["user"] is None


def test_probe_mcp_endpoint_handles_200_404_403_and_error():
    with patch(
        "weaviate_cli.managers.status_manager.httpx.post",
        return_value=httpx.Response(200, json={"result": {}}),
    ):
        assert probe_mcp_endpoint("https://demo.weaviate.cloud", "secret") == {
            "endpoint": "https://demo.weaviate.cloud/v1/mcp",
            "available": True,
        }

    with patch(
        "weaviate_cli.managers.status_manager.httpx.post",
        return_value=httpx.Response(404),
    ):
        assert probe_mcp_endpoint("http://localhost:8080") == {
            "endpoint": "http://localhost:8080/v1/mcp",
            "available": False,
        }

    with patch(
        "weaviate_cli.managers.status_manager.httpx.post",
        return_value=httpx.Response(403),
    ):
        assert probe_mcp_endpoint("https://demo.weaviate.cloud") == {
            "endpoint": "https://demo.weaviate.cloud/v1/mcp",
            "available": True,
            "auth_required": True,
        }

    with patch(
        "weaviate_cli.managers.status_manager.httpx.post",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        assert probe_mcp_endpoint("http://localhost:8080") == {
            "endpoint": "http://localhost:8080/v1/mcp",
            "available": None,
        }


def test_status_cli_json_and_text_modes(cli_runner: CliRunner):
    client = _mock_client(collections={})
    forbidden = InsufficientPermissionsError(
        httpx.Response(403, json={"error": [{"message": "forbidden"}]})
    )
    client.cluster.nodes.side_effect = forbidden

    mock_config = MagicMock()
    mock_config.target_description = "https://demo.weaviate.cloud"
    mock_config.source = "env_file"
    mock_config.rest_base_url = "https://demo.weaviate.cloud"
    mock_config.get_api_key.return_value = "secret"
    mock_config.get_client.return_value = client

    with patch("cli.ConfigManager", return_value=mock_config):
        with patch(
            "weaviate_cli.managers.status_manager.probe_mcp_endpoint",
            return_value={
                "endpoint": "https://demo.weaviate.cloud/v1/mcp",
                "available": True,
            },
        ):
            res_json = cli_runner.invoke(main, ["status"])
            assert res_json.exit_code == 0
            payload = json.loads(res_json.stdout)
            assert payload["error"] is None
            assert payload["data"]["version"] == "1.37.2"
            assert payload["data"]["collections"]["count"] == 0
            assert payload["data"]["nodes"]["accessible"] is False
            assert payload["data"]["vectorizers"] == ["text2vec-weaviate"]
            assert payload["metadata"]["command"] == "status"
            assert payload["metadata"]["warnings"]
            assert "Warning:" in res_json.stderr

            res_text = cli_runner.invoke(main, ["--no-json", "status"])
            assert res_text.exit_code == 0
            assert "Target:      https://demo.weaviate.cloud" in res_text.stdout
            assert "Vectorizers: text2vec-weaviate" in res_text.stdout
            assert "Native MCP:  available" in res_text.stdout


def test_status_cli_connection_error_returns_exit_5(cli_runner: CliRunner):
    mock_config = MagicMock()
    mock_config.target_description = "localhost:8080"
    mock_config.source = "default_localhost"
    mock_config.get_client.side_effect = WeaviateConnectionError("connection refused")

    with patch("cli.ConfigManager", return_value=mock_config):
        result = cli_runner.invoke(main, ["status"])

    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "CONNECTION_FAILED"
    assert payload["metadata"]["exit_code"] == 5


def test_guide_cli_outputs_raw_markdown_by_default_even_when_piped(
    cli_runner: CliRunner,
):
    result = cli_runner.invoke(main, ["guide"])
    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.stdout.startswith("# weaviate-cli guide")
    assert "## Connection precedence" in result.stdout
    assert "--env-file" in result.stdout
    assert "`status`" in result.stdout
    assert "`collection`" in result.stdout
    assert "/v1/mcp" in result.stdout


def test_guide_cli_topic_filter_and_unknown_topic(cli_runner: CliRunner):
    res_topic = cli_runner.invoke(main, ["guide", "collection"])
    assert res_topic.exit_code == 0
    assert "# weaviate-cli guide: collection" in res_topic.stdout
    assert "### `weaviate-cli collection create" in res_topic.stdout
    assert "--from-file" in res_topic.stdout

    res_bad = cli_runner.invoke(main, ["guide", "nonexistent"])
    assert res_bad.exit_code == 2
    payload = json.loads(res_bad.stdout)
    assert payload["error"]["code"] == "UNKNOWN_TOPIC"
    assert "collection" in payload["error"]["hint"]


def test_guide_cli_schema_introspects_live_click_tree(cli_runner: CliRunner):
    result = cli_runner.invoke(main, ["guide", "--schema"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["error"] is None
    assert payload["metadata"]["command"] == "guide"
    schema = payload["data"]["schema"]
    assert schema["path"] == "weaviate-cli"
    assert set(schema["subcommands"].keys()) == set(main.commands.keys())

    # Scoped schema for one group
    scoped = cli_runner.invoke(main, ["guide", "--schema", "collection"])
    assert scoped.exit_code == 0
    scoped_payload = json.loads(scoped.stdout)
    assert scoped_payload["data"]["topic"] == "collection"
    assert "create" in scoped_payload["data"]["schema"]["subcommands"]
    create_opts = {
        opt["name"]
        for opt in scoped_payload["data"]["schema"]["subcommands"]["create"]["options"]
    }
    assert {
        "from_file",
        "from_json",
        "template",
        "dry_run",
        "check_cluster",
    } <= create_opts
