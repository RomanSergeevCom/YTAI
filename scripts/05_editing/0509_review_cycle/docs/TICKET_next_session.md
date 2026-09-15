# ТИКЕТ · практика и правки системы «Ревью ката + ТЗ на монтаж» — новая сессия

**Запуск в новом чате:** `/review` (скилл сам читает README, contracts, карточку и профиль) или просто
«ревью YTUVI02 …» / «измени в системе ревью …». Роман будет **практиковать** систему на реальных катах и
**просить менять** правила, форматы и стадии. Работать локально, act-then-report, статусы писать по ходу
любой операции длиннее минуты (см. «Правила сессии»).

## 0. Состояние на 15.09.2026

- Система собрана и проверена целиком на YTUVI02: коммит `ff03ac5` в `~/YTAI` (папка `scripts/05_editing/0509_review_cycle/`),
  KB 4.7/4.8 задеплоены, инфографика `docs/scheme_2026-09-14.html` (артефакт v5, копия в TG).
- Что было сделано и найдено — `docs/HANDOFF_2026-09-14.md` (там же список хвостов). Не переписывать, дополнять.
- YTUVI02 (T7-Blue-2): карточка `00_Setup/05_Review/review_card.json`, `pravki/pravki_v2.json` = 46 ТЗ (полированные тексты
  через `tz_overrides.json`), `work/v1/audit_findings.json` = 55 находок нового облака (41 подтверждена), `cloud/` все пакеты done.
  **Рабочий док «ТЗ монтажёру · v1» YTUVI02 не тронут.** Все внешние поверхности гонялись на тестовых ресурсах в Drive-папке
  проекта `_review_cycle_TEST_2026-09-14` (док `1R17Ez2U29s5UhMPcn9u4jOgFkIY48WnE0W7-2MWFaN4`, лист `1LQO9HYKcENULlBJFZC0W1xhe2U9FEQgOT11pR1xOzxA`,
  материалы `1HdfpZ1EATU19Tzn3r7GLQV4y3-52dISJ`) — можно удалить; `pravki/proj_material_ids.json` и `shots_ids.json` возвращены на
  настоящую папку (тестовые копии `*.TEST_2026-09-15.json`).
- Memex: код стадии залит (`memex push`, VERSION = sha), данные YTUVI02 в `~/YTAI_work/YTUVI02/`, флаг нагрузки и сторож работают.
- В `examples/ytevo02/*` и `shared/notes_sync.py` есть незакоммиченные правки **другой сессии (YTEVO02)** — не трогать, не откатывать.

## 1. Сценарии практики (что Роман скорее всего попросит)

| Роман говорит | команда | чего ждать |
|---|---|---|
| «пришёл кат YTXX00, разбери» | `review.py init --project <path|CODE> --channel <CH> --mode cut_review --cut gdrive:…` → заполнить карточку (chapters/ch_name, film, doc_id, materials_id, project_folder_id, sprint_folder_id, ocr_anchors, notes) → `card check` → `memex push [--with-cut]` → `memex start` | TG «🔥 начинаю…», через 2–3 ч «🏁»; статус `memex status` |
| «что там на Memex» / пауза | `memex status` · `memex pause` / `resume` / `stop` | таблица стадий, дрейф VERSION |
| «локальный разбор готов» | `memex pull` → `run --until route` | candidates.json, сводка auto/cloud/drop |
| «запускай облако» | `cloud judge --print-call` → выполнить `Workflow({...})` ОДИН раз → `cloud collect --run <id>` → `resume` (при pending — повтор `judge --print-call`, будут F/V/S) | ≈7 агентов, ≈1 M токенов на фильм; `cloud cost --session <id>` |
| «примени к доку» (первый раз для фильма) | `resume` доводит до `doc_tz/doc_nav/verify/doc_qc/phone_brief` | verify ALL PASS, бриф в TG |
| «я поправил док, пересобери» | `edits` → `run --from format_tz` (или `--from polish`, `--from render`, `--from doc_tz`) | без облака; гейт не пустит без `edits` |
| «пришли бриф на телефон» | `run --only phone_brief` | файл ≤1 МБ в TG |
| «YTEVO: лист из исходников» | `init --mode montage_tz` → `run` → `cloud structure --print-call` → Workflow → `resume` | montage.json, мокапы, standalone |
| «сколько стоило / что упало» | `cloud cost` · `cloud salvage --latest` | таблица прогонов; спасённые пакеты |
| «проверь систему» | `review.py selftest` | 1 с, ИТОГ OK |

Все команды: `python3 ~/YTAI/scripts/05_editing/0509_review_cycle/review.py <cmd> --project <path|CODE>`.
Длинные стадии на маке — фоном (`nohup caffeinate -dims … &`, лог `05_Review/logs/<stage>.log`), Memex — `memex start`.
⚠️ Один прогон на проект: пока идёт `run`, второй `run`/`stage start` откажет (`review.pid` в `~/.cache/<project>/`).

## 2. Хочу изменить … → правлю здесь (и только здесь)

| что | где | после правки |
|---|---|---|
| правила канала: валюта, язык титров, что ошибка, латиница-исключения, чувствительные темы, правила структуры | `YTs/{CH}/review_profile.json` (`rules_text`, `tz_classes`, `latin_whitelist`, `sensitivity`, `structure_rules`) | ничего не пересобирать; на следующий `route/pack` подхватится |
| термины, места, каноны названий, путаемые пары | `YTs/YTUVI/review_terms_base.json`; у фильма `review_terms.json` | `run --from terms` |
| главы, подглавы, перечисления, якоря, ссылки на док/Drive, грабли | `review_card.json` фильма | `card check`; `run --from render` при смене глав |
| как судит облако (промпты J/F/V/S, классы, «не ошибка») | `cloud/wf_judge.js` | `node --check`; `selftest` |
| пороги маршрутизации (auto/cloud/drop) | константы в шапке `stages/route_candidates.py`; `--eval` на YTUVI02 | цель: 0 ложных auto |
| порядок/набор стадий, хосты, гейты | `STAGES_CUT` / `STAGES_MONTAGE` + `STAGE_DESC` в `review.py` | `review.py docs` (таблица в README и KB) |
| вид вкладки ТЗ / навигатора / листа / таймлайна (канон 4.6) | `stages/doc_tab_tz_v3.py` (+`_verify`), `doc_tab_review_v1.py`, `tz_sheet.py`, `make_review_v6.py` | `run --from doc_tz` / `--from review_json` |
| графика: плашки, карты, стрелки, карточки глав, стиль | `stages/make_infographics_v6.py` + `style` в профиле | `run --from render` |
| бриф для телефона / страница продюсера / заметки | `shared/phone_brief.py`, `producer_page.py`, `notes_sync.py` | `run --only phone_brief` |
| QA дока / превью (критерии, пороги) | `stages/doc_pdf_qc.py`, `preview_qc_local.py` | `run --only doc_qc` |
| полировка текста ТЗ (модель, правила, страж) | `stages/s14_polish_local.py`, `polish_todo.py`, `merge_local_fixes.py`, `guard_v7b.py`, `listify_rules_v2.md` | `run --from polish` |
| Memex-раннер, сторож, флаг нагрузки | `memex/*.sh`, `LOAD_FLAG`/`HEAVY` в `review.py`, `999_extra/bin/ytai_load` | `memex push` |

Порядок любой правки кода: правка в репо → `review.py selftest` → commit → `memex push` (если трогали стадии Memex).
Скрипты **никогда** не правятся «под проект» внутри сессии и не копируются в проект; разовое — в scratchpad.

## 3. Правила сессии (Роман просил)

- **Статусы**: перед любой операцией длиннее минуты написать, что запускается и сколько ждать; во время ожидания — проверять и
  писать прогресс (уведомления фоновых задач могут не прийти — опрашивать самому); «молчание = завис» недопустимо.
- Гигиена токенов: кадры/скриншоты только `shared/shot.py` (≤1280 px; имена скриншотов macOS содержат узкий пробел — искать через `ls -t ~/Desktop/Screenshot*`),
  JSON > 50 КБ только `shared/peek.py`, читать 5 файлов входа, не больше.
- Облако: один Workflow на стадию, аргументы из `--print-call`, сразу `cloud collect`; повтор только pending; QA-стадий агентами не добавлять.
- Внешние записи (док, лист, Drive): в рабочий док только после явного «примени»; тест — на тестовых ресурсах через окружение
  `YTAI_DOC_ID / YTAI_MATERIALS_ID / YTAI_NOTES_SHEET_ID / YTAI_SHOTS_REMOTE / YTAI_NAV_TAB`.
- Memex: тяжёлое — только там, флаг нагрузки ставится сам; чужие тяжёлые прогоны заявлять `ytai_load start "…" <мин>`.
- Форматы для монтажёра (6 слоёв, ОДНА таблица, блоки ❌/✅/📋/📍/📚/🎬/💬) — канон KB 4.6; менять только по просьбе Романа.

## 4. Открытые хвосты (кандидаты на «измени»)

- `s8_apply_audit`: находка v8 на экране с существующей ТЗ при том же наборе классов не обновляет её текст (улучшенный fix_text судьи теряется).
- `s10_format_tz`, `review_page`, `doc_tab_review_v1` читают легаси `audit_findings_v6.json` (авто-конвертация `collect --emit-legacy`); перевести на v8.
- `doc_pdf_qc` после полировки: 17 high (9 «перечисление», 7 длинных строк из 2 ТЗ, заблокированных guard’ом, 1 подпись) — либо ослабить критерий « / » в цитатах, либо доразбить вручную.
- `preview_qc_local`: 2 high (fix_tz09/35 срезаны справа) — поправить кропы в `pravki/previews_v7.json` или в `s12`.
- Профиль YTCH: паттерны `debts`/`harassment`/`age_dates` шумят — калибровать на транскрипте YTCH12 v4 (T7-Beige).
- `review_page.py` (страница экранов) хардкодов больше нет, но стиль старый; при желании объединить с `producer_page`.
- KB: дубль гейт-блока no-flash в 9 страницах (включая 4.7/4.8) — одна строка в `scripts/site/patch_site_chrome.py` (Winston предлагал).
- Старые копии: `~/Downloads/YTUVI01_Sonya_cut/work/`, `~/YTUVI02_Review/work/*.py`, Memex `~/YTAI/scripts/999_extra/review_timeline_audit` — удалить руками после проверки; launchd `ae.rya.ytuvi01/ytch11/ytch12-notes-push` → bootout или перегенерить.
- Карточка YTUVI02: `ocr_anchors` пусты (селфчек OCR по якорям пропускается).

## 5. Где всё лежит

Код `~/YTAI/scripts/05_editing/0509_review_cycle/` (README · docs/contracts.md · docs/HANDOFF_2026-09-14.md · docs/scheme_2026-09-14.html · этот тикет) ·
скилл `~/YTAI/.claude/skills/review/SKILL.md` · раздел в `CLAUDE.md` · профили `YTs/{CH}/review_profile.json` · KB 4.7 https://yt.rya.ae/kb/review-cycle/ ,
4.8 https://yt.rya.ae/kb/montage-tz/ , 4.6 https://yt.rya.ae/kb/review-timeline/ · память `reference_review_cycle_system` (+ `reference_memex_mlx_stack` про нагрузку) ·
проект: `{project}/00_Setup/05_Review/REVIEW_STATE.md` (генерится `review.py ticket`) · чаты-источники: см. HANDOFF «Где лежит».
