from __future__ import annotations

import json
from typing import Any, Literal

import click
import semver
from prettytable import PrettyTable
from weaviate.backup.backup import (
    BackupCompressionLevel,
    BackupConfigCreate,
    BackupConfigRestore,
    BackupReturn,
    BackupStorage,
)
from weaviate.classes.backup import BackupLocation
from weaviate.client import WeaviateClient

from weaviate_cli.defaults import (
    CancelBackupDefaults,
    CreateBackupDefaults,
    GetBackupDefaults,
    RestoreBackupDefaults,
)
from weaviate_cli.errors import CLIError, ExitCode

COMPRESSION_LEVEL_MAP: dict[str, BackupCompressionLevel] = {
    "default": BackupCompressionLevel.DEFAULT,
    "defaultcompression": BackupCompressionLevel.DEFAULT,
    "best-speed": BackupCompressionLevel.BEST_SPEED,
    "bestspeed": BackupCompressionLevel.BEST_SPEED,
    "best-compression": BackupCompressionLevel.BEST_COMPRESSION,
    "bestcompression": BackupCompressionLevel.BEST_COMPRESSION,
    "zstd-best-speed": BackupCompressionLevel.ZSTD_BEST_SPEED,
    "zstdbestspeed": BackupCompressionLevel.ZSTD_BEST_SPEED,
    "zstd-default": BackupCompressionLevel.ZSTD_DEFAULT,
    "zstddefaultcompression": BackupCompressionLevel.ZSTD_DEFAULT,
    "zstd-best-compression": BackupCompressionLevel.ZSTD_BEST_COMPRESSION,
    "zstdbestcompression": BackupCompressionLevel.ZSTD_BEST_COMPRESSION,
    "no-compression": BackupCompressionLevel.NO_COMPRESSION,
    "nocompression": BackupCompressionLevel.NO_COMPRESSION,
}

COMPRESSION_LEVEL_CHOICES: tuple[str, ...] = (
    "default",
    "best-speed",
    "best-compression",
    "zstd-best-speed",
    "zstd-default",
    "zstd-best-compression",
    "no-compression",
)


def _split_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    parts = [item.strip() for item in value.split(",") if item.strip()]
    return parts or None


def _normalize_rbac_restore(
    value: str | None, *, flag_name: str
) -> Literal["noRestore", "all"] | None:
    if value is None:
        return None
    low = value.lower()
    if low in ("none", "norestore"):
        return "noRestore"
    if low == "all":
        return "all"
    raise CLIError(
        code="INVALID_RESTORE_OPTION",
        message=f"Invalid value '{value}' for {flag_name}.",
        exit_code=ExitCode.USAGE,
        hint="Use 'all' or 'none' (or 'noRestore').",
    )


def _resolve_compression_level(value: str | None) -> BackupCompressionLevel | None:
    if value is None:
        return None
    resolved = COMPRESSION_LEVEL_MAP.get(value.lower())
    if resolved is None:
        raise CLIError(
            code="INVALID_COMPRESSION_LEVEL",
            message=f"Invalid compression level '{value}'.",
            exit_code=ExitCode.USAGE,
            hint=f"Valid values: {', '.join(COMPRESSION_LEVEL_CHOICES)}.",
        )
    return resolved


def _build_backup_location(
    backend: str,
    bucket: str | None,
    path: str | None,
) -> Any:
    if bucket is None and path is None:
        return None
    backend_low = backend.lower()
    if backend_low == "filesystem":
        if bucket is not None:
            raise CLIError(
                code="INVALID_BACKUP_LOCATION",
                message="--bucket cannot be used with the 'filesystem' backend.",
                exit_code=ExitCode.USAGE,
                hint="Use --path alone for filesystem backup locations.",
            )
        assert path is not None
        return BackupLocation.FileSystem(path=path)

    if not bucket or not path:
        raise CLIError(
            code="INVALID_BACKUP_LOCATION",
            message=f"Both --bucket and --path are required for custom '{backend_low}' backup locations.",
            exit_code=ExitCode.USAGE,
        )
    if backend_low == "s3":
        return BackupLocation.S3(bucket=bucket, path=path)
    if backend_low == "gcs":
        return BackupLocation.GCP(bucket=bucket, path=path)
    if backend_low == "azure":
        return BackupLocation.Azure(bucket=bucket, path=path)
    raise CLIError(
        code="INVALID_BACKEND",
        message=f"Unsupported backup backend '{backend}'.",
        exit_code=ExitCode.USAGE,
    )


class BackupManager:
    def __init__(self, client: WeaviateClient) -> None:
        self.client: WeaviateClient = client

    def list_backups(
        self,
        backend: str = GetBackupDefaults.backend,
        sort_asc: bool | None = None,
        json_output: bool = False,
    ) -> list[dict[str, Any]]:
        storage = BackupStorage(backend.lower())
        raw_backups = self.client.backup.list_backups(
            backend=storage,
            sort_by_starting_time_asc=sort_asc,
        )
        rows: list[dict[str, Any]] = []
        for entry in raw_backups:
            status_val = getattr(entry.status, "value", str(entry.status))
            row: dict[str, Any] = {
                "backup_id": entry.backup_id,
                "status": str(status_val),
                "collections": list(entry.collections or []),
                "started_at": str(entry.started_at) if entry.started_at else None,
                "completed_at": str(entry.completed_at) if entry.completed_at else None,
                "size_gb": entry.size,
            }
            inc_base = getattr(entry, "incremental_base_backup_id", None)
            if inc_base:
                row["incremental_base_backup_id"] = inc_base
            rows.append(row)

        if json_output:
            click.echo(
                json.dumps(
                    {"backend": storage.value, "backups": rows, "total": len(rows)},
                    indent=2,
                    default=str,
                )
            )
        else:
            if not rows:
                click.echo(f"No backups found on backend '{storage.value}'.")
            else:
                table = PrettyTable()
                table.field_names = [
                    "Backup ID",
                    "Status",
                    "Collections",
                    "Started At",
                    "Size (GB)",
                ]
                table.align = "l"
                for row in rows:
                    cols_str = (
                        ", ".join(row["collections"]) if row["collections"] else "-"
                    )
                    table.add_row(
                        [
                            row["backup_id"],
                            row["status"],
                            cols_str,
                            row["started_at"] or "-",
                            f"{row['size_gb']:.4f}"
                            if isinstance(row["size_gb"], (int, float))
                            else "-",
                        ]
                    )
                click.echo(table)
                click.echo(f"Total: {len(rows)} backup(s)")
        return rows

    def create_backup(
        self,
        backup_id: str | None = CreateBackupDefaults.backup_id,
        backend: str = CreateBackupDefaults.backend,
        include: str | None = CreateBackupDefaults.include,
        exclude: str | None = CreateBackupDefaults.exclude,
        wait: bool = CreateBackupDefaults.wait,
        cpu_for_backup: int = CreateBackupDefaults.cpu_for_backup,
        compression_level: str | None = CreateBackupDefaults.compression_level,
        bucket: str | None = CreateBackupDefaults.bucket,
        path: str | None = CreateBackupDefaults.path,
        include_roles: str | None = CreateBackupDefaults.include_roles,
        include_users: str | None = CreateBackupDefaults.include_users,
        json_output: bool = False,
        incremental_base_backup_id: (
            str | None
        ) = CreateBackupDefaults.incremental_base_backup_id,
    ) -> None:
        if not backup_id:
            raise CLIError(
                code="MISSING_BACKUP_ID",
                message="Backup ID is required.",
                exit_code=ExitCode.USAGE,
            )
        version = semver.Version.parse(self.client.get_meta()["version"])
        if include:
            for collection in include.split(","):
                if not self.client.collections.exists(collection):
                    raise Exception(
                        f"Collection '{collection}' does not exist in Weaviate. Cannot include in backup."
                    )
        if exclude:
            for collection in exclude.split(","):
                if not self.client.collections.exists(collection):
                    raise Exception(
                        f"Collection '{collection}' does not exist in Weaviate. Cannot exclude from backup."
                    )

        resolved_compression = _resolve_compression_level(compression_level)
        backup_location = _build_backup_location(backend, bucket, path)

        config = (
            BackupConfigCreate(
                cpu_percentage=cpu_for_backup,
                compression_level=resolved_compression,
            )
            if version.compare(semver.Version.parse("1.25.0")) > 0
            else None
        )

        create_kwargs: dict[str, Any] = {
            "backup_id": backup_id,
            "backend": BackupStorage(backend.lower()),
            "incremental_base_backup_id": incremental_base_backup_id,
            "include_collections": _split_csv(include),
            "exclude_collections": _split_csv(exclude),
            "wait_for_completion": wait,
            "config": config,
        }
        if backup_location is not None:
            create_kwargs["backup_location"] = backup_location
        parsed_roles = _split_csv(include_roles)
        if parsed_roles is not None:
            create_kwargs["include_roles"] = parsed_roles
        parsed_users = _split_csv(include_users)
        if parsed_users is not None:
            create_kwargs["include_users"] = parsed_users

        result = self.client.backup.create(**create_kwargs)

        if wait and result and result.status.value != "SUCCESS":
            raise Exception(
                f"Backup '{backup_id}' failed with status '{result.status.value}'"
            )

        if json_output:
            click.echo(
                json.dumps(
                    {
                        "status": "success",
                        "message": f"Backup '{backup_id}' created successfully in Weaviate.",
                    },
                    indent=2,
                )
            )
        else:
            click.echo(f"Backup '{backup_id}' created successfully in Weaviate.")

    def restore_backup(
        self,
        backup_id: str | None = RestoreBackupDefaults.backup_id,
        backend: str = RestoreBackupDefaults.backend,
        include: str | None = RestoreBackupDefaults.include,
        exclude: str | None = RestoreBackupDefaults.exclude,
        wait: bool = RestoreBackupDefaults.wait,
        override_alias: bool = RestoreBackupDefaults.override_alias,
        roles_restore: str | None = RestoreBackupDefaults.roles_restore,
        users_restore: str | None = RestoreBackupDefaults.users_restore,
        cpu_for_restore: int | None = RestoreBackupDefaults.cpu_for_restore,
        bucket: str | None = RestoreBackupDefaults.bucket,
        path: str | None = RestoreBackupDefaults.path,
        json_output: bool = False,
    ) -> None:
        if not backup_id:
            raise CLIError(
                code="MISSING_BACKUP_ID",
                message="Backup ID is required.",
                exit_code=ExitCode.USAGE,
            )

        norm_roles = _normalize_rbac_restore(roles_restore, flag_name="--roles-restore")
        norm_users = _normalize_rbac_restore(users_restore, flag_name="--users-restore")
        backup_location = _build_backup_location(backend, bucket, path)

        restore_kwargs: dict[str, Any] = {
            "backup_id": backup_id,
            "backend": BackupStorage(backend.lower()),
            "include_collections": _split_csv(include),
            "exclude_collections": _split_csv(exclude),
            "overwrite_alias": override_alias,
            "wait_for_completion": wait,
        }
        if norm_roles is not None:
            restore_kwargs["roles_restore"] = norm_roles
        if norm_users is not None:
            restore_kwargs["users_restore"] = norm_users
        if cpu_for_restore is not None:
            restore_kwargs["config"] = BackupConfigRestore(
                cpu_percentage=cpu_for_restore
            )
        if backup_location is not None:
            restore_kwargs["backup_location"] = backup_location

        result = self.client.backup.restore(**restore_kwargs)

        if wait and result and result.status.value != "SUCCESS":
            raise Exception(
                f"Backup '{backup_id}' failed with status '{result.status.value}'"
            )

        if json_output:
            click.echo(
                json.dumps(
                    {
                        "status": "success",
                        "message": f"Backup '{backup_id}' restored successfully in Weaviate.",
                    },
                    indent=2,
                )
            )
        else:
            click.echo(f"Backup '{backup_id}' restored successfully in Weaviate.")

    def get_backup(
        self,
        backend: str = GetBackupDefaults.backend,
        backup_id: str | None = GetBackupDefaults.backup_id,
        restore: bool = GetBackupDefaults.restore,
        bucket: str | None = None,
        path: str | None = None,
        json_output: bool = False,
    ) -> None:
        if backup_id is None:
            if restore:
                raise ValueError("A backup ID is required for restore status.")
            raise Exception("This functionality is not supported yet.")

        backup_location = _build_backup_location(backend, bucket, path)
        get_status = (
            self.client.backup.get_restore_status
            if restore
            else self.client.backup.get_create_status
        )
        status_kwargs: dict[str, Any] = {
            "backup_id": backup_id,
            "backend": BackupStorage(backend.lower()),
        }
        if backup_location is not None:
            status_kwargs["backup_location"] = backup_location
        backup = get_status(**status_kwargs)
        status_val = str(getattr(backup.status, "value", backup.status))
        if json_output:
            data: dict[str, str | list[str]] = {
                "backup_id": backup.backup_id,
                "path": backup.path,
                "status": status_val,
            }
            if isinstance(backup, BackupReturn):
                data["collections"] = backup.collections
            click.echo(json.dumps(data, indent=2, default=str))
        else:
            click.echo(f"Backup ID: {backup.backup_id}")
            click.echo(f"Backup Path: {backup.path}")
            click.echo(f"Backup Status: {status_val}")
            if isinstance(backup, BackupReturn):
                click.echo(f"Collections: {backup.collections}")

    def cancel_backup(
        self,
        backend: str = CancelBackupDefaults.backend,
        backup_id: str | None = CancelBackupDefaults.backup_id,
        restore: bool = CancelBackupDefaults.restore,
        bucket: str | None = CancelBackupDefaults.bucket,
        path: str | None = CancelBackupDefaults.path,
        json_output: bool = False,
    ) -> None:
        if not backup_id:
            raise CLIError(
                code="MISSING_BACKUP_ID",
                message="Backup ID is required.",
                exit_code=ExitCode.USAGE,
            )
        storage = BackupStorage(backend.lower())
        backup_location = _build_backup_location(backend, bucket, path)
        cancel_kwargs: dict[str, Any] = {
            "backend": storage,
            "backup_id": backup_id,
        }
        if restore:
            cancel_kwargs["operation"] = "restore"
        if backup_location is not None:
            cancel_kwargs["backup_location"] = backup_location

        action_label = "Backup restore" if restore else "Backup"
        if self.client.backup.cancel(**cancel_kwargs):
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "success",
                            "message": f"{action_label} '{backup_id}' cancelled successfully in Weaviate.",
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(
                    f"{action_label} '{backup_id}' cancelled successfully in Weaviate."
                )
        else:
            status_fn = (
                self.client.backup.get_restore_status
                if restore
                else self.client.backup.get_create_status
            )
            status_kwargs: dict[str, Any] = {"backend": storage, "backup_id": backup_id}
            if backup_location is not None:
                status_kwargs["backup_location"] = backup_location
            backup_status = status_fn(**status_kwargs)
            status_val = str(
                getattr(backup_status.status, "value", backup_status.status)
            )
            raise Exception(
                f"Error: {action_label} '{backup_id}' could not be cancelled in Weaviate. Current status: {status_val}"
            )
