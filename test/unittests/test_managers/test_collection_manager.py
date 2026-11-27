"""Unit tests for CollectionManager adapter (data-only, no stdout coupling)."""

from unittest.mock import MagicMock, patch

import pytest
import weaviate.classes.config as wvc
from weaviate.exceptions import WeaviateConnectionError

from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.managers.collection_manager import CollectionManager


@pytest.fixture
def mock_wvc_object_ttl():
    """Mock ObjectTTL configuration builders."""
    with patch.object(wvc.Reconfigure, "ObjectTTL", create=True) as mock_reconfigure:
        mock_reconfigure.delete_by_creation_time = MagicMock(return_value=MagicMock())
        mock_reconfigure.delete_by_update_time = MagicMock(return_value=MagicMock())
        mock_reconfigure.delete_by_date_property = MagicMock(return_value=MagicMock())
        mock_reconfigure.disable = MagicMock(return_value=MagicMock())
        yield mock_reconfigure


def test_create_collection_from_spec(mock_client):
    mock_collections = MagicMock()
    mock_client.collections = mock_collections
    mock_collections.exists.return_value = False

    manager = CollectionManager(mock_client)
    spec = {"class": "Articles", "vectorizer": "none"}
    result = manager.create_collection(spec)

    mock_collections.create_from_dict.assert_called_once_with(spec)
    assert result == {
        "collection": "Articles",
        "created": True,
        "already_exists": False,
    }


def test_create_collection_existing_raises_conflict(mock_client):
    mock_collections = MagicMock()
    mock_client.collections = mock_collections
    mock_collections.exists.return_value = True

    manager = CollectionManager(mock_client)
    with pytest.raises(CLIError) as exc_info:
        manager.create_collection({"class": "Articles", "vectorizer": "none"})

    assert exc_info.value.code == "COLLECTION_EXISTS"
    assert exc_info.value.exit_code == ExitCode.NOT_FOUND
    mock_collections.create_from_dict.assert_not_called()


def test_create_collection_existing_with_if_not_exists(mock_client):
    mock_collections = MagicMock()
    mock_client.collections = mock_collections
    mock_collections.exists.return_value = True

    manager = CollectionManager(mock_client)
    result = manager.create_collection(
        {"class": "Articles", "vectorizer": "none"}, if_not_exists=True
    )

    assert result == {
        "collection": "Articles",
        "created": False,
        "already_exists": True,
    }
    mock_collections.create_from_dict.assert_not_called()


def test_create_collection_missing_class_raises(mock_client):
    manager = CollectionManager(mock_client)
    with pytest.raises(CLIError) as exc_info:
        manager.create_collection({"vectorizer": "none"})
    assert exc_info.value.code == "INVALID_COLLECTION_SPEC"
    assert exc_info.value.exit_code == ExitCode.USAGE


def test_create_collection_propagates_sdk_errors(mock_client):
    mock_collections = MagicMock()
    mock_client.collections = mock_collections
    mock_collections.exists.return_value = False
    mock_collections.create_from_dict.side_effect = WeaviateConnectionError("down")

    manager = CollectionManager(mock_client)
    with pytest.raises(WeaviateConnectionError):
        manager.create_collection({"class": "Articles"})


def test_get_available_modules(mock_client):
    mock_client.get_meta.return_value = {
        "version": "1.37.1",
        "modules": {"text2vec-weaviate": {}, "generative-openai": {}},
    }
    manager = CollectionManager(mock_client)
    assert manager.get_available_modules() == [
        "generative-openai",
        "text2vec-weaviate",
    ]


def test_get_collection_returns_dict_and_raises_not_found(mock_client):
    mock_collections = MagicMock()
    mock_client.collections = mock_collections
    mock_collections.exists.return_value = True
    mock_col = MagicMock()
    mock_col.config.get.return_value.to_dict.return_value = {
        "class": "Articles",
        "vectorizer": "none",
    }
    mock_collections.get.return_value = mock_col

    manager = CollectionManager(mock_client)
    assert manager.get_collection("Articles") == {
        "class": "Articles",
        "vectorizer": "none",
    }

    mock_collections.exists.return_value = False
    with pytest.raises(CLIError) as exc_info:
        manager.get_collection("Missing")
    assert exc_info.value.code == "COLLECTION_NOT_FOUND"
    assert exc_info.value.exit_code == ExitCode.NOT_FOUND


def test_list_collections(mock_client):
    mock_collections = MagicMock()
    mock_client.collections = mock_collections
    mock_collections.list_all.return_value = {"Articles": MagicMock()}

    mock_col = MagicMock()
    mock_col.__len__.return_value = 42
    mock_schema = MagicMock()
    mock_schema.vector_config = None
    mock_schema.vectorizer = MagicMock(value="text2vec-weaviate")
    mock_schema.vector_index_type = MagicMock(value="hnsw")
    mock_schema.multi_tenancy_config.enabled = False
    mock_schema.replication_config.factor = 1
    mock_col.config.get.return_value = mock_schema
    mock_collections.get.return_value = mock_col

    manager = CollectionManager(mock_client)
    rows = manager.list_collections()
    assert rows == [
        {
            "name": "Articles",
            "multitenancy": False,
            "tenant_count": 0,
            "object_count": 42,
            "replication_factor": 1,
            "vector_index": "hnsw",
            "named_vectors": False,
            "vectorizer": "text2vec-weaviate",
        }
    ]


def test_delete_single_and_all_collections(mock_client):
    mock_collections = MagicMock()
    mock_client.collections = mock_collections
    manager = CollectionManager(mock_client)

    mock_collections.exists.return_value = True
    res = manager.delete_collection("Articles")
    assert res == {"deleted": ["Articles"], "count": 1}
    mock_collections.delete.assert_called_once_with("Articles")

    mock_collections.reset_mock()
    mock_collections.list_all.return_value = ["A", "B"]
    res_all = manager.delete_collection(delete_all=True)
    assert res_all == {"deleted": ["A", "B"], "count": 2}
    assert mock_collections.delete.call_count == 2


def test_delete_collection_missing_raises_not_found(mock_client):
    mock_collections = MagicMock()
    mock_client.collections = mock_collections
    mock_collections.exists.return_value = False
    manager = CollectionManager(mock_client)

    with pytest.raises(CLIError) as exc_info:
        manager.delete_collection("Missing")
    assert exc_info.value.code == "COLLECTION_NOT_FOUND"
    assert exc_info.value.exit_code == ExitCode.NOT_FOUND


def test_update_collection_with_ttl_and_warnings(mock_client, mock_wvc_object_ttl):
    mock_collections = MagicMock()
    mock_client.collections = mock_collections
    mock_collections.exists.return_value = True
    mock_client.get_meta.return_value = {"version": "1.37.3"}

    mock_collection = MagicMock()
    mock_collections.get.return_value = mock_collection
    mock_collection.config.get.return_value = MagicMock(
        replication_config=MagicMock(factor=1),
        multi_tenancy_config=MagicMock(
            enabled=True, auto_tenant_creation=False, auto_tenant_activation=False
        ),
    )

    manager = CollectionManager(mock_client)
    res = manager.update_collection(
        collection="Articles",
        description="Updated",
        replication_factor=3,
        async_enabled=True,
        auto_tenant_creation=True,
        object_ttl_type="property",
        object_ttl_time=3600,
        object_ttl_filter_expired=True,
        object_ttl_property_name="expiresAt",
        async_replication_config={"max_workers": 10},
    )

    assert res["collection"] == "Articles"
    assert res["updated"] is True
    assert any("max_workers removed" in w for w in res["warnings"])
    mock_collection.config.update.assert_called_once()
    mock_wvc_object_ttl.delete_by_date_property.assert_called_once_with(
        property_name="expiresAt",
        ttl_offset=3600,
        filter_expired_objects=True,
    )


def test_update_collection_guardrails(mock_client):
    mock_collections = MagicMock()
    mock_client.collections = mock_collections
    manager = CollectionManager(mock_client)

    with pytest.raises(CLIError) as exc_info:
        manager.update_collection(
            collection="Articles",
            object_ttl_type="create",
            object_ttl_property_name="expiresAt",
        )
    assert exc_info.value.code == "INVALID_TTL_CONFIG"
    assert exc_info.value.exit_code == ExitCode.USAGE

    mock_collections.exists.return_value = False
    with pytest.raises(CLIError) as missing_exc:
        manager.update_collection(collection="Missing", description="hi")
    assert missing_exc.value.code == "COLLECTION_NOT_FOUND"
    assert missing_exc.value.exit_code == ExitCode.NOT_FOUND
