import sys

import click
from weaviate import WeaviateClient

from weaviate_cli.completion.complete import collection_name_complete
from weaviate_cli.defaults import CreateTenantsDefaults
from weaviate_cli.managers.tenant_manager import TenantManager
from weaviate_cli.utils import get_client_from_context


@click.group("tenant")
def tenant_group() -> None:
    """Manage multi-tenancy tenants in Weaviate."""


@tenant_group.command("create")
@click.argument("tenants", nargs=-1, required=True)
@click.option(
    "--collection",
    required=True,
    help="The name of the collection to create tenants in.",
    shell_complete=collection_name_complete,
)
@click.option(
    "--state",
    default=CreateTenantsDefaults.state,
    type=click.Choice(["hot", "active", "cold", "inactive", "frozen", "offloaded"]),
    help=f"Initial tenant activity state (default: '{CreateTenantsDefaults.state}').",
)
@click.option(
    "--batch-size",
    default=CreateTenantsDefaults.tenant_batch_size,
    type=int,
    help="Number of tenants to create per batch (default: all in one batch).",
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def create_tenants_cli(
    ctx: click.Context,
    tenants: tuple[str, ...],
    collection: str,
    state: str,
    batch_size: int | None,
    json_output: bool,
) -> None:
    """Create one or more named tenants in a collection."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        tenant_manager = TenantManager(client)
        tenant_manager.create_tenants(
            collection=collection,
            tenant_batch_size=batch_size,
            state=state,
            tenants_list=list(tenants),
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


@tenant_group.command("list")
@click.option(
    "--collection",
    required=True,
    help="The name of the collection to list tenants from.",
    shell_complete=collection_name_complete,
)
@click.option("--verbose", is_flag=True, help="Print each tenant name and status.")
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def list_tenants_cli(
    ctx: click.Context,
    collection: str,
    verbose: bool,
    json_output: bool,
) -> None:
    """List tenants in a collection."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        tenant_manager = TenantManager(client)
        tenant_manager.get_tenants(
            collection=collection,
            tenant_id=None,
            verbose=verbose,
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


@tenant_group.command("get")
@click.argument("name")
@click.option(
    "--collection",
    required=True,
    help="The name of the collection containing the tenant.",
    shell_complete=collection_name_complete,
)
@click.option("--verbose", is_flag=True, help="Print verbose output.")
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def get_tenant_cli(
    ctx: click.Context,
    name: str,
    collection: str,
    verbose: bool,
    json_output: bool,
) -> None:
    """Get details for a specific tenant in a collection."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        tenant_manager = TenantManager(client)
        tenant_manager.get_tenants(
            collection=collection,
            tenant_id=name,
            verbose=verbose,
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


@tenant_group.command("update")
@click.argument("tenants", nargs=-1, required=True)
@click.option(
    "--collection",
    required=True,
    help="The name of the collection containing the tenants.",
    shell_complete=collection_name_complete,
)
@click.option(
    "--state",
    required=True,
    type=click.Choice(["hot", "active", "cold", "inactive", "frozen", "offloaded"]),
    help="Target activity state for the tenants.",
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def update_tenants_cli(
    ctx: click.Context,
    tenants: tuple[str, ...],
    collection: str,
    state: str,
    json_output: bool,
) -> None:
    """Update the activity state of one or more named tenants."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        tenant_manager = TenantManager(client)
        tenant_manager.update_tenants(
            collection=collection,
            state=state,
            tenants=",".join(tenants),
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


@tenant_group.command("delete")
@click.argument("tenants", nargs=-1, required=True)
@click.option(
    "--collection",
    required=True,
    help="The name of the collection containing the tenants.",
    shell_complete=collection_name_complete,
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def delete_tenants_cli(
    ctx: click.Context,
    tenants: tuple[str, ...],
    collection: str,
    json_output: bool,
) -> None:
    """Delete one or more named tenants from a collection."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        tenant_manager = TenantManager(client)
        tenant_manager.delete_tenants(
            collection=collection,
            tenants_list=list(tenants),
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
