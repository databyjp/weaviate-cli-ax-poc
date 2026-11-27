from dataclasses import dataclass

PERMISSION_HELP_STRING = (
    "Permission in format action[:target[:subtarget]]. Can be specified multiple times.\n\n"
    "Available Permissions:\n\n"
    "  Role management: create_roles, read_roles, update_roles, delete_roles\n\n"
    "  Cluster management: read_cluster\n\n"
    "  Backup management: manage_backups, read_backups\n\n"
    "  Collection management: create_collections, read_collections, update_collections, delete_collections\n\n"
    "  Tenant management: create_tenants, read_tenants, update_tenants, delete_tenants\n\n"
    "  Data management: create_data, read_data, update_data, delete_data\n\n"
    "  User management: create_users, read_users, update_users, delete_users, assign_and_revoke_users\n\n"
    "  Group (OIDC) management: read_groups, assign_and_revoke_groups\n\n"
    "  Node management: read_nodes\n\n"
    "  Alias management: create_aliases, read_aliases, update_aliases, delete_aliases\n\n"
    "  Replication management: create_replicate, read_replicate, update_replicate, delete_replicate\n\n"
    "  Native MCP (/v1/mcp): create_mcp, read_mcp, update_mcp (or c/r/u shorthands like cru_mcp)\n\n"
    "  CRUD shorthands for collections, roles, tenants, users, data, aliases, replicate:\n\n"
    "    crud_collections:collection, cud_data:collection:tenant, rd_collections,\n\n"
    "    crud_roles:role:scope, cud_tenants:collection:tenant, crud_users:user,\n\n"
    "    crud_aliases:collection:alias, crud_replicate:collection:shard\n\n"
    "Subfields:\n\n"
    "  - *_collections:collection[,...] (comma-separated)\n\n"
    "  - *_roles:role[,...][:all|match]\n\n"
    "  - *_users:user[,...]\n\n"
    "  - *_groups:group[,...][:oidc]\n\n"
    "  - *_tenants:collection[,...][:tenant[,...]]\n\n"
    "  - *_data:collection[,...][:tenant[,...]]\n\n"
    "  - *_aliases:collection[,...][:alias[,...]]\n\n"
    "  - *_replicate:collection[,...][:shard[,...]]\n\n"
    "  - *_backups:collection[,...]\n\n"
    "  - read_nodes:minimal|verbose[:collection[,...]]\n\n"
    "  - *_mcp (no target subfield)\n\n"
    "Examples:\n\n"
    "  --permission crud_collections:Articles\n\n"
    "  --permission read_data:Articles:tenant-a,tenant-b\n\n"
    "  --permission cru_mcp\n\n"
    "  --permission crud_replicate:Articles:shard-1\n\n"
    "  --permission read_groups:engineering\n\n"
    "  --permission assign_and_revoke_groups:engineering\n\n"
    "  --permission read_backups:Articles\n\n"
    "  --permission manage_backups:Articles\n\n"
    "  --permission assign_and_revoke_users:user-1,user-2\n\n"
    "  --permission crud_tenants:Articles,Books:MyTenant*\n\n"
    "  --permission crud_roles:Admin,Editor:all\n\n"
    "  --permission read_nodes:verbose:Articles\n\n"
    "  --permission read_nodes:minimal\n\n"
    "  --permission read_cluster\n\n"
    "  --permission crud_aliases:Articles,Books:Alias*\n\n"
)


@dataclass
class CreateTenantsDefaults:
    collection: str | None = None
    tenant_suffix: str = "Tenant"
    number_tenants: int = 100
    tenant_batch_size: int | None = None
    state: str = "active"
    tenants: list[str] | None = None


@dataclass
class CreateBackupDefaults:
    backend: str = "s3"
    backup_id: str | None = None
    incremental_base_backup_id: str | None = None
    include: str | None = None
    exclude: str | None = None
    wait: bool = False
    cpu_for_backup: int = 40
    compression_level: str | None = None
    bucket: str | None = None
    path: str | None = None
    include_roles: str | None = None
    include_users: str | None = None


@dataclass
class CreateRoleDefaults:
    role_name: str = "NewRole"
    permission: tuple = ()


@dataclass
class CancelBackupDefaults:
    backend: str = "s3"
    backup_id: str | None = None
    restore: bool = False
    bucket: str | None = None
    path: str | None = None


@dataclass
class DeleteCollectionDefaults:
    collection: str | None = None
    all: bool = False


@dataclass
class DeleteTenantsDefaults:
    collection: str | None = None
    tenant_suffix: str = "Tenant"
    number_tenants: int = 100
    tenants: list | None = None


@dataclass
class DeleteRoleDefaults:
    role_name: str = "NewRole"


@dataclass
class GetCollectionDefaults:
    collection: str | None = None


@dataclass
class GetTenantsDefaults:
    collection: str | None = None
    tenant_id: str | None = None
    verbose: bool = False


@dataclass
class GetShardsDefaults:
    collection: str | None = None


@dataclass
class GetRoleDefaults:
    role_name: str | None = None
    user_name: str | None = None
    user_type: str = "db"


@dataclass
class GetBackupDefaults:
    backend: str = "s3"
    backup_id: str | None = None
    restore: bool = False


@dataclass
class GetUserDefaults:
    role_name: str | None = None
    user_name: str | None = None


@dataclass
class RestoreBackupDefaults:
    backend: str = "s3"
    backup_id: str | None = None
    wait: bool = False
    include: str | None = None
    exclude: str | None = None
    override_alias: bool = False
    roles_restore: str | None = None
    users_restore: str | None = None
    cpu_for_restore: int | None = None
    bucket: str | None = None
    path: str | None = None


@dataclass
class UpdateCollectionDefaults:
    collection: str | None = None
    async_enabled: bool | None = None
    replication_factor: int | None = None
    vector_index: str | None = None
    description: str | None = None
    training_limit: int = 10000
    auto_tenant_creation: bool | None = None
    auto_tenant_activation: bool | None = None
    replication_deletion_strategy: str | None = None
    object_ttl_type: str = "create"
    object_ttl_time: int | None = None
    object_ttl_filter_expired: bool | None = None
    object_ttl_property_name: str | None = None


@dataclass
class UpdateTenantsDefaults:
    collection: str | None = None
    tenant_suffix: str = "Tenant"
    number_tenants: int = 100
    state: str = "active"
    tenants: str | None = None


@dataclass
class UpdateShardsDefaults:
    collection: str | None = None
    status: str = "READY"
    shards: str | None = None
    all: bool = False


@dataclass
class UpdateUserDefaults:
    user_name: str | None = None
    rotate_api_key: bool = False
    activate: bool = False
    deactivate: bool = False


@dataclass
class GetNodesDefaults:
    collection: str | None = None


@dataclass
class GetAliasDefaults:
    alias_name: str | None = None
    collection: str | None = None
    all: bool = False


@dataclass
class CreateExportCollectionDefaults:
    export_id: str | None = None
    backend: str = "filesystem"
    file_format: str = "parquet"
    include: str | None = None
    exclude: str | None = None
    wait: bool = False


@dataclass
class GetExportCollectionDefaults:
    export_id: str | None = None
    backend: str = "filesystem"


@dataclass
class CancelExportCollectionDefaults:
    export_id: str | None = None
    backend: str = "filesystem"
