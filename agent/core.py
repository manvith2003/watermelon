"""
Agent Core — the main entry point for running instructions.

Ties together: planner → executor → memory → learning.
Returns a full ExecutionReport after each run.
"""
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
        """
        Execute a natural language instruction on GitHub.

        Returns a structured execution report containing:
          - What was done (step by step)
          - What failed and why
          - What the agent decided to do about failures
          - Memory usage summary (was memory used? what changed?)
          - Self-learning metrics (improvement since last similar run)
        """
        self._ensure_initialized()
        effective_repo = repo or self.default_repo
        client = GitHubClient(self.github_token)

        # ── 1. Get memory context (before) ──────────────────────────────────
        memory_context_before = get_planning_context(instruction)

        # ── 2. Plan ──────────────────────────────────────────────────────────
        plan_start = time.time()
        execution_plan = plan(instruction, repo=effective_repo)
        plan_duration_ms = int((time.time() - plan_start) * 1000)

        # ── 3. Execute ───────────────────────────────────────────────────────
        report = execute_plan(execution_plan, client)
        report["plan_duration_ms"] = plan_duration_ms

        # ── 4. Extract structured learnings ─────────────────────────────────
        learnings = extract_learnings(report)
        report["learnings"].update(learnings)

        # ── 5. Persist to execution memory ───────────────────────────────────
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

        # ── 6. Memory diff (what changed) ────────────────────────────────────
        memory_context_after = get_planning_context(instruction)
        report["memory_delta"] = _compute_memory_delta(
            memory_context_before, memory_context_after, report
        )

        # ── 7. Self-learning signal ───────────────────────────────────────────
        report["improvement_signal"] = compute_improvement_signal(instruction)

        return report

    def show_memory_state(self) -> dict:
        """Return current memory state for inspection (useful in demos)."""
        from memory.capability_memory import get_capability_stats, get_all_capabilities
        from memory.execution_memory import get_learning_metrics
        return {
            "capabilities": get_capability_stats(),
            "learning_metrics": get_learning_metrics(),
        }


def _compute_memory_delta(before: dict, after: dict, report: dict) -> dict:
    """
    Compute what changed in memory as a result of this execution.
    This is the 'show before/after' requirement.
    """
    new_constraints = (
        len(after.get("runtime_constraints", []))
        - len(before.get("runtime_constraints", []))
    )

    new_capabilities = (
        len([c for c in after.get("available_capabilities", []) if c.get("is_synthesized")])
        - len([c for c in before.get("available_capabilities", []) if c.get("is_synthesized")])
    )

    return {
        "new_constraints_discovered": new_constraints,
        "new_capabilities_synthesized": new_capabilities,
        "execution_added_to_memory": True,
        "pattern_updated": True,
        "memory_was_used_for_planning": bool(before.get("optimal_step_pattern", {}).get("exists")),
        "summary": _delta_summary(new_constraints, new_capabilities, report),
    }


def _delta_summary(new_constraints: int, new_capabilities: int, report: dict) -> str:
    parts = []
    if new_constraints > 0:
        parts.append(f"+{new_constraints} runtime constraint(s) discovered and stored")
    if new_capabilities > 0:
        parts.append(f"+{new_capabilities} new capability/capabilities synthesized and registered")
    parts.append(f"Execution recorded (ID={report.get('execution_id')}): "
                 f"{report['total_api_calls']} API calls, "
                 f"{report['total_duration_ms']}ms")
    if report.get("memory_delta", {}).get("memory_was_used_for_planning"):
        parts.append("Memory was actively used: planner adopted known-good step pattern")
    return "; ".join(parts)
