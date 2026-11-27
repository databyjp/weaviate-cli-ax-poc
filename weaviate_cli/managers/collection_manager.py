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
from weaviate_cli.specs.collection import is_cross_reference_data_type
from weaviate_cli.utils import (
    ASYNC_REPLICATION_CONFIG_DEPRECATED_KEYS,
    ASYNC_REPLICATION_CONFIG_REMOVED_VERSION,
    older_than_version,
)


def _enum_str(value: object) -> str:
    return str(getattr(value, "value", value))


def _camel_or_snake(mapping: dict[str, Any], camel: str, snake: str) -> Any:
    if camel in mapping:
        return mapping[camel]
    return mapping.get(snake)


def _build_property_from_spec(spec: dict[str, Any]) -> wvc.Property:
    """Convert a validated /v1/schema property dict into a weaviate Property object."""
    data_type_list = spec["dataType"]
    data_type = wvc.DataType(data_type_list[0])
    tokenization_raw = spec.get("tokenization")
    tokenization = (
        wvc.Tokenization(tokenization_raw) if tokenization_raw is not None else None
    )

    skip_vectorization = spec.get("skipVectorization")
    vectorize_property_name = spec.get("vectorizePropertyName")
    module_config = spec.get("moduleConfig")
    if isinstance(module_config, dict) and module_config:
        first_mod = next(iter(module_config.values()))
        if isinstance(first_mod, dict):
            if skip_vectorization is None and "skip" in first_mod:
                skip_vectorization = bool(first_mod["skip"])
            if vectorize_property_name is None and "vectorizePropertyName" in first_mod:
                vectorize_property_name = bool(first_mod["vectorizePropertyName"])

    nested_raw = spec.get("nestedProperties")
    nested_properties = (
        [_build_property_from_spec(np) for np in nested_raw] if nested_raw else None
    )

    text_analyzer = None
    ta_raw = spec.get("textAnalyzer")
    if isinstance(ta_raw, dict):
        text_analyzer = wvc.Configure.text_analyzer(
            ascii_fold=_camel_or_snake(ta_raw, "asciiFold", "ascii_fold"),
            ascii_fold_ignore=_camel_or_snake(
                ta_raw, "asciiFoldIgnore", "ascii_fold_ignore"
            ),
            stopword_preset=_camel_or_snake(
                ta_raw, "stopwordPreset", "stopword_preset"
            ),
        )

    return wvc.Property(
        name=str(spec["name"]),
        data_type=data_type,
        description=spec.get("description"),
        tokenization=tokenization,
        index_filterable=spec.get("indexFilterable"),
        index_searchable=spec.get("indexSearchable"),
        index_range_filters=spec.get("indexRangeFilters"),
        skip_vectorization=bool(skip_vectorization)
        if skip_vectorization is not None
        else False,
        vectorize_property_name=bool(vectorize_property_name)
        if vectorize_property_name is not None
        else True,
        nested_properties=nested_properties,
        text_analyzer=text_analyzer,
    )


def _build_quantizer_create(vic: dict[str, Any]) -> Any:
    """Convert a /v1/schema quantizer sub-dict into a Configure.VectorIndex.Quantizer object."""
    rq = vic.get("rq")
    if isinstance(rq, dict):
        if rq.get("enabled") is False:
            return wvc.Configure.VectorIndex.Quantizer.none()
        return wvc.Configure.VectorIndex.Quantizer.rq(
            cache=rq.get("cache"),
            bits=rq.get("bits"),
            rescore_limit=_camel_or_snake(rq, "rescoreLimit", "rescore_limit"),
            centering=rq.get("centering"),
            training_limit=_camel_or_snake(rq, "trainingLimit", "training_limit"),
        )

    bq = vic.get("bq")
    if isinstance(bq, dict):
        if bq.get("enabled") is False:
            return wvc.Configure.VectorIndex.Quantizer.none()
        return wvc.Configure.VectorIndex.Quantizer.bq(
            cache=bq.get("cache"),
            rescore_limit=_camel_or_snake(bq, "rescoreLimit", "rescore_limit"),
        )

    pq = vic.get("pq")
    if isinstance(pq, dict):
        if pq.get("enabled") is False:
            return wvc.Configure.VectorIndex.Quantizer.none()
        raw_encoder = pq.get("encoder")
        encoder: dict[str, Any] = raw_encoder if isinstance(raw_encoder, dict) else {}
        enc_type = encoder.get("type")
        enc_dist = encoder.get("distribution")
        return wvc.Configure.VectorIndex.Quantizer.pq(
            bit_compression=_camel_or_snake(pq, "bitCompression", "bit_compression"),
            centroids=pq.get("centroids"),
            encoder_type=wvc.PQEncoderType(enc_type) if enc_type is not None else None,
            encoder_distribution=(
                wvc.PQEncoderDistribution(enc_dist) if enc_dist is not None else None
            ),
            segments=pq.get("segments"),
            training_limit=_camel_or_snake(pq, "trainingLimit", "training_limit"),
        )

    sq = vic.get("sq")
    if isinstance(sq, dict):
        if sq.get("enabled") is False:
            return wvc.Configure.VectorIndex.Quantizer.none()
        return wvc.Configure.VectorIndex.Quantizer.sq(
            cache=sq.get("cache"),
            rescore_limit=_camel_or_snake(sq, "rescoreLimit", "rescore_limit"),
            training_limit=_camel_or_snake(sq, "trainingLimit", "training_limit"),
        )

    return None


def _build_vector_index_create(
    index_type: str | None,
    vic: dict[str, Any] | None,
) -> Any:
    """Convert a /v1/schema vectorIndexType + vectorIndexConfig into a Configure.VectorIndex object."""
    cfg = vic or {}
    if not index_type and not cfg:
        return None

    resolved_type = (index_type or "hnsw").lower()
    distance_raw = cfg.get("distance")
    distance = wvc.VectorDistances(distance_raw) if distance_raw is not None else None
    quantizer = _build_quantizer_create(cfg)

    if resolved_type == "flat":
        return wvc.Configure.VectorIndex.flat(
            distance_metric=distance,
            vector_cache_max_objects=_camel_or_snake(
                cfg, "vectorCacheMaxObjects", "vector_cache_max_objects"
            ),
            quantizer=quantizer,
        )

    if resolved_type == "hfresh":
        return wvc.Configure.VectorIndex.hfresh(
            distance_metric=distance,
            max_posting_size_kb=_camel_or_snake(
                cfg, "maxPostingSizeKb", "max_posting_size_kb"
            ),
            replicas=cfg.get("replicas"),
            search_probe=_camel_or_snake(cfg, "searchProbe", "search_probe"),
            quantizer=quantizer,
        )

    if resolved_type == "dynamic":
        hnsw_sub = cfg.get("hnsw")
        flat_sub = cfg.get("flat")
        return wvc.Configure.VectorIndex.dynamic(
            distance_metric=distance,
            threshold=cfg.get("threshold"),
            hnsw=(
                _build_vector_index_create("hnsw", hnsw_sub)
                if isinstance(hnsw_sub, dict)
                else None
            ),
            flat=(
                _build_vector_index_create("flat", flat_sub)
                if isinstance(flat_sub, dict)
                else None
            ),
        )

    if resolved_type == "none":
        return wvc.Configure.VectorIndex.none()

    filter_strategy_raw = _camel_or_snake(cfg, "filterStrategy", "filter_strategy")
    filter_strategy = (
        VectorFilterStrategy(filter_strategy_raw)
        if filter_strategy_raw is not None
        else None
    )
    return wvc.Configure.VectorIndex.hnsw(
        cleanup_interval_seconds=_camel_or_snake(
            cfg, "cleanupIntervalSeconds", "cleanup_interval_seconds"
        ),
        distance_metric=distance,
        dynamic_ef_factor=_camel_or_snake(cfg, "dynamicEfFactor", "dynamic_ef_factor"),
        dynamic_ef_max=_camel_or_snake(cfg, "dynamicEfMax", "dynamic_ef_max"),
        dynamic_ef_min=_camel_or_snake(cfg, "dynamicEfMin", "dynamic_ef_min"),
        ef=cfg.get("ef"),
        ef_construction=_camel_or_snake(cfg, "efConstruction", "ef_construction"),
        filter_strategy=filter_strategy,
        flat_search_cutoff=_camel_or_snake(
            cfg, "flatSearchCutoff", "flat_search_cutoff"
        ),
        max_connections=_camel_or_snake(cfg, "maxConnections", "max_connections"),
        vector_cache_max_objects=_camel_or_snake(
            cfg, "vectorCacheMaxObjects", "vector_cache_max_objects"
        ),
        quantizer=quantizer,
    )


def _build_vector_config_create(name: str, vec_def: dict[str, Any]) -> Any:
    """Convert a validated named vector definition dict into a Configure.Vectors object."""
    vec_mod = vec_def["vectorizer"]
    mod_name, raw_mod_cfg = next(iter(vec_mod.items()))
    mod_cfg = dict(raw_mod_cfg) if isinstance(raw_mod_cfg, dict) else {}

    vic_create = _build_vector_index_create(
        vec_def.get("vectorIndexType"),
        vec_def.get("vectorIndexConfig"),
    )

    if mod_name == "none":
        return wvc.Configure.Vectors.self_provided(
            name=name,
            vector_index_config=vic_create,
        )

    source_properties = mod_cfg.pop("properties", None)
    return wvc.Configure.Vectors.custom(
        name=name,
        module_name=mod_name,
        module_config=mod_cfg or None,
        source_properties=source_properties,
        vector_index_config=vic_create,
    )


def _build_quantizer_update(vic: dict[str, Any]) -> Any:
    """Convert a quantizer update sub-dict into a Reconfigure.VectorIndex.Quantizer object."""
    rq = vic.get("rq")
    if isinstance(rq, dict):
        return wvc.Reconfigure.VectorIndex.Quantizer.rq(
            enabled=rq.get("enabled", True),
            bits=rq.get("bits"),
            rescore_limit=_camel_or_snake(rq, "rescoreLimit", "rescore_limit"),
            centering=rq.get("centering"),
            training_limit=_camel_or_snake(rq, "trainingLimit", "training_limit"),
        )

    bq = vic.get("bq")
    if isinstance(bq, dict):
        return wvc.Reconfigure.VectorIndex.Quantizer.bq(
            enabled=bq.get("enabled", True),
            rescore_limit=_camel_or_snake(bq, "rescoreLimit", "rescore_limit"),
        )

    pq = vic.get("pq")
    if isinstance(pq, dict):
        raw_encoder = pq.get("encoder")
        encoder: dict[str, Any] = raw_encoder if isinstance(raw_encoder, dict) else {}
        enc_type = encoder.get("type")
        enc_dist = encoder.get("distribution")
        return wvc.Reconfigure.VectorIndex.Quantizer.pq(
            enabled=pq.get("enabled", True),
            bit_compression=_camel_or_snake(pq, "bitCompression", "bit_compression"),
            centroids=pq.get("centroids"),
            encoder_type=wvc.PQEncoderType(enc_type) if enc_type is not None else None,
            encoder_distribution=(
                wvc.PQEncoderDistribution(enc_dist) if enc_dist is not None else None
            ),
            segments=pq.get("segments"),
            training_limit=_camel_or_snake(pq, "trainingLimit", "training_limit"),
        )

    sq = vic.get("sq")
    if isinstance(sq, dict):
        return wvc.Reconfigure.VectorIndex.Quantizer.sq(
            enabled=sq.get("enabled", True),
            rescore_limit=_camel_or_snake(sq, "rescoreLimit", "rescore_limit"),
            training_limit=_camel_or_snake(sq, "trainingLimit", "training_limit"),
        )

    return None


def _infer_index_type(
    explicit_type: str | None,
    vic: dict[str, Any],
    fallback_type: str | None,
) -> str:
    if explicit_type:
        return explicit_type.lower()
    if any(
        k in vic
        for k in (
            "maxPostingSizeKb",
            "max_posting_size_kb",
            "searchProbe",
            "search_probe",
        )
    ):
        return "hfresh"
    if "threshold" in vic or "hnsw" in vic or "flat" in vic:
        return "dynamic"
    if fallback_type:
        return fallback_type.lower()
    return "hnsw"


def _build_vector_index_update(
    index_type: str | None,
    vic: dict[str, Any],
    *,
    fallback_type: str | None = None,
) -> Any:
    """Convert a vectorIndexConfig patch dict into a Reconfigure.VectorIndex object."""
    resolved_type = _infer_index_type(index_type, vic, fallback_type)
    quantizer = _build_quantizer_update(vic)

    if resolved_type == "flat":
        return wvc.Reconfigure.VectorIndex.flat(
            vector_cache_max_objects=_camel_or_snake(
                vic, "vectorCacheMaxObjects", "vector_cache_max_objects"
            ),
            quantizer=quantizer,
        )

    if resolved_type == "hfresh":
        return wvc.Reconfigure.VectorIndex.hfresh(
            max_posting_size_kb=_camel_or_snake(
                vic, "maxPostingSizeKb", "max_posting_size_kb"
            ),
            search_probe=_camel_or_snake(vic, "searchProbe", "search_probe"),
            quantizer=quantizer,
        )

    if resolved_type == "dynamic":
        hnsw_sub = vic.get("hnsw")
        flat_sub = vic.get("flat")
        return wvc.Reconfigure.VectorIndex.dynamic(
            threshold=vic.get("threshold"),
            hnsw=(
                _build_vector_index_update("hnsw", hnsw_sub)
                if isinstance(hnsw_sub, dict)
                else None
            ),
            flat=(
                _build_vector_index_update("flat", flat_sub)
                if isinstance(flat_sub, dict)
                else None
            ),
            quantizer=quantizer,
        )

    filter_strategy_raw = _camel_or_snake(vic, "filterStrategy", "filter_strategy")
    filter_strategy = (
        VectorFilterStrategy(filter_strategy_raw)
        if filter_strategy_raw is not None
        else None
    )
    return wvc.Reconfigure.VectorIndex.hnsw(
        dynamic_ef_factor=_camel_or_snake(vic, "dynamicEfFactor", "dynamic_ef_factor"),
        dynamic_ef_min=_camel_or_snake(vic, "dynamicEfMin", "dynamic_ef_min"),
        dynamic_ef_max=_camel_or_snake(vic, "dynamicEfMax", "dynamic_ef_max"),
        ef=vic.get("ef"),
        flat_search_cutoff=_camel_or_snake(
            vic, "flatSearchCutoff", "flat_search_cutoff"
        ),
        filter_strategy=filter_strategy,
        vector_cache_max_objects=_camel_or_snake(
            vic, "vectorCacheMaxObjects", "vector_cache_max_objects"
        ),
        quantizer=quantizer,
    )


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

    def _collect_async_replication_warnings(
        self, async_replication_config: dict[str, Any] | None
    ) -> list[str]:
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
        return warnings

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
                    f"or delete it first with 'weaviate-cli collection delete {collection} --yes'."
                ),
            )

        self.client.collections.create_from_dict(spec)
        return {
            "collection": collection,
            "created": True,
            "already_exists": False,
        }

    def add_property(
        self,
        collection: str,
        prop_spec: dict[str, Any],
        *,
        if_not_exists: bool = False,
    ) -> dict[str, Any]:
        """Add a property or cross-reference to an existing collection."""
        if not self.client.collections.exists(collection):
            raise CLIError(
                code="COLLECTION_NOT_FOUND",
                message=f"Collection '{collection}' does not exist.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli collection list' to see existing collections.",
            )

        prop_name = str(prop_spec["name"])
        data_type = list(prop_spec["dataType"])
        is_ref = is_cross_reference_data_type(data_type)
        kind = "reference" if is_ref else "property"

        col_obj: Collection = self.client.collections.get(collection)
        current_cfg = col_obj.config.get()
        existing_names = {p.name for p in (current_cfg.properties or ())} | {
            r.name for r in (current_cfg.references or ())
        }

        if prop_name in existing_names:
            if if_not_exists:
                return {
                    "collection": collection,
                    "property": prop_name,
                    "kind": kind,
                    "data_type": data_type,
                    "added": False,
                    "already_exists": True,
                }
            raise CLIError(
                code="PROPERTY_EXISTS",
                message=f"{kind.capitalize()} '{prop_name}' already exists in collection '{collection}'.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Pass --if-not-exists to succeed idempotently or choose a different property name.",
            )

        if is_ref:
            ref: wvc.ReferenceProperty | wvc.ReferencePropertyMultiTarget
            if len(data_type) == 1:
                ref = wvc.ReferenceProperty(
                    name=prop_name,
                    target_collection=data_type[0],
                    description=prop_spec.get("description"),
                )
            else:
                ref = wvc.ReferencePropertyMultiTarget(
                    name=prop_name,
                    target_collections=data_type,
                    description=prop_spec.get("description"),
                )
            col_obj.config.add_reference(ref)
        else:
            col_obj.config.add_property(_build_property_from_spec(prop_spec))

        return {
            "collection": collection,
            "property": prop_name,
            "kind": kind,
            "data_type": data_type,
            "added": True,
            "already_exists": False,
        }

    def add_vector(
        self,
        collection: str,
        vectors_spec: dict[str, dict[str, Any]],
        *,
        if_not_exists: bool = False,
    ) -> dict[str, Any]:
        """Add one or more named vectors to an existing collection."""
        if not self.client.collections.exists(collection):
            raise CLIError(
                code="COLLECTION_NOT_FOUND",
                message=f"Collection '{collection}' does not exist.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli collection list' to see existing collections.",
            )

        col_obj: Collection = self.client.collections.get(collection)
        current_cfg = col_obj.config.get()
        existing_vectors = set((current_cfg.vector_config or {}).keys())

        to_add: list[Any] = []
        added_names: list[str] = []
        skipped_names: list[str] = []

        for vec_name, vec_def in vectors_spec.items():
            if vec_name in existing_vectors:
                if if_not_exists:
                    skipped_names.append(vec_name)
                    continue
                raise CLIError(
                    code="VECTOR_EXISTS",
                    message=f"Named vector '{vec_name}' already exists in collection '{collection}'.",
                    exit_code=ExitCode.NOT_FOUND,
                    hint="Pass --if-not-exists to skip existing vectors or choose a different vector name.",
                )
            to_add.append(_build_vector_config_create(vec_name, vec_def))
            added_names.append(vec_name)

        if to_add:
            col_obj.config.add_vector(
                vector_config=to_add[0] if len(to_add) == 1 else to_add
            )

        return {
            "collection": collection,
            "added": added_names,
            "skipped": skipped_names,
        }

    def delete_vector(
        self,
        collection: str,
        vector_name: str,
    ) -> dict[str, Any]:
        """Drop a named vector index (and its vectors) asynchronously."""
        if not self.client.collections.exists(collection):
            raise CLIError(
                code="COLLECTION_NOT_FOUND",
                message=f"Collection '{collection}' does not exist.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli collection list' to see existing collections.",
            )

        col_obj: Collection = self.client.collections.get(collection)
        col_obj.config.delete_vector_index(vector_name)
        return {
            "collection": collection,
            "vector": vector_name,
            "deleted": True,
            "async": True,
            "note": (
                f"Vector index drop for '{vector_name}' was accepted asynchronously. "
                f"Run 'weaviate-cli collection get {collection}' to confirm removal from vectorConfig."
            ),
        }

    def delete_property_index(
        self,
        collection: str,
        property_name: str,
        index_name: str,
    ) -> dict[str, Any]:
        """Drop an inverted index (searchable, filterable, or rangeFilters) from a property."""
        index_map = {
            "searchable": "searchable",
            "filterable": "filterable",
            "range-filters": "rangeFilters",
            "rangefilters": "rangeFilters",
        }
        resolved = index_map.get(index_name.lower())
        if resolved is None:
            raise CLIError(
                code="INVALID_INDEX_TYPE",
                message=f"Invalid property index type '{index_name}'.",
                exit_code=ExitCode.USAGE,
                hint="Valid index types: searchable, filterable, range-filters.",
            )

        if not self.client.collections.exists(collection):
            raise CLIError(
                code="COLLECTION_NOT_FOUND",
                message=f"Collection '{collection}' does not exist.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli collection list' to see existing collections.",
            )

        col_obj: Collection = self.client.collections.get(collection)
        deleted = bool(
            col_obj.config.delete_property_index(
                property_name=property_name,
                index_name=resolved,  # type: ignore[arg-type]
            )
        )
        return {
            "collection": collection,
            "property": property_name,
            "index_type": resolved,
            "deleted": deleted,
        }

    def update_collection_from_spec(
        self,
        collection: str,
        spec: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply a validated declarative JSON update patch to an existing collection."""
        if not self.client.collections.exists(collection):
            raise CLIError(
                code="COLLECTION_NOT_FOUND",
                message=f"Collection '{collection}' does not exist.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli collection list' to see existing collections.",
            )

        col_obj: Collection = self.client.collections.get(collection)
        current_cfg = col_obj.config.get()
        warnings: list[str] = []

        update_kwargs: dict[str, Any] = {}

        if "description" in spec:
            update_kwargs["description"] = spec["description"]

        if "propertyDescriptions" in spec:
            update_kwargs["property_descriptions"] = spec["propertyDescriptions"]

        if "invertedIndexConfig" in spec and spec["invertedIndexConfig"] is not None:
            inv = spec["invertedIndexConfig"]
            bm25 = inv.get("bm25") if isinstance(inv.get("bm25"), dict) else {}
            sw = inv.get("stopwords") if isinstance(inv.get("stopwords"), dict) else {}
            preset_raw = sw.get("preset")
            update_kwargs["inverted_index_config"] = wvc.Reconfigure.inverted_index(
                bm25_b=bm25.get("b"),
                bm25_k1=bm25.get("k1"),
                cleanup_interval_seconds=_camel_or_snake(
                    inv, "cleanupIntervalSeconds", "cleanup_interval_seconds"
                ),
                stopwords_preset=(
                    wvc.StopwordsPreset(preset_raw) if preset_raw is not None else None
                ),
                stopwords_additions=sw.get("additions"),
                stopwords_removals=sw.get("removals"),
                stopword_presets=_camel_or_snake(
                    inv, "stopwordPresets", "stopword_presets"
                ),
            )

        if "replicationConfig" in spec and spec["replicationConfig"] is not None:
            repl = spec["replicationConfig"]
            async_cfg = _camel_or_snake(repl, "asyncConfig", "async_config")
            if isinstance(async_cfg, dict):
                warnings.extend(self._collect_async_replication_warnings(async_cfg))
            strategy_raw = _camel_or_snake(
                repl, "deletionStrategy", "deletion_strategy"
            )
            update_kwargs["replication_config"] = wvc.Reconfigure.replication(
                factor=repl.get("factor"),
                async_enabled=_camel_or_snake(repl, "asyncEnabled", "async_enabled"),
                deletion_strategy=(
                    wvc.ReplicationDeletionStrategy(strategy_raw)
                    if strategy_raw is not None
                    else None
                ),
                async_config=(
                    wvc.Reconfigure.Replication.async_config(**async_cfg)
                    if isinstance(async_cfg, dict)
                    else None
                ),
            )

        if "multiTenancyConfig" in spec and spec["multiTenancyConfig"] is not None:
            mt = spec["multiTenancyConfig"]
            update_kwargs["multi_tenancy_config"] = wvc.Reconfigure.multi_tenancy(
                auto_tenant_creation=_camel_or_snake(
                    mt, "autoTenantCreation", "auto_tenant_creation"
                ),
                auto_tenant_activation=_camel_or_snake(
                    mt, "autoTenantActivation", "auto_tenant_activation"
                ),
            )

        if "objectTtlConfig" in spec and spec["objectTtlConfig"] is not None:
            ttl = spec["objectTtlConfig"]
            if ttl.get("enabled") is False:
                update_kwargs["object_ttl_config"] = wvc.Reconfigure.ObjectTTL.disable()
            else:
                delete_on = _camel_or_snake(ttl, "deleteOn", "delete_on")
                default_ttl = _camel_or_snake(ttl, "defaultTtl", "default_ttl")
                filter_expired = _camel_or_snake(
                    ttl, "filterExpiredObjects", "filter_expired_objects"
                )
                if delete_on in ("_creationTimeUnix", "creationTime", "create"):
                    update_kwargs["object_ttl_config"] = (
                        wvc.Reconfigure.ObjectTTL.delete_by_creation_time(
                            time_to_live=default_ttl,
                            filter_expired_objects=filter_expired,
                        )
                    )
                elif delete_on in ("_lastUpdateTimeUnix", "updateTime", "update"):
                    update_kwargs["object_ttl_config"] = (
                        wvc.Reconfigure.ObjectTTL.delete_by_update_time(
                            time_to_live=default_ttl,
                            filter_expired_objects=filter_expired,
                        )
                    )
                elif isinstance(delete_on, str) and delete_on:
                    update_kwargs["object_ttl_config"] = (
                        wvc.Reconfigure.ObjectTTL.delete_by_date_property(
                            property_name=delete_on,
                            ttl_offset=default_ttl,
                            filter_expired_objects=filter_expired,
                        )
                    )
                else:
                    raise CLIError(
                        code="INVALID_TTL_CONFIG",
                        message="objectTtlConfig requires 'enabled: false' or a valid 'deleteOn' target ('creationTime', 'updateTime', or a date property name).",
                        exit_code=ExitCode.USAGE,
                    )

        if "vectorIndexConfig" in spec and spec["vectorIndexConfig"] is not None:
            vic = spec["vectorIndexConfig"]
            fallback_type = (
                _enum_str(current_cfg.vector_index_type)
                if current_cfg.vector_index_type
                else None
            )
            update_kwargs["vectorizer_config"] = _build_vector_index_update(
                vic.get("vectorIndexType"),
                vic,
                fallback_type=fallback_type,
            )

        if "vectorConfig" in spec and spec["vectorConfig"] is not None:
            existing_vc = current_cfg.vector_config or {}
            vec_updates: list[Any] = []
            for vec_name, vec_patch in spec["vectorConfig"].items():
                if existing_vc and vec_name not in existing_vc:
                    available = ", ".join(sorted(existing_vc.keys()))
                    raise CLIError(
                        code="VECTOR_NOT_FOUND",
                        message=f"Named vector '{vec_name}' does not exist in collection '{collection}'.",
                        exit_code=ExitCode.NOT_FOUND,
                        hint=f"Available named vectors: {available}. Use 'collection add-vector' to add a new vector.",
                    )
                existing_type = None
                if vec_name in existing_vc:
                    existing_type = _enum_str(
                        existing_vc[vec_name].vector_index_config.vector_index_type()
                    )
                vic_patch = (
                    vec_patch["vectorIndexConfig"]
                    if isinstance(vec_patch.get("vectorIndexConfig"), dict)
                    else vec_patch
                )
                vec_updates.append(
                    wvc.Reconfigure.Vectors.update(
                        name=vec_name,
                        vector_index_config=_build_vector_index_update(
                            vec_patch.get("vectorIndexType"),
                            vic_patch,
                            fallback_type=existing_type,
                        ),
                    )
                )
            update_kwargs["vector_config"] = (
                vec_updates[0] if len(vec_updates) == 1 else vec_updates
            )

        if "generativeConfig" in spec and spec["generativeConfig"] is not None:
            mod_name, mod_cfg = next(iter(spec["generativeConfig"].items()))
            update_kwargs["generative_config"] = wvc.Reconfigure.Generative.custom(
                module_name=mod_name,
                module_config=mod_cfg or None,
            )

        if "rerankerConfig" in spec and spec["rerankerConfig"] is not None:
            mod_name, mod_cfg = next(iter(spec["rerankerConfig"].items()))
            update_kwargs["reranker_config"] = wvc.Reconfigure.Reranker.custom(
                module_name=mod_name,
                module_config=mod_cfg or None,
            )

        col_obj.config.update(**update_kwargs)
        return {
            "collection": collection,
            "updated": True,
            "updated_fields": sorted(spec.keys()),
            "warnings": warnings,
        }

    def update_collection(
        self,
        collection: str | None = UpdateCollectionDefaults.collection,
        description: str | None = UpdateCollectionDefaults.description,
        vector_index: str | None = UpdateCollectionDefaults.vector_index,
        vector_name: str | None = None,
        rq_bits: int | None = None,
        filter_strategy: str | None = None,
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
        if rq_bits is not None and rq_bits not in (1, 4, 8):
            raise CLIError(
                code="INVALID_VECTOR_INDEX_CONFIG",
                message=f"Invalid --rq-bits value '{rq_bits}'.",
                exit_code=ExitCode.USAGE,
                hint="Use 1, 4, or 8 for rotational quantization bits.",
            )

        warnings = self._collect_async_replication_warnings(async_replication_config)

        if not self.client.collections.exists(collection):
            raise CLIError(
                code="COLLECTION_NOT_FOUND",
                message=f"Collection '{collection}' does not exist.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli collection list' to see existing collections.",
            )

        resolved_filter = (
            VectorFilterStrategy(filter_strategy)
            if filter_strategy is not None
            else None
        )
        rq_quantizer = wvc.Reconfigure.VectorIndex.Quantizer.rq(bits=rq_bits)

        vector_index_map: dict[str, Any] = {
            "hnsw": wvc.Reconfigure.VectorIndex.hnsw(filter_strategy=resolved_filter),
            "flat": wvc.Reconfigure.VectorIndex.flat(),
            "hfresh": wvc.Reconfigure.VectorIndex.hfresh(),
            "hnsw_pq": wvc.Reconfigure.VectorIndex.hnsw(
                filter_strategy=resolved_filter,
                quantizer=wvc.Reconfigure.VectorIndex.Quantizer.pq(
                    training_limit=training_limit
                ),
            ),
            "hnsw_sq": wvc.Reconfigure.VectorIndex.hnsw(
                filter_strategy=resolved_filter,
                quantizer=wvc.Reconfigure.VectorIndex.Quantizer.sq(
                    training_limit=training_limit
                ),
            ),
            "hnsw_bq": wvc.Reconfigure.VectorIndex.hnsw(
                filter_strategy=resolved_filter,
                quantizer=wvc.Reconfigure.VectorIndex.Quantizer.bq(),
            ),
            "hnsw_rq": wvc.Reconfigure.VectorIndex.hnsw(
                filter_strategy=resolved_filter,
                quantizer=rq_quantizer,
            ),
            "hnsw_acorn": wvc.Reconfigure.VectorIndex.hnsw(
                filter_strategy=VectorFilterStrategy.ACORN
            ),
            "hnsw_pathseer": wvc.Reconfigure.VectorIndex.hnsw(
                filter_strategy=VectorFilterStrategy.PATHSEER
            ),
            "flat_bq": wvc.Reconfigure.VectorIndex.flat(
                quantizer=wvc.Reconfigure.VectorIndex.Quantizer.bq()
            ),
            "flat_rq": wvc.Reconfigure.VectorIndex.flat(quantizer=rq_quantizer),
            "hfresh_rq": wvc.Reconfigure.VectorIndex.hfresh(quantizer=rq_quantizer),
        }

        vec_update: Any = None
        if vector_index:
            vec_update = vector_index_map[vector_index]
        elif resolved_filter is not None:
            vec_update = wvc.Reconfigure.VectorIndex.hnsw(
                filter_strategy=resolved_filter
            )

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

        vectorizer_config_arg: Any = None
        vector_config_arg: Any = None
        if vec_update is not None:
            named_vectors_dict = (
                current_cfg.vector_config
                if isinstance(current_cfg.vector_config, dict)
                else {}
            )
            if vector_name is not None:
                if named_vectors_dict and vector_name not in named_vectors_dict:
                    available = ", ".join(sorted(named_vectors_dict.keys()))
                    raise CLIError(
                        code="VECTOR_NOT_FOUND",
                        message=f"Named vector '{vector_name}' does not exist in collection '{collection}'.",
                        exit_code=ExitCode.NOT_FOUND,
                        hint=f"Available named vectors: {available}.",
                    )
                vector_config_arg = wvc.Reconfigure.Vectors.update(
                    name=vector_name,
                    vector_index_config=vec_update,
                )
            elif named_vectors_dict and not current_cfg.vectorizer:
                if len(named_vectors_dict) == 1:
                    only_name = next(iter(named_vectors_dict.keys()))
                    vector_config_arg = wvc.Reconfigure.Vectors.update(
                        name=only_name,
                        vector_index_config=vec_update,
                    )
                else:
                    available = ", ".join(sorted(named_vectors_dict.keys()))
                    raise CLIError(
                        code="MISSING_VECTOR_NAME",
                        message=(
                            f"Collection '{collection}' has multiple named vectors; "
                            "specify --vector-name to choose which vector index to update."
                        ),
                        exit_code=ExitCode.USAGE,
                        hint=f"Available named vectors: {available}. Or use --from-json to update multiple vectors at once.",
                    )
            else:
                vectorizer_config_arg = vec_update
        elif vector_name is not None:
            raise CLIError(
                code="INVALID_OPTIONS",
                message="--vector-name requires --vector-index or --filter-strategy.",
                exit_code=ExitCode.USAGE,
            )

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

        update_kwargs: dict[str, Any] = {
            "description": description,
            "vectorizer_config": vectorizer_config_arg,
            "replication_config": wvc.Reconfigure.replication(
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
            "multi_tenancy_config": (
                wvc.Reconfigure.multi_tenancy(
                    auto_tenant_creation=resolved_auto_creation,
                    auto_tenant_activation=resolved_auto_activation,
                )
                if mt
                else None
            ),
            "object_ttl_config": object_ttl_config,
        }
        if vector_config_arg is not None:
            update_kwargs["vector_config"] = vector_config_arg

        col_obj.config.update(**update_kwargs)

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
