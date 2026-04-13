# Scout: Autonomous Deal Flow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register Scout as the 5th agent with autonomous daily web research across 6 domains, deal pipeline management, outreach drafting, and morning standup integration.

**Architecture:** Scout is added to `agents/registry.py` with scoped tools (web search, fetch URL, deal CRUD). A new `_step_scout_sweep()` function in `standup.py` calls `call_agent("scout", prompt)` during the overnight loop, then surfaces findings in the morning standup drip-feed using the existing button infrastructure.

**Tech Stack:** Python 3.9+ (`from __future__ import annotations`), Claude API via `call_agent()`, existing web search tools, PostgreSQL deals table

**Spec:** `docs/superpowers/specs/2026-04-13-scout-autonomous-deal-flow-design.md`

---

### File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `agents/registry.py` | Add scout as 5th agent | Modify |
| `tools/deals.py` | Add `list_deals` tool, unscope deal tools from wakil-only | Modify |
| `standup.py` | Add `_step_scout_sweep()` as step 6, update overview + action items | Modify |
| `tests/test_standup.py` | Tests for scout sweep, list_deals, overview message update | Modify |

---

### Task 1: Register Scout Agent + Add list_deals Tool

**Files:**
- Modify: `agents/registry.py:17-53` (AGENTS dict)
- Modify: `tools/deals.py` (add list_deals, change agent scope)
- Modify: `tests/test_standup.py` (add tests)

- [ ] **Step 1: Write test for Scout agent registration**

Append to `tests/test_standup.py`:

```python
def test_scout_agent_registered():
    """Test that Scout is registered as an agent."""
    from agents.registry import AGENTS, build_agent_system_prompt
    assert "scout" in AGENTS
    assert AGENTS["scout"]["role"] == "Market Intelligence & Research Agent"
    prompt = build_agent_system_prompt("scout")
    assert "Scout" in prompt


def test_list_deals_tool_exists():
    """Test that list_deals tool is registered."""
    from tools.registry import discover_tools, get_tool_definitions
    discover_tools()
    all_tools = get_tool_definitions()
    tool_names = [t["name"] for t in all_tools]
    assert "list_deals" in tool_names


def test_deal_tools_available_to_scout():
    """Test that deal tools are available to scout agent."""
    from tools.registry import discover_tools, get_tool_definitions
    discover_tools()
    scout_tools = get_tool_definitions(agent="scout")
    tool_names = [t["name"] for t in scout_tools]
    assert "create_deal" in tool_names
    assert "update_deal" in tool_names
    assert "list_deals" in tool_names
    assert "web_search" in tool_names
    assert "fetch_url" in tool_names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_scout_agent_registered tests/test_standup.py::test_list_deals_tool_exists tests/test_standup.py::test_deal_tools_available_to_scout -v`
Expected: FAIL — `AssertionError: assert 'scout' in AGENTS`

- [ ] **Step 3: Add Scout to agents/registry.py**

In `agents/registry.py`, add the scout entry to the `AGENTS` dict after the `leo` entry (after line 52):

```python
    "scout": {
        "role": "Market Intelligence & Research Agent",
        "persona_file": "scout_persona.md",
        "knowledge_files": [
            "shams_knowledge_qcc_overview.md",
            "shams_knowledge_active_deals.md",
        ],
        "color": "#ef4444",
    },
```

Also update the module docstring on line 1 from `"""Agent registry — defines 4 agents` to `"""Agent registry — defines 5 agents`.

- [ ] **Step 4: Add list_deals tool and unscope deal tools in tools/deals.py**

In `tools/deals.py`, change `agent="wakil"` to `agent=None` on both `create_deal` (line 11) and `update_deal` (line 49).

Then append the `list_deals` tool at the end of `tools/deals.py`:

```python
@tool(
    name="list_deals",
    description="List deals in the pipeline. Filter by stage to see what's being tracked. Use before creating deals to avoid duplicates.",
    schema={
        "properties": {
            "stage": {"type": "string", "description": "Filter by stage", "enum": ["lead", "researching", "evaluating", "loi", "due_diligence", "closing", "closed", "dead"]},
            "limit": {"type": "integer", "description": "Max deals to return (default 20)", "default": 20},
        },
    },
)
def list_deals(stage: str = None, limit: int = 20) -> str:
    import memory

    deals = memory.get_deals(stage=stage, limit=limit)
    if not deals:
        return "No deals in pipeline." + (f" (filtered by stage={stage})" if stage else "")

    lines = []
    for d in deals:
        score = d.get("score", 0)
        stage_val = d.get("stage", "?")
        lines.append(
            f"#{d['id']} [{stage_val}] {d['title']} — score:{score}/10"
            + (f" ${d['value']:,.0f}" if d.get("value") else "")
            + (f" — {d.get('location', '')}" if d.get("location") else "")
        )
    return f"{len(deals)} deal(s):\n" + "\n".join(lines)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_scout_agent_registered tests/test_standup.py::test_list_deals_tool_exists tests/test_standup.py::test_deal_tools_available_to_scout -v`
Expected: PASS

- [ ] **Step 6: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add agents/registry.py tools/deals.py tests/test_standup.py
git commit -m "feat: register Scout as 5th agent + add list_deals tool + unscope deal tools"
```

---

### Task 2: Scout Sweep — Step 6 of Overnight Loop

**Files:**
- Modify: `standup.py` (add `_step_scout_sweep()` + wire into `run_overnight_loop()`)
- Modify: `tests/test_standup.py` (add test)

- [ ] **Step 1: Write test for scout sweep**

Append to `tests/test_standup.py`:

```python
def test_scout_sweep_structure():
    """Test that _step_scout_sweep returns structured results."""
    from unittest.mock import patch, MagicMock
    import standup

    with patch("standup.memory") as mock_memory, \
         patch("standup._call_scout") as mock_call:

        mock_memory.get_deals.return_value = []
        mock_call.return_value = {
            "findings": [],
            "searches_run": 5,
            "new_deals": 0,
            "updated_deals": 0,
        }

        result = standup._step_scout_sweep()

        assert "findings" in result
        assert "searches_run" in result
        assert "new_deals" in result
        assert "updated_deals" in result
        mock_call.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_scout_sweep_structure -v`
Expected: FAIL — `AttributeError: module 'standup' has no attribute '_step_scout_sweep'`

- [ ] **Step 3: Add `_step_scout_sweep()` and `_call_scout()` to standup.py**

Add these two functions after `_draft_reminder_work_product()` and before `_build_overnight_summary()` in `standup.py`:

```python
# ── Scout sweep ────────────────────────────────────────────────────────────


def _step_scout_sweep() -> dict:
    """Run Scout's daily research sweep across all 6 domains."""
    result = _call_scout()
    return result


def _call_scout() -> dict:
    """Call the Scout agent with a research prompt and parse results."""
    from agents.registry import call_agent

    # Determine which rotating queries to run today (cycle by day of week)
    rotating_queries = [
        '"coffee roaster" restructuring OR closing NJ',
        'NJ small business acquisition opportunities',
        'commercial real estate coffee Middlesex OR Union OR Passaic county',
        'specialty coffee M&A 2026',
        'NJ small business grants OR incentives 2026',
        'coffee equipment auction OR liquidation NJ NY',
        'new coffee roaster opening NJ',
    ]
    day_of_week = datetime.now(timezone.utc).weekday()  # 0=Monday
    # Pick 2 rotating queries based on day
    rotate_start = (day_of_week * 2) % len(rotating_queries)
    todays_rotating = [
        rotating_queries[rotate_start % len(rotating_queries)],
        rotating_queries[(rotate_start + 1) % len(rotating_queries)],
    ]

    core_queries = [
        '"coffee roaster for sale" OR "cafe for sale" NJ 2026',
        'commercial space lease Somerville OR Clifton OR Plainfield NJ',
        'specialty coffee industry news',
    ]
    all_queries = core_queries + todays_rotating

    # Build existing deals context for dedup
    existing_deals = memory.get_deals(limit=50)
    deals_context = ""
    if existing_deals:
        deals_context = "\n\nExisting deals in pipeline (check before creating duplicates):\n"
        for d in existing_deals:
            deals_context += f"- #{d['id']} [{d.get('stage', '?')}] {d['title']}"
            if d.get("location"):
                deals_context += f" ({d['location']})"
            deals_context += "\n"

    prompt = (
        f"Run your daily research sweep. Search each of these queries using web_search, "
        f"then follow up on promising results with fetch_url.\n\n"
        f"Queries to search:\n"
        + "\n".join(f"- {q}" for q in all_queries)
        + f"\n{deals_context}\n"
        f"For each finding worth tracking:\n"
        f"1. Check existing deals with list_deals to avoid duplicates\n"
        f"2. If it's new and scores 6+, create it with create_deal\n"
        f"3. If it matches an existing deal, update it with update_deal (add a note)\n"
        f"4. For deals scored 8+, include a draft outreach message in the notes\n\n"
        f"Score findings 1-10 based on: relevance to QCC, financial fit, location, timing.\n\n"
        f"After all searches, summarize your findings in this exact format "
        f"(one block per finding, separated by ---):\n\n"
        f"FINDING: <title>\n"
        f"TYPE: acquisition|real_estate|partnership|vendor|regulatory|competitor\n"
        f"SCORE: <1-10>\n"
        f"DEAL_ID: <id if created, or EXISTING:<id> if updated, or SKIP if below 6>\n"
        f"SUMMARY: <one paragraph>\n"
        f"OUTREACH: <draft message or NONE>\n"
        f"---"
    )

    # Call Scout agent — it has web_search, fetch_url, create_deal, update_deal, list_deals
    scout_response = call_agent("scout", prompt)

    # Parse findings from Scout's response
    findings = []
    new_deals = 0
    updated_deals = 0

    for block in scout_response.split("---"):
        block = block.strip()
        if not block:
            continue

        fields = {}
        current_key = None
        for line in block.split("\n"):
            matched = False
            for key in ("FINDING", "TYPE", "SCORE", "DEAL_ID", "SUMMARY", "OUTREACH"):
                if line.upper().startswith(key + ":"):
                    _, _, v = line.partition(":")
                    fields[key] = v.strip()
                    current_key = key
                    matched = True
                    break
            if not matched and current_key in ("SUMMARY", "OUTREACH"):
                fields[current_key] = fields.get(current_key, "") + "\n" + line

        if not fields.get("FINDING"):
            continue

        try:
            score = int(fields.get("SCORE", "0"))
        except ValueError:
            score = 0

        deal_id_raw = fields.get("DEAL_ID", "")
        deal_id = None
        if deal_id_raw.startswith("EXISTING:"):
            try:
                deal_id = int(deal_id_raw.split(":")[1])
            except (ValueError, IndexError):
                pass
            updated_deals += 1
        elif deal_id_raw not in ("SKIP", ""):
            try:
                deal_id = int(deal_id_raw)
            except ValueError:
                pass
            new_deals += 1

        outreach = fields.get("OUTREACH", "").strip()
        if outreach.upper() == "NONE":
            outreach = ""

        findings.append({
            "title": fields.get("FINDING", ""),
            "type": fields.get("TYPE", "other"),
            "score": score,
            "deal_id": deal_id,
            "summary": fields.get("SUMMARY", "").strip(),
            "outreach": outreach,
        })

    return {
        "findings": findings,
        "searches_run": len(all_queries),
        "new_deals": new_deals,
        "updated_deals": updated_deals,
    }
```

- [ ] **Step 4: Wire scout sweep into `run_overnight_loop()` as step 6**

In `standup.py`, in the `run_overnight_loop()` function, add this after the Step 5 forgetting check block (after line 104, before the `# Save results` comment):

```python
    # Step 6: Scout research sweep
    try:
        results["scout"] = _step_scout_sweep()
        memory.log_activity("scout", "overnight", "Scout sweep complete", {
            "findings": len(results["scout"]["findings"]),
            "new_deals": results["scout"]["new_deals"],
            "searches_run": results["scout"]["searches_run"],
        })
    except Exception as e:
        logger.error(f"Overnight Scout sweep failed: {e}", exc_info=True)
        results["scout"] = {"findings": [], "searches_run": 0, "new_deals": 0, "updated_deals": 0}
        status = "partial"
```

Also add `"scout"` to the initial `results` dict at the top of `run_overnight_loop()`. Find the line:

```python
        "reminders": [],
    }
```

And add after it (inside the dict, before the closing `}`):

```python
        "scout": {"findings": [], "searches_run": 0, "new_deals": 0, "updated_deals": 0},
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_scout_sweep_structure -v`
Expected: PASS

- [ ] **Step 6: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add standup.py tests/test_standup.py
git commit -m "feat: add Scout sweep as step 6 of overnight loop"
```

---

### Task 3: Standup Integration — Overview + Drip-Feed for Scout Findings

**Files:**
- Modify: `standup.py` (update `_build_overview_message`, `_build_action_items`, `_send_next_standup_item`, `_build_overnight_summary`)
- Modify: `tests/test_standup.py` (update test)

- [ ] **Step 1: Write test for Scout in overview message**

Append to `tests/test_standup.py`:

```python
def test_overview_message_includes_scout():
    """Test that overview message includes Scout findings."""
    import standup

    results = {
        "email": {"reply": [], "read": [], "archived": [], "archive_summary": ""},
        "mercury": {"balances": {}, "grand_total": 0, "alerts": []},
        "rumi": {},
        "calendar": {"events": [], "prep_briefs": []},
        "reminders": [],
        "scout": {
            "findings": [
                {"title": "Test Lead", "score": 8, "type": "acquisition"},
                {"title": "Updated Deal", "score": 6, "type": "real_estate"},
            ],
            "searches_run": 5,
            "new_deals": 2,
            "updated_deals": 1,
        },
    }

    msg = standup._build_overview_message(results)
    assert "2 new leads" in msg or "2 leads" in msg
    assert "1 deal updated" in msg or "1 updated" in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_overview_message_includes_scout -v`
Expected: FAIL — no Scout line in overview

- [ ] **Step 3: Update `_build_overview_message` to include Scout line**

In `standup.py`, in `_build_overview_message()`, add this after the reminders section (after the line `lines.append(f"🔔 {len(reminders)} things you might be forgetting")`):

```python
    # Scout
    scout = results.get("scout", {})
    scout_findings = scout.get("findings", [])
    new_deals = scout.get("new_deals", 0)
    updated_deals = scout.get("updated_deals", 0)
    if new_deals or updated_deals:
        parts = []
        if new_deals:
            parts.append(f"{new_deals} new lead{'s' if new_deals != 1 else ''}")
        if updated_deals:
            parts.append(f"{updated_deals} deal{'s' if updated_deals != 1 else ''} updated")
        lines.append(f"🔍 {' · '.join(parts)}")
```

- [ ] **Step 4: Update `_build_action_items` to include Scout findings**

In `standup.py`, in `_build_action_items()`, add this after the reminders section (after the `# 3. Reminders` loop, before `return items`):

```python
    # 4. Scout findings (high-score with outreach, then informational)
    scout = results.get("scout", {})
    for f in scout.get("findings", []):
        if f.get("score", 0) >= 8 and f.get("outreach"):
            items.append({
                "type": "scout_outreach",
                "title": f.get("title", ""),
                "finding_type": f.get("type", ""),
                "score": f.get("score", 0),
                "summary": f.get("summary", ""),
                "outreach": f.get("outreach", ""),
                "deal_id": f.get("deal_id"),
            })
        elif f.get("score", 0) >= 6:
            items.append({
                "type": "scout_info",
                "title": f.get("title", ""),
                "finding_type": f.get("type", ""),
                "score": f.get("score", 0),
                "summary": f.get("summary", ""),
                "deal_id": f.get("deal_id"),
            })
```

- [ ] **Step 5: Update `_send_next_standup_item` to render Scout items**

In `standup.py`, in `_send_next_standup_item()`, add these two blocks after the `elif item["type"] == "reminder":` block (before the closing of the function):

```python
    elif item["type"] == "scout_outreach":
        msg = (
            f"🔍 Scout: {item['title']}\n"
            f"{item['summary']}\n"
            f"Score: {item['score']}/10\n\n"
            f"Draft outreach: {item['outreach']}"
        )
        buttons = [
            {"text": "✓ Save draft", "callback_data": f"su_ok:{idx}"},
            {"text": "✏️ Edit", "callback_data": f"su_edit:{idx}"},
            {"text": "Skip", "callback_data": f"su_skip:{idx}"},
            {"text": "Create mission", "callback_data": f"su_mission:{idx}"},
        ]
        send_telegram_with_buttons(chat_id, msg, buttons)

    elif item["type"] == "scout_info":
        msg = (
            f"🔍 Scout: {item['title']}\n"
            f"{item['summary']}\n"
            f"Score: {item['score']}/10"
        )
        buttons = [
            {"text": "Got it", "callback_data": f"su_ok:{idx}"},
            {"text": "Create mission", "callback_data": f"su_mission:{idx}"},
        ]
        send_telegram_with_buttons(chat_id, msg, buttons)
```

- [ ] **Step 6: Update `_build_overnight_summary` to include Scout**

In `standup.py`, in `_build_overnight_summary()`, add this after the reminders section (after the `if reminders:` block, before `return " | ".join(parts)`):

```python
    scout = results.get("scout", {})
    if scout.get("findings"):
        parts.append(f"Scout: {len(scout['findings'])} findings, {scout.get('new_deals', 0)} new deals")
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_overview_message_includes_scout -v`
Expected: PASS

- [ ] **Step 8: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add standup.py tests/test_standup.py
git commit -m "feat: integrate Scout findings into standup — overview + drip-feed"
```

---

### Task 4: Deploy + Smoke Test

**Files:**
- None (deployment only)

- [ ] **Step 1: Push to GitHub**

```bash
cd /Users/mj/code/Shams && git push origin main
```

- [ ] **Step 2: Monitor Railway deploy**

```bash
/Users/mj/.local/bin/railway service status --all
```

Wait for `shams` status to show `SUCCESS`.

- [ ] **Step 3: Verify scheduler logs**

```bash
/Users/mj/.local/bin/railway logs --service shams 2>&1 | grep -i "scheduler\|scout" | tail -10
```

Confirm Scout agent is registered (should see 5 agents in startup logs).

- [ ] **Step 4: Verify Scout agent is callable**

Send a Telegram message to Shams: "Ask Scout to search for coffee roasters for sale in NJ"

Confirm:
- Scout uses web_search tool
- Scout returns findings with sources
- Results are coherent

- [ ] **Step 5: Tag the release**

```bash
cd /Users/mj/code/Shams && git tag -a shams-v2-scout -m "Shams v2: Scout autonomous deal flow agent"
git push origin shams-v2-scout
```
