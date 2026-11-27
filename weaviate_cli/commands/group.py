"""Click commands for the 'group' (OIDC RBAC) resource group."""

from __future__ import annotations

import json
from typing import Any

import click
from weaviate import WeaviateClient

from weaviate_cli.completion.complete import role_name_complete
from weaviate_cli.managers.group_manager import GroupManager
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    AXGroup,
    emit_success,
    get_runtime,
    handle_command_error,
)
from weaviate_cli.utils import get_client_from_context


@click.group("group", cls=AXGroup)
def group_group() -> None:
    """Manage OIDC group RBAC role assignments in Weaviate."""


@group_group.command(
    "list",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli group list\n"
        "  weaviate-cli group list --role viewer"
    ),
)
@click.option(
    "--role",
    "role_name",
    default=None,
    help="List groups assigned to a specific RBAC role.",
    shell_complete=role_name_complete,
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def list_groups_cli(
    ctx: click.Context,
    role_name: str | None,
    json_output: bool | None,
) -> None:
    """List known OIDC groups, or groups assigned to a specific role."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "group list"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        group_man = GroupManager(client)
        if role_name:
            assignments = group_man.get_groups_for_role(role_name)
            payload: dict[str, Any] = {
                "role": role_name,
                "groups": assignments,
                "total": len(assignments),
            }

            def _render_role_groups() -> None:
                if not assignments:
                    click.echo(f"No groups assigned to role '{role_name}'.")
                    return
                click.echo(f"Groups assigned to role '{role_name}':")
                for item in assignments:
                    click.echo(f"  - {item['group_id']} ({item['group_type']})")

            emit_success(
                runtime, payload, command=command, text_renderer=_render_role_groups
            )
        else:
            groups = group_man.list_known_groups()
            payload = {"groups": groups, "total": len(groups)}

            def _render_all_groups() -> None:
                if not groups:
                    click.echo("No OIDC groups found.")
                    return
                click.echo("OIDC Groups:")
                for gid in groups:
                    click.echo(f"  - {gid}")

            emit_success(
                runtime, payload, command=command, text_renderer=_render_all_groups
            )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@group_group.command(
    "get",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli group get engineering\n"
        "  weaviate-cli group get engineering --include-permissions"
    ),
)
@click.argument("group_id")
@click.option(
    "--include-permissions",
    is_flag=True,
    default=False,
    help="Include full permissions for each role assigned to the group.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def get_group_cli(
    ctx: click.Context,
    group_id: str,
    include_permissions: bool,
    json_output: bool | None,
) -> None:
    """Get RBAC roles assigned to an OIDC group."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "group get"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        group_man = GroupManager(client)
        data = group_man.get_group_roles(
            group_id, include_permissions=include_permissions
        )

        def _render_group() -> None:
            click.echo(f"Group: {data['group_id']} ({data['group_type']})")
            roles = data["roles"]
            if not roles:
                click.echo("Roles: none")
            elif include_permissions:
                click.echo(json.dumps(roles, indent=2))
            else:
                click.echo("Roles:")
                for role in roles:
                    click.echo(f"  - {role}")

        emit_success(runtime, data, command=command, text_renderer=_render_group)
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@group_group.command(
    "assign-role",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli group assign-role engineering --role viewer --role mcp-agent"
    ),
)
@click.argument("group_id")
@click.option(
    "--role",
    "role_names",
    multiple=True,
    required=True,
    help="Role name to assign to the OIDC group (repeatable).",
    shell_complete=role_name_complete,
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def assign_group_role_cli(
    ctx: click.Context,
    group_id: str,
    role_names: tuple[str, ...],
    json_output: bool | None,
) -> None:
    """Assign one or more RBAC roles to an OIDC group."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "group assign-role"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        result = GroupManager(client).assign_roles(group_id, role_names)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: click.echo(result["message"]),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@group_group.command(
    "revoke-role",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\nExamples:\n  weaviate-cli group revoke-role engineering --role viewer"
    ),
)
@click.argument("group_id")
@click.option(
    "--role",
    "role_names",
    multiple=True,
    required=True,
    help="Role name to revoke from the OIDC group (repeatable).",
    shell_complete=role_name_complete,
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def revoke_group_role_cli(
    ctx: click.Context,
    group_id: str,
    role_names: tuple[str, ...],
    json_output: bool | None,
) -> None:
    """Revoke one or more RBAC roles from an OIDC group."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "group revoke-role"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        result = GroupManager(client).revoke_roles(group_id, role_names)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: click.echo(result["message"]),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()
