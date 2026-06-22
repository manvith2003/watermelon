"""
Executor — runs a plan step by step with partial-failure handling.

Key behaviours:
  - Steps run in dependency order
  - A step failure does NOT silently continue — it raises, records the failure,
    and decides (via LLM) whether to retry, skip, or abort the plan
  - Capability gaps trigger the synthesizer before execution
  - Runtime constraints (rate limits, field validation) are recorded to memory
"""
import json
import os
import time
from typing import Any, Optional

from litellm import completion

from tools.base import GitHubClient, ToolResult, RateLimitError, ValidationError
from tools.registry import call_tool, get_tool
from memory.capability_memory import record_capability_use, record_constraint

LLM_MODEL = os.environ.get("LLM_MODEL", "groq/llama-3.3-70b-versatile")

FAILURE_DECISION_PROMPT = """\
A step in an autonomous GitHub agent plan has failed. Decide what to do next.

Failed step: {step}
Error: {error}
Steps completed so far: {completed}
Remaining steps: {remaining}

Respond with JSON:
{
  "action": "retry" | "skip" | "abort",
  "reason": "...",
  "retry_modified_params": {}  // only if action=retry, with fixes applied
}

Rules:
- retry: if the error looks transient or fixable (wrong param, missing field)
- skip: if this step is optional and the plan can continue without it
- abort: if this step is critical and further steps cannot proceed
"""


def execute_plan(plan: dict, client: GitHubClient) -> dict:
    """
    Execute a plan. Returns a structured execution report.

    Report shape:
    {
      "instruction": str,
      "plan_summary": str,
      "steps": [{ "id", "tool", "description", "status", "result", "error",
                  "api_calls", "duration_ms", "decision" }],
      "overall_success": bool,
      "total_api_calls": int,
      "total_duration_ms": int,
      "capability_gaps_resolved": [],
      "learnings": {}
    }
    """
    from synthesis.synthesizer import synthesize_capability

    steps = plan.get("steps", [])
    report_steps = []
    completed_ids: set[int] = set()
    failed_ids: set[int] = set()
    step_outputs: dict[int, Any] = {}  # id → data from each step
    capability_gaps_resolved = []
    learnings: dict[str, Any] = {}

    total_start = time.time()
    client.reset_call_count()

    for step in steps:
        step_id = step["id"]
        tool_name = step["tool"]
        params = step.get("params", {})
        depends_on = step.get("depends_on", [])

        # Dependency check — skip if a dependency failed
        unmet_deps = [d for d in depends_on if d not in completed_ids]
        blocked_by_failure = [d for d in depends_on if d in failed_ids]

        if blocked_by_failure:
            report_steps.append({
                "id": step_id,
                "tool": tool_name,
                "description": step.get("description", ""),
                "status": "skipped",
                "result": None,
                "error": f"Skipped: dependency step(s) {blocked_by_failure} failed",
                "api_calls": 0,
                "duration_ms": 0,
                "decision": "auto-skipped due to dependency failure",
            })
            failed_ids.add(step_id)
            continue

        # Check if tool exists — if not, try to synthesize
        if get_tool(tool_name) is None:
            gap_description = step.get("description", f"Operation: {tool_name}")
            synth_result = synthesize_capability(
                tool_name=tool_name,
                description=gap_description,
                client=client,
            )
            if synth_result["success"]:
                capability_gaps_resolved.append({
                    "tool": tool_name,
                    "synthesized": True,
                    "description": gap_description,
                })
            else:
                report_steps.append({
                    "id": step_id,
                    "tool": tool_name,
                    "description": step.get("description", ""),
                    "status": "failed",
                    "result": None,
                    "error": f"Capability synthesis failed: {synth_result['error']}",
                    "api_calls": 0,
                    "duration_ms": 0,
                    "decision": synth_result.get("attempts_detail"),
                })
                failed_ids.add(step_id)
                continue

        # Inject outputs from prior steps if params reference them
        params = _resolve_param_references(params, step_outputs)

        # Execute with retry loop
        step_start = time.time()
        calls_before = client.api_calls
        status = "failed"
        result_data = None
        error_msg = None
        decision = None
        retries = 0
        MAX_RETRIES = 2

        while retries <= MAX_RETRIES:
            try:
                result: ToolResult = call_tool(client, tool_name, params)
                result_data = result.data
                status = "success"
                record_capability_use(tool_name, True, int((time.time() - step_start) * 1000))
                break
            except RateLimitError as e:
                error_msg = str(e)
                record_constraint(tool_name, "rate_limit", str(e))
                learnings["rate_limit_encountered"] = str(e)
                decision = "abort — rate limit"
                break
            except ValidationError as e:
                error_msg = str(e)
                record_constraint(tool_name, "validation", str(e))
                # Ask LLM how to fix
                fix = _ask_failure_decision(step, str(e), report_steps, steps[steps.index(step)+1:])
                if fix["action"] == "retry" and retries < MAX_RETRIES:
                    params.update(fix.get("retry_modified_params", {}))
                    retries += 1
                    decision = f"retry with modified params: {fix.get('retry_modified_params')}"
                    continue
                else:
                    decision = fix["action"] + ": " + fix["reason"]
                    record_capability_use(tool_name, False, int((time.time() - step_start) * 1000))
                    break
            except Exception as e:
                error_msg = str(e)
                fix = _ask_failure_decision(step, str(e), report_steps, steps[steps.index(step)+1:])
                if fix["action"] == "retry" and retries < MAX_RETRIES:
                    params.update(fix.get("retry_modified_params", {}))
                    retries += 1
                    decision = f"retry ({retries}/{MAX_RETRIES}): {fix['reason']}"
                    continue
                else:
                    decision = fix["action"] + ": " + fix["reason"]
                    record_capability_use(tool_name, False, int((time.time() - step_start) * 1000))
                    break

        duration_ms = int((time.time() - step_start) * 1000)
        api_calls_this_step = client.api_calls - calls_before

        step_report = {
            "id": step_id,
            "tool": tool_name,
            "description": step.get("description", ""),
            "status": status,
            "result": result_data,
            "error": error_msg,
            "api_calls": api_calls_this_step,
            "duration_ms": duration_ms,
            "decision": decision,
            "memory_note": step.get("memory_note"),
        }
        report_steps.append(step_report)

        if status == "success":
            completed_ids.add(step_id)
            step_outputs[step_id] = result_data
        else:
            failed_ids.add(step_id)

    total_duration_ms = int((time.time() - total_start) * 1000)
    overall_success = len(failed_ids) == 0

    return {
        "instruction": plan.get("_instruction", ""),
        "plan_summary": plan.get("plan_summary", ""),
        "steps": report_steps,
        "overall_success": overall_success,
        "total_api_calls": client.api_calls,
        "total_duration_ms": total_duration_ms,
        "steps_succeeded": len(completed_ids),
        "steps_failed": len(failed_ids),
        "capability_gaps_resolved": capability_gaps_resolved,
        "learnings": learnings,
        "memory_was_used": plan.get("memory_used", False),
    }


def _ask_failure_decision(step: dict, error: str, completed: list, remaining: list) -> dict:
    """Ask the LLM what to do about a failed step."""
    try:
        prompt = FAILURE_DECISION_PROMPT.format(
            step=json.dumps(step, indent=2),
            error=error,
            completed=json.dumps([s.get("tool") for s in completed]),
            remaining=json.dumps([s.get("tool") for s in remaining]),
        )
        response = completion(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
    except Exception:
        return {"action": "abort", "reason": "Could not get LLM decision"}


def _resolve_param_references(params: dict, step_outputs: dict) -> dict:
    """
    Substitute {{step_N.field}} references in params with actual step outputs.
    e.g. {"issue_number": "{{step_1.number}}"} → {"issue_number": 42}
    """
    import re

    def resolve_value(val: Any) -> Any:
        if isinstance(val, str):
            match = re.fullmatch(r"\{\{step_(\d+)\.(.+?)\}\}", val.strip())
            if match:
                step_id = int(match.group(1))
                field = match.group(2)
                output = step_outputs.get(step_id)
                if isinstance(output, dict):
                    return output.get(field, val)
        elif isinstance(val, dict):
            return {k: resolve_value(v) for k, v in val.items()}
        elif isinstance(val, list):
            return [resolve_value(v) for v in val]
        return val

    return {k: resolve_value(v) for k, v in params.items()}
