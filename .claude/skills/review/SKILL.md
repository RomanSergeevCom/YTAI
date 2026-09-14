---
name: review
description: >-
  Ревью ката монтажёра и ТЗ на монтаж (стадия scripts/05_editing/0509_review_cycle/, KB 4.7).
  Use when Roman wants to review an editor's cut, build the editor's ТЗ (техзадание), audit on-screen
  titles, run the 6-layer review timeline, regenerate doc tabs/sheet after his edits, send the phone brief,
  or build a montage list from raw sources (montage_tz, no cut). Triggers (RU+EN): «ревью ката», «ревью
  сборки», «ТЗ монтажёру», «аудит экранов», «правки Романа в доке», «монтажный лист из исходников»,
  «review cut», «review timeline», упоминания 05_Review, review_card.json, review.py, код проекта + «ревью».
  НЕ для Assembly-брифа (0501_brief) и не для синхрона мультикама (wordsync).
---

# /review — ревью ката + ТЗ на монтаж

Интерфейс к стадии `scripts/05_editing/0509_review_cycle/` (`review.py`). Скрипты живут в репо,
всё состояние фильма — в `{project}/00_Setup/05_Review/`. Memex — «глаза» (кадры, OCR, транскрипт,
VLM, LLM, пробы — автономно), Mac — «руки» (маршрутизация, один облачный проход, все поверхности).
Экономия: облако — ≤10 агентов на фильм, без картинок по умолчанию; никакой сессия не пишет
ad-hoc скриптов и не читает кадры в тред.

## Шаг 0 — загрузить знания (ровно эти файлы, в этом порядке)

1. `scripts/05_editing/0509_review_cycle/README.md` — машинный ранбук, таблица стадий
2. `scripts/05_editing/0509_review_cycle/docs/contracts.md` — схемы карточки/профиля/стейта/pravki/облака
3. `{project}/00_Setup/05_Review/REVIEW_STATE.md` — тикет проекта (если есть; иначе `review.py init`)
4. `{project}/00_Setup/05_Review/review_card.json`
5. `YTs/{CH}/review_profile.json`

Не читать: `work/*/screens_v6.json`, `vlm_v6.jsonl`, `llm_v6.json`, `audit_findings*.json`, кадры `hires/`.
Для больших JSON — `shared/peek.py <file>`; для картинок — `shared/shot.py <img> --max 1280` (или `--bbox`).

## Шаг 1 — где проект и что уже сделано

```bash
R=~/YTAI/scripts/05_editing/0509_review_cycle/review.py
python3 $R status --project <путь к проекту | YTUVI02>
```
Нет карточки → `python3 $R init --project <path> --channel YTUVI --mode cut_review --cut gdrive:…/cut.mp4`
(или `--from-prep-config <старая prep_config.json>`), затем заполнить в карточке главы (`chapters`,
`ch_name`), `film`, `doc_id`/`materials_id`/`project_folder_id`, `ocr_anchors` (2–3 фразы, которые точно
есть в кате), `notes` (грабли). `python3 $R card check --project P`.

## Шаг 2 — намерение → команда

| Роман говорит | делаем |
|---|---|
| новый кат прислали | `init` → `memex push [--with-cut]` → `memex start` → сообщить: разбор идёт автономно, вехи придут в TG |
| «что там на Memex» | `memex status`; пауза/продолжить/стоп — `memex pause|resume|stop` |
| локальный разбор готов | `memex pull` → `run --project P --until route` |
| облако | `cloud judge --print-call` → выполнить напечатанный `Workflow({...})` ОДИН раз → **сразу** `cloud collect --run <runId>` → `resume` |
| воркфлоу упал по лимиту | `cloud salvage --latest` (или `--session <id>`) → `cloud collect` → повтор ТОЛЬКО pending: `cloud judge --print-call` |
| Роман правил док (удалял строки, дописывал) | `edits` — ДО любой регенерации вкладок (иначе гейт остановит `doc_tz`) |
| «пересобери док/лист/таймлайн» | `run --from format_tz` (или `--from render`, `--from doc_tz`) |
| «пришли на телефон» | `run --only phone_brief` (файл ≤1 МБ уходит в TG) |
| ТЗ из исходников (YTEVO, ката нет) | `init --mode montage_tz` → `run` (segment → montage → структура одним агентом → мокапы → standalone) |
| «сколько стоил» | `cloud cost --session <id>` |

Все команды: `python3 $R <cmd> --project P`. Прогон длинных стадий на маке — фоном
(`nohup caffeinate -dims … &`, лог `05_Review/logs/`), на Memex — `memex start`.

## Шаг 3 — протокол облака (единственные токены)

- Один Workflow на фильм: `cloud/wf_judge.js` — судья J по пакетам ≤50 экранов (текст, без картинок),
  факт-чек F (1 агент), кропы V (1 агент, ≤16 кропов), скептик S (1 агент, default real=true).
  Аргументы печатает `cloud judge --print-call` — не сочинять свои.
- Результаты агенты пишут на диск сами (`cloud/out/`); после возврата или обрыва — сразу `cloud collect`.
- Повтор только `--pending`; перед повтором `cloud salvage`. Непрошенных QA-стадий (страницы дока,
  превью, listify агентами) не добавлять — это делает код (`doc_qc`, `previews`, `polish`).
- YTCH: вердикт — `cloud verdict --print-call` (1 агент). YTEVO: структура — `cloud structure --print-call`.

## Шаг 4 — читать результат

`status` + хвост `05_Review/logs/<stage>.log` (не весь лог). Гейты: селфчек ALL OK · candidates.json ·
все пакеты done · mock 0 ошибок · verify ALL PASS · doc QA 0 high · бриф отправлен.
Секвенцию в Premiere строит Роман (UXP → Review → `{CODE}_review_v6.json`, кнопка Build — GUI).

## Гигиена (нарушение = утечка токенов)

- Скриншоты и кадры — только через `shared/shot.py` (≤1280 px / кроп по bbox), JSON > 50 КБ — только `shared/peek.py`.
- Скрипты не править «под проект» и не писать разовые: баг → правка в репо + README + `memex push`; разовое — в scratchpad.
- Тикет руками не писать — `review.py ticket`; сессию заканчивать `status` + `ticket`.
- Grep/Glob вместо `cat`; выводы ≤2 КБ.

## Границы

Деплой KB, права на Drive, форс-удаления — Winston. UXP-панель не коммитить. Формат поверхностей
(6 слоёв, ОДНА таблица во вкладке, блоки ❌/✅/📋/📍/📚/🎬/💬) — канон KB 4.6, не переизобретать.
