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


# ── Files & Folders ──────────────────────────────────────────────────────────

def create_folder(name: str, parent_id: int | None = None) -> int:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}folders (name, parent_id) VALUES (%s, %s) RETURNING id",
            (name, parent_id),
        )
        return cur.fetchone()[0]


def get_folders(parent_id: int | None = None) -> list[dict]:
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if parent_id is None:
            cur.execute(f"SELECT * FROM {P}folders WHERE parent_id IS NULL ORDER BY name")
        else:
            cur.execute(f"SELECT * FROM {P}folders WHERE parent_id = %s ORDER BY name", (parent_id,))
        return cur.fetchall()


def save_file(filename: str, file_type: str, mime_type: str = "", file_size: int = 0,
              folder_id: int | None = None, telegram_file_id: str = "",
              summary: str = "", transcript: str = "", tags: list = None,
              conversation_id: int | None = None) -> int:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}files (filename, file_type, mime_type, file_size, folder_id, "
            f"telegram_file_id, summary, transcript, tags, conversation_id) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (filename, file_type, mime_type, file_size, folder_id,
             telegram_file_id, summary, transcript, tags or [], conversation_id),
        )
        return cur.fetchone()[0]


def get_files(folder_id: int | None = None, file_type: str | None = None,
              limit: int = 50) -> list[dict]:
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        conditions = []
        params = []
        if folder_id is not None:
            conditions.append("folder_id = %s")
            params.append(folder_id)
        if file_type:
            conditions.append("file_type = %s")
            params.append(file_type)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        cur.execute(f"SELECT * FROM {P}files {where} ORDER BY uploaded_at DESC LIMIT %s", params)
        return cur.fetchall()


def get_file(file_id: int) -> dict | None:
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {P}files WHERE id = %s", (file_id,))
        return cur.fetchone()


# ── Sessions & Auth ──────────────────────────────────────────────────────────

def create_session(email: str, token: str, hours: int = 168) -> None:
    from datetime import timedelta
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}sessions (token, email, expires_at) VALUES (%s, %s, NOW() + %s)",
            (token, email, timedelta(hours=hours)),
        )


def validate_session(token: str) -> str | None:
    """Returns email if valid, None otherwise."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT email FROM {P}sessions WHERE token = %s AND expires_at > NOW()",
            (token,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def delete_session(token: str):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(f"DELETE FROM {P}sessions WHERE token = %s", (token,))


def create_magic_link(email: str, token: str, minutes: int = 15) -> None:
    from datetime import timedelta
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}magic_links (token, email, expires_at) VALUES (%s, %s, NOW() + %s)",
            (token, email, timedelta(minutes=minutes)),
        )


def validate_magic_link(token: str) -> str | None:
    """Returns email if valid and unused, None otherwise. Marks as used."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT id, email FROM {P}magic_links WHERE token = %s AND used = FALSE AND expires_at > NOW()",
            (token,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(f"UPDATE {P}magic_links SET used = TRUE WHERE id = %s", (row[0],))
        return row[1]


# ── Agents ───────────────────────────────────────────────────────────────────

def get_agents() -> list[dict]:
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {P}agents ORDER BY name")
        return cur.fetchall()


def update_agent_status(name: str, status: str):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {P}agents SET status = %s, last_heartbeat = NOW() WHERE name = %s",
            (status, name),
        )


# ── Missions ─────────────────────────────────────────────────────────────────

def create_mission(title: str, description: str = "", priority: str = "normal",
                   assigned_agent: str | None = None, tags: list | None = None) -> int:
    with _conn() as conn, conn.cursor() as cur:
        status = "assigned" if assigned_agent else "inbox"
        cur.execute(
            f"INSERT INTO {P}missions (title, description, status, priority, assigned_agent, tags) "
            f"VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (title, description, status, priority, assigned_agent, tags or []),
        )
        return cur.fetchone()[0]


def get_missions(status: str | None = None, agent: str | None = None) -> list[dict]:
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        conditions, params = [], []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if agent:
            conditions.append("assigned_agent = %s")
            params.append(agent)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        cur.execute(f"SELECT * FROM {P}missions {where} ORDER BY "
                    f"CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, "
                    f"created_at DESC LIMIT 100", params)
        return cur.fetchall()


def update_mission(mission_id: int, **kwargs):
    with _conn() as conn, conn.cursor() as cur:
        sets = ["updated_at = NOW()"]
        params = []
        for k, v in kwargs.items():
            if k in ("status", "priority", "assigned_agent", "result", "title", "description"):
                sets.append(f"{k} = %s")
                params.append(v)
        params.append(mission_id)
        cur.execute(f"UPDATE {P}missions SET {', '.join(sets)} WHERE id = %s", params)


# ── Activity Feed ────────────────────────────────────────────────────────────

def log_activity(agent_name: str, event_type: str, content: str, metadata: dict | None = None):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}activity_feed (agent_name, event_type, content, metadata) VALUES (%s, %s, %s, %s)",
            (agent_name, event_type, content, json.dumps(metadata or {})),
        )


def get_activity_feed(limit: int = 50, agent: str | None = None) -> list[dict]:
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if agent:
            cur.execute(f"SELECT * FROM {P}activity_feed WHERE agent_name = %s ORDER BY timestamp DESC LIMIT %s",
                        (agent, limit))
        else:
            cur.execute(f"SELECT * FROM {P}activity_feed ORDER BY timestamp DESC LIMIT %s", (limit,))
        return cur.fetchall()


# ── Schema bootstrap ─────────────────────────────────────────────────────────

def ensure_tables():
    """Run schema.sql to create tables if they don't exist."""
    import pathlib
    sql = pathlib.Path(__file__).parent.joinpath("schema.sql").read_text()
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
