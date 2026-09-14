#!/bin/bash
# pull.sh <project_root> — результаты локального разбора с Memex → папка проекта на SSD.
#   work/{cut}/ (кадры, OCR, экраны, VLM, LLM, пробы, селфчеки), транскрипт {CODE}_{cut}.*, логи → logs/memex/.
#   Состояние не сливается: гейты review.py подтверждают стадии по артефактам.
source "$(dirname "$0")/common.sh"
mkdir -p "$REVIEW_DIR/work/$CUT" "$REVIEW_DIR/logs/memex"
echo "← work/$CUT с Memex"
rsync -a --info=progress2 "$MX_HOST:$MX_REVIEW_ABS/work/$CUT/" "$REVIEW_DIR/work/$CUT/"
rsync -a "$MX_HOST:$MX_REVIEW_ABS/${CODE}_${CUT}.*" "$REVIEW_DIR/" 2>/dev/null || true
rsync -a "$MX_HOST:$MX_REVIEW_ABS/logs/" "$REVIEW_DIR/logs/memex/" 2>/dev/null || true
echo "← проверка хэшей ключевых файлов"
for f in screens_v6.json vlm_v6.jsonl llm_v6.json ocr_hires.jsonl probes.jsonl prep_check_all.json; do
  L=$( [ -f "$REVIEW_DIR/work/$CUT/$f" ] && md5 -q "$REVIEW_DIR/work/$CUT/$f" || echo none)
  R=$(mx "[ -f $MX_REVIEW/work/$CUT/$f ] && md5 -q $MX_REVIEW/work/$CUT/$f || echo none")
  [ "$L" = "$R" ] && echo "  = $f" || echo "  ≠ $f (local $L / memex $R)"
done
N=$(ls "$REVIEW_DIR/work/$CUT/hires" 2>/dev/null | wc -l | tr -d ' ')
echo "кадров локально: $N · дальше: review.py run --project \"$ROOT\" --from route"
