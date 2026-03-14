#!/bin/bash
# Screen Cues PNG generator — launched from UXP via shell.openPath()
# Reads brief path from /tmp/ytai_screen_cues_brief.txt
#
# Usage: called automatically by UXP "Generate PNGs" button.
# Manual: echo "/path/to/edit_brief.json" > /tmp/ytai_screen_cues_brief.txt && open run_generate.command

# --- ANSI colors ---
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

BRIEF_FILE="/tmp/ytai_screen_cues_brief.txt"
if [ ! -f "$BRIEF_FILE" ]; then
  echo ""
  echo -e "  ${RED}✗ Error:${NC} brief path file not found at $BRIEF_FILE"
  echo "  Launch from UXP panel 'Generate PNGs' button."
  sleep 5
  exit 1
fi

BRIEF_PATH=$(cat "$BRIEF_FILE")
if [ ! -f "$BRIEF_PATH" ]; then
  echo ""
  echo -e "  ${RED}✗ Error:${NC} brief not found: $BRIEF_PATH"
  rm -f "$BRIEF_FILE"
  sleep 5
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DONE_DIR="$(dirname "$BRIEF_PATH")/screen_cues"

echo -e "${BOLD}${CYAN}"
echo "  ╔═══════════════════════════════════╗"
echo "  ║  YTAI — Screen Cues PNG Generator ║"
echo "  ╚═══════════════════════════════════╝"
echo -e "${NC}"
echo -e "  ${CYAN}Brief:${NC}  $BRIEF_PATH"
echo -e "  ${CYAN}Output:${NC} $DONE_DIR/"
echo ""

python3 "$SCRIPT_DIR/generate_screen_cues_png.py" --brief "$BRIEF_PATH"
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
  PNG_COUNT=$(ls -1 "$DONE_DIR"/*.png 2>/dev/null | wc -l | tr -d ' ')
  echo -e "  ${GREEN}✓ Done!${NC} ${PNG_COUNT} PNGs saved to:"
  echo -e "  ${DONE_DIR}/"
  echo "DONE" > "$DONE_DIR/.done"
else
  echo -e "  ${RED}✗ Error:${NC} Python exited with code $EXIT_CODE"
fi

rm -f "$BRIEF_FILE"

echo ""
echo -e "  ${YELLOW}Closing in 3s...${NC}"
sleep 3

# Auto-close this Terminal window
osascript -e 'tell application "Terminal" to close first window' 2>/dev/null &
