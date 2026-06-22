"""
Tool Registry — single source of truth for all available capabilities.

At startup, base GitHub tools are registered here and written to capability_memory.
Synthesized tools (generated at runtime) are dynamically added.
"""
import inspect
import json
import time
from typing import Callable, Optional

from tools.base import GitHubClient, ToolResult
import tools.github_tools as github_tools
from memory.capability_memory import register_capability, get_synthesized_capabilities, get_capability


# Maps tool name → callable
_TOOL_REGISTRY: dict[str, Callable] = {}


def _build_params_schema(fn: Callable) -> dict:
    """Derive a simple params schema from function signature (excluding 'client')."""
    sig = inspect.signature(fn)
    schema = {}
    for param_name, param in sig.parameters.items():
        if param_name == "client":
            continue
        annotation = param.annotation
        type_name = annotation.__name__ if hasattr(annotation, "__name__") else str(annotation)
        schema[param_name] = {
            "type": type_name,
            "required": param.default is inspect.Parameter.empty,
            "default": None if param.default is inspect.Parameter.empty else param.default,
        }
    return schema


def _register_base_tools():
    """Register all functions from github_tools module as base capabilities."""
    for fn_name in dir(github_tools):
        fn = getattr(github_tools, fn_name)
        if not callable(fn) or fn_name.startswith("_"):
            continue
        if "client" not in inspect.signature(fn).parameters:
            continue
        doc = inspect.getdoc(fn) or fn_name.replace("_", " ")
        params_schema = _build_params_schema(fn)
        _TOOL_REGISTRY[fn_name] = fn
        register_capability(
            name=fn_name,
            description=doc.split("\n")[0],  # first line of docstring
            implementation=f"# base tool: tools.github_tools.{fn_name}",
            params_schema=params_schema,
            is_synthesized=False,
        )


def _load_synthesized_tools():
    """Load previously synthesized tools from DB and compile them into the registry."""
    for cap in get_synthesized_capabilities():
        try:
            namespace: dict = {}
            exec(cap["implementation"], namespace)
            fn = namespace.get(cap["name"])
            if fn and callable(fn):
                _TOOL_REGISTRY[cap["name"]] = fn
        except Exception as e:
            pass  # Synthesized tool failed to load; will re-synthesize if needed


def initialize_registry():
    """Call once at startup to populate the tool registry."""
    _register_base_tools()
    _load_synthesized_tools()


def get_tool(name: str) -> Optional[Callable]:
    return _TOOL_REGISTRY.get(name)


def get_all_tool_names() -> list[str]:
    return list(_TOOL_REGISTRY.keys())


def register_synthesized_tool(name: str, description: str, implementation: str,
                               params_schema: Optional[dict] = None) -> bool:
    """
    Compile and register a newly synthesized tool.
    Returns True if successful, False if compilation fails.
    """
    try:
        namespace: dict = {}
        exec(implementation, namespace)
        fn = namespace.get(name)
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
    """
    Invoke a registered tool by name with the given params.
    Raises KeyError if the tool is not found.
    """
    fn = get_tool(tool_name)
    if fn is None:
        raise KeyError(f"Tool '{tool_name}' not in registry")
    start = time.time()
    result: ToolResult = fn(client, **params)
    result.api_calls = client.api_calls  # may be overridden by individual tools
    return result


def get_tool_descriptions() -> str:
    """Return a formatted list of all tools for the LLM system prompt."""
    lines = []
    from memory.capability_memory import get_all_capabilities
    caps = {c["name"]: c for c in get_all_capabilities()}
    for name in sorted(_TOOL_REGISTRY.keys()):
        cap = caps.get(name)
        desc = cap["description"] if cap else name
        synth = " [SYNTHESIZED]" if (cap and cap["is_synthesized"]) else ""
        schema = cap["params_schema"] if cap else {}
        params_str = ", ".join(
            f"{k}{'?' if not v.get('required') else ''}"
            for k, v in schema.items()
            if k != "client"
        )
        lines.append(f"- {name}({params_str}){synth}: {desc}")
    return "\n".join(lines)
