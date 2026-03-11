# YTAI Quick Start

## Quick Run (single command)

```bash
source ~/YTAI/environment/.venv_transcribe/bin/activate
python ~/YTAI/scripts/run_pipeline.py "/Volumes/RYA Blue/{project}" --speakers 2
```

This runs the full pipeline: init → extract audio → transcribe.

---

## Setup

### 1. Activate environment
```bash
source ~/YTAI/environment/.venv_transcribe/bin/activate
```

### 2. Set project path
```bash
export PROJECT="/Volumes/RYA Blue/{project}"
```

---

## Pipeline (automatic)

```bash
# Full pipeline — 2 speakers (interview)
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --speakers 2

# With DJI wireless audio sync
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --speakers 2 --tz-offset 4

# Check what's done
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --list

# Dry run (show what would happen)
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --dry-run
```

### Pipeline stages

| # | Stage | What it does |
|---|-------|-------------|
| 0 | `init` | Create v3.0 folder structure (auto if missing) |
| 1 | `extract_audio` | Extract WAV from each clip + concat FULL_AUDIO.wav |
| 2 | `sync_dji` | Sync DJI wireless audio to clips (optional, needs `--tz-offset`) |
| 3 | `transcribe` | Whisper transcription + Pyannote speaker diarization |

### Options

| Flag | Description |
|------|-------------|
| `--speakers N` | Number of speakers for Pyannote (e.g. 2 for interview) |
| `--language XX` | Language for Whisper (default: auto-detect) |
| `--tz-offset N` | Timezone offset for DJI sync (e.g. 4 for Dubai, 3 for Moscow) |
| `--only STAGE` | Run only one stage |
| `--from STAGE` | Start from this stage |
| `--to STAGE` | Stop after this stage |
| `--no-pause` | Don't pause between stages |
| `--force` | Re-run even if output exists |
| `--type footage\|production` | Folder type for init (default: footage) |

---

## Pipeline (step-by-step)

For debugging or running individual stages:

### Stage 1: Extract audio
```bash
python ~/YTAI/scripts/01_prepare/02_extract_audio.py --project "$PROJECT"
```

Extracts audio from each video clip, concatenates into FULL_AUDIO.wav.

**Output:**
```
01_Media/Source/Transcription/
├── {clip}_AUDIO.wav                    (per-clip audio)
└── {project}_FULL_AUDIO.wav            (concatenated for transcription)
```

**Check:**
```bash
ls -la "$PROJECT/01_Media/Source/Transcription/"*FULL_AUDIO.wav
```

---

### Stage 2: DJI audio sync (optional)
```bash
python ~/YTAI/scripts/01_prepare/03_sync_dji_audio.py --project "$PROJECT" --tz-offset 4
```

Syncs DJI wireless mic audio to camera clips by matching timestamps.

**Output:**
```
01_Media/Source/Audio/
├── {clip}_TX02.wav
└── ...
```

---

### Stage 3: Transcription
```bash
python ~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py --project "$PROJECT" -n 2
```

**Parameters:**
- `-n 2` — number of speakers (2 for interview)
- `-m large-v3` — Whisper model (default)
- `--language en` — language (default: auto-detect)

**Time:** ~15-25 min per hour of audio

**Output:**
```
01_Media/Source/Transcription/
├── {project}_transcript.json           (main transcript)
├── {project}_transcript.srt            (subtitles)
├── {project}_transcript.xlsx           (spreadsheet)
├── per_clip/
│   └── {clip}/
│       ├── {clip}_transcript.json
│       ├── {clip}_transcript.srt
│       └── {clip}_premiere_transcript.json

01_Media/Source/Setup/
└── {project}_ingest.json               (Premiere UXP)
```

**Check:**
```bash
ls "$PROJECT/01_Media/Source/Transcription/"*_transcript*
grep -o '"SPEAKER_[0-9]*"' "$PROJECT/01_Media/Source/Transcription/"*_transcript.json | sort -u
```

---

## Next step: Speaker ID

Speaker identification is done via **Claude Desktop project** (recommended)
or manually with scripts:

```bash
python ~/YTAI/scripts/03_speaker_id/00_process_all.py --project "$PROJECT" --no-pause
```

This replaces SPEAKER_00/SPEAKER_01 with real names and generates per-clip SRT files.

---

## Project structure (after full pipeline)

```
{project}/
├── 01_Media/
│   ├── Source/
│   │   ├── Video/                      ← camera MP4
│   │   ├── Audio/                      ← DJI synced WAV (optional)
│   │   ├── Transcription/              ← transcripts, per-clip data
│   │   │   ├── {project}_transcript.json
│   │   │   ├── {project}_FULL_AUDIO.wav
│   │   │   └── per_clip/...
│   │   ├── Setup/
│   │   │   ├── {project}_ingest.json   ← Premiere UXP
│   │   │   └── logs/                   ← all pipeline logs
│   │   └── LUT/                        ← .cube from SD card
│   ├── Assets/                         ← Music/, SFX/, Graphics/, Stock/, Fonts/
│   └── {project}.prproj               ← Premiere working project
├── 02_Exports/
├── 03_Shorts/
├── 04_Thumbnail/
├── YouTube/
├── 99_Pipeline/DJI_Audio/              ← original DJI WAV (archive)
└── {project}.gdoc
```

---

## Premiere Pro files

| File | Purpose |
|------|---------|
| `*_ingest.json` | Input for UXP Ingest plugin — imports clips, bins, LUT, captions |
| `*_transcript.srt` | Global subtitles (full timeline) |
| `per_clip/{clip}_premiere_transcript.json` | Premiere-native transcript per clip |
| `per_clip/{clip}_transcript.srt` | Per-clip subtitles with local timecodes |

---

## Troubleshooting

### "FULL_AUDIO.wav not found"
```bash
python ~/YTAI/scripts/01_prepare/02_extract_audio.py --project "$PROJECT"
```

### View logs
```bash
# Latest extract audio log
tail -50 "$PROJECT/01_Media/Source/Setup/logs/"*extract_audio*.log

# Latest transcription log
tail -50 "$PROJECT/01_Media/Source/Transcription/"*_transcribe_*.log
```

### Re-run a single stage
```bash
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only transcribe --speakers 2 --force
```

---

## Configuration

| Parameter | Value |
|-----------|-------|
| Python venv | `~/YTAI/environment/.venv_transcribe` |
| Whisper model | `large-v3` |
| Default speakers | 2 (interview) |
