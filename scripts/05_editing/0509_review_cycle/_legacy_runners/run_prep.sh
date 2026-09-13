#!/bin/bash
# v6 PREP — автономный локальный конвейер подготовки аудита экранов (Роман 07.09:
# «максимум локальных моделей», «самопроверка, что всё хорошо», «самодостаточность и стабильность»).
#
# Стадии (каждая: чекпойнт → резюмируется, timeout, до 3 попыток, после — селфчек s5):
#   frames  ffmpeg 1 fps 1920×1080 из 4K-рендера        → hires/h%04d.jpg (2440)
#   ocr     Apple Vision OCR (vision_ocr_ru)             → ocr_hires.jsonl + screens_v6.json
#   vlm     Qwen2.5-VL-7B дословная транскрипция экранов → vlm_v6.jsonl
#   llm     Qwen3-8B корректор/факт-кандидаты            → llm_v6.json
#   check   финальный селфчек всех артефактов            → prep_check_all.json
# Лог: prep.log; статус-маркер: prep.status (RUNNING/OK/FAIL); TG-уведомления по стадиям.
set -uo pipefail
# Папка и исходник берутся из окружения или из карточки проекта prep_config.json,
# лежащей рядом со скриптами. Зашитые пути прошлого проекта отсюда убраны.
W6="${W6:-$(cd "$(dirname "$0")" && pwd)}"
LOG=$W6/prep.log
PY_VLM=${PY_VLM:-~/YTAI/environment/.venv_vlm/bin/python}
PY_LLM=${PY_LLM:-~/YTAI/environment/.venv_llm/bin/python}
PY=${PY:-python3}
export HF_HOME=~/YTAI/models/huggingface
export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH
cd "$W6" || exit 1
[ -f "$W6/prep_config.json" ] || { echo "нет $W6/prep_config.json — карточка проекта не заведена"; exit 1; }
SRC="${SRC:-$($PY -c "import proj_config as P; print(P.SRC)")}"
PROJ_NAME="$($PY -c "import proj_config as P; print(P.PROJECT)")"
# Сколько кадров ждём: считаем от длительности ИМЕННО этого ката (было зашито 2439).
EXPECT_FRAMES="$($PY -c "import proj_config as P; print(P.expect_frames())")"
FRAMES_MIN=$(( EXPECT_FRAMES - $($PY -c "import proj_config as P; print(P.FRAMES_TOLERANCE)") ))
[ -s "$SRC" ] || { echo "нет исходника: $SRC"; exit 1; }

tg() { TG_BOT_TOKEN=$(cat ~/.config/rscore-tg/rya.token 2>/dev/null) ~/bin/tg.py text rya 155880671 "$1" --parse html >/dev/null 2>&1 || true; }
mark() { echo "[$(date +%H:%M:%S)] $1" | tee -a "$LOG"; }
echo RUNNING > prep.status

timeout_run() { # timeout_run <sec> <cmd...>  (macOS без coreutils timeout)
  local tmo=$1; shift
  "$@" & local pid=$!
  ( sleep "$tmo" && kill -9 $pid 2>/dev/null ) & local wd=$!
  wait $pid; local rc=$?
  kill $wd 2>/dev/null; wait $wd 2>/dev/null
  return $rc
}

stage() { # stage <name> <timeout_min> <cmd...> — до 3 попыток, после каждой селфчек
  local name=$1 tmo=$2; shift 2
  local t0=$SECONDS
  for attempt in 1 2 3; do
    mark "STAGE_START $name (попытка $attempt)"
    timeout_run $((tmo*60)) "$@" >> "$LOG" 2>&1
    local rc=$?
    if $PY "$W6/s5_selfcheck.py" "$name" >> "$LOG" 2>&1; then
      mark "STAGE_OK $name ($(( (SECONDS-t0)/60 )) мин, rc=$rc)"
      tg "✅ v6-prep: <b>$name</b> готов за $(( (SECONDS-t0)/60 )) мин"
      return 0
    fi
    mark "STAGE_CHECK_FAIL $name (попытка $attempt, rc=$rc) — см. prep_check_$name.json"
    sleep 20
  done
  mark "STAGE_FAIL $name после 3 попыток"
  tg "🔴 v6-prep: стадия <b>$name</b> НЕ прошла селфчек после 3 попыток — смотри $LOG"
  return 1
}

frames_cmd() { # докачать недостающие кадры, если фон-ffmpeg не дошёл
  mkdir -p hires
  local n; n=$(ls hires/h*.jpg 2>/dev/null | wc -l | tr -d ' ')
  if [ "$n" -ge "$FRAMES_MIN" ]; then return 0; fi
  # если уже идёт фоновой ffmpeg — ждём его
  while pgrep -f "fps=1,scale=1920:-2" >/dev/null; do sleep 15; done
  n=$(ls hires/h*.jpg 2>/dev/null | wc -l | tr -d ' ')
  if [ "$n" -lt "$FRAMES_MIN" ]; then
    mark "frames: есть $n из $EXPECT_FRAMES — перегоняю 4K целиком (стадия не возобновляема)"
    rm -f hires/h*.jpg
    ffmpeg -hide_banner -v error -hwaccel videotoolbox -i "$SRC" -vf "fps=1,scale=1920:-2" -q:v 2 hires/h%04d.jpg
  fi
}

mark "PREP start ($PROJ_NAME, кат $SRC, ждём $EXPECT_FRAMES кадров)"
tg "🌙 <b>$PROJ_NAME v6-prep стартовал</b>: кадры → OCR → VLM 7B → LLM 8B → селфчек. Всё локально."
ok=1
stage frames 45 frames_cmd || ok=0
[ $ok = 1 ] && { stage ocr 40 $PY "$W6/s2_ocr_hires.py" || ok=0; }
[ $ok = 1 ] && { stage vlm 240 $PY_VLM "$W6/s3_vlm.py" || ok=0; }
[ $ok = 1 ] && { stage llm 180 $PY_LLM "$W6/s4_llm.py" || ok=0; }
if $PY "$W6/s5_selfcheck.py" all >> "$LOG" 2>&1 && [ $ok = 1 ]; then
  echo OK > prep.status; mark "PREP OK"
  tg "🏁 <b>$PROJ_NAME v6-prep готов</b>, селфчек ALL OK — можно запускать аудит агентами."
else
  echo FAIL > prep.status; mark "PREP FAIL (см. prep_check_*.json)"
  tg "⚠️ v6-prep завершён с проблемами — смотри $W6/prep_check_all.json"
fi
