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
| `fps` | int \| float | 25 · 29.97 · 23.976 · 59.94 — NTSC-частоты считаются точной дробью `P.FPS_EXACT` (29.97 → 30000/1001): сетка tc таймлайна, стиллы, главы |
| `frames_tolerance`? | int | допуск числа кадров 1 fps |
| `lang`? | `"ru"` \| `"en"` \| `""` | язык поверхностей монтажёра; пусто/нет — `profile.lang`, иначе `ru`. Окружение `YTAI_LANG` перебивает |
| `language`? | str | язык озвучки для whisper (`--language`); нет — `lang` → `profile.lang`; `auto` не передаётся никогда. RU-карточка без ключей — без флага, как раньше |
| `exclusions`? | `[{t0, t1, reason}]` | заведомые не-ошибки ката (дыра футажа, недоделанные экраны): кандидаты в интервале → drop `known_exclusion`, экраны не пакуются в облако, находки не становятся ТЗ (`P.in_exclusion`, пересечение с границами включительно). Записи с `t0`/`t1` = null — заметка, в фильтр не идут (card check предупреждает) |
| `align_against`? | `[path]` | words.json прошлых версий/плана для стадии `align` (n-gram кат ↔ база → `work/{cut}/align.json`) |
| `chapters_plan`? | path | план частей `ytai-part-v1` (`part.chapter_markers[]` + `part.base_segments[]`) → стадия `chapters` ставит главы ката через align с прошлым рендером (первый не-сценовый words.json из `align_against`) |
| `canon_words`? | `[str]` | слова фильма, которые не опечатка (входят в `P.LEXICON` вместе с `profile.lexicon` + `latin_whitelist`) |
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
| `drop_segments`? | `[segment_id]` | экраны, которые Роман удалил на ревью-таймлайне (id сегментов прошлой сборки `{CODE}_review_v6.json`, читаются из автосейва .prproj). `make_review_v6` вырезает их ПОСЛЕ арбитража — остальные экраны остаются там, где он их отсматривал |
| `disabled_ranges`? | `[{t0, t1, why, source}]` | куски ката, выключенные на таймлайне (Clip → Enable, в .prproj `ClipTrackItem/IsMuted`) = «вырезать». `make_review_v6` режет V1 на `part.base_segments` (`on_NN` / `off_NN` + `disabled: true`, §9); `kb_visuals needs` не ищет визуал в бите, перекрытом > 50 %. ТЗ «вырезать» к куску заводится отдельно (YTUVI02: ТЗ-63) |
| `v2`? | `[{kind, sid, path, t, in?, out?, opts}]` | вставки слоя V2 (свои клипы и стиллы): `kind` `seg` (клип `in`→`out` в `t`) \| `still` (картинка в `t`, `opts.dur`); `path` абсолютный или с префиксом `FOOT/` `REFS/` `NAT/` `MOCK/`; `opts` зависит от `kind`: `seg` — {`keep_audio`, `speaker`, `kind`, `audio`, `prio`, `item_marker` {name, comment}}, `still` — {`dur`, `prio`, `item_marker`}; лишний ключ (например `dur` у `seg`) → TypeError в `make_review_v6`. Пишет `kb_visuals apply` (перезаписывает ключ целиком), читает `make_review_v6` (цвет Cyan) |
| `footage_routing`? | path | каталог своих съёмок для `kb_visuals pick`; нет — `{project}/00_Setup/FOOTAGE_ROUTING.md` |

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
| `lang`? | `ru` (по умолчанию) \| `en` — язык поверхностей монтажёра канала (YTCR = `en`); карточка `lang` перебивает. §10 |
| `lexicon`? | `[str]` — слова канала, которые не опечатка и не «чужой язык» (EN-словарь роутера; `P.LEXICON` = lexicon + latin_whitelist + card canon_words, нижний регистр) |
| `currency`? | EN: `{canon: "AED 2M", code_before: bool, suffix: ["K","M","B"], decimal: ".", group: ","}` — канон суммы для EN-правил роутера (`rule_currency_en`); формат-варианты того же значения — не ошибка |
| `verdict`? | `{enabled, kind: "editorial", acts_llm: false, propose_chapters: false}` — редакторский вердикт без `structure_rules` (YTCR): стадия `acts` идёт `--no-llm` на Mac, `verdict` — один облачный агент (`verdict_call.py`, EN-промпт по `args.lang`) |
| `probe`? | `{own_logo: "Core Realty"}` — собственный логотип канала: зонд s3b и роутер не считают его чужим следом (drop `own_logo`) |
| `ocr_langs`? | `["en-US"]` — языки Apple Vision для s2 (`bin/vision_ocr_ru --langs en-US`); нет — `ru-RU,en-US`. Список — подсказка Vision, кириллицу он всё равно прочтёт |
| `terms_base` | общие термины канала (та же структура, что `review_terms.json`) |
| `sensitivity`? | YTCH: `{policy: "fund_confirm", mark: "⚠️", never_cut: true, patterns: [...]}` |
| `structure_rules`? | YTCH: `{fund_entry_min, teaser_rule, last_sound_rule}` |
| `doc` | `{tab_tz_template: "ТЗ монтажёру · {ver}", nav_template: "Ревью {ver} по видео"}` |
| `drive` | `{materials_folder: "Review_materials"}` |
| `notes_cycle` | bool — заводить ли notes-цикл по умолчанию |
| `mode_default` | `cut_review` \| `montage_tz` |
| `kb`? | `{root, exclude_sources, min_side, per_beat, footage_root, books_manifest?, books_policy?, drive_originals_root?, drive_footage_root?}` — база знаний канала для `stages/kb_visuals.py`: `root` — папка с `_KB/index.sqlite` (FTS5 по подписям), `exclude_sources` — префиксы источников, которые не берём (YTUVI с 16.09.2026: пусто — база открыта целиком, включая `01_SSEF`), `min_side` (1000 px), `per_beat` (6 кандидатов на бит), `footage_root` — корень своих съёмок. `books_manifest` — размеченные половины страниц книг (YTUVI: `01_ScanBook-SSEF/02_Pages/halves_manifest.json` — сканы вынесены из базы, плохое качество: book, module, printed_page_no, heading, summary, content_type); `books_policy` `fallback` — книга идёт в кандидаты, только если ни одна картинка базы не прошла verify (метка «⚠️ скан книги — в базе не нашлось»), `always` (по умолчанию) — как раньше. `drive_originals_root` / `drive_footage_root` — id Drive-зеркала базы и папки своих съёмок: ссылки ТЗ на САМИ файлы (`shared/drive_links.py`, кэш `pravki/drive_originals_ids.json`). Нет ключа `kb` — корни `/nonexistent`, `kb_visuals pick` падает на открытии `_KB/index.sqlite` |

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
| `material_rich` | `[{t, img, src?, src_auto?}]` — материалы: подпись, картинка, источник (у вставок kb_visuals — «📄 файл целиком: <Drive-ссылка>#page=N · стр. N · 📁 папка: <ссылка>»; у своих клипов — оригинал в Drive-футаже; у макетов — строка на каждый исходник) |
| `kbv_group`? | группа `picks.json`, из которой запись собрал `kb_visuals apply`: по ней запись остаётся на СВОЁМ месте при повторном apply (номер ТЗ = позиция в `all`); убранная группа (`removed`) → `status: rejected`, `rejected_by: kb_visuals`, `removed_why` |
| `gen`? | `sub` \| `terms` \| `locs` — список из данных (подглавы / термины / места) в этой ТЗ; без поля s10 списков не ставит (по номеру ТЗ-30/75/76 — только у проекта ytuvi01) |
| `typo` | `[{tc, was, now}]` — пары «было → стало» |
| `decision`? | ❓ вопрос Роману |
| `status`? | `rejected` — Роман снял строку (номер сохранён) |
| `rejected_by`?, `roman_comment`?, `replies`?, `sheet_answer`? | обратная связь |
| `skeptic`? | `{code: T|V|H|C|F|D, reason}` — вердикт скептика |
| `sensitive`? | YTCH: `{flag: true, reason}` — ⚠️ на подтверждение фонда |
| `notes` | ids заметок/источников |

**Номер ТЗ = позиция записи в `all`** на всех поверхностях (s10, вкладка, verify, лист, таймлайн, doc_pdf_qc). Записи не
удаляются и не переставляются: снятое — `status: rejected`, новое — только в конец. `pravki/tz_overrides.json` привязан
к номерам (`"ТЗ-NN": {parts_replace | parts | material_rich | title …}`); поле `_title` — заголовок, под который писался
ручной текст: s10 пропускает оверрайд с `!!`, если у записи на этой позиции другой заголовок.

**Вкладка ТЗ (канон 5.6, v3 16.09.2026):** `№ | ⏱ TC | категория | ТЗ монтажёру | Говорит | Материал / ссылки`,
ширины `[30, 56, 20, 176, 132, 262]` pt. «Говорит» — `shared/said.py`: дословные слова `words.json` в окне `tc_range`
±3 с (до границ предложений; диапазон > 40 с — якорь ±10 с; ≤ 70 слов), абзацы по паузе ≥ 1,2 с / смене спикера,
жирным — слова в секунде `v1_tc`; у глав и ТЗ «весь фильм» пусто. verify: каждый абзац — подстрока потока слов.

**`work/{cut}/kb_visuals/picks.json`**: `groups[]` только дописываются (`removed: "<почему>"` вместо удаления),
`inserts[].sources` у макетов (`src: mock`) — `[{clip: путь|RYA-…} | {kb: путь картинки базы} | {url, note}]` → ссылки
на каждый исходник. `targets_<name>.json` → `kb_visuals targets` → `candidates_<name>.json` (тот же формат, что у битов).

## 6. `work/{cut}/candidates.json` — маршрутизация кандидатов (0 токенов)

```
[ {"cand_id": "c0012", "screen_id": "s031", "kind": "typo", "on_screen_text": "ВЫСОКВАЯ", "line_idx": 2,
   "fix_local": "ВЫСОКАЯ", "signals": ["ocr=vlm=zoom", "vo_match:0.91"], "route": "auto_confirm|cloud|drop",
   "route_reason": "три чтения совпали, исправление из озвучки", "need_frame": false} ]
```
Правила выбираются по языку: RU — прежние (typo/grammar/language «английский без перевода»/currency по канону YTUVI) +
общие fact/mismatch/foreign_trace; EN (`lang en`) — `rule_typo_en` (pyspellchecker в `.venv_llm`, фолбэк
`/usr/share/dict/web2`; исправление из озвучки или словаря), `rule_language_en` (кириллица/арабское письмо в графике
канала; латинское слово с кириллическими двойниками = артефакт OCR), `rule_currency_en` (`profile.currency`) + те же общие.
`route_reason` у auto_confirm уходит в находку как `problem` — у EN он английский. Классы drop (`drop_class`):
`known_exclusion` (card exclusions) · `real_world_text` (вывеска/документ реального мира по vlm_desc) · `ocr_homoglyph` ·
`own_logo` (+ прежние). EN-сигналы: `fixes:N`, `figure_vs_vo`, `currency_vs_vo`, `mixed_currency`, `script:cyrillic|arabic`,
`vlm=cyr`, `llm:foreign_script`, `homoglyph_mix:…`. Находка auto_confirm у EN хранит сигналы в `signals`, а не в `why`
(«📚 SOURCE» монтажёра их не показывает); у RU `why` = сигналы, как было.
`work/{cut}/llm_v6.json` (s4): у EN `english_only` всегда пуст, чужой алфавит графики — `foreign_script: [str]`.
`prep_check_vlm.json` (s5): доля алфавита VLM — ключ `cyrillic` (ru) / `latin` (en), порог 40 %.

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
                "local_flags": {"typo_susp": [...], "latin_ratio": 0.1, "foreign_ratio"?: 0.0, "numbers_screen": [...],
                                "numbers_vo": [...], "probe_foreign": false, "dup_of": null,
                                "llm"?: {currency, english | foreign_script (en), facts, mismatch}},
                "candidates": [ {"cand_id", "kind", "text", "line_idx", "fix_local", "route_reason", "signals"} ] } ] }
```
EN-пакет: `foreign_ratio` (доля нелатинского письма), `llm.foreign_script`, `summary.excluded: [{id, tc, reason}]`
(экраны в card exclusions не пакуются), `hires_note` по-английски. Args воркфлоу: `lang` (`P.LANG`; только `"en"` включает
английские промпты/схемы, любое другое значение — русский текст байт-в-байт) и `exclusions` (`P.EXCLUSIONS`, только если
непусто — агентам «не выносить», скептику код T). Судья видит у EN метки `FIX-NN`; collect/derive_findings нормализуют их
обратно в ключи `ТЗ-NN` (данные не меняются).
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
`part.base_segments?` — только при `card.disabled_ranges`: V1 кусками `{seg_id: on_NN|off_NN, source_in_sec, source_out_sec,
timeline_in_sec, timeline_out_sec, disabled?: true}` встык на всю длину ката; partsBuilder ≥ 1.13.0 ставит выключенным кускам
V1/A1 `createSetDisabledAction` (кусок тёмный, но на месте — tc остальных экранов не сдвигаются). Без ключа — цельный V1, как раньше.
`part.fps` = `P.FPS_EXACT` (29.97 → 30000/1001); все `timeline_in/out_sec` и маркеры глав лежат на этой сетке (допуск
0.02 кадра), стиллы ≤ floor(4.8·fps) кадров. Язык маркеров/шапки/summary — i18n (§10), номер ТЗ на поверхности — `tz_label`.

## 10. Язык поверхностей (i18n) и регрессия

`shared/i18n.py`: `LANG` = карточка `lang` → профиль `lang` → `ru` (окружение `YTAI_LANG` перебивает; всё, кроме `en`, = `ru`).
`T(key, **kw)` — строка на LANG (`str.format(**kw)` при kw); неизвестный ключ или ключ без `en` при LANG=en → `KeyError`
(никакой тихой подстановки русского). `TL(lang, key)` — явный язык; `tz_label(num)` → `ТЗ-07` / `FIX-07` (ключи данных
`ТЗ-NN` во всех JSON не меняются). Стадии: `from _bootstrap import P, W6, M, HERE, ROOT, T, LANG, tz_label`; shared/cloud:
`import i18n` (STAGE/shared в sys.path). Облачные JS получают `args.lang`.
Таблицы — `shared/i18n_strings/<owner>.py`, `STRINGS = {'<owner>.key': {'ru': …, 'en': …}}`; owner = имя файла до первого
`_`; ключ обязан начинаться с `<owner>.`; дубль ключа между файлами → `ImportError`. RU-значения — байт-в-байт прежние
литералы. Общие ключи `core.*`: метки блоков `core.lbl_now|do|list|where|source|timeline|comment`, классы
`core.kind_up.<kind>` / `core.kind_low.<kind>`, диф опечатки `core.was_pre|was_mid|was_post`, `core.chapter`,
`core.draft_badge`, `core.tz_prefix`. Операторские логи и продюсерские поверхности Романа (phone_brief, producer_page,
селфчек, stdout стадий) остаются русскими.

Регрессия (0 токенов):
- `python3 shared/golden.py compare [--only STEP]` — RU-цепочка на песочной копии YTUVI02 (`~/YTAI_work/_golden/`, входы
  заморожены в `_golden_in/`, эталон `examples/ytuvi02_golden/golden.json`) — любой байт расхождения = FAIL. Реальный
  YTUVI02 только читается (find -newer до/после). `snapshot` пересъёмка, `rehash` после правки нормализации.
- `python3 examples/ytcr_en_fixture/run_fixture.py` — EN-цепочка на синтетике YTCR (20 экранов, 29.97, исключение) во
  временной копии: s2-пересборка → route → pack → канон ответа облака (`cloud_canned.json`) → collect → apply → terms →
  format_tz → графика (HTML) → review_json → mockbuild → дампы вкладок/листа; проверки: нет language auto_confirm на
  английских титрах, INFRASTRUCTURE, кириллическая С → language (drop ocr_homoglyph), кириллический титр → auto_confirm,
  исключение → drop и без ТЗ, сетка 29.97, mock error 0, нет кириллицы в поверхностях монтажёра вне текста с экрана.
  Входы пересобирает `build_fixture.py`.
- `review.py selftest` гоняет обе + полноту таблиц i18n (у каждого ключа с `ru` есть `en`).

## 11. Стадия `chapters` → `work/{cut}/chapters_proposal.json`

`shared/chapters_from_plan.py --apply` (после `align`, только при `card.chapters_plan`): `{schema: "chapters-proposal-v1",
status: ok | inversion, chapters[{n, name, sec, frame, tc, method, …}], missing, warnings, inversions, card_patch{chapters,
ch_name}}`; `ok` → бэкап `review_card.json.bak-chapters-<ts>` и замена `chapters`/`ch_name` в карточке; `inversion` (exit 2) →
карточка не трогается, решает Роман. После применения `review.py` перепомечает `chapter` у `screens_v6.json` и
`audit_findings.json` по новым границам (без OCR). Если главы меняются после прохода дальше — `run --only chapters`, затем
`run --from terms`.

## 12. Обратная связь по кату (`feedback-v1`) — указатель

Полный контракт — **`docs/feedback_v1.md`** (модель `work/{cut}/feedback.json`, статусы и разделы, лимиты текста, облачный
сверщик, протокол кадров). Здесь — только то, что касается карточки, стейта и цепочки.

Ключи карточки (все необязательные; без `prev_pravki` три стадии пропускаются, а страница продюсера их не показывает):

| ключ | значение | по умолчанию |
|---|---|---|
| `prev_pravki` | ТЗ прошлой версии, путь от `05_Review` или абсолютный; env `YTAI_PREV_PRAVKI`. `memex push` кладёт файл в `aux/` | нет → сверка пропущена; ключ есть, а файла нет → стадия `feedback` = ⚠️ с путём |
| `prev_cut_version` | `"v4"` | из `align_against` по `_v(\d+)\.words` |
| `images_mode` | `none` \| `public_folder` \| `temp_grant`; читается ТОЛЬКО из карточки (`proj_config.card_only`, окружением не подменить) | `public_folder` при непустом `shots_remote`, иначе `none` |
| `private_frames_folder_id` | папка Drive для кадров вкладки, БЕЗ доступа по ссылке (ни прямого, ни унаследованного) | нет → `temp_grant` отказывает |
| `feedback_tab` | имя вкладки | «Обратная связь · {ver}» |
| `feedback_sensitive_extra` | номера пунктов прошлого ТЗ, которые считать чувствительными, хотя флага у них нет: `[86, 97]` (в облако не уходят); env `YTAI_FEEDBACK_SENSITIVE_EXTRA=86,97` | `[]` |

Стадии (в конце `STAGES_CUT`, после `producer_page`, все SOFT, хост mac): `feedback` (модель → один облачный агент →
вливание; модель пересобирается ВСЕГДА перед вливанием; устаревший ответ не удаляется, а переименовывается в
`cloud/out/feedback_check.stale-<sha>.json`; в автономном режиме — один облачный раунд) → `feedback_page` (HTML, без отправки;
в Telegram — только `shared/feedback_page.py --send` после «ок») → `doc_feedback` (вкладка + проверка `ALL PASS`; кадры — только
`run --images temp` с Мака; перед записью — отказ, если на Memex жив прогон этого же проекта или проверить это не удалось,
отключается `YTAI_SKIP_MEMEX_CHECK=1`; `edits_guard` не вызывается — вкладка целиком пересобирается кодом).
Дочерним процессам `review.py` передаёт `YTAI_HOST` (`mac`|`memex`) и `YTAI_AUTONOMOUS=1`.

`review_state.json → surfaces`: `feedback {at, cloud: applied|skipped}` · `feedback_html` = файл `{CODE}_{cut}_feedback.html`
(гейт стадии — наличие файла) · `doc_feedback {at, rc, doc, images, verify: ALL PASS|FAIL}`.
`review.py status` показывает ⚠️, пока в `work/{cut}/feedback_grants.json` есть незакрытые временные доступы к кадрам.
Регрессия: `examples/feedback_fixture/` (в `review.py selftest`, офлайн, данные — литералы в `build_fixture.py`).
