from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from weaviate_cli.managers.node_manager import NodeManager


@dataclass
class Stats:
    object_count: int
    shard_count: int


@dataclass
class Shard:
    collection: str
    name: str
    node: str
    object_count: int
    vector_indexing_status: str
    vector_queue_length: int
    compressed: bool
    loaded: bool


@dataclass
class Node:
    git_hash: str
    name: str
    shards: list[Shard] | None
    stats: Stats | None
    status: str
    version: str


@pytest.fixture
def mock_client():
    return Mock()


@pytest.fixture
def empty_cluster_nodes():
    return [
        Node(
            git_hash="cca3177",
            name="weaviate-0",
            shards=None,
            stats=Stats(object_count=0, shard_count=0),
            status="HEALTHY",
            version="1.25.25",
        ),
        Node(
            git_hash="cca3177",
            name="weaviate-1",
            shards=None,
            stats=Stats(object_count=0, shard_count=0),
            status="HEALTHY",
            version="1.25.25",
        ),
        Node(
            git_hash="cca3177",
            name="weaviate-2",
            shards=None,
            stats=Stats(object_count=0, shard_count=0),
            status="HEALTHY",
            version="1.25.25",
        ),
        Node(
            git_hash="cca3177",
            name="weaviate-3",
            shards=None,
            stats=Stats(object_count=0, shard_count=0),
            status="HEALTHY",
            version="1.25.25",
        ),
        Node(
            git_hash="cca3177",
            name="weaviate-4",
            shards=None,
            stats=Stats(object_count=0, shard_count=0),
            status="HEALTHY",
            version="1.25.25",
        ),
    ]


@pytest.fixture
def populated_cluster_nodes():
    # Create a subset of the provided data for testing
    return [
        Node(
            git_hash="fd8d6af",
            name="weaviate-0",
            shards=[
                Shard(
                    collection="PreUpgradeEnableAsyncReplicationWithInconsistency",
                    name="LqOOCO4oujNl",
                    node="weaviate-0",
                    object_count=146,
                    vector_indexing_status="READY",
                    vector_queue_length=0,
                    compressed=False,
                    loaded=True,
                ),
                Shard(
                    collection="PostUpgradeEnableAsyncReplicationWithInconsistency",
                    name="UVbYdOHcABet",
                    node="weaviate-0",
                    object_count=190,
                    vector_indexing_status="READY",
                    vector_queue_length=0,
                    compressed=False,
                    loaded=True,
                ),
            ],
            stats=Stats(object_count=336, shard_count=2),
            status="HEALTHY",
            version="1.26.13",
        ),
        Node(
            git_hash="fd8d6af",
            name="weaviate-1",
            shards=[
                Shard(
                    collection="PreUpgradeEnableAsyncReplicationWithInconsistency",
                    name="LqOOCO4oujNl",
                    node="weaviate-1",
                    object_count=146,
                    vector_indexing_status="READY",
                    vector_queue_length=0,
                    compressed=False,
                    loaded=True,
                ),
            ],
            stats=Stats(object_count=146, shard_count=1),
            status="UNHEALTHY",
            version="1.26.13",
        ),
    ]


def test_get_nodes_objects_empty_cluster(mock_client, empty_cluster_nodes):
    mock_client.cluster.nodes.return_value = empty_cluster_nodes
    node_manager = NodeManager(mock_client)

    nodes = node_manager.get_nodes_objects()

    assert len(nodes) == 5
    for node, expected in zip(nodes, empty_cluster_nodes):
        assert node.name == expected.name
        assert node.status == expected.status
        assert node.version == expected.version
        assert node.object_count == 0
        assert node.shard_count == 0


def test_get_nodes_objects_populated_cluster(mock_client, populated_cluster_nodes):
    mock_client.cluster.nodes.return_value = populated_cluster_nodes
    node_manager = NodeManager(mock_client)

    nodes = node_manager.get_nodes_objects()

    assert len(nodes) == 2
    assert nodes[0].name == "weaviate-0"
    assert nodes[0].object_count == 336
    assert nodes[0].shard_count == 2
    assert nodes[0].status == "HEALTHY"

    assert nodes[1].name == "weaviate-1"
    assert nodes[1].object_count == 146
    assert nodes[1].shard_count == 1
    assert nodes[1].status == "UNHEALTHY"


def test_get_shards_objects_empty_cluster(mock_client, empty_cluster_nodes):
    mock_client.cluster.nodes.return_value = empty_cluster_nodes
    node_manager = NodeManager(mock_client)

    shards = node_manager.get_shards_objects()

    assert len(shards) == 0


def test_get_shards_objects_populated_cluster(mock_client, populated_cluster_nodes):
    mock_client.cluster.nodes.return_value = populated_cluster_nodes
    node_manager = NodeManager(mock_client)

    shards = node_manager.get_shards_objects()

    assert len(shards) == 2

    # Check first shard
    shard = next(s for s in shards if s.name == "LqOOCO4oujNl")
    assert shard.collection == "PreUpgradeEnableAsyncReplicationWithInconsistency"
    assert shard.node_objects == {"weaviate-0": 146, "weaviate-1": 146}
    assert shard.vector_indexing_status == "READY"
    assert shard.loaded is True


def test_get_collections_objects_empty_cluster(mock_client, empty_cluster_nodes):
    mock_client.cluster.nodes.return_value = empty_cluster_nodes
    node_manager = NodeManager(mock_client)

    collections = node_manager.get_collections_objects()

    assert len(collections) == 0


def test_get_collections_objects_populated_cluster(
    mock_client, populated_cluster_nodes
):
    mock_client.cluster.nodes.return_value = populated_cluster_nodes
    node_manager = NodeManager(mock_client)

    collections = node_manager.get_collections_objects()

    assert len(collections) == 2

    # Check PreUpgrade collection
    pre_upgrade = next(
        c
        for c in collections
        if c.name == "PreUpgradeEnableAsyncReplicationWithInconsistency"
    )
    assert pre_upgrade.node_objects == {"weaviate-0": 146, "weaviate-1": 146}
    assert pre_upgrade.total_objects == 292

    # Check PostUpgrade collection
    post_upgrade = next(
        c
        for c in collections
        if c.name == "PostUpgradeEnableAsyncReplicationWithInconsistency"
    )
    assert post_upgrade.node_objects == {"weaviate-0": 190}
    assert post_upgrade.total_objects == 190


def test_get_collection_shards(mock_client, populated_cluster_nodes):
    mock_client.cluster.nodes.return_value = populated_cluster_nodes
    node_manager = NodeManager(mock_client)

    shards = node_manager.get_collection_shards(
        "PreUpgradeEnableAsyncReplicationWithInconsistency"
    )

    assert len(shards) == 1
    assert shards[0].name == "LqOOCO4oujNl"
    assert shards[0].node_objects == {"weaviate-0": 146, "weaviate-1": 146}
    assert shards[0].vector_indexing_status == "READY"
    assert shards[0].loaded is True


def test_get_collection_shards_nonexistent_collection(
    mock_client, populated_cluster_nodes
):
    mock_client.cluster.nodes.return_value = populated_cluster_nodes
    node_manager = NodeManager(mock_client)

    shards = node_manager.get_collection_shards("NonexistentCollection")

    assert len(shards) == 0


def test_node_list_surfaces_queue_length_compressed_and_shard_filter(
    mock_client, populated_cluster_nodes, capsys
):
    import json

    populated_cluster_nodes[0].shards[0].vector_queue_length = 42
    populated_cluster_nodes[0].shards[0].compressed = True
    populated_cluster_nodes[1].shards[0].vector_queue_length = 8
    mock_client.cluster.nodes.return_value = populated_cluster_nodes

    node_manager = NodeManager(mock_client)
    node_manager.get_nodes(shard="LqOOCO4oujNl", json_output=True)

    mock_client.cluster.nodes.assert_called_once_with(
        output="verbose", collection=None, shard="LqOOCO4oujNl"
    )
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["shards"]) == 1
    assert payload["shards"][0]["name"] == "LqOOCO4oujNl"
    assert payload["shards"][0]["vector_queue_length"] == 50
    assert payload["shards"][0]["compressed"] is True


def test_get_cluster_statistics_json_and_text(mock_client, capsys):
    import json
    from types import SimpleNamespace

    mock_client.cluster.statistics.return_value = SimpleNamespace(
        synchronized=True,
        statistics=[
            SimpleNamespace(
                name="weaviate-0",
                status="HEALTHY",
                ready=True,
                db_loaded=True,
                is_voter=True,
                is_open=True,
                leader_id="weaviate-0",
                leader_address="10.0.0.1:8300",
                initial_last_applied_index=120,
                candidates={},
                raft=SimpleNamespace(
                    state="Leader",
                    term=3,
                    applied_index=120,
                    commit_index=120,
                    fsm_pending=0,
                    last_contact="0",
                    last_log_index=120,
                    last_log_term=3,
                    last_snapshot_index=100,
                    last_snapshot_term=2,
                    latest_configuration_index=1,
                    latest_configuration=[
                        SimpleNamespace(
                            node_id="weaviate-0",
                            address="10.0.0.1:8300",
                            suffrage=0,
                        )
                    ],
                    num_peers=0,
                ),
            )
        ],
    )

    node_manager = NodeManager(mock_client)
    res = node_manager.get_cluster_statistics(json_output=True)
    assert res["synchronized"] is True
    assert res["nodes"][0]["raft"]["state"] == "Leader"
    assert res["nodes"][0]["raft"]["latest_configuration"][0]["suffrage"] == "Voter"
    out_json = json.loads(capsys.readouterr().out)
    assert out_json["synchronized"] is True
    assert out_json["nodes"][0]["raft"]["applied_index"] == 120

    node_manager.get_cluster_statistics(json_output=False)
    out_text = capsys.readouterr().out
    assert "Cluster Synchronized: True" in out_text
    assert "Leader" in out_text
    assert "120/120" in out_text
