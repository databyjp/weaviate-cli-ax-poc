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
    emit_captured_json_or_text,
    get_runtime,
    handle_command_error,
)
from weaviate_cli.utils import get_client_from_context


@click.group("node", context_settings=DEFAULT_CONTEXT_SETTINGS)
def node_group() -> None:
    """Inspect Weaviate cluster nodes."""


@node_group.command("list", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option(
    "--minimal",
    is_flag=True,
    help="Get minimal node information (fast for large clusters).",
)
@click.option(
    "--shards",
    is_flag=True,
    help="Show per-shard node information.",
)
@click.option(
    "--collections",
    is_flag=True,
    help="Show per-collection node information.",
)
@click.option(
    "--collection",
    default=GetNodesDefaults.collection,
    help="Filter shard details to a specific collection.",
    shell_complete=collection_name_complete,
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
    json_output: bool | None,
) -> None:
    """List cluster nodes and their status."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "node list"
    client: WeaviateClient | None = None
    try:
        if sum([bool(collection), shards, collections, minimal]) > 1:
            raise CLIError(
                code="CONFLICTING_OPTIONS",
                message="Only one of --collection, --shards, --minimal, or --collections can be provided.",
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
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()
