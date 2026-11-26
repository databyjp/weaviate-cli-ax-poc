import json
from typing import overload

import click
from weaviate import WeaviateClient
from weaviate.users.users import OwnUser, UserDB

from weaviate_cli.defaults import (
    GetUserDefaults,
)
from weaviate_cli.utils import older_than_version


class UserManager:
    def __init__(self, client: WeaviateClient):
        self.client = client

    def get_user_from_role(
        self, role_name: str | None = GetUserDefaults.role_name
    ) -> list[str]:
        """Get the user IDs assigned to the specified role."""
        if role_name is None:
            raise ValueError("Role name is required.")
        try:
            return self.client.roles.get_assigned_user_ids(role_name=role_name)
        except Exception as e:
            raise Exception(f"Error getting users for role '{role_name}': {e}")

    @overload
    def get_user(self, user_name: None = None) -> OwnUser: ...

    @overload
    def get_user(self, user_name: str) -> UserDB | None: ...

    def get_user(
        self,
        user_name: str | None = None,
    ) -> OwnUser | UserDB | None:
        """Return the current user, or look up a named DB user (None if absent)."""

        try:
            if user_name is None:
                return self.client.users.get_my_user()
            else:
                return self.client.users.db.get(user_id=user_name)
        except Exception as e:
            raise Exception(f"Error getting user '{user_name}': {e}")

    def get_all_users(self) -> list[UserDB]:
        """Get all users in Weaviate."""
        try:
            return self.client.users.db.list_all()
        except Exception as e:
            raise Exception(f"Error getting all users: {e}")

    def create_user(
        self,
        user_name: str | None = None,
    ) -> str:
        """
        Create a user in Weaviate.
        Returns the api key for the user.
        """
        if user_name is None:
            raise Exception("User name is required.")
        try:
            return self.client.users.db.create(user_id=user_name)
        except Exception as e:
            raise Exception(f"Error creating user '{user_name}': {e}")

    def update_user(
        self,
        user_name: str | None = None,
        rotate_api_key: bool = False,
        activate: bool = False,
        deactivate: bool = False,
    ) -> str | bool | None:
        """Return the rotated key, the SDK activation/deactivation result, or None for no action."""
        if user_name is None:
            raise Exception("User name is required.")
        if rotate_api_key and (activate or deactivate):
            raise Exception(
                "Cannot rotate api key and activate or deactivate user at the same time."
            )
        if activate and deactivate:
            raise Exception("Cannot activate and deactivate user at the same time.")
        try:
            if rotate_api_key:
                return self.client.users.db.rotate_key(user_id=user_name)
            if activate:
                return self.client.users.db.activate(user_id=user_name)
            if deactivate:
                return self.client.users.db.deactivate(user_id=user_name)
        except Exception as e:
            raise Exception(f"Error updating user '{user_name}': {e}")

    def delete_user(
        self,
        user_name: str | None = None,
    ) -> None:
        """Delete a user in Weaviate."""
        if user_name is None:
            raise Exception("User name is required.")
        try:
            self.client.users.db.delete(user_id=user_name)
        except Exception as e:
            raise Exception(f"Error deleting user '{user_name}': {e}")

    def add_role(
        self,
        role_name: tuple[str],
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
            )

    def revoke_role(
        self,
        role_name: tuple[str],
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
            )

    def print_user(self, user: str, json_output: bool = False) -> None:
        """Print user roles in a human readable format."""
        if json_output:
            click.echo(json.dumps({"user_id": user}, indent=2))
            return
        print(f"User: {user}")

    def print_own_user(self, user: OwnUser, json_output: bool = False) -> None:
        """Print user roles in a human readable format."""
        if json_output:
            click.echo(
                json.dumps(
                    {"user_id": user.user_id, "roles": list(user.roles.keys())},
                    indent=2,
                )
            )
            return
        print(f"User: {user.user_id}")
        print("Roles:")
        if len(user.roles) == 0:
            print(" - No roles assigned")
        else:
            for role in user.roles:
                print(f" - Role: {role}")

    def print_db_user(self, user: UserDB, json_output: bool = False) -> None:
        """Print user roles in a human readable format."""
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "user_id": user.user_id,
                        "active": user.active,
                        "user_type": user.user_type.name,
                        "roles": list(user.role_names),
                    },
                    indent=2,
                )
            )
            return
        print(f"User: {user.user_id}")
        print(f"Active: {'Yes' if user.active else 'No'}")
        print(f"Type: {user.user_type.name}")
        print("Roles:")
        if len(user.role_names) == 0:
            print(" - No roles assigned")
        else:
            for role in user.role_names:
                print(f" - Role: {role}")
