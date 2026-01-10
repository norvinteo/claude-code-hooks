#!/bin/bash
# Auto-Continue Script for Claude Code
#
# This script monitors the tmux pane for "STOP BLOCKED" messages
# and automatically sends "c" to continue.
#
# Usage:
#   1. Start Claude in a tmux session: tmux new -s claude
#   2. Run this script in another terminal: ./auto_continue.sh claude
#
# The script will monitor the tmux session and auto-continue when blocked.

SESSION_NAME="${1:-claude}"
CHECK_INTERVAL=2  # seconds between checks
LAST_BLOCK_LINE=""  # Track the last blocked message to avoid duplicates

echo "🤖 Auto-continue monitoring started for tmux session: $SESSION_NAME"
echo "   Press Ctrl+C to stop"

while true; do
    # Capture last 30 lines of the tmux pane
    OUTPUT=$(tmux capture-pane -t "$SESSION_NAME" -p -S -30 2>/dev/null)

    if [ $? -ne 0 ]; then
        echo "❌ tmux session '$SESSION_NAME' not found. Waiting..."
        sleep 5
        continue
    fi

    # Find the most recent "STOP BLOCKED" line
    BLOCK_LINE=$(echo "$OUTPUT" | grep -n "STOP BLOCKED" | tail -1)

    if [ -n "$BLOCK_LINE" ]; then
        # Check if this is a NEW block message (different from last one we handled)
        if [ "$BLOCK_LINE" != "$LAST_BLOCK_LINE" ]; then
            # Check if the pane ends with a prompt waiting for input
            # Look for Claude's input indicator (>) at the end
            LAST_LINES=$(echo "$OUTPUT" | tail -3)

            # If we see "Type" instruction and no command after it, send continue
            if echo "$LAST_LINES" | grep -q "force stop"; then
                echo "$(date '+%H:%M:%S') 🔄 Stop blocked detected - sending 'c' to continue..."
                tmux send-keys -t "$SESSION_NAME" "c" Enter
                LAST_BLOCK_LINE="$BLOCK_LINE"
                sleep 3  # Wait after sending to let Claude process
            fi
        fi
    fi

    sleep $CHECK_INTERVAL
done
