import sys

import click
from weaviate import WeaviateClient

from weaviate_cli.defaults import (
    CancelBackupDefaults,
    CreateBackupDefaults,
    GetBackupDefaults,
    RestoreBackupDefaults,
)
from weaviate_cli.managers.backup_manager import BackupManager
from weaviate_cli.utils import get_client_from_context


@click.group("backup")
def backup_group() -> None:
    """Manage backups and restores in Weaviate."""


@backup_group.command("create")
@click.argument("backup_id", default=CreateBackupDefaults.backup_id)
@click.option(
    "--backend",
    default=CreateBackupDefaults.backend,
    type=click.Choice(["s3", "gcs", "filesystem"]),
    help=f"Backup storage backend (default: '{CreateBackupDefaults.backend}').",
)
@click.option(
    "--include",
    default=CreateBackupDefaults.include,
    help="Comma separated list of collections to include in the backup.",
)
@click.option(
    "--exclude",
    default=CreateBackupDefaults.exclude,
    help="Comma separated list of collections to exclude from the backup.",
)
@click.option(
    "--wait",
    is_flag=True,
    default=CreateBackupDefaults.wait,
    help="Wait for the backup to complete before returning.",
)
@click.option(
    "--cpu-for-backup",
    default=CreateBackupDefaults.cpu_for_backup,
    type=int,
    help=f"Percentage of CPU to use for the backup (default: {CreateBackupDefaults.cpu_for_backup}).",
)
@click.option(
    "--incremental-base-backup-id",
    default=CreateBackupDefaults.incremental_base_backup_id,
    help="Backup ID of the previous backup to create an incremental backup from.",
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def create_backup_cli(
    ctx: click.Context,
    backup_id: str,
    backend: str,
    include: str | None,
    exclude: str | None,
    wait: bool,
    cpu_for_backup: int,
    incremental_base_backup_id: str | None,
    json_output: bool,
) -> None:
    """Create a backup in Weaviate."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        backup_manager = BackupManager(client)
        backup_manager.create_backup(
            backend=backend,
            backup_id=backup_id,
            include=include,
            exclude=exclude,
            wait=wait,
            cpu_for_backup=cpu_for_backup,
            incremental_base_backup_id=incremental_base_backup_id,
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


@backup_group.command("get")
@click.argument("backup_id", required=False, default=GetBackupDefaults.backup_id)
@click.option(
    "--backend",
    default=GetBackupDefaults.backend,
    type=click.Choice(["s3", "gcs", "filesystem"]),
    help=f"Backup storage backend (default: '{GetBackupDefaults.backend}').",
)
@click.option(
    "--restore",
    is_flag=True,
    default=GetBackupDefaults.restore,
    help="Get the status of the restoration job instead of the backup job.",
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def get_backup_cli(
    ctx: click.Context,
    backup_id: str | None,
    backend: str,
    restore: bool,
    json_output: bool,
) -> None:
    """Get backup status (or restore job status with --restore)."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        backup_man = BackupManager(client)
        backup_man.get_backup(
            backend=backend,
            backup_id=backup_id,
            restore=restore,
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


@backup_group.command("restore")
@click.argument("backup_id", default=RestoreBackupDefaults.backup_id)
@click.option(
    "--backend",
    default=RestoreBackupDefaults.backend,
    type=click.Choice(["s3", "gcs", "filesystem"]),
    help=f"Backup storage backend (default: '{RestoreBackupDefaults.backend}').",
)
@click.option(
    "--wait",
    is_flag=True,
    default=RestoreBackupDefaults.wait,
    help="Wait for the restore to complete before returning.",
)
@click.option(
    "--include",
    default=RestoreBackupDefaults.include,
    help="Comma separated list of collections to include in restore.",
)
@click.option(
    "--exclude",
    default=RestoreBackupDefaults.exclude,
    help="Comma separated list of collections to exclude from restore.",
)
@click.option(
    "--override-alias",
    is_flag=True,
    default=RestoreBackupDefaults.override_alias,
    help="Override existing collection aliases during restore.",
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def restore_backup_cli(
    ctx: click.Context,
    backup_id: str,
    backend: str,
    wait: bool,
    include: str | None,
    exclude: str | None,
    override_alias: bool,
    json_output: bool,
) -> None:
    """Restore a backup in Weaviate."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        backup_manager = BackupManager(client)
        backup_manager.restore_backup(
            backend=backend,
            backup_id=backup_id,
            include=include,
            exclude=exclude,
            wait=wait,
            override_alias=override_alias,
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


@backup_group.command("cancel")
@click.argument("backup_id", default=CancelBackupDefaults.backup_id)
@click.option(
    "--backend",
    default=CancelBackupDefaults.backend,
    type=click.Choice(["s3", "gcs", "filesystem"]),
    help=f"Backup storage backend (default: '{CancelBackupDefaults.backend}').",
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def cancel_backup_cli(
    ctx: click.Context,
    backup_id: str,
    backend: str,
    json_output: bool,
) -> None:
    """Cancel an in-progress backup in Weaviate."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        backup_manager = BackupManager(client)
        backup_manager.cancel_backup(
            backend=backend, backup_id=backup_id, json_output=json_output
        )
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()
