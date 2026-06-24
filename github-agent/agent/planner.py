import json
import os
from typing import Optional

from litellm import completion

from memory.memory_manager import get_planning_context, format_context_for_prompt
from tools.registry import get_tool_descriptions

LLM_MODEL = os.environ.get("LLM_MODEL", "groq/llama-3.3-70b-versatile")

PLANNER_SYSTEM_TEMPLATE = """You are an autonomous GitHub agent. Break the user's instruction into executable steps
using the tools listed below.

AVAILABLE TOOLS:
{tool_descriptions}

MEMORY CONTEXT:
{memory_context}

RULES:
1. Return ONLY valid JSON — no markdown, no extra text.
2. Every step must use a tool from the list above.
3. Unknown operations go in capability_gaps.
4. If memory has a known-good step sequence, use it.
5. Respect all runtime constraints from memory.
6. depends_on lists step IDs that must succeed first.
7. Add a memory_note explaining if memory influenced the step.

Return this exact JSON shape:
{{{{
  "plan_summary": "one sentence",
  "steps": [
    {{{{
      "id": 1,
      "description": "what this step does",
      "tool": "tool_name",
      "params": {{{{"repo": "owner/repo"}}}},
      "depends_on": [],
      "confidence": 0.9,
      "memory_note": "reusing known-good approach from past run",
      "rollback_tool": null,
      "rollback_params": null
    }}}}
  ],
  "capability_gaps": [],
  "estimated_api_calls": 3,
  "memory_used": true
}}}}
"""


def plan(instruction: str, repo: Optional[str] = None) -> dict:
    context = get_planning_context(instruction)
    memory_str = format_context_for_prompt(context)
    tools_str = get_tool_descriptions()

    system_prompt = PLANNER_SYSTEM_TEMPLATE.format(
        tool_descriptions=tools_str,
        memory_context=memory_str,
    )

    user_msg = f"Instruction: {instruction}"
    if repo:
        user_msg += f"\nDefault repo: {repo}"
    user_msg += "\n\nReturn the execution plan as JSON."

    response = completion(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    result = json.loads(raw)
    result["_instruction"] = instruction
    result["_memory_context"] = context
    result["_model"] = LLM_MODEL
    return result
