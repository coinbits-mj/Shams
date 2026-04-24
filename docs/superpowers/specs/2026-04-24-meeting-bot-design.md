# Meeting Bot — Design

**Date:** 2026-04-24
**Status:** Approved
**Author:** MJ + Claude

## Problem

MJ misses meetings or can't attend every standup/sync. When he does attend, action items and commitments get lost. Lindy demonstrated the "aha" moment: a bot joins on your behalf, records, transcribes, summarizes, and sends action items — even when you're not there.

## Goal

Shams joins MJ's meetings automatically (Google Meet, Zoom, Slack huddles), records + transcribes via Recall.ai, then generates a persona-aware summary cross-referenced against the email archive, open commitments, and active missions. Delivers via Telegram + email + queryable DB storage.

## Non-Goals

- Real-time transcription/live captions during meetings (Recall.ai handles recording; Shams processes after)
- Video recording or screen capture — audio transcript only
- Replacing the calendar; Shams reads events but doesn't create/modify them (calendar write is a separate roadmap item)

## Architecture

Three trigger paths share a single post-processing pipeline:

1. **Calendar watcher** — existing 10-min poll (`check_upcoming_meetings`) detects events with Meet/Zoom links, applies smart filter, dispatches Recall.ai bot ~5 min before start
2. **Slack listener** — `huddle_started` events in configured channels trigger Recall.ai bot dispatch
3. **Telegram command** — "join my 2pm" or "join huddle in #ops" for manual overrides

Post-meeting pipeline (triggered by Recall.ai webhook or fallback poller):
```
transcript received
  → detect meeting type from attendees + title
  → select persona lens
  → pull cross-references (email archive, commitments, missions)
  → synthesize summary via Haiku
  → auto-create new commitments from action items
  → auto-resolve commitments confirmed in meeting
  → store in shams_meeting_notes
  → send Telegram brief
  → send email digest via Resend
```

## Smart Filter (auto-join logic)

A calendar event gets a bot if ALL conditions met:
- Has a meeting link (Google Meet or Zoom URL)
- Has 2+ attendees (not just MJ)
- Not an all-day event
- Duration < 3 hours (skip conferences/webinars — manual opt-in)
- Title doesn't match exclusion patterns: "lunch", "dentist", "personal", "block", "focus time", "gym", "doctor" (configurable via env var `MEETING_EXCLUDE_PATTERNS`)
- MJ hasn't declined the event (RSVP status != "declined")
- Daily bot limit not exceeded (default: 10/day, configurable via `MEETING_BOT_MAX_DAILY`)

MJ can override via Telegram:
- "don't join my 3pm" → adds event_id to skip list for today
- "join my dentist call" → forces join even if filtered out

## Recall.ai Integration

### API calls used
- `POST /api/v1/bot` — create a bot to join a meeting URL at a scheduled time
- `GET /api/v1/bot/{id}` — check bot status
- `GET /api/v1/bot/{id}/transcript` — pull completed transcript
- Webhook: `bot.status_change` → fires when bot finishes recording

### Bot lifecycle
1. Shams creates bot via API with `meeting_url` + `join_at` (event start time)
2. Bot joins meeting, starts recording
3. Meeting ends → bot leaves → status changes to `done`
4. Webhook fires → Shams pulls transcript
5. If webhook missed: fallback poller every 5 min checks active bots for completion

### Supported platforms
- Google Meet: direct URL from calendar `hangoutLink`
- Zoom: meeting URL from calendar event description/location
- Slack huddles: Recall.ai native support via channel ID

## Persona-Aware Summarization

Meeting type detected from attendees + title keywords:

| Detection signal | Meeting type | Persona |
|---|---|---|
| Attendee email contains law firm domains (sewkis, amslawgrp, cooley, rajehsaadeh) | legal | Wakil |
| Title contains: standup, ops, sync, check-in, weekly | operations | Rumi |
| Attendee in shams_deals contact list OR title contains: deal, NDA, LOI, partnership, acquisition | deal | Scout |
| Title contains: interview, barista, candidate, hire | interview | Shams (hiring lens) |
| Everything else | general | Shams |

### Cross-referencing (the moat)

For each attendee, pull:
1. **Email archive** (last 60d) — recent threads, subjects, categories
2. **Open commitments** — unfulfilled promises MJ made to this person
3. **Active missions** — missions mentioning this person

Injected into the summarization prompt so the LLM can:
- Detect when a commitment is being fulfilled ("Richard says NDA is signed" → auto-mark `shams_open_commitments` row as fulfilled)
- Detect new commitments MJ makes ("I'll send the LOI by Friday" → auto-create commitment row)
- Surface unresolved items ("MJ still owes Brandon the vendor price list — 7d overdue")

## Data Model

### `shams_meeting_notes`

One row per meeting recorded.

| Column | Type | Notes |
|---|---|---|
| id | BIGSERIAL PK | |
| event_id | TEXT | Google Calendar event ID (nullable for huddles) |
| recall_bot_id | TEXT UNIQUE | Recall.ai bot UUID |
| title | TEXT | Meeting title |
| started_at | TIMESTAMPTZ | |
| ended_at | TIMESTAMPTZ | |
| duration_min | INT | |
| attendees | JSONB | `[{email, name, role}]` |
| platform | TEXT | 'google_meet' \| 'zoom' \| 'slack_huddle' |
| transcript | TEXT | Full transcript text |
| summary | TEXT | Persona-aware summary |
| action_items | JSONB | `[{assignee, task, deadline}]` |
| decisions | JSONB | `[{decision, context}]` |
| commitments_created | INT[] | FK refs to shams_open_commitments rows created |
| commitments_resolved | INT[] | FK refs to shams_open_commitments rows resolved |
| persona_used | TEXT | 'wakil' \| 'rumi' \| 'scout' \| 'shams' |
| meeting_type | TEXT | 'legal' \| 'standup' \| 'deal' \| 'interview' \| 'general' |
| telegram_sent | BOOLEAN DEFAULT FALSE | |
| email_sent | BOOLEAN DEFAULT FALSE | |
| created_at | TIMESTAMPTZ DEFAULT NOW() | |

Indexes: `(event_id)`, `(started_at DESC)`, GIN on `attendees`, GIN on `action_items`.

## Telegram Output (terse, per MJ style)

```
📋 *Daily Stand-Up* just ended (28 min)
👥 Brandon, Daniel, Mo

📌 Decisions:
- Thursday AM block for HubSpot sales updates
- Plainfield CC auth form → send to Admirald

⚡ Action items:
- Brandon: call new inbound lead, forward to Danny
- Mo: reach out to Terminal re: internal order process
- Maher: cut Plainfield credit card + get amex from Monica

⚠️ You committed to: cut Plainfield CC + get amex (auto-tracked)
✅ Resolved: Brandon confirmed Annie interview setup (was open 3d)
```

## Email Digest

Sent via Resend (already configured in Shams) to `maher@qcitycoffee.com`. Contains:
- Same content as Telegram but with full transcript attached as expandable section
- Link to query the meeting in Shams: "ask me about this meeting"

## Slack Huddle Integration

- **Auto-join config**: env var `SLACK_HUDDLE_CHANNELS` — comma-separated channel IDs
- Shams listens for Slack `huddle_started` events in these channels via existing slack_bolt connection
- On trigger: dispatches Recall.ai bot to the huddle
- Same post-meeting pipeline as calendar meetings

## Claude Tool Integration

New tool for Shams chat:

`search_meeting_notes(query, attendee, meeting_type, since, limit)` — search past meeting transcripts and summaries. Enables:
- "What did we discuss with Richard last week?"
- "Show me action items from the last 3 standups"
- "Did anyone mention the Somerville property in a meeting?"

## Error Handling

- **Bot can't join** (bad link, expired, meeting cancelled) → Telegram: "❌ Couldn't join your 2pm — [reason]. Want me to retry?"
- **Meeting < 3 min** → skip summarization, don't store (likely test/accidental)
- **Recall.ai webhook missed** → fallback poller every 5 min checks active bots via GET /api/v1/bot/{id}
- **MJ joins late** → bot already there from 5 min before start, captures full meeting
- **MJ doesn't join** → bot still records everything (the Lindy "aha" moment)
- **Transcript empty/garbled** → store raw, flag in Telegram: "⚠️ transcript quality was poor for your 2pm"
- **Recall.ai API down** → log error, skip meeting, Telegram: "⚠️ Meeting bot unavailable — couldn't join your 2pm"

## Cost Controls

- `MEETING_BOT_MAX_DAILY=10` — hard cap on bots per day
- Skip meetings over 3 hours (configurable via `MEETING_MAX_DURATION_HOURS=3`)
- Telegram alert if estimated daily spend exceeds $30
- Monthly spend tracking in `shams_memory` key `recall_monthly_spend_YYYY_MM`

## Rollout

1. Sign up for Recall.ai, get API key, set as `RECALL_API_KEY` env var
2. Deploy meeting bot code
3. Test with one meeting manually ("Shams join my next meeting")
4. Enable smart filter auto-join after manual test passes
5. Configure Slack huddle channels
6. Monitor for 1 week before trusting fully
