import json
import sys
from pathlib import Path

import click
from weaviate import WeaviateClient

from weaviate_cli.completion.complete import collection_name_complete
from weaviate_cli.defaults import (
    CreateCollectionDefaults,
    UpdateCollectionDefaults,
)
from weaviate_cli.managers.collection_manager import CollectionManager
from weaviate_cli.utils import (
    ASYNC_REPLICATION_CONFIG_HELP,
    get_client_from_context,
    parse_async_replication_config,
    parse_property_spec,
)


@click.group("collection")
def collection_group() -> None:
    """Manage collections in Weaviate."""


@collection_group.command("create")
@click.argument("name", required=False, default=None)
@click.option(
    "--from-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to a JSON file defining the Weaviate collection schema.",
)
@click.option(
    "--from-json",
    type=str,
    default=None,
    help="Raw JSON string defining the Weaviate collection schema.",
)
@click.option(
    "-p",
    "--property",
    "properties",
    multiple=True,
    help=(
        "Property definition in 'name:type' format (repeatable). "
        "Types: text, int, number, bool/boolean, date, uuid, blob, geo, phone, object, "
        "plus [] array variants (e.g. title:text, tags:text[])."
    ),
)
@click.option(
    "--replication-factor",
    default=CreateCollectionDefaults.replication_factor,
    type=int,
    help=f"Replication factor (default: {CreateCollectionDefaults.replication_factor}).",
)
@click.option(
    "--async-enabled",
    is_flag=True,
    default=CreateCollectionDefaults.async_enabled,
    help="Enable async replication (default: False).",
)
@click.option(
    "--vector-index",
    default=CreateCollectionDefaults.vector_index,
    type=click.Choice(
        [
            "hnsw",
            "flat",
            "dynamic",
            "dynamic_flat_bq",
            "dynamic_flat_bq_hnsw_pq",
            "dynamic_flat_bq_hnsw_sq",
            "dynamic_flat_bq_hnsw_bq",
            "dynamic_hnsw_pq",
            "dynamic_hnsw_sq",
            "dynamic_hnsw_bq",
            "hnsw_pq",
            "hnsw_bq",
            "hnsw_sq",
            "hnsw_rq",
            "hnsw_acorn",
            "hnsw_multivector",
            "flat_bq",
            "hfresh",
        ]
    ),
    help="Vector index type (default: 'hnsw').",
)
@click.option(
    "--inverted-index",
    default=CreateCollectionDefaults.inverted_index,
    type=click.Choice(["timestamp", "null", "length"]),
    help="Inverted index option: 'timestamp', 'null', or 'length'.",
)
@click.option(
    "--training-limit",
    default=CreateCollectionDefaults.training_limit,
    type=int,
    help=f"Training limit for PQ and SQ (default: {CreateCollectionDefaults.training_limit}).",
)
@click.option(
    "--multitenant",
    is_flag=True,
    default=CreateCollectionDefaults.multitenant,
    help="Enable multi-tenancy (default: False).",
)
@click.option(
    "--auto-tenant-creation",
    is_flag=True,
    default=CreateCollectionDefaults.auto_tenant_creation,
    help="Enable auto tenant creation (default: False).",
)
@click.option(
    "--auto-tenant-activation",
    is_flag=True,
    default=CreateCollectionDefaults.auto_tenant_activation,
    help="Enable auto tenant activation (default: False).",
)
@click.option(
    "--shards",
    default=CreateCollectionDefaults.shards,
    type=int,
    help=f"Number of shards (default: {CreateCollectionDefaults.shards}).",
)
@click.option(
    "--vectorizer",
    default=CreateCollectionDefaults.vectorizer,
    type=click.Choice(
        [
            "contextionary",
            "transformers",
            "openai",
            "ollama",
            "cohere",
            "jinaai",
            "jinaai_colbert",
            "weaviate",
            "weaviate-1.5",
            "model2vec",
            "none",
        ]
    ),
    help="Vectorizer to use (default: 'none'). Note: jinaai_colbert requires --named-vector.",
)
@click.option(
    "--vectorizer-base-url",
    default=CreateCollectionDefaults.vectorizer_base_url,
    help="Base URL for the vectorizer.",
)
@click.option(
    "--named-vector",
    is_flag=True,
    default=CreateCollectionDefaults.named_vector,
    help="Enable named vectors (default: False).",
)
@click.option(
    "--named-vector-name",
    default=CreateCollectionDefaults.named_vector_name,
    help="Name of the named vector when --named-vector is enabled (default: 'default').",
)
@click.option(
    "--replication-deletion-strategy",
    default=CreateCollectionDefaults.replication_deletion_strategy,
    type=click.Choice(
        ["delete_on_conflict", "no_automated_resolution", "time_based_resolution"]
    ),
    help="Replication deletion strategy.",
)
@click.option(
    "--object-ttl-type",
    default=CreateCollectionDefaults.object_ttl_type,
    type=click.Choice(["create", "update", "property"]),
    help="Object TTL type (default: 'create').",
)
@click.option(
    "--object-ttl-time",
    default=CreateCollectionDefaults.object_ttl_time,
    type=int,
    help="Object TTL time in seconds.",
)
@click.option(
    "--object-ttl-filter-expired",
    is_flag=True,
    default=False,
    help="Filter expired objects (default: False).",
)
@click.option(
    "--object-ttl-property-name",
    default=CreateCollectionDefaults.object_ttl_property_name,
    type=str,
    help="Date property name for TTL when --object-ttl-type=property.",
)
@click.option(
    "--hfresh-max-posting-size-kb",
    default=CreateCollectionDefaults.hfresh_max_posting_size_kb,
    type=int,
    help="hfresh max posting size in KB.",
)
@click.option(
    "--hfresh-replicas",
    default=CreateCollectionDefaults.hfresh_replicas,
    type=int,
    help="hfresh number of replicas per element across posting lists.",
)
@click.option(
    "--hfresh-search-probe",
    default=CreateCollectionDefaults.hfresh_search_probe,
    type=int,
    help="hfresh search probe.",
)
@click.option(
    "--distance-metric",
    default=CreateCollectionDefaults.distance_metric,
    type=click.Choice(["cosine", "dot", "l2-squared", "hamming", "manhattan"]),
    help="Distance metric (default: server default).",
)
@click.option(
    "--rescore-limit",
    default=CreateCollectionDefaults.rescore_limit,
    type=int,
    help="Rescore limit (default: server default).",
)
@click.option(
    "--async-replication-config",
    multiple=True,
    help=ASYNC_REPLICATION_CONFIG_HELP,
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def create_collection_cli(
    ctx: click.Context,
    name: str | None,
    from_file: Path | None,
    from_json: str | None,
    properties: tuple[str, ...],
    replication_factor: int,
    async_enabled: bool,
    vector_index: str,
    inverted_index: str | None,
    training_limit: int,
    multitenant: bool,
    auto_tenant_creation: bool,
    auto_tenant_activation: bool,
    shards: int,
    vectorizer: str,
    vectorizer_base_url: str | None,
    named_vector: bool,
    named_vector_name: str | None,
    replication_deletion_strategy: str | None,
    object_ttl_type: str,
    object_ttl_time: int | None,
    object_ttl_filter_expired: bool,
    object_ttl_property_name: str | None,
    hfresh_max_posting_size_kb: int | None,
    hfresh_replicas: int | None,
    hfresh_search_probe: int | None,
    distance_metric: str | None,
    rescore_limit: int | None,
    async_replication_config: tuple[str, ...],
    json_output: bool,
) -> None:
    """Create a collection in Weaviate."""
    if from_file is not None and from_json is not None:
        raise click.UsageError("Cannot specify both --from-file and --from-json.")

    if from_file is not None or from_json is not None:
        if properties:
            raise click.UsageError(
                "Cannot combine --property with --from-file or --from-json."
            )
        client: WeaviateClient | None = None
        try:
            raw_json = (
                from_file.read_text(encoding="utf-8")
                if from_file is not None
                else from_json or ""
            )
            config = json.loads(raw_json)
            if not isinstance(config, dict):
                raise ValueError("Collection schema JSON must be a JSON object.")
            client = get_client_from_context(ctx)
            collection_man = CollectionManager(client)
            collection_man.create_collection_from_dict(
                config=config,
                name_override=name,
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
        return

    if not name:
        raise click.UsageError(
            "Collection NAME is required unless --from-file or --from-json is provided."
        )

    if (
        object_ttl_type != "property"
        and object_ttl_property_name
        != CreateCollectionDefaults.object_ttl_property_name
    ):
        click.echo(
            "Error: object_ttl_property_name is only valid when object_ttl_type is 'property'.",
            err=True,
        )
        sys.exit(1)

    client = None
    try:
        parsed_async_config = parse_async_replication_config(async_replication_config)
        if parsed_async_config == {}:
            raise click.UsageError(
                "--async-replication-config 'reset' is only supported on update, not create."
            )
        parsed_properties = (
            [parse_property_spec(spec) for spec in properties] if properties else None
        )
        client = get_client_from_context(ctx)
        collection_man = CollectionManager(client)
        collection_man.create_collection(
            collection=name,
            replication_factor=replication_factor,
            async_enabled=async_enabled,
            vector_index=vector_index,
            inverted_index=inverted_index,
            training_limit=training_limit,
            multitenant=multitenant,
            auto_tenant_creation=auto_tenant_creation,
            auto_tenant_activation=auto_tenant_activation,
            shards=shards,
            vectorizer=vectorizer,
            vectorizer_base_url=vectorizer_base_url,
            replication_deletion_strategy=replication_deletion_strategy,
            named_vector=named_vector,
            named_vector_name=named_vector_name,
            hfresh_max_posting_size_kb=hfresh_max_posting_size_kb,
            hfresh_replicas=hfresh_replicas,
            hfresh_search_probe=hfresh_search_probe,
            distance_metric=distance_metric,
            rescore_limit=rescore_limit,
            json_output=json_output,
            object_ttl_type=object_ttl_type,
            object_ttl_time=object_ttl_time,
            object_ttl_filter_expired=object_ttl_filter_expired,
            object_ttl_property_name=object_ttl_property_name,
            async_replication_config=parsed_async_config,
            properties=parsed_properties,
        )
    except click.UsageError:
        raise
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@collection_group.command("list")
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def list_collections_cli(ctx: click.Context, json_output: bool) -> None:
    """List all collections in Weaviate."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        collection_man = CollectionManager(client)
        collection_man.get_collection(collection=None, json_output=json_output)
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@collection_group.command("get")
@click.argument("name", shell_complete=collection_name_complete)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def get_collection_cli(ctx: click.Context, name: str, json_output: bool) -> None:
    """Get configuration for a specific collection."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        collection_man = CollectionManager(client)
        collection_man.get_collection(collection=name, json_output=json_output)
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@collection_group.command("update")
@click.argument("name", shell_complete=collection_name_complete)
@click.option(
    "--async-enabled",
    default=UpdateCollectionDefaults.async_enabled,
    type=bool,
    help="Enable or disable async replication.",
)
@click.option(
    "--replication-factor",
    default=UpdateCollectionDefaults.replication_factor,
    type=int,
    help="Replication factor.",
)
@click.option(
    "--vector-index",
    default=UpdateCollectionDefaults.vector_index,
    type=click.Choice(
        ["hnsw", "flat", "hnsw_pq", "hnsw_bq", "hnsw_sq", "flat_bq", "hnsw_acorn"]
    ),
    help="Vector index type.",
)
@click.option(
    "--description",
    default=UpdateCollectionDefaults.description,
    help="Collection description.",
)
@click.option(
    "--training-limit",
    default=UpdateCollectionDefaults.training_limit,
    type=int,
    help=f"Training limit for PQ and SQ (default: {UpdateCollectionDefaults.training_limit}).",
)
@click.option(
    "--auto-tenant-creation",
    default=UpdateCollectionDefaults.auto_tenant_creation,
    type=bool,
    help="Enable or disable auto tenant creation.",
)
@click.option(
    "--auto-tenant-activation",
    default=UpdateCollectionDefaults.auto_tenant_activation,
    type=bool,
    help="Enable or disable auto tenant activation.",
)
@click.option(
    "--replication-deletion-strategy",
    default=UpdateCollectionDefaults.replication_deletion_strategy,
    type=click.Choice(
        ["delete_on_conflict", "no_automated_resolution", "time_based_resolution"]
    ),
    help="Replication deletion strategy.",
)
@click.option(
    "--object-ttl-type",
    default=UpdateCollectionDefaults.object_ttl_type,
    type=click.Choice(["create", "update", "property", "disable"]),
    help="Object TTL type (default: 'create'). Use 'disable' to turn off TTL.",
)
@click.option(
    "--object-ttl-time",
    default=UpdateCollectionDefaults.object_ttl_time,
    type=int,
    help="Object TTL time in seconds.",
)
@click.option(
    "--object-ttl-filter-expired",
    type=bool,
    default=UpdateCollectionDefaults.object_ttl_filter_expired,
    help="Filter expired objects.",
)
@click.option(
    "--object-ttl-property-name",
    default=UpdateCollectionDefaults.object_ttl_property_name,
    type=str,
    help="Date property name for TTL when --object-ttl-type=property.",
)
@click.option(
    "--async-replication-config",
    multiple=True,
    help=ASYNC_REPLICATION_CONFIG_HELP,
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def update_collection_cli(
    ctx: click.Context,
    name: str,
    async_enabled: bool | None,
    replication_factor: int | None,
    vector_index: str | None,
    description: str | None,
    training_limit: int,
    auto_tenant_creation: bool | None,
    auto_tenant_activation: bool | None,
    replication_deletion_strategy: str | None,
    object_ttl_type: str,
    object_ttl_time: int | None,
    object_ttl_filter_expired: bool | None,
    object_ttl_property_name: str | None,
    async_replication_config: tuple[str, ...],
    json_output: bool,
) -> None:
    """Update operational configuration for a collection."""
    if (
        object_ttl_type not in ("property", "disable")
        and object_ttl_property_name
        != UpdateCollectionDefaults.object_ttl_property_name
    ):
        click.echo(
            "Error: object_ttl_property_name is only valid when object_ttl_type is 'property'.",
            err=True,
        )
        sys.exit(1)

    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        collection_man = CollectionManager(client)
        collection_man.update_collection(
            collection=name,
            async_enabled=async_enabled,
            replication_factor=replication_factor,
            vector_index=vector_index,
            description=description,
            training_limit=training_limit,
            auto_tenant_creation=auto_tenant_creation,
            auto_tenant_activation=auto_tenant_activation,
            replication_deletion_strategy=replication_deletion_strategy,
            json_output=json_output,
            object_ttl_type=object_ttl_type,
            object_ttl_time=object_ttl_time,
            object_ttl_filter_expired=object_ttl_filter_expired,
            object_ttl_property_name=object_ttl_property_name,
            async_replication_config=parse_async_replication_config(
                async_replication_config
            ),
        )
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@collection_group.command("delete")
@click.argument(
    "name", required=False, default=None, shell_complete=collection_name_complete
)
@click.option("--all", "delete_all", is_flag=True, help="Delete all collections.")
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def delete_collection_cli(
    ctx: click.Context, name: str | None, delete_all: bool, json_output: bool
) -> None:
    """Delete a collection (or all collections with --all)."""
    if delete_all and name:
        raise click.UsageError("Cannot specify both NAME and --all.")
    if not delete_all and not name:
        raise click.UsageError("Either NAME or --all must be specified.")

    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        collection_man = CollectionManager(client)
        collection_man.delete_collection(
            collection=name, all=delete_all, json_output=json_output
        )
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()
