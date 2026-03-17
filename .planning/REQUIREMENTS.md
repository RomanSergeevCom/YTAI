# Requirements: YTAI — Multi-Scene Nested Projects

**Defined:** 2026-03-17
**Milestone:** v1.0
**Core Value:** Every word in the transcript has a timecode — the editor selects quotes, the timeline builds itself.

---

## v1 Requirements

### ORGANIZE — Инициализация структуры папок

- [x] **ORG-01**: Скрипт детектирует nested-проект по наличию TX01/ и/или TX02/ папок в корне проекта
- [x] **ORG-02**: MP4/MOV-клипы каждой сцены перемещаются в `01_Media/Source/Video/{scene}/`; структура сцен-подпапок сохраняется
- [x] **ORG-03**: TX01/, TX02/, TX02_2/ (и любые TX\d+_\d*/ варианты) — все WAV мёрджатся flat в `99_Pipeline/DJI_Audio/`; имена файлов сохраняются
- [x] **ORG-04**: Sony XML-сайдкары (`C5089M01.XML`) перемещаются в `01_Media/Source/Transcription/per_clip/{scene}/{clip}/` — рядом с аудио, не мешают видео
- [x] **ORG-05**: Отсутствие XML-сайдкаров не блокирует pipeline (graceful, как сейчас)
- [x] **ORG-06**: Создаётся стандартная v3.0 структура папок (шаблон `YTAI_Folder_Templates/Type2_Production`)

**Целевая структура после ORG:**
```
ProjectName/
├── 01_Media/
│   └── Source/
│       ├── Video/
│       │   ├── apartment/      ← scene subfolder preserved
│       │   │   ├── C5210.MP4
│       │   │   └── C5211.MP4 ...
│       │   ├── volleyball/
│       │   └── drive_home/ ...
│       ├── Audio/
│       │   ├── apartment/      ← {clip}_TX01.wav, {clip}_TX02.wav (synced, after AUD)
│       │   └── {scene}/ ...
│       ├── Transcription/
│       │   └── per_clip/       ← XML + audio будут здесь
│       ├── Setup/logs/
│       └── LUT/
└── 99_Pipeline/
    └── DJI_Audio/              ← TX01_MIC*.wav, TX02_MIC*.wav (flat)
        ├── TX01_MIC001_20260228_102211_orig.wav
        ├── TX02_MIC024_20260228_100209_orig.wav
        └── ...
```

---

### AUDIO — Извлечение и синхронизация аудио

- [x] **AUD-01**: Для каждого клипа извлекается `Transcription/per_clip/{scene}/{clip}/{clip}_AUDIO.wav` (ffmpeg, 48kHz stereo) — аналогично `0102_extract_audio`, добавляется сцена-подпапка
- [x] **AUD-02**: Для каждой сцены клипы конкатенируются во временный `{scene}_FULL_AUDIO.wav` — используется как reference для DJI sync
- [x] **AUD-03**: Для каждого клипа перебираются **все** TX01 WAV из `99_Pipeline/DJI_Audio/` как кандидаты; выбирается лучший по waveform cross-correlation с clip-audio
- [x] **AUD-04**: Найденный TX01 WAV обрезается с точным offset → `01_Media/Source/Audio/{scene}/{clip}_TX01.wav`
- [x] **AUD-05**: Аналогично для TX02 → `01_Media/Source/Audio/{scene}/{clip}_TX02.wav`
- [x] **AUD-06**: Скрипт репортует точность sync для каждого клипа: delta в фреймах (target: 0F, допустимо: ≤1F)
- [x] **AUD-07**: ingest.json каждой сцены: A1=camera embed, A2=TX01_SYNC, A3=TX02_SYNC
- [ ] **AUD-08**: Глобальный `{project}_ingest.json` в Setup/ агрегирует все per-scene ingest.json в список `scenes[]`

---

### TRANSCRIBE — Транскрипция

- [ ] **TRN-01**: Существующий `transcribe_project.py` запускается per-scene или с `01_Media/Source/Video/` — находит сцены как подпапки; внутренняя логика (Whisper, Pyannote, ingest JSON) без изменений
- [ ] **TRN-02**: Каждая сцена транскрибируется отдельно → `01_Media/Source/Transcription/{scene}_transcript.json` с word-level таймкодами
- [ ] **TRN-03**: Все сцены объединяются → `01_Media/Source/Transcription/merged_transcript.json`; каждое слово содержит `scene_id` и локальный таймкод внутри сцены

---

### UXP — Плагин Premiere Pro (0500_uxp)

- [ ] **UXP-01**: UXP загружает multi-scene ingest из общего `{project}_ingest.json` (список сцен + пути к клипам и аудио)
- [ ] **UXP-02**: Для каждой сцены создаётся отдельный Premiere-таймлайн с именем `{project_code}_{scene}_1_Ingest`; SRT для сцены импортируется в `02_Transcripts/` (caption добавляется вручную)
- [ ] **UXP-03**: UXP читает `merged_transcript.json` для построения cross-scene брифа (0501_brief)
- [ ] **UXP-04**: Word-based резка в ASSEMBLY (0502_assembly) работает по всем сценам: выбрал слово → таймкод → нужная сцена

---

### PIPELINE — Интеграция

- [ ] **PIPE-01**: `run_pipeline.py` автодетектирует nested-режим (есть TX01/ папка → nested) и запускает нужные скрипты с нужными аргументами
- [ ] **PIPE-02**: Flat-проекты работают без изменений (обратная совместимость гарантирована)
- [ ] **PIPE-03**: В dry-run режиме выводится план: какие сцены найдены, сколько клипов, какие TX-папки

---

## v2 Requirements (deferred)

- **MULTI-CAM**: Поддержка GoPro + Sony FX3 в одной сцене (al_qudra_lake) — синхронизация разных камер
- **SPEAKER-ID**: Speaker ID pipeline (`03_speaker_id`) адаптирован для nested-проектов
- **SHORTS**: Поддержка `07_shorts` для nested (поиск моментов по all scenes)

---

## Out of Scope

| Feature | Reason |
|---|---|
| Timecode-based TX sync | TX WAV не содержит записанного TC; waveform correlation точнее |
| Автоматический матчинг TX к сцене по timestamp | TX пишет непрерывно, один WAV перекрывает несколько сцен — нужна correlation |
| Cloud sync / remote rendering | Локальный pipeline |
| Windows/Linux | macOS Apple Silicon only |

---

## Traceability

| Requirement | Phase | Status |
|---|---|---|
| ORG-01 | Phase 1 — Organize | Complete |
| ORG-02 | Phase 1 — Organize | Complete |
| ORG-03 | Phase 1 — Organize | Complete |
| ORG-04 | Phase 1 — Organize | Complete |
| ORG-05 | Phase 1 — Organize | Complete |
| ORG-06 | Phase 1 — Organize | Complete |
| AUD-01 | Phase 2 — Audio Sync | Complete |
| AUD-02 | Phase 2 — Audio Sync | Complete |
| AUD-03 | Phase 2 — Audio Sync | Complete |
| AUD-04 | Phase 2 — Audio Sync | Complete |
| AUD-05 | Phase 2 — Audio Sync | Complete |
| AUD-06 | Phase 2 — Audio Sync | Complete |
| AUD-07 | Phase 2 — Audio Sync | Complete |
| AUD-08 | Phase 2 — Audio Sync | Complete |
| TRN-01 | Phase 3 — Transcribe | Pending |
| TRN-02 | Phase 3 — Transcribe | Pending |
| TRN-03 | Phase 3 — Transcribe | Pending |
| UXP-01 | Phase 4 — UXP Plugin | Pending |
| UXP-02 | Phase 4 — UXP Plugin | Pending |
| UXP-03 | Phase 4 — UXP Plugin | Pending |
| UXP-04 | Phase 4 — UXP Plugin | Pending |
| PIPE-01 | Phase 5 — Pipeline Integration | Pending |
| PIPE-02 | Phase 5 — Pipeline Integration | Pending |
| PIPE-03 | Phase 5 — Pipeline Integration | Pending |

**Coverage:**
- v1 requirements: 24 total
- Mapped to phases: 23
- Unmapped: 0 ✓

---

## Reference Project

`/Volumes/RYA T7 Black/YTCR_1_Arty_Dzis`
- 7 сцен: volleyball (114), dubai_driving (51), desert_drive (44), apartment (40), al_qudra_lake (34+GoPro), al_qudra_lake_story (35), drive_home (7)
- TX01/ (3 WAV, Feb 28), TX02/ (9 WAV, Feb 28), TX02_2/ (WAV, Mar 2)
- Итого: 325 клипов Sony FX3 + GoPro в al_qudra_lake

---
*Requirements defined: 2026-03-17*
*Last updated: 2026-03-17 — 01-02 complete: ORG-02, ORG-03, ORG-04 marked complete*
