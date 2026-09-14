#!/bin/bash
# YTCH12 v4 (montage_1 от 09.09) — локальный разбор, ноль облачных токенов.
# Ждёт завершения загрузки (pid rclone) → байт-сверка → ffprobe →
#   [фон] кадры 1 fps 1280px → OCR Apple Vision (s2)
#   [фон] техконтроль ffmpeg: blackdetect/freezedetect/scene-cuts/silencedetect/ebur128
#   [основной] wordrole v4 (mlx-whisper large-v3 + pyannote) — ПОСЛЕ v3 (один mlx за раз)
#   → VLM-свип Qwen2.5-VL (s4) — после whisper (тоже mlx)
# Каждая стадия пишет строку «STAGE <имя> OK|FAIL» — по ним следит Monitor.
set -u
RENDER=/Volumes/T9-Black-RYA/YTCH/YTCH12_Sveta/03_Exports/YTCH12_Sveta_montage_1.mp4
EXPECT=24202793779
REV=/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review
W=$REV/v4_review
DLPID=$(cat /Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/logs/download_montage_1.pid)
PYT=$HOME/YTAI/environment/.venv_transcribe/bin/python
PYV=$HOME/YTAI/environment/.venv_vlm/bin/python
ts() { date '+%H:%M:%S'; }

echo "[$(ts)] wait download pid $DLPID"
while kill -0 "$DLPID" 2>/dev/null; do sleep 20; done
SZ=$(stat -f %z "$RENDER" 2>/dev/null || echo 0)
if [ "$SZ" != "$EXPECT" ]; then
  echo "[$(ts)] STAGE download FAIL size=$SZ expected=$EXPECT"
  exit 1
fi
echo "[$(ts)] STAGE download OK size=$SZ"

ffprobe -v error -show_format -show_streams -of json "$RENDER" > "$W/probe.json" \
  && echo "[$(ts)] STAGE probe OK" || echo "[$(ts)] STAGE probe FAIL"

# [фон A] кадры → OCR
(
  ffmpeg -hide_banner -nostats -loglevel error -hwaccel videotoolbox -i "$RENDER" \
    -vf "fps=1,scale=1280:-2" -q:v 3 "$W/frames1s/f%04d.jpg" \
    && echo "[$(ts)] STAGE frames OK n=$(ls "$W/frames1s" | wc -l | tr -d ' ')" \
    || { echo "[$(ts)] STAGE frames FAIL"; exit 1; }
  cd "$W" && python3 -u s2_ocr_screens.py > "$W/ocr.log" 2>&1 \
    && echo "[$(ts)] STAGE ocr OK $(tail -2 "$W/ocr.log" | tr '\n' ' ')" \
    || echo "[$(ts)] STAGE ocr FAIL"
) &
CHAIN_A=$!

# [фон B] техконтроль
(
  ffmpeg -hide_banner -nostats -hwaccel videotoolbox -i "$RENDER" -filter_complex \
    "[0:v]scale=480:-2,split=2[va][vb];[va]blackdetect=d=0.4:pix_th=0.10,freezedetect=n=0.003:d=2[vo1];[vb]select='gt(scene,0.30)',showinfo[vo2];[0:a]silencedetect=n=-45dB:d=1.5,ebur128=peak=true[ao]" \
    -map "[vo1]" -f null - -map "[vo2]" -f null - -map "[ao]" -f null - \
    2> "$W/qc_ffmpeg.log" \
    && echo "[$(ts)] STAGE qc OK" || echo "[$(ts)] STAGE qc FAIL"
) &
CHAIN_B=$!

# [основной] whisper — один mlx-процесс за раз: ждём транскрипт v3
while pgrep -f "wordrole_transcribe.py.*YTCH12_v3" >/dev/null; do sleep 30; done
echo "[$(ts)] STAGE wordrole_v4 START"
"$PYT" -u "$HOME/YTAI/scripts/999_extra/wordrole_transcribe.py" \
  --media "$RENDER" --language ru --out-dir "$REV" --base YTCH12_v4 \
  --title "YTCH12 монтаж v4 (montage_1 от 09.09)" --plain --max-speakers 6 \
  > "$W/wordrole_v4.log" 2>&1 \
  && echo "[$(ts)] STAGE wordrole_v4 OK" || echo "[$(ts)] STAGE wordrole_v4 FAIL"

# VLM нужны кадры (цепочка A) — ждём её, затем свип (mlx после whisper)
wait "$CHAIN_A"
cd "$W" && "$PYV" -u s4_vlm_sweep.py > "$W/vlm.log" 2>&1 \
  && echo "[$(ts)] STAGE vlm OK" || echo "[$(ts)] STAGE vlm FAIL"

wait "$CHAIN_B"
echo "[$(ts)] STAGE ALL DONE"
