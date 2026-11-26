# PoC Tasks and Progress Log

Active checklist, command specifications, and dated progress log for the `weaviate-cli` AX PoC. See `AGENTS.md` for durable architecture boundaries, design rules, and ecosystem rationale.

## Active PoC plan

### 0. Research and strategy alignment
- [x] Conduct research on managing Weaviate's agentic surfaces (CLI, native `/v1/mcp`, SDKs, `weaviate/agent-skills`) and audit the forked `weaviate-cli` codebase.
- [x] Confirm surface boundaries and revise PoC plan (`noun-verb` grammar, redesigned `collection`/`tenant` DDL, safe `wcloud` delegation, `local` Docker lifecycle with `snowflake-snowflake-arctic-embed-m-v1.5-onnx`, and AX contract hardening).

### 1. Prune QA and data-plane scope
- [x] Remove data-plane commands (`create/update/delete/query data`) and `weaviate_cli/managers/data_manager.py`.
- [x] Remove `benchmark` command and `weaviate_cli/managers/benchmark_manager.py`.
- [x] Remove `weaviate_cli/datasets/movies.json`, hardcoded `Movies` schema in `collection_manager.py`, and `"Movies"` / `replication_factor=3` QA defaults in `defaults.py`.
- [x] Drop heavy dependencies (`numpy`, `faker`, `matplotlib`) from `setup.cfg` and clean up removed tests/imports.

### 2. Migrate to `noun-verb` admin and DDL command tree
- [ ] Reorganize commands into `noun-verb` groups with `kebab-case` flags (no backwards-compatible `verb-noun` aliases):
  - **Lifecycle:**
    - `local`: `start`, `stop`, `status`, `destroy`
    - `cloud`: `install-wcloud`, `auth-status`, `regions`, `create`, `list`, `get`, `status`
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
    - `role`: `create`, `list`, `get`, `delete`, `assign`, `revoke`
    - `user`: `create`, `list`, `get`, `update`, `delete`
  - **Diagnostics and surface glue:**
    - `status`
    - `config`: `show`, `use`, `test`
    - `mcp`: `config`
    - `guide`

### 3. Harden AX contracts
- [ ] Route all errors, warnings, and progress messages strictly to `stderr` (`err=True`); keep `stdout` strictly for command output (including removing `stdout` gRPC warnings in `ConfigManager`).
- [ ] Add global `--json` flag (auto-enabled when `!isatty()`) emitting a consistent `data`/`error`/`metadata` envelope matching `wcloud` on both success and error.
- [ ] Support `WEAVIATE_URL`, `WEAVIATE_API_KEY`, and `WEAVIATE_GRPC_URL` env vars (precedence: CLI flags > env vars > `--config-file` > `~/.config/weaviate/config.json` > `localhost`).
- [ ] Implement semantic exit codes (`0` ok, `1` runtime/server, `2` usage/validation, `3` auth/RBAC, `4` not found/conflict, `5` connectivity/missing dependency).
- [ ] Require `--yes` on destructive/bulk operations (`collection delete --all`, `replication delete --all`, `role delete`, `user delete`, `backup restore`, `local destroy`) and require explicit resource names.

### 4. Implement lifecycle, diagnostics, and surface glue
- [ ] Implement `cloud` delegation to `wcloud`:
  - User-first binary resolution (`WEAVIATE_WCLOUD_PATH` > `$PATH` > managed cache).
  - Interactive TTY install prompt for humans; explicit `--install-wcloud` / `cloud install-wcloud` with pinned SHA-256 verification for non-TTY/agents (otherwise fail fast with `WCLOUD_NOT_FOUND`).
  - Pre-check `wcloud auth whoami` (launch login in TTY, fail fast with `WCLOUD_AUTH_REQUIRED` in non-TTY).
  - Capture cluster URL and one-time admin API key from `wcloud cluster create --wait` into CLI profile / `.env`.
- [ ] Implement `local` Docker lifecycle (`start`, `stop`, `status`, `destroy`):
  - Verify whether `cr.weaviate.io/semitechnologies/transformers-inference:snowflake-snowflake-arctic-embed-m-v1.5-onnx` mirrors Docker Hub and supports `arm64`/`amd64` (fall back to Docker Hub image if not mirrored).
  - Launch single-node Weaviate + `text2vec-transformers` sidecar on a dedicated labeled Docker network with `/v1/mcp` enabled by default (`--no-mcp`), `ENABLE_API_BASED_MODULES=true`, optional `--rbac`, and `--vectorizer none` escape hatch.
  - Emit a `stderr` notice on first image pull and structured `DOCKER_UNAVAILABLE` / `PORT_IN_USE` errors when Docker or ports are unavailable.
- [ ] Implement `status` (readiness/liveness, Weaviate version, node summary, enabled modules, `/v1/mcp` availability), `config` (`show` with redacted keys, `use`, `test`), `mcp config` (ready-to-use client snippet), and `guide` (compact Markdown self-documentation matching `wcloud guide`).

### 5. Update skills, docs, and evaluate agent DX/AX
- [ ] Update `CLAUDE.md` conventions (replace legacy `click.echo("Error: ...")` and `sys.exit(1)` rules once Phase 3 lands).
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
- Completed Phase 1: removed data-plane commands (`create/update/delete/query data`), `benchmark`, `data_manager.py`, `benchmark_manager.py`, `datasets/movies.json`, hardcoded `Movies` schema/defaults, `replication_factor=3` default, and `numpy`/`faker`/`matplotlib`/`importlib-resources` dependencies.
