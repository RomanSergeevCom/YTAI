# YTAI Project Folder Structure v3.0

## Quick Start

### Option 1: Use Script
```bash
# Type 1: Footage
python /Users/romansergeev/YTAI/YTAI_Folder_Templates/create_folders.py -f "/path/to/folder"

# Type 2: Production
python /Users/romansergeev/YTAI/YTAI_Folder_Templates/create_folders.py -p "/path/to/folder"
```

### Option 2: Copy Templates Manually
```bash
# Type 1: Footage
cp -r /Users/romansergeev/YTAI/YTAI_Folder_Templates/Type1_Footage "/path/to/20250125_Interview"

# Type 2: Production
cp -r /Users/romansergeev/YTAI/YTAI_Folder_Templates/Type2_Production "/path/to/YTRF01_My_Video"
```

---

## Templates Location

```
/Users/romansergeev/YTAI/YTAI_Folder_Templates/
├── YTAI_Folder_Structure.md      # This documentation
├── create_folders.py             # Script (optional)
├── Type1_Footage/                # Template folder
└── Type2_Production/             # Template folder
```

**To modify templates:** Edit the folders directly in `YTAI_Folder_Templates/`

---

## Type 1: Footage

Single shooting day. For reviewing what was shot.

```
Type1_Footage/
├── 01_Media/
│   └── Source/
│       ├── Video/               # Camera files (*.MP4)
│       ├── Audio/               # DJI synced WAV (pipeline creates)
│       ├── Transcription/       # Transcripts & per-clip data
│       ├── Setup/
│       │   └── logs/            # Script execution logs
│       └── LUT/                 # Color correction (*.cube)
├── 02_Exports/
│   └── *.mp4
└── 99_Pipeline/
    └── DJI_Audio/               # Original DJI TX/MIC WAV (archive)
```

---

## Type 2: Production

Full project. Type 1 folders go inside `01_Media/Source/`.

```
Type2_Production/
├── PROJECT_NAME.gdoc                    # Rename to: {YourProject}.gdoc
│
├── 01_Media/
│   ├── Source/                          # PIPELINE CREATES
│   │   ├── Video/                       # Camera MP4 (from SD card)
│   │   ├── Audio/                       # DJI synced WAV (pipeline creates)
│   │   ├── Transcription/              # Transcripts, per_clip/, FULL_AUDIO
│   │   │   └── per_clip/{clip_id}/     # Per-clip transcripts & SRT
│   │   ├── Setup/                       # UXP control center
│   │   │   ├── {project}_ingest.json   # UXP Ingest entry point
│   │   │   ├── {project}_edit_brief.json
│   │   │   ├── ScreenCues/             # PNG overlays
│   │   │   └── logs/                   # All script logs
│   │   ├── LUT/                        # Color correction (*.cube)
│   │   └── PROJECT_NAME_Source.prproj  # Rename to: {project}_Source.prproj
│   │
│   ├── Assets/                          # EDITOR ADDS
│   │   ├── Music/
│   │   ├── SFX/
│   │   ├── Graphics/
│   │   ├── Stock/
│   │   └── Fonts/
│   │
│   └── PROJECT_NAME.prproj             # Rename to: {project}.prproj
│
├── 02_Exports/
│   └── *.mp4
│
├── 03_Shorts/
│
├── 04_Thumbnail/
│   ├── prompts/
│   ├── drafts/
│   └── thumbnail.png
│
├── YouTube/
│   ├── video.mp4
│   ├── thumbnail.png
│   ├── description.txt
│   ├── chapters.txt
│   └── tags.txt
│
└── 99_Pipeline/
    └── DJI_Audio/                       # Original DJI TX/MIC WAV (archive)
```

**After copying, rename:**
1. `PROJECT_NAME.gdoc` -> `{YourProject}.gdoc`
2. `01_Media/Source/PROJECT_NAME_Source.prproj` -> `01_Media/Source/{YourProject}_Source.prproj`
3. `01_Media/PROJECT_NAME.prproj` -> `01_Media/{YourProject}.prproj`

---

## Workflow

```
Type 1                                Type 2
------                                ------

01_Media/Source/
  ├── Video/*.MP4  ──────┐
  ├── Audio/*.WAV  ──────┤
  └── LUT/*.cube  ──────┤
                         ├──>  01_Media/
                         │       ├── Source/
                         │       │   ├── Video/
99_Pipeline/             │       │   ├── Audio/
  └── DJI_Audio/*.wav ──┘       │   ├── Transcription/
                                │   ├── Setup/
                                │   └── {project}_Source.prproj
                                ├── Assets/
                                └── {project}.prproj
```

**Steps:**
1. Film -> Copy `Type1_Footage` -> rename -> add MP4 to `01_Media/Source/Video/`
2. Copy DJI WAV to `99_Pipeline/DJI_Audio/`
3. Run pipeline -> `01_Media/Source/Transcription/`
4. Approve -> Copy `Type2_Production` -> rename folder
5. Rename `.gdoc`, `_Source.prproj`, `.prproj`
6. Copy footage -> `01_Media/Source/Video/`
7. Edit -> Export to `02_Exports/`
8. Thumbnail -> `04_Thumbnail/`
9. Publish -> `YouTube/`

---

## Comparison

| # | Type 1 | Type 2 |
|---|--------|--------|
| - | - | `PROJECT_NAME.gdoc` (rename) |
| 01 | `01_Media/Source/Video/` | `01_Media/Source/Video/` |
| 01 | `01_Media/Source/Audio/` | `01_Media/Source/Audio/` |
| 01 | `01_Media/Source/Transcription/` | `01_Media/Source/Transcription/` |
| 01 | `01_Media/Source/Setup/` | `01_Media/Source/Setup/` |
| 01 | `01_Media/Source/LUT/` | `01_Media/Source/LUT/` |
| 01 | - | `01_Media/Source/*_Source.prproj` (rename) |
| 01 | - | `01_Media/Assets/` |
| 01 | - | `01_Media/*.prproj` (rename) |
| 02 | `02_Exports/` | `02_Exports/` |
| 03 | - | `03_Shorts/` |
| 04 | - | `04_Thumbnail/` |
| - | - | `YouTube/` |
| 99 | `99_Pipeline/DJI_Audio/` | `99_Pipeline/DJI_Audio/` |

---

## Log Files

When using the script, logs are created automatically:
```
01_Media/Source/Setup/logs/20250125_143022_folder_created.log
```

---

## Commands Summary

```bash
# Type 1 (Script)
python /Users/romansergeev/YTAI/YTAI_Folder_Templates/create_folders.py -f "/path"

# Type 1 (Manual)
cp -r /Users/romansergeev/YTAI/YTAI_Folder_Templates/Type1_Footage "/path"

# Type 2 (Script)
python /Users/romansergeev/YTAI/YTAI_Folder_Templates/create_folders.py -p "/path"

# Type 2 (Manual)
cp -r /Users/romansergeev/YTAI/YTAI_Folder_Templates/Type2_Production "/path"
```
