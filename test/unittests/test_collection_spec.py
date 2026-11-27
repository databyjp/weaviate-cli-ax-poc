"""Pure unit tests for weaviate_cli.specs.collection (no I/O, no mocks)."""

import copy
import json

import pytest

from weaviate_cli.errors import CLIError, ExitCode
from weaviate_cli.specs.collection import (
    extract_referenced_modules,
    get_collection_template,
    is_cross_reference_data_type,
    parse_collection_json,
    validate_collection_spec,
    validate_collection_update_spec,
    validate_property_spec,
    validate_vector_add_spec,
)


def test_template_is_valid():
    template = get_collection_template()
    prepared, issues = validate_collection_spec(template)
    assert issues == []
    assert prepared["class"] == "Articles"


def test_parse_collection_json_valid():
    parsed = parse_collection_json('{"class": "Articles"}')
    assert parsed == {"class": "Articles"}


def test_parse_collection_json_invalid_syntax():
    with pytest.raises(CLIError) as exc_info:
        parse_collection_json('{"class": "Articles",}', source="schema.json")
    err = exc_info.value
    assert err.code == "INVALID_JSON"
    assert err.exit_code == ExitCode.USAGE
    assert "line 1" in err.message
    assert err.hint and "--template" in err.hint


def test_parse_collection_json_non_object():
    with pytest.raises(CLIError) as exc_info:
        parse_collection_json('["Articles"]', source="schema.json")
    assert exc_info.value.code == "INVALID_COLLECTION_SPEC"
    assert exc_info.value.exit_code == ExitCode.USAGE


def test_validate_rejects_top_level_name_strictly():
    _, issues = validate_collection_spec({"name": "Articles", "vectorizer": "none"})
    assert len(issues) == 1
    assert issues[0].path == "name"
    assert issues[0].code == "INVALID_FIELD"
    assert issues[0].hint and '"class"' in issues[0].hint


def test_validate_detects_piped_cli_envelope():
    envelope = {
        "data": {"class": "Articles", "vectorizer": "none"},
        "error": None,
        "metadata": {"command": "collection get", "exit_code": 0},
    }
    _, issues = validate_collection_spec(envelope)
    assert len(issues) == 1
    assert issues[0].code == "UNEXPECTED_ENVELOPE"
    assert issues[0].hint and ".data" in issues[0].hint


def test_validate_class_name_rules():
    _, missing_issues = validate_collection_spec({"vectorizer": "none"})
    assert any(i.path == "class" and i.code == "MISSING_FIELD" for i in missing_issues)

    _, lower_issues = validate_collection_spec({"class": "supportDocs"})
    assert len(lower_issues) == 1
    assert lower_issues[0].code == "INVALID_NAME"
    assert lower_issues[0].hint and "SupportDocs" in lower_issues[0].hint

    _, bad_chars = validate_collection_spec({"class": "Support-Docs"})
    assert len(bad_chars) == 1
    assert bad_chars[0].code == "INVALID_NAME"


def test_validate_name_override_does_not_mutate_input():
    original = {"class": "Original", "vectorizer": "none"}
    snapshot = copy.deepcopy(original)
    prepared, issues = validate_collection_spec(original, name_override="Renamed")
    assert issues == []
    assert prepared["class"] == "Renamed"
    assert original == snapshot


def test_validate_unknown_top_level_field_suggests_match():
    _, issues = validate_collection_spec(
        {"class": "Articles", "multitenancyConfig": {"enabled": True}}
    )
    assert len(issues) == 1
    assert issues[0].path == "multitenancyConfig"
    assert issues[0].code == "UNKNOWN_FIELD"
    assert issues[0].hint and "multiTenancyConfig" in issues[0].hint


def test_validate_property_footguns():
    spec = {
        "class": "Articles",
        "properties": [
            {"name": "title", "dataType": "text"},
            {"name": "summary", "type": "text"},
            {"name": "count", "dataType": ["integer"]},
            {"name": "flag", "dataType": ["bool"]},
            {"name": "title", "dataType": ["text"]},
            {"name": "bad_tok", "dataType": ["text"], "tokenization": "bogus"},
        ],
    }
    _, issues = validate_collection_spec(spec)
    by_path = {(i.path, i.code): i for i in issues}

    assert ("properties[0].dataType", "INVALID_TYPE") in by_path
    assert '["text"]' in (
        by_path[("properties[0].dataType", "INVALID_TYPE")].hint or ""
    )

    assert ("properties[1].type", "INVALID_FIELD") in by_path
    assert ("properties[2].dataType[0]", "INVALID_VALUE") in by_path
    assert '"int"' in (
        by_path[("properties[2].dataType[0]", "INVALID_VALUE")].hint or ""
    )

    assert ("properties[3].dataType[0]", "INVALID_VALUE") in by_path
    assert '"boolean"' in (
        by_path[("properties[3].dataType[0]", "INVALID_VALUE")].hint or ""
    )

    assert ("properties[4].name", "DUPLICATE_PROPERTY") in by_path
    assert ("properties[5].tokenization", "INVALID_VALUE") in by_path


def test_validate_cross_reference_and_nested_properties():
    spec = {
        "class": "Articles",
        "properties": [
            {"name": "hasAuthor", "dataType": ["Author"]},
            {
                "name": "meta",
                "dataType": ["object"],
                "nestedProperties": [
                    {"name": "source", "dataType": ["text"]},
                    {"name": "score", "dataType": "number"},
                ],
            },
        ],
    }
    _, issues = validate_collection_spec(spec)
    assert len(issues) == 1
    assert issues[0].path == "properties[1].nestedProperties[1].dataType"


def test_validate_vectorizer_and_vector_config_rules():
    conflict_spec = {
        "class": "Articles",
        "vectorizer": "text2vec-weaviate",
        "vectorConfig": {
            "default": {
                "vectorizer": {"text2vec-weaviate": {}},
                "vectorIndexType": "hnsw",
            }
        },
    }
    _, conflict_issues = validate_collection_spec(conflict_spec)
    assert any(
        i.path == "vectorConfig" and i.code == "CONFLICTING_FIELDS"
        for i in conflict_issues
    )

    string_vec_spec = {
        "class": "Articles",
        "vectorConfig": {
            "default": {
                "vectorizer": "text2vec-weaviate",
                "vectorIndexType": "unknown_index",
            }
        },
    }
    _, vec_issues = validate_collection_spec(string_vec_spec)
    assert any(
        i.path == "vectorConfig.default.vectorizer" and i.code == "INVALID_TYPE"
        for i in vec_issues
    )
    assert any(
        i.path == "vectorConfig.default.vectorIndexType" and i.code == "INVALID_VALUE"
        for i in vec_issues
    )


def test_validate_multitenancy_sharding_and_replication():
    spec = {
        "class": "Articles",
        "multiTenancyConfig": {"enabled": True},
        "shardingConfig": {"desiredCount": 2},
        "replicationConfig": {"factor": 0, "deletionStrategy": "invalid"},
    }
    _, issues = validate_collection_spec(spec)
    paths = {i.path for i in issues}
    assert "shardingConfig" in paths
    assert "replicationConfig.factor" in paths
    assert "replicationConfig.deletionStrategy" in paths


def test_validate_cluster_available_modules():
    spec = {
        "class": "Articles",
        "vectorConfig": {
            "default": {
                "vectorizer": {"text2vec-transformers": {}},
                "vectorIndexType": "hnsw",
            }
        },
    }
    assert extract_referenced_modules(spec) == [
        (
            "vectorConfig.default.vectorizer.text2vec-transformers",
            "text2vec-transformers",
        )
    ]
    _, issues = validate_collection_spec(
        spec, available_modules=["text2vec-weaviate", "generative-openai"]
    )
    assert len(issues) == 1
    assert issues[0].code == "MODULE_NOT_ENABLED"
    assert "text2vec-weaviate" in (issues[0].hint or "")

    _, ok_issues = validate_collection_spec(
        {"class": "Articles", "vectorizer": "none"},
        available_modules=["text2vec-weaviate"],
    )
    assert ok_issues == []


def test_template_json_round_trip():
    raw = json.dumps(get_collection_template())
    parsed = parse_collection_json(raw)
    _, issues = validate_collection_spec(parsed)
    assert issues == []


def test_validate_rejects_vectorizer_none_and_index_with_vector_config():
    spec_none = {
        "class": "Articles",
        "vectorizer": "none",
        "vectorConfig": {"default": {"vectorizer": {"none": {}}}},
    }
    _, issues_none = validate_collection_spec(spec_none)
    assert any(
        i.path == "vectorConfig" and i.code == "CONFLICTING_FIELDS" for i in issues_none
    )

    spec_idx = {
        "class": "Articles",
        "vectorIndexType": "hnsw",
        "vectorConfig": {"default": {"vectorizer": {"none": {}}}},
    }
    _, issues_idx = validate_collection_spec(spec_idx)
    assert any(
        i.path == "vectorConfig" and i.code == "CONFLICTING_FIELDS" for i in issues_idx
    )


def test_validate_surfaces_all_common_draft_errors_in_one_round():
    draft = {
        "name": "axEvalNotes",
        "properties": [
            {"name": "body", "type": "string", "tokenization": "bogus"},
            {"name": "score", "dataType": "number"},
        ],
        "vectorizer": "none",
        "vectorConfig": {"default": {"vectorizer": {"none": {}}}},
    }
    _, issues = validate_collection_spec(draft)
    by_path = {i.path: i for i in issues}

    assert set(by_path.keys()) == {
        "name",
        "properties[0].type",
        "properties[0].tokenization",
        "properties[1].dataType",
        "vectorConfig",
    }
    assert "AxEvalNotes" in (by_path["name"].hint or "")
    assert '["text"]' in (by_path["properties[0].type"].hint or "")
    assert '["number"]' in (by_path["properties[1].dataType"].hint or "")
    assert by_path["vectorConfig"].code == "CONFLICTING_FIELDS"


def test_validate_property_spec_primitive_nested_and_cross_ref():
    ok_prop, issues = validate_property_spec(
        {
            "name": "tags",
            "dataType": ["text[]"],
            "tokenization": "word",
            "indexFilterable": True,
        }
    )
    assert issues == []
    assert not is_cross_reference_data_type(ok_prop["dataType"])

    ref_prop, ref_issues = validate_property_spec(
        {"name": "related", "dataType": ["Author", "Publisher"]}
    )
    assert ref_issues == []
    assert is_cross_reference_data_type(ref_prop["dataType"])

    _, mixed_issues = validate_property_spec(
        {"name": "bad", "dataType": ["text", "Author"]}
    )
    assert any(i.code == "CONFLICTING_FIELDS" for i in mixed_issues)

    _, alias_issues = validate_property_spec({"name": "bad", "type": "string"})
    assert any(i.path == "property[0].type" for i in alias_issues)


def test_validate_vector_add_spec_map_single_and_modules():
    prepared, issues = validate_vector_add_spec(
        {
            "vectorizer": {"text2vec-transformers": {"properties": ["title"]}},
            "vectorIndexType": "hnsw",
            "vectorIndexConfig": {
                "distance": "cosine",
                "filterStrategy": "pathseer",
                "rq": {"enabled": True, "bits": 8},
            },
        },
        vector_name="title_vec",
        available_modules=["text2vec-transformers"],
    )
    assert issues == []
    assert "title_vec" in prepared

    # Unwrap {"vectorConfig": {...}} cleanly
    unwrapped, unwrap_issues = validate_vector_add_spec(
        {"vectorConfig": {"v1": {"vectorizer": {"none": {}}}}}
    )
    assert unwrap_issues == []
    assert list(unwrapped.keys()) == ["v1"]

    # Rejects disabled module and invalid RQ bits / filterStrategy
    _, bad_issues = validate_vector_add_spec(
        {
            "bad_vec": {
                "vectorizer": {"text2vec-openai": {}},
                "vectorIndexConfig": {
                    "filterStrategy": "unknown",
                    "rq": {"bits": 3},
                },
            }
        },
        available_modules=["text2vec-transformers"],
    )
    codes = {i.code for i in bad_issues}
    assert "MODULE_NOT_ENABLED" in codes
    assert "INVALID_VALUE" in codes


def test_validate_collection_update_spec_mutable_immutable_and_typos():
    ok_patch, issues = validate_collection_update_spec(
        {
            "description": "Updated",
            "propertyDescriptions": {"title": "Doc title"},
            "invertedIndexConfig": {
                "bm25": {"b": 0.7, "k1": 1.3},
                "stopwords": {"preset": "en", "additions": ["foo"]},
                "stopwordPresets": {"custom": ["bar"]},
            },
            "vectorConfig": {
                "title_vec": {
                    "vectorIndexType": "hnsw",
                    "vectorIndexConfig": {
                        "filterStrategy": "pathseer",
                        "rq": {"enabled": True, "bits": 4},
                    },
                }
            },
            "generativeConfig": {"generative-openai": {"model": "gpt-4o"}},
            "rerankerConfig": {"reranker-cohere": {"model": "rerank-v3.5"}},
        },
        available_modules=["generative-openai", "reranker-cohere"],
    )
    assert issues == []
    assert ok_patch["description"] == "Updated"

    _, bad_issues = validate_collection_update_spec(
        {
            "properties": [{"name": "x", "dataType": ["text"]}],
            "descripton": "typo",
            "multiTenancyConfig": {"enabled": True},
            "generativeConfig": {"generative-anthropic": {}},
        },
        available_modules=["generative-openai"],
    )
    by_path = {i.path: i for i in bad_issues}
    assert by_path["properties"].code == "IMMUTABLE_FIELD"
    assert "add-property" in (by_path["properties"].hint or "")
    assert by_path["descripton"].code == "UNKNOWN_FIELD"
    assert "description" in (by_path["descripton"].hint or "")
    assert by_path["multiTenancyConfig.enabled"].code == "IMMUTABLE_FIELD"
    assert by_path["generativeConfig.generative-anthropic"].code == "MODULE_NOT_ENABLED"
