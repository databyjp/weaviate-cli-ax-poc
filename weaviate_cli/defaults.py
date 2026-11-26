from dataclasses import dataclass
from typing import Optional, List


PERMISSION_HELP_STRING = (
    "Permission in format action:collection. Can be specified multiple times.\n\n"
    "Available Permissions:\n\n"
    "  Role management: create_roles, read_roles, update_roles, delete_roles\n\n"
    "  Cluster management: read_cluster\n\n"
    "  Backup management: manage_backups\n\n"
    "  Collection management: create_collections, read_collections, update_collections, delete_collections\n\n"
    "  Tenant management: create_tenants, read_tenants, update_tenants, delete_tenants\n\n"
    "  Data management: create_data, read_data, update_data, delete_data\n\n"
    "  User management: assign_and_revoke_users, read_users\n\n"
    "  Node management: read_nodes\n\n"
    "  Alias management: create_aliases, read_aliases, update_aliases, delete_aliases\n\n"
    "  CRUD shorthands for collections, roles, tenants, users and data:\n\n"
    "    crud_collections:collection,cud_data:collection,rd_collections,\n\n"
    "    crud_roles:role,cud_tenants:tenant,rd_tenants,\n\n"
    "    crud_users:user,cud_data:*,rd_data:*\n\n"
    "    crud_aliases:MyCollection,cud_aliases:MyCollection,rd_aliases:MyCollection\n\n"
    "Subfields:\n\n"
    "  - *_collections:collection name, can be specified multiple times\n\n"
    "  - *_roles:role name:scope, can be specified multiple times.\n\n"
    "  - *_users:user_name, can be specified multiple times\n\n"
    "  - *_tenants:collection_name:tenant_name, can be specified multiple times\n\n"
    "  - *_aliases:collection_name:alias_name, can be specified multiple times\n\n"
    "  - *_data:collection_name, can be specified multiple times\n\n"
    "  - *_backups:collection_name, can be specified multiple times\n\n"
    "  - read_nodes:verbosity (verbosity level)\n\n"
    "Examples:\n\n"
    "  --permission crud_collections:Articles\n\n"
    "  --permission cud_tenants:Person_*\n\n"
    "  --permission rucd_data:Person_*\n\n"
    "  --permission assign_and_revoke_users:user-1,user-2\n\n"
    "  --permission create_collections:Articles,Books\n\n"
    "  --permission create_tenants:Articles,Books\n\n"
    "  --permission crud_tenants:Articles,Books:MyTenant*,YourTenant*\n\n"
    "  --permission crud_roles:Admin,Editor:all\n\n"
    "  --permission create_roles:Editor:match\n\n"
    "  --permission read_roles:Admin,Editor:match\n\n"
    "  --permission read_nodes:verbose:Articles\n\n"
    "  --permission read_nodes:minimal\n\n"
    "  --permission manage_backups:Articles\n\n"
    "  --permission read_cluster\n\n"
    "  --permission crud_aliases:Articles,Books:Alias*\n\n"
    "  --permission create_aliases:Banks\n\n"
    "  --permission crud_users:user-1,user-2\n\n"
)


@dataclass
class CreateCollectionDefaults:
    collection: Optional[str] = None
    replication_factor: int = 1
    async_enabled: bool = False
    vector_index: str = "hnsw"
    inverted_index: Optional[str] = None
    training_limit: int = 10000
    multitenant: bool = False
    auto_tenant_creation: bool = False
    auto_tenant_activation: bool = False
    shards: int = 0
    vectorizer: str = "none"
    vectorizer_base_url: Optional[str] = None
    replication_deletion_strategy: Optional[str] = None
    named_vector: bool = False
    named_vector_name: Optional[str] = "default"
    hfresh_max_posting_size_kb: Optional[int] = None
    hfresh_replicas: Optional[int] = None
    hfresh_search_probe: Optional[int] = None
    distance_metric: Optional[str] = None
    rescore_limit: Optional[int] = None
    object_ttl_type: str = "create"
    object_ttl_time: Optional[int] = None
    object_ttl_filter_expired: Optional[bool] = None
    object_ttl_property_name: Optional[str] = None


@dataclass
class CreateTenantsDefaults:
    collection: Optional[str] = None
    tenant_suffix: str = "Tenant"
    number_tenants: int = 100
    tenant_batch_size: Optional[int] = None
    state: str = "active"
    tenants: Optional[List[str]] = None


@dataclass
class CreateBackupDefaults:
    backend: str = "s3"
    backup_id: str = "test-backup"
    incremental_base_backup_id: Optional[str] = None
    include: Optional[str] = None
    exclude: Optional[str] = None
    wait: bool = False
    cpu_for_backup: int = 40


@dataclass
class CreateRoleDefaults:
    role_name: str = "NewRole"
    permission: tuple = ()


@dataclass
class CancelBackupDefaults:
    backend: str = "s3"
    backup_id: str = "test-backup"


@dataclass
class DeleteCollectionDefaults:
    collection: Optional[str] = None
    all: bool = False


@dataclass
class DeleteTenantsDefaults:
    collection: Optional[str] = None
    tenant_suffix: str = "Tenant"
    number_tenants: int = 100
    tenants: Optional[list] = None


@dataclass
class DeleteRoleDefaults:
    role_name: str = "NewRole"


@dataclass
class GetCollectionDefaults:
    collection: Optional[str] = None


@dataclass
class GetTenantsDefaults:
    collection: Optional[str] = None
    tenant_id: Optional[str] = None
    verbose: bool = False


@dataclass
class GetShardsDefaults:
    collection: Optional[str] = None


@dataclass
class GetRoleDefaults:
    role_name: Optional[str] = None
    user_name: Optional[str] = None
    user_type: Optional[str] = "db"


@dataclass
class GetBackupDefaults:
    backend: str = "s3"
    backup_id: Optional[str] = None
    restore: bool = False


@dataclass
class GetUserDefaults:
    role_name: Optional[str] = None
    user_name: Optional[str] = None


@dataclass
class RestoreBackupDefaults:
    backend: str = "s3"
    backup_id: str = "test-backup"
    wait: bool = False
    include: Optional[str] = None
    exclude: Optional[str] = None
    override_alias: bool = False


@dataclass
class UpdateCollectionDefaults:
    collection: Optional[str] = None
    async_enabled: Optional[bool] = None
    replication_factor: Optional[int] = None
    vector_index: Optional[str] = None
    description: Optional[str] = None
    training_limit: int = 10000
    auto_tenant_creation: Optional[bool] = None
    auto_tenant_activation: Optional[bool] = None
    replication_deletion_strategy: Optional[str] = None
    object_ttl_type: str = "create"
    object_ttl_time: Optional[int] = None
    object_ttl_filter_expired: Optional[bool] = None
    object_ttl_property_name: Optional[str] = None


@dataclass
class UpdateTenantsDefaults:
    collection: Optional[str] = None
    tenant_suffix: str = "Tenant"
    number_tenants: int = 100
    state: str = "active"
    tenants: Optional[str] = None


@dataclass
class UpdateShardsDefaults:
    collection: Optional[str] = None
    status: str = "READY"
    shards: Optional[str] = None
    all: bool = False


@dataclass
class UpdateUserDefaults:
    user_name: Optional[str] = None
    rotate_api_key: bool = False
    activate: bool = False
    deactivate: bool = False


@dataclass
class GetNodesDefaults:
    collection: Optional[str] = None


@dataclass
class GetAliasDefaults:
    alias_name: Optional[str] = None
    collection: Optional[str] = None
    all: bool = False


@dataclass
class CreateExportCollectionDefaults:
    export_id: str = "test-export"
    backend: str = "filesystem"
    file_format: str = "parquet"
    include: Optional[str] = None
    exclude: Optional[str] = None
    wait: bool = False


@dataclass
class GetExportCollectionDefaults:
    export_id: str = "test-export"
    backend: str = "filesystem"


@dataclass
class CancelExportCollectionDefaults:
    export_id: str = "test-export"
    backend: str = "filesystem"
