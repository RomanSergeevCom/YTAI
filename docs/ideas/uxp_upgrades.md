# Текущие решения → Замена на новые API

8 мест в плагине, где текущий подход можно заменить на более надёжный/функциональный через UXP API.

---

## 1. LUT Manager → Effects API (Lumetri)

**Сейчас:** `src/ingest/lutManager.js` — копирует .cube файлы в папку `Creative/` Premiere, потом пользователь вручную применяет Lumetri.

**Проблема:** Хрупкий путь к папке Creative, зависимость от ОС, ручное применение.

**Замена:** `VideoFilterFactory` → программное добавление эффекта Lumetri Color на клип + загрузка LUT через `ComponentParam`.

**Файлы:** `src/ingest/lutManager.js` → переписать на Effects API

**Сложность:** Средняя. Нужно найти matchName для Lumetri (`AE.ADBE Lumetri`) и параметр для пути LUT.

---

## 2. Screen Cues PNG → MOGRT Templates

**Сейчас:** Python генерирует PNG (5 типов), UXP вставляет их на V2 как статичные изображения.

**Проблема:** Нельзя редактировать текст в Premiere. Любое изменение — перегенерация PNG. Нет анимации.

**Замена:** 5 шаблонов .mogrt (full_overlay, half_overlay, three_fifths, chapter_bar, lower_third) → вставка через API с параметрами (text, color).

**Файлы:** `src/screens/screenBuilder.js` → вставка MOGRT вместо PNG. Новый набор .mogrt файлов в проекте.

**Сложность:** Высокая. Нужно подготовить шаблоны в AE, затем адаптировать screenBuilder.

**Подробнее:** см. [mogrt_workflow.md](mogrt_workflow.md)

---

## 3. Review = полная пересборка → Track Item Clone

**Сейчас:** `src/review/reviewBuilder.js` — заново ищет клипы в 00_Source, применяет trim, вставляет. Дублирует логику Assembly.

**Проблема:** Дублирование кода, долгая сборка, рассинхрон если 00_Source изменился.

**Замена:** Clone track items из Ingest sequence → пометить цветом unused ranges. Или: clone из Assembly + инвертировать (complement).

**Файлы:** `src/review/reviewBuilder.js` — упростить через clone API

**Сложность:** Средняя. Нужно проверить, работает ли clone между секвенциями.

---

## 4. Screen Cues V1 = повторная сборка → Clone из Assembly

**Сейчас:** `src/screens/screenBuilder.js` — собирает V1 заново: парсит brief, ищет клипы, trim, insert. Идентично Assembly.

**Проблема:** Полное дублирование Assembly pipeline. Если Assembly обновился, Screen Cues может отстать.

**Замена:** Clone все track items из Assembly sequence → V1 Screen Cues. Потом добавить V2 (PNG/MOGRT) + markers.

**Файлы:** `src/screens/screenBuilder.js` → clone from Assembly + add overlays

**Сложность:** Средняя.

---

## 5. Маркер экспорт Python (.prproj парсинг) → UXP getMarkers()

**Сейчас:** `scripts/05_editing/0506_marker_export/export_markers_from_prproj.py` — парсит XML из .prproj файла, извлекает маркеры.

**Проблема:** Хрупкий XML парсинг, ломается при смене формата .prproj, требует закрытия проекта.

**Текущий прогресс:** В `index.js` уже есть `exportAssemblyMarkers()` — экспорт маркеров через UXP API. Работает из открытого проекта.

**Статус:** Частично решено. Python скрипт можно считать legacy, UXP версия уже работает. Убедиться что UXP покрывает все кейсы Python-скрипта.

**Файлы:** `index.js` (exportAssemblyMarkers) — проверить полноту vs Python

**Сложность:** Низкая (уже реализовано).

---

## 6. Ручной выбор проекта → Event Listener OPENED

**Сейчас:** Пользователь открывает панель → вручную выбирает папку проекта через picker.

**Проблема:** Лишний шаг каждый раз. Путь проекта можно определить из открытого .prproj.

**Замена:**
```js
ppro.EventManager.addGlobalEventListener(
  ppro.Constants.ProjectEvent.OPENED,
  () => {
    const project = ppro.Project.getActiveProject();
    const path = project.path; // путь к .prproj
    // извлечь папку проекта из пути
    autoSetProjectFolder(path);
  }
);
```

**Файлы:** `index.js` → добавить event listener при инициализации панели

**Сложность:** Низкая. Quick win.

---

## 7. SRT import → нативный Transcript API

**Сейчас:** `src/ingest/transcriptImporter.js` — импортирует .srt файлы в секвенцию.

**Проблема:** SRT формат ограничен (нет word-level timing, нет speaker diarization).

**Замена:** `createImportTextSegmentsAction()` — нативный импорт с word-level timing из Claude4_assembly.json.

**Нюанс:** Нужно проверить, поддерживает ли API формат наших JSON (words[] array с s/e timestamps). Возможно потребуется конвертация.

**Файлы:** `src/ingest/transcriptImporter.js` → адаптировать под Transcript API

**Сложность:** Средняя. Нужно изучить формат TextSegments.

---

## 8. Нет переходов → Transitions API

**Сейчас:** Все cuts между сегментами — hard cut. Переходы добавляются вручную.

**Проблема:** Рутинная работа для редактора. Типовые переходы предсказуемы (dissolve между блоками, dip-to-black для экранов).

**Замена:** Поле `"transition"` в brief JSON:
```json
{
  "segment_id": "seg_005",
  "transition_in": "dissolve",
  "transition_out": "dip_to_black",
  "transition_duration": 15  // frames
}
```

Assembly builder читает поле → `createAddVideoTransitionAction()`.

**Файлы:** `src/assembly/assemblyBuilder.js` → добавить transition logic после вставки клипов

**Сложность:** Средняя. Нужен mapping названий → matchNames переходов в Premiere.
