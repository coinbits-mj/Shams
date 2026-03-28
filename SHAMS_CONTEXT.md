# Shams Build Context
*Transferred from claude.ai — March 2026*

## What Shams Is
Shams is MJ's personal AI chief of staff. Separate service from Rumi
(QCC's ops platform). Shams talks to MJ. Rumi talks to the team.

## Architecture Decided
- Python/Flask service on Railway port 8081
- Same Railway Postgres as Rumi, shams_ prefixed tables (already created)
- WhatsApp interface via Twilio
- Calls Rumi's internal API for live business data
- Gmail + Google Calendar access for MJ's personal accounts
- Scheduled morning + evening briefings
- Persistent memory across all conversations

## What's Already Built
- Full scaffold at /Users/mj/code/Shams
- All 5 database tables created on Railway Postgres
- app.py — Flask + WhatsApp webhook + APScheduler
- memory.py — full CRUD for all shams_ tables
- claude_client.py — Claude API wrapper with memory injection
- rumi_client.py — HTTP client calling Rumi's API
- briefing.py — morning/evening briefing logic
- google_client.py — Gmail + Calendar OAuth
- config.py — env vars
- schema.sql — already run against Railway Postgres

## What Needs Doing Next
1. Read briefing.py and config.py — not reviewed yet
2. Audit Rumi's actual /api/ routes — rumi_client.py calls endpoints
   that may not exist yet
3. Replace placeholder system prompt in claude_client.py with the real
   Shams founding document
4. Check Rumi JWT auth — Shams API calls may need auth headers
5. Set up .env with real credentials:
   - DATABASE_URL (same as Rumi)
   - ANTHROPIC_API_KEY (same as Rumi)
   - TWILIO_ACCOUNT_SID + AUTH_TOKEN + WHATSAPP_NUMBER
   - MAHER_WHATSAPP_NUMBER
   - GOOGLE_CLIENT_ID + SECRET
   - RUMI_BASE_URL
6. Add missing Rumi endpoints if needed
7. Deploy to Railway

## Rumi Architecture (Already Read)
- Flask on port 8080, 30+ API blueprints
- PostgreSQL on Railway (same instance Shams will use)
- Integrations: Square, Mercury, Gmail, Claude API, Twilio,
  Google My Business, Slack
- APScheduler with 25+ background jobs
- React frontend served from /frontend/dist
- JWT auth on API routes
- Repo: /Users/mj/code/coffee-pl-bot

## Key Files in Rumi
- app.py — entry point
- /data/ — API clients
- /engine/ — P&L, forecasting, AI engines
- /slack/ — Slack handlers
- /auth/ — JWT auth

## Credentials Note
- .env is in .gitignore on both repos
- Never committed to git history
- Railway Postgres: crossover.proxy.rlwy.net:27823/railway

## MJ Context
- Founder of Queen City Coffee Roasters + Coinbits
- Building toward $100M coffee platform
- Active deals: Red House Roasters acquisition, Somerville plaza,
  Zenbumi distribution, Coinbits sale
- Shams system prompt (full founding doc) is in the project files —
  must be injected into claude_client.py system prompt
- WhatsApp is MJ's preferred interface for Shams
- Morning briefing: business data from Rumi + calendar + emails
- Evening briefing: MTD summary + tomorrow prep + open loops
