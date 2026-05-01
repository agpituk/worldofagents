"""Build OpenAI-format tool specs from plain Python functions.

Mirrors the octonous `_build_tool_definition` pattern but emits the
OpenAI/llama.cpp tool-calling shape (the format the gateway forwards to
llamafile):

    [{
      "type": "function",
      "function": {
        "name": "<fn name>",
        "description": "<docstring>",
        "parameters": {"type": "object", "properties": {...}, "required": [...]}
      }
    }, ...]

The function's docstring is the model's *only* description of when/how to use
the tool — write it well.
"""

from __future__ import annotations

import inspect
import textwrap
from collections.abc import Callable
from typing import Any, get_args, get_origin, get_type_hints


def _py_to_jsonschema(annotation: Any) -> dict[str, Any]:
    """Translate a Python type annotation to a JSON-schema fragment.

    Covers the cases our action verbs use: str, int, float, bool, list[T].
    Anything more exotic falls back to "string".
    """
    if annotation is inspect.Parameter.empty:
        return {"type": "string"}

    origin = get_origin(annotation)
    if origin is list:
        (inner,) = get_args(annotation) or (Any,)
        return {"type": "array", "items": _py_to_jsonschema(inner)}

    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}

    # Fallback — covers Union[str, None] etc. without elaborating
    return {"type": "string"}


def function_to_tool_spec(fn: Callable[..., Any]) -> dict[str, Any]:
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except Exception:
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name == "self":
            continue
        annotation = hints.get(name, param.annotation)
        prop = _py_to_jsonschema(annotation)
        # Pull the per-arg description from the docstring "Args:" block if present
        prop["description"] = _extract_arg_description(fn.__doc__ or "", name) or f"Argument {name}"
        properties[name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(name)

    description = textwrap.dedent(fn.__doc__ or f"Tool {fn.__name__}").strip()

    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _extract_arg_description(docstring: str, arg_name: str) -> str | None:
    """Find a description line for `arg_name` inside an Args: block.

    Heuristic; not a full docstring parser. Returns None if not found.
    Accepts lines like:
        target: The slug of the ...
        target (str): The slug of ...
    """
    if not docstring or "Args:" not in docstring:
        return None
    after_args = docstring.split("Args:", 1)[1]
    # Stop at the next section
    for terminator in ("\n\n", "Returns:", "Raises:", "Yields:", "Examples:", "Note:"):
        if terminator in after_args:
            after_args = after_args.split(terminator, 1)[0]
    lines = [line.strip() for line in after_args.splitlines() if line.strip()]
    for line in lines:
        # match "name: ..." or "name (type): ..."
        head, _, rest = line.partition(":")
        head = head.split("(", 1)[0].strip()
        if head == arg_name and rest:
            return rest.strip()
    return None


def build_tool_specs(fns: list[Callable[..., Any]]) -> list[dict[str, Any]]:
    return [function_to_tool_spec(fn) for fn in fns]


def build_tool_index(fns: list[Callable[..., Any]]) -> dict[str, Callable[..., Any]]:
    return {fn.__name__: fn for fn in fns}
