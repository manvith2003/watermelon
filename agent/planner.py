"""
Planner — uses the LLM to decompose a natural language instruction into
an ordered list of executable steps, informed by memory context.

The planner is memory-aware: it receives the full planning context from
memory_manager and uses it to:
  - Reuse known-good step orderings
  - Avoid steps that previously failed for this instruction type
  - Respect discovered runtime constraints (pagination limits, rate limits, etc.)
  - Prefer synthesized tools when available
"""
import json
import os
from typing import Optional

from litellm import completion

from memory.memory_manager import get_planning_context, format_context_for_prompt
from tools.registry import get_tool_descriptions

LLM_MODEL = os.environ.get("LLM_MODEL", "groq/llama-3.3-70b-versatile")

PLANNER_SYSTEM_TEMPLATE = """\
You are an autonomous GitHub platform agent. Your job is to decompose a natural language
instruction into an ordered list of executable steps using the available GitHub tools.

AVAILABLE TOOLS:
{tool_descriptions}

MEMORY CONTEXT (use this to make better decisions):
{memory_context}

RULES:
1. Return ONLY valid JSON — no markdown fences, no prose.
2. Each step must specify a tool from the available tools list.
3. If you need an operation that no tool covers, add it to "capability_gaps".
4. If memory shows a known-good step sequence, prefer it (fewer API calls = better).
5. Respect all KNOWN RUNTIME CONSTRAINTS listed in memory.
6. steps[].depends_on lists step IDs that must succeed before this step.
7. confidence: 0.0-1.0 — how sure you are this step will succeed.
8. For each step, include "memory_note" explaining if/how memory influenced this choice.

OUTPUT FORMAT (return exactly this structure):
{{
  "plan_summary": "one sentence",
  "steps": [
    {{
      "id": 1,
      "description": "human-readable description",
      "tool": "tool_name",
      "params": {{"repo": "owner/repo"}},
      "depends_on": [],
      "confidence": 0.9,
      "memory_note": "reusing known-good approach from similar past execution",
      "rollback_tool": null,
      "rollback_params": null
    }}
  ],
  "capability_gaps": [],
  "estimated_api_calls": 3,
  "memory_used": true
}}
"""


def plan(instruction: str, repo: Optional[str] = None) -> dict:
    """
    Produce an execution plan for the given instruction.
    Returns the parsed plan dict.
    """
    # Pull memory context
    context = get_planning_context(instruction)
    memory_context_str = format_context_for_prompt(context)
    tool_descriptions = get_tool_descriptions()

    system_prompt = PLANNER_SYSTEM_TEMPLATE.format(
        tool_descriptions=tool_descriptions,
        memory_context=memory_context_str,
    )

    user_message = f"Instruction: {instruction}"
    if repo:
        user_message += f"\nDefault repository: {repo}"

    user_message += "\n\nProduce the execution plan as JSON."

    response = completion(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    plan_dict = json.loads(raw)

    # Attach planning metadata
    plan_dict["_instruction"] = instruction
    plan_dict["_memory_context"] = context
    plan_dict["_model"] = LLM_MODEL

    return plan_dict
