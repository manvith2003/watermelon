import inspect
import json
import time
from typing import Callable, Optional

from tools.base import GitHubClient, ToolResult
import tools.github_tools as github_tools
from memory.capability_memory import register_capability, get_synthesized_capabilities, get_capability

_TOOL_REGISTRY: dict[str, Callable] = {}


def _build_params_schema(fn: Callable) -> dict:
    sig = inspect.signature(fn)
    schema = {}
    for name, param in sig.parameters.items():
        if name == "client":
            continue
        ann = param.annotation
        type_name = ann.__name__ if hasattr(ann, "__name__") else str(ann)
        schema[name] = {
            "type": type_name,
            "required": param.default is inspect.Parameter.empty,
            "default": None if param.default is inspect.Parameter.empty else param.default,
        }
    return schema


def _synthesis_namespace() -> dict:
    import datetime, json, re
    return {"ToolResult": ToolResult, "datetime": datetime, "json": json, "re": re}


def _register_base_tools():
    for fn_name in dir(github_tools):
        fn = getattr(github_tools, fn_name)
        if not callable(fn) or fn_name.startswith("_"):
            continue
        if "client" not in inspect.signature(fn).parameters:
            continue
        doc = inspect.getdoc(fn) or fn_name.replace("_", " ")
        _TOOL_REGISTRY[fn_name] = fn
        register_capability(
            name=fn_name,
            description=doc.split("\n")[0],
            implementation=f"# base tool: tools.github_tools.{fn_name}",
            params_schema=_build_params_schema(fn),
            is_synthesized=False,
        )


def _load_synthesized_tools():
    for cap in get_synthesized_capabilities():
        try:
            ns = _synthesis_namespace()
            exec(cap["implementation"], ns)
            fn = ns.get(cap["name"])
            if fn and callable(fn):
                _TOOL_REGISTRY[cap["name"]] = fn
        except Exception:
            pass


def initialize_registry():
    _register_base_tools()
    _load_synthesized_tools()


def get_tool(name: str) -> Optional[Callable]:
    return _TOOL_REGISTRY.get(name)


def get_all_tool_names() -> list[str]:
    return list(_TOOL_REGISTRY.keys())


def register_synthesized_tool(name, description, implementation, params_schema=None) -> bool:
    try:
        ns = _synthesis_namespace()
        exec(implementation, ns)
        fn = ns.get(name)
        if not fn or not callable(fn):
            return False
        _TOOL_REGISTRY[name] = fn
        register_capability(
            name=name,
            description=description,
            implementation=implementation,
            params_schema=params_schema or {},
            is_synthesized=True,
        )
        return True
    except Exception:
        return False


def call_tool(client: GitHubClient, tool_name: str, params: dict) -> ToolResult:
    fn = get_tool(tool_name)
    if fn is None:
        raise KeyError(f"Tool '{tool_name}' not found in registry")
    result: ToolResult = fn(client, **params)
    result.api_calls = client.api_calls
    return result


def get_tool_descriptions() -> str:
    from memory.capability_memory import get_all_capabilities
    caps = {c["name"]: c for c in get_all_capabilities()}
    lines = []
    for name in sorted(_TOOL_REGISTRY.keys()):
        cap    = caps.get(name)
        desc   = cap["description"] if cap else name
        synth  = " [SYNTHESIZED]" if (cap and cap["is_synthesized"]) else ""
        schema = cap["params_schema"] if cap else {}
        params = ", ".join(
            f"{k}{'?' if not v.get('required') else ''}"
            for k, v in schema.items() if k != "client"
        )
        lines.append(f"- {name}({params}){synth}: {desc}")
    return "\n".join(lines)
