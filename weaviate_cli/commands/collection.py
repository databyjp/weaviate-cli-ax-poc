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
    emit_error,
    emit_success,
    emit_warning,
    get_runtime,
    handle_command_error,
)
from weaviate_cli.specs.collection import (
    get_collection_template,
    parse_collection_json,
    validate_collection_spec,
)
from weaviate_cli.utils import (
    ASYNC_REPLICATION_CONFIG_HELP,
    get_client_from_context,
    parse_async_replication_config,
)


def _read_schema_input(from_file: str | None, from_json: str | None) -> tuple[str, str]:
    if from_file is not None:
        if from_file == "-":
            return sys.stdin.read(), "stdin"
        path = Path(from_file)
        if not path.is_file():
            raise CLIError(
                code="FILE_NOT_FOUND",
                message=f"Schema file '{from_file}' does not exist or is not a file.",
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


@click.group("collection", context_settings=DEFAULT_CONTEXT_SETTINGS)
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


@collection_group.command("update", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("name", shell_complete=collection_name_complete)
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
    json_output: bool | None,
) -> None:
    """Update operational configuration for a collection."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "collection update"
    client: WeaviateClient | None = None
    try:
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
    help="Confirm destructive bulk deletion (required with --all).",
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
    """Delete a collection (or all collections with --all --yes)."""
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
                hint="Example: 'weaviate-cli collection delete Articles' or 'weaviate-cli collection delete --all --yes'.",
            ),
            command=command,
        )
    if delete_all and not yes:
        emit_error(
            runtime,
            CLIError(
                code="CONFIRMATION_REQUIRED",
                message="Deleting all collections is destructive and requires --yes.",
                exit_code=ExitCode.USAGE,
                hint="Re-run with 'weaviate-cli collection delete --all --yes' after confirming.",
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
