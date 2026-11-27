"""Shared CLI runtime: JSON envelope, TTY detection, stream hygiene, and error handling."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, NoReturn

import click

from weaviate_cli.errors import CLIError, ExitCode, classify_exception

HELP_OPTION_NAMES = ["-h", "--help"]
DEFAULT_CONTEXT_SETTINGS: dict[str, Any] = {"help_option_names": HELP_OPTION_NAMES}


@dataclass
class RuntimeContext:
    """Per-invocation output configuration and accumulated warnings."""

    json_output: bool
    warnings: list[str] = field(default_factory=list)


def resolve_json_output(explicit: bool | None) -> bool:
    """Resolve JSON mode: explicit flag wins, otherwise auto-enable when stdout is not a TTY."""
    if explicit is not None:
        return explicit
    return not sys.stdout.isatty()


def get_runtime(
    ctx: click.Context | None, *, json_override: bool | None = None
) -> RuntimeContext:
    """Fetch the RuntimeContext from Click context, applying any subcommand override."""
    if ctx is not None and isinstance(ctx.obj, dict) and "runtime" in ctx.obj:
        runtime: RuntimeContext = ctx.obj["runtime"]
        if json_override is not None:
            return RuntimeContext(
                json_output=json_override,
                warnings=runtime.warnings,
            )
        return runtime
    return RuntimeContext(json_output=resolve_json_output(json_override))


def emit_warning(runtime: RuntimeContext, message: str) -> None:
    """Record a warning and route it strictly to stderr."""
    runtime.warnings.append(message)
    click.echo(f"Warning: {message}", err=True)


def build_envelope(
    *,
    data: Any,
    error: dict[str, Any] | None,
    command: str,
    exit_code: ExitCode,
    warnings: Sequence[str] = (),
) -> dict[str, Any]:
    """Construct the standard data/error/metadata JSON envelope matching wcloud."""
    metadata: dict[str, Any] = {
        "command": command,
        "exit_code": int(exit_code),
    }
    if warnings:
        metadata["warnings"] = list(warnings)
    return {
        "data": data,
        "error": error,
        "metadata": metadata,
    }


def emit_success(
    runtime: RuntimeContext,
    data: Any,
    *,
    command: str,
    text_renderer: Callable[[], None] | None = None,
) -> None:
    """Write successful command output to stdout (JSON envelope or human text)."""
    if runtime.json_output:
        envelope = build_envelope(
            data=data,
            error=None,
            command=command,
            exit_code=ExitCode.OK,
            warnings=runtime.warnings,
        )
        click.echo(json.dumps(envelope, indent=2, default=str))
        return

    if text_renderer is not None:
        text_renderer()
    else:
        click.echo(json.dumps(data, indent=2, default=str))


def emit_error(
    runtime: RuntimeContext,
    error: CLIError,
    *,
    command: str,
) -> NoReturn:
    """Emit a structured error and exit with its semantic exit code."""
    if runtime.json_output:
        envelope = build_envelope(
            data=None,
            error=error.to_dict(),
            command=command,
            exit_code=error.exit_code,
            warnings=runtime.warnings,
        )
        click.echo(json.dumps(envelope, indent=2, default=str))
        sys.exit(int(error.exit_code))

    click.echo(f"Error [{error.code}]: {error.message}", err=True)
    for issue in error.issues:
        line = f"  - {issue.path}: {issue.message}"
        if issue.hint:
            line += f" ({issue.hint})"
        click.echo(line, err=True)
    if error.hint:
        click.echo(f"Hint: {error.hint}", err=True)
    sys.exit(int(error.exit_code))


def get_config_meta(ctx: click.Context | None) -> tuple[str | None, str | None]:
    """Return (target_description, config_source) from Click context if present."""
    config = (
        ctx.obj.get("config") if ctx is not None and isinstance(ctx.obj, dict) else None
    )
    if config is None:
        return None, None
    return getattr(config, "target_description", None), getattr(config, "source", None)


def handle_command_error(
    ctx: click.Context | None,
    runtime: RuntimeContext,
    exc: Exception,
    *,
    command: str,
) -> NoReturn:
    """Classify any command exception with target context and emit a structured error."""
    target, source = get_config_meta(ctx)
    cli_err = classify_exception(exc, target=target, config_source=source)
    emit_error(runtime, cli_err, command=command)


def _infer_json_from_argv(args: Sequence[str] | None) -> bool:
    """Determine JSON mode from raw argv when Click fails before invoking main()."""
    if args is not None:
        explicit: bool | None = None
        for token in args:
            if token == "--json":
                explicit = True
            elif token == "--no-json":
                explicit = False
        if explicit is not None:
            return explicit
    return not sys.stdout.isatty()


def _command_label_from_ctx(ctx: click.Context | None) -> str:
    if ctx is None:
        return "weaviate-cli"
    parts: list[str] = []
    cur: click.Context | None = ctx
    while cur is not None:
        if cur.info_name:
            parts.append(cur.info_name)
        cur = cur.parent
    parts.reverse()
    if len(parts) > 1:
        return " ".join(parts[1:])
    return parts[0] if parts else "weaviate-cli"


class AXGroup(click.Group):
    """Click Group that enables -h/--help and emits structured JSON on usage errors."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        context_settings = dict(DEFAULT_CONTEXT_SETTINGS)
        if "context_settings" in kwargs and kwargs["context_settings"]:
            context_settings.update(kwargs["context_settings"])
        kwargs["context_settings"] = context_settings
        super().__init__(*args, **kwargs)

    def main(  # type: ignore[override]
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        if not standalone_mode:
            return super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )

        raw_args = list(args) if args is not None else sys.argv[1:]
        try:
            return super().main(
                args=raw_args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )
        except click.exceptions.Exit as exc:
            sys.exit(exc.exit_code)
        except click.Abort:
            runtime = RuntimeContext(json_output=_infer_json_from_argv(raw_args))
            emit_error(
                runtime,
                CLIError(
                    code="ABORTED",
                    message="Operation aborted.",
                    exit_code=ExitCode.RUNTIME,
                ),
                command="weaviate-cli",
            )
        except click.UsageError as exc:
            runtime = RuntimeContext(json_output=_infer_json_from_argv(raw_args))
            cmd_label = _command_label_from_ctx(exc.ctx)
            help_cmd = (
                f"weaviate-cli {cmd_label} --help"
                if cmd_label and cmd_label != "weaviate-cli"
                else "weaviate-cli --help"
            )
            emit_error(
                runtime,
                CLIError(
                    code="USAGE_ERROR",
                    message=exc.format_message(),
                    exit_code=ExitCode.USAGE,
                    hint=f"Run '{help_cmd}' for usage and options.",
                ),
                command=cmd_label,
            )
        except click.ClickException as exc:
            runtime = RuntimeContext(json_output=_infer_json_from_argv(raw_args))
            emit_error(
                runtime,
                CLIError(
                    code="CLI_ERROR",
                    message=exc.format_message(),
                    exit_code=ExitCode.RUNTIME,
                ),
                command="weaviate-cli",
            )
        except CLIError as exc:
            runtime = RuntimeContext(json_output=_infer_json_from_argv(raw_args))
            emit_error(runtime, exc, command="weaviate-cli")
