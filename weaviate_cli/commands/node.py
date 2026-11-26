import sys

import click
from weaviate import WeaviateClient

from weaviate_cli.completion.complete import collection_name_complete
from weaviate_cli.defaults import GetNodesDefaults
from weaviate_cli.managers.node_manager import NodeManager
from weaviate_cli.utils import get_client_from_context


@click.group("node")
def node_group() -> None:
    """Inspect Weaviate cluster nodes."""


@node_group.command("list")
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
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def list_nodes_cli(
    ctx: click.Context,
    minimal: bool,
    shards: bool,
    collections: bool,
    collection: str | None,
    json_output: bool,
) -> None:
    """List cluster nodes and their status."""
    client: WeaviateClient | None = None
    try:
        if sum([bool(collection), shards, collections, minimal]) > 1:
            raise Exception(
                "Only one of --collection, --shards, --minimal, or --collections can be provided."
            )
        client = get_client_from_context(ctx)
        node_man = NodeManager(client)
        node_man.get_nodes(
            minimal=minimal,
            shards=shards,
            collections=collections,
            collection=collection,
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
