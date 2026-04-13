# macOS Communication Bridge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local macOS bridge script that reads iMessage + WhatsApp databases every 30 minutes, pushes touchpoints to the Shams API, and executes outbound messaging commands (iMessage via AppleScript, WhatsApp via deep link).

**Architecture:** A single Python script (`bridge/shams_bridge.py`) reads three SQLite databases on the local Mac, extracts touchpoint metadata (contact handle, direction, timestamp — no message content), and POSTs to `POST /api/touchpoints` on Shams. It also polls `GET /api/bridge/pending` for outbound commands. A LaunchAgent plist auto-runs it every 30 minutes.

**Tech Stack:** Python 3 (macOS built-in or Homebrew), SQLite3, requests, AppleScript (osascript), macOS LaunchAgent

**Spec:** `docs/superpowers/specs/2026-04-13-relationship-intelligence-design.md` (Bridge section)

---

### File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `bridge/shams_bridge.py` | Main bridge script — read DBs, push touchpoints, execute commands | **Create** |
| `bridge/com.shams.bridge.plist` | LaunchAgent config for auto-running every 30 min | **Create** |
| `bridge/install.sh` | One-command install script | **Create** |
| `bridge/README.md` | Setup instructions | **Create** |

---

### Task 1: Bridge Script — iMessage + WhatsApp Reader

**Files:**
- Create: `bridge/shams_bridge.py`

- [ ] **Step 1: Create the bridge directory**

```bash
mkdir -p /Users/mj/code/Shams/bridge
```

- [ ] **Step 2: Create `bridge/shams_bridge.py`**

```python
#!/usr/bin/env python3
"""Shams Communication Bridge — reads iMessage + WhatsApp, pushes touchpoints to Shams API.

Runs locally on macOS. Reads SQLite databases for contact touchpoint metadata only
(who, when, direction). Never reads message content.

Usage:
    python3 shams_bridge.py              # Run once
    python3 shams_bridge.py --daemon     # Run continuously (every 30 min)

Environment:
    SHAMS_API_URL       - Shams API URL (e.g. https://app.myshams.ai)
    SHAMS_BRIDGE_TOKEN  - Bridge API token (matches BRIDGE_API_TOKEN on server)
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("shams-bridge")

# ── Config ─────────────────────────────────────────────────────────────────

API_URL = os.environ.get("SHAMS_API_URL", "https://app.myshams.ai")
BRIDGE_TOKEN = os.environ.get("SHAMS_BRIDGE_TOKEN", "")

STATE_FILE = Path.home() / ".shams_bridge_state.json"

IMESSAGE_DB = Path.home() / "Library" / "Messages" / "chat.db"
WHATSAPP_CHAT_DB = (
    Path.home() / "Library" / "Group Containers" /
    "group.net.whatsapp.WhatsApp.shared" / "ChatStorage.sqlite"
)
WHATSAPP_CONTACTS_DB = (
    Path.home() / "Library" / "Group Containers" /
    "group.net.whatsapp.WhatsApp.shared" / "ContactsV2.sqlite"
)

# iMessage timestamps are in Apple's "Core Data" epoch: seconds since 2001-01-01
# But the `date` column uses nanoseconds since 2001-01-01
APPLE_EPOCH_OFFSET = 978307200  # seconds between Unix epoch and Apple epoch


# ── State management ──────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"imessage_last": 0, "whatsapp_last": 0.0}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── iMessage reader ───────────────────────────────────────────────────────

def read_imessage(since_timestamp: int) -> list[dict]:
    """Read new iMessage touchpoints since last run."""
    if not IMESSAGE_DB.exists():
        log.warning("iMessage database not found: %s", IMESSAGE_DB)
        return []

    touchpoints = []
    try:
        conn = sqlite3.connect(f"file:{IMESSAGE_DB}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(
            "SELECT h.id, m.is_from_me, m.date "
            "FROM message m JOIN handle h ON m.handle_id = h.ROWID "
            "WHERE m.date > ? ORDER BY m.date ASC",
            (since_timestamp,),
        )
        for handle_id, is_from_me, date_val in cur.fetchall():
            # Convert Apple nanosecond timestamp to Unix timestamp
            unix_ts = (date_val / 1_000_000_000) + APPLE_EPOCH_OFFSET
            iso_time = datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()

            touchpoints.append({
                "source": "imessage",
                "contact_handle": handle_id,
                "contact_name": None,
                "contact_phone": handle_id if not handle_id.startswith("mailto:") else None,
                "direction": "outbound" if is_from_me else "inbound",
                "timestamp": iso_time,
                "_raw_date": date_val,
            })
        conn.close()
    except Exception as e:
        log.error("iMessage read failed: %s", e)

    log.info("iMessage: %d new touchpoints", len(touchpoints))
    return touchpoints


# ── WhatsApp reader ───────────────────────────────────────────────────────

def load_whatsapp_contacts() -> dict[str, dict]:
    """Load WhatsApp contact names from ContactsV2.sqlite."""
    contacts = {}
    if not WHATSAPP_CONTACTS_DB.exists():
        return contacts

    try:
        conn = sqlite3.connect(f"file:{WHATSAPP_CONTACTS_DB}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(
            "SELECT ZWHATSAPPID, ZFULLNAME, ZPHONENUMBER FROM ZWAADDRESSBOOKCONTACT "
            "WHERE ZWHATSAPPID IS NOT NULL AND ZFULLNAME IS NOT NULL"
        )
        for wa_id, name, phone in cur.fetchall():
            contacts[wa_id] = {"name": name, "phone": phone}
        conn.close()
    except Exception as e:
        log.error("WhatsApp contacts read failed: %s", e)

    log.info("WhatsApp contacts loaded: %d", len(contacts))
    return contacts


def read_whatsapp(since_timestamp: float, contacts: dict) -> list[dict]:
    """Read new WhatsApp touchpoints since last run."""
    if not WHATSAPP_CHAT_DB.exists():
        log.warning("WhatsApp database not found: %s", WHATSAPP_CHAT_DB)
        return []

    touchpoints = []
    try:
        conn = sqlite3.connect(f"file:{WHATSAPP_CHAT_DB}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(
            "SELECT ZFROMJID, ZTOJID, ZISFROMME, ZMESSAGEDATE "
            "FROM ZWAMESSAGE "
            "WHERE ZMESSAGEDATE > ? ORDER BY ZMESSAGEDATE ASC",
            (since_timestamp,),
        )
        for from_jid, to_jid, is_from_me, msg_date in cur.fetchall():
            # Determine the other party's JID
            other_jid = to_jid if is_from_me else from_jid
            if not other_jid:
                continue

            # Skip group chats (contain @g.us)
            if "@g.us" in other_jid:
                continue

            # Look up contact name
            contact_info = contacts.get(other_jid, {})
            name = contact_info.get("name")
            phone = contact_info.get("phone")

            # Extract phone from JID if not in contacts (format: 19735551234@s.whatsapp.net)
            if not phone and "@" in other_jid:
                raw_number = other_jid.split("@")[0]
                if raw_number.isdigit():
                    phone = f"+{raw_number}"

            # WhatsApp timestamps are seconds since 2001-01-01 (Apple epoch)
            unix_ts = msg_date + APPLE_EPOCH_OFFSET
            iso_time = datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()

            touchpoints.append({
                "source": "whatsapp",
                "contact_handle": other_jid,
                "contact_name": name,
                "contact_phone": phone,
                "direction": "outbound" if is_from_me else "inbound",
                "timestamp": iso_time,
                "_raw_date": msg_date,
            })
        conn.close()
    except Exception as e:
        log.error("WhatsApp read failed: %s", e)

    log.info("WhatsApp: %d new touchpoints", len(touchpoints))
    return touchpoints


# ── API communication ─────────────────────────────────────────────────────

def push_touchpoints(touchpoints: list[dict]) -> int:
    """Push touchpoints to Shams API. Returns count processed."""
    if not touchpoints:
        return 0
    if not BRIDGE_TOKEN:
        log.error("SHAMS_BRIDGE_TOKEN not set — cannot push touchpoints")
        return 0

    # Remove internal fields
    payload = []
    for tp in touchpoints:
        clean = {k: v for k, v in tp.items() if not k.startswith("_")}
        payload.append(clean)

    data = json.dumps({"touchpoints": payload}).encode()
    req = urllib.request.Request(
        f"{API_URL}/api/touchpoints",
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Bridge-Token": BRIDGE_TOKEN,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            processed = result.get("processed", 0)
            log.info("Pushed %d touchpoints, %d processed", len(payload), processed)
            return processed
    except Exception as e:
        log.error("Push touchpoints failed: %s", e)
        return 0


def poll_commands() -> list[dict]:
    """Poll for pending outbound commands."""
    if not BRIDGE_TOKEN:
        return []

    req = urllib.request.Request(
        f"{API_URL}/api/bridge/pending",
        headers={"X-Bridge-Token": BRIDGE_TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return result.get("commands", [])
    except Exception as e:
        log.error("Poll commands failed: %s", e)
        return []


def ack_command(command_id: int, status: str = "sent"):
    """Acknowledge command execution."""
    data = json.dumps({"id": command_id, "status": status}).encode()
    req = urllib.request.Request(
        f"{API_URL}/api/bridge/ack",
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Bridge-Token": BRIDGE_TOKEN,
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        log.error("Ack command %d failed: %s", command_id, e)


# ── Command execution ─────────────────────────────────────────────────────

def execute_command(cmd: dict):
    """Execute an outbound messaging command."""
    channel = cmd.get("channel", "")
    recipient = cmd.get("recipient", "")
    message = cmd.get("message", "")
    cmd_id = cmd.get("id")

    if not recipient or not message:
        log.warning("Skipping command %s: missing recipient or message", cmd_id)
        if cmd_id:
            ack_command(cmd_id, "failed")
        return

    try:
        if channel == "imessage":
            send_imessage(recipient, message)
            log.info("iMessage sent to %s", recipient)
            if cmd_id:
                ack_command(cmd_id, "sent")

        elif channel == "whatsapp":
            open_whatsapp(recipient, message)
            log.info("WhatsApp opened for %s", recipient)
            if cmd_id:
                ack_command(cmd_id, "sent")

        else:
            log.warning("Unknown channel: %s", channel)
            if cmd_id:
                ack_command(cmd_id, "failed")

    except Exception as e:
        log.error("Command execution failed for %s: %s", channel, e)
        if cmd_id:
            ack_command(cmd_id, "failed")


def send_imessage(recipient: str, message: str):
    """Send an iMessage via AppleScript."""
    # Escape message for AppleScript
    escaped = message.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'tell application "Messages"\n'
        f'    set targetService to 1st account whose service type = iMessage\n'
        f'    set targetBuddy to participant "{recipient}" of targetService\n'
        f'    send "{escaped}" to targetBuddy\n'
        f'end tell'
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript failed: {result.stderr.strip()}")


def open_whatsapp(recipient: str, message: str):
    """Open WhatsApp with a pre-filled message. MJ taps send."""
    # Strip + and non-digits from phone number
    phone = "".join(c for c in recipient if c.isdigit())
    encoded_msg = urllib.parse.quote(message)
    url = f"whatsapp://send?phone={phone}&text={encoded_msg}"
    subprocess.run(["open", url], timeout=10)


# ── Main loop ─────────────────────────────────────────────────────────────

def run_once():
    """Run one cycle: read databases, push touchpoints, execute commands."""
    state = load_state()

    # Read iMessage
    imessage_touchpoints = read_imessage(state.get("imessage_last", 0))

    # Read WhatsApp
    wa_contacts = load_whatsapp_contacts()
    whatsapp_touchpoints = read_whatsapp(state.get("whatsapp_last", 0.0), wa_contacts)

    # Push all touchpoints
    all_touchpoints = imessage_touchpoints + whatsapp_touchpoints
    if all_touchpoints:
        push_touchpoints(all_touchpoints)

    # Update high-water marks
    if imessage_touchpoints:
        state["imessage_last"] = max(tp["_raw_date"] for tp in imessage_touchpoints)
    if whatsapp_touchpoints:
        state["whatsapp_last"] = max(tp["_raw_date"] for tp in whatsapp_touchpoints)
    save_state(state)

    # Poll and execute commands
    commands = poll_commands()
    for cmd in commands:
        execute_command(cmd)

    log.info("Cycle complete: %d iMessage, %d WhatsApp touchpoints, %d commands",
             len(imessage_touchpoints), len(whatsapp_touchpoints), len(commands))


def main():
    if "--daemon" in sys.argv:
        log.info("Starting bridge daemon (30 min interval)")
        while True:
            try:
                run_once()
            except Exception as e:
                log.error("Cycle failed: %s", e)
            time.sleep(1800)  # 30 minutes
    else:
        run_once()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run a test cycle**

```bash
cd /Users/mj/code/Shams && python3 bridge/shams_bridge.py
```

Expected: Reads databases, logs touchpoint counts. Will fail to push (no BRIDGE_API_TOKEN set on server yet) but should read successfully.

- [ ] **Step 4: Commit**

```bash
git add bridge/shams_bridge.py
git commit -m "feat: create macOS bridge script — reads iMessage + WhatsApp, pushes touchpoints"
```

---

### Task 2: LaunchAgent + Install Script

**Files:**
- Create: `bridge/com.shams.bridge.plist`
- Create: `bridge/install.sh`
- Create: `bridge/README.md`

- [ ] **Step 1: Create LaunchAgent plist**

Create `bridge/com.shams.bridge.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.shams.bridge</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/mj/Library/Application Support/Shams/shams_bridge.py</string>
    </array>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>SHAMS_API_URL</key>
        <string>https://app.myshams.ai</string>
        <key>SHAMS_BRIDGE_TOKEN</key>
        <string>REPLACE_WITH_TOKEN</string>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/shams-bridge.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/shams-bridge.log</string>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
```

- [ ] **Step 2: Create install script**

Create `bridge/install.sh`:

```bash
#!/bin/bash
# Shams Bridge Installer
# Installs the macOS communication bridge for iMessage + WhatsApp

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/Library/Application Support/Shams"
PLIST_SRC="$SCRIPT_DIR/com.shams.bridge.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.shams.bridge.plist"

echo "=== Shams Bridge Installer ==="
echo ""

# Check for required env vars
if [ -z "$SHAMS_BRIDGE_TOKEN" ]; then
    echo "ERROR: Set SHAMS_BRIDGE_TOKEN environment variable first."
    echo "  Generate a token and set it as BRIDGE_API_TOKEN on Railway."
    echo "  Then: export SHAMS_BRIDGE_TOKEN=<your-token>"
    exit 1
fi

# Create install directory
mkdir -p "$INSTALL_DIR"

# Copy bridge script
cp "$SCRIPT_DIR/shams_bridge.py" "$INSTALL_DIR/shams_bridge.py"
echo "✓ Bridge script installed to $INSTALL_DIR"

# Create plist with token substituted
sed "s|REPLACE_WITH_TOKEN|$SHAMS_BRIDGE_TOKEN|g" "$PLIST_SRC" > "$PLIST_DST"
echo "✓ LaunchAgent installed to $PLIST_DST"

# Unload if already loaded
launchctl unload "$PLIST_DST" 2>/dev/null || true

# Load the agent
launchctl load "$PLIST_DST"
echo "✓ Bridge started"

echo ""
echo "Bridge is now running every 30 minutes."
echo "Logs: /tmp/shams-bridge.log"
echo "State: ~/.shams_bridge_state.json"
echo ""
echo "To stop:  launchctl unload $PLIST_DST"
echo "To start: launchctl load $PLIST_DST"
echo "To test:  python3 '$INSTALL_DIR/shams_bridge.py'"
```

- [ ] **Step 3: Make install script executable**

```bash
chmod +x /Users/mj/code/Shams/bridge/install.sh
```

- [ ] **Step 4: Create README**

Create `bridge/README.md`:

```markdown
# Shams Communication Bridge

Local macOS script that reads iMessage + WhatsApp databases and pushes touchpoint data to Shams for relationship intelligence.

## What it does

Every 30 minutes:
1. Reads `~/Library/Messages/chat.db` (iMessage) — extracts contact handle, direction, timestamp
2. Reads WhatsApp's `ChatStorage.sqlite` — extracts contact JID, direction, timestamp
3. Maps WhatsApp JIDs to names via `ContactsV2.sqlite`
4. Pushes touchpoints to Shams API (`POST /api/touchpoints`)
5. Polls for outbound commands (`GET /api/bridge/pending`)
6. Executes commands: iMessage via AppleScript, WhatsApp via deep link

**No message content is ever read or transmitted.** Only: who, when, direction.

## Prerequisites

- macOS with iMessage signed in
- WhatsApp Desktop installed and linked
- Full Disk Access for Terminal/Python (System Settings → Privacy & Security → Full Disk Access)
- `BRIDGE_API_TOKEN` set on Railway (Shams server)

## Install

1. Generate a bridge token:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. Set it on Railway:
   ```bash
   railway variables --set BRIDGE_API_TOKEN=<your-token>
   ```

3. Install the bridge:
   ```bash
   export SHAMS_BRIDGE_TOKEN=<your-token>
   cd bridge && ./install.sh
   ```

## Verify

```bash
# Check if running
launchctl list | grep shams

# View logs
tail -f /tmp/shams-bridge.log

# Run manually
python3 ~/Library/Application\ Support/Shams/shams_bridge.py
```

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.shams.bridge.plist
rm ~/Library/LaunchAgents/com.shams.bridge.plist
rm -rf ~/Library/Application\ Support/Shams/
rm ~/.shams_bridge_state.json
```
```

- [ ] **Step 5: Commit**

```bash
git add bridge/
git commit -m "feat: add bridge LaunchAgent, install script, and README"
```

---

### Task 3: Set Bridge Token on Railway + Test End-to-End

**Files:**
- None (configuration + testing)

- [ ] **Step 1: Generate a bridge token**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Save the output — you'll need it in the next two steps.

- [ ] **Step 2: Set BRIDGE_API_TOKEN on Railway**

```bash
/Users/mj/.local/bin/railway variables --set BRIDGE_API_TOKEN=<token-from-step-1> --service shams
```

Then redeploy:

```bash
/Users/mj/.local/bin/railway service redeploy --service shams
```

- [ ] **Step 3: Install the bridge locally**

```bash
export SHAMS_BRIDGE_TOKEN=<token-from-step-1>
cd /Users/mj/code/Shams/bridge && ./install.sh
```

- [ ] **Step 4: Grant Full Disk Access**

Open System Settings → Privacy & Security → Full Disk Access. Add Terminal (or iTerm, whichever you use) and Python.

- [ ] **Step 5: Run a test cycle**

```bash
SHAMS_BRIDGE_TOKEN=<token> SHAMS_API_URL=https://app.myshams.ai python3 /Users/mj/code/Shams/bridge/shams_bridge.py
```

Check logs for:
- "iMessage: X new touchpoints"
- "WhatsApp: X new touchpoints"
- "Pushed X touchpoints, Y processed"

- [ ] **Step 6: Verify contacts were created on the server**

```bash
/Users/mj/.local/bin/railway run python3 -c "
import psycopg2, os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute('SELECT name, email, phone, channels, touchpoint_count FROM shams_contacts ORDER BY touchpoint_count DESC LIMIT 10')
for r in cur.fetchall():
    print(f'{r[0]} | {r[1] or r[2]} | channels={r[3]} | {r[4]} touchpoints')
"
```

- [ ] **Step 7: Tag the release**

```bash
cd /Users/mj/code/Shams && git push origin main
git tag -a shams-v2-bridge -m "Shams v2: macOS communication bridge — iMessage + WhatsApp"
git push origin shams-v2-bridge
```
