# Assembly brief + Parts: контракты для премонтажа (проверено по коду 2026-07-12)

Продолжение конвейера word-sync: синк → Preedit-док → **премонтаж**.
Полный ранбук: `WORDSYNC_RUNBOOK.md`. Тулинг генерации: `scripts/999_extra/ytuvi_preedit/`.

## 1. Assembly brief (одна дорожка + DeletedScene)

Файл: `{PROJECT}/00_Setup/02_Assembly/{CODE}_Assembly_v{N}_in.json` — панель
авто-берёт максимальную v{N} (index.js:541). Format A: `{segments:[], project:{}}`.

Per-segment (briefParser.js:89):
- ОБЯЗАТЕЛЬНО: `source_file` (имя файла с расширением — резолв ProjectItem ТОЛЬКО
  по имени из бина `00_Source`; INGEST должен быть уже отработан), `tc_in`/`tc_out`
  ("MM:SS.mmm" | "HH:MM:SS.mmm" | **голые секунды числом** — точный трим без
  frame-snap), `use` ("TRUE"/"FALSE" СТРОКОЙ — незаданный use выпадает из сборки!).
- `block` int (99 = cut), `block_name`, `segment_name`, `speaker`, `color`
  (Green/Blue/Cyan/Yellow/Orange/Red/Magenta/Purple), `priority` (2=alt, 9=cut),
  `is_chapter` "TRUE" на первом сегменте блока → chapter-маркер,
  `transcript` ≤500 (маркер-заметка), `broll_note` ≤200, `notes` ≤500.
- Несколько исходников в одном брифе — ДА (сегменты свободно чередуют клипы).

project: `project_name` (→ {CODE} и имя секвенции `{code}_2_Assembly`), `fps`,
`width/height/sample_rate`, `create_assembly_sequence/chapter_markers`,
`include_unused: true`.

Поведение: USE=TRUE && block!=99 → секвенция `_2_Assembly` (V1 + звук камеры A1);
всё остальное + непокрытые остатки клипов → авто-`{CODE}_3_DeletedScene[_scene]`
(комплемент по длительностям из `{CODE}_1_Ingest`; use=FALSE куски + Purple-gaps).
Отдельный WAV: только механизм `{имя_видео}_TX{nn}` (те же in/out, 1:1 синхрон) —
для рекордера со смещением НЕ подходит → мультикам-часть (ниже).

## 2. Мультикам-премонтаж (4 камеры + рекордер) — через Parts

Assembly одноканален by design. Мультикам-версия того же ката = **ytai-part-v1**:
`{PROJECT}/00_Setup/02_Assembly/parts/{CODE}_part_{Name}.json`
(панель Parts → Load: авто-подхват свежайшего `_part_*.json`; index.js:1590).

```json
{"schema": "ytai-part-v1",
 "part": {"code": "YTUVI05", "name": "Premontage_MCAM",
          "sequence_name": "YTUVI05_2_Assembly_MCAM_v1",
          "seed_clip": "CAM_3_2190.MP4", "fps": 25.0},
 "segments": [{
    "source_file": "CAM_1_2182.MP4",
    "source_in_sec": 12.34, "source_out_sec": 45.67,   // точные секунды
    "timeline_in_sec": 0.0,                             // АБСОЛЮТНАЯ позиция
    "track": "V2", "audio_track": "A2", "keep_audio": true,
    "color": "Cyan", "segment_name": "seg_1_1 V2"}]}
```

- `track`/`audio_track` парсятся по числу (V4/A5 валидны); ensureTracks создаёт
  сколько нужно, аудио-максимум считается по `audio_track` ОТДЕЛЬНО от видео
  (partsBuilder ≥1.6.0 / панель ≥ v2.2.8; в 1.5.0 просился только A=V-max и REC-A5
  улетал бы в insert-fallback с limitShift=false = сдвиг всех дорожек).
- partsBuilder ≥1.6.1 (панель ≥ v2.2.9): сид зачищается ДО ensureTracks async-паттерном
  getTrackItems — иначе пре-варм толкал сид вправо и оставлял полнометражные «хвосты»
  после ката (наблюдалось на live Build YTUVI05 MCAM v1).
- ⚠️ Premiere 25.6 UXP: `TrackItem.createRemoveAction` НЕ СУЩЕСТВУЕТ, а
  `TrackItemSelection.createEmptySelection(callback)` требует CALLBACK (no-arg →
  «Not Enough Parameters»). Единственное удаление = `createRemoveItemsAction(sel,
  ripple, mediaType, shiftOverlapping)` с callback-селекшеном — хелпер
  `sequenceFactory.createEmptySelectionCompat`. partsBuilder ≥1.6.2 (панель ≥2.2.10)
  дополнительно триммит сид/плейсхолдер до 1 кадра (неудалённый огрызок = пылинка
  на TL 0 под контентом) и не пре-вармит аудио-only дорожки (insert auto-create).
- `make_mcam_part.py --deleted` — та же мультикам-раскладка для USE=FALSE (вырезанное):
  `_rec5` у них нет, маппинг tc→REC через покрытие V1 → `{code}_3_DeletedScene_MCAM_v1`.
- Несколько секвенций одним Build: обернуть части в `ytai-parts-bundle-v1`
  (`{schema, parts:[{part,segments},…]}`); Load авто-берёт СВЕЖАЙШИЙ `_part_*.json`
  по mtime — bundle генерировать последним.
- Аудио-only файл (WAV рекордера): `track` инертен, кладётся по `audio_track`
  проверенным TX-паттерном (insert vIdx=-1, limitShift=true — как clipPlacer.placeTx;
  restrict: восходящий `timeline_in`, что sort билдера и гарантирует).
- `part.seed_clip` ДОЛЖЕН существовать в проекте (иначе fallback на первый
  видео-сегмент — не фатально, но генератор ≥2026-07-12 пишет валидный).
- Генератор: `scripts/999_extra/ytuvi_preedit/make_mcam_part.py` — берёт брифовые
  USE=TRUE сегменты (`_rec5`-диапазоны), покрытия камер из wordsync_result,
  раскладывает пересечения по дорожкам на те же compressed-позиции + REC на A5.
- Мастер «всё вместе» из нескольких частей: `make_master_part.py` (там же) —
  конкатенация part-JSONов со сдвигом `timeline_in` (+chapter-маркеры частей,
  `part.markers=true`); строится тем же Build Part, БЕЗ нестинга секвенций.

## 3. Порядок запуска (Premiere)

1. Открыт {PROJECT}.prproj, INGEST отработан (бин `00_Source` со всеми клипами).
2. Assembly → Refresh → Build Assembly (v{N} авто) → `_2_Assembly` + `_3_DeletedScene`.
3. Parts → Load → Build Part → `_2_Assembly_MCAM_v1` (4V + 4A камер + A5 REC).

Генерация брифа из Preedit-анализа: `make_assembly_brief.py` (там же): USE=TRUE =
выбранный дубль каждого блока (span_tokens → слова s/e, smart padding 0.3с, стыки
соседних блоков в непрерывном дубле склеиваются SNAP<1.5с), USE=FALSE block=99 =
комплемент покрытия камеры (дубли/паузы) с транскриптом в маркере.
