"""Pydantic's JSON Schema -> a schema a strict structured-output mode will accept. By hand.

`packages/llm-kit/src/llm_kit/schema.py` already does this (`to_provider_schema` and
`require_all_properties`), and its docstring opens with the 400 that forced it into
existence. This file is the same idea rebuilt from nothing, one rule at a time, so that each
rule can be switched OFF on its own and section S of main.py can find out which one a given
provider actually needed (CLAUDE.md rule 6: build the thing by hand once before using the
abstraction). It is not imported from llm-kit on purpose.

Why the raw schema is a problem at all. `Invoice.model_json_schema()` is correct JSON Schema
- for *validating* a document. Strict structured outputs use the schema for something else:
the provider compiles it into a grammar and masks every token the grammar does not allow at
that position (constrained decoding). A grammar needs a CLOSED, FINITE shape:

    - "any other key may appear" (no additionalProperties: false) is not finite;
    - "this key may or may not be present" (not in `required`) doubles the paths at every
      optional key, so OpenAI-style strict mode bans it and asks for a nullable TYPE instead:
      the key is always present, its value may be null;
    - `$ref` is a pointer the compiler has to chase, and some providers' schema subsets
      (Gemini's, historically) do not chase pointers at all;
    - `title`, `default`, `format` are validation/documentation keywords. A generator has no
      use for a title, cannot "use" a default (it must emit every key), and support for
      `format` varies by provider. All of them cost input tokens on every call.

The five rules, in the order they are applied. Order matters in two places, noted inline.

    inline_refs     replace every {"$ref": "#/$defs/X"} with the definition; drop $defs
    nullable_types  anyOf [{type: X, ...}, {type: null}]  ->  {type: [X, "null"], ...}
    strip_keywords  drop title / default / format (format's meaning is in the description)
    close_objects   additionalProperties: false on every object
    require_all     every property listed in `required`

A trap llm-kit's version has and this one avoids: a naive "delete every key named title"
walk also deletes a FIELD named `title`, because inside `properties` the keys are field
names, not keywords. `_walk` below knows which dicts are property maps.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

Schema = dict[str, Any]

STRIPPED_KEYWORDS = ("title", "default", "format")


def _walk(node: Any, fn: Callable[[Schema], Schema]) -> Any:
    """Apply `fn` to every SCHEMA dict, bottom-up. The keys of a `properties` or `$defs`
    mapping are names chosen by the developer, not keywords, so those mappings are walked
    into but never passed to `fn` themselves."""
    if isinstance(node, list):
        return [_walk(item, fn) for item in node]
    if not isinstance(node, dict):
        return node
    out: Schema = {}
    for key, value in node.items():
        if key in ("properties", "$defs") and isinstance(value, dict):
            out[key] = {name: _walk(sub, fn) for name, sub in value.items()}
        else:
            out[key] = _walk(value, fn)
    return fn(out)


def inline_refs(schema: Schema) -> Schema:
    defs: Schema = schema.get("$defs", {})

    def resolve(node: Any, depth: int = 0) -> Any:
        if depth > 20:  # a self-referencing model would recurse forever
            raise ValueError("schema nests deeper than 20 levels; refusing to inline")
        if isinstance(node, list):
            return [resolve(item, depth + 1) for item in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            target = resolve(defs[ref.removeprefix("#/$defs/")], depth + 1)
            siblings = {k: resolve(v, depth + 1) for k, v in node.items() if k != "$ref"}
            return {**target, **siblings}  # a sibling `description` overrides the def's
        return {k: resolve(v, depth + 1) for k, v in node.items() if k != "$defs"}

    return resolve(schema)


def nullable_types(schema: Schema) -> Schema:
    """Runs BEFORE strip_keywords would matter: it reads `type` inside the anyOf branches."""

    def fn(node: Schema) -> Schema:
        options = node.get("anyOf")
        if not (isinstance(options, list) and len(options) == 2 and {"type": "null"} in options):
            return node
        other = next(o for o in options if o != {"type": "null"})
        if not isinstance(other.get("type"), str):
            return node  # a nullable object/union: leave the anyOf alone
        rest = {k: v for k, v in node.items() if k != "anyOf"}
        return {**other, **rest, "type": [other["type"], "null"]}

    return _walk(schema, fn)


def strip_keywords(schema: Schema) -> Schema:
    return _walk(schema, lambda n: {k: v for k, v in n.items() if k not in STRIPPED_KEYWORDS})


def close_objects(schema: Schema) -> Schema:
    def fn(node: Schema) -> Schema:
        if node.get("type") == "object" or "properties" in node:
            return {**node, "additionalProperties": False}
        return node

    return _walk(schema, fn)


def require_all(schema: Schema) -> Schema:
    """Runs AFTER strip_keywords removed `default`: a field that is required AND has a
    default is a contradiction some validators reject. The meaning change is real: a field
    that Pydantic lets you omit must now be sent explicitly as null. That is fine here only
    because every optional field in models.py is `X | None`, so null is a legal value."""

    def fn(node: Schema) -> Schema:
        props = node.get("properties")
        if isinstance(props, dict) and props:
            return {**node, "required": list(props)}
        return node

    return _walk(schema, fn)


RULES: dict[str, Callable[[Schema], Schema]] = {
    "inline_refs": inline_refs,
    "nullable_types": nullable_types,
    "strip_keywords": strip_keywords,
    "close_objects": close_objects,
    "require_all": require_all,
}


def to_strict_schema(raw: Schema, skip: str | None = None) -> Schema:
    """Apply every rule except `skip` (section S's leave-one-out). Never mutates `raw`."""
    schema = copy.deepcopy(raw)
    for name, rule in RULES.items():
        if name != skip:
            schema = rule(schema)
    return schema


# ---------------------------------------------------------------- diffing


def diff(before: Any, after: Any, path: str = "") -> list[str]:
    """Every leaf-level difference between two schemas, as readable one-liners."""
    if isinstance(before, dict) and isinstance(after, dict):
        lines: list[str] = []
        for key in before.keys() | after.keys():
            sub = f"{path}/{key}"
            if key not in after:
                lines.append(f"- {sub}")
            elif key not in before:
                lines.append(f"+ {sub} = {_short(after[key])}")
            else:
                lines.extend(diff(before[key], after[key], sub))
        return sorted(lines, key=lambda s: s[2:])
    if before != after:
        return [f"~ {path or '/'}: {_short(before)} -> {_short(after)}"]
    return []


def _short(value: Any, limit: int = 60) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def changes_per_rule(raw: Schema) -> list[tuple[str, list[str]]]:
    """Apply the rules one at a time and diff each step, so every change is attributed
    to the rule that made it. A single raw-vs-final diff would mix them together."""
    steps: list[tuple[str, list[str]]] = []
    current = copy.deepcopy(raw)
    for name, rule in RULES.items():
        nxt = rule(current)
        steps.append((name, diff(current, nxt)))
        current = nxt
    return steps
