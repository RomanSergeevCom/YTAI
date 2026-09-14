# Восстановлено из логов сессий dbd19194, 7c6f6f58

Префикс: `/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review`

| файл | байт | источник | не легло правок |
|---|---:|---|---:|
| `PLAN_V2_DOC_URL.txt` | 604 | Write@dbd19194 | 0 |
| `a2_align.py` | 5467 | seed:d364a110/a2_align.py | 0 |
| `b_risk_v2.py` | 2932 | seed:d364a110/b_risk.py | 4 |
| `c2_chrono.py` | 4566 | seed:d364a110/c2_chrono.py | 0 |
| `c4_content_v2.py` | 34826 | Write@dbd19194 | 0 |
| `c5_header.py` | 9272 | Write@dbd19194 | 0 |
| `d2_doc_build.py` | 11221 | seed:d364a110/d2_doc_build.py | 0 |
| `d3_verify.py` | 5099 | Write@7c6f6f58 | 0 |
| `e2_tobe_content.py` | 29437 | Write@dbd19194 | 0 |
| `f2_structure_html.py` | 26095 | Write@7c6f6f58 | 0 |
| `make_review_v2_full.py` | 4513 | Write@7c6f6f58 | 0 |
| `notes_sync.py` | 13470 | Write@7c6f6f58 | 0 |
| `u_frames.py` | 3780 | seed:d364a110/u_frames.py | 0 |

## Не восстановлены (только Edit, базы нет)

- `d3_review_build.py` — правок 3

## Правки, которые не легли (old_string не найден — файл вычитать глазами)

- `b_risk_v2.py`:
  - `"""Риск-свип ката YTCH12 по стоп-реестру ТЗ (юр/этические ст…`
  - `    ('Насилие в паре (дерёмся/бьёт)',          True,  r'дер[…`
  - `    ('Учительница «била по голове»',           False, r'би[л…`
  - `    ('Имена третьих лиц (проверить контекст)', False, r'\bсе…`

## Edit, провалившиеся ещё в исходной сессии (пропущены — это не потеря)

- dbd19194 2026-08-27T08:15:13 Edit c5_header.py: провалился и в оригинале — пропущен
- 7c6f6f58 2026-09-06T06:07:15 Edit d3_review_build.py: провалился и в оригинале — пропущен
- 7c6f6f58 2026-09-07T10:33:55 Edit f2_structure_html.py: провалился и в оригинале — пропущен
- 7c6f6f58 2026-09-07T10:33:57 Edit f2_structure_html.py: провалился и в оригинале — пропущен
- 7c6f6f58 2026-09-07T10:34:03 Edit f2_structure_html.py: провалился и в оригинале — пропущен

## Bash-команды, трогавшие эти файлы (sed -i / cp / mv — НЕ воспроизводятся, проверить вручную)

- 2026-08-27T07:36:44 dbd19194 [по префиксу]: `mkdir -p /Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review && cp /Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/v2_review/*.py /Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup`
- 2026-08-27T07:37:10 dbd19194 [по префиксу]: `cp /Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/v1_review/s2_ocr_screens.py /Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review/ && python3 /Users/romansergeev/YTAI/scripts/999_extra`
- 2026-08-27T07:39:23 dbd19194 [по префиксу]: `tail -5 /Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/logs/wordrole_v2_review.log; echo ---; SP=/private/tmp/claude-501/-Users-romansergeev-YTAI/dbd19194-53c5-4a23-beb9-6e7408dfbbef/scratchpad; mkdir -p $SP/fra`
- 2026-08-27T10:22:59 dbd19194 [по префиксу]: `cd /Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review && python3 - <<'EOF' import sys, os, json, urllib.parse sys.path.insert(0, os.path.expanduser('~/YTAI/scripts/999_extra/ytuvi_doctabs')) from`
- 2026-08-27T11:06:41 dbd19194 [d2_doc_build.py]: `cd /Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review && python3 - <<'EOF' import sys, os, json, urllib.parse sys.path.insert(0, os.path.expanduser('~/YTAI/scripts/999_extra/ytuvi_doctabs')) from`
- 2026-08-27T11:54:44 dbd19194 [e2_tobe_content.py]: `cd /Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review && cp e2_tobe_content.py e2_tobe_content.py.bak && echo ok`
- 2026-08-27T11:57:34 dbd19194 [u_frames.py]: `cd /Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review && python3 u_frames.py frames_wanted_tobe.json 2>&1 | tail -2 && python3 - <<'EOF' import sys, os, json, urllib.parse sys.path.insert(0, os.p`
- 2026-08-27T12:03:21 dbd19194 [d2_doc_build.py, e2_tobe_content.py]: `cd /Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review && python3 e2_tobe_content.py && python3 - <<'EOF' import sys, os, json, urllib.parse sys.path.insert(0, os.path.expanduser('~/YTAI/scripts/9`
- 2026-09-06T06:03:41 7c6f6f58 [notes_sync.py]: `mkdir -p "/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/notes" cat > "/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/notes/note_test.json" << 'EOF' { "id": "TEST", "ts": "2026-09-06`
- 2026-09-06T06:04:22 7c6f6f58 [notes_sync.py]: `python3 << 'EOF' import json, sys sys.path.insert(0,'/Users/romansergeev/YTAI/scripts/999_extra/ytuvi_doctabs') from doctab_lib import api sid='1x0OP7vvd9hUzfNCjekbdpCm1kkY6Dr5QxQ9jGn_v_eQ' gid=json.load(open('/Volumes/T`
- 2026-09-06T06:04:40 7c6f6f58 [по префиксу]: `python3 << 'EOF' import json, sys, urllib.parse sys.path.insert(0,'/Users/romansergeev/YTAI/scripts/999_extra/ytuvi_doctabs') from doctab_lib import api S='/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Revie`
- 2026-09-06T06:06:50 7c6f6f58 [по префиксу]: `python3 << 'EOF' import json from bisect import bisect_right V='/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review/' final=json.load(open(V+'review_rows_final.json')) plan=json.load(open(V+'doc_c`
- 2026-09-06T06:07:03 7c6f6f58 [d2_doc_build.py]: `cp "/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review/d2_doc_build.py" "/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review/d3_review_build.py"`
- 2026-09-06T06:09:29 7c6f6f58 [PLAN_V2_DOC_URL.txt]: `cat >> "/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review/PLAN_V2_DOC_URL.txt" << 'EOF' YTCH11_Review_v2_video (ревью v2 ПО ВИДЕО — отсмотр: 15 глав-карточек + 57 кусков, полная транскрибация с `
- 2026-09-06T07:05:08 7c6f6f58 [по префиксу]: `python3 << 'EOF' import json, re V='/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review/' SCR='/private/tmp/claude-501/-Users-romansergeev-YTAI/7c6f6f58-2b04-40d5-9077-3eaa44a56535/scratchpad' c=j`
- 2026-09-06T07:08:05 7c6f6f58 [f2_structure_html.py]: `open "/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/YTCH11_v3_structure.html" cat >> "/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/TICKET_review_cycle_video_v2.md" << 'EOF' ## + 06.09: структура фил`
- 2026-09-06T07:08:17 7c6f6f58 [f2_structure_html.py]: `V="/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review" SCR="/private/tmp/claude-501/-Users-romansergeev-YTAI/7c6f6f58-2b04-40d5-9077-3eaa44a56535/scratchpad" cp "$SCR/tobe_acts.json" "$V/tobe_act`
- 2026-09-07T09:26:09 7c6f6f58 [по префиксу]: `python3 << 'EOF' import json, re V='/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review/' gems=json.load(open(V+'source_gems.json')) def toks(t): return re.findall(r'[А-Яа-яЁёA-Za-z0-9]+', t.lower`
- 2026-09-07T09:26:28 7c6f6f58 [по префиксу]: `python3 << 'EOF' import json, os, re V='/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review/' SCR='/private/tmp/claude-501/-Users-romansergeev-YTAI/7c6f6f58-2b04-40d5-9077-3eaa44a56535/scratchpad/`
- 2026-09-07T10:38:35 7c6f6f58 [по префиксу]: `python3 << 'EOF' import json V='/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review/' reps=json.load(open(V+'source_gems_new.json')) res=json.load(open('/private/tmp/claude-501/-Users-romansergeev`

## Довосстановлено отдельным прогоном

- `d3_review_build.py` — база `d2_doc_build.py` (cp 06.09, сессия 7c6f6f58) + 2 успешных Edit; `--map d3_review_build.py=d2_doc_build.py`
