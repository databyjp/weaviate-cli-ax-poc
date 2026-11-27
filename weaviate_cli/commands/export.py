"""Click commands for the 'export' resource group."""

from __future__ import annotations

import click
from weaviate import WeaviateClient

from weaviate_cli.defaults import (
    CancelExportCollectionDefaults,
    CreateExportCollectionDefaults,
    GetExportCollectionDefaults,
)
from weaviate_cli.managers.export_manager import ExportManager
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    AXGroup,
    emit_captured_json_or_text,
    get_runtime,
    handle_command_error,
)
from weaviate_cli.utils import get_client_from_context


@click.group("export", cls=AXGroup)
def export_group() -> None:
    """Manage collection exports in Weaviate."""


@export_group.command("create", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("export_id", default=CreateExportCollectionDefaults.export_id)
@click.option(
    "--backend",
    default=CreateExportCollectionDefaults.backend,
    type=click.Choice(["filesystem", "s3", "gcs", "azure"]),
    help=f"Export storage backend (default: '{CreateExportCollectionDefaults.backend}').",
)
@click.option(
    "--file-format",
    default=CreateExportCollectionDefaults.file_format,
    type=click.Choice(["parquet"]),
    help=f"Export file format (default: '{CreateExportCollectionDefaults.file_format}').",
)
@click.option(
    "--include",
    default=CreateExportCollectionDefaults.include,
    help="Comma separated list of collections to include in the export.",
)
@click.option(
    "--exclude",
    default=CreateExportCollectionDefaults.exclude,
    help="Comma separated list of collections to exclude from the export.",
)
@click.option(
    "--wait",
    is_flag=True,
    default=CreateExportCollectionDefaults.wait,
    help="Wait for the export to complete before returning.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def create_export_cli(
    ctx: click.Context,
    export_id: str,
    backend: str,
    file_format: str,
    include: str | None,
    exclude: str | None,
    wait: bool,
    json_output: bool | None,
) -> None:
    """Create a collection export in Weaviate."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "export create"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        export_manager = ExportManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: export_manager.create_export(
                export_id=export_id,
                backend=backend,
                file_format=file_format,
                include=include,
                exclude=exclude,
                wait=wait,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@export_group.command("get", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("export_id", default=GetExportCollectionDefaults.export_id)
@click.option(
    "--backend",
    default=GetExportCollectionDefaults.backend,
    type=click.Choice(["filesystem", "s3", "gcs", "azure"]),
    help=f"Export storage backend (default: '{GetExportCollectionDefaults.backend}').",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def get_export_cli(
    ctx: click.Context,
    export_id: str,
    backend: str,
    json_output: bool | None,
) -> None:
    """Get the status of a collection export."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "export get"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        export_manager = ExportManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: export_manager.get_export_status(
                export_id=export_id,
                backend=backend,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@export_group.command("cancel", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("export_id", default=CancelExportCollectionDefaults.export_id)
@click.option(
    "--backend",
    default=CancelExportCollectionDefaults.backend,
    type=click.Choice(["filesystem", "s3", "gcs", "azure"]),
    help=f"Export storage backend (default: '{CancelExportCollectionDefaults.backend}').",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def cancel_export_cli(
    ctx: click.Context,
    export_id: str,
    backend: str,
    json_output: bool | None,
) -> None:
    """Cancel an in-progress collection export."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "export cancel"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        export_manager = ExportManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: export_manager.cancel_export(
                export_id=export_id,
                backend=backend,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()
