"""Click commands for the 'collection' resource group."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click
from prettytable import PrettyTable
from weaviate import WeaviateClient

from weaviate_cli.completion.complete import collection_name_complete
from weaviate_cli.defaults import UpdateCollectionDefaults
from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.managers.collection_manager import CollectionManager
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    AXGroup,
    emit_error,
    emit_success,
    emit_warning,
    get_runtime,
    handle_command_error,
)
from weaviate_cli.specs.collection import (
    VALID_DISTANCE_METRICS,
    VALID_FILTER_STRATEGIES,
    VALID_TOKENIZATIONS,
    VALID_VECTOR_INDEX_TYPES,
    get_collection_template,
    parse_collection_json,
    parse_json_object,
    validate_collection_spec,
    validate_collection_update_spec,
    validate_property_spec,
    validate_vector_add_spec,
)
from weaviate_cli.utils import (
    ASYNC_REPLICATION_CONFIG_HELP,
    get_client_from_context,
    parse_async_replication_config,
)


def _read_schema_input(
    from_file: str | None,
    from_json: str | None,
    *,
    label: str = "Schema",
) -> tuple[str, str]:
    if from_file is not None:
        if from_file == "-":
            return sys.stdin.read(), "stdin"
        path = Path(from_file)
        if not path.is_file():
            raise CLIError(
                code="FILE_NOT_FOUND",
                message=f"{label} file '{from_file}' does not exist or is not a file.",
                exit_code=ExitCode.USAGE,
                hint="Provide an existing JSON file path to --from-file or pass '-' to read from stdin.",
            )
        return path.read_text(encoding="utf-8"), str(path)
    assert from_json is not None
    return from_json, "--from-json"


def _render_collections_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        click.echo("No collections found.")
        return

    table = PrettyTable()
    table.field_names = [
        "Collection",
        "Multitenancy",
        "Tenants",
        "Objects",
        "Repl. Factor",
        "Vector Index",
        "Named Vectors",
        "Vectorizer",
    ]
    table.align = "l"
    for row in rows:
        table.add_row(
            [
                row["name"],
                "True" if row["multitenancy"] else "False",
                row["tenant_count"],
                row["object_count"],
                row["replication_factor"],
                row["vector_index"],
                "True" if row["named_vectors"] else "False",
                row["vectorizer"],
            ]
        )
    click.echo(table)
    click.echo(f"Total: {len(rows)} collections")


@click.group("collection", cls=AXGroup)
def collection_group() -> None:
    """Manage Weaviate collections (DDL and operational configuration)."""


@collection_group.command(
    "create",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  # Print a valid starter /v1/schema JSON template (no cluster needed)\n"
        "  weaviate-cli collection create --template > schema.json\n"
        "\n\b\n"
        "  # Validate a schema file locally without creating it\n"
        "  weaviate-cli collection create --from-file schema.json --dry-run\n"
        "\n\b\n"
        "  # Create a collection from a JSON file (or '-' for stdin)\n"
        "  weaviate-cli collection create --from-file schema.json\n"
        "\n\b\n"
        "  # Override the collection name from a file or pass inline JSON\n"
        "  weaviate-cli collection create ArticlesV2 --from-file schema.json\n"
        '  weaviate-cli collection create --from-json \'{"class": "Articles", "vectorizer": "none"}\''
    ),
)
@click.argument("name", required=False, default=None)
@click.option(
    "--from-file",
    type=str,
    default=None,
    metavar="PATH|-",
    help="Path to a Weaviate /v1/schema JSON file, or '-' to read from stdin.",
)
@click.option(
    "--from-json",
    type=str,
    default=None,
    metavar="JSON",
    help="Inline Weaviate /v1/schema JSON string.",
)
@click.option(
    "--template",
    is_flag=True,
    default=False,
    help="Print a valid starter /v1/schema JSON template to stdout and exit.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Validate the collection schema locally without creating it.",
)
@click.option(
    "--check-cluster",
    is_flag=True,
    default=False,
    help="With --dry-run, also verify enabled modules and name conflicts against the live cluster.",
)
@click.option(
    "--if-not-exists",
    is_flag=True,
    default=False,
    help="Succeed without error if the collection already exists.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def create_collection_cli(
    ctx: click.Context,
    name: str | None,
    from_file: str | None,
    from_json: str | None,
    template: bool,
    dry_run: bool,
    check_cluster: bool,
    if_not_exists: bool,
    json_output: bool | None,
) -> None:
    """Create a collection from a Weaviate /v1/schema JSON definition."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "collection create"

    # --template prints raw valid JSON directly so `... --template > schema.json`
    # composes cleanly with `... --from-file schema.json` even when redirected.
    if template:
        if from_file is not None or from_json is not None or dry_run or check_cluster:
            emit_error(
                runtime,
                CLIError(
                    code="CONFLICTING_OPTIONS",
                    message="Cannot combine --template with --from-file, --from-json, --dry-run, or --check-cluster.",
                    exit_code=ExitCode.USAGE,
                    hint="Run 'weaviate-cli collection create --template' by itself.",
                ),
                command=command,
            )
        starter = get_collection_template()
        if name:
            starter["class"] = name
        click.echo(json.dumps(starter, indent=2))
        return

    if check_cluster and not dry_run:
        emit_error(
            runtime,
            CLIError(
                code="INVALID_OPTIONS",
                message="--check-cluster is only valid together with --dry-run.",
                exit_code=ExitCode.USAGE,
                hint="Live cluster checks run automatically during normal 'collection create'.",
            ),
            command=command,
        )

    if from_file is not None and from_json is not None:
        emit_error(
            runtime,
            CLIError(
                code="CONFLICTING_OPTIONS",
                message="Cannot specify both --from-file and --from-json.",
                exit_code=ExitCode.USAGE,
                hint="Pass either --from-file <path|-> or --from-json '<json>'.",
            ),
            command=command,
        )

    if from_file is None and from_json is None:
        emit_error(
            runtime,
            CLIError(
                code="MISSING_SCHEMA_INPUT",
                message="A collection schema JSON is required via --from-file or --from-json.",
                exit_code=ExitCode.USAGE,
                hint=(
                    "Run 'weaviate-cli collection create --template' to generate a valid "
                    "starter JSON schema, then pass it to --from-file or --from-json."
                ),
            ),
            command=command,
        )

    client: WeaviateClient | None = None
    try:
        raw_json, source = _read_schema_input(from_file, from_json)
        raw_spec = parse_collection_json(raw_json, source=source)

        # Stage 1: local structural and semantic validation (offline).
        prepared_spec, issues = validate_collection_spec(
            raw_spec,
            name_override=name,
        )
        if issues:
            raise CLIError(
                code="INVALID_COLLECTION_SPEC",
                message=f"Collection schema validation failed with {len(issues)} issue(s).",
                exit_code=ExitCode.USAGE,
                issues=issues,
                hint="Run 'weaviate-cli collection create --template' for a valid /v1/schema example.",
            )

        collection_name = str(prepared_spec["class"])

        if dry_run and not check_cluster:
            payload = {
                "valid": True,
                "dry_run": True,
                "cluster_checked": False,
                "collection": collection_name,
                "schema": prepared_spec,
            }
            emit_success(
                runtime,
                payload,
                command=command,
                text_renderer=lambda: click.echo(
                    f"Collection schema for '{collection_name}' is valid (dry-run; not created)."
                ),
            )
            return

        # Stage 2: live cluster preflight (enabled modules + conflict check).
        client = get_client_from_context(ctx)
        collection_man = CollectionManager(client)
        available_modules = collection_man.get_available_modules()
        if available_modules is not None:
            _, live_issues = validate_collection_spec(
                prepared_spec,
                available_modules=available_modules,
            )
            if live_issues:
                raise CLIError(
                    code="INVALID_COLLECTION_SPEC",
                    message=(
                        f"Cluster compatibility validation failed with "
                        f"{len(live_issues)} issue(s)."
                    ),
                    exit_code=ExitCode.USAGE,
                    issues=live_issues,
                    hint='Update the module names in your schema or use \'"vectorizer": "none"\'.',
                )

        if dry_run:
            exists = bool(client.collections.exists(collection_name))
            if exists and not if_not_exists:
                raise CLIError(
                    code="COLLECTION_EXISTS",
                    message=f"Collection '{collection_name}' already exists.",
                    exit_code=ExitCode.NOT_FOUND,
                    hint="Pass --if-not-exists to allow existing collections, or choose a different name.",
                )
            payload = {
                "valid": True,
                "dry_run": True,
                "cluster_checked": True,
                "collection": collection_name,
                "already_exists": exists,
                "schema": prepared_spec,
            }
            emit_success(
                runtime,
                payload,
                command=command,
                text_renderer=lambda: click.echo(
                    f"Collection schema for '{collection_name}' is valid against cluster (dry-run; not created)."
                ),
            )
            return

        result = collection_man.create_collection(
            prepared_spec,
            if_not_exists=if_not_exists,
        )

        def _render_create_text() -> None:
            if result["already_exists"]:
                click.echo(
                    f"Collection '{collection_name}' already exists (skipped via --if-not-exists)."
                )
            else:
                click.echo(f"Collection '{collection_name}' created successfully.")

        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=_render_create_text,
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@collection_group.command("list", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def list_collections_cli(ctx: click.Context, json_output: bool | None) -> None:
    """List all collections in Weaviate."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "collection list"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        collection_man = CollectionManager(client)
        rows = collection_man.list_collections()
        emit_success(
            runtime,
            {"collections": rows, "total": len(rows)},
            command=command,
            text_renderer=lambda: _render_collections_table(rows),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@collection_group.command("get", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("name", shell_complete=collection_name_complete)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def get_collection_cli(ctx: click.Context, name: str, json_output: bool | None) -> None:
    """Get the /v1/schema configuration for a specific collection."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "collection get"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        collection_man = CollectionManager(client)
        config = collection_man.get_collection(collection=name)
        emit_success(
            runtime,
            config,
            command=command,
            text_renderer=lambda: click.echo(json.dumps(config, indent=2)),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@collection_group.command(
    "add-property",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  # Add a primitive property using flags\n"
        '  weaviate-cli collection add-property Articles --name tags --data-type "text[]" --description "Topic tags"\n'
        "\n\b\n"
        "  # Add a single-target or multi-target cross-reference\n"
        "  weaviate-cli collection add-property Articles --name hasAuthor --data-type Author\n"
        "  weaviate-cli collection add-property Articles --name related --data-type Author --data-type Publisher\n"
        "\n\b\n"
        "  # Add a nested or advanced property from /v1/schema JSON\n"
        '  weaviate-cli collection add-property Articles --from-json \'{"name": "meta", "dataType": ["object"], "nestedProperties": [{"name": "source", "dataType": ["text"]}]}\''
    ),
)
@click.argument("collection", shell_complete=collection_name_complete)
@click.option(
    "--from-file",
    type=str,
    default=None,
    metavar="PATH|-",
    help="Path to a property JSON file, or '-' to read from stdin.",
)
@click.option(
    "--from-json",
    type=str,
    default=None,
    metavar="JSON",
    help="Inline /v1/schema property JSON string.",
)
@click.option(
    "--name",
    "prop_name",
    type=str,
    default=None,
    help="Property or cross-reference name (flag mode).",
)
@click.option(
    "--data-type",
    "data_types",
    type=str,
    multiple=True,
    help="Primitive dataType (e.g. text, int, text[]) or uppercase target collection name for a cross-reference. Repeat for multi-target references.",
)
@click.option(
    "--description",
    type=str,
    default=None,
    help="Property description.",
)
@click.option(
    "--tokenization",
    type=click.Choice(sorted(VALID_TOKENIZATIONS)),
    default=None,
    help="Tokenization strategy for text properties.",
)
@click.option(
    "--index-filterable/--no-index-filterable",
    default=None,
    help="Enable or disable filterable inverted index.",
)
@click.option(
    "--index-searchable/--no-index-searchable",
    default=None,
    help="Enable or disable searchable BM25 inverted index.",
)
@click.option(
    "--index-range-filters/--no-index-range-filters",
    default=None,
    help="Enable or disable range filter index (int/number/date).",
)
@click.option(
    "--skip-vectorization/--no-skip-vectorization",
    default=None,
    help="Skip this property during automatic vectorization.",
)
@click.option(
    "--vectorize-property-name/--no-vectorize-property-name",
    default=None,
    help="Include or exclude the property name during vectorization.",
)
@click.option(
    "--if-not-exists",
    is_flag=True,
    default=False,
    help="Succeed without error if the property or cross-reference already exists.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def add_property_cli(
    ctx: click.Context,
    collection: str,
    from_file: str | None,
    from_json: str | None,
    prop_name: str | None,
    data_types: tuple[str, ...],
    description: str | None,
    tokenization: str | None,
    index_filterable: bool | None,
    index_searchable: bool | None,
    index_range_filters: bool | None,
    skip_vectorization: bool | None,
    vectorize_property_name: bool | None,
    if_not_exists: bool,
    json_output: bool | None,
) -> None:
    """Add a property or cross-reference to an existing collection."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "collection add-property"

    if from_file is not None and from_json is not None:
        emit_error(
            runtime,
            CLIError(
                code="CONFLICTING_OPTIONS",
                message="Cannot specify both --from-file and --from-json.",
                exit_code=ExitCode.USAGE,
            ),
            command=command,
        )

    using_json = from_file is not None or from_json is not None
    using_flags = any(
        val is not None
        for val in (
            prop_name,
            description,
            tokenization,
            index_filterable,
            index_searchable,
            index_range_filters,
            skip_vectorization,
            vectorize_property_name,
        )
    ) or bool(data_types)

    if using_json and using_flags:
        emit_error(
            runtime,
            CLIError(
                code="CONFLICTING_OPTIONS",
                message="Cannot combine --from-file/--from-json with property flags (--name, --data-type, etc.).",
                exit_code=ExitCode.USAGE,
                hint="Either pass a JSON definition via --from-file/--from-json or use flag options.",
            ),
            command=command,
        )

    if not using_json and not using_flags:
        emit_error(
            runtime,
            CLIError(
                code="MISSING_PROPERTY_INPUT",
                message="Provide property flags (--name and --data-type) or JSON via --from-file/--from-json.",
                exit_code=ExitCode.USAGE,
                hint="Example: 'weaviate-cli collection add-property Articles --name tags --data-type text[]'.",
            ),
            command=command,
        )

    client: WeaviateClient | None = None
    try:
        if using_json:
            raw_json, source = _read_schema_input(
                from_file, from_json, label="Property"
            )
            raw_spec = parse_json_object(
                raw_json,
                source=source,
                error_code="INVALID_PROPERTY_SPEC",
                label="Property definition",
                hint='Pass a JSON object like {"name": "tags", "dataType": ["text[]"]}.',
            )
        else:
            raw_spec = {}
            if prop_name is not None:
                raw_spec["name"] = prop_name
            if data_types:
                expanded_types: list[str] = []
                for entry in data_types:
                    for part in entry.split(","):
                        cleaned = part.strip()
                        if cleaned:
                            expanded_types.append(cleaned)
                raw_spec["dataType"] = expanded_types
            if description is not None:
                raw_spec["description"] = description
            if tokenization is not None:
                raw_spec["tokenization"] = tokenization
            if index_filterable is not None:
                raw_spec["indexFilterable"] = index_filterable
            if index_searchable is not None:
                raw_spec["indexSearchable"] = index_searchable
            if index_range_filters is not None:
                raw_spec["indexRangeFilters"] = index_range_filters
            if skip_vectorization is not None:
                raw_spec["skipVectorization"] = skip_vectorization
            if vectorize_property_name is not None:
                raw_spec["vectorizePropertyName"] = vectorize_property_name

        prepared_spec, issues = validate_property_spec(raw_spec)
        if issues:
            raise CLIError(
                code="INVALID_PROPERTY_SPEC",
                message=f"Property validation failed with {len(issues)} issue(s).",
                exit_code=ExitCode.USAGE,
                issues=issues,
                hint='Example: {"name": "tags", "dataType": ["text[]"]} or --name tags --data-type text[].',
            )

        client = get_client_from_context(ctx)
        collection_man = CollectionManager(client)
        result = collection_man.add_property(
            collection,
            prepared_spec,
            if_not_exists=if_not_exists,
        )

        def _render_add_prop_text() -> None:
            kind = result["kind"].capitalize()
            if result["already_exists"]:
                click.echo(
                    f"{kind} '{result['property']}' already exists in collection '{collection}' "
                    "(skipped via --if-not-exists)."
                )
            else:
                click.echo(
                    f"{kind} '{result['property']}' added to collection '{collection}'."
                )

        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=_render_add_prop_text,
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@collection_group.command(
    "add-vector",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  # Add a self-provided (BYOV) named vector with HNSW + 8-bit RQ\n"
        "  weaviate-cli collection add-vector Articles title_vec --quantizer rq --rq-bits 8\n"
        "\n\b\n"
        "  # Add a module-backed named vector targeting specific properties\n"
        "  weaviate-cli collection add-vector Articles summary_vec --vectorizer text2vec-transformers --source-property summary\n"
        "\n\b\n"
        "  # Add one or more named vectors from /v1/schema vectorConfig JSON\n"
        '  weaviate-cli collection add-vector Articles --from-json \'{"title_vec": {"vectorizer": {"none": {}}, "vectorIndexType": "hfresh"}}\''
    ),
)
@click.argument("collection", shell_complete=collection_name_complete)
@click.argument("vector_name", required=False, default=None)
@click.option(
    "--from-file",
    type=str,
    default=None,
    metavar="PATH|-",
    help="Path to a vectorConfig JSON file, or '-' to read from stdin.",
)
@click.option(
    "--from-json",
    type=str,
    default=None,
    metavar="JSON",
    help="Inline vectorConfig JSON (either {name: config} map or single config when VECTOR_NAME is passed).",
)
@click.option(
    "--vectorizer",
    type=str,
    default=None,
    help="Vectorizer module name (default: 'none' for bring-your-own vectors).",
)
@click.option(
    "--source-property",
    "source_properties",
    type=str,
    multiple=True,
    help="Property to vectorize (repeatable; used with module-backed --vectorizer).",
)
@click.option(
    "--vector-index",
    type=click.Choice(sorted(VALID_VECTOR_INDEX_TYPES)),
    default=None,
    help="Vector index type (hnsw, flat, hfresh, dynamic).",
)
@click.option(
    "--distance",
    type=click.Choice(sorted(VALID_DISTANCE_METRICS)),
    default=None,
    help="Vector distance metric (e.g. cosine, dot, l2-squared).",
)
@click.option(
    "--quantizer",
    type=click.Choice(["rq", "bq", "pq", "sq"]),
    default=None,
    help="Compression quantizer for the new vector index.",
)
@click.option(
    "--rq-bits",
    type=int,
    default=None,
    help="Bit width for RQ quantizer (1, 4, or 8).",
)
@click.option(
    "--filter-strategy",
    type=click.Choice(sorted(VALID_FILTER_STRATEGIES)),
    default=None,
    help="HNSW filter strategy (sweeping, acorn, pathseer).",
)
@click.option(
    "--if-not-exists",
    is_flag=True,
    default=False,
    help="Skip named vectors that already exist instead of failing.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def add_vector_cli(
    ctx: click.Context,
    collection: str,
    vector_name: str | None,
    from_file: str | None,
    from_json: str | None,
    vectorizer: str | None,
    source_properties: tuple[str, ...],
    vector_index: str | None,
    distance: str | None,
    quantizer: str | None,
    rq_bits: int | None,
    filter_strategy: str | None,
    if_not_exists: bool,
    json_output: bool | None,
) -> None:
    """Add one or more named vectors to an existing collection."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "collection add-vector"

    if from_file is not None and from_json is not None:
        emit_error(
            runtime,
            CLIError(
                code="CONFLICTING_OPTIONS",
                message="Cannot specify both --from-file and --from-json.",
                exit_code=ExitCode.USAGE,
            ),
            command=command,
        )

    using_json = from_file is not None or from_json is not None
    using_flags = any(
        val is not None
        for val in (
            vectorizer,
            vector_index,
            distance,
            quantizer,
            rq_bits,
            filter_strategy,
        )
    ) or bool(source_properties)

    if using_json and using_flags:
        emit_error(
            runtime,
            CLIError(
                code="CONFLICTING_OPTIONS",
                message="Cannot combine --from-file/--from-json with vector flags (--vectorizer, --vector-index, etc.).",
                exit_code=ExitCode.USAGE,
            ),
            command=command,
        )

    if not using_json and vector_name is None:
        emit_error(
            runtime,
            CLIError(
                code="MISSING_VECTOR_INPUT",
                message="Specify VECTOR_NAME (flag mode) or pass vector definitions via --from-file/--from-json.",
                exit_code=ExitCode.USAGE,
                hint="Example: 'weaviate-cli collection add-vector Articles title_vec --vectorizer none'.",
            ),
            command=command,
        )

    client: WeaviateClient | None = None
    try:
        if using_json:
            raw_json, source = _read_schema_input(from_file, from_json, label="Vector")
            raw_spec = parse_json_object(
                raw_json,
                source=source,
                error_code="INVALID_VECTOR_SPEC",
                label="Vector definition",
                hint='Pass a map like {"title_vec": {"vectorizer": {"none": {}}}}.',
            )
            prepared_vectors, issues = validate_vector_add_spec(
                raw_spec,
                vector_name=vector_name,
            )
        else:
            assert vector_name is not None
            mod_name = vectorizer or "none"
            mod_cfg: dict[str, Any] = {}
            if source_properties:
                mod_cfg["properties"] = list(source_properties)
            vic: dict[str, Any] = {}
            if distance is not None:
                vic["distance"] = distance
            if filter_strategy is not None:
                vic["filterStrategy"] = filter_strategy
            if quantizer == "rq" or (quantizer is None and rq_bits is not None):
                rq_obj: dict[str, Any] = {"enabled": True}
                if rq_bits is not None:
                    rq_obj["bits"] = rq_bits
                vic["rq"] = rq_obj
            elif quantizer is not None:
                vic[quantizer] = {"enabled": True}

            vec_def: dict[str, Any] = {"vectorizer": {mod_name: mod_cfg}}
            if vector_index is not None:
                vec_def["vectorIndexType"] = vector_index
            if vic:
                vec_def["vectorIndexConfig"] = vic

            prepared_vectors, issues = validate_vector_add_spec(
                vec_def,
                vector_name=vector_name,
            )

        if issues:
            raise CLIError(
                code="INVALID_VECTOR_SPEC",
                message=f"Vector configuration validation failed with {len(issues)} issue(s).",
                exit_code=ExitCode.USAGE,
                issues=issues,
            )

        client = get_client_from_context(ctx)
        collection_man = CollectionManager(client)
        available_modules = collection_man.get_available_modules()
        if available_modules is not None:
            _, live_issues = validate_vector_add_spec(
                prepared_vectors,
                available_modules=available_modules,
            )
            if live_issues:
                raise CLIError(
                    code="INVALID_VECTOR_SPEC",
                    message=(
                        f"Cluster compatibility validation failed with "
                        f"{len(live_issues)} issue(s)."
                    ),
                    exit_code=ExitCode.USAGE,
                    issues=live_issues,
                    hint='Update the vectorizer module name or use "none" for bring-your-own vectors.',
                )

        result = collection_man.add_vector(
            collection,
            prepared_vectors,
            if_not_exists=if_not_exists,
        )

        def _render_add_vec_text() -> None:
            added = result["added"]
            skipped = result["skipped"]
            if added:
                click.echo(
                    f"Added named vector(s) {', '.join(added)} to collection '{collection}'."
                )
            if skipped:
                click.echo(
                    f"Skipped existing named vector(s) {', '.join(skipped)} (--if-not-exists)."
                )

        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=_render_add_vec_text,
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@collection_group.command(
    "delete-vector",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli collection delete-vector Articles title_vec --yes"
    ),
)
@click.argument("collection", shell_complete=collection_name_complete)
@click.argument("vector_name")
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm destructive and irreversible named vector deletion (required).",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def delete_vector_cli(
    ctx: click.Context,
    collection: str,
    vector_name: str,
    yes: bool,
    json_output: bool | None,
) -> None:
    """Delete a named vector index and its vector data from a collection (requires --yes)."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "collection delete-vector"

    if not yes:
        emit_error(
            runtime,
            CLIError(
                code="CONFIRMATION_REQUIRED",
                message=(
                    f"Deleting named vector '{vector_name}' from collection '{collection}' "
                    "is destructive and irreversible and requires --yes."
                ),
                exit_code=ExitCode.USAGE,
                hint=(
                    f"Re-run with 'weaviate-cli collection delete-vector {collection} "
                    f"{vector_name} --yes' after confirming."
                ),
            ),
            command=command,
        )

    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        collection_man = CollectionManager(client)
        result = collection_man.delete_vector(collection, vector_name)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: click.echo(result["note"]),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@collection_group.command(
    "delete-property-index",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli collection delete-property-index Articles body --index-type searchable --yes\n"
        "  weaviate-cli collection delete-property-index Articles price --index-type range-filters --yes"
    ),
)
@click.argument("collection", shell_complete=collection_name_complete)
@click.argument("property_name")
@click.option(
    "--index-type",
    required=True,
    type=click.Choice(
        ["searchable", "filterable", "range-filters"], case_sensitive=False
    ),
    help="Property inverted index type to drop.",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm destructive property index deletion (required).",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def delete_property_index_cli(
    ctx: click.Context,
    collection: str,
    property_name: str,
    index_type: str,
    yes: bool,
    json_output: bool | None,
) -> None:
    """Drop an inverted index from an existing property (requires --yes)."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "collection delete-property-index"

    if not yes:
        emit_error(
            runtime,
            CLIError(
                code="CONFIRMATION_REQUIRED",
                message=(
                    f"Dropping '{index_type}' index on property '{property_name}' of collection "
                    f"'{collection}' is destructive and requires --yes."
                ),
                exit_code=ExitCode.USAGE,
                hint=(
                    f"Re-run with 'weaviate-cli collection delete-property-index {collection} "
                    f"{property_name} --index-type {index_type} --yes' after confirming."
                ),
            ),
            command=command,
        )

    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        collection_man = CollectionManager(client)
        result = collection_man.delete_property_index(
            collection, property_name, index_type
        )
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: click.echo(
                f"Property index '{result['index_type']}' on '{collection}.{property_name}' "
                f"{'deleted' if result['deleted'] else 'was not present'}."
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@collection_group.command(
    "update",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  # Update operational settings via flags (including named vectors, RQ, PathSeer, HFresh)\n"
        '  weaviate-cli collection update Articles --description "Knowledge base"\n'
        "  weaviate-cli collection update Articles --vector-name title_vec --vector-index hnsw_rq --rq-bits 8 --filter-strategy pathseer\n"
        "\n\b\n"
        "  # Declarative JSON patch (supports BM25/stopwords, named vectors, propertyDescriptions, generative/reranker)\n"
        '  weaviate-cli collection update Articles --from-json \'{"invertedIndexConfig": {"bm25": {"b": 0.7, "k1": 1.4}}, "propertyDescriptions": {"body": "Main text"}}\'\n'
        "  weaviate-cli collection update Articles --from-file patch.json --dry-run"
    ),
)
@click.argument("name", shell_complete=collection_name_complete)
@click.option(
    "--from-file",
    type=str,
    default=None,
    metavar="PATH|-",
    help="Path to a declarative collection update patch JSON file, or '-' for stdin.",
)
@click.option(
    "--from-json",
    type=str,
    default=None,
    metavar="JSON",
    help="Inline declarative collection update patch JSON string.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="With --from-file/--from-json, validate the update patch locally without applying it.",
)
@click.option(
    "--async-enabled",
    default=UpdateCollectionDefaults.async_enabled,
    type=bool,
    show_default=True,
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
        [
            "hnsw",
            "flat",
            "hfresh",
            "hnsw_pq",
            "hnsw_bq",
            "hnsw_sq",
            "hnsw_rq",
            "flat_bq",
            "flat_rq",
            "hfresh_rq",
            "hnsw_acorn",
            "hnsw_pathseer",
        ]
    ),
    help="Vector index reconfiguration preset (supports PQ, BQ, SQ, RQ, ACORN, PathSeer, HFresh).",
)
@click.option(
    "--vector-name",
    default=None,
    type=str,
    help="Target named vector when using --vector-index or --filter-strategy.",
)
@click.option(
    "--rq-bits",
    default=None,
    type=int,
    help="Bit width for RQ quantizer (1, 4, or 8) when using *_rq.",
)
@click.option(
    "--filter-strategy",
    default=None,
    type=click.Choice(sorted(VALID_FILTER_STRATEGIES)),
    help="HNSW filter strategy (sweeping, acorn, pathseer).",
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
    show_default=True,
    help="Training limit for PQ and SQ.",
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
    show_default=True,
    help="Object TTL type. Use 'disable' to turn off TTL.",
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
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def update_collection_cli(
    ctx: click.Context,
    name: str,
    from_file: str | None,
    from_json: str | None,
    dry_run: bool,
    async_enabled: bool | None,
    replication_factor: int | None,
    vector_index: str | None,
    vector_name: str | None,
    rq_bits: int | None,
    filter_strategy: str | None,
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
    json_output: bool | None,
) -> None:
    """Update operational configuration for a collection (via flags or declarative JSON patch)."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "collection update"

    if from_file is not None and from_json is not None:
        emit_error(
            runtime,
            CLIError(
                code="CONFLICTING_OPTIONS",
                message="Cannot specify both --from-file and --from-json.",
                exit_code=ExitCode.USAGE,
            ),
            command=command,
        )

    using_json = from_file is not None or from_json is not None
    if dry_run and not using_json:
        emit_error(
            runtime,
            CLIError(
                code="INVALID_OPTIONS",
                message="--dry-run is only valid together with --from-file or --from-json.",
                exit_code=ExitCode.USAGE,
            ),
            command=command,
        )

    flag_overrides = (
        any(
            val is not None
            for val in (
                async_enabled,
                replication_factor,
                vector_index,
                vector_name,
                rq_bits,
                filter_strategy,
                description,
                auto_tenant_creation,
                auto_tenant_activation,
                replication_deletion_strategy,
                object_ttl_time,
                object_ttl_filter_expired,
                object_ttl_property_name,
            )
        )
        or bool(async_replication_config)
        or (object_ttl_type != UpdateCollectionDefaults.object_ttl_type)
        or (training_limit != UpdateCollectionDefaults.training_limit)
    )

    if using_json and flag_overrides:
        emit_error(
            runtime,
            CLIError(
                code="CONFLICTING_OPTIONS",
                message="Cannot combine --from-file/--from-json with individual update flags.",
                exit_code=ExitCode.USAGE,
                hint="Put all changes in the JSON patch or use flag options alone.",
            ),
            command=command,
        )

    client: WeaviateClient | None = None
    try:
        if using_json:
            raw_json, source = _read_schema_input(
                from_file, from_json, label="Collection update patch"
            )
            raw_spec = parse_json_object(
                raw_json,
                source=source,
                error_code="INVALID_UPDATE_SPEC",
                label="Collection update patch",
                hint='Pass a JSON object with mutable fields such as {"description": "...", "invertedIndexConfig": {...}}.',
            )
            prepared_spec, issues = validate_collection_update_spec(raw_spec)
            if issues:
                raise CLIError(
                    code="INVALID_UPDATE_SPEC",
                    message=f"Collection update patch validation failed with {len(issues)} issue(s).",
                    exit_code=ExitCode.USAGE,
                    issues=issues,
                )

            if dry_run:
                payload = {
                    "valid": True,
                    "dry_run": True,
                    "collection": name,
                    "patch": prepared_spec,
                }
                emit_success(
                    runtime,
                    payload,
                    command=command,
                    text_renderer=lambda: click.echo(
                        f"Update patch for collection '{name}' is valid (dry-run; not applied)."
                    ),
                )
                return

            client = get_client_from_context(ctx)
            collection_man = CollectionManager(client)
            available_modules = collection_man.get_available_modules()
            if available_modules is not None:
                _, live_issues = validate_collection_update_spec(
                    prepared_spec,
                    available_modules=available_modules,
                )
                if live_issues:
                    raise CLIError(
                        code="INVALID_UPDATE_SPEC",
                        message=(
                            f"Cluster compatibility validation failed with "
                            f"{len(live_issues)} issue(s)."
                        ),
                        exit_code=ExitCode.USAGE,
                        issues=live_issues,
                    )

            result = collection_man.update_collection_from_spec(name, prepared_spec)
        else:
            try:
                parsed_async_config = parse_async_replication_config(
                    async_replication_config
                )
            except ValueError as exc:
                raise CLIError(
                    code="INVALID_REPLICATION_CONFIG",
                    message=str(exc),
                    exit_code=ExitCode.USAGE,
                ) from exc

            client = get_client_from_context(ctx)
            collection_man = CollectionManager(client)
            result = collection_man.update_collection(
                collection=name,
                async_enabled=async_enabled,
                replication_factor=replication_factor,
                vector_index=vector_index,
                vector_name=vector_name,
                rq_bits=rq_bits,
                filter_strategy=filter_strategy,
                description=description,
                training_limit=training_limit,
                auto_tenant_creation=auto_tenant_creation,
                auto_tenant_activation=auto_tenant_activation,
                replication_deletion_strategy=replication_deletion_strategy,
                object_ttl_type=object_ttl_type,
                object_ttl_time=object_ttl_time,
                object_ttl_filter_expired=object_ttl_filter_expired,
                object_ttl_property_name=object_ttl_property_name,
                async_replication_config=parsed_async_config,
            )

        for warning in result.pop("warnings", ()):
            emit_warning(runtime, warning)

        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: click.echo(
                f"Collection '{name}' updated successfully."
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@collection_group.command("delete", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument(
    "name", required=False, default=None, shell_complete=collection_name_complete
)
@click.option(
    "--all",
    "delete_all",
    is_flag=True,
    default=False,
    help="Delete all collections (requires --yes).",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm destructive collection deletion (required).",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def delete_collection_cli(
    ctx: click.Context,
    name: str | None,
    delete_all: bool,
    yes: bool,
    json_output: bool | None,
) -> None:
    """Delete a collection or all collections (requires --yes)."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "collection delete"

    if delete_all and name:
        emit_error(
            runtime,
            CLIError(
                code="CONFLICTING_OPTIONS",
                message="Cannot specify both NAME and --all.",
                exit_code=ExitCode.USAGE,
            ),
            command=command,
        )
    if not delete_all and not name:
        emit_error(
            runtime,
            CLIError(
                code="MISSING_COLLECTION_NAME",
                message="Either NAME or --all must be specified.",
                exit_code=ExitCode.USAGE,
                hint="Example: 'weaviate-cli collection delete Articles --yes' or 'weaviate-cli collection delete --all --yes'.",
            ),
            command=command,
        )
    if not yes:
        target_label = "all collections" if delete_all else f"collection '{name}'"
        rerun_cmd = (
            "weaviate-cli collection delete --all --yes"
            if delete_all
            else f"weaviate-cli collection delete {name} --yes"
        )
        emit_error(
            runtime,
            CLIError(
                code="CONFIRMATION_REQUIRED",
                message=f"Deleting {target_label} is destructive and requires --yes.",
                exit_code=ExitCode.USAGE,
                hint=f"Re-run with '{rerun_cmd}' after confirming.",
            ),
            command=command,
        )

    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        collection_man = CollectionManager(client)
        result = collection_man.delete_collection(
            collection=name,
            delete_all=delete_all,
        )

        def _render_delete_text() -> None:
            if delete_all:
                click.echo(f"Deleted {result['count']} collection(s).")
            else:
                click.echo(f"Collection '{name}' deleted successfully.")

        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=_render_delete_text,
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()
