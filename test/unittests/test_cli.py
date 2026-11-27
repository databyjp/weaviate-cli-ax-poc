import json
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner
from weaviate.exceptions import WeaviateConnectionError

from cli import main
from weaviate_cli.runtime import AXGroup


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
        "config": {"show"},
        "mcp": {"config"},
        "local": {"start", "template", "stop", "status", "logs", "destroy"},
        "cloud": {
            "install-wcloud",
            "login",
            "whoami",
            "logout",
            "regions",
            "create",
            "list",
            "get",
            "status",
        },
        "collection": {
            "create",
            "list",
            "get",
            "add-property",
            "add-vector",
            "delete-vector",
            "update",
            "delete",
        },
        "tenant": {"create", "list", "get", "update", "delete"},
        "alias": {"create", "list", "get", "update", "delete"},
        "node": {"list", "stats"},
        "shard": {"list", "update", "state"},
        "replication": {"create", "list", "get", "cancel", "delete"},
        "backup": {"list", "create", "get", "restore", "cancel"},
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
        "group": {"list", "get", "assign-role", "revoke-role"},
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
        assert isinstance(group, AXGroup)
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
        blocked_single = cli_runner.invoke(main, ["collection", "delete", "A"])
        assert blocked_single.exit_code == 2
        assert (
            json.loads(blocked_single.stdout)["error"]["code"]
            == "CONFIRMATION_REQUIRED"
        )
        mock_client.collections.delete.assert_not_called()

        allowed_single = cli_runner.invoke(main, ["collection", "delete", "A", "--yes"])
        assert allowed_single.exit_code == 0, allowed_single.stdout
        assert json.loads(allowed_single.stdout)["data"] == {
            "deleted": ["A"],
            "count": 1,
        }

        blocked = cli_runner.invoke(main, ["collection", "delete", "--all"])
        assert blocked.exit_code == 2
        payload = json.loads(blocked.stdout)
        assert payload["error"]["code"] == "CONFIRMATION_REQUIRED"

        allowed = cli_runner.invoke(main, ["collection", "delete", "--all", "--yes"])
        assert allowed.exit_code == 0, allowed.stdout
        assert json.loads(allowed.stdout)["data"] == {"deleted": ["A", "B"], "count": 2}


def test_guide_role_does_not_repeat_full_permission_help(cli_runner):
    result = cli_runner.invoke(main, ["guide", "role"])
    assert result.exit_code == 0
    assert result.stdout.count("Available Permissions:") == 1


def test_rbac001_user_warning_is_filtered():
    import warnings

    from weaviate.warnings import _Warnings

    from cli import configure_warning_filters

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        configure_warning_filters()
        _Warnings.unknown_permission_encountered({"action": "manage_namespaces"})
    assert caught == []


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


def test_collection_schema_evolution_cli_commands(cli_runner):
    mock_client = MagicMock()
    mock_client.collections.exists.return_value = True
    mock_client.get_meta.return_value = {
        "version": "1.41.0",
        "modules": {"text2vec-transformers": {}, "generative-openai": {}},
    }
    mock_col = MagicMock()
    mock_col.config.get.return_value = MagicMock(
        properties=[],
        references=[],
        vector_config={},
        vectorizer=None,
        vector_index_type=MagicMock(value="hnsw"),
    )
    mock_client.collections.get.return_value = mock_col
    mock_config = MagicMock()
    mock_config.get_client.return_value = mock_client

    with patch("cli.ConfigManager", return_value=mock_config):
        res_prop = cli_runner.invoke(
            main,
            [
                "collection",
                "add-property",
                "Articles",
                "--name",
                "tags",
                "--data-type",
                "text[]",
                "--description",
                "Topic tags",
            ],
        )
        assert res_prop.exit_code == 0, res_prop.stdout + res_prop.stderr
        prop_payload = json.loads(res_prop.stdout)
        assert prop_payload["data"]["property"] == "tags"
        assert prop_payload["data"]["kind"] == "property"
        assert prop_payload["data"]["added"] is True

        res_ref = cli_runner.invoke(
            main,
            [
                "collection",
                "add-property",
                "Articles",
                "--name",
                "related",
                "--data-type",
                "Author",
                "--data-type",
                "Publisher",
            ],
        )
        assert res_ref.exit_code == 0, res_ref.stdout + res_ref.stderr
        assert json.loads(res_ref.stdout)["data"]["kind"] == "reference"

        res_vec = cli_runner.invoke(
            main,
            [
                "collection",
                "add-vector",
                "Articles",
                "title_vec",
                "--vectorizer",
                "text2vec-transformers",
                "--source-property",
                "title",
                "--quantizer",
                "rq",
                "--rq-bits",
                "8",
            ],
        )
        assert res_vec.exit_code == 0, res_vec.stdout + res_vec.stderr
        assert json.loads(res_vec.stdout)["data"]["added"] == ["title_vec"]

        res_del_vec = cli_runner.invoke(
            main,
            ["collection", "delete-vector", "Articles", "title_vec", "--yes"],
        )
        assert res_del_vec.exit_code == 0, res_del_vec.stdout + res_del_vec.stderr
        del_payload = json.loads(res_del_vec.stdout)
        assert del_payload["data"]["vector"] == "title_vec"
        assert del_payload["data"]["async"] is True
        mock_col.config.delete_vector_index.assert_called_once_with("title_vec")

        res_upd_dry = cli_runner.invoke(
            main,
            [
                "collection",
                "update",
                "Articles",
                "--from-json",
                '{"invertedIndexConfig": {"bm25": {"b": 0.7}}, "propertyDescriptions": {"title": "Doc title"}}',
                "--dry-run",
            ],
        )
        assert res_upd_dry.exit_code == 0, res_upd_dry.stdout + res_upd_dry.stderr
        assert json.loads(res_upd_dry.stdout)["data"]["dry_run"] is True

        res_upd = cli_runner.invoke(
            main,
            [
                "collection",
                "update",
                "Articles",
                "--from-json",
                '{"description": "Updated", "generativeConfig": {"generative-openai": {"model": "gpt-4o"}}}',
            ],
        )
        assert res_upd.exit_code == 0, res_upd.stdout + res_upd.stderr
        assert json.loads(res_upd.stdout)["data"]["updated_fields"] == [
            "description",
            "generativeConfig",
        ]


def test_tenant_list_filters_multi_get_and_delete_yes_cli(cli_runner):
    from weaviate.collections.classes.tenants import Tenant, TenantActivityStatus

    mock_client = MagicMock()
    mock_client.collections.exists.return_value = True
    mock_col = MagicMock()
    mock_col.name = "Docs"
    mock_col.config.get.return_value = MagicMock(
        multi_tenancy_config=MagicMock(enabled=True)
    )
    mock_col.tenants.get.return_value = {
        "acme-1": Tenant(name="acme-1", activity_status=TenantActivityStatus.ACTIVE),
        "acme-2": Tenant(
            name="acme-2", activity_status=TenantActivityStatus.OFFLOADING
        ),
        "beta-1": Tenant(name="beta-1", activity_status=TenantActivityStatus.ONLOADING),
    }
    mock_col.tenants.get_by_names.side_effect = [
        {"acme-1": Tenant(name="acme-1", activity_status=TenantActivityStatus.ACTIVE)},
        {"acme-1": Tenant(name="acme-1", activity_status=TenantActivityStatus.ACTIVE)},
        {},
    ]
    mock_client.collections.get.return_value = mock_col
    mock_config = MagicMock()
    mock_config.get_client.return_value = mock_client

    with patch("cli.ConfigManager", return_value=mock_config):
        res_list = cli_runner.invoke(
            main,
            [
                "tenant",
                "list",
                "--collection",
                "Docs",
                "--prefix",
                "acme-",
                "--state",
                "offloading",
                "--limit",
                "1",
            ],
        )
        assert res_list.exit_code == 0, res_list.stdout + res_list.stderr
        list_payload = json.loads(res_list.stdout)
        assert list_payload["data"]["tenants"] == [
            {"name": "acme-2", "activity_status": "OFFLOADING"}
        ]
        assert list_payload["data"]["summary"]["offloading"] == 1
        assert list_payload["data"]["summary"]["total_unfiltered"] == 3

        res_get = cli_runner.invoke(
            main,
            ["tenant", "get", "acme-1", "missing-1", "--collection", "Docs"],
        )
        assert res_get.exit_code == 0, res_get.stdout + res_get.stderr
        get_payload = json.loads(res_get.stdout)
        assert [t["name"] for t in get_payload["data"]["tenants"]] == ["acme-1"]
        assert get_payload["data"]["missing"] == ["missing-1"]

        res_del = cli_runner.invoke(
            main,
            ["tenant", "delete", "acme-1", "--collection", "Docs", "--yes"],
        )
        assert res_del.exit_code == 0, res_del.stdout + res_del.stderr
        assert json.loads(res_del.stdout)["data"]["tenants_deleted"] == 1
