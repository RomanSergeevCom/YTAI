# UXP-стадия «Preset Cutter» — спека (draft 2026-08-03)

Цель: вырезать из финального проекта Premiere переиспользуемые графические приёмы
(тайтл-карты, тайм-оверлеи, графики, счётчики — всё, что НЕ AE Linked Comp) в
самодостаточные мини-проекты-пресеты для будущих видео.

Контекст-прецедент: YTCR01. AE-экраны уже упакованы без UXP
(`/Volumes/T9-Black-RYA/YTCR/YTCR_StyleLibrary/`, aep + (Footage) + прокси-плейсхолдеры).
Premiere-native приёмы ждут эту стадию. Вход уже генерится пайплайном:
`YTCR_StyleLibrary/presets_premiere.json`.

## Вход

`presets_premiere.json` — массив:
```json
{ "name": "clock-overlay_845pm", "tc": "09:28", "screen_type": "clock-overlay",
  "clips": ["Nested Sequence 83", "..."] }
```
TC указаны по финальному рендеру; допуск ±1s. Секвенция-мастер задаётся в UI стадии
(для YTCR01 = «сборка_Claude_V10 Copy 01»).

## Что делает стадия (в СУЩЕСТВУЮЩЕЙ панели ytai, новая вкладка — по образцу parts-стадии)

1. Читает presets_premiere.json (файл-пикер или из 00_Setup).
2. Для каждого пресета:
   - находит диапазон: tc±0.5s → берёт out самого длинного графического клипа в точке
     (или явные tc_in/tc_out из json, если проставлены);
   - создаёт субсеквенцию мастер-секвенции на диапазон (как parts: `ytai-part-v1`-паттерн,
     Sequence.createSubsequence, имя `PRESET__{name}`);
   - складывает в bin `_Presets`;
   - удалять из субсеквенции нижние дорожки с интервью НЕ надо — это и есть
     placeholder-слой, который в новом проекте заменяется.
3. Отчёт в панели: список созданных субсеквенций + чек-лист ручного шага.

## Ручной шаг (Premiere не даёт API)

Для каждой `PRESET__*` секвенции: выделить → File → Export → Selection as Premiere
Project… → в папку `YTCR_StyleLibrary/premiere/{name}/` → затем Project Manager
(Collect Files / Consolidate & Transcode) для локализации медиа. Панель показывает
инструкцию и открывает целевую папку.

## Грабли (из памяти проекта)

- Sequence API работает только с АКТИВНОЙ секвенцией (uxp-seq-quirks) — активировать
  мастер перед резкой.
- Media Analyzer не видит nested seq (nested-blind) — состав nested резолвим заранее
  оффлайн-парсом prproj (скрипт `scratchpad/graphics_map.py` → перенести в
  `scripts/05_editing/0500_uxp/tools/` при имплементации).
- Insert-order: при вставке на один tc — реверс (insert-order).

## Definition of done

- Из presets_premiere.json YTCR01 собраны субсеквенции всех premiere-native экранов;
- после ручного экспорта каждый мини-prproj открывается на чистой машине, медиа
  локализованы, интервью-слой заменяется на новый футедж без ошибок.
