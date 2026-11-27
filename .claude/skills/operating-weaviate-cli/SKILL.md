---
name: operating-weaviate-cli
description: >-
  Operates Weaviate clusters through the agent-first weaviate-cli tool for
  cluster lifecycle (local Docker and Weaviate Cloud), DDL, and operational
  administration. Use this skill whenever "weaviate-cli" appears in the prompt,
  or when the user wants to start/stop a local Weaviate Docker cluster,
  provision or inspect Weaviate Cloud clusters, inspect cluster status or
  configuration, generate native /v1/mcp client config, create/update/delete
  collections, tenants, or aliases, manage RBAC roles and dynamic users, run or
  restore backups/exports, or manage nodes, shards, and replication.
  Do NOT use for querying or bulk-ingesting object data (route those to
  Weaviate's native /v1/mcp server or a Weaviate SDK) or for modifying the
  weaviate-cli source code (use contributing-to-weaviate-cli for that).
---

# Operating weaviate-cli

Agent-first CLI for Weaviate cluster lifecycle management, DDL, and operational administration.

## Four-Surface Routing

Choose the right surface before running commands:

| Task | Use | Why |
|------|-----|-----|
| Local Docker cluster lifecycle, Weaviate Cloud provisioning (`wcloud`), cluster `status`, `config show`, `mcp config`, DDL (`collection`, `tenant`, `alias`), and operational admin (`node`, `shard`, `replication`, `backup`, `export`, `role`, `user`) | **`weaviate-cli`** | Zero prompt-token overhead, deterministic JSON envelopes, semantic exit codes, and operations native MCP cannot perform |
| Live schema/tenant reads, hybrid search, and RBAC-scoped object upserts inside a coding/web agent | **Native Weaviate MCP (`/v1/mcp`)** | Built into Weaviate v1.37.1+; configure with `weaviate-cli mcp config --client <client>` |
| Persistent app code, ETL/batch data ingestion pipelines, code-managed schemas | **Weaviate SDKs** (Python/TS/Go/Java) | Typed application logic and high-throughput streaming |

## Live Discovery (Prefer Over Memorizing Flags)

`weaviate-cli` is self-documenting and drift-free:

```bash
weaviate-cli guide                    # Compact Markdown overview + workflows
weaviate-cli guide <group>            # Detailed flags for one group (e.g. cloud, local, collection)
weaviate-cli guide --schema [group]   # Machine-readable JSON command/option schema
weaviate-cli <group> <action> -h      # Per-command help and examples
```

## Connection Configuration & Precedence

Connection settings resolve in strict precedence order (highest to lowest):

1. **CLI flags**: `--url`, `--api-key`, `--grpc-url`
2. **Explicit env file**: `--env-file <path>` (pair-isolated; loads `WEAVIATE_URL`, `WEAVIATE_API_KEY`, `WEAVIATE_GRPC_URL` without mixing ambient env vars)
3. **Environment variables**: `WEAVIATE_URL`, `WEAVIATE_API_KEY`, `WEAVIATE_GRPC_URL`
4. **Explicit config file**: `--config-file <path>` (plus `--user <name>` when `auth.type` is `"user"`)
5. **Default config file**: `~/.config/weaviate/config.json`
6. **Fallback**: `http://localhost:8080` (gRPC `50051`)

Verify target resolution (offline, redacted) and live cluster health before mutating:

```bash
weaviate-cli [--env-file .env] config show
weaviate-cli [--env-file .env] status
```

**Config hygiene rules:**
- Never overwrite `~/.config/weaviate/config.json` without explicit user consent.
- Never silently assume `.env` is auto-loaded — always pass `--env-file <path>` explicitly or export `WEAVIATE_URL`/`WEAVIATE_API_KEY`.
- Store credential files in durable, gitignored locations (`.env`, `.env.<name>` added to `.gitignore`, or `~/.config/weaviate/<name>.json`) with mode `0600` — never inside disposable directories like `.venv/`.

## Output, Streams, and Exit Codes

- **Auto-JSON**: When `stdout` is not a TTY (e.g., agent tool shells or pipes), every command automatically emits a JSON envelope:
  ```json
  {
    "data": { "...": "..." },
    "error": null,
    "metadata": { "command": "status", "exit_code": 0 }
  }
  ```
  Override explicitly with `--json` or `--no-json`.
- **Stream separation**: Command output goes strictly to `stdout`; warnings, pull notices, and text-mode errors go to `stderr`.
- **Semantic exit codes**:
  - `0`: Success
  - `1`: Runtime / server error
  - `2`: Usage / validation / missing `--yes` confirmation error
  - `3`: Authentication / RBAC / `wcloud` login required
  - `4`: Resource not found or conflict
  - `5`: Connectivity / Docker / `wcloud` / `/v1/mcp` unavailable
- **Destructive confirmation**: Bulk or irreversible commands require `--yes` (e.g., `local destroy --yes`, `collection delete --all --yes`, `role delete <name> --yes`, `user delete <name> --yes`, `backup restore <id> --yes`, `replication delete --all --yes`, `shard update --all --yes`).

## Command Groups

| Group / Command | Actions | Purpose |
|-----------------|---------|---------|
| `status` | *(top-level)* | Live readiness, version, RBAC identity, collections/nodes summary, enabled vectorizers/modules, `/v1/mcp` probe |
| `guide` | *(top-level)* | Compact Markdown guide or `--schema` JSON command tree |
| `config` | `show` | Offline inspection of resolved target URL, gRPC endpoint, precedence source, and redacted auth |
| `mcp` | `config` | Generate Streamable HTTP `/v1/mcp` config (`generic`, `claude-code`, `cursor`, `vscode`) with optional `--check` |
| `local` | `start`, `template`, `stop`, `status`, `logs`, `destroy` | Managed local Docker Compose cluster (`weaviate-cli-local`) |
| `cloud` | `install-wcloud`, `login`, `whoami`, `logout`, `regions`, `create`, `list`, `get`, `status` | Weaviate Cloud lifecycle delegated to `wcloud` |
| `collection` | `create`, `list`, `get`, `update`, `delete` | Declarative JSON collection DDL and config updates |
| `tenant` | `create`, `list`, `get`, `update`, `delete` | Multi-tenant lifecycle (`hot`/`active`, `cold`/`inactive`, `frozen`/`offloaded`) |
| `alias` | `create`, `list`, `get`, `update`, `delete` | Zero-downtime collection alias management |
| `node` | `list` | Cluster node health, versions, shards, and collections |
| `shard` | `list`, `update`, `state` | Shard health, status transitions (`READY`/`READONLY`), and sharding state |
| `replication` | `create`, `list`, `get`, `cancel`, `delete` | Cross-node shard `COPY`/`MOVE` replication operations |
| `backup` | `create`, `get`, `restore`, `cancel` | Cluster/collection backup and restore (`s3`, `gcs`, `filesystem`) |
| `export` | `create`, `get`, `cancel` | Collection Parquet export (`filesystem`, `s3`, `gcs`, `azure`) |
| `role` | `create`, `list`, `get`, `delete`, `assign`, `revoke`, `add-permission`, `revoke-permission` | RBAC role and permission administration |
| `user` | `create`, `list`, `get`, `update`, `delete` | Dynamic DB user management and API key rotation |

## Core Workflows

### 1. Local Docker Cluster -> Collection -> Native MCP

```bash
# Easy mode: Weaviate :latest + /v1/mcp + local snowflake-arctic-embed-m-v1.5 ONNX sidecar
weaviate-cli local start
weaviate-cli local status                  # Includes data.config (auth/RBAC/DB-users/MCP/modules)
weaviate-cli local status --show-env       # Redacted container environment variables

# Advanced mode (e.g., enabling API key auth, RBAC, and DB users):
weaviate-cli local template > docker-compose.yml
# Uncomment AUTHENTICATION_APIKEY_ENABLED, AUTHENTICATION_DB_USERS_ENABLED, AUTHORIZATION_RBAC_ENABLED
weaviate-cli local start --compose-file docker-compose.yml

# Declarative collection DDL (JSON-only /v1/schema; uses "class", never "name")
weaviate-cli collection create --template > schema.json
weaviate-cli collection create --from-file schema.json --dry-run --check-cluster
weaviate-cli collection create --from-file schema.json --if-not-exists

# Wire up native /v1/mcp for data upsert & hybrid search
weaviate-cli mcp config --client claude-code --check
```

- Use `weaviate-cli local start --vectorizer none` for fast admin/CI runs without downloading the ONNX vectorizer image.
- `local` only manages containers labeled `com.docker.compose.project=weaviate-cli-local` and never touches external Docker containers.

### 2. Weaviate Cloud Provisioning (via `wcloud`)

```bash
# Pre-check auth first — 'cloud login' uses browser OAuth loopback and fails fast in non-TTY
weaviate-cli cloud whoami

# Provision a cluster and capture the ONE-TIME admin API key into a durable gitignored file
weaviate-cli cloud create --name my-cluster --region eu-central-1 --wait --write-env .env.cloud
# Ensure .env.cloud is in .gitignore, then verify:
weaviate-cli --env-file .env.cloud status
weaviate-cli --env-file .env.cloud mcp config --client claude-code --check
```

**Critical Cloud rules:**
- **One-time admin API key**: Weaviate Cloud returns the cluster admin API key **only once** (on `cloud create --wait` or the first `cloud get <id>` after `READY`). Before either key-bearing call, choose `--write-env`, `--write-config`, or `--include-key` for a protected stdout consumer. Use `cloud status <id>` to poll. A populated destination blocks the call; an ambient `WEAVIATE_API_KEY` used for authentication does not. File saves do not print the key on success unless `--include-key` is also set.
- **`CREDENTIAL_SAVE_FAILED` (exit 1)**: The cluster exists. Do not retry provisioning. Check `data.credentials_saved_to` for successful writes and `data.credential_save_failures` for failed paths. If no write succeeded, save the one-time key from stdout before discarding it. Treat this output as a secret, not a CI log.
- **`wcloud` installation**: Resolved `WEAVIATE_WCLOUD_PATH` > `$PATH` > `~/.cache/weaviate-cli/bin/wcloud`. Never silently downloaded in non-TTY; use `weaviate-cli cloud install-wcloud` (SHA-256 verified) or ask the user to install `wcloud`.

### 3. Collections, Tenants, and Aliases

```bash
weaviate-cli collection list
weaviate-cli collection get Articles
weaviate-cli collection update Articles --description "Knowledge base"
weaviate-cli collection delete Articles

# Tenants require explicit names (states: hot/active, cold/inactive, frozen/offloaded)
weaviate-cli tenant create tenant-a tenant-b --collection Articles --state active
weaviate-cli tenant list --collection Articles
weaviate-cli tenant update tenant-b --collection Articles --state frozen
weaviate-cli tenant delete tenant-b --collection Articles

# Zero-downtime alias switch
weaviate-cli alias create Docs Articles_v1
weaviate-cli alias update Docs Articles_v2
weaviate-cli alias list
weaviate-cli alias delete Docs
```

### 4. RBAC Roles & Dynamic DB Users

```bash
# Quote permissions with wildcards so zsh/bash does not glob them
weaviate-cli role create ArticlesReader -p 'read_collections:Articles' -p 'read_data:Articles'
weaviate-cli user create app-reader --store
weaviate-cli role assign --role ArticlesReader --user app-reader
weaviate-cli role get ArticlesReader
weaviate-cli user get app-reader
# Route stdout to a secret manager when rotating a key already present in the config.
# --store refuses to overwrite it, even on rotation.
# weaviate-cli user update app-reader --rotate-api-key --include-key | <secret consumer>
weaviate-cli user delete app-reader --yes
weaviate-cli role delete ArticlesReader --yes
```

`--store` needs an `auth.type=user` config with an unused slot for the requested user. If a save fails after creation or rotation, save the new key from stdout. Do not repeat the operation. After an interrupted file save, inspect the private `.<filename>.weaviate-key-lock` directory for `original` and `pending` before removing it; either may contain credentials.

**Prerequisite**: Dynamic user CRUD (`user create/update/delete`) requires `AUTHENTICATION_DB_USERS_ENABLED=true` on the Weaviate server (check `local status` -> `data.config.db_users` for local clusters).

### 5. Cluster Ops, Backups, Exports, and Replication

```bash
weaviate-cli node list --minimal
weaviate-cli shard list --collection Articles
weaviate-cli shard state Articles
weaviate-cli shard update --collection Articles --status READY

weaviate-cli replication create --collection Articles --shard shard-1 --source-node node1 --target-node node2 --type COPY
weaviate-cli replication list --collection Articles
weaviate-cli replication get <UUID> --history
weaviate-cli replication cancel <UUID>
weaviate-cli replication delete <UUID>

weaviate-cli backup create bk-2026 --backend s3 --include "Articles" --wait
weaviate-cli backup get bk-2026 --backend s3
weaviate-cli backup restore bk-2026 --backend s3 --wait --yes
weaviate-cli backup cancel bk-2026 --backend s3

weaviate-cli export create exp-2026 --backend s3 --include "Articles" --wait
weaviate-cli export get exp-2026 --backend s3
weaviate-cli export cancel exp-2026 --backend s3
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `WEAVIATE_URL` | Weaviate REST endpoint URL |
| `WEAVIATE_API_KEY` | Weaviate Bearer API key |
| `WEAVIATE_GRPC_URL` | Optional explicit Weaviate gRPC endpoint. When overriding the REST target, supply the matching gRPC override at the same or higher precedence; otherwise the CLI derives the endpoint from the new target. |
| `WEAVIATE_WCLOUD_PATH` | Optional explicit path override for the `wcloud` binary |
| `SLOW_CONNECTION` | Set to `1`/`true` to double Weaviate client timeouts |
| `HOME` | Base directory for `~/.config/weaviate/config.json` and `~/.cache/weaviate-cli/` |
