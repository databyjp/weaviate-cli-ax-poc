import pytest
import weaviate
import weaviate.classes.config as wvc

from weaviate_cli.managers.collection_manager import CollectionManager
from weaviate_cli.managers.config_manager import ConfigManager
from weaviate_cli.managers.shard_manager import ShardManager


@pytest.fixture
def client() -> weaviate.Client:
    config = ConfigManager()
    return config.get_client()


@pytest.fixture
def collection_manager(client: weaviate.Client) -> CollectionManager:
    return CollectionManager(client)


@pytest.fixture
def shard_manager(client: weaviate.Client) -> ShardManager:
    return ShardManager(client)


def test_collection_lifecycle(collection_manager: CollectionManager):
    col_name = "LifecycleTestCol"
    try:
        # Create collection
        collection_manager.create_collection(
            collection=col_name,
            inverted_index="timestamp",
            replication_factor=1,
            training_limit=100000,
            async_enabled=True,
            vectorizer="contextionary",
        )

        # Verify collection exists
        assert collection_manager.client.collections.exists(col_name)

        # Update collection
        collection_manager.update_collection(
            collection=col_name,
            description="Updated test collection",
            vector_index="hnsw_pq",
            training_limit=100000,
            async_enabled=False,
        )

        # Get collection config to verify update
        col = collection_manager.client.collections.get(col_name)
        config = col.config.get()
        assert config.description == "Updated test collection"
        assert config.replication_config.async_enabled is False

    finally:
        # Delete collection
        if collection_manager.client.collections.exists(col_name):
            collection_manager.delete_collection(collection=col_name)
        assert not collection_manager.client.collections.exists(col_name)


def test_multiple_collections(collection_manager: CollectionManager):
    try:
        # Create multiple collections
        collections = ["Articles", "Books", "Music"]

        for col in collections:
            collection_manager.create_collection(
                collection=col,
                vector_index="flat",
                replication_factor=1,
                shards=2,
                training_limit=100000,
                async_enabled=True,
                vectorizer="contextionary",
            )
            assert collection_manager.client.collections.exists(col)
    finally:
        # Delete all collections
        collection_manager.delete_collection(collection="", all=True)

        # Verify all collections deleted
        for col in collections:
            assert not collection_manager.client.collections.exists(col)


def test_shard_operations(
    collection_manager: CollectionManager,
    shard_manager: ShardManager,
):
    col_name = "ShardTestCol"
    try:
        # Create collection with multiple shards
        collection_manager.create_collection(
            collection=col_name,
            inverted_index="null",
            replication_factor=1,
            training_limit=1000,
            shards=3,
            async_enabled=True,
            vectorizer="none",
        )

        # Get shard info
        col = collection_manager.client.collections.get(col_name)
        col.data.insert_many([{"title": f"Item {i}"} for i in range(10)])

        shards = col.config.get_shards()
        assert len(shards) == 3

        objects = col.with_consistency_level(
            wvc.ConsistencyLevel.ONE
        ).query.fetch_objects(limit=10)
        assert len(objects.objects) == 10
    finally:
        # Clean up
        if collection_manager.client.collections.exists(col_name):
            collection_manager.delete_collection(collection=col_name)


def test_error_handling(collection_manager: CollectionManager):
    try:
        # Test creating duplicate collection
        collection_manager.create_collection(
            collection="TestCol",
            replication_factor=1,
            training_limit=100000,
            async_enabled=True,
            vectorizer="transformers",
        )

        with pytest.raises(Exception, match="already exists"):
            collection_manager.create_collection(
                collection="TestCol",
                replication_factor=1,
                training_limit=100000,
                async_enabled=True,
                vectorizer="transformers",
            )
    finally:
        # Test deleting non-existent collection
        collection_manager.delete_collection(collection="TestCol")

    with pytest.raises(Exception, match="doesn't exist"):
        collection_manager.delete_collection(collection="NonExistentCol")

    # Test updating non-existent collection
    with pytest.raises(Exception, match="does not exist"):
        collection_manager.update_collection(
            collection="NonExistentCol",
            description="Updated description",
            training_limit=100000,
            async_enabled=True,
        )
