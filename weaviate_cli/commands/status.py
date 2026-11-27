"""Click command for `weaviate-cli status`."""

from __future__ import annotations

from typing import Any

import click
from weaviate import WeaviateClient

from weaviate_cli.managers.status_manager import StatusManager
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    emit_success,
    emit_warning,
    get_runtime,
    handle_command_error,
)
from weaviate_cli.utils import get_client_from_context


def _render_status_text(status: dict[str, Any]) -> None:
    click.echo(f"Target:      {status['target']} (source: {status['config_source']})")
    click.echo(
        f"Health:      live={status['live']}, ready={status['ready']}, "
        f"version={status['version'] or 'unknown'}"
    )

    user = status.get("user")
    if isinstance(user, dict) and user.get("user_id"):
        roles = ", ".join(user.get("roles") or []) or "none"
        click.echo(f"User:        {user['user_id']} (roles: {roles})")

    cols = status.get("collections")
    if isinstance(cols, dict):
        if cols.get("accessible"):
            names = cols.get("names") or []
            preview = ", ".join(names[:10])
            if len(names) > 10:
                preview += f", ... (+{len(names) - 10} more)"
            suffix = f" ({preview})" if preview else ""
            click.echo(f"Collections: {cols['count']}{suffix}")
        else:
            click.echo(f"Collections: unavailable ({cols.get('error', 'forbidden')})")

    nodes = status.get("nodes")
    if isinstance(nodes, dict):
        if nodes.get("accessible"):
            click.echo(f"Nodes:       {nodes['healthy']}/{nodes['count']} healthy")
        else:
            click.echo(f"Nodes:       unavailable ({nodes.get('error', 'forbidden')})")

    vectorizers = status.get("vectorizers") or []
    vec_label = ", ".join(vectorizers) if vectorizers else 'none (use "none" for BYOV)'
    click.echo(f"Vectorizers: {vec_label}")

    modules = status.get("modules") or []
    click.echo(f"Modules:     {len(modules)} enabled")

    mcp = status.get("mcp")
    if isinstance(mcp, dict):
        avail = mcp.get("available")
        state = (
            "available"
            if avail is True
            else "not enabled"
            if avail is False
            else "unknown"
        )
        write_enabled = mcp.get("write_enabled")
        if avail is True and isinstance(write_enabled, bool):
            state += " (read+write)" if write_enabled else " (read-only)"
        click.echo(f"Native MCP:  {state} ({mcp.get('endpoint')})")


@click.command(
    "status",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli status\n"
        "  weaviate-cli --env-file .env status\n"
        "  weaviate-cli --url https://demo.weaviate.cloud --api-key $KEY status"
    ),
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def status_command(ctx: click.Context, json_output: bool | None) -> None:
    """Inspect cluster connectivity, health, identity, enabled modules, and /v1/mcp."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "status"
    client: WeaviateClient | None = None
    try:
        config = ctx.obj["config"]
        client = get_client_from_context(ctx)
        manager = StatusManager(
            client,
            target=config.target_description,
            config_source=config.source,
            rest_base_url=config.rest_base_url,
            api_key=config.get_api_key(),
        )
        result = manager.get_status()
        for warning in result.pop("warnings", ()):
            emit_warning(runtime, warning)

        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: _render_status_text(result),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
    finally:
        if client is not None:
            client.close()
