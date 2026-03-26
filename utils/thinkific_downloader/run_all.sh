#!/bin/bash
# Run the full pipeline for ALL 59 lessons from YTCG.docx.
#
# Pipeline per lesson:
#   1. Download video (Wistia/ffmpeg)
#   2. Save DOCX notes, images, extra links
#   3. Extract screenshots every 5 seconds
#   4. AI classify + describe content frames (Ollama minicpm-v)
#   5. Transcribe (Whisper large-v3 + pyannote diarization)
#
# Usage:
#   chmod +x run_all.sh
#   ./run_all.sh
#
# Prerequisites:
#   - Ollama running: ollama serve
#   - Model pulled:   ollama pull minicpm-v
#   - ffmpeg installed
#   - Transcription venv at /Users/romansergeev/YTAI/environment/.venv_transcribe
#
# Logs are written to: /Users/romansergeev/YTAI/utils/thinkific_downloader/logs/

set -euo pipefail
cd "$(dirname "$0")"

DOCX_PATH="/Users/romansergeev/Downloads/YTCG.docx"
OUTPUT_DIR="downloads"
LOG_FILE="logs/run_all_$(date +%Y%m%d_%H%M%S).log"

mkdir -p logs

echo "========================================" | tee -a "$LOG_FILE"
echo "Starting full batch run: $(date)" | tee -a "$LOG_FILE"
echo "DOCX: $DOCX_PATH" | tee -a "$LOG_FILE"
echo "Output: $OUTPUT_DIR" | tee -a "$LOG_FILE"
echo "Log: $LOG_FILE" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

# Check prerequisites
if ! command -v ffmpeg &>/dev/null; then
    echo "ERROR: ffmpeg not found" | tee -a "$LOG_FILE"
    exit 1
fi

if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "ERROR: Ollama not running. Start with: ollama serve" | tee -a "$LOG_FILE"
    exit 1
fi

echo "Prerequisites OK" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

python3 process_docx_thinkific.py \
    "$DOCX_PATH" \
    --output-dir "$OUTPUT_DIR" \
    --screenshot-mode interval \
    --screenshot-interval 5 \
    --vision-model minicpm-v \
    --model large-v3 \
    2>&1 | tee -a "$LOG_FILE"

echo "" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "Batch run finished: $(date)" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
