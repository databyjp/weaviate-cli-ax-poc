---
name: contributing-to-weaviate-cli
description: >-
  Develops, tests, and reviews weaviate-cli source code. Use this skill when
  the task involves modifying the weaviate-cli codebase itself. Trigger if
  the request: asks to add a new command or flag to weaviate-cli; needs to
  fix a bug in the CLI source code (weaviate_cli/ Python files); involves
  reviewing a PR that changes weaviate-cli; wants to write or update unit or
  integration tests for the CLI; asks about the Click-based architecture,
  AX runtime, or command-to-manager pattern; or the working directory is
  the weaviate-cli repository and Python source files need to be modified.
  Do NOT use for running weaviate-cli commands against a Weaviate cluster —
  use operating-weaviate-cli for that.
---

# Contributing to weaviate-cli

Guide for developing, testing, and maintaining the `weaviate-cli` codebase. See `AGENTS.md` for standing AX design rules and surface boundaries, and `CLAUDE.md` for concise contributor conventions.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
make install-dev          # pip install -r requirements-dev.txt + pre-commit install
```

Key development commands:
```bash
make format               # Ruff formatter on cli.py, weaviate_cli/, test/
make lint                 # Check Ruff lint rules and formatting
make typecheck            # Pyright on CLI and tests
make test                 # pytest test/unittests
make build-all            # python -m build + twine check
make all                  # format + lint + test + build-all
```

## Repository Architecture

```
weaviate-cli/
  cli.py                        # Entry point: Click AXGroup, global options, command registration
  weaviate_cli/
    __init__.py                 # Package version
    runtime.py                  # AXGroup, DEFAULT_CONTEXT_SETTINGS, JSON envelope, warnings, --yes guard
    errors.py                   # ExitCode (0..5), CLIError, classify_exception()
    defaults.py                 # Dataclass defaults for admin/DDL commands
    utils.py                    # Shared helpers: get_client_from_context, parse_permission
    specs/
      collection.py             # Declarative /v1/schema validation + live module checks
    commands/                   # Click noun-verb command groups & top-level commands
      local.py                  # local start/template/stop/status/logs/destroy
      cloud.py                  # cloud install-wcloud/login/whoami/logout/regions/create/list/get/status
      config.py                 # config show
      mcp.py                    # mcp config
      status.py                 # status
      guide.py                  # guide [--schema] [topic]
      collection.py             # collection create/list/get/update/delete
      tenant.py                 # tenant create/list/get/update/delete
      alias.py                  # alias create/list/get/update/delete
      node.py                   # node list
      shard.py                  # shard list/update/state
      replication.py            # replication create/list/get/cancel/delete
      backup.py                 # backup create/get/restore/cancel
      export.py                 # export create/get/cancel
      role.py                   # role create/list/get/delete/assign/revoke/add-permission/revoke-permission
      user.py                   # user create/list/get/update/delete
    managers/                   # Business logic (one file per domain)
      config_manager.py         # ConfigManager: precedence, --env-file, client creation, describe_connection
      local_manager.py          # LocalManager: Docker Compose v2 lifecycle + config/env redaction
      cloud_manager.py          # CloudManager: wcloud resolution, SHA-256 install, credential capture
      status_manager.py         # StatusManager + probe_mcp_endpoint
      collection_manager.py     # CollectionManager
      tenant_manager.py         # TenantManager
      alias_manager.py          # AliasManager
      node_manager.py           # NodeManager
      shard_manager.py          # ShardManager
      cluster_manager.py        # ClusterManager (replication)
      backup_manager.py         # BackupManager
      export_manager.py         # ExportManager
      role_manager.py           # RoleManager
      user_manager.py           # UserManager
    completion/                 # Shell completion helpers
    types/                      # Type definitions
  test/
    unittests/
      conftest.py               # Shared fixtures
      test_cli.py               # Command tree, kebab-case, collection/tenant/config contracts
      test_ax_rollout.py        # Cross-command -h/--json/envelope/exit-code/--yes contract suite
      test_local.py             # Local Docker manager + CLI tests
      test_cloud.py             # Cloud wcloud delegation + credential capture tests
      test_config_mcp.py        # config show + mcp config tests
      test_managers/            # Manager unit tests
    integration/                # Integration tests (require running Weaviate cluster)
```

## AX Command Contract

Every command added or modified must follow these rules:

1. **Noun-verb grammar & kebab-case flags**: Register under `<resource> <action>` with `kebab-case` long options (`test_all_cli_options_are_kebab_case` enforces this).
2. **Short help & JSON option**: Groups use `cls=AXGroup`; leaf commands use `context_settings=DEFAULT_CONTEXT_SETTINGS` (`-h`/`--help`) and accept `@click.option("--json/--no-json", "json_output", default=None, ...)` (`test_every_command_supports_short_help_and_json_flag` enforces this).
3. **Envelope & stream hygiene**:
   - Resolve runtime with `runtime = get_runtime(ctx, json_override=json_output)`.
   - Emit results with `emit_success(runtime, data, command=..., text_renderer=...)`.
   - Emit warnings with `emit_warning(runtime, msg)` (always `stderr`).
   - Handle all exceptions via `handle_command_error(ctx, runtime, exc, command=...)` so `ExitCode` (`0..5`) and structured `error` payloads apply uniformly.
4. **Destructive guards**: Require `--yes` via `require_confirmation(yes, action=..., target=...)` on bulk or destructive actions.
5. **Client lifecycle**: Open client inside `try:` and always close in `finally:`.
6. **Secret safety**: Never print plaintext API keys or secret env vars unless explicitly requested (and warn on `stderr`).

## Code Review Checklist

1. `noun-verb` command path and `kebab-case` options
2. `-h`/`--help` and `--json/--no-json` supported on every leaf command
3. Output uses `emit_success` / `emit_warning` / `handle_command_error` (no raw `print` or `click.echo("Error: ...")` on stdout)
4. Destructive/bulk actions enforce `--yes`
5. Unit tests cover happy path, JSON envelope, text output, and error exit codes
6. `make lint`, `make typecheck`, and `make test` all pass with 0 errors
7. Update `test/unittests/test_cli.py`, `weaviate_cli/commands/guide.py` (if needed), and `.claude/skills/operating-weaviate-cli/SKILL.md`
