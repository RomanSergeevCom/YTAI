# Порядок внедрения неиспользуемых UXP API

3 волны: от quick wins к новым возможностям.

---

## Wave 1 — Quick Wins (малый риск, быстрая отдача)

Минимальные изменения в текущем коде, максимальный эффект.

### 1.1 Event Listeners → авто-определение проекта
- **Что:** При открытии .prproj → автоматически определить папку проекта и обновить UI
- **Где:** `index.js` — добавить listener при инициализации
- **Усилия:** ~1 час
- **Риск:** Нулевой — не ломает существующий flow, fallback = ручной выбор

### 1.2 Track Item Clone → упрощение Review
- **Что:** Вместо пересборки Review — clone track items из Ingest и пометить цветом
- **Где:** `src/review/reviewBuilder.js`
- **Усилия:** ~4 часа
- **Риск:** Низкий — нужно проверить clone API между секвенциями
- **Проверка:** Собрать Review через clone, сравнить с текущим результатом

### 1.3 Track Item Clone → Screen Cues V1
- **Что:** Clone Assembly → V1 Screen Cues (вместо повторной сборки)
- **Где:** `src/screens/screenBuilder.js`
- **Усилия:** ~2 часа (после 1.2 уже понятен паттерн)
- **Риск:** Низкий

---

## Wave 2 — Замена текущих решений

Переписываем существующие модули на более надёжные API.

### 2.1 Effects API → замена LUT Manager
- **Что:** Программное добавление Lumetri + загрузка .cube через ComponentParam
- **Где:** `src/ingest/lutManager.js` → переписать
- **Усилия:** ~6 часов
- **Риск:** Средний — нужно найти matchName и параметры Lumetri
- **Проверка:** Применить LUT через API, сравнить визуально с ручным

### 2.2 Transitions API → автоматические переходы
- **Что:** Добавить поле `transition` в brief → auto-apply при сборке
- **Где:** `src/assembly/assemblyBuilder.js`, brief JSON schema
- **Усилия:** ~4 часа
- **Риск:** Низкий — необязательное поле, backward compatible
- **Проверка:** Собрать Assembly с transition полями, проверить на таймлайне

### 2.3 Encoder Manager → кнопка экспорта
- **Что:** Кнопка "Export to AME" в панели с пресетом
- **Где:** `index.html` (UI) + `index.js` (handler)
- **Усилия:** ~3 часа
- **Риск:** Низкий — новая функция, не меняет существующее

### 2.4 Overwrite → Screen Cues V2
- **Что:** PNG/MOGRT на V2 через overwrite (не insert) для точного позиционирования
- **Где:** `src/screens/screenBuilder.js`
- **Усилия:** ~2 часа
- **Риск:** Низкий

---

## Wave 3 — Новые возможности

Расширение функционала плагина.

### 3.1 MOGRT → замена PNG Screen Cues
- **Что:** 5 шаблонов .mogrt вместо Python-генерации PNG
- **Где:** `src/screens/screenBuilder.js`, новая папка `assets/mogrt/`
- **Усилия:** ~2-3 дня (включая подготовку шаблонов в AE)
- **Риск:** Высокий — новый workflow, зависимость от AE
- **Подробнее:** [mogrt_workflow.md](mogrt_workflow.md)

### 3.2 Transcript API → нативный word-level импорт
- **Что:** Импорт транскрипта через нативный API (вместо SRT)
- **Где:** `src/ingest/transcriptImporter.js`
- **Усилия:** ~4 часа + исследование формата TextSegments
- **Риск:** Средний — нужно проверить совместимость формата

### 3.3 Metadata API → pipeline state
- **Что:** Хранение версии brief, статуса сборки в XMP metadata проекта
- **Где:** Новый модуль `src/shared/metadataManager.js`
- **Усилия:** ~4 часа
- **Риск:** Низкий — дополнительная функция

### 3.4 Keyframes → fade для Screen Cues
- **Что:** Auto-fade (opacity 0→100→100→0) для PNG/MOGRT overlays
- **Где:** `src/screens/screenBuilder.js`
- **Усилия:** ~3 часа
- **Риск:** Низкий — опциональное улучшение

### 3.5 Source Monitor → preview из панели
- **Что:** Кнопка preview сегмента → открывает клип в Source Monitor на нужном TC
- **Где:** `index.html` (UI) + `index.js` (handler)
- **Усилия:** ~2 часа
- **Риск:** Нулевой — read-only операция

---

## Общие требования перед началом

- [ ] Проверить доступность каждого API в Premiere Pro 25.6.0+ (текущий minVersion в manifest)
- [ ] Тестировать каждый wave на реальном проекте перед переходом к следующему
- [ ] Сохранить fallback на текущие решения до подтверждения стабильности

## Примерный таймлайн

| Wave | Усилия | Приоритет |
|---|---|---|
| Wave 1 (Events, Clone) | ~1 день | Можно начать сразу |
| Wave 2 (Effects, Transitions, Encoder) | ~2 дня | После стабилизации Wave 1 |
| Wave 3 (MOGRT, Transcript, Metadata) | ~1 неделя | По мере необходимости |
