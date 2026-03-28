# Shams

MJ's personal AI chief of staff — powered by Claude.

Receives messages via WhatsApp, maintains persistent memory in PostgreSQL, pulls business data from Rumi (Queen City P&L bot), and delivers scheduled morning/evening briefings.

## Setup

1. Copy `.env.example` to `.env` and fill in credentials
2. Run `pip install -r requirements.txt`
3. Run schema: `psql $DATABASE_URL -f schema.sql`
4. Start: `python app.py`

## Architecture

- **app.py** — Flask server + WhatsApp webhook + APScheduler
- **claude_client.py** — Claude API with memory context injection
- **memory.py** — PostgreSQL read/write for conversations, memory, open loops, decisions
- **briefing.py** — Morning/evening briefing generation
- **rumi_client.py** — HTTP client for Rumi's P&L API
- **google_client.py** — Gmail + Google Calendar integration
