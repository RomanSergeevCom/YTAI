#!/usr/bin/env bash
# Развернуть фабрику прокси на Мемекс (Mac mini M4, Дубай).
#
# Что делает: везёт этап 16_proxy целиком (контракт — одна точка правды, копий
# не заводим), ставит launchd-агент и сторожа, прогоняет регрессию НА МЕСТЕ.
# Медиа не возит: фабрика берёт исходники с Drive.
#
# ⚠️ В неинтерактивном ssh PATH без Homebrew — ffmpeg/rclone/python3 «исчезают».
# Поэтому PATH выставляется в каждой удалённой команде и в plist тоже.
#
#   bash deploy_memex.sh              развернуть и проверить
#   bash deploy_memex.sh --check      только проверить, ничего не менять
#
# Версия 1.0 · 23.09.2026 · этап 16_proxy/1603_farm
set -euo pipefail

HOST="${FARM_HOST:-memex}"
LOCAL_STAGE="$HOME/YTAI/scripts/16_proxy"
REMOTE_STAGE="YTAI/scripts/16_proxy"
PLIST_LABEL="ae.rya.ytai-proxy-farm"
CHECK_ONLY="${1:-}"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
rsh() { ssh -o ConnectTimeout=20 "$HOST" "export PATH=/opt/homebrew/bin:\$PATH; $*"; }

say "1. Мемекс на связи и годен"
rsh 'sw_vers -productVersion; sysctl -n hw.memsize | awk "{printf \"%.0f ГБ RAM\n\", \$1/1073741824}"
     df -g / | awk "NR==2 {print \$4\" ГиБ свободно на /\"}"
     for t in ffmpeg ffprobe rclone python3; do printf "%-9s %s\n" "$t" "$(command -v $t || echo НЕТ)"; done
     ffmpeg -hide_banner -encoders 2>/dev/null | grep -q hevc_videotoolbox \
       && echo "hevc_videotoolbox есть" || { echo "⛔ аппаратного HEVC нет"; exit 1; }
     rclone listremotes | tr "\n" " "; echo'

if [ "$CHECK_ONLY" = "--check" ]; then
  say "проверка: остальное пропущено (--check)"
  rsh "ls -la $REMOTE_STAGE 2>/dev/null | head -5 || echo 'этап ещё не развёрнут'"
  exit 0
fi

say "2. Везу этап 16_proxy (код, не медиа)"
# Состояние и логи прошлых прогонов не везём: у Мемекса своё.
rsync -az --delete \
  --exclude '__pycache__' --exclude 'state/' --exclude '*.pyc' --exclude '.DS_Store' \
  "$LOCAL_STAGE/" "$HOST:$REMOTE_STAGE/"
rsh "ls $REMOTE_STAGE && echo '---' && ls $REMOTE_STAGE/1603_farm"

say "3. Регрессия НА МЕСТЕ — без неё дальше не идём"
rsh "cd $REMOTE_STAGE/1601_build && python3 rebuild.py selftest"
rsh "cd $REMOTE_STAGE/1603_farm && python3 selftest.py"

say "4. Манифест читается с Drive"
rsh "cd $REMOTE_STAGE/1603_farm && python3 - <<'PY'
import json, os, sys
sys.path.insert(0, '.'); sys.path.insert(0, '../1601_build')
import plan as P
from drive import Drive
cfg = P.load_units(); u = P.unit_by_name(cfg, 'YTEVO03')
d = Drive(u['remote'], u.get('team_drive',''))
t = d.get_text(u['drive_kit'].rstrip('/') + '/' + P.PLAN_NAME)
if not t: print('⛔ манифеста на Drive нет'); sys.exit(1)
p = json.loads(t); m = p['meta']
print(f\"манифест: {m['clips']} клипов, {m['bytes']/1e9:.1f} ГБ, построен {m['built_at']} на {m['built_on']}\")
print('проблем в манифесте:', len(m.get('problems') or []))
PY"

say "5. Сторож: смотрит, что фабрика жива, и поднимает её, если нет"
rsh "mkdir -p ~/bin ~/Library/Logs/ytai/proxy_farm ~/.cache/ytai/proxy_farm"
rsh "cat > ~/bin/proxy_farm_watch.sh <<'SH'
#!/usr/bin/env bash
# Сторож фабрики прокси. Смотрит на ДВИЖЕНИЕ, а не на наличие процесса:
# живой процесс, который ничего не делает, — худший случай из всех.
export PATH=/opt/homebrew/bin:\$PATH
RUN=\"\$HOME/Library/Logs/ytai/proxy_farm\"
LOG=\"\$RUN/farm_YTEVO03.log\"
STAGE=\"\$HOME/.cache/ytai/proxy_farm\"
[ -f \"\$STAGE/STOP\" ] && exit 0
# лог не шевелился 60 минут, а процесс есть → он завис, снимаем: launchd поднимет
if [ -f \"\$LOG\" ]; then
  AGE=\$(( \$(date +%s) - \$(stat -f %m \"\$LOG\") ))
  if [ \"\$AGE\" -gt 3600 ] && pgrep -f 'farm.py run' >/dev/null; then
    echo \"\$(date '+%F %T') сторож: лог молчит \$((AGE/60)) мин — снимаю зависший прогон\" >> \"\$RUN/watch.log\"
    pkill -f 'farm.py run' || true
  fi
fi
SH
chmod +x ~/bin/proxy_farm_watch.sh"

say "6. launchd: ночной прогон и сторож"
rsh "cat > ~/Library/LaunchAgents/$PLIST_LABEL.plist <<'PL'
<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict>
  <key>Label</key><string>$PLIST_LABEL</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>ProgramArguments</key><array>
    <!-- ⚠️ caffeinate это СИСТЕМНЫЙ бинарь в /usr/bin, а не homebrew. Путь
         /opt/homebrew/bin/caffeinate не существует, и launchd на нём молча
         отдаёт EX_CONFIG (78) и уводит агент в penalty box: в логах прогона
         при этом ПУСТО, потому что программа так и не запустилась. -->
    <string>/usr/bin/caffeinate</string><string>-ims</string>
    <string>/opt/homebrew/bin/python3</string><string>-u</string>
    <string>$HOME/$REMOTE_STAGE/1603_farm/farm.py</string>
    <string>run</string><string>--unit</string><string>YTEVO03</string>
    <!-- ⚠️ Два кодировщика, а не один, и это НЕ противоречит правилу «jobs почти
         не помогает». То правило про аппаратный блок hevc_videotoolbox — он
         действительно один. Но на съёмочном материале FX3 узкое место другое:
         исходник h264 High 4:2:2 10 бит, а такой профиль Apple аппаратно НЕ
         декодирует (проверено 23.09.2026: -hwaccel videotoolbox отвечает
         «Error submitting packet to decoder» и при этом молча отдаёт 75 кадров
         вместо 84 — гейт такое ловит, но полагаться на это нельзя). Значит
         декод программный и упирается в ядра, а они на M4 есть. -->
    <string>--jobs</string><string>2</string>
    <string>--fetchers</string><string>6</string>
    <string>--prefetch</string><string>6</string>
  </array>
  <key>WorkingDirectory</key><string>$HOME/$REMOTE_STAGE/1603_farm</string>
  <!-- Ночью: очередь долговечна, так что незаконченное подхватится следующим запуском -->
  <key>StartCalendarInterval</key><array>
    <dict><key>Hour</key><integer>1</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <!-- ⚠️ KeepAlive НЕ ставим: фабрика сама решает, когда работы нет, и выходит
       с кодом 0. KeepAlive крутил бы её по кругу и жёг Drive-квоту на снимках. -->
  <key>StandardOutPath</key><string>$HOME/Library/Logs/ytai/proxy_farm/launchd.out</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/ytai/proxy_farm/launchd.err</string>
  <!-- ⚠️ НЕ Background и НЕ nice. Замер 23.09.2026: с ProcessType Background
       и Nice 5 процесс шёл с PRI 4, и прогон выдавал 5 МБ/с по исходнику —
       26 часов на 479 ГБ. Эта работа и есть то, ради чего машина стоит;
       душить её приоритетом нечем. Standard — обычный приоритет. -->
  <key>ProcessType</key><string>Standard</string>
  <key>LowPriorityIO</key><false/>
</dict></plist>
PL
cat > ~/Library/LaunchAgents/$PLIST_LABEL-watch.plist <<'PL'
<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict>
  <key>Label</key><string>$PLIST_LABEL-watch</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>$HOME/bin/proxy_farm_watch.sh</string>
  </array>
  <key>StartInterval</key><integer>900</integer>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/ytai/proxy_farm/watch.out</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/ytai/proxy_farm/watch.err</string>
  <key>ProcessType</key><string>Background</string>
</dict></plist>
PL
plutil -lint ~/Library/LaunchAgents/$PLIST_LABEL.plist
plutil -lint ~/Library/LaunchAgents/$PLIST_LABEL-watch.plist"

say "7. Агенты загружены (но прогон НЕ запущен — это делается руками)"
rsh "launchctl bootout gui/\$(id -u)/$PLIST_LABEL 2>/dev/null || true
     launchctl bootout gui/\$(id -u)/$PLIST_LABEL-watch 2>/dev/null || true
     launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/$PLIST_LABEL.plist
     launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/$PLIST_LABEL-watch.plist
     launchctl print-disabled gui/\$(id -u) 2>/dev/null | grep -i proxy-farm || true
     launchctl list | grep -i proxy-farm || echo 'в списке пока нет (нормально до первого запуска)'"

say "Готово. Что делать дальше"
cat <<'TXT'
  сухой прогон на Мемексе (ничего не пишет, только говорит, что будет):
    ssh memex 'export PATH=/opt/homebrew/bin:$PATH; cd YTAI/scripts/16_proxy/1603_farm \
      && python3 farm.py run --unit YTEVO03 --dry-run'

  боевой прогон прямо сейчас (не дожидаясь ночи):
    ssh memex 'export PATH=/opt/homebrew/bin:$PATH; launchctl kickstart -p gui/$(id -u)/ae.rya.ytai-proxy-farm'

  где стоим:
    ssh memex 'export PATH=/opt/homebrew/bin:$PATH; cd YTAI/scripts/16_proxy/1603_farm \
      && python3 farm.py status --unit YTEVO03'

  остановить, не убивая (очередь цела, прогон дойдёт до конца клипа и выйдет):
    ssh memex 'touch ~/.cache/ytai/proxy_farm/STOP'
  снять стоп:
    ssh memex 'rm -f ~/.cache/ytai/proxy_farm/STOP'
TXT
