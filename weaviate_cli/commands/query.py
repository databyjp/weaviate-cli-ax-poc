import sys
import click

from typing import Optional

from weaviate_cli.utils import get_client_from_context
from weaviate_cli.managers.cluster_manager import ClusterManager
from weaviate.exceptions import WeaviateConnectionError


# Query Group
@click.group()
def query() -> None:
    """Query resources in Weaviate."""
    pass


@query.command(
    "replications",
    help="Query replication operations in Weaviate. If no options are provided, all replications will be queried.",
)
@click.option(
    "--collection",
    default=None,
    help="The name of the collection to query replications for.",
)
@click.option(
    "--shard",
    default=None,
    help="The shard to query replications for. If not provided, all shards will be queried.",
)
@click.option(
    "--target-node",
    default=None,
    help="The target node to query replications for. If not provided, all nodes will be queried.",
)
@click.option(
    "--history/--no-history",
    default=False,
    help="Include the history of the replication operations.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Output in JSON format.",
)
@click.pass_context
def query_replications_cli(
    ctx: click.Context,
    collection: Optional[str],
    shard: Optional[str],
    target_node: Optional[str],
    history: bool,
    json_output: bool,
) -> None:
    """Query replication operations by collection, collection and shard, or target node in Weaviate."""

    client = None
    try:
        client = get_client_from_context(ctx)
        manager = ClusterManager(client, click.echo)

        if shard and not collection:
            click.echo("Please provide a collection when specifying a shard.")
            sys.exit(1)

        if target_node and (collection or shard):
            click.echo(
                "Please provide either collection and shard, or node, but not both."
            )
            sys.exit(1)

        if collection and not shard:
            ops = manager.query_replications_by_collection(collection, history)
        elif collection and shard:
            ops = manager.query_replications_by_shard(collection, shard, history)
        elif target_node:
            ops = manager.query_replications_by_node(target_node, history)
        else:
            ops = manager.query_all_replications(history)

        manager.print_replications(ops, json_output=json_output)

    except WeaviateConnectionError as e:
        click.echo(f"Connection error: {e}")
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@query.command("sharding-state")
@click.argument("collection")
@click.option(
    "--shard",
    default=None,
    help="The shard to query. If not provided, the state of all shards will be queried.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Output in JSON format.",
)
@click.pass_context
def query_sharding_state_cli(
    ctx: click.Context,
    collection: str,
    shard: Optional[str],
    json_output: bool,
):
    """Query the sharding state of a COLLECTION in Weaviate."""

    client = None
    try:
        client = get_client_from_context(ctx)
        manager = ClusterManager(client, click.echo)

        state = manager.query_sharding_state(collection, shard)

        if not state:
            click.echo(f"No sharding state found for collection '{collection}'")
            return

        if not json_output:
            if shard:
                click.echo(
                    f"Sharding state for collection '{collection}', shard '{shard}':"
                )
            else:
                click.echo(f"Sharding state for collection '{collection}':")

        manager.print_sharding_state(state, json_output=json_output)

    except WeaviateConnectionError as e:
        click.echo(f"Connection error: {e}")
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()
