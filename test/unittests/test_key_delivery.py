"""Exercise one-time key delivery without a live server or real credentials."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from cli import main
from weaviate_cli.credentials import reserve_key_file
from weaviate_cli.errors import CLIError


@pytest.fixture(params=[["create", "reader"], ["update", "reader", "--rotate-api-key"]])
def user_command(request):
    return ["user", *request.param]


def invoke_user(profile, user_command, options, *, text=False):
    return CliRunner(mix_stderr=False).invoke(
        main,
        [
            "--no-json" if text else "--json",
            "--config-file",
            str(profile),
            *user_command,
            *options,
        ],
        env={"WEAVIATE_API_KEY": "admin-auth-input"},
    )


@pytest.mark.parametrize("options", [[], ["--store"], ["--store", "--include-key"]])
def test_unsafe_user_destination_blocks_before_connecting(
    tmp_path, user_command, options
):
    profile = tmp_path / "profile.json"
    original = b'{"auth": {"type": "user", "reader": "previous-key"}}\n'
    profile.write_bytes(original)
    with patch("weaviate_cli.commands.user.get_client_from_context") as connect:
        result = invoke_user(profile, user_command, options)
    assert result.exit_code == 2
    assert profile.read_bytes() == original
    assert "previous-key" not in result.stdout + result.stderr
    connect.assert_not_called()


@pytest.mark.parametrize(
    "options", [["--store"], ["--include-key"], ["--store", "--include-key"]]
)
@pytest.mark.parametrize("text", [False, True])
def test_user_key_goes_only_to_selected_destinations(
    tmp_path, user_command, options, text
):
    profile = tmp_path / "profile.json"
    profile.write_text('{"auth":{"type":"user","admin":"existing-key"}}')
    client = MagicMock()
    client.users.db.create.return_value = client.users.db.rotate_key.return_value = (
        "issued-key"
    )
    with patch(
        "weaviate_cli.commands.user.get_client_from_context", return_value=client
    ):
        result = invoke_user(profile, user_command, options, text=text)
    assert result.exit_code == 0, result.stderr
    assert ("issued-key" in result.stdout) == ("--include-key" in options)
    assert "issued-key" not in result.stderr
    assert "admin-auth-input" not in result.stdout + result.stderr
    auth = json.loads(profile.read_text())["auth"]
    assert auth["admin"] == "existing-key"
    if "--store" in options:
        assert auth["reader"] == "issued-key" and str(profile) in result.stdout
        assert profile.stat().st_mode & 0o777 == 0o600
    else:
        assert "reader" not in auth


@pytest.mark.parametrize("text", [False, True])
def test_post_issuance_change_preserves_both_user_keys(tmp_path, user_command, text):
    profile = tmp_path / "profile.json"
    profile.write_text('{"auth":{"type":"user"}}')
    intervening = b'{"auth":{"type":"user","reader":"other-key"}}\n'

    def issue_key(**kwargs):
        profile.write_bytes(intervening)
        return "issued-key"

    client = MagicMock()
    client.users.db.create.side_effect = client.users.db.rotate_key.side_effect = (
        issue_key
    )
    with patch(
        "weaviate_cli.commands.user.get_client_from_context", return_value=client
    ):
        result = invoke_user(profile, user_command, ["--store"], text=text)
    assert result.exit_code == 1 and "do not repeat" in result.stderr
    assert "issued-key" in result.stdout and "issued-key" not in result.stderr
    assert "other-key" not in result.stdout + result.stderr
    assert profile.read_bytes() == intervening
    if not text:
        payload = json.loads(result.stdout)
        assert payload["error"]["code"] == "CREDENTIAL_SAVE_FAILED"
        assert payload["data"]["api_key"] == "issued-key"


def test_concurrent_cli_writer_cannot_reserve_same_file(tmp_path):
    dest = tmp_path / ".env"
    with reserve_key_file(dest, "env") as first:
        with (
            pytest.raises(CLIError, match="Cannot reserve"),
            reserve_key_file(dest, "env"),
        ):
            pytest.fail("second writer must not reach issuance")
        first.save("issued-key")
    assert dest.read_text() == "WEAVIATE_API_KEY=issued-key\n"


def test_racing_non_cli_writer_at_publication_keeps_both_files(tmp_path):
    dest = tmp_path / "profile.json"
    original = b'{"auth":{"type":"user","admin":"admin-key"}}'
    dest.write_bytes(original)
    link = os.link

    def race(source, target, **kwargs):
        if source.name == "pending" and target == dest:
            dest.write_bytes(b"intervening file")
        return link(source, target, **kwargs)

    with reserve_key_file(dest, "user", user="reader") as target:
        with (
            patch("os.link", side_effect=race),
            pytest.raises(OSError, match="Previous file retained"),
        ):
            target.save("new-key")
    assert dest.read_bytes() == b"intervening file"
    assert (
        tmp_path / ".profile.json.weaviate-key-lock" / "original"
    ).read_bytes() == original
