import json
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from cli import main


@pytest.fixture
def cli_runner():
    return CliRunner()


def test_main_without_config_file(cli_runner):
    result = cli_runner.invoke(main)
    assert result.exit_code == 0


def test_main_with_non_existing_config_file(cli_runner):
    with patch("weaviate_cli.managers.config_manager.ConfigManager") as mock_config:
        result = cli_runner.invoke(
            main, ["--config-file", "test_config.json", "shard", "list"]
        )
        # Non existing config file is a usage error, so error code 2 is expected
        assert result.exit_code == 2
        assert (
            "Error: Invalid value for '--config-file': Path 'test_config.json' does not exist"
            in result.output
        )
        mock_config.assert_not_called()


def test_main_with_invalid_command(cli_runner):
    result = cli_runner.invoke(main, ["invalid_command"])
    assert result.exit_code == 2
    assert "No such command 'invalid_command'" in result.output


def test_main_help(cli_runner):
    result = cli_runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "--config-file" in result.output


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
    assert set(main.commands.keys()) == set(expected_groups.keys())

    # Legacy verb-noun groups must not exist
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


def test_collection_create_from_json(cli_runner):
    mock_client = MagicMock()
    mock_client.collections.exists.side_effect = [False, True]
    mock_config = MagicMock()
    mock_config.get_client.return_value = mock_client

    schema = {"class": "Articles", "vectorizer": "none"}
    with patch("cli.ConfigManager", return_value=mock_config):
        result = cli_runner.invoke(
            main,
            ["collection", "create", "--from-json", json.dumps(schema), "--json"],
        )

    assert result.exit_code == 0, result.output
    mock_client.collections.create_from_dict.assert_called_once_with(schema)
    payload = json.loads(result.output)
    assert payload["status"] == "success"
    assert "Articles" in payload["message"]


def test_collection_create_from_file_with_name_override(cli_runner, tmp_path):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps({"class": "Original", "vectorizer": "none"}), encoding="utf-8"
    )
    mock_client = MagicMock()
    mock_client.collections.exists.side_effect = [False, True]
    mock_config = MagicMock()
    mock_config.get_client.return_value = mock_client

    with patch("cli.ConfigManager", return_value=mock_config):
        result = cli_runner.invoke(
            main,
            [
                "collection",
                "create",
                "Overridden",
                "--from-file",
                str(schema_file),
                "--json",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_client.collections.create_from_dict.assert_called_once_with(
        {"class": "Overridden", "vectorizer": "none"}
    )


def test_collection_create_with_property_flags(cli_runner):
    mock_client = MagicMock()
    mock_client.collections.exists.side_effect = [False, True]
    mock_config = MagicMock()
    mock_config.get_client.return_value = mock_client

    with patch("cli.ConfigManager", return_value=mock_config):
        result = cli_runner.invoke(
            main,
            [
                "collection",
                "create",
                "Articles",
                "--property",
                "title:text",
                "-p",
                "tags:text[]",
                "--multitenant",
                "--json",
            ],
        )

    assert result.exit_code == 0, result.output
    call_kwargs = mock_client.collections.create.call_args.kwargs
    assert call_kwargs["name"] == "Articles"
    assert [p.name for p in call_kwargs["properties"]] == ["title", "tags"]
    assert call_kwargs["multi_tenancy_config"].enabled is True


def test_collection_create_rejects_conflicting_inputs(cli_runner):
    mock_config = MagicMock()
    with patch("cli.ConfigManager", return_value=mock_config):
        res_missing = cli_runner.invoke(main, ["collection", "create"])
        assert res_missing.exit_code == 2

        res_conflict = cli_runner.invoke(
            main,
            [
                "collection",
                "create",
                "Articles",
                "--from-json",
                '{"class": "Articles"}',
                "--property",
                "title:text",
            ],
        )
        assert res_conflict.exit_code == 2


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
