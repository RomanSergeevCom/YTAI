# 020101_transcribe v3.1 — Specification

## Overview

Transcription v3.1 (based on v3.0): word-level timestamps, Premiere Transcript JSON, global diarization.
Generates ingest JSON for UXP Premiere plugin (020201_premiere_ingest).
Parses Sony camera XML sidecars (NonRealTimeMeta) for camera/lens/color metadata.

**Script:** ~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py
**Version:** 3.1
**Dependencies:** whisper, pyannote.audio, torch, ffmpeg, openpyxl, soundfile, numpy

---

## Changes from v3.0

1. **Camera XML sidecars:** Parses Sony `{clip}M01.XML` files — extracts device, lens, gamma, color primaries, LUT, LTC timecode, UMID.
2. **XML moved to per_clip/:** Sidecars are relocated from source directory to `per_clip/{clip_id}/` during Stage 1.
3. **camera_meta block:** Added to transcript.json (per-clip), meta.json (summary), XLSX Media sheet (6 new columns).
4. **Extended ffprobe fields:** `color_primaries`, `color_transfer`, `color_space`, `display_aspect_ratio`, `sample_aspect_ratio`, `audio_channel_layout`, `rotation`.
5. **captions_srt:** Added to ingest JSON files block.

## Changes from v2.16

1. **Output paths:** JSON and SRT now inside `_transcription/`. Only xlsx stays next to video files.
2. **Stage 5b (prproj) removed.** Premiere project created via UXP plugin (020201_premiere_ingest).
3. **Stage 6 (new):** Generates ingest JSON (`{project}_ingest.json`) for UXP plugin.
4. **`--multicam` flag:** Multi-camera without master files (replaces `--no-prproj`).

---

## Environment

    source ~/YTAI/environment/.venv_transcribe/bin/activate

    # Flat project
    python ~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py \
      --project "/path/to/Interview" -n 2 -y

    # Multi-camera (no master files)
    python ~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py \
      --project "/path/to/MultiCam" -n 2 --multicam -y

    # Multi-folder (with master files, default)
    python ~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py \
      --project "/path/to/YTCG_Project" -n 2 -y

    # Re-generate ingest JSON only
    python ~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py \
      --project "/path/to/Interview" --stages 6

    # Dry-run
    python ~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py \
      --project "/path/to/Interview" --dry-run

**Python venv:** `~/YTAI/environment/.venv_transcribe`
**HuggingFace token:** auto-detected from `~/.huggingface/token` or `~/.cache/huggingface/token`
**Whisper model:** large-v3 (default)
**Device:** Apple Silicon MPS (auto-detected)

---

## Parameters

    --project PATH      folder or file (required)
    -n NUM              number of speakers (optional, auto-detect if omitted)
    -m MODEL            Whisper model (default: large-v3)
    -y                  skip confirmations
    --language LANG     language (default: auto-detect)
    --resume            continue from last completed stage
    --stages 3,4,5      run only specified stages (valid: 1, 2, 3, 4, 5, 6)
    --multicam          multi-camera without master files
    --dry-run           show plan without executing

---

## Folder Structure

### Variant A: Flat project

    Interview/
    +-- *.MP4 (video files)
    +-- Interview_transcript.xlsx              <- ONLY file next to video
    +-- Interview_transcription/
        +-- Interview_transcript.json
        +-- Interview_transcript.srt
        +-- Interview_1_Ingest_captions.srt
        +-- Interview_ingest.json
        +-- full_audio.wav
        +-- clip_offsets.json
        +-- diarization.json
        +-- speakers.json
        +-- combined_transcript.json
        +-- meta.json
        +-- *_transcribe_*.log
        +-- per_clip/
            +-- C5090/
                +-- C5090_audio.wav
                +-- C5090_whisper_raw.json
                +-- C5090_transcript.json
                +-- C5090_transcript.srt
                +-- C5090_transcript.txt
                +-- C5090_premiere_transcript.json
                +-- C5090M01.XML              <- camera XML sidecar (moved from source dir, if present)

### Variant B: Single file

    SomeFolder/
    +-- C5090.MP4
    +-- C5090_transcript.xlsx                  <- ONLY file next to video
    +-- C5090_transcription/
        +-- C5090_transcript.json
        +-- C5090_transcript.srt
        +-- C5090_ingest.json
        +-- ...

### Variant C: Subfolders with `--multicam` (multi-camera)

Cameras record the same event. Master files NOT needed — content is duplicated.

    YTCG Gambling Ru/
    +-- FX3/                                        <- camera 1
    |   +-- RYA-FX3-0090.MP4, ...
    |   +-- FX3_transcript.xlsx
    |   +-- FX3_transcription/
    |       +-- FX3_transcript.json
    |       +-- FX3_transcript.srt
    |       +-- FX3_ingest.json                     <- per-camera ingest
    |       +-- per_clip/
    |           +-- RYA-FX3-0090/
    |               +-- RYA-FX3-0090_audio.wav
    |               +-- RYA-FX3-0090_transcript.json
    |               +-- RYA-FX3-0090_transcript.srt
    |               +-- RYA-FX3-0090_transcript.txt
    |               +-- RYA-FX3-0090_premiere_transcript.json
    |               +-- RYA-FX3-0090M01.XML         <- camera XML sidecar
    +-- ZVE1/                                       <- camera 2
    |   +-- RYA-ZVE1-1674.MP4, ...
    |   +-- ZVE1_transcript.xlsx
    |   +-- ZVE1_transcription/
    |       +-- ZVE1_transcript.json
    |       +-- ZVE1_transcript.srt
    |       +-- ZVE1_ingest.json
    |       +-- per_clip/...
    +-- YTCG Gambling Ru_transcription/             <- internal (NO master xlsx/json/srt/ingest)
        +-- full_audio.wav
        +-- clip_offsets.json
        +-- diarization.json
        +-- speakers.json
        +-- meta.json
        +-- *.log

### Variant D: Subfolders without `--multicam` (multi-folder, default)

Folders are different parts of the project. Master files ARE needed.

    YTCG Gambling Ru/
    +-- Part1/
    |   +-- *.MP4
    |   +-- Part1_transcript.xlsx
    |   +-- Part1_transcription/
    |       +-- Part1_transcript.json
    |       +-- Part1_transcript.srt
    |       +-- per_clip/...
    +-- Part2/
    |   +-- *.MP4
    |   +-- Part2_transcript.xlsx
    |   +-- Part2_transcription/...
    +-- YTCG Gambling Ru_transcript.xlsx            <- MASTER xlsx (combined)
    +-- YTCG Gambling Ru_transcription/
        +-- YTCG Gambling Ru_transcript.json        <- master JSON
        +-- YTCG Gambling Ru_transcript.srt         <- master SRT
        +-- YTCG Gambling Ru_ingest.json            <- master ingest (for UXP)
        +-- full_audio.wav
        +-- clip_offsets.json
        +-- diarization.json
        +-- speakers.json
        +-- combined_transcript.json
        +-- meta.json
        +-- *.log

### `--multicam` vs default comparison

| | `--multicam` | Default (multi-folder) |
|---|---|---|
| Master xlsx | No | Yes, in root |
| Master JSON/SRT | No | Yes, in `_transcription/` |
| Master ingest | No | Yes, in `_transcription/` |
| Per-folder xlsx | Yes | Yes |
| Per-folder JSON/SRT | Yes | Yes |
| Per-folder ingest | Yes (per-camera) | No (master only) |
| Shared diarization | Yes | Yes |

### Recursive pattern (each level)

    {folder}/
    +-- video files
    +-- {folder_name}_transcript.xlsx      <- only file next to video
    +-- {folder_name}_transcription/
        +-- {folder_name}_transcript.json
        +-- {folder_name}_transcript.srt
        +-- {folder_name}_1_Ingest_captions.srt
        +-- {folder_name}_ingest.json
        +-- per_clip/...

---

## Pipeline

    Preflight:
      ffmpeg/ffprobe check, load ML models, scan media info via ffprobe,
      parse camera XML sidecars (Sony NonRealTimeMeta) -> ctx["clip_camera_meta"]

    Stage 1: Extract Audio
      Per clip -> WAV (16kHz mono) + concatenate -> full_audio.wav + clip_offsets.json
      Move camera XML sidecars ({clip}M01.XML) from source dir to per_clip/{clip_id}/

    Stage 2: Global Diarization
      pyannote on full_audio.wav -> speaker intervals [start, end, SPEAKER_XX]

    Stage 3: Per-clip Whisper
      word_timestamps=True per clip -> words with local timecodes

    Stage 4: Speaker Mapping
      Local word -> global timecode -> speaker via diarization

    Stage 5: Generate Outputs
      xlsx (with camera_meta columns on Media sheet),
      SRT, captions SRT, TXT, internal JSON, Premiere JSON,
      transcript.json (with per-clip camera_meta block),
      meta.json (with camera_meta summary)
      JSON and SRT -> inside _transcription/ (changed from v2.16)
      Multi-camera: per-camera XLSX + transcript.json

    Stage 6: Generate Ingest JSON
      ingest_json.generate() -> {transcription_dir}/{project}_ingest.json

Stage 5b (prproj) from v2.16 removed. Premiere project via UXP plugin (020201_premiere_ingest).

---

## Camera XML (Sony NonRealTimeMeta)

Sony cameras produce `{clip_stem}M01.XML` sidecar files next to each video clip. These contain metadata **not available via ffprobe**.

### Search pattern

For each video file `{clip_stem}.MP4`, looks for `{clip_stem}M01.XML` in the same directory.

### Extracted fields

| XML Element | Field | Example | Purpose |
|---|---|---|---|
| `Device` | device, device_manufacturer, device_model, device_serial | Sony ILME-FX3A | Camera identification for multicam |
| `Lens` | lens | FE 50mm F1.2 GM | FOV, shot matching, grouping |
| `CaptureGammaEquation` | gamma | s-log3-cine | Exact log profile for LUT selection |
| `CaptureColorPrimaries` | color_primaries | s-gamut3-cine | Exact color space for grading |
| `CodingEquations` | coding_equations | rec709 | Encoding matrix |
| `RelevantFiles` (LUT) | lut | SL3SG3Ctos709.cube | Camera-recommended LUT |
| `LtcChangeTable` | ltc_start, ltc_fps | 23:24:57:08, 25 | Frame-accurate timecode for multicam sync |
| `CreationDate` | creation_date | 2026-03-06T09:26:08+03:00 | Precise timestamp with timezone |
| `TargetMaterial` | umid | 060A2B34... | Globally unique clip identifier |
| `Duration` | duration_frames | 55116 | Duration in frames (more precise than seconds) |
| `VideoFrame` | video_codec_full, capture_fps | AVC140_3840_2160_H422P@L51, 25.00p | Full codec profile |
| `AudioFormat` | audio_codec_xml, audio_channels_xml | LPCM16, 2 | Audio format details |
| `RecordingMode` | recording_mode | normal | Recording mode (normal, cache) |

### Output targets

**transcript.json** — per-clip `camera_meta` block:
```json
{
  "clips": [{
    "clip_id": "RYA-FX3-0099",
    "media": { ... },
    "camera_meta": {
      "device": "Sony ILME-FX3A",
      "device_serial": "4294967295",
      "lens": "FE 50mm F1.2 GM",
      "gamma": "s-log3-cine",
      "color_primaries": "s-gamut3-cine",
      "coding_equations": "rec709",
      "lut": "SL3SG3Ctos709.cube",
      "ltc_start": "23:24:57:08",
      "ltc_fps": 25,
      "creation_date": "2026-03-06T09:26:08+03:00",
      "umid": "060A2B34...",
      "duration_frames": 444,
      "video_codec_full": "AVC140_3840_2160_H422P@L51",
      "xml_source": "per_clip/RYA-FX3-0099/RYA-FX3-0099M01.XML"
    }
  }]
}
```

**meta.json** — summary camera_meta:
```json
{
  "camera_meta": {
    "device": "Sony ILME-FX3A",
    "lens": "FE 50mm F1.2 GM",
    "gamma": "s-log3-cine",
    "color_primaries": "s-gamut3-cine",
    "coding_equations": "rec709",
    "lut": "SL3SG3Ctos709.cube",
    "sidecars_found": 2
  }
}
```

**XLSX Media sheet** — 6 additional columns: Camera, Lens, Gamma, Color Space, LTC Start, LUT.

### Backward compatibility

If no XML sidecars are found next to video files, the pipeline works exactly as before. The `camera_meta` block is simply omitted from outputs.

---

## Media Metadata (ffprobe)

`get_media_info()` extracts the following fields via `ffprobe -print_format json -show_format -show_streams`:

| Category | Fields | Used for |
|---|---|---|
| **Video** | width, height, fps, fps_raw, nb_frames | Sequence settings in Premiere |
| **Video codec** | video_codec, video_profile, video_bitrate, pix_fmt, bits_per_raw_sample, color_range | XLSX and logs |
| **Video color** | color_primaries, color_transfer, color_space | Color pipeline verification |
| **Video geometry** | display_aspect_ratio, sample_aspect_ratio, rotation | Aspect ratio and orientation |
| **Audio** | audio_codec, audio_channels, audio_sample_rate, audio_bits_per_sample, audio_channel_layout | Audio settings |
| **File** | duration, file_size, overall_bitrate | Pipeline planning, XLSX |
| **Metadata** | creation_time, timecode | XLSX Media sheet |

---

## Ingest JSON Contract

File: `{transcription_dir}/{project}_ingest.json`

```json
{
    "version": "1.0",
    "type": "ingest",
    "project_name": "Interview",
    "created_at": "2026-03-08T12:00:00Z",
    "media": {
        "width": 3840,
        "height": 2160,
        "fps": 25.0,
        "sample_rate": 48000
    },
    "clips": [
        {
            "clip_id": "C5402",
            "filename": "C5402.MP4",
            "path": "/abs/Interview/C5402.MP4",
            "duration": 156.0,
            "offset": 0.0,
            "premiere_transcript": "/abs/Interview_transcription/per_clip/C5402/C5402_premiere_transcript.json"
        }
    ],
    "files": {
        "transcript_json": "/abs/Interview_transcription/Interview_transcript.json",
        "transcript_srt": "/abs/Interview_transcription/Interview_transcript.srt",
        "transcript_xlsx": "/abs/Interview_transcript.xlsx",
        "captions_srt": "/abs/Interview_transcription/Interview_1_Ingest_captions.srt"
    },
    "source_folder": "/abs/Interview"
}
```

Fields:
- `media` — resolution, FPS, sample_rate from first clip
- `clips[]` — absolute paths to video and premiere transcript JSON
- `clips[].offset` — clip offset in concatenated audio (for diarization)
- `files` — absolute paths to combined transcript JSON, SRT, captions SRT, XLSX
- `source_folder` — project root folder

---

## Module: ingest_json.py

File: `~/YTAI/scripts/02_transcribe/020101_transcribe/ingest_json.py`

```python
from ingest_json import generate
ingest_path = generate(Path("/path/to/Interview_transcription/Interview_transcript.json"))
```

Reads `{project}_transcript.json` (inside `_transcription/`), generates `{project}_ingest.json` alongside it.

Can be run standalone:

    python ingest_json.py /path/to/Interview_transcription/Interview_transcript.json

---

## Project Structure

    ~/YTAI/scripts/02_transcribe/020101_transcribe/
    +-- transcribe_project.py              # Main pipeline script
    +-- ingest_json.py                     # Module: ingest JSON generation
    +-- 020101_transcribe_spec.md          # This specification
