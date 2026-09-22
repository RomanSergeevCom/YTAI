# Shorts Tab — спецификация (design v0.1, 2026-08-18)

Вкладка **Shorts** в UXP-панели (0500_uxp): поиск интересных моментов → демонстрация
кандидатов → коррекция → выбор → сборка 9:16-секвенций → round-trip с Claude через JSON.

Пилот: `YTCR01_Arty_Dzis` (T9-Black), режим «готовое видео» на финальном рендере v16.

---

## 1. Архитектура: Claude = мозг, панель = руки, HTML = витрина

Никакого LLM внутри панели. Как в Assembly-цикле:

```
┌─ Claude Code (чат) ──────────────────────────────────────────┐
│ читает транскрипты (пословные) + vision-индекс               │
│ ищет моменты, скорит, режет по словам с «воздухом»           │
│ пишет: {CODE}_Shorts_v{N}_in.json + {CODE}_shorts_review_v{N}.html
└──────────────┬───────────────────────────────────────────────┘
               ▼ file (00_Setup/07_Shorts/)
┌─ UXP-панель, вкладка Shorts ────────────────────────────────┐
│ показывает кандидатов, ставит маркеры-превью,               │
│ строит 9:16 секвенции (тики, фрейм-в-фрейм),                │
│ читает обратно правки юзера (маркеры, статусы)              │
│ кнопка «Out → Claude»: пишет _out.json, путь в клипборд     │
└──────────────┬───────────────────────────────────────────────┘
               ▼ paste path в чат
        Claude читает _out.json → улучшает → _v{N+1}_in.json → панель Refresh
```

Это ровно паттерн Assembly `_in`/`_out` (0501_brief/INSTRUCTIONS.md), только своя папка,
своя схема и свой builder. Ни один конкурент такого round-trip не имеет (см. §10) —
у всех либо чёрный ящик, либо direct-manipulation без экспортируемого состояния.

## 2. Два режима и их входы

### Mode A — `finished` (готовое видео) — MVP-1
Вход: финальный рендер + пословный транскрипт **самого рендера**.
- YTCR01: `02_Exports/YTCR1_v16_Arty_Dzis.mp4` (31:13) + `00_Setup/05_Review/v16/YTCR01_v16_pass2.json`
  (979 сегментов, words[{word,start,end}], EN, на таймлайне рендера).
- Маппинг на камерные исходники НЕ нужен: режем сам рендер (качество уже запечено).
- Для будущих проектов: шаг пайплайна «transcribe final export» (mlx, минуты) — уже
  делаем ad-hoc для QC (v14/v16), закрепить как стандартный пре-шаг Shorts.
- Диаризации у финального транскрипта нет → если нужна, pyannote поверх
  (память diarize-fast) или пометки спикеров делает Claude по контексту.

### Mode B — `ingest` (после инжеста) — MVP-3
Вход: пословные транскрипты исходников + vision-каталог.
- `01_Media/Source/Transcription/{CODE}_*_transcript_assembly.json` (сегменты по клипам),
  `per_clip/<scene>/C####.words.json` (RU words, clip-local) и `C####_en.json` ({w,s,e}),
  мастер `{CODE}_transcript.json` (words_data + диаризация 6 спикеров).
- `00_Setup/06_Enrichment/full_source_index.json` — vision-каталог 1129 клипов
  (energy, emotion, live_score, best_tc, moments) — второй сигнал скоринга и B-roll.
- Кандидат может быть МНОГОБЛОЧНЫМ: hook из середины + тело из другого клипа
  (hook-first reorder — самая недообслуженная фича рынка, §10).
- ⚠️ Грабли данных: конкатенированные SRT (`{CODE}_transcript.srt`, `_wordlevel.srt`)
  имеют сброс таймкода на границах сцен — в finder НЕ подавать; только per-clip/scene JSON.

## 3. Этапы вкладки (UI)

Вкладка `Shorts` в tab-bar (index.html:407-414, `data-tab="shorts"`), контент по образцу
tab-parts: status-row → секции этапов. Вертикально компактно (память panel-ui).

```
[Shorts]  ● v3 loaded · 12 candidates (5 approved)
──────────────────────────────────────────────────
 1. SOURCE      mode: (auto) finished | ingest     [Refresh]
 2. CANDIDATES  список карточек (см. ниже)
 3. PREVIEW     [Build Preview Seq]  [Read Back Markers]
 4. BUILD       [Build Approved →9:16]  □ also 16:9
 5. EXCHANGE    [Out → Claude]  [Open Review HTML]
```

**Карточка кандидата** (строка списка, как selections-чекбоксы index.js:2695-2818):
```
□ S03  87  0:42  «я потерял $2M за один звонок…»   [→] [✓] [✗]
        Hook 92 · Flow 85 · Emo 88 — “payoff в конце, цитируемо”
```
- чекбокс = approve; `[→]` = jump playhead к кандидату в preview-секвенции;
  `[✓]/[✗]` = статус approved/rejected; счётчик длительности живой (после read-back).
- Скор с ИМЕНОВАННЫМИ факторами + одна строка «почему» — не голая цифра
  (рынок: голым цифрам не доверяют, ~40% кандидатов выбрасывают).

### Этап 1 — Source (авторезолв)
Проект уже выбран глобально (projectState index.js:452-745). Панель сканирует
`00_Setup/07_Shorts/` на свежайший `_in.json` (паттерн loadPart index.js:2505-2534,
newest by dateModified + file-picker fallback). Mode берётся из JSON.

### Этап 2 — Candidates (демонстрация)
Рендер списка из `candidates[]`. Правки статусов живут в `shortsState` панели
и попадают в `_out.json`. Ничего в проект Premiere ещё не пишется.

### Этап 3 — Preview (коррекция в таймлайне)
Кнопка **Build Preview Seq**:
- finished: секвенция `{CODE}_Shorts_Preview_v{N}` = рендер v16 на V1 + range-маркер
  (chapter) на каждого кандидата: имя `S03 [87] slug`, комментарий = hook.
  Один таймлайн — скраббинг всех кандидатов, границы правятся ПЕРЕТАСКИВАНИЕМ маркеров
  (паттерн Firecut: таймлайн = поверхность ревью, панель = синхронный индекс).
- ingest: «кандидатский рил» — все кандидаты подряд (absolute placement, 1 c
  чёрного между), маркер на каждом. Движок — buildPartSequence как есть.
- Маркеры: createAddMarkerAction + отдельными транзакциями type=chapter URI + цвет
  (sceneMarkers.js:53, HANDOFF_UXP.md:79-89; add игнорирует type — известные грабли).

Кнопка **Read Back Markers**: читает маркеры активной секвенции (exportMarkers-паттерн
index.js:3899-3951), матчит по имени `S{NN}`, обновляет tc кандидатов в state.
Снап прочитанного: in→floor, out→ceil по сетке кадров. Юзер двигает маркер == правит границу.

### Этап 4 — Build (сборка выбранных)
Для каждого approved-кандидата:
1. Секвенция `{CODE}_S{NN}_{slug}` (канон имён — scripts/07_shorts/README.md), 1080×1920
   принудительно через applyMediaSettings (src/shared/mediaSettings.js:39) после
   createSequenceFromMedia (seed = источник, trim-to-1-frame гигиена partsBuilder.js:255-261).
2. Блоки кладутся overwrite-ом на тиковой сетке, ПОСЛЕДОВАТЕЛЬНЫМИ транзакциями по
   возрастанию времени (никаких compound — реверс-порядок, память frame-floor):
   pre-trim источника createSetInOutPointsAction(inTick,outTick) → overwrite → clear in/out.
3. keep_audio=true у речевых блоков; audio на A1; B-roll (ingest-mode) на V2/A2+
   (гроб: aIdx=-1 маршрутизируется в A1 — форсить A2+, partsBuilder.js:395-397).
4. Цвет лейбла по роли блока (hook=Mango, body=Caribbean, broll=Lavender) — на
   ProjectItem ДО вставки (clipActions.js:37-77).
5. Маркеры-метаданные в секвенции: chapter-маркер на старте с комментом
   `score:87|hook:...|src:v16@12:34.120-13:16.480` — самодокументируемость.
6. Опция «also 16:9»: та же нарезка в 1920×1080 секвенцию `{CODE}_S{NN}_{slug}_h`
   (паттерн Premiere Copilot: dual output бесплатен при том же плане нарезки).
7. Bin: всё в бин `Shorts` (ensureBin partsBuilder.js:74-100 — проверка существования,
   иначе дубли). Пере-сборка той же S{NN} — cleanExistingSequence-версионирование.
8. **Verify-гейт**: после сборки — Debug Dump активной секвенции → сверка позиций
   с планом (2 мс толеранс), как канон 0113/verify_build_sync (память frame-floor).
   Результат в панель: `S03 built ✓ (drift 0ms)` и в `_out.json.build_report`.

### Этап 5 — Exchange (round-trip)
**Out → Claude**: пишет `{CODE}_Shorts_v{N}_out.json` (см. §5), путь в клипборд
(паттерн «Out → Claude» уже есть: index.js:11260-11264 → exportSequenceJson 9177-9240).
Roman вставляет путь в чат → Claude правит → пишет `_v{N+1}_in.json` + новый HTML
(changelog, CHANGED-бейджи, зачёркнутые rejected — как Assembly round-trip).
Панель: Refresh → подхватывает новую версию.

## 4. HTML-витрина (генерит Claude вместе с _in.json)

`00_Setup/07_Shorts/{CODE}_shorts_review_v{N}.html` — статик file:// (память html-static),
стиль карточек как review-страницы (shared.css/stage-card, портальная палитра, лайм скупо):
- встроенный `<video>` плеер (file:// на рендер v16; H.264 играет в браузере) —
  карточка кандидата = кнопка «play range» (currentTime=tc_in, pause на tc_out);
- на карточке: скор с факторами, «почему», hook-цитата, полный транскрипт кандидата,
  предполагаемое имя `{CODE}_S{NN}_{slug}`, вертикальная рамка-схема (какая часть кадра
  попадёт в 9:16 при заданном crop_center);
- ingest-режим: плеер на per-clip прокси/исходник (4K HEVC браузер может не потянуть —
  тогда ссылки на клип + tc, или прокси из 01_Source_Proxy);
- changelog-блок сверху со v2+.

Это «демонстрация возможных шортсов» без ожидания сборки в Premiere: смотреть можно
сразу после генерации, выбирать — чекбоксами в панели или ответом в чате.

## 5. Контракт данных

Папка: `00_Setup/07_Shorts/` (следующий номер после 06_Enrichment; канон нумерации
00_Setup — память setup-layout). Файлы: `{CODE}_Shorts_v{N}_in.json`,
`{CODE}_Shorts_v{N}_out.json`, `{CODE}_shorts_review_v{N}.html`, `srt/{CODE}_S{NN}.srt`.

### 5.1 `ytai-shorts-v1` — `_in.json` (Claude → панель)

```jsonc
{
  "schema": "ytai-shorts-v1",
  "direction": "in",
  "version": 3,
  "generated_at": "2026-08-18T14:00:00+04:00",
  "project": {
    "code": "YTCR01", "channel": "YTCR",
    "mode": "finished",                       // finished | ingest
    "fps": 25,
    "source": {                                // главный источник (finished)
      "file": "YTCR1_v16_Arty_Dzis.mp4",
      "path": "/Volumes/T9-Black-RYA/.../02_Exports/YTCR1_v16_Arty_Dzis.mp4",
      "duration_sec": 1873.44,
      "transcript_ref": "00_Setup/05_Review/v16/YTCR01_v16_pass2.json"
    }
  },
  "render_target": { "width": 1080, "height": 1920, "fps": 25,
                     "also_horizontal": false },
  "defaults": { "pad_head_max_ms": 250, "pad_tail_max_ms": 300,
                "duration_target_sec": [30, 59] },
  "candidates": [
    {
      "short_id": "S03",
      "slug": "poteryal-2m-za-zvonok",          // latin-kebab, хук, 2-5 слов
      "status": "proposed",                      // proposed|approved|rejected|built
      "rank": 1,
      "score": { "total": 87, "hook": 92, "flow": 85, "value": 80, "emotion": 88 },
      "why": "цитируемый провал → урок; payoff в последней фразе",
      "hook_text": "I lost two million dollars on one phone call",
      "title_ru": "Потерял $2M за один звонок",
      "duration_sec": 42.36,
      "blocks": [
        {
          "block_id": "b1", "role": "hook",      // hook|body|payoff|broll
          "source": { "kind": "final_render",     // final_render | source_clip
                      "file": "YTCR1_v16_Arty_Dzis.mp4",
                      "path": "...", "scene": null, "clip_id": null },
          // ЧЕТЫРЕ представления каждой границы — фрейм-в-фрейм без пересчётов:
          "tc_in":  { "tc": "12:34.120", "sec": 754.120, "frame": 18853,
                      "ticks": 191554525920000 },
          "tc_out": { "tc": "13:16.480", "sec": 796.480, "frame": 19912,
                      "ticks": 202314826080000 },
          "words": { "first": "I", "last": "call",
                     "first_start_sec": 754.32, "last_end_sec": 796.11 },
          "pad_head_ms": 200, "pad_tail_ms": 300,   // фактически применённый воздух
          "speaker": "Arty",
          "transcript": "I lost two million dollars ... on one phone call.",
          "keep_audio": true, "track": "V1", "audio_track": "A1"
        }
        // + блоки body/payoff; ingest-mode: source.kind=source_clip + scene/clip_id
      ],
      "reframe": { "mode": "static",              // static|auto_reframe|keyframes
                   "crop_center_x_pct": 42,        // где спикер по горизонтали
                   "note": "спикер слева, стол справа — не центр" },
      "captions": { "srt": "srt/YTCR01_S03.srt", "burn": false },
      "broll": [],                                  // ingest-mode: вставки поверх
      "notes": "",                                  // Claude → Roman
      "editor_notes": ""                            // Roman/панель → Claude (не трогать)
    }
  ],
  "changelog": [ { "v": 3, "date": "...", "changes": ["S03: хвост +1 фраза (payoff)"] } ]
}
```

Правила:
- **Все границы** несут `{tc, sec, frame, ticks}`; истина = `ticks`
  (TICKS_PER_SECOND=254016000000, constants.js:96). Панель НЕ пересчитывает секунды —
  кладёт тиками (float-секунды драйфуют: проверено, double 109.44 → +1 кадр).
- `words` — самоконтроль: панель может отвалидировать, что tc_in ≤ first_start
  и tc_out ≥ last_end (иначе слова режутся — validation error W01).
- Версии: новая генерация Claude = `_v{N+1}_in.json`, старые не переписываются
  (память asm-versions).

### 5.2 `_out.json` (панель → Claude) — «состояние + баги»

Самодостаточен: Claude может улучшать, не открывая проект.

```jsonc
{
  "schema": "ytai-shorts-v1", "direction": "out",
  "version": 3, "exported_at": "...",
  "based_on_in": "YTCR01_Shorts_v3_in.json",
  "panel_state": {
    "statuses": { "S01": "approved", "S02": "rejected", "S03": "built" },
    "editor_notes": { "S02": "не тот вайб, найди про brokers exam",
                      "S03": "хук начать на фразу раньше" },
    "marker_readback": {                       // юзер двигал маркеры в preview
      "S03": { "tc_in": {"sec":753.4,"ticks":...}, "tc_out": {...},
               "moved": true }
    }
  },
  "build_report": [                             // результат verify-гейта
    { "short_id": "S03", "sequence": "YTCR01_S03_poteryal-2m-za-zvonok",
      "built_at": "...", "drift_ms": 0, "ok": true,
      "clips": [ { "track":"V1", "timeline_start":{"tc":"00:00:00:00","sec":0,"ticks":0},
                   "source_in":{...}, "source_out":{...}, "duration":{...} } ] }
  ],
  "issues": [                                   // «экспорт багов»
    { "code": "W01", "short_id": "S05", "severity": "error",
      "msg": "tc_out 812.400 < last word end 812.610 — слово 'deal' режется" },
    { "code": "B03", "short_id": "S07", "severity": "warn",
      "msg": "media offline: C5391.MP4 не найден по source_path" }
  ],
  "sequence_dumps": { "S03": { /* dumpSequence-формат index.js:10079-10154 */ } }
}
```

Коды issues (валидатор панели, .validation-panel):
`W01` слово режется (tc за пределами words) · `W02` pad захватил соседнее слово ·
`O01` пересечение кандидатов в preview · `B01` fps mismatch · `B02` дрейф > 2 мс
после сборки · `B03` media offline · `S01` дубль slug/S{NN}.
Пересечение кандидатов = блокирующий гейт на Build Preview (паттерн Firecut: кнопка
задизейблена, пока юзер не разрулил — AI не гадает).

## 6. Канон точности (границы реза)

Проблема, которую решаем: у всех конкурентов границы «примерные» (сами документируют
«drag the marker to fix»); слова обрезаются в ноль. Наш канон:

1. **База — слово, не сегмент.** tc берутся из words[] (whisper word-grid ~10-20 мс).
2. **Воздух (air padding), никогда не в ноль:**
   - `pad_head = min(gap_from_prev_word, 250ms)`; `pad_tail = min(gap_to_next_word, 300ms)`
     (зеркало Assembly-канона smart padding = min(gap, 0.3)).
   - gap=0 (слова впритык) → pad=0, НЕ захватываем чужое слово; но тогда Claude обязан
     рассмотреть сдвиг границы на фразу (лучше начать раньше, чем встык).
3. **Снап к кадру ПОСЛЕ паддинга:** in → floor, out → ceil (frameSnap.js:18-32,
   epsilon 1e-9). В JSON пишутся уже снапнутые значения + ticks.
4. **Позиции на таймлайне — только тики** (TickTime.createWithTicks), транзакции
   последовательные по возрастанию. Никаких float-секунд и compound overwrite
   (реверс-порядок исполнения — память frame-floor).
5. **Верификация числом, не глазом:** после сборки read-back дампом, толеранс 2 мс,
   результат в build_report. Не прошло — issue B02, секвенция помечается.
6. Спорные границы Claude слушает ушами: ffmpeg-вырезка wav вокруг границы (локально,
   секунды) прежде чем ставить финальный tc — опционально в finder-скрипте.
7. Мульти-блочные шорты: на стыках блоков рекомендация +2 кадра audio crossfade —
   вручную/этап полировки (UXP пока не умеет транзишны — вне MVP).

## 7. Скоринг-рубрика (Claude-side, для finder-промпта)

Скор 0-100 = взвешенно: **Hook** (первые 3 с останавливают скролл: вопрос, цифра,
провокация, незавершённость) · **Flow** (законченная мысль: началась и закрылась,
никакого mid-sentence; арка внутри 20-59 с) · **Value** (польза/инсайт/цитируемость) ·
**Emotion** (пики: смех, злость, уязвимость; в ingest-режиме += energy/emotion/live_score
из full_source_index). Обязательно поле `why` — одна строка на человеческом.
Кандидатов на видео: 8-15 (передоза нет смысла: рынок показывает ~40% брак даже у топов).
Длительность: default 30-59 с (канон YT Shorts), таргет из ContentList/канала.
Hook-first reorder разрешён (blocks с role), но всегда есть прямой вариант.

## 8. Reframe и captions

**Reframe (9:16 из 16:9/4K):**
- MVP: `mode:"static"` — кадр 4K кладётся в 1080×1920, статичный горизонтальный сдвиг
  по `crop_center_x_pct`. ⚠️ **Спайк S-1 (блокер MVP по этой части):** проверить, умеет
  ли UXP 25.6/26.0 ставить Motion Position/Scale (ppro.VideoComponentChain /
  ComponentParam.createSetValueAction). В кодовой базе прецедента НЕТ, а
  VideoClipTrackItem.cast в 26.0 сломан (грабли adjust-вкладки). Fallback-и:
  a) юзер жмёт Premiere Auto Reframe на построенной секвенции (одна кнопка, как Firecut);
  b) офлайн-рендер: ffmpeg crop по x-треку (face_finder уже умеет находить лицо локально)
     — путь «шорт без Premiere вообще» для батчей.
- Позже: `mode:"keyframes"` — трек позиции по лицу (face_finder/vision) → кейфреймы.
- `crop_center_x_pct` Claude оценивает по кадрам (vision/OCR-карта экранов — локально).

**Captions:** Claude пишет per-short SRT (clip-local от 0, из words[], с воздухом,
фразы 1-4 слова). MVP: файл рядом (`srt/`), импорт в Premiere руками/позже кнопкой.
Burn-in стили — вне MVP (Essential Graphics/MOGRT — отдельная история).

## 9. Roadmap

- **MVP-1 `finished` (пилот YTCR01 v16):**
  finder-скрипт (Claude + локальный пре-процессинг words) → `_in.json` + HTML-витрина →
  вкладка: load/candidates/preview-маркеры/read-back → build 9:16 (без reframe-двига,
  static center) → verify-гейт → `_out.json` round-trip. Спайк S-1 параллельно.
- **MVP-2 полировка:** dual 16:9, SRT-генерация, ContentList (кол. N/O), экспорт-пресет
  (спайк S-3: AME через UXP или руками), именование файлов `{PROJECT}_S{NN}_{slug}.mp4`
  в шортс-папку проекта.
- **MVP-3 `ingest`:** finder по per-clip words + full_source_index, мульти-блок +
  hook-first, кандидатский рил, B-roll вставки (V2), прокси-превью в HTML.
- **R&D:** S-1 Motion params · S-2 face-track кейфреймы → reframe keyframes ·
  S-3 batch export · S-4 диаризация финального рендера · S-5 audio crossfade на стыках.

## 10. Что взяли у конкурентов (сводка исследования 18.08.2026)

| Продукт | Берём | Отвергаем |
|---|---|---|
| Firecut | маркеры = поверхность ревью; панель-список синхронен таймлайну; overlap-гейт блокирует кнопку; выход = НОВЫЕ секвенции в бине; кэш анализа | нет экспорта состояния; границы «примерные» by design |
| Premiere Copilot | скор с факторами; accept/reject/regenerate per-candidate; dual 16:9+9:16; «только транскрипт+метаданные уходят в LLM» | закрытый формат, нет JSON round-trip |
| Phantom | «Create Markers» как дешёвый preview-шаг отдельно от «Create Clips»; стоп-кнопка генерации | нет пословного снапа границ, нет паддинга — наша главная фора |
| GoatEdit | streamed-лог сборки с галочками и цифрами; Hook Score как один бейдж | маркетинг > механика; чёрный ящик |
| Cola | manual-путь рядом с auto (юзер сам выбрал диапазон — панель всё равно соберёт 9:16); auto-backup перед правками; click-word-to-seek | нет скора вовсе |
| Рынок (Opus и др.) | named-факторы скора + «why»; complete-thought границы; +handles (наш аналог: границы двигаются маркерами без пере-генерации); hook-first reorder | web-рендер вместо секвенций; opaque score |

Наши уникальные вещи (ни у кого): пословный паддинг-канон с verify-гейтом 2 мс;
полный JSON-стейт наружу для LLM-итерации; HTML-витрина с плеером до открытия Premiere;
локальный finder (токены — только на мышление, не на транскрибацию).

## 11. Решения по умолчанию (можно переиграть)

1. **Папка JSON:** `00_Setup/07_Shorts/` (после 06_Enrichment). Рендеры-мастера —
   в шортс-папку проекта: v4.1 = `04_Shorts/`, старая структура (YTCR01) = `03_Shorts/`.
2. **Пилот:** YTCR01, finished-mode, 8-12 кандидатов из v16.
3. **Bin в Premiere:** `Shorts`.
4. **Язык кандидатов YTCR01:** транскрипт v16 — EN; hook_text EN + title_ru для Романа.
5. scripts/07_shorts (01_find_moments.py и др.) — устарели (слой 03_Analysis),
   переписываются как finder к этой схеме, README-канон имён остаётся.

## 12. Файлы реализации (когда начнём кодить)

- `index.html`: таб-кнопка + `#tab-shorts` контент (+bump версии index.html:371).
- `index.js`: блок `// SHORTS` в DOMContentLoaded (11214-11398), `shortsState`,
  setShortsStatus/Validation (паттерн parts index.js:2204-2216), `new Logger('SHORTS')`.
- `src/shorts/shortsBuilder.js` (+ `SHORTS_BUILDER_VERSION`): импорт только shared/* +
  sequenceFactory; mock-fallback require; тесты `tests/shorts/` (node:test + mock ppro).
- Finder: `scripts/07_shorts/find_moments.py` (rewrite) — препроцессинг words +
  кандидаты-заготовки; финальный отбор/скоринг — Claude в чате.
- Валидатор: `scripts/07_shorts/validate_shorts.py` — W01/W02/O01/S01 офлайн
  (зеркало панельного, как validate_ingest в wordsync).
