"""Pure collection schema template, parser, and validator for Weaviate /v1/schema JSON.

This module performs zero I/O and never constructs a Weaviate client. Canonical enum
values are borrowed directly from ``weaviate.classes.config`` so validation stays
aligned with the installed client version.
"""

from __future__ import annotations

import copy
import difflib
import json
import re
from collections.abc import Collection
from typing import Any

import weaviate.classes.config as wvc
from weaviate.collections.classes.config_vector_index import VectorIndexType

from weaviate_cli.errors import CLIError, ExitCode, ValidationIssue

_CLASS_NAME_RE = re.compile(r"^[A-Z][_0-9A-Za-z]*$")
_PROPERTY_NAME_RE = re.compile(r"^[_A-Za-z][_0-9A-Za-z]*$")

VALID_DATA_TYPES: frozenset[str] = frozenset(dt.value for dt in wvc.DataType)
VALID_TOKENIZATIONS: frozenset[str] = frozenset(tok.value for tok in wvc.Tokenization)
VALID_VECTOR_INDEX_TYPES: frozenset[str] = frozenset(
    vit.value for vit in VectorIndexType
)
VALID_DISTANCE_METRICS: frozenset[str] = frozenset(
    dist.value for dist in wvc.VectorDistances
)
VALID_DELETION_STRATEGIES: frozenset[str] = frozenset(
    ds.value for ds in wvc.ReplicationDeletionStrategy
)

KNOWN_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "class",
        "description",
        "properties",
        "vectorizer",
        "vectorIndexType",
        "vectorIndexConfig",
        "vectorConfig",
        "moduleConfig",
        "invertedIndexConfig",
        "multiTenancyConfig",
        "replicationConfig",
        "shardingConfig",
        "objectTtlConfig",
        "generativeConfig",
        "rerankerConfig",
    }
)

_DATA_TYPE_ALIASES: dict[str, str] = {
    "str": "text",
    "string": "text",
    "str[]": "text[]",
    "string[]": "text[]",
    "integer": "int",
    "integer[]": "int[]",
    "float": "number",
    "double": "number",
    "float[]": "number[]",
    "double[]": "number[]",
    "bool": "boolean",
    "bool[]": "boolean[]",
    "datetime": "date",
    "timestamp": "date",
    "datetime[]": "date[]",
    "geo": "geoCoordinates",
    "phone": "phoneNumber",
}

COLLECTION_TEMPLATE: dict[str, Any] = {
    "class": "Articles",
    "description": "Collection description",
    "vectorizer": "none",
    "properties": [
        {
            "name": "title",
            "dataType": ["text"],
            "description": "Document title",
        },
        {
            "name": "body",
            "dataType": ["text"],
            "description": "Document body",
        },
    ],
    "multiTenancyConfig": {
        "enabled": False,
    },
}


def get_collection_template() -> dict[str, Any]:
    """Return a fresh copy of the starter Weaviate /v1/schema collection template."""
    return copy.deepcopy(COLLECTION_TEMPLATE)


def parse_collection_json(raw: str, *, source: str = "input") -> dict[str, Any]:
    """Parse raw JSON text into a collection schema dictionary."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CLIError(
            code="INVALID_JSON",
            message=(
                f"Invalid JSON in {source} at line {exc.lineno}, column {exc.colno}: "
                f"{exc.msg}."
            ),
            exit_code=ExitCode.USAGE,
            hint=(
                "Fix the JSON syntax or run 'weaviate-cli collection create --template' "
                "for a valid starter schema."
            ),
        ) from exc

    if not isinstance(parsed, dict):
        raise CLIError(
            code="INVALID_COLLECTION_SPEC",
            message=f"Collection schema in {source} must be a JSON object.",
            exit_code=ExitCode.USAGE,
            hint="Run 'weaviate-cli collection create --template' for a valid starter schema.",
        )

    return parsed


def extract_referenced_modules(spec: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (json_path, module_name) pairs referenced by a collection spec."""
    referenced: list[tuple[str, str]] = []

    vectorizer = spec.get("vectorizer")
    if isinstance(vectorizer, str) and vectorizer and vectorizer != "none":
        referenced.append(("vectorizer", vectorizer))

    vector_config = spec.get("vectorConfig")
    if isinstance(vector_config, dict):
        for vec_name, vec_def in vector_config.items():
            if not isinstance(vec_def, dict):
                continue
            vec_mod = vec_def.get("vectorizer")
            if isinstance(vec_mod, dict):
                for mod_name in vec_mod:
                    if isinstance(mod_name, str) and mod_name and mod_name != "none":
                        referenced.append(
                            (f"vectorConfig.{vec_name}.vectorizer.{mod_name}", mod_name)
                        )

    module_config = spec.get("moduleConfig")
    if isinstance(module_config, dict):
        for mod_name in module_config:
            if isinstance(mod_name, str) and mod_name and mod_name != "none":
                referenced.append((f"moduleConfig.{mod_name}", mod_name))

    return referenced


def _normalize_suggested_data_type(raw_val: Any) -> list[str]:
    """Normalize a property 'type' value into a canonical Weaviate 'dataType' list."""
    if isinstance(raw_val, str) and raw_val.strip():
        cleaned = raw_val.strip()
        return [_DATA_TYPE_ALIASES.get(cleaned.lower(), cleaned)]
    if isinstance(raw_val, list) and raw_val:
        normalized: list[str] = []
        for entry in raw_val:
            if not isinstance(entry, str) or not entry.strip():
                return ["text"]
            cleaned = entry.strip()
            normalized.append(_DATA_TYPE_ALIASES.get(cleaned.lower(), cleaned))
        return normalized
    return ["text"]


def _is_valid_data_type_entry(value: str) -> bool:
    """Return True if value is a valid primitive DataType or cross-reference target."""
    return value in VALID_DATA_TYPES or bool(_CLASS_NAME_RE.match(value))


def _validate_properties(
    properties: Any,
    *,
    path_prefix: str,
    issues: list[ValidationIssue],
) -> None:
    if not isinstance(properties, list):
        issues.append(
            ValidationIssue(
                path=path_prefix,
                code="INVALID_TYPE",
                message=f"Expected a list of property objects, got {type(properties).__name__}.",
                hint='Provide properties as a list, e.g. [{"name": "title", "dataType": ["text"]}].',
            )
        )
        return

    seen_names: set[str] = set()
    for idx, prop in enumerate(properties):
        prop_path = f"{path_prefix}[{idx}]"
        if not isinstance(prop, dict):
            issues.append(
                ValidationIssue(
                    path=prop_path,
                    code="INVALID_TYPE",
                    message=f"Property definition must be an object, got {type(prop).__name__}.",
                )
            )
            continue

        name = prop.get("name")
        if not isinstance(name, str) or not name.strip():
            issues.append(
                ValidationIssue(
                    path=f"{prop_path}.name",
                    code="MISSING_FIELD",
                    message="Property must include a non-empty string 'name'.",
                )
            )
        else:
            if not _PROPERTY_NAME_RE.match(name):
                issues.append(
                    ValidationIssue(
                        path=f"{prop_path}.name",
                        code="INVALID_NAME",
                        message=f"Invalid property name '{name}'.",
                        hint=(
                            "Property names must match ^[_A-Za-z][_0-9A-Za-z]*$ "
                            "(ASCII letters, digits, and underscores)."
                        ),
                    )
                )
            if name in seen_names:
                issues.append(
                    ValidationIssue(
                        path=f"{prop_path}.name",
                        code="DUPLICATE_PROPERTY",
                        message=f"Duplicate property name '{name}'.",
                    )
                )
            seen_names.add(name)

        if "type" in prop and "dataType" not in prop:
            suggested_list = _normalize_suggested_data_type(prop["type"])
            if all(_is_valid_data_type_entry(dt) for dt in suggested_list):
                hint = f'Rename "type" to "dataType": {json.dumps(suggested_list)}.'
            else:
                hint = (
                    'Rename "type" to "dataType" using a valid Weaviate type list '
                    f'(e.g. ["text"]). Valid primitive dataTypes: '
                    f"{', '.join(sorted(VALID_DATA_TYPES))}."
                )
            issues.append(
                ValidationIssue(
                    path=f"{prop_path}.type",
                    code="INVALID_FIELD",
                    message="Property uses 'type' instead of 'dataType'.",
                    hint=hint,
                )
            )
        else:
            data_type = prop.get("dataType")
            if data_type is None:
                issues.append(
                    ValidationIssue(
                        path=f"{prop_path}.dataType",
                        code="MISSING_FIELD",
                        message="Property must specify 'dataType' as a non-empty list of strings.",
                        hint='Example: "dataType": ["text"].',
                    )
                )
            elif isinstance(data_type, str):
                mapped = _DATA_TYPE_ALIASES.get(data_type.lower(), data_type)
                issues.append(
                    ValidationIssue(
                        path=f"{prop_path}.dataType",
                        code="INVALID_TYPE",
                        message=(
                            f'Expected a list of strings (e.g. ["text"]), got string {data_type!r}.'
                        ),
                        hint=f'Wrap dataType in a list: "dataType": ["{mapped}"].',
                    )
                )
            elif not isinstance(data_type, list) or len(data_type) == 0:
                issues.append(
                    ValidationIssue(
                        path=f"{prop_path}.dataType",
                        code="INVALID_TYPE",
                        message="Property 'dataType' must be a non-empty list of strings.",
                        hint='Example: "dataType": ["text"].',
                    )
                )
            else:
                for dt_idx, dt_val in enumerate(data_type):
                    dt_path = f"{prop_path}.dataType[{dt_idx}]"
                    if not isinstance(dt_val, str) or not dt_val:
                        issues.append(
                            ValidationIssue(
                                path=dt_path,
                                code="INVALID_TYPE",
                                message="Each 'dataType' entry must be a non-empty string.",
                            )
                        )
                        continue
                    # Weaviate allows either a built-in DataType or an uppercase
                    # target collection name (cross-reference).
                    if _is_valid_data_type_entry(dt_val):
                        continue
                    alias_target = _DATA_TYPE_ALIASES.get(dt_val.lower())
                    if alias_target:
                        hint = f'Use "{alias_target}" instead of "{dt_val}".'
                    else:
                        hint = (
                            f"Valid primitive dataTypes: {', '.join(sorted(VALID_DATA_TYPES))} "
                            "(or an uppercase target collection name for cross-references)."
                        )
                    issues.append(
                        ValidationIssue(
                            path=dt_path,
                            code="INVALID_VALUE",
                            message=f"Unknown property dataType '{dt_val}'.",
                            hint=hint,
                        )
                    )

        if "tokenization" in prop and prop["tokenization"] is not None:
            tok = prop["tokenization"]
            if not isinstance(tok, str) or tok not in VALID_TOKENIZATIONS:
                issues.append(
                    ValidationIssue(
                        path=f"{prop_path}.tokenization",
                        code="INVALID_VALUE",
                        message=f"Invalid tokenization '{tok}'.",
                        hint=f"Valid values: {', '.join(sorted(VALID_TOKENIZATIONS))}.",
                    )
                )

        if "nestedProperties" in prop and prop["nestedProperties"] is not None:
            _validate_properties(
                prop["nestedProperties"],
                path_prefix=f"{prop_path}.nestedProperties",
                issues=issues,
            )


def _validate_vector_config(
    spec: dict[str, Any],
    issues: list[ValidationIssue],
) -> None:
    vectorizer = spec.get("vectorizer")
    vector_config = spec.get("vectorConfig")

    if vectorizer is not None and not isinstance(vectorizer, str):
        issues.append(
            ValidationIssue(
                path="vectorizer",
                code="INVALID_TYPE",
                message=f"'vectorizer' must be a string, got {type(vectorizer).__name__}.",
                hint='Use a module name like "text2vec-weaviate" or "none".',
            )
        )

    # Weaviate rejects combining any class-level vector setting (including
    # "vectorizer": "none", "vectorIndexType", or "vectorIndexConfig") with
    # named vectors in "vectorConfig".
    conflicting_top_keys: list[str] = []
    if isinstance(vectorizer, str) and bool(vectorizer.strip()):
        conflicting_top_keys.append("'vectorizer'")
    if spec.get("vectorIndexType") is not None:
        conflicting_top_keys.append("'vectorIndexType'")
    if spec.get("vectorIndexConfig") is not None:
        conflicting_top_keys.append("'vectorIndexConfig'")

    has_vector_config = isinstance(vector_config, dict) and len(vector_config) > 0

    if conflicting_top_keys and has_vector_config:
        keys_str = ", ".join(conflicting_top_keys)
        issues.append(
            ValidationIssue(
                path="vectorConfig",
                code="CONFLICTING_FIELDS",
                message=(
                    f"Cannot combine top-level {keys_str} with named vectors in 'vectorConfig'."
                ),
                hint=(
                    f"Remove top-level {keys_str} when using 'vectorConfig' "
                    "(named vectors configure their own vectorizer and index)."
                ),
            )
        )

    if vector_config is not None:
        if not isinstance(vector_config, dict):
            issues.append(
                ValidationIssue(
                    path="vectorConfig",
                    code="INVALID_TYPE",
                    message=f"'vectorConfig' must be an object mapping vector names to configs, got {type(vector_config).__name__}.",
                )
            )
        else:
            for vec_name, vec_def in vector_config.items():
                vec_path = f"vectorConfig.{vec_name}"
                if not isinstance(vec_def, dict):
                    issues.append(
                        ValidationIssue(
                            path=vec_path,
                            code="INVALID_TYPE",
                            message=f"Named vector '{vec_name}' must be a JSON object.",
                        )
                    )
                    continue
                vec_mod = vec_def.get("vectorizer")
                if vec_mod is not None and not isinstance(vec_mod, dict):
                    hint = (
                        f'Use an object keyed by module name: "vectorizer": {{"{vec_mod}": {{}}}}.'
                        if isinstance(vec_mod, str)
                        else 'Use an object keyed by module name, e.g. {"text2vec-weaviate": {}}.'
                    )
                    issues.append(
                        ValidationIssue(
                            path=f"{vec_path}.vectorizer",
                            code="INVALID_TYPE",
                            message=(
                                "Inside 'vectorConfig', 'vectorizer' must be an object keyed by "
                                f"module name, got {type(vec_mod).__name__}."
                            ),
                            hint=hint,
                        )
                    )
                vec_idx_type = vec_def.get("vectorIndexType")
                if vec_idx_type is not None and (
                    not isinstance(vec_idx_type, str)
                    or vec_idx_type not in VALID_VECTOR_INDEX_TYPES
                ):
                    issues.append(
                        ValidationIssue(
                            path=f"{vec_path}.vectorIndexType",
                            code="INVALID_VALUE",
                            message=f"Invalid vectorIndexType '{vec_idx_type}'.",
                            hint=f"Valid values: {', '.join(sorted(VALID_VECTOR_INDEX_TYPES))}.",
                        )
                    )

    if "vectorIndexType" in spec and spec["vectorIndexType"] is not None:
        vit = spec["vectorIndexType"]
        if not isinstance(vit, str) or vit not in VALID_VECTOR_INDEX_TYPES:
            issues.append(
                ValidationIssue(
                    path="vectorIndexType",
                    code="INVALID_VALUE",
                    message=f"Invalid vectorIndexType '{vit}'.",
                    hint=f"Valid values: {', '.join(sorted(VALID_VECTOR_INDEX_TYPES))}.",
                )
            )

    vic = spec.get("vectorIndexConfig")
    if vic is not None:
        if not isinstance(vic, dict):
            issues.append(
                ValidationIssue(
                    path="vectorIndexConfig",
                    code="INVALID_TYPE",
                    message=f"'vectorIndexConfig' must be an object, got {type(vic).__name__}.",
                )
            )
        elif "distance" in vic and vic["distance"] is not None:
            dist = vic["distance"]
            if not isinstance(dist, str) or dist not in VALID_DISTANCE_METRICS:
                issues.append(
                    ValidationIssue(
                        path="vectorIndexConfig.distance",
                        code="INVALID_VALUE",
                        message=f"Invalid distance metric '{dist}'.",
                        hint=f"Valid values: {', '.join(sorted(VALID_DISTANCE_METRICS))}.",
                    )
                )


def validate_collection_spec(
    spec: dict[str, Any],
    *,
    name_override: str | None = None,
    available_modules: Collection[str] | None = None,
) -> tuple[dict[str, Any], list[ValidationIssue]]:
    """Validate a Weaviate /v1/schema collection dict and return neutral evidence.

    Args:
        spec: Raw collection schema dict.
        name_override: Optional CLI NAME argument overriding ``spec["class"]``.
        available_modules: Optional set of module names enabled on the target cluster
            (from ``GET /v1/meta``). When provided, referenced modules are verified.

    Returns:
        Tuple of ``(prepared_spec, issues)``. ``prepared_spec`` is a deep copy of
        ``spec`` with ``name_override`` applied to ``"class"`` when given.
    """
    prepared = copy.deepcopy(spec)
    issues: list[ValidationIssue] = []

    if name_override is not None:
        prepared["class"] = name_override

    # Catch accidentally piped CLI response envelopes ({"data": {"class": ...}}).
    if (
        "class" not in prepared
        and isinstance(prepared.get("data"), dict)
        and "class" in prepared["data"]
    ):
        issues.append(
            ValidationIssue(
                path="data",
                code="UNEXPECTED_ENVELOPE",
                message="Input looks like a CLI JSON response envelope rather than a collection schema.",
                hint="Unwrap the inner '.data' object (e.g. via 'jq .data') before passing to --from-file.",
            )
        )
        return prepared, issues

    # Strictly reject top-level "name" so agents learn canonical /v1/schema syntax,
    # and fold any collection naming issue into the hint to avoid a second round-trip.
    if "name" in prepared:
        raw_name = prepared["name"]
        if (
            "class" not in prepared
            and isinstance(raw_name, str)
            and raw_name.strip()
            and not _CLASS_NAME_RE.match(raw_name)
        ):
            if raw_name[0].islower() and _CLASS_NAME_RE.match(
                raw_name[0].upper() + raw_name[1:]
            ):
                suggested = raw_name[0].upper() + raw_name[1:]
                name_hint = (
                    f'Use "class": "{suggested}" instead of "name" '
                    "(collection names must start with an uppercase ASCII letter)."
                )
            else:
                name_hint = (
                    'Use "class" instead of "name", and ensure the collection name '
                    "starts with an uppercase ASCII letter and contains only ASCII "
                    "letters, digits, and underscores (^[A-Z][_0-9A-Za-z]*$)."
                )
        else:
            name_hint = 'Use "class" instead of "name" for the collection name.'
        issues.append(
            ValidationIssue(
                path="name",
                code="INVALID_FIELD",
                message="Top-level 'name' is not valid in Weaviate /v1/schema JSON.",
                hint=name_hint,
            )
        )

    # Validate collection name ("class").
    class_name = prepared.get("class")
    if class_name is None:
        if "name" not in prepared:
            issues.append(
                ValidationIssue(
                    path="class",
                    code="MISSING_FIELD",
                    message="Collection schema must include a 'class' name.",
                    hint='Set "class": "MyCollection" in the JSON or pass NAME on the CLI.',
                )
            )
    elif not isinstance(class_name, str) or not class_name.strip():
        issues.append(
            ValidationIssue(
                path="class",
                code="INVALID_TYPE",
                message="Collection 'class' must be a non-empty string.",
            )
        )
    elif not _CLASS_NAME_RE.match(class_name):
        if class_name[0].islower() and _CLASS_NAME_RE.match(
            class_name[0].upper() + class_name[1:]
        ):
            suggested = class_name[0].upper() + class_name[1:]
            hint = (
                "Collection names must start with an uppercase ASCII letter. "
                f"Try '{suggested}'."
            )
        else:
            hint = (
                "Collection names must start with an uppercase ASCII letter and contain "
                "only ASCII letters, digits, and underscores (^[A-Z][_0-9A-Za-z]*$)."
            )
        issues.append(
            ValidationIssue(
                path="class",
                code="INVALID_NAME",
                message=f"Invalid collection name '{class_name}'.",
                hint=hint,
            )
        )

    # Catch unknown top-level keys (typos like multitenancyConfig or vector_config).
    for key in prepared:
        if key in KNOWN_TOP_LEVEL_KEYS or key == "name":
            continue
        close = difflib.get_close_matches(key, sorted(KNOWN_TOP_LEVEL_KEYS), n=1)
        hint = (
            f"Did you mean '{close[0]}'?"
            if close
            else f"Valid top-level keys: {', '.join(sorted(KNOWN_TOP_LEVEL_KEYS))}."
        )
        issues.append(
            ValidationIssue(
                path=key,
                code="UNKNOWN_FIELD",
                message=f"Unknown top-level schema field '{key}'.",
                hint=hint,
            )
        )

    # Description.
    if "description" in prepared and prepared["description"] is not None:
        if not isinstance(prepared["description"], str):
            issues.append(
                ValidationIssue(
                    path="description",
                    code="INVALID_TYPE",
                    message=f"'description' must be a string, got {type(prepared['description']).__name__}.",
                )
            )

    # Properties.
    if "properties" in prepared and prepared["properties"] is not None:
        _validate_properties(
            prepared["properties"],
            path_prefix="properties",
            issues=issues,
        )

    # Vectorizer and vectorConfig.
    _validate_vector_config(prepared, issues)

    # Multi-tenancy vs sharding.
    mt_cfg = prepared.get("multiTenancyConfig")
    mt_enabled = False
    if mt_cfg is not None:
        if not isinstance(mt_cfg, dict):
            issues.append(
                ValidationIssue(
                    path="multiTenancyConfig",
                    code="INVALID_TYPE",
                    message=f"'multiTenancyConfig' must be an object, got {type(mt_cfg).__name__}.",
                )
            )
        else:
            for bool_field in (
                "enabled",
                "autoTenantCreation",
                "autoTenantActivation",
            ):
                if bool_field in mt_cfg and not isinstance(mt_cfg[bool_field], bool):
                    issues.append(
                        ValidationIssue(
                            path=f"multiTenancyConfig.{bool_field}",
                            code="INVALID_TYPE",
                            message=(
                                f"'multiTenancyConfig.{bool_field}' must be a boolean, "
                                f"got {type(mt_cfg[bool_field]).__name__}."
                            ),
                        )
                    )
            mt_enabled = mt_cfg.get("enabled") is True

    sharding_cfg = prepared.get("shardingConfig")
    if sharding_cfg is not None:
        if not isinstance(sharding_cfg, dict):
            issues.append(
                ValidationIssue(
                    path="shardingConfig",
                    code="INVALID_TYPE",
                    message=f"'shardingConfig' must be an object, got {type(sharding_cfg).__name__}.",
                )
            )
        elif mt_enabled and len(sharding_cfg) > 0:
            issues.append(
                ValidationIssue(
                    path="shardingConfig",
                    code="CONFLICTING_FIELDS",
                    message="Cannot set 'shardingConfig' when 'multiTenancyConfig.enabled' is true.",
                    hint="Remove 'shardingConfig' (multi-tenant collections manage shards per tenant).",
                )
            )

    # Replication config.
    repl_cfg = prepared.get("replicationConfig")
    if repl_cfg is not None:
        if not isinstance(repl_cfg, dict):
            issues.append(
                ValidationIssue(
                    path="replicationConfig",
                    code="INVALID_TYPE",
                    message=f"'replicationConfig' must be an object, got {type(repl_cfg).__name__}.",
                )
            )
        else:
            factor = repl_cfg.get("factor")
            if factor is not None and (
                isinstance(factor, bool) or not isinstance(factor, int) or factor < 1
            ):
                issues.append(
                    ValidationIssue(
                        path="replicationConfig.factor",
                        code="INVALID_VALUE",
                        message="'replicationConfig.factor' must be an integer >= 1.",
                    )
                )
            strategy = repl_cfg.get("deletionStrategy")
            if strategy is not None and (
                not isinstance(strategy, str)
                or strategy not in VALID_DELETION_STRATEGIES
            ):
                issues.append(
                    ValidationIssue(
                        path="replicationConfig.deletionStrategy",
                        code="INVALID_VALUE",
                        message=f"Invalid deletionStrategy '{strategy}'.",
                        hint=f"Valid values: {', '.join(sorted(VALID_DELETION_STRATEGIES))}.",
                    )
                )

    # Cluster module availability check (when live metadata is supplied).
    if available_modules is not None:
        enabled_set = set(available_modules)
        available_str = ", ".join(sorted(enabled_set)) if enabled_set else "none"
        for mod_path, mod_name in extract_referenced_modules(prepared):
            if mod_name not in enabled_set:
                issues.append(
                    ValidationIssue(
                        path=mod_path,
                        code="MODULE_NOT_ENABLED",
                        message=f"Module '{mod_name}' is not enabled on this Weaviate cluster.",
                        hint=(
                            f"Available modules on this cluster: {available_str}. "
                            'Use "vectorizer": "none" for bring-your-own vectors.'
                        ),
                    )
                )

    return prepared, issues
