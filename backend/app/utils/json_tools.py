"""Tolerant JSON extraction + Pydantic → Gemini schema conversion."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")

#: Keys the Gemini `responseSchema` (OpenAPI 3 subset) does not accept.
_UNSUPPORTED_SCHEMA_KEYS = {
    "additionalProperties",
    "$schema",
    "$defs",
    "definitions",
    "discriminator",
    "examples",
    "const",
    "default",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "pattern",
    "anyOf",
    "oneOf",
    "allOf",
    "title",
}


def extract_json(raw: str) -> Any:
    """Parse JSON out of an LLM answer that may contain prose or fences.

    Raises ``ValueError`` when nothing parseable is found.
    """
    if raw is None:
        raise ValueError("empty response")
    text = raw.strip()
    if not text:
        raise ValueError("empty response")

    candidates: list[str] = []
    fenced = _FENCE_RE.findall(text)
    candidates.extend(block.strip() for block in fenced)
    candidates.append(text)

    for start, end in (("{", "}"), ("[", "]")):
        i, j = text.find(start), text.rfind(end)
        if i != -1 and j > i:
            candidates.append(text[i : j + 1])

    for candidate in candidates:
        for attempt in (candidate, _TRAILING_COMMA_RE.sub(r"\1", candidate)):
            try:
                return json.loads(attempt)
            except json.JSONDecodeError:
                continue

    raise ValueError(f"no valid JSON found in response: {text[:200]!r}")


def _resolve_refs(node: Any, defs: dict[str, Any], depth: int = 0) -> Any:
    """Inline ``$ref`` pointers so the schema becomes self contained."""
    if depth > 12 or not isinstance(node, dict | list):
        return node
    if isinstance(node, list):
        return [_resolve_refs(child, defs, depth + 1) for child in node]

    if "$ref" in node:
        ref = str(node["$ref"]).split("/")[-1]
        target = defs.get(ref, {})
        merged = {**_resolve_refs(target, defs, depth + 1)}
        merged.update({k: v for k, v in node.items() if k != "$ref"})
        return merged

    return {key: _resolve_refs(value, defs, depth + 1) for key, value in node.items()}


def _simplify(node: Any) -> Any:
    """Drop keywords Gemini rejects and collapse optional unions."""
    if isinstance(node, list):
        return [_simplify(child) for child in node]
    if not isinstance(node, dict):
        return node

    # `str | None` becomes anyOf[{type:string},{type:null}] -> keep the real
    # type and flag it nullable, which Gemini understands.
    for combinator in ("anyOf", "oneOf", "allOf"):
        if combinator in node:
            branches = [b for b in node[combinator] if b.get("type") != "null"]
            nullable = len(branches) != len(node[combinator])
            chosen = branches[0] if branches else {"type": "string"}
            merged = {k: v for k, v in node.items() if k != combinator}
            merged.update(chosen)
            if nullable:
                merged["nullable"] = True
            node = merged
            break

    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key in _UNSUPPORTED_SCHEMA_KEYS:
            continue
        if key == "properties":
            # Keys here are field names, not schema keywords — a field called
            # "description" must be recursed into, not stringified.
            cleaned[key] = {name: _simplify(sub) for name, sub in value.items()}
        elif key == "items":
            cleaned[key] = _simplify(value)
        elif key == "description":
            cleaned[key] = str(value)[:300]
        elif key in ("enum", "required", "type", "format", "nullable"):
            cleaned[key] = value
        else:
            cleaned[key] = _simplify(value)

    if cleaned.get("type") == "object":
        if "properties" not in cleaned:
            # Gemini requires at least one property; use a free-form string.
            cleaned["properties"] = {"value": {"type": "string"}}
        # Pydantic marks only fields without defaults as required, and our
        # schemas default everything — which lets the model return an almost
        # empty object. Demand every field instead.
        cleaned["required"] = list(cleaned["properties"].keys())
    if cleaned.get("type") == "array" and "items" not in cleaned:
        cleaned["items"] = {"type": "string"}
    if cleaned.get("format") in {"uuid", "date-time", "date", "email", "uri"}:
        cleaned.pop("format", None)
    return cleaned


def to_gemini_schema(model: type) -> dict[str, Any]:
    """Convert a Pydantic model class into a Gemini ``responseSchema``."""
    schema = model.model_json_schema()  # type: ignore[attr-defined]
    defs = schema.pop("$defs", {}) or schema.pop("definitions", {}) or {}
    resolved = _resolve_refs(schema, defs)
    return _simplify(resolved)


def compact_json(value: Any, limit: int | None = None) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if limit and len(text) > limit:
        return text[:limit] + "…"
    return text


#: Keys that OpenAI's strict `json_schema` mode rejects outright.
_OPENAI_STRIPPED_KEYS = {
    "$schema",
    "$defs",
    "definitions",
    "default",
    "examples",
    "discriminator",
    "format",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "pattern",
    "minItems",
    "maxItems",
    "title",
}


def _openai_node(node: Any, depth: int = 0) -> Any:
    """Normalise one schema node for OpenAI strict structured outputs."""
    if isinstance(node, list):
        return [_openai_node(child, depth + 1) for child in node]
    if not isinstance(node, dict):
        return node

    # `str | None` arrives as anyOf[{type:string},{type:null}] — flatten it to a
    # nullable concrete type, which strict mode accepts.
    for combinator in ("anyOf", "oneOf"):
        branches = node.get(combinator)
        if not isinstance(branches, list):
            continue
        concrete = [b for b in branches if isinstance(b, dict) and b.get("type") != "null"]
        nullable = len(concrete) != len(branches)
        chosen = dict(concrete[0]) if concrete else {"type": "string"}
        merged = {k: v for k, v in node.items() if k != combinator}
        merged.update(chosen)
        if nullable and isinstance(merged.get("type"), str):
            merged["type"] = [merged["type"], "null"]
        node = merged
        break

    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key in _OPENAI_STRIPPED_KEYS:
            continue
        if key == "description":
            cleaned[key] = str(value)[:300]
        elif key == "properties":
            cleaned[key] = {name: _openai_node(sub, depth + 1) for name, sub in value.items()}
        else:
            cleaned[key] = _openai_node(value, depth + 1)

    node_type = cleaned.get("type")
    is_object = node_type == "object" or (isinstance(node_type, list) and "object" in node_type)

    if is_object:
        properties = cleaned.setdefault("properties", {})
        if not properties:
            properties["value"] = {"type": "string"}
        # Strict mode demands additionalProperties:false and every key required.
        cleaned["additionalProperties"] = False
        cleaned["required"] = list(properties.keys())
    elif node_type == "array" and "items" not in cleaned:
        cleaned["items"] = {"type": "string"}

    return cleaned


def to_openai_schema(model: type) -> dict[str, Any]:
    """Convert a Pydantic model into an OpenAI strict `json_schema`."""
    schema = model.model_json_schema()  # type: ignore[attr-defined]
    defs = schema.pop("$defs", {}) or schema.pop("definitions", {}) or {}
    resolved = _resolve_refs(schema, defs)
    normalised = _openai_node(resolved)
    normalised.pop("title", None)
    return normalised
