"""
Execution Memory — what the agent has done before.

Stores past instructions, how they were decomposed, which approaches worked/failed,
and structured learnings extracted from each run. The agent actively queries this
before planning to reuse successful patterns and avoid known failure modes.
"""
import json
import time
from typing import Optional
from difflib import SequenceMatcher

from memory.db import get_connection


def record_execution(
    instruction: str,
    decomposed_steps: list[dict],
    results: list[dict],
    success: bool,
    total_api_calls: int,
    execution_time_ms: int,
    learnings: Optional[dict] = None,
) -> int:
    """Save a completed execution. Returns the new execution ID."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO executions
            (instruction, decomposed_steps, results, success,
             total_api_calls, execution_time_ms, learnings)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            instruction,
            json.dumps(decomposed_steps),
            json.dumps(results),
            int(success),
            total_api_calls,
            execution_time_ms,
            json.dumps(learnings or {}),
        ),
    )
    exec_id = c.lastrowid
    conn.commit()
    conn.close()

    # Update step_patterns for the instruction signature
    _update_step_pattern(instruction, decomposed_steps, success, total_api_calls, execution_time_ms)

    return exec_id


def _instruction_signature(instruction: str) -> str:
    """Normalise an instruction to a pattern key (lowercased, stripped, truncated)."""
    words = instruction.lower().split()
    # Keep only the first 8 "meaningful" words (skip common stop-words)
    STOP = {"a", "an", "the", "in", "on", "for", "and", "or", "of", "to", "from", "all", "my"}
    key_words = [w for w in words if w not in STOP][:8]
    return " ".join(key_words)


def _update_step_pattern(
    instruction: str,
    steps: list[dict],
    success: bool,
    api_calls: int,
    time_ms: int,
):
    pattern_key = _instruction_signature(instruction)
    conn = get_connection()
    c = conn.cursor()
    row = c.execute(
        "SELECT * FROM step_patterns WHERE pattern_key = ?", (pattern_key,)
    ).fetchone()

    if row is None:
        c.execute(
            """
            INSERT INTO step_patterns
                (pattern_key, optimal_steps, success_count, failure_count, avg_api_calls, avg_time_ms)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                pattern_key,
                json.dumps(steps) if success else "[]",
                1 if success else 0,
                0 if success else 1,
                float(api_calls),
                float(time_ms),
            ),
        )
    else:
        new_success = row["success_count"] + (1 if success else 0)
        new_failure = row["failure_count"] + (0 if success else 1)
        total = new_success + new_failure
        new_avg_api = (row["avg_api_calls"] * (total - 1) + api_calls) / total
        new_avg_time = (row["avg_time_ms"] * (total - 1) + time_ms) / total
        # Update optimal_steps only if this run succeeded and used fewer API calls
        current_best = json.loads(row["optimal_steps"])
        if success and (not current_best or api_calls < row["avg_api_calls"]):
            new_optimal = json.dumps(steps)
        else:
            new_optimal = row["optimal_steps"]

        c.execute(
            """
            UPDATE step_patterns SET
                optimal_steps = ?, success_count = ?, failure_count = ?,
                avg_api_calls = ?, avg_time_ms = ?,
                last_updated = datetime('now')
            WHERE pattern_key = ?
            """,
            (new_optimal, new_success, new_failure, new_avg_api, new_avg_time, pattern_key),
        )

    conn.commit()
    conn.close()


def find_similar_executions(instruction: str, limit: int = 3) -> list[dict]:
    """
    Return past executions most similar to the given instruction.
    Uses string similarity (good enough for structured task instructions).
    Returns list sorted by similarity desc.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM executions ORDER BY timestamp DESC LIMIT 100"
    ).fetchall()
    conn.close()

    scored = []
    for row in rows:
        sim = SequenceMatcher(None, instruction.lower(), row["instruction"].lower()).ratio()
        scored.append((sim, dict(row)))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for sim, row in scored[:limit]:
        if sim > 0.3:  # Only return if meaningfully similar
            row["similarity"] = round(sim, 2)
            row["decomposed_steps"] = json.loads(row["decomposed_steps"])
            row["results"] = json.loads(row["results"])
            row["learnings"] = json.loads(row["learnings"])
            results.append(row)
    return results


def get_optimal_pattern(instruction: str) -> Optional[dict]:
    """Return the best known step sequence for this instruction type, if one exists."""
    pattern_key = _instruction_signature(instruction)
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM step_patterns WHERE pattern_key = ? AND success_count > 0",
        (pattern_key,),
    ).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["optimal_steps"] = json.loads(d["optimal_steps"])
        return d
    return None


def get_learning_metrics() -> dict:
    """
    Return measurable improvement signals across all executions.
    Groups similar executions and shows api_calls over time.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM executions ORDER BY timestamp ASC"
    ).fetchall()
    conn.close()

    # Group by pattern_key
    from collections import defaultdict
    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        key = _instruction_signature(row["instruction"])
        groups[key].append({
            "timestamp": row["timestamp"],
            "api_calls": row["total_api_calls"],
            "time_ms": row["execution_time_ms"],
            "success": bool(row["success"]),
        })

    metrics = {}
    for key, runs in groups.items():
        if len(runs) >= 2:
            first = runs[0]
            last = runs[-1]
            metrics[key] = {
                "runs": len(runs),
                "first_run_api_calls": first["api_calls"],
                "latest_run_api_calls": last["api_calls"],
                "api_calls_saved": first["api_calls"] - last["api_calls"],
                "first_run_time_ms": first["time_ms"],
                "latest_run_time_ms": last["time_ms"],
                "time_saved_ms": first["time_ms"] - last["time_ms"],
                "success_rate": sum(r["success"] for r in runs) / len(runs),
            }
    return metrics


def get_all_learnings() -> list[dict]:
    """Return all structured learnings extracted from past executions."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT instruction, learnings, timestamp FROM executions WHERE learnings != '{}' ORDER BY timestamp DESC LIMIT 50"
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        learnings = json.loads(row["learnings"])
        if learnings:
            result.append({"instruction": row["instruction"], "learnings": learnings})
    return result
