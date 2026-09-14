# YTCH12 v4 — тулинг ревью монтажа (10.09.2026), восстановлен из лога сессии

Оригинал лежал в `/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/v4_review/` (SSD не смонтирован).
Файлы восстановлены `shared/recover_from_session_log.py` из сессии `4de45847` (Write + успешные Edit по timestamp);
`u_frames.py` и `notes_sync.py` — копии из YTCH11 `v2_review/` (сессии `dbd19194` + `7c6f6f58`, база — scratchpad
сессии `d364a110`, YTCH12 v2) с правками v4 поверх. Провенанс каждого файла — `RECOVERED.md`; там же список
Bash-команд (`sed -i`, `cp`), которые лог не воспроизводит — эти места вычитывать глазами.
Сестринская папка `../ytch11_v2/` — YTCH11 v2 (`a2_align`, `b_risk_v2`, `c4_content_v2`, `e2_tobe_content`, `f2_structure_html`…).

Это **пример**, не рабочий код стадии: пути в скриптах зашиты под YTCH12 (T7-Beige / T9-Black), константы фильма — в коде.
Рабочие инструменты стадии `0509_review_cycle` берут всё из карточки `review_card.json` и профиля канала.

## Что делал каждый скрипт → чем заменён в стадии

| скрипт v4 | что делал | замена в `0509_review_cycle` |
|---|---|---|
| `run_local_v4.sh` | локальный разбор одной командой: ждёт загрузку рендера, кадры 1 fps, OCR, техконтроль ffmpeg, wordrole, VLM-свип | `review.py run` (стадии s1–s5 на Memex/Mac, состояние в `review_state.json`) |
| `make_light_4k.sh` | лайт-копия 4K кадр-в-кадр (HEVC 8 Мбит/с) для UXP-таймлайна | канон прокси `reference_editing_proxy_pipeline` (вне стадии) |
| `qc_parse.py` | `qc_ffmpeg.log` → `qc.json` (чёрное, фризы, тишина, склейки, громкость) | s1/s5 техконтроль (`work/{cut}/`) |
| `a4_align_v4.py` | n-gram сверка v4 ↔ v3 ↔ v2 ↔ исходники: `map_*.json`, `diff_*.json`, `nosrc_v4.json` | **`shared/align.py`** — `--against <words.json|assembly.json>…` → `work/{cut}/align.json` (cut_map, new, unused, moved, coverage) |
| `b_risk_v4.py` | стоп-реестр по словам транскрипта (18 паттернов в коде) → `risk_hits.json` | **`shared/risk_registry.py`** — паттерны в `YTs/YTCH/review_profile.json → sensitivity.patterns` (25 шт., из v1/v2/v4 и YTCH11), `--apply` ставит `sensitive` в ТЗ |
| `c_chapters_v4.py` | канонический список зрительских глав из `structure_v4.json` → `viewer_chapters.json`, `chapters_cards.json` | карточка фильма (`chapters`, `ch_name`, `sub`) + вердикт (`structure_proposal`) |
| `p_packs.py` | пакеты актов для агентов-ревьюеров (транскрипт + OCR + VLM + техконтроль + адреса исходников + риски) → `packs/actNN.md` | **`shared/acts_compact.py`** — сжатие актов локальной Qwen3-8B (`acts_compact.json`) + `structure_checks.json`; в облако уходят сводки и ПУТЬ к транскрипту, а не мегабайты |
| `x_wf_extract.py` | task-output воркфлоу → `wf_result.json`, `structure_raw.json` + компактная сводка (после падения по лимиту сессии) | `cloud/salvage.py` (`review.py cloud salvage --latest`) |
| `x_synth_local.py` | локальное сведение вердикта: `synth_manual.json` (вердикт + 15 обязательных правок) + группировка находок, заголовки Qwen3-8B | **`cloud/wf_verdict_doc.js`** (один агент `verdict`) + `shared/verdict_call.py` (`--print-call` / `--apply`) |
| `x_structure_local.py` | локальный выбор структуры P1/P2 и проверка якорей карточек по словам и склейкам | `structure_checks` в `acts_compact.py` (правила листа) + `structure_proposal` вердикта; to-be — агент `tobe` (`--want-tobe`) |
| `synth_manual.json` | ручной вердикт YTCH12 v4: заголовок, сильные стороны, 15 обязательных правок с id находок | пример выхода `verdict.json` (та же логика полей: verdict / must / time_math / fund_checklist) |
| `p_pravki_v4.py` | единый JSON правок `pravki_v4.json` (ТЗ-01 = структура, must/should, чек-лист фонда, графика), формат v7 | `stages/s8_apply_audit.py` (находки аудита) + **`shared/verdict_call.py --apply`** (ТЗ `class: structure`, `source: verdict`) + `s10_format_tz.py` (рендер `nado`) |
| `r_rows_v4.py` | строки вкладки «Ревью по видео» (навигатор: главы + куски + партиция слов) | `stages/doc_tab_review_v1.py` |
| `doc_tab_tz_v4.py` (+`_verify`) | вкладка «ТЗ монтажёру · v4» в доке (одна таблица, блоки ❌/✅/📋/📍/📚/🎬, превью) + verify ALL PASS | `stages/doc_tab_tz_v4.py` + `doc_tab_tz_v4_verify.py` (та же линия, на карточке) |
| `d4_review_build.py` (+`d4_verify`) | вкладка-навигатор в доке через tabId; verify партиции слов | `stages/doc_tab_review_v1.py` + verify |
| `mk_cards_v4.py` | мокапы карточек глав / титула / подписи / карты структуры (чёрный кадр, белый узкий капс) | `stages/make_infographics_v6.py` со стилем канала из профиля (`style.mockup_style = ytch_black_caps`) |
| `mk_tz_lt_v4.py` | плашки ТЗ для слоя V4 ревью-таймлайна | `stages/make_infographics_v6.py` (плашки ТЗ, стиль из профиля) |
| `make_review_v4.py` / `make_review_v4_full.py` | 6-слойный ревью-таймлайн (`review_overlay`) / смотровой таймлайн целиком | `stages/make_review_v6.py` (канон 6 слоёв, contracts.md §9) |
| `h_summary_v4.py` | локальная HTML-сводка для продюсера (кадры base64, вердикт, must, таблицы) | producer page: `stages/review_page.py` (→ `shared/producer_page.py`), данные — `work/{cut}/producer_summary.json` из `verdict_call.py --apply` |
| `u_media_v4.py` / `u_frames.py` | кадры и мокапы → приватная папка Drive → манифест thumbnailLink (живёт ~1 ч, `--refresh`) | `stages/s9_materials_drive.py` / `s12_doc_previews.py` |
| `t_vlm_ru.py` | перевод VLM-описаний кадров на русский локальной Qwen3-8B (батчи по 15, резюмируемо) | `stages/s3_vlm.py` (RU-подписи в свипе) |
| `notes_sync.py` | мост «Review notes»: панель UXP → лист → подбор (push / pull / answer / fmt) | notes-цикл стадии (`notes_cycle` в профиле) |
| `finalize_v4.sh` | финальная сборка поверхностей одной командой (chapters → mockups → pravki → rows → док → таймлайн → HTML) | `review.py run --from apply` |
| `speakers.json` | имена спикеров wordrole (`Speaker 1` → Света, `Speaker 2` → Гуля) | карточка фильма, ключ `speakers` (+ `fund_speaker` для проверки «фонд малыми кусками») |

## Порядок, который воспроизводит линию YTCH12 v4 в стадии

```
YTAI_CARD=…/05_Review/review_card.json
python3 shared/align.py --against …/YTCH12_v3.words.json …/YTCH12_v2.words.json …/00_Setup/YTCH12_Claude4_assembly.json
python3 shared/risk_registry.py            # ⚠️ чек-лист фонда → work/v4/risk.json (--apply после появления ТЗ)
~/YTAI/environment/.venv_llm/bin/python shared/acts_compact.py     # акты Qwen3-8B + structure_checks.json
python3 shared/verdict_call.py --print-call [--want-tobe]           # → вызов Workflow(cloud/wf_verdict_doc.js)
python3 shared/verdict_call.py --apply                              # verdict.json → ТЗ + producer_summary.json
python3 shared/risk_registry.py --apply                             # sensitive: {flag, reason} на ТЗ по таймкодам
```
