"""Memory layer — read/write conversations, memory, open loops, decisions to PostgreSQL."""

from __future__ import annotations

import json
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from config import DATABASE_URL

P = "shams_"  # table prefix


def _conn():
    return psycopg2.connect(DATABASE_URL)


# ── Conversations ────────────────────────────────────────────────────────────

def save_message(role: str, content: str, metadata: dict | None = None):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}conversations (role, content, metadata) VALUES (%s, %s, %s)",
            (role, content, json.dumps(metadata or {})),
        )


def get_recent_messages(limit: int = 50) -> list[dict]:
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT role, content, metadata, timestamp FROM {P}conversations "
            f"ORDER BY timestamp DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
    return list(reversed(rows))


# ── Key-Value Memory ─────────────────────────────────────────────────────────

def remember(key: str, value: str):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}memory (key, value, updated_at) VALUES (%s, %s, NOW()) "
            f"ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            (key, value),
        )


def recall(key: str) -> str | None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT value FROM {P}memory WHERE key = %s", (key,))
        row = cur.fetchone()
    return row[0] if row else None


def recall_all() -> dict[str, str]:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT key, value FROM {P}memory ORDER BY key")
        return {r[0]: r[1] for r in cur.fetchall()}


# ── Open Loops ───────────────────────────────────────────────────────────────

def add_open_loop(title: str, context: str = "") -> int:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}open_loops (title, context) VALUES (%s, %s) RETURNING id",
            (title, context),
        )
        return cur.fetchone()[0]


def close_loop(loop_id: int, status: str = "done"):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {P}open_loops SET status = %s, updated_at = NOW() WHERE id = %s",
            (status, loop_id),
        )


def get_open_loops() -> list[dict]:
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT id, title, context, created_at FROM {P}open_loops WHERE status = 'open' ORDER BY created_at"
        )
        return cur.fetchall()


# ── Decisions ────────────────────────────────────────────────────────────────

def log_decision(summary: str, reasoning: str = "", outcome: str = ""):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}decisions (summary, reasoning, outcome) VALUES (%s, %s, %s)",
            (summary, reasoning, outcome),
        )


def get_recent_decisions(limit: int = 10) -> list[dict]:
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT summary, reasoning, outcome, created_at FROM {P}decisions "
            f"ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        return list(reversed(cur.fetchall()))


# ── Briefings ────────────────────────────────────────────────────────────────

def save_briefing(briefing_type: str, content: str, channel: str = "whatsapp"):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}briefings (type, content, delivered_at, channel) VALUES (%s, %s, NOW(), %s)",
            (briefing_type, content, channel),
        )


def get_last_briefing(briefing_type: str) -> dict | None:
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT type, content, delivered_at, channel FROM {P}briefings "
            f"WHERE type = %s ORDER BY delivered_at DESC LIMIT 1",
            (briefing_type,),
        )
        return cur.fetchone()


# ── Schema bootstrap ─────────────────────────────────────────────────────────

def ensure_tables():
    """Run schema.sql to create tables if they don't exist."""
    import pathlib
    sql = pathlib.Path(__file__).parent.joinpath("schema.sql").read_text()
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
