import json

import click
import semver
from weaviate.backup.backup import BackupConfigCreate, BackupReturn, BackupStorage
from weaviate.client import WeaviateClient

from weaviate_cli.defaults import (
    CancelBackupDefaults,
    CreateBackupDefaults,
    GetBackupDefaults,
    RestoreBackupDefaults,
)


class BackupManager:
    def __init__(self, client: WeaviateClient) -> None:
        self.client: WeaviateClient = client

    def create_backup(
        self,
        backup_id: str = CreateBackupDefaults.backup_id,
        backend: str = CreateBackupDefaults.backend,
        include: str | None = CreateBackupDefaults.include,
        exclude: str | None = CreateBackupDefaults.exclude,
        wait: bool = CreateBackupDefaults.wait,
        cpu_for_backup: int = CreateBackupDefaults.cpu_for_backup,
        json_output: bool = False,
        incremental_base_backup_id: (
            str | None
        ) = CreateBackupDefaults.incremental_base_backup_id,
    ) -> None:
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

        result = self.client.backup.create(
            backup_id=backup_id,
            backend=BackupStorage(backend.lower()),
            incremental_base_backup_id=incremental_base_backup_id,
            include_collections=include.split(",") if include else None,
            exclude_collections=exclude.split(",") if exclude else None,
            wait_for_completion=wait,
            config=(
                BackupConfigCreate(
                    cpu_percentage=cpu_for_backup,
                )
                if version.compare(semver.Version.parse("1.25.0")) > 0
                else None
            ),
        )

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
        backup_id: str = RestoreBackupDefaults.backup_id,
        backend: str = RestoreBackupDefaults.backend,
        include: str | None = RestoreBackupDefaults.include,
        exclude: str | None = RestoreBackupDefaults.exclude,
        wait: bool = RestoreBackupDefaults.wait,
        override_alias: bool = RestoreBackupDefaults.override_alias,
        json_output: bool = False,
    ) -> None:
        result = self.client.backup.restore(
            backup_id=backup_id,
            backend=BackupStorage(backend.lower()),
            include_collections=include.split(",") if include else None,
            exclude_collections=exclude.split(",") if exclude else None,
            overwrite_alias=override_alias,
            wait_for_completion=wait,
        )

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
        json_output: bool = False,
    ) -> None:
        if backup_id is None:
            if restore:
                raise ValueError("A backup ID is required for restore status.")
            raise Exception("This functionality is not supported yet.")

        get_status = (
            self.client.backup.get_restore_status
            if restore
            else self.client.backup.get_create_status
        )
        backup = get_status(backup_id=backup_id, backend=BackupStorage(backend.lower()))
        if json_output:
            data: dict[str, str | list[str]] = {
                "backup_id": backup.backup_id,
                "path": backup.path,
                "status": str(backup.status),
            }
            if isinstance(backup, BackupReturn):
                data["collections"] = backup.collections
            click.echo(json.dumps(data, indent=2, default=str))
        else:
            print(f"Backup ID: {backup.backup_id}")
            print(f"Backup Path: {backup.path}")
            print(f"Backup Status: {backup.status}")
            if isinstance(backup, BackupReturn):
                print(f"Collections: {backup.collections}")

    def cancel_backup(
        self,
        backend: str = CancelBackupDefaults.backend,
        backup_id: str = CancelBackupDefaults.backup_id,
        json_output: bool = False,
    ) -> None:
        storage = BackupStorage(backend.lower())
        if self.client.backup.cancel(backend=storage, backup_id=backup_id):
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "success",
                            "message": f"Backup '{backup_id}' cancelled successfully in Weaviate.",
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(f"Backup '{backup_id}' cancelled successfully in Weaviate.")
        else:
            backup_status = self.client.backup.get_create_status(
                backend=storage, backup_id=backup_id
            )
            raise Exception(
                f"Error: Backup '{backup_id}' could not be cancelled in Weaviate. Current status: {backup_status.status}"
            )
