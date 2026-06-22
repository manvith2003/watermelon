"""
SQLite database setup and connection management.
"""
import sqlite3
import os
from pathlib import Path

DB_PATH = os.environ.get("AGENT_DB_PATH", str(Path.home() / ".github_agent" / "memory.db"))


def get_connection() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    c = conn.cursor()

    # --- Execution Memory ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS executions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            instruction TEXT NOT NULL,
            decomposed_steps TEXT NOT NULL,       -- JSON array
            results     TEXT NOT NULL,            -- JSON array, one per step
            success     INTEGER NOT NULL,         -- 0/1
            total_api_calls INTEGER NOT NULL DEFAULT 0,
            execution_time_ms INTEGER NOT NULL DEFAULT 0,
            timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
            learnings   TEXT NOT NULL DEFAULT '{}' -- JSON: constraints, patterns
        )
    """)

    # Tracks which step orderings succeed for a given instruction category
    c.execute("""
        CREATE TABLE IF NOT EXISTS step_patterns (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_key     TEXT NOT NULL,        -- normalised instruction signature
            optimal_steps   TEXT NOT NULL,        -- JSON: step sequence that worked
            success_count   INTEGER NOT NULL DEFAULT 0,
            failure_count   INTEGER NOT NULL DEFAULT 0,
            avg_api_calls   REAL NOT NULL DEFAULT 0,
            avg_time_ms     REAL NOT NULL DEFAULT 0,
            last_updated    TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pattern_key ON step_patterns(pattern_key)")

    # --- Capability Memory ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS capabilities (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL UNIQUE,
            description     TEXT NOT NULL,
            implementation  TEXT NOT NULL,        -- Python source code
            params_schema   TEXT NOT NULL DEFAULT '{}', -- JSON schema for params
            is_synthesized  INTEGER NOT NULL DEFAULT 0,  -- 0=base, 1=synthesized
            success_count   INTEGER NOT NULL DEFAULT 0,
            failure_count   INTEGER NOT NULL DEFAULT 0,
            avg_time_ms     REAL NOT NULL DEFAULT 0,
            last_used       TEXT,
            constraints     TEXT NOT NULL DEFAULT '[]', -- JSON list of discovered constraints
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Runtime-discovered constraints (rate limits, field rules, permission boundaries)
    c.execute("""
        CREATE TABLE IF NOT EXISTS runtime_constraints (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name   TEXT NOT NULL,
            constraint_type TEXT NOT NULL,        -- 'rate_limit'|'permission'|'validation'|'pagination'
            description TEXT NOT NULL,
            value       TEXT,                     -- e.g. "100" for page size limit
            discovered_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    conn.commit()
    conn.close()
