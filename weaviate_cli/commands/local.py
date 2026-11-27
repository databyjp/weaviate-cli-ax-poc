"""Click commands for local Docker Weaviate cluster lifecycle (`weaviate-cli local`)."""

from __future__ import annotations

from typing import Any, Literal, cast

import click

from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.managers.local_manager import (
    WEAVIATE_PINNED_VERSION,
    LocalManager,
    render_template_compose_yaml,
)
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    AXGroup,
    RuntimeContext,
    emit_success,
    emit_warning,
    get_runtime,
    handle_command_error,
    require_confirmation,
)


def _render_local_status_text(data: dict[str, Any]) -> None:
    state = data.get("state", "unknown")
    action = data.get("action")
    header = f"State:       {state}" + (f" ({action})" if action else "")
    click.echo(header)
    if state == "not_created":
        click.echo("Start one with: weaviate-cli local start")
        return

    mode = data.get("mode") or "default"
    mode_suffix = (
        f" ({data['compose_file']})"
        if mode == "compose" and data.get("compose_file")
        else ""
    )
    click.echo(f"Mode:        {mode}{mode_suffix}")
    if data.get("vectorizer"):
        click.echo(f"Vectorizer:  {data['vectorizer']}")
    if data.get("url"):
        click.echo(f"URL:         {data['url']}")
    if data.get("grpc_url"):
        click.echo(f"gRPC URL:    {data['grpc_url']}")
    click.echo(f"Ready:       {data.get('ready', False)}")

    mcp = data.get("mcp")
    if isinstance(mcp, dict):
        avail = mcp.get("available")
        mcp_state = (
            "available"
            if avail is True
            else "not enabled"
            if avail is False
            else "unknown"
        )
        if mcp.get("auth_required"):
            mcp_state += " (auth required)"
        click.echo(f"Native MCP:  {mcp_state} ({mcp.get('endpoint')})")

    cfg = data.get("config")
    if isinstance(cfg, dict):
        click.echo(
            "Auth/RBAC:   "
            f"anonymous={str(cfg.get('anonymous_access', False)).lower()}, "
            f"api_key={str(cfg.get('apikey_auth', False)).lower()}, "
            f"db_users={str(cfg.get('db_users', False)).lower()}, "
            f"rbac={str(cfg.get('rbac', False)).lower()}"
        )
        default_vec = cfg.get("default_vectorizer") or "none"
        click.echo(
            "Modules/MCP: "
            f"api_modules={str(cfg.get('api_based_modules', False)).lower()}, "
            f"default_vectorizer={default_vec}, "
            f"mcp={str(cfg.get('mcp_enabled', False)).lower()} "
            f"(write={str(cfg.get('mcp_write_access', False)).lower()})"
        )

    services = data.get("services") or []
    if services:
        click.echo("Services:")
        for svc in services:
            click.echo(f"  - {svc['service']} ({svc['state']}): {svc['image']}")
            svc_env = svc.get("env")
            if isinstance(svc_env, dict) and svc_env:
                for key, value in svc_env.items():
                    click.echo(f"      {key}={value}")


def _render_stop_text(data: dict[str, Any]) -> None:
    if data.get("action") == "already_stopped":
        click.echo("Local Weaviate cluster is already stopped.")
        return
    svcs = ", ".join(data.get("stopped_services") or [])
    click.echo(f"Stopped local Weaviate cluster ({svcs}). Data volume preserved.")


def _render_destroy_text(data: dict[str, Any]) -> None:
    if data.get("already_absent"):
        click.echo("No weaviate-cli-managed local cluster exists.")
        return
    click.echo(
        "Destroyed local Weaviate cluster "
        f"(containers: {len(data.get('removed_containers') or [])}, "
        f"networks: {len(data.get('removed_networks') or [])}, "
        f"volumes: {len(data.get('removed_volumes') or [])})."
    )


def _progress_to_stderr(message: str) -> None:
    click.echo(message, err=True)


@click.group("local", cls=AXGroup)
def local_group() -> None:
    """Manage a local Docker Weaviate cluster (start, template, stop, status, logs, destroy)."""


@local_group.command(
    "start",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli local start\n"
        "  weaviate-cli local start --vectorizer none\n"
        "  weaviate-cli local template > docker-compose.yml\n"
        "  weaviate-cli local start --compose-file docker-compose.yml"
    ),
)
@click.option(
    "--vectorizer",
    type=click.Choice(["transformers", "none"], case_sensitive=False),
    default=None,
    help=(
        "Local vectorizer mode for default startup: 'transformers' (default, ONNX sidecar) "
        "or 'none' (fast admin-only). Mutually exclusive with --compose-file."
    ),
)
@click.option(
    "--compose-file",
    "compose_file",
    type=click.Path(dir_okay=False),
    default=None,
    help="Path to a custom docker-compose.yml file (run 'weaviate-cli local template' to generate one).",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def local_start(
    ctx: click.Context,
    vectorizer: str | None,
    compose_file: str | None,
    json_output: bool | None,
) -> None:
    """Start the local Weaviate Docker cluster (default stack or custom --compose-file)."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "local start"
    try:
        if compose_file is not None and vectorizer is not None:
            raise CLIError(
                code="CONFLICTING_OPTIONS",
                message="Cannot combine --compose-file with --vectorizer.",
                exit_code=ExitCode.USAGE,
                hint=(
                    "When using --compose-file, edit the Compose file directly to "
                    "configure modules or remove the vectorizer service."
                ),
            )
        chosen_vec = cast(
            Literal["transformers", "none"],
            (vectorizer or "transformers").lower(),
        )
        manager = LocalManager(progress_callback=_progress_to_stderr)
        result = manager.start(vectorizer=chosen_vec, compose_file=compose_file)
        for warning in result.pop("warnings", ()):
            emit_warning(runtime, warning)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: _render_local_status_text(result),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)


@local_group.command(
    "template",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli local template > docker-compose.yml\n"
        "  weaviate-cli local start --compose-file docker-compose.yml"
    ),
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Emit JSON envelope when --json is explicitly set (defaults to raw YAML even when piped).",
)
def local_template(json_output: bool | None) -> None:
    """Print a starter docker-compose.yml (with pinned version and commented RBAC settings)."""
    yaml_body = render_template_compose_yaml()
    if json_output is True:
        emit_success(
            RuntimeContext(json_output=True),
            {
                "pinned_version": WEAVIATE_PINNED_VERSION,
                "template": yaml_body,
            },
            command="local template",
        )
        return
    click.echo(yaml_body, nl=False)


@local_group.command(
    "status",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli local status\n"
        "  weaviate-cli local status --show-env"
    ),
)
@click.option(
    "--show-env",
    is_flag=True,
    default=False,
    help="Include redacted container environment variables for each service.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def local_status(ctx: click.Context, show_env: bool, json_output: bool | None) -> None:
    """Show the status, ports, config summary, readiness, and services of the local cluster."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "local status"
    try:
        manager = LocalManager()
        result = manager.status(show_env=show_env)
        for warning in result.pop("warnings", ()):
            emit_warning(runtime, warning)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: _render_local_status_text(result),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)


@local_group.command(
    "stop",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog="\b\nExamples:\n  weaviate-cli local stop",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def local_stop(ctx: click.Context, json_output: bool | None) -> None:
    """Stop the managed local Weaviate cluster while preserving its data volume."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "local stop"
    try:
        manager = LocalManager()
        result = manager.stop()
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: _render_stop_text(result),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)


@local_group.command(
    "logs",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli local logs\n"
        "  weaviate-cli local logs --service vectorizer --tail 50"
    ),
)
@click.option(
    "--service",
    default="weaviate",
    show_default=True,
    help="Compose service name to fetch logs from (e.g. weaviate, vectorizer).",
)
@click.option(
    "--tail",
    type=click.IntRange(min=1),
    default=100,
    show_default=True,
    help="Number of recent log lines to return.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def local_logs(
    ctx: click.Context,
    service: str,
    tail: int,
    json_output: bool | None,
) -> None:
    """Print recent logs from a service in the managed local cluster."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "local logs"
    try:
        manager = LocalManager()
        result = manager.logs(service=service, tail=tail)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: click.echo(result["logs"]),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)


@local_group.command(
    "destroy",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog="\b\nExamples:\n  weaviate-cli local destroy --yes",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm removal of the managed local containers, network, and persistent data volume.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Output JSON envelope (auto-enabled when stdout is not a TTY).",
)
@click.pass_context
def local_destroy(
    ctx: click.Context,
    yes: bool,
    json_output: bool | None,
) -> None:
    """Remove the managed local Weaviate containers, network, and persistent data volume."""
    runtime = get_runtime(ctx, json_override=json_output)
    command = "local destroy"
    try:
        require_confirmation(
            runtime,
            yes=yes,
            command=command,
            message=(
                "Destroying the local cluster permanently deletes its containers "
                "and persistent data volume."
            ),
            hint="Re-run with '--yes' to confirm: weaviate-cli local destroy --yes",
        )
        manager = LocalManager()
        result = manager.destroy()
        for warning in result.pop("warnings", ()):
            emit_warning(runtime, warning)
        emit_success(
            runtime,
            result,
            command=command,
            text_renderer=lambda: _render_destroy_text(result),
        )
    except Exception as exc:
        handle_command_error(ctx, runtime, exc, command=command)
