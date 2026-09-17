#!/bin/bash
# pull.sh <project_root> — результаты локального разбора с Memex → папка проекта на SSD.
#   work/{cut}/ (кадры, OCR, экраны, VLM, LLM, пробы, селфчеки), транскрипт {CODE}_{cut}.*, логи → logs/memex/.
#   Состояние не сливается: гейты review.py подтверждают стадии по артефактам.
source "$(dirname "$0")/common.sh"
mkdir -p "$REVIEW_DIR/work/$CUT" "$REVIEW_DIR/logs/memex"
echo "← work/$CUT с Memex"
RSYNC=$(command -v /opt/homebrew/bin/rsync || command -v rsync)   # встроенный macOS rsync не знает --info=progress2
"$RSYNC" -a "$MX_HOST:$MX_REVIEW_ABS/work/$CUT/" "$REVIEW_DIR/work/$CUT/" || { echo "rsync work/$CUT не прошёл"; exit 3; }
rsync -a "$MX_HOST:$MX_REVIEW_ABS/${CODE}_${CUT}.*" "$REVIEW_DIR/" 2>/dev/null || true
rsync -a "$MX_HOST:$MX_REVIEW_ABS/logs/" "$REVIEW_DIR/logs/memex/" 2>/dev/null || true
echo "← проверка хэшей ключевых файлов"
for f in screens_v6.json vlm_v6.jsonl llm_v6.json ocr_hires.jsonl probes.jsonl prep_check_all.json; do
  L=$( [ -f "$REVIEW_DIR/work/$CUT/$f" ] && md5 -q "$REVIEW_DIR/work/$CUT/$f" || echo none)
  R=$(mx "[ -f $MX_REVIEW/work/$CUT/$f ] && md5 -q $MX_REVIEW/work/$CUT/$f || echo none")
  [ "$L" = "$R" ] && echo "  = $f" || echo "  ≠ $f (local $L / memex $R)"
done
N=$(ls "$REVIEW_DIR/work/$CUT/hires" 2>/dev/null | wc -l | tr -d ' ')
ALL=0; for a in "${@:2}"; do [ "$a" = "--all" ] && ALL=1; done
if [ $ALL = 1 ]; then
  # автономный прогон: всё, что построила вторая половина цепочки на Memex
  echo "← pravki/ cloud/ mockups/ поверхности (--all)"
  for d in pravki cloud mockups notes; do
    "$RSYNC" -a --exclude 'raw' "$MX_HOST:$MX_REVIEW_ABS/$d/" "$REVIEW_DIR/$d/" 2>/dev/null || true
  done
  rsync -a "$MX_HOST:$MX_REVIEW_ABS/${CODE}_review_v6*" "$MX_HOST:$MX_REVIEW_ABS/${CODE}_${CUT}_*" \
        "$MX_HOST:$MX_REVIEW_ABS/REVIEW_STATE.md" "$REVIEW_DIR/" 2>/dev/null || true
  rsync -a "$MX_HOST:$MX_REVIEW_ABS/review_card.json" /tmp/review_card.from_memex.json && python3 - "$CARD" /tmp/review_card.from_memex.json <<'EOF'
import json, sys
mac, mx = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
keys = [k for k in ('chapters', 'ch_name', 'duration_sec', 'ocr_anchors', 'exclusions') if k in mx and mx.get(k) != mac.get(k)]
for k in keys:
    mac[k] = mx[k]
json.dump(mac, open(sys.argv[1], 'w'), ensure_ascii=False, indent=1)
print('  карточка мака: из Memex взяты', keys or 'ничего (совпадает)')
EOF
  echo "кадров локально: $N · секвенция в Premiere: UXP → Review → ${CODE}_review_v6.json → Build"
else
  echo "кадров локально: $N · дальше: review.py run --project \"$ROOT\" --from route"
fi
