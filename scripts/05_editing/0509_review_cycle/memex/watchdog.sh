#!/bin/bash
# watchdog.sh <memex_project_root> — сторож автономного разбора НА Memex (запускается start.sh через nohup).
#   Живёт отдельным процессом от review.py: если прогон умер (pid не жив), а стадии Memex не закрыты
#   и нет флага STOP/PAUSE — поднимает его снова (≤5 раз). Вехи в Telegram шлёт сам review.py (--tg).
#   Выходит, когда все memex-стадии done/warn, либо стадия провалена HARD, либо стоит STOP.
set -uo pipefail
export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH
export HF_HOME=$HOME/YTAI/models/huggingface
ROOT=${1:?root}
STAGE=$HOME/YTAI/scripts/05_editing/0509_review_cycle
REVIEW=$ROOT/00_Setup/05_Review
STATE=$REVIEW/review_state.json
PROJECT=$(python3 -c "import json;print(json.load(open('$REVIEW/review_card.json')).get('project','x'))")
CTL=$HOME/.cache/$PROJECT
tg() { TG_BOT_TOKEN=$(cat "$HOME/.config/rscore-tg/rya.token" 2>/dev/null) "$HOME/bin/tg.py" text rya 155880671 "$1" --parse html >/dev/null 2>&1 || true; }
alive() { [ -f "$CTL/review.pid" ] && kill -0 "$(cat "$CTL/review.pid")" 2>/dev/null; }
auto() { [ -f "$CTL/AUTONOMOUS" ]; }      # автономный режим: сторож ведёт всю цепочку до producer_page
verdict() {  # done | fail | cloud | pending
  python3 - "$STATE" "$(auto && echo all || echo memex)" <<'EOF'
import json, sys
try: s = json.load(open(sys.argv[1]))
except Exception: print('pending'); sys.exit()
st = s.get('stages', {})
if sys.argv[2] == 'all':
    mem = list(st.keys())
    if st.get('producer_page', {}).get('status') in ('done', 'warn'): print('done'); sys.exit()
else:
    mem = ['download','frames','ocr','transcript','vlm','llm','probe','selfcheck']
    if all(st.get(n, {}).get('status') in ('done','warn') for n in mem): print('done'); sys.exit()
if any(st.get(n, {}).get('status') == 'failed' and st[n].get('attempts', 0) >= 3 for n in mem): print('fail')
elif any(st.get(n, {}).get('status') == 'awaiting_cloud' for n in mem): print('cloud')
else: print('pending')
EOF
}
restarts=0
echo "[$(date '+%d.%m %H:%M:%S')] сторож стартовал ($ROOT)"
while :; do
  sleep 60
  [ -f "$CTL/STOP" ] && { echo "STOP — сторож выходит"; exit 0; }
  v=$(verdict)
  if [ "$v" = done ]; then
    if auto; then echo "автономная цепочка закончена — сторож выходит"          # 🏁 шлёт сам review.py
    else tg "🏁 <b>$(basename "$ROOT")</b>: локальный разбор на Memex закончен — на маке: review.py memex pull → run --from route"; fi
    exit 0
  fi
  [ "$v" = fail ] && { tg "🔴 <b>$(basename "$ROOT")</b>: стадия на Memex провалилась 3 раза — нужен разбор руками (logs/)"; exit 1; }
  [ -f "$CTL/PAUSE" ] && continue
  if ! alive; then
    [ "$v" = cloud ] && ! auto && { tg "☁️ <b>$(basename "$ROOT")</b>: цепочка ждёт облачный проход из сессии (не автономный режим) — сторож выходит"; exit 0; }
    restarts=$((restarts + 1))
    [ $restarts -gt 5 ] && { tg "🔴 <b>$(basename "$ROOT")</b>: прогон падает 5 раз подряд — сторож остановился"; exit 1; }
    echo "[$(date '+%H:%M:%S')] прогон не жив ($v) — подъём #$restarts"
    tg "♻️ <b>$(basename "$ROOT")</b>: прогон на Memex не жив — поднимаю (#$restarts), сделанное не теряется"
    (cd "$REVIEW" && YTAI_TG=1 nohup caffeinate -dims python3 "$STAGE/review.py" run --project "$ROOT" --host memex --tg $(auto && echo --autonomous) >> "$REVIEW/logs/memex_run.out" 2>&1 < /dev/null &)
    sleep 120
  fi
done
