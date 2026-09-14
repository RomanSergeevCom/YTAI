#!/bin/bash
# YTCH12 v4 — лайт-версия в 4K по канону прокси (reference_editing_proxy_pipeline):
# 3840×2160, тот же fps и ТО ЖЕ число кадров (меняется на оригинал без сдвигов),
# hevc_videotoolbox 8 Мбит/с + tag hvc1, звук — копией (без перекодирования).
# Рендер монтажёра 1920×1080 → масштаб аппаратный scale_vt (не грузит CPU разбора).
# Пишет во временный .encoding.mp4, после сверки кадров переименовывает в финальный.
set -u
IN=/Volumes/T9-Black-RYA/YTCH/YTCH12_Sveta/03_Exports/YTCH12_Sveta_montage_1.mp4
OUTD=/Volumes/T9-Black-RYA/YTCH/YTCH12_Sveta/03_Exports
TMP=$OUTD/YTCH12_v4_light_4K.encoding.mp4
OUT=$OUTD/YTCH12_v4_light_4K.mp4
PROG=/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/logs/light4k_progress.txt
ts() { date '+%H:%M:%S'; }

echo "[$(ts)] START $IN → $OUT"
ffmpeg -hide_banner -nostats -loglevel error -y \
  -hwaccel videotoolbox -hwaccel_output_format videotoolbox_vld -i "$IN" \
  -map 0:v:0 -map 0:a:0 \
  -vf "scale_vt=w=3840:h=2160" -fps_mode passthrough \
  -c:v hevc_videotoolbox -b:v 8M -tag:v hvc1 \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 \
  -c:a copy -movflags +faststart -progress "$PROG" -f mp4 "$TMP"
rc=$?
if [ $rc -ne 0 ]; then echo "[$(ts)] ENCODE FAIL rc=$rc"; exit 1; fi

SRC=$(ffprobe -v error -select_streams v:0 -show_entries stream=nb_frames -of csv=p=0 "$IN")
DST=$(ffprobe -v error -select_streams v:0 -count_packets -show_entries stream=nb_read_packets -of csv=p=0 "$TMP")
D_IN=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$IN")
D_OUT=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TMP")
if [ "$SRC" = "$DST" ]; then
  mv "$TMP" "$OUT"
  echo "[$(ts)] DONE OK frames $DST/$SRC · dur $D_OUT/$D_IN · size $(stat -f %z "$OUT") bytes"
else
  echo "[$(ts)] VERIFY FAIL frames $DST vs $SRC (оставлен $TMP)"
  exit 2
fi
