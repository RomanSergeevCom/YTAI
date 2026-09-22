# Wall-Clock Multicam Layout — Design Document

**Status:** Draft v1.0 — Phase 0 of UXP plugin rewrite
**Author:** YTAI team
**Date:** 2026-05-31
**Test project:** YTCR03 Vlad Myshinskii
**Related:** [0500_uxp_spec.md](../../0500_uxp_spec.md) (will be updated in Phase 8)

---

## 1. Executive Summary

Этот документ описывает переписку INGEST-стадии UXP-плагина YTAI с back-to-back placement на wall-clock multicam layout. Цель — собирать в Premiere секвенции, отражающие реальную хронологию съёмочного дня: клипы стоят на своих фактических временных позициях (включая разрывы между моментами съёмки), несколько камер раскладываются параллельно на V1/V2/V3, а беспроводные лавалье-микрофоны кладутся непрерывными полосами на отдельные A-track'и.

**Ключевые решения:**
- Wall-clock offset = `(clip.creation_time - scene_t0).total_seconds()`, где `scene_t0` — наиболее раннее время начала записи среди всех клипов и TX-стрипов сцены
- Каждая камера получает свой V-track (auto-detected по `path.parent.name`: FX3, FX3A, iPhone, DJI, screen_recording)
- TX-лавалье импортируется как **полный unsplit WAV** в bin, размещается одной полосой scene-bounded в sequence с сохранением trim handles
- Старый back-to-back builder сохраняется как `linearBuilder` и автоматически используется для legacy-проектов без `layout_mode: "wallclock"` в JSON
- JSON формат bump до `v2.0`: добавлены `layout_mode`, `wall_offset`, `cam_layers`, `tx_strips`

**Затрагиваемые компоненты:**
- UXP plugin: новые модули в `src/ingest/{layout,placement,shared}/`, dispatcher в `timelineBuilder.js`
- Python pipeline: расширение `0111_inject_multicam_pairs.py`, новый скрипт `0112_collect_tx_strips.py`
- Test fixtures: 4 новых JSON-фикстуры покрывают edge cases

---

## 2. Background

### 2.1 Текущее состояние (back-to-back placement)

Текущий `timelineBuilder.js:buildMultiSceneIngest` (lines 453-817) для каждой сцены делает следующее:

1. Создаёт sequence через `project.createSequenceFromMedia(name, [firstClip])` — первый клип автоматически вставляется на time=0
2. Поддерживает `cumulativePosition` (счётчик секунд), начинающийся с `firstClipDuration` после первого клипа
3. Для каждого следующего клипа: вычисляет `tickTime = ppro.TickTime.createWithSeconds(cumulativePosition)`, вставляет через `createInsertProjectItemAction(item, tickTime, 0, 0, true)` (V1+A1), увеличивает `cumulativePosition += clip.duration`
4. Если в JSON есть `multicam.{scene}.pairs` — для каждого второго cam клипа (`camera: 2`) находит paired cam1-клип, использует его timeline-позицию, вставляет через `createOverwriteItemAction(item, time, 1, 1)` на V2+A2
5. DJI TX-аудио (per-clip нарезки из `clip.dji_audio[].path`) кладётся на A2/A3 на той же позиции что соответствующий видеоклип

**Поведенческие свойства такого подхода:**

```
Real timeline of S03 (Developer Meeting):
DJI запись:  ▓▓▓▓▓▓▓▓ ░░░░░░░░░░░░░░░░░░░░░░░░░░ ▓▓ ░░░░ ▓▓▓▓
             09:01:47                              09:36:42       09:46:02
             scene_t0                              iPhone moment   continued

В текущем плагине эти клипы становятся:
V1: [DJI_0075|DJI_0076|DJI_0077|...|DJI_0093|DJI_0094]   ← всё встык
                                                              ↑ потеряны 32 минуты пауз
V2: пусто (iPhone не помещается в pair-схему DJI)             потеряна вся iPhone-сессия
A3: [TX_per_clip][TX_per_clip][TX_per_clip]...          ← 18 кусков с дырами
```

### 2.2 Проблемы

| Проблема | Последствие |
|---|---|
| Gap'ы между видеоклипами схлопываются в 0 | Монтажёр не видит реальную хронологию дня |
| 3-я камера не поддерживается | S04 (Roman + жена) имеет FX3+FX3A+iPhone — iPhone теряется |
| TX режется per-clip | Между видеоклипами TX-полоса разорвана, теряется VO-материал из моментов когда камера выключена, но recorder писал |
| Pair-mapping требует ручной разметки в JSON | Если в `multicam.pairs` нет нужной пары — клипы V2 не помещаются |

### 2.3 Реальная съёмка YTCR03 — 7 сцен

| Сцена | Кадры | Камеры | TX-лавалье | Wall-clock диапазон |
|---|---|---|---|---|
| S01 morning_drive | 8 | FX3 + FX3A | — | ~07:30–07:45 Dubai |
| S02 amer_centre | 16 | DJI + iPhone | **TX01_MIC007** (от 12:41:05) | ~12:30–12:45 Dubai |
| S03 developer_meeting | 25 | DJI + iPhone | **TX00_MIC044** (от 13:03:10) | 13:01:47–13:46:00 Dubai |
| S04 with_wife | 47 | **FX3 + FX3A + iPhone** | TX02 (часть) | ~14:00–15:30 Dubai |
| S05 property_tour | 8 | FX3A | — | ~16:00–16:15 Dubai |
| S06 numbers_breakdown | 6 | FX3A | — | ~17:30–17:45 Dubai |
| S07 street_outro | 24 | FX3A + iPhone | TX02 (часть) | ~18:30–19:00 Dubai |

Все creation_time'ы в JSON хранятся в UTC. Dubai = UTC+4.

### 2.4 Что хочет монтажёр от wall-clock layout

```
Wall-clock layout для S03:

V1 DJI:        █23s     ░░ █5s █4s ░░░ █15s ░░░░░░ ............... ░░░ █2s █12s
V2 iPhone:                                  █6s █6s █4s █..█5s
A3 TX00:       ▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰
               0s                                                          27:31

         scene_t0 = 09:01:47Z (DJI_0075 — earliest creation_time)
         iPhone входит на ~34:40 от scene_t0
         TX00 начинается через 83s после scene_t0 (09:03:10Z)
```

**Преимущества:**
- Реальная хронология видна на таймлайне → монтажёр сразу понимает что происходило когда
- Все камеры всех сцен раскладываются единообразно (3+ камер — не проблема)
- TX непрерывной полосой → можно слышать комментарии из gap'ов между видео → больше VO-материала для монтажа
- Trim handles на TX сохранены → монтажёр может расширить полосу в любую сторону если нужно

---

## 3. Концепция Wall-Clock Layout

### 3.1 Определения

**Scene t0** — наиболее раннее `creation_time` среди ВСЕХ источников сцены (видеоклипов и TX-стрипов). Это zero-point локального таймлайна сцены.

**Wall offset (`wall_offset`)** — секунды между `clip.creation_time` и `scene_t0`. Всегда `≥ 0` (по определению `scene_t0 = min(...)`).

**V-track** — videoTrackIndex в Premiere sequence. 0=V1, 1=V2, 2=V3, и т.д.
**A-track** — audioTrackIndex. Аналогично.

**Cam layers** — упорядоченный список камер сцены, где позиция определяет V-track. Например для S04: `["FX3", "FX3A", "iPhone"]` → FX3 на V1, FX3A на V2, iPhone на V3.

### 3.2 Алгоритм placement'а (концепт)

```
для каждой сцены:
  scene_t0 = min(creation_time для clip in scene.clips ∪ tx_strips[scene])
  cam_layers = override OR auto_detect(scene.clips)  → {"FX3": 0, "FX3A": 1, "iPhone": 2}

  seq = создать пустую sequence + применить media settings (3840×2160@50fps, 48kHz)

  для каждого видеоклипа в scene.clips:
    v_idx = cam_layers[cam_from_path(clip.path)]
    offset_sec = clip.wall_offset
    overwrite(seq, clip.item, TickTime(offset_sec), v_idx, v_idx)

  для каждого tx_strip в tx_strips[scene]:
    tx_idx = position in scene's tx_strips list
    a_idx = max(cam_layers.values()) + 1 + tx_idx     ← выше всех cam audio-track'ов
    offset_sec = (tx_strip.creation_time - scene_t0).total_seconds()
    overwrite(seq, tx_strip.item, TickTime(offset_sec), -1, a_idx)  ← audio-only
```

### 3.3 Граничные случаи

| Случай | Поведение |
|---|---|
| Клип без `creation_time` в v2.0 JSON | Hard error в `parseIngest` (контракт v2.0 = обязательно) |
| Naive timestamp без TZ | Warning + assume UTC (мягкая обработка для legacy ingestов) |
| Два клипа одной камеры пересекаются во времени | Warning + later wins (overwrite). Зафиксировано в `plan.warnings[]` |
| Камера в `path.parent.name` неизвестна (нет в priority list) | Fallback в конец списка cam_layers с warning |
| TX-стрип начался раньше первого видеоклипа сцены | TX становится scene_t0; видео сдвигается соответственно |
| `wall_offset` отрицателен после нормализации | Невозможно по определению scene_t0; assertion в test |
| ProjectItem не найден в bin'е | Skip placement, log error, продолжать со следующим |
| `videoTrackIndex >= existingTrackCount` (V3 в свежей sequence) | Pre-warm placeholder на нужном vIdx → потом удалить, либо trust auto-create |

---

## 4. JSON v2.0 Format Specification

### 4.1 Полный пример

```json
{
  "version": "2.0",
  "layout_mode": "wallclock",
  "type": "ingest",
  "project_name": "YTCR03_Vlad_Myshinskii",
  "created_at": "2026-05-31T20:00:00Z",
  "media": {
    "width": 3840,
    "height": 2160,
    "fps": 50.0,
    "sample_rate": 48000,
    "timezone": "UTC"
  },
  "source_folder": "/Volumes/T9-Black-RYA/YTCR/YTCR03_Vlad_Myshinskii",
  "clips": [
    {
      "clip_id": "DJI_20260402130147_0075_D",
      "filename": "DJI_20260402130147_0075_D.MP4",
      "path": "/abs/01_Source/Video/03_developer_meeting/DJI/DJI_20260402130147_0075_D.MP4",
      "duration": 22.88,
      "creation_time": "2026-04-02T09:01:47.000000Z",
      "wall_offset": 0.0,
      "scene": "03_developer_meeting"
    },
    {
      "clip_id": "IMG_2868",
      "filename": "IMG_2868.MOV",
      "path": "/abs/01_Source/Video/03_developer_meeting/iPhone/IMG_2868.MOV",
      "duration": 6.49,
      "creation_time": "2026-04-02T09:36:27.000000Z",
      "wall_offset": 2080.0,
      "scene": "03_developer_meeting"
    }
  ],
  "cam_layers": {
    "04_with_wife": ["FX3", "FX3A", "iPhone"]
  },
  "tx_strips": {
    "02_amer_centre": [
      {
        "tx": "TX01",
        "filename": "TX01_MIC007_20260402_124105_orig.wav",
        "path": "/abs/99_Pipeline/DJI_Audio/TX01_MIC007_20260402_124105_orig.wav",
        "creation_time": "2026-04-02T08:41:05.000Z",
        "duration": 408.0,
        "sample_rate": 48000
      }
    ],
    "03_developer_meeting": [
      {
        "tx": "TX00",
        "filename": "TX00_MIC044_20260402_130310_orig.wav",
        "path": "/abs/99_Pipeline/DJI_Audio/TX00_MIC044_20260402_130310_orig.wav",
        "creation_time": "2026-04-02T09:03:10.000Z",
        "duration": 1651.6,
        "sample_rate": 48000
      }
    ]
  },
  "files": { /* ... transcript paths ... */ }
}
```

### 4.2 Field reference

| Field | Type | Required (v2.0) | Description |
|---|---|---|---|
| `version` | string | Yes | `"2.0"` для wall-clock JSON |
| `layout_mode` | string | Yes | `"wallclock"` для нового builder'а, `"linear"` или отсутствие → legacy |
| `media.fps` | float | Yes | 50.0 для YTCR03 (4K UHD 50p) |
| `media.timezone` | string | No | `"UTC"` если все creation_time приведены к UTC. Используется для валидации |
| `clips[].creation_time` | string (ISO 8601) | Yes | UTC с суффиксом `Z` или `±HH:MM`. Naive timestamp → warning |
| `clips[].wall_offset` | float (seconds) | Yes | Pre-computed в Python (`0111_inject_multicam_pairs.py`). Защита от Date-edge-cases в UXP JS |
| `clips[].scene` | string | Yes | Имя сцены, как в `01_Source/Video/{scene}/` |
| `cam_layers` | object | No | Per-scene override. Если отсутствует — auto-detect из `path.parent.name` |
| `tx_strips` | object | No | Per-scene массивы TX-полос. Required если в сцене есть TX-аудио |
| `tx_strips[scene][].creation_time` | string | Yes (если есть tx_strips) | Время начала записи TX-recorder'а |
| `tx_strips[scene][].sample_rate` | int | Yes | Должен совпадать с `media.sample_rate`, иначе hard error |

### 4.3 Back-compat (v1.x)

JSON без `layout_mode` или с `layout_mode: "linear"` обрабатывается старым `linearBuilder`. Старые поля (`offset`, `multicam.pairs`, `camera`, `dji_audio`) остаются валидными для v1.x.

---

## 5. Архитектура модулей

### 5.1 Файловая структура (after refactor)

```
~/YTAI/scripts/05_editing/0500_uxp/
├── docs/wallclock/
│   ├── WALLCLOCK_DESIGN.md          ← этот документ
│   └── WALLCLOCK_DESIGN.html        ← HTML render с ASCII-диаграммами
├── src/
│   ├── shared/                       ← Phase 1: extracted helpers
│   │   ├── projectItemFinder.js     ← findProjectItemByName
│   │   └── mediaSettings.js         ← applyMediaSettings + logSequenceSettings
│   └── ingest/
│       ├── timelineBuilder.js        ← becomes thin dispatcher (~80 lines)
│       ├── ingestLoader.js           ← + v2.0 validator
│       ├── binManager.js
│       ├── lutManager.js
│       ├── transcriptImporter.js
│       ├── layout/                   ← Phase 2: PURE modules, no UXP imports
│       │   ├── sceneLayout.js
│       │   ├── cameraResolver.js
│       │   └── txResolver.js
│       └── placement/                ← Phase 3-4: UXP-touching
│           ├── linearBuilder.js     ← старый builder verbatim
│           ├── wallClockBuilder.js  ← новый builder
│           ├── sequenceFactory.js
│           ├── clipPlacer.js
│           └── binImporter.js
└── tests/
    ├── ingest/wallclock/             ← Phase 2-3: новые тесты
    │   ├── sceneLayout.test.js
    │   ├── cameraResolver.test.js
    │   ├── txResolver.test.js
    │   └── wallClockBuilder.test.js
    └── fixtures/
        ├── wallclock_3cam_scene.json
        ├── wallclock_with_tx.json
        ├── wallclock_overlapping.json
        └── wallclock_legacy_v1.json
```

### 5.2 Зависимости между модулями

```
                    ┌─────────────────┐
                    │ timelineBuilder │ ← dispatcher
                    │   .js (~80 LoC) │
                    └────┬────┬───────┘
              ┌──────────┘    └────────────┐
              ▼                            ▼
   ┌──────────────────┐         ┌──────────────────┐
   │ linearBuilder.js │         │ wallClockBuilder │
   │ (verbatim from   │         │      .js         │
   │  old code)       │         └──────┬───────────┘
   └──────────────────┘                │
                                       │ orchestrates
                          ┌────────────┴──────────────────┐
                          ▼                                ▼
              ┌─────────────────────┐       ┌─────────────────────┐
              │ layout/  (PURE)     │       │ placement/  (UXP)   │
              │  ├ sceneLayout      │       │  ├ sequenceFactory  │
              │  ├ cameraResolver   │       │  ├ clipPlacer       │
              │  └ txResolver       │       │  └ binImporter      │
              └─────────────────────┘       └─────────┬───────────┘
                          │                            │
                          └──── computeOffsetSec ──────┤
                                                       ▼
                                              ┌──────────────┐
                                              │ shared/      │
                                              │  ├ projectItemFinder
                                              │  └ mediaSettings
                                              └──────────────┘
                                                       │
                                                       ▼
                                              ┌──────────────┐
                                              │  premierepro │ (UXP API)
                                              └──────────────┘
```

**Three layering rules** (enforced by code review):

1. `layout/*`, `cameraResolver`, `txResolver` — pure JS, **никаких imports из `premierepro`**. Тестируются Node-юнит-тестами без mock UXP.
2. `placement/*` — может импортировать `premierepro`, использует `layout/*`. Не наоборот.
3. `timelineBuilder.js` — публичный API. Re-exports `findProjectItemByName`, `applyMediaSettings` для обратной совместимости с `transcriptImporter.js:13`.

### 5.3 Dispatcher (timelineBuilder.js after refactor)

```javascript
const linearBuilder = require('./placement/linearBuilder');
const wallClockBuilder = require('./placement/wallClockBuilder');
const projectItemFinder = require('../shared/projectItemFinder');
const mediaSettings = require('../shared/mediaSettings');

function resolveLayoutMode(ingest) {
  if (ingest.layout_mode) return ingest.layout_mode;
  if (ingest.clips.every(c => c.creation_time)) return 'wallclock';
  return 'linear';
}

async function buildMultiSceneIngest(project, ingest, sourceBin, logger) {
  const mode = resolveLayoutMode(ingest);
  logger.info(`Layout mode: ${mode}`);
  if (mode === 'wallclock') {
    return wallClockBuilder.build(project, ingest, sourceBin, logger);
  }
  return linearBuilder.build(project, ingest, sourceBin, logger);
}

// Back-compat re-exports
module.exports = {
  buildMultiSceneIngest,
  buildIngestSequence: linearBuilder.buildIngestSequence, // legacy single-scene path
  findProjectItemByName: projectItemFinder.findProjectItemByName,
  applyMediaSettings: mediaSettings.applyMediaSettings,
};
```

---

## 6. Algorithm — Detailed Pseudocode

### 6.1 `sceneLayout.plan(sceneClips, txStrips, camLayersOverride)` → `Plan`

```javascript
function plan(sceneClips, txStrips = [], camLayersOverride = null) {
  // 1. Compute scene_t0
  const allSources = [
    ...sceneClips.map(c => ({ts: parseISO(c.creation_time), kind: 'clip'})),
    ...txStrips.map(t => ({ts: parseISO(t.creation_time), kind: 'tx'}))
  ];
  const scene_t0 = Math.min(...allSources.map(s => s.ts.getTime())) / 1000;

  // 2. Resolve cam layers
  const camLayers = camLayersOverride
    || cameraResolver.deriveCamLayers(sceneClips);  // {FX3: 0, FX3A: 1, iPhone: 2}

  // 3. Build placements
  const placements = [];
  const warnings = [];
  const v_track_occupancy = {}; // {vIdx: [{start, end, clipId}, ...]}

  // 3a. Video clips
  for (const clip of sceneClips) {
    const cam = parentBasename(clip.path);
    const vIdx = camLayers[cam];
    if (vIdx === undefined) {
      warnings.push({type: 'unknown_cam', cam, clipId: clip.clip_id});
      continue;
    }
    const offsetSec = clip.wall_offset !== undefined
      ? clip.wall_offset
      : (parseISO(clip.creation_time).getTime() / 1000) - scene_t0;

    // Check overlap on same vIdx
    const existing = v_track_occupancy[vIdx] || [];
    const overlap = existing.find(e =>
      offsetSec < e.end && offsetSec + clip.duration > e.start);
    if (overlap) {
      warnings.push({
        type: 'overlap', vIdx,
        loser: overlap.clipId, winner: clip.clip_id,
        note: 'later clip overwrites earlier'
      });
    }
    (v_track_occupancy[vIdx] ||= []).push({
      start: offsetSec, end: offsetSec + clip.duration, clipId: clip.clip_id
    });

    placements.push({
      kind: 'video',
      clipId: clip.clip_id,
      filename: clip.filename,
      vIdx,
      aIdx: vIdx,  // matching audio track
      offsetSec,
      duration: clip.duration
    });
  }

  // 3b. TX strips — video-bounded TrackItems (Path B++)
  //   For each TX, compute video-union intervals on ALL V-tracks,
  //   intersect with TX's [tx_offset, tx_offset+tx.duration],
  //   emit one placement per intersection with proper in-point.
  const tx_aIdx_base = Math.max(...Object.values(camLayers)) + 1;
  const videoIntervals = computeVideoUnion(placements.filter(p => p.kind === 'video'));
  // videoIntervals = [[start1, end1], [start2, end2], ...]  (sorted, non-overlapping)

  for (let i = 0; i < txStrips.length; i++) {
    const tx = txStrips[i];
    const txOffsetSec = (parseISO(tx.creation_time).getTime() / 1000) - scene_t0;
    const txEndSec = txOffsetSec + tx.duration;
    const aIdx = tx_aIdx_base + i;

    for (const [vStart, vEnd] of videoIntervals) {
      // Intersect video interval with TX time window
      const partStart = Math.max(vStart, txOffsetSec);
      const partEnd = Math.min(vEnd, txEndSec);
      if (partEnd <= partStart) continue;  // no overlap

      placements.push({
        kind: 'tx',
        txId: tx.tx,
        filename: tx.filename,
        vIdx: -1,  // audio-only
        aIdx,
        offsetSec: partStart,                         // position in sequence
        duration: partEnd - partStart,                // length of TrackItem
        sourceInPoint: partStart - txOffsetSec,       // in-point into source WAV
        sample_rate: tx.sample_rate
      });
    }
  }

  // Helper:
  // computeVideoUnion(videoPlacements) merges intervals across all V-tracks.
  // Example: [[0,10] on V1, [5,15] on V2, [20,25] on V1] → [[0,15], [20,25]]

  // 4. Sort by offsetSec (deterministic placement order)
  placements.sort((a, b) => a.offsetSec - b.offsetSec || a.vIdx - b.vIdx);

  return {
    scene_t0,
    cam_layers: camLayers,
    tx_aIdx_base,
    placements,
    warnings
  };
}
```

### 6.2 `wallClockBuilder.build(project, ingest, sourceBin, logger)`

```javascript
async function build(project, ingest, sourceBin, logger) {
  // 1. Validate v2.0 contract
  if (ingest.version !== '2.0') {
    throw new Error(`Wall-clock builder requires version 2.0, got ${ingest.version}`);
  }
  for (const clip of ingest.clips) {
    if (!clip.creation_time) {
      throw new Error(`Clip ${clip.filename} missing creation_time (required in v2.0)`);
    }
  }

  // 2. Import all media into scene bins (reuse binImporter.js)
  const sceneBins = await binImporter.importAllScenes(project, ingest, sourceBin, logger);

  // 3. Import unsplit TX WAVs into a shared TX bin
  const txBin = await binImporter.importTxStrips(project, ingest.tx_strips, sourceBin, logger);

  // 4. Group clips by scene
  const sceneNames = uniqueSorted(ingest.clips.map(c => c.scene));
  const results = [];

  for (const sceneName of sceneNames) {
    const sceneClips = ingest.clips.filter(c => c.scene === sceneName);
    const sceneTx = ingest.tx_strips?.[sceneName] || [];
    const camLayersOverride = ingest.cam_layers?.[sceneName] || null;

    // Build the placement plan (pure logic)
    const layoutPlan = sceneLayout.plan(sceneClips, sceneTx, camLayersOverride);

    // Log warnings
    for (const w of layoutPlan.warnings) {
      logger.warn(`[${sceneName}] ${w.type}: ${JSON.stringify(w)}`);
    }

    // Create empty sequence + apply media settings
    const sequenceName = `${ingest.project_name}_${sceneName}`;
    const seq = await sequenceFactory.create(
      project, sequenceName, ingest.media, logger
    );
    const seqEditor = ppro.SequenceEditor.getEditor(seq);

    // Wrap placements in a single transaction
    await project.lockedAccess(async () => {
      await project.executeTransaction((compoundAction) => {
        for (const p of layoutPlan.placements) {
          const projItem = p.kind === 'tx'
            ? findProjectItemByName(project, p.filename, txBin)
            : findProjectItemByName(project, p.filename, sceneBins[sceneName]);
          if (!projItem) {
            logger.error(`[${sceneName}] ProjectItem not found: ${p.filename}`);
            continue;
          }
          const action = clipPlacer.buildAction(seqEditor, projItem, p, logger);
          if (action) compoundAction.addAction(action);
        }
      });
    });

    results.push({ sceneName, sequence: seq, placements: layoutPlan.placements });
  }

  return {
    sequences: results,
    totalClipCount: ingest.clips.length,
    totalTxStrips: Object.values(ingest.tx_strips || {}).flat().length
  };
}
```

### 6.3 `clipPlacer.buildAction(seqEditor, projItem, placement)` — single placement

```javascript
function buildAction(seqEditor, projItem, p, logger) {
  const insertTime = ppro.TickTime.createWithSeconds(p.offsetSec);

  try {
    if (p.kind === 'video') {
      return seqEditor.createOverwriteItemAction(projItem, insertTime, p.vIdx, p.aIdx);
    } else if (p.kind === 'tx') {
      // Audio-only: vIdx=-1
      // Note: if createOverwriteItemAction doesn't support audio-only in current UXP,
      // fall back to createInsertProjectItemAction with limitShift=true
      return seqEditor.createOverwriteItemAction(projItem, insertTime, -1, p.aIdx);
    }
  } catch (err) {
    logger.error(`Failed to build action for ${p.filename} at ${p.offsetSec}s: ${err.message}`);
    return null;
  }
}
```

---

## 7. TX Path B++ Strategy (deep dive)

### 7.1 Что такое Path B++

**Эволюция:**
- **Path A** (legacy) — per-clip нарезанные WAV куски, gaps между клипами на TX-track.
- **Path B** (handoff initial) — unsplit WAV одной полосой полной длительности scene-bounded. Покрывает дыры между видеоклипами.
- **Path B+** — unsplit WAV в bin как ProjectItem, в sequence одна полоса scene-bounded с сохранением trim handles. Дыры между видеоклипами покрыты TX.
- **Path B++** (chosen, Roman 2026-05-31) — unsplit WAV в bin как **один** ProjectItem, в sequence **множество TrackItems на одном A-track'е**, по одному на каждый видеоклип (или union непрерывных видеоклипов). **TX отображается строго под видеоматериалом, gap'ы на V-tracks → gap'ы на TX-track.**

**Mental model для Path B++:**

```
SOURCE (full WAV in bin):
TX00_MIC044:  ▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰  (1651s)
              ▲ tx_creation_time = 09:03:10Z

SCENE TIMELINE (Path B++ placement):
V1 DJI:       [DJI75] ░ [76] [77] ░░░ [78] ░░░░░░░░░░░░░░░░░░░░░░░░░░ [93] ░ [94]
V2 iPhone:                                          [68] [69] [70] ░ [72]
A3 TX00:      [tx_part1] ░ [pt2] [pt3] ░░░ [pt4]   ░░░░░░░░░░░░░░░░░  [pt5] ░ [pt6]
              ↑ только под видео — gaps синхронны с gaps на V-tracks
              ↑ каждый TrackItem ссылается на тот же source, разные in-points

ProjectItem TX00 в bin: ВСЕГДА полный 1651s.
TrackItems в sequence: 6 кусков покрывающих video-union, in/out соответствуют offset'ам.
Trim handles на каждом TrackItem: можно расширить за пределы видео → услышать что было в gap'ах.
```

**Преимущества Path B++:**
- **Visual cleanness** — TX совпадает с видеоматериалом, нет «висящей» аудио-полосы в моменты когда камеры не снимали
- **VO-материал доступен** — drag trim handle любого куска расширяет в gap → монтажёр слышит что говорилось когда камера выключена
- **Один source-файл в bin'е** — нет дублирования media, footprint минимален
- **Sync precision** — все TrackItems ссылаются на тот же ProjectItem, sample-accurate выравнивание по wall-clock

### 7.2 Multi-format support (1-cam, 2-cam, 3-cam)

Wall-clock builder поддерживает **любое число камер** через auto-detect из `path.parent.name`. Конкретные форматы:

| Формат | Камеры | V-tracks | A-tracks (cam) | A-tracks (TX) | Пример сцены YTCR03 |
|---|---|---|---|---|---|
| **1-cam + TX** | 1 | V1 | A1 | A2 (TX1), опционально A3 (TX2) | гипотетически: S05 если был бы TX |
| **2-cam + TX** | 2 | V1, V2 | A1, A2 | A3 (TX1), A4 (TX2 если есть) | S02 (DJI+iPhone+TX01), S03 (DJI+iPhone+TX00) |
| **3-cam + TX** | 3 (редко) | V1, V2, V3 | A1, A2, A3 | A4 (TX) | S04 (FX3+FX3A+iPhone+TX) |
| **N-cam без TX** | 1, 2, 3 | соответственно | соответственно | — | S01, S05, S06 |

A-track индексация ВСЕГДА начинается выше cam audio-tracks: `tx_aIdx_base = max(camLayers.values()) + 1`. Это значит:
- 1-cam → TX на A2 (aIdx=1)
- 2-cam → TX1 на A3 (aIdx=2), TX2 на A4 (aIdx=3)
- 3-cam → TX1 на A4 (aIdx=3), TX2 на A5 (aIdx=4)

Detection алгоритм (`cameraResolver.deriveCamLayers`):
1. Группировать клипы по `path.parent.name` (FX3, FX3A, DJI, iPhone, screen_recording)
2. Сортировать по приоритету `["FX3", "FX3A", "DJI", "iPhone", "screen_recording"]` (matches Python `0111_inject_multicam_pairs.py:103`)
3. Mapped to vIdx 0, 1, 2, ...
4. Override через `ingest.cam_layers[scene]` если задан

### 7.3 Где живут unsplit оригиналы

Проверено для YTCR03: `/Volumes/T9-Black-RYA/YTCR/YTCR03_Vlad_Myshinskii/99_Pipeline/DJI_Audio/`:

```
TX00_MIC044_20260402_130310_orig.wav     ← S03, 27:31 (1651s)
TX01_MIC007_20260402_124105_orig.wav     ← S02, 6:48
TX02_MIC045_20260402_141609_orig.wav     ← S07 (часть)
TX02_MIC046_20260402_141658_orig.wav     ← S07 (продолжение, after battery swap)
```

Filename pattern: `TX{NN}_MIC{NNN}_{YYYYMMDD}_{HHMMSS}_orig.wav`

Datetime — в local TZ Dubai (UTC+4). Конверсия в UTC: `subtract 4 hours`.

### 7.3 Зачем pre-warm Python шаг

В текущем pipeline скрипт `0103_sync_dji_audio.py` создаёт per-clip нарезки TX, но в JSON dji_audio пуст (`0/135 clips` имеют `dji_audio` для YTCR03). Это значит:
- Path A (per-clip placement) для YTCR03 невозможен — нет данных в JSON
- Path B+ (unsplit) единственный вариант, и нам нужен новый Python шаг для генерации `tx_strips` блока

**Скрипт `0112_collect_tx_strips.py`** (Phase 5.2):
1. Сканирует `99_Pipeline/DJI_Audio/*_orig.wav`
2. Парсит datetime из filename → `creation_time_utc = local_dt - 4h` (assuming Dubai TZ; в идеале — читать из `bext.timeReference` BWF chunk через `python-soundfile` или `wavfile`)
3. Через `ffprobe -show_format` получает `duration` и `sample_rate`
4. Маппит TX → scene по времени: для каждого TX находит сцену чей `[scene_t0, scene_end]` пересекается с `[tx_start, tx_start + tx_duration]`
5. Валидирует `sample_rate == ingest.media.sample_rate`
6. Записывает `tx_strips` блок в JSON

### 7.4 Visual diagram — Premiere bin vs sequence

```
PROJECT BIN (Premiere project panel):
├── 00_Source
│   ├── 03_developer_meeting
│   │   ├── DJI_..._0075_D.MP4              ← полный 22.88s
│   │   ├── DJI_..._0076_D.MP4              ← полный 4.76s
│   │   └── ... (все 25 DJI/iPhone клипов)
│   └── TX_Strips (новый bin)
│       └── TX00_MIC044_20260402_130310_orig.wav    ← ПОЛНЫЙ 1651s
│
└── Sequences
    └── YTCR03_03_developer_meeting           ← новая sequence

SEQUENCE TIMELINE (scene-bounded TrackItems):

        0s    100   200   300   400   ...                    1651s   2655s
        │     │     │     │     │                            │       │
V1 DJI: [DJI75]  [DJI76][DJI77]  ░...gaps...░  [DJI93][DJI94]
V2 iPhone:                              [IMG_2868][IMG_2869]...
A3 TX00:[━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━]
                                                            ↑
                                                            TX TrackItem end
                                                            (TX source longer
                                                             can extend via trim handles)

ProjectItem TX00 в bin'е остаётся ПОЛНЫМ 1651s. В sequence лежит
TrackItem с in=0 (или in=83 если scene_t0 != tx_start), длиной до scene_end.
Trim handles (drag edge клипа в sequence) расширяют до полного source.
```

### 7.5 Edge case: TX начался раньше первого видео

Гипотетически, recorder включили в 13:00:00, а первый видеоклип DJI начался в 13:01:47. Тогда:
- `scene_t0 = 13:00:00` (TX становится сценой-anchor)
- DJI на `wall_offset = +1:47` (+107s)
- TX на `wall_offset = 0`, `tx_in_point = 0`

Это корректно — scene_t0 это **min across all sources**, не только клипов.

### 7.6 Edge case: TX короче чем scene

Recorder выключился в середине сцены. TX просто покрывает первые N секунд. Trim handles позволяют монтажёру понять, что дальше нет аудио (правый край TrackItem — это конец source).

### 7.7 Edge case: TX split на два файла (TX02_MIC045 + TX02_MIC046 — battery swap)

Два WAV-файла, оба попадают в одну сцену (S07). Каждый получает свой A-track? Или склеиваются в один?

**Решение:** каждый получает свой A-track, маркируется в имени (`_part1`, `_part2`). Монтажёр в Premiere может вручную склеить если хочет. Автоматическая склейка не делается — она бы потеряла информацию о разрыве записи.

---

## 8. Testing Strategy

### 8.1 Unit tests (Phase 2) — pure layout modules

`tests/ingest/wallclock/sceneLayout.test.js`:

```javascript
describe('sceneLayout.plan', () => {
  test('3-cam scene with explicit cam_layers', () => {
    const plan = sceneLayout.plan(fixtures.threeCamClips, [], ['FX3', 'FX3A', 'iPhone']);
    expect(plan.cam_layers).toEqual({FX3: 0, FX3A: 1, iPhone: 2});
    expect(plan.placements.filter(p => p.vIdx === 2)).toHaveLength(7); // 7 iPhone clips
  });

  test('scene_t0 includes TX start time', () => {
    // TX starts at 09:00:00, earliest clip at 09:01:47
    const plan = sceneLayout.plan(
      [{creation_time: '09:01:47Z', duration: 10, path: '...FX3/...'}],
      [{creation_time: '09:00:00Z', duration: 100, path: 'TX.wav'}]
    );
    expect(plan.scene_t0).toBe(/* 09:00:00 unix */);
    expect(plan.placements[0].offsetSec).toBe(107); // 1:47 = 107s
  });

  test('overlapping clips on same vIdx emit warning', () => {
    const plan = sceneLayout.plan([
      {clip_id: 'A', wall_offset: 0, duration: 30, path: '.../FX3/A.MP4'},
      {clip_id: 'B', wall_offset: 20, duration: 30, path: '.../FX3/B.MP4'},  // overlaps A
    ]);
    expect(plan.warnings.find(w => w.type === 'overlap')).toBeDefined();
  });

  test('microsecond precision preserved', () => {
    const plan = sceneLayout.plan([{creation_time: '09:01:47.123456Z', wall_offset: 1.123456, ...}]);
    expect(plan.placements[0].offsetSec).toBe(1.123456);
  });

  test('missing creation_time throws in v2.0 mode', () => {
    expect(() => sceneLayout.plan([{path: '.../FX3/A.MP4'}], [], null, {strict: true}))
      .toThrow(/missing creation_time/);
  });
});

describe('cameraResolver.deriveCamLayers', () => {
  test('auto-detect from path parent name', () => {
    const layers = cameraResolver.deriveCamLayers([
      {path: '/a/b/FX3/A.MP4'},
      {path: '/a/b/FX3A/B.MP4'},
      {path: '/a/b/iPhone/C.MOV'},
    ]);
    expect(layers).toEqual({FX3: 0, FX3A: 1, iPhone: 2});
  });

  test('explicit override wins', () => {
    const layers = cameraResolver.deriveCamLayers(clips, ['iPhone', 'FX3']);
    expect(layers).toEqual({iPhone: 0, FX3: 1});
  });

  test('unknown cam falls to end with warning', () => {
    const layers = cameraResolver.deriveCamLayers([{path: '/a/b/UnknownCam/A.MP4'}]);
    expect(layers).toHaveProperty('UnknownCam');
    expect(Object.values(layers)).toContain(0);
  });
});
```

### 8.2 Integration tests (Phase 3-4) — mock UXP

`tests/ingest/wallclock/wallClockBuilder.test.js`:

```javascript
describe('wallClockBuilder.build', () => {
  test('creates empty sequence (NOT createSequenceFromMedia)', async () => {
    const mockProject = createMockProject(/* fixture */);
    await wallClockBuilder.build(mockProject, fixtures.simpleIngest, mockBin, mockLogger);
    expect(mockProject.recorder.getCalls('createSequence')).toHaveLength(7); // 7 scenes
    expect(mockProject.recorder.getCalls('createSequenceFromMedia')).toHaveLength(0);
  });

  test('S04 3-cam scene → V1+V2+V3 placements', async () => {
    const result = await wallClockBuilder.build(mockProject, fixtures.ytcr03_s04, ...);
    const s04Calls = mockProject.recorder.getCalls('createOverwriteItemAction');
    const vIdxValues = new Set(s04Calls.map(c => c.args[2]));
    expect(vIdxValues).toContain(0); // V1 = FX3
    expect(vIdxValues).toContain(1); // V2 = FX3A
    expect(vIdxValues).toContain(2); // V3 = iPhone
  });

  test('TX strip placed on A-track above cams with vIdx=-1', async () => {
    const result = await wallClockBuilder.build(mockProject, fixtures.withTx, ...);
    const txCalls = mockProject.recorder.getCalls('createOverwriteItemAction')
      .filter(c => c.args[2] === -1); // video-track = -1 → audio-only
    expect(txCalls).toHaveLength(1);
    expect(txCalls[0].args[3]).toBeGreaterThan(2); // aIdx > max cam aIdx
  });

  test('legacy fixture (no layout_mode) routes to linearBuilder', async () => {
    await timelineBuilder.buildMultiSceneIngest(mockProject, fixtures.legacyV1, ...);
    expect(linearBuilderSpy).toHaveBeenCalled();
    expect(wallClockBuilderSpy).not.toHaveBeenCalled();
  });
});
```

### 8.3 Manual E2E (Phase 6) — live Premiere

См. секцию 9.6.

### 8.4 Regression smoke (Phase 7) — YTCR01/YTCR02

Открыть в Premiere, запустить Build Ingest, eyeball-check 5 минут на проект. Также — automated test с fixture `wallclock_legacy_v1.json` который проверяет dispatcher routing.

---

## 9. Roadmap (8 phases)

### 9.0 Phase 0 — Design documentation (этот документ)

- ✅ `WALLCLOCK_DESIGN.md` (этот файл)
- 🔲 `WALLCLOCK_DESIGN.html` (рендер с ASCII-диаграммами через простой шаблон)

### 9.1 Phase 1 — Extract shared helpers (no behavior change)

**Commit 1.1:** `src/shared/projectItemFinder.js` — move `findProjectItemByName` (timelineBuilder.js:35-75)
**Commit 1.2:** `src/shared/mediaSettings.js` — move `applyMediaSettings` + `logSequenceSettings` (lines 101-219)

Verify: existing tests green, manual reload плагина → ingest на любом старом проекте работает.

### 9.2 Phase 2 — Pure layout modules + unit tests

**Commit 2.1:** `src/ingest/layout/cameraResolver.js` + unit tests
**Commit 2.2:** `src/ingest/layout/sceneLayout.js` + unit tests
**Commit 2.3:** `src/ingest/layout/txResolver.js` + unit tests

### 9.3 Phase 3 — UXP placement modules + integration tests

**Commit 3.1:** `src/ingest/placement/sequenceFactory.js`
**Commit 3.2:** `src/ingest/placement/clipPlacer.js`
**Commit 3.3:** `src/ingest/placement/binImporter.js`
**Commit 3.4:** `src/ingest/placement/wallClockBuilder.js` + integration tests с mock SequenceEditor

### 9.4 Phase 4 — Linear builder extraction + dispatch wire

**Commit 4.1:** `src/ingest/placement/linearBuilder.js` — verbatim move + identical-trace test
**Commit 4.2:** `timelineBuilder.js` → thin dispatcher (~80 lines) + e2e test on legacy fixture

### 9.5 Phase 5 — Python pipeline

**Commit 5.1:** `0111_inject_multicam_pairs.py` — добавить `wall_offset` per clip, `layout_mode: "wallclock"`, bump version → `"2.0"`
**Commit 5.2:** `0112_collect_tx_strips.py` (new) — scan `99_Pipeline/DJI_Audio/*_orig.wav`, parse datetime from filename, validate sample_rate, emit `tx_strips`
**Commit 5.3:** Audit `0103_sync_dji_audio.py` — убедиться что `*_orig.wav` НЕ удаляются (или добавить флаг сохранения)

### 9.6 Phase 6 — Live test на YTCR03

**Backup:**
```bash
cp "/Volumes/T9-Black-RYA/YTCR/YTCR03_Vlad_Myshinskii/YTCR03_Vlad_Myshinskii.prproj" \
   "/Volumes/T9-Black-RYA/YTCR/YTCR03_Vlad_Myshinskii/YTCR03_Vlad_Myshinskii.PRE_WALLCLOCK.prproj"
```

**Run:**
1. `python3 0111_inject_multicam_pairs.py /Volumes/T9-Black-RYA/YTCR/YTCR03_Vlad_Myshinskii`
2. `python3 0112_collect_tx_strips.py /Volumes/T9-Black-RYA/YTCR/YTCR03_Vlad_Myshinskii`
3. Reload UXP плагин (Cmd+R в Developer Tool)
4. Premiere → File → Open → YTCR03.prproj → Build Ingest

**Verify (Definition of Done):**
- [ ] 7 секвенций созданы
- [ ] S03 V1=DJI и V2=iPhone с видимым gap
- [ ] S04 V1=FX3, V2=FX3A, V3=iPhone (3 камеры!)
- [ ] S02 TX01 непрерывной полосой 6:48
- [ ] S03 TX00 непрерывной полосой 27:31
- [ ] Trim handles работают на TX

**Iteration cycle:** File→Revert + плагин reload (~2 минуты).

### 9.7 Phase 7 — Regression на YTCR01/YTCR02

**Commit 7.1:** Manual smoke на YTCR01 + YTCR02
**Commit 7.2:** Automated regression test с `wallclock_legacy_v1.json` fixture

### 9.8 Phase 8 — Spec update + Telegram notify

**Commit 8.1:** Update `0500_uxp_spec.md` — добавить wall-clock как primary mode, описать v2.0 формат
**Commit 8.2:** Telegram notification через RYA или Winston bot

---

## 10. Risks & Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | `createOverwriteItemAction` с `vIdx >= existingTrackCount` НЕ auto-create'ит треки (подтверждено по Adobe docs: только `createInsertProjectItemAction` auto-creates) | Medium | High (S04 не соберётся) | **РЕШЕНО:** `sequenceFactory.ensureTracks()` материализует треки через insert-placeholder на макс. (vIdx,aIdx) + remove (`createInsertProjectItemAction` auto-creates по доке Adobe; `createAddTracksAction` в UXP DOM нет). Video-placement затем использует overwrite на уже существующих треках. Реальный V2-прецедент: `linearBuilder.js:466` (через `createSequenceFromMedia`). **Pending live-verify в Premiere** для empty-`createSequence` + V3. |
| 2 | `creation_time` без TZ suffix | Low | Medium | Strict parser в `sceneLayout.js`: refuse naive timestamps в v2.0 mode, allow только ISO `Z` или `±HH:MM`. Python `0111` нормализует к UTC при emission. |
| 3 | `ProjectItem.name` ≠ filename (Premiere добавляет ` (1)`, ` (2)`) | Low | Medium | `findProjectItemByName` уже handles stem-without-extension. Add regex `/\s*\(\d+\)$/` третий attempt. Unit test покрывает. |
| 4 | TX sample_rate mismatch с `media.sample_rate` | Low | High (silent time-stretch) | `txResolver.js` валидирует sample_rate — hard error при mismatch. Python `0112` тоже валидирует через ffprobe и refuses to emit бракованный strip. |
| 5 | Original unsplit TX WAV удалены `0103_sync_dji_audio.py` | Low (verified: для YTCR03 присутствуют) | High | Audit `0103` в Commit 5.3, добавить флаг сохранения если требуется. Fallback: если оригинала нет — `0112` склеивает per-clip куски (timestamp-precision concatenation) |
| 6 | `createSequence()` создаёт seq с дефолтными settings (HD?) | Medium | Medium | `applyMediaSettings` override. Verified pattern at timelineBuilder.js:287-293. |
| 7 | `createOverwriteItemAction` с `vIdx=-1` для audio-only не работает | Low | Medium | Fallback на `createInsertProjectItemAction(item, t, -1, aIdx, true)` — точно работает для audio-only (verified at timelineBuilder.js:410). |
| 8 | TX datetime в filename в Dubai TZ, не UTC | High (filename = local) | Low | Python `0112` явно конверсит local→UTC (Dubai = UTC+4). В идеале — читать BWF `bext.timeReference` для точности. |
| 9 | Один TX покрывает 2+ сцены (recorder писал весь день) | Medium | Medium | Маппинг TX→scene: TX дублируется в `tx_strips` каждой сцены чьё временное окно пересекается с TX. Trim handles в Premiere позволяют монтажёру обрезать к scene boundaries. |
| 10 | MD+HTML doc может разъехаться | Low | Low | HTML рендерится из MD простым шаблоном. Источник правды — MD. HTML обновляется в том же коммите. |

---

## 11. Glossary

| Term | Definition |
|---|---|
| **Scene t0** | Earliest `creation_time` across all clips and TX strips in a scene. Defines zero-point of scene's local timeline. |
| **Wall offset / `wall_offset`** | Time difference in seconds between a clip's creation_time and scene_t0. Always ≥ 0. Pre-computed in Python. |
| **V-track / V-index** | Video track in Premiere sequence. V1 = videoTrackIndex 0, V2 = 1, etc. |
| **A-track / A-index** | Audio track in Premiere sequence. A1 = audioTrackIndex 0, A2 = 1, etc. |
| **Cam layers** | Per-scene ordered list mapping camera name to V-track index. Example: `["FX3", "FX3A", "iPhone"]` → FX3 на V1, FX3A на V2, iPhone на V3. |
| **TX** | Transmitter — беспроводной передатчик микрофона-петлички (lavalier). Каждый передатчик имеет уникальный номер TX00, TX01, TX02. |
| **Lavalier (петличка)** | Маленький микрофон-клипса, носится на одежде. Подключается к беспроводному передатчику (TX). Используется для интервью когда камера далеко. |
| **BWF / `bext`** | Broadcast Wave Format — расширение WAV с метаданными. `bext.timeReference` — chunk хранящий время начала записи в samples от полуночи. Используется для точной timecode-синхронизации между recorder'ами. |
| **Recorder** | Устройство, записывающее аудио с одного или нескольких TX. В нашем pipeline — DJI Mic 2. Пишет длинные непрерывные WAV-файлы. |
| **ProjectItem** | В Premiere — entry в Project Panel (bin). Указывает на media file (полный, без обрезок). Один ProjectItem может быть инстанциирован много раз в разных sequences. |
| **TrackItem** | В Premiere — instance ProjectItem'а в sequence. Имеет in-point и out-point (sub-range полного source). Обрезка TrackItem (drag edges) не модифицирует ProjectItem. |
| **Trim handles** | Визуальные ручки на краях TrackItem в Premiere timeline. Drag расширяет/сужает видимый range без re-import. |
| **createOverwriteItemAction** | UXP API method: `seqEditor.createOverwriteItemAction(item, TickTime, vIdx, aIdx)`. Кладёт ProjectItem в sequence на указанной позиции, перезаписывая существующий материал на тех track'ах (не shift'ит other tracks). |
| **createInsertProjectItemAction** | UXP API method: `seqEditor.createInsertProjectItemAction(item, TickTime, vIdx, aIdx, limitShift)`. Вставляет с shift downstream clips. |
| **TickTime** | UXP class для точного времени в sequence. Создаётся через `ppro.TickTime.createWithSeconds(seconds)`. |
| **lockedAccess + executeTransaction** | UXP pattern для thread-safe project modification. Все placement'ы заворачиваются в `project.lockedAccess(() => project.executeTransaction(ca => { ca.addAction(...); }))`. |
| **scene_bounded** | TrackItem обрезан до scene end (правый край). Trim handles доступны → можно расширить если нужно. |
| **Path A** | TX placement strategy: per-clip pre-trimmed WAV'ы на позиции соответствующих видеоклипов. Gaps между клипами на TX-track. Sync корректен. Used in legacy mode. |
| **Path B+** | TX placement strategy: unsplit оригинальный WAV кладётся одной полосой scene-bounded с сохранением trim handles. Источник всегда полный. Used in wall-clock mode. |

---

## 12. References

### Internal

- [0500_uxp_spec.md](../../0500_uxp_spec.md) — Full UXP plugin specification (will be updated in Phase 8 to describe wall-clock mode)
- `timelineBuilder.js:35-75` — `findProjectItemByName` (will move to `src/shared/projectItemFinder.js`)
- `timelineBuilder.js:101-150` — `applyMediaSettings` (will move to `src/shared/mediaSettings.js`)
- `timelineBuilder.js:233-440` — `buildIngestSequence` (single-scene legacy path)
- `timelineBuilder.js:453-817` — `buildMultiSceneIngest` (multi-scene legacy path → moves to `linearBuilder.js`)
- `linearBuilder.js:466` — legacy V2 placement via `createOverwriteItemAction(item, t, 1, 1)` (post-refactor; `timelineBuilder.js` is now a ~95-line dispatcher with no placement code)
- `screenBuilder.js:611` — PNG overlay V2 placement (pattern reference)
- `tests/mocks/premierepro.js:373-380` — MockSequenceEditor recorder for integration tests
- `~/YTAI/scripts/01_prepare/0103_sync_dji_audio.py` — DJI WAV trimming (Phase 5.3 audit target)
- `~/YTAI/scripts/01_prepare/0111_inject_multicam_pairs.py` — Phase 5.1 target

### External (Adobe Premiere Pro UXP DOM API)

- Project Pro UXP overview: https://developer.adobe.com/premiere-pro/uxp/
- DOM API reference: https://developer.adobe.com/premiere-pro/uxp/ppro-reference/
- `Sequence` class: https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/sequence
- `SequenceEditor` class: https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/sequenceeditor
- `TickTime` class: https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/ticktime
- `VideoTrack` / `AudioTrack` classes: same `classes/` directory

---

## 12.5. Implementation Notes (as-built, 2026-05-31)

После Phase 0-5 прошла адверсариальная верификация (2 раунда workflow) которая нашла и устранила 6 блокеров. Финальная архитектура отличается от первичного дизайна в нескольких местах — зафиксировано здесь.

### Реализованные решения (заземлены на Adobe UXP DOM docs)

| Аспект | Как реализовано | Файл |
|---|---|---|
| **Dispatch** | wallclock ТОЛЬКО при `layout_mode` ИЛИ (`version=='2.0'` И все клипы имеют numeric `wall_offset`). v1.x с одним `creation_time` → linear (защита от тихого video-only). | `timelineBuilder.js:resolveLayoutMode` |
| **scene_t0 authority** | `0112` — единственный финализатор. `scene_t0 = min(clip ct ∪ mapped-TX ct)`, re-bake ВСЕХ wall_offset ≥ 0. `0111` только multicam + `cam_layers`. | `0112_collect_tx_strips.py`, `0111_inject_multicam_pairs.py` |
| **TX → scene** | Каждый TX в РОВНО одну сцену: `tx_holistic_map.json` target_scene (authority) → иначе best-overlap. Устраняет утечку TX00 в 04 (−559 leak). | `0112` |
| **TX placement (Path B++)** | 3 ОТДЕЛЬНЫЕ транзакции per slice (set→insert→clear), зеркало `clipActions.insertDjiAudio`. INSERT (vIdx=-1, limitShift=true) auto-creates A-track. Видео-bounded нарезка по union видео-интервалов. | `clipPlacer.js:placeTxStrip`, `sceneLayout.js` |
| **Video placement** | OVERWRITE (точная позиция, без сдвига), батч в одной транзакции. | `clipPlacer.js:buildVideoAction`, `wallClockBuilder.js` |
| **Track materialization** | Pre-warm: insert placeholder на макс. (vIdx,aIdx) → auto-creates треки (Adobe docs) → remove placeholder. НЕТ `createAddTracksAction` в UXP DOM. | `sequenceFactory.js:ensureTracks` |
| **TX spanning (split WAV)** | TX-стрипы группируются по label → один A-track на label. Lazy aIdx (только эмитящие TX занимают трек). | `sceneLayout.js` |
| **Negative offset guard** | `computeOffsetSec` бросает на отрицательном `wall_offset` (обе ветки). | `sceneLayout.js` |
| **Orphan scenes** | Клипы без `scene` → bucket `_all` → скипаются (no junk sequence). | `wallClockBuilder.js:build` |

### Подтверждено (mock + real-data simulation на YTCR03)

- 80/80 wall-clock unit+integration тестов зелёные; mock переписан реалистично (deferred apply, insert auto-creates треки, overwrite — нет, реальные TrackItems с захватом in/out → тесты проверяют РЕАЛЬНЫЕ длительности TX, не маскируют баг).
- Прогон `0111`+`0112` на реальном YTCR03 → v2.0, layout_mode=wallclock, **0 отрицательных offset** (134 clips + 4 tx).
- `sceneLayout.plan` на реальных данных: S03 TX00 = 9 video-bounded TrackItems на A3; S04 = V1+V2+V3 (FX3+FX3A+iPhone); TX00→03 только, TX01→02 (holistic), TX02→04 (0 эмитов, A-track не занят).

### Pending live-verify в Premiere (mock не может доказать)

1. **V3 auto-create через insert-placeholder** на empty `createSequence` — doc-grounded, но не проверено в живом PP. Главный риск S04.
2. **TX insert vIdx=-1 + limitShift=true** — зеркало proven `insertDjiAudio`, высокая уверенность.
3. **createOverwriteItemAction** ставит видео на точные wall-clock позиции без сдвига других треков.

Watch-list для live-теста — см. handoff `/tmp/HANDOFF_v2_wallclock_uxp_continue.md` (раздел Phase 6).

## 13. Changelog

| Date | Version | Changes | Author |
|---|---|---|---|
| 2026-05-31 | 1.0 | Initial design doc — Phase 0 of UXP plugin rewrite | YTAI team |
| 2026-05-31 | 1.1 | As-built notes after adversarial verification + 6 blocker fixes (dispatcher, scene_t0 unify, TX 3-txn, track pre-warm, TX→scene holistic, TX label grouping). Section 12.5 added. Stale `timelineBuilder.js:660` ref → `linearBuilder.js:466`. | Opus 4.8 session |
