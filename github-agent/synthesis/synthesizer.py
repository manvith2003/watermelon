import json
import os
import traceback
from typing import Any, Optional

from litellm import completion
from tools.base import GitHubClient, ToolResult
from tools.registry import register_synthesized_tool

LLM_MODEL = os.environ.get("LLM_MODEL", "groq/llama-3.3-70b-versatile")
MAX_ATTEMPTS = 3

SYNTHESIS_PROMPT = """You are an expert at writing Python functions that call the GitHub REST API.

Write a function with these rules:
1. Name it exactly: {tool_name}
2. Signature: def {tool_name}(client, **kwargs)  — always use **kwargs
3. Get params with: repo = kwargs.get('repo', '')
4. repo is always "owner/repo" format — split: owner, name = repo.split('/', 1)
5. Must return ToolResult(success=True, data=...) or ToolResult(success=False, data=None, error="...")
6. Never return a plain dict — always ToolResult
7. Use client.get(path) or client.post(path, json=...) for API calls
8. No imports needed — datetime, json, re, ToolResult are already available

Example:
def example_tool(client, **kwargs):
    repo = kwargs.get('repo', '')
    owner, name = repo.split('/', 1)
    data = client.get(f'/repos/{{owner}}/{{name}}/issues', params={{'state': 'open', 'per_page': 100}})
    result = [{{'number': i['number'], 'title': i['title']}} for i in data if 'pull_request' not in i]
    return ToolResult(success=True, data=result)

Known constraints:
{constraints}

Return JSON with these exact keys:
{{{{
  "function_code": "def {tool_name}(client, **kwargs):\n    ...",
  "params_schema": {{{{"repo": {{{{"type": "str", "required": true, "default": null}}}}}}}},
  "description": "one-line description",
  "reasoning": "why you implemented it this way"
}}}}
"""

FIX_PROMPT = """This function failed. Fix it.

FUNCTION:
{code}

ERROR:
{error}

TRACEBACK:
{traceback}

Return JSON with the same format:
{{{{
  "function_code": "...",
  "params_schema": {{{{}}}},
  "description": "...",
  "reasoning": "what was wrong and how you fixed it"
}}}}
"""


def synthesize_capability(tool_name: str, description: str, client: GitHubClient,
                           test_params: Optional[dict] = None) -> dict:
    from memory.capability_memory import get_all_constraints
    constraints_str = "\n".join(
        f"- [{c['tool_name']}] {c['constraint_type']}: {c['description']}"
        for c in get_all_constraints()
    ) or "None yet."

    attempts_detail = []
    last_code = last_error = last_tb = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt == 1:
            system = SYNTHESIS_PROMPT.format(tool_name=tool_name, constraints=constraints_str)
            user   = f"Write a function named '{tool_name}' that: {description}\nReturn only JSON."
        else:
            system = "Fix the broken GitHub API Python function below."
            user   = FIX_PROMPT.format(code=last_code, error=str(last_error), traceback=last_tb or "")

        try:
            resp = completion(
                model=LLM_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            synth = json.loads(resp.choices[0].message.content)
        except Exception as e:
            attempts_detail.append({"attempt": attempt, "error": f"LLM call failed: {e}"})
            last_error = e
            continue

        code        = synth.get("function_code", "")
        params_schema = synth.get("params_schema", {})
        desc        = synth.get("description", description)
        last_code   = code

        try:
            import datetime as _dt, json as _json, re as _re
            ns: dict[str, Any] = {
                "ToolResult": ToolResult, "client": client,
                "datetime": _dt, "json": _json, "re": _re,
            }
            exec(code, ns)
            fn = ns.get(tool_name)
            if not callable(fn):
                raise ValueError(f"Function '{tool_name}' not defined in generated code")
        except Exception as e:
            tb = traceback.format_exc()
            attempts_detail.append({"attempt": attempt, "code": code, "error": f"Compile: {e}", "traceback": tb})
            last_error, last_tb = e, tb
            continue

        try:
            params = _infer_test_params(params_schema, client) if not test_params else test_params
            result = fn(client, **params)
            if not isinstance(result, ToolResult):
                raise ValueError(f"Expected ToolResult, got {type(result)}")
            if not result.success:
                raise ValueError(f"Test returned success=False: {result.error}")
        except Exception as e:
            tb = traceback.format_exc()
            attempts_detail.append({"attempt": attempt, "code": code, "error": f"Runtime: {e}", "traceback": tb})
            last_error, last_tb = e, tb
            continue

        registered = register_synthesized_tool(tool_name, desc, code, params_schema)
        attempts_detail.append({"attempt": attempt, "code": code, "error": None, "registered": registered})
        return {"success": True, "tool_name": tool_name, "attempts": attempt,
                "description": desc, "error": None, "attempts_detail": attempts_detail}

    return {"success": False, "tool_name": tool_name, "attempts": MAX_ATTEMPTS,
            "error": f"Failed after {MAX_ATTEMPTS} attempts: {last_error}",
            "attempts_detail": attempts_detail}


def _infer_test_params(params_schema: dict, client: GitHubClient) -> dict:
    params = {}
    for name, schema in params_schema.items():
        if not schema.get("required", False):
            continue
        t = schema.get("type", "str")
        if name == "repo":
            try:
                user = client.get("/user")
                params["repo"] = f"{user['login']}/{user['login']}"
            except Exception:
                params["repo"] = "octocat/Hello-World"
        elif t in ("int", "integer"):
            params[name] = 1
        elif t in ("bool", "boolean"):
            params[name] = False
        elif t in ("list", "List"):
            params[name] = []
        else:
            params[name] = "test"
    return params
