# STACK.md — Technology Stack

## Languages

- **Python 3.11+** — Pipeline scripts (audio extraction, transcription, sync)
- **JavaScript (ES modules)** — Adobe UXP plugin (`scripts/05_editing/0500_uxp/`)
- **Node.js 18+** — UXP plugin runtime within Adobe Premiere Pro

## Runtimes & Environments

- **macOS with Apple Silicon (MPS)** — Primary platform
- **Python virtual environments:**
  - `.venv_transcribe` — Whisper/transcription dependencies
  - `.venv_ytai` — General pipeline dependencies
- **Adobe Premiere Pro 25.6+** — UXP plugin host

## Core Frameworks & Libraries

### Python
| Library | Version | Purpose |
|---|---|---|
| `openai-whisper` | v20250625 | Speech-to-text transcription |
| `mlx-whisper` | latest | Apple Silicon-optimized Whisper |
| `pyannote.audio` | 3.1.1 | Speaker diarization |
| `torch` (PyTorch) | 2.10.0 | ML inference backend |
| `huggingface_hub` | latest | Model downloads & auth |
| `soundfile` | latest | Audio I/O |
| `numpy` | latest | Numerical processing |
| `openpyxl` | latest | Excel file output |
| `requests` | latest | HTTP client (Ollama API) |
| `easyocr` | latest | OCR for screen content |
| `opencv` | latest | Image/video processing |
| `scikit-image` | latest | Image analysis |
| `ffmpeg` / `ffprobe` | system | Media processing & info |

### JavaScript (UXP)
- **Adobe UXP SDK** — Plugin API for Premiere Pro
- **Jest** — Unit testing framework
- No external npm dependencies beyond dev tooling

## Configuration

- **HuggingFace token** — Required for pyannote.audio model downloads
- **Ollama** — Optional local LLM at `localhost:11434` (model: `qwen2.5:32b`)
- **Environment variables** — Managed via `.env` files per script directory
- **`run_pipeline.py`** — Unified runner coordinating all pipeline stages

## Build & Tooling

- `package.json` in `scripts/05_editing/0500_uxp/` — Jest test runner
- No build step for Python (scripts run directly)
- UXP plugin loaded directly into Premiere Pro (no bundling)
