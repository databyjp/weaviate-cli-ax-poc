"""Click commands for the 'backup' resource group."""

from __future__ import annotations

import click
from weaviate import WeaviateClient

from weaviate_cli.defaults import (
    CancelBackupDefaults,
    CreateBackupDefaults,
    GetBackupDefaults,
    RestoreBackupDefaults,
)
from weaviate_cli.managers.backup_manager import (
    COMPRESSION_LEVEL_CHOICES,
    BackupManager,
)
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    AXGroup,
    emit_captured_json_or_text,
    get_runtime,
    handle_command_error,
    require_confirmation,
)
from weaviate_cli.utils import get_client_from_context

BACKUP_BACKENDS = ["s3", "gcs", "azure", "filesystem"]


@click.group("backup", cls=AXGroup)
def backup_group() -> None:
    """Manage backups and restores in Weaviate."""


@backup_group.command(
    "list",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli backup list --backend s3\n"
        "  weaviate-cli backup list --backend filesystem --sort-asc"
    ),
)
@click.option(
    "--backend",
    default=GetBackupDefaults.backend,
    type=click.Choice(BACKUP_BACKENDS),
    help=f"Backup storage backend (default: '{GetBackupDefaults.backend}').",
)
@click.option(
    "--sort-asc",
    is_flag=True,
    default=False,
    help="Sort backups by starting time ascending.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def list_backups_cli(
    ctx: click.Context,
    backend: str,
    sort_asc: bool,
    json_output: bool | None,
) -> None:
    """List existing backups for a storage backend."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "backup list"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        backup_manager = BackupManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: backup_manager.list_backups(
                backend=backend,
                sort_asc=True if sort_asc else None,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@backup_group.command(
    "create",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli backup create bk-2026 --backend s3 --include Articles --wait\n"
        "  weaviate-cli backup create bk-rbac --backend azure --bucket backups --path prod/2026 --compression-level zstd-default --include-roles Admin"
    ),
)
@click.argument("backup_id")
@click.option(
    "--backend",
    default=CreateBackupDefaults.backend,
    type=click.Choice(BACKUP_BACKENDS),
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
    "--compression-level",
    default=CreateBackupDefaults.compression_level,
    type=click.Choice(list(COMPRESSION_LEVEL_CHOICES), case_sensitive=False),
    help="Backup compression level (e.g. default, best-speed, best-compression, zstd-default, no-compression).",
)
@click.option(
    "--bucket",
    default=CreateBackupDefaults.bucket,
    help="Custom storage bucket/container name (s3, gcs, azure; requires --path).",
)
@click.option(
    "--path",
    default=CreateBackupDefaults.path,
    help="Custom storage path within the backend or bucket.",
)
@click.option(
    "--include-roles",
    default=CreateBackupDefaults.include_roles,
    help="Comma separated list of RBAC role names to include in the backup.",
)
@click.option(
    "--include-users",
    default=CreateBackupDefaults.include_users,
    help="Comma separated list of DB user IDs to include in the backup.",
)
@click.option(
    "--incremental-base-backup-id",
    default=CreateBackupDefaults.incremental_base_backup_id,
    help="Backup ID of the previous backup to create an incremental backup from.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
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
    compression_level: str | None,
    bucket: str | None,
    path: str | None,
    include_roles: str | None,
    include_users: str | None,
    incremental_base_backup_id: str | None,
    json_output: bool | None,
) -> None:
    """Create a backup in Weaviate."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "backup create"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        backup_manager = BackupManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: backup_manager.create_backup(
                backend=backend,
                backup_id=backup_id,
                include=include,
                exclude=exclude,
                wait=wait,
                cpu_for_backup=cpu_for_backup,
                compression_level=compression_level,
                bucket=bucket,
                path=path,
                include_roles=include_roles,
                include_users=include_users,
                incremental_base_backup_id=incremental_base_backup_id,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@backup_group.command("get", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("backup_id")
@click.option(
    "--backend",
    default=GetBackupDefaults.backend,
    type=click.Choice(BACKUP_BACKENDS),
    help=f"Backup storage backend (default: '{GetBackupDefaults.backend}').",
)
@click.option(
    "--restore",
    is_flag=True,
    default=GetBackupDefaults.restore,
    help="Get the status of the restoration job instead of the backup job.",
)
@click.option(
    "--bucket",
    default=None,
    help="Custom storage bucket/container name (s3, gcs, azure; requires --path).",
)
@click.option(
    "--path",
    default=None,
    help="Custom storage path within the backend or bucket.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def get_backup_cli(
    ctx: click.Context,
    backup_id: str,
    backend: str,
    restore: bool,
    bucket: str | None,
    path: str | None,
    json_output: bool | None,
) -> None:
    """Get backup status (or restore job status with --restore)."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "backup get"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        backup_man = BackupManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: backup_man.get_backup(
                backend=backend,
                backup_id=backup_id,
                restore=restore,
                bucket=bucket,
                path=path,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@backup_group.command(
    "restore",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli backup restore bk-2026 --backend s3 --wait --yes\n"
        "  weaviate-cli backup restore bk-rbac --backend s3 --roles-restore all --users-restore all --cpu-for-restore 60 --yes"
    ),
)
@click.argument("backup_id")
@click.option(
    "--backend",
    default=RestoreBackupDefaults.backend,
    type=click.Choice(BACKUP_BACKENDS),
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
    "--roles-restore",
    default=RestoreBackupDefaults.roles_restore,
    type=click.Choice(["all", "none", "noRestore"], case_sensitive=False),
    help="Restore RBAC roles from backup ('all' or 'none'/'noRestore').",
)
@click.option(
    "--users-restore",
    default=RestoreBackupDefaults.users_restore,
    type=click.Choice(["all", "none", "noRestore"], case_sensitive=False),
    help="Restore DB users from backup ('all' or 'none'/'noRestore').",
)
@click.option(
    "--cpu-for-restore",
    default=RestoreBackupDefaults.cpu_for_restore,
    type=int,
    help="Percentage of CPU to allocate for the restore.",
)
@click.option(
    "--bucket",
    default=RestoreBackupDefaults.bucket,
    help="Custom storage bucket/container name (s3, gcs, azure; requires --path).",
)
@click.option(
    "--path",
    default=RestoreBackupDefaults.path,
    help="Custom storage path within the backend or bucket.",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm restoring the backup onto the cluster.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
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
    roles_restore: str | None,
    users_restore: str | None,
    cpu_for_restore: int | None,
    bucket: str | None,
    path: str | None,
    yes: bool,
    json_output: bool | None,
) -> None:
    """Restore a backup in Weaviate (requires --yes)."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "backup restore"
    require_confirmation(
        runtime,
        yes=yes,
        command=command,
        message=f"Restoring backup '{backup_id}' modifies cluster data and requires --yes.",
        hint=f"Re-run with 'weaviate-cli backup restore {backup_id} --backend {backend} --yes' after confirming.",
    )

    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        backup_manager = BackupManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: backup_manager.restore_backup(
                backend=backend,
                backup_id=backup_id,
                include=include,
                exclude=exclude,
                wait=wait,
                override_alias=override_alias,
                roles_restore=roles_restore,
                users_restore=users_restore,
                cpu_for_restore=cpu_for_restore,
                bucket=bucket,
                path=path,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@backup_group.command(
    "cancel",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli backup cancel bk-2026 --backend s3\n"
        "  weaviate-cli backup cancel bk-2026 --backend s3 --restore"
    ),
)
@click.argument("backup_id")
@click.option(
    "--backend",
    default=CancelBackupDefaults.backend,
    type=click.Choice(BACKUP_BACKENDS),
    help=f"Backup storage backend (default: '{CancelBackupDefaults.backend}').",
)
@click.option(
    "--restore",
    is_flag=True,
    default=CancelBackupDefaults.restore,
    help="Cancel an in-progress restore operation instead of a backup creation.",
)
@click.option(
    "--bucket",
    default=CancelBackupDefaults.bucket,
    help="Custom storage bucket/container name (s3, gcs, azure; requires --path).",
)
@click.option(
    "--path",
    default=CancelBackupDefaults.path,
    help="Custom storage path within the backend or bucket.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def cancel_backup_cli(
    ctx: click.Context,
    backup_id: str,
    backend: str,
    restore: bool,
    bucket: str | None,
    path: str | None,
    json_output: bool | None,
) -> None:
    """Cancel an in-progress backup (or restore with --restore) in Weaviate."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "backup cancel"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        backup_manager = BackupManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: backup_manager.cancel_backup(
                backend=backend,
                backup_id=backup_id,
                restore=restore,
                bucket=bucket,
                path=path,
                json_output=as_json,
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()
