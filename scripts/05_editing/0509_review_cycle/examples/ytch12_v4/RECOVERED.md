# Восстановлено из логов сессий 4de45847

Префикс: `/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/v4_review`

| файл | байт | источник | не легло правок |
|---|---:|---|---:|
| `a4_align_v4.py` | 8205 | Write@4de45847 | 0 |
| `b_risk_v4.py` | 4146 | Write@4de45847 | 0 |
| `c_chapters_v4.py` | 2808 | Write@4de45847 | 0 |
| `d4_review_build.py` | 11496 | Write@4de45847 | 0 |
| `d4_verify.py` | 4536 | Write@4de45847 | 0 |
| `doc_tab_tz_v4.py` | 22000 | Write@4de45847 | 0 |
| `doc_tab_tz_v4_verify.py` | 4620 | Write@4de45847 | 0 |
| `finalize_v4.sh` | 2003 | Write@4de45847 | 0 |
| `h_summary_v4.py` | 9187 | Write@4de45847 | 0 |
| `make_light_4k.sh` | 1820 | Write@4de45847 | 0 |
| `make_review_v4.py` | 8261 | Write@4de45847 | 0 |
| `make_review_v4_full.py` | 4963 | Write@4de45847 | 0 |
| `mk_cards_v4.py` | 7148 | Write@4de45847 | 0 |
| `mk_tz_lt_v4.py` | 4221 | Write@4de45847 | 0 |
| `notes_sync.py` | 13587 | base:ytch11_v2/notes_sync.py | 0 |
| `p_packs.py` | 8429 | Write@4de45847 | 0 |
| `p_pravki_v4.py` | 16073 | Write@4de45847 | 0 |
| `qc_parse.py` | 3133 | Write@4de45847 | 0 |
| `r_rows_v4.py` | 10232 | Write@4de45847 | 0 |
| `run_local_v4.sh` | 3146 | Write@4de45847 | 0 |
| `speakers.json` | 44 | Write@4de45847 | 0 |
| `synth_manual.json` | 10317 | Write@4de45847 | 0 |
| `t_vlm_ru.py` | 2256 | Write@4de45847 | 0 |
| `u_frames.py` | 3801 | base:ytch11_v2/u_frames.py | 0 |
| `u_media_v4.py` | 5019 | Write@4de45847 | 0 |
| `x_structure_local.py` | 6725 | Write@4de45847 | 0 |
| `x_synth_local.py` | 3959 | Write@4de45847 | 0 |
| `x_wf_extract.py` | 3486 | Write@4de45847 | 0 |

## Edit, провалившиеся ещё в исходной сессии (пропущены — это не потеря)

- 4de45847 2026-09-10T08:07:05 Edit notes_sync.py: провалился и в оригинале — пропущен
- 4de45847 2026-09-10T11:03:08 Edit p_pravki_v4.py: провалился и в оригинале — пропущен

## Bash-команды, трогавшие эти файлы (sed -i / cp / mv — НЕ воспроизводятся, проверить вручную)

- 2026-09-10T07:57:33 4de45847 [notes_sync.py, u_frames.py]: `S=/Users/romansergeev/YTAI/scripts/999_extra/wordrole_transcribe.py grep -nE "_wordrole_work|add_argument|HF_TOKEN|hf_token|token" "$S" | head -40 REV=/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review W=$REV/v4_`
- 2026-09-10T08:01:59 4de45847 [по префиксу]: `P=/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta W=$P/00_Setup/05_Review/v4_review ls -la $P/00_Setup/02_Assembly/ | head -40 python3 - <<'EOF' import json W='/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/v4_review`
- 2026-09-10T08:02:15 4de45847 [по префиксу]: `W=/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/v4_review A=/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/02_Assembly python3 - <<'EOF' import re, html, json A='/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_`
- 2026-09-10T08:32:25 4de45847 [p_packs.py]: `cd /Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/v4_review && python3 - <<'EOF' import json W='/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review' d=json.load(open(W+'/YTCH12_v4.words.json')) starts=`
- 2026-09-10T08:34:16 4de45847 [по префиксу]: `cd /Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/v4_review && python3 - <<'EOF' import json, re P='/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta' asm=json.load(open(P+'/00_Setup/YTCH12_Claude4_assembly.json',encod`
- 2026-09-10T09:25:13 4de45847 [u_media_v4.py]: `cd /Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/v4_review && echo '["f0074.jpg","lt_gulya.png"]' > /private/tmp/claude-501/-Users-romansergeev-YTAI/4de45847-b922-401d-971c-97057cf921d5/scratchpad/w_test.jso`
