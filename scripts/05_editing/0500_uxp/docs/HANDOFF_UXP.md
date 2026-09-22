# UXP-панель — хэндофф для отдельного чата (2026-07-12)

## 📁 00_Source_Timelines + «Hide source timelines» (2026-09-15, НЕ закоммичено)

Жалоба Романа (Premiere 26.x, YTUVI02): корень Project-панели забит ~18 исходными
таймлайнами сцен `{CODE}_{NN}_{Scene}` (двузначный индекс: `YTUVI02_01_Studio` …
`YTUVI02_17_UviStore_Showcase_Broll`). Теперь они живут в бине верхнего уровня
**`00_Source_Timelines`** (`constants.SOURCE_TIMELINES_BIN`; НЕ внутри 00_Source —
cleanBeforeBuild чистит детей 00_Source). Рабочие таймлайны стадий остаются на месте:
`{CODE}_5_Review_*`, `{CODE}_1_Ingest` (однозначный индекс), `_part_*`, `A01_*`, шорты.

- **Корень бага:** `bin.createMoveItemAction(item)` с ОДНИМ аргументом в partsBuilder,
  shortsBuilder, clipActions (архив в 03_Assembly). Реальная сигнатура 25.6+ —
  `FolderItem.createMoveItemAction(item, newParent)`; one-arg молча ничего не двигал и
  логировался как успех (авто-сейв YTUVI02 15.09: SSEF_sources_v1 и 5_Review_v6 в корне,
  05_Review пуст). Мок это «покрывал» — двигал в `this`.
- **`src/shared/binMove.js` (v1.0.0):** единственный путь перемещения —
  `root.createMoveItemAction(item, bin)` (фолбэк: `item.getParentBin()`), синхронные
  колбэки lockedAccess/executeTransaction, проверка `false` от транзакции, READ-BACK по
  свежим getItems (getId → guid → имя) + страж «число секвенций выросло = копия». true
  только после проверки; ничего не удаляет. Там же `ensureRootBin` (бывший
  partsBuilder.ensureBin), `findSequenceProjectItem` (Sequence.getProjectItem → корень),
  `collectTakenNames` (все секвенции ∪ корень — для _v{N}).
- **`src/shared/sourceTimelines.js` (v1.0.0):** правило `^{CODE}_\d{2}_`;
  `fileBuiltSceneSequences` — wallClockBuilder.build и linearBuilder.buildMultiSceneIngest
  после всех сцен (с маркерами) кладут свежие сцены в бин (non-fatal);
  `hideSourceTimelines` — батч для кнопки.
- **Кнопка «📁 Hide source timelines»:** Ingest-таб (`btn-hide-source-timelines`, рядом с
  Build Ingest) и Doctor-таб (`btn-doctor-hide-source-timelines`). Берёт секвенции
  открытого проекта через listProjectSequences, код — из имени/пути ОТКРЫТОГО проекта,
  двигает только лежащие в КОРНЕ; повторный запуск безопасен. Probe-first: если первое
  перемещение не подтвердилось — остальные не трогает. Статус:
  `moved N · already in bin M · failed K` (+ skipped / stopped). `_SYNC`-таймлайны
  (`{code}_{NN}_{scene}_SYNC`) под правило тоже попадают — при Spread НЕ двигаются.
- **Потребители:** partsBuilder v1.12.0 (part.bin реально двигает — SSEF
  `YTUVI02_18_SSEF_Commentary` с `bin: 00_Source_Timelines`; auto-version видит версии в
  бинах), shortsBuilder v0.1.1, cleanExistingSequence (сканирует корень + extraBin +
  00_Source_Timelines + getProjectItem одноимённых; rename и move — РАЗНЫЕ транзакции;
  номер _v{N} по всем именам секвенций), listProjectSequences / verifyIngest (фолбэк-cast
  и по бину), превью «Will build» в Parts (collectTakenNames).
- **⚠️ Живой тест первым:** API-перемещение секвенций подтверждено только ответом Adobe на
  форуме. Роману: нажать кнопку на YTUVI02 — probe-first остановит батч, если первое
  перемещение не подтвердится; смотреть лог INGEST («Moved … (verified)» / «NOT verified»).

## ✅ Preedit-дедуп ЗАВЕРШЁН по всем 5 (v3→v5, 3 раунда воркфлоу + инлайн)

Итоговые брифы: 01=v4, 02=v5, 03=v5, 04=v5, 05=v3; бандлы A01_Studio +
__DeletedScene + PE00 перегенерены везде, старые в scenes/archive/. Раунды:
(1) анализ 43 дефекта; (2) fix по рецепту + адверсариальный verify — 01 принят,
у 02/03/04 верификаторы выкопали остаточные пропуски (потерянные слова на стыках,
единственные прочтения в катах, хук с полуслова); (3) точечный touchup по
координатам верификаторов — все приняты (ok=true ×4, word-точная сверка).
Роману: в каждом проекте Assembly-таб → Build Selected (A01_Studio) → Build
Premontage (PE). Незакрытые мелочи для монтажёра (в notes сегментов): 02 —
Pigeon Blood-буллет блока 29 не прочитан (преэкзистентно), «Кстати» на хвосте
seg_29_r2 проверить на слух; 03 — 18с тишины в seg_23_r2, оговорка «цвете→свете»
в 31.1a; 04 — заикания в seg_42_r2/seg_26; 01 — фальстарт «Лазер» в seg_39_1,
CTA блока 51 отличается от сценария (поздний ретейк, ранний в cut_4_1603).

## Preedit v3 (дубли прочтений) — YTUVI05 ГОТОВ, 01-04 в резюме воркфлоу

Жалоба Романа (CSV STT c A01_Studio): дубли в кате. Причина: матчер брал блоки
широкими пролётами (seg_1_1 = 52.5с с ОБОИМИ дублями «Ришелье»). Воркфлоу
wf_93f9bd96: 5 анализов ГОТОВЫ (журнал; 43 дефекта суммарно), fix-агенты упали в
session limit (сброс 22:00). YTUVI05 доделан инлайном: бриф
`YTUVI05_Assembly_v3_in.json` (96 сегментов: 6 блоков разрезано по правилу
«последний чистый дубль», вырезки → USE=FALSE; +6 пустых паддинг-перекрытий
затримлено, 3 оставшихся ≤0.16с в допуске), бандлы перегенерены штатными
генераторами: A01_Studio 305 seg / 27.7 мин (было 270/29.6 — −1.9 мин дублей),
__DeletedScene 175, PE00_Premontage 27.7 мин. Старые бандлы в scenes/archive/.
Верификация: ключевые фразы в TRUE-покрытии по одному разу («Ришелье» 1, «Жан
Демест» 1); «Рубин Тимура»×3 и «розовая шпинель»×8 — легитимные сценарные
повторы в РАЗНЫХ блоках. Романовы клики: Assembly-таб → Build Selected
(A01_Studio) → Build Premontage (PE). Рецепт inline-фикса = эталон для 01-04
(fix-агентам: применять fix_primary из анализов к брифу latest → v+1,
make_mcam_part --scene 01_Studio (+--sound-stem по _recN брифа) →
make_master_part --pe; wordsync result Studio = ingest.sync['01_Studio'].result).

## ЗАДАЧА от основного чата: маркеры в Debug dump + канон цветов

1. Debug dump НЕ экспортирует маркеры секвенций — добавить в all_sequences.json
   per-sequence markers[] (name, start, duration, colorIndex, type, comment) —
   Роман шлёт дампы на проверку маркеров, сейчас слепая зона.
2. Канон применён (основной чат, markers v2 в YTUVIS1 ingest): имя маркера начинается
   с камня; ЕДИНЫЙ цвет камня: Рубин=Red, Сапфир=Blue, Турмалин/Параиба=Cyan,
   Шпинель=Magenta, Бриллиант=White(5, ДОБАВЛЕН в MARKER_COLOR_INDEX constants.js),
   Опал/Топаз=Orange, Изумруд=Green, без камня=Yellow. ⚠️ Маркеры в sync-сценах
   считать в REMAPPED-координатах (gap-компрессия схлопывает union-дыры в 0) —
   генератор scratchpad/markers_v2.py это уже делает.

## v2.4.2 — НАСТОЯЩИЙ источник артефактов Studio: placeholder ensureTracks

Диагноз «01_Studio = старая сборка» был НЕВЕРЕН: пересборка 18:05 воспроизвела
раскладку 1-в-1 (дамп 15-05-47). Разбор: план корректен (details V4 подряд — это
дизайн no-gap; TX «5 стрипов» — video-bounded нарезка планировщика). Артефакты =
placeholder из `ensureTracks` (сид целиком вставляется на верхние V4/A5 для
создания дорожек, удаление в 25.6 не работает) → его рубят overwrite деталей и
двигают TX-insert'ы → многоминутные куски CAM_3_2190 на V4/A4/A5.
Фикс: 1-кадровый трим placeholder'а ПЕРЕД insert-циклом ensureTracks (insert
уважает in/out, паттерн partsBuilder 1.6.2) + clear после. Урок:
`createSequenceFromMedia` in/out ИГНОРИРУЕТ (трим сида в create() не работает —
оставлен как no-op-страховка), `createInsertProjectItemAction` — уважает.
Тесты 243/6. Требует пересборки сцен после перезагрузки панели (v2.4.2).

## Debug dump: фикс «rootItem is not defined» + маркеры/диагнозы YTUVI05

- Debug падал «rootItem is not defined» (✗ у имени проекта = индикатор упавшего
  дампа): при переводе энумерации на listProjectSequences() потерялось объявление
  rootItem, шаг 9 (dumpBinTree) им пользовался. Возвращено `var rootItem = await
  project.getRootItem()`. Дампы 17:52 пригодны (упало ПОСЛЕ all_sequences.json;
  нет только premiere_bins.json).
- YTUVI05 ingest обогащён: markers['03_Cafe_Gem_Expert_Talk'] (11 глав из
  stone_labels YTUVIS1, offset=wall−min) + stone_labels-подмножество; бэкап
  YTUVI05_ingest_backup_20260712_180018.json. Билдеры уже ставят маркеры (v2.4.1).
- Диагнозы по дампу 14-52-50: 01_Studio = СТАРАЯ сборка (сид CAM_3_2190 фрагментами
  на V4/A4/A5, details линейно с 0 вместо wall, TX A5 порезан insert'ами) → лечится
  пересборкой на v2.4.x. 02_Natalia: «дырки» только на A1 — 15/38 IMG_*.MOV Натальи
  БЕЗ аудио-потока в исходнике (ffprobe подтвердил), видео сплошное — НЕ баг.
  03_Cafe (свежая, 57 клипов, fps 50 от сида-BTS): камеры лежат по wall.

## ✅ v2.4.2 (основной чат): маркеры-главы = ДИАПАЗОНЫ с цветами; переписан sceneMarkers

Роман: маркер = глава-диапазон (3-10 мин), разные цвета по камню. sceneMarkers.js
переписан по проверенному Assembly-паттерну: `ppro.Markers.getMarkers(seq)` (в v2.4.1
был sequence.getMarkers() — вероятно, маркеры вообще не ставились!), duration в
createAddMarkerAction, затем отдельными транзакциями createSetColorByIndexAction +
createSetTypeAction(MARKER_TYPE_CHAPTER) (createAddMarkerAction игнорирует type).
Контракт ingest.markers[scene] расширен: {offset_sec, duration_sec, name, comment, color}
(color = ключ MARKER_COLOR_INDEX). Тесты sceneMarkers: 5 pass (через мок ppro).
YTUVIS1 ingest сцены 03 обновлён (длительности до следующей главы + цвета по камню:
рубин Red, сапфир Blue, шпинель Magenta, турмалин Cyan, опал Orange, изумруд Green).
Также созданы YTUVIS1_Footage/{99_Pipeline/logs,00_Setup/logs} (Debug-дамп «не работал»
у Романа — возможно, из-за отсутствия папок; точная ошибка не получена).

## ✅ СДЕЛАНО основным чатом (v2.4.1): маркеры-главы из ingest

Реализовано: `src/ingest/placement/sceneMarkers.js` (`addSceneMarkers`, тип Chapter
с фолбэком на Comment, guard-паттерн addTimeJumpMarkers) + хуки в ОБОИХ билдерах
(wallClockBuilder после buildScene, linearBuilder перед results.push) —
читают `ingest.markers[sceneName]`. Тесты: `tests/ingest/sceneMarkers.test.js` (4 pass).
Branding v2.4.1. index.js НЕ тронут.

## (АРХИВ) ЗАДАЧА от основного чата: маркеры-главы из ingest (для YTUVIS1_Footage)

Роман создал review-проект `/Volumes/T7-Blue-2-RYA/YTUVI-Footage/YTUVIS1_Footage`
(«первый спринт», отсмотр всех папок; таймлайн = папка, номер = номер папки).
Ingest уже содержит НОВЫЕ поля (собраны основным чатом):
- `markers: {scene: [{offset_sec, name, comment}]}` — маркеры-главы «какой камень
  обсуждаем/показываем» (offset_sec от начала секвенции сцены = wall_offset−min(wall_offset));
- `stone_labels: {scene: {clip_id: {label, stones[]}}}` — справочно.

**Нужно в билдере**: после buildScene ставить sequence-маркеры из
`ingest.markers[scene]` — механика уже есть в `wallClockBuilder.addTimeJumpMarkers`
(markers.createAddMarkerAction(name,'Comment',tick,TIME_ZERO,comment) с guard'ами);
обобщить/вызвать и для linear-сцен. Пока собрана сцена 03 (132 клипа, 45 маркеров) —
пример для проверки; остальные 13 папок основной чат раскатает после ок Романа.



## v2.3.4 — фикс «артефактов» ingest-сборки (стрей-сид)

Разбор жалоб Романа по собранным таймлайнам YTUVI05: «артефакты» в 01_Studio =
незачищенный сид createSequenceFromMedia (25.6: удаление падает «script object is
no longer valid», в логе «Pre-warm cleanup undefined: 1 item(s) REMAIN»).
Фикс в `src/ingest/placement/sequenceFactory.create()` по паттерну partsBuilder
1.6.2: сид обрезается до 1 КАДРА (createSetInOutPointsAction) ДО
createSequenceFromMedia (формат наследуется всё равно), после — clear; при
несработавшей зачистке остаётся невидимая точка, не полный клип. Плюс label
'seed V1/A1' в removeAllItemsOnTrack (был undefined). «Лидер» 4.6 мин в
01_Studio — НЕ баг: TX-WAV начинается с 0, видео с 277с (рекордер писал раньше).
«Дырка» в 02_Natalia — в данных зазоры ровно 1.0с, дырка сборочная → пересборка
после фикса; если останется — смотреть дамп. Тесты: 239 pass / 6 fail (предсущ.).

## Universal растворён: сцены 14 больше нет (решение Романа)

74 universal-клипа разложены по сценам СВОИХ юнитов (03←42, 04←14, 05←1, 06←5,
07←3, 08←4, 11←5); YTUVI05: 16 сцен / 247 клипов, PASSED; сцена 14 удалена
(--remove-scene) + папка симлинков снята. YTUVI01-04 — воркфлоу (см. журнал
wf_78f82f70). ⚠️ Грабля make_ingest: клипы с именами, уже занятыми ДРУГОЙ сценой,
МОЛЧА пропускаются («filename collisions») — удалять сцену 14 ПЕРВОЙ, потом re-add;
на YTUVI05 из-за этого пришлось повторить sync re-add (247 вместо 194 со второго
захода). Номер 14 теперь свободен под досъём Натальи 2026-07-13 (план в памяти —
перенумерация 14→18 больше не нужна, Universal-сцены не существует).

## v2.3.3 — компактный список сцен + открытие: css/styles.css МЁРТВ

⚠️ **`css/styles.css` не подключён НИЧЕМ** (ни `<link>` в index.html, ни manifest, ни JS)
— все стили v2.3.0-2.3.2 для scene-list молча не грузились, список рендерился голыми
UA-стилями UXP (label блочный и притемнённый → имя сцены нечитаемо, строка в два этажа).
Живые стили = инлайн-`<style>` в index.html — новые правила класть ТУДА (в styles.css
добавлен warning-header). Scene-list переписан: одна компактная строка
`[cb] имя · N clips · badge`, всё inline (UXP не умеет flex gap и float), явный
display:inline и цвет для label-текста. Версия v2.3.3.

## Ingest YTUVI05 доукомплектован футадж-сценами (2026-07-12, та же сессия)

По FOOTAGE_ROUTING.md эпизода 05 в ingest добавлены 10 сцен / 83 клипа (стало 13 сцен /
141 клип): 03_Cafe, 04_Driving, 05_Street — **sync-режим** (wordsync в НОВЫЕ папки
`YTUVI-Footage/_pipeline/wordsync-{unit}-YTUVI05`, старые прогоны YTUVI01 не тронуты;
ZVE1-дельты 194.45–195.24с, unplaced=0, один soft-gate: RYA-ZVE1-1790 resid 1.38с —
standalone-стык, принято); 07–13 — linear flat (gap 1.0). Номера 10–13 закреплены
алфавитно ВПЕРВЫЕ (канона не было): 10_Gem_Weighing_Broll, 11_Gems_In_Hands_Macro,
12_Globe_Gem_Origins, 13_Jewelry_Try_On_Closeups — теперь это канон для ep01–04.
Списки: `00_Setup/01_Ingest/scene_lists/`. validate_ingest --strict: единственный warn —
предсуществующий лидер 277с в 01_Studio. Симлинки целы (0 broken).

## v2.3.2 (2026-07-12, та же сессия) — адверсариальное ревью v2.3.1 + UI/бины

После v2.3.1 прогнано ревью-воркфлоу (19 агентов): 9 подтверждённых находок, все исправлены:
1. Асимметрия detect(getSequences-only) vs delete(getSequences+cast) → общий
   `listProjectSequences()` (getSequences-first + cast-supplement, дедуп по guid),
   и detect, и clean, и verify, и syncAudio, и stage-детекция, и Debug dump — через него.
2. **Регрессия** прошлой сессии: `linearBuilder.js` именовал секвенции голым `{scene}`
   (HEAD был `{code}_{scene}`) → вечное «new» + дубли при каждом Build. Возвращён префикс;
   detect/clean/badge принимают И legacy bare-имена.
3. `findSequencesByName` теперь массивы по имени → rebuild удаляет ВСЕ дубли имени.
4. `clipActions.cleanExistingSequence` (Assembly/DeletedScene/Parts/Screens/Review):
   архив только guid/cast/name-подтверждённых секвенций; last-resort delete — только confirmed.
5. `buildReview` «already exists» — только реальная секвенция (раньше стем рендера матчился
   как «секвенция» → вставки уезжали в активный таймлайн); существующая активируется.
6. Пустые дубли-бины «00_Source 05» при каждой сборке: `createBinStructure` теперь
   идемпотентен (создаёт только отсутствующие).
7. Список сцен в Ingest рендерился в одну кашу (UXP игнорирует flex gap, label инлайновый)
   → блочные `.scene-row` + отступы марджинами + float-бейдж (styles.css + index.js).
Ключевые знания: `project.getSequences()` — надёжный энумератор; `Sequence.cast(rootItem)`
в реальном билде Романа работает ТОЛЬКО для активной секвенции; `createBinAction`
на существующем имени плодит «00_Source 05»; UXP не умеет flex gap.
Тесты: 234 pass / 7 fail (та же предсуществующая семёрка). Дампы-доказательства:
`YTUVI05_Spinel/99_Pipeline/logs/YTUVI05_Spinel_dump_2026-07-12T{09-45-37,10-05-35,10-06-39}`.
Незакрыто: тестового покрытия detect/clean нет (index.js не модуляризован); Lumetri
`ppro.VideoClipTrackItem.cast is not a function` (0/9 клипов с LUT) — отдельная тема.

## v2.3.1 (2026-07-12, вторая сессия, НЕ закоммичено) — фикс ложного «built ✓»

Симптом (YTUVI05): все сцены в «Sequences to build» помечены «built ✓» и сняты,
выбрать нечего — при том что реальных секвенций сцен в проекте НЕТ.
Причина: в корне проекта лежат offline-стабы от импорта чужого prproj с именами
`YTUVI05_01_Studio` (×2), `YTUVI05_02_Natalia_Gems` (×2), `YTUVI05_06_Office_Gem_Commentary`
(+ дубли-бины `00_Source 01`, `01_Transcripts 02`, копии `*_v1`). Старый
`detectExistingSequences` матчил корневые итемы по голому имени.
Фикс (index.js):
- `detectExistingSequences` → сверка с `project.getSequences()` (надёжный энумератор,
  см. комменты Doctor: `Sequence.cast` может врать) + дедуп;
- новые `findSequencesByName`/`deleteSequencesByName` (getSequences + cast-fallback);
  `cleanBeforeBuild`/`cleanScenesBeforeBuild` удаляют секвенции ТОЛЬКО через них —
  раньше `deleteSequence()` звался на любой корневой итем с совпавшим именем (риск
  задеть MCAM-стабы при rebuild);
- `verifyIngest`: карта секвенций тоже с getSequences(), cast остался как дополнение;
- index.html: branding v2.3.1 (проверка, что Роман перезагрузил панель).
Тесты: 234 pass / 7 fail — те же предсуществующие (reviewBuilder и пр.), новых нет.

## Только что сделано (v2.3.0, НЕ закоммичено)

**Ingest: выбор сцен-секвенций (как в Parts)** — Роман строит таймлайны по одной,
уже собранные не пересобираются.

Файлы и точки входа:
- `index.html` — блок `#ingest-scenes` («Sequences to build», чекбоксы + ссылки new/all/none)
  между `#ingest-summary` и progress-bar; версия в branding → `v2.3.0`.
- `css/styles.css` — стили `.scene-select-panel/.scene-row/.scene-badge` (в конце файла).
- `index.js`:
  - `getIngestSceneNames / renderIngestSceneList / getSelectedIngestScenes / setIngestSceneChecks / filterIngestScenes` — рядом с `detectExistingSequences` (~line 795+);
  - `cleanScenesBeforeBuild(project, ingest, scenes)` — селективная очистка: удаляет ТОЛЬКО секвенции `{code}_{scene}` и бины `{code}_{scene}[,_transcripts]` под `00_Source`; старый `cleanBeforeBuild` (полная зачистка Source/Transcripts) остался для single-scene;
  - `buildIngest()` — в мультисцене строит отмеченные сцены (фильтрованная копия ingest: clips/tx_strips/cam_layers), после сборки re-render списка;
  - `verifyIngest()` — **фикс бага**: искал секвенцию по голому имени сцены, а реальные = `{code}_{scene}`; несобранные сцены теперь нейтральное «○ not built yet» (helper `info()`), не fail;
  - слушатели ссылок new/all/none — в init рядом с `btn-build-ingest` (~line 10290).

Статус: `node --check` OK; тесты 234 pass / **7 fail — PRE-EXISTING** (reviewBuilder.js
удалён в рабочем дереве прошлой сессией, BIN_NAMES/formatTimecode — не мои модули).
**Роман ещё не перезагружал панель в Premiere** — первая проверка UI за ним.

## Рабочее дерево 0500_uxp (uncommitted, смесь нескольких сессий!)

`git status`: M index.html, index.js, css/styles.css, manifest.json, 0500_uxp_spec.md,
src/ingest/{ingestLoader,lutManager,timelineBuilder,transcriptImporter}.js,
**D src/review/reviewBuilder.js**. Коммитить аккуратно, не сваливать в один.
⚠️ `git stash` в репо падает («docs/ytfp/index.html beyond a symbolic link») — не пользоваться.

## Контекст: зачем это всё

Поток «папка футаджа → ingest всех проектов → таймлайн по одной сцене»:
- Футадж: `/Volumes/T7-Blue-2-RYA/YTUVI-Footage/` (14 сцен, поклиповый роутинг по эпизодам:
  `EPISODE_ROUTING.html` + `YTUVI-Projects/{эп}/00_Setup/FOOTAGE_ROUTING.md`).
- Сделано: `Office_Gem_Commentary` → сцена `06_Office_Gem_Commentary` в ingest YTUVI02-05
  (`make_ingest.py --add --linear --flat --gap 1.0`, списки = primary∪also минус working/skip;
  симлинки `01_Source/{scene}/`). YTUVI01 уже имел сцены 03-09 (прошлая сессия) — не трогать.
- Очередь: остальные папки футаджа тем же паттерном (по команде Романа).

## Известные хвосты / идеи для этого чата

1. При rebuild одной сцены транскрипт-итемы прошлой сборки в бине Transcripts не чистятся
   (возможны дубли SRT-итемов) — селективный clean их не трогает. Мелочь, но заметная.
2. 7 падающих тестов — привести в порядок (reviewBuilder удалён: тест ссылается на него).
3. manifest.json / 0500_uxp_spec.md изменены прошлыми сессиями — сверить и закоммитить.
4. Прочие «моменты» Романа по UXP — спросить у него, это его список.

## Память (memory-ключи)

`project_ytuvi_footage_routing` (роутинг+ingest-раскатка+v2.3.0), `feedback_uxp_parts_stage`,
`feedback_uxp_panel_ui` (вкладка solid, Project сворачивается, без логов), `reference_uxp_doctor_relink`.
