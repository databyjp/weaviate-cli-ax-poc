import sys

import click
from weaviate import WeaviateClient

from weaviate_cli.defaults import (
    CancelExportCollectionDefaults,
    CreateExportCollectionDefaults,
    GetExportCollectionDefaults,
)
from weaviate_cli.managers.export_manager import ExportManager
from weaviate_cli.utils import get_client_from_context


@click.group("export")
def export_group() -> None:
    """Manage collection exports in Weaviate."""


@export_group.command("create")
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
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
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
    json_output: bool,
) -> None:
    """Create a collection export in Weaviate."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        export_manager = ExportManager(client)
        export_manager.create_export(
            export_id=export_id,
            backend=backend,
            file_format=file_format,
            include=include,
            exclude=exclude,
            wait=wait,
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


@export_group.command("get")
@click.argument("export_id", default=GetExportCollectionDefaults.export_id)
@click.option(
    "--backend",
    default=GetExportCollectionDefaults.backend,
    type=click.Choice(["filesystem", "s3", "gcs", "azure"]),
    help=f"Export storage backend (default: '{GetExportCollectionDefaults.backend}').",
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def get_export_cli(
    ctx: click.Context,
    export_id: str,
    backend: str,
    json_output: bool,
) -> None:
    """Get the status of a collection export."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        export_manager = ExportManager(client)
        export_manager.get_export_status(
            export_id=export_id,
            backend=backend,
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


@export_group.command("cancel")
@click.argument("export_id", default=CancelExportCollectionDefaults.export_id)
@click.option(
    "--backend",
    default=CancelExportCollectionDefaults.backend,
    type=click.Choice(["filesystem", "s3", "gcs", "azure"]),
    help=f"Export storage backend (default: '{CancelExportCollectionDefaults.backend}').",
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def cancel_export_cli(
    ctx: click.Context,
    export_id: str,
    backend: str,
    json_output: bool,
) -> None:
    """Cancel an in-progress collection export."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        export_manager = ExportManager(client)
        export_manager.cancel_export(
            export_id=export_id,
            backend=backend,
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
