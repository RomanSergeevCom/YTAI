# whisper_batch v2.3

Media transcription (video + audio) with automatic speaker diarization.

**Whisper** (transcription) + **pyannote** (diarization) = text with speaker labels in Excel.

## Features

- ✅ **Audio & Video support** — mp4, mov, mkv, m4a, mp3, ogg, wav, flac, and more
- ✅ **Preflight checks** — validates all dependencies before processing
- ✅ **Speaker diarization** — automatic speaker detection and labeling
- ✅ **Excel output** — structured tables with speakers, timestamps, and text
- ✅ **Batch processing** — process entire folders with combined output
- ✅ **Timecode column** — first column for easy video navigation
- ✅ **Project naming** — sheet names match folder/file names
- ✅ **Organized output** — folder mode creates `{name}_transcription/` subdirectory *(new in v2.3)*
- ✅ **Smart naming** — auto-detects project name from parent folder *(new in v2.3)*

---

## Table of Contents

- [Quick Start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
- [Output Files](#output-files)
- [Architecture](#architecture)
- [Preflight Checks](#preflight-checks)
- [Options Reference](#options-reference)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

```bash
# 1. Activate environment
source ~/YTAI/environment/.venv_transcribe/bin/activate

# 2. Run preflight check
python ~/YTAI/scripts/999_extra/whisper_batch.py --preflight

# 3. Process a video
python ~/YTAI/scripts/999_extra/whisper_batch.py video.mp4 --language en

# 4. Process an audio file
python ~/YTAI/scripts/999_extra/whisper_batch.py recording.m4a --language ru

# 5. Process a folder
python ~/YTAI/scripts/999_extra/whisper_batch.py /path/to/folder --folder --language en
```

---

## Installation

### Requirements

| Component | Purpose | Install |
|-----------|---------|---------|
| Python 3.9+ | Runtime | — |
| ffmpeg | Audio extraction | `brew install ffmpeg` |
| openai-whisper | Transcription | `pip install openai-whisper` |
| torch | ML framework | `pip install torch` |
| pyannote.audio | Speaker diarization | `pip install pyannote.audio` |
| soundfile | Audio loading | `pip install soundfile` |
| openpyxl | Excel output | `pip install openpyxl` |

### One-line install

```bash
pip install openai-whisper torch pyannote.audio soundfile openpyxl --break-system-packages
```

### HuggingFace Token (required for speaker diarization)

1. Create token: https://huggingface.co/settings/tokens
2. Accept model licenses:
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
3. Set token:
   ```bash
   export HF_TOKEN="hf_your_token_here"
   ```
   Or login:
   ```bash
   huggingface-cli login
   ```

---

## Usage

### Preflight Check Only

```bash
python whisper_batch.py --preflight
```

Validates all dependencies without processing. Use this to verify your setup.

### Single File (Video or Audio)

```bash
# Video files
python whisper_batch.py video.mp4
python whisper_batch.py video.mp4 --language en
python whisper_batch.py video.mp4 --language en --num-speakers 2

# Audio files
python whisper_batch.py recording.m4a --language ru
python whisper_batch.py podcast.mp3 --language en
python whisper_batch.py voice_memo.ogg
```

### Folder of Media Files

```bash
python whisper_batch.py /path/to/folder --folder
python whisper_batch.py /path/to/folder --folder --language en
python whisper_batch.py /path/to/folder --folder --name "MyProject"
```

### Dry Run

```bash
python whisper_batch.py /path/to/folder --folder --dry-run
```

Shows what would be processed without actually processing.

---

## Supported Formats

### Video
`.mp4`, `.mov`, `.m4v`, `.mts`, `.avi`, `.mkv`, `.webm`

### Audio
`.m4a`, `.mp3`, `.wav`, `.ogg`, `.flac`, `.aac`, `.opus`

---

## Output Files

### Single File Mode

No changes — results go into a subfolder next to the file:

```
video_name/
├── video_name.wav      # Extracted audio (48kHz mono)
├── video_name.json     # Full data with metadata
├── video_name.srt      # Subtitles with [SPEAKER] labels
├── video_name.txt      # Plain text with speakers
└── video_name.xlsx     # Excel table
```

### Folder Mode (v2.3 — new structure)

Results are organized in a `{name}_transcription/` subdirectory inside the source folder:

```
01_01_Video/
├── RYA-ZVE1-1146.MP4                    # Source files stay clean
├── RYA-ZVE1-1147.MP4
├── RYA-ZVE1-1148.MP4
│
└── YTDEMO_transcription/                 # ← created by script
    ├── YTDEMO_transcription.xlsx         # Combined table (all videos)
    ├── RYA-ZVE1-1146/
    │   ├── RYA-ZVE1-1146.wav
    │   ├── RYA-ZVE1-1146.json
    │   ├── RYA-ZVE1-1146.srt
    │   ├── RYA-ZVE1-1146.txt
    │   └── RYA-ZVE1-1146.xlsx
    ├── RYA-ZVE1-1147/
    │   └── ...
    └── RYA-ZVE1-1148/
        └── ...
```

**Project name logic:**
- `--name "MyProject"` → `MyProject_transcription/`
- Folder is `01_01_Video` (technical) → uses parent folder name (e.g. `YTDEMO`)
- Folder is `Interview_Dubai` (meaningful) → uses `Interview_Dubai`

### Smart Naming — Auto-Detection

The script recognizes technical folder names and automatically uses the parent:

| Source folder | Parent | Output |
|---|---|---|
| `YTDEMO/01_Raw/01_01_Video/` | `01_Raw` → `YTDEMO` | `YTDEMO_transcription/` |
| `Interview_Dubai/` | — | `Interview_Dubai_transcription/` |
| `videos/` | `MyProject` | `MyProject_transcription/` |
| Any folder + `--name X` | — | `X_transcription/` |

Technical names that trigger parent lookup: `01_01_video`, `01_02_audio`, `01_raw`, `01_source`, `video`, `videos`, `audio`, `raw`, `source`, `media`, `clips`, `footage`, `input`, `inputs`.

### Excel Table Structure

**Single video:**

| Timecode | Start | End | Duration | Speaker | Text |
|----------|-------|-----|----------|---------|------|
| 00:05 | 00:05 | 00:12 | 7.0s | SPEAKER_00 | Hello everyone! |
| 00:12 | 00:12 | 00:18 | 6.0s | SPEAKER_01 | Hi, thanks for having me. |

**Folder (combined):**

| Timecode | # | Video | Start | End | Duration | Speaker | Text |
|----------|---|-------|-------|-----|----------|---------|------|
| 00:05 | 1 | interview1.mp4 | 00:05 | 00:12 | 7.0s | SPEAKER_00 | Hello! |
| 00:12 | 1 | | 00:12 | 00:18 | 6.0s | SPEAKER_01 | Hi there! |
| 00:00 | 2 | interview2.mp4 | 00:00 | 00:08 | 8.0s | SPEAKER_00 | Welcome... |

**Sheet naming:**
- Single file: sheet named after video file (e.g., "interview_01")
- Folder mode: sheet named after project (e.g., "YTDEMO")

---

## Architecture

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                           INPUT                                      │
│                                                                     │
│    video.mp4          OR          /folder/  (--folder)              │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      PREFLIGHT CHECKS                                │
│                                                                     │
│  [1] System: ffmpeg, ffprobe                                        │
│  [2] Packages: whisper, torch, pyannote, soundfile, openpyxl        │
│  [3] Auth: HF_TOKEN                                                 │
│  [4] Models: Whisper cache                                          │
│  [5] Input: path exists, videos found, disk space                   │
│  [6] Device: MPS/CUDA/CPU                                           │
│                                                                     │
│  ❌ Errors → EXIT       ✅ All passed → CONTINUE                    │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│              PROJECT NAME RESOLUTION (folder mode)                    │
│                                                                     │
│  --name "X"  →  X_transcription/                                    │
│  01_01_Video →  {parent}_transcription/                             │
│  MyFolder    →  MyFolder_transcription/                             │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    PROCESSING PIPELINE                               │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ PHASE 1: Audio Extraction                                   │    │
│  │   video.mp4 → ffmpeg → video.wav (48kHz mono PCM)          │    │
│  └────────────────────────────────────────────────────────────┘    │
│                              │                                      │
│                              ▼                                      │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ PHASE 2: Transcription (Whisper)                           │    │
│  │   video.wav → Whisper large-v3 → segments[]                │    │
│  │   {start, end, text}                                       │    │
│  └────────────────────────────────────────────────────────────┘    │
│                              │                                      │
│                              ▼                                      │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ PHASE 3: Speaker Diarization (pyannote)                    │    │
│  │   video.wav → pyannote 3.1 → diarization[]                 │    │
│  │   {start, end, speaker}                                    │    │
│  └────────────────────────────────────────────────────────────┘    │
│                              │                                      │
│                              ▼                                      │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ PHASE 4: Merge & Save                                      │    │
│  │   segments[] + diarization[] → merged[]                    │    │
│  │   → .json, .srt, .txt, .xlsx                              │    │
│  │   → saved to {name}_transcription/video_name/             │    │
│  └────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           OUTPUT                                     │
│                                                                     │
│  Single: video_name/*.{json,srt,txt,xlsx,wav}                       │
│  Folder: {name}_transcription/{name}_transcription.xlsx              │
│          + {name}_transcription/video_name/*                         │
└─────────────────────────────────────────────────────────────────────┘
```

### Speaker Assignment Algorithm

```
For each Whisper segment:

  Whisper:    [========segment========]
              start                end

  pyannote:   [==SPEAKER_00==][=====SPEAKER_01=====]

  Overlap:    [====2 sec====][========4 sec========]

  Result:     SPEAKER_01 wins (4s > 2s maximum overlap)
```

---

## Preflight Checks

The script validates everything before processing to avoid failures mid-run.

### Checks Performed

| # | Check | Critical | Description |
|---|-------|----------|-------------|
| 1 | ffmpeg | ❌ Yes | Required for audio extraction |
| 1 | ffprobe | ❌ Yes | Required for duration detection |
| 2 | openai-whisper | ❌ Yes | Required for transcription |
| 2 | torch | ❌ Yes | Required for ML models |
| 2 | pyannote.audio | ❌ Yes | Required for speaker diarization |
| 2 | soundfile | ❌ Yes | Required for audio loading |
| 2 | openpyxl | ❌ Yes | Required for Excel output |
| 3 | HF_TOKEN | ❌ Yes | Required for pyannote models |
| 4 | Whisper model | ⚠️ Warning | Will download if missing |
| 5 | Input path | ❌ Yes | Must exist |
| 5 | Video files | ❌ Yes | Must find videos |
| 5 | Disk space | ❌ Yes | Need ≥1 GB free |
| 6 | GPU | ⚠️ Warning | CPU works but slow |

### Example Output

```
╔════════════════════════════════════════════════════════════════════╗
║                        PREFLIGHT CHECKS                            ║
╚════════════════════════════════════════════════════════════════════╝

[1/6] System dependencies
  ✅ ffmpeg: 7.1
  ✅ ffprobe: available

[2/6] Python packages
  ✅ openai-whisper: 20240930
  ✅ torch: 2.8.0
  ✅ pyannote.audio: 3.3.2
  ✅ soundfile: 0.12.1
  ✅ openpyxl: 3.1.2

[3/6] Authentication
  ✅ HF_TOKEN: found (hf_xxxx...xxxx)
     Source: ~/YTAI/config/HuggingFace-yt-prod.conf

[4/6] Models
  ✅ Whisper large-v3: cached (2.9 GB)
  ℹ️  pyannote/speaker-diarization-3.1: checked at runtime

[5/6] Input validation
  ✅ Path exists: YTCG Feedback Rakez
  ✅ Videos found: 5 files (17.9 GB)
  ✅ Disk space: 45.2 GB free

[6/6] Compute device
  ✅ Apple Silicon (MPS)

──────────────────────────────────────────────────────────────────────
✅ All checks passed! Ready to process.
──────────────────────────────────────────────────────────────────────
```

---

## Options Reference

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--folder` | `-f` | — | Process folder, create combined table |
| `--name` | — | auto | Project name for output folder *(new in v2.3)* |
| `--model` | `-m` | large-v3 | Whisper model size |
| `--language` | `-l` | auto | Language code (en, ru, ar, etc.) |
| `--num-speakers` | `-n` | auto | Expected number of speakers |
| `--beam-size` | — | 5 | Beam size for Whisper (1-10) |
| `--no-word-timestamps` | — | — | Disable word-level timestamps |
| `--prompt` | — | — | Initial prompt for Whisper |
| `--no-keep-audio` | — | — | Delete WAV after processing |
| `--dry-run` | — | — | Show what would be processed |
| `--preflight` | — | — | Run preflight checks only |
| `--skip-preflight` | — | — | Skip preflight (not recommended) |
| `--version` | — | — | Show version |

### Whisper Models

| Model | Size | Quality | Speed | Use Case |
|-------|------|---------|-------|----------|
| tiny | ~75 MB | ★☆☆☆☆ | ⚡⚡⚡⚡⚡ | Quick test |
| base | ~150 MB | ★★☆☆☆ | ⚡⚡⚡⚡ | Draft |
| small | ~500 MB | ★★★☆☆ | ⚡⚡⚡ | Good enough |
| medium | ~1.5 GB | ★★★★☆ | ⚡⚡ | Better quality |
| large-v3 | ~2.9 GB | ★★★★★ | ⚡ | Best quality (default) |

---

## Commands Quick Reference

### Environment Setup

```bash
# Activate virtual environment
source ~/YTAI/environment/.venv_transcribe/bin/activate

# Set HuggingFace token (if not in config)
export HF_TOKEN="hf_your_token_here"
```

### Preflight

```bash
python whisper_batch.py --preflight
```

### Single File

```bash
python whisper_batch.py video.mp4 -l en
python whisper_batch.py video.mp4 -l en -n 2
python whisper_batch.py recording.m4a -l ru
```

### Folder Batch

```bash
python whisper_batch.py /path/to/folder -f -l en
python whisper_batch.py /path/to/folder -f -l en -n 2
python whisper_batch.py /path/to/folder -f -l en --name "MyProject"
```

### YTAI Project Workflow

```bash
# 1. Activate
source ~/YTAI/environment/.venv_transcribe/bin/activate

# 2. Preflight
python ~/YTAI/scripts/999_extra/whisper_batch.py --preflight

# 3. Process (auto-detects project name from parent)
python ~/YTAI/scripts/999_extra/whisper_batch.py "/Volumes/RYA Blue/YTDEMO/01_Raw/01_01_Video" -f -l en -n 2
# → Creates: 01_01_Video/YTDEMO_transcription/

# 4. Or override name
python ~/YTAI/scripts/999_extra/whisper_batch.py "/Volumes/RYA Blue/YTDEMO/01_Raw/01_01_Video" -f -l en -n 2 --name "YTCG38_Coffee"
# → Creates: 01_01_Video/YTCG38_Coffee_transcription/
```

---

## Examples

### Basic Usage

```bash
# Single video with English
python whisper_batch.py interview.mp4 --language en

# Folder with 2 expected speakers
python whisper_batch.py /Volumes/Drive/Project --folder -l en -n 2

# Quick test with smaller model
python whisper_batch.py video.mp4 -m small -l en
```

### With Custom Prompt

```bash
# Help Whisper with domain-specific terms
python whisper_batch.py video.mp4 -l en --prompt "UAE, DMCC, freezone, RAKEZ, visa"
```

### With Custom Project Name

```bash
# Override auto-detected name
python whisper_batch.py /path/to/videos --folder --name "YTCG37_Hadi_Dawani"
```

### Check Setup Only

```bash
# Verify everything is installed
python whisper_batch.py --preflight

# Check with specific input
python whisper_batch.py /path/to/folder --folder --preflight
```

---

## Troubleshooting

### Preflight fails: missing packages

```bash
pip install openai-whisper torch pyannote.audio soundfile openpyxl --break-system-packages
```

### Preflight fails: HF_TOKEN not found

```bash
# Option 1: Environment variable
export HF_TOKEN="hf_your_token_here"

# Option 2: HuggingFace CLI
huggingface-cli login

# Option 3: Config file
echo 'HF_TOKEN=hf_your_token_here' > ~/YTAI/config/HuggingFace-yt-prod.conf
```

### Preflight fails: ffmpeg not found

```bash
brew install ffmpeg
```

### Processing is slow (CPU mode)

Check that GPU is detected:
```
[6/6] Compute device
  ✅ Apple Silicon (MPS)    # Good!
  ⚠️  CPU (processing will be slow)  # Bad - check torch installation
```

Reinstall torch with GPU support:
```bash
pip uninstall torch
pip install torch --break-system-packages
```

### Out of memory

Use a smaller model:
```bash
python whisper_batch.py video.mp4 -m medium -l en
```

### Wrong language detected

Specify language explicitly:
```bash
python whisper_batch.py video.mp4 --language en
```

### Re-running on same folder

Safe to re-run — the script skips existing audio files and overwrites previous results in the `_transcription/` directory.

---

## File Locations

```
~/YTAI/
├── config/
│   └── HuggingFace-yt-prod.conf    # HF_TOKEN storage
├── environment/
│   └── .venv_transcribe/           # Python virtual environment
├── scripts/
│   └── 999_extra/
│       ├── whisper_batch.py        # This script
│       └── whisper_batch_README.md # This documentation
└── models/                         # Model cache (optional)

~/.cache/
├── whisper/
│   └── large-v3.pt                 # Whisper model cache
└── huggingface/
    └── token                       # HF token (alternative location)
```

### Quick alias (optional)

```bash
# Add to ~/.zshrc:
alias wb='source ~/YTAI/environment/.venv_transcribe/bin/activate && python ~/YTAI/scripts/999_extra/whisper_batch.py'

# Then use:
wb "/path/to/folder" -f -l ru
```

---

## Version History

- **v2.3.0** — Organized folder output: `{name}_transcription/` subdirectory, smart project naming with `--name` and auto-detection from parent folder
- **v2.2.0** — Added Timecode column (first position), folder/file name as sheet name
- **v2.1.0** — Added audio file support (m4a, mp3, ogg, wav, flac, aac, opus)
- **v2.0.0** — Added preflight checks, soundfile audio loading, pyannote 3.x support, file numbering
- **v1.0.0** — Initial version with Whisper + pyannote

---

## License

MIT
