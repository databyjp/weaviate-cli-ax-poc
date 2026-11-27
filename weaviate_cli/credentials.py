"""Reserve a file destination before requesting a one-time API key."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from weaviate_cli.errors import CLIError, ExitCode

Kind = Literal["env", "config", "user"]
_ENV_ENTRY = re.compile(r"^\s*(export\s+)?(\w+)\s*=(.*)$")


def require_key_destination(selected: bool, options: str) -> None:
    """Reject a key-bearing call unless the caller selected storage or stdout."""
    if not selected:
        raise CLIError(
            "KEY_DESTINATION_REQUIRED",
            f"Choose {options} before requesting a one-time key.",
            exit_code=ExitCode.USAGE,
        )


def _read_regular(path: Path) -> bytes | None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(mode):
        raise ValueError("destination must be a regular file, not a symlink or device")
    return path.read_bytes()


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("duplicate config fields")
    return obj


@dataclass(repr=False)
class KeyDestination:
    """A destination validated and reserved for the lifetime of `reserve_key_file`."""

    path: Path
    kind: Kind
    user: str | None
    _work: Path
    _original: bytes | None
    _config: dict[str, Any] = field(default_factory=dict)
    retained_original: Path | None = field(init=False, default=None)

    def _validate(self) -> None:
        if self.kind == "env":
            for line in (self._original or b"").decode().splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                entry = _ENV_ENTRY.fullmatch(line)
                if not entry:
                    raise ValueError("expected dotenv KEY=VALUE entries")
                if entry[2] == "WEAVIATE_API_KEY" and not re.fullmatch(
                    r"""\s*(?:""|'')?(?:\s+#.*)?\s*""", entry[3]
                ):
                    raise ValueError("WEAVIATE_API_KEY is already populated")
            return
        if self._original is not None:
            try:
                self._config = json.loads(
                    self._original.decode(), object_pairs_hook=_unique_keys
                )
            except (ValueError, RecursionError) as exc:
                raise ValueError(
                    "invalid or ambiguous JSON config; choose another file"
                ) from exc
            if not isinstance(self._config, dict):
                raise ValueError("expected a JSON object")
        auth = self._config.get("auth", {})
        if not isinstance(auth, dict):
            raise ValueError("invalid auth block")
        if self.kind == "user":
            if auth.get("type") != "user" or not self.user or self.user == "type":
                raise ValueError(
                    "--store requires a named user slot in an auth.type=user config"
                )
            if auth.get(self.user) not in (None, ""):
                raise ValueError("user already has a stored credential")
        elif auth and not (
            set(auth) <= {"type", "api_key"}
            and auth.get("type") == "api_key"
            and auth.get("api_key") in (None, "")
        ):
            raise ValueError("would replace an existing auth block")

    def _content(self, key: str, url: str | None, grpc_url: str | None) -> str:
        if self.kind == "env":
            updates = {
                k: v
                for k, v in (
                    ("WEAVIATE_URL", url),
                    ("WEAVIATE_API_KEY", key),
                    ("WEAVIATE_GRPC_URL", grpc_url),
                )
                if v is not None
            }
            lines = []
            seen = set()
            for line in (self._original or b"").decode().splitlines():
                entry = _ENV_ENTRY.match(line)
                if entry and entry[2] in updates:
                    name = entry[2]
                    if name not in seen:
                        lines.append(f"{entry[1] or ''}{name}={updates[name]}")
                    seen.add(name)
                else:
                    lines.append(line)
            lines.extend(f"{k}={v}" for k, v in updates.items() if k not in seen)
            return "\n".join(lines) + "\n"
        config = dict(self._config)
        if self.kind == "user":
            config["auth"] = {**config["auth"], self.user: key}
        else:
            config["auth"] = {"type": "api_key", "api_key": key}
            if url:
                config["host"] = url
            if grpc_url:
                config["grpc_host"] = grpc_url
        return json.dumps(config, indent=2) + "\n"

    def save(
        self, key: str, *, url: str | None = None, grpc_url: str | None = None
    ) -> None:
        """Publish private contents without clobbering a file changed after preflight.

        On failure the caller still owns the issued key and must provide recovery.
        """
        pending = self._work / "pending"
        with pending.open("w", encoding="utf-8") as stream:
            stream.write(self._content(key, url, grpc_url))
            stream.flush()
            os.fsync(stream.fileno())
        if _read_regular(self.path) != self._original:
            raise ValueError("destination changed after preflight")
        if self._original is None:
            os.link(pending, self.path)
            return

        # A check followed by replace could delete a key written by a non-CLI
        # process in between. Claim the old entry, verify what we actually moved,
        # then publish without replacement. Never unlink an intervening writer.
        original = self._work / "original"
        try:
            os.rename(self.path, original)
        except FileNotFoundError as exc:
            raise ValueError("destination disappeared during save") from exc
        self.retained_original = original
        try:
            if _read_regular(original) != self._original:
                raise ValueError("destination changed during save")
            os.link(pending, self.path)
        except BaseException:
            # If the name has been taken, retain both files. The reservation is
            # deliberately left in place for recovery rather than deleting either.
            try:
                os.link(original, self.path, follow_symlinks=False)
            except OSError:
                raise OSError(f"Previous file retained at {original}") from None
            original.unlink()
            self.retained_original = None
            raise
        # The issued key is already published. A cleanup failure is not a
        # delivery failure and must not cause the new key to be printed.
        with suppress(OSError):
            original.unlink()
            self.retained_original = None


@contextmanager
def reserve_key_file(
    path: str | Path, kind: Kind, *, user: str | None = None
) -> Iterator[KeyDestination]:
    """Exclude concurrent CLI writers and reject unsafe destinations before issuance.

    A stale reservation fails closed. If interrupted during publication, inspect
    `original` and `pending` inside the private reservation before removing it.
    """
    dest = Path(path)
    work = dest.with_name(f".{dest.name}.weaviate-key-lock")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        work.mkdir(mode=0o700)
    except OSError as exc:
        raise CLIError(
            "KEY_DESTINATION_UNAVAILABLE",
            f"Cannot reserve '{dest}'. Choose another destination or inspect '{work}'.",
            exit_code=ExitCode.USAGE,
        ) from exc
    try:
        try:
            target = KeyDestination(dest, kind, user, work, _read_regular(dest))
            target._validate()
            # Exercise the filesystem's private staging and no-replace primitives
            # before a remote operation can issue or invalidate a key.
            pending = work / "pending"
            pending.touch(mode=0o600, exist_ok=False)
            os.link(pending, work / "probe")
            (work / "probe").unlink()
        except (OSError, ValueError) as exc:
            raise CLIError(
                "UNSAFE_KEY_DESTINATION",
                f"Cannot save a key to '{dest}': {exc}",
                exit_code=ExitCode.USAGE,
            ) from exc
        yield target
    finally:
        with suppress(OSError):
            (work / "probe").unlink(missing_ok=True)
            (work / "pending").unlink(missing_ok=True)
            work.rmdir()
