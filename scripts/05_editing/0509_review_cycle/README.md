# 0509_review_cycle — ревью ката + ТЗ на монтаж (машинный ранбук)

Стадия главы «Editing» (KB 5.7 `/kb/review-cycle/`, канон форматов — KB 5.6 `/kb/review-timeline/`).
Скрипты живут здесь, в репо; всё состояние фильма — в `{project}/00_Setup/05_Review/`.
Никаких рабочих копий инструмента рядом с данными (так расходились три версии YTUVI01/02/Memex).

## Один вызов

```bash
R=~/YTAI/scripts/05_editing/0509_review_cycle/review.py
python3 $R init    --project <path|CODE> --channel YTUVI --mode cut_review [--cut gdrive:…/cut.mp4] [--from-prep-config old.json]
python3 $R status  --project P
python3 $R memex   --project P push [--with-cut] | start | status | pause | resume | stop | pull
python3 $R run     --project P [--from S] [--until S] [--only S] [--force] [--dry-run] [--host mac|memex] [--tg] [--no-drive] [--no-doc]
python3 $R resume  --project P
python3 $R cloud   --project P judge --print-call | collect --run <id> | salvage [--session <id>] | cost | verdict | structure
python3 $R edits   --project P        # правки Романа из дока → pravki; ОБЯЗАТЕЛЬНО перед регенерацией вкладок
python3 $R ticket  --project P        # REVIEW_STATE.md
python3 $R card    --project P check
python3 $R docs                        # таблица стадий → README + KB 5.7 (между маркерами)
```

Стадии идемпотентны, гейт — по артефактам на диске (`review_state.json` можно потерять — ничего не
переделается). `--force` гоняет заново, `--from S` сбрасывает S и всё после. Пауза/стоп — флаги
`~/.cache/<project>/PAUSE|STOP` (стадии читают их на границе экрана). Логи — `05_Review/logs/<stage>.log`.

## Что где

```
{project}/00_Setup/05_Review/
├── review_card.json      карточка фильма (пути, главы, film, внешние id, якоря, notes)   ← docs/contracts.md §1
├── review_state.json     стейт-машина                                                     ← §4
├── REVIEW_STATE.md       тикет для новой сессии (генерится)
├── review_terms.json     термины/места фильма (сверх YTs/{CH}/review_terms_base.json)      ← §3
├── {CODE}_v1.words.json  транскрипт (wordrole, --plain)
├── {CODE}_review_v6.json таймлайн ревью для UXP (ytai-part-v1, review_overlay, 6 слоёв)   ← §9
├── pravki/               pravki_v2.json (источник истины всех поверхностей) · tz_overrides · previews_v7 · shots_ids · drive_clips · notes_sheet · channel_rules
├── work/v1/              hires/ · ocr_hires.jsonl · screens_v6.json · vlm_v6.jsonl · llm_v6.json · probes.jsonl · candidates.json · audit_findings.json · audit_v6.json · terms_v6.json · lint_v7.json · previews_* · err_frames* · polish/
├── cloud/                state.json · in/ · out/ · raw/<runId>/ · CALL.txt
├── mockups/ · notes/ · logs/
YTs/{CH}/review_profile.json   профиль канала (стиль, каноны, классы ТЗ, чувствительность)       ← §2
```

Папка стадии: `review.py` · `proj_config.py` (карточка+профиль, `YTAI_CARD`/`YTAI_PROJECT_DIR`/поиск вверх) ·
`stages/` (s2…s14, make_*, doc_tab_*, tz_sheet, s9, route_candidates, s3b_probe_vlm, doc_pdf_qc,
preview_qc_local, kb_visuals — вне конвейера, см. «Визуал из базы»; `_bootstrap.py` — единая точка путей) · `cloud/` (pack, wf_judge, collect, salvage,
wf_verdict_doc, wf_structure_src; `_legacy/` — старые 250-агентные воркфлоу, не запускать) · `montage/`
(режим montage_tz) · `shared/` (card_tools, align, risk_registry, acts_compact, phone_brief, producer_page,
notes_sync, recover_from_session_log, shot, peek, i18n + i18n_strings/, golden, fake_docs, chapters_from_plan) ·
`memex/` (push/pull/start/status/pause/resume/stop/watchdog) · `geo/` · `templates/` · `examples/` (YTUVI01 данные, YTCH12 v4,
YTEVO02 — только как справка; `ytuvi02_golden/` — эталон RU-регрессии; `ytcr_en_fixture/` — EN-фикстура selftest) ·
`docs/contracts.md`.

<!-- stages:begin -->
### Стадии cut_review (генерится `review.py docs`)
| # | стадия | хост | инструмент | гейт |
|---|---|---|---|---|
| 1 | download | memex | rclone из cut_drive напрямую | кат на диске |
| 2 | frames | memex | ffmpeg 1 fps 1080p | кадров ≥ длительность − допуск |
| 3 | ocr | memex | s2_ocr_hires (Apple Vision, bbox) | селфчек ocr + якоря |
| 4 | transcript | memex | wordrole_transcribe --plain (.venv_transcribe) | words.json |
| 5 | vlm | memex | s3_vlm Qwen2.5-VL-7B | селфчек vlm |
| 6 | llm | memex | s4_llm Qwen3-8B (признаки, не вердикты) | селфчек llm |
| 7 | probe | memex | s3b_probe_vlm: чужие следы, обрезка, zoom-перечит | probes на всех экранах |
| 8 | selfcheck | memex | s5_selfcheck all | ALL OK |
| 9 | route | mac | route_candidates: auto / cloud / drop | candidates.json |
| 10 | cloud | mac | pack → Workflow wf_judge (J≤4, F, V, S) → collect | все пакеты done, покрытие 100 % |
| 11 | apply | mac | s8_apply_audit: классовый фильтр, одна ТЗ на экран | audit_v6.json + pravki |
| 12 | align | mac | align: n-gram кат ↔ план/прошлые версии (card.align_against) | align.json |
| 13 | chapters | mac | chapters_from_plan --apply: главы ката по плану частей (card.chapters_plan) через align; chapter экранов перепомечается | chapters_proposal.json (инверсия → карточка не тронута) |
| 14 | risk | mac | risk_registry (YTCH): ⚠️ на подтверждение фонда, не ⛔ | risk.json |
| 15 | acts | mac | acts_compact Qwen3-8B по актам + проверки структуры (YTCH) | acts_compact.json |
| 16 | verdict | mac | 1 облачный агент: вердикт, обязательные правки, структура (YTCH) | verdict.json применён |
| 17 | terms | mac | terms_index | terms_v6.json |
| 18 | format_tz | mac | s10_format_tz + lint | lint_v7.json |
| 19 | polish | mac | s14_polish_local Qwen3-8B по одной строке + guard | длинных строк 0 |
| 20 | sources | mac | s11_apply_sources | — |
| 21 | render | mac | make_infographics_v6 (chrome-headless 4K PNG) | PNG в mockups |
| 22 | review_json | mac | make_review_v6 (ytai-part-v1, 6 слоёв) | {CODE}_review_v6.json |
| 23 | mock | mac | mockbuild_v6.js через partsBuilder | 0 ошибок |
| 24 | previews | mac | s7 + s12 --render + preview_qc_local | qc 0 high |
| 25 | drive | mac | s9_materials_drive + s12 --upload/--apply + ensure_shots | файлы с комментами, все картинки pravki в shots_ids |
| 26 | sheet | mac | tz_sheet | лист обновлён |
| 27 | doc_tz | mac | ensure_shots → doc_tab_tz_v4, 6 колонок с «Говорит» (гейт: review.py edits) | вкладка записана |
| 28 | doc_nav | mac | doc_tab_review_v1 (навигатор) | вкладка записана |
| 29 | verify | mac | doc_tab_tz_v4_verify | ALL PASS |
| 30 | doc_qc | mac | doc_pdf_qc (pdftotext/pdfimages/PIL) | 0 high |
| 31 | phone_brief | mac | phone_brief → Telegram | файл ≤1 МБ отправлен |
| 32 | producer_page | mac | producer_page / review_page | HTML |

### Стадии montage_tz
| # | стадия | хост | инструмент | гейт |
|---|---|---|---|---|
| 1 | transcript | memex | wordrole_transcribe --plain (.venv_transcribe) | words.json |
| 2 | segment | memex | segment_local Qwen3-8B: тезисы + якоря | segments.json |
| 3 | montage | mac | build_montage по пословным якорям | montage.json |
| 4 | structure | mac | 1 облачный агент: структура/тезисы/графика | montage_plan обновлён |
| 5 | mockups | mac | build_mockups + DOM-QC | PNG 4K |
| 6 | design_review | mac | 1 облачный агент по контактному листу мокапов | design_review.json применён |
| 7 | structure_html | mac | build_structure_html | HTML |
| 8 | standalone | mac | make_standalone (для телефона) | один HTML |
| 9 | phone_brief | mac | phone_brief → Telegram | файл ≤1 МБ отправлен |
<!-- stages:end -->

## Визуал из базы (`stages/kb_visuals.py`, вне конвейера)

Где в кате не хватает картинки: база знаний канала (профиль `kb`) + свои съёмки (`FOOTAGE_ROUTING.md`) → вставки V2 и ТЗ.
Не стадия `review.py` — шаги запускаются руками по порядку (`python3 stages/kb_visuals.py <шаг>`; карточка ищется как у
остальных стадий: `YTAI_CARD`, `YTAI_PROJECT_DIR` или запуск из папки проекта), всё локально, 0 токенов, выход в
`work/{cut}/kb_visuals/`; `verify` уважает PAUSE (`P.pause_gate`):

| шаг | что делает | выход |
|---|---|---|
| `needs` | транскрипт → биты 8–18 с → предметы по словарю: термины `YTs/{CH}/review_terms_base.json`, у которых есть запросы в `VIS_QUERIES`, + места (`places[].en`) + камни `VIS_EXTRA` → EN-запросы. В файл идут все биты: `need` 3/1/0 (сильный предмет / слабый / нет), в `card.disabled_ranges` — `need` 0, доля графики ката — `graphic_cover` | `needs.json` |
| `pick` | биты с `need` ≥ порога (`--min-need=N`, по умолчанию 3), `graphic_cover` < 0.6 и не disabled → FTS5 `_KB/index.sqlite` → фильтр `kb.exclude_sources`/`min_side` и отсев карт, графиков и страниц по `vlm_captions` → зрелищность `fig_scores`, дедуп phash, до `kb.per_beat` на бит; + до 4 своих клипов (кроме `working`) по регэкспу предмета в `FOOTAGE_ROUTING.md` или папке камня; + **книги**: половины страниц из `kb.books_manifest` по заголовку и краткому содержанию, приоритет `photo_plate` (`--no-books` выключает) | `candidates.json` (`cands` · `own` · `books`) |
| `targets` | адресный поиск по СВОИМ запросам (заметки Романа, замена картинок): `--in=targets_<name>.json` [{id, t0, t1, subject, queries, diagrams?, skip?}] → FTS базы тем же отбором, что `pick` (`--per=N`) | `candidates_<name>.json` |
| `verify` | Qwen2.5-VL-7B (`.venv_vlm/bin/python`, ~7–10 картинок/мин): тема, фото/страница, качество 1–5, подпись; `--in=candidates_<name>.json` | `verify.jsonl` |
| `sheets` | контактные листы по главам (колонки K журналы · B книги · O свои клипы, подпись = вердикт VLM) — отбор глазами через `shared/shot.py` → руками `picks.json` {inserts, groups, tz}; `--in=…` `--per=N` `--rows=N` | `sheet_[<name>_]chNN_pP.jpg` |
| `propose` | черновик вставок на пустые биты БЕЗ участия сессии: лучший проверенный кадр (`match` yes, `quality` ≥ `--min-q`, русская подпись), пауза между вставками `--gap` с, тексты ТЗ по шаблону; время вставки = первое слово предмета в бите (не начало бита) | `proposals.json` |
| `retime` | переставить отобранные вставки на слово: `--ids=…` [`--word=регэксп`] (окно — tc_range группы) | `picks.json` (+ бэкап) |
| `cards` | 4K-карточки `mockups/kbv_*.png` (на карточке кредит + ссылка на издание, бейдж «DRAFT · макет монтажёру») + jpg для дока с **плашкой источника по низу** (журнал/книга со ссылкой · свой клип со сценой и таймкодом · макет с перечнем исходников) + **сама страница издания** `doc/kbvsrc_*.jpg` | `mockups/`, `doc/kbv*.jpg` |
| `apply` | `card.v2` (перезаписывается целиком), ТЗ в `pravki_v2.json`: запись каждой группы встаёт на СВОЁ прежнее место (`kbv_group`; номер ТЗ = позиция), убранная группа (`removed`) — `status: rejected` с тем же номером, новые — в конец; у kb-вставки ДВА материала — макет и страница источника со ссылками на САМ файл в Drive (весь PDF `#page=N` + папка, `shared/drive_links.py`), блок 📚 = кредит + ссылка на файл; у макета (`src: mock`) — строка со ссылкой на каждый `sources[]`; у своих клипов — фрагмент (вход −2 с, 1280p) в Drive и ссылка на него + запись в `drive_clips.json` (`--no-clips` выключает); `rclone copy` kbv*.jpg / src_*.mp4 → `shots_remote` + `shots_ids.json` | — |

После `apply` — `run --from format_tz` (или `--from render`). Модель не решает «что показать»: Qwen3-8B на YTUVI02 в 63 из 97
битов выдумал «включения под микроскопом», поэтому предметы берутся по словарю. `apply` пишет в Drive (`shots_remote`) — на
тестовых ресурсах подменять `YTAI_SHOTS_REMOTE`.

## Облако — один проход на фильм

`cloud/pack.py` собирает текстовые пакеты J (≤50 экранов, ≤60 кандидатов; OCR + VLM + озвучка ±8 с +
локальные сигналы, картинок нет) → сессия выполняет напечатанный `Workflow({scriptPath: cloud/wf_judge.js, …})`
один раз → агенты пишут `cloud/out/<batch>.json` сами → `cloud/collect.py` сливает в `work/v1/audit_findings.json`
(покрытие 100 %, непокрытые экраны досылаются) → после J: `pack.py --facts --crops --skeptic` → тот же воркфлоу
(F: факт-чек списком, V: ≤16 кропов ≤800 px, S: скептик default real=true с кодами T|V|H|C|F|D) → `s8_apply_audit`.
Обрыв по лимиту сессии: `cloud/salvage.py` достаёт результаты из journal/agent-логов сессии; повтор — только pending.
Бюджет: 7–10 агентов и ≈0,7–1,5 M токенов на 40-минутный фильм (было 233–560 агентов, 25–37 M).

## Memex («глаза»)

`memex push` — rsync папки стадии + зависимостей (`ytuvi_doctabs/doctab_lib.py`, `infographic/render.py`,
`wordrole_transcribe.py`, `bin/vision_ocr_ru`) по путям репо и карточка в Memex-варианте в
`~/YTAI_work/{CODE}/00_Setup/05_Review/`; `VERSION` = git sha (дрейф виден в `status`). `memex start` —
`nohup caffeinate -dims review.py run --host memex --tg` + `watchdog.sh` (подъём ≤5 раз, выход по готовности).
`memex pull` — rsync `work/v1/` + транскрипт назад, сверка md5. Одна модель за раз (16 ГБ): стадии строго последовательны.
Нагрузка подписывается: на тяжёлых стадиях пишется флаг `~/.cache/ytai/LOAD.json` (мониторинг Memex читает его и помечает
тревоги температуры как «идёт разбор»), в TG уходят «🔥 начинаю разбор … ожидаемо N ч» и «🧊 закончен». Регрессия перед
любым commit/push — `review.py selftest` (секунда, 0 токенов). `--from S` / `--only S` гоняют стадии заново, `resume` — по артефактам.

### Автономный режим — вся цепочка на Memex (17.09.2026)

`memex start --autonomous` (= `review.py run --host memex --autonomous`): после «глаз» Memex сам идёт дальше —
route → облако → apply → align → chapters → acts → verdict → ТЗ → графика → таймлайн → mock → превью → бриф в TG →
страница продюсера. Ноутбук можно закрыть. Стадия, упёршаяся в `AwaitCloud`, сама выполняет напечатанный `Workflow({...})`
через `shared/headless_claude.py` (≤4 раундов на стадию: J → F/V/S → pending), затем повторяется и собирает `cloud/out/`.
- **Почему launchd:** через ssh/nohup `claude -p` пишет «Not logged in» — OAuth в связке ключей, а её видит только
  GUI-сессия. `headless_claude.run()` грузит задачу в `launchctl bootstrap gui/<uid>` и ждёт маркер кода выхода.
  Проверка входа: `python3 shared/headless_claude.py --ping` на Memex.
- Флаг `~/.cache/<project>/AUTONOMOUS`: сторож поднимает упавший прогон тоже с `--autonomous` и выходит, когда
  закрыта `producer_page`; снимается при успешном финише (🏁 в TG).
- `memex push` возит `0500_uxp/src` + `tests/mocks` (мок-сборка) и файлы карточки вне 05_Review (`align_against`,
  `chapters_plan`) в `aux/` с переписанными путями. Нет `node` на хосте — `mock` честно помечается «не выполнена».
- Внешние поверхности (Drive, лист, док) пишутся только при заполненных id в карточке — как и на маке.
- Забрать результат на мак: `memex pull --all` (pravki, cloud, mockups, `{CODE}_review_v6.json`, бриф; главы и длительность
  из карточки Memex вливаются в карточку мака).
- **Грабля кэша транскрипта (исправлено):** wordrole кэширует WAV/слова/диаризацию по имени `{CODE}_{cut}` — новая версия ката
  под тем же именем получала транскрипт старой за 1 с. `st_transcript` сверяет штамп источника (`_wordrole_work/{base}.src_stamp`,
  без штампа — mtime) и переносит чужой кэш в `_wordrole_work/_stale_*`.

## Правила

- Классы ТЗ: только `typo · grammar · fact · currency · language · mismatch · foreign_trace` (+`structure` у YTCH);
  `design/taste/pacing` не попадают в ТЗ по коду (профиль `tz_classes`). Целевой размер списка не задаётся.
- Язык поверхностей монтажёра — профиль канала `lang` (карточка `lang` перебивает): `en` (YTCR, монтажёр Aymen) → ТЗ,
  таймлайн, вкладки дока, лист, графика и промпты облака по-английски, `FIX-NN` вместо `ТЗ-NN`; всё прочее = `ru`
  байт-в-байт. Строки — `shared/i18n_strings/<owner>.py` (контракт §10). Логи и поверхности Романа — по-русски.
- Известные не-ошибки ката (дыра в футаже, недоделанные экраны) — `card.exclusions [{t0, t1, reason}]`, не ТЗ.
- Любая правка кода → `review.py selftest` (RU golden YTUVI02 байт-в-байт + EN-фикстура YTCR + полнота i18n) до commit/push.
- Номера ТЗ никогда не переиспользуются и не едут: номер = позиция в `pravki.all`, новые ТЗ — только в конец; `status: rejected` = Роман снял строку в доке (`review.py edits`) или `kb_visuals` убрал группу. Номерные фикстуры YTUVI01 (списки ТЗ-30/75/76, `ADD_MAT`, `_ATTACH_FILES`) работают только у проекта `ytuvi01` **и только на кате v1**, под номера которого они писались: на новом круге номера уезжают, и карточка прошлого круга приезжает к чужому ТЗ (22.09.2026: ТЗ-02 «UVi | ZUAETDI» получил карту Могока, ТЗ-25 «БИРМАНСКИЙ РУБИН» — три плашки про high jewelry).
- Внешние id (док, Drive, лист) — только из карточки; пусто = отказ, не фолбэк на прошлый фильм.
- Чувствительное (YTCH) = ⚠️ «на подтверждение фонда/блюр», не ⛔.
- Формат поверхностей заморожен (KB 5.6): 6 слоёв · ОДНА таблица во вкладке · блоки ❌/✅/📋/📍/📚/🎬/💬 · превью на кадре.
  Вкладка ТЗ — 6 колонок: `№ | ⏱ TC | | ТЗ монтажёру | Говорит | Материал` (Роман 16.09.2026: «транскрипт обязателен — без него не виден контекст»); «Говорит» — дословно из words.json (`shared/said.py`), опорная фраза жирным.
- Все картинки pravki — в `shots_ids` до записи вкладки: `stages/ensure_shots.py` (в стадиях `drive` и `doc_tz`) дозаливает найденные в mockups/ и kb_visuals/doc/, битая ссылка = отказ `doc_tz`.
- YTUVI: визуал — сначала `YTUVI-Digital_Originals` (открыта целиком), сканы книг `01_ScanBook-SSEF` — только если в базе пусто (`books_policy: fallback`, пометка ⚠️).

## Грабли

- alpha-рендер: `html,body{background:transparent}`; chrome-headless-shell (GUI-Chrome в headless виснет).
- Стиллы ≤4,8 с; tc на сетке `fps` карточки (25p; 29.97 = 30000/1001 точной дробью `P.FPS_EXACT` — десятичные 29.97
  за 30 минут уводят tc на ~2 кадра); `sequence_name` не кончать на `_v\d`.
- EN-роутер ищет опечатки словарём pyspellchecker (0.9.0, поставлен руками в `.venv_llm` на Mac и Memex, в requirements
  нет); без него — фолбэк `/usr/share/dict/web2`.
- Polish (s14 Qwen) у `lang en` пропускается; главы ката по плану частей — стадия `chapters` (card `chapters_plan` +
  `align_against`), инверсия порядка глав карточку не трогает.
- OCR путает Й/И — такие пары никогда не auto_confirm; стрелку ставить на секунду ДОПИСАННОГО титра.
- `get_doc` тянет весь док (~30 с) — шапку вкладки вставлять одной пачкой.
- Верх кадра занят титрами ката: подглавы/прогресс слева-посередине, термины/карты справа-посередине.
- Memex 16 ГБ: две модели одновременно не запускать; в неинтерактивном ssh `export PATH=/opt/homebrew/bin:$PATH`.
- Клипы магазина 23.976 → Interpret 25p (fps-warning в ТЗ).
