#!/bin/bash
# YTAI: Export markers from Premiere .prproj file
# Reads project path from /tmp/ytai_export_markers_project.txt

PROJECT_PATH=$(cat /tmp/ytai_export_markers_project.txt 2>/dev/null)

if [ -z "$PROJECT_PATH" ]; then
    echo "Error: No project path found at /tmp/ytai_export_markers_project.txt"
    read -p "Press Enter to close..."
    exit 1
fi

echo "=== YTAI Marker Export ==="
echo "Project: $PROJECT_PATH"
echo

python3 ~/YTAI/scripts/05_editing/0506_marker_export/export_markers_from_prproj.py \
    --project "$PROJECT_PATH"

echo
echo "Done. Closing in 3 seconds..."
sleep 3
