# PoC Tasks and Progress Log

Active checklist, command specifications, and dated progress log for the `weaviate-cli` AX PoC. See `AGENTS.md` for durable architecture boundaries, design rules, and ecosystem rationale.

## Active PoC plan

### Research and strategy alignment
- [x] Conduct research on managing Weaviate's agentic surfaces (CLI, native `/v1/mcp`, SDKs, `weaviate/agent-skills`) and audit the forked `weaviate-cli` codebase.
- [x] Confirm surface boundaries and revise PoC plan (`noun-verb` grammar, redesigned `collection`/`tenant` DDL, safe `wcloud` delegation, `local` Docker lifecycle with `snowflake-snowflake-arctic-embed-m-v1.5-onnx`, and AX contract hardening).

### Prune QA and data-plane scope
- [x] Remove data-plane commands (`create/update/delete/query data`) and `weaviate_cli/managers/data_manager.py`.
- [x] Remove `benchmark` command and `weaviate_cli/managers/benchmark_manager.py`.
- [x] Remove `weaviate_cli/datasets/movies.json`, hardcoded `Movies` schema in `collection_manager.py`, and `"Movies"` / `replication_factor=3` QA defaults in `defaults.py`.
- [x] Drop heavy dependencies (`numpy`, `faker`, `matplotlib`) from `setup.cfg` and clean up removed tests/imports.

### Migrate to `noun-verb` admin and DDL command tree
- [x] Reorganize existing admin and DDL commands into `noun-verb` groups with `kebab-case` flags (no backwards-compatible `verb-noun` aliases):
  - **DDL and data organization:**
    - `collection`: `create` (via `--from-file` / `--from-json` using `create_from_dict(...)` or lightweight `--property` flags), `list`, `get`, `update`, `delete`
    - `tenant`: `create`, `list`, `get`, `update`, `delete` (explicit tenant names, no 100-tenant QA generator default)
    - `alias`: `create`, `list`, `get`, `update`, `delete`
  - **Cluster ops and security:**
    - `node`: `list`
    - `shard`: `list`, `update`, `state`
    - `replication`: `create`, `list`, `get`, `cancel`, `delete`
    - `backup`: `create`, `get`, `restore`, `cancel`
    - `export`: `create`, `get`, `cancel`
    - `role`: `create`, `list`, `get`, `delete`, `assign`, `revoke`, `add-permission`, `revoke-permission`
    - `user`: `create`, `list`, `get`, `update`, `delete`
  - *(Lifecycle `local`/`cloud` and diagnostics/glue `status`/`config`/`mcp`/`guide` are tracked in [Implement lifecycle, diagnostics, and surface glue](#implement-lifecycle-diagnostics-and-surface-glue).)*

### Harden AX contracts
- [x] Shared AX runtime & `collection` vertical slice:
  - Added `weaviate_cli/errors.py`, `weaviate_cli/runtime.py`, and `weaviate_cli/specs/collection.py`.
  - Enabled global `--url`, `--api-key`, `--grpc-url`, `--env-file` + `WEAVIATE_URL`, `WEAVIATE_API_KEY`, `WEAVIATE_GRPC_URL` precedence in `ConfigManager` (pair-isolated `--env-file`, gRPC fallback warnings on `stderr`, and silenced `AuthlibDeprecationWarning` on CLI startup).
  - Added global `--json`/`--no-json` (auto-enabled when `!isatty()`) with `data`/`error`/`metadata` envelope, semantic exit codes (`0`..`5`), `-h`/`--help` with connection precedence and surface boundaries, and `collection delete --all --yes`.
  - Refactored `collection create` to JSON-only (`/v1/schema` via `--from-file <path|->` or `--from-json`, `--template`, `--dry-run`, `--check-cluster`, `--if-not-exists`) with pure client-side + live cluster module validation and strict rejection of top-level `"name"`.
- [x] Add one-shot command/syntax discovery (`guide` Markdown + `guide --schema` machine-readable Click command introspection) and `status` diagnostics (readiness, version, identity, enabled vectorizers/modules, `/v1/mcp` probe, graceful RBAC fallback).
- [ ] Roll out shared AX runtime (`stderr` routing, global `--json` envelope, semantic exit codes, `--yes` guards, `-h`/`--help` examples) to remaining command groups (`tenant`, `alias`, `node`, `shard`, `replication`, `backup`, `export`, `role`, `user`).

### Implement lifecycle, diagnostics, and surface glue
- [ ] Implement `cloud` delegation to `wcloud`:
  - User-first binary resolution (`WEAVIATE_WCLOUD_PATH` > `$PATH` > managed cache).
  - Interactive TTY install prompt for humans; explicit `--install-wcloud` / `cloud install-wcloud` with pinned SHA-256 verification for non-TTY/agents (otherwise fail fast with `WCLOUD_NOT_FOUND`).
  - Pre-check `wcloud auth whoami` (launch login in TTY, fail fast with `WCLOUD_AUTH_REQUIRED` in non-TTY).
  - Capture cluster URL and one-time admin API key from `wcloud cluster create --wait` into CLI profile / `.env`.
- [ ] Implement `local` Docker lifecycle (`start`, `stop`, `status`, `destroy`):
  - Verify whether `cr.weaviate.io/semitechnologies/transformers-inference:snowflake-snowflake-arctic-embed-m-v1.5-onnx` mirrors Docker Hub and supports `arm64`/`amd64` (fall back to Docker Hub image if not mirrored).
  - Launch single-node Weaviate + `text2vec-transformers` sidecar on a dedicated labeled Docker network with `/v1/mcp` enabled by default (`--no-mcp`), `ENABLE_API_BASED_MODULES=true`, optional `--rbac`, and `--vectorizer none` escape hatch.
  - Emit a `stderr` notice on first image pull and structured `DOCKER_UNAVAILABLE` / `PORT_IN_USE` errors when Docker or ports are unavailable.
- [ ] Implement `config` (`show` with redacted keys, `use`, `test`) and `mcp config` (ready-to-use client snippet). *(Done: `status` and `guide`.)*

### Update skills, docs, and evaluate agent DX/AX
- [ ] Update `CLAUDE.md` conventions once the CLI implements the [stderr and exit-code contracts](#harden-ax-contracts), replacing the legacy `click.echo("Error: ...")` and `sys.exit(1)` guidance.
- [ ] Update `.claude/skills/operating-weaviate-cli/` to document the `noun-verb` admin CLI and surface routing boundaries (CLI vs. `/v1/mcp` vs. SDK).
- [ ] Evaluate the PoC across coding agents on end-to-end tasks:
  1. Local start + `collection create` + `mcp config` + MCP upsert/hybrid query.
  2. Cloud provisioning + one-time API key capture + `status` check.
  3. RBAC setup (least-privilege role + dynamic user + access verification).
  4. Shard/tenant operational recovery (offload/activate tenant, repair shard state).
  5. Backup create + verify + restore.
  6. Mixed-surface routing (verify CLI vs. MCP vs. SDK selection without thrashing).
- [ ] Record evaluation metrics (completion rate, turns/tool calls, tokens, zero-hang rate, error recovery, routing accuracy) to inform the post-PoC decision: keep Python or consolidate into the Go `wcloud` binary.

### Deferred post-PoC ideas
- Local-to-Weaviate Cloud migration command (`migrate`):
  - Tier 1 (DDL/metadata): copy collection schemas, tenants, and aliases from local to WCD, automatically rewriting `text2vec-transformers` to `text2vec-weaviate` (`Snowflake/snowflake-arctic-embed-m-v1.5`), with `--dry-run` preview.
  - Tier 2 (prototype data copy): stream objects (and optionally precomputed vectors) for small local dev datasets, after empirically verifying vector-space parity (pooling, normalization, query prefix) between local `snowflake-snowflake-arctic-embed-m-v1.5-onnx` and WCD `text2vec-weaviate`.
- Explicit demo dataset seeding (e.g., `demo load movies`).
- Full `--dry-run` simulation across all mutating commands.
- Shell tab-completion updates for the `noun-verb` tree.

---

## Progress log

### 2026.11.26
- Audited `weaviate-cli` codebase alongside `wcloud` (`weaviate/weaviate-cloud`), native Weaviate MCP (`/v1/mcp` in `v1.37.1+`), and `weaviate/agent-skills`.
- Confirmed four-surface strategy and revised the PoC plan: `noun-verb` grammar, keeping redesigned `collection` and `tenant` DDL for `CLI -> MCP` completeness, safe TTY-aware `wcloud` delegation with one-time API key capture, opinionated `local` Docker lifecycle using `snowflake-snowflake-arctic-embed-m-v1.5-onnx`, and AX contract hardening.
- Split durable architecture rules and rationale (`AGENTS.md`) from volatile checklists and progress logs (`TODO.md`).
- Removed data-plane commands (`create/update/delete/query data`), `benchmark`, `data_manager.py`, `benchmark_manager.py`, `datasets/movies.json`, hardcoded `Movies` schema/defaults, `replication_factor=3` default, and `numpy`/`faker`/`matplotlib`/`importlib-resources` dependencies.
- Replaced Black with Ruff for local formatting and pre-commit checks. Added `make lint` for read-only lint and format checks and `make typecheck` for Pyright across the CLI and tests.
- Resolved all 121 Pyright errors without raising the SDK minimum. Fixes included stale collection config annotations, shell completion without `--config-file`, and collection listing for vectorizers the SDK returns as plain strings. All 286 existing unit tests passed; no new tests were added.
- Configured GitHub Actions to run `make lint` and `make typecheck` before the test jobs on pull requests and pushes to `main`. Removed Black's dependency and configuration. Both checks passed locally; the release workflow was unchanged.
- Migrated all existing admin and DDL commands to `noun-verb` groups (`collection`, `tenant`, `alias`, `node`, `shard`, `replication`, `backup`, `export`, `role`, `user`) with `kebab-case` flags and no legacy `verb-noun` aliases. Redesigned `collection create` with `--from-file`/`--from-json` (`create_from_dict`) and `--property name:type`, and required explicit tenant names across `tenant` commands.
- Surveyed `weaviate-client`, `wcloud`, `kubectl`, `aws` CLI, `supabase/cli`, `mongodb-atlas-cli`, `neonctl`, and `pscale` for declarative schema creation and AX contracts, then implemented the shared AX foundation (`errors.py`, `runtime.py`, `ConfigManager` env/flag precedence) and refactored the `collection` group (`collection create` simplified to JSON-only with `--template`, `--dry-run`, `--check-cluster`, `--if-not-exists`, and pure `specs/collection.py` client-side + live module validation; `collection delete --all` guarded by `--yes`).

### 2026.11.27
- Ran isolated `claude -p` black-box eval traces (cluster inspect, collection lifecycle, validation recovery), fixed trace-discovered issues (rejecting `"vectorizer": "none"`/`vectorIndex*` with `"vectorConfig"`, 1-round `"name"` + `"type"` validation hints, and silencing `AuthlibDeprecationWarning` on startup), and added pair-isolated global `--env-file <path>`.
- Implemented `weaviate-cli status` (target, readiness, version, RBAC-tolerant user/collections/nodes summary, enabled vectorizers/modules, and `/v1/mcp` probe) and `weaviate-cli guide` (compact Markdown + `--schema` live Click introspection), and added `.env` to `.gitignore`.
