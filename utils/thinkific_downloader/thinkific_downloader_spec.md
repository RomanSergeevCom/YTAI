# Thinkific Downloader Spec

## Purpose

`download_thinkific.py` is a local pipeline wrapper for Thinkific lessons.
It is designed to live only in:

`/Users/romansergeev/YTAI/utils/thinkific_downloader`

The script must:

1. Resolve a playable media URL from a Thinkific lesson URL or direct media URL.
2. Create a dedicated local project folder for the lesson.
3. Download the video into that project folder.
4. Trigger the existing YTAI transcription pipeline on the downloaded file.
5. Extract scene-change screenshots into a sibling folder inside the same project.

## Input Sources

Supported input forms:

- Thinkific lesson URL
- direct `.m3u8`
- direct `.mp4`
- Thinkific URL with `wvideo=...`

Resolution priority:

1. direct media URL if already present
2. `wvideo` Wistia ID from the URL
3. direct `.m3u8` / `.mp4` links in lesson HTML
4. Wistia IDs in lesson HTML

## Project Layout

For lesson title `Phase_2_-_1._Intro`:

```text
{output_dir}/
└── Phase_2_-_1._Intro/
    ├── Phase_2_-_1._Intro.mp4
    ├── Phase_2_-_1._Intro.info.json
    ├── Phase_2_-_1._Intro_transcript.xlsx
    ├── Phase_2_-_1._Intro_transcription/
    │   ├── Phase_2_-_1._Intro_transcript.json
    │   ├── Phase_2_-_1._Intro_transcript.srt
    │   ├── Phase_2_-_1._Intro_1_Ingest_captions.srt
    │   └── ...
    ├── screenshots/
    │   ├── scene_0001_t00-00-12.480.jpg
    │   └── ...
    ├── screenshots_manifest.json
    └── project_manifest.json
```

Rules:

- video lives in the project root
- transcription outputs live next to the video
- screenshots live in a dedicated `screenshots/` subfolder
- project-level metadata is written to `project_manifest.json`

## Download Stage

Download backends:

- `ffmpeg`
- `yt-dlp`
- `auto` -> prefer `yt-dlp` if installed, else `ffmpeg`

Metadata:

- `{video_stem}.info.json` stores source page, resolved media URL, title, engine, and video path

## Transcription Stage

The downloader does not re-implement transcription internals.
It calls the existing pipeline:

- script:
  `/Users/romansergeev/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py`
- default Python:
  `/Users/romansergeev/YTAI/environment/.venv_transcribe/bin/python3`

Invocation pattern:

```bash
python3 transcribe_project.py --project "/abs/path/to/video.mp4" -y
```

Optional passthrough flags:

- `-n / --speakers`
- `-m / --model`
- `--language`

Expected output behavior:

- xlsx next to the video
- `_transcription/` folder next to the video

## Screenshots Stage

Screenshots are extracted by `ffmpeg` using scene detection.

Heuristic:

- use `select='gt(scene,THRESHOLD)'`
- optional scaling down to `--scene-max-width`
- save sequential `.jpg` images
- rename them to include timestamps when available from `showinfo`

Important limitation:

- this is visual change detection, not semantic understanding
- it catches slide changes, graphics, edits, illustrations, layout changes
- it may miss subtle graphic changes
- it may over-capture if the threshold is too low

Outputs:

- `screenshots/`
- `screenshots_manifest.json`

## CLI Contract

Main options:

- `source`
- `--output-dir`
- `--title`
- `--cookie-header`
- `--cookie-file`
- `--engine`
- `--download-only`
- `--no-transcribe`
- `--no-screenshots`
- `-n / --speakers`
- `-m / --model`
- `--language`
- `--transcribe-python`
- `--transcribe-script`
- `--scene-threshold`
- `--scene-max-width`
- `--dry-run`

## Failure Handling

If a stage fails:

- the script writes `project_manifest.json`
- the manifest includes `errors[]`
- download failure stops all later stages
- screenshot or transcription failures are surfaced clearly

## Non-Goals

- DRM bypass
- generalized course crawling
- semantic image understanding
- modifying any files outside `/Users/romansergeev/YTAI/utils/thinkific_downloader`
