# Контракты стадии 0509_review_cycle

Все файлы — JSON (UTF-8, `ensure_ascii=False`, отступ 1). Поля с `?` — необязательные.
Схемы версионируются полем `schema`; читатели принимают текущую и предыдущую версию.

## 1. `review_card.json` — карточка фильма (лежит в `{project}/00_Setup/05_Review/`)

Единственный источник проектных констант. Скрипты падают с текстом, если ключа нет,
а не подставляют значения прошлого фильма. Любой ключ перебивается окружением `YTAI_<KEY>`.

| ключ | тип | смысл |
|---|---|---|
| `schema` | `"review-card-v1"` | версия |
| `project` | str | короткий id в нижнем регистре (`ytuvi02`) — имя каталога пауз `~/.cache/<project>/` |
| `code` | str | `YTUVI02` — префикс выходных файлов |
| `channel` | str | код канала (`YTUVI`, `YTCH`, `YTEVO`) → `YTs/{channel}/review_profile.json` |
| `mode` | `cut_review` \| `montage_tz` | режим |
| `cut_version` | str | `v1` — имя подпапки `work/{cut_version}/` |
| `project_dir` | path | корень проекта (`…/YTUVI02_Ruby_Certificate`) |
| `src` | path | кат (mp4) локально |
| `cut_drive`? | str | `gdrive:…/file.mp4` — откуда Memex качает кат |
| `render`? | path | лёгкая копия ката для UXP (если не `src`) |
| `words` | path | транскрипт `{CODE}_{cut}.words.json` (wordrole) |
| `duration_sec` | float | длительность ката |
| `fps` | int | 25 |
| `frames_tolerance`? | int | допуск числа кадров 1 fps |
| `chapters` | `[[sec, "NN"], …]` | границы глав ката |
| `ch_name` | `{ "NN": "Название", … }` | имена глав |
| `ch_img`? | `{ "NN": "file.jpg" }` | кадр-карточка главы |
| `sub`? | `{ "NN": [[sec, "подглава"], …] }` | подглавы |
| `prog`? | `{ "NN": {"title": …, "items": [[sec, "пункт"], …]} }` | перечисления «N из M» |
| `new_ch`? | `["NN", …]` | главы, которых нет в кате (➕) |
| `film` | str | одна строка: что за фильм, кто ведёт, канал |
| `film_subject`? | str | тема одним словом (для промптов) |
| `sources`? | `[str]` | авторитеты факт-чека именно этого фильма (дополняют профиль) |
| `ocr_anchors`, `llm_anchors` | list / dict | тексты ИМЕННО этого ката для селфчеков; пусто = проверка пропущена |
| `screens_range`? | `[first, last]` | ограничить инвентарь экранов |
| `doc_id`, `tab_title`, `nav_tab`? | str | док сценария, имя вкладки ТЗ, имя вкладки-навигатора |
| `frozen_tabs`? | `[[doc_id, tab_title], …]` | вкладки, которые нельзя перезаписывать |
| `materials_id`, `project_folder_id`, `sprint_folder_id` | str | Drive-папки |
| `sheet_url`?, `notes_sheet_id`? | str | лист ТЗ, лист заметок |
| `shots_remote`? | str | rclone-remote публичной папки кадров для `=IMAGE` |
| `terms_file`? | str | `review_terms.json` рядом с карточкой |
| `plan_file`? | str | `montage_plan.json` (режим montage_tz) |
| `clips`?, `speakers`? | list / dict | режим montage_tz: клипы встык, роли |
| `notes`? | `[str]` | грабли проекта — печатаются в `REVIEW_STATE.md` |
| `verify_tz`?, `verify_first_tz`? | dict / str | проверки «по содержанию ТЗ» для verify-скриптов |

Пути внутри карточки могут быть относительными к папке карточки.

## 2. `YTs/{CH}/review_profile.json` — профиль канала (в репо)

| ключ | смысл |
|---|---|
| `style` | `{ivory, red, mut, bg, panel, font_stack, mockup_style}` — цвета/шрифты графики V3–V6 |
| `ch_marker_colors` | цвета маркеров глав по кругу |
| `rules_text` | канон канала для промптов (валюта, язык титров, локации на карте, имена мест) |
| `tz_classes` | `{keep: [...], drop: [...]}` — какие классы находок попадают в ТЗ |
| `sources_default` | авторитеты факт-чека по умолчанию |
| `latin_whitelist` | латинские токены, которые не считаются «английским без перевода» |
| `terms_base` | общие термины канала (та же структура, что `review_terms.json`) |
| `sensitivity`? | YTCH: `{policy: "fund_confirm", mark: "⚠️", never_cut: true, patterns: [...]}` |
| `structure_rules`? | YTCH: `{fund_entry_min, teaser_rule, last_sound_rule}` |
| `doc` | `{tab_tz_template: "ТЗ монтажёру · {ver}", nav_template: "Ревью {ver} по видео"}` |
| `drive` | `{materials_folder: "Review_materials"}` |
| `notes_cycle` | bool — заводить ли notes-цикл по умолчанию |
| `mode_default` | `cut_review` \| `montage_tz` |

## 3. `review_terms.json` — термины и места фильма (рядом с карточкой)

```
{ "schema": "review-terms-v1",
  "terms":  [ {"key": "corundum", "rx": "корунд\\w*", "title": "КОРУНД", "sub": "corundum", "def": "…"} ],
  "extra":  { "key": {"def_short": "…"} },
  "places": [ {"key": "myanmar", "kind": "country", "title": "МЬЯНМА", "old": "БИРМА", "renamed": 1989,
               "rx": "…", "parent": null, "role": null, "sub": "…", "note": "…", "points": [[lon, lat]], "label": "…"} ],
  "map_windows": [ [t0, t1, "mapfull_belt", "…"] ],
  "confusables": [ ["дуплет", "дублет"] ],
  "canon_words": ["Gübelin", "yuvi.ru"] }
```
`terms_catalog.py` = загрузчик: `profile.terms_base` + этот файл → те же экспорты `TERMS, LOCS, PLACE, PLACES,
TERM_EXTRA, TERM_RX, LOC_RX, MAP_WINDOWS, place_family`.

## 4. `review_state.json` — стейт-машина (рядом с карточкой)

```
{ "schema": "review-state-v1", "code": "YTUVI02", "cut_version": "v1", "mode": "cut_review",
  "host_policy": {"prep": "memex", "surfaces": "mac"},
  "stages": { "<name>": {"status": "todo|running|done|failed|awaiting_cloud|blocked_gui|skipped",
                         "host": "mac|memex", "started": iso, "finished": iso, "attempts": n,
                         "inputs_hash": "sha1", "outputs": {...}, "check_file": path, "log": path} },
  "cloud": { "run_ids": [], "batches": { "<batch_id>": {"status": "pending|done", "in": path, "out": path, "source": "agent|journal|task-output"} },
             "unverified": 0 },
  "pravki": {"count": n, "max_num": n, "rejected": n},
  "surfaces": {"review_json": {...}, "doc_tz": {...}, "doc_nav": {...}, "sheet": {...}, "drive": {...}},
  "updated": iso }
```
Стадия `done` пропускается при повторном `run`, если её `inputs_hash` не изменился (`--force` гоняет заново).

## 5. `pravki/pravki.json` — источник истины всех поверхностей

`{"all": [ ТЗ, … ]}`; запись ТЗ:

| поле | смысл |
|---|---|
| `num` | int — номер ТЗ; никогда не переиспользуется |
| `title` | заголовок |
| `category` | `graphics` \| `cut` \| `insert` \| `structure` … |
| `class`? | класс находки: `typo` \| `grammar` \| `fact` \| `currency` \| `language` \| `mismatch` \| `foreign_trace` \| `structure` |
| `source` | `audit` \| `structure` \| `notes` \| `manual` |
| `v1_tc`, `tc_range` | таймкоды ката |
| `timeline_in_sec`, `timeline_out_sec` | секунды для таймлайна |
| `est` | ❌ СЕЙЧАС — что на экране |
| `nado` | отрендеренный текст блоков (генерится из `parts`) |
| `parts` | `{now: [{h, items[]}], do: [{h, items[]}], list?, where?, source?, timeline?}` — структурная истина |
| `material_rich` | `[{t, img, src?, src_auto?}]` — материалы: подпись, картинка, источник |
| `typo` | `[{tc, was, now}]` — пары «было → стало» |
| `decision`? | ❓ вопрос Роману |
| `status`? | `rejected` — Роман снял строку (номер сохранён) |
| `rejected_by`?, `roman_comment`?, `replies`?, `sheet_answer`? | обратная связь |
| `skeptic`? | `{code: T|V|H|C|F|D, reason}` — вердикт скептика |
| `sensitive`? | YTCH: `{flag: true, reason}` — ⚠️ на подтверждение фонда |
| `notes` | ids заметок/источников |

## 6. `work/{cut}/candidates.json` — маршрутизация кандидатов (0 токенов)

```
[ {"cand_id": "c0012", "screen_id": "s031", "kind": "typo", "on_screen_text": "ВЫСОКВАЯ", "line_idx": 2,
   "fix_local": "ВЫСОКАЯ", "signals": ["ocr=vlm=zoom", "vo_match:0.91"], "route": "auto_confirm|cloud|drop",
   "route_reason": "три чтения совпали, исправление из озвучки", "need_frame": false} ]
```

## 7. Облако — один проход `cloud/wf_judge.js`

Инструменты: `cloud/pack.py` (пакеты, 0 токенов) → `Workflow({scriptPath: cloud/wf_judge.js, args})` (вызов печатает
`pack.py --print-call`) → `cloud/collect.py` (сбор, покрытие, `audit_findings.json`) → `stages/s8_apply_audit.py`.
Спасение результатов упавшего прогона и таблица стоимости — `cloud/salvage.py`. Общий код — `cloud/cloudlib.py`.
Цикл: прогон 1 = J (+ скептик по его результатам) → collect → `pack.py` (при всех J done сам добирает F/V/S) →
прогон 2 = F ‖ V → S → collect (exit 0). Args воркфлоу — только пути; пакеты агенты читают сами (Read).

**Вход пакета J** `cloud/in/J_<nn>_<sha8>.json` (≤50 экранов, ≤60 кандидатов, ≤120 КБ; `sha8` = sha1 блока `screens` —
шапка film/rules/existing_tz в хеш не входит, иначе каждое новое ТЗ переупаковывало бы фильм):
```
{ "batch_id": "J_01_ab12cd34", "sha8": "ab12cd34", "kind": "J", "film": "...", "rules": "...", "existing_tz": ["ТЗ-01 · 0:57 · …"],
  "summary": {"auto_confirmed": n, "dropped": m, "cloud": k}, "n_screens", "n_candidates", "range_tc",
  "screens": [ {"id": "s031", "tc": "5:12", "t0": 312, "t1": 318, "chapter": "03", "frame": "h0313.jpg",
                "ocr_lines": [{"i": 0, "t": "…"}], "ocr_last"?: "…", "vlm_text": "…", "vlm_desc": "…", "vo": "…",
                "local_flags": {"typo_susp": [...], "latin_ratio": 0.1, "numbers_screen": [...], "numbers_vo": [...],
                                "probe_foreign": false, "dup_of": null, "llm"?: {currency, english, facts, mismatch}},
                "candidates": [ {"cand_id", "kind", "text", "line_idx", "fix_local", "route_reason", "signals"} ] } ] }
```
Без `candidates.json` пакеты собираются с пустыми `candidates[]` (предупреждение в stderr). Экран, уже покрытый
done-батчем с тем же хешем записи, второй раз не пакуется; done-батчи не трогаются.

**Выход J** `cloud/out/J_<nn>_<sha8>.json` (агент СНАЧАЛА пишет файл Write'ом, затем возвращает по схеме):
```
{ "batch_id", "sha8",
  "verdicts": [ {"cand_id", "screen_id", "kind", "verdict": "confirm|refute|need_frame|fact_check", "reason", "on_screen_text",
                 "fix_text", "existing_tz", "severity", "confidence"} ],
  "new_findings": [ {"screen_id", "kind", "on_screen_text", "line_idx", "problem", "fix_text", "why", "severity", "existing_tz"} ],
  "need_frames": [ {"screen_id", "cand_id", "on_screen_text", "what_to_look_at"} ],
  "facts_to_check": [ {"screen_id", "cand_id", "claim", "on_screen_text"} ],
  "clean_screens": ["s001", …], "notes" }
```
Код проверяет покрытие: каждый экран пакета должен быть в `verdicts`/`new_findings`/`clean_screens`; непокрытые
досылаются пакетом `J_<nn>b_<sha8>` (collect.py делает его сразу).

**Идентификаторы находок** (детерминированы, считают и python, и wf_judge.js): вердикт по кандидату → `cand_id`;
новая находка → `<J batch>.n<NN>`; факт без кандидата → `<F batch>.f<NN>`; вопрос к кадру → `<V batch>.q<NN>`.

**F (факт-чек, 1 агент):** вход `in/F_<sha8>.json` = `{batch_id, sha8, kind: "F", film, rules, sources, items: [{fact_id, screen_id,
cand_id, claim, on_screen_text}]}` (facts_to_check судей + вердикты fact_check + локальные utverzhdenija с числом;
потолок `profile.fact_check.max_claims`); выход `out/F_<sha8>.json` = `{batch_id, sha8, results: [{fact_id, screen_id, cand_id, claim,
on_screen_text, status: verified|wrong|unclear, correct_value, source_url, note}]}`. `wrong` без кандидата → новая находка kind fact.
**V (кропы, 1 агент):** вход `in/V_<sha8>.json` = `{batch_id, sha8, kind: "V", images: [...], items: [{q_id, screen_id, cand_id, tc,
what_to_look_at, on_screen_text, image, cell?}]}` — кропы ≤800 px из `hires` по bbox строки (`cloud/crops/V_<sha8>/`),
при >16 — контактные листы 4×4 ≤1568 px с подписью q_id в ячейке; выход `out/V_<sha8>.json` = `{batch_id, sha8, results: [{q_id,
screen_id, cand_id, on_screen_text, text_as_seen, error_visible, answer, confidence}]}` (`error_visible` — решающее поле для кода).
**S (скептик, 1 агент, текст):** два режима — `mode: "pack"` (`in/S_<sha8>.json` от `pack.py --skeptic`: `items[]` = находки
без вердикта скептика) и `mode: "run"` (`in` нет; id регистрирует `--print-call`, скептик судит результаты того же прогона);
выход `out/S_<sha8>.json` = `{batch_id, sha8, verdicts: [{finding_id, real, code: ""|T|V|H|C|F|D, reason, corrected_fix_text}]}`
(T вкус/вёрстка · V допустимый вариант · H буквы за головой → kind `check_source`, fix «проверить исходник титра» ·
C покрыто ТЗ-NN · F факт защитим · D дубль). По умолчанию real=true; коды T,V,C,F,D снимают находку.

**`cloud/state.json`**: `{schema: "review-cloud-state-v1", run_ids: [], batches: {id: {status: pending|done, kind: J|F|V|S, in, out,
source: agent|journal|agent-file|wf-meta|task-output, n, run_id?, screens? {sid: sha8}, covered?, uncovered?, mode?, covers?}}}`
— повтор отправляет только `pending`. Результат прогона воркфлоу: `{batches_done, batches_failed, summary, results: {batch_id: …}}`.
**`work/{cut}/audit_findings.json`** (`schema: "review-findings-v8"`): `{code, cut_version, run_ids, batches, summary,
findings: [ {finding_id, screen_id, tc, t0, t1, chapter, frame, kind, on_screen_text, line_idx, bbox{x,y,w,h}, fix_text, problem, why,
severity, route: cloud|auto_confirm|legacy, verdict, confidence, existing_tz, run_id, batch_id, skeptic?{real,code,reason,corrected_fix_text},
fact?{status,correct_value,source_url,note}, crop?{text_as_seen,error_visible,answer,confidence}, status, confirmed} ],
confirmed: [finding_id…], facts_ok, unmapped}`. `status`: confirm · new_finding · refute · pending_frame · pending_fact · unclear ·
refuted_by_skeptic; confirmed = статус confirm/new_finding (факт wrong, кроп error_visible) и скептик не снял.
`collect.py --from-legacy` переводит старый `audit_findings_v6.json` в находки `route: legacy`; `--emit-legacy` пишет старую
форму, если файла нет (её ещё читают s10_format_tz / review_page / doc_tab_review_v1). Коды выхода collect: 0 всё done · 3 есть pending.

## 8. `montage.json` — режим montage_tz (`schema: "ytai-montage-v1"`)

Вход `montage_plan.json`:
```
{ "pieces": [ {"id": 1, "title": "…", "block": "…", "act": "…",
               "parts": [ ["say", [hint_sec, "слово"], [hint_sec, "слово"]], ["gfx", "G03", 4.0], ["hold", "текст", 2.0] ],
               "gfx": [ ["G03", [hint_sec, "слово"]] ], "note": "…"} ],
  "gfx_catalog": [ {"id": "G03", "title": "…", "kind": "…", "place": "…"} ] }
```
Выход `montage.json`: `total, total_trimmed, source_total, pieces[{id,title,block,act,note,dst_in,dst_out,dur,dur_trimmed,
parts[{kind, src_in, src_out, dur, dst_in, dst_out, file_in, off_in, file_out, off_out, crosses_clip, camera, speaker, words, first, last, text, gaps, trim_est}],
gfx[{id, src, dst, on_word, kind, title, place}]}], gfx_catalog, gfx_used, n_say_parts, n_gaps`.

## 9. `{CODE}_review_v{N}.json` — таймлайн ревью (`schema: "ytai-part-v1"`, `build_model: "review_overlay"`)

Не меняется: `part{code, project_name, name, stage, fps, sequence_name, build_model, seed_clip, base_clip, base_clip_path,
markers, min_builder, chapter_markers, bin, created, note}`, `segments[{segment_id, role, track, audio_track, keep_audio,
color, source_file, source_path, clip_id, kind, use, speaker, source_in_sec, source_out_sec, timeline_in_sec, timeline_out_sec,
item_marker?}]`, `tracks`, `audio_policy`, `required_imports`, `counts`, `dropped`. Слои: V1 оригинал · V2 футажи ·
V3 инфографика · V4 плашки ТЗ · V5 стрелки · V6 структура; маркеры секвенции = только главы.
