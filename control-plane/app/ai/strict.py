"""Turn a Pydantic model into a JSON schema that Groq accepts in strict mode.

Groq strict mode (docs: console.groq.com/docs/structured-outputs) requires every property to
be listed in `required` (optional = a union with null) and `additionalProperties: false` on
every object, and supports only basic keywords. Length and count limits are therefore removed
from the schema sent to Groq; the Pydantic model still enforces them on the answer.
"""

from typing import Any

from pydantic import BaseModel

# Keywords Groq strict mode does not document; the Pydantic model checks them afterwards.
_DROP = frozenset(
    {
        "default",
        "title",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "uniqueItems",
    }
)


def _clean(node: Any) -> Any:
    if isinstance(node, list):
        return [_clean(n) for n in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _DROP:
            continue
        if key in ("properties", "$defs"):
            out[key] = {name: _clean(sub) for name, sub in value.items()}
        else:
            out[key] = _clean(value)
    if out.get("type") == "object" or "properties" in out:
        out["type"] = "object"
        out["additionalProperties"] = False
        out["required"] = list(out.get("properties", {}))
    return out


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    cleaned: dict[str, Any] = _clean(model.model_json_schema(mode="validation"))
    return cleaned


def response_format(model: type[BaseModel], name: str) -> dict[str, Any]:
    """The `response_format` for Groq chat completions."""
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": strict_schema(model)},
    }
