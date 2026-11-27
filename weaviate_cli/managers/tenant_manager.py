import json

import click
import semver
from weaviate import WeaviateClient
from weaviate.collections.classes.tenants import Tenant, TenantActivityStatus

from weaviate_cli.defaults import (
    CreateTenantsDefaults,
    DeleteTenantsDefaults,
    GetTenantsDefaults,
    UpdateTenantsDefaults,
)
from weaviate_cli.errors import CLIError, ExitCode


class TenantManager:
    def __init__(self, client: WeaviateClient):
        self.client = client

    def create_tenants(
        self,
        collection: str | None = CreateTenantsDefaults.collection,
        tenant_suffix: str = CreateTenantsDefaults.tenant_suffix,
        number_tenants: int = CreateTenantsDefaults.number_tenants,
        tenant_batch_size: int | None = CreateTenantsDefaults.tenant_batch_size,
        state: str = CreateTenantsDefaults.state,
        tenants_list: list[str] | None = None,
        json_output: bool = False,
    ) -> None:
        """
        Create tenants for a given collection in Weaviate.
        """
        if not collection:
            raise CLIError(
                code="MISSING_COLLECTION",
                message="Collection name is required.",
                exit_code=ExitCode.USAGE,
            )

        if not self.client.collections.exists(collection):
            raise CLIError(
                code="COLLECTION_NOT_FOUND",
                message=f"Collection '{collection}' does not exist in Weaviate.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli collection list' to see existing collections.",
            )

        version = semver.Version.parse(self.client.get_meta()["version"])
        col = self.client.collections.get(collection)

        if not col.config.get().multi_tenancy_config.enabled:
            raise CLIError(
                code="MULTI_TENANCY_DISABLED",
                message=f"Collection '{col.name}' does not have multi-tenancy enabled.",
                exit_code=ExitCode.USAGE,
                hint='Enable "multiTenancyConfig": {"enabled": true} when creating the collection.',
            )

        tenant_state_map = {
            "hot": TenantActivityStatus.HOT,
            "active": TenantActivityStatus.ACTIVE,
            "cold": TenantActivityStatus.COLD,
            "inactive": TenantActivityStatus.INACTIVE,
            "frozen": TenantActivityStatus.FROZEN,
            "offloaded": TenantActivityStatus.OFFLOADED,
        }

        # Fetch existing tenants once to avoid redundant network calls
        existing_tenants = col.tenants.get()

        # Resolve tenant names to create
        new_tenant_names = self._resolve_tenant_names_to_create(
            existing_tenants=existing_tenants,
            tenant_suffix=tenant_suffix,
            number_tenants=number_tenants,
            tenants_list=tenants_list,
        )

        # Filter out already existing tenants
        new_tenant_names = [
            name for name in new_tenant_names if name not in existing_tenants
        ]

        # Create the new tenants
        tenants = [
            Tenant(name=name, activity_status=tenant_state_map[state])
            for name in new_tenant_names
        ]

        if not tenants:
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "success",
                            "tenants_created": 0,
                            "message": f"No new tenants to create for collection '{col.name}'",
                        }
                    )
                )
            else:
                click.echo(f"No new tenants to create for collection '{col.name}'")
            return

        # Create tenants (in batches if specified)
        if tenant_batch_size:
            for i in range(0, len(tenants), tenant_batch_size):
                batch = tenants[i : i + tenant_batch_size]
                col.tenants.create(batch)
        else:
            col.tenants.create(tenants)

        # Verify creation
        self._verify_tenant_creation(
            collection=col,
            version=version,
            new_tenant_names=new_tenant_names,
            expected_status=tenant_state_map[state],
        )

        if json_output:
            click.echo(
                json.dumps(
                    {
                        "status": "success",
                        "tenants_created": len(new_tenant_names),
                        "message": f"{len(new_tenant_names)} tenants added with status '{tenant_state_map[state]}' for collection '{col.name}'",
                    }
                )
            )
        else:
            click.echo(
                f"{len(new_tenant_names)} tenants added with status '{tenant_state_map[state]}' for collection '{col.name}'"
            )

    def _resolve_tenant_names_to_create(
        self,
        existing_tenants: dict,
        tenant_suffix: str,
        number_tenants: int,
        tenants_list: list[str] | None,
    ) -> list[str]:
        """
        Determine which tenant names to create.

        Cases:
        1. Explicit tenants_list provided: use those names directly
        2. Auto-generate with suffix: find highest existing index for this suffix, continue from there
        """
        # Case 1: Explicit tenant list
        if tenants_list is not None:
            return tenants_list

        # Case 2: Auto-generate with suffix pattern
        # Only look at existing tenants matching this suffix (ignore others)
        highest_index = -1

        for tenant_name in existing_tenants:
            if tenant_name.startswith(f"{tenant_suffix}-"):
                try:
                    index = int(tenant_name[len(f"{tenant_suffix}-") :])
                    highest_index = max(highest_index, index)
                except ValueError:
                    # Tenant matches prefix but doesn't follow pattern - skip it
                    continue

        start_index = highest_index + 1
        return [
            f"{tenant_suffix}-{i}"
            for i in range(start_index, start_index + number_tenants)
        ]

    def _verify_tenant_creation(
        self,
        collection,
        version: semver.Version,
        new_tenant_names: list[str],
        expected_status: TenantActivityStatus,
    ) -> None:
        """Verify all requested tenants were created with correct status."""
        if version.compare(semver.Version.parse("1.25.0")) < 0:
            created_tenants = {
                name: tenant
                for name, tenant in collection.tenants.get().items()
                if name in new_tenant_names
            }
        else:
            created_tenants = collection.tenants.get_by_names(new_tenant_names)

        if len(created_tenants) != len(new_tenant_names):
            missing = set(new_tenant_names) - set(created_tenants.keys())
            raise Exception(
                f"Not all requested tenants were created. Missing: {', '.join(missing)}"
            )

        for tenant_name, tenant in created_tenants.items():
            if tenant.activity_status != expected_status:
                raise Exception(
                    f"Tenant '{tenant_name}' has status '{tenant.activity_status}', expected '{expected_status}'"
                )

    def delete_tenants(
        self,
        collection: str | None = DeleteTenantsDefaults.collection,
        tenant_suffix: str = DeleteTenantsDefaults.tenant_suffix,
        number_tenants: int = DeleteTenantsDefaults.number_tenants,
        tenants_list: list | None = DeleteTenantsDefaults.tenants,
        json_output: bool = False,
    ) -> None:
        """Delete tenants for a given collection in Weaviate."""
        if not collection:
            raise CLIError(
                code="MISSING_COLLECTION",
                message="Collection name is required.",
                exit_code=ExitCode.USAGE,
            )

        if not self.client.collections.exists(collection):
            raise CLIError(
                code="COLLECTION_NOT_FOUND",
                message=f"Collection '{collection}' does not exist in Weaviate.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli collection list' to see existing collections.",
            )

        col = self.client.collections.get(collection)

        if not col.config.get().multi_tenancy_config.enabled:
            raise CLIError(
                code="MULTI_TENANCY_DISABLED",
                message=f"Collection '{col.name}' does not have multi-tenancy enabled.",
                exit_code=ExitCode.USAGE,
            )

        try:
            if tenants_list:
                deleting_tenants = col.tenants.get_by_names(tenants_list)
            else:
                if tenant_suffix == "*":
                    if not json_output:
                        click.echo(
                            f"Deleting {number_tenants} existing tenants from {col.name} (not taking into account the tenant suffix)"
                        )
                    tenants_list_with_suffix = col.tenants.get()
                else:
                    tenants_list_with_suffix = {
                        name: tenant
                        for name, tenant in col.tenants.get().items()
                        if name.startswith(tenant_suffix)
                    }
                total_tenants = len(tenants_list_with_suffix)
                if total_tenants == 0:
                    raise CLIError(
                        code="TENANT_NOT_FOUND",
                        message=f"No tenants present in class {col.name}.",
                        exit_code=ExitCode.NOT_FOUND,
                    )

                if number_tenants < total_tenants:
                    deleting_tenants = dict(
                        list(tenants_list_with_suffix.items())[:number_tenants]
                    )
                else:
                    deleting_tenants = tenants_list_with_suffix

            if not deleting_tenants:
                raise CLIError(
                    code="TENANT_NOT_FOUND",
                    message=f"No tenants present in class {col.name}.",
                    exit_code=ExitCode.NOT_FOUND,
                )
            else:
                col.tenants.remove(list(deleting_tenants.values()))

        except Exception as e:
            raise Exception(f"Failed to delete tenants: {e}") from e

        # Verify deletion
        remaining = col.tenants.get_by_names(list(deleting_tenants.keys()))
        assert len(remaining) == 0, (
            f"Expected all {len(deleting_tenants)} tenants to be deleted, but {len(remaining)} still exist"
        )

        if json_output:
            click.echo(
                json.dumps(
                    {
                        "status": "success",
                        "tenants_deleted": len(deleting_tenants),
                        "message": f"{len(deleting_tenants)} tenants deleted",
                    },
                    indent=2,
                )
            )
        else:
            click.echo(f"{len(deleting_tenants)} tenants deleted")

    def get_tenants(
        self,
        collection: str | None = GetTenantsDefaults.collection,
        tenant_id: str | None = GetTenantsDefaults.tenant_id,
        verbose: bool = GetTenantsDefaults.verbose,
        json_output: bool = False,
    ) -> dict:
        """Retrieve tenants for a given collection in Weaviate."""
        if not collection:
            raise CLIError(
                code="MISSING_COLLECTION",
                message="Collection name is required.",
                exit_code=ExitCode.USAGE,
            )
        if tenant_id:
            tenants = self.client.collections.get(collection).tenants.get_by_names(
                [tenant_id]
            )
            if not tenants:
                raise CLIError(
                    code="TENANT_NOT_FOUND",
                    message=f"Tenant '{tenant_id}' not found in class {collection}",
                    exit_code=ExitCode.NOT_FOUND,
                )
        else:
            tenants = self.client.collections.get(collection).tenants.get()

        if json_output:
            tenants_data = []
            for name, tenant in tenants.items():
                tenants_data.append(
                    {"name": name, "activity_status": tenant.activity_status.value}
                )
            active = sum(
                1
                for t in tenants.values()
                if t.activity_status == TenantActivityStatus.ACTIVE
            )
            inactive = sum(
                1
                for t in tenants.values()
                if t.activity_status == TenantActivityStatus.INACTIVE
            )
            offloaded = sum(
                1
                for t in tenants.values()
                if t.activity_status == TenantActivityStatus.OFFLOADED
            )
            click.echo(
                json.dumps(
                    {
                        "tenants": tenants_data,
                        "summary": {
                            "total": len(tenants),
                            "active": active,
                            "inactive": inactive,
                            "offloaded": offloaded,
                        },
                    },
                    indent=2,
                    default=str,
                )
            )
            return tenants

        if verbose:
            click.echo(f"{'Tenant Name':<30}{'Activity Status':<20}")
            for name, tenant in tenants.items():
                click.echo(f"{name:<30}{tenant.activity_status.value:<20}")
        else:
            active_tenants = [
                tenant
                for name, tenant in tenants.items()
                if tenant.activity_status == TenantActivityStatus.ACTIVE
            ]
            inactive_tenants = [
                tenant
                for name, tenant in tenants.items()
                if tenant.activity_status == TenantActivityStatus.INACTIVE
            ]
            offoaded_tenants = [
                tenant
                for name, tenant in tenants.items()
                if tenant.activity_status == TenantActivityStatus.OFFLOADED
            ]

            click.echo(
                f"{'Number Tenants':<20}{'Cold Tenants':<20}{'Hot Tenants': <20}{'Offloaded Tenants':<20}"
            )
            click.echo(
                f"{len(tenants):<20}{len(inactive_tenants):<20}{len(active_tenants):<20}{len(offoaded_tenants):<20}"
            )
        return tenants

    def update_tenants(
        self,
        collection: str | None = UpdateTenantsDefaults.collection,
        tenant_suffix: str = UpdateTenantsDefaults.tenant_suffix,
        number_tenants: int = UpdateTenantsDefaults.number_tenants,
        state: str = UpdateTenantsDefaults.state,
        tenants: str | None = UpdateTenantsDefaults.tenants,
        json_output: bool = False,
    ) -> None:
        """Updates the activity status of tenants in a collection."""
        if not collection:
            raise CLIError(
                code="MISSING_COLLECTION",
                message="Collection name is required.",
                exit_code=ExitCode.USAGE,
            )

        if not self.client.collections.exists(collection):
            raise CLIError(
                code="COLLECTION_NOT_FOUND",
                message=f"Collection '{collection}' does not exist in Weaviate.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli collection list' to see existing collections.",
            )

        version = semver.Version.parse(self.client.get_meta()["version"])
        col = self.client.collections.get(collection)

        if not col.config.get().multi_tenancy_config.enabled:
            raise CLIError(
                code="MULTI_TENANCY_DISABLED",
                message=f"Collection '{col.name}' does not have multi-tenancy enabled.",
                exit_code=ExitCode.USAGE,
            )

        tenant_state_map = {
            "hot": TenantActivityStatus.HOT,
            "active": TenantActivityStatus.ACTIVE,
            "cold": TenantActivityStatus.COLD,
            "inactive": TenantActivityStatus.INACTIVE,
            "frozen": TenantActivityStatus.FROZEN,
            "offloaded": TenantActivityStatus.OFFLOADED,
        }

        equivalent_state_map = {
            "hot": TenantActivityStatus.ACTIVE,
            "active": TenantActivityStatus.ACTIVE,
            "cold": TenantActivityStatus.INACTIVE,
            "inactive": TenantActivityStatus.INACTIVE,
            "frozen": TenantActivityStatus.OFFLOADED,
            "offloaded": TenantActivityStatus.OFFLOADED,
        }

        tenants_with_suffix: dict = {}
        if tenants is None:
            tenants_with_suffix = {
                name: tenant
                for name, tenant in col.tenants.get().items()
                if name.startswith(tenant_suffix)
            }

        if tenants is None and len(tenants_with_suffix) < number_tenants:
            raise CLIError(
                code="TENANT_NOT_FOUND",
                message=(
                    f"Not enough tenants present in class {col.name} with suffix {tenant_suffix}. "
                    f"Expected {number_tenants}, found {len(tenants_with_suffix)}."
                ),
                exit_code=ExitCode.NOT_FOUND,
            )
        if tenants:
            # Update only the specified tenants passed via arguments.
            existing_tenants = col.tenants.get_by_names(
                [t.strip() for t in tenants.split(",") if t.strip()]
            )
        else:
            existing_tenants = dict(list(tenants_with_suffix.items())[:number_tenants])

        tenants_to_update = [
            (
                Tenant(name=name, activity_status=tenant_state_map[state])
                if tenant.activity_status != tenant_state_map[state]
                else tenant
            )
            for name, tenant in existing_tenants.items()
        ]
        if not tenants_to_update:
            raise CLIError(
                code="TENANT_NOT_FOUND",
                message=f"No matching tenants found in collection '{col.name}' to update.",
                exit_code=ExitCode.NOT_FOUND,
            )
        col.tenants.update(tenants_to_update)

        # get_by_names is only available after 1.25.0
        if version.compare(semver.Version.parse("1.25.0")) < 0:
            tenants_list = {
                name: tenant
                for name, tenant in col.tenants.get().items()
                if name in existing_tenants.keys()
            }
        else:
            tenants_list = col.tenants.get_by_names(list(existing_tenants.keys()))
        if tenants is None:
            assert len(tenants_list) == number_tenants, (
                f"Expected {number_tenants} tenants, but found {len(tenants_list)}"
            )
        else:
            clean = [t.strip() for t in tenants.split(",") if t.strip()]
            assert len(tenants_list) == len(clean), (
                f"Expected {len(clean)} tenants, but found {len(tenants_list)}"
            )
        last_status = equivalent_state_map[state]
        for tenant in tenants_list.values():
            last_status = tenant.activity_status
            if tenant.activity_status != equivalent_state_map[state]:
                raise Exception(
                    f"Tenant '{tenant.name}' has activity status '{tenant.activity_status}', but expected '{tenant_state_map[state]}'"
                )
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "status": "success",
                        "tenants_updated": len(tenants_list),
                        "message": f"{len(tenants_list)} tenants updated with tenant status '{last_status}' for class '{col.name}'.",
                    },
                    indent=2,
                )
            )
        else:
            click.echo(
                f"{len(tenants_list)} tenants updated with tenant status '{last_status}' for class '{col.name}'."
            )
