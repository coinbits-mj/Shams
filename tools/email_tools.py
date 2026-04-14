# tools/email_tools.py
"""Claude tools for querying Shams's email archive + routed tables."""
from __future__ import annotations

import logging

import db
from tools.registry import tool

log = logging.getLogger(__name__)


@tool(
    name="search_email_archive",
    description="Search Shams's full email archive across all connected Gmail accounts. Supports free-text search on body/subject plus optional filters.",
    agent=None,
    schema={
        "properties": {
            "query": {"type": "string", "description": "Free-text query (matches body and subject)"},
            "account": {"type": "string", "enum": ["personal", "coinbits", "qcc"], "description": "Limit to one account"},
            "category": {"type": "string", "description": "Filter by category (e.g. 'invoice')"},
            "from_addr": {"type": "string", "description": "Filter by sender email"},
            "since": {"type": "string", "description": "ISO date, return emails on/after this date"},
            "limit": {"type": "integer", "description": "Max rows (default 20, max 100)"},
        },
        "required": [],
    },
)
def search_email_archive(
    query: str = "",
    account: str = "",
    category: str = "",
    from_addr: str = "",
    since: str = "",
    limit: int = 20,
) -> str:
    limit = max(1, min(int(limit or 20), 100))
    sql = ["SELECT id, account, date, from_addr, subject, category, priority FROM shams_email_archive WHERE 1=1"]
    params: list = []

    if query:
        sql.append("AND (to_tsvector('english', coalesce(body,'')) @@ plainto_tsquery('english', %s) OR subject ILIKE %s)")
        params.extend([query, f"%{query}%"])
    if account:
        sql.append("AND account = %s")
        params.append(account)
    if category:
        sql.append("AND category = %s")
        params.append(category)
    if from_addr:
        sql.append("AND from_addr ILIKE %s")
        params.append(f"%{from_addr}%")
    if since:
        sql.append("AND date >= %s")
        params.append(since)

    sql.append("ORDER BY date DESC LIMIT %s")
    params.append(limit)

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(" ".join(sql), params)
            rows = cur.fetchall()

    if not rows:
        return "No emails match those filters."
    lines = [f"Found {len(rows)} email(s):"]
    for id_, acct, date, fa, subj, cat, prio in rows:
        lines.append(f"  #{id_} [{acct} {prio} {cat}] {date} — {fa} — {subj}")
    return "\n".join(lines)


@tool(
    name="get_ap_summary",
    description="Summarize Shams's AP queue (invoices extracted from email). Filter by status, vendor, min amount.",
    agent=None,
    schema={
        "properties": {
            "status": {"type": "string", "enum": ["unpaid", "paid", "disputed", "ignored"], "description": "Filter"},
            "vendor": {"type": "string", "description": "Filter by vendor name (partial match)"},
            "min_amount_cents": {"type": "integer", "description": "Only invoices >= this amount"},
            "limit": {"type": "integer", "description": "Max rows (default 25, max 200)"},
        },
        "required": [],
    },
)
def get_ap_summary(status: str = "", vendor: str = "", min_amount_cents: int = 0, limit: int = 25) -> str:
    limit = max(1, min(int(limit or 25), 200))
    sql = [
        "SELECT id, vendor, amount_cents, currency, invoice_number, due_date, status",
        "FROM shams_ap_queue WHERE 1=1",
    ]
    params: list = []
    if status:
        sql.append("AND status = %s")
        params.append(status)
    if vendor:
        sql.append("AND vendor ILIKE %s")
        params.append(f"%{vendor}%")
    if min_amount_cents:
        sql.append("AND amount_cents >= %s")
        params.append(int(min_amount_cents))
    sql.append("ORDER BY due_date ASC NULLS LAST, amount_cents DESC LIMIT %s")
    params.append(limit)

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(" ".join(sql), params)
            rows = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount_cents),0) FROM shams_ap_queue WHERE status='unpaid'"
            )
            unpaid_count, unpaid_total = cur.fetchone()

    header = f"AP queue: {unpaid_count} unpaid totaling ${unpaid_total/100:,.2f}."
    if not rows:
        return header + "\n(no rows match current filter)"
    lines = [header, ""]
    for id_, v, amt, cur_, inv, due, st in rows:
        amt_str = f"${(amt or 0)/100:,.2f} {cur_}"
        due_str = str(due) if due else "no due date"
        lines.append(f"  #{id_} {st:8s} {amt_str:>15s} — {v or '?'} — inv {inv or '?'} — due {due_str}")
    return "\n".join(lines)


@tool(
    name="get_cx_summary",
    description="Summarize Shams's customer complaint log. Filter by status or severity.",
    agent=None,
    schema={
        "properties": {
            "status": {"type": "string", "enum": ["open", "resolved"], "description": "Filter"},
            "severity": {"type": "string", "enum": ["low", "med", "high"], "description": "Filter"},
            "limit": {"type": "integer", "description": "Max rows (default 25, max 100)"},
        },
        "required": [],
    },
)
def get_cx_summary(status: str = "", severity: str = "", limit: int = 25) -> str:
    limit = max(1, min(int(limit or 25), 100))
    sql = [
        "SELECT id, customer_email, customer_name, issue_summary, severity, status, created_at",
        "FROM shams_cx_log WHERE 1=1",
    ]
    params: list = []
    if status:
        sql.append("AND status = %s")
        params.append(status)
    if severity:
        sql.append("AND severity = %s")
        params.append(severity)
    sql.append("ORDER BY created_at DESC LIMIT %s")
    params.append(limit)

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(" ".join(sql), params)
            rows = cur.fetchall()

    if not rows:
        return "No CX entries match."
    lines = [f"CX log ({len(rows)} rows):"]
    for id_, ce, cn, iss, sev, st, ts in rows:
        lines.append(f"  #{id_} [{st} {sev or '?'}] {ts} — {cn or ce or '?'}: {(iss or '')[:100]}")
    return "\n".join(lines)
