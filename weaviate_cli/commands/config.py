"""Click commands for inspecting resolved CLI target configuration (`weaviate-cli config`)."""

from __future__ import annotations

from typing import Any

import click

from weaviate_cli.managers.config_manager import ConfigManager
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    AXGroup,
    emit_success,
    get_runtime,
    handle_command_error,
)


def _render_config_show_text(data: dict[str, Any]) -> None:
    click.echo(f"Target:          {data['target']}")
    click.echo(f"Source:          {data['source']}")
    click.echo(f"REST URL:        {data['rest_url']}")
    grpc = data.get("grpc") or {}
    grpc_scheme = "grpcs" if grpc.get("secure") else "grpc"
    click.echo(
        f"gRPC endpoint:   {grpc_scheme}://{grpc.get('host')}:{grpc.get('port')}"
    )
    click.echo(f"MCP endpoint:    {data['mcp_endpoint']}")

    if data.get("env_file"):
        click.echo(f"Env file:        {data['env_file']}")
    if data.get("config_file"):
        click.echo(f"Config file:     {data['config_file']}")

    auth = data.get("auth") or {}
    if auth.get("configured"):
        auth_desc = f"{auth.get('type')} ({auth.get('api_key')})"
        if auth.get("user"):
            auth_desc += f" [user: {auth['user']}]"
    elif auth.get("type") == "user":
        users = ", ".join(auth.get("available_users") or []) or "none"
        auth_desc = f"user (pass --user <name>; configured: {users})"
    else:
        auth_desc = "none"
    click.echo(f"Auth:            {auth_desc}")

    headers = data.get("header_names") or []
    if headers:
        click.echo(f"Custom headers:  {', '.join(headers)} (values redacted)")
    if data.get("slow_connection"):
        click.echo("Slow connection: enabled (2x timeouts)")

    click.echo(
        "Tip: run 'weaviate-cli status' to verify live connectivity and modules."
    )


@click.group(
    "config",
    cls=AXGroup,
    help=(
        "Inspect resolved Weaviate connection configuration.\n\n"
        "Switch targets with --url/--api-key, --env-file <path>, WEAVIATE_URL/WEAVIATE_API_KEY, "
        "or --config-file <path>. Run 'weaviate-cli status' to verify live connectivity."
    ),
)
def config_group() -> None:
    pass


@config_group.command(
    "show",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli config show\n"
        "  weaviate-cli --env-file .env config show\n"
        "  weaviate-cli --url https://demo.weaviate.cloud --api-key $KEY config show"
    ),
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def config_show(ctx: click.Context, json_output: bool | None) -> None:
    """Show the resolved target URL, gRPC endpoint, precedence source, and redacted auth status."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "config show"
    try:
        config: ConfigManager = ctx.obj["config"]
        result = config.describe_connection()
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: _render_config_show_text(result),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
