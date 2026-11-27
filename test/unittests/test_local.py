"""Unit tests for `weaviate-cli local` Docker lifecycle manager and commands."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from cli import main
from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.managers.local_manager import (
    COMPOSE_CONFIG_FILES_LABEL,
    COMPOSE_PROJECT_LABEL,
    COMPOSE_SERVICE_LABEL,
    LOCAL_PROJECT_NAME,
    MANAGED_LABEL,
    MODE_LABEL,
    TRANSFORMERS_IMAGE,
    VECTORIZER_LABEL,
    WEAVIATE_LATEST_IMAGE,
    WEAVIATE_PINNED_IMAGE,
    CommandResult,
    LocalManager,
    redact_env,
    render_default_compose_yaml,
    render_template_compose_yaml,
)


def _container_inspect_entry(
    *,
    name: str,
    service: str,
    image: str,
    running: bool = True,
    http_port: int | None = None,
    grpc_port: int | None = None,
    mode: str = "default",
    vectorizer: str | None = "transformers",
    compose_file: str | None = None,
    env: list[str] | None = None,
) -> dict[str, Any]:
    labels: dict[str, str] = {
        COMPOSE_PROJECT_LABEL: LOCAL_PROJECT_NAME,
        COMPOSE_SERVICE_LABEL: service,
    }
    if mode == "default":
        labels[MANAGED_LABEL] = "true"
        labels[MODE_LABEL] = "default"
        if vectorizer is not None:
            labels[VECTORIZER_LABEL] = vectorizer
    if compose_file is not None:
        labels[COMPOSE_CONFIG_FILES_LABEL] = compose_file

    ports: dict[str, Any] = {}
    if http_port is not None:
        ports["8080/tcp"] = [{"HostIp": "127.0.0.1", "HostPort": str(http_port)}]
    if grpc_port is not None:
        ports["50051/tcp"] = [{"HostIp": "127.0.0.1", "HostPort": str(grpc_port)}]

    return {
        "Id": f"deadbeef{service:0<12}"[:16],
        "Name": f"/{name}",
        "Config": {"Image": image, "Labels": labels, "Env": env or []},
        "State": {"Status": "running" if running else "exited", "Running": running},
        "NetworkSettings": {"Ports": ports},
    }


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


def test_template_and_default_compose_yaml_contents():
    tpl = render_template_compose_yaml()
    assert f"image: {WEAVIATE_PINNED_IMAGE}" in tpl
    assert f"image: {TRANSFORMERS_IMAGE}" in tpl
    assert 'MCP_SERVER_ENABLED: "true"' in tpl
    assert 'MCP_SERVER_WRITE_ACCESS_ENABLED: "true"' in tpl
    assert 'ENABLE_API_BASED_MODULES: "true"' in tpl
    assert '# AUTHENTICATION_APIKEY_ENABLED: "true"' in tpl
    assert '# AUTHENTICATION_DB_USERS_ENABLED: "true"' in tpl
    assert '# AUTHORIZATION_RBAC_ENABLED: "true"' in tpl
    assert '# AUTHORIZATION_RBAC_ROOT_USERS: "admin"' in tpl

    default_tf = render_default_compose_yaml(vectorizer="transformers")
    assert f"image: {WEAVIATE_LATEST_IMAGE}" in default_tf
    assert f"image: {TRANSFORMERS_IMAGE}" in default_tf
    assert f'{VECTORIZER_LABEL}: "transformers"' in default_tf
    assert "depends_on:" in default_tf

    default_none = render_default_compose_yaml(vectorizer="none")
    assert f"image: {WEAVIATE_LATEST_IMAGE}" in default_none
    assert TRANSFORMERS_IMAGE not in default_none
    assert "  vectorizer:" not in default_none
    assert f'{VECTORIZER_LABEL}: "none"' in default_none


def test_local_start_fresh_default_pulls_missing_images_and_waits():
    calls: list[tuple[list[str], str | None]] = []
    progress: list[str] = []
    created = False

    def runner(args: Sequence[str], stdin_text: str | None) -> CommandResult:
        nonlocal created
        cmd = list(args)
        calls.append((cmd, stdin_text))
        if cmd[:2] == ["docker", "info"]:
            return CommandResult(0, "29.5.2\n", "")
        if cmd[:3] == ["docker", "compose", "version"]:
            return CommandResult(0, "Docker Compose version 5.6.0\n", "")
        if cmd[:2] == ["docker", "ps"] and "--filter" in cmd:
            if any(a.startswith("publish=") for a in cmd):
                return CommandResult(0, "", "")
            if created:
                return CommandResult(0, "c1\nc2\n", "")
            return CommandResult(0, "", "")
        if cmd[:3] == ["docker", "image", "inspect"]:
            # Simulate weaviate cached, transformers missing
            if cmd[3] == WEAVIATE_LATEST_IMAGE:
                return CommandResult(0, "[]", "")
            return CommandResult(1, "", "No such image")
        if cmd[:2] == ["docker", "pull"]:
            return CommandResult(0, "Pulled\n", "")
        if cmd[:2] == ["docker", "compose"] and "up" in cmd:
            created = True
            assert stdin_text is not None
            assert WEAVIATE_LATEST_IMAGE in stdin_text
            assert TRANSFORMERS_IMAGE in stdin_text
            return CommandResult(0, "", "")
        if cmd[:2] == ["docker", "inspect"]:
            entries = [
                _container_inspect_entry(
                    name="weaviate-cli-local-weaviate-1",
                    service="weaviate",
                    image=WEAVIATE_LATEST_IMAGE,
                    http_port=8080,
                    grpc_port=50051,
                ),
                _container_inspect_entry(
                    name="weaviate-cli-local-vectorizer-1",
                    service="vectorizer",
                    image=TRANSFORMERS_IMAGE,
                ),
            ]
            return CommandResult(0, json.dumps(entries), "")
        raise AssertionError(f"Unexpected docker call: {cmd}")

    ready_attempts = iter([None, 503, 200, 200])
    manager = LocalManager(
        runner=runner,
        port_checker=lambda _: False,
        http_ready_checker=lambda _: next(ready_attempts),
        mcp_probe=lambda url, _: {"endpoint": f"{url}/v1/mcp", "available": True},
        progress_callback=progress.append,
        sleep_fn=lambda _: None,
    )
    result = manager.start(vectorizer="transformers")

    assert result["state"] == "running"
    assert result["action"] == "created"
    assert result["mode"] == "default"
    assert result["vectorizer"] == "transformers"
    assert result["url"] == "http://127.0.0.1:8080"
    assert result["grpc_url"] == "127.0.0.1:50051"
    assert result["ready"] is True
    assert result["mcp"]["available"] is True
    assert len(result["services"]) == 2
    assert any("Pulling" in msg and TRANSFORMERS_IMAGE in msg for msg in progress)
    # Weaviate was cached so only transformers should have been pulled
    pull_cmds = [c for c, _ in calls if c[:2] == ["docker", "pull"]]
    assert pull_cmds == [["docker", "pull", TRANSFORMERS_IMAGE]]


def test_local_start_vectorizer_none_skips_sidecar():
    created = False

    def runner(args: Sequence[str], stdin_text: str | None) -> CommandResult:
        nonlocal created
        cmd = list(args)
        if cmd[:2] == ["docker", "info"]:
            return CommandResult(0, "29.5.2\n", "")
        if cmd[:3] == ["docker", "compose", "version"]:
            return CommandResult(0, "v5\n", "")
        if cmd[:2] == ["docker", "ps"]:
            if any(a.startswith("publish=") for a in cmd):
                return CommandResult(0, "", "")
            return CommandResult(0, "c1\n" if created else "", "")
        if cmd[:3] == ["docker", "image", "inspect"]:
            assert cmd[3] == WEAVIATE_LATEST_IMAGE
            return CommandResult(0, "[]", "")
        if cmd[:2] == ["docker", "compose"] and "up" in cmd:
            created = True
            assert stdin_text is not None
            assert TRANSFORMERS_IMAGE not in stdin_text
            return CommandResult(0, "", "")
        if cmd[:2] == ["docker", "inspect"]:
            entries = [
                _container_inspect_entry(
                    name="weaviate-cli-local-weaviate-1",
                    service="weaviate",
                    image=WEAVIATE_LATEST_IMAGE,
                    http_port=8080,
                    grpc_port=50051,
                    vectorizer="none",
                )
            ]
            return CommandResult(0, json.dumps(entries), "")
        raise AssertionError(f"Unexpected docker call: {cmd}")

    manager = LocalManager(
        runner=runner,
        port_checker=lambda _: False,
        http_ready_checker=lambda _: 200,
        mcp_probe=lambda url, _: {"endpoint": f"{url}/v1/mcp", "available": True},
        sleep_fn=lambda _: None,
    )
    result = manager.start(vectorizer="none")
    assert result["vectorizer"] == "none"
    assert len(result["services"]) == 1


def test_local_start_idempotent_when_already_running_and_restarts_when_stopped():
    running_flag = True
    docker_start_called = False

    def runner(args: Sequence[str], stdin_text: str | None) -> CommandResult:
        nonlocal running_flag, docker_start_called
        cmd = list(args)
        if cmd[:2] == ["docker", "info"]:
            return CommandResult(0, "29.5.2\n", "")
        if cmd[:3] == ["docker", "compose", "version"]:
            return CommandResult(0, "v5\n", "")
        if cmd[:2] == ["docker", "ps"]:
            if any(a.startswith("publish=") for a in cmd):
                return CommandResult(0, "", "")
            return CommandResult(0, "c1\n", "")
        if cmd[:2] == ["docker", "inspect"]:
            return CommandResult(
                0,
                json.dumps(
                    [
                        _container_inspect_entry(
                            name="weaviate-cli-local-weaviate-1",
                            service="weaviate",
                            image=WEAVIATE_LATEST_IMAGE,
                            running=running_flag,
                            http_port=8080,
                            grpc_port=50051,
                            vectorizer="none",
                        )
                    ]
                ),
                "",
            )
        if cmd[:2] == ["docker", "start"]:
            docker_start_called = True
            running_flag = True
            return CommandResult(0, "weaviate-cli-local-weaviate-1\n", "")
        raise AssertionError(f"Unexpected docker call: {cmd}")

    manager = LocalManager(
        runner=runner,
        port_checker=lambda _: False,
        http_ready_checker=lambda _: 200,
        mcp_probe=lambda url, _: {"endpoint": f"{url}/v1/mcp", "available": True},
        sleep_fn=lambda _: None,
    )

    res_running = manager.start(vectorizer="none")
    assert res_running["action"] == "already_running"
    assert not docker_start_called

    running_flag = False
    res_restarted = manager.start(vectorizer="none")
    assert res_restarted["action"] == "started"
    assert docker_start_called


def test_local_start_detects_config_mismatch_across_modes_and_vectorizers(tmp_path):
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text("services: {}\n", encoding="utf-8")

    def runner(args: Sequence[str], stdin_text: str | None) -> CommandResult:
        cmd = list(args)
        if cmd[:2] == ["docker", "info"]:
            return CommandResult(0, "29.5.2\n", "")
        if cmd[:3] == ["docker", "compose", "version"]:
            return CommandResult(0, "v5\n", "")
        if cmd[:2] == ["docker", "ps"]:
            return CommandResult(0, "c1\n", "")
        if cmd[:2] == ["docker", "inspect"]:
            return CommandResult(
                0,
                json.dumps(
                    [
                        _container_inspect_entry(
                            name="weaviate-cli-local-weaviate-1",
                            service="weaviate",
                            image=WEAVIATE_LATEST_IMAGE,
                            vectorizer="transformers",
                        )
                    ]
                ),
                "",
            )
        raise AssertionError(f"Unexpected docker call: {cmd}")

    manager = LocalManager(runner=runner, port_checker=lambda _: False)

    with pytest.raises(CLIError) as vec_err:
        manager.start(vectorizer="none")
    assert vec_err.value.code == "LOCAL_CONFIG_MISMATCH"
    assert vec_err.value.exit_code == ExitCode.NOT_FOUND

    with pytest.raises(CLIError) as mode_err:
        manager.start(compose_file=str(compose_path))
    assert mode_err.value.code == "LOCAL_CONFIG_MISMATCH"
    assert mode_err.value.exit_code == ExitCode.NOT_FOUND


def test_local_start_custom_compose_discovers_custom_ports(tmp_path):
    compose_path = tmp_path / "custom.yml"
    compose_path.write_text(render_template_compose_yaml(), encoding="utf-8")
    created = False
    checked_urls: list[str] = []

    def runner(args: Sequence[str], stdin_text: str | None) -> CommandResult:
        nonlocal created
        cmd = list(args)
        if cmd[:2] == ["docker", "info"]:
            return CommandResult(0, "29.5.2\n", "")
        if cmd[:3] == ["docker", "compose", "version"]:
            return CommandResult(0, "v5\n", "")
        if cmd[:2] == ["docker", "ps"]:
            return CommandResult(0, "c1\n" if created else "", "")
        if cmd[:2] == ["docker", "compose"] and "up" in cmd:
            created = True
            assert str(compose_path.resolve()) in cmd
            assert stdin_text is None
            return CommandResult(0, "", "")
        if cmd[:2] == ["docker", "inspect"]:
            return CommandResult(
                0,
                json.dumps(
                    [
                        _container_inspect_entry(
                            name="weaviate-cli-local-weaviate-1",
                            service="weaviate",
                            image=WEAVIATE_PINNED_IMAGE,
                            http_port=8099,
                            grpc_port=50099,
                            mode="compose",
                            vectorizer=None,
                            compose_file=str(compose_path.resolve()),
                        )
                    ]
                ),
                "",
            )
        raise AssertionError(f"Unexpected docker call: {cmd}")

    def ready_check(url: str) -> int:
        checked_urls.append(url)
        return 200

    manager = LocalManager(
        runner=runner,
        port_checker=lambda _: False,
        http_ready_checker=ready_check,
        mcp_probe=lambda url, _: {
            "endpoint": f"{url}/v1/mcp",
            "available": True,
            "auth_required": True,
        },
        sleep_fn=lambda _: None,
    )
    res = manager.start(compose_file=str(compose_path))
    assert res["mode"] == "compose"
    assert res["url"] == "http://127.0.0.1:8099"
    assert res["grpc_url"] == "127.0.0.1:50099"
    assert res["compose_file"] == str(compose_path.resolve())
    assert "http://127.0.0.1:8099/v1/.well-known/ready" in checked_urls


def test_local_start_fails_fast_on_unmanaged_port_conflict_without_touching_it():
    def runner(args: Sequence[str], stdin_text: str | None) -> CommandResult:
        cmd = list(args)
        if cmd[:2] == ["docker", "info"]:
            return CommandResult(0, "29.5.2\n", "")
        if cmd[:3] == ["docker", "compose", "version"]:
            return CommandResult(0, "v5\n", "")
        if cmd[:2] == ["docker", "ps"]:
            if "publish=8080" in cmd:
                return CommandResult(0, "sandpit-weaviate-1\tsandpit\n", "")
            return CommandResult(0, "", "")
        raise AssertionError(f"Should not run further docker commands: {cmd}")

    manager = LocalManager(runner=runner, port_checker=lambda p: p == 8080)
    with pytest.raises(CLIError) as exc:
        manager.start()
    assert exc.value.code == "PORT_IN_USE"
    assert exc.value.exit_code == ExitCode.CONNECTIVITY
    assert "sandpit-weaviate-1" in exc.value.message
    assert "local template" in (exc.value.hint or "")


def test_local_start_docker_unavailable_and_compose_missing():
    def missing_docker(args: Sequence[str], stdin_text: str | None) -> CommandResult:
        raise FileNotFoundError("docker")

    manager_missing = LocalManager(runner=missing_docker)
    with pytest.raises(CLIError) as err1:
        manager_missing.status()
    assert err1.value.code == "DOCKER_UNAVAILABLE"
    assert err1.value.exit_code == ExitCode.CONNECTIVITY

    def no_compose(args: Sequence[str], stdin_text: str | None) -> CommandResult:
        cmd = list(args)
        if cmd[:2] == ["docker", "info"]:
            return CommandResult(0, "29.5.2\n", "")
        if cmd[:3] == ["docker", "compose", "version"]:
            return CommandResult(1, "", "unknown command: compose")
        raise AssertionError(cmd)

    manager_no_compose = LocalManager(runner=no_compose)
    with pytest.raises(CLIError) as err2:
        manager_no_compose.start()
    assert err2.value.code == "DOCKER_COMPOSE_UNAVAILABLE"
    assert err2.value.exit_code == ExitCode.CONNECTIVITY


def test_local_start_attaches_logs_on_timeout():
    created = False
    now = 0.0

    def fake_monotonic() -> float:
        nonlocal now
        now += 5.0
        return now

    def runner(args: Sequence[str], stdin_text: str | None) -> CommandResult:
        nonlocal created
        cmd = list(args)
        if cmd[:2] == ["docker", "info"]:
            return CommandResult(0, "29.5.2\n", "")
        if cmd[:3] == ["docker", "compose", "version"]:
            return CommandResult(0, "v5\n", "")
        if cmd[:2] == ["docker", "ps"]:
            if any(a.startswith("publish=") for a in cmd):
                return CommandResult(0, "", "")
            return CommandResult(0, "c1\n" if created else "", "")
        if cmd[:3] == ["docker", "image", "inspect"]:
            return CommandResult(0, "[]", "")
        if cmd[:2] == ["docker", "compose"] and "up" in cmd:
            created = True
            return CommandResult(0, "", "")
        if cmd[:2] == ["docker", "inspect"]:
            return CommandResult(
                0,
                json.dumps(
                    [
                        _container_inspect_entry(
                            name="weaviate-cli-local-weaviate-1",
                            service="weaviate",
                            image=WEAVIATE_LATEST_IMAGE,
                            http_port=8080,
                            grpc_port=50051,
                            vectorizer="none",
                        )
                    ]
                ),
                "",
            )
        if cmd[:2] == ["docker", "logs"]:
            return CommandResult(0, "", "booting weaviate...")
        raise AssertionError(cmd)

    manager = LocalManager(
        runner=runner,
        port_checker=lambda _: False,
        http_ready_checker=lambda _: None,
        ready_timeout=10.0,
        sleep_fn=lambda _: None,
        monotonic_fn=fake_monotonic,
    )
    with pytest.raises(CLIError) as exc:
        manager.start(vectorizer="none")
    assert exc.value.code == "LOCAL_STARTUP_TIMEOUT"
    assert exc.value.exit_code == ExitCode.CONNECTIVITY
    assert exc.value.details == {"logs": {"weaviate": "booting weaviate..."}}


def test_local_status_warns_about_unmanaged_container_without_touching_it():
    def runner(args: Sequence[str], stdin_text: str | None) -> CommandResult:
        cmd = list(args)
        if cmd[:2] == ["docker", "info"]:
            return CommandResult(0, "29.5.2\n", "")
        if cmd[:2] == ["docker", "ps"]:
            if "publish=8080" in cmd:
                return CommandResult(0, "sandpit-weaviate-1\tsandpit\n", "")
            return CommandResult(0, "", "")
        raise AssertionError(cmd)

    manager = LocalManager(runner=runner, port_checker=lambda _: True)
    res = manager.status()
    assert res["state"] == "not_created"
    assert res["services"] == []
    assert any("sandpit-weaviate-1" in w for w in res["warnings"])


def test_local_stop_logs_and_destroy_only_target_managed_project():
    removed_calls: list[list[str]] = []

    def runner(args: Sequence[str], stdin_text: str | None) -> CommandResult:
        cmd = list(args)
        if cmd[:2] == ["docker", "info"]:
            return CommandResult(0, "29.5.2\n", "")
        if cmd[:2] == ["docker", "ps"]:
            assert f"label={COMPOSE_PROJECT_LABEL}={LOCAL_PROJECT_NAME}" in cmd
            return CommandResult(0, "c1\n", "")
        if cmd[:2] == ["docker", "inspect"]:
            return CommandResult(
                0,
                json.dumps(
                    [
                        _container_inspect_entry(
                            name="weaviate-cli-local-weaviate-1",
                            service="weaviate",
                            image=WEAVIATE_LATEST_IMAGE,
                            http_port=8080,
                            grpc_port=50051,
                            vectorizer="none",
                        )
                    ]
                ),
                "",
            )
        if cmd[:2] == ["docker", "stop"]:
            return CommandResult(0, "weaviate-cli-local-weaviate-1\n", "")
        if cmd[:2] == ["docker", "logs"]:
            return CommandResult(0, "ready\n", "")
        if cmd[:3] == ["docker", "network", "ls"]:
            assert f"label={COMPOSE_PROJECT_LABEL}={LOCAL_PROJECT_NAME}" in cmd
            return CommandResult(0, "weaviate-cli-local_default\n", "")
        if cmd[:3] == ["docker", "volume", "ls"]:
            assert f"label={COMPOSE_PROJECT_LABEL}={LOCAL_PROJECT_NAME}" in cmd
            return CommandResult(0, "weaviate-cli-local_weaviate_data\n", "")
        if cmd[:2] in (["docker", "rm"], ["docker", "network"], ["docker", "volume"]):
            removed_calls.append(cmd)
            return CommandResult(0, "", "")
        raise AssertionError(cmd)

    manager = LocalManager(runner=runner)

    stop_res = manager.stop()
    assert stop_res["action"] == "stopped"
    assert stop_res["stopped_services"] == ["weaviate"]

    log_res = manager.logs(service="weaviate", tail=50)
    assert log_res["logs"] == "ready"

    with pytest.raises(CLIError) as bad_svc:
        manager.logs(service="missing")
    assert bad_svc.value.code == "LOCAL_SERVICE_NOT_FOUND"
    assert bad_svc.value.exit_code == ExitCode.NOT_FOUND

    destroy_res = manager.destroy()
    assert destroy_res["destroyed"] is True
    assert destroy_res["removed_containers"] == ["weaviate-cli-local-weaviate-1"]
    assert destroy_res["removed_networks"] == ["weaviate-cli-local_default"]
    assert destroy_res["removed_volumes"] == ["weaviate-cli-local_weaviate_data"]
    assert len(removed_calls) == 3


def test_local_cli_template_outputs_raw_yaml_without_docker(cli_runner: CliRunner):
    with patch("weaviate_cli.commands.local.LocalManager") as mock_mgr:
        result = cli_runner.invoke(main, ["local", "template"])
        assert result.exit_code == 0, result.stderr
        assert result.stderr == ""
        assert f"image: {WEAVIATE_PINNED_IMAGE}" in result.stdout
        assert "# AUTHORIZATION_RBAC_ENABLED" in result.stdout

        json_res = cli_runner.invoke(main, ["local", "template", "--json"])
        assert json_res.exit_code == 0, json_res.stderr
        payload = json.loads(json_res.stdout)
        assert payload["data"]["pinned_version"] == "1.41.0"
        assert f"image: {WEAVIATE_PINNED_IMAGE}" in payload["data"]["template"]
        mock_mgr.assert_not_called()


def test_local_cli_start_rejects_conflicting_compose_and_vectorizer(
    cli_runner: CliRunner, tmp_path
):
    compose = tmp_path / "compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    result = cli_runner.invoke(
        main,
        [
            "local",
            "start",
            "--compose-file",
            str(compose),
            "--vectorizer",
            "none",
        ],
    )
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "CONFLICTING_OPTIONS"


def test_local_cli_destroy_requires_yes_and_emits_envelope(cli_runner: CliRunner):
    with patch("weaviate_cli.commands.local.LocalManager") as mock_cls:
        blocked = cli_runner.invoke(main, ["local", "destroy"])
        assert blocked.exit_code == 2
        assert json.loads(blocked.stdout)["error"]["code"] == "CONFIRMATION_REQUIRED"
        mock_cls.assert_not_called()

        mock_mgr = MagicMock()
        mock_mgr.destroy.return_value = {
            "project": LOCAL_PROJECT_NAME,
            "destroyed": True,
            "already_absent": False,
            "removed_containers": ["weaviate-cli-local-weaviate-1"],
            "removed_networks": ["weaviate-cli-local_default"],
            "removed_volumes": ["weaviate-cli-local_weaviate_data"],
            "warnings": [],
        }
        mock_cls.return_value = mock_mgr

        allowed = cli_runner.invoke(main, ["local", "destroy", "--yes"])
        assert allowed.exit_code == 0, allowed.stdout
        payload = json.loads(allowed.stdout)
        assert payload["data"]["destroyed"] is True
        assert payload["metadata"]["command"] == "local destroy"

        text_res = cli_runner.invoke(main, ["--no-json", "local", "destroy", "--yes"])
        assert text_res.exit_code == 0
        assert "Destroyed local Weaviate cluster" in text_res.stdout


def test_redact_env_masks_secrets_but_preserves_toggles_and_users():
    raw = {
        "AUTHENTICATION_APIKEY_ENABLED": "true",
        "AUTHENTICATION_APIKEY_ALLOWED_KEYS": "super-secret-key",
        "AUTHENTICATION_APIKEY_USERS": "admin",
        "AUTHENTICATION_DB_USERS_ENABLED": "true",
        "AUTHORIZATION_RBAC_ENABLED": "true",
        "OPENAI_APIKEY": "sk-1234",
        "AWS_SECRET_ACCESS_KEY": "aws-secret",
        "CUSTOM_AUTH_TOKEN": "tok-xyz",
        "DB_PASSWORD": "pw",
        "CLUSTER_HOSTNAME": "node1",
    }
    redacted = redact_env(raw)
    assert redacted["AUTHENTICATION_APIKEY_ENABLED"] == "true"
    assert redacted["AUTHENTICATION_APIKEY_USERS"] == "admin"
    assert redacted["AUTHENTICATION_DB_USERS_ENABLED"] == "true"
    assert redacted["AUTHORIZATION_RBAC_ENABLED"] == "true"
    assert redacted["CLUSTER_HOSTNAME"] == "node1"
    assert redacted["AUTHENTICATION_APIKEY_ALLOWED_KEYS"] == "***REDACTED***"
    assert redacted["OPENAI_APIKEY"] == "***REDACTED***"
    assert redacted["AWS_SECRET_ACCESS_KEY"] == "***REDACTED***"
    assert redacted["CUSTOM_AUTH_TOKEN"] == "***REDACTED***"
    assert redacted["DB_PASSWORD"] == "***REDACTED***"


def test_local_status_extracts_config_summary_and_optional_redacted_env():
    def runner(args: Sequence[str], stdin_text: str | None) -> CommandResult:
        cmd = list(args)
        if cmd[:2] == ["docker", "info"]:
            return CommandResult(0, "29.5.2\n", "")
        if cmd[:2] == ["docker", "ps"]:
            return CommandResult(0, "c1\n", "")
        if cmd[:2] == ["docker", "inspect"]:
            return CommandResult(
                0,
                json.dumps(
                    [
                        _container_inspect_entry(
                            name="weaviate-cli-local-weaviate-1",
                            service="weaviate",
                            image=WEAVIATE_PINNED_IMAGE,
                            http_port=8080,
                            grpc_port=50051,
                            mode="compose",
                            vectorizer=None,
                            env=[
                                "AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=false",
                                "AUTHENTICATION_APIKEY_ENABLED=true",
                                "AUTHENTICATION_APIKEY_ALLOWED_KEYS=top-secret",
                                "AUTHENTICATION_APIKEY_USERS=admin",
                                "AUTHENTICATION_DB_USERS_ENABLED=true",
                                "AUTHORIZATION_RBAC_ENABLED=true",
                                "MCP_SERVER_ENABLED=true",
                                "MCP_SERVER_WRITE_ACCESS_ENABLED=false",
                                "ENABLE_API_BASED_MODULES=true",
                                "ENABLE_MODULES=text2vec-transformers,reranker-transformers",
                                "DEFAULT_VECTORIZER_MODULE=text2vec-transformers",
                            ],
                        )
                    ]
                ),
                "",
            )
        raise AssertionError(cmd)

    manager = LocalManager(
        runner=runner,
        http_ready_checker=lambda _: 200,
        mcp_probe=lambda url, _: {"endpoint": f"{url}/v1/mcp", "available": True},
    )

    res_default = manager.status()
    assert res_default["config"] == {
        "anonymous_access": False,
        "apikey_auth": True,
        "db_users": True,
        "rbac": True,
        "mcp_enabled": True,
        "mcp_write_access": False,
        "api_based_modules": True,
        "default_vectorizer": "text2vec-transformers",
        "enable_modules": ["text2vec-transformers", "reranker-transformers"],
    }
    assert "env" not in res_default["services"][0]

    res_env = manager.status(show_env=True)
    svc_env = res_env["services"][0]["env"]
    assert svc_env["AUTHENTICATION_DB_USERS_ENABLED"] == "true"
    assert svc_env["AUTHENTICATION_APIKEY_ENABLED"] == "true"
    assert svc_env["AUTHENTICATION_APIKEY_ALLOWED_KEYS"] == "***REDACTED***"


def test_local_cli_status_and_logs_json_and_text(cli_runner: CliRunner):
    mock_mgr = MagicMock()
    mock_mgr.status.return_value = {
        "project": LOCAL_PROJECT_NAME,
        "state": "running",
        "mode": "default",
        "vectorizer": "transformers",
        "compose_file": None,
        "url": "http://127.0.0.1:8080",
        "grpc_url": "127.0.0.1:50051",
        "ready": True,
        "mcp": {"endpoint": "http://127.0.0.1:8080/v1/mcp", "available": True},
        "config": {
            "anonymous_access": True,
            "apikey_auth": False,
            "db_users": False,
            "rbac": False,
            "mcp_enabled": True,
            "mcp_write_access": True,
            "api_based_modules": True,
            "default_vectorizer": "text2vec-transformers",
            "enable_modules": ["text2vec-transformers"],
        },
        "services": [
            {
                "service": "weaviate",
                "container": "weaviate-cli-local-weaviate-1",
                "image": WEAVIATE_LATEST_IMAGE,
                "state": "running",
                "ports": {"8080/tcp": 8080, "50051/tcp": 50051},
                "env": {"AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED": "true"},
            }
        ],
        "warnings": [],
    }
    mock_mgr.logs.return_value = {
        "project": LOCAL_PROJECT_NAME,
        "service": "weaviate",
        "container": "weaviate-cli-local-weaviate-1",
        "tail": 50,
        "logs": "line1\nline2",
    }

    with patch("weaviate_cli.commands.local.LocalManager", return_value=mock_mgr):
        st_json = cli_runner.invoke(main, ["local", "status", "--show-env"])
        assert st_json.exit_code == 0
        mock_mgr.status.assert_called_with(show_env=True)
        payload = json.loads(st_json.stdout)["data"]
        assert payload["url"] == "http://127.0.0.1:8080"
        assert payload["config"]["db_users"] is False

        st_text = cli_runner.invoke(
            main, ["--no-json", "local", "status", "--show-env"]
        )
        assert st_text.exit_code == 0
        assert "State:       running" in st_text.stdout
        assert (
            "Auth/RBAC:   anonymous=true, api_key=false, db_users=false, rbac=false"
            in st_text.stdout
        )
        assert "AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true" in st_text.stdout
        assert "Native MCP:  available" in st_text.stdout

        lg_json = cli_runner.invoke(main, ["local", "logs", "--tail", "50"])
        assert lg_json.exit_code == 0
        assert json.loads(lg_json.stdout)["data"]["logs"] == "line1\nline2"

        lg_text = cli_runner.invoke(
            main, ["--no-json", "local", "logs", "--tail", "50"]
        )
        assert lg_text.exit_code == 0
        assert "line1\nline2" in lg_text.stdout
