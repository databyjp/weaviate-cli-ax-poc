"""Click commands for the 'user' resource group."""

from __future__ import annotations

import json
from typing import Any

import click
from weaviate import WeaviateClient
from weaviate.users.users import OwnUser, UserDB

from weaviate_cli.completion.complete import role_name_complete
from weaviate_cli.defaults import UpdateUserDefaults
from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.managers.user_manager import UserManager
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    emit_success,
    get_runtime,
    handle_command_error,
    require_confirmation,
)
from weaviate_cli.utils import get_client_from_context


def _store_user_api_key(ctx: click.Context, user_name: str, api_key: str) -> str:
    config_manager = ctx.obj.get("config") if isinstance(ctx.obj, dict) else None
    if not config_manager:
        raise CLIError(
            code="CONFIG_UNAVAILABLE",
            message="--store option requires a config manager in the context.",
            exit_code=ExitCode.USAGE,
        )
    config_path = config_manager.config_path
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    if "auth" not in config or config["auth"].get("type") != "user":
        raise CLIError(
            code="INVALID_CONFIG",
            message="Cannot store API key: config file must have auth type 'user'.",
            exit_code=ExitCode.USAGE,
        )
    config["auth"][user_name] = api_key
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)
    return str(config_path)


@click.group("user", context_settings=DEFAULT_CONTEXT_SETTINGS)
def user_group() -> None:
    """Manage dynamic RBAC users in Weaviate."""


@user_group.command("create", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("user_name")
@click.option(
    "--store",
    is_flag=True,
    help="Store the API key in the config file (requires auth type 'user').",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def create_user_cli(
    ctx: click.Context, user_name: str, store: bool, json_output: bool | None
) -> None:
    """Create a dynamic user in Weaviate."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "user create"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        user_man = UserManager(client)
        api_key = user_man.create_user(user_name=user_name)

        payload: dict[str, Any] = {
            "status": "success",
            "user_name": user_name,
            "api_key": api_key,
        }
        stored_at: str | None = None
        if store:
            stored_at = _store_user_api_key(ctx, user_name, api_key)
            payload["stored_at"] = stored_at

        def _render_text() -> None:
            if stored_at:
                click.echo(
                    f"User '{user_name}' created and API key stored in config file at {stored_at}"
                )
            else:
                click.echo(
                    f"User '{user_name}' created successfully in Weaviate with api key: \n{api_key}"
                )

        emit_success(runtime, payload, command=command, text_renderer=_render_text)
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@user_group.command("list", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option(
    "--role",
    "role_name",
    default=None,
    help="Filter users assigned to a specific role.",
    shell_complete=role_name_complete,
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def list_users_cli(
    ctx: click.Context, role_name: str | None, json_output: bool | None
) -> None:
    """List all users, or users assigned to a specific role."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "user list"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        user_man = UserManager(client)
        if role_name:
            users = user_man.get_user_from_role(role_name=role_name)
            payload: dict[str, Any] = {"role": role_name, "users": list(users)}

            def _render_role_users() -> None:
                click.echo(f"Users of role '{role_name}':")
                separator = "-" * 50
                click.echo(f"\n{separator}")
                if not users:
                    click.echo(f"No users found for role '{role_name}'.")
                else:
                    for user in users:
                        user_man.print_user(user)

            emit_success(
                runtime, payload, command=command, text_renderer=_render_role_users
            )
        else:
            db_users = user_man.get_all_users()
            users_data = [
                {
                    "user_id": u.user_id,
                    "active": u.active,
                    "user_type": u.user_type.name,
                    "roles": list(u.role_names),
                }
                for u in db_users
            ]

            def _render_all_users() -> None:
                click.echo("Users:")
                for user in db_users:
                    click.echo("-" * 50)
                    user_man.print_db_user(user)

            emit_success(
                runtime,
                {"users": users_data},
                command=command,
                text_renderer=_render_all_users,
            )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@user_group.command("get", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("user_name", required=False, default=None)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def get_user_cli(
    ctx: click.Context, user_name: str | None, json_output: bool | None
) -> None:
    """Get details for a specific user, or the current user if USER_NAME is omitted."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "user get"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        user_man = UserManager(client)
        if user_name:
            user = user_man.get_user(user_name=user_name)
            if user is None:
                raise CLIError(
                    code="USER_NOT_FOUND",
                    message=f"User '{user_name}' not found.",
                    exit_code=ExitCode.NOT_FOUND,
                    hint="Run 'weaviate-cli user list' to see existing users.",
                )
            assert isinstance(user, UserDB)
            data = {
                "user_id": user.user_id,
                "active": user.active,
                "user_type": user.user_type.name,
                "roles": list(user.role_names),
            }
            emit_success(
                runtime,
                data,
                command=command,
                text_renderer=lambda: user_man.print_db_user(user, json_output=False),
            )
        else:
            own_user = user_man.get_user()
            assert isinstance(own_user, OwnUser)
            data = {
                "user_id": own_user.user_id,
                "roles": list(own_user.roles.keys()),
            }
            emit_success(
                runtime,
                data,
                command=command,
                text_renderer=lambda: user_man.print_own_user(
                    own_user, json_output=False
                ),
            )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@user_group.command("update", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("user_name")
@click.option(
    "--rotate-api-key",
    is_flag=True,
    default=UpdateUserDefaults.rotate_api_key,
    help="Rotate the API key for the user.",
)
@click.option(
    "--activate",
    is_flag=True,
    default=UpdateUserDefaults.activate,
    help="Activate the user.",
)
@click.option(
    "--deactivate",
    is_flag=True,
    default=UpdateUserDefaults.deactivate,
    help="Deactivate the user.",
)
@click.option(
    "--store",
    is_flag=True,
    help="Store the rotated API key in the config file (requires auth type 'user' and --rotate-api-key).",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def update_user_cli(
    ctx: click.Context,
    user_name: str,
    rotate_api_key: bool,
    activate: bool,
    deactivate: bool,
    store: bool,
    json_output: bool | None,
) -> None:
    """Update a user (rotate API key, activate, or deactivate)."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "user update"
    client: WeaviateClient | None = None
    try:
        if not (rotate_api_key or activate or deactivate):
            raise CLIError(
                code="MISSING_ACTION",
                message="Specify one of --rotate-api-key, --activate, or --deactivate.",
                exit_code=ExitCode.USAGE,
            )

        client = get_client_from_context(ctx)
        user_man = UserManager(client)
        result = user_man.update_user(
            user_name=user_name,
            rotate_api_key=rotate_api_key,
            activate=activate,
            deactivate=deactivate,
        )

        if rotate_api_key and isinstance(result, str):
            if store:
                stored_at = _store_user_api_key(ctx, user_name, result)
                msg = f"API key for user '{user_name}' has been rotated and stored in config file at {stored_at}"
                emit_success(
                    runtime,
                    {
                        "status": "success",
                        "user_name": user_name,
                        "stored_at": stored_at,
                        "message": msg,
                    },
                    command=command,
                    text_renderer=lambda: click.echo(msg),
                )
            else:
                msg = f"API key for user '{user_name}' rotated successfully."
                emit_success(
                    runtime,
                    {
                        "status": "success",
                        "user_name": user_name,
                        "api_key": result,
                        "message": msg,
                    },
                    command=command,
                    text_renderer=lambda: click.echo(f"{msg}\n{result}"),
                )
        elif activate:
            msg = f"User '{user_name}' activated successfully."
            emit_success(
                runtime,
                {
                    "status": "success",
                    "user_name": user_name,
                    "active": True,
                    "message": msg,
                },
                command=command,
                text_renderer=lambda: click.echo(msg),
            )
        elif deactivate:
            msg = f"User '{user_name}' deactivated successfully."
            emit_success(
                runtime,
                {
                    "status": "success",
                    "user_name": user_name,
                    "active": False,
                    "message": msg,
                },
                command=command,
                text_renderer=lambda: click.echo(msg),
            )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@user_group.command("delete", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("user_name")
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm deleting the dynamic user.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def delete_user_cli(
    ctx: click.Context, user_name: str, yes: bool, json_output: bool | None
) -> None:
    """Delete a dynamic user in Weaviate (requires --yes)."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "user delete"
    require_confirmation(
        runtime,
        yes=yes,
        command=command,
        message=f"Deleting dynamic user '{user_name}' is destructive and requires --yes.",
        hint=f"Re-run with 'weaviate-cli user delete {user_name} --yes' after confirming.",
    )

    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        user_manager = UserManager(client)
        user_manager.delete_user(user_name=user_name)
        msg = f"User '{user_name}' deleted successfully."
        emit_success(
            runtime,
            {"status": "success", "user_name": user_name, "message": msg},
            command=command,
            text_renderer=lambda: click.echo(msg),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()
