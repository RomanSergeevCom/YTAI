# transcribe v2.5

Media transcription (video + audio) with automatic speaker diarization.

**Whisper** (transcription) + **pyannote** (diarization) = text with speaker labels in Excel.

## Features

- ✅ **Audio & Video support** — mp4, mov, mkv, m4a, mp3, ogg, wav, flac, and more
- ✅ **Preflight checks** — validates all dependencies before processing
- ✅ **Speaker diarization** — automatic speaker detection and labeling
- ✅ **Excel output** — structured tables with speakers, timestamps, and text
- ✅ **Batch processing** — process entire folders with combined output
- ✅ **Timecode column** — first column for easy video navigation
- ✅ **Organized output** — folder mode creates `{name}_transcription/` subdirectory
- ✅ **Smart naming** — auto-detects project name from parent folder
- ✅ **Descriptive filenames** — `_transcript.json`, `_transcript.srt`, `_audio.wav`
- ✅ **Plan vs Fact** — per-file time estimates with actual comparison and % deviation *(new in v2.5)*

---

## Script Location

```
~/YTAI/scripts/999_extra/transcribe_v2.5.py
~/YTAI/scripts/999_extra/transcribe_v2.5_README.md
```

---

## Quick Start

```bash
# 1. Activate environment
source ~/YTAI/environment/.venv_transcribe/bin/activate

# 2. Preflight check
python ~/YTAI/scripts/999_extra/transcribe_v2.5.py --preflight

# 3. Single file
python ~/YTAI/scripts/999_extra/transcribe_v2.5.py video.mp4 -l en

# 4. Folder
python ~/YTAI/scripts/999_extra/transcribe_v2.5.py /path/to/folder -f -l en

# 5. Dry run (time estimate only)
python ~/YTAI/scripts/999_extra/transcribe_v2.5.py /path/to/folder -f -l ru --dry-run
```

### Quick alias (optional)

```bash
# Add to ~/.zshrc:
alias transcribe='source ~/YTAI/environment/.venv_transcribe/bin/activate && python ~/YTAI/scripts/999_extra/transcribe_v2.5.py'

# Then use:
transcribe "/path/to/folder" -f -l ru
transcribe video.mp4 -l en
```

---

## Plan vs Fact — Time Tracking

### Before processing: PLAN table

```
╔════════════════════════════════════════════════════════════════════════╗
║                               PLAN                                    ║
╠════════════════════════════════════════════════════════════════════════╣
║  #   File                            Audio       Est. time            ║
║──────────────────────────────────────────────────────────────────────║
║  1   RYA-ZVE1-1146.MP4               12m 34s     9m 16s              ║
║  2   RYA-ZVE1-1147.MP4               15m 12s     10m 28s             ║
║  3   RYA-ZVE1-1148.MP4               18m 45s     12m 50s             ║
║──────────────────────────────────────────────────────────────────────║
║      TOTAL                            46m 31s     32m 34s             ║
║      Estimated finish: ~15:02                                         ║
╚════════════════════════════════════════════════════════════════════════╝
```

### Before each file: completed files plan/fact

```
┌──────────────────────────────────────────────────────────────────────┐
│  #   File                        Plan      Fact      Δ              │
│──────────────────────────────────────────────────────────────────────│
│  1   RYA-ZVE1-1146.MP4           9m 16s    8m 42s    -6%            │
└──────────────────────────────────────────────────────────────────────┘

╔════════════════════════════════════════════════════════════════════════╗
║  [2/3] RYA-ZVE1-1147.MP4                                             ║
║  Audio: 15m 12s     Est: ~10m 28s     Finish: ~14:55                  ║
╚════════════════════════════════════════════════════════════════════════╝
```

### After all files: full PLAN vs FACT table

```
╔════════════════════════════════════════════════════════════════════════╗
║                          PLAN vs FACT                                  ║
╠════════════════════════════════════════════════════════════════════════╣
║  #   File                        Plan      Fact      Δ               ║
║──────────────────────────────────────────────────────────────────────║
║  1   RYA-ZVE1-1146.MP4           9m 16s    8m 42s    -6%        ✅  ║
║  2   RYA-ZVE1-1147.MP4           10m 28s   11m 05s   +6%        ✅  ║
║  3   RYA-ZVE1-1148.MP4           12m 50s   12m 10s   -5%        ✅  ║
║──────────────────────────────────────────────────────────────────────║
║      TOTAL                        32m 34s   31m 57s   -2%            ║
╚════════════════════════════════════════════════════════════════════════╝
```

After the first file, remaining estimates recalibrate based on actual processing speed.

---

## Output Files

### File Naming Convention

| File | Purpose |
|------|---------|
| `{name}_audio.wav` | Extracted audio (48kHz mono PCM) |
| `{name}_transcript.json` | Full data with metadata and segments |
| `{name}_transcript.srt` | Subtitles with [SPEAKER] labels |
| `{name}_transcript.txt` | Plain text with timecodes and speakers |
| `{name}_transcript.xlsx` | Excel table for navigation |

### Single File Mode

```
video_name/
├── video_name_audio.wav
├── video_name_transcript.json
├── video_name_transcript.srt
├── video_name_transcript.txt
└── video_name_transcript.xlsx
```

### Folder Mode

```
01_01_Video/
├── RYA-ZVE1-1146.MP4
├── RYA-ZVE1-1147.MP4
│
└── YTDEMO_transcription/
    ├── YTDEMO_transcription.xlsx         # Combined table
    ├── RYA-ZVE1-1146/
    │   ├── RYA-ZVE1-1146_audio.wav
    │   ├── RYA-ZVE1-1146_transcript.json
    │   ├── RYA-ZVE1-1146_transcript.srt
    │   ├── RYA-ZVE1-1146_transcript.txt
    │   └── RYA-ZVE1-1146_transcript.xlsx
    └── RYA-ZVE1-1147/
        └── ...
```

### Smart Naming

| Source folder | Output |
|---|---|
| `YTDEMO/01_Raw/01_01_Video/` | `YTDEMO_transcription/` |
| `Interview_Dubai/` | `Interview_Dubai_transcription/` |
| Any folder + `--name X` | `X_transcription/` |

### Text Output Format (.txt)

```
[00:00:05] [SPEAKER_00] Hello and welcome to Connect Group channel...
[00:00:12] [SPEAKER_01] Thank you for having me, Roman...
```

---

## Options Reference

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--folder` | `-f` | — | Process folder, create combined table |
| `--name` | — | auto | Project name for output folder |
| `--model` | `-m` | large-v3 | Whisper model size |
| `--language` | `-l` | auto | Language code (en, ru, ar, etc.) |
| `--num-speakers` | `-n` | auto | Expected number of speakers |
| `--beam-size` | — | 5 | Beam size for Whisper (1-10) |
| `--no-word-timestamps` | — | — | Disable word-level timestamps |
| `--prompt` | — | — | Initial prompt for Whisper |
| `--no-keep-audio` | — | — | Delete WAV after processing |
| `--dry-run` | — | — | Show plan table + time estimate |
| `--preflight` | — | — | Run preflight checks only |
| `--skip-preflight` | — | — | Skip preflight (not recommended) |
| `--version` | — | — | Show version |

### Whisper Models

| Model | Size | Speed | Use Case |
|-------|------|-------|----------|
| tiny | ~75 MB | ⚡⚡⚡⚡⚡ | Quick test |
| base | ~150 MB | ⚡⚡⚡⚡ | Draft |
| small | ~500 MB | ⚡⚡⚡ | Good enough |
| medium | ~1.5 GB | ⚡⚡ | Better quality |
| large-v3 | ~2.9 GB | ⚡ | Best quality (default) |

---

## Installation

```bash
pip install openai-whisper torch pyannote.audio soundfile openpyxl --break-system-packages
brew install ffmpeg
```

### HuggingFace Token

```bash
export HF_TOKEN="hf_your_token_here"
# Or: huggingface-cli login
# Or: echo 'HF_TOKEN=hf_xxx' > ~/YTAI/config/HuggingFace-yt-prod.conf
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Missing packages | `pip install openai-whisper torch pyannote.audio soundfile openpyxl --break-system-packages` |
| HF_TOKEN not found | `export HF_TOKEN="hf_xxx"` or `huggingface-cli login` |
| ffmpeg not found | `brew install ffmpeg` |
| Slow (CPU mode) | `pip uninstall torch && pip install torch --break-system-packages` |
| Out of memory | Use `-m medium` instead of `large-v3` |

---

## Version History

- **v2.5.0** — Plan vs Fact: per-file time estimates with plan/fact table before each block and full comparison at the end with % deviation
- **v2.4.0** — Renamed to `transcribe.py`. Descriptive filenames (`_transcript`, `_audio`). Timecodes in .txt. Per-file ETA during batch processing
- **v2.3.0** — Organized folder output: `{name}_transcription/`, smart project naming, `--name` flag
- **v2.2.0** — Timecode column, folder/file name as sheet name
- **v2.1.0** — Audio file support (m4a, mp3, ogg, wav, flac, aac, opus)
- **v2.0.0** — Preflight checks, soundfile audio loading, pyannote 3.x support
- **v1.0.0** — Initial version

---

## License

MIT
