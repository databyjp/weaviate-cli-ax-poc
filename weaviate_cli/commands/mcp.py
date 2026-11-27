"""Click commands for generating native Weaviate MCP (/v1/mcp) client configuration."""

from __future__ import annotations

import json
import shlex
from typing import Any, Literal, cast

import click

from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.managers.config_manager import ConfigManager
from weaviate_cli.managers.status_manager import McpProbeFn, probe_mcp_endpoint
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    AXGroup,
    emit_success,
    emit_warning,
    get_runtime,
    handle_command_error,
)

McpClientFormat = Literal["generic", "claude-code", "cursor", "vscode"]

_CONFIG_FILE_HINTS: dict[McpClientFormat, str] = {
    "generic": "mcp.json",
    "claude-code": ".mcp.json",
    "cursor": ".cursor/mcp.json",
    "vscode": ".vscode/mcp.json",
}


def build_mcp_config(
    *,
    rest_base_url: str,
    api_key: str | None = None,
    client: McpClientFormat = "generic",
    server_name: str = "weaviate",
    include_key: bool = False,
) -> dict[str, Any]:
    """Build a ready-to-use Streamable HTTP MCP client config snippet for /v1/mcp."""
    cleaned_name = server_name.strip()
    if not cleaned_name:
        raise CLIError(
            code="INVALID_SERVER_NAME",
            message="--server-name must be a non-empty string.",
            exit_code=ExitCode.USAGE,
        )

    endpoint = f"{rest_base_url.rstrip('/')}/v1/mcp"

    auth_header_value: str | None = None
    auth_mode: str = "none"
    if api_key:
        if include_key:
            auth_header_value = f"Bearer {api_key}"
            auth_mode = "inline_key"
        elif client == "vscode":
            auth_header_value = "Bearer ${env:WEAVIATE_API_KEY}"
            auth_mode = "env_placeholder"
        else:
            auth_header_value = "Bearer ${WEAVIATE_API_KEY}"
            auth_mode = "env_placeholder"

    server_entry: dict[str, Any] = {"url": endpoint}
    if client in {"generic", "claude-code", "vscode"}:
        server_entry = {"type": "http", "url": endpoint}
    if auth_header_value is not None:
        server_entry["headers"] = {"Authorization": auth_header_value}

    if client == "vscode":
        config_snippet: dict[str, Any] = {"servers": {cleaned_name: server_entry}}
    else:
        config_snippet = {"mcpServers": {cleaned_name: server_entry}}

    cli_command: str | None = None
    if client == "claude-code":
        parts = [
            "claude",
            "mcp",
            "add",
            "--transport",
            "http",
            shlex.quote(cleaned_name),
            shlex.quote(endpoint),
        ]
        if auth_header_value is not None:
            if include_key:
                parts.extend(
                    ["--header", shlex.quote(f"Authorization: {auth_header_value}")]
                )
            else:
                # Double-quoted so the user's shell expands ${WEAVIATE_API_KEY}.
                parts.extend(
                    ["--header", '"Authorization: Bearer ${WEAVIATE_API_KEY}"']
                )
        cli_command = " ".join(parts)

    return {
        "client": client,
        "server_name": cleaned_name,
        "endpoint": endpoint,
        "transport": "streamable-http",
        "config_file_hint": _CONFIG_FILE_HINTS[client],
        "auth_mode": auth_mode,
        "config": config_snippet,
        "cli_command": cli_command,
    }


def _render_mcp_config_text(data: dict[str, Any]) -> None:
    click.echo(json.dumps(data["config"], indent=2))
    click.echo("")
    click.echo(f"Endpoint:    {data['endpoint']} (transport: {data['transport']})")
    click.echo(f"Target file: {data['config_file_hint']} (client: {data['client']})")
    if data.get("auth_mode") == "env_placeholder":
        click.echo(
            "Auth:        references WEAVIATE_API_KEY env var (pass --include-key to inline the literal key)"
        )
    elif data.get("auth_mode") == "inline_key":
        click.echo("Auth:        literal API key embedded (--include-key)")
    else:
        click.echo(
            "Auth:        none configured (set WEAVIATE_API_KEY or --env-file if your cluster requires auth)"
        )
    if data.get("cli_command"):
        click.echo(f"CLI command: {data['cli_command']}")
    probe = data.get("probe")
    if isinstance(probe, dict):
        avail = probe.get("available")
        state = "reachable" if avail is True else "unavailable"
        if probe.get("auth_required"):
            state += " (auth required)"
        click.echo(f"Live probe:  {state}")


@click.group(
    "mcp",
    cls=AXGroup,
    help=(
        "Configure coding-agent clients for Weaviate's native /v1/mcp server.\n\n"
        "Weaviate v1.37.1+ serves Streamable HTTP MCP directly at <WEAVIATE_URL>/v1/mcp "
        "(enabled by default on Weaviate Cloud and via 'weaviate-cli local start')."
    ),
)
def mcp_group() -> None:
    pass


@mcp_group.command(
    "config",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli mcp config\n"
        "  weaviate-cli --env-file .env mcp config --client claude-code\n"
        "  weaviate-cli --env-file .env mcp config --client cursor --check\n"
        "  weaviate-cli --env-file .env mcp config --client vscode --include-key"
    ),
)
@click.option(
    "--client",
    "client_format",
    type=click.Choice(
        ["generic", "claude-code", "cursor", "vscode"], case_sensitive=False
    ),
    default="generic",
    show_default=True,
    help="Target MCP client configuration format.",
)
@click.option(
    "--server-name",
    default="weaviate",
    show_default=True,
    type=str,
    help="Server entry name in the generated MCP config.",
)
@click.option(
    "--include-key",
    is_flag=True,
    default=False,
    help="Embed the literal API key instead of an env-var placeholder (prints a warning to stderr).",
)
@click.option(
    "--check",
    is_flag=True,
    default=False,
    help="Probe <WEAVIATE_URL>/v1/mcp live to confirm the native MCP endpoint is enabled and reachable.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def mcp_config(
    ctx: click.Context,
    client_format: str,
    server_name: str,
    include_key: bool,
    check: bool,
    json_output: bool | None,
) -> None:
    """Emit a ready-to-use Streamable HTTP MCP client config for the active Weaviate target."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "mcp config"
    try:
        config: ConfigManager = ctx.obj["config"]
        api_key = config.get_api_key()
        normalized_client = cast(McpClientFormat, client_format.lower())

        result = build_mcp_config(
            rest_base_url=config.rest_base_url,
            api_key=api_key,
            client=normalized_client,
            server_name=server_name,
            include_key=include_key,
        )

        if include_key and api_key:
            emit_warning(
                runtime,
                "Output contains a plaintext Weaviate API key (--include-key). "
                "Avoid committing generated MCP config files containing secrets to Git.",
            )
        elif include_key and not api_key:
            emit_warning(
                runtime,
                "--include-key was set, but no API key is configured for the active target.",
            )

        if check:
            probe_fn: McpProbeFn = probe_mcp_endpoint
            probe = probe_fn(config.rest_base_url, api_key)
            result["probe"] = probe
            if probe.get("available") is not True:
                status_code = probe.get("status_code")
                detail = (
                    f" (HTTP {status_code})"
                    if status_code is not None
                    else " (returned 404)"
                    if probe.get("available") is False
                    else " (endpoint unreachable)"
                )
                raise CLIError(
                    code="MCP_UNAVAILABLE",
                    message=f"Native MCP endpoint '{result['endpoint']}' is not available{detail}.",
                    exit_code=ExitCode.CONNECTIVITY,
                    hint=(
                        "Ensure Weaviate v1.37.1+ is running with MCP_SERVER_ENABLED=true "
                        "(enabled automatically by 'weaviate-cli local start' and on Weaviate Cloud)."
                    ),
                )
            if probe.get("auth_required"):
                emit_warning(
                    runtime,
                    "Native MCP endpoint is reachable but requires Bearer API key authentication. "
                    "Pass --api-key, --env-file, or set WEAVIATE_API_KEY.",
                )

        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: _render_mcp_config_text(result),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
