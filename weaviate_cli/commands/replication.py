"""Click commands for the 'replication' resource group."""

from __future__ import annotations

from typing import Any

import click
from weaviate import WeaviateClient

from weaviate_cli.completion.complete import collection_name_complete
from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.managers.cluster_manager import ClusterManager
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    AXGroup,
    emit_success,
    get_runtime,
    handle_command_error,
    require_confirmation,
)
from weaviate_cli.utils import get_client_from_context


def _replication_to_dict(op: Any, *, include_history: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {
        "uuid": str(op.uuid),
        "type": op.transfer_type.value,
        "collection": op.collection,
        "shard": op.shard,
        "source_node": op.source_node,
        "target_node": op.target_node,
        "status": op.status.state.value,
        "errors": list(op.status.errors) if op.status.errors else [],
    }
    if include_history and op.status_history is not None:
        data["status_history"] = [
            {
                "state": s.state.value,
                "errors": list(s.errors) if s.errors else [],
            }
            for s in op.status_history
        ]
    return data


@click.group("replication", cls=AXGroup)
def replication_group() -> None:
    """Manage shard replication operations in Weaviate."""


@replication_group.command("create", context_settings=DEFAULT_CONTEXT_SETTINGS)
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
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def create_replication_cli(
    ctx: click.Context,
    collection: str,
    shard: str,
    source_node: str,
    target_node: str,
    type_: str,
    json_output: bool | None,
) -> None:
    """Create and start a shard replication operation."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "replication create"
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
        msg = f"Replication successfully started with UUID: {uuid}."
        emit_success(
            runtime,
            {"status": "success", "uuid": str(uuid), "message": msg},
            command=command,
            text_renderer=lambda: click.echo(msg),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@replication_group.command("list", context_settings=DEFAULT_CONTEXT_SETTINGS)
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
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def list_replications_cli(
    ctx: click.Context,
    collection: str | None,
    shard: str | None,
    target_node: str | None,
    history: bool,
    json_output: bool | None,
) -> None:
    """List replication operations, optionally filtered by collection, shard, or node."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "replication list"
    client: WeaviateClient | None = None
    try:
        if shard and not collection:
            raise CLIError(
                code="INVALID_OPTIONS",
                message="Please provide --collection when specifying --shard.",
                exit_code=ExitCode.USAGE,
            )
        if target_node and (collection or shard):
            raise CLIError(
                code="CONFLICTING_OPTIONS",
                message="Provide either --collection/--shard or --target-node, not both.",
                exit_code=ExitCode.USAGE,
            )

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

        reps = [_replication_to_dict(op, include_history=history) for op in (ops or [])]
        emit_success(
            runtime,
            {"replications": reps},
            command=command,
            text_renderer=lambda: manager.print_replications(ops, json_output=False),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@replication_group.command("get", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("op_id")
@click.option(
    "--history/--no-history",
    default=False,
    help="Include replication operation history.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def get_replication_cli(
    ctx: click.Context, op_id: str, history: bool, json_output: bool | None
) -> None:
    """Get a replication operation by OP_ID."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "replication get"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        manager = ClusterManager(client, click.echo)
        op = manager.get_replication(op_id=op_id, include_history=history)
        if op is None:
            raise CLIError(
                code="REPLICATION_NOT_FOUND",
                message=f"No replication operation found with UUID '{op_id}'.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli replication list' to see existing replication operations.",
            )
        emit_success(
            runtime,
            _replication_to_dict(op, include_history=True),
            command=command,
            text_renderer=lambda: manager.print_replication(op, json_output=False),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@replication_group.command("cancel", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("op_id")
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def cancel_replication_cli(
    ctx: click.Context, op_id: str, json_output: bool | None
) -> None:
    """Cancel a replication operation by OP_ID."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "replication cancel"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        manager = ClusterManager(client)
        manager.cancel_replication(op_id=op_id)
        msg = f"Replication with UUID '{op_id}' cancelled successfully."
        emit_success(
            runtime,
            {"status": "success", "uuid": op_id, "message": msg},
            command=command,
            text_renderer=lambda: click.echo(msg),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@replication_group.command("delete", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("op_id", required=False, default=None)
@click.option(
    "--all",
    "delete_all",
    is_flag=True,
    help="Delete all replication operations (requires --yes).",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm deleting all replication operations (required with --all).",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def delete_replication_cli(
    ctx: click.Context,
    op_id: str | None,
    delete_all: bool,
    yes: bool,
    json_output: bool | None,
) -> None:
    """Delete a replication operation by OP_ID, or all with --all --yes."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "replication delete"

    if delete_all and op_id:
        handle_command_error(
            ctx,
            runtime,
            CLIError(
                code="CONFLICTING_OPTIONS",
                message="Cannot specify both OP_ID and --all.",
                exit_code=ExitCode.USAGE,
            ),
            command=command,
        )
    if not delete_all and not op_id:
        handle_command_error(
            ctx,
            runtime,
            CLIError(
                code="MISSING_OP_ID",
                message="Either OP_ID or --all must be specified.",
                exit_code=ExitCode.USAGE,
                hint="Example: 'weaviate-cli replication delete <op-id>' or 'weaviate-cli replication delete --all --yes'.",
            ),
            command=command,
        )
    if delete_all:
        require_confirmation(
            runtime,
            yes=yes,
            command=command,
            message="Deleting all replication operations is destructive and requires --yes.",
            hint="Re-run with 'weaviate-cli replication delete --all --yes' after confirming.",
        )

    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        manager = ClusterManager(client)
        if delete_all:
            manager.delete_all_replication()
            msg = "All replications scheduled for deletion successfully."
            emit_success(
                runtime,
                {"status": "success", "deleted_all": True, "message": msg},
                command=command,
                text_renderer=lambda: click.echo(msg),
            )
        else:
            assert op_id is not None
            manager.delete_replication(op_id=op_id)
            msg = f"Replication scheduled for deletion successfully with UUID: {op_id}"
            emit_success(
                runtime,
                {"status": "success", "uuid": op_id, "message": msg},
                command=command,
                text_renderer=lambda: click.echo(msg),
            )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()
