# Неиспользуемые UXP API Premiere Pro

Сравнение текущего плагина `0500_uxp/` с Adobe UXP samples (`uxp-premiere-pro-samples/premiere-api`).

---

## Что используем сейчас

| Область | API |
|---|---|
| Bins | `createBinAction`, `getRootItem`, `getItems`, `FolderItem.cast` |
| Секвенции | `createSequenceFromMedia` |
| Вставка | `createInsertProjectItemAction` (pre-trim → insert → clear) |
| Тримминг | `createSetInOutPointsAction` / `createClearInOutPointsAction` |
| Цвет | `createSetColorLabelAction` |
| Маркеры | `getMarkers().createMarker()` (chapter, comment) |
| Транзакции | `executeTransaction` + `lockedAccess` |
| Файлы | UXP `localFileSystem` (JSON, PNG, SRT) |
| LUT | Копирование .cube в Creative |
| Аудио | DJI placement на треки A2/A3 |

---

## ВЫСОКИЙ приоритет — реально полезно для пайплайна

### 1. Effects API — автоматизация эффектов

**API:** `VideoFilterFactory`, `AudioFilterFactory`, `VideoComponentChain`, `AudioComponentChain`, `Component`, `ComponentParam`

**Что даёт:**
- Программное добавление Lumetri Color (заменяет копирование .cube файлов)
- Автоматические аудио-эффекты при сборке (нормализация, EQ, DeNoise)
- Чтение списка доступных эффектов (`getVideoFilterMatchNames()`)

**Пример из samples:**
```js
// Получить цепочку эффектов клипа
const chain = trackItem.getComponentChain();
const component = chain.getComponentAtIndex(0);

// Добавить эффект
const factory = ppro.VideoFilterFactory;
const effect = factory.createEffect(matchName);
trackItem.createAddEffectAction(effect);

// Прочитать/изменить параметры
const param = component.getParamForDisplayName("Opacity");
param.createSetValueAction(50); // 50%
```

**Применение у нас:** LUT Manager → прямое применение Lumetri через API.

---

### 2. Keyframes — анимация параметров

**API:** `createKeyframe()`, `getKeyframePtr()`, `createAddKeyframeAction()`, `createSetInterpolationAtKeyframeAction()`

**Что даёт:**
- Fade-in/fade-out opacity для Screen Cues overlays
- Анимация позиции/масштаба
- Интерполяция: Linear, Hold, Bezier

**Пример:**
```js
const param = component.getParamForDisplayName("Opacity");
param.createSetTimeVaryingAction(true); // включить анимацию

const kf = ppro.Keyframe.createKeyframe();
kf.setValue(0);   // начальное значение
kf.setTime(startTime);
param.createAddKeyframeAction(kf);

const kf2 = ppro.Keyframe.createKeyframe();
kf2.setValue(100);
kf2.setTime(endTime);
param.createAddKeyframeAction(kf2);

param.createSetInterpolationAtKeyframeAction(kf, ppro.Constants.InterpolationMode.LINEAR);
```

**Применение:** Плавные переходы для PNG-оверлеев, auto-fade на screen cues.

---

### 3. Transitions API — автоматические переходы

**API:** `getVideoTransitionMatchNames()`, `createAddVideoTransitionAction()`, `createRemoveVideoTransitionAction()`, `AddTransitionOptions`

**Что даёт:**
- Cross-dissolve между блоками Assembly
- Dip-to-black для screen cues
- Задаётся в brief JSON → применяется при сборке

**Пример:**
```js
// Получить список доступных переходов
const transitions = ppro.getVideoTransitionMatchNames();

// Добавить переход в начало клипа
const options = new ppro.AddTransitionOptions();
options.setApplyToStart(true);
trackItem.createAddVideoTransitionAction(matchName, options);

// Добавить переход в конец
trackItem.createAddVideoTransitionAction(matchName); // default = end
```

**Применение:** `"transition": "dissolve"` в brief JSON → auto-apply.

---

### 4. Event Listeners — реактивный плагин

**API:** `ppro.EventManager.addGlobalEventListener()`

**События:**
- `Project.OPENED` / `Project.ACTIVATED` — проект открыт
- `Project.DIRTY` — проект изменён (напоминание сохранить)
- `Sequence.ACTIVATED` — смена активной секвенции
- `Sequence.SELECTION_CHANGED` — выделение клипа
- `EFFECT_DROP_COMPLETE` — эффект применён
- `TRACKITEM` snap, `PLAYHEAD_TRACKITEM` snap

**Пример:**
```js
ppro.EventManager.addGlobalEventListener(
  ppro.Constants.ProjectEvent.OPENED,
  (event) => {
    const project = ppro.Project.getActiveProject();
    autoDetectProjectFolder(project);
    updateUI();
  }
);

ppro.EventManager.addGlobalEventListener(
  ppro.Constants.SequenceEvent.ACTIVATED,
  (event) => {
    updateActiveSequenceInfo();
  }
);
```

**Применение:** Авто-определение проекта при открытии .prproj (вместо ручного выбора папки).

---

### 5. Encoder Manager — экспорт через AME

**API:** `EncoderManager.getManager()`, `exportSequence()`, `encodeProjectItem()`, `encodeFile()`, `exportSequenceFrame()`

**Что даёт:**
- Кнопка "Export to AME" прямо из панели
- Экспорт текущего кадра как PNG (превью/тамбнейлы)
- Batch-экспорт всех секвенций
- Проверка `isAMEInstalled`

**Пример:**
```js
const encoder = ppro.EncoderManager.getManager();

// Экспорт кадра
await ppro.Exporter.exportSequenceFrame(
  sequence, outputPath, 600, 500 // width, height
);

// Экспорт в AME
await encoder.exportSequence(
  sequence, outputPath, presetPath // .epr preset
);

// Статус
encoder.addEventListener('progress', (e) => updateProgress(e));
encoder.addEventListener('complete', (e) => onExportDone(e));
```

**Применение:** Assembly → кнопка → AME рендерит с нужным пресетом.

---

### 6. Overwrite / Insert / Ripple Delete

**API:** Sequence Editor operations

**Что даёт:**
- **Overwrite** — вставка поверх (не сдвигает таймлайн), идеально для Screen Cues V2
- **Insert** — вставка со сдвигом
- **Ripple Delete** — удаление с автосхлопыванием
- Более надёжная сборка без зависимости от порядка

**Применение:** Screen Cues V2 PNG → overwrite вместо insert. Обновление brief → ripple delete старых сегментов.

---

### 7. Track Item Clone

**API:** Clone track items with time offset

**Что даёт:**
- Клонирование клипов между треками/секвенциями
- Сохранение всех свойств (эффекты, цвет, trim)

**Применение:**
- Review → clone complement из Ingest (вместо пересборки)
- Screen Cues V1 → clone из Assembly (вместо повторной сборки)

---

## СРЕДНИЙ приоритет — полезно, но не критично

### 8. Transcript API (нативный)

**API:** `createImportTextSegmentsAction()`, `importFromJSON()`, `exportToJSON()`

Нативный импорт транскрипта в Premiere (word-level timing). Потенциально заменяет текущий SRT import через `transcriptImporter.js`.

### 9. MOGRT — Motion Graphics Templates

**API:** Insert MOGRT files, set parameters

Вставка готовых .mogrt шаблонов (lower thirds, title cards) с программной настройкой текста/цвета. Потенциально заменяет PNG Screen Cues → см. [mogrt_workflow.md](mogrt_workflow.md).

### 10. Metadata API

**API:** `getProjectMetadata()`, `setProjectMetadata()`, `addPropertiesToMetadataSchema()`, XMP

Хранение pipeline state в metadata проекта (версия brief, статус, timestamps). Кастомные поля на клипах (speaker, block, use/skip) → видны в Project Panel.

### 11. Source Monitor Control

**API:** `openProjectItem()`, `play()`, `getPosition()`

Preview конкретного сегмента из панели (кнопка "play segment"). Навигация к проблемному месту.

### 12. Sequence Properties (persistent)

**API:** `getProperties()`, `createSetValueAction()`, `PropertyType.PERSISTENT` / `NON_PERSISTENT`

Сохранение метаданных секвенции (pipeline version, brief hash). Проверка "эта секвенция уже собрана из brief v3?".

---

## НЕ нужно для нашего workflow

| API | Почему не нужно |
|---|---|
| OAuth / external services | Нет внешних сервисов в пайплайне |
| Smart bins | Структура проекта жёсткая |
| Proxy workflow | Работаем с оригиналами |
| Production API | Один проект за раз |
| Scratch disk settings | Настраивается один раз вручную |
| FCP XML / AAF / OTIO export | Нет обмена с другими NLE |
| App Preferences | Нет необходимости менять глобальные настройки |
| Import sequences from other projects | Каждый проект самостоятельный |
| Import AE compositions | AE используется отдельно |
