#!/usr/bin/env bash
# refresh_site.sh — одна команда после регенерации любых страниц yt.rya.ae:
#   1) выдать пароли новым страницам (gen_access.py — старые не трогает; --force = перегенерить все)
#   2) вставить общую шапку-навигацию + клиент-гейт во все страницы (patch_site_chrome.py)
# Затем — commit + push (через Winston) для деплоя.
#
# Использование:
#   ./refresh_site.sh                 # обычный прогон
#   ./refresh_site.sh --force         # + перегенерировать ВСЕ пароли (portal/bypass сохраняются)
#   ./refresh_site.sh /path/to/web    # другой WEB_DIR
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$DIR/gen_access.py" "$@"
echo "----"
python3 "$DIR/patch_site_chrome.py"
echo "----"
echo "✓ refresh готов. Дальше: commit web/ + push (Winston) → GH Actions деплой."
