#!/bin/bash
# Verify Sync — запускается кнопкой «Verify Sync» во вкладке Ingest панели.
# Панель сохраняет проект и кладёт заказ в /tmp/ytai_verify_sync.json;
# здесь снимается дамп сохранённого .prproj и меряется звук каждой пары
# дорожек активной секвенции. Вердикт в кадрах уходит обратно в панель.
cd "$(dirname "$0")" || exit 1
REQ="/tmp/ytai_verify_sync.json"
if [ ! -f "$REQ" ]; then
  echo "No request at $REQ — press «Verify Sync» in the panel."
  read -r -n 1 -p "Press any key to close…"
  exit 1
fi
python3 verify_sync.py --request "$REQ"
echo
echo "The verdict is in the panel status line; the full table is in the Ingest log."
read -r -n 1 -t 30 -p "This window closes in 30 s (or press any key)…"
