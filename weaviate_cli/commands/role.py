"""Click commands for the 'role' resource group."""

from __future__ import annotations

import click
from weaviate import WeaviateClient
from weaviate.rbac.models import Role

from weaviate_cli.completion.complete import role_name_complete
from weaviate_cli.defaults import PERMISSION_HELP_STRING
from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.managers.role_manager import RoleManager
from weaviate_cli.managers.user_manager import UserManager
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    AXGroup,
    emit_captured_json_or_text,
    emit_success,
    get_runtime,
    handle_command_error,
    require_confirmation,
)
from weaviate_cli.utils import get_client_from_context


@click.group("role", cls=AXGroup)
def role_group() -> None:
    """Manage RBAC roles and permissions in Weaviate."""


@role_group.command(
    "create",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli role create reader -p read_collections:* -p read_data:*\n"
        "  weaviate-cli role create articles-rw -p crud_data:Articles"
    ),
)
@click.argument("role_name", shell_complete=role_name_complete)
@click.option(
    "-p",
    "--permission",
    multiple=True,
    required=True,
    help=PERMISSION_HELP_STRING,
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def create_role_cli(
    ctx: click.Context,
    role_name: str,
    permission: tuple[str, ...],
    json_output: bool | None,
) -> None:
    """Create an RBAC role with permissions."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "role create"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        role_man = RoleManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: role_man.create_role(
                role_name=role_name, permissions=permission, json_output=as_json
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@role_group.command("list", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option(
    "--user",
    "user_name",
    default=None,
    help="List roles assigned to a specific user.",
)
@click.option(
    "--user-type",
    type=click.Choice(["db", "oidc"]),
    default="db",
    help="Type of user when --user is specified (default: 'db').",
)
@click.option(
    "--mine",
    is_flag=True,
    help="List roles assigned to the current authenticated user.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def list_roles_cli(
    ctx: click.Context,
    user_name: str | None,
    user_type: str,
    mine: bool,
    json_output: bool | None,
) -> None:
    """List all roles, roles for a specific user, or current user's roles."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "role list"
    client: WeaviateClient | None = None
    try:
        if mine and user_name:
            raise CLIError(
                code="CONFLICTING_OPTIONS",
                message="Cannot specify both --mine and --user.",
                exit_code=ExitCode.USAGE,
            )

        client = get_client_from_context(ctx)
        role_man = RoleManager(client)
        roles: list[Role] = []
        if mine:
            roles = list(role_man.role_of_current_user().values())
        elif user_name:
            role_names = role_man.get_roles_from_user(
                user_name=user_name, user_type=user_type
            ).keys()
            for r_name in role_names:
                role = role_man.get_role(role_name=r_name)
                if role is not None:
                    roles.append(role)
        else:
            roles = list(role_man.get_all_roles().values())

        roles_data = [RoleManager.role_to_dict(role) for role in roles]

        def _render_text() -> None:
            if not roles:
                click.echo("No roles found.")
                return
            for role in roles:
                role_man.print_role(role)

        emit_success(
            runtime,
            {"roles": roles_data},
            command=command,
            text_renderer=_render_text,
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@role_group.command("get", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("role_name", shell_complete=role_name_complete)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def get_role_cli(ctx: click.Context, role_name: str, json_output: bool | None) -> None:
    """Get details for a specific role."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "role get"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        role_man = RoleManager(client)
        role = role_man.get_role(role_name=role_name)
        if role is None:
            raise CLIError(
                code="ROLE_NOT_FOUND",
                message=f"Role '{role_name}' not found.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli role list' to see existing roles.",
            )
        emit_success(
            runtime,
            RoleManager.role_to_dict(role),
            command=command,
            text_renderer=lambda: role_man.print_role(role),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@role_group.command("delete", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("role_name", shell_complete=role_name_complete)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm deleting the RBAC role.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def delete_role_cli(
    ctx: click.Context, role_name: str, yes: bool, json_output: bool | None
) -> None:
    """Delete an RBAC role (requires --yes)."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "role delete"
    require_confirmation(
        runtime,
        yes=yes,
        command=command,
        message=f"Deleting RBAC role '{role_name}' is destructive and requires --yes.",
        hint=f"Re-run with 'weaviate-cli role delete {role_name} --yes' after confirming.",
    )

    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        role_manager = RoleManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: role_manager.delete_role(
                role_name=role_name, json_output=as_json
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@role_group.command("assign", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option(
    "--role",
    "role_names",
    multiple=True,
    required=True,
    help="Role name to assign (repeatable).",
    shell_complete=role_name_complete,
)
@click.option(
    "--user",
    "user_name",
    required=True,
    help="User to assign the role(s) to.",
)
@click.option(
    "--user-type",
    type=click.Choice(["db", "oidc"]),
    default="db",
    help="Type of user (default: 'db').",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def assign_role_cli(
    ctx: click.Context,
    role_names: tuple[str, ...],
    user_name: str,
    user_type: str,
    json_output: bool | None,
) -> None:
    """Assign one or more roles to a user."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "role assign"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        user_manager = UserManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: user_manager.add_role(
                role_name=role_names,
                user_name=user_name,
                user_type=user_type,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@role_group.command("revoke", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option(
    "--role",
    "role_names",
    multiple=True,
    required=True,
    help="Role name to revoke (repeatable).",
    shell_complete=role_name_complete,
)
@click.option(
    "--user",
    "user_name",
    required=True,
    help="User to revoke the role(s) from.",
)
@click.option(
    "--user-type",
    type=click.Choice(["db", "oidc"]),
    default="db",
    help="Type of user (default: 'db').",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def revoke_role_cli(
    ctx: click.Context,
    role_names: tuple[str, ...],
    user_name: str,
    user_type: str,
    json_output: bool | None,
) -> None:
    """Revoke one or more roles from a user."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "role revoke"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        user_manager = UserManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: user_manager.revoke_role(
                role_name=role_names,
                user_name=user_name,
                user_type=user_type,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@role_group.command("add-permission", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("role_name", shell_complete=role_name_complete)
@click.option(
    "-p",
    "--permission",
    multiple=True,
    required=True,
    help=PERMISSION_HELP_STRING,
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def add_permission_cli(
    ctx: click.Context,
    role_name: str,
    permission: tuple[str, ...],
    json_output: bool | None,
) -> None:
    """Add one or more permissions to a role."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "role add-permission"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        role_manager = RoleManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: role_manager.add_permission(
                permission=permission, role_name=role_name, json_output=as_json
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@role_group.command("revoke-permission", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("role_name", shell_complete=role_name_complete)
@click.option(
    "-p",
    "--permission",
    multiple=True,
    required=True,
    help=PERMISSION_HELP_STRING,
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def revoke_permission_cli(
    ctx: click.Context,
    role_name: str,
    permission: tuple[str, ...],
    json_output: bool | None,
) -> None:
    """Revoke one or more permissions from a role."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "role revoke-permission"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        role_manager = RoleManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: role_manager.revoke_permission(
                permission=permission, role_name=role_name, json_output=as_json
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()
