"""
Self-Learning Feedback Loop.

Extracts structured learnings from an execution report and computes
measurable improvement signals — the numbers you show on the walkthrough call.

The primary learning signal: api_calls_per_similar_task decreases over time.
The mechanism: the planner uses memory context (optimal step patterns) to
plan fewer, better-ordered API calls on repeated task types.

Secondary signals:
  - failure_rate per task type (drops as constraints are learned)
  - synthesis_reuse_rate (synthesized tools get reused rather than re-synthesized)
  - step_order_stability (agent stops reordering steps once optimal order is known)
"""
import json
from typing import Any
from memory.execution_memory import get_learning_metrics, find_similar_executions


def extract_learnings(report: dict) -> dict:
    """
    Extract structured learnings from an execution report.
    These are stored in execution_memory.learnings and used by the planner.
    """
    learnings: dict[str, Any] = {}

    # Constraint discovery
    failed_steps = [s for s in report["steps"] if s["status"] == "failed"]
    for step in failed_steps:
        error = step.get("error", "")
        if "rate limit" in error.lower():
            learnings["rate_limit_pattern"] = {
                "tool": step["tool"],
                "note": "Rate limit hit — add delay or reduce batch size",
            }
        if "422" in error or "validation" in error.lower():
            learnings["validation_constraint"] = {
                "tool": step["tool"],
                "error": error[:200],
                "note": "Validation error discovered — check field requirements",
            }
        if "404" in error:
            learnings["not_found_pattern"] = {
                "tool": step["tool"],
                "note": "Resource not found — verify repo/issue exists before calling",
            }

    # Step ordering insight
    succeeded_tools = [s["tool"] for s in report["steps"] if s["status"] == "success"]
    if succeeded_tools:
        learnings["successful_tool_sequence"] = succeeded_tools

    # API efficiency insight
    total_calls = report.get("total_api_calls", 0)
    num_steps = len(report["steps"])
    if num_steps > 0:
        learnings["avg_calls_per_step"] = round(total_calls / num_steps, 2)

    # Capability synthesis record
    if report.get("capability_gaps_resolved"):
        learnings["synthesized_tools"] = [
            g["tool"] for g in report["capability_gaps_resolved"]
        ]

    # Memory usage record
    if report.get("memory_was_used"):
        learnings["memory_actively_used"] = True

    return learnings


def compute_improvement_signal(instruction: str) -> dict:
    """
    Compute the measurable improvement signal for a given instruction type.
    Called after recording the latest execution to show before/after numbers.

    Returns a dict with concrete numbers the demo can show.
    """
    metrics = get_learning_metrics()
    similar = find_similar_executions(instruction, limit=10)

    if not similar:
        return {
            "message": "First execution of this task type — baseline established.",
            "run_count": 1,
            "improvement": None,
        }

    # Find the most relevant metric group
    from memory.execution_memory import _instruction_signature
    key = _instruction_signature(instruction)
    metric = metrics.get(key)

    if not metric:
        # Try to find nearest key
        for k, v in metrics.items():
            if any(word in k for word in key.split()):
                metric = v
                break

    if not metric:
        return {
            "message": "Not enough similar runs to measure improvement yet.",
            "run_count": len(similar),
            "improvement": None,
        }

    api_saved = metric["api_calls_saved"]
    time_saved_ms = metric["time_saved_ms"]
    runs = metric["runs"]

    signal = {
        "run_count": runs,
        "first_run_api_calls": metric["first_run_api_calls"],
        "latest_run_api_calls": metric["latest_run_api_calls"],
        "api_calls_saved": api_saved,
        "api_calls_improvement_pct": (
            round(api_saved / metric["first_run_api_calls"] * 100, 1)
            if metric["first_run_api_calls"] > 0 else 0
        ),
        "first_run_time_ms": metric["first_run_time_ms"],
        "latest_run_time_ms": metric["latest_run_time_ms"],
        "time_saved_ms": time_saved_ms,
        "success_rate": round(metric["success_rate"] * 100, 1),
    }

    if api_saved > 0:
        signal["message"] = (
            f"Run {runs}: Used {metric['latest_run_api_calls']} API calls "
            f"(was {metric['first_run_api_calls']} on run 1). "
            f"Saved {api_saved} API calls ({signal['api_calls_improvement_pct']}% fewer) "
            f"because the agent learned the optimal step ordering from memory."
        )
    elif api_saved < 0:
        signal["message"] = (
            f"Run {runs}: Used {metric['latest_run_api_calls']} API calls "
            f"({abs(api_saved)} more than run 1 — likely a more complex variant of the task)."
        )
    else:
        signal["message"] = (
            f"Run {runs}: Same API call count as run 1. "
            f"Failure rate: {100 - signal['success_rate']:.0f}% → learning ongoing."
        )

    return signal
