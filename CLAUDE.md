# weaviate-cli

Agent-first CLI for Weaviate cluster lifecycle management (local Docker and Weaviate Cloud), DDL, and operational administration.

See `AGENTS.md` for surface boundaries (CLI vs. native `/v1/mcp` vs. SDKs vs. Agent Skills) and standing design rules, and `TODO.md` for active PoC tasks and progress history.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
make install-dev    # Install deps + pre-commit hooks
make test           # Run unit tests
```

## Development Commands

| Command | What it does |
|---------|--------------|
| `make format` | Ruff formatter on `cli.py`, `weaviate_cli/`, and `test/` |
| `make lint` | Check Ruff lint rules and formatting without writing files |
| `make typecheck` | Run Pyright on the CLI and tests using the active Python environment |
| `make test` | Run `pytest test/unittests` |
| `make build-all` | Build package + `twine check` |
| `make all` | `format` + `lint` + `test` + `build-all` |

## Architecture

`cli.py` (Click `AXGroup`) -> `weaviate_cli/commands/` (`noun-verb` groups + `status`/`guide`) -> `weaviate_cli/managers/` (business logic) + `weaviate_cli/specs/` (declarative validation)

- **`weaviate_cli/runtime.py`**: Shared AX runtime — `AXGroup`, `DEFAULT_CONTEXT_SETTINGS` (`-h`/`--help`), `resolve_json_output()`, `emit_success()`, `emit_warning()`, `emit_error()`, `handle_command_error()`, `require_confirmation()`
- **`weaviate_cli/errors.py`**: `ExitCode` (`0` ok, `1` runtime, `2` usage/validation, `3` auth/RBAC, `4` not-found/conflict, `5` connectivity/dependency), `CLIError`, and `classify_exception()`
- **`weaviate_cli/managers/config_manager.py`**: `ConfigManager` (created once in `cli.py`, stored in `ctx.obj["config"]`), handling precedence: CLI flags (`--url`, `--api-key`, `--grpc-url`) > `--env-file` > `WEAVIATE_*` env vars > `--config-file` > `~/.config/weaviate/config.json` > `localhost:8080`
- **`weaviate_cli/commands/`**: `local`, `cloud`, `config`, `mcp`, `status`, `guide`, `collection`, `tenant`, `alias`, `node`, `shard`, `replication`, `backup`, `export`, `role`, `user`
- **`weaviate_cli/defaults.py`**: Dataclass defaults for admin/DDL commands (no QA fixture defaults)
- **`weaviate_cli/utils.py`**: `get_client_from_context()`, `parse_permission()`, and shared helpers

## Key Conventions

- **Grammar & flags**: `noun-verb` subcommands (`<resource> <action>`) and `kebab-case` long options (enforced by `test_cli.py`). Every group uses `cls=AXGroup` and every leaf command uses `context_settings=DEFAULT_CONTEXT_SETTINGS` (`-h`/`--help`).
- **JSON envelope**: Every leaf command supports `--json/--no-json` (parameter `json_output: bool | None = None`, auto-enabled when `!isatty()`, enforced by `test_ax_rollout.py`) and emits a `data`/`error`/`metadata` envelope via `emit_success()` / `handle_command_error()`.
- **Stream hygiene**: Keep `stdout` strictly for command output; route all warnings, progress notices, and text-mode errors to `stderr` (`emit_warning()` / `click.echo(..., err=True)`).
- **Exit codes**: Classify all errors through `handle_command_error(ctx, runtime, exc, command=...)` / `CLIError` so semantic exit codes (`0`..`5`) apply consistently.
- **Safety**: Guard destructive or bulk mutations with `--yes` via `require_confirmation()`. Preflight key destinations before issuing, retrieving, or rotating a key. Do not overwrite credentials. Only `--include-key` opts into plaintext stdout on success. If every requested save fails after issuance, exit nonzero and return the key on stdout for recovery, never on stderr.
- **Client lifecycle**: Open in `try`, close in `finally`, and handle exceptions via `handle_command_error(...)`.
- **Formatting & typing**: Ruff formatting (88-char line length), `make lint`, and `make typecheck` (0 errors).

## Testing

- **Unit tests**: `test/unittests/` — `CliRunner(mix_stderr=False)` for CLI contract tests (`test_cli.py`, `test_ax_rollout.py`, `test_local.py`, `test_cloud.py`, `test_config_mcp.py`, etc.) and `MagicMock` for manager tests.
- **Integration tests**: `test/integration/` — requires a running Weaviate cluster.
- **CI**: `make lint` + `make typecheck` + build check -> unit tests (Python 3.10–3.13) -> integration tests.

## Agent Skills

Skills live in `.claude/skills/`:
- `operating-weaviate-cli/` — Using the CLI for cluster lifecycle, DDL, and admin (with four-surface routing)
- `contributing-to-weaviate-cli/` — Developing and testing the CLI codebase

When adding new commands or options, update the code, unit tests, `weaviate_cli/commands/guide.py` (if needed), and the relevant skill documentation.
