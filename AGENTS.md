# weaviate-cli AX PoC

This repo is a PoC fork of `weaviate/weaviate-cli` (originally a Weaviate QA tool) being reshaped into an agent-first CLI for Weaviate cluster lifecycle management, DDL, and operational administration.

See `TODO.md` for active PoC tasks, detailed command specs, and the chronological progress log. See `CLAUDE.md` for local dev/test commands (`make format`, `make lint`, `make test`).

## Surface boundaries

- **CLI (`weaviate-cli` + `wcloud`)**: Cluster lifecycle (local Docker and Weaviate Cloud), DDL, and operational administration for shell, CI, and terminal coding agents (zero upfront prompt token cost).
- **Native Weaviate MCP (`/v1/mcp`)**: Focused live schema/tenant read, hybrid search, and RBAC-scoped object upsert for coding agents and web/non-shell agents.
- **SDKs**: Persistent user-facing applications, robust data ingestion/ETL pipelines, and code-managed schemas.
- **Agent Skills (`weaviate/agent-skills`)**: Progressive-disclosure playbooks and the routing contract between CLI, MCP, and SDK (removing helper scripts that duplicate CLI or MCP).

## Standing design rules for this fork

- **Grammar and flags:** Use `noun-verb` commands (`<resource> <action>`) and `kebab-case` flags to align with `wcloud` and improve agent `--help` discovery. Do not keep `verb-noun` aliases.
- **AX contracts:** Route all errors, warnings, and progress notices strictly to `stderr`; keep `stdout` strictly for command output. Provide global `--json` (auto-enabled when `!isatty()`) with a `data`/`error`/`metadata` envelope matching `wcloud`. Support `WEAVIATE_URL`, `WEAVIATE_API_KEY`, and `WEAVIATE_GRPC_URL` (precedence: CLI flags > env vars > `--config-file` > default config > `localhost`). Use semantic exit codes (`0` ok, `1` runtime/server, `2` usage/validation, `3` auth/RBAC, `4` not found/conflict, `5` connectivity/missing dependency) and require `--yes` on destructive/bulk operations.
- **DDL scope:** Keep `collection` and `tenant` commands without QA fixtures (`collection create` uses declarative JSON via `--from-file`/`--from-json` backed by `weaviate-client` v4 `create_from_dict(...)`, plus lightweight `--property` flags; `tenant` commands require explicit names). Defer demo datasets (`demo load movies`) to post-PoC.
- **Cloud delegation (`wcloud`):** Resolve `wcloud` user-first (`WEAVIATE_WCLOUD_PATH` > `$PATH` > managed cache). Never silently auto-download or hang in non-TTY / `--json` mode: prompt only in a TTY, otherwise require explicit `--install-wcloud` or `cloud install-wcloud` (with SHA-256 verification) or fail fast with `WCLOUD_NOT_FOUND`. Pre-check `wcloud auth whoami` and capture `wcloud`'s one-time admin API key into CLI profile / `.env`.
- **Local Docker lifecycle:** Keep `local` minimal and opinionated (`start`, `stop`, `status`, `destroy`) wrapping the `docker` CLI: single-node Weaviate + `/v1/mcp` enabled + `ENABLE_API_BASED_MODULES=true` + `text2vec-transformers` sidecar using `semitechnologies/transformers-inference:snowflake-snowflake-arctic-embed-m-v1.5-onnx` (prefer `cr.weaviate.io` mirror if available; verify `arm64` support), with `--vectorizer none` and optional `--rbac`.

## Ecosystem context and rationale

Non-obvious facts about surrounding Weaviate surfaces and this fork that newly instantiated agents should know:

- **Native Weaviate MCP (`/v1/mcp`):** Built into the Weaviate server binary (`v1.37.1+`, Streamable HTTP on port `8080`, enabled by default on WCD, opt-in self-hosted via `MCP_SERVER_ENABLED=true` and `MCP_SERVER_WRITE_ACCESS_ENABLED=true`). Authenticated via Bearer API key under standard RBAC. Exposes four tools: `weaviate-collections-get-config`, `weaviate-tenants-list`, `weaviate-query-hybrid`, and `weaviate-objects-upsert`. Because it cannot create collections/tenants, mutate operational configs, or offload tenants (`hot`/`cold`/`frozen`), the CLI owns DDL and operational admin so `CLI -> MCP` works without throwaway SDK scripts.
- **Weaviate Cloud CLI (`wcloud`, `github.com/weaviate/weaviate-cloud`):** A separate **Go** agent-first CLI (`brew install weaviate/tap/weaviate-cloud`, `npm install -g weaviate-cloud`, `go install`) using `noun-verb` commands (`auth`, `region`, `cluster`, `guide`, `skill`) and a `data`/`error`/`metadata` JSON envelope.
  - `wcloud auth login` uses a local browser OAuth 2.0 PKCE loopback (`127.0.0.1`), which hangs in headless/sandboxed agents if called blindly; always pre-check `wcloud auth whoami` and fail fast with `WCLOUD_AUTH_REQUIRED` in non-TTY mode.
  - `wcloud cluster create --wait` prints a **one-time admin API key** that `wcloud` never stores; capturing it into CLI profile / `.env` is a primary DX/AX win.
  - Wrapping Go `wcloud` from this Python fork is an intentional PoC bridge to test single-CLI AX before deciding whether to consolidate into the Go `wcloud` binary post-PoC.
- **Why no silent `wcloud` auto-download:** Coding agent sandboxes frequently block outbound downloads or writes outside the workspace, and fetching unverified binaries at runtime is a supply-chain risk.
- **`weaviate/agent-skills` alignment:** Existing skills standardize on `WEAVIATE_URL` / `WEAVIATE_API_KEY` and Python Client v4. Matching those env vars keeps credentials consistent across surfaces and avoids failing when a sandbox blocks writes to `~/.config/weaviate/`.
- **Why `snowflake-snowflake-arctic-embed-m-v1.5-onnx` for `local start`:** `/v1/mcp` upsert and hybrid search take text rather than raw vectors, so local clusters need a default vectorizer for offline semantic search. `Snowflake/snowflake-arctic-embed-m-v1.5` matches Weaviate Embeddings on WCD (`text2vec-weaviate`) for smoother local-to-cloud migration (do not confuse it with the older `v1.0` `snowflake-snowflake-arctic-embed-m-onnx` tag, which has an incompatible vector space; migrating a collection to WCD still swaps `text2vec-transformers` to `text2vec-weaviate`). Emit a `stderr` pull notice on first run and keep `--vectorizer none` for fast admin-only/CI runs.
- **QA-era pitfalls in the original fork (do not carry forward):**
  - `collection_manager.py` hardcoded a 16-property `Movies` schema unless `--force_auto_schema` was passed, and `defaults.py` defaulted `--collection` to `"Movies"` (even on `delete collection`) and `--replication_factor` to `3`.
  - Commands echoed `Error:` to `stdout` instead of `stderr`, and `ConfigManager` printed gRPC fallback warnings to `stdout`, corrupting `--json`.
  - Destructive commands (`delete collection --all`, `delete all-replications`) lacked `--yes` guards, and all errors exited with code `1`.
