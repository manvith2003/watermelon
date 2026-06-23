"""
Capability Synthesizer — runtime capability generation.

When the executor encounters a task requiring a tool that doesn't exist,
the synthesizer:
  1. Reasons about what the tool needs to do (via LLM)
  2. Generates a Python function implementation
  3. Compiles and tests it with a dry-run validation
  4. If it works, registers it in capability memory for future reuse
  5. If it fails after N attempts, reports clearly what was tried

This is the REAL version: the synthesis happens at runtime, the generated
function makes actual GitHub API calls, and successful synthesis persists
across sessions via capability_memory.
"""
import json
import os
import traceback
from typing import Any, Optional

from litellm import completion

from tools.base import GitHubClient, ToolResult
from tools.registry import register_synthesized_tool

LLM_MODEL = os.environ.get("LLM_MODEL", "groq/llama-3.3-70b-versatile")
MAX_SYNTHESIS_ATTEMPTS = 3

SYNTHESIS_SYSTEM = """\
You are an expert at writing Python functions that call the GitHub REST API.

You must generate a Python function that:
1. Is named exactly: {tool_name}
2. Signature: def {tool_name}(client, **kwargs)  — ALWAYS use **kwargs, never positional args after client
3. Extract params from kwargs like: repo = kwargs.get('repo', '')
4. repo is ALWAYS in "owner/repo" format — split it like: owner, name = repo.split('/', 1)
5. MUST return ToolResult(success=True, data=...) or ToolResult(success=False, data=None, error="...")
6. NEVER return a plain dict — always ToolResult
7. Use client.get(path), client.post(path, json=...) for API calls
8. No imports needed — these are pre-imported: ToolResult, client, datetime, json, re

EXAMPLE of a correct function:
def example_tool(client, **kwargs):
    repo = kwargs.get('repo', '')
    owner, name = repo.split('/', 1)
    data = client.get(f'/repos/{{owner}}/{{name}}/issues', params={{'state': 'open', 'per_page': 100}})
    result = [{{'number': i['number'], 'title': i['title']}} for i in data if 'pull_request' not in i]
    return ToolResult(success=True, data=result)

KNOWN CONSTRAINTS TO RESPECT:
{constraints}

Return ONLY a JSON object with these exact keys:
{{
  "function_code": "def {tool_name}(client, **kwargs):\\n    ...",
  "params_schema": {{"repo": {{"type": "str", "required": true, "default": null}}}},
  "description": "one-line description of what this tool does",
  "reasoning": "why you implemented it this way"
}}
"""

SYNTHESIS_FIX_PROMPT = """\
This Python function failed when executed. Fix it.

FUNCTION:
{code}

ERROR:
{error}

TRACEBACK:
{traceback}

Return JSON with the same format as before:
{{
  "function_code": "...",
  "params_schema": {{}},
  "description": "...",
  "reasoning": "what was wrong and how you fixed it"
}}
"""


def synthesize_capability(
    tool_name: str,
    description: str,
    client: GitHubClient,
    test_params: Optional[dict] = None,
) -> dict:
    """
    Attempt to synthesize a new capability at runtime.

    Returns:
    {
      "success": bool,
      "tool_name": str,
      "attempts": int,
      "error": str | None,
      "attempts_detail": [{"attempt": n, "code": ..., "error": ...}]
    }
    """
    from memory.capability_memory import get_all_constraints

    constraints = get_all_constraints()
    constraints_str = "\n".join(
        f"- [{c['tool_name']}] {c['constraint_type']}: {c['description']}"
        for c in constraints
    ) or "None discovered yet."

    attempts_detail = []
    last_code = None
    last_error = None
    last_tb = None

    for attempt in range(1, MAX_SYNTHESIS_ATTEMPTS + 1):
        # Generate or fix
        if attempt == 1:
            system = SYNTHESIS_SYSTEM.format(
                tool_name=tool_name,
                constraints=constraints_str,
            )
            user_msg = (
                f"Generate a function named '{tool_name}' that: {description}\n"
                f"Return only the JSON object."
            )
        else:
            # Ask LLM to fix the previous attempt
            system = "You are fixing a broken Python GitHub API function. Follow instructions carefully."
            user_msg = SYNTHESIS_FIX_PROMPT.format(
                code=last_code,
                error=str(last_error),
                traceback=last_tb or "",
            )

        try:
            response = completion(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            synth = json.loads(raw)
        except Exception as e:
            attempts_detail.append({"attempt": attempt, "error": f"LLM call failed: {e}"})
            last_error = e
            continue

        code = synth.get("function_code", "")
        params_schema = synth.get("params_schema", {})
        desc = synth.get("description", description)
        last_code = code

        # Compile check
        try:
            import datetime as _dt
            import json as _json
            import re as _re
            namespace: dict[str, Any] = {
                "ToolResult": ToolResult,
                "client": client,
                "datetime": _dt,
                "json": _json,
                "re": _re,
            }
            exec(code, namespace)
            fn = namespace.get(tool_name)
            if not callable(fn):
                raise ValueError(f"Function '{tool_name}' not defined in generated code")
        except Exception as e:
            tb = traceback.format_exc()
            attempts_detail.append({
                "attempt": attempt,
                "code": code,
                "error": f"Compile error: {e}",
                "traceback": tb,
            })
            last_error = e
            last_tb = tb
            continue

        # Dry-run validation: call with test_params or infer minimal params
        try:
            inferred_params = _infer_test_params(params_schema, client) if not test_params else test_params
            result = fn(client, **inferred_params)
            if not isinstance(result, ToolResult):
                raise ValueError(f"Function must return ToolResult, got {type(result)}")
            if not result.success:
                raise ValueError(f"Test run returned success=False: {result.error}")
        except Exception as e:
            tb = traceback.format_exc()
            attempts_detail.append({
                "attempt": attempt,
                "code": code,
                "error": f"Execution error: {e}",
                "traceback": tb,
            })
            last_error = e
            last_tb = tb
            continue

        # Success — register in memory
        registered = register_synthesized_tool(
            name=tool_name,
            description=desc,
            implementation=code,
            params_schema=params_schema,
        )
        attempts_detail.append({
            "attempt": attempt,
            "code": code,
            "error": None,
            "registered": registered,
        })

        return {
            "success": True,
            "tool_name": tool_name,
            "attempts": attempt,
            "description": desc,
            "error": None,
            "attempts_detail": attempts_detail,
        }

    # All attempts failed
    return {
        "success": False,
        "tool_name": tool_name,
        "attempts": MAX_SYNTHESIS_ATTEMPTS,
        "error": f"Synthesis failed after {MAX_SYNTHESIS_ATTEMPTS} attempts: {last_error}",
        "attempts_detail": attempts_detail,
    }


def _infer_test_params(params_schema: dict, client: GitHubClient) -> dict:
    """
    Infer minimal test params from schema.
    Uses the authenticated user's login to construct a safe test repo name.
    """
    params = {}
    for param_name, schema in params_schema.items():
        if not schema.get("required", False):
            continue
        type_hint = schema.get("type", "str")
        if param_name == "repo":
            # Get authenticated user to build a safe repo ref
            try:
                user_data = client.get("/user")
                params["repo"] = f"{user_data['login']}/{user_data['login']}"
            except Exception:
                params["repo"] = "octocat/Hello-World"
        elif type_hint in ("int", "integer"):
            params[param_name] = 1
        elif type_hint in ("bool", "boolean"):
            params[param_name] = False
        elif type_hint in ("list", "List"):
            params[param_name] = []
        else:
            params[param_name] = "test"
    return params
