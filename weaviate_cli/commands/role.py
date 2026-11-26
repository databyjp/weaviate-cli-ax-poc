import json
import sys

import click
from weaviate import WeaviateClient
from weaviate.rbac.models import Role

from weaviate_cli.completion.complete import role_name_complete
from weaviate_cli.defaults import PERMISSION_HELP_STRING
from weaviate_cli.managers.role_manager import RoleManager
from weaviate_cli.managers.user_manager import UserManager
from weaviate_cli.utils import get_client_from_context


@click.group("role")
def role_group() -> None:
    """Manage RBAC roles and permissions in Weaviate."""


@role_group.command("create")
@click.argument("role_name", shell_complete=role_name_complete)
@click.option(
    "-p",
    "--permission",
    multiple=True,
    required=True,
    help=PERMISSION_HELP_STRING,
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def create_role_cli(
    ctx: click.Context,
    role_name: str,
    permission: tuple[str, ...],
    json_output: bool,
) -> None:
    """Create an RBAC role with permissions."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        role_man = RoleManager(client)
        role_man.create_role(
            role_name=role_name, permissions=permission, json_output=json_output
        )
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@role_group.command("list")
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
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def list_roles_cli(
    ctx: click.Context,
    user_name: str | None,
    user_type: str,
    mine: bool,
    json_output: bool,
) -> None:
    """List all roles, roles for a specific user, or current user's roles."""
    if mine and user_name:
        raise click.UsageError("Cannot specify both --mine and --user.")

    client: WeaviateClient | None = None
    try:
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

        if len(roles) == 0:
            if json_output:
                click.echo(json.dumps({"roles": []}, indent=2))
            else:
                click.echo("No roles found.")
        elif json_output:
            roles_data = [RoleManager.role_to_dict(role) for role in roles]
            click.echo(json.dumps({"roles": roles_data}, indent=2, default=str))
        else:
            for role in roles:
                role_man.print_role(role)
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@role_group.command("get")
@click.argument("role_name", shell_complete=role_name_complete)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def get_role_cli(ctx: click.Context, role_name: str, json_output: bool) -> None:
    """Get details for a specific role."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        role_man = RoleManager(client)
        role = role_man.get_role(role_name=role_name)
        if role is None:
            raise Exception(f"Role '{role_name}' not found.")
        if json_output:
            click.echo(
                json.dumps(
                    {"roles": [RoleManager.role_to_dict(role)]},
                    indent=2,
                    default=str,
                )
            )
        else:
            role_man.print_role(role)
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@role_group.command("delete")
@click.argument("role_name", shell_complete=role_name_complete)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def delete_role_cli(ctx: click.Context, role_name: str, json_output: bool) -> None:
    """Delete an RBAC role."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        role_manager = RoleManager(client)
        role_manager.delete_role(role_name=role_name, json_output=json_output)
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@role_group.command("assign")
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
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def assign_role_cli(
    ctx: click.Context,
    role_names: tuple[str, ...],
    user_name: str,
    user_type: str,
    json_output: bool,
) -> None:
    """Assign one or more roles to a user."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        user_manager = UserManager(client)
        user_manager.add_role(
            role_name=role_names,
            user_name=user_name,
            user_type=user_type,
            json_output=json_output,
        )
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@role_group.command("revoke")
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
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def revoke_role_cli(
    ctx: click.Context,
    role_names: tuple[str, ...],
    user_name: str,
    user_type: str,
    json_output: bool,
) -> None:
    """Revoke one or more roles from a user."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        user_manager = UserManager(client)
        user_manager.revoke_role(
            role_name=role_names,
            user_name=user_name,
            user_type=user_type,
            json_output=json_output,
        )
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@role_group.command("add-permission")
@click.argument("role_name", shell_complete=role_name_complete)
@click.option(
    "-p",
    "--permission",
    multiple=True,
    required=True,
    help=PERMISSION_HELP_STRING,
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def add_permission_cli(
    ctx: click.Context,
    role_name: str,
    permission: tuple[str, ...],
    json_output: bool,
) -> None:
    """Add one or more permissions to a role."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        role_manager = RoleManager(client)
        role_manager.add_permission(
            permission=permission, role_name=role_name, json_output=json_output
        )
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@role_group.command("revoke-permission")
@click.argument("role_name", shell_complete=role_name_complete)
@click.option(
    "-p",
    "--permission",
    multiple=True,
    required=True,
    help=PERMISSION_HELP_STRING,
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def revoke_permission_cli(
    ctx: click.Context,
    role_name: str,
    permission: tuple[str, ...],
    json_output: bool,
) -> None:
    """Revoke one or more permissions from a role."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        role_manager = RoleManager(client)
        role_manager.revoke_permission(
            permission=permission, role_name=role_name, json_output=json_output
        )
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()
