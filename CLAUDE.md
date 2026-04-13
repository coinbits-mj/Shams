# Shams — MJ's Personal AI Chief of Staff

## What this is
Shams is a personal AI assistant for MJ (Maher Janajri), founder of Queen City Coffee Roasters and Coinbits. Shams talks to MJ via Telegram and a web dashboard. Separate from Rumi (QCC's ops bot at ~/code/coffee-pl-bot).

## Stack
- **Backend:** Python/Flask on Railway, port 8081
- **AI:** Claude API via `claude_client.py` (tool-use loop with memory injection)
- **Database:** PostgreSQL on Railway (shared with Rumi, tables prefixed `shams_`)
- **Frontend:** React (Vite) dashboard at `frontend/`
- **Deploy:** `git push origin main` → Railway auto-deploys via Dockerfile

## Key files
- `app.py` — Flask server + Telegram bot (long-polling) + APScheduler
- `claude_client.py` — Claude API wrapper with tools, memory context injection, multi-persona
- `dashboard_api.py` — REST API for the web dashboard
- `memory.py` — PostgreSQL CRUD for conversations, memories, open loops, decisions
- `media_client.py` — HTTP client for media bridge (Jellyfin/torrent automation)
- `standup.py` — Overnight ops loop (3am) + morning standup delivery (7am) + evening briefing
- `config.py` — Environment variable loading
- `context/` — Persona definitions and knowledge docs
- `schema.sql` — Database schema (already deployed on Railway Postgres)

## Integrations
- Telegram (primary interface, long-polling)
- Gmail + Google Calendar (OAuth)
- Rumi (QCC ops bot, HTTP API)
- Mercury Banking
- GitHub
- DocuSeal
- Media bridge at media-bridge.myshams.ai (Radarr/Sonarr/qBittorrent)

## Personas (in context/)
- `shams_system_prompt.md` — core identity
- `leo_persona.md` — health coaching (Leo)
- `rumi_persona.md` — QCC ops (Rumi)
- `wakil_persona.md` — legal (Wakil)
- `scout_persona.md` — deal sourcing (Scout)
- `inbox_persona.md` — email triage (Inbox)
- `builder_persona.md` — technical projects (Builder)

## Conventions
- Never commit `.env` (contains API keys, database URL)
- Use `CLAUDE_MODEL` env var to control which Claude model Shams uses
- All database tables use `shams_` prefix
- Telegram bot only responds to MJ's chat ID (set in env)
- Tools are defined in the `TOOLS` list in `claude_client.py`
- Tool dispatch is in `_execute_tool()` in `claude_client.py`

## Common tasks
- **Add a new tool:** define in TOOLS list, add handler in _execute_tool(), both in claude_client.py
- **Add a Telegram command:** add handler in process_message() in app.py, before the Claude passthrough
- **Test locally:** `pip install -r requirements.txt && python app.py` (needs .env with real credentials)
- **Deploy:** `git push origin main` (Railway auto-deploys)
