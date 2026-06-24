from memory.execution_memory import get_learning_metrics, find_similar_executions, _instruction_signature


def extract_learnings(report: dict) -> dict:
    learnings = {}

    failed = [s for s in report["steps"] if s["status"] == "failed"]
    for step in failed:
        err = step.get("error", "")
        if "rate limit" in err.lower():
            learnings["rate_limit_pattern"] = {"tool": step["tool"], "note": "hit rate limit"}
        if "422" in err or "validation" in err.lower():
            learnings["validation_constraint"] = {"tool": step["tool"], "error": err[:200]}
        if "404" in err:
            learnings["not_found_pattern"] = {"tool": step["tool"], "note": "resource not found"}

    succeeded = [s["tool"] for s in report["steps"] if s["status"] == "success"]
    if succeeded:
        learnings["successful_tool_sequence"] = succeeded

    total_calls = report.get("total_api_calls", 0)
    num_steps   = len(report["steps"])
    if num_steps > 0:
        learnings["avg_calls_per_step"] = round(total_calls / num_steps, 2)

    if report.get("capability_gaps_resolved"):
        learnings["synthesized_tools"] = [g["tool"] for g in report["capability_gaps_resolved"]]

    if report.get("memory_was_used"):
        learnings["memory_actively_used"] = True

    return learnings


def compute_improvement_signal(instruction: str) -> dict:
    metrics = get_learning_metrics()
    similar = find_similar_executions(instruction, limit=10)

    if not similar:
        return {"message": "First run of this task type — baseline set.", "run_count": 1, "improvement": None}

    key    = _instruction_signature(instruction)
    metric = metrics.get(key)
    if not metric:
        for k, v in metrics.items():
            if any(w in k for w in key.split()):
                metric = v
                break

    if not metric:
        return {"message": "Need more runs to measure improvement.", "run_count": len(similar), "improvement": None}

    saved   = metric["api_calls_saved"]
    runs    = metric["runs"]
    pct     = round(saved / metric["first_run_api_calls"] * 100, 1) if metric["first_run_api_calls"] > 0 else 0

    signal = {
        "run_count":              runs,
        "first_run_api_calls":    metric["first_run_api_calls"],
        "latest_run_api_calls":   metric["latest_run_api_calls"],
        "api_calls_saved":        saved,
        "api_calls_improvement_pct": pct,
        "first_run_time_ms":      metric["first_run_time_ms"],
        "latest_run_time_ms":     metric["latest_run_time_ms"],
        "time_saved_ms":          metric["time_saved_ms"],
        "success_rate":           round(metric["success_rate"] * 100, 1),
    }

    if saved > 0:
        signal["message"] = (
            f"Run {runs}: {metric['latest_run_api_calls']} API calls "
            f"vs {metric['first_run_api_calls']} on run 1 — saved {saved} calls ({pct}% fewer)."
        )
    elif saved < 0:
        signal["message"] = (
            f"Run {runs}: {metric['latest_run_api_calls']} calls "
            f"({abs(saved)} more than run 1 — task was more complex)."
        )
    else:
        signal["message"] = f"Run {runs}: same call count as run 1. Learning in progress."

    return signal
