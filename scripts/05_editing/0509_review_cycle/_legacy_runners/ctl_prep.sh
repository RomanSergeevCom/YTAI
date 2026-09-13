#!/usr/bin/env bash
# ctl_prep.sh — запуск локального разбора ката (VLM/LLM) С ПАУЗОЙ.
#
# Зачем отдельно от run_prep.sh: внутри run_prep.sh стоит сторож по часам (kill -9 по таймауту),
# который ничего не знает про паузу — стадия, простоявшая на паузе дольше остатка таймаута, будет убита.
# Обе модельные стадии возобновляемы (vlm — поэкранно с flush, llm — раз в 10 экранов), поэтому по
# отдельности пауза и продолжение достаются бесплатно.
#
# Контрольные файлы живут на ВНУТРЕННЕМ диске: работают, даже если SSD с медиа отвалился.
#
# usage: ./ctl_prep.sh {vlm|llm|ocr} start | pause | resume | stop | status
#        PROJ=ytuvi02 W6=/Volumes/T9-Black-RYA/YTUVI02_Review/work/v6 ./ctl_prep.sh vlm start
set -u

PROJ="${PROJ:-ytuvi02}"
W6="${W6:-$(cd "$(dirname "$0")" && pwd)}"
CTL="$HOME/.cache/$PROJ"
# ⚠️ У стадий РАЗНЫЕ окружения: mlx_vlm стоит только в .venv_vlm. Один PY на обе стадии
# означал мгновенный ImportError на «vlm start» — venv выбирается по стадии ниже.
PY_VLM="${PY_VLM:-$HOME/YTAI/environment/.venv_vlm/bin/python}"
PY_LLM="${PY_LLM:-$HOME/YTAI/environment/.venv_llm/bin/python}"
PY_OCR="${PY_OCR:-python3}"
mkdir -p "$CTL"

stage="${1:-}"; cmd="${2:-}"
case "$stage" in
  vlm) SCRIPT=s3_vlm.py;        OUTF="$W6/vlm_v6.jsonl";    PY="$PY_VLM" ;;
  llm) SCRIPT=s4_llm.py;        OUTF="$W6/llm_v6.json";     PY="$PY_LLM" ;;
  ocr) SCRIPT=s2_ocr_hires.py;  OUTF="$W6/ocr_hires.jsonl"; PY="$PY_OCR" ;;
  *) echo "usage: $0 {vlm|llm|ocr} {start|pause|resume|stop|status}"; exit 2 ;;
esac
if [ ! -x "$PY" ] && ! command -v "$PY" >/dev/null 2>&1; then
  echo "нет интерпретатора для стадии $stage: $PY"; exit 2
fi
PID="$CTL/$stage.pid"
LOG="$W6/$stage.log"

alive() { [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; }

case "$cmd" in
  start)
    if alive; then echo "уже идёт (pid $(cat "$PID"))"; exit 0; fi
    if [ ! -f "$W6/prep_config.json" ]; then
      echo "нет $W6/prep_config.json — карточка проекта не заведена, стадия взяла бы чужой транскрипт"; exit 2
    fi
    rm -f "$CTL/PAUSE"
    # detached: nohup + caffeinate. setsid на macOS нет, поэтому подоболочка + nohup.
    export YTAI_PROJECT="$PROJ" YTAI_CTL_DIR="$CTL"
    ( cd "$W6" && nohup caffeinate -dims "$PY" -u "$SCRIPT" >> "$LOG" 2>&1 < /dev/null & echo $! > "$PID" )
    sleep 1
    echo "▶️ $stage запущен (pid $(cat "$PID")), лог: $LOG"
    echo "   проверь отцепление: ps -o ppid= -p $(cat "$PID")  → должно быть 1"
    ;;
  pause)
    touch "$CTL/PAUSE"
    pkill -STOP -f "$SCRIPT" 2>/dev/null && echo "⏸ $stage на паузе (0% CPU, модель остаётся в памяти)" \
      || echo "процесс не найден — возможно, стадия уже закончилась"
    ;;
  resume)
    rm -f "$CTL/PAUSE"
    pkill -CONT -f "$SCRIPT" 2>/dev/null && echo "▶️ $stage продолжает" \
      || echo "процесс не найден — запусти заново: $0 $stage start (стадия возобновляема)"
    ;;
  stop)
    # ВАЖНО: сначала SIGCONT, иначе остановленный процесс не обработает сигнал завершения
    pkill -CONT -f "$SCRIPT" 2>/dev/null
    if [ "$stage" = llm ]; then
      echo "⚠️ llm пишет json неатомарно (дамп раз в 10 экранов) — убиваем мягко, с паузой на дозапись"
      pkill -TERM -f "$SCRIPT" 2>/dev/null; sleep 3
    fi
    pkill -f "$SCRIPT" 2>/dev/null
    rm -f "$PID" "$CTL/PAUSE"
    echo "⏹ $stage остановлен"
    ;;
  status)
    if alive; then
      st=$(ps -o state= -p "$(cat "$PID")" | tr -d ' ')
      case "$st" in T*) s="⏸ на паузе";; *) s="▶️ идёт";; esac
      echo "$s · pid $(cat "$PID")"
    else
      echo "⏹ не запущен"
    fi
    [ -f "$CTL/PAUSE" ] && echo "   флаг PAUSE стоит: $CTL/PAUSE"
    if [ -f "$OUTF" ]; then
      case "$OUTF" in
        *.jsonl) echo "   сделано: $(wc -l < "$OUTF" | tr -d ' ') записей в $(basename "$OUTF")" ;;
        *) echo "   размер $(basename "$OUTF"): $(du -h "$OUTF" | cut -f1)" ;;
      esac
    fi
    [ -f "$LOG" ] && tail -2 "$LOG"
    exit 0            # иначе код возврата берётся от последней проверки и status «падает»
    ;;
  *) echo "usage: $0 {vlm|llm|ocr} {start|pause|resume|stop|status}"; exit 2 ;;
esac
