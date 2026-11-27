import pytest
import weaviate
import weaviate.classes.config as wvc

from weaviate_cli.managers.collection_manager import CollectionManager
from weaviate_cli.managers.config_manager import ConfigManager
from weaviate_cli.managers.shard_manager import ShardManager


@pytest.fixture
def client() -> weaviate.WeaviateClient:
    config = ConfigManager()
    return config.get_client()


@pytest.fixture
def collection_manager(client: weaviate.WeaviateClient) -> CollectionManager:
    return CollectionManager(client)


@pytest.fixture
def shard_manager(client: weaviate.WeaviateClient) -> ShardManager:
    return ShardManager(client)


def test_collection_lifecycle(collection_manager: CollectionManager):
    col_name = "LifecycleTestCol"
    try:
        collection_manager.create_collection(
            {
                "class": col_name,
                "vectorizer": "text2vec-contextionary",
                "invertedIndexConfig": {"indexTimestamps": True},
                "replicationConfig": {"factor": 1, "asyncEnabled": True},
            }
        )

        assert collection_manager.client.collections.exists(col_name)

        collection_manager.update_collection(
            collection=col_name,
            description="Updated test collection",
            vector_index="hnsw_pq",
            training_limit=100000,
            async_enabled=False,
        )

        col = collection_manager.client.collections.get(col_name)
        config = col.config.get()
        assert config.description == "Updated test collection"
        assert config.replication_config.async_enabled is False

    finally:
        if collection_manager.client.collections.exists(col_name):
            collection_manager.delete_collection(collection=col_name)
        assert not collection_manager.client.collections.exists(col_name)


def test_multiple_collections(collection_manager: CollectionManager):
    collections = ["Articles", "Books", "Music"]
    try:
        for col in collections:
            collection_manager.create_collection(
                {
                    "class": col,
                    "vectorIndexType": "flat",
                    "vectorizer": "text2vec-contextionary",
                    "shardingConfig": {"desiredCount": 2},
                    "replicationConfig": {"factor": 1, "asyncEnabled": True},
                }
            )
            assert collection_manager.client.collections.exists(col)
    finally:
        collection_manager.delete_collection(delete_all=True)

        for col in collections:
            assert not collection_manager.client.collections.exists(col)


def test_shard_operations(
    collection_manager: CollectionManager,
    shard_manager: ShardManager,
):
    col_name = "ShardTestCol"
    try:
        collection_manager.create_collection(
            {
                "class": col_name,
                "vectorizer": "none",
                "invertedIndexConfig": {"indexNullState": True},
                "shardingConfig": {"desiredCount": 3},
                "replicationConfig": {"factor": 1, "asyncEnabled": True},
            }
        )

        col = collection_manager.client.collections.get(col_name)
        col.data.insert_many([{"title": f"Item {i}"} for i in range(10)])

        shards = col.config.get_shards()
        assert len(shards) == 3

        objects = col.with_consistency_level(
            wvc.ConsistencyLevel.ONE
        ).query.fetch_objects(limit=10)
        assert len(objects.objects) == 10
    finally:
        if collection_manager.client.collections.exists(col_name):
            collection_manager.delete_collection(collection=col_name)


def test_error_handling(collection_manager: CollectionManager):
    try:
        collection_manager.create_collection(
            {
                "class": "TestCol",
                "vectorizer": "text2vec-transformers",
                "replicationConfig": {"factor": 1, "asyncEnabled": True},
            }
        )

        with pytest.raises(Exception):
            collection_manager.create_collection(
                {
                    "class": "TestCol",
                    "vectorizer": "text2vec-transformers",
                    "replicationConfig": {"factor": 1, "asyncEnabled": True},
                }
            )
    finally:
        if collection_manager.client.collections.exists("TestCol"):
            collection_manager.delete_collection(collection="TestCol")

    with pytest.raises(Exception):
        collection_manager.delete_collection(collection="NonExistentCol")

    with pytest.raises(Exception):
        collection_manager.update_collection(
            collection="NonExistentCol",
            description="Updated description",
            training_limit=100000,
            async_enabled=True,
        )
