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


def test_add_property_primitive_nested_and_references(mock_client):
    mock_collections = MagicMock()
    mock_client.collections = mock_collections
    mock_collections.exists.return_value = True

    mock_col = MagicMock()
    mock_col.config.get.return_value = MagicMock(
        properties=[MagicMock(name="existing")],
        references=[],
    )
    mock_col.config.get.return_value.properties[0].name = "existing"
    mock_collections.get.return_value = mock_col

    manager = CollectionManager(mock_client)

    # Primitive + nested property
    res = manager.add_property(
        "Articles",
        {
            "name": "meta",
            "dataType": ["object"],
            "description": "Metadata",
            "nestedProperties": [{"name": "source", "dataType": ["text"]}],
        },
    )
    assert res == {
        "collection": "Articles",
        "property": "meta",
        "kind": "property",
        "data_type": ["object"],
        "added": True,
        "already_exists": False,
    }
    mock_col.config.add_property.assert_called_once()
    added_prop = mock_col.config.add_property.call_args[0][0]
    assert isinstance(added_prop, wvc.Property)
    assert added_prop.name == "meta"
    assert added_prop.nestedProperties is not None

    # Single-target cross-reference
    res_ref = manager.add_property(
        "Articles", {"name": "hasAuthor", "dataType": ["Author"]}
    )
    assert res_ref["kind"] == "reference"
    assert isinstance(
        mock_col.config.add_reference.call_args[0][0], wvc.ReferenceProperty
    )

    # Multi-target cross-reference
    res_multi = manager.add_property(
        "Articles", {"name": "related", "dataType": ["Author", "Publisher"]}
    )
    assert res_multi["kind"] == "reference"
    assert isinstance(
        mock_col.config.add_reference.call_args[0][0], wvc.ReferencePropertyMultiTarget
    )

    # Existing property: conflict by default, idempotent with --if-not-exists
    with pytest.raises(CLIError) as exists_exc:
        manager.add_property("Articles", {"name": "existing", "dataType": ["text"]})
    assert exists_exc.value.code == "PROPERTY_EXISTS"
    assert exists_exc.value.exit_code == ExitCode.NOT_FOUND

    skipped = manager.add_property(
        "Articles",
        {"name": "existing", "dataType": ["text"]},
        if_not_exists=True,
    )
    assert skipped["added"] is False
    assert skipped["already_exists"] is True


def test_add_vector_and_delete_vector(mock_client):
    mock_collections = MagicMock()
    mock_client.collections = mock_collections
    mock_collections.exists.return_value = True

    mock_col = MagicMock()
    mock_col.config.get.return_value = MagicMock(
        vector_config={"existing_vec": MagicMock()}
    )
    mock_collections.get.return_value = mock_col

    manager = CollectionManager(mock_client)

    res = manager.add_vector(
        "Articles",
        {
            "title_vec": {
                "vectorizer": {"text2vec-transformers": {"properties": ["title"]}},
                "vectorIndexType": "hfresh",
                "vectorIndexConfig": {"distance": "cosine", "rq": {"bits": 8}},
            }
        },
    )
    assert res == {"collection": "Articles", "added": ["title_vec"], "skipped": []}
    mock_col.config.add_vector.assert_called_once()
    vec_cfg = mock_col.config.add_vector.call_args.kwargs["vector_config"]
    assert vec_cfg.name == "title_vec"

    # Existing vector conflict & if_not_exists skip
    with pytest.raises(CLIError) as exc_info:
        manager.add_vector("Articles", {"existing_vec": {"vectorizer": {"none": {}}}})
    assert exc_info.value.code == "VECTOR_EXISTS"
    assert exc_info.value.exit_code == ExitCode.NOT_FOUND

    res_skip = manager.add_vector(
        "Articles",
        {"existing_vec": {"vectorizer": {"none": {}}}},
        if_not_exists=True,
    )
    assert res_skip == {
        "collection": "Articles",
        "added": [],
        "skipped": ["existing_vec"],
    }

    # delete_vector delegates to delete_vector_index
    del_res = manager.delete_vector("Articles", "title_vec")
    mock_col.config.delete_vector_index.assert_called_once_with("title_vec")
    assert del_res["deleted"] is True
    assert del_res["async"] is True


def test_update_collection_from_spec_and_named_vector_flags(mock_client):
    mock_collections = MagicMock()
    mock_client.collections = mock_collections
    mock_collections.exists.return_value = True

    mock_col = MagicMock()
    mock_vec = MagicMock()
    mock_vec.vector_index_config.vector_index_type.return_value = MagicMock(
        value="hnsw"
    )
    mock_col.config.get.return_value = MagicMock(
        vector_config={"title_vec": mock_vec},
        vectorizer=None,
        vector_index_type=None,
        replication_config=MagicMock(factor=1),
        multi_tenancy_config=MagicMock(
            enabled=False, auto_tenant_creation=False, auto_tenant_activation=False
        ),
    )
    mock_collections.get.return_value = mock_col

    manager = CollectionManager(mock_client)

    # Declarative spec update covering BM25/stopwords, named vector RQ+PathSeer, generative & reranker
    res = manager.update_collection_from_spec(
        "Articles",
        {
            "description": "Evolved",
            "propertyDescriptions": {"title": "Article title"},
            "invertedIndexConfig": {
                "bm25": {"b": 0.7, "k1": 1.3},
                "stopwords": {"preset": "en", "additions": ["the"]},
            },
            "vectorConfig": {
                "title_vec": {
                    "vectorIndexConfig": {
                        "filterStrategy": "pathseer",
                        "rq": {"enabled": True, "bits": 8},
                    }
                }
            },
            "generativeConfig": {"generative-openai": {"model": "gpt-4o"}},
            "rerankerConfig": {"reranker-cohere": {"model": "rerank-v3.5"}},
        },
    )
    assert res["updated"] is True
    update_kwargs = mock_col.config.update.call_args.kwargs
    assert update_kwargs["description"] == "Evolved"
    assert update_kwargs["property_descriptions"] == {"title": "Article title"}
    assert update_kwargs["inverted_index_config"] is not None
    assert update_kwargs["vector_config"].name == "title_vec"
    assert update_kwargs["generative_config"] is not None
    assert update_kwargs["reranker_config"] is not None

    # Flag-based update auto-targets single named vector with RQ + PathSeer
    mock_col.config.update.reset_mock()
    manager.update_collection(
        collection="Articles",
        vector_index="hnsw_rq",
        rq_bits=4,
        filter_strategy="pathseer",
    )
    flag_kwargs = mock_col.config.update.call_args.kwargs
    assert flag_kwargs["vectorizer_config"] is None
    assert flag_kwargs["vector_config"].name == "title_vec"
    assert flag_kwargs["vector_config"].vectorIndexConfig.quantizer.bits == 4
    assert (
        flag_kwargs["vector_config"].vectorIndexConfig.filterStrategy
        == wvc.VectorFilterStrategy.PATHSEER
    )

    # Multiple named vectors without --vector-name raises MISSING_VECTOR_NAME
    mock_col.config.get.return_value.vector_config = {
        "title_vec": mock_vec,
        "body_vec": mock_vec,
    }
    with pytest.raises(CLIError) as multi_exc:
        manager.update_collection(collection="Articles", vector_index="hnsw_pathseer")
    assert multi_exc.value.code == "MISSING_VECTOR_NAME"
    assert multi_exc.value.exit_code == ExitCode.USAGE


def test_delete_property_index(mock_client):
    mock_collections = MagicMock()
    mock_client.collections = mock_collections
    mock_collections.exists.return_value = True
    mock_col = MagicMock()
    mock_col.config.delete_property_index.return_value = True
    mock_collections.get.return_value = mock_col

    manager = CollectionManager(mock_client)
    res = manager.delete_property_index("Articles", "price", "range-filters")
    assert res == {
        "collection": "Articles",
        "property": "price",
        "index_type": "rangeFilters",
        "deleted": True,
    }
    mock_col.config.delete_property_index.assert_called_once_with(
        property_name="price", index_name="rangeFilters"
    )
