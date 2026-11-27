"""Click commands for the 'alias' resource group."""

from __future__ import annotations

import click
from weaviate import WeaviateClient

from weaviate_cli.completion.complete import collection_name_complete
from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.managers.alias_manager import AliasManager
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    emit_captured_json_or_text,
    emit_success,
    get_runtime,
    handle_command_error,
)
from weaviate_cli.utils import get_client_from_context


@click.group("alias", context_settings=DEFAULT_CONTEXT_SETTINGS)
def alias_group() -> None:
    """Manage collection aliases in Weaviate."""


@alias_group.command("create", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("alias_name")
@click.argument("collection", shell_complete=collection_name_complete)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def create_alias_cli(
    ctx: click.Context, alias_name: str, collection: str, json_output: bool | None
) -> None:
    """Create an alias pointing to a collection."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "alias create"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        alias_man = AliasManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: alias_man.create_alias(
                alias_name=alias_name, collection=collection, json_output=as_json
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@alias_group.command("list", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option(
    "--collection",
    default=None,
    help="Filter aliases by collection name.",
    shell_complete=collection_name_complete,
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def list_aliases_cli(
    ctx: click.Context, collection: str | None, json_output: bool | None
) -> None:
    """List all aliases, or aliases for a specific collection."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "alias list"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        alias_man = AliasManager(client)
        aliases = (
            alias_man.list_aliases(collection=collection)
            if collection
            else alias_man.list_aliases()
        )
        aliases_data = [
            {"alias": a.alias, "collection": a.collection} for a in aliases.values()
        ]
        payload: dict[str, object] = (
            {"collection": collection, "aliases": aliases_data}
            if collection
            else {"aliases": aliases_data}
        )

        def _render_text() -> None:
            separator = "-" * 50
            if collection:
                click.echo(f"Aliases for collection '{collection}'")
                click.echo(f"\n{separator}")
                if not aliases:
                    click.echo(f"No aliases found for collection '{collection}'.")
                    return
            else:
                click.echo("Aliases")
                click.echo(f"\n{separator}")
                if not aliases:
                    click.echo("No aliases found.")
                    return
            for alias in aliases.values():
                alias_man.print_alias(alias)
                click.echo(f"\n{separator}")

        emit_success(runtime, payload, command=command, text_renderer=_render_text)
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@alias_group.command("get", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("alias_name")
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def get_alias_cli(
    ctx: click.Context, alias_name: str, json_output: bool | None
) -> None:
    """Get details for a specific alias."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "alias get"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        alias_man = AliasManager(client)
        alias = alias_man.get_alias(alias_name=alias_name)
        if alias is None:
            raise CLIError(
                code="ALIAS_NOT_FOUND",
                message=f"Alias '{alias_name}' not found.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Run 'weaviate-cli alias list' to see existing aliases.",
            )

        def _render_text() -> None:
            separator = "-" * 50
            click.echo(f"Alias '{alias_name}'")
            click.echo(f"\n{separator}")
            alias_man.print_alias(alias, json_output=False)
            click.echo(f"\n{separator}")

        emit_success(
            runtime,
            {"alias": alias.alias, "collection": alias.collection},
            command=command,
            text_renderer=_render_text,
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@alias_group.command("update", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("alias_name")
@click.argument("collection", shell_complete=collection_name_complete)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def update_alias_cli(
    ctx: click.Context, alias_name: str, collection: str, json_output: bool | None
) -> None:
    """Repoint an existing alias to a collection."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "alias update"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        alias_man = AliasManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: alias_man.update_alias(
                alias_name=alias_name, collection=collection, json_output=as_json
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()


@alias_group.command("delete", context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("alias_name")
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def delete_alias_cli(
    ctx: click.Context, alias_name: str, json_output: bool | None
) -> None:
    """Delete a collection alias."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "alias delete"
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        alias_man = AliasManager(client)
        emit_captured_json_or_text(
            runtime,
            command=command,
            invoke=lambda as_json: alias_man.delete_alias(
                alias_name=alias_name, json_output=as_json
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()
