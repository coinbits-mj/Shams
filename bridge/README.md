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
