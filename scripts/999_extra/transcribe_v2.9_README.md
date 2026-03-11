# transcribe v2.9

Media transcription with speaker diarization. Whisper + pyannote → Excel.

## What's New in v2.9

### Smart Auto-Detect
`-f` now works for **any folder structure**. No need to choose between `-f` and `-b`:

```bash
# Videos in root → folder mode
python transcribe_v2.9.py "/path/to/videos" -f -l en

# No videos in root, but subfolders have videos → auto-switches to batch
python transcribe_v2.9.py "/path/to/project" -f -l en

# Nested folders (any depth) → finds all recursively
python transcribe_v2.9.py "/path/to/deep/structure" -f -l en
```

Auto-detect logic:
1. Videos in root folder → **folder mode** (one project)
2. No videos in root, subfolders have videos → **auto-batch** (each folder = project)
3. Recursive search — works at any nesting depth
4. Skips `_transcription/` output dirs and hidden folders

`-b` still works as explicit batch if needed.

### Audio-Based Progress
Progress % is based on **audio minutes**, not file count:

```
══════════════════════════════════════════════════════════════════════
  PROGRESS: 22m 15s / 1h 04m 20s audio processed
  [█████████████░░░░░░ 34% ░░░░░░░░░░░░░░░░░░]

  Files:    12/45 done │ Next: RYA-ZVE1-1395.MP4
  Time:     34m 12s elapsed │ ~1h 05m remaining │ finish ~17:15
  Speed:    0.65x RT (avg) │ last: 0.91x RT
  Estimate: Plan 1h 39m │ Pace → 1h 39m │ Δ +0%
══════════════════════════════════════════════════════════════════════
```

### Session Log
Detailed analytics log saved after each run:

```
PER-FILE METRICS
  #   File                  Audio     Total     Whisper   Pyannote  Speed   Words
  1   RYA-ZVE1-1370         29m 27s   20m 18s   19m 35s   6s        1.45x   847

TIME BREAKDOWN (% of total processing)
  Whisper transcription:     24m 05s  ( 95.8%)
  Pyannote diarization:         9s   (  0.6%)

CALIBRATION DATA
  Measured speed:       0.82x RT
  Suggested ESTIMATE_SPEED['large-v3']: 0.82
```

Log location: `{name}_transcription/{name}_log_{timestamp}.txt`

---

## Quick Start

```bash
source ~/YTAI/environment/.venv_transcribe/bin/activate

# Universal command — works for any structure
python ~/YTAI/scripts/999_extra/transcribe_v2.9.py "/path/to/anything" -f -l en

# Dry run (see plan without processing)
python ~/YTAI/scripts/999_extra/transcribe_v2.9.py "/path/to/anything" -f -l en --dry-run

# Skip confirmation
python ~/YTAI/scripts/999_extra/transcribe_v2.9.py "/path/to/anything" -f -l ru -y
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

---

## Output Files

| File | Purpose |
|------|---------|
| `{name}_transcript.json` | Full data with metadata |
| `{name}_transcript.srt` | Subtitles with speaker labels |
| `{name}_transcript.txt` | Plain text with timecodes |
| `{name}_transcript.xlsx` | Excel table |
| `{name}_audio.wav` | Extracted audio |
| `{name}_log_{ts}.txt` | Session analytics log |

---

## Features

- ✅ Smart auto-detect: `-f` handles any folder structure
- ✅ Recursive subfolder discovery (any depth)
- ✅ Audio-based progress (% by minutes, not file count)
- ✅ Colored progress: blue → yellow → green
- ✅ Dual speed: avg + last file
- ✅ Plan vs Pace live comparison
- ✅ Session log with phase timing + calibration data
- ✅ Calibrated estimates (±10-15%)
- ✅ Speaker diarization (pyannote)
- ✅ Excel, JSON, SRT, TXT output
- ✅ Error resilience in batch mode
- ✅ Skips _transcription/ output dirs

---

## Version History

- **v2.9.0** — Smart auto-detect (`-f` works for any structure). Recursive subfolder search. Audio-based progress block. Session log with phase timing and calibration data.
- **v2.8.0** — Colored progress bar
- **v2.7.0** — Batch mode (`-b`), error resilience
- **v2.6.0** — Confirmation prompt
- **v2.5.0** — Plan vs Fact per-file
- **v2.4.0** — Descriptive filenames
- **v2.3.0** — Organized folder output
- **v2.0.0** — Preflight checks, pyannote 3.x
- **v1.0.0** — Initial version
