#!/bin/bash
# Pre-Edit docx generator — launched from UXP via shell.openPath()
# Reads params from /tmp/ytai_pre_edit_params.txt (JSON path + DOCX path, one per line)
#
# Usage: called automatically by UXP "Export Doc" button.
# Manual: printf '/path/to/input.json\n/path/to/output.docx' > /tmp/ytai_pre_edit_params.txt && open run_export_docx.command

# --- ANSI colors ---
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PARAMS_FILE="/tmp/ytai_pre_edit_params.txt"
if [ ! -f "$PARAMS_FILE" ]; then
  echo ""
  echo -e "  ${RED}✗ Error:${NC} params file not found at $PARAMS_FILE"
  echo "  Launch from UXP panel 'Export Doc' button."
  sleep 5
  exit 1
fi

INPUT=$(sed -n '1p' "$PARAMS_FILE")
OUTPUT=$(sed -n '2p' "$PARAMS_FILE")

if [ ! -f "$INPUT" ]; then
  echo ""
  echo -e "  ${RED}✗ Error:${NC} JSON not found: $INPUT"
  rm -f "$PARAMS_FILE"
  sleep 5
  exit 1
fi

echo -e "${BOLD}${CYAN}"
echo "  ╔═══════════════════════════════════╗"
echo "  ║  YTAI — Pre-Edit DocX Generator   ║"
echo "  ╚═══════════════════════════════════╝"
echo -e "${NC}"
echo -e "  ${CYAN}Input:${NC}  $INPUT"
echo -e "  ${CYAN}Output:${NC} $OUTPUT"
echo ""

python3 ~/YTAI/scripts/05_editing/0507_pre_edit/export_to_gdoc.py --input "$INPUT" --output "$OUTPUT"
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
  echo -e "  ${GREEN}✓ Done!${NC} DocX saved to:"
  echo -e "  $OUTPUT"
  open "$OUTPUT"
else
  echo -e "  ${RED}✗ Error:${NC} Python exited with code $EXIT_CODE"
fi

rm -f "$PARAMS_FILE"

echo ""
echo -e "  ${YELLOW}Closing in 3s...${NC}"
sleep 3

# Auto-close this Terminal window
osascript -e 'tell application "Terminal" to close first window' 2>/dev/null &
