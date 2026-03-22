# YTAI Quick Start

## Quick Run

```bash
source ~/YTAI/environment/.venv_transcribe/bin/activate
python ~/YTAI/scripts/run_pipeline.py "/Volumes/DISK/{project}"
```

Just point to the project folder — the pipeline does the rest:

1. **Init folders** — creates v3.0 project structure
2. **Organize files** — moves video/DJI/LUT/XML to correct dirs
3. **Extract audio** — WAV per clip + concatenated FULL_AUDIO
4. **DJI sync** — trims DJI mic recordings to match each video clip (timezone auto-detected)

By default only **Prepare** runs. Add `--all` for transcription too.

---

## Pipeline

```bash
# Default: prepare files (init + extract audio + DJI sync)
python ~/YTAI/scripts/run_pipeline.py "$PROJECT"

# Full pipeline (prepare + transcribe)
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --all --speakers 2 --language en

# Only transcribe (files already prepared)
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only transcribe --speakers 2

# Check status / dry run
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --list
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --dry-run
```

---

## Options

| Flag | Description | Example |
|------|-------------|---------|
| `--all` | Run all phases (prepare + transcribe) | `--all --speakers 2` |
| `-n, --speakers N` | Number of speakers (Pyannote) | `--speakers 2` |
| `--language XX` | Whisper language code | `--language en` |
| `-m MODEL` | Whisper model | `-m large-v3` (default) |
| `--tz-offset N` | Manual timezone for DJI sync (auto-detected if omitted) | `--tz-offset 4` |
| `--only PHASE` | Run one phase/sub-stage | `--only transcribe` |
| `--from / --to` | Range of phases | `--from transcribe` |
| `--no-pause` | Skip confirmation between phases | |
| `--force` | Re-run even if output exists | |
| `--type TYPE` | Folder template: `production` (default) or `footage` | |
| `--dry-run` | Preview without executing | |
| `--list` | Show status of each phase | |

---

## What happens

```
Phase 1/1 — Prepare files

  [1/3] Init folders       — v3.0 structure + .prproj + .gdoc
  [2/3] Extract audio      — per_clip/{clip}/{clip}_AUDIO.wav + FULL_AUDIO.wav
  [3/3] DJI sync           — Source/Audio/{clip}_TX{N}.wav (TZ auto-detected)
```

### Phases detail

| Phase | Sub-stage | Input | Output |
|-------|-----------|-------|--------|
| **Prepare** | Init folders | project folder | v3.0 directory tree + .prproj + .gdoc |
| | Organize files | stray video/DJI/LUT/XML | moved to correct dirs + per_clip |
| | Extract audio | `Source/Video/*.mp4` | `per_clip/{clip}/{clip}_AUDIO.wav` + `FULL_AUDIO.wav` |
| | DJI sync | `Source/Video/` + `DJI_Audio/*.wav` | `Source/Audio/{clip}_TX{N}.wav` |
| **Transcribe** | Transcribe | `Source/Video/*.mp4` | transcript JSON/SRT/XLSX + ingest.json |

---

## Output structure

### Source/Audio/ — DJI synced audio

DJI mic recordings trimmed to match each video clip:
```
Source/Audio/
├── RYA-FX3-0099_TX02.wav     ← DJI TX02, synced with clip 0099
├── RYA-FX3-0100_TX02.wav     ← DJI TX02, synced with clip 0100
└── ...
```
Naming: `{video_clip}_TX{N}.wav` — video clip name + DJI transmitter number.

### per_clip/ — extracted audio (for transcription)

Audio extracted from video files:
```
Transcription/per_clip/
├── RYA-FX3-0099/
│   └── RYA-FX3-0099_AUDIO.wav    ← 48kHz stereo from video
└── RYA-FX3-0100/
    └── RYA-FX3-0100_AUDIO.wav    ← 48kHz stereo from video
```

These are **different** from Source/Audio/ — per_clip audio is from the camera mic, Source/Audio is from DJI wireless mics.

---

## Transcription output

```
pipeline/                                   intermediate files
├── full_audio.wav
├── diarization.json
├── meta.json
├── speakers.json
├── clip_offsets.json
└── combined_transcript.json

Transcription/
├── {CODE}_FULL_AUDIO.wav                  concatenated audio
├── {scene}/                               per-scene transcripts
│   ├── {CODE}_{scene}_transcript.json
│   ├── {CODE}_{scene}_transcript.srt
│   ├── {CODE}_{scene}_transcript.xlsx
│   └── {CODE}_{scene}_captions.srt
├── per_clip/{clip}/
│   ├── {clip}_AUDIO.wav                   48kHz stereo (from extract_audio)
│   ├── {clip}M01.XML                      camera metadata
│   ├── {clip}_audio.wav                   16kHz mono (from transcribe)
│   ├── {clip}_transcript.json
│   ├── {clip}_transcript.srt
│   ├── {clip}_transcript.txt
│   └── {clip}_premiere_transcript.json    Premiere format

Setup/
├── {CODE}_ingest.json                     Premiere UXP plugin
├── {CODE}_Claude4_assembly.json           assembly JSON
├── {CODE}_Claude4_assembly_prompt.md      assembly prompt helper
├── {CODE}_transcript.json                 main transcript
├── {CODE}_transcript.srt                  subtitles [Speaker] text
├── {CODE}_transcript_wordlevel.srt        word-level captions
├── {CODE}_transcript.xlsx                 spreadsheet
```

---

## Manual scripts

For debugging or running individual stages:

### Extract audio
```bash
python ~/YTAI/scripts/01_prepare/0102_extract_audio/0102_extract_audio.py --project "$PROJECT"
```

### DJI audio sync
```bash
# Multi-window cross-correlation sync (auto-detects DJI files, no timezone needed)
python ~/YTAI/scripts/01_prepare/0105_multiwindow_sync_dji/0105_multiwindow_sync_dji.py --project "$PROJECT"

# Re-sync (overwrite existing)
python ~/YTAI/scripts/01_prepare/0105_multiwindow_sync_dji/0105_multiwindow_sync_dji.py --project "$PROJECT" --overwrite
```

### Transcription
```bash
python ~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py \
    --project "$PROJECT" -n 2 --language en -y
```

---

## Next step: Speaker ID

```bash
python ~/YTAI/scripts/03_speaker_id/00_process_all.py --project "$PROJECT" --no-pause
```

---

## Project structure (production — default)

```
{project}/
├── 01_Media/
│   ├── {project}.prproj                   ← Premiere project (auto-created)
│   ├── Assets/                            ← Music/, SFX/, Graphics/, Stock/, Fonts/
│   └── Source/
│       ├── {project}_Source.prproj        ← Premiere source project
│       ├── Video/                         ← camera MP4 (auto-organized)
│       ├── Audio/                         ← DJI synced WAV (auto-generated)
│       ├── pipeline/                      ← intermediate files (full_audio, diarization, etc.)
│       ├── Transcription/                 ← transcripts + per-clip hub
│       │   ├── {CODE}_FULL_AUDIO.wav
│       │   ├── {scene}/                   ← per-scene transcripts
│       │   └── per_clip/
│       │       └── {clip}/
│       │           ├── {clip}_AUDIO.wav   ← extracted audio (48kHz)
│       │           ├── {clip}M01.XML      ← camera metadata
│       │           ├── {clip}_transcript.json
│       │           └── ...
│       ├── Setup/
│       │   ├── {CODE}_ingest.json         ← Premiere UXP
│       │   ├── {CODE}_Claude4_assembly.json ← assembly JSON
│       │   └── logs/                      ← all pipeline logs
│       └── LUT/                           ← .cube from SD card (auto-organized)
├── 02_Exports/
├── 03_Shorts/
├── 04_Thumbnail/
├── YouTube/
├── 99_Pipeline/DJI_Audio/                 ← original DJI WAV (auto-organized)
└── {project}.gdoc
```

Use `--type footage` for minimal structure.

---

## Troubleshooting

### DJI sync failed
```bash
# Try with explicit timezone
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --tz-offset 4 --force
```

### No video files
```bash
cp /path/to/camera/*.MP4 "$PROJECT/01_Media/Source/Video/"
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --force
```

### Re-run with force
```bash
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --force
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --all --speakers 2 --force
```

### View logs
```bash
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --list
tail -50 "$PROJECT/01_Media/Source/Setup/logs/"*run_pipeline*.log
```

---

## Configuration

| Parameter | Value |
|-----------|-------|
| Python venv | `~/YTAI/environment/.venv_transcribe` |
| Whisper model | `large-v3` (default) |
| Scripts | `~/YTAI/scripts/` |
| Templates | `~/YTAI/YTAI_Folder_Templates/` |
| Default type | `production` (use `--type footage` for minimal) |
