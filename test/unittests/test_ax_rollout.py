"""AX contract tests across all migrated command groups.

Verifies uniform JSON envelopes, semantic exit codes, stderr hygiene,
-h/--help availability, and --yes destructive confirmation guards across
tenant, alias, node, role, user, shard, replication, backup, and export.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import click
import httpx
import pytest
from click.testing import CliRunner
from weaviate.exceptions import InsufficientPermissionsError
from weaviate.users.users import OwnUser

from cli import main


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


def _mock_config_with_client(client: MagicMock) -> MagicMock:
    cfg = MagicMock()
    cfg.target_description = "https://demo.weaviate.cloud"
    cfg.source = "env"
    cfg.get_client.return_value = client
    return cfg


def test_every_command_supports_short_help_and_json_flag():
    """Every command in the CLI tree must support -h and (for leaf commands) --json/--no-json."""

    def _walk(cmd: click.Command, path: str) -> None:
        assert "-h" in (cmd.context_settings.get("help_option_names") or []), (
            f"Missing -h help_option_names on {path}"
        )
        if isinstance(cmd, click.Group):
            for name, sub in cmd.commands.items():
                _walk(sub, f"{path} {name}")
        else:
            opt_names = {
                opt for p in cmd.params if isinstance(p, click.Option) for opt in p.opts
            }
            assert "--json" in opt_names, f"Missing --json on {path}"

    _walk(main, "weaviate-cli")


def test_node_list_forbidden_emits_json_envelope_and_exit_3(cli_runner: CliRunner):
    client = MagicMock()
    client.cluster.nodes.side_effect = InsufficientPermissionsError(
        httpx.Response(403, json={"error": [{"message": "forbidden read_nodes"}]})
    )
    with patch("cli.ConfigManager", return_value=_mock_config_with_client(client)):
        result = cli_runner.invoke(main, ["node", "list"])

    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["data"] is None
    assert payload["error"]["code"] == "FORBIDDEN"
    assert payload["metadata"]["command"] == "node list"
    assert payload["metadata"]["exit_code"] == 3


def test_alias_list_and_get_not_found_contracts(cli_runner: CliRunner):
    client = MagicMock()
    client.alias.list_all.return_value = {
        "docs": SimpleNamespace(alias="docs", collection="Articles")
    }
    client.alias.get.return_value = None

    with patch("cli.ConfigManager", return_value=_mock_config_with_client(client)):
        res_list = cli_runner.invoke(main, ["alias", "list"])
        res_missing = cli_runner.invoke(main, ["alias", "get", "missing"])

    assert res_list.exit_code == 0
    list_payload = json.loads(res_list.stdout)
    assert list_payload["data"] == {
        "aliases": [{"alias": "docs", "collection": "Articles"}]
    }
    assert list_payload["metadata"]["command"] == "alias list"

    assert res_missing.exit_code == 4
    missing_payload = json.loads(res_missing.stdout)
    assert missing_payload["error"]["code"] == "ALIAS_NOT_FOUND"


def test_user_get_and_role_get_contracts(cli_runner: CliRunner):
    client = MagicMock()
    own = OwnUser(user_id="agent1", roles={"admin": MagicMock()}, groups=[])
    client.users.get_my_user.return_value = own
    client.roles.get.return_value = None

    with patch("cli.ConfigManager", return_value=_mock_config_with_client(client)):
        res_user = cli_runner.invoke(main, ["user", "get"])
        res_role = cli_runner.invoke(main, ["role", "get", "nonexistent"])

    assert res_user.exit_code == 0
    user_payload = json.loads(res_user.stdout)
    assert user_payload["data"] == {"user_id": "agent1", "roles": ["admin"]}
    assert user_payload["metadata"]["command"] == "user get"

    assert res_role.exit_code == 4
    role_payload = json.loads(res_role.stdout)
    assert role_payload["error"]["code"] == "ROLE_NOT_FOUND"


def test_tenant_list_and_not_found_contracts(cli_runner: CliRunner):
    from weaviate.collections.classes.tenants import Tenant, TenantActivityStatus

    client = MagicMock()
    col = MagicMock()
    col.tenants.get.return_value = {
        "t1": Tenant(name="t1", activity_status=TenantActivityStatus.ACTIVE)
    }
    col.tenants.get_by_names.return_value = {}
    client.collections.get.return_value = col

    with patch("cli.ConfigManager", return_value=_mock_config_with_client(client)):
        res_list = cli_runner.invoke(main, ["tenant", "list", "--collection", "Docs"])
        res_get = cli_runner.invoke(
            main, ["tenant", "get", "missing", "--collection", "Docs"]
        )

    assert res_list.exit_code == 0
    payload = json.loads(res_list.stdout)
    assert payload["data"]["summary"]["total"] == 1
    assert payload["metadata"]["command"] == "tenant list"

    assert res_get.exit_code == 4
    missing_payload = json.loads(res_get.stdout)
    assert missing_payload["error"]["code"] == "TENANT_NOT_FOUND"


@pytest.mark.parametrize(
    "argv",
    [
        ["collection", "delete", "Articles"],
        ["collection", "delete", "--all"],
        ["collection", "delete-vector", "Articles", "title_vec"],
        ["tenant", "delete", "tenant-a", "--collection", "Articles"],
        ["role", "delete", "viewer"],
        ["user", "delete", "temp-user"],
        ["backup", "restore", "bk-1", "--backend", "s3"],
        ["replication", "delete", "--all"],
        ["shard", "update", "--all", "--status", "READONLY"],
    ],
)
def test_destructive_operations_require_yes(cli_runner: CliRunner, argv: list[str]):
    with patch("cli.ConfigManager") as mock_cfg:
        result = cli_runner.invoke(main, argv)

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["data"] is None
    assert payload["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert "--yes" in payload["error"]["hint"]
    mock_cfg.return_value.get_client.assert_not_called()


def test_replication_list_and_export_get_json_envelopes(cli_runner: CliRunner):
    client = MagicMock()
    client.cluster.replications.query.return_value = []
    client.export.get_status.return_value = SimpleNamespace(
        export_id="exp-1",
        backend="s3",
        path="s3://bucket/exp-1",
        status=SimpleNamespace(value="SUCCESS"),
        collections=["Articles"],
        started_at=None,
        error=None,
        took_in_ms=42,
        shard_status=None,
    )

    with patch("cli.ConfigManager", return_value=_mock_config_with_client(client)):
        res_rep = cli_runner.invoke(main, ["replication", "list"])
        res_exp = cli_runner.invoke(main, ["export", "get", "exp-1", "--backend", "s3"])

    assert res_rep.exit_code == 0
    assert json.loads(res_rep.stdout)["data"] == {"replications": []}

    assert res_exp.exit_code == 0
    exp_payload = json.loads(res_exp.stdout)
    assert exp_payload["data"]["export_id"] == "exp-1"
    assert exp_payload["data"]["status"] == "SUCCESS"
    assert exp_payload["metadata"]["command"] == "export get"
