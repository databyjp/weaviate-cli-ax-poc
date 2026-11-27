import json
from unittest.mock import MagicMock, mock_open, patch

import pytest
import weaviate

from weaviate_cli.managers.config_manager import ConfigManager


def test_init_with_config_file():
    config_data = {"host": "localhost", "http_port": "8080", "grpc_port": "50051"}

    with patch("builtins.open", mock_open(read_data=json.dumps(config_data))):
        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = True
            config = ConfigManager(config_file="test_config.json")
            assert config.config == config_data


def test_create_default_config():
    with patch("pathlib.Path.exists") as mock_exists:
        mock_exists.return_value = False
        config = ConfigManager()
        assert config.config["host"] == "localhost"
        assert config.config["http_port"] == "8080"
        assert config.config["grpc_port"] == "50051"


@patch("socket.create_connection")
def test_check_host_docker_internal(mock_socket):
    config = ConfigManager()

    # Test successful connection
    mock_socket.return_value = MagicMock()
    assert config._ConfigManager__check_host_docker_internal() is True  # type: ignore[attr-defined]


@patch("socket.create_connection")
def test_check_host_docker_internal_failed(mock_socket):
    config = ConfigManager()

    # Test failed connection
    mock_socket.side_effect = OSError()
    assert config._ConfigManager__check_host_docker_internal() is False  # type: ignore[attr-defined]


def test_init_with_user():
    config_data = {
        "host": "localhost",
        "http_port": "8080",
        "grpc_port": "50051",
        "auth": {"type": "user", "admin": "admin-key", "jose": "jose-key"},
    }

    with patch("builtins.open", mock_open(read_data=json.dumps(config_data))):
        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = True
            config = ConfigManager(config_file="test_config.json", user="jose")
            assert config.user == "jose"
            assert config.config == config_data


def test_get_client_with_user_auth():
    config_data = {
        "host": "localhost",
        "http_port": "8080",
        "grpc_port": "50051",
        "auth": {"type": "user", "admin": "admin-key", "jose": "jose-key"},
    }

    with patch("builtins.open", mock_open(read_data=json.dumps(config_data))):
        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = True
            with patch("weaviate.connect_to_local") as mock_connect:
                config = ConfigManager(config_file="test_config.json", user="jose")
                config.get_client()

                mock_connect.assert_called_once()
                call_kwargs = mock_connect.call_args.kwargs
                assert isinstance(
                    call_kwargs["auth_credentials"], weaviate.auth.AuthApiKey
                )
                assert call_kwargs["auth_credentials"].api_key == "jose-key"


def test_get_client_with_invalid_user():
    config_data = {
        "host": "localhost",
        "http_port": "8080",
        "grpc_port": "50051",
        "auth": {"type": "user", "admin": "admin-key"},
    }

    with patch("builtins.open", mock_open(read_data=json.dumps(config_data))):
        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = True
            config = ConfigManager(config_file="test_config.json", user="jose")
            with pytest.raises(Exception) as exc_info:
                config.get_client()
            assert str(exc_info.value) == "User 'jose' not found in config file"


def test_get_client_missing_user():
    config_data = {
        "host": "localhost",
        "http_port": "8080",
        "grpc_port": "50051",
        "auth": {"type": "user", "admin": "admin-key"},
    }

    with patch("builtins.open", mock_open(read_data=json.dumps(config_data))):
        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = True
            config = ConfigManager(config_file="test_config.json")
            with pytest.raises(Exception) as exc_info:
                config.get_client()
            assert (
                str(exc_info.value) == "User must be specified when auth type is 'user'"
            )


def test_get_client_with_api_key_auth():
    config_data = {
        "host": "localhost",
        "http_port": "8080",
        "grpc_port": "50051",
        "auth": {"type": "api_key", "api_key": "test-key"},
    }

    with patch("builtins.open", mock_open(read_data=json.dumps(config_data))):
        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = True
            with patch("weaviate.connect_to_local") as mock_connect:
                config = ConfigManager(config_file="test_config.json")
                config.get_client()

                mock_connect.assert_called_once()
                call_kwargs = mock_connect.call_args.kwargs
                assert isinstance(
                    call_kwargs["auth_credentials"], weaviate.auth.AuthApiKey
                )
                assert call_kwargs["auth_credentials"].api_key == "test-key"


def test_get_client_with_ip_address():
    config_data = {
        "host": "127.0.0.1",
        "grpc_host": "127.0.0.1",
        "http_port": 8080,
        "grpc_port": 50051,
    }

    with patch("builtins.open", mock_open(read_data=json.dumps(config_data))):
        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = True
            with patch("weaviate.connect_to_custom") as mock_connect:
                config = ConfigManager(config_file="test_config.json")
                config.get_client()

                mock_connect.assert_called_once()
                call_kwargs = mock_connect.call_args.kwargs
                assert call_kwargs["http_host"] == "127.0.0.1"
                assert call_kwargs["grpc_host"] == "127.0.0.1"
                assert call_kwargs["http_port"] == 8080
                assert call_kwargs["grpc_port"] == 50051
                assert call_kwargs["http_secure"] is False
                assert call_kwargs["grpc_secure"] is False


def test_get_client_with_ip_address_and_secure_ports():
    config_data = {
        "host": "127.0.0.1",
        "grpc_host": "127.0.0.1",
        "http_port": 443,
        "grpc_port": 443,
    }

    with patch("builtins.open", mock_open(read_data=json.dumps(config_data))):
        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = True
            with patch("weaviate.connect_to_custom") as mock_connect:
                config = ConfigManager(config_file="test_config.json")
                config.get_client()

                mock_connect.assert_called_once()
                call_kwargs = mock_connect.call_args.kwargs
                assert call_kwargs["http_host"] == "127.0.0.1"
                assert call_kwargs["grpc_host"] == "127.0.0.1"
                assert call_kwargs["http_port"] == 443
                assert call_kwargs["grpc_port"] == 443
                assert call_kwargs["http_secure"] is True
                assert call_kwargs["grpc_secure"] is True


def test_get_client_with_ip_address_with_https():
    config_data = {
        "host": "https://85.10.20.30",
        "grpc_host": "https://85.10.20.31",
        "http_port": 443,
        "grpc_port": 443,
    }

    with patch("builtins.open", mock_open(read_data=json.dumps(config_data))):
        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = True
            with patch("weaviate.connect_to_custom") as mock_connect:
                config = ConfigManager(config_file="test_config.json")
                config.get_client()

                mock_connect.assert_called_once()
                call_kwargs = mock_connect.call_args.kwargs
                assert call_kwargs["http_host"] == "85.10.20.30"
                assert call_kwargs["grpc_host"] == "85.10.20.31"
                assert call_kwargs["http_port"] == 443
                assert call_kwargs["grpc_port"] == 443
                assert call_kwargs["http_secure"] is True
                assert call_kwargs["grpc_secure"] is True


def test_get_client_with_host_and_custom():
    config_data = {
        "host": "https://weaviate.google.my-cloud.com",
        "grpc_host": "https://grpc.weaviate.google.my-cloud.com",
    }

    with patch("builtins.open", mock_open(read_data=json.dumps(config_data))):
        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = True
            with patch("weaviate.connect_to_custom") as mock_connect:
                config = ConfigManager(config_file="test_config.json")
                config.get_client()

                mock_connect.assert_called_once()
                call_kwargs = mock_connect.call_args.kwargs
                assert call_kwargs["http_host"] == "weaviate.google.my-cloud.com"
                assert call_kwargs["grpc_host"] == "grpc.weaviate.google.my-cloud.com"
                assert call_kwargs["http_port"] == 443
                assert call_kwargs["grpc_port"] == 443
                assert call_kwargs["http_secure"] is True
                assert call_kwargs["grpc_secure"] is True


def test_get_client_with_host_and_custom_with_ports():
    config_data = {
        "host": "https://weaviate.google.my-cloud.com",
        "grpc_host": "https://grpc.weaviate.google.my-cloud.com",
        "http_port": 8080,
        "grpc_port": 8080,
    }

    with patch("builtins.open", mock_open(read_data=json.dumps(config_data))):
        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = True
            with patch("weaviate.connect_to_custom") as mock_connect:
                config = ConfigManager(config_file="test_config.json")
                config.get_client()

                mock_connect.assert_called_once()
                call_kwargs = mock_connect.call_args.kwargs
                assert call_kwargs["http_host"] == "weaviate.google.my-cloud.com"
                assert call_kwargs["grpc_host"] == "grpc.weaviate.google.my-cloud.com"
                assert call_kwargs["http_port"] == 8080
                assert call_kwargs["grpc_port"] == 8080
                assert call_kwargs["http_secure"] is True  # URL contains https
                assert call_kwargs["grpc_secure"] is True  # URL contains https


def test_env_vars_override_config_file_and_connect_wcd():
    config_data = {"host": "localhost", "http_port": 8080, "grpc_port": 50051}
    env = {
        "WEAVIATE_URL": "https://demo.c0.us-west3.gcp.weaviate.cloud/",
        "WEAVIATE_API_KEY": "env-secret",
    }

    with patch("builtins.open", mock_open(read_data=json.dumps(config_data))):
        with patch("os.path.isfile", return_value=True):
            with patch("weaviate.connect_to_weaviate_cloud") as mock_connect:
                config = ConfigManager(config_file="test_config.json", env=env)
                assert config.source == "env"
                config.get_client()

                mock_connect.assert_called_once()
                kwargs = mock_connect.call_args.kwargs
                assert (
                    kwargs["cluster_url"]
                    == "https://demo.c0.us-west3.gcp.weaviate.cloud"
                )
                assert kwargs["auth_credentials"].api_key == "env-secret"


def test_cli_flags_override_env_vars():
    env = {
        "WEAVIATE_URL": "https://env.c0.us-west3.gcp.weaviate.cloud",
        "WEAVIATE_API_KEY": "env-secret",
    }
    with patch("pathlib.Path.exists", return_value=False):
        with patch("weaviate.connect_to_weaviate_cloud") as mock_connect:
            config = ConfigManager(
                url="https://flag.c0.us-west3.gcp.weaviate.cloud",
                api_key="flag-secret",
                env=env,
            )
            assert config.source == "flag"
            config.get_client()

            kwargs = mock_connect.call_args.kwargs
            assert (
                kwargs["cluster_url"] == "https://flag.c0.us-west3.gcp.weaviate.cloud"
            )
            assert kwargs["auth_credentials"].api_key == "flag-secret"


def test_env_custom_url_without_grpc_url_derives_grpc_host():
    env = {"WEAVIATE_URL": "http://127.0.0.1:8080"}
    with patch("pathlib.Path.exists", return_value=False):
        with patch("weaviate.connect_to_custom") as mock_connect:
            config = ConfigManager(env=env)
            config.get_client()

            kwargs = mock_connect.call_args.kwargs
            assert kwargs["http_host"] == "127.0.0.1"
            assert kwargs["http_port"] == 8080
            assert kwargs["grpc_host"] == "127.0.0.1"
            assert kwargs["grpc_port"] == 50051
            assert kwargs["http_secure"] is False
            assert kwargs["grpc_secure"] is False


def test_grpc_url_accepts_schemeless_host_port():
    with patch("pathlib.Path.exists", return_value=False):
        with patch("weaviate.connect_to_custom") as mock_connect:
            config = ConfigManager(
                url="http://127.0.0.1:18080",
                grpc_url="127.0.0.1:51051",
                env={},
            )
            config.get_client()

            kwargs = mock_connect.call_args.kwargs
            assert kwargs["http_host"] == "127.0.0.1"
            assert kwargs["http_port"] == 18080
            assert kwargs["grpc_host"] == "127.0.0.1"
            assert kwargs["grpc_port"] == 51051
            assert kwargs["grpc_secure"] is False


def test_wcd_grpc_fallback_warning_routes_to_stderr(capsys):
    from weaviate.exceptions import WeaviateGRPCUnavailableError

    env = {
        "WEAVIATE_URL": "https://demo.c0.us-west3.gcp.weaviate.cloud",
        "WEAVIATE_API_KEY": "secret",
    }
    with patch("pathlib.Path.exists", return_value=False):
        with patch("weaviate.connect_to_weaviate_cloud") as mock_connect:
            mock_connect.side_effect = [
                WeaviateGRPCUnavailableError("grpc down"),
                MagicMock(),
            ]
            config = ConfigManager(env=env)
            config.get_client()

            captured = capsys.readouterr()
            assert captured.out == ""
            assert "gRPC connection seems unavailable" in captured.err


def test_env_file_loads_and_overrides_ambient_env_without_mixing(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# Local sandbox\n"
        'export WEAVIATE_URL="http://127.0.0.1:8080/" # inline comment\n',
        encoding="utf-8",
    )
    ambient_env = {
        "WEAVIATE_URL": "https://prod.c0.us-west3.gcp.weaviate.cloud",
        "WEAVIATE_API_KEY": "prod-secret-should-not-leak",
    }
    with patch("pathlib.Path.exists", return_value=False):
        with patch("weaviate.connect_to_custom") as mock_connect:
            config = ConfigManager(env_file=str(env_file), env=ambient_env)
            assert config.source == "env_file"
            assert "auth" not in config.config
            config.get_client()

            kwargs = mock_connect.call_args.kwargs
            assert kwargs["http_host"] == "127.0.0.1"
            assert kwargs["http_port"] == 8080
            assert kwargs["auth_credentials"] is None


def test_cli_flags_override_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "WEAVIATE_URL=https://file.c0.us-west3.gcp.weaviate.cloud\n"
        "WEAVIATE_API_KEY='file-secret'\n",
        encoding="utf-8",
    )
    with patch("pathlib.Path.exists", return_value=False):
        with patch("weaviate.connect_to_weaviate_cloud") as mock_connect:
            config = ConfigManager(
                env_file=str(env_file),
                url="https://flag.c0.us-west3.gcp.weaviate.cloud",
                api_key="flag-secret",
                env={},
            )
            assert config.source == "flag"
            config.get_client()

            kwargs = mock_connect.call_args.kwargs
            assert (
                kwargs["cluster_url"] == "https://flag.c0.us-west3.gcp.weaviate.cloud"
            )
            assert kwargs["auth_credentials"].api_key == "flag-secret"


def test_env_file_missing_raises_usage_error(tmp_path):
    from weaviate_cli.errors import CLIError, ExitCode

    with patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(CLIError) as exc_info:
            ConfigManager(env_file=str(tmp_path / "missing.env"), env={})
    assert exc_info.value.code == "ENV_FILE_NOT_FOUND"
    assert exc_info.value.exit_code == ExitCode.USAGE


def test_env_file_with_unrecognized_keys_hints_canonical_without_leaking_secret(
    tmp_path,
):
    from weaviate_cli.errors import CLIError, ExitCode

    env_file = tmp_path / ".env"
    env_file.write_text(
        "WEAVIATE_CLOUD_URL=https://demo.weaviate.cloud\n"
        "WEAVIATE_CLOUD_API_KEY=super-secret-value\n",
        encoding="utf-8",
    )
    with patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(CLIError) as exc_info:
            ConfigManager(env_file=str(env_file), env={})
    err = exc_info.value
    assert err.code == "INVALID_ENV_FILE"
    assert err.exit_code == ExitCode.USAGE
    assert err.hint and "WEAVIATE_CLOUD_URL" in err.hint
    assert "super-secret-value" not in err.message
    assert "super-secret-value" not in (err.hint or "")


def test_env_file_invalid_syntax_raises_invalid_env_file(tmp_path):
    from weaviate_cli.errors import CLIError, ExitCode

    env_file = tmp_path / ".env"
    env_file.write_text("NOT_A_VALID_LINE\n", encoding="utf-8")
    with patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(CLIError) as exc_info:
            ConfigManager(env_file=str(env_file), env={})
    assert exc_info.value.code == "INVALID_ENV_FILE"
    assert exc_info.value.exit_code == ExitCode.USAGE
    assert "line 1" in exc_info.value.message
