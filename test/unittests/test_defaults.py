from unittest.mock import MagicMock

import click
import pytest
from click.testing import CliRunner
from weaviate.collections.classes.tenants import TenantActivityStatus

from weaviate_cli.commands.create import (
    create_backup_cli,
    create_collection_cli,
    create_tenants_cli,
)
from weaviate_cli.commands.delete import (
    delete_collection_cli,
    delete_tenants_cli,
)
from weaviate_cli.commands.get import (
    get_backup_cli,
    get_collection_cli,
    get_shards_cli,
    get_tenants_cli,
)
from weaviate_cli.commands.restore import restore_backup_cli
from weaviate_cli.commands.update import (
    update_collection_cli,
    update_shards_cli,
    update_tenants_cli,
)
from weaviate_cli.defaults import *


@pytest.fixture
def runner():
    return CliRunner()


def test_create_collection_defaults(runner):
    ctx = click.Context(create_collection_cli)
    ctx.obj = {"config": MagicMock()}
    ctx.obj["config"].get_client = MagicMock()

    mock_client = MagicMock()
    mock_client.collections.exists.side_effect = [False, True]
    ctx.obj["config"].get_client.return_value = mock_client

    # Omitting --collection must fail (no implicit "Movies" default)
    missing_result = runner.invoke(create_collection_cli, obj=ctx.obj)
    assert missing_result.exit_code == 2

    result = runner.invoke(
        create_collection_cli, ["--collection", "TestCollection"], obj=ctx.obj
    )
    assert result.exit_code == 0, result.output
    assert CreateCollectionDefaults.collection is None
    assert CreateCollectionDefaults.replication_factor == 1
    assert CreateCollectionDefaults.object_ttl_property_name is None
    assert CreateCollectionDefaults.async_enabled is False
    assert CreateCollectionDefaults.vector_index == "hnsw"
    assert CreateCollectionDefaults.training_limit == 10000
    assert CreateCollectionDefaults.multitenant is False
    assert CreateCollectionDefaults.shards == 0


def test_create_tenants_defaults(runner):
    ctx = click.Context(create_tenants_cli)
    ctx.obj = {"config": MagicMock()}
    mock_client = MagicMock()

    mock_client.collections.exists.return_value = True
    mock_client.get_meta.return_value = {"version": "1.25.0"}

    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection

    mock_config = MagicMock()
    mock_config.multi_tenancy_config.enabled = True
    mock_collection.config.get.return_value = mock_config

    mock_collection.tenants.get.return_value = {}
    mock_tenants = {
        f"{CreateTenantsDefaults.tenant_suffix}-{i}": MagicMock(
            activity_status=TenantActivityStatus.ACTIVE
        )
        for i in range(CreateTenantsDefaults.number_tenants)
    }
    mock_collection.tenants.get_by_names.return_value = mock_tenants
    ctx.obj["config"].get_client.return_value = mock_client

    missing_result = runner.invoke(create_tenants_cli, obj=ctx.obj)
    assert missing_result.exit_code == 2

    result = runner.invoke(
        create_tenants_cli, ["--collection", "TestCollection"], obj=ctx.obj
    )
    assert result.exit_code == 0, result.output
    assert CreateTenantsDefaults.collection is None
    assert CreateTenantsDefaults.tenant_suffix == "Tenant"
    assert CreateTenantsDefaults.number_tenants == 100
    assert CreateTenantsDefaults.state == "active"


def test_create_backup_defaults(runner):
    ctx = click.Context(create_backup_cli)
    ctx.obj = {"config": MagicMock()}
    mock_client = MagicMock()
    mock_client.collections.exists.return_value = True
    mock_client.get_meta.return_value = {"version": "1.24.0"}
    mock_client.backup.create.return_value = MagicMock(
        status=MagicMock(value="SUCCESS")
    )
    ctx.obj["config"].get_client.return_value = mock_client

    result = runner.invoke(create_backup_cli, obj=ctx.obj)
    assert result.exit_code == 0, result.output
    assert CreateBackupDefaults.backend == "s3"
    assert CreateBackupDefaults.backup_id == "test-backup"
    assert CreateBackupDefaults.include is None
    assert CreateBackupDefaults.exclude is None
    assert CreateBackupDefaults.wait is False
    assert CreateBackupDefaults.cpu_for_backup == 40


def test_delete_collection_defaults(runner):
    ctx = click.Context(delete_collection_cli)
    ctx.obj = {"config": MagicMock()}
    mock_client = MagicMock()
    mock_client.collections.exists.side_effect = [True, False]
    ctx.obj["config"].get_client.return_value = mock_client

    # Omitting both --collection and --all must fail
    missing_result = runner.invoke(delete_collection_cli, obj=ctx.obj)
    assert missing_result.exit_code == 1

    result = runner.invoke(
        delete_collection_cli, ["--collection", "TestCollection"], obj=ctx.obj
    )
    assert result.exit_code == 0, result.output
    assert DeleteCollectionDefaults.collection is None
    assert DeleteCollectionDefaults.all is False


def test_delete_tenants_defaults(runner):
    ctx = click.Context(delete_tenants_cli)
    ctx.obj = {"config": MagicMock()}
    mock_client = MagicMock()
    mock_client.get_meta.return_value = {"version": "1.25.0"}
    mock_client.collections.exists.return_value = True

    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection

    mock_config = MagicMock()
    mock_config.multi_tenancy_config.enabled = True
    mock_collection.config.get.return_value = mock_config

    mock_tenants = {
        f"{DeleteTenantsDefaults.tenant_suffix}-{i}": MagicMock()
        for i in range(1, DeleteTenantsDefaults.number_tenants + 1)
    }
    mock_collection.tenants.get.side_effect = [mock_tenants, {}]

    ctx.obj["config"].get_client.return_value = mock_client

    missing_result = runner.invoke(delete_tenants_cli, obj=ctx.obj)
    assert missing_result.exit_code == 2

    result = runner.invoke(
        delete_tenants_cli, ["--collection", "TestCollection"], obj=ctx.obj
    )
    assert result.exit_code == 0, result.output
    assert DeleteTenantsDefaults.collection is None
    assert DeleteTenantsDefaults.tenant_suffix == "Tenant"
    assert DeleteTenantsDefaults.number_tenants == 100


def test_get_collection_defaults(runner):
    ctx = click.Context(get_collection_cli)
    ctx.obj = {"config": MagicMock()}
    ctx.obj["config"].get_client = MagicMock()

    result = runner.invoke(get_collection_cli, obj=ctx.obj)
    assert result.exit_code == 0, result.output
    assert GetCollectionDefaults.collection is None


def test_get_tenants_defaults(runner):
    ctx = click.Context(get_tenants_cli)
    ctx.obj = {"config": MagicMock()}
    ctx.obj["config"].get_client = MagicMock()

    missing_result = runner.invoke(get_tenants_cli, obj=ctx.obj)
    assert missing_result.exit_code == 2

    result = runner.invoke(
        get_tenants_cli, ["--collection", "TestCollection"], obj=ctx.obj
    )
    assert result.exit_code == 0, result.output
    assert GetTenantsDefaults.collection is None
    assert GetTenantsDefaults.verbose is False


def test_get_shards_defaults(runner):
    ctx = click.Context(get_shards_cli)
    ctx.obj = {"config": MagicMock()}
    ctx.obj["config"].get_client = MagicMock()

    result = runner.invoke(get_shards_cli, obj=ctx.obj)
    assert result.exit_code == 0, result.output
    assert GetShardsDefaults.collection is None


def test_get_backup_defaults(runner):
    ctx = click.Context(get_backup_cli)
    ctx.obj = {"config": MagicMock()}
    ctx.obj["config"].get_client = MagicMock()

    backup_manager = MagicMock()
    backup_manager.get_backup = MagicMock()

    client = MagicMock()
    client.backup = backup_manager
    ctx.obj["config"].get_client.return_value = client

    result = runner.invoke(get_backup_cli, ["--backup_id", "test-backup"], obj=ctx.obj)
    assert result.exit_code == 0, result.output
    assert GetBackupDefaults.backend == "s3"
    assert GetBackupDefaults.backup_id is None
    assert GetBackupDefaults.restore is False


def test_restore_backup_defaults(runner):
    ctx = click.Context(restore_backup_cli)
    ctx.obj = {"config": MagicMock()}
    ctx.obj["config"].get_client = MagicMock()

    result = runner.invoke(restore_backup_cli, obj=ctx.obj)
    assert result.exit_code == 0, result.output
    assert RestoreBackupDefaults.backend == "s3"
    assert RestoreBackupDefaults.backup_id == "test-backup"
    assert RestoreBackupDefaults.wait is False
    assert RestoreBackupDefaults.include is None
    assert RestoreBackupDefaults.exclude is None


def test_update_collection_defaults(runner):
    ctx = click.Context(update_collection_cli)
    ctx.obj = {"config": MagicMock()}

    mock_client = MagicMock()
    mock_client.collections.exists.side_effect = [True, True]

    mock_collection = MagicMock()
    mock_config = MagicMock()
    mock_config.replication_config.factor = 1
    mock_config.multi_tenancy_config.enabled = True
    mock_config.multi_tenancy_config.auto_tenant_creation = False
    mock_config.multi_tenancy_config.auto_tenant_activation = False
    mock_collection.config.get.return_value = mock_config
    mock_client.collections.get.return_value = mock_collection

    ctx.obj["config"].get_client.return_value = mock_client

    missing_result = runner.invoke(update_collection_cli, obj=ctx.obj)
    assert missing_result.exit_code == 2

    result = runner.invoke(
        update_collection_cli, ["--collection", "TestCollection"], obj=ctx.obj
    )
    assert result.exit_code == 0, result.output
    assert UpdateCollectionDefaults.collection is None
    assert UpdateCollectionDefaults.object_ttl_property_name is None
    assert UpdateCollectionDefaults.async_enabled is None
    assert UpdateCollectionDefaults.vector_index is None
    assert UpdateCollectionDefaults.description is None
    assert UpdateCollectionDefaults.training_limit == 10000
    assert UpdateCollectionDefaults.auto_tenant_creation is None
    assert UpdateCollectionDefaults.auto_tenant_activation is None
    assert UpdateCollectionDefaults.replication_deletion_strategy is None


def test_update_tenants_defaults(runner):
    ctx = click.Context(update_tenants_cli)
    ctx.obj = {"config": MagicMock()}
    mock_client = MagicMock()

    mock_client.collections.exists.return_value = True
    mock_client.get_meta.return_value = {"version": "1.25.0"}

    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection

    mock_config = MagicMock()
    mock_config.multi_tenancy_config.enabled = True
    mock_collection.config.get.return_value = mock_config

    mock_tenants = {
        f"{UpdateTenantsDefaults.tenant_suffix}-{i}": MagicMock(
            activity_status=TenantActivityStatus.ACTIVE
        )
        for i in range(UpdateTenantsDefaults.number_tenants)
    }
    mock_collection.tenants.get.return_value = mock_tenants
    mock_collection.tenants.get_by_names.return_value = mock_tenants
    ctx.obj["config"].get_client.return_value = mock_client

    missing_result = runner.invoke(update_tenants_cli, obj=ctx.obj)
    assert missing_result.exit_code == 2

    result = runner.invoke(
        update_tenants_cli, ["--collection", "TestCollection"], obj=ctx.obj
    )
    assert result.exit_code == 0, result.output
    assert UpdateTenantsDefaults.collection is None
    assert UpdateTenantsDefaults.tenant_suffix == "Tenant"
    assert UpdateTenantsDefaults.number_tenants == 100
    assert UpdateTenantsDefaults.state == "active"


def test_update_shards_defaults(runner):
    ctx = click.Context(update_shards_cli)
    ctx.obj = {"config": MagicMock()}
    ctx.obj["config"].get_client = MagicMock()

    result = runner.invoke(update_shards_cli, obj=ctx.obj)
    assert result.exit_code == 0, result.output
    assert UpdateShardsDefaults.collection is None
    assert UpdateShardsDefaults.status == "READY"
    assert UpdateShardsDefaults.shards is None
    assert UpdateShardsDefaults.all is False
