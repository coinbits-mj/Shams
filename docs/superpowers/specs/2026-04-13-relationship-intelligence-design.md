# Relationship Intelligence — Automatic CRM with Communication Bridge

*Design spec — April 13, 2026*

## Overview

Shams builds and maintains a contact graph automatically from four sources: email, calendar, iMessage, and WhatsApp. No manual entry. A local bridge script on MJ's Mac reads iMessage and WhatsApp databases every 30 minutes and pushes touchpoint metadata (who, when, direction — no message content) to Shams via API. The overnight loop scans all touchpoints, calculates warmth scores, and surfaces cooling/cold relationships in the morning standup with drafted follow-up messages and channel-aware send buttons (Email / iMessage / WhatsApp).

## Data Sources

| Source | Database/API | What we extract |
|--------|-------------|-----------------|
| **Email** | Gmail API (3 accounts) | Sender/recipient, timestamp, direction |
| **Calendar** | Google Calendar API | Attendee names/emails, meeting timestamps |
| **iMessage** | `~/Library/Messages/chat.db` (SQLite) | `handle.id` (phone/email), `is_from_me`, `date` |
| **WhatsApp** | `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite` | `ZFROMJID`/`ZTOJID`, `ZISFROMME`, `ZMESSAGEDATE` |
| **WhatsApp Contacts** | `ContactsV2.sqlite` | `ZWHATSAPPID` → `ZFULLNAME`, `ZPHONENUMBER` |
| **Deals** | `shams_deals` table | Contact names, deal context |

No message content is ever read or stored — only touchpoint metadata.

## Local Bridge (`shams_bridge.py`)

A Python script that runs on MJ's Mac as a macOS LaunchAgent. ~200 lines.

### What it does

Every 30 minutes:
1. Reads iMessage `chat.db` — extracts handle ID (phone/email), direction (`is_from_me`), timestamp
2. Reads WhatsApp `ChatStorage.sqlite` — extracts JID, direction (`ZISFROMME`), timestamp
3. Maps WhatsApp JIDs to names/phone numbers via `ContactsV2.sqlite`
4. Filters out touchpoints already sent (tracks high-water mark per source in a local JSON file)
5. POSTs new touchpoints to Shams: `POST /api/touchpoints`
6. Polls for outbound commands: `GET /api/bridge/pending`
7. Executes outbound commands:
   - **iMessage:** AppleScript `tell application "Messages" to send <text> to buddy <handle>`
   - **WhatsApp:** `open "whatsapp://send?phone=<number>&text=<urlencoded>"` (opens WhatsApp with pre-filled message — MJ hits send)

### Touchpoint payload format

```json
{
  "touchpoints": [
    {
      "source": "imessage",
      "contact_handle": "+17325551234",
      "contact_name": null,
      "direction": "inbound",
      "timestamp": "2026-04-13T02:30:00Z"
    },
    {
      "source": "whatsapp",
      "contact_handle": "19735551234@s.whatsapp.net",
      "contact_name": "Ahmed Khan",
      "contact_phone": "+19735551234",
      "direction": "outbound",
      "timestamp": "2026-04-13T01:15:00Z"
    }
  ]
}
```

### Bridge command format

```json
{
  "commands": [
    {
      "id": 42,
      "channel": "imessage",
      "recipient": "+17325551234",
      "message": "Hey Ahmed, circling back on Q2 pricing..."
    }
  ]
}
```

### Installation

```bash
# Copy bridge script to a stable location
cp shams_bridge.py ~/Library/Application\ Support/Shams/shams_bridge.py

# Install LaunchAgent plist
cp com.shams.bridge.plist ~/Library/LaunchAgents/

# Load it
launchctl load ~/Library/LaunchAgents/com.shams.bridge.plist
```

The bridge needs:
- Full Disk Access permission in System Settings → Privacy & Security (for `chat.db`)
- `SHAMS_API_URL` and `SHAMS_API_TOKEN` environment variables (or in a config file)

### High-water mark

The bridge stores `~/.shams_bridge_state.json`:
```json
{
  "imessage_last_timestamp": 797750508837352064,
  "whatsapp_last_timestamp": 797753391.362144
}
```

Only touchpoints newer than these timestamps are sent on each cycle.

## Shams API Endpoints

Two new endpoints in a new `api/bridge.py` module:

### `POST /api/touchpoints`

Receives touchpoint batches from the bridge. For each touchpoint:
1. Find or create a `shams_contacts` record by phone/email handle
2. Update `last_inbound` or `last_outbound` timestamp
3. Increment `touchpoint_count`
4. Add the source channel to the contact's `channels` array

Auth: API token header (`X-Bridge-Token`) matching `BRIDGE_API_TOKEN` env var.

### `GET /api/bridge/pending`

Returns queued outbound commands. Bridge polls this every 30 minutes (same cycle as touchpoint push).

### `POST /api/bridge/command`

Queues a new outbound command (called by standup callback handlers).

### `POST /api/bridge/ack`

Bridge acknowledges command execution (marks as completed or failed).

## Contact Table

```sql
CREATE TABLE IF NOT EXISTS shams_contacts (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255),
    phone           VARCHAR(50),
    whatsapp_jid    VARCHAR(100),
    source          VARCHAR(50) DEFAULT 'email',
    channels        TEXT[] DEFAULT '{}',
    last_inbound    TIMESTAMPTZ,
    last_outbound   TIMESTAMPTZ,
    last_meeting    TIMESTAMPTZ,
    touchpoint_count INTEGER DEFAULT 0,
    warmth_score    INTEGER DEFAULT 50,
    deal_id         INTEGER,
    notes           TEXT DEFAULT '',
    snoozed_until   TIMESTAMPTZ,
    auto_discovered BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_email ON shams_contacts (email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON shams_contacts (phone);
CREATE INDEX IF NOT EXISTS idx_contacts_warmth ON shams_contacts (warmth_score);
```

The `channels` array tracks which channels this contact has been seen on: `{'email', 'imessage', 'whatsapp', 'calendar'}`. This determines which send buttons appear in the standup.

## Bridge Command Queue Table

```sql
CREATE TABLE IF NOT EXISTS shams_bridge_commands (
    id          SERIAL PRIMARY KEY,
    channel     VARCHAR(20) NOT NULL CHECK (channel IN ('imessage', 'whatsapp')),
    recipient   VARCHAR(255) NOT NULL,
    message     TEXT NOT NULL,
    status      VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    executed_at TIMESTAMPTZ
);
```

## Warmth Score

0-100 scale, recalculated nightly in the overnight loop:

- **Base decay:** starts at 100 after last interaction, drops ~3 points per day of silence
- **Frequency boost:** contacts with weekly interaction decay slower (1.5 points/day). Monthly contacts decay at standard rate (3 points/day).
- **Direction weight:** inbound touchpoint = +5 warmth boost (they're engaging with you). Outbound-only = no boost.
- **Deal boost:** contacts on active deals get a warmth floor of 20 (don't flag as cold while deal is live)
- **Multi-channel bonus:** contacts seen on 2+ channels get +10 warmth (deeper relationship signal)

Formula:
```python
days_since = (now - max(last_inbound, last_outbound, last_meeting)).days
decay_rate = 1.5 if touchpoint_count > 12 else 3.0  # weekly vs less frequent
base = max(0, 100 - (days_since * decay_rate))

# Boosts
if last_inbound and last_inbound > last_outbound:
    base = min(100, base + 5)
if deal_id and deal is active:
    base = max(20, base)
if len(channels) >= 2:
    base = min(100, base + 10)

warmth_score = int(base)
```

Thresholds:
- **80-100:** Hot — active relationship
- **50-79:** Warm — healthy cadence
- **25-49:** Cooling — needs a touchpoint soon
- **0-24:** Cold — at risk of going dark

## Contact Noise Filtering

Not every message sender is a relationship worth tracking. Filter out:

- **Email:** `noreply@`, `no-reply@`, `notifications@`, `support@`, `info@` addresses. Domains: `shopify.com`, `squareup.com`, `klaviyo.com`, `recharge.io`, `github.com`, `railway.app`, `google.com`, `apple.com`.
- **iMessage/WhatsApp:** Contacts with only 1 touchpoint and no deal association (one-off messages). Short codes and verification numbers.
- **Snoozed contacts:** `snoozed_until` > now — suppressed from standup alerts.

Minimum threshold: 2+ touchpoints OR deal association to activate warmth tracking.

## Overnight Loop Integration

New step 7: `_step_relationship_scan()`

1. Scan today's triaged emails — extract sender/recipient, upsert contacts, update touchpoints
2. Scan today's calendar events — extract attendees, upsert contacts, update `last_meeting`
3. Scan active deals — ensure deal contacts exist in contacts table
4. Recalculate warmth scores for all contacts
5. Find contacts that crossed from warm→cooling or cooling→cold since yesterday
6. For cooling/cold contacts, draft follow-up messages using Claude (context-aware: knows the deal, last email subject, etc.)

Results structure:
```json
{
  "contacts_updated": 47,
  "new_contacts": 3,
  "cooling": [
    {
      "id": 12,
      "name": "Ahmed Khan",
      "email": "ahmed@cafeimports.com",
      "phone": "+19735551234",
      "channels": ["email", "whatsapp"],
      "warmth": 35,
      "days_silent": 22,
      "context": "Last email: Q2 green coffee pricing",
      "draft": "Hey Ahmed, circling back on Q2 pricing...",
      "deal_id": null
    }
  ],
  "cold": [],
  "follow_ups_drafted": 2
}
```

## Standup Integration

### Overview message

```
🤝 3 contacts cooling · 1 going cold
```

### Drip-feed action items

After Scout findings, before the wrap-up. One message per cooling/cold contact:

```
🤝 Going cold: Ahmed Khan
Last contact: 22 days ago (WhatsApp)
Warmth: 35/100 — was 58 last week
Context: Q2 green coffee pricing discussion

Draft: "Hey Ahmed, circling back on the Q2 pricing — are the updated numbers for the Yirgacheffe and Sumatra ready? We're looking to place our order soon."

[📧 Email]  [💬 iMessage]  [💚 WhatsApp]  [✏️ Edit]  [Skip]  [😴 Snooze 7d]
```

Channel buttons only appear if Shams has seen that contact on that channel (checked via `channels` array):
- **📧 Email** → `su_email:{idx}` callback → saves Gmail draft (existing flow)
- **💬 iMessage** → `su_imsg:{idx}` callback → queues bridge command
- **💚 WhatsApp** → `su_wa:{idx}` callback → queues bridge command (opens WhatsApp with pre-filled message)
- **😴 Snooze 7d** → `su_snooze7:{idx}` callback → sets `snoozed_until = now + 7 days`

### Trust integration

Relationship follow-ups map to trust action type `relationship_followup` (medium risk, 15 approvals to auto-approve). Once trusted, Shams auto-sends follow-ups via the most recently used channel without asking.

## Files Changed

| File | Change |
|------|--------|
| `shams_bridge.py` | **Create** — local macOS bridge script (iMessage + WhatsApp reader + command executor) |
| `com.shams.bridge.plist` | **Create** — LaunchAgent config for auto-starting bridge |
| `schema.sql` | Add `shams_contacts` + `shams_bridge_commands` tables |
| `memory.py` | Contact CRUD (upsert_contact, get_contacts_by_warmth, update_warmth_scores, snooze_contact, get_cooling_contacts) + bridge command CRUD |
| `api/bridge.py` | **Create** — touchpoints endpoint + bridge command queue |
| `standup.py` | Add `_step_relationship_scan()` as step 7, update overview + action items + drip-feed for relationship items |
| `telegram.py` | Add callbacks: `su_email`, `su_imsg`, `su_wa`, `su_snooze7` |
| `tests/test_standup.py` | Warmth calculation tests, contact filtering tests, touchpoint processing tests |

## What This Does NOT Include

- No message content — only touchpoint metadata (who, when, direction, channel)
- No group chat tracking — 1:1 conversations only
- No automated WhatsApp sending — opens WhatsApp with pre-filled message, MJ taps send
- No contact detail page in dashboard — future work
- No contact import from phone contacts — auto-discovered from communication only
- No relationship categorization (supplier/customer/investor) — inferred from deal associations and email context
- No SMS reading from WhatsApp (WhatsApp and iMessage are separate sources)
