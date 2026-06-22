"""
Capability Memory — what the agent knows how to do.

Stores both base tools and synthesized tools, along with their success rates,
discovered runtime constraints, and usage patterns. The agent uses this to:
  - Know which tools exist and what they do
  - Prefer tools with higher success rates for a given task
  - Avoid or work around known constraints (rate limits, pagination limits, etc.)
  - Reuse synthesized capabilities across sessions
"""
import json
import time
from typing import Optional

from memory.db import get_connection


def register_capability(
    name: str,
    description: str,
    implementation: str,
    params_schema: Optional[dict] = None,
    is_synthesized: bool = False,
) -> None:
    """Add or update a capability in memory."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO capabilities (name, description, implementation, params_schema, is_synthesized)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            description = excluded.description,
            implementation = excluded.implementation,
            params_schema = excluded.params_schema
        """,
        (
            name,
            description,
            implementation,
            json.dumps(params_schema or {}),
            int(is_synthesized),
        ),
    )
    conn.commit()
    conn.close()


def record_capability_use(name: str, success: bool, duration_ms: int) -> None:
    """Update success/failure counts and average time for a capability."""
    conn = get_connection()
    row = conn.execute(
        "SELECT success_count, failure_count, avg_time_ms FROM capabilities WHERE name = ?",
        (name,),
    ).fetchone()
    if not row:
        conn.close()
        return

    total = row["success_count"] + row["failure_count"] + 1
    new_avg = (row["avg_time_ms"] * (total - 1) + duration_ms) / total
    new_success = row["success_count"] + (1 if success else 0)
    new_failure = row["failure_count"] + (0 if success else 1)

    conn.execute(
        """
        UPDATE capabilities SET
            success_count = ?, failure_count = ?, avg_time_ms = ?,
            last_used = datetime('now')
        WHERE name = ?
        """,
        (new_success, new_failure, new_avg, name),
    )
    conn.commit()
    conn.close()


def record_constraint(
    tool_name: str,
    constraint_type: str,
    description: str,
    value: Optional[str] = None,
) -> None:
    """
    Record a runtime-discovered constraint.
    e.g. ("list_issues", "pagination", "GitHub returns max 100 items per page", "100")
    """
    conn = get_connection()
    # Avoid duplicates
    existing = conn.execute(
        "SELECT id FROM runtime_constraints WHERE tool_name=? AND constraint_type=? AND description=?",
        (tool_name, constraint_type, description),
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO runtime_constraints (tool_name, constraint_type, description, value) VALUES (?,?,?,?)",
            (tool_name, constraint_type, description, value),
        )
        # Also append to the capability's constraints JSON
        row = conn.execute(
            "SELECT constraints FROM capabilities WHERE name = ?", (tool_name,)
        ).fetchone()
        if row:
            constraints = json.loads(row["constraints"])
            constraints.append({
                "type": constraint_type,
                "description": description,
                "value": value,
            })
            conn.execute(
                "UPDATE capabilities SET constraints = ? WHERE name = ?",
                (json.dumps(constraints), tool_name),
            )
    conn.commit()
    conn.close()


def get_all_capabilities() -> list[dict]:
    """Return all registered capabilities with their stats."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM capabilities ORDER BY is_synthesized ASC, success_count DESC"
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        d["params_schema"] = json.loads(d["params_schema"])
        d["constraints"] = json.loads(d["constraints"])
        result.append(d)
    return result


def get_synthesized_capabilities() -> list[dict]:
    """Return only synthesized (LLM-generated) capabilities."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM capabilities WHERE is_synthesized = 1 ORDER BY success_count DESC"
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        d["params_schema"] = json.loads(d["params_schema"])
        d["constraints"] = json.loads(d["constraints"])
        result.append(d)
    return result


def get_capability(name: str) -> Optional[dict]:
    """Fetch a single capability by name."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM capabilities WHERE name = ?", (name,)
    ).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["params_schema"] = json.loads(d["params_schema"])
        d["constraints"] = json.loads(d["constraints"])
        return d
    return None


def get_constraints_for_tool(tool_name: str) -> list[dict]:
    """Return all runtime constraints discovered for a specific tool."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM runtime_constraints WHERE tool_name = ? ORDER BY discovered_at DESC",
        (tool_name,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_constraints() -> list[dict]:
    """Return all known runtime constraints."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM runtime_constraints ORDER BY discovered_at DESC LIMIT 100"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def capability_exists(name: str) -> bool:
    conn = get_connection()
    row = conn.execute("SELECT id FROM capabilities WHERE name = ?", (name,)).fetchone()
    conn.close()
    return row is not None


def get_capability_stats() -> dict:
    """Summary statistics for the demo walkthrough."""
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM capabilities").fetchone()[0]
    synthesized = conn.execute(
        "SELECT COUNT(*) FROM capabilities WHERE is_synthesized = 1"
    ).fetchone()[0]
    constraints = conn.execute("SELECT COUNT(*) FROM runtime_constraints").fetchone()[0]
    best = conn.execute(
        "SELECT name, success_count, avg_time_ms FROM capabilities ORDER BY success_count DESC LIMIT 3"
    ).fetchall()
    conn.close()
    return {
        "total_capabilities": total,
        "base_capabilities": total - synthesized,
        "synthesized_capabilities": synthesized,
        "known_constraints": constraints,
        "most_used": [dict(r) for r in best],
    }
