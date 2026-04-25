# Shams Voice Sync — Design

**Date:** 2026-04-24
**Status:** Approved
**Author:** MJ + Claude

## Problem

MJ wants a daily voice conversation with Shams — brain dump ideas, talk through priorities, reflect on the day. Not a fixed-schedule meeting but an on-demand sync that Shams initiates at a smart time. Shams should be an active conversational participant (not a passive recorder), speaking with a human-quality voice, surfacing relevant context, and pushing back when useful.

## Goal

Build a real-time voice conversation system where Shams joins a Google Meet as an active participant with a professional male ElevenLabs voice. Shams listens, thinks with full business context (email archive, commitments, calendar, missions, P&L), and responds naturally. Smart ping via Telegram during a preferred daily window. Post-call: full transcript processing pipeline (same as meeting bot).

## Non-Goals

- Phone calls (Twilio/Vapi) — MJ wants Google Meet so he can add people to the call
- Fixed schedule — adapts to MJ's calendar
- Passive recording only — Shams must speak and engage
- Voice cloning — using pre-built ElevenLabs voice, not MJ's clone

## Architecture

### Real-time conversation loop

```
MJ speaks
  → Recall.ai real-time transcription webhook (~200ms)
  → Shams server receives utterance
  → Pause detection (~1.5s silence = turn complete)
  → Claude processes (Haiku for speed, ~500ms):
      - Full conversation history for this sync
      - Injected context:
          - Today's remaining calendar events
          - Top 5 overdue open commitments
          - Recent P1 emails (last 24h)
          - Mercury balance snapshot
          - Active missions summary
          - Any person MJ just mentioned → pull their email history + deals + commitments
  → ElevenLabs TTS Flash v2.5 (~75ms first chunk)
  → Convert to mp3 base64
  → Recall.ai POST /api/v1/bot/{id}/output_audio/ → plays in meeting
  
Total round-trip: ~1.5-2.5 seconds
```

### Trigger flow

```
Scheduler (every 15 min during preferred window)
  → Check: within preferred window? (default 9-11am ET)
  → Check: current 30-min block free on calendar?
  → Check: haven't pinged today? (or was dismissed)
  → Check: not weekend? (configurable)
  → All pass → Send Telegram ping with Join button
  → MJ taps Join → opens persistent Google Meet link
  → Shams dispatches Recall.ai bot with real-time transcription + audio output enabled
  → Bot joins Meet, waits for MJ
  → MJ joins → conversation begins
  → MJ leaves → bot leaves → post-call processing pipeline
```

### Post-call pipeline

Same as meeting bot (already built):
- Transcript → persona-aware summary → action items → commitments auto-tracked
- Telegram brief + email digest + stored in `shams_meeting_notes`
- Meeting type auto-detected as "daily_sync" with Shams persona

## Smart Ping Logic

Runs every 15 min via APScheduler during preferred window.

### Configuration (env vars)

- `SYNC_WINDOW_START_UTC` — default 13 (9am ET)
- `SYNC_WINDOW_END_UTC` — default 15 (11am ET)
- `SYNC_SKIP_WEEKENDS` — default true
- `SYNC_MEET_URL` — persistent Google Meet link (created once, reused)

### Conditions to ping

All must be true:
1. Current time is within the preferred window
2. Current 30-min calendar block is free (no event starting within 30 min)
3. Haven't pinged today — or MJ tapped "Not today" (flag in `shams_memory`)
4. Not a weekend (if `SYNC_SKIP_WEEKENDS` is true)

### Telegram message

```
☀️ Got a clear window — want to sync?

[Join Sync ☕]  ← deeplink to SYNC_MEET_URL
[Not today]     ← sets shams_memory flag, no more pings today
```

Inline keyboard buttons. "Join Sync" opens the Meet link. "Not today" calls back to Shams which sets a memory flag.

### Persistent Meet link

One standing Google Meet link for all daily syncs. Stored as `SYNC_MEET_URL` env var on Railway. Created manually once (MJ creates a recurring "Shams Sync" event, copies the Meet link). Shams bot joins it on-demand and leaves when MJ leaves.

## Voice

### ElevenLabs integration

- **Model:** Flash v2.5 (75ms latency — prioritize responsiveness over maximum quality)
- **Voice character:** Professional male, calm, measured, executive-advisor energy. American English, neutral accent. Clear diction, moderate pace.
- **Voice selection:** During implementation, shortlist 3 candidate voices from ElevenLabs library. MJ picks via Telegram audio samples.
- **API:** Streaming TTS endpoint (`POST /v1/text-to-speech/{voice_id}/stream`)
- **Output format:** mp3 (required by Recall.ai `output_audio` endpoint)
- **New env var:** `ELEVENLABS_API_KEY`

### Conversation personality

System prompt for the real-time Claude loop:

```
You are Shams, MJ's chief of staff. You're in a live voice conversation.

RULES:
- Be concise. Speak in 1-3 sentences per turn. Never monologue.
- Surface relevant context proactively: "You have an open commitment to X from Y days ago" or "Your calendar has Z in 2 hours"
- Push back gently when useful: "Are you sure about that timeline? The Somerville retainer is still unsigned."
- Ask ONE clarifying question at a time, never multiple.
- When MJ mentions a person, silently pull their email history + commitments + deals. Reference what you find.
- When MJ makes a commitment ("I'll do X"), confirm: "Got it, tracking that."
- When MJ asks about data (revenue, balances, schedule), pull it and state it concisely.
- Don't say "as an AI" or "I don't have feelings" — you're his chief of staff.
- Match his energy: if he's casual, be casual. If he's focused, be sharp.
- If he says "just listen" — go quiet, only speak when asked.
```

### Active co-pilot behaviors

Shams proactively surfaces:
- **Open commitments** involving anyone MJ mentions ("You told Richard you'd send the LOI 50 days ago")
- **Calendar awareness** ("You have a call with Brandon in 45 minutes")
- **Email context** ("Adam emailed you about the matcha samples 3 days ago, no response yet")
- **Financial snapshots** when relevant ("Mercury shows $48K across accounts, ODEKO charged $4.2K yesterday")
- **Deadline reminders** ("Tax docs are due tomorrow")

## Data Model

No new tables needed. Uses existing:
- `shams_meeting_notes` — stores sync transcript + summary (meeting_type = "daily_sync")
- `shams_open_commitments` — auto-creates/resolves from conversation
- `shams_memory` — tracks sync state (pinged_today, last_sync_date, etc.)

## New Files

- `voice_sync.py` — smart ping scheduler, bot dispatch for syncs, real-time conversation handler, turn management
- `elevenlabs_client.py` — TTS API wrapper (stream text → mp3 bytes)

## Modified Files

- `config.py` — add ELEVENLABS_API_KEY, SYNC_* env vars
- `scheduler.py` — add sync ping scheduler job (every 15 min)
- `app.py` — add real-time transcription webhook handler for conversation (separate from post-meeting webhook)
- `recall_client.py` — add `output_audio(bot_id, mp3_b64)` and `create_bot` option for real-time transcription webhook URL

## Real-time Webhook Flow

Recall.ai's real-time transcription sends webhooks for each utterance during the meeting (not after). Shams needs a dedicated endpoint for these:

`POST /api/recall/realtime` — receives real-time transcript chunks

For each chunk:
1. Append to conversation buffer
2. Detect if speaker finished (1.5s silence or end-of-utterance signal)
3. If MJ's turn is done:
   a. Build context (calendar + commitments + email for mentioned people)
   b. Call Claude with conversation history + context
   c. Stream Claude's response through ElevenLabs TTS
   d. POST the mp3 audio to Recall.ai `output_audio`
   e. Append Shams's response to conversation history

### Conversation state

Managed in-memory (per active sync session):

```python
{
    "bot_id": "...",
    "conversation_history": [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."},
    ],
    "context_cache": { ... },  # refreshed every few turns
    "mode": "active" | "passive",  # "just listen" toggle
    "started_at": "...",
}
```

## Error Handling

- **MJ doesn't join within 5 min** — bot leaves, Telegram: "No worries, catch you later ☕"
- **ElevenLabs TTS fails** — Shams sends text response in Meet chat instead of speaking
- **Claude response too long** — truncate to 3 sentences, speak only the key point
- **Real-time webhook lag** — buffer utterances, process in order
- **MJ says "just listen"** — set mode to passive, only respond when directly asked a question
- **MJ adds someone to call** — Shams detects new participant, adjusts tone (more professional), pulls their context
- **Recall.ai output_audio fails** — log error, continue listening, deliver summary post-call

## Cost Estimate

| Component | Per sync (15 min) | Monthly (20 syncs) |
|---|---|---|
| Recall.ai bot | ~$3-5 | ~$60-100 |
| ElevenLabs TTS | ~$0.50-1 | ~$10-20 |
| Claude Haiku (real-time) | ~$0.10 | ~$2 |
| Claude (post-call summary) | ~$0.05 | ~$1 |
| **Total** | **~$4-6** | **~$75-125/month** |

## Rollout

1. Sign up for ElevenLabs, get API key
2. Pick a voice (I'll send 3 audio samples via Telegram for MJ to choose)
3. Create a persistent Google Meet link, set as `SYNC_MEET_URL`
4. Deploy voice sync code
5. Test with one manual sync triggered via Telegram
6. Enable smart ping scheduler
7. Use for 1 week, tune conversation personality based on feedback
