# YTAI Project Folder Structure

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
├── 01_Source/
│   ├── video/               # Camera files (*.MP4)
│   └── audio/               # External audio (*.WAV)
├── 02_Brief/
│   ├── transcription.xlsx
│   └── analysis.md
├── 03_Exports/
│   └── *.mp4
└── 99_Pipeline/
    └── logs/
```

---

## Type 2: Production

Full project. Type 1 folders go inside `01_Source/`.

```
Type2_Production/
├── PROJECT_NAME.gdoc            # Rename to: {YourProject}.gdoc
│
├── 01_Source/
│   ├── PROJECT_NAME.prproj      # Rename to: {YourProject}.prproj
│   ├── 20250124_Interview/      # Copy Type 1 folders here
│   │   ├── video/
│   │   └── audio/
│   └── assets/
│       ├── music/
│       ├── fonts/
│       ├── graphics/
│       ├── sfx/
│       └── stock/
│
├── 02_Brief/
│   ├── transcription.xlsx
│   ├── edit_brief.xlsx
│   ├── edit_brief.md
│   ├── premiere_import.xml
│   ├── chapters.txt
│   └── description.txt
│
├── 03_Exports/
│   └── *.mp4
│
├── 04_Thumbnail/
│   ├── thumbnail.psd
│   ├── thumbnail.png
│   └── assets/
│
├── YouTube/
│   ├── video.mp4
│   └── thumbnail.png
│
└── 99_Pipeline/
    └── logs/
```

**After copying, rename:**
1. `PROJECT_NAME.gdoc` → `{YourProject}.gdoc`
2. `01_Source/PROJECT_NAME.prproj` → `01_Source/{YourProject}.prproj`

---

## Workflow

```
Type 1                                Type 2
──────                                ──────

Interview/01_Source/
  ├── video/*.MP4  ───┐
  └── audio/*.WAV  ───┤
                      ├──→  Project/01_Source/
Broll/01_Source/      │       ├── Project.prproj
  └── video/*.MP4  ───┘       ├── Interview/
                              ├── Broll/
                              └── assets/
```

**Steps:**
1. Film → Copy `Type1_Footage` → rename → add files to `01_Source/video/`
2. Transcribe → `02_Brief/transcription.xlsx`
3. Approve → Copy `Type2_Production` → rename folder
4. Rename `PROJECT_NAME.gdoc` and `PROJECT_NAME.prproj`
5. Copy footage → `01_Source/{footage_folders}/`
6. Edit → Export to `03_Exports/`
7. Thumbnail → `04_Thumbnail/`
8. Publish → `YouTube/`

---

## Comparison

| # | Type 1 | Type 2 |
|---|--------|--------|
| — | — | `PROJECT_NAME.gdoc` (rename) |
| 01 | `01_Source/video/` | `01_Source/{footage}/` |
| 01 | `01_Source/audio/` | `01_Source/assets/` |
| 01 | — | `01_Source/PROJECT_NAME.prproj` (rename) |
| 02 | `02_Brief/` | `02_Brief/` |
| 03 | `03_Exports/` | `03_Exports/` |
| 04 | — | `04_Thumbnail/` |
| — | — | `YouTube/` |
| 99 | `99_Pipeline/logs/` | `99_Pipeline/logs/` |

---

## 99_Pipeline Folder

System folder for YTAI automation:
- `logs/` — Script execution logs
- `project.json` — Project metadata (auto-generated)
- Other automation files

---

## Log Files

When using the script, logs are created automatically:
```
99_Pipeline/logs/20250125_143022_folder_created.log
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

# Copy Type 1 into Type 2
cp -r "/Footage/01_Source" "/Project/01_Source/Footage"
```
