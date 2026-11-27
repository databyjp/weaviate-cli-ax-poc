import warnings


def configure_warning_filters() -> None:
    """Suppress noisy third-party/SDK warnings that would pollute stderr."""
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
    warnings.filterwarnings(
        "ignore",
        message=r"RBAC001: Unknown permission .*",
        category=UserWarning,
    )

    # authlib.deprecate calls warnings.simplefilter("always", AuthlibDeprecationWarning)
    # at import time; import it first so our ignore filter takes precedence before
    # weaviate imports authlib.integrations.httpx_client.
    try:
        from authlib.deprecate import AuthlibDeprecationWarning

        warnings.filterwarnings("ignore", category=AuthlibDeprecationWarning)
    except ImportError:
        pass


configure_warning_filters()

import click

from weaviate_cli import __version__
from weaviate_cli.commands.alias import alias_group
from weaviate_cli.commands.backup import backup_group
from weaviate_cli.commands.cloud import cloud_group
from weaviate_cli.commands.collection import collection_group
from weaviate_cli.commands.config import config_group
from weaviate_cli.commands.export import export_group
from weaviate_cli.commands.group import group_group
from weaviate_cli.commands.guide import guide_command
from weaviate_cli.commands.local import local_group
from weaviate_cli.commands.mcp import mcp_group
from weaviate_cli.commands.node import node_group
from weaviate_cli.commands.replication import replication_group
from weaviate_cli.commands.role import role_group
from weaviate_cli.commands.shard import shard_group
from weaviate_cli.commands.status import status_command
from weaviate_cli.commands.tenant import tenant_group
from weaviate_cli.commands.user import user_group
from weaviate_cli.errors import classify_exception
from weaviate_cli.managers.config_manager import ConfigManager
from weaviate_cli.runtime import (
    AXGroup,
    RuntimeContext,
    emit_error,
    resolve_json_output,
)

# Re-apply after imports because transitive dependencies (e.g. weaviate/google.protobuf)
# insert a global ('default', Warning) filter at index 0 during import.
configure_warning_filters()

ROOT_HELP = """Weaviate CLI for cluster lifecycle (local Docker & Weaviate Cloud), DDL, and admin.

Scope: manages local Docker clusters, Weaviate Cloud provisioning (via wcloud),
collections, tenants, aliases, nodes, shards, replication, backups, exports,
roles, and users. For querying or upserting object data, use Weaviate's native
MCP endpoint (/v1/mcp) or an SDK.

\b
Connection precedence (highest to lowest):
  1. CLI flags:    --url, --api-key, --grpc-url
  2. Env file:     --env-file <path>  (e.g. weaviate-cli --env-file .env collection list)
  3. Environment:  WEAVIATE_URL, WEAVIATE_API_KEY, WEAVIATE_GRPC_URL
  4. Config file:  --config-file <path>
  5. Default file: ~/.config/weaviate/config.json
  6. Fallback:     http://localhost:8080 (gRPC 50051)

\b
Output & exit codes:
  Structured JSON envelope (data/error/metadata) is enabled automatically when
  stdout is not a TTY; override with --json or --no-json.
  Exit codes: 0=ok, 1=runtime, 2=usage/validation, 3=auth/RBAC, 4=not-found/conflict, 5=connectivity.
  Tip: run 'weaviate-cli status' to inspect connectivity/modules, or 'weaviate-cli guide' for a full reference.
"""


def print_version(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(f"Weaviate CLI version {__version__}")
    ctx.exit()


@click.group(cls=AXGroup, help=ROOT_HELP)
@click.option(
    "--url",
    required=False,
    type=str,
    default=None,
    help="Weaviate REST endpoint URL (overrides WEAVIATE_URL).",
)
@click.option(
    "--api-key",
    required=False,
    type=str,
    default=None,
    help="Weaviate API key (overrides WEAVIATE_API_KEY).",
)
@click.option(
    "--grpc-url",
    required=False,
    type=str,
    default=None,
    help="Weaviate gRPC endpoint URL (overrides WEAVIATE_GRPC_URL).",
)
@click.option(
    "--env-file",
    required=False,
    type=click.Path(dir_okay=False),
    default=None,
    help="Load WEAVIATE_URL, WEAVIATE_API_KEY, and WEAVIATE_GRPC_URL from a .env file.",
)
@click.option(
    "--config-file",
    required=False,
    type=click.Path(exists=True),
    is_flag=False,
    help="Path to a JSON config file (default: ~/.config/weaviate/config.json).",
)
@click.option(
    "--user",
    required=False,
    type=str,
    help="User key inside the config file when auth.type is 'user'.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Emit data/error/metadata JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.option(
    "--version",
    is_flag=True,
    callback=print_version,
    expose_value=False,
    is_eager=True,
    help="Print the CLI version and exit.",
)
@click.pass_context
def main(
    ctx: click.Context,
    url: str | None,
    api_key: str | None,
    grpc_url: str | None,
    env_file: str | None,
    config_file: str | None,
    user: str | None,
    json_output: bool | None,
) -> None:
    runtime = RuntimeContext(json_output=resolve_json_output(json_output))
    try:
        config = ConfigManager(
            config_file=config_file,
            user=user,
            env_file=env_file,
            url=url,
            api_key=api_key,
            grpc_url=grpc_url,
        )
        ctx.obj = {"config": config, "runtime": runtime}
    except Exception as exc:
        emit_error(runtime, classify_exception(exc), command="weaviate-cli")


main.add_command(status_command)
main.add_command(guide_command)
main.add_command(config_group)
main.add_command(mcp_group)
main.add_command(local_group)
main.add_command(cloud_group)
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
main.add_command(group_group)

if __name__ == "__main__":
    main()
