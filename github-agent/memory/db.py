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
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS executions (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            instruction       TEXT NOT NULL,
            decomposed_steps  TEXT NOT NULL,
            results           TEXT NOT NULL,
            success           INTEGER NOT NULL,
            total_api_calls   INTEGER NOT NULL DEFAULT 0,
            execution_time_ms INTEGER NOT NULL DEFAULT 0,
            timestamp         TEXT NOT NULL DEFAULT (datetime('now')),
            learnings         TEXT NOT NULL DEFAULT '{}'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS step_patterns (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_key   TEXT NOT NULL,
            optimal_steps TEXT NOT NULL,
            success_count INTEGER NOT NULL DEFAULT 0,
            failure_count INTEGER NOT NULL DEFAULT 0,
            avg_api_calls REAL NOT NULL DEFAULT 0,
            avg_time_ms   REAL NOT NULL DEFAULT 0,
            last_updated  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pattern_key ON step_patterns(pattern_key)")

    c.execute("""
        CREATE TABLE IF NOT EXISTS capabilities (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT NOT NULL UNIQUE,
            description    TEXT NOT NULL,
            implementation TEXT NOT NULL,
            params_schema  TEXT NOT NULL DEFAULT '{}',
            is_synthesized INTEGER NOT NULL DEFAULT 0,
            success_count  INTEGER NOT NULL DEFAULT 0,
            failure_count  INTEGER NOT NULL DEFAULT 0,
            avg_time_ms    REAL NOT NULL DEFAULT 0,
            last_used      TEXT,
            constraints    TEXT NOT NULL DEFAULT '[]',
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS runtime_constraints (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name       TEXT NOT NULL,
            constraint_type TEXT NOT NULL,
            description     TEXT NOT NULL,
            value           TEXT,
            discovered_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    conn.commit()
    conn.close()
