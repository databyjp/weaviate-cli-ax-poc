"""Unit tests for `weaviate-cli cloud` delegation to `wcloud`."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tarfile
import zipfile
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from cli import main
from weaviate_cli.credentials import reserve_key_file
from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.managers.cloud_manager import (
    WCLOUD_ASSETS,
    WCLOUD_VERSION,
    CloudManager,
    CommandResult,
    extract_cluster_credentials,
)


def _make_tar_gz_bytes(binary_name: str, payload: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name=binary_name)
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def _make_zip_bytes(binary_name: str, payload: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(binary_name, payload)
    return buf.getvalue()


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


def test_resolve_wcloud_precedence_env_over_path_over_cache(tmp_path):
    env_bin = tmp_path / "env-wcloud"
    env_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    env_bin.chmod(0o755)

    path_bin = tmp_path / "path-wcloud"
    path_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    path_bin.chmod(0o755)

    cache_root = tmp_path / "cache"
    cache_bin = cache_root / "bin" / "wcloud"
    cache_bin.parent.mkdir(parents=True)
    cache_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    cache_bin.chmod(0o755)

    # 1. WEAVIATE_WCLOUD_PATH wins over PATH and cache
    m1 = CloudManager(
        env={
            "WEAVIATE_WCLOUD_PATH": str(env_bin),
            "WEAVIATE_CLI_CACHE_DIR": str(cache_root),
        },
        which_fn=lambda _: str(path_bin),
        platform_fn=lambda: ("darwin", "arm64"),
    )
    assert m1.resolve_wcloud_binary() == (env_bin, "env_override")

    # 2. $PATH wins over managed cache
    m2 = CloudManager(
        env={"WEAVIATE_CLI_CACHE_DIR": str(cache_root)},
        which_fn=lambda _: str(path_bin),
        platform_fn=lambda: ("darwin", "arm64"),
    )
    assert m2.resolve_wcloud_binary() == (path_bin, "path")

    # 3. Managed cache used when PATH misses
    m3 = CloudManager(
        env={"WEAVIATE_CLI_CACHE_DIR": str(cache_root)},
        which_fn=lambda _: None,
        platform_fn=lambda: ("darwin", "arm64"),
    )
    assert m3.resolve_wcloud_binary() == (cache_bin, "managed_cache")

    # 4. Broken WEAVIATE_WCLOUD_PATH fails fast
    m_bad = CloudManager(
        env={"WEAVIATE_WCLOUD_PATH": str(tmp_path / "missing")},
        which_fn=lambda _: str(path_bin),
    )
    with pytest.raises(CLIError) as err:
        m_bad.resolve_wcloud_binary()
    assert err.value.code == "WCLOUD_NOT_FOUND"
    assert err.value.exit_code == ExitCode.CONNECTIVITY


def test_install_wcloud_verifies_sha256_and_extracts_tar_and_zip(tmp_path, monkeypatch):
    # Test tar.gz (darwin/arm64)
    tar_bytes = _make_tar_gz_bytes("wcloud", b"fake-macho-binary")
    tar_sha = hashlib.sha256(tar_bytes).hexdigest()
    monkeypatch.setitem(
        WCLOUD_ASSETS,
        ("darwin", "arm64"),
        (f"weaviate-cloud_{WCLOUD_VERSION}_darwin_arm64.tar.gz", tar_sha),
    )

    progress: list[str] = []
    manager = CloudManager(
        env={"WEAVIATE_CLI_CACHE_DIR": str(tmp_path / "cache")},
        downloader=lambda url: tar_bytes,
        platform_fn=lambda: ("darwin", "arm64"),
        progress_callback=progress.append,
    )
    res = manager.install_wcloud()
    installed_path = Path(res["path"])
    assert res["already_installed"] is False
    assert installed_path.read_bytes() == b"fake-macho-binary"
    assert os.access(installed_path, os.X_OK)
    assert any("Downloading wcloud" in msg for msg in progress)

    # Idempotent second install without --force
    res2 = manager.install_wcloud()
    assert res2["already_installed"] is True

    # Checksum mismatch refuses to install
    bad_manager = CloudManager(
        env={"WEAVIATE_CLI_CACHE_DIR": str(tmp_path / "bad_cache")},
        downloader=lambda url: b"tampered-bytes",
        platform_fn=lambda: ("darwin", "arm64"),
    )
    with pytest.raises(CLIError) as bad_err:
        bad_manager.install_wcloud()
    assert bad_err.value.code == "WCLOUD_CHECKSUM_MISMATCH"
    assert bad_err.value.exit_code == ExitCode.CONNECTIVITY
    assert not (tmp_path / "bad_cache" / "bin" / "wcloud").exists()

    # Test zip (windows/amd64)
    zip_bytes = _make_zip_bytes("wcloud.exe", b"fake-pe-binary")
    zip_sha = hashlib.sha256(zip_bytes).hexdigest()
    monkeypatch.setitem(
        WCLOUD_ASSETS,
        ("windows", "amd64"),
        (f"weaviate-cloud_{WCLOUD_VERSION}_windows_amd64.zip", zip_sha),
    )
    win_manager = CloudManager(
        env={"WEAVIATE_CLI_CACHE_DIR": str(tmp_path / "win_cache")},
        downloader=lambda url: zip_bytes,
        platform_fn=lambda: ("windows", "amd64"),
    )
    win_res = win_manager.install_wcloud()
    assert Path(win_res["path"]).name == "wcloud.exe"
    assert Path(win_res["path"]).read_bytes() == b"fake-pe-binary"


def test_ensure_wcloud_never_auto_downloads_in_non_tty_but_prompts_in_tty(
    tmp_path, monkeypatch
):
    tar_bytes = _make_tar_gz_bytes("wcloud", b"bin")
    tar_sha = hashlib.sha256(tar_bytes).hexdigest()
    monkeypatch.setitem(
        WCLOUD_ASSETS,
        ("darwin", "arm64"),
        (f"weaviate-cloud_{WCLOUD_VERSION}_darwin_arm64.tar.gz", tar_sha),
    )

    # Non-TTY without allow_install -> fail fast
    non_tty = CloudManager(
        env={"WEAVIATE_CLI_CACHE_DIR": str(tmp_path / "c1")},
        which_fn=lambda _: None,
        is_interactive=False,
        platform_fn=lambda: ("darwin", "arm64"),
    )
    with pytest.raises(CLIError) as err:
        non_tty.ensure_wcloud(allow_install=False)
    assert err.value.code == "WCLOUD_NOT_FOUND"
    assert err.value.exit_code == ExitCode.CONNECTIVITY

    # Non-TTY with explicit --install-wcloud -> installs
    non_tty_optin = CloudManager(
        env={"WEAVIATE_CLI_CACHE_DIR": str(tmp_path / "c2")},
        which_fn=lambda _: None,
        downloader=lambda _: tar_bytes,
        is_interactive=False,
        platform_fn=lambda: ("darwin", "arm64"),
    )
    path, source = non_tty_optin.ensure_wcloud(allow_install=True)
    assert source == "managed_cache"
    assert path.is_file()

    # Interactive TTY prompts user
    prompts: list[str] = []
    tty_mgr = CloudManager(
        env={"WEAVIATE_CLI_CACHE_DIR": str(tmp_path / "c3")},
        which_fn=lambda _: None,
        downloader=lambda _: tar_bytes,
        is_interactive=True,
        prompt_fn=lambda msg: (prompts.append(msg) or True),
        platform_fn=lambda: ("darwin", "arm64"),
    )
    path_tty, _ = tty_mgr.ensure_wcloud(allow_install=False)
    assert path_tty.is_file()
    assert len(prompts) == 1


def test_auth_precheck_fails_fast_in_non_tty_and_prompts_in_tty(tmp_path):
    fake_bin = tmp_path / "wcloud"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)

    logged_in = False

    def runner(args: Sequence[str]) -> CommandResult:
        cmd = list(args)
        if cmd[1:3] == ["auth", "whoami"]:
            if not logged_in:
                return CommandResult(
                    3,
                    json.dumps(
                        {
                            "error": {
                                "code": "auth_required",
                                "message": "not logged in",
                            }
                        }
                    ),
                    "",
                )
            return CommandResult(
                0,
                json.dumps({"data": {"user_id": "u1", "email": "dev@example.com"}}),
                "",
            )
        if cmd[1:3] == ["region", "list"]:
            return CommandResult(
                0,
                json.dumps({"data": [{"id": "eu-central-1", "is_default": True}]}),
                "",
            )
        raise AssertionError(cmd)

    # Non-TTY fails fast with WCLOUD_AUTH_REQUIRED (exit 3)
    non_tty = CloudManager(
        env={"WEAVIATE_WCLOUD_PATH": str(fake_bin)},
        runner=runner,
        is_interactive=False,
    )
    with pytest.raises(CLIError) as auth_err:
        non_tty.list_regions()
    assert auth_err.value.code == "WCLOUD_AUTH_REQUIRED"
    assert auth_err.value.exit_code == ExitCode.AUTH

    # Non-TTY `cloud login` fails fast without hanging
    with pytest.raises(CLIError) as login_err:
        non_tty.login()
    assert login_err.value.code == "WCLOUD_AUTH_INTERACTIVE_REQUIRED"
    assert login_err.value.exit_code == ExitCode.AUTH

    # Interactive TTY prompts and runs interactive login
    def interactive_login(args: Sequence[str]) -> int:
        nonlocal logged_in
        assert list(args)[1:3] == ["auth", "login"]
        logged_in = True
        return 0

    tty_mgr = CloudManager(
        env={"WEAVIATE_WCLOUD_PATH": str(fake_bin)},
        runner=runner,
        interactive_runner=interactive_login,
        is_interactive=True,
        prompt_fn=lambda _: True,
    )
    regions = tty_mgr.list_regions()
    assert regions["count"] == 1
    assert regions["regions"][0]["id"] == "eu-central-1"


def test_create_cluster_wait_nudges_save_and_writes_env_and_config(tmp_path):
    fake_bin = tmp_path / "wcloud"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)

    cluster_payload = {
        "id": "clu-123",
        "name": "demo-cluster",
        "status": "READY",
        "tier": "free",
        "region": "eu-central-1",
        "endpoint": "demo-123.c0.eu-central-1.gcp.weaviate.cloud",
        "grpc_endpoint": "grpc-demo-123.c0.eu-central-1.gcp.weaviate.cloud",
        "api_key": {
            "value": "wcd-one-time-secret",
            "warning": "shown once",
        },
    }

    def runner(args: Sequence[str]) -> CommandResult:
        cmd = list(args)
        if cmd[1:3] == ["auth", "whoami"]:
            return CommandResult(0, json.dumps({"data": {"user_id": "u1"}}), "")
        if cmd[1:3] == ["cluster", "create"]:
            return CommandResult(0, json.dumps({"data": cluster_payload}), "")
        raise AssertionError(cmd)

    manager = CloudManager(
        env={"WEAVIATE_WCLOUD_PATH": str(fake_bin)},
        runner=runner,
        is_interactive=False,
    )

    # Without --write-env: returns key AND emits SAVE_ONE_TIME_API_KEY nudge + warning
    unsaved = manager.create_cluster(name="demo-cluster", wait=True, include_key=True)
    assert unsaved["url"] == "https://demo-123.c0.eu-central-1.gcp.weaviate.cloud"
    assert unsaved["api_key"]["value"] == "wcd-one-time-secret"
    assert unsaved["action_required"] == "SAVE_ONE_TIME_API_KEY"
    assert "Prompt the user to save" in unsaved["one_time_api_key_notice"]
    assert len(unsaved["warnings"]) == 1

    # With --write-env + --write-config: saves securely (0600) and preserves other .env lines
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# existing\nOTHER_VAR=keep\nWEAVIATE_URL=old\n", encoding="utf-8"
    )
    cfg_file = tmp_path / "config.json"

    saved = manager.create_cluster(
        name="demo-cluster",
        wait=True,
        write_env=str(env_file),
        write_config=str(cfg_file),
    )
    assert "api_key" not in saved
    assert "action_required" not in saved
    assert saved["warnings"] == []
    assert str(env_file) in saved["credentials_saved_to"]
    assert str(cfg_file) in saved["credentials_saved_to"]

    env_text = env_file.read_text(encoding="utf-8")
    assert "OTHER_VAR=keep" in env_text
    assert (
        "WEAVIATE_URL=https://demo-123.c0.eu-central-1.gcp.weaviate.cloud" in env_text
    )
    assert "WEAVIATE_API_KEY=wcd-one-time-secret" in env_text
    assert (
        "WEAVIATE_GRPC_URL=grpc-demo-123.c0.eu-central-1.gcp.weaviate.cloud" in env_text
    )
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600

    cfg_parsed = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert cfg_parsed["host"] == "https://demo-123.c0.eu-central-1.gcp.weaviate.cloud"
    assert cfg_parsed["auth"] == {"type": "api_key", "api_key": "wcd-one-time-secret"}
    assert stat.S_IMODE(cfg_file.stat().st_mode) == 0o600


def test_create_cluster_validation_and_async_next_step(tmp_path):
    fake_bin = tmp_path / "wcloud"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)

    def runner(args: Sequence[str]) -> CommandResult:
        cmd = list(args)
        if cmd[1:3] == ["auth", "whoami"]:
            return CommandResult(0, json.dumps({"data": {"user_id": "u1"}}), "")
        if cmd[1:3] == ["cluster", "create"]:
            return CommandResult(
                0,
                json.dumps({"data": {"id": "clu-99", "status": "CREATING"}}),
                "",
            )
        raise AssertionError(cmd)

    manager = CloudManager(
        env={"WEAVIATE_WCLOUD_PATH": str(fake_bin)},
        runner=runner,
        is_interactive=False,
    )

    with pytest.raises(CLIError) as err_env:
        manager.create_cluster(write_env=str(tmp_path / ".env"), wait=False)
    assert err_env.value.exit_code == ExitCode.USAGE

    with pytest.raises(CLIError) as err_timeout:
        manager.create_cluster(timeout="10m", wait=False)
    assert err_timeout.value.exit_code == ExitCode.USAGE

    async_res = manager.create_cluster(wait=False)
    assert async_res["id"] == "clu-99"
    assert "cloud status clu-99" in async_res["next_step"]
    assert "cloud get clu-99 --write-env .env" in async_res["next_step"]


def test_wcloud_error_exit_code_mapping_and_details(tmp_path):
    fake_bin = tmp_path / "wcloud"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)

    def runner(args: Sequence[str]) -> CommandResult:
        cmd = list(args)
        if cmd[1:3] == ["auth", "whoami"]:
            return CommandResult(0, json.dumps({"data": {"user_id": "u1"}}), "")
        if cmd[1:3] == ["cluster", "get"]:
            return CommandResult(
                4,
                json.dumps(
                    {
                        "error": {
                            "code": "cluster_not_found",
                            "message": "cluster missing",
                            "details": {"cluster_id": "bad"},
                        }
                    }
                ),
                "",
            )
        raise AssertionError(cmd)

    manager = CloudManager(
        env={"WEAVIATE_WCLOUD_PATH": str(fake_bin)},
        runner=runner,
        is_interactive=False,
    )
    with pytest.raises(CLIError) as exc:
        manager.get_cluster("bad", include_key=True)
    assert exc.value.code == "WCLOUD_CLUSTER_NOT_FOUND"
    assert exc.value.exit_code == ExitCode.NOT_FOUND
    assert exc.value.details == {"cluster_id": "bad"}


def test_credential_helpers_normalize_and_extract():
    url, grpc, key = extract_cluster_credentials(
        {
            "endpoint": "https://abc.weaviate.cloud/",
            "grpc_endpoint": "grpc-abc.weaviate.cloud",
            "api_key": {"value": "k1"},
        }
    )
    assert url == "https://abc.weaviate.cloud"
    assert grpc == "grpc-abc.weaviate.cloud"
    assert key == "k1"


def test_cloud_cli_commands_and_guide_cloud(cli_runner: CliRunner, tmp_path):
    mock_mgr = MagicMock()
    mock_mgr.whoami.return_value = {
        "user_id": "u1",
        "email": "dev@example.com",
        "org_id": "org1",
        "wcloud_path": "/usr/local/bin/wcloud",
        "wcloud_source": "path",
    }
    mock_mgr.list_regions.return_value = {
        "regions": [{"id": "eu-central-1", "name": "Frankfurt", "is_default": True}],
        "count": 1,
    }
    mock_mgr.create_cluster.return_value = {
        "id": "clu-1",
        "name": "demo",
        "status": "READY",
        "url": "https://demo.weaviate.cloud",
        "api_key": {"value": "secret-once"},
        "credentials_saved_to": [],
        "action_required": "SAVE_ONE_TIME_API_KEY",
        "one_time_api_key_notice": "Save this key now!",
        "warnings": ["Save this key now!"],
    }
    mock_mgr.list_clusters.return_value = {
        "clusters": [{"id": "clu-1", "name": "demo", "status": "READY"}],
        "count": 1,
    }
    mock_mgr.cluster_status.return_value = {"id": "clu-1", "status": "READY"}

    with patch("weaviate_cli.commands.cloud._make_manager", return_value=mock_mgr):
        res_whoami = cli_runner.invoke(main, ["cloud", "whoami"])
        assert res_whoami.exit_code == 0
        assert json.loads(res_whoami.stdout)["data"]["email"] == "dev@example.com"

        res_regions = cli_runner.invoke(main, ["--no-json", "cloud", "regions"])
        assert res_regions.exit_code == 0
        assert "eu-central-1 (default)" in res_regions.stdout

        res_create = cli_runner.invoke(
            main, ["cloud", "create", "--wait", "--include-key"]
        )
        assert res_create.exit_code == 0
        payload = json.loads(res_create.stdout)
        assert payload["data"]["action_required"] == "SAVE_ONE_TIME_API_KEY"
        assert "Save this key now!" in payload["metadata"]["warnings"]
        assert "Warning: Save this key now!" in res_create.stderr

        res_list = cli_runner.invoke(main, ["cloud", "list"])
        assert res_list.exit_code == 0
        assert json.loads(res_list.stdout)["data"]["count"] == 1

        res_status = cli_runner.invoke(main, ["--no-json", "cloud", "status", "clu-1"])
        assert res_status.exit_code == 0
        assert "Cluster clu-1: READY" in res_status.stdout

    # Verify guide cloud includes the one-time API key & durable path guidance
    res_guide = cli_runner.invoke(main, ["guide", "cloud"])
    assert res_guide.exit_code == 0
    assert "One-time admin API key" in res_guide.stdout
    assert "--write-env" in res_guide.stdout
    assert ".gitignore" in res_guide.stdout
    assert ".venv/" in res_guide.stdout
    assert "weaviate-cli cloud create" in res_guide.stdout


def test_async_create_recovers_unexpected_key_instead_of_reporting_success(cli_runner):
    manager = MagicMock()
    manager.create_cluster.return_value = {
        "id": "cluster-id",
        "api_key": "unexpected-key",
    }
    with patch("weaviate_cli.commands.cloud._make_manager", return_value=manager):
        result = cli_runner.invoke(main, ["cloud", "create"])
    payload = json.loads(result.stdout)
    assert (
        result.exit_code == 1 and payload["error"]["code"] == "UNEXPECTED_ONE_TIME_KEY"
    )
    assert payload["data"]["api_key"] == "unexpected-key"
    assert "do not retry" in result.stderr and "unexpected-key" not in result.stderr


def test_write_env_warns_when_unignored_in_git_repo(tmp_path):
    fake_bin = tmp_path / "wcloud"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)

    cluster_payload = {
        "id": "clu-1",
        "status": "READY",
        "endpoint": "demo.weaviate.cloud",
        "api_key": {"value": "secret-once"},
    }

    def runner(args: Sequence[str]) -> CommandResult:
        cmd = list(args)
        if cmd[1:3] == ["auth", "whoami"]:
            return CommandResult(0, json.dumps({"data": {"user_id": "u1"}}), "")
        if cmd[1:3] == ["cluster", "create"]:
            return CommandResult(0, json.dumps({"data": cluster_payload}), "")
        raise AssertionError(cmd)

    # Inside git repo and NOT ignored -> emits warning
    mgr_unignored = CloudManager(
        env={"WEAVIATE_WCLOUD_PATH": str(fake_bin)},
        runner=runner,
        is_interactive=False,
        git_ignored_checker=lambda _: False,
    )
    res_warn = mgr_unignored.create_cluster(
        wait=True, write_env=str(tmp_path / ".env.cloud")
    )
    assert any("not ignored by .gitignore" in w for w in res_warn["warnings"])

    # Inside git repo and ignored -> no warning
    mgr_ignored = CloudManager(
        env={"WEAVIATE_WCLOUD_PATH": str(fake_bin)},
        runner=runner,
        is_interactive=False,
        git_ignored_checker=lambda _: True,
    )
    res_ok = mgr_ignored.create_cluster(
        wait=True, write_env=str(tmp_path / ".env.ignored")
    )
    assert res_ok["warnings"] == []


@pytest.mark.parametrize("kind", ["config", "env"])
def test_credential_publication_is_private_and_preserves_original_on_failure(
    tmp_path, kind
):
    dest = tmp_path / "profile"
    original = "{}\n" if kind == "config" else "# existing\n"
    dest.write_text(original)
    link = os.link

    def fail_publish(source, target, **kwargs):
        if Path(source).name == "pending":
            assert stat.S_IMODE(source.stat().st_mode) == 0o600
            assert "one-time-key" in source.read_text()
            raise OSError("publish failed")
        return link(source, target, **kwargs)

    previous = os.umask(0o022)
    try:
        with (
            reserve_key_file(dest, kind) as destination,
            patch("os.link", side_effect=fail_publish),
            pytest.raises(OSError, match="publish failed"),
        ):
            destination.save("one-time-key")
    finally:
        os.umask(previous)
    assert list(tmp_path.iterdir()) == [dest]
    assert dest.read_text() == original


@pytest.mark.parametrize(
    ("fail_env", "fail_config"), [(True, False), (False, True), (True, True)]
)
@pytest.mark.parametrize("json_mode", [True, False])
@pytest.mark.parametrize("command", [["create", "--wait"], ["get", "clu-1"]])
def test_cloud_save_failure_retains_cluster_result(
    cli_runner, tmp_path, fail_env, fail_config, json_mode, command
):
    env_file = tmp_path / ".env"
    config_file = tmp_path / "config.json"
    destinations = [(env_file, fail_env), (config_file, fail_config)]
    fake_bin = tmp_path / "wcloud"
    fake_bin.touch(mode=0o700)

    def runner(args):
        if list(args[1:3]) == ["auth", "whoami"]:
            return CommandResult(0, '{"data":{}}', "")
        assert list(args[1:3]) == ["cluster", command[0]]
        for path, race in destinations:
            if race:
                path.write_text("intervening-key")
        return CommandResult(
            0, '{"data":{"id":"clu-1","api_key":{"value":"one-time-key"}}}', ""
        )

    manager = CloudManager(
        env={"WEAVIATE_WCLOUD_PATH": str(fake_bin)},
        runner=runner,
        git_ignored_checker=lambda _: True,
    )
    with patch("weaviate_cli.commands.cloud._make_manager", return_value=manager):
        result = cli_runner.invoke(
            main,
            [
                "--json" if json_mode else "--no-json",
                "cloud",
                *command,
                "--write-env",
                str(env_file),
                "--write-config",
                str(config_file),
            ],
        )
    assert result.exit_code == 1
    assert "do not retry provisioning" in result.stderr
    assert "one-time-key" not in result.stderr
    assert ("one-time-key" in result.stdout) == (fail_env and fail_config)
    assert "clu-1" in result.stdout
    for path, failed in destinations:
        if failed:
            assert path.read_text() == "intervening-key"
            assert str(path) in result.stderr
        else:
            assert "one-time-key" in path.read_text() and str(path) in result.stdout
    if json_mode:
        payload = json.loads(result.stdout)
        assert payload["error"]["code"] == "CREDENTIAL_SAVE_FAILED"
        assert payload["metadata"]["exit_code"] == 1
        assert payload["data"]["credentials_saved_to"] == [
            str(p) for p, f in destinations if not f
        ]
        assert payload["data"]["credential_save_failures"] == [
            str(p) for p, f in destinations if f
        ]


@pytest.mark.parametrize("command", [["create", "--wait"], ["get", "cluster-id"]])
@pytest.mark.parametrize(
    ("option", "original"),
    [
        (None, None),
        ("--write-env", "WEAVIATE_API_KEY=\nexport WEAVIATE_API_KEY='old-key'\n"),
        ("--write-config", '{"auth":{"type":"user","admin":"old-key"}}'),
        ("--write-config", '{"auth":{"type":"api_key","api_key":"old-key"}}'),
        ("--write-config", "malformed: old-key"),
    ],
)
def test_cloud_preflight_prevents_wcloud_call(
    cli_runner, tmp_path, command, option, original
):
    path = tmp_path / "occupied"
    args = ["cloud", *command]
    if option:
        path.write_text(original)
        # Both paths must pass, even if stdout is also authorized.
        other = "--write-env" if option == "--write-config" else "--write-config"
        args.extend([other, str(tmp_path / "free"), option, str(path), "--include-key"])
    with patch.object(CloudManager, "ensure_wcloud") as wcloud:
        result = cli_runner.invoke(main, args)
    assert result.exit_code == 2
    assert "old-key" not in result.stdout + result.stderr
    wcloud.assert_not_called()
    if option:
        assert path.read_text() == original
        assert list(tmp_path.iterdir()) == [path]
