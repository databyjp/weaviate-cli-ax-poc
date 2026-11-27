"""Click commands for the 'tenant' resource group."""

from __future__ import annotations

import click
from weaviate import WeaviateClient

from weaviate_cli.completion.complete import collection_name_complete
from weaviate_cli.defaults import CreateTenantsDefaults
from weaviate_cli.managers.tenant_manager import TenantManager
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    AXGroup,
    emit_captured_json_or_text,
    get_runtime,
    handle_command_error,
)
from weaviate_cli.utils import get_client_from_context


@click.group("tenant", cls=AXGroup)
def tenant_group() -> None:
    """Manage multi-tenancy tenants in Weaviate."""


@tenant_group.command(
    "create",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli tenant create tenant-a tenant-b --collection Articles\n"
        "  weaviate-cli tenant create tenant-c --collection Articles --state inactive"
    ),
)
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
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def create_tenants_cli(
    ctx: click.Context,
    tenants: tuple[str, ...],
    collection: str,
    state: str,
    batch_size: int | None,
    json_output: bool | None,
) -> None:
    """Create one or more named tenants in a collection."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "tenant create"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        tenant_manager = TenantManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: tenant_manager.create_tenants(
                collection=collection,
                tenant_batch_size=batch_size,
                state=state,
                tenants_list=list(tenants),
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@tenant_group.command("list", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option(
    "--collection",
    required=True,
    help="The name of the collection to list tenants from.",
    shell_complete=collection_name_complete,
)
@click.option("--verbose", is_flag=True, help="Print each tenant name and status.")
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def list_tenants_cli(
    ctx: click.Context,
    collection: str,
    verbose: bool,
    json_output: bool | None,
) -> None:
    """List tenants in a collection."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "tenant list"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        tenant_manager = TenantManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: tenant_manager.get_tenants(
                collection=collection,
                tenant_id=None,
                verbose=verbose,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@tenant_group.command("get", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("name")
@click.option(
    "--collection",
    required=True,
    help="The name of the collection containing the tenant.",
    shell_complete=collection_name_complete,
)
@click.option("--verbose", is_flag=True, help="Print verbose output.")
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def get_tenant_cli(
    ctx: click.Context,
    name: str,
    collection: str,
    verbose: bool,
    json_output: bool | None,
) -> None:
    """Get details for a specific tenant in a collection."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "tenant get"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        tenant_manager = TenantManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: tenant_manager.get_tenants(
                collection=collection,
                tenant_id=name,
                verbose=verbose,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@tenant_group.command(
    "update",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli tenant update tenant-a --collection Articles --state offloaded\n"
        "  weaviate-cli tenant update tenant-a tenant-b --collection Articles --state active"
    ),
)
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
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def update_tenants_cli(
    ctx: click.Context,
    tenants: tuple[str, ...],
    collection: str,
    state: str,
    json_output: bool | None,
) -> None:
    """Update the activity state of one or more named tenants."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "tenant update"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        tenant_manager = TenantManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: tenant_manager.update_tenants(
                collection=collection,
                state=state,
                tenants=",".join(tenants),
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@tenant_group.command("delete", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("tenants", nargs=-1, required=True)
@click.option(
    "--collection",
    required=True,
    help="The name of the collection containing the tenants.",
    shell_complete=collection_name_complete,
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def delete_tenants_cli(
    ctx: click.Context,
    tenants: tuple[str, ...],
    collection: str,
    json_output: bool | None,
) -> None:
    """Delete one or more named tenants from a collection."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "tenant delete"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        tenant_manager = TenantManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: tenant_manager.delete_tenants(
                collection=collection,
                tenants_list=list(tenants),
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()
