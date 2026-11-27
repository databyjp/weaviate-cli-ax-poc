"""Weaviate Cloud (`wcloud`) delegation manager with verified install and key capture."""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from weaviate_cli.credentials import (
    KeyDestination,
    require_key_destination,
    reserve_key_file,
)
from weaviate_cli.errors import CLIError, ExitCode

WCLOUD_VERSION = "0.1.4"
WCLOUD_RELEASE_BASE_URL = (
    f"https://github.com/weaviate/weaviate-cloud/releases/download/v{WCLOUD_VERSION}"
)

# Pinned release archive names and SHA-256 digests from wcloud v0.1.4 checksums.txt.
WCLOUD_ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("darwin", "amd64"): (
        f"weaviate-cloud_{WCLOUD_VERSION}_darwin_amd64.tar.gz",
        "69723755903052d713e2707d0e56e96d707b841020e929f54a2cff416053cf8e",
    ),
    ("darwin", "arm64"): (
        f"weaviate-cloud_{WCLOUD_VERSION}_darwin_arm64.tar.gz",
        "c23aebc03c8e5c639d5da5749ddede2ca39966bf66b29e10086f9d167c51735f",
    ),
    ("linux", "amd64"): (
        f"weaviate-cloud_{WCLOUD_VERSION}_linux_amd64.tar.gz",
        "83aabc2b742012172e23cebef524ec41a776e88e43ba55e5d4240fc822525724",
    ),
    ("linux", "arm64"): (
        f"weaviate-cloud_{WCLOUD_VERSION}_linux_arm64.tar.gz",
        "540bce2c319c1d1c0450b02d2126d20fec689e5425d6b575d55c6a855d7dff7e",
    ),
    ("windows", "amd64"): (
        f"weaviate-cloud_{WCLOUD_VERSION}_windows_amd64.zip",
        "c4348bfd3d201f70e72f407c3d0a5b90493186f78e6a2d1132103cbd2e3f24d0",
    ),
}

WCLOUD_INSTALL_HINT = (
    "Install wcloud via 'weaviate-cli cloud install-wcloud' (SHA-256 verified), "
    "'brew install weaviate/tap/weaviate-cloud', 'npm install -g weaviate-cloud', "
    "or point WEAVIATE_WCLOUD_PATH to an existing binary."
)

FREE_TIER_LIMITS: dict[str, Any] = {
    "max_collections": 1,
    "max_tenants_per_collection": 3,
    "max_objects": 100_000,
    "vector_index": "hfresh",
    "region": "eu-central-1",
    "cloud_provider": "aws",
    "backups": False,
    "high_availability": False,
    "max_free_clusters_per_user": 1,
    "delete_or_wake": "console_only",
    "console_url": "https://console.weaviate.cloud",
}

FREE_TIER_LIMITS_SUMMARY = (
    "1 collection, 3 tenants/collection, 100,000 objects, hfresh vector index only, "
    "no backups or HA, 1 free cluster/user; delete/wake at https://console.weaviate.cloud."
)


def _attach_tier_limits(cluster: dict[str, Any]) -> dict[str, Any]:
    """Attach free-tier limits metadata when wcloud does not return structured limits."""
    tier = str(cluster.get("tier") or "").strip().lower()
    if tier == "free" and "limits" not in cluster and "tier_limits" not in cluster:
        return {**cluster, "tier_limits": dict(FREE_TIER_LIMITS)}
    return cluster


@dataclass(frozen=True)
class CommandResult:
    """Captured output of a subprocess execution."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str]], CommandResult]
InteractiveRunner = Callable[[Sequence[str]], int]
Downloader = Callable[[str], bytes]
PromptFn = Callable[[str], bool]
ProgressFn = Callable[[str], None]
WhichFn = Callable[[str], str | None]
GitIgnoredChecker = Callable[[Path], bool | None]


def _default_git_ignored_checker(path: Path) -> bool | None:
    """Return True if git ignores `path`, False if inside a git repo and unignored, None otherwise."""
    resolved = path.resolve()
    try:
        completed = subprocess.run(
            ["git", "-C", str(resolved.parent), "check-ignore", "-q", str(resolved)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    return None


def _default_command_runner(args: Sequence[str]) -> CommandResult:
    completed = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _default_interactive_runner(args: Sequence[str]) -> int:
    completed = subprocess.run(list(args), check=False)
    return completed.returncode


def _default_downloader(url: str) -> bytes:
    try:
        response = httpx.get(url, follow_redirects=True, timeout=60.0)
        response.raise_for_status()
        return response.content
    except httpx.HTTPError as exc:
        raise CLIError(
            code="WCLOUD_DOWNLOAD_FAILED",
            message=f"Failed to download wcloud from '{url}': {exc}",
            exit_code=ExitCode.CONNECTIVITY,
            hint=(
                "Verify outbound network access to github.com, or install wcloud "
                "manually via Homebrew ('brew install weaviate/tap/weaviate-cloud') "
                "or npm ('npm install -g weaviate-cloud')."
            ),
        ) from exc


def detect_platform() -> tuple[str, str]:
    """Return normalized (os, arch) matching wcloud GitHub release asset naming."""
    sys_name = platform.system().lower()
    if sys_name.startswith("darwin"):
        os_name = "darwin"
    elif sys_name.startswith("linux"):
        os_name = "linux"
    elif sys_name.startswith("win"):
        os_name = "windows"
    else:
        os_name = sys_name

    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = machine
    return os_name, arch


def default_wcloud_cache_dir(env: Mapping[str, str] | None = None) -> Path:
    """Return the managed cache directory for `wcloud`."""
    source_env = os.environ if env is None else env
    explicit = source_env.get("WEAVIATE_CLI_CACHE_DIR", "").strip()
    if explicit:
        return Path(explicit) / "bin"
    xdg = source_env.get("XDG_CACHE_HOME", "").strip()
    if xdg:
        return Path(xdg) / "weaviate-cli" / "bin"
    home = source_env.get("HOME") or str(Path.home())
    return Path(home) / ".cache" / "weaviate-cli" / "bin"


def _binary_filename(os_name: str) -> str:
    return "wcloud.exe" if os_name == "windows" else "wcloud"


def _extract_wcloud_binary(
    archive_bytes: bytes, *, asset_name: str, binary_name: str
) -> bytes:
    """Safely extract the `wcloud` binary bytes from a .tar.gz or .zip release archive."""
    if asset_name.endswith(".tar.gz"):
        try:
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tf:
                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    if Path(member.name).name == binary_name:
                        extracted = tf.extractfile(member)
                        if extracted is not None:
                            return extracted.read()
        except tarfile.TarError as exc:
            raise CLIError(
                code="WCLOUD_EXTRACT_FAILED",
                message=f"Failed to extract '{asset_name}': {exc}",
                exit_code=ExitCode.RUNTIME,
            ) from exc
    elif asset_name.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    if Path(info.filename).name == binary_name:
                        return zf.read(info)
        except zipfile.BadZipFile as exc:
            raise CLIError(
                code="WCLOUD_EXTRACT_FAILED",
                message=f"Failed to extract '{asset_name}': {exc}",
                exit_code=ExitCode.RUNTIME,
            ) from exc

    raise CLIError(
        code="WCLOUD_EXTRACT_FAILED",
        message=f"Release archive '{asset_name}' did not contain '{binary_name}'.",
        exit_code=ExitCode.RUNTIME,
    )


def _normalize_https_endpoint(raw: str | None) -> str | None:
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip().rstrip("/")
    if not cleaned:
        return None
    if "://" not in cleaned:
        return f"https://{cleaned}"
    return cleaned


def extract_cluster_credentials(
    cluster: Mapping[str, Any],
) -> tuple[str | None, str | None, str | None]:
    """Extract (url, grpc_url, one_time_api_key) from a wcloud cluster payload."""
    url = _normalize_https_endpoint(cluster.get("endpoint") or cluster.get("url"))
    raw_grpc = cluster.get("grpc_endpoint") or cluster.get("grpc_url")
    grpc_url = (
        str(raw_grpc).strip()
        if isinstance(raw_grpc, str) and raw_grpc.strip()
        else None
    )

    raw_key = cluster.get("api_key")
    api_key: str | None = None
    if isinstance(raw_key, dict):
        val = raw_key.get("value")
        if isinstance(val, str) and val.strip():
            api_key = val.strip()
    elif isinstance(raw_key, str) and raw_key.strip():
        api_key = raw_key.strip()

    return url, grpc_url, api_key


def _map_wcloud_exit_code(rc: int, error_code: str) -> ExitCode:
    code_lower = error_code.lower()
    if rc == 2 or code_lower in ("validation_failed", "invalid_argument"):
        return ExitCode.USAGE
    if rc in (3, 5) or code_lower in (
        "auth_required",
        "permission_denied",
        "access_restricted",
    ):
        return ExitCode.AUTH
    if rc in (4, 6) or "not_found" in code_lower or "already_exists" in code_lower:
        return ExitCode.NOT_FOUND
    if rc == 9 or code_lower in ("service_unavailable", "network_error"):
        return ExitCode.CONNECTIVITY
    return ExitCode.RUNTIME


def _parse_wcloud_envelope(stdout: str) -> dict[str, Any] | None:
    stripped = stdout.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


class CloudManager:
    """Delegate Weaviate Cloud operations to `wcloud` with safe install, auth, and key capture."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        runner: CommandRunner | None = None,
        interactive_runner: InteractiveRunner | None = None,
        downloader: Downloader | None = None,
        which_fn: WhichFn = shutil.which,
        platform_fn: Callable[[], tuple[str, str]] = detect_platform,
        is_interactive: bool | None = None,
        prompt_fn: PromptFn | None = None,
        progress_callback: ProgressFn | None = None,
        git_ignored_checker: GitIgnoredChecker | None = None,
    ) -> None:
        self._env: Mapping[str, str] = os.environ if env is None else env
        self._runner: CommandRunner = (
            _default_command_runner if runner is None else runner
        )
        self._interactive_runner: InteractiveRunner = (
            _default_interactive_runner
            if interactive_runner is None
            else interactive_runner
        )
        self._downloader: Downloader = (
            _default_downloader if downloader is None else downloader
        )
        self._which = which_fn
        self._platform_fn = platform_fn
        self._is_interactive = (
            (sys.stdin.isatty() and sys.stdout.isatty())
            if is_interactive is None
            else is_interactive
        )
        self._prompt_fn = prompt_fn
        self._progress = progress_callback
        self._git_ignored_checker: GitIgnoredChecker = (
            _default_git_ignored_checker
            if git_ignored_checker is None
            else git_ignored_checker
        )

    def _emit_progress(self, message: str) -> None:
        if self._progress is not None:
            self._progress(message)

    def _confirm_tty(self, prompt_text: str) -> bool:
        if not self._is_interactive or self._prompt_fn is None:
            return False
        return bool(self._prompt_fn(prompt_text))

    def resolve_wcloud_binary(self) -> tuple[Path, str] | None:
        """Resolve `wcloud` user-first: WEAVIATE_WCLOUD_PATH > $PATH > managed cache."""
        override = self._env.get("WEAVIATE_WCLOUD_PATH", "").strip()
        if override:
            override_path = Path(override)
            if override_path.is_file() and os.access(override_path, os.X_OK):
                return override_path, "env_override"
            raise CLIError(
                code="WCLOUD_NOT_FOUND",
                message=f"WEAVIATE_WCLOUD_PATH points to '{override}', which is missing or not executable.",
                exit_code=ExitCode.CONNECTIVITY,
                hint="Fix WEAVIATE_WCLOUD_PATH or unset it to let weaviate-cli resolve wcloud automatically.",
            )

        from_path = self._which("wcloud")
        if from_path:
            return Path(from_path), "path"

        os_name, _ = self._platform_fn()
        cached = default_wcloud_cache_dir(self._env) / _binary_filename(os_name)
        if cached.is_file() and os.access(cached, os.X_OK):
            return cached, "managed_cache"

        return None

    def install_wcloud(
        self, *, install_dir: str | Path | None = None, force: bool = False
    ) -> dict[str, Any]:
        """Download, SHA-256 verify, and install pinned `wcloud` binary into the cache dir."""
        os_name, arch = self._platform_fn()
        asset_entry = WCLOUD_ASSETS.get((os_name, arch))
        if asset_entry is None:
            raise CLIError(
                code="WCLOUD_UNSUPPORTED_PLATFORM",
                message=f"No prebuilt wcloud v{WCLOUD_VERSION} binary is available for {os_name}/{arch}.",
                exit_code=ExitCode.USAGE,
                hint="Install wcloud from source via 'go install github.com/weaviate/weaviate-cloud/cmd/wcloud@latest'.",
            )

        asset_name, expected_sha256 = asset_entry
        binary_name = _binary_filename(os_name)
        target_dir = (
            Path(install_dir)
            if install_dir is not None
            else default_wcloud_cache_dir(self._env)
        )
        dest_path = target_dir / binary_name

        if dest_path.is_file() and os.access(dest_path, os.X_OK) and not force:
            return {
                "version": WCLOUD_VERSION,
                "path": str(dest_path),
                "platform": f"{os_name}/{arch}",
                "sha256": expected_sha256,
                "already_installed": True,
            }

        download_url = f"{WCLOUD_RELEASE_BASE_URL}/{asset_name}"
        self._emit_progress(
            f"Downloading wcloud v{WCLOUD_VERSION} ({os_name}/{arch})..."
        )
        archive_bytes = self._downloader(download_url)

        actual_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        if actual_sha256.lower() != expected_sha256.lower():
            raise CLIError(
                code="WCLOUD_CHECKSUM_MISMATCH",
                message=(
                    f"SHA-256 verification failed for '{asset_name}': "
                    f"expected {expected_sha256}, got {actual_sha256}."
                ),
                exit_code=ExitCode.CONNECTIVITY,
                hint=(
                    "Refusing to install unverified binary. Try again or install via "
                    "'brew install weaviate/tap/weaviate-cloud'."
                ),
            )

        binary_bytes = _extract_wcloud_binary(
            archive_bytes, asset_name=asset_name, binary_name=binary_name
        )

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=target_dir, prefix=".wcloud-", delete=False
            ) as tmp:
                tmp.write(binary_bytes)
                tmp_path = Path(tmp.name)
            try:
                os.chmod(tmp_path, 0o755)
            except OSError:
                pass
            os.replace(tmp_path, dest_path)
        except OSError as exc:
            raise CLIError(
                code="WCLOUD_INSTALL_FAILED",
                message=f"Failed to write wcloud binary to '{dest_path}': {exc}",
                exit_code=ExitCode.RUNTIME,
                hint="Pass --dir <writable-path> or install wcloud on $PATH.",
            ) from exc

        return {
            "version": WCLOUD_VERSION,
            "path": str(dest_path),
            "platform": f"{os_name}/{arch}",
            "sha256": actual_sha256,
            "already_installed": False,
        }

    def ensure_wcloud(self, *, allow_install: bool = False) -> tuple[Path, str]:
        """Resolve `wcloud`, optionally installing via --install-wcloud or interactive TTY prompt."""
        resolved = self.resolve_wcloud_binary()
        if resolved is not None:
            return resolved

        if allow_install:
            installed = self.install_wcloud()
            return Path(installed["path"]), "managed_cache"

        if self._confirm_tty(
            f"wcloud was not found. Download and install wcloud v{WCLOUD_VERSION} "
            "(SHA-256 verified) into cache now?"
        ):
            installed = self.install_wcloud()
            return Path(installed["path"]), "managed_cache"

        raise CLIError(
            code="WCLOUD_NOT_FOUND",
            message="The 'wcloud' CLI binary was not found on PATH or in the managed cache.",
            exit_code=ExitCode.CONNECTIVITY,
            hint=WCLOUD_INSTALL_HINT,
        )

    def _invoke_wcloud_json(
        self, wcloud_bin: Path, args: Sequence[str]
    ) -> dict[str, Any]:
        cmd = [str(wcloud_bin), *args, "-o", "json"]
        try:
            result = self._runner(cmd)
        except FileNotFoundError as exc:
            raise CLIError(
                code="WCLOUD_NOT_FOUND",
                message=f"Could not execute wcloud at '{wcloud_bin}'.",
                exit_code=ExitCode.CONNECTIVITY,
                hint=WCLOUD_INSTALL_HINT,
            ) from exc

        envelope = _parse_wcloud_envelope(result.stdout)
        if result.returncode != 0:
            err_obj = (
                envelope.get("error")
                if isinstance(envelope, dict)
                and isinstance(envelope.get("error"), dict)
                else None
            )
            raw_code = str(err_obj.get("code") or "") if err_obj else ""
            message = (
                str(err_obj.get("message") or "")
                if err_obj
                else (result.stderr or result.stdout).strip()
                or f"wcloud exited with status {result.returncode}."
            )
            details = (
                err_obj.get("details")
                if err_obj and isinstance(err_obj.get("details"), dict)
                else None
            )
            exit_code = _map_wcloud_exit_code(result.returncode, raw_code)
            normalized_code = (
                "WCLOUD_AUTH_REQUIRED"
                if raw_code.lower() == "auth_required" or result.returncode == 3
                else f"WCLOUD_{raw_code.upper()}"
                if raw_code
                else "WCLOUD_ERROR"
            )
            if normalized_code == "WCLOUD_AUTH_REQUIRED":
                hint: str | None = (
                    "Run 'weaviate-cli cloud login' (or 'wcloud auth login') in an "
                    "interactive terminal with a browser."
                )
            elif normalized_code == "WCLOUD_QUOTA_EXCEEDED":
                hint = (
                    "Weaviate Cloud allows 1 free cluster per user across all "
                    "organizations (including SUSPENDED clusters). Manage or delete "
                    "existing clusters at https://console.weaviate.cloud."
                )
            else:
                hint = None
            raise CLIError(
                code=normalized_code,
                message=message,
                exit_code=exit_code,
                hint=hint,
                details=details,
            )

        if envelope is None:
            return {"data": result.stdout.strip(), "metadata": {}}
        return envelope

    def _ensure_authenticated(self, wcloud_bin: Path) -> dict[str, Any]:
        """Pre-check `wcloud auth whoami` to prevent headless OAuth browser hangs."""
        try:
            env = self._invoke_wcloud_json(wcloud_bin, ["auth", "whoami"])
            data = env.get("data")
            return data if isinstance(data, dict) else {}
        except CLIError as exc:
            if exc.code != "WCLOUD_AUTH_REQUIRED":
                raise
            if self._confirm_tty(
                "Not logged in to Weaviate Cloud. Launch browser OAuth login now?"
            ):
                self._run_interactive_login(wcloud_bin)
                env = self._invoke_wcloud_json(wcloud_bin, ["auth", "whoami"])
                data = env.get("data")
                return data if isinstance(data, dict) else {}
            raise

    def _run_interactive_login(
        self,
        wcloud_bin: Path,
        *,
        no_launch_browser: bool = False,
        timeout: str | None = None,
    ) -> None:
        if not self._is_interactive:
            raise CLIError(
                code="WCLOUD_AUTH_INTERACTIVE_REQUIRED",
                message=(
                    "Weaviate Cloud login uses a browser OAuth 2.0 loopback on 127.0.0.1 "
                    "and cannot run in a non-interactive shell."
                ),
                exit_code=ExitCode.AUTH,
                hint=(
                    "Ask the user to run 'weaviate-cli cloud login' (or 'wcloud auth login') "
                    "in an interactive terminal with a local browser."
                ),
            )
        cmd = [str(wcloud_bin), "auth", "login"]
        if no_launch_browser:
            cmd.append("--no-launch-browser")
        if timeout:
            cmd.extend(["--timeout", timeout])
        rc = self._interactive_runner(cmd)
        if rc != 0:
            raise CLIError(
                code="WCLOUD_AUTH_FAILED",
                message=f"wcloud auth login exited with status {rc}.",
                exit_code=ExitCode.AUTH,
                hint="Retry 'weaviate-cli cloud login' and complete sign-in in your browser.",
            )

    def login(
        self,
        *,
        no_launch_browser: bool = False,
        timeout: str | None = None,
        allow_install: bool = False,
    ) -> dict[str, Any]:
        wcloud_bin, source = self.ensure_wcloud(allow_install=allow_install)
        self._run_interactive_login(
            wcloud_bin,
            no_launch_browser=no_launch_browser,
            timeout=timeout,
        )
        whoami = self._invoke_wcloud_json(wcloud_bin, ["auth", "whoami"]).get("data")
        return {
            "authenticated": True,
            "identity": whoami if isinstance(whoami, dict) else {},
            "wcloud_path": str(wcloud_bin),
            "wcloud_source": source,
        }

    def whoami(self, *, allow_install: bool = False) -> dict[str, Any]:
        wcloud_bin, source = self.ensure_wcloud(allow_install=allow_install)
        envelope = self._invoke_wcloud_json(wcloud_bin, ["auth", "whoami"])
        data = envelope.get("data")
        result = dict(data) if isinstance(data, dict) else {"identity": data}
        result["wcloud_path"] = str(wcloud_bin)
        result["wcloud_source"] = source
        return result

    def logout(self, *, allow_install: bool = False) -> dict[str, Any]:
        wcloud_bin, _ = self.ensure_wcloud(allow_install=allow_install)
        envelope = self._invoke_wcloud_json(wcloud_bin, ["auth", "logout"])
        data = envelope.get("data")
        if isinstance(data, dict):
            return {"logged_out": True, **data}
        return {"logged_out": True}

    def list_regions(self, *, allow_install: bool = False) -> dict[str, Any]:
        wcloud_bin, _ = self.ensure_wcloud(allow_install=allow_install)
        self._ensure_authenticated(wcloud_bin)
        envelope = self._invoke_wcloud_json(wcloud_bin, ["region", "list"])
        regions = envelope.get("data")
        region_list = regions if isinstance(regions, list) else []
        return {"regions": region_list, "count": len(region_list)}

    def _attach_credential_handling(
        self,
        cluster: dict[str, Any],
        *,
        destinations: list[KeyDestination],
        include_key: bool,
        waited: bool,
    ) -> tuple[dict[str, Any], list[str]]:
        warnings: list[str] = []
        url, grpc_url, api_key = extract_cluster_credentials(cluster)
        enriched = _attach_tier_limits(dict(cluster))
        if url:
            enriched["url"] = url
        if grpc_url:
            enriched["grpc_url"] = grpc_url

        saved_paths: list[str] = []
        if api_key is not None:
            failed_paths: list[str] = []
            for destination in destinations:
                written = destination.path
                try:
                    destination.save(api_key, url=url, grpc_url=grpc_url)
                except Exception:
                    # The cloud operation already succeeded. Keep its one-time key
                    # available and still attempt any other requested destination.
                    failed_paths.append(str(written))
                    continue
                finally:
                    if destination.retained_original:
                        warnings.append(
                            f"Previous file retained at '{destination.retained_original}'."
                        )
                saved_paths.append(str(written))
                if destination.kind == "env":
                    enriched["next_step"] = f"weaviate-cli --env-file {written} status"
                if self._git_ignored_checker(written) is False:
                    warnings.append(
                        f"'{written}' is inside a Git repository and is not ignored by "
                        ".gitignore. Add it to .gitignore before committing so your API "
                        "key is not exposed."
                    )

            if failed_paths:
                enriched["credential_save_failures"] = failed_paths
            enriched["credentials_saved_to"] = saved_paths
            if saved_paths:
                joined = ", ".join(saved_paths)
                enriched["one_time_api_key_notice"] = (
                    f"One-time admin API key was saved to {joined} (mode 0600). "
                    "Weaviate Cloud displays this key only once — keep that file "
                    "secret (gitignored) and back it up if needed."
                )
                if not include_key:
                    enriched.pop("api_key", None)
            else:
                notice = (
                    "IMPORTANT: This admin API key is displayed ONCE by Weaviate Cloud "
                    "and is NOT stored by wcloud or weaviate-cli. Prompt the user to "
                    "save WEAVIATE_URL and WEAVIATE_API_KEY immediately (for example, "
                    "in a gitignored .env file or password manager) — it cannot be "
                    "retrieved again."
                )
                enriched["action_required"] = "SAVE_ONE_TIME_API_KEY"
                enriched["one_time_api_key_notice"] = notice
                warnings.append(notice)
        elif not waited and cluster.get("id"):
            cid = cluster["id"]
            enriched["next_step"] = (
                f"Poll 'weaviate-cli cloud status {cid}' until READY, then run "
                f"'weaviate-cli cloud get {cid} --write-env .env' to retrieve and "
                "save the one-time admin API key."
            )

        return enriched, warnings

    def _key_bearing_cluster_call(
        self,
        args: list[str],
        *,
        write_env: str | None,
        write_config: str | None,
        include_key: bool,
        allow_install: bool,
        waited: bool,
    ) -> dict[str, Any]:
        if waited:
            require_key_destination(
                bool(write_env or write_config or include_key),
                "--write-env, --write-config or --include-key",
            )
        with ExitStack() as reservations:
            destinations = []
            if write_env:
                destinations.append(
                    reservations.enter_context(reserve_key_file(write_env, "env"))
                )
            if write_config:
                destinations.append(
                    reservations.enter_context(reserve_key_file(write_config, "config"))
                )
            wcloud_bin, _ = self.ensure_wcloud(allow_install=allow_install)
            self._ensure_authenticated(wcloud_bin)
            if args[:2] == ["cluster", "create"] and waited:
                self._emit_progress(
                    "Creating Weaviate Cloud cluster and waiting for READY (this may take several minutes)..."
                )
            envelope = self._invoke_wcloud_json(wcloud_bin, args)
            raw_cluster = envelope.get("data")
            enriched, warnings = self._attach_credential_handling(
                raw_cluster if isinstance(raw_cluster, dict) else {},
                destinations=destinations,
                include_key=include_key,
                waited=waited,
            )
            enriched["warnings"] = warnings
            return enriched

    def create_cluster(
        self,
        *,
        name: str | None = None,
        region: str | None = None,
        tier: str | None = None,
        wait: bool = False,
        timeout: str | None = None,
        include_key: bool = False,
        write_env: str | None = None,
        write_config: str | None = None,
        allow_install: bool = False,
    ) -> dict[str, Any]:
        if timeout and not wait:
            raise CLIError(
                code="USAGE_ERROR",
                message="--timeout requires --wait.",
                exit_code=ExitCode.USAGE,
                hint="Use --wait with a key destination, for example --wait --timeout 15m --write-env .env.cloud.",
            )
        if (write_env or write_config or include_key) and not wait:
            raise CLIError(
                code="USAGE_ERROR",
                message="Key destination options require --wait on 'cloud create'.",
                exit_code=ExitCode.USAGE,
                hint=(
                    "Pass --wait to capture the one-time API key upon creation, or "
                    "omit --write-env and later run 'weaviate-cli cloud get <id> --write-env .env' "
                    "once the cluster is READY."
                ),
            )

        args = ["cluster", "create"]
        if name:
            args.extend(["--name", name])
        if region:
            args.extend(["--region", region])
        if tier:
            args.extend(["--tier", tier])
        if wait:
            args.append("--wait")
        if timeout:
            args.extend(["--timeout", timeout])

        return self._key_bearing_cluster_call(
            args,
            write_env=write_env,
            write_config=write_config,
            include_key=include_key,
            allow_install=allow_install,
            waited=wait,
        )

    def list_clusters(self, *, allow_install: bool = False) -> dict[str, Any]:
        wcloud_bin, _ = self.ensure_wcloud(allow_install=allow_install)
        self._ensure_authenticated(wcloud_bin)
        envelope = self._invoke_wcloud_json(wcloud_bin, ["cluster", "list"])
        clusters = envelope.get("data")
        cluster_list = (
            [_attach_tier_limits(c) if isinstance(c, dict) else c for c in clusters]
            if isinstance(clusters, list)
            else []
        )
        return {"clusters": cluster_list, "count": len(cluster_list)}

    def get_cluster(
        self,
        cluster_id: str,
        *,
        write_env: str | None = None,
        write_config: str | None = None,
        include_key: bool = False,
        allow_install: bool = False,
    ) -> dict[str, Any]:
        return self._key_bearing_cluster_call(
            ["cluster", "get", cluster_id],
            write_env=write_env,
            write_config=write_config,
            include_key=include_key,
            allow_install=allow_install,
            waited=True,
        )

    def cluster_status(
        self, cluster_id: str, *, allow_install: bool = False
    ) -> dict[str, Any]:
        wcloud_bin, _ = self.ensure_wcloud(allow_install=allow_install)
        self._ensure_authenticated(wcloud_bin)
        envelope = self._invoke_wcloud_json(
            wcloud_bin, ["cluster", "status", cluster_id]
        )
        data = envelope.get("data")
        if isinstance(data, dict):
            return {"id": cluster_id, **data}
        return {"id": cluster_id, "status": data}
