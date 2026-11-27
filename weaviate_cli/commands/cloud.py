"""Click commands for Weaviate Cloud lifecycle delegated to `wcloud` (`weaviate-cli cloud`)."""

from __future__ import annotations

import sys
from typing import Any

import click

from weaviate_cli.managers.cloud_manager import (
    WCLOUD_VERSION,
    CloudManager,
    extract_cluster_credentials,
)
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    AXGroup,
    RuntimeContext,
    emit_success,
    emit_warning,
    get_runtime,
    handle_command_error,
)


def _make_manager(runtime: RuntimeContext) -> CloudManager:
    interactive = sys.stdin.isatty() and sys.stdout.isatty() and not runtime.json_output
    return CloudManager(
        is_interactive=interactive,
        prompt_fn=(lambda msg: click.confirm(msg, default=False))
        if interactive
        else None,
        progress_callback=lambda msg: click.echo(msg, err=True),
    )


def _render_cluster_text(data: dict[str, Any]) -> None:
    click.echo(f"ID:       {data.get('id', 'unknown')}")
    if data.get("name"):
        click.echo(f"Name:     {data['name']}")
    if data.get("status"):
        click.echo(f"Status:   {data['status']}")
    if data.get("tier"):
        click.echo(f"Tier:     {data['tier']}")
    if data.get("region"):
        click.echo(f"Region:   {data['region']}")
    url, grpc_url, api_key = extract_cluster_credentials(data)
    if url:
        click.echo(f"URL:      {url}")
    if grpc_url:
        click.echo(f"gRPC URL: {grpc_url}")
    if api_key:
        click.echo(f"API Key:  {api_key}")
    saved = data.get("credentials_saved_to") or []
    if saved:
        click.echo(f"Saved to: {', '.join(saved)}")
    if data.get("one_time_api_key_notice"):
        click.echo(f"\nNotice: {data['one_time_api_key_notice']}")
    if data.get("next_step"):
        click.echo(f"Next:   {data['next_step']}")


def _render_clusters_text(data: dict[str, Any]) -> None:
    clusters = data.get("clusters") or []
    if not clusters:
        click.echo("No Weaviate Cloud clusters found.")
        return
    for cluster in clusters:
        click.echo(
            f"- {cluster.get('id')}  {cluster.get('name', '')}  "
            f"[{cluster.get('status', 'UNKNOWN')}]  "
            f"region={cluster.get('region', '')}  tier={cluster.get('tier', '')}"
        )


def _render_regions_text(data: dict[str, Any]) -> None:
    regions = data.get("regions") or []
    if not regions:
        click.echo("No regions available.")
        return
    for region in regions:
        default_tag = " (default)" if region.get("is_default") else ""
        click.echo(
            f"- {region.get('id')}{default_tag}: {region.get('name', '')} "
            f"({region.get('cloud_provider', '')}, {region.get('status', '')})"
        )


def _render_whoami_text(data: dict[str, Any]) -> None:
    if data.get("email"):
        click.echo(f"Email:   {data['email']}")
    if data.get("user_id"):
        click.echo(f"User ID: {data['user_id']}")
    if data.get("org_id"):
        click.echo(f"Org ID:  {data['org_id']}")
    if data.get("wcloud_path"):
        click.echo(
            f"wcloud:  {data['wcloud_path']} (source: {data.get('wcloud_source', 'unknown')})"
        )


def _render_install_text(data: dict[str, Any]) -> None:
    if data.get("already_installed"):
        click.echo(f"wcloud v{data['version']} is already installed at {data['path']}.")
    else:
        click.echo(
            f"Installed wcloud v{data['version']} ({data['platform']}) to {data['path']} "
            f"(SHA-256 verified)."
        )


@click.group("cloud", cls=AXGroup)
def cloud_group() -> None:
    """Manage Weaviate Cloud clusters via `wcloud` (auth, regions, create, list, get, status)."""


@cloud_group.command(
    "install-wcloud",
    help=f"Download and SHA-256 verify the pinned wcloud v{WCLOUD_VERSION} binary.",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli cloud install-wcloud\n"
        "  weaviate-cli cloud install-wcloud --force"
    ),
)
@click.option(
    "--dir",
    "install_dir",
    type=click.Path(file_okay=False),
    default=None,
    help="Target directory for the wcloud binary (default: ~/.cache/weaviate-cli/bin).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Re-download and overwrite an existing cached wcloud binary.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def cloud_install_wcloud(
    ctx: click.Context,
    install_dir: str | None,
    force: bool,
    json_output: bool | None,
) -> None:
    runtime = get_runtime(ctx, json_override=json_output)
    command = "cloud install-wcloud"
    try:
        manager = _make_manager(runtime)
        result = manager.install_wcloud(install_dir=install_dir, force=force)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: _render_install_text(result),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)


@cloud_group.command(
    "login",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Requires an interactive terminal with a local browser (127.0.0.1 OAuth loopback).\n"
        "Examples:\n"
        "  weaviate-cli cloud login\n"
        "  weaviate-cli cloud login --no-launch-browser"
    ),
)
@click.option(
    "--no-launch-browser",
    is_flag=True,
    default=False,
    help="Print the OAuth sign-in URL instead of opening a browser automatically.",
)
@click.option(
    "--timeout",
    type=str,
    default=None,
    help="Maximum wait duration for browser sign-in (e.g. '5m').",
)
@click.option(
    "--install-wcloud",
    is_flag=True,
    default=False,
    help="Download and install pinned wcloud (SHA-256 verified) if not found.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def cloud_login(
    ctx: click.Context,
    no_launch_browser: bool,
    timeout: str | None,
    install_wcloud: bool,
    json_output: bool | None,
) -> None:
    """Authenticate with Weaviate Cloud via browser OAuth 2.0 PKCE."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "cloud login"
    try:
        manager = _make_manager(runtime)
        result = manager.login(
            no_launch_browser=no_launch_browser,
            timeout=timeout,
            allow_install=install_wcloud,
        )
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: click.echo("Logged in to Weaviate Cloud."),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)


@cloud_group.command(
    "whoami",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog="\b\nExamples:\n  weaviate-cli cloud whoami",
)
@click.option(
    "--install-wcloud",
    is_flag=True,
    default=False,
    help="Download and install pinned wcloud (SHA-256 verified) if not found.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def cloud_whoami(
    ctx: click.Context, install_wcloud: bool, json_output: bool | None
) -> None:
    """Show the current authenticated Weaviate Cloud identity."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "cloud whoami"
    try:
        manager = _make_manager(runtime)
        result = manager.whoami(allow_install=install_wcloud)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: _render_whoami_text(result),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)


@cloud_group.command(
    "logout",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog="\b\nExamples:\n  weaviate-cli cloud logout",
)
@click.option(
    "--install-wcloud",
    is_flag=True,
    default=False,
    help="Download and install pinned wcloud (SHA-256 verified) if not found.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def cloud_logout(
    ctx: click.Context, install_wcloud: bool, json_output: bool | None
) -> None:
    """Revoke and forget local Weaviate Cloud credentials."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "cloud logout"
    try:
        manager = _make_manager(runtime)
        result = manager.logout(allow_install=install_wcloud)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: click.echo("Logged out of Weaviate Cloud."),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)


@cloud_group.command(
    "regions",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog="\b\nExamples:\n  weaviate-cli cloud regions",
)
@click.option(
    "--install-wcloud",
    is_flag=True,
    default=False,
    help="Download and install pinned wcloud (SHA-256 verified) if not found.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def cloud_regions(
    ctx: click.Context, install_wcloud: bool, json_output: bool | None
) -> None:
    """List available Weaviate Cloud regions."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "cloud regions"
    try:
        manager = _make_manager(runtime)
        result = manager.list_regions(allow_install=install_wcloud)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: _render_regions_text(result),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)


@cloud_group.command(
    "create",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "IMPORTANT — One-time admin API key:\n"
        "  Weaviate Cloud returns the cluster's admin API key ONCE when the cluster\n"
        "  reaches READY (via --wait, or on the first 'cloud get <id>'). Neither\n"
        "  wcloud nor weaviate-cli stores it automatically. Pass --write-env to a\n"
        "  durable, gitignored path such as '.env' (or '.env.<name>' + .gitignore\n"
        "  if '.env' already exists) or ~/.config/weaviate/<name>.json — avoid\n"
        "  disposable directories like '.venv/'.\n"
        "\b\n"
        "Examples:\n"
        "  weaviate-cli cloud create --name demo --region eu-central-1 --wait --write-env .env\n"
        "  weaviate-cli cloud create --name demo\n"
        "  weaviate-cli cloud get <cluster-id> --write-env .env"
    ),
)
@click.option(
    "--name", type=str, default=None, help="Cluster name (auto-generated if omitted)."
)
@click.option(
    "--region",
    type=str,
    default=None,
    help="Region ID from 'weaviate-cli cloud regions' (default: eu-central-1).",
)
@click.option("--tier", type=str, default=None, help="Cluster tier (default: free).")
@click.option(
    "--wait",
    is_flag=True,
    default=False,
    help="Block until the cluster is READY and return its endpoint and one-time admin API key.",
)
@click.option(
    "--timeout",
    type=str,
    default=None,
    help="Maximum wait time for READY (e.g. '15m'; requires --wait).",
)
@click.option(
    "--write-env",
    "write_env",
    type=click.Path(dir_okay=False),
    default=None,
    help="Write WEAVIATE_URL and the one-time WEAVIATE_API_KEY to a .env file (mode 0600; requires --wait).",
)
@click.option(
    "--write-config",
    "write_config",
    type=click.Path(dir_okay=False),
    default=None,
    help="Write cluster URL and one-time API key to a JSON config file (mode 0600; requires --wait).",
)
@click.option(
    "--install-wcloud",
    is_flag=True,
    default=False,
    help="Download and install pinned wcloud (SHA-256 verified) if not found.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def cloud_create(
    ctx: click.Context,
    name: str | None,
    region: str | None,
    tier: str | None,
    wait: bool,
    timeout: str | None,
    write_env: str | None,
    write_config: str | None,
    install_wcloud: bool,
    json_output: bool | None,
) -> None:
    """Create a Weaviate Cloud cluster (use --wait --write-env .env to capture the one-time key)."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "cloud create"
    try:
        manager = _make_manager(runtime)
        result = manager.create_cluster(
            name=name,
            region=region,
            tier=tier,
            wait=wait,
            timeout=timeout,
            write_env=write_env,
            write_config=write_config,
            allow_install=install_wcloud,
        )
        for warning in result.pop("warnings", ()):
            emit_warning(runtime, warning)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: _render_cluster_text(result),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)


@cloud_group.command(
    "list",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog="\b\nExamples:\n  weaviate-cli cloud list",
)
@click.option(
    "--install-wcloud",
    is_flag=True,
    default=False,
    help="Download and install pinned wcloud (SHA-256 verified) if not found.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def cloud_list(
    ctx: click.Context, install_wcloud: bool, json_output: bool | None
) -> None:
    """List Weaviate Cloud clusters in your organization."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "cloud list"
    try:
        manager = _make_manager(runtime)
        result = manager.list_clusters(allow_install=install_wcloud)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: _render_clusters_text(result),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)


@cloud_group.command(
    "get",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "IMPORTANT — One-time admin API key:\n"
        "  When a cluster was created without --wait, the first 'cloud get <id>'\n"
        "  after READY returns the one-time admin API key. Pass --write-env to a\n"
        "  durable, gitignored path such as '.env' (or '.env.<name>' + .gitignore)\n"
        "  — avoid disposable directories like '.venv/'.\n"
        "\b\n"
        "Examples:\n"
        "  weaviate-cli cloud get <cluster-id>\n"
        "  weaviate-cli cloud get <cluster-id> --write-env .env"
    ),
)
@click.argument("cluster_id")
@click.option(
    "--write-env",
    "write_env",
    type=click.Path(dir_okay=False),
    default=None,
    help="If a one-time API key is returned, write WEAVIATE_URL and WEAVIATE_API_KEY to a .env file (mode 0600).",
)
@click.option(
    "--write-config",
    "write_config",
    type=click.Path(dir_okay=False),
    default=None,
    help="If a one-time API key is returned, write credentials to a JSON config file (mode 0600).",
)
@click.option(
    "--install-wcloud",
    is_flag=True,
    default=False,
    help="Download and install pinned wcloud (SHA-256 verified) if not found.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def cloud_get(
    ctx: click.Context,
    cluster_id: str,
    write_env: str | None,
    write_config: str | None,
    install_wcloud: bool,
    json_output: bool | None,
) -> None:
    """Fetch details for a Weaviate Cloud cluster (including one-time API key on first READY read)."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "cloud get"
    try:
        manager = _make_manager(runtime)
        result = manager.get_cluster(
            cluster_id,
            write_env=write_env,
            write_config=write_config,
            allow_install=install_wcloud,
        )
        for warning in result.pop("warnings", ()):
            emit_warning(runtime, warning)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: _render_cluster_text(result),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)


@cloud_group.command(
    "status",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog="\b\nExamples:\n  weaviate-cli cloud status <cluster-id>",
)
@click.argument("cluster_id")
@click.option(
    "--install-wcloud",
    is_flag=True,
    default=False,
    help="Download and install pinned wcloud (SHA-256 verified) if not found.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def cloud_status(
    ctx: click.Context,
    cluster_id: str,
    install_wcloud: bool,
    json_output: bool | None,
) -> None:
    """Check the provisioning lifecycle status of a Weaviate Cloud cluster."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "cloud status"
    try:
        manager = _make_manager(runtime)
        result = manager.cluster_status(cluster_id, allow_install=install_wcloud)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: click.echo(
                f"Cluster {result.get('id')}: {result.get('status')}"
            ),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
