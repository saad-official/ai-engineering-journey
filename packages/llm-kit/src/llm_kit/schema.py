"""Turning a Pydantic model into a JSON Schema that providers actually accept.

This module exists because of a real 400, on the first live run of `smoke.py`:

    invalid JSON schema for response_format: 'Repo':
    `additionalProperties:false` must be set on every object

Pydantic's `model_json_schema()` is correct JSON Schema. It is not, however, what strict
structured-output modes want. Providers that implement OpenAI's `strict: true` constrain
generation with a grammar compiled from the schema, and a grammar cannot be compiled from
a schema that leaves the set of legal keys open - so they reject anything that does not
close every object explicitly. Pydantic never emits `additionalProperties: false`, because
by its own semantics extra keys are ignored rather than forbidden.

That is the whole shape of the portability problem TECHNOLOGY_STACK.md flagged: "a Pydantic
model that works on one provider can fail on another". The fix belongs in one place, so
every provider is handed the same normalised schema and there is one fewer difference to
debug at 1 a.m.

Normalisations applied, each for a named reason:

  1. `$ref` / `$defs` inlined     - Gemini's schema subset rejects references.
  2. `additionalProperties: false` on every object - required by OpenAI/Groq strict mode.
  3. `title` stripped             - Pydantic emits one per field; pure input-token tax.
  4. `default` stripped           - meaningless to a generator, and some providers reject
                                    it alongside `strict`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve `$ref`/`$defs` into an inline schema."""
    defs = schema.pop("$defs", {})
    if not defs:
        return schema

    def walk(node: Any, depth: int = 0) -> Any:
        # A self-referencing model would recurse forever. Depth-capped rather than
        # cycle-tracked because a schema nested 12 deep is a design problem before it is
        # a serialisation problem - and no provider handles it well either.
        if depth > 12:
            return {}
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = defs.get(ref.split("/")[-1], {})
                inlined = walk(dict(target), depth + 1)
                return {**inlined, **{k: v for k, v in node.items() if k != "$ref"}}
            return {key: walk(value, depth + 1) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(item, depth + 1) for item in node]
        return node

    return walk(schema)


def _close_objects(node: Any) -> Any:
    """Recursively set `additionalProperties: false` and drop title/default noise."""
    if isinstance(node, dict):
        cleaned = {
            key: _close_objects(value)
            for key, value in node.items()
            if key not in ("title", "default")
        }
        if cleaned.get("type") == "object" or "properties" in cleaned:
            cleaned["additionalProperties"] = False
        return cleaned
    if isinstance(node, list):
        return [_close_objects(item) for item in node]
    return node


def to_provider_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A Pydantic model as a JSON Schema every provider in PROVIDERS accepts."""
    return _close_objects(_inline_refs(model.model_json_schema()))


def require_all_properties(schema: dict[str, Any]) -> dict[str, Any]:
    """Mark every property required, recursively.

    OpenAI's strict mode demands this: a grammar has no way to express "this key may be
    absent", so optionality is expressed as a nullable *type* instead. Applied only where
    a provider insists, because it changes meaning - a Pydantic field with a default is no
    longer allowed to be omitted, and the model must emit `null` for it explicitly.
    """
    if isinstance(schema, dict):
        result = {key: require_all_properties(value) for key, value in schema.items()}
        properties = result.get("properties")
        if isinstance(properties, dict) and properties:
            result["required"] = list(properties)
        return result
    if isinstance(schema, list):
        return [require_all_properties(item) for item in schema]
    return schema
