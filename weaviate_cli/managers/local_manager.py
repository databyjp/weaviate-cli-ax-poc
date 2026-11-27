"""Local Docker lifecycle manager wrapping Docker and Docker Compose v2."""

from __future__ import annotations

import json
import socket
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.managers.status_manager import McpProbeFn, probe_mcp_endpoint

LOCAL_PROJECT_NAME = "weaviate-cli-local"

WEAVIATE_LATEST_IMAGE = "cr.weaviate.io/semitechnologies/weaviate:latest"
WEAVIATE_PINNED_VERSION = "1.41.0"
WEAVIATE_PINNED_IMAGE = (
    f"cr.weaviate.io/semitechnologies/weaviate:{WEAVIATE_PINNED_VERSION}"
)
TRANSFORMERS_IMAGE = (
    "cr.weaviate.io/semitechnologies/transformers-inference:"
    "snowflake-snowflake-arctic-embed-m-v1.5-onnx"
)

DEFAULT_HTTP_PORT = 8080
DEFAULT_GRPC_PORT = 50051
DEFAULT_READY_TIMEOUT_SECONDS = 120.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0

COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"
COMPOSE_CONFIG_FILES_LABEL = "com.docker.compose.project.config_files"
MANAGED_LABEL = "weaviate-cli.managed"
MODE_LABEL = "weaviate-cli.mode"
VECTORIZER_LABEL = "weaviate-cli.vectorizer"

VectorizerMode = Literal["transformers", "none"]


@dataclass(frozen=True)
class CommandResult:
    """Result of invoking an external CLI command."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], str | None], CommandResult]
PortChecker = Callable[[int], bool]
HttpReadyChecker = Callable[[str], int | None]
ProgressCallback = Callable[[str], None]


def _default_command_runner(
    args: Sequence[str], stdin_text: str | None = None
) -> CommandResult:
    completed = subprocess.run(
        list(args),
        input=stdin_text,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _default_port_in_use(port: int) -> bool:
    """Return True if something is already listening on or bound to 127.0.0.1:<port>."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as binder:
        try:
            binder.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def _default_http_ready_checker(url: str) -> int | None:
    try:
        response = httpx.get(url, timeout=2.0)
        return response.status_code
    except httpx.HTTPError:
        return None


def render_template_compose_yaml() -> str:
    """Return the starter docker-compose.yml printed by `weaviate-cli local template`."""
    return (
        "# Starter Docker Compose configuration for local Weaviate.\n"
        "# Start with: weaviate-cli local start --compose-file docker-compose.yml\n"
        "services:\n"
        "  weaviate:\n"
        f"    # Pinned to {WEAVIATE_PINNED_VERSION} for reproducibility (default `local start` uses :latest)\n"
        f"    image: {WEAVIATE_PINNED_IMAGE}\n"
        "    ports:\n"
        f'      - "127.0.0.1:{DEFAULT_HTTP_PORT}:8080"\n'
        f'      - "127.0.0.1:{DEFAULT_GRPC_PORT}:50051"\n'
        "    volumes:\n"
        "      - weaviate_data:/var/lib/weaviate\n"
        "    restart: on-failure:0\n"
        "    depends_on:\n"
        "      - vectorizer\n"
        "    environment:\n"
        '      QUERY_DEFAULTS_LIMIT: "25"\n'
        '      PERSISTENCE_DATA_PATH: "/var/lib/weaviate"\n'
        '      CLUSTER_HOSTNAME: "node1"\n'
        '      ENABLE_API_BASED_MODULES: "true"\n'
        '      MCP_SERVER_ENABLED: "true"\n'
        '      MCP_SERVER_WRITE_ACCESS_ENABLED: "true"\n'
        "\n"
        "      # Local vectorizer (remove these 3 lines and the vectorizer service for --vectorizer none)\n"
        '      ENABLE_MODULES: "text2vec-transformers"\n'
        '      DEFAULT_VECTORIZER_MODULE: "text2vec-transformers"\n'
        '      TRANSFORMERS_INFERENCE_API: "http://vectorizer:8080"\n'
        "\n"
        "      # Authentication & RBAC (default: anonymous local access)\n"
        '      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "true"\n'
        '      # To enable API key auth, DB users, and RBAC, set AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "false"\n'
        "      # and uncomment the lines below:\n"
        '      # AUTHENTICATION_APIKEY_ENABLED: "true"\n'
        '      # AUTHENTICATION_APIKEY_ALLOWED_KEYS: "local-admin-key"\n'
        '      # AUTHENTICATION_APIKEY_USERS: "admin"\n'
        '      # AUTHENTICATION_DB_USERS_ENABLED: "true"\n'
        '      # AUTHORIZATION_RBAC_ENABLED: "true"\n'
        '      # AUTHORIZATION_RBAC_ROOT_USERS: "admin"\n'
        "\n"
        "      # Dynamic runtime configuration overrides (optional, Weaviate v1.30+):\n"
        '      # RUNTIME_OVERRIDES_ENABLED: "true"\n'
        '      # RUNTIME_OVERRIDES_PATH: "/etc/weaviate/runtime-overrides.yaml"\n'
        '      # RUNTIME_OVERRIDES_LOAD_INTERVAL: "30s"\n'
        "\n"
        "  vectorizer:\n"
        f"    image: {TRANSFORMERS_IMAGE}\n"
        "    environment:\n"
        '      ENABLE_CUDA: "0"\n'
        "\n"
        "volumes:\n"
        "  weaviate_data:\n"
    )


def render_default_compose_yaml(*, vectorizer: VectorizerMode = "transformers") -> str:
    """Return the in-memory Compose YAML used by `weaviate-cli local start` easy mode."""
    lines: list[str] = [
        "services:",
        "  weaviate:",
        f"    image: {WEAVIATE_LATEST_IMAGE}",
        "    ports:",
        f'      - "127.0.0.1:{DEFAULT_HTTP_PORT}:8080"',
        f'      - "127.0.0.1:{DEFAULT_GRPC_PORT}:50051"',
        "    volumes:",
        "      - weaviate_data:/var/lib/weaviate",
        "    restart: on-failure:0",
    ]
    if vectorizer == "transformers":
        lines.extend(
            [
                "    depends_on:",
                "      - vectorizer",
            ]
        )
    lines.extend(
        [
            "    labels:",
            f'      {MANAGED_LABEL}: "true"',
            f'      {MODE_LABEL}: "default"',
            f'      {VECTORIZER_LABEL}: "{vectorizer}"',
            "    environment:",
            '      QUERY_DEFAULTS_LIMIT: "25"',
            '      PERSISTENCE_DATA_PATH: "/var/lib/weaviate"',
            '      CLUSTER_HOSTNAME: "node1"',
            '      ENABLE_API_BASED_MODULES: "true"',
            '      MCP_SERVER_ENABLED: "true"',
            '      MCP_SERVER_WRITE_ACCESS_ENABLED: "true"',
            '      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "true"',
        ]
    )
    if vectorizer == "transformers":
        lines.extend(
            [
                '      ENABLE_MODULES: "text2vec-transformers"',
                '      DEFAULT_VECTORIZER_MODULE: "text2vec-transformers"',
                '      TRANSFORMERS_INFERENCE_API: "http://vectorizer:8080"',
                "  vectorizer:",
                f"    image: {TRANSFORMERS_IMAGE}",
                "    labels:",
                f'      {MANAGED_LABEL}: "true"',
                f'      {MODE_LABEL}: "default"',
                f'      {VECTORIZER_LABEL}: "{vectorizer}"',
                "    environment:",
                '      ENABLE_CUDA: "0"',
            ]
        )
    lines.extend(
        [
            "volumes:",
            "  weaviate_data:",
        ]
    )
    return "\n".join(lines) + "\n"


_SECRET_ENV_SUBSTRINGS: tuple[str, ...] = (
    "KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASS",
    "CREDENTIAL",
    "PRIVATE",
)
_NON_SECRET_ENV_SUFFIXES: tuple[str, ...] = (
    "_ENABLED",
    "_USERS",
    "_USER",
    "_HEADER",
    "_HEADERS",
    "_ENDPOINT",
    "_URL",
    "_HOST",
    "_PORT",
    "_PATH",
    "_DIR",
    "_FILE",
    "_TYPE",
    "_MODE",
)


def _parse_env_list(raw_env: Any) -> dict[str, str]:
    """Parse Docker's Config.Env list (['KEY=VALUE', ...]) into a dict."""
    if not isinstance(raw_env, list):
        return {}
    parsed: dict[str, str] = {}
    for entry in raw_env:
        if not isinstance(entry, str) or "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        if key:
            parsed[key] = value
    return parsed


def redact_env(env: dict[str, str]) -> dict[str, str]:
    """Return a sorted copy of container env vars with secret-like values masked."""
    redacted: dict[str, str] = {}
    for key in sorted(env.keys()):
        upper = key.upper()
        is_secret = any(sub in upper for sub in _SECRET_ENV_SUBSTRINGS) and not any(
            upper.endswith(suffix) for suffix in _NON_SECRET_ENV_SUFFIXES
        )
        redacted[key] = "***REDACTED***" if is_secret else env[key]
    return redacted


def _env_bool(env: dict[str, str], key: str) -> bool:
    return env.get(key, "").strip().lower() == "true"


def _extract_weaviate_config(
    containers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Derive a non-secret operational configuration summary from the Weaviate container env."""
    if not containers:
        return None
    primary = next(
        (c for c in containers if c.get("service") == "weaviate"),
        next(
            (c for c in containers if "8080/tcp" in (c.get("ports") or {})),
            containers[0],
        ),
    )
    raw_env = primary.get("env")
    env: dict[str, str] = raw_env if isinstance(raw_env, dict) else {}

    modules_raw = env.get("ENABLE_MODULES", "")
    enable_modules = [m.strip() for m in modules_raw.split(",") if m.strip()]
    default_vec = env.get("DEFAULT_VECTORIZER_MODULE", "").strip() or None

    return {
        "anonymous_access": _env_bool(env, "AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED"),
        "apikey_auth": _env_bool(env, "AUTHENTICATION_APIKEY_ENABLED"),
        "db_users": _env_bool(env, "AUTHENTICATION_DB_USERS_ENABLED"),
        "rbac": _env_bool(env, "AUTHORIZATION_RBAC_ENABLED"),
        "mcp_enabled": _env_bool(env, "MCP_SERVER_ENABLED"),
        "mcp_write_access": _env_bool(env, "MCP_SERVER_WRITE_ACCESS_ENABLED"),
        "api_based_modules": _env_bool(env, "ENABLE_API_BASED_MODULES"),
        "default_vectorizer": default_vec,
        "enable_modules": enable_modules,
    }


def _parse_container_summary(raw: dict[str, Any]) -> dict[str, Any]:
    raw_config = raw.get("Config")
    config: dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
    raw_labels = config.get("Labels")
    labels: dict[str, Any] = raw_labels if isinstance(raw_labels, dict) else {}
    raw_state = raw.get("State")
    state_obj: dict[str, Any] = raw_state if isinstance(raw_state, dict) else {}
    raw_net = raw.get("NetworkSettings")
    net_obj: dict[str, Any] = raw_net if isinstance(raw_net, dict) else {}
    raw_ports = net_obj.get("Ports")
    ports_raw: dict[str, Any] = raw_ports if isinstance(raw_ports, dict) else {}

    published_ports: dict[str, int] = {}
    for container_port, bindings in ports_raw.items():
        if isinstance(bindings, list) and bindings:
            first = bindings[0]
            if isinstance(first, dict) and first.get("HostPort"):
                try:
                    published_ports[str(container_port)] = int(first["HostPort"])
                except (TypeError, ValueError):
                    pass

    raw_name = str(raw.get("Name") or "").lstrip("/")
    service = str(labels.get(COMPOSE_SERVICE_LABEL) or raw_name)
    full_id = str(raw.get("Id") or "")

    return {
        "id": full_id[:12] if full_id else "",
        "name": raw_name,
        "service": service,
        "image": str(config.get("Image") or ""),
        "state": str(state_obj.get("Status") or "unknown"),
        "running": bool(state_obj.get("Running", False)),
        "ports": published_ports,
        "labels": {str(k): str(v) for k, v in labels.items()},
        "env": _parse_env_list(config.get("Env")),
    }


def _extract_primary_ports(
    containers: list[dict[str, Any]],
) -> tuple[int | None, int | None]:
    """Locate mapped host HTTP (8080/tcp) and gRPC (50051/tcp) ports."""
    ordered = sorted(
        containers,
        key=lambda c: (0 if c.get("service") == "weaviate" else 1, c.get("name", "")),
    )
    http_port: int | None = None
    grpc_port: int | None = None
    for item in ordered:
        ports = item.get("ports") or {}
        if http_port is None and "8080/tcp" in ports:
            http_port = int(ports["8080/tcp"])
        if grpc_port is None and "50051/tcp" in ports:
            grpc_port = int(ports["50051/tcp"])
    return http_port, grpc_port


def _extract_project_metadata(containers: list[dict[str, Any]]) -> dict[str, Any]:
    mode = "compose"
    vectorizer: str | None = None
    compose_file: str | None = None

    for item in containers:
        labels = item.get("labels") or {}
        if labels.get(MODE_LABEL) == "default":
            mode = "default"
        if labels.get(VECTORIZER_LABEL):
            vectorizer = labels[VECTORIZER_LABEL]
        cfg = labels.get(COMPOSE_CONFIG_FILES_LABEL)
        if cfg and cfg != "-" and compose_file is None:
            compose_file = cfg

    if mode == "compose":
        # Infer whether a transformers sidecar is part of the custom stack.
        has_vectorizer = any(
            c.get("service") == "vectorizer"
            or "transformers-inference" in str(c.get("image", ""))
            for c in containers
        )
        vectorizer = "transformers" if has_vectorizer else "custom"
    else:
        compose_file = None

    return {
        "mode": mode,
        "vectorizer": vectorizer,
        "compose_file": compose_file,
    }


def _aggregate_state(containers: list[dict[str, Any]]) -> str:
    if not containers:
        return "not_created"
    running_count = sum(1 for c in containers if c.get("running"))
    if running_count == len(containers):
        return "running"
    if running_count == 0:
        return "stopped"
    return "degraded"


def _public_service_view(
    container: dict[str, Any], *, show_env: bool = False
) -> dict[str, Any]:
    view: dict[str, Any] = {
        "service": container["service"],
        "container": container["name"],
        "image": container["image"],
        "state": container["state"],
        "ports": container["ports"],
    }
    if show_env:
        raw_env = container.get("env")
        view["env"] = redact_env(raw_env if isinstance(raw_env, dict) else {})
    return view


class LocalManager:
    """Manage a single local Weaviate Docker stack under project `weaviate-cli-local`."""

    def __init__(
        self,
        *,
        project: str = LOCAL_PROJECT_NAME,
        runner: CommandRunner | None = None,
        port_checker: PortChecker | None = None,
        http_ready_checker: HttpReadyChecker | None = None,
        mcp_probe: McpProbeFn | None = None,
        progress_callback: ProgressCallback | None = None,
        ready_timeout: float = DEFAULT_READY_TIMEOUT_SECONDS,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.project = project
        self._runner: CommandRunner = (
            _default_command_runner if runner is None else runner
        )
        self._port_checker: PortChecker = (
            _default_port_in_use if port_checker is None else port_checker
        )
        self._http_ready_checker: HttpReadyChecker = (
            _default_http_ready_checker
            if http_ready_checker is None
            else http_ready_checker
        )
        self._mcp_probe: McpProbeFn = (
            probe_mcp_endpoint if mcp_probe is None else mcp_probe
        )
        self._progress: ProgressCallback | None = progress_callback
        self.ready_timeout = ready_timeout
        self.poll_interval = poll_interval
        self._sleep = sleep_fn
        self._monotonic = monotonic_fn

    def _emit_progress(self, message: str) -> None:
        if self._progress is not None:
            self._progress(message)

    def _run_docker(
        self, args: Sequence[str], *, stdin_text: str | None = None
    ) -> CommandResult:
        try:
            return self._runner(args, stdin_text)
        except FileNotFoundError as exc:
            raise CLIError(
                code="DOCKER_UNAVAILABLE",
                message="Docker CLI ('docker') was not found on PATH.",
                exit_code=ExitCode.CONNECTIVITY,
                hint=(
                    "Install Docker Desktop, OrbStack, or Docker Engine and ensure "
                    "'docker' is available on PATH."
                ),
            ) from exc
        except OSError as exc:
            raise CLIError(
                code="DOCKER_UNAVAILABLE",
                message=f"Failed to execute Docker CLI: {exc}",
                exit_code=ExitCode.CONNECTIVITY,
                hint="Verify Docker is installed and accessible from this shell.",
            ) from exc

    def _ensure_docker_ready(self, *, require_compose: bool = False) -> None:
        info = self._run_docker(["docker", "info", "--format", "{{.ServerVersion}}"])
        if info.returncode != 0:
            detail = (info.stderr or info.stdout).strip().splitlines()
            first_line = detail[-1] if detail else "Docker daemon is not reachable."
            raise CLIError(
                code="DOCKER_UNAVAILABLE",
                message=f"Docker daemon is not available: {first_line}",
                exit_code=ExitCode.CONNECTIVITY,
                hint=(
                    "Start Docker Desktop, OrbStack, or the Docker daemon and ensure "
                    "this process has permission to access the Docker socket."
                ),
            )

        if require_compose:
            compose_ver = self._run_docker(["docker", "compose", "version"])
            if compose_ver.returncode != 0:
                raise CLIError(
                    code="DOCKER_COMPOSE_UNAVAILABLE",
                    message="Docker Compose v2 ('docker compose') is not available.",
                    exit_code=ExitCode.CONNECTIVITY,
                    hint=(
                        "Install or enable the Docker Compose v2 plugin "
                        "(bundled with Docker Desktop and OrbStack)."
                    ),
                )

    def _inspect_project_containers(self) -> list[dict[str, Any]]:
        listed = self._run_docker(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"label={COMPOSE_PROJECT_LABEL}={self.project}",
                "--format",
                "{{.ID}}",
            ]
        )
        if listed.returncode != 0:
            raise CLIError(
                code="DOCKER_ERROR",
                message=f"Failed to list local containers: {(listed.stderr or listed.stdout).strip()}",
                exit_code=ExitCode.RUNTIME,
            )
        ids = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
        if not ids:
            return []

        inspected = self._run_docker(["docker", "inspect", *ids])
        if inspected.returncode != 0:
            raise CLIError(
                code="DOCKER_ERROR",
                message=f"Failed to inspect local containers: {(inspected.stderr or inspected.stdout).strip()}",
                exit_code=ExitCode.RUNTIME,
            )
        try:
            parsed = json.loads(inspected.stdout)
        except json.JSONDecodeError as exc:
            raise CLIError(
                code="DOCKER_ERROR",
                message=f"Could not parse 'docker inspect' output: {exc}",
                exit_code=ExitCode.RUNTIME,
            ) from exc

        if not isinstance(parsed, list):
            return []
        return [
            _parse_container_summary(item) for item in parsed if isinstance(item, dict)
        ]

    def _find_unmanaged_containers_on_port(self, port: int) -> list[str]:
        res = self._run_docker(
            [
                "docker",
                "ps",
                "--filter",
                f"publish={port}",
                "--format",
                '{{.Names}}\t{{.Label "com.docker.compose.project"}}',
            ]
        )
        if res.returncode != 0:
            return []
        names: list[str] = []
        for line in res.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split("\t", 1)
            cname = parts[0].strip()
            proj = parts[1].strip() if len(parts) > 1 else ""
            if cname and proj != self.project:
                names.append(cname)
        return names

    def _check_default_ports_available(self) -> None:
        for label, port in (
            ("HTTP", DEFAULT_HTTP_PORT),
            ("gRPC", DEFAULT_GRPC_PORT),
        ):
            unmanaged = self._find_unmanaged_containers_on_port(port)
            if unmanaged or self._port_checker(port):
                owner = (
                    f"Docker container '{', '.join(unmanaged)}'"
                    if unmanaged
                    else "another process"
                )
                raise CLIError(
                    code="PORT_IN_USE",
                    message=(
                        f"{label} port {port} on 127.0.0.1 is already in use by {owner} "
                        f"(not managed by 'weaviate-cli local')."
                    ),
                    exit_code=ExitCode.CONNECTIVITY,
                    hint=(
                        f"Stop {owner}, or generate a custom Compose file with different "
                        "ports via 'weaviate-cli local template > docker-compose.yml' and "
                        "start it with 'weaviate-cli local start --compose-file docker-compose.yml'."
                    ),
                    details={
                        "port": port,
                        "unmanaged_containers": unmanaged,
                    },
                )

    def _ensure_images_pulled(self, images: Sequence[tuple[str, str]]) -> None:
        for image, size_hint in images:
            inspect = self._run_docker(["docker", "image", "inspect", image])
            if inspect.returncode == 0:
                continue
            suffix = f" ({size_hint}, one-time download)" if size_hint else ""
            self._emit_progress(f"Pulling {image}{suffix}...")
            pulled = self._run_docker(["docker", "pull", image])
            if pulled.returncode != 0:
                detail = (pulled.stderr or pulled.stdout).strip()
                raise CLIError(
                    code="IMAGE_PULL_FAILED",
                    message=f"Failed to pull Docker image '{image}': {detail}",
                    exit_code=ExitCode.CONNECTIVITY,
                    hint="Verify network access to cr.weaviate.io and Docker registry settings.",
                )

    def _collect_recent_logs(
        self, containers: list[dict[str, Any]], *, tail: int = 25
    ) -> dict[str, str]:
        collected: dict[str, str] = {}
        for item in containers:
            res = self._run_docker(
                ["docker", "logs", "--tail", str(tail), item["name"]]
            )
            combined = "\n".join(
                part.strip() for part in (res.stdout, res.stderr) if part.strip()
            )
            if combined:
                collected[item["service"]] = combined
        return collected

    def _wait_for_ready(self, http_port: int) -> None:
        ready_url = f"http://127.0.0.1:{http_port}/v1/.well-known/ready"
        deadline = self._monotonic() + self.ready_timeout
        while True:
            status_code = self._http_ready_checker(ready_url)
            if status_code == 200:
                return

            containers = self._inspect_project_containers()
            weaviate_containers = [
                c for c in containers if c.get("service") == "weaviate"
            ] or containers
            if weaviate_containers and all(
                not c.get("running") for c in weaviate_containers
            ):
                logs = self._collect_recent_logs(containers)
                raise CLIError(
                    code="LOCAL_STARTUP_FAILED",
                    message="Local Weaviate container exited before becoming ready.",
                    exit_code=ExitCode.CONNECTIVITY,
                    hint=(
                        "Inspect logs with 'weaviate-cli local logs' or reset with "
                        "'weaviate-cli local destroy --yes'."
                    ),
                    details={"logs": logs} if logs else None,
                )

            if self._monotonic() >= deadline:
                logs = self._collect_recent_logs(containers)
                raise CLIError(
                    code="LOCAL_STARTUP_TIMEOUT",
                    message=(
                        f"Timed out after {int(self.ready_timeout)}s waiting for "
                        f"{ready_url} to report ready."
                    ),
                    exit_code=ExitCode.CONNECTIVITY,
                    hint=(
                        "Check startup progress with 'weaviate-cli local logs' or "
                        "'weaviate-cli local status'."
                    ),
                    details={"logs": logs} if logs else None,
                )

            self._sleep(self.poll_interval)

    def _build_status_payload(
        self,
        containers: list[dict[str, Any]],
        *,
        action: str | None = None,
        check_unmanaged_port: bool = False,
        show_env: bool = False,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        state = _aggregate_state(containers)
        if not containers:
            if check_unmanaged_port:
                unmanaged = self._find_unmanaged_containers_on_port(DEFAULT_HTTP_PORT)
                if unmanaged or self._port_checker(DEFAULT_HTTP_PORT):
                    owner = (
                        f"Docker container '{', '.join(unmanaged)}'"
                        if unmanaged
                        else "another process"
                    )
                    warnings.append(
                        f"No weaviate-cli-managed local cluster exists, but {owner} is "
                        f"listening on 127.0.0.1:{DEFAULT_HTTP_PORT}."
                    )
            payload: dict[str, Any] = {
                "project": self.project,
                "state": "not_created",
                "mode": None,
                "vectorizer": None,
                "compose_file": None,
                "url": None,
                "grpc_url": None,
                "ready": False,
                "mcp": None,
                "config": None,
                "services": [],
                "warnings": warnings,
            }
            if action is not None:
                payload["action"] = action
            return payload

        meta = _extract_project_metadata(containers)
        http_port, grpc_port = _extract_primary_ports(containers)
        url = f"http://127.0.0.1:{http_port}" if http_port is not None else None
        grpc_url = f"127.0.0.1:{grpc_port}" if grpc_port is not None else None

        ready = False
        mcp_info: dict[str, Any] | None = None
        if state == "running" and url is not None:
            ready = self._http_ready_checker(f"{url}/v1/.well-known/ready") == 200
            if ready:
                mcp_info = self._mcp_probe(url, None)

        payload = {
            "project": self.project,
            "state": state,
            "mode": meta["mode"],
            "vectorizer": meta["vectorizer"],
            "compose_file": meta["compose_file"],
            "url": url,
            "grpc_url": grpc_url,
            "ready": ready,
            "mcp": mcp_info,
            "config": _extract_weaviate_config(containers),
            "services": [
                _public_service_view(c, show_env=show_env) for c in containers
            ],
            "warnings": warnings,
        }
        if action is not None:
            payload["action"] = action
        return payload

    def start(
        self,
        *,
        vectorizer: VectorizerMode = "transformers",
        compose_file: str | None = None,
    ) -> dict[str, Any]:
        """Start the local Weaviate stack (default mode or custom Compose file)."""
        resolved_compose: str | None = None
        if compose_file is not None:
            path = Path(compose_file)
            if not path.is_file():
                raise CLIError(
                    code="COMPOSE_FILE_NOT_FOUND",
                    message=f"Compose file '{compose_file}' does not exist.",
                    exit_code=ExitCode.USAGE,
                    hint="Generate a starter Compose file with 'weaviate-cli local template > docker-compose.yml'.",
                )
            resolved_compose = str(path.resolve())

        self._ensure_docker_ready(require_compose=True)
        existing = self._inspect_project_containers()
        action = "created"

        if existing:
            meta = _extract_project_metadata(existing)
            requested_mode = "compose" if resolved_compose is not None else "default"

            if meta["mode"] != requested_mode:
                raise CLIError(
                    code="LOCAL_CONFIG_MISMATCH",
                    message=(
                        f"Local cluster already exists in '{meta['mode']}' mode, "
                        f"cannot start in '{requested_mode}' mode."
                    ),
                    exit_code=ExitCode.NOT_FOUND,
                    hint="Run 'weaviate-cli local destroy --yes' first to recreate the local cluster.",
                )

            if requested_mode == "default" and meta["vectorizer"] != vectorizer:
                raise CLIError(
                    code="LOCAL_CONFIG_MISMATCH",
                    message=(
                        f"Local cluster already exists with vectorizer='{meta['vectorizer']}', "
                        f"cannot start with vectorizer='{vectorizer}'."
                    ),
                    exit_code=ExitCode.NOT_FOUND,
                    hint="Run 'weaviate-cli local destroy --yes' first to switch vectorizers.",
                )

            if (
                requested_mode == "compose"
                and meta["compose_file"]
                and resolved_compose
                and str(Path(meta["compose_file"]).resolve()) != resolved_compose
            ):
                raise CLIError(
                    code="LOCAL_CONFIG_MISMATCH",
                    message=(
                        f"Local cluster was created from '{meta['compose_file']}', "
                        f"cannot start from '{resolved_compose}'."
                    ),
                    exit_code=ExitCode.NOT_FOUND,
                    hint="Run 'weaviate-cli local destroy --yes' first to switch Compose files.",
                )

            state = _aggregate_state(existing)
            if state == "running":
                if requested_mode == "default":
                    return self._build_status_payload(
                        existing, action="already_running"
                    )
                assert resolved_compose is not None
                self._run_compose_up(compose_file=resolved_compose)
                action = "updated"
            else:
                if requested_mode == "default":
                    # Running siblings may already own the published ports. Docker
                    # checks for conflicts when binding the stopped services.
                    stopped = [c["name"] for c in existing if not c["running"]]
                    started = self._run_docker(["docker", "start", *stopped])
                    if started.returncode != 0:
                        self._raise_compose_or_port_error(started)
                else:
                    assert resolved_compose is not None
                    self._run_compose_up(compose_file=resolved_compose)
                action = "started"
        else:
            if resolved_compose is None:
                self._check_default_ports_available()
                images: list[tuple[str, str]] = [
                    (WEAVIATE_LATEST_IMAGE, "~150 MB"),
                ]
                if vectorizer == "transformers":
                    images.append((TRANSFORMERS_IMAGE, "~1.2 GB"))
                self._ensure_images_pulled(images)
                yaml_body = render_default_compose_yaml(vectorizer=vectorizer)
                self._emit_progress("Starting local Weaviate cluster...")
                self._run_compose_up(stdin_yaml=yaml_body)
            else:
                self._emit_progress(
                    f"Starting local Weaviate stack from '{resolved_compose}'..."
                )
                self._run_compose_up(compose_file=resolved_compose)

        containers = self._inspect_project_containers()
        http_port, _ = _extract_primary_ports(containers)
        if http_port is not None:
            self._wait_for_ready(http_port)

        return self._build_status_payload(containers, action=action)

    def _run_compose_up(
        self,
        *,
        compose_file: str | None = None,
        stdin_yaml: str | None = None,
    ) -> None:
        cmd = [
            "docker",
            "compose",
            "-p",
            self.project,
            "-f",
            compose_file if compose_file is not None else "-",
            "up",
            "-d",
        ]
        res = self._run_docker(cmd, stdin_text=stdin_yaml)
        if res.returncode != 0:
            self._raise_compose_or_port_error(res)

    def _raise_compose_or_port_error(self, res: CommandResult) -> None:
        detail = (res.stderr or res.stdout).strip()
        lowered = detail.lower()
        if (
            "port is already allocated" in lowered
            or "address already in use" in lowered
        ):
            raise CLIError(
                code="PORT_IN_USE",
                message=f"Port conflict while starting local cluster: {detail}",
                exit_code=ExitCode.CONNECTIVITY,
                hint=(
                    "Stop the conflicting process or change published ports in a "
                    "custom Compose file ('weaviate-cli local template > docker-compose.yml')."
                ),
            )
        raise CLIError(
            code="DOCKER_COMPOSE_FAILED",
            message=f"Failed to start local Docker stack: {detail}",
            exit_code=ExitCode.RUNTIME,
        )

    def status(self, *, show_env: bool = False) -> dict[str, Any]:
        """Inspect status of the managed local Weaviate stack."""
        self._ensure_docker_ready(require_compose=False)
        containers = self._inspect_project_containers()
        return self._build_status_payload(
            containers, check_unmanaged_port=True, show_env=show_env
        )

    def stop(self) -> dict[str, Any]:
        """Stop managed local containers while preserving persistent volumes."""
        self._ensure_docker_ready(require_compose=False)
        containers = self._inspect_project_containers()
        if not containers:
            raise CLIError(
                code="LOCAL_NOT_FOUND",
                message="No weaviate-cli-managed local cluster exists.",
                exit_code=ExitCode.NOT_FOUND,
                hint=(
                    "Start one with 'weaviate-cli local start'. "
                    "External Weaviate containers are never modified."
                ),
            )

        running = [c for c in containers if c.get("running")]
        if not running:
            return {
                "project": self.project,
                "state": "stopped",
                "action": "already_stopped",
                "stopped_services": [],
            }

        res = self._run_docker(["docker", "stop", *(c["name"] for c in running)])
        if res.returncode != 0:
            raise CLIError(
                code="DOCKER_ERROR",
                message=f"Failed to stop local containers: {(res.stderr or res.stdout).strip()}",
                exit_code=ExitCode.RUNTIME,
            )
        return {
            "project": self.project,
            "state": "stopped",
            "action": "stopped",
            "stopped_services": [c["service"] for c in running],
        }

    def logs(self, *, service: str = "weaviate", tail: int = 100) -> dict[str, Any]:
        """Return recent container logs for a service in the managed local stack."""
        self._ensure_docker_ready(require_compose=False)
        containers = self._inspect_project_containers()
        if not containers:
            raise CLIError(
                code="LOCAL_NOT_FOUND",
                message="No weaviate-cli-managed local cluster exists.",
                exit_code=ExitCode.NOT_FOUND,
                hint="Start one with 'weaviate-cli local start'.",
            )

        target = next((c for c in containers if c["service"] == service), None)
        if target is None:
            available = ", ".join(sorted(c["service"] for c in containers))
            raise CLIError(
                code="LOCAL_SERVICE_NOT_FOUND",
                message=f"Service '{service}' was not found in the local cluster.",
                exit_code=ExitCode.NOT_FOUND,
                hint=f"Available services: {available}.",
            )

        res = self._run_docker(["docker", "logs", "--tail", str(tail), target["name"]])
        if res.returncode != 0:
            raise CLIError(
                code="DOCKER_ERROR",
                message=f"Failed to fetch logs for '{service}': {(res.stderr or res.stdout).strip()}",
                exit_code=ExitCode.RUNTIME,
            )
        parts = [p for p in (res.stdout, res.stderr) if p]
        combined = "\n".join(p.rstrip("\n") for p in parts)
        return {
            "project": self.project,
            "service": target["service"],
            "container": target["name"],
            "tail": tail,
            "logs": combined,
        }

    def _list_project_resources(self, kind: Literal["network", "volume"]) -> list[str]:
        label_filter = f"label={COMPOSE_PROJECT_LABEL}={self.project}"
        result = self._run_docker(
            ["docker", kind, "ls", "--filter", label_filter, "--format", "{{.Name}}"]
        )
        if result.returncode != 0:
            raise CLIError(
                "DOCKER_ERROR",
                f"Failed to list local {kind}s: {(result.stderr or result.stdout).strip()}",
            )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def destroy(self) -> dict[str, Any]:
        """Remove all containers, networks, and volumes owned by `weaviate-cli-local`."""
        self._ensure_docker_ready(require_compose=False)
        containers = self._inspect_project_containers()
        networks = self._list_project_resources("network")
        volumes = self._list_project_resources("volume")

        if not containers and not networks and not volumes:
            warnings: list[str] = []
            unmanaged = self._find_unmanaged_containers_on_port(DEFAULT_HTTP_PORT)
            if unmanaged:
                warnings.append(
                    f"External container '{', '.join(unmanaged)}' on port "
                    f"{DEFAULT_HTTP_PORT} is not managed by weaviate-cli and was not modified."
                )
            return {
                "project": self.project,
                "destroyed": False,
                "already_absent": True,
                "removed_containers": [],
                "removed_networks": [],
                "removed_volumes": [],
                "warnings": warnings,
            }

        removed_containers: list[str] = []
        if containers:
            cnames = [c["name"] for c in containers]
            rm_res = self._run_docker(["docker", "rm", "-f", *cnames])
            if rm_res.returncode != 0:
                raise CLIError(
                    code="DOCKER_ERROR",
                    message=f"Failed to remove local containers: {(rm_res.stderr or rm_res.stdout).strip()}",
                    exit_code=ExitCode.RUNTIME,
                )
            removed_containers = cnames

        removed_networks: list[str] = []
        if networks:
            net_res = self._run_docker(["docker", "network", "rm", *networks])
            if net_res.returncode != 0:
                raise CLIError(
                    "DOCKER_ERROR",
                    f"Failed to remove local networks: {(net_res.stderr or net_res.stdout).strip()}",
                )
            removed_networks = networks

        removed_volumes: list[str] = []
        if volumes:
            vol_res = self._run_docker(["docker", "volume", "rm", *volumes])
            if vol_res.returncode != 0:
                raise CLIError(
                    code="DOCKER_ERROR",
                    message=f"Failed to remove local volumes: {(vol_res.stderr or vol_res.stdout).strip()}",
                    exit_code=ExitCode.RUNTIME,
                )
            removed_volumes = volumes

        return {
            "project": self.project,
            "destroyed": True,
            "already_absent": False,
            "removed_containers": removed_containers,
            "removed_networks": removed_networks,
            "removed_volumes": removed_volumes,
            "warnings": [],
        }
