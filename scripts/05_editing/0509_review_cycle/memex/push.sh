#!/bin/bash
# push.sh <project_root> [--with-cut] — код стадии + зависимости + карточка фильма → Memex.
#   код:    rsync папки стадии (без легаси/примеров/__pycache__) и 999_extra-зависимостей по тем же путям репо;
#           VERSION = git sha (status показывает дрейф);
#   данные: ~/YTAI_work/{CODE}/00_Setup/05_Review/ — карточка в Memex-варианте (пути относительные,
#           project_dir = ~/YTAI_work/{CODE}), review_terms.json, профиль канала, words.json если уже есть;
#   --with-cut: залить и сам кат (иначе Memex качает его сам из cut_drive).
source "$(dirname "$0")/common.sh"
WITH_CUT=0; for a in "${@:2}"; do [ "$a" = "--with-cut" ] && WITH_CUT=1; done
SHA=$(git -C "$YTAI_DIR" rev-parse --short HEAD 2>/dev/null || echo dev)
echo "$SHA" > "$STAGE_DIR/VERSION"
echo "→ код $REL_STAGE @ $SHA → $MX_HOST"
mx "mkdir -p ~/YTAI/$REL_STAGE ~/YTAI/scripts/999_extra/ytuvi_doctabs ~/YTAI/scripts/999_extra/infographic ~/YTAI/scripts/999_extra/bin ~/YTAI/YTs/$CHANNEL $MX_REVIEW/work/$CUT $MX_REVIEW/pravki $MX_REVIEW/cloud $MX_REVIEW/logs $MX_REVIEW/cut" >/dev/null
rsync -a --delete --exclude '__pycache__' --exclude '_legacy_runners' --exclude 'examples' --exclude '.DS_Store' \
  "$STAGE_DIR/" "$MX_HOST:~/YTAI/$REL_STAGE/"
rsync -a "$YTAI_DIR/scripts/999_extra/ytuvi_doctabs/doctab_lib.py" "$MX_HOST:~/YTAI/scripts/999_extra/ytuvi_doctabs/"
rsync -a "$YTAI_DIR/scripts/999_extra/infographic/render.py" "$MX_HOST:~/YTAI/scripts/999_extra/infographic/"
rsync -a "$YTAI_DIR/scripts/999_extra/wordrole_transcribe.py" "$MX_HOST:~/YTAI/scripts/999_extra/"
rsync -a "$YTAI_DIR/scripts/999_extra/bin/vision_ocr_ru" "$MX_HOST:~/YTAI/scripts/999_extra/bin/" 2>/dev/null || echo "  (vision_ocr_ru: бинарь собран на Memex отдельно — не перезаписываю)"
rsync -a "$YTAI_DIR/YTs/$CHANNEL/" --include 'review_*.json' --exclude '*' "$MX_HOST:~/YTAI/YTs/$CHANNEL/"
# карточка в Memex-варианте
python3 - "$CARD" "$CODE" "$CUT" <<'EOF' > /tmp/review_card.memex.json
import json, sys, os
card = json.load(open(sys.argv[1])); code, cut = sys.argv[2], sys.argv[3]
mx_root = f'/Users/romansergeev/YTAI_work/{code}'
card['project_dir'] = mx_root
card['review_dir'] = f'{mx_root}/00_Setup/05_Review'
src = card.get('src', '')
card['src'] = f'cut/{os.path.basename(src)}' if src else ''
card['render'] = ''
card['words'] = os.path.basename(card.get('words', f'{code}_{cut}.words.json'))
card['mockups_dir'] = ''
card['_memex'] = 'вариант карточки для Memex: пути относительно 05_Review; сгенерирован push.sh'
print(json.dumps(card, ensure_ascii=False, indent=1))
EOF
rsync -a /tmp/review_card.memex.json "$MX_HOST:$MX_REVIEW_ABS/review_card.json"
[ -f "$REVIEW_DIR/review_terms.json" ] && rsync -a "$REVIEW_DIR/review_terms.json" "$MX_HOST:$MX_REVIEW_ABS/"
WORDS=$(cardval words); WORDS_ABS="$REVIEW_DIR/$WORDS"; [ "${WORDS:0:1}" = "/" ] && WORDS_ABS="$WORDS"
if [ -f "$WORDS_ABS" ]; then rsync -a "$WORDS_ABS" "$MX_HOST:$MX_REVIEW_ABS/$(basename "$WORDS_ABS")"; echo "  транскрипт залит (стадию transcript Memex пропустит)"; fi
if [ $WITH_CUT = 1 ]; then
  SRC=$(cardval src); [ "${SRC:0:1}" = "/" ] || SRC="$REVIEW_DIR/$SRC"
  [ -f "$SRC" ] && { echo "→ кат $(du -h "$SRC" | cut -f1) → Memex"; rsync -a --progress "$SRC" "$MX_HOST:$MX_REVIEW_ABS/cut/"; }
fi
mx "cat ~/YTAI/$REL_STAGE/VERSION; ls $MX_REVIEW" | sed 's/^/  memex: /'
echo "готово: код $SHA, данные $MX_REVIEW"
