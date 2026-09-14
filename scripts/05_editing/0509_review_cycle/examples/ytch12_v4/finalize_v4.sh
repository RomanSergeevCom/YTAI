#!/bin/bash
# YTCH12 v4 — финальная сборка поверхностей ревью из результатов двух воркфлоу
# (wf_result.json — ревью, structure_v4.json — структура). Один JSON правок (pravki_v4.json) →
# док YTCH12_Review_v4 (вкладки «ТЗ монтажёру · v4» + «Ревью по видео · v4»), 6-слойный таймлайн, HTML.
# Каждый шаг печатает «STEP <имя> OK|FAIL»; на FAIL — стоп.
set -u
W=/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/v4_review
cd "$W" || exit 1
step() { local name=$1; shift; echo "[$(date +%T)] STEP $name …"; if "$@"; then echo "[$(date +%T)] STEP $name OK"; else echo "[$(date +%T)] STEP $name FAIL"; exit 1; fi; }

step chapters   python3 c_chapters_v4.py
step mockups    python3 mk_cards_v4.py
step pravki     python3 p_pravki_v4.py
step tz_lt      python3 mk_tz_lt_v4.py
step rows       python3 r_rows_v4.py
step wanted     python3 - <<'EOF'
import json, glob, os
W = '/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/v4_review'
want = set(json.load(open(f'{W}/frames_wanted_nav.json')))
for p in json.load(open(f'{W}/pravki_v4.json'))['all']:
    for it in p.get('material_rich') or []:
        if it.get('img'):
            want.add(it['img'])
for c in json.load(open(f'{W}/viewer_chapters.json')):
    if c.get('img'):
        want.add(c['img'])
want |= {os.path.basename(x) for x in glob.glob(os.path.join(os.path.dirname(W), 'mockups', '*.png'))
         if not os.path.basename(x).startswith('test_')}
json.dump(sorted(want), open(f'{W}/media_wanted.json', 'w'))
print('media wanted:', len(want))
EOF
step upload     python3 u_media_v4.py media_wanted.json
step tz_tab     python3 doc_tab_tz_v4.py
step tz_verify  python3 doc_tab_tz_v4_verify.py
step refresh    python3 u_media_v4.py --refresh
step nav_tab    python3 d4_review_build.py "$(python3 -c "import json;print(json.load(open('review_v4_doc.json'))['doc_id'])")"
step nav_verify python3 d4_verify.py
step part       python3 make_review_v4.py
step html       python3 h_summary_v4.py
echo "[$(date +%T)] ALL SURFACES DONE"
