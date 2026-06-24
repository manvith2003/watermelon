import json
from typing import Optional
from difflib import SequenceMatcher
from collections import defaultdict

from memory.db import get_connection

STOP_WORDS = {"a", "an", "the", "in", "on", "for", "and", "or", "of", "to", "from", "all", "my"}


def _instruction_signature(instruction: str) -> str:
    words = instruction.lower().split()
    key_words = [w for w in words if w not in STOP_WORDS][:8]
    return " ".join(key_words)


def record_execution(
    instruction: str,
    decomposed_steps: list,
    results: list,
    success: bool,
    total_api_calls: int,
    execution_time_ms: int,
    learnings: Optional[dict] = None,
) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO executions
           (instruction, decomposed_steps, results, success, total_api_calls, execution_time_ms, learnings)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
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
    _update_step_pattern(instruction, decomposed_steps, success, total_api_calls, execution_time_ms)
    return exec_id


def _update_step_pattern(instruction, steps, success, api_calls, time_ms):
    key = _instruction_signature(instruction)
    conn = get_connection()
    c = conn.cursor()
    row = c.execute("SELECT * FROM step_patterns WHERE pattern_key = ?", (key,)).fetchone()

    if row is None:
        c.execute(
            """INSERT INTO step_patterns
               (pattern_key, optimal_steps, success_count, failure_count, avg_api_calls, avg_time_ms)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (key, json.dumps(steps) if success else "[]",
             1 if success else 0, 0 if success else 1,
             float(api_calls), float(time_ms)),
        )
    else:
        new_s = row["success_count"] + (1 if success else 0)
        new_f = row["failure_count"] + (0 if success else 1)
        total = new_s + new_f
        new_avg_api  = (row["avg_api_calls"] * (total - 1) + api_calls) / total
        new_avg_time = (row["avg_time_ms"]   * (total - 1) + time_ms)   / total
        current_best = json.loads(row["optimal_steps"])
        new_optimal  = (json.dumps(steps)
                        if success and (not current_best or api_calls < row["avg_api_calls"])
                        else row["optimal_steps"])
        c.execute(
            """UPDATE step_patterns SET
               optimal_steps=?, success_count=?, failure_count=?,
               avg_api_calls=?, avg_time_ms=?, last_updated=datetime('now')
               WHERE pattern_key=?""",
            (new_optimal, new_s, new_f, new_avg_api, new_avg_time, key),
        )
    conn.commit()
    conn.close()


def find_similar_executions(instruction: str, limit: int = 3) -> list:
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
        if sim > 0.3:
            row["similarity"]        = round(sim, 2)
            row["decomposed_steps"]  = json.loads(row["decomposed_steps"])
            row["results"]           = json.loads(row["results"])
            row["learnings"]         = json.loads(row["learnings"])
            results.append(row)
    return results


def get_optimal_pattern(instruction: str) -> Optional[dict]:
    key = _instruction_signature(instruction)
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM step_patterns WHERE pattern_key=? AND success_count>0", (key,)
    ).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["optimal_steps"] = json.loads(d["optimal_steps"])
        return d
    return None


def get_learning_metrics() -> dict:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM executions ORDER BY timestamp ASC").fetchall()
    conn.close()

    groups: dict = defaultdict(list)
    for row in rows:
        key = _instruction_signature(row["instruction"])
        groups[key].append({
            "timestamp": row["timestamp"],
            "api_calls": row["total_api_calls"],
            "time_ms":   row["execution_time_ms"],
            "success":   bool(row["success"]),
        })

    metrics = {}
    for key, runs in groups.items():
        if len(runs) >= 2:
            first, last = runs[0], runs[-1]
            metrics[key] = {
                "runs":                   len(runs),
                "first_run_api_calls":    first["api_calls"],
                "latest_run_api_calls":   last["api_calls"],
                "api_calls_saved":        first["api_calls"] - last["api_calls"],
                "first_run_time_ms":      first["time_ms"],
                "latest_run_time_ms":     last["time_ms"],
                "time_saved_ms":          first["time_ms"] - last["time_ms"],
                "success_rate":           sum(r["success"] for r in runs) / len(runs),
            }
    return metrics


def get_all_learnings() -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT instruction, learnings, timestamp FROM executions "
        "WHERE learnings != '{}' ORDER BY timestamp DESC LIMIT 50"
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        learnings = json.loads(row["learnings"])
        if learnings:
            result.append({"instruction": row["instruction"], "learnings": learnings})
    return result
