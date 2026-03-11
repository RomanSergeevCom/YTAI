# transcribe v2.7

Media transcription (video + audio) with automatic speaker diarization.

**Whisper** (transcription) + **pyannote** (diarization) = text with speaker labels in Excel.

## Features

- ✅ **Three modes**: single file, folder (`-f`), batch of folders (`-b`) *(new in v2.7)*
- ✅ **Audio & Video support** — mp4, mov, mkv, m4a, mp3, ogg, wav, flac, and more
- ✅ **Preflight checks** — validates all dependencies before processing
- ✅ **Speaker diarization** — automatic speaker detection and labeling
- ✅ **Excel output** — structured tables with speakers, timestamps, and text
- ✅ **Organized output** — `{name}_transcription/` subdirectory per folder
- ✅ **Smart naming** — auto-detects project name from parent folder
- ✅ **Descriptive filenames** — `_transcript.json`, `_transcript.srt`, `_audio.wav`
- ✅ **Plan vs Fact** — per-file/folder time estimates with % deviation
- ✅ **Confirm before start** — shows PLAN, waits for Enter (`-y` to skip)
- ✅ **Error resilience** — in batch mode, failed folder → continues to next

---

## Script Location

```
~/YTAI/scripts/999_extra/transcribe_v2.7.py
~/YTAI/scripts/999_extra/transcribe_v2.7_README.md
```

---

## Quick Start

```bash
source ~/YTAI/environment/.venv_transcribe/bin/activate

# Single file
python ~/YTAI/scripts/999_extra/transcribe_v2.7.py video.mp4 -l en

# Folder — all videos in one folder
python ~/YTAI/scripts/999_extra/transcribe_v2.7.py /path/to/folder -f -l ru

# Batch — all subfolders with videos
python ~/YTAI/scripts/999_extra/transcribe_v2.7.py /path/to/parent -b -l ru

# Dry run (any mode)
python ~/YTAI/scripts/999_extra/transcribe_v2.7.py /path/to/parent -b -l ru --dry-run
```

### Quick alias

```bash
# Add to ~/.zshrc:
alias transcribe='source ~/YTAI/environment/.venv_transcribe/bin/activate && python ~/YTAI/scripts/999_extra/transcribe_v2.7.py'

# Then use:
transcribe "/Volumes/RYA T7 Black/YTRF" -b -l ru
transcribe video.mp4 -l en
```

---

## Three Modes

### 1. Single File

```bash
transcribe video.mp4 -l en
transcribe recording.m4a -l ru
```

### 2. Folder (`-f`)

All media files in one folder → combined table:

```bash
transcribe /path/to/folder -f -l en
```

### 3. Batch (`-b`) *(new in v2.7)*

All subfolders with media → each processed as a separate project:

```bash
transcribe "/Volumes/RYA T7 Black/YTRF" -b -l ru
```

Automatically discovers subfolders, skips those without media:

```
YTRF/
├── 20250124_Artem_Dogaev/     ← has videos → process ✅
├── 20250128/                  ← has videos → process ✅
├── 20250128_Mechnikov/        ← has videos → process ✅
├── 20250129_Michael/          ← has videos → process ✅
├── 20250129_Ylia/             ← has videos → process ✅
├── 20250130_Andrey/           ← has videos → process ✅
└── Extra files/               ← no videos → skip ⏭️
```

---

## Batch Workflow

```
1. PREFLIGHT — checks dependencies
2. SCAN — discovers subfolders with media
3. BATCH PLAN — table with all folders, files, durations, estimates
4. CONFIRM — "Start processing? (Enter / n)"
5. PROCESS — each folder sequentially
   ├── If OK → ✅ continues
   └── If ERROR → ❌ logs, continues to next
6. REPORT — BATCH PLAN vs FACT with % deviation
```

### Example Session

```
╔════════════════════════════════════════════════════════════════════════╗
║                           BATCH PLAN                                  ║
╠════════════════════════════════════════════════════════════════════════╣
║  #   Folder                         Files   Audio       Est.          ║
║──────────────────────────────────────────────────────────────────────║
║  1   20250124_Artem_Dogaev           5       1h 12m      48m 30s      ║
║  2   20250128                        3       42m 15s     28m 40s      ║
║  3   20250128_Mechnikov              4       55m 30s     37m 20s      ║
║  4   20250129_Michael                3       38m 10s     25m 47s      ║
║  5   20250129_Ylia                   2       28m 45s     19m 30s      ║
║  6   20250130_Andrey                 4       50m 20s     33m 47s      ║
║──────────────────────────────────────────────────────────────────────║
║      TOTAL                           21      5h 07m      3h 13m       ║
║      Estimated finish: ~17:43                                         ║
╚════════════════════════════════════════════════════════════════════════╝

[?] Start processing? (Enter = yes, n = cancel):

... processing 6 folders ...

╔════════════════════════════════════════════════════════════════════════╗
║                   BATCH COMPLETED — PLAN vs FACT                      ║
╠════════════════════════════════════════════════════════════════════════╣
║  #   Folder                   Plan      Fact      Δ                  ║
║──────────────────────────────────────────────────────────────────────║
║  1   20250124_Artem_Dogaev     48m 30s   45m 12s   -7%          ✅  ║
║  2   20250128                  28m 40s   30m 05s   +5%          ✅  ║
║  3   20250128_Mechnikov        37m 20s   35m 48s   -4%          ✅  ║
║  4   20250129_Michael          25m 47s   24m 30s   -5%          ✅  ║
║  5   20250129_Ylia             19m 30s   19m 55s   +2%          ✅  ║
║  6   20250130_Andrey           33m 47s   32m 10s   -5%          ✅  ║
║──────────────────────────────────────────────────────────────────────║
║      TOTAL                     3h 13m    3h 07m    -3%               ║
╚════════════════════════════════════════════════════════════════════════╝

Folders: 6 successful, 0 failed
Total time: 3h 07m
```

---

## Output Structure

### Batch Mode Result

```
YTRF/
├── 20250124_Artem_Dogaev/
│   ├── video1.MP4
│   ├── video2.MP4
│   └── 20250124_Artem_Dogaev_transcription/
│       ├── 20250124_Artem_Dogaev_transcription.xlsx
│       ├── video1/
│       │   ├── video1_audio.wav
│       │   ├── video1_transcript.json
│       │   ├── video1_transcript.srt
│       │   ├── video1_transcript.txt
│       │   └── video1_transcript.xlsx
│       └── video2/
│           └── ...
├── 20250128/
│   └── 20250128_transcription/
│       └── ...
├── 20250128_Mechnikov/
│   └── 20250128_Mechnikov_transcription/
│       └── ...
└── Extra files/                               ← untouched
```

### File Naming Convention

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
| `--folder` | `-f` | — | Process one folder, combined table |
| `--batch` | `-b` | — | Process all subfolders with videos |
| `--name` | — | auto | Project name (for `-f` mode) |
| `--yes` | `-y` | — | Skip confirmation |
| `--model` | `-m` | large-v3 | Whisper model size |
| `--language` | `-l` | auto | Language code (en, ru, ar) |
| `--num-speakers` | `-n` | auto | Expected number of speakers |
| `--beam-size` | — | 5 | Beam size for Whisper (1-10) |
| `--prompt` | — | — | Initial prompt for Whisper |
| `--no-keep-audio` | — | — | Delete WAV after processing |
| `--dry-run` | — | — | Show plan only, no processing |
| `--preflight` | — | — | Check setup only |
| `--skip-preflight` | — | — | Skip preflight |

---

## Installation

```bash
pip install openai-whisper torch pyannote.audio soundfile openpyxl --break-system-packages
brew install ffmpeg
export HF_TOKEN="hf_your_token_here"
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Missing packages | `pip install openai-whisper torch pyannote.audio soundfile openpyxl --break-system-packages` |
| HF_TOKEN not found | `export HF_TOKEN="hf_xxx"` or `huggingface-cli login` |
| ffmpeg not found | `brew install ffmpeg` |
| Slow (CPU) | `pip uninstall torch && pip install torch --break-system-packages` |
| Out of memory | Use `-m medium` instead of `large-v3` |
| One folder fails in batch | Script logs error and continues to next |

---

## Version History

- **v2.7.0** — Batch mode (`-b`): process all subfolders, auto-discover media, error resilience, batch PLAN vs FACT
- **v2.6.0** — Confirmation prompt before processing, `-y` flag, timer starts after confirmation
- **v2.5.0** — Plan vs Fact per-file with % deviation
- **v2.4.0** — Renamed to `transcribe.py`. Descriptive filenames. Timecodes in .txt. Per-file ETA
- **v2.3.0** — Organized folder output: `{name}_transcription/`, smart naming, `--name`
- **v2.2.0** — Timecode column, folder/file name as sheet name
- **v2.1.0** — Audio file support
- **v2.0.0** — Preflight checks, soundfile loading, pyannote 3.x
- **v1.0.0** — Initial version

---

## License

MIT
