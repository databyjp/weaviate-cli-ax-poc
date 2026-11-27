import json
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner
from weaviate.exceptions import WeaviateConnectionError

from cli import main


@pytest.fixture
def cli_runner():
    return CliRunner(mix_stderr=False)


def test_main_without_config_file(cli_runner):
    result = cli_runner.invoke(main)
    assert result.exit_code == 0


def test_main_with_non_existing_config_file(cli_runner):
    with patch("cli.ConfigManager") as mock_config:
        result = cli_runner.invoke(
            main, ["--config-file", "test_config.json", "shard", "list"]
        )
        assert result.exit_code == 2
        payload = json.loads(result.stdout)
        assert payload["data"] is None
        assert payload["error"]["code"] == "USAGE_ERROR"
        assert (
            "Invalid value for '--config-file': Path 'test_config.json' does not exist"
            in payload["error"]["message"]
        )
        mock_config.assert_not_called()


def test_main_with_invalid_command(cli_runner):
    result = cli_runner.invoke(main, ["invalid_command"])
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "USAGE_ERROR"
    assert "No such command 'invalid_command'" in payload["error"]["message"]


def test_main_help_and_short_h(cli_runner):
    for flag in ("--help", "-h"):
        result = cli_runner.invoke(main, [flag])
        assert result.exit_code == 0
        assert "WEAVIATE_URL" in result.stdout
        assert "WEAVIATE_API_KEY" in result.stdout
        assert "--url" in result.stdout
        assert "--env-file" in result.stdout
        assert "--json" in result.stdout
        assert "/v1/mcp" in result.stdout


def test_main_passes_env_file_to_config_manager(cli_runner, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("WEAVIATE_URL=http://localhost:8080\n", encoding="utf-8")
    with patch("cli.ConfigManager") as mock_config:
        mock_manager = MagicMock()
        mock_manager.list_collections.return_value = []
        with patch(
            "weaviate_cli.commands.collection.CollectionManager",
            return_value=mock_manager,
        ):
            result = cli_runner.invoke(
                main, ["--env-file", str(env_file), "collection", "list"]
            )
    assert result.exit_code == 0
    assert mock_config.call_args.kwargs["env_file"] == str(env_file)


def test_main_noun_verb_commands_registered():
    expected_groups = {
        "collection": {"create", "list", "get", "update", "delete"},
        "tenant": {"create", "list", "get", "update", "delete"},
        "alias": {"create", "list", "get", "update", "delete"},
        "node": {"list"},
        "shard": {"list", "update", "state"},
        "replication": {"create", "list", "get", "cancel", "delete"},
        "backup": {"create", "get", "restore", "cancel"},
        "export": {"create", "get", "cancel"},
        "role": {
            "create",
            "list",
            "get",
            "delete",
            "assign",
            "revoke",
            "add-permission",
            "revoke-permission",
        },
        "user": {"create", "list", "get", "update", "delete"},
    }
    expected_top_commands = {"status", "guide"}
    assert (
        set(main.commands.keys()) == set(expected_groups.keys()) | expected_top_commands
    )

    for legacy in (
        "create",
        "delete",
        "get",
        "update",
        "query",
        "restore",
        "cancel",
        "assign",
        "revoke",
        "benchmark",
    ):
        assert legacy not in main.commands

    for group_name, expected_subs in expected_groups.items():
        group = main.commands[group_name]
        assert isinstance(group, click.Group)
        assert set(group.commands.keys()) == expected_subs

    for top_name in expected_top_commands:
        cmd = main.commands[top_name]
        assert isinstance(cmd, click.Command)
        assert not isinstance(cmd, click.Group)


def test_all_cli_options_are_kebab_case():
    """Every long option across the entire CLI command tree must be kebab-case."""
    offenders: list[str] = []

    def _walk(cmd: click.Command, path: str) -> None:
        for param in cmd.params:
            if isinstance(param, click.Option):
                for opt in param.opts + param.secondary_opts:
                    if opt.startswith("--") and "_" in opt:
                        offenders.append(f"{path}: {opt}")
        if isinstance(cmd, click.Group):
            for sub_name, sub_cmd in cmd.commands.items():
                _walk(sub_cmd, f"{path} {sub_name}")

    _walk(main, "weaviate-cli")
    assert offenders == [], f"Found non-kebab-case options: {offenders}"


def test_collection_create_template_outputs_raw_valid_json(cli_runner):
    with patch("cli.ConfigManager") as mock_config:
        result = cli_runner.invoke(main, ["collection", "create", "--template"])
        assert result.exit_code == 0, result.stderr
        parsed = json.loads(result.stdout)
        assert parsed["class"] == "Articles"
        assert "properties" in parsed
        # Template should not contact any Weaviate server
        mock_config.return_value.get_client.assert_not_called()

        # Optional NAME overrides "class" in the printed template
        named = cli_runner.invoke(
            main, ["collection", "create", "SupportDocs", "--template"]
        )
        assert named.exit_code == 0
        assert json.loads(named.stdout)["class"] == "SupportDocs"


def test_collection_create_from_json_and_envelope(cli_runner):
    mock_client = MagicMock()
    mock_client.collections.exists.return_value = False
    mock_client.get_meta.return_value = {"version": "1.37.1", "modules": {}}
    mock_config = MagicMock()
    mock_config.get_client.return_value = mock_client

    schema = {"class": "Articles", "vectorizer": "none"}
    with patch("cli.ConfigManager", return_value=mock_config):
        result = cli_runner.invoke(
            main,
            ["collection", "create", "--from-json", json.dumps(schema)],
        )

    assert result.exit_code == 0, result.stdout + result.stderr
    mock_client.collections.create_from_dict.assert_called_once_with(schema)
    payload = json.loads(result.stdout)
    assert payload["data"] == {
        "collection": "Articles",
        "created": True,
        "already_exists": False,
    }
    assert payload["error"] is None
    assert payload["metadata"]["command"] == "collection create"
    assert payload["metadata"]["exit_code"] == 0


def test_collection_create_from_file_and_stdin_with_name_override(cli_runner, tmp_path):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps({"class": "Original", "vectorizer": "none"}), encoding="utf-8"
    )
    mock_client = MagicMock()
    mock_client.collections.exists.return_value = False
    mock_client.get_meta.return_value = {"version": "1.37.1", "modules": {}}
    mock_config = MagicMock()
    mock_config.get_client.return_value = mock_client

    with patch("cli.ConfigManager", return_value=mock_config):
        res_file = cli_runner.invoke(
            main,
            [
                "collection",
                "create",
                "Overridden",
                "--from-file",
                str(schema_file),
            ],
        )
        assert res_file.exit_code == 0, res_file.stdout
        mock_client.collections.create_from_dict.assert_called_with(
            {"class": "Overridden", "vectorizer": "none"}
        )

        res_stdin = cli_runner.invoke(
            main,
            ["collection", "create", "--from-file", "-"],
            input=json.dumps({"class": "FromStdin", "vectorizer": "none"}),
        )
        assert res_stdin.exit_code == 0, res_stdin.stdout
        mock_client.collections.create_from_dict.assert_called_with(
            {"class": "FromStdin", "vectorizer": "none"}
        )


def test_collection_create_dry_run_offline_and_check_cluster(cli_runner):
    mock_client = MagicMock()
    mock_client.collections.exists.return_value = False
    mock_client.get_meta.return_value = {
        "version": "1.37.1",
        "modules": {"text2vec-weaviate": {}},
    }
    mock_config = MagicMock()
    mock_config.get_client.return_value = mock_client

    with patch("cli.ConfigManager", return_value=mock_config):
        # Offline dry-run must not call get_client()
        offline = cli_runner.invoke(
            main,
            [
                "collection",
                "create",
                "--from-json",
                '{"class": "Articles", "vectorizer": "text2vec-transformers"}',
                "--dry-run",
            ],
        )
        assert offline.exit_code == 0, offline.stdout
        mock_config.get_client.assert_not_called()
        assert json.loads(offline.stdout)["data"]["dry_run"] is True

        # --dry-run --check-cluster catches module not enabled on the cluster
        live = cli_runner.invoke(
            main,
            [
                "collection",
                "create",
                "--from-json",
                '{"class": "Articles", "vectorizer": "text2vec-transformers"}',
                "--dry-run",
                "--check-cluster",
            ],
        )
        assert live.exit_code == 2
        payload = json.loads(live.stdout)
        assert payload["error"]["code"] == "INVALID_COLLECTION_SPEC"
        assert payload["error"]["issues"][0]["code"] == "MODULE_NOT_ENABLED"
        assert "text2vec-weaviate" in payload["error"]["issues"][0]["hint"]
        mock_client.collections.create_from_dict.assert_not_called()


def test_collection_create_rejects_invalid_schema_and_name_field(cli_runner):
    mock_config = MagicMock()
    with patch("cli.ConfigManager", return_value=mock_config):
        res_missing = cli_runner.invoke(main, ["collection", "create"])
        assert res_missing.exit_code == 2
        assert json.loads(res_missing.stdout)["error"]["code"] == "MISSING_SCHEMA_INPUT"

        # Strict rejection of top-level "name" and string dataType
        res_invalid = cli_runner.invoke(
            main,
            [
                "collection",
                "create",
                "--from-json",
                '{"name": "Articles", "properties": [{"name": "title", "dataType": "text"}]}',
            ],
        )
        assert res_invalid.exit_code == 2
        payload = json.loads(res_invalid.stdout)
        assert payload["error"]["code"] == "INVALID_COLLECTION_SPEC"
        paths = {i["path"] for i in payload["error"]["issues"]}
        assert "name" in paths
        assert "properties[0].dataType" in paths
        mock_config.get_client.assert_not_called()


def test_collection_create_text_mode_routes_errors_to_stderr(cli_runner):
    mock_config = MagicMock()
    with patch("cli.ConfigManager", return_value=mock_config):
        result = cli_runner.invoke(
            main,
            ["--no-json", "collection", "create", "--from-json", '{"name": "Docs"}'],
        )
        assert result.exit_code == 2
        assert result.stdout == ""
        assert "Error [INVALID_COLLECTION_SPEC]" in result.stderr
        assert 'Use "class" instead of "name"' in result.stderr


def test_collection_delete_all_requires_yes(cli_runner):
    mock_client = MagicMock()
    mock_client.collections.list_all.return_value = ["A", "B"]
    mock_config = MagicMock()
    mock_config.get_client.return_value = mock_client

    with patch("cli.ConfigManager", return_value=mock_config):
        blocked = cli_runner.invoke(main, ["collection", "delete", "--all"])
        assert blocked.exit_code == 2
        payload = json.loads(blocked.stdout)
        assert payload["error"]["code"] == "CONFIRMATION_REQUIRED"
        mock_client.collections.delete.assert_not_called()

        allowed = cli_runner.invoke(main, ["collection", "delete", "--all", "--yes"])
        assert allowed.exit_code == 0, allowed.stdout
        assert json.loads(allowed.stdout)["data"] == {"deleted": ["A", "B"], "count": 2}


def test_collection_list_connection_error_exit_code_5(cli_runner):
    mock_config = MagicMock()
    mock_config.target_description = "localhost:8080"
    mock_config.source = "default_localhost"
    mock_config.get_client.side_effect = WeaviateConnectionError("connection refused")

    with patch("cli.ConfigManager", return_value=mock_config):
        result = cli_runner.invoke(main, ["collection", "list"])

    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "CONNECTION_FAILED"
    assert "WEAVIATE_URL" in payload["error"]["hint"]


def test_main_passes_url_and_api_key_flags_to_config_manager(cli_runner):
    mock_client = MagicMock()
    mock_client.collections.list_all.return_value = {}
    mock_config = MagicMock()
    mock_config.get_client.return_value = mock_client

    with patch("cli.ConfigManager", return_value=mock_config) as mock_cls:
        result = cli_runner.invoke(
            main,
            [
                "--url",
                "https://demo.weaviate.cloud",
                "--api-key",
                "secret",
                "collection",
                "list",
            ],
        )

    assert result.exit_code == 0, result.stdout
    mock_cls.assert_called_once_with(
        config_file=None,
        user=None,
        env_file=None,
        url="https://demo.weaviate.cloud",
        api_key="secret",
        grpc_url=None,
    )


def test_tenant_commands_require_explicit_names(cli_runner):
    mock_config = MagicMock()
    with patch("cli.ConfigManager", return_value=mock_config):
        assert (
            cli_runner.invoke(
                main, ["tenant", "create", "--collection", "Docs"]
            ).exit_code
            == 2
        )
        assert (
            cli_runner.invoke(
                main, ["tenant", "update", "--collection", "Docs", "--state", "cold"]
            ).exit_code
            == 2
        )
        assert (
            cli_runner.invoke(
                main, ["tenant", "delete", "--collection", "Docs"]
            ).exit_code
            == 2
        )
