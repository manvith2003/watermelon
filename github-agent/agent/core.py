import json
import time
from typing import Optional

from memory.db import init_db
from memory.execution_memory import record_execution
from memory.memory_manager import get_planning_context
from tools.base import GitHubClient
from tools.registry import initialize_registry
from agent.planner import plan
from agent.executor import execute_plan
from learning.feedback import extract_learnings, compute_improvement_signal


class Agent:
    def __init__(self, github_token: str, default_repo: Optional[str] = None):
        self.github_token = github_token
        self.default_repo = default_repo
        self._initialized = False

    def _ensure_initialized(self):
        if not self._initialized:
            init_db()
            initialize_registry()
            self._initialized = True

    def run(self, instruction: str, repo: Optional[str] = None) -> dict:
        self._ensure_initialized()
        effective_repo = repo or self.default_repo
        client = GitHubClient(self.github_token)

        memory_before = get_planning_context(instruction)

        plan_start = time.time()
        execution_plan = plan(instruction, repo=effective_repo)
        plan_ms = int((time.time() - plan_start) * 1000)

        report = execute_plan(execution_plan, client)
        report["plan_duration_ms"] = plan_ms

        learnings = extract_learnings(report)
        report["learnings"].update(learnings)

        exec_id = record_execution(
            instruction=instruction,
            decomposed_steps=execution_plan.get("steps", []),
            results=report["steps"],
            success=report["overall_success"],
            total_api_calls=report["total_api_calls"],
            execution_time_ms=report["total_duration_ms"],
            learnings=report["learnings"],
        )
        report["execution_id"] = exec_id

        memory_after = get_planning_context(instruction)
        report["memory_delta"] = _memory_delta(memory_before, memory_after, report)
        report["improvement_signal"] = compute_improvement_signal(instruction)

        return report

    def show_memory_state(self) -> dict:
        from memory.capability_memory import get_capability_stats
        from memory.execution_memory import get_learning_metrics
        return {
            "capabilities": get_capability_stats(),
            "learning_metrics": get_learning_metrics(),
        }


def _memory_delta(before: dict, after: dict, report: dict) -> dict:
    new_constraints = (
        len(after.get("runtime_constraints", []))
        - len(before.get("runtime_constraints", []))
    )
    new_synth = (
        len([c for c in after.get("available_capabilities", []) if c.get("is_synthesized")])
        - len([c for c in before.get("available_capabilities", []) if c.get("is_synthesized")])
    )
    parts = []
    if new_constraints > 0:
        parts.append(f"+{new_constraints} constraint(s) stored")
    if new_synth > 0:
        parts.append(f"+{new_synth} new capability synthesized")
    parts.append(
        f"Run saved (id={report.get('execution_id')}): "
        f"{report['total_api_calls']} API calls, {report['total_duration_ms']}ms"
    )
    if before.get("optimal_step_pattern", {}).get("exists"):
        parts.append("Memory was used to plan this run")
    return {
        "new_constraints_discovered": new_constraints,
        "new_capabilities_synthesized": new_synth,
        "execution_added_to_memory": True,
        "pattern_updated": True,
        "memory_was_used_for_planning": bool(before.get("optimal_step_pattern", {}).get("exists")),
        "summary": "; ".join(parts),
    }
