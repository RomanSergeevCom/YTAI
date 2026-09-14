#!/bin/bash
# status.sh <project_root> — состояние разбора на Memex: версия кода (дрейф), стадии, хвост лога, процессы.
source "$(dirname "$0")/common.sh"
LOCAL_SHA=$(git -C "$YTAI_DIR" rev-parse --short HEAD 2>/dev/null || echo dev)
MX_SHA=$(mx "cat ~/YTAI/$REL_STAGE/VERSION 2>/dev/null || echo none")
echo "код: локально $LOCAL_SHA · Memex $MX_SHA $([ "$LOCAL_SHA" = "$MX_SHA" ] && echo '(совпадает)' || echo '⚠️ ДРЕЙФ — push.sh')"
mx "[ -f $MX_REVIEW/review_card.json ] && python3 ~/YTAI/$REL_STAGE/review.py status --project $MX_ROOT 2>&1 | head -20 || echo 'на Memex нет проекта $CODE'"
echo "--- процессы"; mx "pgrep -fl 'review.py run|watchdog.sh|s3_vlm|s4_llm|s2_ocr|wordrole|ffmpeg' | head -6 || true"
echo "--- хвост лога"; mx "tail -5 $MX_REVIEW/logs/review.log 2>/dev/null; ls $MX_REVIEW/work/$CUT/hires 2>/dev/null | wc -l | xargs echo кадров:"
