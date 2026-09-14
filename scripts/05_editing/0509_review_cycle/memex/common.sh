#!/bin/bash
# common.sh — общие переменные для memex/*.sh (source'ится).
# Memex = «глаза»: качает кат, режет кадры, OCR, транскрипт, VLM, LLM, пробы — автономно.
# Код на Memex = rsync-копия папки стадии из репо (там нет git); данные — ~/YTAI_work/{CODE}/.
set -uo pipefail
MX_HOST=${MX_HOST:-memex}
MX_PATH='export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH; export HF_HOME=$HOME/YTAI/models/huggingface;'
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE_DIR="$(cd "$HERE/.." && pwd)"                       # …/0509_review_cycle
YTAI_DIR="$(cd "$STAGE_DIR/../../.." && pwd)"             # ~/YTAI
REL_STAGE=${STAGE_DIR#"$YTAI_DIR/"}                       # scripts/05_editing/0509_review_cycle
ROOT=${1:?usage: $0 <project_root>}
CODE=${YTAI_CODE:-$(basename "$ROOT" | sed -E 's/^(YT[A-Z]{2,4}[0-9]+)_.*/\1/')}
REVIEW_DIR="$ROOT/00_Setup/05_Review"
CARD="$REVIEW_DIR/review_card.json"
MX_ROOT="\$HOME/YTAI_work/$CODE"
MX_REVIEW="$MX_ROOT/00_Setup/05_Review"
MX_REVIEW_ABS="/Users/romansergeev/YTAI_work/$CODE/00_Setup/05_Review"
[ -f "$CARD" ] || { echo "нет карточки $CARD"; exit 2; }
cardval() { python3 -c "import json,sys;d=json.load(open('$CARD'));v=d.get('$1','');print(v if not isinstance(v,(list,dict)) else json.dumps(v,ensure_ascii=False))"; }
CUT=$(cardval cut_version); CUT=${CUT:-v1}
CHANNEL=$(cardval channel)
mx() { ssh -o ConnectTimeout=8 -o BatchMode=yes "$MX_HOST" "$MX_PATH $*"; }
