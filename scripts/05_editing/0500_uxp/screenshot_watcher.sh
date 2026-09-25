#!/bin/bash
# Screenshot watcher for YTAI UXP plugin
# Run once: bash ~/YTAI/scripts/05_editing/0500_uxp/screenshot_watcher.sh &
# UXP writes /tmp/ytai_screenshot.trigger with target path → this script captures screen

TRIGGER="/tmp/ytai_screenshot.trigger"
echo "YTAI screenshot watcher started (PID $$). Waiting for triggers..."

while true; do
  if [ -f "$TRIGGER" ]; then
    TARGET=$(cat "$TRIGGER")
    rm -f "$TRIGGER"
    if [ -n "$TARGET" ]; then
      sleep 0.3  # brief delay for UI to settle
      screencapture -x "$TARGET"
      echo "$(date '+%H:%M:%S') Screenshot → $TARGET"
    fi
  fi
  sleep 0.5
done
