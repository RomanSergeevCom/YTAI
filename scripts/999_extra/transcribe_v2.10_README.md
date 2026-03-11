# transcribe v2.10

Media transcription with speaker diarization. Whisper + pyannote → Excel.

## What's New in v2.10

### xlsx Next to Source, Service Files in Subfolder
Transcript xlsx lands **right next to the video** — easy to find. Everything else goes into a `_transcription/` service folder:

```
folder/
├── video.mp4                          ← source
├── video_transcript.xlsx              ← RIGHT HERE
└── video_transcription/               ← service folder
    ├── video_audio.wav
    ├── video_transcript.json
    ├── video_transcript.srt
    └── video_transcript.txt
```

Folder mode (`-f`) adds a project-level service folder:
```
Interview/
├── RYA-ZVE1-1146.MP4
├── RYA-ZVE1-1146_transcript.xlsx      ← next to video
├── RYA-ZVE1-1146_transcription/       ← service per file
│   ├── RYA-ZVE1-1146_audio.wav
│   ├── RYA-ZVE1-1146_transcript.json
│   ├── RYA-ZVE1-1146_transcript.srt
│   └── RYA-ZVE1-1146_transcript.txt
│
├── RYA-ZVE1-1147.MP4
├── RYA-ZVE1-1147_transcript.xlsx
├── RYA-ZVE1-1147_transcription/
│   └── ...
│
└── Interview_transcription/           ← project service
    ├── Interview_transcription.xlsx   ← combined table
    └── Interview_log_*.txt            ← session log
```

### Terminal Title — Live Status
Terminal tab/window title updates in real time at every stage:

```
🎙 Loading Whisper large-v3...
🎙 video — [1/4] extracting audio...
🎙 video — [2/4] Whisper (45m 30s)...
🎙 video — [3/4] diarization...
🎙 video — [4/4] saving...
🎙 project — 3/5 done — 60% ~25m left
✅ project — 5 done in 1h 30m
❌ project — error on filename
⛔ project — interrupted
```

Visible even when terminal is in another tab or minimized.

### Colored Phase Display
Each processing phase has a colored header with step indicator:

```
  ▶ PHASE 1/4  Audio Extraction
  ──────────────────────────────────────────────────────────

  ▶ PHASE 2/4  Transcription (Whisper) — this is the long step
  ──────────────────────────────────────────────────────────

  ▶ PHASE 3/4  Speaker Diarization (pyannote)
  ──────────────────────────────────────────────────────────

  ▶ PHASE 4/4  Merge & Save
  ──────────────────────────────────────────────────────────
```

Phase 2 is explicitly marked as the long step so you know what to expect.

### Completion Bell
Terminal bell (`\a`) rings when processing finishes — no need to watch the screen.

### xlsx Fix — No More Duplicate Columns
Timecode column shows `MM:SS`, Start/End columns show seconds as numbers (useful for sorting/filtering in Excel).

---

## Quick Start

```bash
source ~/YTAI/environment/.venv_transcribe/bin/activate

# Universal command — works for any structure
python ~/YTAI/scripts/999_extra/transcribe_v2.10.py "/path/to/anything" -f -l en

# Dry run (see plan without processing)
python ~/YTAI/scripts/999_extra/transcribe_v2.10.py "/path/to/anything" -f -l en --dry-run

# Skip confirmation
python ~/YTAI/scripts/999_extra/transcribe_v2.10.py "/path/to/anything" -f -l ru -y
```

---

## Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--folder` | `-f` | — | Smart mode: folder or auto-batch |
| `--batch` | `-b` | — | Force batch (explicit) |
| `--yes` | `-y` | — | Skip confirmation |
| `--model` | `-m` | large-v3 | Whisper model |
| `--language` | `-l` | auto | Language code |
| `--num-speakers` | `-n` | auto | Expected speakers |
| `--dry-run` | — | — | Show plan only |
| `--name` | — | auto | Project name override |
| `--no-keep-audio` | — | keep | Delete WAV after processing |

---

## Output Files

**Next to source file:**

| File | Purpose |
|------|---------|
| `{name}_transcript.xlsx` | Excel table with timecodes + speakers |

**In `{name}_transcription/` service folder:**

| File | Purpose |
|------|---------|
| `{name}_transcript.json` | Full data with metadata |
| `{name}_transcript.srt` | Subtitles with speaker labels |
| `{name}_transcript.txt` | Plain text with timecodes |
| `{name}_audio.wav` | Extracted audio |

**In project `_transcription/` folder (folder/batch mode):**

| File | Purpose |
|------|---------|
| `{project}_transcription.xlsx` | Combined table for all files |
| `{project}_log_{ts}.txt` | Session analytics log |

---

## Features

- ✅ xlsx next to source file, service files in subfolder
- ✅ Terminal title with live status at every phase
- ✅ Colored phase display with step indicators
- ✅ Terminal bell on completion
- ✅ Smart auto-detect: `-f` handles any folder structure
- ✅ Recursive subfolder discovery (any depth)
- ✅ Audio-based progress (% by minutes, not file count)
- ✅ Colored progress bar: blue → yellow → green
- ✅ Dual speed: avg + last file
- ✅ Plan vs Pace live comparison
- ✅ Session log with phase timing + calibration data
- ✅ Calibrated estimates (±10-15%)
- ✅ Speaker diarization (pyannote)
- ✅ Excel, JSON, SRT, TXT output
- ✅ Error resilience in batch mode
- ✅ Skips `_transcription/` output dirs

---

## Version History

- **v2.10.0** — xlsx next to source file, service files in `_transcription/` subfolder. Terminal title with live status. Colored phase display. Terminal bell on completion. Fixed duplicate Timecode/Start columns in xlsx. Start/End as numeric seconds in xlsx.
- **v2.9.0** — Smart auto-detect (`-f` works for any structure). Recursive subfolder search. Audio-based progress block. Session log with phase timing and calibration data.
- **v2.8.0** — Colored progress bar
- **v2.7.0** — Batch mode (`-b`), error resilience
- **v2.6.0** — Confirmation prompt
- **v2.5.0** — Plan vs Fact per-file
- **v2.4.0** — Descriptive filenames
- **v2.3.0** — Organized folder output
- **v2.0.0** — Preflight checks, pyannote 3.x
- **v1.0.0** — Initial version
