"""One-shot CLI self-documentation (`guide`) and machine-readable command schema."""

from __future__ import annotations

from typing import Any

import click

from weaviate_cli import __version__
from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.runtime import (
    DEFAULT_CONTEXT_SETTINGS,
    RuntimeContext,
    emit_error,
    emit_success,
    get_runtime,
)


def _param_type_label(param: click.Parameter) -> str:
    ptype = param.type
    if isinstance(ptype, click.Choice):
        return f"choice({', '.join(ptype.choices)})"
    return getattr(ptype, "name", str(ptype)).lower()


def _serialize_param(param: click.Parameter) -> dict[str, Any]:
    info: dict[str, Any] = {
        "name": param.name,
        "required": bool(param.required),
        "multiple": bool(param.multiple),
        "type": _param_type_label(param),
    }
    if isinstance(param, click.Option):
        info["opts"] = list(param.opts)
        if param.secondary_opts:
            info["secondary_opts"] = list(param.secondary_opts)
        info["is_flag"] = bool(param.is_flag)
        if param.help:
            info["help"] = param.help
    elif isinstance(param, click.Argument):
        info["metavar"] = param.make_metavar()
    return info


def introspect_command(
    cmd: click.Command,
    *,
    path: str = "weaviate-cli",
) -> dict[str, Any]:
    """Build a drift-free, machine-readable schema for a Click command or group."""
    arguments: list[dict[str, Any]] = []
    options: list[dict[str, Any]] = []
    for param in cmd.params:
        if isinstance(param, click.Argument):
            arguments.append(_serialize_param(param))
        elif isinstance(param, click.Option):
            if param.name == "help":
                continue
            options.append(_serialize_param(param))

    node: dict[str, Any] = {
        "name": cmd.name or path,
        "path": path,
        "summary": _first_line(cmd.help),
        "arguments": arguments,
        "options": options,
    }
    if isinstance(cmd, click.Group):
        subcommands: dict[str, dict[str, Any]] = {}
        for sub_name in sorted(cmd.commands.keys()):
            sub_cmd = cmd.commands[sub_name]
            subcommands[sub_name] = introspect_command(
                sub_cmd,
                path=f"{path} {sub_name}",
            )
        node["subcommands"] = subcommands
    return node


def _first_line(text: str | None) -> str:
    if not text:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and stripped != "\b":
            return stripped
    return ""


def _format_command_signature(cmd: click.Command, path: str) -> str:
    arg_parts = [
        param.make_metavar()
        for param in cmd.params
        if isinstance(param, click.Argument)
    ]
    if arg_parts:
        return f"{path} {' '.join(arg_parts)}"
    return path


def _render_command_detail_markdown(cmd: click.Command, path: str) -> list[str]:
    lines: list[str] = [f"## `{path}`", ""]
    summary = _first_line(cmd.help)
    if summary:
        lines.append(summary)
        lines.append("")

    if isinstance(cmd, click.Group):
        for sub_name in sorted(cmd.commands.keys()):
            sub_cmd = cmd.commands[sub_name]
            sub_path = f"{path} {sub_name}"
            sig = _format_command_signature(sub_cmd, sub_path)
            lines.append(f"### `{sig}`")
            sub_summary = _first_line(sub_cmd.help)
            if sub_summary:
                lines.append(sub_summary)
            opts = [
                p
                for p in sub_cmd.params
                if isinstance(p, click.Option) and p.name != "help"
            ]
            if opts:
                lines.append("")
                for opt in opts:
                    flags = ", ".join(opt.opts + opt.secondary_opts)
                    desc = opt.help or ""
                    lines.append(f"- `{flags}` ({_param_type_label(opt)}): {desc}")
            lines.append("")
    else:
        sig = _format_command_signature(cmd, path)
        lines.append(f"Usage: `{sig}`")
        opts = [
            p for p in cmd.params if isinstance(p, click.Option) and p.name != "help"
        ]
        if opts:
            lines.append("")
            for opt in opts:
                flags = ", ".join(opt.opts + opt.secondary_opts)
                desc = opt.help or ""
                lines.append(f"- `{flags}` ({_param_type_label(opt)}): {desc}")
        lines.append("")
    return lines


def render_guide_markdown(
    root: click.Group,
    *,
    topic: str | None = None,
) -> str:
    """Render a compact Markdown reference dynamically from the live Click command tree."""
    if topic is not None:
        target_cmd = root.commands[topic]
        lines = [
            f"# weaviate-cli guide: {topic}",
            "",
            *_render_command_detail_markdown(target_cmd, f"weaviate-cli {topic}"),
            "Run `weaviate-cli guide` for the full overview, or `weaviate-cli guide --schema "
            f"{topic}` for machine-readable JSON.",
        ]
        return "\n".join(lines).rstrip() + "\n"

    lines: list[str] = [
        f"# weaviate-cli guide (v{__version__})",
        "",
        "Agent-first CLI for Weaviate cluster DDL and operational administration.",
        "",
        "## Scope & surface boundaries",
        "- **CLI (`weaviate-cli`)**: Local Docker cluster lifecycle (`local`), cluster status, collections, tenants, aliases, nodes, shards, replication, backups, exports, roles, and users.",
        "- **Native MCP (`/v1/mcp`) or SDKs**: Querying, searching, or upserting object data.",
        "",
        "## Connection precedence (highest to lowest)",
        "1. CLI flags: `--url`, `--api-key`, `--grpc-url`",
        "2. Env file: `--env-file <path>` (loads `WEAVIATE_URL`, `WEAVIATE_API_KEY`, `WEAVIATE_GRPC_URL`)",
        "3. Environment: `WEAVIATE_URL`, `WEAVIATE_API_KEY`, `WEAVIATE_GRPC_URL`",
        "4. Config file: `--config-file <path>`",
        "5. Default file: `~/.config/weaviate/config.json`",
        "6. Fallback: `http://localhost:8080` (gRPC `50051`)",
        "",
        "## Output & exit codes",
        "- Non-TTY stdout automatically emits a `data`/`error`/`metadata` JSON envelope (override with `--json` / `--no-json`).",
        "- Errors and warnings go to `stderr` in text mode; `stdout` stays clean.",
        "- Exit codes: `0` ok, `1` runtime/server, `2` usage/validation, `3` auth/RBAC, `4` not found/conflict, `5` connectivity.",
        "- Bulk destructive actions require `--yes` (e.g. `collection delete --all --yes`).",
        "",
        "## Command map",
    ]

    for cmd_name in sorted(root.commands.keys()):
        cmd = root.commands[cmd_name]
        summary = _first_line(cmd.help)
        if isinstance(cmd, click.Group):
            subs = ", ".join(sorted(cmd.commands.keys()))
            lines.append(f"- **`{cmd_name}`** (`{subs}`): {summary}")
        else:
            lines.append(f"- **`{cmd_name}`**: {summary}")

    lines.extend(
        [
            "",
            "## Common workflows",
            "```bash",
            "# Start a local Docker Weaviate cluster (or customize via Compose template)",
            "weaviate-cli local start",
            "weaviate-cli local template > docker-compose.yml",
            "weaviate-cli local start --compose-file docker-compose.yml",
            "",
            "# Inspect target, readiness, version, identity, enabled vectorizers, and /v1/mcp",
            "weaviate-cli --env-file .env status",
            "",
            "# Declarative collection creation (JSON-only /v1/schema)",
            "weaviate-cli collection create --template > schema.json",
            "weaviate-cli --env-file .env collection create --from-file schema.json --dry-run --check-cluster",
            "weaviate-cli --env-file .env collection create --from-file schema.json",
            "weaviate-cli --env-file .env collection get Articles",
            "weaviate-cli --env-file .env collection delete Articles",
            "",
            "# Drill into one group or fetch full machine-readable command schema",
            "weaviate-cli guide collection",
            "weaviate-cli guide --schema",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def _resolve_root_group(ctx: click.Context) -> click.Group:
    root_ctx = ctx.find_root()
    if not isinstance(root_ctx.command, click.Group):
        raise CLIError(
            code="INTERNAL_ERROR",
            message="Could not locate root CLI command group.",
            exit_code=ExitCode.RUNTIME,
        )
    return root_ctx.command


@click.command(
    "guide",
    context_settings=DEFAULT_CONTEXT_SETTINGS,
    epilog=(
        "\b\n"
        "Examples:\n"
        "  weaviate-cli guide\n"
        "  weaviate-cli guide collection\n"
        "  weaviate-cli guide --schema\n"
        "  weaviate-cli guide --schema collection"
    ),
)
@click.argument("topic", required=False, default=None)
@click.option(
    "--schema",
    "emit_schema",
    is_flag=True,
    default=False,
    help="Emit a machine-readable JSON schema of commands, arguments, and options.",
)
@click.option(
    "--json/--no-json",
    "json_output",
    default=None,
    help="Emit JSON envelope (implies --schema when --json is explicitly set).",
)
@click.pass_context
def guide_command(
    ctx: click.Context,
    topic: str | None,
    emit_schema: bool,
    json_output: bool | None,
) -> None:
    """Print a compact CLI guide (Markdown) or machine-readable command --schema."""
    command = "guide"
    root = _resolve_root_group(ctx)

    if topic is not None and topic not in root.commands:
        runtime = get_runtime(ctx, json_override=json_output)
        available = ", ".join(sorted(root.commands.keys()))
        emit_error(
            runtime,
            CLIError(
                code="UNKNOWN_TOPIC",
                message=f"Unknown guide topic '{topic}'.",
                exit_code=ExitCode.USAGE,
                hint=f"Available topics: {available}.",
            ),
            command=command,
        )

    # Emit structured JSON when --schema is passed or --json is explicitly requested.
    # Otherwise print raw Markdown directly (even when piped) so agents can read it
    # in one shot without JSON-escaping overhead.
    if emit_schema or json_output is True:
        target_cmd: click.Command = root.commands[topic] if topic else root
        target_path = f"weaviate-cli {topic}" if topic else "weaviate-cli"
        schema_data = {
            "version": __version__,
            "topic": topic,
            "schema": introspect_command(target_cmd, path=target_path),
        }
        emit_success(
            RuntimeContext(json_output=True),
            schema_data,
            command=command,
        )
        return

    click.echo(render_guide_markdown(root, topic=topic), nl=False)
