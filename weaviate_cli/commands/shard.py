import sys

import click
from weaviate import WeaviateClient
from weaviate.exceptions import WeaviateConnectionError

from weaviate_cli.completion.complete import collection_name_complete
from weaviate_cli.defaults import GetShardsDefaults, UpdateShardsDefaults
from weaviate_cli.managers.cluster_manager import ClusterManager
from weaviate_cli.managers.shard_manager import ShardManager
from weaviate_cli.utils import get_client_from_context


@click.group("shard")
def shard_group() -> None:
    """Inspect and manage collection shards."""


@shard_group.command("list")
@click.option(
    "--collection",
    default=GetShardsDefaults.collection,
    help="Filter shards to a specific collection.",
    shell_complete=collection_name_complete,
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def list_shards_cli(
    ctx: click.Context, collection: str | None, json_output: bool
) -> None:
    """List shards for all collections or a specific collection."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        client.collections.list_all()
        shard_man = ShardManager(client)
        shard_man.get_shards(
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


@shard_group.command("update")
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
    help="Update shards across all collections.",
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def update_shards_cli(
    ctx: click.Context,
    status: str,
    collection: str | None,
    shards: str | None,
    update_all: bool,
    json_output: bool,
) -> None:
    """Update shard statuses."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        shard_man = ShardManager(client)
        shard_man.update_shards(
            status=status,
            collection=collection,
            shards=shards,
            all=update_all,
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


@shard_group.command("state")
@click.argument("collection", shell_complete=collection_name_complete)
@click.option(
    "--shard",
    default=None,
    help="Filter sharding state to a specific shard.",
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def shard_state_cli(
    ctx: click.Context,
    collection: str,
    shard: str | None,
    json_output: bool,
) -> None:
    """Inspect sharding state for a collection."""
    client: WeaviateClient | None = None
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
