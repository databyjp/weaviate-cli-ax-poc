import json
import sys

import click
from weaviate import WeaviateClient
from weaviate.exceptions import WeaviateConnectionError

from weaviate_cli.completion.complete import collection_name_complete
from weaviate_cli.managers.cluster_manager import ClusterManager
from weaviate_cli.utils import get_client_from_context


@click.group("replication")
def replication_group() -> None:
    """Manage shard replication operations in Weaviate."""


@replication_group.command("create")
@click.option(
    "--collection",
    required=True,
    help="The name of the collection containing the shard to replicate.",
    shell_complete=collection_name_complete,
)
@click.option(
    "--shard",
    required=True,
    help="The shard to replicate.",
)
@click.option(
    "--source-node",
    required=True,
    help="The source node of the shard replication.",
)
@click.option(
    "--target-node",
    required=True,
    help="The target node of the shard replication.",
)
@click.option(
    "--type",
    "type_",
    default="MOVE",
    type=click.Choice(["COPY", "MOVE"]),
    help="The type of replication to perform (default: 'MOVE').",
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def create_replication_cli(
    ctx: click.Context,
    collection: str,
    shard: str,
    source_node: str,
    target_node: str,
    type_: str,
    json_output: bool,
) -> None:
    """Create and start a shard replication operation."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        manager = ClusterManager(client)
        uuid = manager.start_replication(
            collection=collection,
            shard=shard,
            source_node=source_node,
            target_node=target_node,
            type_=type_,
        )
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "status": "success",
                        "uuid": str(uuid),
                        "message": f"Replication successfully started with UUID: {uuid}.",
                    },
                    indent=2,
                )
            )
        else:
            click.echo(f"Replication successfully started with UUID: {uuid}.")
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


@replication_group.command("list")
@click.option(
    "--collection",
    default=None,
    help="Filter replications by collection.",
    shell_complete=collection_name_complete,
)
@click.option(
    "--shard",
    default=None,
    help="Filter replications by shard (requires --collection).",
)
@click.option(
    "--target-node",
    default=None,
    help="Filter replications by target node.",
)
@click.option(
    "--history/--no-history",
    default=False,
    help="Include replication operation history.",
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def list_replications_cli(
    ctx: click.Context,
    collection: str | None,
    shard: str | None,
    target_node: str | None,
    history: bool,
    json_output: bool,
) -> None:
    """List replication operations, optionally filtered by collection, shard, or node."""
    client: WeaviateClient | None = None
    try:
        if shard and not collection:
            click.echo("Please provide a collection when specifying a shard.")
            sys.exit(1)

        if target_node and (collection or shard):
            click.echo(
                "Please provide either collection and shard, or target-node, but not both."
            )
            sys.exit(1)

        client = get_client_from_context(ctx)
        manager = ClusterManager(client, click.echo)
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


@replication_group.command("get")
@click.argument("op_id")
@click.option(
    "--history/--no-history",
    default=False,
    help="Include replication operation history.",
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def get_replication_cli(
    ctx: click.Context, op_id: str, history: bool, json_output: bool
) -> None:
    """Get a replication operation by OP_ID."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        manager = ClusterManager(client, click.echo)
        op = manager.get_replication(op_id=op_id, include_history=history)
        if op is not None:
            manager.print_replication(op, json_output=json_output)
        else:
            click.echo(f"No replication operation found with UUID '{op_id}'")
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@replication_group.command("cancel")
@click.argument("op_id")
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def cancel_replication_cli(ctx: click.Context, op_id: str, json_output: bool) -> None:
    """Cancel a replication operation by OP_ID."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        manager = ClusterManager(client)
        manager.cancel_replication(op_id=op_id)
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "status": "success",
                        "message": f"Replication with UUID '{op_id}' cancelled successfully.",
                    },
                    indent=2,
                )
            )
        else:
            click.echo(f"Replication with UUID '{op_id}' cancelled successfully.")
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@replication_group.command("delete")
@click.argument("op_id", required=False, default=None)
@click.option(
    "--all", "delete_all", is_flag=True, help="Delete all replication operations."
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def delete_replication_cli(
    ctx: click.Context, op_id: str | None, delete_all: bool, json_output: bool
) -> None:
    """Delete a replication operation by OP_ID, or all with --all."""
    if delete_all and op_id:
        raise click.UsageError("Cannot specify both OP_ID and --all.")
    if not delete_all and not op_id:
        raise click.UsageError("Either OP_ID or --all must be specified.")

    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        manager = ClusterManager(client)
        if delete_all:
            manager.delete_all_replication()
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "success",
                            "message": "All replications scheduled for deletion successfully.",
                        },
                        indent=2,
                    )
                )
            else:
                click.echo("All replications scheduled for deletion successfully.")
        else:
            assert op_id is not None
            manager.delete_replication(op_id=op_id)
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "success",
                            "message": f"Replication scheduled for deletion successfully with UUID: {op_id}",
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(
                    f"Replication scheduled for deletion successfully with UUID: {op_id}"
                )
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()
