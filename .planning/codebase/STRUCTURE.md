# STRUCTURE.md — Directory Layout

## Root Structure

```
YTAI/
├── scripts/                    ← All pipeline scripts
│   ├── run_pipeline.py         ← Unified CLI entry point
│   ├── README.md
│   ├── YTAI_QuickStart.md
│   ├── 00_init/                ← Project folder initialization
│   ├── 01_prepare/             ← Media prep (audio extraction, sync)
│   ├── 02_transcribe/          ← ASR + diarization
│   ├── 03_speaker_id/          ← Speaker labeling
│   ├── 04_video_analysis/      ← Scene/emotion/gesture detection
│   ├── 05_editing/             ← UXP plugin + editing helpers
│   ├── 06_thumbnails/          ← Thumbnail generation
│   ├── 07_shorts/              ← Shorts clip extraction
│   ├── 08_youtube/             ← YouTube metadata generation
│   ├── 999_extra/              ← Standalone utilities
│   └── backup/                 ← Archived old versions
├── YTAI_Folder_Templates/      ← Folder structure templates
│   └── Type2_Production/       ← Standard production project template
│       └── 01_Media/Source/
│           └── LUT/            ← Color LUT files (.cube)
└── utils/
    └── thinkific_downloader/   ← Standalone utility (unrelated to pipeline)
```

## Key Script Directories

### `scripts/01_prepare/`
```
0102_extract_audio/
│   └── 0102_extract_audio.py   ← ffmpeg-based audio extraction
0103_sync_dji_audio/
│   ├── 0103_sync_dji_audio.py  ← DJI audio sync logic
│   ├── generate_prproj.py      ← Premiere .prproj file generator
│   └── fix_dji_sync.py         ← DJI sync fixes (new)
```

### `scripts/02_transcribe/`
```
020101_transcribe/
│   ├── transcribe_project.py   ← Main transcription runner
│   └── ingest_json.py          ← JSON output formatter
```

### `scripts/03_speaker_id/`
```
00_process_all.py               ← Orchestrator
01_extract_speakers.py
02_analyze_speakers.py          ← Ollama LLM analysis
03_apply_names.py
04_split_clips.py
utils/
│   ├── formatting.py
│   ├── llm.py                  ← Ollama API wrapper
│   ├── paths.py
│   └── video.py
```

### `scripts/05_editing/`
```
0500_uxp/                       ← Adobe UXP Plugin (main deliverable)
│   ├── index.html              ← Plugin panel HTML
│   ├── index.js                ← Entry point & router
│   ├── package.json            ← Jest test config
│   ├── src/
│   │   ├── shared/
│   │   │   ├── constants.js
│   │   │   └── archiver.js
│   │   ├── ingest/
│   │   │   ├── timelineBuilder.js
│   │   │   └── transcriptImporter.js
│   │   ├── assembly/
│   │   │   └── briefParser.js
│   │   ├── review/
│   │   │   └── reviewBuilder.js
│   │   └── screens/
│   │       ├── screenBuilder.js
│   │       └── screenParser.js
│   └── tests/
│       ├── assembly/
│       ├── review/
│       ├── screens/
│       ├── shared/
│       └── mocks/
│           └── premierepro.js  ← Premiere Pro API mock
0502_assembly/
│   └── generate_assembly_captions.py
0503_review/
│   └── generate_review.py
0504_screen_cues/
│   ├── generate_screen_cues.py
│   └── generate_screen_cues_png.py
LUTs/                           ← Color LUT files for Premiere
```

## Naming Conventions

- **Script directories:** `XXYY_descriptive_name/` (e.g., `0102_extract_audio/`)
- **Stage numbers:** 2-digit stage + 2-digit substage (e.g., `0102` = stage 01, step 02)
- **Spec files:** `*_spec.md` alongside the script they document
- **Archive directories:** `Archive/` inside each stage for old versions
- **Backup:** `scripts/backup/` for legacy v1 scripts

## Project Data Folder (Runtime, Not in Repo)

```
/Volumes/Drive/ProjectName/
└── 01_Media/Source/
    ├── Video/          ← Source video files
    ├── Audio/          ← DJI audio recordings
    ├── Transcription/  ← Generated: transcript.json, .srt, ingest.json
    ├── Setup/          ← Generated: logs, config
    └── LUT/            ← Color correction LUTs
```
