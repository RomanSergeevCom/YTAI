# 0509_review_cycle — ревью ката + ТЗ на монтаж (машинный ранбук)

Стадия главы «Editing» (KB 4.7 `/kb/review-cycle/`, канон форматов — KB 4.6 `/kb/review-timeline/`).
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
python3 $R docs                        # таблица стадий → README + KB 4.7 (между маркерами)
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
preview_qc_local; `_bootstrap.py` — единая точка путей) · `cloud/` (pack, wf_judge, collect, salvage,
wf_verdict_doc, wf_structure_src; `_legacy/` — старые 250-агентные воркфлоу, не запускать) · `montage/`
(режим montage_tz) · `shared/` (card_tools, align, risk_registry, acts_compact, phone_brief, producer_page,
notes_sync, recover_from_session_log, shot, peek) · `memex/` (push/pull/start/status/pause/resume/stop/watchdog) ·
`geo/` · `templates/` · `examples/` (YTUVI01 данные, YTCH12 v4, YTEVO02 — только как справка) · `docs/contracts.md`.

<!-- stages:begin -->
(таблица стадий генерится `review.py docs`)
<!-- stages:end -->

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

## Правила

- Классы ТЗ: только `typo · grammar · fact · currency · language · mismatch · foreign_trace` (+`structure` у YTCH);
  `design/taste/pacing` не попадают в ТЗ по коду (профиль `tz_classes`). Целевой размер списка не задаётся.
- Номера ТЗ никогда не переиспользуются; `status: rejected` = Роман снял строку в доке (`review.py edits`).
- Внешние id (док, Drive, лист) — только из карточки; пусто = отказ, не фолбэк на прошлый фильм.
- Чувствительное (YTCH) = ⚠️ «на подтверждение фонда/блюр», не ⛔.
- Формат поверхностей заморожен (KB 4.6): 6 слоёв · ОДНА таблица во вкладке · блоки ❌/✅/📋/📍/📚/🎬/💬 · превью на кадре.

## Грабли

- alpha-рендер: `html,body{background:transparent}`; chrome-headless-shell (GUI-Chrome в headless виснет).
- Стиллы ≤4,8 с; tc на сетке 25p; `sequence_name` не кончать на `_v\d`.
- OCR путает Й/И — такие пары никогда не auto_confirm; стрелку ставить на секунду ДОПИСАННОГО титра.
- `get_doc` тянет весь док (~30 с) — шапку вкладки вставлять одной пачкой.
- Верх кадра занят титрами ката: подглавы/прогресс слева-посередине, термины/карты справа-посередине.
- Memex 16 ГБ: две модели одновременно не запускать; в неинтерактивном ssh `export PATH=/opt/homebrew/bin:$PATH`.
- Клипы магазина 23.976 → Interpret 25p (fps-warning в ТЗ).
