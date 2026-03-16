# INTEGRATIONS.md — External Services & APIs

## AI / ML Services

### OpenAI Whisper (Local)
- **Type:** Local ML model (no API key required)
- **Purpose:** Speech-to-text transcription of audio tracks
- **Variants:** Standard Whisper (`large-v3`) and MLX-optimized for Apple Silicon
- **Used in:** `scripts/02_transcribe/020101_transcribe/`

### Pyannote.audio (via HuggingFace)
- **Type:** Local ML model with HuggingFace Hub download
- **Purpose:** Speaker diarization — identifying who is speaking when
- **Auth:** HuggingFace token required (`HF_TOKEN` env var)
- **Model:** Downloaded on first run, cached locally
- **Used in:** `scripts/02_transcribe/`

### Ollama (Local LLM)
- **Type:** Local HTTP API
- **Endpoint:** `http://localhost:11434`
- **Model:** `qwen2.5:32b` (optional, for speaker analysis/labeling)
- **Purpose:** Optional LLM-assisted speaker identification
- **Auth:** None (local)

### HuggingFace Hub
- **Type:** Model hosting service
- **Purpose:** Downloading pyannote.audio and other ML models
- **Auth:** Token-based (`HF_TOKEN`)

## Media Processing

### ffmpeg / ffprobe (System)
- **Type:** CLI tools (system-installed)
- **Purpose:** Audio extraction, format conversion, media info extraction
- **Used in:** `scripts/01_prepare/0102_extract_audio/`
- **No API key required**

## Hardware / Platform

### Apple Silicon MPS
- **Type:** Hardware acceleration
- **Purpose:** GPU-accelerated ML inference via PyTorch MPS backend
- **Auto-detected** — falls back to CPU if unavailable

## Adobe Ecosystem

### Adobe Premiere Pro UXP Plugin
- **Type:** Host application integration
- **Purpose:** Timeline editing, sequence management, marker creation, caption import
- **API:** Adobe UXP SDK (JavaScript)
- **Version:** Premiere Pro 25.6+
- **Plugin location:** `scripts/05_editing/0500_uxp/`

## Camera / Device Integration

### Sony Camera XML Sidecars
- **Type:** File-based metadata
- **Format:** `NonRealTimeMeta` XML (`.xml` sidecar files)
- **Purpose:** Extracting recording metadata (timecodes, GPS, settings)
- **Used in:** `scripts/01_prepare/0103_sync_dji_audio/`

### DJI Audio Sync
- **Type:** File-based
- **Purpose:** Syncing DJI drone audio with main camera footage
- **Used in:** `scripts/01_prepare/0103_sync_dji_audio/`

## Storage

- **Local filesystem only** — No cloud storage detected
- No database integration
- No cloud APIs (AWS, GCP, Azure)
- No authentication providers
