# Scout: Autonomous Deal Flow Agent

*Design spec — April 13, 2026*

## Overview

Scout becomes the 5th registered agent in Shams, with an autonomous daily research sweep that runs as step 6 of the overnight loop. Scout searches the web across 6 domains (acquisitions, real estate, competitors, market trends, vendors, regulatory), evaluates findings, creates deal pipeline entries for promising leads (score 6+), and drafts outreach messages for high-scoring ones (8+). Everything surfaces in the 7am morning standup via the existing drip-feed mechanism.

## Agent Registration

Add Scout to `agents/registry.py` as the 5th agent:

```python
"scout": {
    "role": "Market Intelligence & Research Agent",
    "persona_file": "scout_persona.md",
    "knowledge_files": [
        "shams_knowledge_qcc_overview.md",
        "shams_knowledge_active_deals.md",
    ],
    "color": "#ef4444",
}
```

Scout gets scoped tools: `web_search`, `fetch_url`, `create_deal`, `update_deal`, `list_deals`. The `web_search` and `fetch_url` tools are currently unscoped (available to all agents) — they stay that way. The deal tools need their `agent` scope updated from `wakil`-only to include `scout`.

## New Tool: `list_deals`

Agents can currently create and update deals but cannot query the pipeline. Add a `list_deals` tool to `tools/deals.py`:

```python
@tool(
    name="list_deals",
    description="List deals in the pipeline. Filter by stage or deal type. Use to check what's already tracked before creating duplicates.",
    agent=None,  # Available to all agents
    schema={
        "properties": {
            "stage": {"type": "string", "enum": ["lead", "researching", "evaluating", "loi", "due_diligence", "closing", "closed", "dead"]},
            "limit": {"type": "integer", "default": 20},
        },
    },
)
```

Wraps existing `memory.get_deals(stage, limit)`.

## Deal Tool Scope Change

Currently `create_deal` and `update_deal` are scoped to `agent="wakil"`. Change to `agent=None` (available to all agents), since both Scout and Wakil need access. Scout creates leads; Wakil advances them through legal stages.

## Scout Sweep — Step 6 of Overnight Loop

New function `_step_scout_sweep()` in `standup.py`. Runs during the 3am overnight loop after the forgetting check.

### How it works

1. Load existing deals from the pipeline (to avoid duplicates)
2. Call `call_agent("scout", prompt)` with a structured research prompt
3. Scout uses `web_search` and `fetch_url` to research, then `list_deals` to check for duplicates, then `create_deal` for new findings
4. Parse Scout's response for a structured summary of findings
5. For deals scored 8+, draft an outreach message (stored in the deal's `notes` field)
6. Return results for standup delivery

### Research prompt

The prompt rotates search queries to avoid repetition. Each night, Scout runs:

**Always (3 core queries):**
- Acquisition targets: `"coffee roaster for sale" OR "cafe for sale" NJ 2026`
- Real estate: `commercial space lease Somerville OR Clifton OR Plainfield NJ`
- Industry news: `specialty coffee industry news`

**Rotating (2-3 per day, cycling through this pool based on day-of-week):**
- `"coffee roaster" restructuring OR closing NJ`
- `NJ small business acquisition opportunities`
- `commercial real estate coffee Middlesex OR Union OR Passaic county`
- `specialty coffee M&A 2026`
- `NJ small business grants OR incentives 2026`
- `coffee equipment auction OR liquidation NJ NY`
- `new coffee roaster opening NJ`

The prompt instructs Scout to:
- Search each query using `web_search`
- Follow up on promising results with `fetch_url`
- Check existing deals with `list_deals` before creating duplicates
- Score findings 1-10 based on: relevance to QCC, financial fit, location, timing
- Only create deals for findings scoring 6+
- For 8+ scores, draft a brief outreach message in the deal notes

### Structured response format

Scout returns findings in a structured format that `_step_scout_sweep()` parses:

```
FINDING: <title>
TYPE: acquisition|real_estate|partnership|vendor|regulatory|competitor
SCORE: <1-10>
DEAL_ID: <id if created, or EXISTING:<id> if already tracked>
SUMMARY: <one paragraph>
OUTREACH: <draft message or NONE>
---
```

### Deduplication

Before creating a deal, Scout is instructed to call `list_deals` and check for existing deals with similar titles or locations. If a match exists, Scout calls `update_deal` to add a note instead of creating a duplicate.

## Overnight Loop Integration

`_step_scout_sweep()` becomes step 6 in `run_overnight_loop()`, after the forgetting check. Results structure:

```json
{
  "scout": {
    "findings": [
      {
        "title": "Java Joe's Roasters — For Sale",
        "type": "acquisition",
        "score": 8,
        "deal_id": 42,
        "summary": "Listed on BizBuySell, 2 years operating...",
        "outreach": "Hi, I saw your listing..."
      }
    ],
    "searches_run": 5,
    "new_deals": 2,
    "updated_deals": 1
  }
}
```

Error handling: If Scout's sweep fails, the overnight loop continues (same pattern as other steps — log error, set status to "partial").

## Standup Integration

### Overview message

Add a Scout line to `_build_overview_message()`:

```
🔍 2 new leads · 1 deal updated
```

### Drip-feed action items

Scout findings appear after reminders in the action item order. For each finding with score 8+ and an outreach draft:

```
🔍 Scout: Java Joe's Roasters (Somerville)
Listed for sale, 2 years operating, $180k asking. Equipment included.
Score: 8/10

Draft outreach: "Hi, I came across your listing on BizBuySell and wanted to reach out. I run Queen City Coffee Roasters and we're exploring growth opportunities in the Somerville area. Would you be open to a conversation?"

[✓ Save draft]  [✏️ Edit]  [Skip]  [Create mission]
```

The buttons reuse the existing standup callback infrastructure:
- **Save draft** → `su_send` callback (but for Scout findings, this saves the outreach as a Gmail draft if there's an email, or just confirms it)
- **Edit** → `su_edit` callback (same edit flow — Shams quotes the draft, MJ types new version)
- **Skip** → `su_skip` callback
- **Create mission** → `su_mission` callback (creates a mission to follow up on this deal)

Findings scored 6-7 (created as deals but no outreach) appear as informational items:

```
🔍 Scout: New competitor — Brick City Roasters (Newark)
Opened last month, wholesale-focused. Score: 6/10

[Got it]  [Create mission]
```

## Files Changed

| File | Change |
|------|--------|
| `agents/registry.py` | Add `scout` agent entry (5th agent) |
| `tools/deals.py` | Add `list_deals` tool; change `create_deal`/`update_deal` scope from `wakil` to `None` |
| `standup.py` | Add `_step_scout_sweep()` as step 6 in overnight loop |
| `standup.py` | Update `_build_overview_message()` with Scout line |
| `standup.py` | Update `_build_action_items()` to include Scout findings |
| `tests/test_standup.py` | Add tests for Scout sweep and standup integration |

## What This Does NOT Include

- No Shopify/Klaviyo/Recharge integration — separate sub-project
- No autonomous follow-up on existing deals — Scout only creates new leads and drafts initial outreach
- No dedicated Scout dashboard page — findings show up in the existing deals page + morning standup
- No BizBuySell/LoopNet API integration — Scout uses web search, not direct API access
- No deal scoring model training — scoring is prompt-based via Scout's judgment
