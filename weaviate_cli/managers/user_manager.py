from __future__ import annotations

import json
from typing import Any

import click
from weaviate import WeaviateClient
from weaviate.users.users import OwnUser, UserDB

from weaviate_cli.defaults import (
    GetUserDefaults,
)
from weaviate_cli.utils import older_than_version


def _format_optional_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def db_user_to_dict(user: UserDB) -> dict[str, Any]:
    """Serialize a UserDB object including lifecycle audit metadata."""
    data: dict[str, Any] = {
        "user_id": user.user_id,
        "active": user.active,
        "user_type": user.user_type.name,
        "roles": list(user.role_names),
    }
    created_at = _format_optional_timestamp(getattr(user, "created_at", None))
    last_used = _format_optional_timestamp(getattr(user, "last_used_time", None))
    key_prefix = getattr(user, "api_key_first_letters", None)
    if created_at is not None:
        data["created_at"] = created_at
    if last_used is not None:
        data["last_used_time"] = last_used
    if key_prefix is not None:
        data["api_key_first_letters"] = key_prefix
    return data


class UserManager:
    def __init__(self, client: WeaviateClient):
        self.client = client

    def get_user_from_role(
        self, role_name: str | None = GetUserDefaults.role_name
    ) -> list[str]:
        """Get all users assigned to a role."""
        if role_name is None:
            raise ValueError("Role name is required.")
        try:
            return self.client.roles.get_assigned_user_ids(role_name=role_name)
        except Exception as e:
            raise Exception(f"Error getting users for role '{role_name}': {e}") from e

    def get_user_assignments_from_role(
        self, role_name: str | None = GetUserDefaults.role_name
    ) -> list[dict[str, str]]:
        """Get user assignments (user_id + user_type) for a role."""
        if role_name is None:
            raise ValueError("Role name is required.")
        try:
            assignments = self.client.roles.get_user_assignments(role_name=role_name)
            return [
                {
                    "user_id": str(a.user_id),
                    "user_type": str(getattr(a.user_type, "value", a.user_type)),
                }
                for a in assignments
            ]
        except Exception as e:
            raise Exception(f"Error getting users for role '{role_name}': {e}") from e

    def get_user(
        self,
        user_name: str | None = None,
        *,
        include_last_used_time: bool = False,
    ) -> OwnUser | UserDB | None:
        """Get a user in Weaviate. If no user name is provided, the current user is returned."""
        try:
            if user_name is None:
                return self.client.users.get_my_user()
            if include_last_used_time:
                return self.client.users.db.get(
                    user_id=user_name, include_last_used_time=True
                )
            return self.client.users.db.get(user_id=user_name)
        except Exception as e:
            raise Exception(f"Error getting user '{user_name}': {e}") from e

    def get_all_users(self, *, include_last_used_time: bool = False) -> list[UserDB]:
        """Get all users in Weaviate."""
        try:
            if include_last_used_time:
                return self.client.users.db.list_all(include_last_used_time=True)
            return self.client.users.db.list_all()
        except Exception as e:
            raise Exception(f"Error getting all users: {e}") from e

    def create_user(
        self,
        user_name: str | None = None,
    ) -> str:
        """
        Create a user in Weaviate.
        Returns the api key for the user.
        """
        if user_name is None:
            raise ValueError("User name is required.")
        try:
            return self.client.users.db.create(user_id=user_name)
        except Exception as e:
            raise Exception(f"Error creating user '{user_name}': {e}") from e

    def update_user(
        self,
        user_name: str | None = None,
        rotate_api_key: bool = False,
        activate: bool = False,
        deactivate: bool = False,
        revoke_key: bool = False,
    ) -> str | bool | None:
        """Update a user in Weaviate.
        Returns the api key for the user if the api key was rotated, otherwise a bool or None.
        """
        if user_name is None:
            raise ValueError("User name is required.")
        if rotate_api_key and (activate or deactivate):
            raise ValueError(
                "Cannot rotate api key and activate or deactivate user at the same time."
            )
        if activate and deactivate:
            raise ValueError("Cannot activate and deactivate user at the same time.")
        if revoke_key and not deactivate:
            raise ValueError(
                "--revoke-key can only be used together with --deactivate."
            )
        try:
            if rotate_api_key:
                return self.client.users.db.rotate_key(user_id=user_name)
            if activate:
                return self.client.users.db.activate(user_id=user_name)
            if deactivate:
                if revoke_key:
                    return self.client.users.db.deactivate(
                        user_id=user_name, revoke_key=True
                    )
                return self.client.users.db.deactivate(user_id=user_name)
            return None
        except Exception as e:
            raise Exception(f"Error updating user '{user_name}': {e}") from e

    def delete_user(
        self,
        user_name: str | None = None,
    ) -> None:
        """Delete a user in Weaviate."""
        if user_name is None:
            raise ValueError("User name is required.")
        try:
            self.client.users.db.delete(user_id=user_name)
        except Exception as e:
            raise Exception(f"Error deleting user '{user_name}': {e}") from e

    def add_role(
        self,
        role_name: tuple[str, ...],
        user_name: str,
        user_type: str = "db",
        json_output: bool = False,
    ) -> None:
        """Assign a role to a user."""
        try:
            if older_than_version(self.client, "1.30.0"):
                self.client.users.assign_roles(
                    user_id=user_name, role_names=list(role_name)
                )
            elif user_type == "db":
                self.client.users.db.assign_roles(
                    user_id=user_name, role_names=list(role_name)
                )
            elif user_type == "oidc":
                self.client.users.oidc.assign_roles(
                    user_id=user_name, role_names=list(role_name)
                )
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "success",
                            "message": f"Role(s) {list(role_name)} assigned to {user_type} user '{user_name}' successfully.",
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(
                    f"Role(s) {list(role_name)} assigned to {user_type} user '{user_name}' successfully."
                )
        except Exception as e:
            raise Exception(
                f"Error assigning {user_type} role '{role_name}' to user '{user_name}': {e}"
            ) from e

    def revoke_role(
        self,
        role_name: tuple[str, ...],
        user_name: str,
        user_type: str = "db",
        json_output: bool = False,
    ) -> None:
        """Revoke a role from a user."""
        try:
            if older_than_version(self.client, "1.30.0"):
                self.client.users.revoke_roles(
                    user_id=user_name, role_names=list(role_name)
                )
            elif user_type == "db":
                self.client.users.db.revoke_roles(
                    user_id=user_name, role_names=list(role_name)
                )
            elif user_type == "oidc":
                self.client.users.oidc.revoke_roles(
                    user_id=user_name, role_names=list(role_name)
                )
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "success",
                            "message": f"Role(s) {list(role_name)} revoked from {user_type} user '{user_name}' successfully.",
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(
                    f"Role(s) {list(role_name)} revoked from {user_type} user '{user_name}' successfully."
                )
        except Exception as e:
            raise Exception(
                f"Error revoking {user_type} role '{role_name}' from user '{user_name}': {e}"
            ) from e

    def print_user(self, user: str, json_output: bool = False) -> None:
        """Print user roles in a human readable format."""
        if json_output:
            click.echo(json.dumps({"user_id": user}, indent=2))
            return
        click.echo(f"User: {user}")

    def print_own_user(self, user: OwnUser, json_output: bool = False) -> None:
        """Print current user roles and groups in a human readable format."""
        groups = list(getattr(user, "groups", None) or [])
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "user_id": user.user_id,
                        "roles": list(user.roles.keys()),
                        "groups": groups,
                    },
                    indent=2,
                )
            )
            return
        click.echo(f"User: {user.user_id}")
        click.echo("Roles:")
        if len(user.roles) == 0:
            click.echo(" - No roles assigned")
        else:
            for role in user.roles.keys():
                click.echo(f" - Role: {role}")
        if groups:
            click.echo("Groups:")
            for group in groups:
                click.echo(f" - Group: {group}")

    def print_db_user(self, user: UserDB, json_output: bool = False) -> None:
        """Print DB user details including lifecycle audit metadata."""
        data = db_user_to_dict(user)
        if json_output:
            click.echo(json.dumps(data, indent=2))
            return
        click.echo(f"User: {user.user_id}")
        click.echo(f"Active: {'Yes' if user.active else 'No'}")
        click.echo(f"Type: {user.user_type.name}")
        if "api_key_first_letters" in data:
            click.echo(f"API Key Prefix: {data['api_key_first_letters']}")
        if "created_at" in data:
            click.echo(f"Created At: {data['created_at']}")
        if "last_used_time" in data:
            click.echo(f"Last Used: {data['last_used_time']}")
        click.echo("Roles:")
        if len(user.role_names) == 0:
            click.echo(" - No roles assigned")
        else:
            for role in user.role_names:
                click.echo(f" - Role: {role}")
