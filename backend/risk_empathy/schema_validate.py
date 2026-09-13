"""Validate Provider JSON against the official SCHEMA.json (shared by three Providers)."""

from __future__ import annotations

import re
from typing import Any

from .pack import load_pack

_OFFSET = re.compile(r"[+-][0-9]{2}:[0-9]{2}$")
_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2}$")


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported $ref {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _type_ok(value: Any, expected: str | list[str]) -> bool:
    types = [expected] if isinstance(expected, str) else expected
    mapping = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    for name in types:
        cls = mapping[name]
        if name == "integer" and isinstance(value, bool):
            continue
        if name == "number" and isinstance(value, bool):
            continue
        if isinstance(value, cls):
            return True
    return False


def _walk(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str, errors: list[str]) -> None:
    schema = _resolve(schema, root)
    if "type" in schema and not _type_ok(value, schema["type"]):
        errors.append(f"{path}: expected type {schema['type']}, got {type(value).__name__}")
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']}")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {value!r}")
    if schema.get("type") == "string":
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: minLength {schema['minLength']}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: pattern {schema['pattern']}")
        if schema.get("format") == "date-time" and not _DT.match(value):
            errors.append(f"{path}: not an offset date-time")
    if schema.get("type") == "integer" and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: minimum {schema['minimum']}")
    if schema.get("type") == "number":
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: maximum {schema['maximum']}")
    if schema.get("type") == "object":
        required = schema.get("required") or []
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required {key}")
        props = schema.get("properties") or {}
        additional = schema.get("additionalProperties", True)
        for key, child in value.items():
            if key in props:
                _walk(child, props[key], root, f"{path}.{key}", errors)
            elif additional is False:
                errors.append(f"{path}: additional property {key}")
    if schema.get("type") == "array":
        items = schema.get("items")
        if items is not None:
            for i, child in enumerate(value):
                _walk(child, items, root, f"{path}[{i}]", errors)


def validate_provider_json(payload: Any, pack: dict[str, Any] | None = None) -> dict[str, Any]:
    pack = pack or load_pack()
    schema = pack["provider_schema"]
    errors: list[str] = []
    if not isinstance(payload, dict):
        errors.append("$: expected object")
    else:
        _walk(payload, schema, schema, "$", errors)
        if "run_id" in payload:
            errors.append("$: run_id must not be a Provider JSON top-level field")
        if "safety_check_result" in payload:
            errors.append("$: safety_check_result must not be a Provider JSON top-level field")
    return {
        "valid": not errors,
        "errors": errors,
        "schema_id": pack["versions"]["schema_id"],
        "schema_path": pack["schema_path"],
    }
