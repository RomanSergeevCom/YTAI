# Premiere Pro Edit Brief Generator

Automated video editing preparation pipeline: Transform transcription analysis into Premiere Pro sequences with markers, subclips, and organized bins.

## Overview

```
[Transcription XLSX]  +  [Video Files]
         ↓                     ↓
    Claude Analysis      FFprobe metadata
         ↓                     ↓
         └─────────┬───────────┘
                   ↓
        [edit_brief.xlsx]
         (Edit Decision List)
                   ↓
     01_generate_premiere_xml.py
                   ↓
        [project.xml]
                   ↓
    ┌──────────────┼──────────────┐
    ↓              ↓              ↓
 Sequence       Markers       Subclips
 with cuts    on timeline     in bins
```

## Quick Start

```bash
# Generate Premiere XML from edit brief
python 01_generate_premiere_xml.py --input edit_brief.xlsx --output project.xml

# With custom source folder
python 01_generate_premiere_xml.py --input edit_brief.xlsx --source "/Volumes/RYA/Footage"

# Validate edit brief without generating
python 01_generate_premiere_xml.py --input edit_brief.xlsx --validate-only
```

## File Structure

```
05_editing/
├── README.md                      # This file
├── edit_brief_schema.md           # Detailed column specifications
├── 01_generate_premiere_xml.py    # Main script
├── templates/
│   └── edit_brief_template.xlsx   # Empty template
└── examples/
    └── example_edit_brief.xlsx    # Filled example
```

## Edit Brief Format (XLSX)

The edit brief is an Excel file with 2 sheets:

### Sheet 1: `segments`

Main table containing all video segments for the edit.

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `segment_id` | string | auto | Unique ID (seg_001, seg_002...) |
| `source_file` | string | ✅ | Video filename (RYA-ZVE1-1358.MP4) |
| `tc_in` | string | ✅ | Start timecode (MM:SS.ms or HH:MM:SS:FF) |
| `tc_out` | string | ✅ | End timecode |
| `block` | int | ✅ | Block/chapter number (1, 2, 3...) |
| `block_name` | string | ✅ | Block name (Introduction, Diagnosis...) |
| `segment_name` | string | | Segment description |
| `speaker` | string | | Speaker name |
| `transcript` | string | | Text content (first 200 chars) |
| `track` | string | | V1 (default), V2, V3 |
| `color` | string | | Clip label color |
| `use` | bool | | TRUE = include in sequence |
| `priority` | int | | 1 = best take (for duplicates) |
| `is_chapter` | bool | | TRUE = YouTube chapter marker |
| `broll_note` | string | | B-roll suggestion |
| `notes` | string | | Editor notes |

### Sheet 2: `project`

Project metadata and settings.

| Key | Value | Description |
|-----|-------|-------------|
| `project_name` | YT RF - Patient Story | Project/sequence name |
| `fps` | 29.97 | Frame rate |
| `width` | 3840 | Frame width |
| `height` | 2160 | Frame height |
| `sample_rate` | 48000 | Audio sample rate |
| `source_folder` | /Volumes/RYA/Footage | Path to source files |
| `video_tracks` | 3 | Number of video tracks |
| `audio_tracks` | 4 | Number of audio tracks |
| `create_subclips` | TRUE | Create subclips in bins |
| `create_bins` | TRUE | Organize by blocks |
| `create_chapter_markers` | TRUE | Add YouTube chapter markers |
| `include_unused` | TRUE | Include unused segments in Unused bin |
| `nested_sequences` | FALSE | Create nested sequence per block |

## What Gets Generated

### Premiere Pro Project Structure

```
📁 Project Panel
├── 📁 01_Sources
│   ├── RYA-ZVE1-1356.MP4
│   ├── RYA-ZVE1-1357.MP4
│   ├── RYA-ZVE1-1358.MP4
│   ├── RYA-ZVE1-1359.MP4
│   └── RYA-ZVE1-1360.MP4
│
├── 📁 02_Blocks
│   ├── 📁 Block_01_Introduction
│   │   ├── seg_001_Intro_Main [Subclip 17:40-17:52]
│   │   └── seg_002_Intro_Cont [Subclip 17:52-17:59]
│   ├── 📁 Block_02_Beginning
│   │   ├── seg_003_Student_Years [Subclip]
│   │   └── ...
│   └── 📁 Block_14_Closing
│
├── 📁 03_Alternatives
│   └── [Segments with priority > 1]
│
├── 📁 04_Unused
│   └── [Segments with use=FALSE]
│
└── 🎬 MAIN_Edit_v1 [Sequence]
```

### Timeline Structure

```
Timeline: MAIN_Edit_v1
┌─────────────────────────────────────────────────────────────────┐
│ V3: [Empty - for titles/graphics]                               │
├─────────────────────────────────────────────────────────────────┤
│ V2: [B-roll placeholders where broll_note is set]               │
├─────────────────────────────────────────────────────────────────┤
│ V1: [seg_001][seg_002][seg_003][seg_004][seg_005]...           │
├─────────────────────────────────────────────────────────────────┤
│ A1: [Linked audio from V1]                                      │
├─────────────────────────────────────────────────────────────────┤
│ A2: [Empty - for music]                                         │
├─────────────────────────────────────────────────────────────────┤
│ A3: [Empty - for SFX]                                           │
├─────────────────────────────────────────────────────────────────┤
│ A4: [Empty - for VO]                                            │
└─────────────────────────────────────────────────────────────────┘

Markers:
🟢 00:00:00:00 ─ BLOCK 1: Introduction
🟡 00:00:32:15 ─ BLOCK 2: Beginning
🟡 00:01:45:00 ─ BLOCK 3: Diagnosis
🔵 00:03:20:10 ─ BLOCK 4: What is GERD
🟠 00:04:15:00 ─ BLOCK 5: Symptoms
...
📍 00:00:00:00 ─ CHAPTER: Introduction (YouTube)
📍 00:01:45:00 ─ CHAPTER: My Diagnosis Story (YouTube)
```

## Marker Colors

| Color | Code | Usage |
|-------|------|-------|
| Cyan | 0 | Timeline, current state |
| Blue | 1 | Explanations, education |
| Green | 2 | Introduction, solution, positive |
| Yellow | 3 | Diagnosis, procedures |
| Red | 4 | Danger, risks, warnings |
| Magenta | 5 | Surgery, medical procedures |
| Orange | 6 | Symptoms, life examples |
| Purple | 7 | Treatment, medication |

## Timecode Formats

The script accepts multiple timecode formats:

| Format | Example | Notes |
|--------|---------|-------|
| MM:SS | 06:34 | Minutes:Seconds |
| MM:SS.ms | 06:34.5 | With milliseconds |
| HH:MM:SS | 00:06:34 | Hours:Minutes:Seconds |
| HH:MM:SS:FF | 00:06:34:15 | With frames |
| Seconds | 394.5 | Raw seconds |

## Workflow

### Step 1: Create Edit Brief from Transcription

You provide transcription XLSX to Claude, Claude analyzes and generates:
- `edit_brief.xlsx` - Structured edit decision list
- `edit_brief.md` - Human-readable summary

### Step 2: Review and Adjust

Open `edit_brief.xlsx` in Excel/Google Sheets:
- Adjust timecodes if needed
- Change block order
- Mark segments as use=FALSE to exclude
- Add b-roll notes
- Set priorities for alternate takes

### Step 3: Generate Premiere XML

```bash
python 01_generate_premiere_xml.py --input edit_brief.xlsx --output project.xml
```

### Step 4: Import to Premiere Pro

1. File → Import
2. Select `project.xml`
3. Sequence and bins appear in project
4. Relink media if paths differ (Right-click → Link Media)

## Command Line Options

```
usage: 01_generate_premiere_xml.py [-h] --input INPUT [--output OUTPUT]
                                    [--source SOURCE] [--validate-only]
                                    [--verbose]

options:
  --input, -i       Path to edit_brief.xlsx (required)
  --output, -o      Output XML path (default: premiere_project.xml)
  --source, -s      Override source folder path
  --validate-only   Check edit brief without generating XML
  --verbose, -v     Show detailed progress
```

## Sequence Settings (Default)

```
General
  Editing Mode: Custom
  Timebase: 29.97 fps

Video Settings
  Frame Size: 3840 x 2160 (4K UHD)
  Pixel Aspect Ratio: Square Pixels (1.0)
  Fields: No Fields (Progressive Scan)

Audio Settings
  Sample Rate: 48000 Hz
  
Tracks
  Video: V1, V2, V3
  Audio: A1 (Standard), A2 (Standard), A3 (Standard), A4 (Standard)
```

## Requirements

```bash
pip install openpyxl
```

Optional (for video duration detection):
```bash
brew install ffmpeg  # macOS
apt install ffmpeg   # Linux
```

## Error Handling

The script validates:
- All required columns present
- Timecode format validity
- Source files exist (warning if not)
- No overlapping segments on same track
- Block numbers are sequential

## Integration with YTAI Pipeline

This script is part of the YTAI YouTube production pipeline:

```
02_transcribe/     → Whisper transcription
03_speaker_id/     → Speaker diarization
04_video_analysis/ → Scene detection, emotions
05_editing/        → THIS: Edit brief → Premiere XML
06_thumbnails/     → Title and thumbnail generation
07_shorts/         → Shorts extraction
08_youtube/        → Description, chapters, tags
```

## License

Internal tool for RYA.AE / Connect Group Dubai
