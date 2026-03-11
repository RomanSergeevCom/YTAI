# transcribe v2.8

Media transcription (video + audio) with automatic speaker diarization.

**Whisper** (transcription) + **pyannote** (diarization) = text with speaker labels in Excel.

## Features

- ✅ **Three modes**: single file, folder (`-f`), batch of folders (`-b`)
- ✅ **Colored progress bar** — blue → yellow → green with %, ETA, speed *(new in v2.8)*
- ✅ **Calibrated estimates** — ±10-15% accuracy based on real-world data
- ✅ **Audio & Video support** — mp4, mov, mkv, m4a, mp3, ogg, wav, flac, and more
- ✅ **Speaker diarization** — automatic speaker detection and labeling
- ✅ **Excel output** — structured tables with speakers, timestamps, and text
- ✅ **Organized output** — `{name}_transcription/` subdirectory per folder
- ✅ **Descriptive filenames** — `_transcript.json`, `_transcript.srt`, `_audio.wav`
- ✅ **Plan vs Fact** — per-file/folder time estimates with % deviation
- ✅ **Confirm before start** — shows PLAN, waits for Enter (`-y` to skip)
- ✅ **Error resilience** — in batch mode, failed folder → continues to next

---

## Quick Start

```bash
source ~/YTAI/environment/.venv_transcribe/bin/activate

# Single file
python ~/YTAI/scripts/999_extra/transcribe_v2.8.py video.mp4 -l en

# Folder
python ~/YTAI/scripts/999_extra/transcribe_v2.8.py /path/to/folder -f -l ru

# Batch — all subfolders
python ~/YTAI/scripts/999_extra/transcribe_v2.8.py /path/to/parent -b -l ru

# Dry run
python ~/YTAI/scripts/999_extra/transcribe_v2.8.py /path/to/parent -b -l ru --dry-run
```

### Quick alias

```bash
# Add to ~/.zshrc:
alias transcribe='source ~/YTAI/environment/.venv_transcribe/bin/activate && python ~/YTAI/scripts/999_extra/transcribe_v2.8.py'

# Then:
transcribe "/Volumes/RYA T7 Black/YTRF" -b -l ru
```

---

## Progress Bar

After each file/folder, a colored progress bar shows current status:

```
[████████████ 42% ░░░░░░░░░░░░░░░] 3/6 folders │ 1h 42m / ~3h 20m │ ~17:15 │ 0.8x RT
```

- **Color changes by progress**: blue (0-30%) → yellow (30-70%) → green (70-100%)
- **Shows**: percentage, counter, elapsed/estimated, finish time, realtime speed
- **Recalibrates**: after each step, uses actual speed for remaining estimate

---

## Batch Workflow

```
1. PREFLIGHT — checks dependencies
2. SCAN — discovers subfolders with media
3. BATCH PLAN — table with all folders
4. CONFIRM — Enter / n
5. PROCESS — each folder + progress bar after each
6. REPORT — PLAN vs FACT with % deviation
```

---

## Output Files

| File | Purpose |
|------|---------|
| `{name}_audio.wav` | Extracted audio (48kHz mono PCM) |
| `{name}_transcript.json` | Full data with metadata and segments |
| `{name}_transcript.srt` | Subtitles with [SPEAKER] labels |
| `{name}_transcript.txt` | Plain text with timecodes and speakers |
| `{name}_transcript.xlsx` | Excel table for navigation |

### Text Output (.txt)

```
[00:00:05] [SPEAKER_00] Привет, добро пожаловать...
[00:00:12] [SPEAKER_01] Спасибо, рад быть здесь...
```

---

## Options Reference

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--folder` | `-f` | — | Process one folder |
| `--batch` | `-b` | — | Process all subfolders |
| `--name` | — | auto | Project name (for `-f`) |
| `--yes` | `-y` | — | Skip confirmation |
| `--model` | `-m` | large-v3 | Whisper model |
| `--language` | `-l` | auto | Language code |
| `--num-speakers` | `-n` | auto | Expected speakers |
| `--dry-run` | — | — | Show plan only |
| `--preflight` | — | — | Check setup only |

---

## Installation

```bash
pip install openai-whisper torch pyannote.audio soundfile openpyxl --break-system-packages
brew install ffmpeg
export HF_TOKEN="hf_your_token_here"
```

---

## Version History

- **v2.8.0** — Colored progress bar (blue→yellow→green) with %, ETA, speed. Shows after each file/folder in both folder and batch modes. Calibrated time estimates from real-world data (±10-15%).
- **v2.7.0** — Batch mode (`-b`), auto-discover subfolders, error resilience, batch PLAN vs FACT
- **v2.6.0** — Confirmation prompt, `-y` flag
- **v2.5.0** — Plan vs Fact per-file with % deviation
- **v2.4.0** — Renamed to `transcribe.py`. Descriptive filenames. Timecodes in .txt
- **v2.3.0** — Organized folder output, smart naming, `--name`
- **v2.2.0** — Timecode column, sheet naming
- **v2.1.0** — Audio file support
- **v2.0.0** — Preflight checks, pyannote 3.x
- **v1.0.0** — Initial version

---

## License

MIT
