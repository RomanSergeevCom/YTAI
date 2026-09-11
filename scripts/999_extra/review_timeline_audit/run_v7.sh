#!/bin/bash
# v7 (10.09.2026) — пересборка всех поверхностей после правок текстов/превью: pravki → графика → JSON → превью →
# Drive → лист → док + verify. Каждый шаг с проверкой кода выхода; лог v7.log; статус v7.status.
# usage: ./run_v7.sh [--from STEP] [--until STEP]
#   шаги: terms s10 s11 render review mock prev_render prev_upload prev_apply drive sheet doc verify
# Правки Романа в доке снимать ДО запуска: python3 s13_doc_edits.py
set -uo pipefail
W6=~/Downloads/YTUVI01_Sonya_cut/work/v6
MONT=~/Downloads/YTUVI01_Sonya_cut/work/montage
LOG=$W6/v7.log
export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH
cd "$W6" || exit 1
STEPS=(terms s10 s11 render review mock prev_render prev_upload prev_apply drive sheet doc verify)
FROM=${STEPS[0]}; UNTIL=${STEPS[${#STEPS[@]}-1]}
while [[ $# -gt 0 ]]; do case $1 in --from) FROM=$2; shift 2;; --until) UNTIL=$2; shift 2;; *) echo "?? $1"; exit 2;; esac; done
mark() { echo "[$(date +%H:%M:%S)] $1" | tee -a "$LOG"; }
on=0
run() { # run <step> <cmd...>
  local name=$1; shift
  [[ $name == "$FROM" ]] && on=1
  if [[ $on == 1 ]]; then
    mark "STEP $name"
    if "$@" >> "$LOG" 2>&1; then mark "OK   $name"; else mark "FAIL $name (rc=$?) — см. $LOG"; echo "FAIL $name" > v7.status; exit 1; fi
  fi
  if [[ $name == "$UNTIL" ]]; then echo "OK until $name" > v7.status; mark "STOP after $name"; exit 0; fi
}
echo RUNNING > v7.status
mark "V7 start (from=$FROM until=$UNTIL)"
run terms       python3 "$W6/terms_index.py"
run s10         python3 "$W6/s10_format_tz.py"
run s11         python3 "$W6/s11_apply_sources.py"
run render      python3 "$W6/make_infographics_v6.py" G
run review      python3 "$W6/make_review_v6.py"
run mock        node "$W6/mockbuild_v6.js"
run prev_render python3 "$W6/s12_doc_previews.py" --render
run prev_upload python3 "$W6/s12_doc_previews.py" --upload
run prev_apply  python3 "$W6/s12_doc_previews.py" --apply
run drive       python3 "$W6/s9_materials_drive.py"
run sheet       python3 "$MONT/tz_sheet.py"
run doc         python3 "$MONT/doc_tab_tz_v4.py"
run verify      python3 "$MONT/doc_tab_tz_v4_verify.py"
echo OK > v7.status
mark "V7 OK"
