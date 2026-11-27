from __future__ import annotations

import json
from typing import Any

import click
from prettytable import PrettyTable
from weaviate.client import WeaviateClient

from weaviate_cli.types.models import CollectionInfo, NodeInfo, ShardInfo

_RAFT_SUFFRAGE_LABELS: dict[int, str] = {
    0: "Voter",
    1: "Nonvoter",
    2: "Staging",
}


def _format_suffrage(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return _RAFT_SUFFRAGE_LABELS.get(value, str(value))
    return value


def _serialize_raft_stats(raft: Any) -> dict[str, Any] | None:
    if raft is None:
        return None
    latest_cfg = getattr(raft, "latest_configuration", None) or []
    members = [
        {
            "node_id": getattr(m, "node_id", None),
            "address": getattr(m, "address", None),
            "suffrage": _format_suffrage(getattr(m, "suffrage", None)),
        }
        for m in latest_cfg
    ]
    return {
        "state": getattr(raft, "state", None),
        "term": getattr(raft, "term", None),
        "applied_index": getattr(raft, "applied_index", None),
        "commit_index": getattr(raft, "commit_index", None),
        "fsm_pending": getattr(raft, "fsm_pending", None),
        "last_contact": getattr(raft, "last_contact", None),
        "last_log_index": getattr(raft, "last_log_index", None),
        "last_log_term": getattr(raft, "last_log_term", None),
        "last_snapshot_index": getattr(raft, "last_snapshot_index", None),
        "last_snapshot_term": getattr(raft, "last_snapshot_term", None),
        "latest_configuration_index": getattr(raft, "latest_configuration_index", None),
        "latest_configuration": members,
        "num_peers": getattr(raft, "num_peers", None),
    }


class NodeManager:
    def __init__(self, client: WeaviateClient):
        self.client = client

    def get_cluster_statistics(self, *, json_output: bool = False) -> dict[str, Any]:
        """Fetch Raft consensus statistics from GET /v1/cluster/statistics."""
        stats = self.client.cluster.statistics()
        raw_nodes = getattr(stats, "statistics", None) or []
        node_entries: list[dict[str, Any]] = []
        for entry in raw_nodes:
            node_entries.append(
                {
                    "name": getattr(entry, "name", None),
                    "status": getattr(entry, "status", None),
                    "ready": getattr(entry, "ready", None),
                    "db_loaded": getattr(entry, "db_loaded", None),
                    "is_voter": getattr(entry, "is_voter", None),
                    "is_open": getattr(entry, "is_open", None),
                    "leader_id": getattr(entry, "leader_id", None),
                    "leader_address": getattr(entry, "leader_address", None),
                    "initial_last_applied_index": getattr(
                        entry, "initial_last_applied_index", None
                    ),
                    "candidates": getattr(entry, "candidates", None),
                    "raft": _serialize_raft_stats(getattr(entry, "raft", None)),
                }
            )

        payload: dict[str, Any] = {
            "synchronized": bool(getattr(stats, "synchronized", False)),
            "nodes": node_entries,
        }

        if json_output:
            click.echo(json.dumps(payload, indent=2, default=str))
        else:
            click.echo(f"Cluster Synchronized: {payload['synchronized']}")
            if not node_entries:
                click.echo("No node statistics reported.")
            else:
                table = PrettyTable()
                table.field_names = [
                    "Node",
                    "Status",
                    "Ready",
                    "Raft State",
                    "Leader",
                    "Term",
                    "Applied/Commit",
                    "FSM Pending",
                    "Voter",
                ]
                table.align = "l"
                for node in node_entries:
                    raft = node["raft"] or {}
                    applied = raft.get("applied_index", "-")
                    commit = raft.get("commit_index", "-")
                    table.add_row(
                        [
                            node["name"],
                            node["status"],
                            node["ready"],
                            raft.get("state", "-"),
                            node["leader_id"] or "-",
                            raft.get("term", "-"),
                            f"{applied}/{commit}",
                            raft.get("fsm_pending", "-"),
                            node["is_voter"],
                        ]
                    )
                click.echo(table)
        return payload

    def get_nodes(
        self,
        minimal: bool = False,
        shards: bool = False,
        collections: bool = False,
        collection: str | None = None,
        shard: str | None = None,
        json_output: bool = False,
    ) -> None:
        if minimal:
            nodes = self.__get_nodes_minimal()
            if json_output:
                nodes_data = [
                    {"name": n.name, "status": str(n.status), "version": n.version}
                    for n in nodes
                ]
                click.echo(json.dumps({"nodes": nodes_data}, indent=2, default=str))
            else:
                self.__print_minimal_nodes(nodes)
        else:
            nodes = self.__get_nodes_verbose(collection=collection, shard=shard)
            if collection:
                collection_shards = self.get_collection_shards(
                    collection, nodes, shard_name=shard
                )
                if json_output:
                    rf = (
                        self.client.collections.get(collection)
                        .config.get()
                        .replication_config.factor
                    )
                    shards_data = [
                        {
                            "name": s.name,
                            "node_distribution": s.node_objects,
                            "status": str(s.vector_indexing_status),
                            "vector_queue_length": s.vector_queue_length,
                            "compressed": s.compressed,
                            "loaded": s.loaded,
                        }
                        for s in collection_shards
                    ]
                    click.echo(
                        json.dumps(
                            {
                                "collection": collection,
                                "replication_factor": rf,
                                "shards": shards_data,
                            },
                            indent=2,
                            default=str,
                        )
                    )
                else:
                    self.__print_collection_shards(collection, collection_shards)
            elif shards or shard:
                shard_objects = self.get_shards_objects(nodes, shard_name=shard)
                if json_output:
                    shards_data = [
                        {
                            "name": s.name,
                            "collection": s.collection,
                            "node_distribution": s.node_objects,
                            "status": str(s.vector_indexing_status),
                            "vector_queue_length": s.vector_queue_length,
                            "compressed": s.compressed,
                            "loaded": s.loaded,
                        }
                        for s in shard_objects
                    ]
                    click.echo(
                        json.dumps({"shards": shards_data}, indent=2, default=str)
                    )
                else:
                    self.__print_shards_info(shard_objects)
            elif collections:
                collection_objects = self.get_collections_objects(nodes)
                if json_output:
                    cols_data = []
                    for c in collection_objects:
                        rf = (
                            self.client.collections.get(c.name)
                            .config.get()
                            .replication_config.factor
                        )
                        cols_data.append(
                            {
                                "name": c.name,
                                "replication_factor": rf,
                                "node_distribution": c.node_objects,
                                "total_objects": c.total_objects,
                            }
                        )
                    click.echo(
                        json.dumps({"collections": cols_data}, indent=2, default=str)
                    )
                else:
                    self.__print_collections_info(collection_objects)
            else:
                node_objects = self.get_nodes_objects(nodes)
                if json_output:
                    nodes_data = [
                        {
                            "name": n.name,
                            "status": str(n.status),
                            "version": n.version,
                            "object_count": n.object_count,
                            "shard_count": n.shard_count,
                        }
                        for n in node_objects
                    ]
                    click.echo(json.dumps({"nodes": nodes_data}, indent=2, default=str))
                else:
                    self.__print_nodes_info(node_objects)

    def get_nodes_objects(self, nodes=None) -> list[NodeInfo]:
        if nodes is None:
            nodes = self.__get_nodes_verbose()

        node_infos = []
        for node in nodes:
            object_count = (
                sum(shard.object_count for shard in node.shards) if node.shards else 0
            )
            shard_count = len(node.shards) if node.shards else 0

            node_infos.append(
                NodeInfo(
                    name=node.name,
                    status=node.status,
                    version=node.version,
                    object_count=object_count,
                    shard_count=shard_count,
                )
            )
        return node_infos

    def get_shards_objects(
        self, nodes=None, *, shard_name: str | None = None
    ) -> list[ShardInfo]:
        if nodes is None:
            nodes = self.__get_nodes_verbose(shard=shard_name)

        shard_dict: dict[str, ShardInfo] = {}

        for node in nodes:
            if not node.shards:
                continue

            for shard in node.shards:
                if shard_name is not None and shard.name != shard_name:
                    continue
                shard_key = f"{shard.collection}:{shard.name}"
                qlen = int(getattr(shard, "vector_queue_length", 0) or 0)
                compressed = getattr(shard, "compressed", None)
                if shard_key not in shard_dict:
                    shard_dict[shard_key] = ShardInfo(
                        name=shard.name,
                        collection=shard.collection,
                        node_objects={},
                        vector_indexing_status=shard.vector_indexing_status,
                        loaded=shard.loaded,
                        vector_queue_length=qlen,
                        compressed=compressed,
                    )
                else:
                    shard_dict[shard_key].vector_queue_length += qlen
                    if compressed is True:
                        shard_dict[shard_key].compressed = True
                shard_dict[shard_key].node_objects[node.name] = shard.object_count

        return list(shard_dict.values())

    def get_collections_objects(self, nodes=None) -> list[CollectionInfo]:
        if nodes is None:
            nodes = self.__get_nodes_verbose()

        collection_dict: dict[str, CollectionInfo] = {}

        for node in nodes:
            if not node.shards:
                continue

            for shard in node.shards:
                if shard.collection not in collection_dict:
                    collection_dict[shard.collection] = CollectionInfo(
                        name=shard.collection, node_objects={}, total_objects=0
                    )

                current_count = collection_dict[shard.collection].node_objects.get(
                    node.name, 0
                )
                collection_dict[shard.collection].node_objects[node.name] = (
                    current_count + shard.object_count
                )
                collection_dict[shard.collection].total_objects += shard.object_count

        return list(collection_dict.values())

    def get_collection_shards(
        self,
        collection_name: str,
        nodes=None,
        *,
        shard_name: str | None = None,
    ) -> list[ShardInfo]:
        """Get shard information for a specific collection."""
        if nodes is None:
            nodes = self.__get_nodes_verbose(
                collection=collection_name, shard=shard_name
            )

        shard_dict: dict[str, ShardInfo] = {}

        for node in nodes:
            if not node.shards:
                continue

            for shard in node.shards:
                if shard.collection != collection_name:
                    continue
                if shard_name is not None and shard.name != shard_name:
                    continue

                qlen = int(getattr(shard, "vector_queue_length", 0) or 0)
                compressed = getattr(shard, "compressed", None)
                if shard.name not in shard_dict:
                    shard_dict[shard.name] = ShardInfo(
                        name=shard.name,
                        collection=shard.collection,
                        node_objects={},
                        vector_indexing_status=shard.vector_indexing_status,
                        loaded=shard.loaded,
                        vector_queue_length=qlen,
                        compressed=compressed,
                    )
                else:
                    shard_dict[shard.name].vector_queue_length += qlen
                    if compressed is True:
                        shard_dict[shard.name].compressed = True
                shard_dict[shard.name].node_objects[node.name] = shard.object_count

        return list(shard_dict.values())

    def __print_collection_shards(self, collection_name: str, shards: list[ShardInfo]):
        """Print shard information for a specific collection."""
        if not shards:
            click.echo(f"No shards found for collection '{collection_name}'")
            return

        table = PrettyTable()
        table.field_names = [
            "Shard Name",
            "Node Distribution",
            "Status",
            "Queue Length",
            "Compressed",
            "Loaded",
        ]

        rf = (
            self.client.collections.get(collection_name)
            .config.get()
            .replication_config.factor
        )

        for shard in shards:
            node_dist = ", ".join(
                [f"{node}: {count}" for node, count in shard.node_objects.items()]
            )
            table.add_row(
                [
                    shard.name,
                    node_dist,
                    shard.vector_indexing_status,
                    shard.vector_queue_length,
                    shard.compressed,
                    shard.loaded,
                ]
            )

        click.echo(f"\nCollection: {collection_name} (Replication Factor: {rf})")
        click.echo(table)

    def __get_nodes_verbose(
        self, collection: str | None = None, shard: str | None = None
    ):
        kwargs: dict[str, Any] = {"output": "verbose", "collection": collection}
        if shard is not None:
            kwargs["shard"] = shard
        return self.client.cluster.nodes(**kwargs)

    def __get_nodes_minimal(self):
        return self.client.cluster.nodes(output="minimal")

    def __print_minimal_nodes(self, nodes):
        table = PrettyTable()
        table.field_names = ["Node Name", "Status", "Version"]

        for node in nodes:
            table.add_row([node.name, node.status, node.version])

        click.echo(table)

    def __print_nodes_info(self, nodes: list[NodeInfo]):
        table = PrettyTable()
        table.field_names = [
            "Node Name",
            "Status",
            "Version",
            "Object Count",
            "Shard Count",
        ]

        for node in nodes:
            table.add_row(
                [
                    node.name,
                    node.status,
                    node.version,
                    node.object_count,
                    node.shard_count,
                ]
            )

        click.echo(table)

    def __print_shards_info(self, shards: list[ShardInfo]):
        table = PrettyTable()
        table.field_names = [
            "Shard Name",
            "Collection",
            "Node Distribution",
            "Status",
            "Queue Length",
            "Compressed",
            "Loaded",
        ]

        for shard in shards:
            node_dist = ", ".join(
                [f"{node}: {count}" for node, count in shard.node_objects.items()]
            )
            table.add_row(
                [
                    shard.name,
                    shard.collection,
                    node_dist,
                    shard.vector_indexing_status,
                    shard.vector_queue_length,
                    shard.compressed,
                    shard.loaded,
                ]
            )

        click.echo(table)

    def __print_collections_info(self, collections: list[CollectionInfo]):
        table = PrettyTable()
        table.field_names = [
            "Col. Name",
            "Repl. Factor",
            "Node Distribution",
            "Total Objects",
        ]

        for collection in collections:
            rf = (
                self.client.collections.get(collection.name)
                .config.get()
                .replication_config.factor
            )
            node_dist = ", ".join(
                [f"{node}: {count}" for node, count in collection.node_objects.items()]
            )
            table.add_row([collection.name, rf, node_dist, collection.total_objects])

        click.echo(table)
