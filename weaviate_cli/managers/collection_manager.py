"""Collection adapter translating CLI operations onto weaviate.WeaviateClient.

This module performs no stdout/stderr printing and renders no tables; it returns
structured Python dictionaries and raises typed CLIError or Weaviate SDK exceptions.
"""

from __future__ import annotations

from typing import Any

import weaviate.classes.config as wvc
from weaviate.client import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.config import _CollectionConfigSimple
from weaviate.collections.classes.config_vector_index import VectorFilterStrategy
from weaviate.collections.classes.tenants import TenantActivityStatus

from weaviate_cli.defaults import UpdateCollectionDefaults
from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.utils import (
    ASYNC_REPLICATION_CONFIG_DEPRECATED_KEYS,
    ASYNC_REPLICATION_CONFIG_REMOVED_VERSION,
    older_than_version,
)


def _enum_str(value: object) -> str:
    return str(getattr(value, "value", value))


class CollectionManager:
    """Adapter for collection DDL and operational config updates."""

    def __init__(self, client: WeaviateClient) -> None:
        self.client = client

    def _get_total_objects_with_multitenant(self, col_obj: Collection) -> int:
        total = 0
        for tenant in col_obj.tenants.get().values():
            if tenant.activity_status == TenantActivityStatus.ACTIVE:
                total += len(col_obj.with_tenant(tenant))
        return total

    def get_all_collections(self) -> dict[str, _CollectionConfigSimple]:
        return self.client.collections.list_all()

    def get_available_modules(self) -> list[str] | None:
        """Return enabled module names from /v1/meta, or None if unavailable."""
        meta = self.client.get_meta()
        if not isinstance(meta, dict):
            return None
        modules = meta.get("modules")
        if not isinstance(modules, dict):
            return None
        return sorted(str(name) for name in modules)

    def list_collections(self) -> list[dict[str, Any]]:
        """Return summary metadata rows for all collections in the cluster."""
        collections = self.client.collections.list_all()
        if not collections:
            return []

        rows: list[dict[str, Any]] = []
        for col_name in collections:
            col_obj = self.client.collections.get(col_name)
            schema = col_obj.config.get()
            vectorizer = "None"
            vector_index_type = "None"
            named_vectors = False

            if schema.vector_config and not schema.vectorizer:
                named_vectors = True
                first_vec = next(iter(schema.vector_config.values()))
                vectorizer = _enum_str(first_vec.vectorizer.vectorizer)
                if not schema.vector_index_type:
                    vector_index_type = _enum_str(
                        first_vec.vector_index_config.vector_index_type()
                    )
                else:
                    vector_index_type = _enum_str(schema.vector_index_type)
            else:
                if schema.vectorizer:
                    vectorizer = _enum_str(schema.vectorizer)
                if schema.vector_index_type:
                    vector_index_type = _enum_str(schema.vector_index_type)

            mt_enabled = bool(schema.multi_tenancy_config.enabled)
            tenant_count = len(col_obj.tenants.get()) if mt_enabled else 0
            object_count = (
                self._get_total_objects_with_multitenant(col_obj)
                if mt_enabled
                else len(col_obj)
            )

            rows.append(
                {
                    "name": col_name,
                    "multitenancy": mt_enabled,
                    "tenant_count": tenant_count,
                    "object_count": object_count,
                    "replication_factor": schema.replication_config.factor,
                    "vector_index": vector_index_type,
                    "named_vectors": named_vectors,
                    "vectorizer": vectorizer,
                }
            )

        return rows

    def get_collection(self, collection: str) -> dict[str, Any]:
        """Return the native /v1/schema dict for a single collection."""
        if not self.client.collections.exists(collection):
            raise CLIError(
                code="COLLECTION_NOT_FOUND",
                message=f"Collection '{collection}' does not exist.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli collection list' to see existing collections.",
            )
        col_obj: Collection = self.client.collections.get(collection)
        return col_obj.config.get().to_dict()

    def create_collection(
        self,
        spec: dict[str, Any],
        *,
        if_not_exists: bool = False,
    ) -> dict[str, Any]:
        """Create a collection from a validated /v1/schema dict."""
        collection = spec.get("class")
        if not isinstance(collection, str) or not collection.strip():
            raise CLIError(
                code="INVALID_COLLECTION_SPEC",
                message="Collection schema must include a non-empty 'class' name.",
                exit_code=ExitCode.USAGE,
            )

        if self.client.collections.exists(collection):
            if if_not_exists:
                return {
                    "collection": collection,
                    "created": False,
                    "already_exists": True,
                }
            raise CLIError(
                code="COLLECTION_EXISTS",
                message=f"Collection '{collection}' already exists.",
                exit_code=ExitCode.NOT_FOUND,
                hint=(
                    "Pass --if-not-exists to succeed idempotently, provide a different NAME, "
                    f"or delete it first with 'weaviate-cli collection delete {collection}'."
                ),
            )

        self.client.collections.create_from_dict(spec)
        return {
            "collection": collection,
            "created": True,
            "already_exists": False,
        }

    def update_collection(
        self,
        collection: str | None = UpdateCollectionDefaults.collection,
        description: str | None = UpdateCollectionDefaults.description,
        vector_index: str | None = UpdateCollectionDefaults.vector_index,
        training_limit: int = UpdateCollectionDefaults.training_limit,
        async_enabled: bool | None = UpdateCollectionDefaults.async_enabled,
        replication_factor: int | None = UpdateCollectionDefaults.replication_factor,
        auto_tenant_creation: bool
        | None = UpdateCollectionDefaults.auto_tenant_creation,
        auto_tenant_activation: bool
        | None = UpdateCollectionDefaults.auto_tenant_activation,
        replication_deletion_strategy: str
        | None = UpdateCollectionDefaults.replication_deletion_strategy,
        object_ttl_type: str = UpdateCollectionDefaults.object_ttl_type,
        object_ttl_time: int | None = UpdateCollectionDefaults.object_ttl_time,
        object_ttl_filter_expired: bool
        | None = UpdateCollectionDefaults.object_ttl_filter_expired,
        object_ttl_property_name: str
        | None = UpdateCollectionDefaults.object_ttl_property_name,
        async_replication_config: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Update operational configuration for an existing collection."""
        if not collection:
            raise CLIError(
                code="MISSING_COLLECTION_NAME",
                message="Collection name is required.",
                exit_code=ExitCode.USAGE,
            )
        if (
            object_ttl_type not in ("property", "disable")
            and object_ttl_property_name
            != UpdateCollectionDefaults.object_ttl_property_name
        ):
            raise CLIError(
                code="INVALID_TTL_CONFIG",
                message="object_ttl_property_name is only valid when object_ttl_type is 'property'.",
                exit_code=ExitCode.USAGE,
            )
        if (
            object_ttl_type == "property"
            and object_ttl_time is not None
            and not object_ttl_property_name
        ):
            raise CLIError(
                code="INVALID_TTL_CONFIG",
                message="object_ttl_property_name is required when object_ttl_type is 'property'.",
                exit_code=ExitCode.USAGE,
            )
        if async_replication_config is not None and async_enabled is False:
            raise CLIError(
                code="INVALID_REPLICATION_CONFIG",
                message="--async-replication-config cannot be used when --async-enabled is False.",
                exit_code=ExitCode.USAGE,
            )

        warnings: list[str] = []
        if async_replication_config is not None and older_than_version(
            self.client, "1.36.0"
        ):
            warnings.append(
                "--async-replication-config requires Weaviate >= v1.36.0. "
                "The server may ignore or reject these settings."
            )

        if async_replication_config:
            removed = sorted(
                ASYNC_REPLICATION_CONFIG_DEPRECATED_KEYS & set(async_replication_config)
            )
            if removed and not older_than_version(
                self.client, ASYNC_REPLICATION_CONFIG_REMOVED_VERSION
            ):
                warnings.append(
                    f"{', '.join(removed)} removed from the Weaviate server schema in "
                    f"v{ASYNC_REPLICATION_CONFIG_REMOVED_VERSION}. "
                    "This server will ignore these settings."
                )

        if not self.client.collections.exists(collection):
            raise CLIError(
                code="COLLECTION_NOT_FOUND",
                message=f"Collection '{collection}' does not exist.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli collection list' to see existing collections.",
            )

        vector_index_map: dict[str, Any] = {
            "hnsw": wvc.Reconfigure.VectorIndex.hnsw(),
            "flat": wvc.Reconfigure.VectorIndex.flat(),
            "hnsw_pq": wvc.Reconfigure.VectorIndex.hnsw(
                quantizer=wvc.Reconfigure.VectorIndex.Quantizer.pq(
                    training_limit=training_limit
                )
            ),
            "hnsw_sq": wvc.Reconfigure.VectorIndex.hnsw(
                quantizer=wvc.Reconfigure.VectorIndex.Quantizer.sq(
                    training_limit=training_limit
                )
            ),
            "hnsw_bq": wvc.Reconfigure.VectorIndex.hnsw(
                quantizer=wvc.Reconfigure.VectorIndex.Quantizer.bq()
            ),
            "hnsw_acorn": wvc.Reconfigure.VectorIndex.hnsw(
                filter_strategy=VectorFilterStrategy.ACORN
            ),
            "flat_bq": wvc.Reconfigure.VectorIndex.flat(
                quantizer=wvc.Reconfigure.VectorIndex.Quantizer.bq()
            ),
        }

        object_ttl_config: Any = None
        if object_ttl_type == "disable":
            object_ttl_config = wvc.Reconfigure.ObjectTTL.disable()
        elif object_ttl_time is not None:
            if object_ttl_type == "create":
                object_ttl_config = wvc.Reconfigure.ObjectTTL.delete_by_creation_time(
                    time_to_live=object_ttl_time,
                    filter_expired_objects=object_ttl_filter_expired,
                )
            elif object_ttl_type == "update":
                object_ttl_config = wvc.Reconfigure.ObjectTTL.delete_by_update_time(
                    time_to_live=object_ttl_time,
                    filter_expired_objects=object_ttl_filter_expired,
                )
            elif object_ttl_type == "property":
                assert object_ttl_property_name is not None
                object_ttl_config = wvc.Reconfigure.ObjectTTL.delete_by_date_property(
                    property_name=object_ttl_property_name,
                    ttl_offset=object_ttl_time,
                    filter_expired_objects=object_ttl_filter_expired,
                )

        col_obj: Collection = self.client.collections.get(collection)
        current_cfg = col_obj.config.get()
        rf = (
            replication_factor
            if replication_factor is not None
            else current_cfg.replication_config.factor
        )
        rds_map = {
            "delete_on_conflict": wvc.ReplicationDeletionStrategy.DELETE_ON_CONFLICT,
            "no_automated_resolution": wvc.ReplicationDeletionStrategy.NO_AUTOMATED_RESOLUTION,
            "time_based_resolution": wvc.ReplicationDeletionStrategy.TIME_BASED_RESOLUTION,
        }
        mt = current_cfg.multi_tenancy_config.enabled
        resolved_auto_creation = (
            auto_tenant_creation
            if auto_tenant_creation is not None
            else current_cfg.multi_tenancy_config.auto_tenant_creation
        )
        resolved_auto_activation = (
            auto_tenant_activation
            if auto_tenant_activation is not None
            else current_cfg.multi_tenancy_config.auto_tenant_activation
        )

        col_obj.config.update(
            description=description,
            vectorizer_config=(
                vector_index_map[vector_index] if vector_index else None
            ),
            replication_config=wvc.Reconfigure.replication(
                factor=rf,
                async_enabled=async_enabled if async_enabled is not None else None,
                deletion_strategy=(
                    rds_map[replication_deletion_strategy]
                    if replication_deletion_strategy
                    else None
                ),
                async_config=(
                    wvc.Reconfigure.Replication.async_config(**async_replication_config)
                    if async_replication_config is not None
                    else None
                ),
            ),
            multi_tenancy_config=(
                wvc.Reconfigure.multi_tenancy(
                    auto_tenant_creation=resolved_auto_creation,
                    auto_tenant_activation=resolved_auto_activation,
                )
                if mt
                else None
            ),
            object_ttl_config=object_ttl_config,
        )

        return {
            "collection": collection,
            "updated": True,
            "warnings": warnings,
        }

    def delete_collection(
        self,
        collection: str | None = None,
        *,
        delete_all: bool = False,
    ) -> dict[str, Any]:
        """Delete a single collection or all collections."""
        if not delete_all and not collection:
            raise CLIError(
                code="MISSING_COLLECTION_NAME",
                message="Collection name is required unless --all is specified.",
                exit_code=ExitCode.USAGE,
            )

        if delete_all:
            names = list(self.client.collections.list_all())
            for col_name in names:
                self.client.collections.delete(col_name)
            return {"deleted": names, "count": len(names)}

        assert collection is not None
        if not self.client.collections.exists(collection):
            raise CLIError(
                code="COLLECTION_NOT_FOUND",
                message=f"Collection '{collection}' does not exist.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli collection list' to see existing collections.",
            )

        self.client.collections.delete(collection)
        return {"deleted": [collection], "count": 1}
