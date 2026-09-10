#!/bin/bash
# v6 POST — после аудита агентами (audit_findings_v6.json): применить находки → отрендерить графику →
# собрать part-JSON → превью → мок-сборка через partsBuilder → Drive-материалы с комментами →
# лист «ТЗ монтажёру» → вкладка дока + verify. Каждый шаг с проверкой кода выхода; лог post.log.
# usage: ./run_post.sh [--no-drive] [--no-doc]
set -uo pipefail
W6=~/Downloads/YTUVI01_Sonya_cut/work/v6
MONT=~/Downloads/YTUVI01_Sonya_cut/work/montage
LOG=$W6/post.log
export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH
cd "$W6" || exit 1
mark() { echo "[$(date +%H:%M:%S)] $1" | tee -a "$LOG"; }
step() { # step <name> <cmd...>
  local name=$1; shift
  mark "STEP $name"
  if "$@" >> "$LOG" 2>&1; then mark "OK   $name"; else mark "FAIL $name (rc=$?) — см. $LOG"; echo FAIL > post.status; exit 1; fi
}
echo RUNNING > post.status
mark "POST start"
step apply_audit     python3 "$W6/s8_apply_audit.py"
step render_G        python3 "$W6/make_infographics_v6.py" G
step review_json     python3 "$W6/make_review_v6.py"
step previews        python3 "$W6/s7_preview_sheet.py"
step mockbuild       node "$W6/mockbuild_v6.js"
if [[ " $* " != *" --no-drive "* ]]; then
  step drive_materials python3 "$W6/s9_materials_drive.py"
fi
step tz_sheet        python3 "$MONT/tz_sheet.py"
if [[ " $* " != *" --no-doc "* ]]; then
  step doc_tab         python3 "$MONT/doc_tab_tz_v3.py"
  step doc_verify      python3 "$MONT/doc_tab_tz_v3_verify.py"
fi
echo OK > post.status
mark "POST OK"
