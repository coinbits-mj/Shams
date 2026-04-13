"""Memory layer — read/write conversations, memory, open loops, decisions to PostgreSQL."""

from __future__ import annotations

import json
import psycopg2.extras
from datetime import datetime, timezone
from db import get_conn

P = "shams_"  # table prefix


# ── Conversations ────────────────────────────────────────────────────────────

def save_message(role: str, content: str, metadata: dict | None = None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}conversations (role, content, metadata) VALUES (%s, %s, %s)",
            (role, content, json.dumps(metadata or {})),
        )


def get_recent_messages(limit: int = 50) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT role, content, metadata, timestamp FROM {P}conversations "
            f"ORDER BY timestamp DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
    return list(reversed(rows))


# ── Key-Value Memory ─────────────────────────────────────────────────────────

def remember(key: str, value: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}memory (key, value, updated_at) VALUES (%s, %s, NOW()) "
            f"ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            (key, value),
        )


def recall(key: str) -> str | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT value FROM {P}memory WHERE key = %s", (key,))
        row = cur.fetchone()
    return row[0] if row else None


def recall_all() -> dict[str, str]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT key, value FROM {P}memory ORDER BY key")
        return {r[0]: r[1] for r in cur.fetchall()}


# ── Open Loops ───────────────────────────────────────────────────────────────

def add_open_loop(title: str, context: str = "") -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}open_loops (title, context) VALUES (%s, %s) RETURNING id",
            (title, context),
        )
        return cur.fetchone()[0]


def close_loop(loop_id: int, status: str = "done"):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {P}open_loops SET status = %s, updated_at = NOW() WHERE id = %s",
            (status, loop_id),
        )


def get_open_loops() -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT id, title, context, created_at FROM {P}open_loops WHERE status = 'open' ORDER BY created_at"
        )
        return cur.fetchall()


# ── Decisions ────────────────────────────────────────────────────────────────

def log_decision(summary: str, reasoning: str = "", outcome: str = ""):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}decisions (summary, reasoning, outcome) VALUES (%s, %s, %s)",
            (summary, reasoning, outcome),
        )


def get_recent_decisions(limit: int = 10) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT summary, reasoning, outcome, created_at FROM {P}decisions "
            f"ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        return list(reversed(cur.fetchall()))


# ── Briefings ────────────────────────────────────────────────────────────────

def save_briefing(briefing_type: str, content: str, channel: str = "whatsapp"):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}briefings (type, content, delivered_at, channel) VALUES (%s, %s, NOW(), %s)",
            (briefing_type, content, channel),
        )


def get_last_briefing(briefing_type: str) -> dict | None:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT type, content, delivered_at, channel FROM {P}briefings "
            f"WHERE type = %s ORDER BY delivered_at DESC LIMIT 1",
            (briefing_type,),
        )
        return cur.fetchone()


# ── Files & Folders ──────────────────────────────────────────────────────────

def create_folder(name: str, parent_id: int | None = None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}folders (name, parent_id) VALUES (%s, %s) RETURNING id",
            (name, parent_id),
        )
        return cur.fetchone()[0]


def get_folders(parent_id: int | None = None) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if parent_id is None:
            cur.execute(f"SELECT * FROM {P}folders WHERE parent_id IS NULL ORDER BY name")
        else:
            cur.execute(f"SELECT * FROM {P}folders WHERE parent_id = %s ORDER BY name", (parent_id,))
        return cur.fetchall()


def save_file(filename: str, file_type: str, mime_type: str = "", file_size: int = 0,
              folder_id: int | None = None, telegram_file_id: str = "",
              summary: str = "", transcript: str = "", tags: list = None,
              conversation_id: int | None = None, mission_id: int | None = None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}files (filename, file_type, mime_type, file_size, folder_id, "
            f"telegram_file_id, summary, transcript, tags, conversation_id, mission_id) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (filename, file_type, mime_type, file_size, folder_id,
             telegram_file_id, summary, transcript, tags or [], conversation_id, mission_id),
        )
        return cur.fetchone()[0]


def get_files(folder_id: int | None = None, file_type: str | None = None,
              limit: int = 50) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
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
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {P}files WHERE id = %s", (file_id,))
        return cur.fetchone()


# ── Sessions & Auth ──────────────────────────────────────────────────────────

def create_session(email: str, token: str, hours: int = 168) -> None:
    from datetime import timedelta
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}sessions (token, email, expires_at) VALUES (%s, %s, NOW() + %s)",
            (token, email, timedelta(hours=hours)),
        )


def validate_session(token: str) -> str | None:
    """Returns email if valid, None otherwise."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT email FROM {P}sessions WHERE token = %s AND expires_at > NOW()",
            (token,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def delete_session(token: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"DELETE FROM {P}sessions WHERE token = %s", (token,))


def create_magic_link(email: str, token: str, minutes: int = 15) -> None:
    from datetime import timedelta
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}magic_links (token, email, expires_at) VALUES (%s, %s, NOW() + %s)",
            (token, email, timedelta(minutes=minutes)),
        )


def validate_magic_link(token: str) -> str | None:
    """Returns email if valid and unused, None otherwise. Marks as used."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT id, email FROM {P}magic_links WHERE token = %s AND used = FALSE AND expires_at > NOW()",
            (token,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(f"UPDATE {P}magic_links SET used = TRUE WHERE id = %s", (row[0],))
        return row[1]


# ── Group Chat ────────────────────────────────────────────────────────────────

def save_group_message(agent_name: str, content: str, metadata: dict | None = None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}group_chat (agent_name, content, metadata) VALUES (%s, %s, %s)",
            (agent_name, content, json.dumps(metadata or {})),
        )


def get_group_messages(limit: int = 50) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT agent_name, content, metadata, timestamp FROM {P}group_chat "
            f"ORDER BY timestamp DESC LIMIT %s", (limit,)
        )
        return list(reversed(cur.fetchall()))


# ── Agents ───────────────────────────────────────────────────────────────────

def get_agents() -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {P}agents ORDER BY name")
        return cur.fetchall()


def update_agent_status(name: str, status: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {P}agents SET status = %s, last_heartbeat = NOW() WHERE name = %s",
            (status, name),
        )


# ── Missions ─────────────────────────────────────────────────────────────────

def create_mission(title: str, description: str = "", priority: str = "normal",
                   assigned_agent: str | None = None, tags: list | None = None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        status = "assigned" if assigned_agent else "inbox"
        cur.execute(
            f"INSERT INTO {P}missions (title, description, status, priority, assigned_agent, tags) "
            f"VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (title, description, status, priority, assigned_agent, tags or []),
        )
        return cur.fetchone()[0]


def get_missions(status: str | None = None, agent: str | None = None) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
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
    with get_conn() as conn, conn.cursor() as cur:
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
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}activity_feed (agent_name, event_type, content, metadata) VALUES (%s, %s, %s, %s)",
            (agent_name, event_type, content, json.dumps(metadata or {})),
        )


def get_activity_feed(limit: int = 50, agent: str | None = None,
                      event_type: str | None = None) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        conditions, params = [], []
        if agent:
            conditions.append("agent_name = %s")
            params.append(agent)
        if event_type:
            conditions.append("event_type = %s")
            params.append(event_type)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        cur.execute(f"SELECT * FROM {P}activity_feed {where} ORDER BY timestamp DESC LIMIT %s", params)
        return cur.fetchall()


# ── Notifications ───────────────────────────────────────────────────────────

def create_notification(event_type: str, title: str, detail: str = "",
                        link_type: str = "", link_id: int | None = None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}notifications (event_type, title, detail, link_type, link_id) "
            f"VALUES (%s, %s, %s, %s, %s)",
            (event_type, title, detail, link_type, link_id),
        )


def get_unseen_notifications(limit: int = 20) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT * FROM {P}notifications WHERE seen = FALSE "
            f"ORDER BY created_at DESC LIMIT %s", (limit,)
        )
        return cur.fetchall()


def mark_notifications_seen(ids: list[int]):
    if not ids:
        return
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {P}notifications SET seen = TRUE WHERE id = ANY(%s)", (ids,)
        )


def get_notification_counts() -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {P}notifications WHERE seen = FALSE")
        unseen = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM {P}actions WHERE status = 'pending'")
        pending_actions = cur.fetchone()[0]
        cur.execute(
            f"SELECT COUNT(*) FROM {P}email_triage WHERE priority IN ('P1','P2') AND archived = FALSE"
        )
        inbox_urgent = cur.fetchone()[0]
    return {
        "unseen_total": unseen,
        "actions_pending": pending_actions,
        "inbox_p1p2": inbox_urgent,
    }


# ── Email Triage ────────────────────────────────────────────────────────────

def save_triage_result(account: str, message_id: str, from_addr: str, subject: str,
                       snippet: str, priority: str = "P4", routed_to: list | None = None,
                       action: str = "", draft_reply: str = "") -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}email_triage (account, message_id, from_addr, subject, snippet, "
            f"priority, routed_to, action, draft_reply) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            f"ON CONFLICT (message_id) DO UPDATE SET "
            f"priority = EXCLUDED.priority, routed_to = EXCLUDED.routed_to, "
            f"action = EXCLUDED.action, draft_reply = EXCLUDED.draft_reply, triaged_at = NOW() "
            f"RETURNING id",
            (account, message_id, from_addr, subject, snippet, priority,
             routed_to or [], action, draft_reply),
        )
        return cur.fetchone()[0]


def get_triaged_emails(priority: str | None = None, account: str | None = None,
                       archived: bool | None = None, limit: int = 100) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        conditions, params = [], []
        if priority:
            conditions.append("priority = %s")
            params.append(priority)
        if account:
            conditions.append("account = %s")
            params.append(account)
        if archived is not None:
            conditions.append("archived = %s")
            params.append(archived)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        cur.execute(
            f"SELECT * FROM {P}email_triage {where} "
            f"ORDER BY CASE priority WHEN 'P1' THEN 0 WHEN 'P2' THEN 1 WHEN 'P3' THEN 2 ELSE 3 END, "
            f"triaged_at DESC LIMIT %s", params
        )
        return cur.fetchall()


def mark_email_archived(triage_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE {P}email_triage SET archived = TRUE WHERE id = %s", (triage_id,))


def batch_archive_emails(triage_ids: list[int]) -> int:
    if not triage_ids:
        return 0
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {P}email_triage SET archived = TRUE WHERE id = ANY(%s) RETURNING id",
            (triage_ids,),
        )
        return cur.rowcount


# ── Actions ─────────────────────────────────────────────────────────────────

def create_action(agent_name: str, action_type: str, title: str,
                  description: str = "", payload: dict | None = None,
                  mission_id: int | None = None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}actions (agent_name, action_type, title, description, payload, mission_id) "
            f"VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (agent_name, action_type, title, description, json.dumps(payload or {}), mission_id),
        )
        return cur.fetchone()[0]


def get_actions(status: str | None = None, agent: str | None = None,
                limit: int = 50) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        conditions, params = [], []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if agent:
            conditions.append("agent_name = %s")
            params.append(agent)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        cur.execute(
            f"SELECT * FROM {P}actions {where} ORDER BY created_at DESC LIMIT %s", params
        )
        return cur.fetchall()


def get_action(action_id: int) -> dict | None:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {P}actions WHERE id = %s", (action_id,))
        return cur.fetchone()


def update_action_status(action_id: int, status: str, result: str = ""):
    with get_conn() as conn, conn.cursor() as cur:
        if status in ("approved", "rejected", "completed", "failed"):
            cur.execute(
                f"UPDATE {P}actions SET status = %s, result = %s, resolved_at = NOW() WHERE id = %s",
                (status, result, action_id),
            )
        else:
            cur.execute(
                f"UPDATE {P}actions SET status = %s WHERE id = %s",
                (status, action_id),
            )


# ── Projects ───────────────────────────────────────────────────────────────

def create_project(title: str, brief: str = "", start_date: str | None = None,
                   target_date: str | None = None, color: str = "#38bdf8") -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}projects (title, brief, start_date, target_date, color) "
            f"VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (title, brief, start_date, target_date, color),
        )
        return cur.fetchone()[0]


def get_projects(status: str | None = None) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if status:
            cur.execute(f"SELECT * FROM {P}projects WHERE status = %s ORDER BY created_at", (status,))
        else:
            cur.execute(f"SELECT * FROM {P}projects ORDER BY created_at")
        return cur.fetchall()


def get_project_with_missions(project_id: int) -> dict | None:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {P}projects WHERE id = %s", (project_id,))
        proj = cur.fetchone()
        if not proj:
            return None
        cur.execute(
            f"SELECT m.*, (SELECT COUNT(*) FROM {P}files f WHERE f.mission_id = m.id) as file_count "
            f"FROM {P}missions m WHERE m.project_id = %s "
            f"ORDER BY CASE WHEN m.start_date IS NOT NULL THEN m.start_date ELSE m.created_at::date END",
            (project_id,),
        )
        proj = dict(proj)
        proj["missions"] = [dict(m) for m in cur.fetchall()]
        return proj


def update_project(project_id: int, **kwargs):
    with get_conn() as conn, conn.cursor() as cur:
        sets = ["updated_at = NOW()"]
        params = []
        for k, v in kwargs.items():
            if k in ("title", "brief", "status", "start_date", "target_date", "color"):
                sets.append(f"{k} = %s")
                params.append(v)
        params.append(project_id)
        cur.execute(f"UPDATE {P}projects SET {', '.join(sets)} WHERE id = %s", params)


def link_mission_to_project(mission_id: int, project_id: int,
                            start_date: str | None = None, end_date: str | None = None,
                            depends_on: list | None = None):
    with get_conn() as conn, conn.cursor() as cur:
        sets = ["project_id = %s"]
        params = [project_id]
        if start_date:
            sets.append("start_date = %s")
            params.append(start_date)
        if end_date:
            sets.append("end_date = %s")
            params.append(end_date)
        if depends_on is not None:
            sets.append("depends_on = %s")
            params.append(depends_on)
        params.append(mission_id)
        cur.execute(f"UPDATE {P}missions SET {', '.join(sets)} WHERE id = %s", params)


# ── Deals ───────────────────────────────────────────────────────────────────

def create_deal(title: str, deal_type: str = "acquisition", stage: str = "lead",
                value: float = 0, contact: str = "", source: str = "",
                location: str = "", next_action: str = "", deadline: str | None = None,
                score: int = 0, notes: str = "", assigned_agent: str = "wakil") -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}deals (title, deal_type, stage, value, contact, source, location, "
            f"next_action, deadline, score, notes, assigned_agent) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (title, deal_type, stage, value, contact, source, location,
             next_action, deadline, score, notes, assigned_agent),
        )
        return cur.fetchone()[0]


def get_deals(stage: str | None = None, limit: int = 50) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if stage:
            cur.execute(f"SELECT * FROM {P}deals WHERE stage = %s ORDER BY score DESC, updated_at DESC LIMIT %s", (stage, limit))
        else:
            cur.execute(f"SELECT * FROM {P}deals ORDER BY CASE stage "
                       f"WHEN 'lead' THEN 0 WHEN 'researching' THEN 1 WHEN 'evaluating' THEN 2 "
                       f"WHEN 'loi' THEN 3 WHEN 'due_diligence' THEN 4 WHEN 'closing' THEN 5 "
                       f"WHEN 'closed' THEN 6 ELSE 7 END, score DESC LIMIT %s", (limit,))
        return cur.fetchall()


def update_deal(deal_id: int, **kwargs):
    with get_conn() as conn, conn.cursor() as cur:
        sets = ["updated_at = NOW()"]
        params = []
        for k, v in kwargs.items():
            if k in ("title", "deal_type", "stage", "value", "contact", "source",
                     "location", "next_action", "deadline", "score", "notes", "assigned_agent"):
                sets.append(f"{k} = %s")
                params.append(v)
        params.append(deal_id)
        cur.execute(f"UPDATE {P}deals SET {', '.join(sets)} WHERE id = %s", params)


# ── Alert Rules ─────────────────────────────────────────────────────────────

def create_alert_rule(name: str, metric: str, condition: str, threshold: float,
                      message_template: str) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}alert_rules (name, metric, condition, threshold, message_template) "
            f"VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (name, metric, condition, threshold, message_template),
        )
        return cur.fetchone()[0]


def get_alert_rules(enabled_only: bool = False) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if enabled_only:
            cur.execute(f"SELECT * FROM {P}alert_rules WHERE enabled = TRUE ORDER BY created_at")
        else:
            cur.execute(f"SELECT * FROM {P}alert_rules ORDER BY created_at")
        return cur.fetchall()


def update_alert_rule(rule_id: int, **kwargs):
    with get_conn() as conn, conn.cursor() as cur:
        sets, params = [], []
        for k, v in kwargs.items():
            if k in ("name", "metric", "condition", "threshold", "message_template", "enabled", "last_triggered"):
                sets.append(f"{k} = %s")
                params.append(v)
        if not sets:
            return
        params.append(rule_id)
        cur.execute(f"UPDATE {P}alert_rules SET {', '.join(sets)} WHERE id = %s", params)


# ── Scheduled Tasks ─────────────────────────────────────────────────────────

def create_scheduled_task(name: str, cron_expression: str, prompt: str,
                          agent_name: str = "shams") -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}scheduled_tasks (name, cron_expression, prompt, agent_name) "
            f"VALUES (%s, %s, %s, %s) RETURNING id",
            (name, cron_expression, prompt, agent_name),
        )
        return cur.fetchone()[0]


def get_scheduled_tasks(enabled_only: bool = False) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if enabled_only:
            cur.execute(f"SELECT * FROM {P}scheduled_tasks WHERE enabled = TRUE ORDER BY created_at")
        else:
            cur.execute(f"SELECT * FROM {P}scheduled_tasks ORDER BY created_at")
        return cur.fetchall()


def update_scheduled_task(task_id: int, **kwargs):
    with get_conn() as conn, conn.cursor() as cur:
        sets, params = [], []
        for k, v in kwargs.items():
            if k in ("name", "cron_expression", "prompt", "agent_name", "enabled"):
                sets.append(f"{k} = %s")
                params.append(v)
        if not sets:
            return
        params.append(task_id)
        cur.execute(f"UPDATE {P}scheduled_tasks SET {', '.join(sets)} WHERE id = %s", params)


def delete_scheduled_task(task_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"DELETE FROM {P}scheduled_tasks WHERE id = %s", (task_id,))


def mark_task_run(task_id: int, result: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {P}scheduled_tasks SET last_run_at = NOW(), last_result = %s WHERE id = %s",
            (result[:2000], task_id),
        )


# ── Workflows ──────────────────────────────────────────────────────────────

def create_workflow(title: str, description: str, steps: list[dict],
                    mission_id: int | None = None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}workflows (title, description, mission_id) "
            f"VALUES (%s, %s, %s) RETURNING id",
            (title, description, mission_id),
        )
        workflow_id = cur.fetchone()[0]
        for i, step in enumerate(steps, 1):
            cur.execute(
                f"INSERT INTO {P}workflow_steps (workflow_id, step_number, agent_name, instruction, requires_approval) "
                f"VALUES (%s, %s, %s, %s, %s)",
                (workflow_id, i, step["agent_name"], step["instruction"],
                 step.get("requires_approval", False)),
            )
        return workflow_id


def get_workflow(workflow_id: int) -> dict | None:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {P}workflows WHERE id = %s", (workflow_id,))
        wf = cur.fetchone()
        if not wf:
            return None
        cur.execute(
            f"SELECT * FROM {P}workflow_steps WHERE workflow_id = %s ORDER BY step_number",
            (workflow_id,)
        )
        wf = dict(wf)
        wf["steps"] = [dict(s) for s in cur.fetchall()]
        return wf


def get_workflows(status: str | None = None) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if status:
            cur.execute(f"SELECT * FROM {P}workflows WHERE status = %s ORDER BY created_at DESC", (status,))
        else:
            cur.execute(f"SELECT * FROM {P}workflows ORDER BY created_at DESC LIMIT 50")
        return [dict(r) for r in cur.fetchall()]


def get_active_workflow_step(workflow_id: int) -> dict | None:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT * FROM {P}workflow_steps WHERE workflow_id = %s AND status = 'pending' "
            f"ORDER BY step_number LIMIT 1", (workflow_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def advance_workflow_step(workflow_id: int, step_number: int, result: str):
    with get_conn() as conn, conn.cursor() as cur:
        # Mark current step complete
        cur.execute(
            f"UPDATE {P}workflow_steps SET status = 'completed', output_result = %s, completed_at = NOW() "
            f"WHERE workflow_id = %s AND step_number = %s",
            (result, workflow_id, step_number),
        )
        # Set next step's input_context to this result
        cur.execute(
            f"UPDATE {P}workflow_steps SET input_context = %s "
            f"WHERE workflow_id = %s AND step_number = %s",
            (result, workflow_id, step_number + 1),
        )
        # Update workflow current_step
        cur.execute(
            f"UPDATE {P}workflows SET current_step = %s, updated_at = NOW() WHERE id = %s",
            (step_number + 1, workflow_id),
        )
        # Check if there are more steps
        cur.execute(
            f"SELECT COUNT(*) FROM {P}workflow_steps WHERE workflow_id = %s AND step_number > %s",
            (workflow_id, step_number),
        )
        remaining = cur.fetchone()[0]
        if remaining == 0:
            cur.execute(
                f"UPDATE {P}workflows SET status = 'completed', updated_at = NOW() WHERE id = %s",
                (workflow_id,),
            )


def update_workflow_status(workflow_id: int, status: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {P}workflows SET status = %s, updated_at = NOW() WHERE id = %s",
            (status, workflow_id),
        )


def start_workflow_step(workflow_id: int, step_number: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {P}workflow_steps SET status = 'active', started_at = NOW() "
            f"WHERE workflow_id = %s AND step_number = %s",
            (workflow_id, step_number),
        )


# ── Action Helpers ──────────────────────────────────────────────────────────

def get_actions_for_mission(mission_id: int) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT * FROM {P}actions WHERE mission_id = %s ORDER BY created_at", (mission_id,)
        )
        return cur.fetchall()


# ── Trust Scores ────────────────────────────────────────────────────────────

def get_trust_score(agent_name: str) -> dict | None:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {P}trust_scores WHERE agent_name = %s", (agent_name,))
        return cur.fetchone()


def get_all_trust_scores() -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {P}trust_scores ORDER BY agent_name")
        return cur.fetchall()


def increment_trust(agent_name: str, field: str):
    """Increment total_proposed, total_approved, or total_rejected."""
    if field not in ("total_proposed", "total_approved", "total_rejected"):
        return
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}trust_scores (agent_name, {field}) VALUES (%s, 1) "
            f"ON CONFLICT (agent_name) DO UPDATE SET {field} = {P}trust_scores.{field} + 1, "
            f"updated_at = NOW()",
            (agent_name,),
        )


def set_auto_approve(agent_name: str, enabled: bool):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}trust_scores (agent_name, auto_approve) VALUES (%s, %s) "
            f"ON CONFLICT (agent_name) DO UPDATE SET auto_approve = %s, updated_at = NOW()",
            (agent_name, enabled, enabled),
        )


def should_auto_approve(agent_name: str) -> bool:
    """Check if an agent's actions should be auto-approved."""
    trust = get_trust_score(agent_name)
    if not trust:
        return False
    return trust["auto_approve"]


# ── Schema bootstrap ─────────────────────────────────────────────────────────

def ensure_tables():
    """Run schema.sql to create tables if they don't exist."""
    from pathlib import Path
    schema_path = Path(__file__).parent / "schema.sql"
    if schema_path.exists():
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(schema_path.read_text())


# ── Overnight Runs ─────────────────────────────────────────────────────────

def create_overnight_run() -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}overnight_runs (status) VALUES ('running') RETURNING id"
        )
        return cur.fetchone()[0]


def update_overnight_run(run_id: int, status: str = "completed",
                         results: dict | None = None, summary: str = ""):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {P}overnight_runs SET status = %s, results = %s, summary = %s, "
            f"finished_at = NOW() WHERE id = %s",
            (status, json.dumps(results or {}), summary, run_id),
        )


def get_latest_overnight_run() -> dict | None:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT * FROM {P}overnight_runs ORDER BY started_at DESC LIMIT 1"
        )
        return cur.fetchone()


# ── Standup State ──────────────────────────────────────────────────────────

def get_standup_state() -> dict | None:
    raw = recall("standup_state")
    if not raw:
        return None
    return json.loads(raw)


def set_standup_state(state: dict):
    remember("standup_state", json.dumps(state))


def clear_standup_state():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"DELETE FROM {P}memory WHERE key = 'standup_state'")
