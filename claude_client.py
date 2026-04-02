"""Claude API wrapper with memory injection and tool use."""

from __future__ import annotations

import json
import logging
import pathlib
import anthropic
import config
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
import memory

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_CONTEXT_DIR = pathlib.Path(__file__).parent / "context"


def _load_context_file(filename: str) -> str:
    path = _CONTEXT_DIR / filename
    if path.exists():
        return path.read_text()
    return ""


# Load the full Shams founding document + knowledge base at import time
SYSTEM_PROMPT = _load_context_file("shams_system_prompt.md")

_KNOWLEDGE_FILES = [
    "shams_knowledge_qcc_overview.md",
    "shams_knowledge_active_deals.md",
    "shams_knowledge_personal.md",
]
KNOWLEDGE_BASE = "\n\n---\n\n".join(
    _load_context_file(f) for f in _KNOWLEDGE_FILES if _load_context_file(f)
)


# ── Tool definitions ─────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "web_search",
        "description": "Search the internet for current information. Use this for researching companies, market data, news, real estate listings, competitor intelligence, or any question that needs up-to-date information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch and read the content of a specific URL. Use this to read articles, company websites, property listings, or any web page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "get_mercury_balances",
        "description": "Get current Mercury bank account balances across all entities — Clifton, Plainfield (café + production/wholesale), and Personal. Each API key may have multiple sub-accounts (checking, credit card, savings).",
        "input_schema": {
            "type": "object",
            "properties": {
                "account": {"type": "string", "description": "Optional: 'clifton', 'plainfield', or 'personal'. Omit for all accounts.", "enum": ["clifton", "plainfield", "personal", "coinbits"]}
            },
        },
    },
    {
        "name": "get_mercury_transactions",
        "description": "Get recent Mercury bank transactions. Can filter by entity (clifton, plainfield, personal) or show all.",
        "input_schema": {
            "type": "object",
            "properties": {
                "account": {"type": "string", "description": "Optional: 'clifton', 'plainfield', or 'personal'. Omit for all.", "enum": ["clifton", "plainfield", "personal", "coinbits"]},
                "days": {"type": "integer", "description": "Number of days to look back (default 7)", "default": 7}
            },
        },
    },
    {
        "name": "get_mercury_cash_summary",
        "description": "Get a formatted cash summary across all Mercury accounts (Clifton, Plainfield café + production, Personal) including balances and recent transactions.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_rumi_daily_pl",
        "description": "Get yesterday's P&L from Rumi (QCC's operations platform). Includes revenue, COGS, labor, overhead, net margin.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format, or 'yesterday'", "default": "yesterday"}
            },
        },
    },
    {
        "name": "get_rumi_monthly_pl",
        "description": "Get month-to-date P&L from Rumi.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_rumi_scorecard",
        "description": "Get the QCC location health scorecard from Rumi.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_rumi_action_items",
        "description": "Get today's action items and alerts from Rumi.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_rumi_cashflow_forecast",
        "description": "Get cash flow forecast from Rumi (30/60/90 day projections).",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_rumi_labor",
        "description": "Get labor analysis from Rumi — costs by hour, daypart, employee.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_rumi_inventory_alerts",
        "description": "Get inventory alerts from Rumi — low stock, reorder needed.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_leo_health_summary",
        "description": "Get Maher's latest health data from Leo — weight, sleep, HRV, readiness, glucose, calories, steps, streak, today's meals.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_leo_trends",
        "description": "Get Maher's 7-day health trends from Leo — daily weight, sleep, HRV, calories, steps.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "triage_inbox",
        "description": "Triage Maher's email inbox. Fetches unread emails, classifies by priority (P1 act now, P2 today, P3 this week, P4 archive), and provides recommended actions + draft replies for important ones. Use this when Maher asks about email, inbox, or 'what needs my attention'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_emails": {"type": "integer", "description": "How many unread emails to process (default 10)", "default": 10}
            },
        },
    },
    {
        "name": "search_email",
        "description": "Search Maher's email across all connected accounts (personal, coinbits, qcc). Finds read and unread emails. Use Gmail search syntax: 'from:name', 'subject:topic', 'after:2026/01/01', etc. Use this when Maher asks about specific emails, conversations, or communications.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query (e.g. 'from:seward subject:settlement', 'from:richard red house')"},
                "max_results": {"type": "integer", "description": "Max emails to return (default 10)", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_email",
        "description": "Read the full body of a specific email. Use this after search_email to get the complete text of an important email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "account": {"type": "string", "description": "Account key from search results", "enum": ["personal", "coinbits", "qcc"]},
                "message_id": {"type": "string", "description": "Gmail message ID from search results"},
            },
            "required": ["account", "message_id"],
        },
    },
    {
        "name": "read_codebase",
        "description": "Read a file from any of Maher's codebases (shams, rumi, leo). Use this to understand how something works, review code, or help Builder plan changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Which repo: 'shams', 'rumi', or 'leo'", "enum": ["shams", "rumi", "leo"]},
                "filepath": {"type": "string", "description": "Path to the file, e.g. 'app.py' or 'engine/pl_engine.py'"},
            },
            "required": ["repo", "filepath"],
        },
    },
    {
        "name": "search_codebase",
        "description": "Search for a string across a codebase. Returns matching files and lines.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Which repo: 'shams', 'rumi', or 'leo'", "enum": ["shams", "rumi", "leo"]},
                "query": {"type": "string", "description": "Search string"},
            },
            "required": ["repo", "query"],
        },
    },
    {
        "name": "list_codebase_files",
        "description": "List files in a codebase directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Which repo: 'shams', 'rumi', or 'leo'", "enum": ["shams", "rumi", "leo"]},
                "path": {"type": "string", "description": "Directory path (e.g. 'engine/' or ''  for root)", "default": ""},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "get_repo_structure",
        "description": "Get a tree view of an entire codebase structure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Which repo: 'shams', 'rumi', or 'leo'", "enum": ["shams", "rumi", "leo"]},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "create_mission",
        "description": "Create a new mission (task/project) for an agent to work on. Use this when Maher mentions a task, project, or follow-up that should be tracked. Assign to the right agent based on domain.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short mission title"},
                "description": {"type": "string", "description": "What needs to be done"},
                "priority": {"type": "string", "enum": ["urgent", "high", "normal", "low"], "default": "normal"},
                "assigned_agent": {"type": "string", "description": "Agent to assign: shams, rumi, leo, wakil, scout, builder"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_mission",
        "description": "Update the status or result of an existing mission. Use this when a mission progresses, gets blocked, or is completed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mission_id": {"type": "integer", "description": "The mission ID to update"},
                "status": {"type": "string", "enum": ["inbox", "assigned", "active", "review", "done", "dropped"]},
                "result": {"type": "string", "description": "Result or outcome when completing a mission"},
            },
            "required": ["mission_id"],
        },
    },
    {
        "name": "propose_action",
        "description": "Propose an action for Maher to approve before execution. Use this when you want to take an action that affects the real world — archiving emails, creating PRs, sending messages, drafting documents, etc. The action will appear in the dashboard for approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "description": "Type of action",
                    "enum": ["archive_email", "send_message", "create_pr", "draft_document", "research", "schedule_meeting", "other"]
                },
                "title": {"type": "string", "description": "Short title describing the action (e.g. 'Archive 12 promotional emails')"},
                "description": {"type": "string", "description": "Detailed description of what will happen if approved"},
                "payload": {
                    "type": "object",
                    "description": "Action-specific data (email IDs, code diff, message content, etc.)"
                }
            },
            "required": ["action_type", "title"],
        },
    },
    {
        "name": "draft_legal_document",
        "description": "Have Wakil draft a legal document. Creates the document and saves it to Files. Use for LOIs, NDAs, term sheets, legal memos, employment letters, counter-proposals, or any legal document.",
        "input_schema": {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string",
                    "enum": ["loi", "nda", "term_sheet", "legal_memo", "employment_letter", "counter_proposal", "contract", "other"],
                    "description": "Type of legal document",
                },
                "title": {"type": "string", "description": "Document title"},
                "instructions": {"type": "string", "description": "What the document should cover — parties, terms, key provisions, context"},
                "context": {"type": "string", "description": "Relevant background (deal details, prior negotiations, etc.)"},
                "mission_id": {"type": "integer", "description": "Optional mission ID this document relates to"},
            },
            "required": ["document_type", "title", "instructions"],
        },
    },
    {
        "name": "assign_research",
        "description": "Assign a research task to Scout. Scout will search the web, compile findings, and report back. Creates a mission assigned to Scout.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to research"},
                "depth": {"type": "string", "enum": ["quick", "deep"], "default": "quick",
                          "description": "Quick = surface-level search, Deep = multiple queries and source analysis"},
                "deadline": {"type": "string", "description": "When results are needed (e.g. 'today', 'this week')"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "propose_code_change",
        "description": "Propose a code change to one of Maher's repos. Creates a GitHub PR for review after approval. Use this when Builder plans a fix, feature, or refactor.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Which repo", "enum": ["shams", "rumi", "leo"]},
                "title": {"type": "string", "description": "PR title describing the change"},
                "description": {"type": "string", "description": "What this change does and why"},
                "files": {
                    "type": "array",
                    "description": "Files to create or update",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path in the repo"},
                            "content": {"type": "string", "description": "Full file content"},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            "required": ["repo", "title", "files"],
        },
    },
    {
        "name": "create_deal",
        "description": "Add a new deal/opportunity to the pipeline. Use when Scout finds an acquisition target, real estate listing, partnership opportunity, or any money-making prospect.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Deal title (e.g. 'Red House Roasters Acquisition')"},
                "deal_type": {"type": "string", "enum": ["acquisition", "real_estate", "partnership", "investment", "vendor", "other"]},
                "value": {"type": "number", "description": "Estimated deal value in dollars"},
                "contact": {"type": "string", "description": "Key contact person"},
                "source": {"type": "string", "description": "How we found this (Scout research, email, referral, etc.)"},
                "location": {"type": "string", "description": "Physical location if applicable"},
                "next_action": {"type": "string", "description": "Next step to take"},
                "score": {"type": "integer", "description": "Opportunity score 1-10 (10 = best)"},
                "notes": {"type": "string", "description": "Additional context"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_deal",
        "description": "Update a deal's stage, score, next action, or other details. Use to advance deals through the pipeline.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deal_id": {"type": "integer"},
                "stage": {"type": "string", "enum": ["lead", "researching", "evaluating", "loi", "due_diligence", "closing", "closed", "dead"]},
                "value": {"type": "number"},
                "next_action": {"type": "string"},
                "score": {"type": "integer"},
                "notes": {"type": "string"},
            },
            "required": ["deal_id"],
        },
    },
    {
        "name": "schedule_task",
        "description": "Create a recurring scheduled task. Use when Maher says 'every Monday...', 'from now on...', 'daily at 8am...', etc. Creates a persistent job that runs automatically on schedule.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short name for this task"},
                "cron_expression": {"type": "string", "description": "Cron expression in UTC (e.g. '0 14 * * 1' for Monday 9am ET / 2pm UTC, '0 12 * * 1-5' for weekdays 7am ET)"},
                "prompt": {"type": "string", "description": "The instruction to execute each run"},
            },
            "required": ["name", "cron_expression", "prompt"],
        },
    },
    {
        "name": "list_scheduled_tasks",
        "description": "List all scheduled recurring tasks.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_scheduled_task",
        "description": "Cancel/disable a scheduled task by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "ID of the task to cancel"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "create_workflow",
        "description": "Create a multi-step workflow that chains agents together. Each step runs in sequence — the output of one step feeds into the next agent. Use for complex requests needing multiple agents (e.g. research → draft → review).",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Workflow title"},
                "description": {"type": "string", "description": "What this workflow accomplishes"},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "agent_name": {"type": "string", "enum": ["shams", "rumi", "leo", "wakil", "scout", "builder"]},
                            "instruction": {"type": "string", "description": "What this agent should do in this step"},
                            "requires_approval": {"type": "boolean"},
                        },
                        "required": ["agent_name", "instruction"],
                    },
                },
            },
            "required": ["title", "steps"],
        },
    },
    {
        "name": "route_to_agent",
        "description": "Send a message to a specific agent with optional context from a previous action. The agent responds with their expertise. Use to delegate work or get a specialist's input.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_agent": {"type": "string", "enum": ["shams", "rumi", "leo", "wakil", "scout", "builder"]},
                "message": {"type": "string", "description": "What you need from this agent"},
                "context_from_action_id": {"type": "integer", "description": "Optional: action ID whose result to include as context"},
            },
            "required": ["target_agent", "message"],
        },
    },
    {
        "name": "remember",
        "description": "Save a piece of information to persistent memory. Use this when Maher tells you something important to remember, or when you learn something that should persist across conversations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Short key/label for the memory"},
                "value": {"type": "string", "description": "The information to remember"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "add_open_loop",
        "description": "Track a new open loop — something that needs follow-up or resolution. Use this when Maher mentions something pending, a task to do, or a decision to make.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the open loop"},
                "context": {"type": "string", "description": "Additional context"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "close_open_loop",
        "description": "Close an open loop that has been resolved.",
        "input_schema": {
            "type": "object",
            "properties": {
                "loop_id": {"type": "integer", "description": "The ID of the loop to close"},
                "status": {"type": "string", "description": "'done' or 'dropped'", "default": "done"},
            },
            "required": ["loop_id"],
        },
    },
    {
        "name": "log_decision",
        "description": "Log a decision that was made. Use this when Maher makes a significant business or personal decision worth tracking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What was decided"},
                "reasoning": {"type": "string", "description": "Why"},
                "outcome": {"type": "string", "description": "Expected outcome"},
            },
            "required": ["summary"],
        },
    },
]


# ── Tool execution ───────────────────────────────────────────────────────────

def _execute_tool(name: str, input_data: dict) -> str:
    """Execute a tool and return the result as a string."""
    try:
        if name == "web_search":
            import web_search
            results = web_search.search_web(input_data["query"])
            return json.dumps(results, indent=2) if results else "No results found."

        elif name == "fetch_url":
            import web_search
            return web_search.fetch_url(input_data["url"])

        elif name == "get_mercury_balances":
            import mercury_client
            result = mercury_client.get_balances(input_data.get("account"))
            return json.dumps(result, indent=2) if result else "Mercury unavailable."

        elif name == "get_mercury_transactions":
            import mercury_client
            result = mercury_client.get_recent_transactions(input_data.get("account"), input_data.get("days", 7))
            return json.dumps(result, indent=2) if result else "Mercury unavailable."

        elif name == "get_mercury_cash_summary":
            import mercury_client
            return mercury_client.get_cash_summary()

        elif name == "get_rumi_daily_pl":
            import rumi_client
            result = rumi_client.get_daily_pl(input_data.get("date", "yesterday"))
            return json.dumps(result, indent=2) if result else "Rumi unavailable."

        elif name == "get_rumi_monthly_pl":
            import rumi_client
            result = rumi_client.get_monthly_pl()
            return json.dumps(result, indent=2) if result else "Rumi unavailable."

        elif name == "get_rumi_scorecard":
            import rumi_client
            result = rumi_client.get_scorecard()
            return json.dumps(result, indent=2) if result else "Rumi unavailable."

        elif name == "get_rumi_action_items":
            import rumi_client
            result = rumi_client.get_action_items()
            return json.dumps(result, indent=2) if result else "Rumi unavailable."

        elif name == "get_rumi_cashflow_forecast":
            import rumi_client
            result = rumi_client.get_cashflow_forecast()
            return json.dumps(result, indent=2) if result else "Rumi unavailable."

        elif name == "get_rumi_labor":
            import rumi_client
            result = rumi_client.get_labor_analysis()
            return json.dumps(result, indent=2) if result else "Rumi unavailable."

        elif name == "get_rumi_inventory_alerts":
            import rumi_client
            result = rumi_client.get_inventory_alerts()
            return json.dumps(result, indent=2) if result else "Rumi unavailable."

        elif name == "triage_inbox":
            import google_client
            max_emails = input_data.get("max_emails", 10)
            emails = google_client.get_unread_emails(max_emails)
            if not emails:
                return "No unread emails (or Gmail not connected — check Integrations page)."
            inbox_persona = _load_context_file("inbox_persona.md")
            email_text = "\n\n".join(
                f"Account: {e.get('account', 'unknown')} ({e.get('account_email', '')})\nFrom: {e['from']}\nSubject: {e['subject']}\nSnippet: {e['snippet']}\nDate: {e['date']}"
                for e in emails
            )
            triage_response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2048,
                system=inbox_persona if inbox_persona else "Triage these emails by priority.",
                messages=[{"role": "user", "content": f"Triage these {len(emails)} emails:\n\n{email_text}"}],
            )
            result = triage_response.content[0].text

            # Route triaged emails to agent queues in memory
            # Extract P1/P2 emails routed to specific agents
            for agent in ["wakil", "rumi", "leo", "scout"]:
                if agent in result.lower():
                    # Save the relevant portion so agents can access their queue
                    lines = [l for l in result.split("\n") if agent in l.lower()]
                    if lines:
                        memory.remember(f"inbox_{agent}_queue", "\n".join(lines[:5]))

            return result

        elif name == "search_email":
            import google_client
            results = google_client.search_emails(input_data["query"], input_data.get("max_results", 10))
            if not results:
                return "No emails found matching that search."
            output = f"Found {len(results)} email(s):\n\n"
            for e in results:
                output += f"Account: {e['account']} ({e['account_email']})\n"
                output += f"From: {e['from']}\nSubject: {e['subject']}\nDate: {e['date']}\n"
                output += f"Snippet: {e['snippet']}\nMessage ID: {e['message_id']}\n\n---\n\n"
            return output

        elif name == "read_email":
            import google_client
            body = google_client.get_email_body(input_data["account"], input_data["message_id"])
            return body

        elif name == "read_codebase":
            from agents.codebase import read_file
            return read_file(input_data["repo"], input_data["filepath"])

        elif name == "search_codebase":
            from agents.codebase import search_code
            results = search_code(input_data["repo"], input_data["query"])
            return json.dumps(results, indent=2) if results else "No matches found."

        elif name == "list_codebase_files":
            from agents.codebase import list_files
            files = list_files(input_data["repo"], input_data.get("path", ""))
            return "\n".join(files) if files else "No files found."

        elif name == "get_repo_structure":
            from agents.codebase import get_repo_structure
            return get_repo_structure(input_data["repo"])

        elif name == "get_leo_health_summary":
            import leo_client
            result = leo_client.get_health_summary()
            return json.dumps(result, indent=2, default=str) if result else "Leo unavailable."

        elif name == "get_leo_trends":
            import leo_client
            result = leo_client.get_trends()
            return json.dumps(result, indent=2, default=str) if result else "Leo unavailable."

        elif name == "create_mission":
            mission_id = memory.create_mission(
                title=input_data["title"],
                description=input_data.get("description", ""),
                priority=input_data.get("priority", "normal"),
                assigned_agent=input_data.get("assigned_agent"),
                tags=[],
            )
            agent = input_data.get("assigned_agent", "unassigned")
            memory.log_activity("shams", "mission_created", f"Mission #{mission_id}: {input_data['title']} → {agent}")
            memory.create_notification("mission_created", f"New mission: {input_data['title']}", f"Assigned to {agent}", "mission", mission_id)
            return f"Mission #{mission_id} created: {input_data['title']} (assigned to {agent})"

        elif name == "update_mission":
            kwargs = {}
            if input_data.get("status"):
                kwargs["status"] = input_data["status"]
            if input_data.get("result"):
                kwargs["result"] = input_data["result"]
            memory.update_mission(input_data["mission_id"], **kwargs)
            status_label = input_data.get('status', 'updated')
            memory.log_activity("shams", "mission_update",
                f"Mission #{input_data['mission_id']} → {status_label}")
            memory.create_notification("mission_updated", f"Mission #{input_data['mission_id']} → {status_label}", "", "mission", input_data["mission_id"])
            return f"Mission #{input_data['mission_id']} updated."

        elif name == "draft_legal_document":
            from agents.registry import build_agent_system_prompt
            doc_type = input_data["document_type"]
            title = input_data["title"]
            instructions = input_data["instructions"]
            context = input_data.get("context", "")

            # Templates to guide Wakil
            template_hints = {
                "loi": "Include: parties, target entity, purchase price/structure, due diligence period, exclusivity, earnout terms if applicable, conditions precedent, expiration date. Use professional legal formatting.",
                "nda": "Include: parties, definition of confidential information, obligations, term, exceptions (public info, prior knowledge), remedies, governing law (NJ).",
                "term_sheet": "Include: parties, transaction type, valuation/price, structure (equity/RBF/musharaka), key terms, conditions, timeline, exclusivity. Note any Islamic finance considerations.",
                "legal_memo": "Structure: Issue, Brief Answer, Facts, Analysis, Conclusion, Recommended Action. Be direct and strategic.",
                "employment_letter": "Include: position, compensation, benefits, start date, at-will status, non-compete if applicable, reporting structure.",
                "counter_proposal": "Reference the original proposal, identify areas of agreement, present counter-terms with reasoning, deadline for response.",
                "contract": "Include standard contract elements: parties, recitals, definitions, obligations, representations, indemnification, termination, governing law.",
                "other": "",
            }

            draft_prompt = (
                f"Draft the following legal document:\n\n"
                f"**Type:** {doc_type}\n"
                f"**Title:** {title}\n"
                f"**Instructions:** {instructions}\n"
            )
            if context:
                draft_prompt += f"\n**Context:** {context}\n"
            hint = template_hints.get(doc_type, "")
            if hint:
                draft_prompt += f"\n**Template guidance:** {hint}\n"
            draft_prompt += "\nOutput the full document text, ready for review. Use professional legal formatting."

            wakil_system = build_agent_system_prompt("wakil")
            draft_response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=wakil_system,
                messages=[{"role": "user", "content": draft_prompt}],
            )
            draft_text = draft_response.content[0].text

            # Save to files table
            mission_id = input_data.get("mission_id")
            filename = f"{doc_type}_{title.lower().replace(' ', '_')[:40]}.md"
            file_id = memory.save_file(
                filename=filename,
                file_type="legal_draft",
                mime_type="text/markdown",
                file_size=len(draft_text),
                summary=f"[{doc_type.upper()}] {title}",
                transcript=draft_text,
                mission_id=mission_id,
            )
            memory.log_activity("wakil", "document_drafted",
                f"Legal draft: {title} (file #{file_id})",
                {"document_type": doc_type, "file_id": file_id})
            memory.create_notification("document_ready", f"{doc_type.upper()}: {title} ready for review", "", "file", file_id)

            # Auto-advance linked mission to review
            if mission_id:
                memory.update_mission(mission_id, status="review")
                memory.log_activity("wakil", "mission_update", f"Mission #{mission_id} → review (document drafted)")
                memory.create_notification("mission_updated", f"Mission #{mission_id} moved to review", "Document ready", "mission", mission_id)

            return f"Document drafted and saved as file #{file_id}: {title}\n\nPreview:\n{draft_text[:500]}..."

        elif name == "assign_research":
            depth = input_data.get("depth", "quick")
            deadline = input_data.get("deadline", "")
            description = f"Research query: {input_data['query']}\nDepth: {depth}"
            if deadline:
                description += f"\nDeadline: {deadline}"
            mission_id = memory.create_mission(
                title=f"Research: {input_data['query'][:100]}",
                description=description,
                priority="high" if depth == "deep" else "normal",
                assigned_agent="scout",
            )
            memory.log_activity("scout", "mission_created",
                f"Mission #{mission_id}: Research assigned — {input_data['query'][:80]}")
            return f"Research mission #{mission_id} assigned to Scout: {input_data['query']}"

        elif name == "propose_code_change":
            action_id = memory.create_action(
                agent_name="builder",
                action_type="create_pr",
                title=f"PR: {input_data['title']}",
                description=input_data.get("description", ""),
                payload={
                    "repo": input_data["repo"],
                    "title": input_data["title"],
                    "description": input_data.get("description", ""),
                    "files": input_data["files"],
                },
            )
            memory.log_activity("builder", "action_proposed",
                f"Action #{action_id}: PR proposed for {input_data['repo']} — {input_data['title']}")
            file_list = ", ".join(f["path"] for f in input_data["files"])
            return (f"Code change #{action_id} proposed: {input_data['title']}\n"
                    f"Files: {file_list}\n"
                    f"Waiting for Maher's approval in the dashboard.")

        elif name == "propose_action":
            action_id = memory.create_action(
                agent_name="shams",
                action_type=input_data["action_type"],
                title=input_data["title"],
                description=input_data.get("description", ""),
                payload=input_data.get("payload"),
                mission_id=input_data.get("mission_id"),
            )
            memory.increment_trust("shams", "total_proposed")
            # Check auto-approve
            if memory.should_auto_approve("shams"):
                memory.update_action_status(action_id, "approved")
                memory.increment_trust("shams", "total_approved")
                memory.log_activity("shams", "action_auto_approved", f"Action #{action_id} auto-approved: {input_data['title']}")
                return f"Action #{action_id} auto-approved: {input_data['title']}"
            memory.log_activity("shams", "action_proposed", f"Action #{action_id}: {input_data['title']}")
            memory.create_notification("action_pending", input_data["title"], "", "action", action_id)
            # Send Telegram with approve/reject buttons
            try:
                import config as _cfg
                if _cfg.TELEGRAM_CHAT_ID:
                    from app import send_telegram_with_buttons
                    send_telegram_with_buttons(_cfg.TELEGRAM_CHAT_ID,
                        f"Action #{action_id}: {input_data['title']}\n{input_data.get('description', '')}",
                        [
                            {"text": "Approve", "callback_data": f"approve:{action_id}"},
                            {"text": "Reject", "callback_data": f"reject:{action_id}"},
                        ])
            except Exception:
                pass
            return f"Action #{action_id} proposed: {input_data['title']}. Waiting for Maher's approval (dashboard or Telegram)."

        elif name == "create_deal":
            deal_id = memory.create_deal(
                title=input_data["title"],
                deal_type=input_data.get("deal_type", "acquisition"),
                value=input_data.get("value", 0),
                contact=input_data.get("contact", ""),
                source=input_data.get("source", ""),
                location=input_data.get("location", ""),
                next_action=input_data.get("next_action", ""),
                score=input_data.get("score", 0),
                notes=input_data.get("notes", ""),
            )
            memory.log_activity("scout", "deal_created", f"Deal #{deal_id}: {input_data['title']}")
            memory.create_notification("deal_created", f"New deal: {input_data['title']}", input_data.get("source", ""), "deal", deal_id)
            return f"Deal #{deal_id} added to pipeline: {input_data['title']}"

        elif name == "update_deal":
            kwargs = {k: v for k, v in input_data.items() if k != "deal_id"}
            memory.update_deal(input_data["deal_id"], **kwargs)
            memory.log_activity("shams", "deal_updated", f"Deal #{input_data['deal_id']} → {kwargs.get('stage', 'updated')}")
            return f"Deal #{input_data['deal_id']} updated."

        elif name == "schedule_task":
            task_id = memory.create_scheduled_task(
                name=input_data["name"],
                cron_expression=input_data["cron_expression"],
                prompt=input_data["prompt"],
            )
            # Register with live scheduler
            try:
                from app import register_dynamic_task
                register_dynamic_task(task_id, input_data["cron_expression"], input_data["prompt"])
            except Exception as e:
                logger.warning(f"Could not register task live (will load on restart): {e}")
            memory.log_activity("shams", "task_scheduled",
                f"Scheduled task #{task_id}: {input_data['name']} ({input_data['cron_expression']})")
            memory.create_notification("task_scheduled", f"Recurring task created: {input_data['name']}", input_data["cron_expression"], "", None)
            return f"Scheduled task #{task_id} created: {input_data['name']}\nSchedule: {input_data['cron_expression']}\nPrompt: {input_data['prompt']}"

        elif name == "list_scheduled_tasks":
            tasks = memory.get_scheduled_tasks()
            if not tasks:
                return "No scheduled tasks."
            lines = []
            for t in tasks:
                status = "enabled" if t["enabled"] else "disabled"
                last = t["last_run_at"].isoformat() if t.get("last_run_at") else "never"
                lines.append(f"#{t['id']}: {t['name']} [{status}] — cron: {t['cron_expression']} — last run: {last}")
            return "\n".join(lines)

        elif name == "cancel_scheduled_task":
            memory.update_scheduled_task(input_data["task_id"], enabled=False)
            try:
                from app import remove_dynamic_task
                remove_dynamic_task(input_data["task_id"])
            except Exception:
                pass
            return f"Scheduled task #{input_data['task_id']} disabled."

        elif name == "create_workflow":
            workflow_id = memory.create_workflow(
                title=input_data["title"],
                description=input_data.get("description", ""),
                steps=input_data["steps"],
            )
            step_list = "\n".join(
                f"  {i+1}. {s['agent_name']}: {s['instruction'][:80]}"
                for i, s in enumerate(input_data["steps"])
            )
            memory.log_activity("shams", "workflow_created",
                f"Workflow #{workflow_id}: {input_data['title']} ({len(input_data['steps'])} steps)")
            memory.create_notification("workflow_created", f"Workflow: {input_data['title']}", f"{len(input_data['steps'])} steps", "workflow", workflow_id)
            # Start first step
            try:
                from workflow_engine import run_next_step
                run_next_step(workflow_id)
            except Exception as e:
                logger.warning(f"Could not auto-start workflow: {e}")
            return f"Workflow #{workflow_id} created: {input_data['title']}\nSteps:\n{step_list}\n\nStep 1 is starting now."

        elif name == "route_to_agent":
            from agents.registry import call_agent
            extra = ""
            if input_data.get("context_from_action_id"):
                action = memory.get_action(input_data["context_from_action_id"])
                if action:
                    extra = f"Context from previous action #{action['id']}:\n{action.get('result', '')}"
            response = call_agent(
                input_data["target_agent"],
                input_data["message"],
                extra_context=extra,
            )
            memory.log_activity(input_data["target_agent"], "routed_message",
                f"Message from Shams: {input_data['message'][:80]}")
            return f"[{input_data['target_agent']}]: {response}"

        elif name == "remember":
            memory.remember(input_data["key"], input_data["value"])
            return f"Remembered: {input_data['key']}"

        elif name == "add_open_loop":
            loop_id = memory.add_open_loop(input_data["title"], input_data.get("context", ""))
            return f"Open loop #{loop_id} created: {input_data['title']}"

        elif name == "close_open_loop":
            memory.close_loop(input_data["loop_id"], input_data.get("status", "done"))
            return f"Loop #{input_data['loop_id']} closed."

        elif name == "log_decision":
            memory.log_decision(input_data["summary"], input_data.get("reasoning", ""), input_data.get("outcome", ""))
            return f"Decision logged: {input_data['summary']}"

        else:
            return f"Unknown tool: {name}"

    except Exception as e:
        logger.error(f"Tool {name} error: {e}", exc_info=True)
        return f"Tool error: {e}"


# ── Memory context ───────────────────────────────────────────────────────────

def _build_memory_context() -> str:
    parts = []

    kv = memory.recall_all()
    if kv:
        parts.append("## Memory")
        for k, v in kv.items():
            parts.append(f"- **{k}**: {v}")

    loops = memory.get_open_loops()
    if loops:
        parts.append("\n## Open Loops")
        for loop in loops:
            parts.append(f"- [{loop['id']}] {loop['title']}: {loop['context']}")

    decisions = memory.get_recent_decisions(5)
    if decisions:
        parts.append("\n## Recent Decisions")
        for d in decisions:
            parts.append(f"- {d['summary']}")

    return "\n".join(parts)


def _build_system():
    mem_context = _build_memory_context()
    system = SYSTEM_PROMPT
    if KNOWLEDGE_BASE:
        system += f"\n\n# Knowledge Base\n{KNOWLEDGE_BASE}"
    if mem_context:
        system += f"\n\n# Live State (from memory)\n{mem_context}"

    # Connected accounts
    import google_client
    connected = []
    for acct_key, acct_email in config.GOOGLE_ACCOUNTS.items():
        token = memory.recall(f"google_{acct_key}_access_token")
        if token:
            connected.append(f"{acct_key} ({acct_email})")
    if connected:
        system += f"\n\n# Connected Email Accounts\nYou have access to these Gmail accounts: {', '.join(connected)}. "
        system += "When triaging email or answering questions about email, you pull from ALL connected accounts."

    system += "\n\n# Tools Available"
    system += "\nYou have tools to search the web, check Mercury bank balances and transactions, "
    system += "pull live P&L and operations data from Rumi, triage email from all connected accounts, and manage persistent memory."
    system += "\n\n# CRITICAL: Proactive Memory & Tracking"
    system += "\nYou MUST use your memory tools automatically — never wait for Maher to ask you to remember something."
    system += "\n- **remember**: Save ANY new fact, preference, update, or context Maher shares. Names, numbers, dates, "
    system += "decisions, preferences, relationships, deal updates, personal details — all of it. If he tells you "
    system += "something you didn't already know, save it immediately."
    system += "\n- **add_open_loop**: When Maher mentions ANYTHING that needs follow-up, a pending task, a question "
    system += "to resolve, a call to make, a document to review — create an open loop. Don't ask, just track it."
    system += "\n- **log_decision**: When Maher makes or confirms a decision — a deal term, a hire, a strategy choice, "
    system += "a rejection — log it with reasoning. Decisions are history. They compound."
    system += "\n- **close_open_loop**: When something previously tracked gets resolved, close it."
    system += "\n\nYou are Maher's memory. Everything he tells you persists. Act like it."

    return system


# ── Chat (with tool use loop) ────────────────────────────────────────────────

def chat(user_message: str, images: list = None) -> str:
    """Send a message to Claude with tools, memory, and full context."""
    label = user_message
    if images:
        label = f"[{len(images)} image(s)] {user_message}" if user_message else f"[{len(images)} image(s)]"
    memory.save_message("user", label)

    recent = memory.get_recent_messages(30)
    messages = [{"role": r["role"], "content": r["content"]} for r in recent]

    # If this message has images, replace the last message with multimodal content
    if images:
        content_blocks = []
        for img in images:
            content_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img["media_type"],
                    "data": img["data"],
                },
            })
        content_blocks.append({"type": "text", "text": user_message or "What's in this image?"})
        messages[-1] = {"role": "user", "content": content_blocks}

    # Tool use loop — Claude may call tools multiple times before responding
    max_iterations = 5
    for i in range(max_iterations):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=_build_system(),
            tools=TOOLS,
            messages=messages,
        )

        # If Claude is done (no tool calls), extract text and return
        if response.stop_reason == "end_turn":
            text_parts = [b.text for b in response.content if b.type == "text"]
            reply = "\n".join(text_parts) if text_parts else ""
            memory.save_message("assistant", reply)
            return reply

        # Process tool calls
        tool_results = []
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                logger.info(f"Tool call: {block.name}({json.dumps(block.input)[:100]})")
                result = _execute_tool(block.name, block.input)
                # Log tool call to activity feed
                _input_summary = json.dumps(block.input)[:120]
                _result_summary = (result or "")[:200]
                memory.log_activity(
                    "shams", "tool_call",
                    f"{block.name}: {_input_summary}",
                    {"tool": block.name, "input": block.input, "result_preview": _result_summary},
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        # Add assistant message + tool results to conversation
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    # If we hit max iterations, return whatever text we have
    reply = "I ran into a limit processing your request. Here's what I have so far:\n\n" + "\n".join(text_parts)
    memory.save_message("assistant", reply)
    return reply


def generate_briefing(briefing_type: str, context: str) -> str:
    """Generate a briefing with tool access."""
    messages = [{"role": "user", "content": f"Generate a {briefing_type} briefing.\n\nContext:\n{context}"}]

    max_iterations = 5
    for i in range(max_iterations):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=_build_system(),
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            text_parts = [b.text for b in response.content if b.type == "text"]
            return "\n".join(text_parts) if text_parts else ""

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                logger.info(f"Briefing tool call: {block.name}")
                result = _execute_tool(block.name, block.input)
                memory.log_activity(
                    "shams", "tool_call",
                    f"[briefing] {block.name}: {json.dumps(block.input)[:120]}",
                    {"tool": block.name, "context": "briefing"},
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    return "Briefing generation incomplete."
