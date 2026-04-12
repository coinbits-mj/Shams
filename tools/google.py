"""Google (Gmail) tools."""
from __future__ import annotations

from tools.registry import tool


@tool(
    name="triage_inbox",
    description="Triage Maher's email inbox. Fetches unread emails, classifies by priority (P1 act now, P2 today, P3 this week, P4 archive), and provides recommended actions + draft replies for important ones. Use this when Maher asks about email, inbox, or 'what needs my attention'.",
    schema={
        "properties": {
            "max_emails": {"type": "integer", "description": "How many unread emails to process (default 10)", "default": 10}
        },
    },
)
def triage_inbox(max_emails: int = 10) -> str:
    import pathlib
    import anthropic
    import google_client
    import memory
    from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

    emails = google_client.get_unread_emails(max_emails)
    if not emails:
        return "No unread emails (or Gmail not connected — check Integrations page)."

    context_dir = pathlib.Path(__file__).parent.parent / "context"
    inbox_persona_path = context_dir / "inbox_persona.md"
    inbox_persona = inbox_persona_path.read_text() if inbox_persona_path.exists() else ""

    email_text = "\n\n".join(
        f"Account: {e.get('account', 'unknown')} ({e.get('account_email', '')})\nFrom: {e['from']}\nSubject: {e['subject']}\nSnippet: {e['snippet']}\nDate: {e['date']}"
        for e in emails
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    triage_response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system=inbox_persona if inbox_persona else "Triage these emails by priority.",
        messages=[{"role": "user", "content": f"Triage these {len(emails)} emails:\n\n{email_text}"}],
    )
    result = triage_response.content[0].text

    # Route triaged emails to agent queues in memory
    for agent in ["wakil", "rumi", "leo", "scout"]:
        if agent in result.lower():
            lines = [l for l in result.split("\n") if agent in l.lower()]
            if lines:
                memory.remember(f"inbox_{agent}_queue", "\n".join(lines[:5]))

    return result


@tool(
    name="search_email",
    description="Search Maher's email across all connected accounts (personal, coinbits, qcc). Finds read and unread emails. Use Gmail search syntax: 'from:name', 'subject:topic', 'after:2026/01/01', etc. Use this when Maher asks about specific emails, conversations, or communications.",
    schema={
        "properties": {
            "query": {"type": "string", "description": "Gmail search query (e.g. 'from:seward subject:settlement', 'from:richard red house')"},
            "max_results": {"type": "integer", "description": "Max emails to return (default 10)", "default": 10},
        },
        "required": ["query"],
    },
)
def search_email(query: str, max_results: int = 10) -> str:
    import google_client

    results = google_client.search_emails(query, max_results)
    if not results:
        return "No emails found matching that search."
    output = f"Found {len(results)} email(s):\n\n"
    for e in results:
        output += f"Account: {e['account']} ({e['account_email']})\n"
        output += f"From: {e['from']}\nSubject: {e['subject']}\nDate: {e['date']}\n"
        output += f"Snippet: {e['snippet']}\nMessage ID: {e['message_id']}\n\n---\n\n"
    return output


@tool(
    name="read_email",
    description="Read the full body of a specific email. Use this after search_email to get the complete text of an important email.",
    schema={
        "properties": {
            "account": {"type": "string", "description": "Account key from search results", "enum": ["personal", "coinbits", "qcc"]},
            "message_id": {"type": "string", "description": "Gmail message ID from search results"},
        },
        "required": ["account", "message_id"],
    },
)
def read_email(account: str, message_id: str) -> str:
    import google_client

    return google_client.get_email_body(account, message_id)
