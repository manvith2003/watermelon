"""
Memory Manager — unified interface for the agent to query memory.

Produces a structured context block that the planner injects into its
system prompt, enabling memory to actively change planning decisions.
"""
import json
from memory.execution_memory import find_similar_executions, get_optimal_pattern, get_all_learnings
from memory.capability_memory import get_all_capabilities, get_all_constraints, get_synthesized_capabilities


def get_planning_context(instruction: str) -> dict:
    """
    Returns a structured context dict used by the planner.
    This is what turns memory from a log into an active planning signal.
    """
    similar_execs = find_similar_executions(instruction, limit=3)
    optimal_pattern = get_optimal_pattern(instruction)
    all_constraints = get_all_constraints()
    capabilities = get_all_capabilities()
    synthesized = get_synthesized_capabilities()

    # Extract learnings relevant to this instruction type
    all_learnings = get_all_learnings()
    relevant_learnings = []
    instruction_lower = instruction.lower()
    for item in all_learnings:
        # Simple relevance: keyword overlap
        learning_words = set(item["instruction"].lower().split())
        instruction_words = set(instruction_lower.split())
        if len(learning_words & instruction_words) >= 2:
            relevant_learnings.append(item["learnings"])

    return {
        "similar_past_executions": [
            {
                "instruction": e["instruction"],
                "similarity": e["similarity"],
                "success": bool(e["success"]),
                "api_calls_used": e["total_api_calls"],
                "steps_used": [s.get("tool", "?") for s in e["decomposed_steps"]],
                "what_failed": [
                    r.get("error") for r in e["results"] if not r.get("success")
                ],
            }
            for e in similar_execs
        ],
        "optimal_step_pattern": {
            "exists": optimal_pattern is not None,
            "steps": optimal_pattern["optimal_steps"] if optimal_pattern else [],
            "avg_api_calls": optimal_pattern["avg_api_calls"] if optimal_pattern else None,
            "success_rate": (
                optimal_pattern["success_count"]
                / (optimal_pattern["success_count"] + optimal_pattern["failure_count"])
                if optimal_pattern else None
            ),
        },
        "runtime_constraints": [
            {
                "tool": c["tool_name"],
                "type": c["constraint_type"],
                "description": c["description"],
                "value": c["value"],
            }
            for c in all_constraints
        ],
        "available_capabilities": [
            {
                "name": cap["name"],
                "description": cap["description"],
                "is_synthesized": bool(cap["is_synthesized"]),
                "success_rate": (
                    cap["success_count"] / (cap["success_count"] + cap["failure_count"])
                    if (cap["success_count"] + cap["failure_count"]) > 0 else None
                ),
                "avg_time_ms": round(cap["avg_time_ms"]),
                "known_constraints": cap["constraints"],
            }
            for cap in capabilities
        ],
        "relevant_learnings": relevant_learnings,
    }


def format_context_for_prompt(context: dict) -> str:
    """
    Convert the context dict into a concise text block for the system prompt.
    Keeps it under ~800 tokens so it doesn't dominate the prompt.
    """
    lines = []

    # Similar past executions
    if context["similar_past_executions"]:
        lines.append("## Relevant Past Executions")
        for e in context["similar_past_executions"]:
            status = "SUCCESS" if e["success"] else "FAILED"
            lines.append(
                f"- [{status}] (sim={e['similarity']}) \"{e['instruction']}\""
                f" → {e['api_calls_used']} API calls, steps: {e['steps_used']}"
            )
            if e["what_failed"]:
                lines.append(f"  ⚠ Failures: {e['what_failed']}")

    # Optimal pattern hint
    opt = context["optimal_step_pattern"]
    if opt["exists"] and opt["steps"]:
        lines.append("\n## Known Optimal Step Pattern For This Task Type")
        lines.append(
            f"Success rate: {opt['success_rate']:.0%}, avg {opt['avg_api_calls']:.1f} API calls"
        )
        for i, step in enumerate(opt["steps"], 1):
            tool = step.get("tool", "?") if isinstance(step, dict) else str(step)
            desc = step.get("description", "") if isinstance(step, dict) else ""
            lines.append(f"  Step {i}: {tool} — {desc}")

    # Runtime constraints (critical for avoiding wasted API calls)
    if context["runtime_constraints"]:
        lines.append("\n## Known Runtime Constraints (MUST RESPECT)")
        for c in context["runtime_constraints"]:
            lines.append(f"- [{c['tool']}] {c['type']}: {c['description']}" + (
                f" (limit: {c['value']})" if c["value"] else ""
            ))

    # Relevant learnings
    if context["relevant_learnings"]:
        lines.append("\n## Extracted Learnings From Similar Tasks")
        for learning in context["relevant_learnings"][:3]:
            for k, v in learning.items():
                lines.append(f"- {k}: {v}")

    # Synthesized capabilities (agent should prefer these if applicable)
    synth_caps = [c for c in context["available_capabilities"] if c["is_synthesized"]]
    if synth_caps:
        lines.append("\n## Previously Synthesized Capabilities (prefer these if applicable)")
        for cap in synth_caps:
            sr = f"{cap['success_rate']:.0%}" if cap["success_rate"] is not None else "untested"
            lines.append(f"- {cap['name']}: {cap['description']} [success={sr}]")

    return "\n".join(lines) if lines else "(No relevant memory found for this instruction.)"
