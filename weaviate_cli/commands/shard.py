"""Click commands for the 'shard' resource group."""

from __future__ import annotations

import click
from weaviate import WeaviateClient
from weaviate.exceptions import UnexpectedStatusCodeError

from weaviate_cli.completion.complete import collection_name_complete
from weaviate_cli.defaults import GetShardsDefaults, UpdateShardsDefaults
from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.managers.cluster_manager import ClusterManager
from weaviate_cli.managers.shard_manager import ShardManager
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


@click.group("shard", cls=AXGroup)
def shard_group() -> None:
    """Inspect and manage collection shards."""


@shard_group.command("list", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option(
    "--collection",
    default=GetShardsDefaults.collection,
    help="Filter shards to a specific collection.",
    shell_complete=collection_name_complete,
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def list_shards_cli(
    ctx: click.Context, collection: str | None, json_output: bool | None
) -> None:
    """List shards for all collections or a specific collection."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "shard list"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        shard_man = ShardManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: shard_man.get_shards(
                collection=collection,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@shard_group.command("update", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option(
    "--collection",
    default=UpdateShardsDefaults.collection,
    help="The name of the collection to update shards for.",
    shell_complete=collection_name_complete,
)
@click.option(
    "--status",
    default=UpdateShardsDefaults.status,
    type=click.Choice(["READY", "READONLY"]),
    help=f"Target shard status (default: '{UpdateShardsDefaults.status}').",
)
@click.option(
    "--shards",
    default=UpdateShardsDefaults.shards,
    help="Comma separated list of shard names to update.",
)
@click.option(
    "--all",
    "update_all",
    is_flag=True,
    help="Update shards across all collections (requires --yes).",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm bulk shard status update across all collections (required with --all).",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def update_shards_cli(
    ctx: click.Context,
    status: str,
    collection: str | None,
    shards: str | None,
    update_all: bool,
    yes: bool,
    json_output: bool | None,
) -> None:
    """Update shard statuses."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "shard update"

    if update_all:
        require_confirmation(
            runtime,
            yes=yes,
            command=command,
            message="Updating shard status across all collections requires --yes.",
            hint=f"Re-run with 'weaviate-cli shard update --all --status {status} --yes' after confirming.",
        )
    elif collection is None:
        handle_command_error(
            ctx,
            runtime,
            CLIError(
                code="MISSING_TARGET",
                message="Either --collection or --all must be specified.",
                exit_code=ExitCode.USAGE,
                hint="Example: 'weaviate-cli shard update --collection Articles --status READY'.",
            ),
            command=command,
        )

    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        shard_man = ShardManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: shard_man.update_shards(
                status=status,
                collection=collection,
                shards=shards,
                all=update_all,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@shard_group.command("state", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("collection", shell_complete=collection_name_complete)
@click.option(
    "--shard",
    default=None,
    help="Filter sharding state to a specific shard.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def shard_state_cli(
    ctx: click.Context,
    collection: str,
    shard: str | None,
    json_output: bool | None,
) -> None:
    """Inspect sharding state for a collection."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "shard state"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        manager = ClusterManager(client, click.echo)
        try:
            state = manager.query_sharding_state(collection, shard)
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code is None and isinstance(
                exc.__cause__, UnexpectedStatusCodeError
            ):
                status_code = getattr(exc.__cause__, "status_code", None)
            if status_code == 501:
                raise CLIError(
                    code="SHARDING_STATE_UNSUPPORTED",
                    message=(
                        f"Sharding state endpoint returned HTTP 501 Not Implemented for "
                        f"collection '{collection}'."
                    ),
                    exit_code=ExitCode.RUNTIME,
                    hint=(
                        "The sharding-state endpoint requires a cluster with replication "
                        "enabled. Use 'weaviate-cli shard list --collection "
                        f"{collection}' or 'weaviate-cli node list --collection "
                        f"{collection}' to inspect shard status."
                    ),
                    details={"status_code": 501},
                ) from exc
            raise
        if not state:
            raise CLIError(
                code="SHARDING_STATE_NOT_FOUND",
                message=f"No sharding state found for collection '{collection}'.",
                exit_code=ExitCode.NOT_FOUND,
            )

        shards_data = [
            {
                "name": s.name,
                "replicas": list(s.replicas) if s.replicas else [],
            }
            for s in state.shards
        ]

        def _render_text() -> None:
            if shard:
                click.echo(
                    f"Sharding state for collection '{collection}', shard '{shard}':"
                )
            else:
                click.echo(f"Sharding state for collection '{collection}':")
            manager.print_sharding_state(state, json_output=False)

        emit_success(
            runtime,
            {"collection": collection, "shards": shards_data},
            command=command,
            text_renderer=_render_text,
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()
