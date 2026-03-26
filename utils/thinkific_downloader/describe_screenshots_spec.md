# Screenshot Descriptions Spec

## Purpose

`describe_screenshots.py` sends extracted screenshots to an Ollama vision model
and produces a structured JSON with text descriptions of each screenshot.

This is the bridge between raw scene-change captures and a knowledge base:
screenshots become searchable, indexable text.

The script lives in:

`/Users/romansergeev/YTAI/utils/thinkific_downloader`

## How It Fits Into the Pipeline

```text
1. Download video         → video.mp4
2. Extract screenshots    → screenshots/, screenshots_manifest.json
3. Describe screenshots   → screenshots_descriptions.json        ← THIS SCRIPT
4. Transcription          → _transcription/, _transcript.xlsx
5. Write manifest         → project_manifest.json
```

Stage 3 depends only on stage 2 output. If Ollama is unavailable, it
fails gracefully and the pipeline continues with stages 4+.

## Dependencies

- Python 3.11+
- Ollama running locally at `http://localhost:11434`
- Vision model pulled: `ollama pull minicpm-v`
- `download_thinkific.py` in the same directory (imported for shared utilities)

No pip packages required — uses only stdlib.

### Ollama Setup

```bash
# Install (macOS)
brew install ollama

# Start the server
ollama serve

# Pull the vision model
ollama pull minicpm-v
```

## Input

Primary input: a project directory containing `screenshots_manifest.json`
(produced by the screenshots extraction stage).

The manifest format:

```json
{
  "created_at": "2026-03-15T12:00:00Z",
  "source_video": "/abs/path/to/video.mp4",
  "scene_threshold": 0.18,
  "scene_max_width": 1600,
  "count": 15,
  "screenshots": [
    {
      "index": 1,
      "file": "scene_0001_t00-00-12.480.jpg",
      "path": "/abs/path/to/screenshots/scene_0001_t00-00-12.480.jpg",
      "timestamp_seconds": 12.48
    }
  ]
}
```

## Output

`screenshots_descriptions.json` in the same project directory.

```json
{
  "created_at": "2026-03-15T12:30:00Z",
  "source_manifest": "/abs/path/to/screenshots_manifest.json",
  "model": "minicpm-v",
  "count": 15,
  "errors_count": 0,
  "descriptions": [
    {
      "index": 1,
      "file": "scene_0001_t00-00-12.480.jpg",
      "path": "/abs/path/to/screenshots/scene_0001_t00-00-12.480.jpg",
      "timestamp_seconds": 12.48,
      "description": "TYPE: Text slide with bullet points...",
      "model": "minicpm-v"
    }
  ]
}
```

Each description entry includes:

| Field | Type | Description |
|-------|------|-------------|
| `index` | int | Sequential number matching the screenshot manifest |
| `file` | str | Screenshot filename |
| `path` | str | Absolute path to the screenshot file |
| `timestamp_seconds` | float or null | Video timestamp of the screenshot |
| `description` | str | AI-generated description or `"ERROR: ..."` on failure |
| `model` | str | Vision model used |

## Vision Prompt

The model receives a structured prompt asking for:

1. **TYPE** — slide type (text, bullets, diagram, talking head, demo, etc.)
2. **TEXT** — all visible text on screen
3. **TOPIC** — the key concept being shown
4. **VISUAL** — charts, diagrams, icons, highlights

When a previous frame description is available, the model also gets context
about what changed.

## CLI Reference

### Standalone usage

```bash
# Describe screenshots in a project directory
python3 describe_screenshots.py downloads/Phase_2_-_1._Intro/

# Use a different model
python3 describe_screenshots.py downloads/Phase_2_-_1._Intro/ --model llava

# Re-describe (overwrite existing descriptions)
python3 describe_screenshots.py downloads/Phase_2_-_1._Intro/ --force

# Preview without calling Ollama
python3 describe_screenshots.py downloads/Phase_2_-_1._Intro/ --dry-run
```

### Integrated with download_thinkific.py

```bash
# Full pipeline (download + screenshots + descriptions + transcription)
python3 download_thinkific.py <url> --title "Phase_2_-_1._Intro"

# Skip descriptions
python3 download_thinkific.py <url> --title "Phase_2_-_1._Intro" --no-descriptions

# Custom vision model
python3 download_thinkific.py <url> --title "Phase_2_-_1._Intro" --vision-model llava
```

### Integrated with process_docx_thinkific.py

```bash
# Full batch (all lessons with descriptions)
python3 process_docx_thinkific.py /path/to/YTCG.docx

# Batch without descriptions
python3 process_docx_thinkific.py /path/to/YTCG.docx --no-descriptions

# Process first 3 lessons only
python3 process_docx_thinkific.py /path/to/YTCG.docx --limit 3
```

### CLI options (standalone)

| Flag | Default | Description |
|------|---------|-------------|
| `project_dir` | required | Path to a lesson project directory |
| `--model` | `minicpm-v` | Ollama vision model name |
| `--force` | false | Overwrite existing descriptions |
| `--dry-run` | false | List screenshots without calling Ollama |

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Ollama not running | Print setup instructions, skip or exit |
| Model not pulled | Print `ollama pull <model>`, skip or exit |
| Single image fails | Record `"ERROR: ..."` in description, continue to next |
| File missing on disk | Record error, continue |
| Timeout (120s/image) | Record timeout error, continue |
| Already described | Skip unless `--force` (standalone) or fresh run (pipeline) |

In pipeline mode (called from download_thinkific.py or process_docx_thinkific.py),
failures are added to the project errors list and do not stop the overall pipeline.

## Non-Goals

- Semantic video understanding beyond individual frames
- OCR-specific pipelines (the vision model reads text as part of its analysis)
- Translation or summarization of descriptions
- Modifying any files outside `/Users/romansergeev/YTAI/utils/thinkific_downloader`
