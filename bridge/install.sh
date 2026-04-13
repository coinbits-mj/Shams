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
