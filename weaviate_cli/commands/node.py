"""Click commands for the 'node' resource group."""

from __future__ import annotations

import click
from weaviate import WeaviateClient

from weaviate_cli.completion.complete import collection_name_complete
from weaviate_cli.defaults import GetNodesDefaults
from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.managers.node_manager import NodeManager
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    AXGroup,
    emit_captured_json_or_text,
    get_runtime,
    handle_command_error,
)
from weaviate_cli.utils import get_client_from_context


@click.group("node", cls=AXGroup)
def node_group() -> None:
    """Inspect Weaviate cluster nodes and Raft consensus statistics."""


@node_group.command(
    "list",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli node list --minimal\n"
        "  weaviate-cli node list --shards\n"
        "  weaviate-cli node list --collection Articles --shard shard-1"
    ),
)
@click.option(
    "--minimal",
    is_flag=True,
    help="Get minimal node information (fast for large clusters).",
)
@click.option(
    "--shards",
    is_flag=True,
    help="Show per-shard node information (including async vector queue length and compression).",
)
@click.option(
    "--collections",
    is_flag=True,
    help="Show per-collection node information.",
)
@click.option(
    "--collection",
    default=GetNodesDefaults.collection,
    help="Filter shard details to a specific collection (may be combined with --shards and --shard).",
    shell_complete=collection_name_complete,
)
@click.option(
    "--shard",
    default=None,
    type=str,
    help="Filter shard details to a specific shard name (may be combined with --shards and --collection).",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def list_nodes_cli(
    ctx: click.Context,
    minimal: bool,
    shards: bool,
    collections: bool,
    collection: str | None,
    shard: str | None,
    json_output: bool | None,
) -> None:
    """List cluster nodes and their status."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "node list"
    client: WeaviateClient | None = None
    try:
        shard_view = bool(shards or collection or shard)
        if sum([shard_view, collections, minimal]) > 1:
            raise CLIError(
                code="CONFLICTING_OPTIONS",
                message=(
                    "Shard options (--shards, --collection, --shard) cannot be combined "
                    "with --minimal or --collections, and --minimal cannot be combined "
                    "with --collections."
                ),
                exit_code=ExitCode.USAGE,
            )
        client = get_client_from_context(ctx)
        node_man = NodeManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: node_man.get_nodes(
                minimal=minimal,
                shards=shards,
                collections=collections,
                collection=collection,
                shard=shard,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@node_group.command(
    "stats",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\nExamples:\n  weaviate-cli node stats\n  weaviate-cli node stats --no-json"
    ),
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def node_stats_cli(
    ctx: click.Context,
    json_output: bool | None,
) -> None:
    """Show Raft consensus and cluster synchronization statistics (/v1/cluster/statistics)."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "node stats"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        node_man = NodeManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: node_man.get_cluster_statistics(json_output=as_json),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()
