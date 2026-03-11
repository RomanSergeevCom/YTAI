# unzip_project.py

Extract all `.zip` files in-place into the same folder.
Designed for Google Drive multi-part zip downloads.

## Quick Start

```bash
source ~/YTAI/environment/.venv_ytai-prod/bin/activate
python ~/YTAI/scripts/999_extra/unzip_project.py --path ~/Desktop/
```

> Paste project folder name after `~/Desktop/`

## What it does

1. Scans folder for `.zip` files, sorts alphabetically (001 → 002 → 003)
2. Extracts all files directly into the same folder (flattened, no subfolders)
3. Skips macOS junk (`__MACOSX`, `.DS_Store`, `._*`)
4. Warns about duplicate filenames across archives
5. Prints per-archive stats + final summary with file type breakdown
6. Keeps original zip files in place

## Example

```
BEFORE:
~/Desktop/YTCG37_Anamaria/
├── YTCG37_Anamaria Meshkurti-...-001.zip  (2.1 GB)
├── YTCG37_Anamaria Meshkurti-...-002.zip  (2.1 GB)
└── YTCG37_Anamaria Meshkurti-...-003.zip  (2.1 GB)

AFTER:
~/Desktop/YTCG37_Anamaria/
├── RYA-ZVE1-1001.MP4
├── RYA-ZVE1-1002.MP4
├── RYA-ZVE1-1003.MP4
├── ...
├── YTCG37_Anamaria Meshkurti-...-001.zip
├── YTCG37_Anamaria Meshkurti-...-002.zip
└── YTCG37_Anamaria Meshkurti-...-003.zip
```

## Example output

```
Found 3 zip file(s) in: /Users/romansergeev/Desktop/YTCG37_Anamaria
Total archive size: 6.3 GB

  1. YTCG37_Anamaria Meshkurti-20260209T205649Z-1-001.zip  (2.1 GB)
  2. YTCG37_Anamaria Meshkurti-20260209T205649Z-1-002.zip  (2.1 GB)
  3. YTCG37_Anamaria Meshkurti-20260209T205649Z-1-003.zip  (2.1 GB)

Extracting to: /Users/romansergeev/Desktop/YTCG37_Anamaria

── YTCG37_Anamaria Meshkurti-...-001.zip ──
  ✓ 5 file(s), 2.4 GB, skipped 3 junk
── YTCG37_Anamaria Meshkurti-...-002.zip ──
  ✓ 4 file(s), 2.3 GB, skipped 2 junk
── YTCG37_Anamaria Meshkurti-...-003.zip ──
  ✓ 3 file(s), 2.2 GB

=======================================================
  EXTRACTION COMPLETE
=======================================================
  Zip archives:     3
  Files extracted:   12
  Total size:        6.9 GB
  Junk skipped:      5
  Time:              1m 23s
  Output:            /Users/romansergeev/Desktop/YTCG37_Anamaria

  File types:
    .MP4       10 file(s)
    .WAV       2 file(s)
=======================================================

✓ All OK
```

## Flags

| Flag | Description |
|------|-------------|
| `--path` | Path to folder with `.zip` files (required) |

## Requirements

Python 3.11+ (stdlib only, no extra packages).

## Location

```
/Users/romansergeev/YTAI/scripts/999_extra/
├── unzip_project.py
└── unzip_project.md
```
