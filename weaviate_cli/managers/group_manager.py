"""Manager for OIDC group RBAC role assignments."""

from __future__ import annotations

from typing import Any

from weaviate import WeaviateClient
from weaviate.rbac.models import Role

from weaviate_cli.managers.role_manager import RoleManager


class GroupManager:
    """Adapter for OIDC group RBAC management (`client.groups.oidc` & `client.roles.get_group_assignments`)."""

    def __init__(self, client: WeaviateClient) -> None:
        self.client = client

    def list_known_groups(self) -> list[str]:
        """List all known OIDC group names that have role assignments."""
        return sorted(self.client.groups.oidc.get_known_group_names())

    def get_groups_for_role(self, role_name: str) -> list[dict[str, str]]:
        """List groups assigned to a specific RBAC role."""
        assignments = self.client.roles.get_group_assignments(role_name=role_name)
        return [
            {
                "group_id": str(a.group_id),
                "group_type": str(getattr(a.group_type, "value", a.group_type)),
            }
            for a in assignments
        ]

    def get_group_roles(
        self, group_id: str, *, include_permissions: bool = False
    ) -> dict[str, Any]:
        """Return roles assigned to an OIDC group."""
        assigned = self.client.groups.oidc.get_assigned_roles(
            group_id=group_id,
            include_permissions=include_permissions,
        )
        if include_permissions:
            roles_list: list[Any] = [
                RoleManager.role_to_dict(role)
                if isinstance(role, Role)
                else {"name": role.name}
                for role in assigned.values()
            ]
        else:
            roles_list = sorted(assigned.keys())
        return {
            "group_id": group_id,
            "group_type": "oidc",
            "roles": roles_list,
        }

    def assign_roles(
        self, group_id: str, role_names: tuple[str, ...] | list[str]
    ) -> dict[str, Any]:
        """Assign one or more RBAC roles to an OIDC group."""
        roles = list(role_names)
        self.client.groups.oidc.assign_roles(group_id=group_id, role_names=roles)
        return {
            "status": "success",
            "group_id": group_id,
            "group_type": "oidc",
            "roles": roles,
            "message": f"Role(s) {roles} assigned to OIDC group '{group_id}' successfully.",
        }

    def revoke_roles(
        self, group_id: str, role_names: tuple[str, ...] | list[str]
    ) -> dict[str, Any]:
        """Revoke one or more RBAC roles from an OIDC group."""
        roles = list(role_names)
        self.client.groups.oidc.revoke_roles(group_id=group_id, role_names=roles)
        return {
            "status": "success",
            "group_id": group_id,
            "group_type": "oidc",
            "roles": roles,
            "message": f"Role(s) {roles} revoked from OIDC group '{group_id}' successfully.",
        }
