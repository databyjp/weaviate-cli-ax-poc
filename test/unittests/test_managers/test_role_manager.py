import json
from unittest.mock import MagicMock, patch

import pytest

from weaviate_cli.managers.role_manager import RoleManager


@pytest.fixture
def mock_client():
    client = MagicMock()
    return client


@pytest.fixture
def role_manager(mock_client):
    return RoleManager(mock_client)


# ---------------------------------------------------------------------------
# create_role
# ---------------------------------------------------------------------------


def test_create_role_success_text(role_manager, mock_client, capsys):
    mock_client.roles.create.return_value = None

    with patch("weaviate_cli.managers.role_manager.parse_permission") as mock_parse:
        mock_parse.return_value = MagicMock()
        role_manager.create_role(
            role_name="test-role",
            permissions=("read_collections:Movies",),
            json_output=False,
        )

    out = capsys.readouterr().out
    assert "test-role" in out
    assert "created successfully" in out


def test_create_role_success_json(role_manager, mock_client, capsys):
    mock_client.roles.create.return_value = None

    with patch("weaviate_cli.managers.role_manager.parse_permission") as mock_parse:
        mock_parse.return_value = MagicMock()
        role_manager.create_role(
            role_name="test-role",
            permissions=("read_collections:Movies",),
            json_output=True,
        )

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "success"
    assert "test-role" in data["message"]


def test_create_role_error(role_manager, mock_client):
    mock_client.roles.create.side_effect = Exception("connection failed")

    with patch("weaviate_cli.managers.role_manager.parse_permission") as mock_parse:
        mock_parse.return_value = MagicMock()
        with pytest.raises(Exception) as exc_info:
            role_manager.create_role(
                role_name="test-role",
                permissions=("read_collections:Movies",),
            )

    assert "Error creating role 'test-role'" in str(exc_info.value)


# ---------------------------------------------------------------------------
# delete_role
# ---------------------------------------------------------------------------


def test_delete_role_success_text(role_manager, mock_client, capsys):
    mock_client.roles.exists.side_effect = [True, False]

    role_manager.delete_role(role_name="test-role", json_output=False)

    out = capsys.readouterr().out
    assert "test-role" in out
    assert "deleted successfully" in out


def test_delete_role_success_json(role_manager, mock_client, capsys):
    mock_client.roles.exists.side_effect = [True, False]

    role_manager.delete_role(role_name="test-role", json_output=True)

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "success"
    assert "test-role" in data["message"]


def test_delete_role_not_found(role_manager, mock_client):
    mock_client.roles.exists.return_value = False

    with pytest.raises(Exception) as exc_info:
        role_manager.delete_role(role_name="nonexistent-role")

    assert "does not exist" in str(exc_info.value)


# ---------------------------------------------------------------------------
# add_permission
# ---------------------------------------------------------------------------


def test_add_permission_success_text(role_manager, mock_client, capsys):
    mock_client.roles.add_permissions.return_value = None

    with patch("weaviate_cli.managers.role_manager.parse_permission") as mock_parse:
        mock_parse.return_value = MagicMock()
        role_manager.add_permission(
            permission=("read_collections:Movies",),
            role_name="test-role",
            json_output=False,
        )

    out = capsys.readouterr().out
    assert "test-role" in out
    assert "added" in out


def test_add_permission_success_json(role_manager, mock_client, capsys):
    mock_client.roles.add_permissions.return_value = None

    with patch("weaviate_cli.managers.role_manager.parse_permission") as mock_parse:
        mock_parse.return_value = MagicMock()
        role_manager.add_permission(
            permission=("read_collections:Movies",),
            role_name="test-role",
            json_output=True,
        )

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "success"
    assert "test-role" in data["message"]


def test_add_permission_error(role_manager, mock_client):
    mock_client.roles.add_permissions.side_effect = Exception("failed")

    with patch("weaviate_cli.managers.role_manager.parse_permission") as mock_parse:
        mock_parse.return_value = MagicMock()
        with pytest.raises(Exception) as exc_info:
            role_manager.add_permission(
                permission=("read_collections:Movies",),
                role_name="test-role",
            )

    assert "Error adding permission" in str(exc_info.value)


# ---------------------------------------------------------------------------
# revoke_permission
# ---------------------------------------------------------------------------


def test_revoke_permission_success_text(role_manager, mock_client, capsys):
    mock_client.roles.remove_permissions.return_value = None

    with patch("weaviate_cli.managers.role_manager.parse_permission") as mock_parse:
        mock_parse.return_value = MagicMock()
        role_manager.revoke_permission(
            permission=("read_collections:Movies",),
            role_name="test-role",
            json_output=False,
        )

    out = capsys.readouterr().out
    assert "test-role" in out
    assert "revoked" in out


def test_revoke_permission_success_json(role_manager, mock_client, capsys):
    mock_client.roles.remove_permissions.return_value = None

    with patch("weaviate_cli.managers.role_manager.parse_permission") as mock_parse:
        mock_parse.return_value = MagicMock()
        role_manager.revoke_permission(
            permission=("read_collections:Movies",),
            role_name="test-role",
            json_output=True,
        )

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "success"
    assert "test-role" in data["message"]


def test_revoke_permission_error(role_manager, mock_client):
    mock_client.roles.remove_permissions.side_effect = Exception("failed")

    with patch("weaviate_cli.managers.role_manager.parse_permission") as mock_parse:
        mock_parse.return_value = MagicMock()
        with pytest.raises(Exception) as exc_info:
            role_manager.revoke_permission(
                permission=("read_collections:Movies",),
                role_name="test-role",
            )

    assert "Error revoking permission" in str(exc_info.value)


# ---------------------------------------------------------------------------
# role_to_dict & print_role
# ---------------------------------------------------------------------------


def test_role_to_dict_and_print_role_include_mcp_groups_replicate_tenant_data(
    role_manager, capsys
):
    from weaviate.rbac.models import (
        BackupsAction,
        BackupsPermissionOutput,
        DataAction,
        DataPermissionOutput,
        GroupAction,
        GroupsPermissionOutput,
        MCPAction,
        MCPPermissionOutput,
        ReplicateAction,
        ReplicatePermissionOutput,
        Role,
    )

    role = Role(
        name="mcp-ops",
        alias_permissions=[],
        cluster_permissions=[],
        collections_permissions=[],
        data_permissions=[
            DataPermissionOutput(
                collection="Articles",
                tenant="tenant-a",
                actions={DataAction.READ},
            )
        ],
        roles_permissions=[],
        users_permissions=[],
        backups_permissions=[
            BackupsPermissionOutput(
                collection="Articles",
                actions={BackupsAction.READ},
            )
        ],
        mcp_permissions=[
            MCPPermissionOutput(
                actions={MCPAction.READ, MCPAction.CREATE, MCPAction.UPDATE}
            )
        ],
        nodes_permissions=[],
        tenants_permissions=[],
        replicate_permissions=[
            ReplicatePermissionOutput(
                collection="Articles",
                shard="shard-1",
                actions={ReplicateAction.READ},
            )
        ],
        groups_permissions=[
            GroupsPermissionOutput(
                group="engineering",
                group_type="oidc",
                actions={GroupAction.READ, GroupAction.ASSIGN_AND_REVOKE},
            )
        ],
    )

    as_dict = RoleManager.role_to_dict(role)
    assert as_dict["name"] == "mcp-ops"
    assert as_dict["permissions"]["data"] == [
        {"collection": "Articles", "tenant": "tenant-a", "actions": ["read_data"]}
    ]
    assert as_dict["permissions"]["backups"] == [
        {"collection": "Articles", "actions": ["read_backups"]}
    ]
    assert as_dict["permissions"]["replicate"] == [
        {
            "collection": "Articles",
            "shard": "shard-1",
            "actions": ["read_replicate"],
        }
    ]
    assert as_dict["permissions"]["mcp"] == [
        {"actions": ["create_mcp", "read_mcp", "update_mcp"]}
    ]
    assert as_dict["permissions"]["groups"] == [
        {
            "group": "engineering",
            "group_type": "oidc",
            "actions": ["assign_and_revoke_groups", "read_groups"],
        }
    ]

    role_manager.print_role(role)
    out = capsys.readouterr().out
    assert "Role: mcp-ops" in out
    assert "Tenant: tenant-a" in out
    assert "Shard: shard-1" in out
    assert "MCP Permissions:" in out
    assert "create_mcp, read_mcp, update_mcp" in out
    assert "Groups Permissions:" in out
    assert "Group: engineering (oidc)" in out


def test_role_check_permission_manager_and_cli(role_manager, mock_client):
    from click.testing import CliRunner

    from cli import main

    mock_client.roles.has_permissions.return_value = True
    assert role_manager.has_permissions(("read_mcp",), "mcp-ops") is True
    mock_client.roles.has_permissions.assert_called_once()

    runner = CliRunner(mix_stderr=False)
    cfg = MagicMock()
    cfg.get_client.return_value = mock_client
    with patch("cli.ConfigManager", return_value=cfg):
        res = runner.invoke(
            main, ["role", "check-permission", "mcp-ops", "-p", "read_mcp"]
        )
    assert res.exit_code == 0, res.stdout
    data = json.loads(res.stdout)["data"]
    assert data == {
        "role": "mcp-ops",
        "permissions": ["read_mcp"],
        "has_permissions": True,
    }
