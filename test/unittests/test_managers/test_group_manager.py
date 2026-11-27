"""Unit tests for OIDC GroupManager and `group` CLI commands."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from cli import main
from weaviate_cli.managers.group_manager import GroupManager


def test_group_manager_operations():
    client = MagicMock()
    client.groups.oidc.get_known_group_names.return_value = ["ml", "eng"]
    client.roles.get_group_assignments.return_value = [
        SimpleNamespace(group_id="eng", group_type=SimpleNamespace(value="oidc"))
    ]
    client.groups.oidc.get_assigned_roles.return_value = {
        "viewer": SimpleNamespace(name="viewer")
    }

    gm = GroupManager(client)
    assert gm.list_known_groups() == ["eng", "ml"]
    assert gm.get_groups_for_role("viewer") == [
        {"group_id": "eng", "group_type": "oidc"}
    ]
    assert gm.get_group_roles("eng") == {
        "group_id": "eng",
        "group_type": "oidc",
        "roles": ["viewer"],
    }

    res_assign = gm.assign_roles("eng", ("viewer",))
    assert res_assign["status"] == "success"
    client.groups.oidc.assign_roles.assert_called_once_with(
        group_id="eng", role_names=["viewer"]
    )

    res_revoke = gm.revoke_roles("eng", ("viewer",))
    assert res_revoke["status"] == "success"
    client.groups.oidc.revoke_roles.assert_called_once_with(
        group_id="eng", role_names=["viewer"]
    )


def test_group_cli_and_role_assign_group():
    runner = CliRunner(mix_stderr=False)
    client = MagicMock()
    client.groups.oidc.get_known_group_names.return_value = ["eng"]
    client.roles.get_group_assignments.return_value = [
        SimpleNamespace(group_id="eng", group_type=SimpleNamespace(value="oidc"))
    ]
    client.groups.oidc.get_assigned_roles.return_value = {
        "viewer": SimpleNamespace(name="viewer")
    }
    cfg = MagicMock()
    cfg.get_client.return_value = client

    with patch("cli.ConfigManager", return_value=cfg):
        res_list = runner.invoke(main, ["group", "list"])
        assert res_list.exit_code == 0, res_list.stdout
        assert json.loads(res_list.stdout)["data"] == {"groups": ["eng"], "total": 1}

        res_role_groups = runner.invoke(main, ["group", "list", "--role", "viewer"])
        assert res_role_groups.exit_code == 0
        assert json.loads(res_role_groups.stdout)["data"]["groups"] == [
            {"group_id": "eng", "group_type": "oidc"}
        ]

        res_get = runner.invoke(main, ["group", "get", "eng"])
        assert res_get.exit_code == 0
        assert json.loads(res_get.stdout)["data"]["roles"] == ["viewer"]

        res_assign = runner.invoke(
            main, ["group", "assign-role", "eng", "--role", "viewer"]
        )
        assert res_assign.exit_code == 0

        res_role_assign_grp = runner.invoke(
            main, ["role", "assign", "--role", "viewer", "--group", "eng"]
        )
        assert res_role_assign_grp.exit_code == 0

        res_role_revoke_grp = runner.invoke(
            main, ["role", "revoke", "--role", "viewer", "--group", "eng"]
        )
        assert res_role_revoke_grp.exit_code == 0
