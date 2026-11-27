from unittest.mock import MagicMock

import pytest
from weaviate.rbac.models import Permissions, RoleScope

from weaviate_cli.utils import (
    ASYNC_REPLICATION_CONFIG_DEPRECATED_KEYS,
    ASYNC_REPLICATION_CONFIG_HELP,
    ASYNC_REPLICATION_CONFIG_KEYS,
    get_client_from_context,
    get_random_string,
    parse_async_replication_config,
    parse_permission,
    warn_removed_async_replication_keys,
)


def test_get_client_from_context(mock_click_context, mock_client):
    mock_click_context.obj["config"].get_client.return_value = mock_client
    client = get_client_from_context(mock_click_context)
    assert client == mock_client
    mock_click_context.obj["config"].get_client.assert_called_once()


def test_get_random_string():
    # Test different lengths
    assert len(get_random_string(5)) == 5
    assert len(get_random_string(10)) == 10

    # Test randomness
    str1 = get_random_string(8)
    str2 = get_random_string(8)
    assert str1 != str2

    # Test only lowercase letters
    random_str = get_random_string(20)
    assert all(c.islower() for c in random_str)


def test_parse_permission_collections():
    # Test basic collection permissions
    assert parse_permission("read_collections:Movies") == Permissions.collections(
        collection="Movies", read_config=True
    )

    # Test multiple collections
    assert parse_permission(
        "create_collections:Movies,Books,Films"
    ) == Permissions.collections(
        collection=["Movies", "Books", "Films"], create_collection=True
    )

    # Test crud collections
    assert parse_permission("crud_collections:Movies") == Permissions.collections(
        collection="Movies",
        create_collection=True,
        read_config=True,
        update_config=True,
        delete_collection=True,
    )


def test_parse_permissions_tenant():
    assert parse_permission("create_tenants:Movies") == Permissions.tenants(
        collection="Movies", create=True
    )

    assert parse_permission("read_tenants:Movies") == Permissions.tenants(
        collection="Movies", read=True
    )

    assert parse_permission("crud_tenants:Movies,Books,Films*") == Permissions.tenants(
        collection=["Movies", "Books", "Films*"],
        create=True,
        read=True,
        update=True,
        delete=True,
    )

    assert parse_permission(
        "read_tenants:Books:MyTenant*,YourTenant*"
    ) == Permissions.tenants(
        collection="Books", tenant=["MyTenant*", "YourTenant*"], read=True
    )

    assert parse_permission(
        "crd_tenants:Books,Movies:MyTenant*,YourTenant*"
    ) == Permissions.tenants(
        collection=["Books", "Movies"],
        tenant=["MyTenant*", "YourTenant*"],
        create=True,
        read=True,
        delete=True,
    )


def test_parse_permission_data():
    # Test basic data permissions
    assert parse_permission("read_data:Movies") == Permissions.data(
        collection="Movies", read=True
    )

    # Test multiple collections
    assert parse_permission("create_data:Movies,Books,Films") == Permissions.data(
        collection=["Movies", "Books", "Films"], create=True
    )

    # Test crud data
    assert parse_permission("crud_data:Movies") == Permissions.data(
        collection="Movies", create=True, read=True, update=True, delete=True
    )

    # Test tenant-scoped data permissions
    assert parse_permission("read_data:Movies:tenant-a") == Permissions.data(
        collection="Movies", tenant="tenant-a", read=True
    )
    assert parse_permission(
        "crud_data:Movies,Books:tenant-a,tenant-b"
    ) == Permissions.data(
        collection=["Movies", "Books"],
        tenant=["tenant-a", "tenant-b"],
        create=True,
        read=True,
        update=True,
        delete=True,
    )


def test_parse_permission_roles():
    # Test basic role permissions
    assert parse_permission("read_roles:custom") == Permissions.roles(
        role="custom", read=True
    )

    assert parse_permission("read_roles:custom,viewer") == Permissions.roles(
        role=["custom", "viewer"], read=True
    )

    # Test multiple roles
    assert parse_permission("read_roles:custom,editor,viewer") == Permissions.roles(
        role=["custom", "editor", "viewer"], read=True
    )

    # Test read with scope
    assert parse_permission("read_roles:custom:all") == Permissions.roles(
        role="custom", read=True, scope=RoleScope.ALL
    )

    # Test update roles
    assert parse_permission("update_roles:custom") == Permissions.roles(
        role="custom", update=True
    )
    assert parse_permission("update_roles:*:match") == Permissions.roles(
        role="*", update=True, scope=RoleScope.MATCH
    )

    # Test delete roles
    assert parse_permission("delete_roles:CustomMovies:all") == Permissions.roles(
        role="CustomMovies", delete=True, scope=RoleScope.ALL
    )

    # Test create roles
    assert parse_permission(
        "create_roles:admin1,admin2,admin3:match"
    ) == Permissions.roles(
        role=["admin1", "admin2", "admin3"], create=True, scope=RoleScope.MATCH
    )

    assert parse_permission("rucd_roles:CustomMovies:all") == Permissions.roles(
        role="CustomMovies",
        create=True,
        read=True,
        update=True,
        delete=True,
        scope=RoleScope.ALL,
    )

    assert parse_permission("cr_roles:admin,admin1,admin2") == Permissions.roles(
        role=["admin", "admin1", "admin2"],
        create=True,
        read=True,
        update=False,
        delete=False,
    )


def test_parse_permission_users():
    assert parse_permission("create_users:admin") == Permissions.users(
        user="admin", create=True
    )

    assert parse_permission("crud_users:admin") == Permissions.users(
        user="admin", create=True, read=True, update=True, delete=True
    )

    assert parse_permission("assign_and_revoke_users:admin") == Permissions.users(
        user="admin", assign_and_revoke=True
    )

    assert parse_permission("cr_users:admin1,admin2,viewer1") == Permissions.users(
        user=["admin1", "admin2", "viewer1"],
        create=True,
        read=True,
        update=False,
        delete=False,
    )

    assert parse_permission(
        "assign_and_revoke_users:admin,admin1,admin2"
    ) == Permissions.users(user=["admin", "admin1", "admin2"], assign_and_revoke=True)

    assert parse_permission("assign_and_revoke_users") == Permissions.users(
        user="*", assign_and_revoke=True
    )

    assert parse_permission("read_users:admin") == Permissions.users(
        user="admin", read=True
    )

    assert parse_permission("read_users:admin,admin1,admin2") == Permissions.users(
        user=["admin", "admin1", "admin2"], read=True
    )

    assert parse_permission("read_users") == Permissions.users(user="*", read=True)


def test_parse_permission_backups():
    # Test basic backup permissions
    assert parse_permission("manage_backups:Movies") == Permissions.backup(
        collection="Movies", manage=True
    )

    # Test multiple collections
    assert parse_permission("manage_backups:Movies,Books,Films") == Permissions.backup(
        collection=["Movies", "Books", "Films"], manage=True
    )

    # Test read_backups
    assert parse_permission("read_backups") == Permissions.backup(
        collection="*", read=True
    )
    assert parse_permission("read_backups:Movies,Books") == Permissions.backup(
        collection=["Movies", "Books"], read=True
    )


def test_parse_permission_mcp():
    assert parse_permission("read_mcp") == Permissions.mcp(read=True)
    assert parse_permission("create_mcp") == Permissions.mcp(create=True)
    assert parse_permission("update_mcp") == Permissions.mcp(update=True)
    assert parse_permission("cru_mcp") == Permissions.mcp(
        create=True, read=True, update=True
    )
    assert parse_permission("cr_mcp") == Permissions.mcp(create=True, read=True)


def test_parse_permission_replicate():
    assert parse_permission("read_replicate") == Permissions.replicate(
        collection="*", shard="*", read=True
    )
    assert parse_permission("crud_replicate:Articles") == Permissions.replicate(
        collection="Articles",
        shard="*",
        create=True,
        read=True,
        update=True,
        delete=True,
    )
    assert parse_permission(
        "cr_replicate:Articles,Books:shard-1,shard-2"
    ) == Permissions.replicate(
        collection=["Articles", "Books"],
        shard=["shard-1", "shard-2"],
        create=True,
        read=True,
    )


def test_parse_permission_groups():
    assert parse_permission("read_groups") == Permissions.Groups.oidc(
        group="*", read=True
    )
    assert parse_permission("read_groups:eng,ops") == Permissions.Groups.oidc(
        group=["eng", "ops"], read=True
    )
    assert parse_permission("read_groups:eng:oidc") == Permissions.Groups.oidc(
        group="eng", read=True
    )
    assert parse_permission("assign_and_revoke_groups:eng") == Permissions.Groups.oidc(
        group="eng", assign_and_revoke=True
    )


def test_parse_permission_nodes(capsys):
    # Test basic node permissions (must not emit spurious warning)
    assert parse_permission("read_nodes:minimal") == Permissions.Nodes.minimal(
        read=True
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

    # Specifying collection with minimal verbosity warns strictly on stderr, never stdout
    assert parse_permission("read_nodes:minimal:Movies") == Permissions.Nodes.minimal(
        read=True
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Collection is not supported for minimal verbosity" in captured.err

    # Test verbose node permissions
    assert parse_permission("read_nodes:verbose:Movies") == Permissions.Nodes.verbose(
        collection="Movies", read=True
    )

    # Test multiple collections
    assert parse_permission(
        "read_nodes:verbose:Movies,Books,Films"
    ) == Permissions.Nodes.verbose(collection=["Movies", "Books", "Films"], read=True)


def test_parse_permission_aliases():
    assert parse_permission("crud_aliases:Movies") == Permissions.alias(
        alias="*", collection="Movies", create=True, read=True, update=True, delete=True
    )

    assert parse_permission("cud_aliases:Movies") == Permissions.alias(
        alias="*", collection="Movies", create=True, update=True, delete=True
    )

    assert parse_permission("rd_aliases:Movies*") == Permissions.alias(
        alias="*", collection="Movies*", read=True, delete=True
    )

    assert parse_permission("cr_aliases:Movies,Books,Films*") == Permissions.alias(
        alias="*",
        collection=["Movies", "Books", "Films*"],
        create=True,
        read=True,
        update=False,
        delete=False,
    )

    assert parse_permission("cr_aliases") == Permissions.alias(
        alias="*", collection="*", create=True, read=True, update=False, delete=False
    )

    assert parse_permission("create_aliases:Movies,Books:Alias*") == Permissions.alias(
        alias="Alias*", collection=["Movies", "Books"], create=True
    )

    assert parse_permission(
        "cru_aliases:*:Alias*,MyAlias*,Forget"
    ) == Permissions.alias(
        alias=["Alias*", "MyAlias*", "Forget"],
        collection="*",
        create=True,
        read=True,
        update=True,
    )

    assert parse_permission("create_aliases:Banks") == Permissions.alias(
        alias="*", collection="Banks", create=True
    )


def test_parse_permission_cluster():
    # Test cluster read permission
    assert parse_permission("read_cluster") == Permissions.cluster(read=True)


def test_parse_permission_invalid():
    # Test invalid action
    with pytest.raises(ValueError, match="Invalid permission action: invalid_action"):
        parse_permission("invalid_action:Movies")

    # Test invalid crud combination
    with pytest.raises(ValueError, match="Invalid crud combination: xyz"):
        parse_permission("xyz_collections:Movies")

    # Test invalid node verbosity
    with pytest.raises(ValueError, match="Input should be 'minimal' or 'verbose'"):
        parse_permission("read_nodes:invalid:Movies")

    # Test missing node verbosity
    with pytest.raises(ValueError, match="Input should be 'minimal' or 'verbose'"):
        parse_permission("read_nodes:Movies")

    # Test passing too many parts
    with pytest.raises(ValueError, match="Invalid permission format"):
        parse_permission("read_nodes:minimal:Movies:custom")

    # Test non existing actions
    with pytest.raises(ValueError, match="Invalid permission action: create_cluster"):
        parse_permission("create_cluster")

    with pytest.raises(ValueError, match="Invalid permission action: delete_backups"):
        parse_permission("delete_backups")

    with pytest.raises(ValueError, match="Invalid permission action: update_nodes"):
        parse_permission("update_nodes")

    with pytest.raises(ValueError, match="MCP permissions do not accept a target"):
        parse_permission("read_mcp:Articles")

    with pytest.raises(ValueError, match="Invalid MCP permission action: crud_mcp"):
        parse_permission("crud_mcp")

    with pytest.raises(ValueError, match="Invalid MCP permission action: delete_mcp"):
        parse_permission("delete_mcp")

    with pytest.raises(ValueError, match="Unsupported group type 'ldap'"):
        parse_permission("read_groups:eng:ldap")


def test_parse_async_replication_config_none():
    assert parse_async_replication_config(None) is None


def test_parse_async_replication_config_empty():
    assert parse_async_replication_config(()) is None


def test_parse_async_replication_config_single_key():
    result = parse_async_replication_config(("max_workers=10",))
    assert result == {"max_workers": 10}


def test_parse_async_replication_config_multiple_keys():
    result = parse_async_replication_config(
        ("max_workers=10", "frequency=60", "propagation_concurrency=4")
    )
    assert result == {"max_workers": 10, "frequency": 60, "propagation_concurrency": 4}


def test_parse_async_replication_config_all_keys():
    all_keys = (
        "max_workers=1",
        "hashtree_height=2",
        "frequency=3",
        "frequency_while_propagating=4",
        "alive_nodes_checking_frequency=5",
        "logging_frequency=6",
        "diff_batch_size=7",
        "diff_per_node_timeout=8",
        "pre_propagation_timeout=9",
        "propagation_timeout=10",
        "propagation_limit=11",
        "propagation_delay=12",
        "propagation_concurrency=13",
        "propagation_batch_size=14",
    )
    result = parse_async_replication_config(all_keys)
    assert result is not None
    assert len(result) == 14
    assert result["max_workers"] == 1
    assert result["propagation_batch_size"] == 14


def test_parse_async_replication_config_invalid_key():
    with pytest.raises(ValueError, match="Unknown async replication config key"):
        parse_async_replication_config(("invalid_key=10",))


def test_parse_async_replication_config_invalid_value():
    with pytest.raises(ValueError, match="Must be an integer"):
        parse_async_replication_config(("max_workers=abc",))


def test_parse_async_replication_config_missing_equals():
    with pytest.raises(ValueError, match="Expected key=value"):
        parse_async_replication_config(("max_workers",))


def test_parse_async_replication_config_reset():
    result = parse_async_replication_config(("reset",))
    assert result == {}


def test_parse_async_replication_config_reset_case_insensitive():
    assert parse_async_replication_config(("Reset",)) == {}
    assert parse_async_replication_config(("RESET",)) == {}
    assert parse_async_replication_config((" reset ",)) == {}


def test_parse_async_replication_config_reset_with_other_keys():
    with pytest.raises(ValueError, match="Expected key=value"):
        parse_async_replication_config(("reset", "max_workers=10"))


def test_deprecated_async_replication_keys_still_accepted():
    """Deprecated keys must keep parsing, so older servers are not broken."""
    for key in ASYNC_REPLICATION_CONFIG_DEPRECATED_KEYS:
        assert key in ASYNC_REPLICATION_CONFIG_KEYS
        assert parse_async_replication_config((f"{key}=10",)) == {key: 10}


def test_async_replication_help_flags_deprecated_keys():
    assert "Deprecated keys, ignored by Weaviate >= v1.37.3" in (
        ASYNC_REPLICATION_CONFIG_HELP
    )
    for key in ASYNC_REPLICATION_CONFIG_DEPRECATED_KEYS:
        assert key in ASYNC_REPLICATION_CONFIG_HELP


def test_warn_removed_async_replication_keys_on_new_server(capsys):
    client = MagicMock()
    client.get_meta.return_value = {"version": "1.37.3"}

    warn_removed_async_replication_keys(client, {"max_workers": 10})

    captured = capsys.readouterr()
    assert "max_workers removed from the Weaviate server schema in v1.37.3" in (
        captured.out + captured.err
    )


def test_warn_removed_async_replication_keys_lists_all_removed_keys(capsys):
    client = MagicMock()
    client.get_meta.return_value = {"version": "1.38.0"}

    warn_removed_async_replication_keys(
        client, {"max_workers": 10, "alive_nodes_checking_frequency": 30}
    )

    captured = capsys.readouterr()
    assert "alive_nodes_checking_frequency, max_workers removed" in (
        captured.out + captured.err
    )


def test_warn_removed_async_replication_keys_silent_on_old_server(capsys):
    client = MagicMock()
    client.get_meta.return_value = {"version": "1.37.2"}

    warn_removed_async_replication_keys(client, {"max_workers": 10})

    assert capsys.readouterr().out == ""


def test_warn_removed_async_replication_keys_silent_for_supported_keys(capsys):
    client = MagicMock()
    client.get_meta.return_value = {"version": "1.38.0"}

    warn_removed_async_replication_keys(client, {"frequency": 60})

    assert capsys.readouterr().out == ""


def test_warn_removed_async_replication_keys_handles_empty_config(capsys):
    """None (unset) and {} (reset) must not trigger a server version lookup."""
    client = MagicMock()

    warn_removed_async_replication_keys(client, None)
    warn_removed_async_replication_keys(client, {})

    client.get_meta.assert_not_called()
    assert capsys.readouterr().out == ""
