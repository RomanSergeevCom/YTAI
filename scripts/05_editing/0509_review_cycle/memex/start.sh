#!/bin/bash
# start.sh <project_root> — автономный локальный разбор на Memex: review.py run --host memex (download…selfcheck)
#   отцепленно (nohup caffeinate, ppid=1), с вехами в Telegram, плюс сторож watchdog.sh (подъём ≤5 раз).
#   Ноутбук можно выключать: состояние и кадры живут на Memex, забираются pull.sh.
source "$(dirname "$0")/common.sh"
mx "cat ~/YTAI/$REL_STAGE/VERSION 2>/dev/null" >/dev/null || { echo "на Memex нет кода — сначала push.sh"; exit 2; }
LOCAL_SHA=$(git -C "$YTAI_DIR" rev-parse --short HEAD 2>/dev/null || echo dev)
MX_SHA=$(mx "cat ~/YTAI/$REL_STAGE/VERSION")
[ "$LOCAL_SHA" = "$MX_SHA" ] || echo "⚠️ дрейф версии: локально $LOCAL_SHA, Memex $MX_SHA — push.sh перед стартом"
RUN="cd $MX_REVIEW && YTAI_TG=1 nohup caffeinate -dims python3 ~/YTAI/$REL_STAGE/review.py run --project $MX_ROOT --host memex --tg >> $MX_REVIEW/logs/memex_run.out 2>&1 < /dev/null &"
WD="cd $MX_REVIEW && nohup bash ~/YTAI/$REL_STAGE/memex/watchdog.sh $MX_ROOT >> $MX_REVIEW/logs/watchdog.out 2>&1 < /dev/null &"
mx "rm -f \$HOME/.cache/$(cardval project)/STOP; $RUN sleep 2; $WD sleep 1; pgrep -fl 'review.py run' | head -3"
echo "запущено на Memex: разбор + сторож. Статус: review.py memex status; пауза: memex pause; забрать: memex pull"
