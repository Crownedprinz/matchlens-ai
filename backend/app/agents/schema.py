"""Normalize Pydantic schemas to Microsoft's strict function-tool subset."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

# Constraints remain enforced by the Pydantic input models at runtime. These
# keywords are intentionally omitted from the provider-facing strict schema.
UNSUPPORTED_FOUNDRY_KEYWORDS = frozenset({
    "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
    "exclusiveMaximum", "multipleOf", "pattern", "format", "default",
    "title", "$schema",
})


def normalize_foundry_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return a strict, provider-safe copy without weakening runtime checks.

    Every object is closed, every declared property is required, and nullable
    optional values remain represented by ``anyOf: [value, null]``. References
    and definitions are retained and normalized recursively.
    """
    return _normalize(dict(deepcopy(schema)))


def _normalize(node: dict[str, Any]) -> dict[str, Any]:
    declared_required = set(node.get("required") or [])
    for key in tuple(node):
        if key in UNSUPPORTED_FOUNDRY_KEYWORDS:
            node.pop(key, None)

    for key in ("properties", "$defs", "definitions"):
        value = node.get(key)
        if isinstance(value, dict):
            node[key] = {name: _normalize(dict(child)) for name, child in value.items() if isinstance(child, dict)}

    for key in ("items", "contains", "not", "if", "then", "else"):
        value = node.get(key)
        if isinstance(value, dict):
            node[key] = _normalize(value)

    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        value = node.get(key)
        if isinstance(value, list):
            node[key] = [_normalize(dict(child)) if isinstance(child, dict) else child for child in value]

    if node.get("type") == "object" or "properties" in node:
        node["type"] = "object"
        properties = node.get("properties") or {}
        for name, property_schema in properties.items():
            if name not in declared_required and isinstance(property_schema, dict):
                properties[name] = _nullable(property_schema)
        node["properties"] = properties
        node["required"] = list(properties)
        node["additionalProperties"] = False

    return node


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    branches = schema.get("anyOf")
    if isinstance(branches, list) and any(isinstance(branch, dict) and branch.get("type") == "null" for branch in branches):
        return schema
    return {"anyOf": [schema, {"type": "null"}]}
