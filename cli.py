import warnings

warnings.filterwarnings(
    "ignore", message="pkg_resources is deprecated as an API.", category=UserWarning
)
warnings.filterwarnings(
    "ignore",
    message=(
        r"Protobuf gencode version [\d\.]+ is exactly one major version older than the runtime version [\d\.]+ at v1/tenants\.proto\. "
        r"Please update the gencode to avoid compatibility violations in the next runtime release\."
    ),
    category=UserWarning,
)

import sys

import click

from weaviate_cli import __version__
from weaviate_cli.commands.alias import alias_group
from weaviate_cli.commands.backup import backup_group
from weaviate_cli.commands.collection import collection_group
from weaviate_cli.commands.export import export_group
from weaviate_cli.commands.node import node_group
from weaviate_cli.commands.replication import replication_group
from weaviate_cli.commands.role import role_group
from weaviate_cli.commands.shard import shard_group
from weaviate_cli.commands.tenant import tenant_group
from weaviate_cli.commands.user import user_group
from weaviate_cli.managers.config_manager import ConfigManager


def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo(f"Weaviate CLI version {__version__}")
    ctx.exit()


@click.group()
@click.option(
    "--config-file",
    required=False,
    type=click.Path(exists=True),
    is_flag=False,
    help="If specified cli uses the config specified with this path.",
)
@click.option(
    "--user",
    required=False,
    type=str,
    help="If specified cli uses the user specified in the config file.",
)
@click.option(
    "--version",
    is_flag=True,
    callback=print_version,
    expose_value=False,
    is_eager=True,
    help="Prints the version of the CLI.",
)
@click.pass_context
def main(ctx: click.Context, config_file: str | None, user: str | None):
    """Weaviate CLI tool"""
    try:
        ctx.obj = {"config": ConfigManager(config_file, user)}
    except Exception as e:
        click.echo(f"Fatal Error: {e}")
        sys.exit(1)


main.add_command(collection_group)
main.add_command(tenant_group)
main.add_command(alias_group)
main.add_command(node_group)
main.add_command(shard_group)
main.add_command(replication_group)
main.add_command(backup_group)
main.add_command(export_group)
main.add_command(role_group)
main.add_command(user_group)

if __name__ == "__main__":
    main()
