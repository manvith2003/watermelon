from memory.execution_memory import find_similar_executions, get_optimal_pattern, get_all_learnings
from memory.capability_memory import get_all_capabilities, get_all_constraints, get_synthesized_capabilities


def get_planning_context(instruction: str) -> dict:
    similar  = find_similar_executions(instruction, limit=3)
    optimal  = get_optimal_pattern(instruction)
    all_cons = get_all_constraints()
    caps     = get_all_capabilities()

    all_learnings = get_all_learnings()
    instruction_words = set(instruction.lower().split())
    relevant_learnings = [
        item["learnings"] for item in all_learnings
        if len(set(item["instruction"].lower().split()) & instruction_words) >= 2
    ]

    return {
        "similar_past_executions": [
            {
                "instruction":   e["instruction"],
                "similarity":    e["similarity"],
                "success":       bool(e["success"]),
                "api_calls_used": e["total_api_calls"],
                "steps_used":    [s.get("tool", "?") for s in e["decomposed_steps"]],
                "what_failed":   [r.get("error") for r in e["results"] if not r.get("success")],
            }
            for e in similar
        ],
        "optimal_step_pattern": {
            "exists":       optimal is not None,
            "steps":        optimal["optimal_steps"] if optimal else [],
            "avg_api_calls": optimal["avg_api_calls"] if optimal else None,
            "success_rate": (
                optimal["success_count"] / (optimal["success_count"] + optimal["failure_count"])
                if optimal else None
            ),
        },
        "runtime_constraints": [
            {"tool": c["tool_name"], "type": c["constraint_type"],
             "description": c["description"], "value": c["value"]}
            for c in all_cons
        ],
        "available_capabilities": [
            {
                "name":          cap["name"],
                "description":   cap["description"],
                "is_synthesized": bool(cap["is_synthesized"]),
                "success_rate":  (
                    cap["success_count"] / (cap["success_count"] + cap["failure_count"])
                    if (cap["success_count"] + cap["failure_count"]) > 0 else None
                ),
                "avg_time_ms":   round(cap["avg_time_ms"]),
                "known_constraints": cap["constraints"],
            }
            for cap in caps
        ],
        "relevant_learnings": relevant_learnings,
    }


def format_context_for_prompt(context: dict) -> str:
    lines = []

    if context["similar_past_executions"]:
        lines.append("## Past Similar Runs")
        for e in context["similar_past_executions"]:
            status = "OK" if e["success"] else "FAILED"
            lines.append(
                f"- [{status}] (sim={e['similarity']}) "{e['instruction']}""
                f" → {e['api_calls_used']} calls, steps: {e['steps_used']}"
            )
            if e["what_failed"]:
                lines.append(f"  failures: {e['what_failed']}")

    opt = context["optimal_step_pattern"]
    if opt["exists"] and opt["steps"]:
        lines.append("\n## Best Known Step Order For This Task")
        lines.append(f"Success rate: {opt['success_rate']:.0%}, avg {opt['avg_api_calls']:.1f} calls")
        for i, step in enumerate(opt["steps"], 1):
            tool = step.get("tool", "?") if isinstance(step, dict) else str(step)
            desc = step.get("description", "") if isinstance(step, dict) else ""
            lines.append(f"  {i}. {tool} — {desc}")

    if context["runtime_constraints"]:
        lines.append("\n## Known Constraints (respect these)")
        for c in context["runtime_constraints"]:
            lines.append(
                f"- [{c['tool']}] {c['type']}: {c['description']}"
                + (f" (limit: {c['value']})" if c["value"] else "")
            )

    if context["relevant_learnings"]:
        lines.append("\n## Learnings From Similar Tasks")
        for learning in context["relevant_learnings"][:3]:
            for k, v in learning.items():
                lines.append(f"- {k}: {v}")

    synth = [c for c in context["available_capabilities"] if c["is_synthesized"]]
    if synth:
        lines.append("\n## Previously Synthesized Tools (prefer if applicable)")
        for cap in synth:
            sr = f"{cap['success_rate']:.0%}" if cap["success_rate"] is not None else "untested"
            lines.append(f"- {cap['name']}: {cap['description']} [success={sr}]")

    return "\n".join(lines) if lines else "(No relevant memory for this instruction.)"
