"""Pure data-returning adapter for cluster health, metadata, RBAC identity, and MCP probe."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from weaviate import WeaviateClient
from weaviate.exceptions import (
    AuthenticationFailedError,
    InsufficientPermissionsError,
    MissingScopeError,
    UnexpectedStatusCodeError,
)

from weaviate_cli import __version__

_VECTORIZER_PREFIXES: tuple[str, ...] = (
    "text2vec-",
    "multi2vec-",
    "img2vec-",
    "ref2vec-",
)

McpProbeFn = Callable[[str, str | None], dict[str, Any]]


def _is_forbidden_error(exc: Exception) -> bool:
    if isinstance(exc, (InsufficientPermissionsError, MissingScopeError)):
        return True
    if isinstance(exc, UnexpectedStatusCodeError):
        return getattr(exc, "status_code", None) == 403
    return False


def _is_auth_or_not_supported_error(exc: Exception) -> bool:
    if isinstance(
        exc,
        (AuthenticationFailedError, InsufficientPermissionsError, MissingScopeError),
    ):
        return True
    if isinstance(exc, UnexpectedStatusCodeError):
        return getattr(exc, "status_code", None) in {401, 403, 404, 405, 501}
    return False


def probe_mcp_endpoint(
    rest_base_url: str,
    api_key: str | None = None,
    *,
    timeout: float = 3.0,
) -> dict[str, Any]:
    """Probe Weaviate's native /v1/mcp Streamable HTTP endpoint."""
    endpoint = f"{rest_base_url.rstrip('/')}/v1/mcp"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "weaviate-cli", "version": __version__},
        },
    }
    try:
        response = httpx.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )
    except httpx.HTTPError:
        return {"endpoint": endpoint, "available": None}

    if response.status_code == 404:
        return {"endpoint": endpoint, "available": False}
    if 200 <= response.status_code < 300:
        return {"endpoint": endpoint, "available": True}
    if response.status_code in {401, 403}:
        return {"endpoint": endpoint, "available": True, "auth_required": True}
    return {
        "endpoint": endpoint,
        "available": None,
        "status_code": response.status_code,
    }


class StatusManager:
    """Inspect Weaviate cluster readiness, metadata, enabled modules, and accessible resources."""

    def __init__(
        self,
        client: WeaviateClient,
        *,
        target: str,
        config_source: str,
        rest_base_url: str | None = None,
        api_key: str | None = None,
        mcp_probe: McpProbeFn | None = None,
    ) -> None:
        self.client = client
        self.target = target
        self.config_source = config_source
        self.rest_base_url = rest_base_url
        self.api_key = api_key
        self._mcp_probe: McpProbeFn = (
            probe_mcp_endpoint if mcp_probe is None else mcp_probe
        )

    def get_status(self) -> dict[str, Any]:
        """Collect cluster status, degrading gracefully on RBAC-restricted sub-checks."""
        warnings: list[str] = []

        live = bool(self.client.is_live())
        ready = bool(self.client.is_ready())
        meta = self.client.get_meta()

        version = meta.get("version") if isinstance(meta, dict) else None
        hostname = meta.get("hostname") if isinstance(meta, dict) else None
        raw_modules = meta.get("modules") if isinstance(meta, dict) else None
        modules = (
            sorted(str(k) for k in raw_modules.keys())
            if isinstance(raw_modules, dict)
            else []
        )
        vectorizers = [mod for mod in modules if mod.startswith(_VECTORIZER_PREFIXES)]

        user_info = self._inspect_user()
        collections_info = self._inspect_collections(warnings)
        nodes_info = self._inspect_nodes(warnings)
        mcp_info = (
            self._mcp_probe(self.rest_base_url, self.api_key)
            if self.rest_base_url
            else None
        )

        return {
            "target": self.target,
            "config_source": self.config_source,
            "live": live,
            "ready": ready,
            "version": version,
            "hostname": hostname,
            "user": user_info,
            "collections": collections_info,
            "nodes": nodes_info,
            "vectorizers": vectorizers,
            "modules": modules,
            "mcp": mcp_info,
            "warnings": warnings,
        }

    def _inspect_user(self) -> dict[str, Any] | None:
        try:
            own_user = self.client.users.get_my_user()
        except Exception as exc:
            if _is_auth_or_not_supported_error(exc):
                return None
            return None

        user_id = getattr(own_user, "user_id", None)
        roles_obj = getattr(own_user, "roles", None)
        if isinstance(roles_obj, dict):
            roles = sorted(str(k) for k in roles_obj.keys())
        elif isinstance(roles_obj, (list, set, tuple)):
            roles = sorted(str(r) for r in roles_obj)
        else:
            roles = []
        return {"user_id": user_id, "roles": roles}

    def _inspect_collections(self, warnings: list[str]) -> dict[str, Any]:
        try:
            collections = self.client.collections.list_all(simple=True)
        except Exception as exc:
            if _is_forbidden_error(exc):
                msg = "Insufficient permissions to list collections (read_collections)."
                warnings.append(msg)
                return {"accessible": False, "error": msg}
            raise

        names = sorted(str(name) for name in collections.keys())
        return {
            "accessible": True,
            "count": len(names),
            "names": names,
        }

    def _inspect_nodes(self, warnings: list[str]) -> dict[str, Any]:
        try:
            nodes = self.client.cluster.nodes(output="minimal")
        except Exception as exc:
            if _is_forbidden_error(exc):
                msg = "Insufficient permissions to read cluster nodes (read_nodes)."
                warnings.append(msg)
                return {"accessible": False, "error": msg}
            raise

        summaries: list[dict[str, Any]] = []
        healthy = 0
        for node in nodes:
            status_val = getattr(node, "status", None)
            status_str = str(getattr(status_val, "value", status_val))
            if status_str.upper() == "HEALTHY":
                healthy += 1
            summaries.append(
                {
                    "name": getattr(node, "name", None),
                    "status": status_str,
                    "version": getattr(node, "version", None),
                }
            )

        return {
            "accessible": True,
            "count": len(summaries),
            "healthy": healthy,
            "nodes": summaries,
        }
