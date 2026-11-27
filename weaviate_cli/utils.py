"""
Utility functions.
"""

import json
import random
import string
from collections.abc import Callable, Sequence

import click
import semver
import weaviate
from weaviate.rbac.models import Permissions, PermissionsCreateType, RoleScope


def get_client_from_context(ctx: click.Context) -> weaviate.WeaviateClient:
    """
        Get Configuration object from the specified file.
    :param ctx:
    :return:
    :rtype: semi.config.configuration.Configuration
    """
    return ctx.obj["config"].get_client()


def get_async_client_from_context(ctx: click.Context) -> weaviate.WeaviateAsyncClient:
    """
    Get asynchronous client from context.
    """
    return ctx.obj["config"].get_async_client()


# Insert objects to the replicated collection
def get_random_string(length):
    # choose from all lowercase letter
    letters = string.ascii_lowercase
    result_str = "".join(random.choice(letters) for i in range(length))
    return result_str


def print_json_or_text(
    data: object, json_output: bool, text_fn: Callable[[], None]
) -> None:
    """Output data as JSON or formatted text.

    Args:
        data: The data to serialize when json_output is True.
        json_output: If True, emit JSON to stdout; otherwise call text_fn().
        text_fn: A callable that prints the human-readable representation.
    """
    if json_output:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        text_fn()


ASYNC_REPLICATION_CONFIG_KEYS = {
    "max_workers",
    "hashtree_height",
    "frequency",
    "frequency_while_propagating",
    "alive_nodes_checking_frequency",
    "logging_frequency",
    "diff_batch_size",
    "diff_per_node_timeout",
    "pre_propagation_timeout",
    "propagation_timeout",
    "propagation_limit",
    "propagation_delay",
    "propagation_concurrency",
    "propagation_batch_size",
}


# Removed from the Weaviate server schema in v1.37.3. Still accepted by the CLI so
# that users targeting older servers are not broken, but ignored by newer servers.
ASYNC_REPLICATION_CONFIG_DEPRECATED_KEYS = {
    "max_workers",
    "alive_nodes_checking_frequency",
}

ASYNC_REPLICATION_CONFIG_REMOVED_VERSION = "1.37.3"

ASYNC_REPLICATION_CONFIG_RESET = "reset"

ASYNC_REPLICATION_CONFIG_HELP = (
    "Async replication config as key=value pairs. Can be specified multiple times. "
    "Valid keys: " + ", ".join(sorted(ASYNC_REPLICATION_CONFIG_KEYS)) + ". "
    "All values must be integers. "
    'Use "reset" to revert all async replication settings to server defaults (update only). '
    "Requires --async-enabled on create and Weaviate >= v1.36.0. "
    "Deprecated keys, ignored by Weaviate >= v"
    + ASYNC_REPLICATION_CONFIG_REMOVED_VERSION
    + ": "
    + ", ".join(sorted(ASYNC_REPLICATION_CONFIG_DEPRECATED_KEYS))
    + "."
)


def parse_async_replication_config(
    config_tuples: tuple | None,
) -> dict | None:
    """Parse async replication config key=value tuples into a dict.

    Args:
        config_tuples: Tuple of "key=value" strings, e.g. ("max_workers=10", "frequency=60"),
            or a single "reset" to revert all settings to server defaults.

    Returns:
        Dict mapping parameter names to integer values, empty dict for "reset",
        or None if empty/None.

    Raises:
        ValueError: If a key is unknown or a value is not a valid integer.
    """
    if not config_tuples:
        return None

    if (
        len(config_tuples) == 1
        and config_tuples[0].strip().lower() == ASYNC_REPLICATION_CONFIG_RESET
    ):
        return {}

    result = {}
    for item in config_tuples:
        if "=" not in item:
            raise ValueError(
                f"Invalid async replication config format: '{item}'. Expected key=value."
            )
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()

        if key not in ASYNC_REPLICATION_CONFIG_KEYS:
            raise ValueError(
                f"Unknown async replication config key: '{key}'. "
                f"Valid keys: {', '.join(sorted(ASYNC_REPLICATION_CONFIG_KEYS))}"
            )

        try:
            result[key] = int(value)
        except ValueError:
            raise ValueError(
                f"Invalid value for '{key}': '{value}'. Must be an integer."
            )

    return result


def warn_removed_async_replication_keys(
    client, async_replication_config: dict | None
) -> None:
    """Warn when async replication keys the target server no longer supports are used.

    ``max_workers`` and ``alive_nodes_checking_frequency`` were removed from the
    Weaviate server schema in v1.37.3 and are silently ignored from that version on.
    They remain accepted here so that users targeting older servers keep working.
    """
    if not async_replication_config:
        return

    removed = sorted(
        ASYNC_REPLICATION_CONFIG_DEPRECATED_KEYS & set(async_replication_config)
    )
    if not removed or older_than_version(
        client, ASYNC_REPLICATION_CONFIG_REMOVED_VERSION
    ):
        return

    click.echo(
        f"Warning: {', '.join(removed)} removed from the Weaviate server schema in "
        f"v{ASYNC_REPLICATION_CONFIG_REMOVED_VERSION}. "
        "This server will ignore these settings.",
        err=True,
    )


def parse_permission(perm: str) -> PermissionsCreateType:
    """
    Convert a permission string to RBAC permission object(s).
    Format: action[:target[:subtarget]]

    Supports:
    - CRUD shorthand: crud_collections:Articles, cr_data:Articles:tenant-a
    - Role permissions: create_roles, read_roles, update_roles, delete_roles[:role[:all|match]]
    - Cluster permissions: read_cluster
    - Backup permissions: manage_backups[:collection], read_backups[:collection]
    - Collections permissions: create_collections, read_collections, update_collections, delete_collections[:collection]
    - Tenants permissions: create_tenants, read_tenants, update_tenants, delete_tenants[:collection[:tenant]]
    - Data permissions: create_data, read_data, update_data, delete_data[:collection[:tenant]]
    - Users permissions: create_users, read_users, update_users, delete_users, assign_and_revoke_users[:user]
    - Groups (OIDC) permissions: read_groups, assign_and_revoke_groups[:group[:oidc]]
    - Nodes permissions: read_nodes[:minimal|verbose[:collection]]
    - Aliases permissions: create_aliases, read_aliases, update_aliases, delete_aliases[:collection[:alias]]
    - Replicate permissions: create_replicate, read_replicate, update_replicate, delete_replicate[:collection[:shard]]
    - MCP permissions: create_mcp, read_mcp, update_mcp (or c/r/u shorthands like cru_mcp)
    Args:
        perm (str): Permission string

    Returns:
        PermissionsCreateType: Single permission or list for crud/partial crud
    """
    valid_resources = [
        "collections",
        "data",
        "roles",
        "tenants",
        "users",
        "groups",
        "cluster",
        "backups",
        "nodes",
        "aliases",
        "replicate",
        "mcp",
    ]
    crud_resources = [
        "collections",
        "data",
        "tenants",
        "roles",
        "users",
        "aliases",
        "replicate",
    ]
    three_part_resources = {
        "roles",
        "tenants",
        "aliases",
        "data",
        "replicate",
        "groups",
    }
    parts = perm.split(":")
    action = parts[0]
    action_resource = action.split("_")[-1]

    if action_resource == "mcp" and len(parts) > 1:
        raise ValueError(
            f"Invalid permission format: {perm}. MCP permissions do not accept a target subfield; "
            "use e.g. 'read_mcp', 'create_mcp', 'update_mcp', or 'cru_mcp'."
        )
    if action == "read_cluster" and len(parts) > 1:
        raise ValueError(
            f"Invalid permission format: {perm}. 'read_cluster' does not accept a target subfield."
        )

    if len(parts) > 3 or (
        (action_resource not in three_part_resources and action != "read_nodes")
        and len(parts) > 2
    ):
        raise ValueError(
            f"Invalid permission format: {perm}. Expected format: "
            "action[:collection/role/user/group/verbosity[:scope/tenant/alias/shard]]. "
            "Examples: create_roles:custom:all, crud_collections:Articles, "
            "read_data:Articles:tenant1, crud_replicate:Articles:shard1, "
            "read_groups:admins, read_backups:Articles, cru_mcp, "
            "read_nodes:verbose:Articles, read_tenants:Articles:tenant1, "
            "read_aliases:Articles:alias1"
        )

    role = parts[1] if len(parts) > 1 and action_resource == "roles" else "*"
    role_scope = parts[2] if len(parts) > 2 and action_resource == "roles" else None
    tenant = (
        parts[2].split(",")
        if len(parts) > 2 and action_resource in {"tenants", "data"}
        else None
    )
    shard = (
        parts[2].split(",")
        if len(parts) > 2 and action_resource == "replicate"
        else None
    )
    alias = (
        parts[2].split(",") if len(parts) > 2 and action_resource == "aliases" else "*"
    )
    user = parts[1].split(",") if len(parts) > 1 and action_resource == "users" else "*"
    group = (
        parts[1].split(",") if len(parts) > 1 and action_resource == "groups" else "*"
    )
    group_type = parts[2] if len(parts) > 2 and action_resource == "groups" else "oidc"

    verbosity = "minimal"
    if action == "read_nodes":
        # Handle read_nodes format: read_nodes:verbosity:collection
        if len(parts) > 1:
            if parts[1] not in ["minimal", "verbose"]:
                raise ValueError("Input should be 'minimal' or 'verbose'")
            verbosity = parts[1] if parts[1] == "verbose" else "minimal"
        collection = parts[2] if len(parts) > 2 else "*"
    else:
        non_collection_resources = {"roles", "users", "groups", "cluster", "mcp"}
        collection = (
            parts[1]
            if len(parts) > 1 and action_resource not in non_collection_resources
            else "*"
        )

    # Split collections and roles by comma if they exist
    collection = collection.split(",") if collection != "*" else ["*"]
    role = role.split(",") if role != "*" else ["*"]

    # Handle standalone permissions first
    if action in [
        "read_cluster",
        "manage_backups",
        "read_backups",
        "read_nodes",
        "assign_and_revoke_users",
        "read_groups",
        "assign_and_revoke_groups",
    ]:
        if action in {"assign_and_revoke_users", "assign_and_revoke_groups"}:
            standalone_action = "assign_and_revoke"
        else:
            standalone_action = action.split("_")[0]
        return _create_permission(
            action=standalone_action,
            resource=action_resource,
            user=user,
            group=group,
            group_type=group_type,
            collection=collection,
            verbosity=verbosity,
        )

    # Handle MCP permissions (create, read, update; no delete)
    if "_" in action and action_resource == "mcp":
        prefix = action.rsplit("_", 1)[0]
        mcp_action_map = {"c": "create", "r": "read", "u": "update"}
        if prefix in ["create", "read", "update"]:
            mcp_actions = [prefix]
        elif prefix == "delete" or "d" in prefix:
            raise ValueError(
                f"Invalid MCP permission action: {action}. "
                "MCP permissions support only 'create', 'read', and 'update' (e.g. read_mcp, cru_mcp)."
            )
        elif prefix and all(c in mcp_action_map for c in prefix):
            mcp_actions = [mcp_action_map[c] for c in prefix]
        else:
            raise ValueError(f"Invalid MCP permission combination: {prefix}")
        return _create_permission(action=mcp_actions, resource="mcp")

    # Handle crud and partial crud cases
    if "_" in action:
        action_parts = action.split("_", 2)
        prefix = action_parts[0]
        resource = action_parts[1] if len(action_parts) > 1 else None
        if resource in crud_resources:
            if resource not in valid_resources:
                # Find closest matching resource type
                closest = min(
                    valid_resources,
                    key=lambda x: (
                        sum(c1 != c2 for c1, c2 in zip(x, resource))
                        if len(x) == len(resource)
                        else abs(len(x) - len(resource))
                    ),
                )
                suggestion = f"\nDid you mean '{closest}'?" if closest else ""
                raise ValueError(f"Invalid resource type: {resource}. {suggestion}")

            action_map = {"c": "create", "r": "read", "u": "update", "d": "delete"}

            if prefix in ["create", "read", "update", "delete"]:
                actions = [prefix]
            else:
                # Handle partial crud (curd, cr, ru, ud, etc)
                if not all(c in action_map for c in prefix):
                    raise ValueError(f"Invalid crud combination: {prefix}")
                actions = [action_map[c] for c in prefix]

            return _create_permission(
                action=actions,
                resource=resource,
                collection=collection,
                tenant=tenant if tenant is not None else "*",
                shard=shard if shard is not None else "*",
                alias=alias,
                role=role,
                role_scope=role_scope,
                user=user,
            )

    raise ValueError(f"Invalid permission action: {action}")


def _create_permission(
    action: str | Sequence[str],
    resource: str,
    role: str | Sequence[str] = "*",
    role_scope: str | None = None,
    user: str | Sequence[str] = "*",
    group: str | Sequence[str] = "*",
    group_type: str = "oidc",
    collection: str | Sequence[str] = "*",
    tenant: str | Sequence[str] = "*",
    shard: str | Sequence[str] = "*",
    alias: str | Sequence[str] = "*",
    verbosity: str = "minimal",
) -> PermissionsCreateType:
    """Helper function to create individual RBAC permission objects."""
    action_set = {action} if isinstance(action, str) else set(action)

    # Handle standalone permissions
    if resource == "cluster":
        return Permissions.cluster(read=True)
    elif resource == "backups":
        return Permissions.backup(
            collection=collection,
            read=("read" in action_set),
            manage=("manage" in action_set),
        )
    elif resource == "mcp":
        return Permissions.mcp(
            create=("create" in action_set),
            read=("read" in action_set),
            update=("update" in action_set),
        )
    elif resource == "groups":
        if group_type != "oidc":
            raise ValueError(f"Unsupported group type '{group_type}'. Expected 'oidc'.")
        return Permissions.Groups.oidc(
            group=group,
            read=("read" in action_set),
            assign_and_revoke=("assign_and_revoke" in action_set),
        )
    elif resource == "nodes":
        if verbosity == "minimal":
            if collection not in ("*", ["*"]):
                click.echo(
                    f"Warning: Collection is not supported for minimal verbosity. Ignoring collection: {collection}",
                    err=True,
                )
            return Permissions.Nodes.minimal(read=True)
        else:
            return Permissions.Nodes.verbose(collection=collection, read=True)
    elif resource == "users":
        return Permissions.users(
            user=user,
            create=("create" in action_set),
            read=("read" in action_set),
            update=("update" in action_set),
            delete=("delete" in action_set),
            assign_and_revoke=("assign_and_revoke" in action_set),
        )
    # Handle roles permissions
    elif resource == "roles":
        roles_scope_map = {
            "all": RoleScope.ALL,
            "match": RoleScope.MATCH,
        }
        scope = None
        if role_scope:
            if role_scope not in roles_scope_map:
                raise ValueError(
                    f"Invalid role scope: {role_scope}, expected one of: {', '.join(roles_scope_map.keys())}"
                )
            scope = roles_scope_map[role_scope]

        return Permissions.roles(
            role=role,
            read=("read" in action_set),
            update=("update" in action_set),
            delete=("delete" in action_set),
            create=("create" in action_set),
            scope=scope,
        )

    # Handle schema permissions
    elif resource == "collections":
        return Permissions.collections(
            collection=collection,
            create_collection=("create" in action_set),
            read_config=("read" in action_set),
            update_config=("update" in action_set),
            delete_collection=("delete" in action_set),
        )

    # Handle data permissions
    elif resource == "data":
        return Permissions.data(
            collection=collection,
            tenant=tenant,
            create=("create" in action_set),
            read=("read" in action_set),
            update=("update" in action_set),
            delete=("delete" in action_set),
        )

    # Handle tenants permissions
    elif resource == "tenants":
        return Permissions.tenants(
            tenant=tenant,
            collection=collection,
            create=("create" in action_set),
            read=("read" in action_set),
            update=("update" in action_set),
            delete=("delete" in action_set),
        )
    # Handle aliases permissions
    elif resource == "aliases":
        return Permissions.alias(
            alias=alias,
            collection=collection,
            create=("create" in action_set),
            read=("read" in action_set),
            update=("update" in action_set),
            delete=("delete" in action_set),
        )
    # Handle replication permissions
    elif resource == "replicate":
        return Permissions.replicate(
            collection=collection,
            shard=shard,
            create=("create" in action_set),
            read=("read" in action_set),
            update=("update" in action_set),
            delete=("delete" in action_set),
        )
    raise ValueError(f"Invalid permission action: {action}.")


def older_than_version(client, minimum_version):
    client_version = client.get_meta()["version"]
    if "-" in client_version:
        client_version = client_version.split("-")[0]
    return is_version_older_than(client_version, minimum_version)


def is_version_older_than(version, check_version):
    if (
        semver.Version.compare(
            semver.Version.parse(version), semver.Version.parse(check_version)
        )
        < 0
    ):
        return True
    return False
