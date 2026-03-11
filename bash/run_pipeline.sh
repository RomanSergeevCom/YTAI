#!/bin/bash
# YTAI Pipeline: Transcription + Processing
# Usage: ./run_pipeline.sh "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"

set -e  # Exit on error

PROJECT="$1"
SCRIPTS_DIR="$HOME/YTAI/scripts"

if [ -z "$PROJECT" ]; then
    echo "Usage: $0 <project_path>"
    echo "Example: $0 \"/Volumes/RYA Blue/YTCG37_Hadi_Dawani\""
    exit 1
fi

if [ ! -d "$PROJECT" ]; then
    echo "ERROR: Project folder not found: $PROJECT"
    exit 1
fi

echo ""
echo "============================================================"
echo "YTAI PIPELINE"
echo "============================================================"
echo "Project: $PROJECT"
echo "Started: $(date)"
echo ""

# Step 1: Transcription
echo "============================================================"
echo "STEP 1: TRANSCRIPTION"
echo "============================================================"
python "$SCRIPTS_DIR/transcribe_project.py" --project "$PROJECT"

if [ $? -ne 0 ]; then
    echo "ERROR: Transcription failed!"
    exit 1
fi

echo ""

# Step 2: Processing
echo "============================================================"
echo "STEP 2: PROCESSING"
echo "============================================================"
python "$SCRIPTS_DIR/process_transcript.py" --project "$PROJECT"

if [ $? -ne 0 ]; then
    echo "ERROR: Processing failed!"
    exit 1
fi

echo ""
echo "============================================================"
echo "PIPELINE COMPLETE"
echo "============================================================"
echo "Finished: $(date)"
echo ""
