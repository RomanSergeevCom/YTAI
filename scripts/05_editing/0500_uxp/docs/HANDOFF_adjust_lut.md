# HANDOFF: LUT-слои на ingest (вкладка Ingest → Apply LUT Layers)

**Дата:** 18.08.2026 (обновлён после патча диагностики) · **Тест-проект:**
`/Volumes/T7-Beige-RYA/YTCH/YTCH13_Kirill_2` (Premiere Pro **Beta 26.x**)

## Цель и статус

Автоцветокор на этапе ingest: adjustment layer над **каждым клипом**, LUT по
плану `00_Setup/01_Ingest/{CODE}_lut_plan.json` (план строит
`scripts/999_extra/lut_face_score.py` + правки Ромы через интерактивный HTML,
SOP: https://yt.rya.ae/kb/luts/ — 3.8 Scene LUTs; с 21.09.2026 вынесено из /kb/ingest/ «LUT-ревью»).

| Звено | Статус |
|---|---|
| Слои над каждым клипом, все секвенции, точный трим | ✅ 26/26 на YTCH13 |
| Имя слоя = LUT (`03_dark_scene`…) | ✅ |
| Repair-идемпотентность (повтор = дозаполнить, не дублить) | ✅ |
| Lumetri на слой | ✅ (после фиксов API) |
| **Look (сам LUT) автоматически** | ❌ **ДИАГНОЗ ОКОНЧАТЕЛЬНЫЙ (прогон 18.08 16:30)**: Look = ЧИСЛОВОЙ индекс меню (`current: type=number value=0`); строка через createKeyframe → «Illegal Parameter type», через start-keyframe → коммит без ошибки, но readback=0 (тихий no-op). Параметром не выставить. |
| **План Б: клон донор-AL** | ✅ **ПРОБА ПРОШЛА** (18.08 16:37: CLONE OK, V2@0, Lumetri kept: true, Look приехал — скриншот подтвердил). **Клон-режим встроен в Apply LUT Layers / Active Sequence Only** как основной; legacy (голый AL + Lumetri, Look руками) — fallback без донора. |
| **Раскладка донора v2** | ⚠️ клипы теперь @0 КАЖДЫЙ НА СВОЁМ ТРЕКЕ (убивает неоднозначность timeOffset). Шаблон 16:22 — СТАРАЯ раскладка (0/5/10 на V1) → Рома пере-жмёт Build LUT Donor в шаблоне + 3 клика Look. Устаревшую копию в проектах панель мигрирует сама (deleteSequence → re-import). |

## Что сделано 18.08 (вечер) — ждёт ОДНОГО прогона Ромы

1. **`setEffectParam()` переписан** ([src/adjust/adjustmentBuilder.js](../src/adjust/adjustmentBuilder.js)):
   - Каждый нативный вызов помечен шагом → при падении лог говорит
     `setEffectParam(Lumetri) failed @ <step>: …` — точное место за 1 прогон.
   - Порядок установки: **(A)** канонический путь Adobe UXP-сэмплов
     `getStartValue()` → мутация `keyframe.value.value` → `createSetValueAction`
     (обходит валидацию типов в `createKeyframe`); **(B)** fallback
     `createKeyframe(value)`.
   - **Проба типа**: перед установкой лог печатает
     `Lumetri.Look current: type=<string|number|…> value=…` — реальный тип
     параметра Look на живом билде. Если type=number (индекс меню) — строкой
     его не выставить, идём в План Б.
   - Гипотеза блокера: warn «param "Look" not found among […]» не печатался и в
     случае, когда Look НАЙДЕН, но `createKeyframe('dark_scene')` бросил
     «Illegal Parameter type» (по типингам createKeyframe валидирует тип).
     Путь (A) этот блокер обходит.
2. **Кнопка «Probe Donor Clone»** (вкладка Ingest, рядом с Apply LUT Layers) →
   `probeDonorClone()`: клонирует первый клип секвенции `YTAI_LUT_DONOR` в
   активную секвенцию (`SequenceEditor.createCloneTrackItemAction`, 25.6+) на
   свежий пустой трек над контентом. Лог отвечает: (а) работает ли клон МЕЖДУ
   секвенциями; (б) семантика `timeOffset` (куда лёг vs позиция донора);
   (в) уехал ли Lumetri с клоном. Клон остаётся на таймлайне — глянуть Look
   глазами, потом ⌘Z. Защиты (по итогам адверсариального ревью 18.08):
   - **Клоббер-гейт**: после транзакции проба сверяет каждый существовавший
     клип (имя+границы+трек) — если оффсет на live трактуется иначе и клон
     съел контент, лог кричит `⚠️ CLOBBER … press ⌘Z NOW`, статус —
     «Clone hit existing clips»; «CLONE OK» без этой сверки не бывает.
   - **Stale-handle**: ошибка `The script object is no longer valid` на шаге
     клона = протухший хэндл (донор пере-фетчится после grow, но на всякий) —
     это НЕ вердикт «клон между секвенциями не работает», перезапустить пробу.
   - `offTarget: true` в результате = клон лёг не на ожидаемый трек
     (семантика vertical offset иная) — в лог пишется ожидаемый и фактический.
3. **Фикс `lutManager.applyLumetriToClips`**: мёртвый `VideoClipTrackItem.cast`
   заменён guarded-fallback'ом (из-за него ingest вечно писал «Lumetri: not
   applied»), добавлен `await` на `lockedAccess`, дамп параметров через
   `getComponentCount/AtIndex`.
3½. **Кнопка «Build LUT Donor»** — строитель донор-секвенции (см. «Как
   тестировать» п.2): вся ручная работа Ромы сведена к выбору Look в
   дропдауне (и то лишь если API не осилит) + ⌘S в шаблоне.
4. **Тесты**: 33/33 в `tests/adjust/` (было 18), включая live-26.x-surface
   (raw item без cast + `getComponentCount/AtIndex` + async getDisplayName)
   и клоббер-гейт. Mock: `MockComponentParam` (string/number типы, строгая
   валидация «Illegal Parameter type»), `createCloneTrackItemAction` (клон
   получает КОПИЮ цепочки, не алиас), кэш `cast` (стабильная цепочка эффектов
   как на live). Патч прошёл адверсариальное ревью (19 агентов): 12 находок
   подтверждено и исправлено, 4 отвергнуто. 7 падений в binManager/constants —
   дрейф ЧУЖОЙ незакоммиченной работы, к Adjust отношения не имеют.

## Как тестировать (цикл с Ромой) — прогон после переименования LUT (канон: 01_/02_/03_*_scene, тройка В ВЕРХУ дропдауна)

Reload панели (UXP Developer Tool) → вкладка **Ingest**:

0. **Один раз в шаблоне**: открыть `RYA_example.prproj` → **Build LUT Donor**
   (заменит pre-rename клипы на `01_/02_/03_*_scene`; Look'и после переименования файлов
   всё равно битые) → выбрать 3 Look'а руками (тройка теперь В САМОМ ВЕРХУ списка) → ⌘S.
1. **В YTCH13: Apply LUT Layers** — сам мигрирует устаревший донор
   (deleteSequence → re-import из шаблона), заменит alias-слои клонами.
   В логе смотреть:
   - `AL per clip: mode=clone` — клон-режим включился;
   - `<клип> → <lut> (clone) @ V<N>` — по клипу на строку;
   - `setEnd did not verify` / `clone landed …s off target` → семантика
     трима/оффсета иная, лог покажет числа;
   - статус: `LUT layers (donor clones): … · Look 26`.
2. **До пробы Плана Б** — донор-секвенцию строит ПАНЕЛЬ, не Рома. Рома
   открывает МАСТЕР-ШАБЛОН `scripts/01_prepare/0101_init_folders/RYA_example.prproj`
   в Premiere → кнопка **Build LUT Donor** (вкладка Ingest) →
   `buildLutDonorSequence()` создаёт секвенцию `YTAI_LUT_DONOR`, кладёт 3
   AL-клипа из YTAI_ADJ, называет их `01_bright_scene`/`02_normal_scene`/`03_dark_scene`,
   вешает Lumetri и ПЫТАЕТСЯ выставить Look API-путём. Руками остаётся ТОЛЬКО
   то, что API не смог: выбрать Look в дропдауне для клипов из статуса
   «pick Look by hand: …» (если `Look auto 3` — вообще ничего) + ⌘S.
   Идемпотентно: повторное нажатие дозаполняет, не дублит. В YTCH13 и другие
   СУЩЕСТВУЮЩИЕ проекты ничего копировать не надо: проба сама импортирует
   шаблон, когда секвенции нет в проекте (та же цепочка importFiles, что у
   YTAI_ADJ); новые проекты получат её из шаблона даром. Guard: Apply LUT
   Layers («все секвенции») пропускает `YTAI_LUT_DONOR`.
3. **Probe Donor Clone** → лог:
   - `CLONE OK — … landed @ …s V… Lumetri kept: …` → клон работает;
   - `⚠️ CLOBBER` → немедленно ⌘Z, семантика оффсета иная (лог покажет какая);
   - `stale-handle @ …: The script object is no longer valid` → НЕ вердикт,
     перезапустить пробу;
   - другой `failed @ createCloneTrackItemAction: …` → клон между секвенциями
     не работает → держать донор-клипы в каждой целевой секвенции /
     selection+paste.

Рома жмёт и пишет «нажал» — лог читать САМОМУ с диска:
**`{проект}/99_Pipeline/logs/adjust_last.log`** (fallback `00_Setup/logs/`).
Ничего присылать не нужно. Debug-дампы панели лог Adjust НЕ содержат.

## Решение после прогона

Прогон Apply LUT Layers 18.08 16:30 состоялся: **type=number, пути (A) и (B)
мертвы** (см. таблицу статуса). `setEffectParam` теперь сверяет readback и
честно возвращает false («did NOT stick»; враньё «Look auto 26» устранено,
терминальный случай number-vs-string больше не дёргает createKeyframe).
Остался ОДИН развилочный вопрос — прогон **Probe Donor Clone**:

| Результат пробы | Действие |
|---|---|
| CLONE OK, Lumetri kept | План Б работает: builder перевести с applyEffect на клон донор-AL (трим клона по границам клипа; timeOffset семантика — из лога пробы) |
| ⚠️ CLOBBER | Немедленно ⌘Z; vertical-offset семантика иная — читать лог, скорректировать оффсет в probeDonorClone |
| stale-handle | Не вердикт — перезапустить пробу |
| Иной fail @ createCloneTrackItemAction | Клон между секвенциями не работает → донор-клипы держать в каждой целевой секвенции временно / selection+paste API; либо Look руками по имени слоя (имя = LUT уже стоит) |

## Грабли живого API 26.x (уже пойманы и обойдены, НЕ повторять)

- **Creative Look НЕ читается через параметры** (поймано 18.08 18:43): числовой
  параметр «Look» (0..71) — индекс только ВСТРОЕННЫХ Look'ов Adobe и остаётся 0
  при выборе кастомного LUT; сам выбор живёт в бинарном `Blob`/`LookAsset`
  (ArbVideoComponentParam, base64; внутри — путь к .cube + embeddedlut hash,
  видно в XML .prproj). Следствие: «здоровье» клона нельзя проверить чтением →
  **манифест слоёв** `99_Pipeline/lut_layers_manifest.json`
  ({seq: {clip: {lut,startSec,endSec}}}, пишет index.js после каждого
  clone-прогона): canonical-слой здоров ⇔ есть в манифесте с теми же
  границами; alias-имя или нет записи → replace. Undo-устойчиво (слой пропал —
  манифест есть → доставится; слой есть без записи → заменится).

- `ppro.VideoClipTrackItem.cast` — **НЕ существует** (айтемы из
  `getTrackItems(CLIP)` уже VideoClipTrackItem) → `asVideoClip()` fallback.
  В `lutManager.applyLumetriToClips` пофикшено 18.08.
- Цепочка эффектов: `getComponentCount()` + `getComponentAtIndex(i)`,
  НЕ `getComponents()`; имена — `getDisplayName(): Promise` →
  `getChainComponents()` / `readDisplayName()`.
- `ComponentParam`: имя — readonly-СВОЙСТВО `displayName` (метода
  getDisplayName у параметров НЕТ); `Keyframe.value` — вложенный объект
  `{value: <значение>}` (типинги 26.5.0-beta.73).
- `sequenceFactory.ensureTracks` на секвенции С КОНТЕНТОМ **съедает клипы**
  (sweep всех треков — семантика пустой секвенции). Только `growVideoTracks()`.
- Донор `YTAI_ADJ`: создать программно НЕЛЬЗЯ (ни UXP, ни QE) — только
  донорский item. Цепочка поиска: item в проекте → импорт
  `00_Setup/YTAI_ADJ_donor.prproj` → импорт центрального шаблона
  `scripts/01_prepare/0101_init_folders/RYA_example.prproj` (в нём YTAI_ADJ
  уже есть, 3840×2160 25p). **Рома: айтем YTAI_ADJ из Project-панели не
  удалять** — с ним Premiere сносит все слои (дважды случалось).

## Что где лежит

- Модуль: `src/adjust/adjustmentBuilder.js` (+ `tests/adjust/` — 45 тестов,
  `node --test tests/adjust/*.test.js`); UI-хендлеры `runAdjustPerClipFromPlan`
  и `runAdjustProbeClone` в `index.js`; кнопки в `index.html` (вкладка Ingest, низ).
- Спека: `0500_uxp_spec.md` → раздел «ADJUST», там же грабли.
- Типинги: `@adobe/premierepro@26.5.0-beta.73` (npm; `Component.getParam(i)`,
  `ComponentParam.createKeyframe` THROWS при несовпадении типа,
  `SequenceEditor.createCloneTrackItemAction(item, timeOffset, vOff, aOff,
  alignToVideo, isInsert)`).
- LUT'ы: Creative `~/Library/Application Support/Adobe/Common/LUTs/Creative/YTAI/`
  (дропдаун Look), бандл `0500_uxp/LUTs/`, проект `01_Source/00_LUT/`, шаблоны
  `YTAI_Folder_Templates/*/01_Source/(00_)LUT/` — всё переименовано 18.08 (вечер) в
  `{01_bright,02_normal,03_dark}_scene.cube` (префикс группирует тройку в самом верху списка
  Look; имя = ДЛЯ какой сцены; 03_dark_scene ОСВЕТЛЯЕТ). Старые bright/normal/dark
  → `scripts/05_editing/Archive/LUTs_pre_ytai_20260818/`. ⚠️ Look в Lumetri ссылается
  на ИМЯ .cube-файла → все выбранные до переименования Look'и битые; миграция в
  панели: `LEGACY_LUT_ALIASES` — alias-слой/донор-клип ВСЕГДА заменяется, план
  канонизируется (старые значения в _lut_plan работают). Порядок в review-HTML:
  bright | normal | dark (normal в центре, `lut_face_score.py` LUT_ORDER);
  YTCH13 план+review пропатчены (бэкапы `*_backup_pre_ytai.*`).
- Память: `reference_uxp_adjustment_layer_donor.md` (adj-donor в MEMORY.md).
- YTCH13: план утверждён (`_lut_plan.json`, поле approved), orig-WAV перенесены
  в `99_Pipeline/DJI_Audio/` (ingest пропатчен), prproj пересоздан из шаблона
  (старый: `YTCH13_Kirill_2_pre_adj_20260818.prproj`).
