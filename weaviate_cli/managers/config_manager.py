import json
import os
import socket
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import click
import weaviate
from weaviate.config import AdditionalConfig
from weaviate.config import Timeout as WeaviateTimeout
from weaviate.exceptions import WeaviateGRPCUnavailableError

from weaviate_cli.errors import CLIError, ExitCode

_WEAVIATE_ENV_KEYS: frozenset[str] = frozenset(
    {"WEAVIATE_URL", "WEAVIATE_API_KEY", "WEAVIATE_GRPC_URL"}
)
_LOOKALIKE_ENV_KEYS: frozenset[str] = frozenset(
    {
        "WEAVIATE_CLOUD_URL",
        "WEAVIATE_CLOUD_API_KEY",
        "WCD_URL",
        "WCD_API_KEY",
        "WCS_URL",
        "WCS_API_KEY",
    }
)


def parse_env_file(path: str | Path) -> dict[str, str]:
    """Parse a dotenv-style KEY=VALUE file without mutating os.environ."""
    env_path = Path(path)
    if not env_path.is_file():
        raise CLIError(
            code="ENV_FILE_NOT_FOUND",
            message=f"Env file '{path}' does not exist.",
            exit_code=ExitCode.USAGE,
            hint="Pass an existing .env file to --env-file or set WEAVIATE_URL/WEAVIATE_API_KEY.",
        )

    parsed: dict[str, str] = {}
    for lineno, raw_line in enumerate(
        env_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise CLIError(
                code="INVALID_ENV_FILE",
                message=f"Invalid syntax in env file '{path}' at line {lineno}: expected KEY=VALUE.",
                exit_code=ExitCode.USAGE,
                hint="Each non-comment line in --env-file must be formatted as KEY=VALUE.",
            )
        key, raw_val = line.split("=", 1)
        key = key.strip()
        if not key:
            raise CLIError(
                code="INVALID_ENV_FILE",
                message=f"Empty variable name in env file '{path}' at line {lineno}.",
                exit_code=ExitCode.USAGE,
            )
        val = raw_val.strip()
        if val and val[0] in ("'", '"'):
            quote = val[0]
            chars: list[str] = []
            idx = 1
            closed = False
            while idx < len(val):
                ch = val[idx]
                if quote == '"' and ch == "\\" and idx + 1 < len(val):
                    nxt = val[idx + 1]
                    escape_map = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
                    chars.append(escape_map.get(nxt, "\\" + nxt))
                    idx += 2
                    continue
                if ch == quote:
                    closed = True
                    break
                chars.append(ch)
                idx += 1
            if not closed:
                raise CLIError(
                    code="INVALID_ENV_FILE",
                    message=(
                        f"Unterminated quote in env file '{path}' at line {lineno}."
                    ),
                    exit_code=ExitCode.USAGE,
                )
            val = "".join(chars)
        else:
            # Strip trailing inline comments preceded by whitespace in unquoted values.
            for idx, ch in enumerate(val):
                if ch == "#" and idx > 0 and val[idx - 1].isspace():
                    val = val[:idx].rstrip()
                    break
        parsed[key] = val

    return parsed


class ConfigManager:
    """Weaviate CLI configuration manager.

    Connection precedence (highest to lowest):
      1. Explicit CLI flags (--url, --api-key, --grpc-url)
      2. Explicit env file (--env-file <path>)
      3. Environment variables (WEAVIATE_URL, WEAVIATE_API_KEY, WEAVIATE_GRPC_URL)
      4. --config-file <path>
      5. Default config file (~/.config/weaviate/config.json)
      6. Default localhost (localhost:8080, gRPC 50051)
    """

    default_file_path: str = ".config/weaviate/"
    default_file_name: str = "config.json"
    default_host: str = "localhost"
    default_port: int = 8080
    default_grpc_port: int = 50051

    def __init__(
        self,
        config_file: str | None = None,
        user: str | None = None,
        *,
        env_file: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
        grpc_url: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        """Initialize config manager with explicit flags, env file, env vars, and optional config file."""
        self.user = user
        self._env: Mapping[str, str] = os.environ if env is None else env
        self.env_file: str | None = env_file
        self.config_file_loaded: bool = False
        self.source: str = "default_localhost"
        self.config: dict[str, Any] = {}

        if config_file:
            if not os.path.isfile(config_file):
                raise CLIError(
                    code="CONFIG_NOT_FOUND",
                    message=f"Config file '{config_file}' does not exist.",
                    exit_code=ExitCode.USAGE,
                    hint="Pass an existing JSON config file to --config-file or use WEAVIATE_URL/WEAVIATE_API_KEY.",
                )
            self.config_path: str | Path = config_file
            self.config = self._load_json_config(self.config_path)
            self.config_file_loaded = True
            self.source = "config_file"
        else:
            home = self._env.get("HOME") or os.getenv("HOME") or str(Path.home())
            self.config_path = Path(
                os.path.join(home, self.default_file_path, self.default_file_name)
            )
            if self.config_path.exists():
                self.config = self._load_json_config(self.config_path)
                self.config_file_loaded = True
                self.source = "default_config"
            else:
                self.create_default_config()
                self.source = "default_localhost"

        # Overlay environment source (explicit --env-file beats ambient env vars,
        # and does not mix ambient WEAVIATE_* variables into the chosen env file).
        if env_file is not None:
            file_env = parse_env_file(env_file)
            env_url = file_env.get("WEAVIATE_URL", "").strip()
            env_api_key = file_env.get("WEAVIATE_API_KEY", "").strip()
            env_grpc_url = file_env.get("WEAVIATE_GRPC_URL", "").strip()
            if not (env_url or env_api_key or env_grpc_url):
                lookalikes = sorted(k for k in file_env if k in _LOOKALIKE_ENV_KEYS)
                hint = (
                    f"Found unrecognized key(s): {', '.join(lookalikes)}. "
                    "Use WEAVIATE_URL, WEAVIATE_API_KEY, and optional WEAVIATE_GRPC_URL."
                    if lookalikes
                    else (
                        f"Define WEAVIATE_URL (and WEAVIATE_API_KEY if required) in '{env_file}'."
                    )
                )
                raise CLIError(
                    code="INVALID_ENV_FILE",
                    message=(
                        f"Env file '{env_file}' does not define WEAVIATE_URL, "
                        "WEAVIATE_API_KEY, or WEAVIATE_GRPC_URL."
                    ),
                    exit_code=ExitCode.USAGE,
                    hint=hint,
                )
            if "SLOW_CONNECTION" in file_env:
                self._env = {
                    **self._env,
                    "SLOW_CONNECTION": file_env["SLOW_CONNECTION"],
                }
            env_source = "env_file"
        else:
            env_url = self._env.get("WEAVIATE_URL", "").strip()
            env_api_key = self._env.get("WEAVIATE_API_KEY", "").strip()
            env_grpc_url = self._env.get("WEAVIATE_GRPC_URL", "").strip()
            env_source = "env"

        if env_url:
            self._apply_url_override(env_url)
            self.source = env_source
        if env_grpc_url:
            self._apply_grpc_url_override(env_grpc_url)
            if self.source == "default_localhost":
                self.source = env_source
        if env_api_key:
            self.config["auth"] = {"type": "api_key", "api_key": env_api_key}
            if self.source == "default_localhost":
                self.source = env_source

        # Overlay explicit CLI flags (highest precedence).
        if url and url.strip():
            self._apply_url_override(url.strip())
            self.source = "flag"
        if grpc_url and grpc_url.strip():
            self._apply_grpc_url_override(grpc_url.strip())
            if self.source != "flag":
                self.source = "flag"
        if api_key and api_key.strip():
            self.config["auth"] = {"type": "api_key", "api_key": api_key.strip()}
            if self.source != "flag":
                self.source = "flag"

    def _load_json_config(self, path: str | Path) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as config_data:
            try:
                loaded = json.load(config_data)
            except json.JSONDecodeError as exc:
                raise CLIError(
                    code="INVALID_CONFIG",
                    message=(
                        f"Config file '{path}' is not valid JSON "
                        f"(line {exc.lineno}, column {exc.colno}: {exc.msg})."
                    ),
                    exit_code=ExitCode.USAGE,
                    hint="Fix the JSON syntax in your config file or use WEAVIATE_URL and WEAVIATE_API_KEY.",
                ) from exc
        if not isinstance(loaded, dict):
            raise CLIError(
                code="INVALID_CONFIG",
                message=f"Config file '{path}' must contain a JSON object.",
                exit_code=ExitCode.USAGE,
            )
        return loaded

    def _apply_url_override(self, raw_url: str) -> None:
        cleaned = raw_url.rstrip("/")
        self.config["host"] = cleaned
        # Clear inherited localhost ports when switching to an explicit URL so
        # scheme defaults (443 for https, 80 for http) or URL ports take effect.
        if self.__is_url(cleaned):
            parsed = urlparse(cleaned)
            self.config["http_port"] = self.__get_port(parsed)

    def _apply_grpc_url_override(self, raw_grpc_url: str) -> None:
        cleaned = raw_grpc_url.rstrip("/")
        if self.__is_url(cleaned):
            parsed = urlparse(cleaned)
            self.config["grpc_host"] = cleaned
            self.config["grpc_port"] = self.__get_port(parsed)
            return
        if ":" in cleaned and not cleaned.startswith("["):
            host_part, port_part = cleaned.rsplit(":", 1)
            if host_part and port_part.isdigit():
                self.config["grpc_host"] = host_part
                self.config["grpc_port"] = int(port_part)
                return
        self.config["grpc_host"] = cleaned

    @property
    def target_description(self) -> str:
        """Human-readable summary of the resolved target host (never includes secrets)."""
        host = str(self.config.get("host", self.default_host)).rstrip("/")
        if host == "localhost":
            port = self.config.get("http_port", self.default_port)
            return f"localhost:{port}"
        return host

    @property
    def rest_base_url(self) -> str:
        """Resolved HTTP(S) base URL for the target Weaviate instance (no trailing slash)."""
        host = str(self.config.get("host", self.default_host)).rstrip("/")
        if self.__is_url(host):
            return host
        if host.endswith("weaviate.cloud"):
            return f"https://{host}"
        http_port = int(self.config.get("http_port", self.default_port))
        scheme = "https" if http_port == 443 else "http"
        if (scheme == "https" and http_port == 443) or (
            scheme == "http" and http_port == 80
        ):
            return f"{scheme}://{host}"
        return f"{scheme}://{host}:{http_port}"

    def get_api_key(self) -> str | None:
        """Return the configured Bearer API key if auth is configured, else None."""
        auth_section = self.config.get("auth")
        if not isinstance(auth_section, dict):
            return None
        if auth_section.get("type") == "api_key":
            val = auth_section.get("api_key")
            return str(val) if val else None
        if auth_section.get("type") == "user" and self.user:
            val = auth_section.get(self.user)
            return str(val) if val else None
        return None

    def _resolve_grpc_details(self) -> dict[str, Any]:
        """Resolve effective gRPC host, port, and TLS mode without network calls."""
        raw_host = str(self.config.get("host", self.default_host)).rstrip("/")
        if raw_host == "localhost":
            grpc_port = int(self.config.get("grpc_port", self.default_grpc_port))
            return {"host": "localhost", "port": grpc_port, "secure": False}

        if self._is_weaviate_cloud_host(raw_host):
            hostname = (
                urlparse(raw_host).hostname if self.__is_url(raw_host) else raw_host
            ) or raw_host
            raw_grpc = self.config.get("grpc_host")
            if raw_grpc:
                raw_grpc_str = str(raw_grpc).rstrip("/")
                if self.__is_url(raw_grpc_str):
                    gp = urlparse(raw_grpc_str)
                    return {
                        "host": gp.hostname or raw_grpc_str,
                        "port": self.__get_port(gp),
                        "secure": gp.scheme == "https",
                    }
                grpc_port = int(self.config.get("grpc_port", 443))
                return {
                    "host": raw_grpc_str,
                    "port": grpc_port,
                    "secure": grpc_port == 443,
                }
            return {"host": f"grpc-{hostname}", "port": 443, "secure": True}

        if self.__is_url(raw_host):
            host_parsed = urlparse(raw_host)
            raw_grpc = self.config.get("grpc_host")
            if raw_grpc:
                raw_grpc_str = str(raw_grpc).rstrip("/")
                if self.__is_url(raw_grpc_str):
                    gp = urlparse(raw_grpc_str)
                    grpc_port = (
                        self.__get_port(gp)
                        if "grpc_port" not in self.config
                        or self.config["grpc_port"] == ""
                        else int(self.config["grpc_port"])
                    )
                    return {
                        "host": gp.hostname or raw_grpc_str,
                        "port": grpc_port,
                        "secure": gp.scheme == "https",
                    }
                grpc_port = int(self.config.get("grpc_port", self.default_grpc_port))
                return {
                    "host": raw_grpc_str,
                    "port": grpc_port,
                    "secure": grpc_port == 443,
                }
            grpc_secure = host_parsed.scheme == "https"
            grpc_port = (
                443
                if grpc_secure
                else int(self.config.get("grpc_port", self.default_grpc_port))
            )
            return {
                "host": host_parsed.hostname or raw_host,
                "port": grpc_port,
                "secure": grpc_secure,
            }

        grpc_port = int(self.config.get("grpc_port", self.default_grpc_port))
        grpc_host = str(self.config.get("grpc_host", raw_host))
        return {"host": grpc_host, "port": grpc_port, "secure": grpc_port == 443}

    def describe_connection(self) -> dict[str, Any]:
        """Return resolved connection settings with all secret values redacted."""
        auth_section = self.config.get("auth")
        auth_type = "none"
        configured_users: list[str] = []
        if isinstance(auth_section, dict):
            raw_type = auth_section.get("type")
            if raw_type in {"api_key", "user"}:
                auth_type = str(raw_type)
            if auth_type == "user":
                configured_users = sorted(
                    str(k) for k in auth_section.keys() if k != "type"
                )

        api_key = self.get_api_key()
        auth_info: dict[str, Any] = {
            "configured": api_key is not None,
            "type": auth_type,
            "api_key": "***REDACTED***" if api_key is not None else None,
        }
        if self.user is not None:
            auth_info["user"] = self.user
        if configured_users:
            auth_info["available_users"] = configured_users

        raw_headers = self.config.get("headers")
        header_names = (
            sorted(str(k) for k in raw_headers.keys())
            if isinstance(raw_headers, dict)
            else []
        )

        return {
            "target": self.target_description,
            "rest_url": self.rest_base_url,
            "mcp_endpoint": f"{self.rest_base_url}/v1/mcp",
            "grpc": self._resolve_grpc_details(),
            "source": self.source,
            "env_file": self.env_file,
            "config_file": str(self.config_path) if self.config_file_loaded else None,
            "auth": auth_info,
            "header_names": header_names,
            "slow_connection": self.__additional_config_if_slow() is not None,
        }

    def create_default_config(self) -> None:
        """Populate default localhost configuration."""
        self.config = {
            "host": f"{self.default_host}",
            "http_port": f"{self.default_port}",
            "grpc_port": f"{self.default_grpc_port}",
        }

    def __check_host_docker_internal(self, port: int = 8080) -> bool:
        """Check if host.docker.internal is reachable."""
        try:
            fd = socket.create_connection(
                ("host.docker.internal", int(port)), timeout=2
            )
            fd.close()
            return True
        except (TimeoutError, OSError):
            return False

    def __get_host(self, port: int = 8080) -> str:
        """Determine the appropriate local host based on the environment."""
        if self.__check_host_docker_internal(port):
            return "host.docker.internal"
        return "localhost"

    def __get_port(self, url_parsed: Any) -> int:
        if url_parsed.port:
            return int(url_parsed.port)
        if url_parsed.scheme == "https":
            return 443
        return 80

    def __is_url(self, host: str) -> bool:
        """Check if the host is a URL (has a scheme and a network location)."""
        try:
            result = urlparse(host)
            return all([result.scheme, result.netloc])
        except ValueError:
            return False

    def _is_weaviate_cloud_host(self, host: str) -> bool:
        cleaned = host.rstrip("/")
        if self.__is_url(cleaned):
            hostname = urlparse(cleaned).hostname or ""
            return hostname.endswith("weaviate.cloud")
        return cleaned.endswith("weaviate.cloud")

    def get_client(self) -> weaviate.WeaviateClient:
        """Get synchronous Weaviate client from config."""
        return self._create_client(async_client=False)  # type: ignore[return-value]

    def get_async_client(self) -> weaviate.WeaviateAsyncClient:
        """Get asynchronous Weaviate client from config."""
        return self._create_client(async_client=True)  # type: ignore[return-value]

    def _create_client(
        self, async_client: bool
    ) -> weaviate.WeaviateClient | weaviate.WeaviateAsyncClient:
        """Internal method to create client based on async flag."""
        auth_config: weaviate.auth.AuthCredentials | None = None
        additional_config: AdditionalConfig | None = self.__additional_config_if_slow()

        if "auth" in self.config:
            auth_section = self.config["auth"]
            if auth_section.get("type") == "user":
                if not self.user:
                    raise CLIError(
                        code="MISSING_USER",
                        message="User must be specified when auth type is 'user'",
                        exit_code=ExitCode.USAGE,
                        hint="Pass --user <username> matching a key in your config file's 'auth' block.",
                    )
                if self.user not in auth_section:
                    raise CLIError(
                        code="UNKNOWN_USER",
                        message=f"User '{self.user}' not found in config file",
                        exit_code=ExitCode.USAGE,
                    )
                auth_config = weaviate.auth.AuthApiKey(api_key=auth_section[self.user])
            elif auth_section.get("type") == "api_key":
                auth_config = weaviate.auth.AuthApiKey(api_key=auth_section["api_key"])

        headers = self.config["headers"] if "headers" in self.config else None
        raw_host = str(self.config["host"]).rstrip("/")

        # Localhost handling uses special helpers
        if raw_host == "localhost":
            http_port = int(self.config["http_port"])
            grpc_port = int(self.config["grpc_port"])
            common_kwargs: dict[str, Any] = dict(
                host=self.__get_host(http_port),
                port=http_port,
                grpc_port=grpc_port,
                auth_credentials=auth_config,
                headers=headers,
                additional_config=additional_config,
            )
            if async_client:
                return weaviate.use_async_with_local(**common_kwargs)
            return weaviate.connect_to_local(**common_kwargs)

        # Weaviate Cloud handling with retry fallback (warnings strictly on stderr)
        if self._is_weaviate_cloud_host(raw_host):
            common_kwargs = dict(
                cluster_url=raw_host,
                auth_credentials=auth_config,
                headers=headers,
                additional_config=additional_config,
            )
            if async_client:
                try:
                    return weaviate.use_async_with_weaviate_cloud(**common_kwargs)
                except WeaviateGRPCUnavailableError as exc:
                    click.echo(
                        f"Warning: gRPC connection seems unavailable; reconnecting without init checks: {exc}",
                        err=True,
                    )
                    return weaviate.use_async_with_weaviate_cloud(
                        **{**common_kwargs, "skip_init_checks": True}
                    )
            try:
                return weaviate.connect_to_weaviate_cloud(**common_kwargs)
            except WeaviateGRPCUnavailableError as exc:
                click.echo(
                    f"Warning: gRPC connection seems unavailable; reconnecting without init checks: {exc}",
                    err=True,
                )
                return weaviate.connect_to_weaviate_cloud(
                    **{**common_kwargs, "skip_init_checks": True}
                )

        # Custom host handling (URL vs hostname/IP)
        if self.__is_url(raw_host):
            host_parsed = urlparse(raw_host)
            raw_grpc = self.config.get("grpc_host")
            if raw_grpc:
                raw_grpc_str = str(raw_grpc).rstrip("/")
                if self.__is_url(raw_grpc_str):
                    grpc_parsed = urlparse(raw_grpc_str)
                    grpc_host = grpc_parsed.hostname
                    grpc_secure = grpc_parsed.scheme == "https"
                    grpc_port = (
                        self.__get_port(grpc_parsed)
                        if "grpc_port" not in self.config
                        or self.config["grpc_port"] == ""
                        else int(self.config["grpc_port"])
                    )
                else:
                    grpc_host = raw_grpc_str
                    grpc_port = int(
                        self.config.get("grpc_port", self.default_grpc_port)
                    )
                    grpc_secure = grpc_port == 443
            else:
                grpc_host = host_parsed.hostname
                grpc_secure = host_parsed.scheme == "https"
                grpc_port = (
                    443
                    if grpc_secure
                    else int(self.config.get("grpc_port", self.default_grpc_port))
                )

            http_port = (
                self.__get_port(host_parsed)
                if "http_port" not in self.config or self.config["http_port"] == ""
                else int(self.config["http_port"])
            )
            common_kwargs = dict(
                http_host=host_parsed.hostname,
                grpc_host=grpc_host,
                grpc_secure=grpc_secure,
                http_secure=host_parsed.scheme == "https",
                http_port=http_port,
                grpc_port=grpc_port,
                auth_credentials=auth_config,
                headers=headers,
                additional_config=additional_config,
            )
        else:
            http_port = int(self.config.get("http_port", self.default_port))
            grpc_port = int(self.config.get("grpc_port", self.default_grpc_port))
            grpc_host = self.config.get("grpc_host", raw_host)
            common_kwargs = dict(
                http_host=raw_host,
                grpc_host=grpc_host,
                grpc_secure=grpc_port == 443,
                http_secure=http_port == 443,
                http_port=http_port,
                grpc_port=grpc_port,
                auth_credentials=auth_config,
                headers=headers,
                additional_config=additional_config,
            )

        if async_client:
            return weaviate.use_async_with_custom(**common_kwargs)
        return weaviate.connect_to_custom(**common_kwargs)

    def __additional_config_if_slow(self) -> AdditionalConfig | None:
        """Return AdditionalConfig with doubled timeouts when SLOW_CONNECTION is set."""
        env_flag = self._env.get("SLOW_CONNECTION") or os.getenv("SLOW_CONNECTION")
        if not env_flag:
            return None
        if str(env_flag).strip().lower() not in {"1", "true", "yes", "on"}:
            return None
        defaults = AdditionalConfig().timeout
        return AdditionalConfig(
            timeout=WeaviateTimeout(
                query=defaults.query * 2,
                insert=defaults.insert * 2,
                init=defaults.init * 2,
            )
        )
