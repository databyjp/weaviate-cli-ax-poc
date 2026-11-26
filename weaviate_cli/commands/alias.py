import json
import sys

import click
from weaviate import WeaviateClient

from weaviate_cli.completion.complete import collection_name_complete
from weaviate_cli.managers.alias_manager import AliasManager
from weaviate_cli.utils import get_client_from_context


@click.group("alias")
def alias_group() -> None:
    """Manage collection aliases in Weaviate."""


@alias_group.command("create")
@click.argument("alias_name")
@click.argument("collection", shell_complete=collection_name_complete)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def create_alias_cli(
    ctx: click.Context, alias_name: str, collection: str, json_output: bool
) -> None:
    """Create an alias pointing to a collection."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        alias_man = AliasManager(client)
        alias_man.create_alias(
            alias_name=alias_name, collection=collection, json_output=json_output
        )
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@alias_group.command("list")
@click.option(
    "--collection",
    default=None,
    help="Filter aliases by collection name.",
    shell_complete=collection_name_complete,
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def list_aliases_cli(
    ctx: click.Context, collection: str | None, json_output: bool
) -> None:
    """List all aliases, or aliases for a specific collection."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        alias_man = AliasManager(client)
        if collection:
            aliases = alias_man.list_aliases(collection=collection)
            if json_output:
                aliases_data = [
                    {"alias": a.alias, "collection": a.collection}
                    for a in aliases.values()
                ]
                click.echo(
                    json.dumps(
                        {"collection": collection, "aliases": aliases_data},
                        indent=2,
                        default=str,
                    )
                )
            else:
                click.echo(f"Aliases for collection '{collection}'")
                separator = "-" * 50
                click.echo(f"\n{separator}")
                if len(aliases) == 0:
                    click.echo(f"No aliases found for collection '{collection}'.")
                else:
                    for alias in aliases.values():
                        alias_man.print_alias(alias)
                        click.echo(f"\n{separator}")
        else:
            aliases = alias_man.list_aliases()
            if json_output:
                aliases_data = [
                    {"alias": a.alias, "collection": a.collection}
                    for a in aliases.values()
                ]
                click.echo(json.dumps({"aliases": aliases_data}, indent=2, default=str))
            else:
                click.echo("Aliases")
                separator = "-" * 50
                click.echo(f"\n{separator}")
                if len(aliases) == 0:
                    click.echo("No aliases found.")
                else:
                    for alias in aliases.values():
                        alias_man.print_alias(alias)
                        click.echo(f"\n{separator}")
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@alias_group.command("get")
@click.argument("alias_name")
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def get_alias_cli(ctx: click.Context, alias_name: str, json_output: bool) -> None:
    """Get details for a specific alias."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        alias_man = AliasManager(client)
        alias = alias_man.get_alias(alias_name=alias_name)
        if alias:
            if not json_output:
                separator = "-" * 50
                click.echo(f"Alias '{alias_name}'")
                click.echo(f"\n{separator}")
            alias_man.print_alias(alias, json_output=json_output)
            if not json_output:
                click.echo(f"\n{separator}")
        else:
            click.echo(f"Alias '{alias_name}' not found.")
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@alias_group.command("update")
@click.argument("alias_name")
@click.argument("collection", shell_complete=collection_name_complete)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def update_alias_cli(
    ctx: click.Context, alias_name: str, collection: str, json_output: bool
) -> None:
    """Repoint an existing alias to a collection."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        alias_man = AliasManager(client)
        alias_man.update_alias(
            alias_name=alias_name, collection=collection, json_output=json_output
        )
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()


@alias_group.command("delete")
@click.argument("alias_name")
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output in JSON format."
)
@click.pass_context
def delete_alias_cli(ctx: click.Context, alias_name: str, json_output: bool) -> None:
    """Delete a collection alias."""
    client: WeaviateClient | None = None
    try:
        client = get_client_from_context(ctx)
        alias_man = AliasManager(client)
        alias_man.delete_alias(alias_name=alias_name, json_output=json_output)
    except Exception as e:
        click.echo(f"Error: {e}")
        if client:
            client.close()
        sys.exit(1)
    finally:
        if client:
            client.close()
