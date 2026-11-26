import json
import sys

import click
from weaviate import WeaviateClient
from weaviate.users.users import OwnUser, UserDB

from weaviate_cli.completion.complete import role_name_complete
from weaviate_cli.defaults import UpdateUserDefaults
from weaviate_cli.managers.user_manager import UserManager
from weaviate_cli.utils import get_client_from_context


@click.group("user")
def user_group() -> None:
    """Manage dynamic RBAC users in Weaviate."""


@user_group.command("create")
@click.argument("user_name")
@click.option(
    "--store",
    is_flag=True,
    help="Store the API key in the config file (requires auth type 'user').",
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def create_user_cli(
    ctx: click.Context, user_name: str, store: bool, json_output: bool
) -> None:
    """Create a dynamic user in Weaviate."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        user_man = UserManager(client)
        api_key = user_man.create_user(user_name=user_name)

        if store:
            config_manager = ctx.obj.get("config")
            if not config_manager:
                click.echo(
                    "Error: --store option requires a config manager in the context."
                )
                return

            config_path = config_manager.config_path
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            if "auth" not in config or config["auth"].get("type") != "user":
                click.echo(
                    "Error: Cannot store API key. Config file must have auth type 'user'."
                )
                return

            config["auth"][user_name] = api_key
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)

            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "success",
                            "user_name": user_name,
                            "api_key": api_key,
                            "stored_at": str(config_path),
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(
                    f"User '{user_name}' created and API key stored in config file at {config_path}"
                )
        else:
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "success",
                            "user_name": user_name,
                            "api_key": api_key,
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(
                    f"User '{user_name}' created successfully in Weaviate with api key: \n{api_key}"
                )
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@user_group.command("list")
@click.option(
    "--role",
    "role_name",
    default=None,
    help="Filter users assigned to a specific role.",
    shell_complete=role_name_complete,
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def list_users_cli(
    ctx: click.Context, role_name: str | None, json_output: bool
) -> None:
    """List all users, or users assigned to a specific role."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        user_man = UserManager(client)
        if role_name:
            users = user_man.get_user_from_role(role_name=role_name)
            if json_output:
                click.echo(
                    json.dumps(
                        {"role": role_name, "users": list(users)},
                        indent=2,
                        default=str,
                    )
                )
            else:
                print(f"Users of role '{role_name}':")
                separator = "-" * 50
                print(f"\n{separator}")
                if len(users) == 0:
                    print(f"No users found for role '{role_name}'.")
                else:
                    for user in users:
                        user_man.print_user(user)
        else:
            users = user_man.get_all_users()
            if json_output:
                users_data = [
                    {
                        "user_id": u.user_id,
                        "active": u.active,
                        "user_type": u.user_type.name,
                        "roles": list(u.role_names),
                    }
                    for u in users
                ]
                click.echo(json.dumps({"users": users_data}, indent=2, default=str))
            else:
                click.echo("Users:")
                for user in users:
                    click.echo("-" * 50)
                    user_man.print_db_user(user)
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@user_group.command("get")
@click.argument("user_name", required=False, default=None)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def get_user_cli(ctx: click.Context, user_name: str | None, json_output: bool) -> None:
    """Get details for a specific user, or the current user if USER_NAME is omitted."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        user_man = UserManager(client)
        if user_name:
            user = user_man.get_user(user_name=user_name)
            assert isinstance(user, UserDB)
            user_man.print_db_user(user, json_output=json_output)
        else:
            user = user_man.get_user()
            assert isinstance(user, OwnUser)
            user_man.print_own_user(user, json_output=json_output)
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@user_group.command("update")
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
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def update_user_cli(
    ctx: click.Context,
    user_name: str,
    rotate_api_key: bool,
    activate: bool,
    deactivate: bool,
    store: bool,
    json_output: bool,
) -> None:
    """Update a user (rotate API key, activate, or deactivate)."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        user_man = UserManager(client)
        api_key = user_man.update_user(
            user_name=user_name,
            rotate_api_key=rotate_api_key,
            activate=activate,
            deactivate=deactivate,
        )

        if rotate_api_key and store and api_key:
            config_manager = ctx.obj.get("config")
            if not config_manager:
                click.echo(
                    "Error: --store option requires a config manager in the context."
                )
                return

            config_path = config_manager.config_path
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            if "auth" not in config or config["auth"].get("type") != "user":
                click.echo(
                    "Error: Cannot store API key. Config file must have auth type 'user'."
                )
                return

            config["auth"][user_name] = api_key
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)

            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "success",
                            "message": f"API key for user '{user_name}' has been rotated and stored in config file at {config_path}",
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(
                    f"API key for user '{user_name}' has been rotated and stored in config file at {config_path}"
                )
        elif rotate_api_key and api_key:
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "success",
                            "message": f"API key for user '{user_name}' rotated successfully.",
                            "api_key": api_key,
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(
                    f"API key for user '{user_name}' rotated successfully: \n{api_key}"
                )
        elif activate:
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "success",
                            "message": f"User '{user_name}' activated successfully.",
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(f"User '{user_name}' activated successfully.")
        elif deactivate:
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "success",
                            "message": f"User '{user_name}' deactivated successfully.",
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(f"User '{user_name}' deactivated successfully.")
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@user_group.command("delete")
@click.argument("user_name")
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def delete_user_cli(ctx: click.Context, user_name: str, json_output: bool) -> None:
    """Delete a dynamic user in Weaviate."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        user_manager = UserManager(client)
        user_manager.delete_user(user_name=user_name)
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "status": "success",
                        "message": f"User '{user_name}' deleted successfully.",
                    },
                    indent=2,
                )
            )
        else:
            click.echo(f"User '{user_name}' deleted successfully.")
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()
