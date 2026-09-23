#!/bin/bash
# upload_proxies.sh <local_proxy_dir> <parent_folder_id> <proxy_folder_name>
# Заливает прокси в новую папку внутри Drive-папки проекта и добирает
# петличные WAV + транскрипты server-side копированием (без выгрузки с диска).
set -uo pipefail

LOCAL="$1"; PARENT="$2"; NAME="$3"
R="gdrive,root_folder_id=${PARENT}:"
FLAGS=(--tpslimit 8 --retries 5 --low-level-retries 20 --drive-chunk-size 64M --stats 60s --stats-one-line)
# exFAT-тома плодят AppleDouble ._* — на Drive это мусор
FLAGS+=(--exclude "._*" --exclude ".DS_Store")

echo "== mkdir «${NAME}»"
rclone mkdir "${R}${NAME}" "${FLAGS[@]}" || exit 1

echo "== upload прокси-видео"
rclone copy "$LOCAL" "${R}${NAME}" --transfers 4 --checkers 8 "${FLAGS[@]}" || exit 1

echo "== server-side: петличные WAV из оригинальных сцен"
for scene in $(rclone lsf "$R" --dirs-only | tr -d '/' | grep -E '^[0-9]{2}_'); do
  [ "$scene" = "00_LUT" ] && continue
  rclone copy "${R}${scene}" "${R}${NAME}/${scene}" --include "*.wav" \
    --transfers 4 "${FLAGS[@]}" 2>/dev/null
done

echo "== server-side: транскрипты"
rclone copy "${R}Transcription" "${R}${NAME}/Transcription" --transfers 8 "${FLAGS[@]}" 2>/dev/null

echo "== server-side: спаннер 1071 во вторую сцену"
rclone copyto "${R}${NAME}/06_Photo_Archive_Family/RYA-FX3-1071.MP4" \
              "${R}${NAME}/07_Knitting_Interview_And_Hands/RYA-FX3-1071__S10.MP4" "${FLAGS[@]}" 2>/dev/null

echo "== verify: локальные прокси == залитые"
rclone check "$LOCAL" "${R}${NAME}" --size-only --one-way "${FLAGS[@]}" 2>&1 | tail -5
RC=${PIPESTATUS[0]}

echo "== итог"
rclone size "${R}${NAME}" --fast-list
ID=$(rclone lsjson "$R" --dirs-only | python3 -c "import json,sys;print(next(d['ID'] for d in json.load(sys.stdin) if d['Name']=='''${NAME}'''))")
echo "PROXY_FOLDER_ID=${ID}"
echo "PROXY_FOLDER_URL=https://drive.google.com/drive/folders/${ID}"
exit $RC
