# video_review v1.3

Video review pipeline for finished YouTube videos. Analyze before publishing.

**EasyOCR** (text on screen) + **MiniCPM-V** (scene analysis) + **Whisper** (speech) + **ffmpeg** (audio levels) = comprehensive review report.

---

## Quick Start

```bash
# 1. Activate environment
source ~/YTAI/environment/.venv_transcribe/bin/activate

# 2. Start Ollama (Terminal 1)
OLLAMA_MAX_VRAM=20g ollama serve

# 3. Preflight check
python ~/YTAI/scripts/999_extra/video_review.py --preflight

# 4. Quick review (no Vision LLM)
python ~/YTAI/scripts/999_extra/video_review.py video.mp4 --quick

# 5. Full review
python ~/YTAI/scripts/999_extra/video_review.py video.mp4

# 6. Full review with cross-check
python ~/YTAI/scripts/999_extra/video_review.py video.mp4 \
  --transcript "$PROJECT/02_Transcripts/02_02_Clean/apply_names.txt"
```

---

## Installation

```bash
# Python packages
pip install easyocr Pillow numpy openpyxl openai-whisper torch pyannote.audio soundfile --break-system-packages

# ffmpeg
brew install ffmpeg

# Ollama + vision model
brew install ollama
ollama pull minicpm-v

# HuggingFace token (for speaker diarization)
export HF_TOKEN="hf_your_token_here"
```

Accept pyannote licenses:
- https://huggingface.co/pyannote/speaker-diarization-3.1
- https://huggingface.co/pyannote/segmentation-3.0

---

## Usage

```bash
# Preflight only
python video_review.py --preflight

# Quick (no Vision LLM)
python video_review.py video.mp4 --quick

# Full
python video_review.py video.mp4

# Visual only (no speech)
python video_review.py video.mp4 --skip-speech

# OCR + Audio only
python video_review.py video.mp4 --skip-speech --skip-vision

# With cross-check
python video_review.py video.mp4 --transcript path/to/apply_names.txt

# With channel context for Vision LLM
python video_review.py video.mp4 --vision-context "business in UAE"

# Resume after interruption
python video_review.py video.mp4 --resume

# Dry run
python video_review.py video.mp4 --dry-run
```

---

## Modes

| Feature | `--quick` | `--full` | `--skip-speech` | `--skip-vision` |
|---------|-----------|----------|-----------------|-----------------|
| Frame extraction | ✅ | ✅ | ✅ | ✅ |
| Scene detection | ✅ | ✅ | ✅ | ✅ |
| Black frame / jump cut | ✅ | ✅ | ✅ | ✅ |
| OCR (EasyOCR) | ✅ | ✅ | ✅ | ✅ |
| Text grouping | ✅ | ✅ | ✅ | ✅ |
| Vision LLM | ❌ | ✅ | ✅ | ❌ |
| Speech (Whisper) | ✅ | ✅ | ❌ | ✅ |
| Speaker diarization | ✅ | ✅ | ❌ | ✅ |
| Audio levels (LUFS) | ✅ | ✅ | ✅ | ✅ |
| Cross-check | ✅ | ✅ | ✅ | ✅ |
| **Mode label** | speech | full | vision | speech |
| **Est. time (20 min)** | ~12-15 min | ~20-30 min | ~10-15 min | ~12-15 min |

Mode label is computed dynamically: `full` (vision+speech), `vision` (vision only), `speech` (speech only), `basic` (neither).

---

## Output Files

```
YTCG37_Final_v2_review/
├── frames/                                # Extracted frames
│   ├── frame_0001_000000_00m00s.jpg
│   └── ...
│
├── _intermediate/                         # Resume cache
│   ├── frames.json                        # Frame list
│   ├── ocr.json                           # OCR results per frame
│   └── speech.json                        # Whisper transcript
│
├── YTCG37_Final_v2_review.xlsx            # ← MAIN REPORT
├── YTCG37_Final_v2_review.md              # Markdown
├── YTCG37_Final_v2_review.json            # Machine-readable
│
└── logs/
    └── review_20260217_143000.log         # Full session log
```

---

## Excel Report (5 sheets)

### Summary
Video metadata, analysis results, audio levels, tempo metrics, speaker balance, warning count, processing time.

### Timeline
One row per significant moment combining all data: Timecode, Scene #, OCR Text, Scene Description, Speech, Speaker, Flags. Warning rows highlighted yellow.

### Warnings
All issues sorted by timestamp: Timecode, Type, Severity, Detail.

Types: `black_frame`, `jump_cut`, `long_silence`, `clipping`, `audio_quiet`, `audio_loud`, `name_check`, `no_intro`, `no_end_screen`.

### On-Screen Text
Grouped text appearances: Start, End, Duration, Text, Frame Count.

### Speech
Full transcript: Timecode, End, Speaker, Text.

---

## Architecture

```
Phase 1: Frame Extraction (ffmpeg)
  ├─ Scene detection (threshold-based)
  ├─ Regular sampling (every N sec)
  ├─ Merge + dedup (scene priority)
  ├─ Black frame detection
  ├─ Jump cut detection
  └─ Early exit if 0 frames

Phase 2: OCR (EasyOCR, GPU→CPU fallback)
  ├─ Scan ALL frames
  ├─ Multi-language
  └─ Group into appearances (trigram ≥ 85%)

Phase 3: Vision LLM (Ollama)  [if enabled]
  ├─ Priority: text frames → scenes → every 5th
  ├─ Previous frame context for continuity
  └─ Generic prompt with optional --vision-context

Phase 4: Speech (Whisper + pyannote)  [if enabled + has audio]
  ├─ Audio extraction (16kHz mono WAV)
  ├─ Whisper transcription
  └─ Speaker diarization

Phase 5: Audio Levels (ffmpeg)  [if has audio]
  ├─ Loudness (LUFS, target: -14)
  ├─ True peak (clipping if > -1 dBTP)
  └─ Silence detection (>5s)

Phase 6: Cross-check  [if --transcript]
  └─ OCR names vs transcript speakers

Report: warnings + tempo + Excel/Markdown/JSON + phase timing table
```

### Key Design Decisions

**Frame origin tracking**: Merged timestamps preserve "scene" vs "regular" origin. Scene timestamps win over regular when close together.

**Sequential frame naming**: `frame_0001_000125_02m05s.jpg` — sequential index prevents filename collisions.

**EasyOCR GPU fallback**: Tries GPU, silently falls back to CPU if unavailable.

**Vision LLM context**: Each frame gets the previous frame's description for continuity awareness.

**No-audio guard**: Skips speech + audio phases when video has no audio track.

**Generic vision prompt**: No hardcoded channel context. Use `--vision-context` for domain-specific analysis.

---

## Resume Support

With `--resume`, completed phases are loaded from `_intermediate/`:

| Phase | Cache | Contents |
|-------|-------|----------|
| Frames | `frames.json` | Index, timestamp, source, filename |
| OCR | `ocr.json` | Detections, text, has_text per frame |
| Speech | `speech.json` | Full transcript segments |

Vision LLM and Audio are not cached (fast to re-run or depend on live model).

To force fresh run:
```bash
rm -rf video_name_review/_intermediate/
```

---

## Terminal Output

```
╔════════════════════════════════════════════════════════════════════════╗
║  VIDEO REVIEW — YTCG37_Final_v2                                      ║
╠════════════════════════════════════════════════════════════════════════╣
║  Duration:    19:42  │  Resolution: 3840×2160                        ║
║  Size:     2.14 GB   │  Codec: h264                                  ║
║  Mode:        full   │  Vision: minicpm-v                            ║
╠════════════════════════════════════════════════════════════════════════╣
║  WORK ESTIMATE                                                       ║
║  Frames: ~380    │  Vision frames: ~76                               ║
║  Est. time: ~25m 12s │  Est. disk: ~250 MB                           ║
║  Phases: Frames → OCR → Vision LLM → Speech → Audio                 ║
╚════════════════════════════════════════════════════════════════════════╝

Phase 1/5: Extracting frames
  ✅ Done (48s)

Phase 2/5: OCR — scanning text on screen
  ✅ Done (3m 7s)

Phase 3/5: Vision LLM — analyzing scenes (minicpm-v)
  ✅ Done (9m 15s)

Phase 4/5: Speech transcription (Whisper large-v3)
  ✅ Done (11m 30s)

Phase 5/5: Audio levels check
  ✅ Done (8s)

══════════════════════════════════════════════════════════════════════
RESULTS
══════════════════════════════════════════════════════════════════════
  Scenes:           52
  On-screen text:   8 appearances
  Speakers:         2 (SPEAKER_00, SPEAKER_01)
  ⚠️  Warnings:     3
     • 05:30  jump_cut: Quick cut 05:30 → 05:31 (0.8s gap)
     • 09:12  long_silence: Silence: 7.2s
     • 00:00  audio_quiet: Audio too quiet (-18.5 LUFS)

  Phase timing:
     Frames              48s
     OCR              3m 7s
     Vision           9m 15s
     Speech          11m 30s
     Audio                8s
     ──────────────────────────
     TOTAL           24m 48s

  Output: YTCG37_Final_v2_review/
  Excel:  YTCG37_Final_v2_review.xlsx
══════════════════════════════════════════════════════════════════════
```

---

## Options Reference

| Option | Default | Description |
|--------|---------|-------------|
| `input` | — | Video file to analyze |
| `--quick` | off | Skip Vision LLM |
| `--skip-speech` | off | Skip speech transcription |
| `--skip-vision` | off | Skip Vision LLM |
| `--resume` | off | Resume from cached phases |
| `--dry-run` | off | Show work estimate only |
| `--preflight` | off | Check dependencies only |
| `--skip-preflight` | off | Skip dependency checks |
| `-l`, `--language` | auto | Language code (en, ru, ar) |
| `-n`, `--num-speakers` | auto | Number of speakers |
| `-m`, `--whisper-model` | large-v3 | Whisper model size |
| `--vision-model` | minicpm-v | Ollama vision model |
| `--vision-context` | — | Channel context for prompt |
| `--interval` | 3 | Frame sampling interval (sec) |
| `--scene-threshold` | 0.3 | Scene sensitivity (0-1) |
| `--ocr-languages` | en,ru | OCR language codes |
| `--transcript` | — | Source transcript for cross-check |

---

## Performance (Mac M3 Pro 36GB, 20 min video)

| Phase | Time | Notes |
|-------|------|-------|
| Frame extraction | ~1 min | ~400 frames |
| OCR (EasyOCR) | ~2-3 min | GPU-accelerated |
| Vision LLM | ~8-12 min | ~60 frames |
| Speech (Whisper) | ~10-15 min | With diarization |
| Audio levels | ~10 sec | ffmpeg |
| **Total (--quick)** | **~12-15 min** | |
| **Total (--full)** | **~20-30 min** | |
| **Total (--skip-speech)** | **~10-15 min** | |

---

## Troubleshooting

### Ollama not running
```bash
curl http://localhost:11434/api/tags
OLLAMA_MAX_VRAM=20g ollama serve
```

### No audio in video
Auto-detected. Speech and audio phases are skipped automatically.

### OCR not detecting text
- Lower confidence: edit `OCR_CONFIDENCE_THRESHOLD` (default: 0.3)
- Add languages: `--ocr-languages en,ru,ar`

### Out of memory
- `--whisper-model medium`
- `--vision-model moondream`
- `--interval 5`
- `--skip-speech` or `--skip-vision`

### Resume after crash
```bash
python video_review.py video.mp4 --resume
# Skips: Frames (if cached), OCR (if cached), Speech (if cached)
```

### View logs
```bash
cat video_name_review/logs/review_*.log
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.3.0 | 2026-02-17 | Full resume (OCR+speech), generic vision prompt, `--vision-context`, empty frames guard, `out()` for log coverage, box alignment fix, estimate_work has_audio fix |
| 1.2.0 | 2026-02-17 | No-audio guard, mode label, per-phase timing, bbox fix, progress fix |
| 1.1.0 | 2026-02-17 | Renamed from video_qa, resume, logging, skip-speech/vision, work estimate |
| 1.0.0 | 2026-02-17 | Initial: OCR, Vision LLM, Speech, Audio, Warnings |
