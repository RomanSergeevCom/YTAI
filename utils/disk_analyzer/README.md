# 🍎 Mac Disk Analyzer

A comprehensive disk analysis tool for macOS, optimized for video production workflows on MacBook Pro M3 Max.

## Quick Start

```bash
sudo python3 ~/YTAI/utils/disk_analyzer/analyzer.py --full --serve
```

This single command:
1. Scans your **ENTIRE DRIVE** (requires sudo for full access)
2. Runs pre-flight safety checks
3. Generates interactive HTML report
4. Opens browser with clickable Finder links
5. **Click any file path → Opens in Finder!**

Press `Ctrl+C` to stop the server.

## Other Common Commands

```bash
# Home directory only (no sudo needed)
python3 ~/YTAI/utils/disk_analyzer/analyzer.py --serve

# Quick scan (skip duplicate detection - faster)
sudo python3 ~/YTAI/utils/disk_analyzer/analyzer.py --full --quick --serve

# Scan specific folders
python3 ~/YTAI/utils/disk_analyzer/analyzer.py --scan-path ~/Movies --scan-path ~/Projects --serve

# Preview cleanup (dry-run)
sudo python3 ~/YTAI/utils/disk_analyzer/analyzer.py --full --dry-run

# Clean safe cache items
sudo python3 ~/YTAI/utils/disk_analyzer/analyzer.py --full --clean

# Find files not used in 6 months
sudo python3 ~/YTAI/utils/disk_analyzer/analyzer.py --full --find-dead-files --days 180 --serve
```

## Features

### Deep Analysis
- **24+ File Categories**: Video projects, caches, media, dev tools, AI models
- **Duplicate Detection**: Finds identical files using quick hash comparison
- **Temporal Analysis**: Identifies "dead" files not accessed in months
- **Application Footprints**: Total disk usage per app (app + cache + data)
- **Cloud Storage Detection**: iCloud, Dropbox, Google Drive files
- **Dev Tools Analysis**: Node modules, Python envs, Docker, Xcode, AI models (.gguf, .safetensors)

### Video Production Focused
- Adobe Premiere Pro, After Effects cache detection
- DaVinci Resolve cache and render files (CacheClip, Optimized Media)
- Final Cut Pro X cache identification
- Proxy vs original footage detection
- Project file grouping (.prproj, .aep, .drp, .fcpbundle)

### Pre-flight Safety Checks
- Disk space warnings (critical < 5%, low < 10%)
- Time Machine backup status
- Full Disk Access permission check
- App running detection (warns if Adobe/Resolve/FCPX are open)

### Interactive HTML Report
- D3.js treemap visualization
- **Clickable file paths** — open directly in Finder!
- Duplicate file browser with wasted space
- Cleanup script generator with copy & download buttons

### Cleanup Features
- **Dry-run mode**: Preview without deleting
- **Risk-based filtering**: Only safe items auto-cleaned
- **App quit helper**: Quits Adobe/Resolve before cleaning cache

## Command Line Options

| Option | Description |
|--------|-------------|
| `--serve` | ⭐ Start server with clickable Finder links |
| `--full` | Full drive scan (use with sudo) |
| `--quick` | Skip duplicate detection for faster scan |
| `--scan-path PATH` | Custom path to scan (can use multiple times) |
| `--exclude PATH` | Path to exclude from scan |
| `--find-dead-files` | Find files not accessed in a long time |
| `--days N` | Days threshold for dead files (default: 180) |
| `--dry-run` | Show what would be deleted without deleting |
| `--clean` | Delete safe cache locations |
| `--force` | Skip confirmation prompts |
| `--skip-checks` | Skip pre-flight safety checks |
| `--report FORMAT` | Output format: html, json, terminal |
| `--output PATH` | Output file path |
| `--compare-last` | Compare with previous scan |
| `--history` | Show scan history |
| `--min-size SIZE` | Minimum file size (e.g., 1MB, 500KB) |
| `--verbose` | Verbose output |

## Categories

| Category | Description | Safe to Clean |
|----------|-------------|---------------|
| 🎬 Video Projects | Premiere, After Effects, Resolve projects | ❌ |
| 📹 Raw Media | Original footage, source files | ❌ |
| 📤 Exported Media | Rendered finals, exports | ❌ |
| 🗄️ Adobe Cache | Premiere/AE media cache | ✅ |
| 🎨 DaVinci Cache | Resolve render cache, optimized media | ✅ |
| 🍎 Final Cut Cache | FCPX render files | ✅ |
| ⚙️ System Cache | macOS system caches | ✅ |
| 📋 Logs | Application and system logs | ✅ |
| 🗑️ Trash | Files in Trash | ✅ |
| 📥 Downloads | Downloaded files | ⚠️ Review |
| 💿 Installers | DMG, PKG files | ⚠️ Review |
| 🔨 Xcode | DerivedData, simulators | ✅ |
| 📦 Node Modules | npm packages | ✅ |
| 🐍 Python Envs | Virtual environments, pip cache | ⚠️ Review |
| 🐳 Docker | Docker images, volumes | ⚠️ Review |
| 🤖 AI Models | Ollama, LM Studio, Hugging Face | ⚠️ Review |
| 🍺 Homebrew | Homebrew cache | ✅ |
| ☁️ Cloud Storage | iCloud, Dropbox, Google Drive | ❌ |

## Pre-flight Checks Output

```
============================================================
PRE-FLIGHT CHECKS
============================================================
✅ Python Version: Python 3.12
✅ macOS: macOS 14.3
⚠️ Disk Space: 18.5 GB free (9.2%)
   💡 Low disk space - cleanup recommended
✅ Time Machine: Not running
✅ Full Disk Access: Available
✅ Adobe Premiere Pro Status: Not running
⚠️ DaVinci Resolve Status: Running
   💡 Close DaVinci Resolve before cleaning its cache
============================================================
```

## Tips for Video Editors

### Clean Adobe Cache
```bash
rm -rf ~/Library/Caches/Adobe/
rm -rf ~/Library/Application\ Support/Adobe/Common/Media\ Cache*/
```

### Clean DaVinci Resolve Cache
In Resolve: **Playback → Delete Render Cache → All**

Or manually:
```bash
rm -rf ~/Movies/DaVinci\ Resolve/CacheClip/
rm -rf ~/Movies/DaVinci\ Resolve/Render\ Cache/
```

### Clean Xcode
```bash
rm -rf ~/Library/Developer/Xcode/DerivedData/
xcrun simctl delete unavailable
```

### Clean AI Models
```bash
ollama list
ollama rm model-name
```

## Architecture

```
~/YTAI/utils/disk_analyzer/
├── analyzer.py              # Main CLI
├── serve_report.py          # Local server for clickable links
├── logs/                    # Timestamped log files
│   ├── 2026-01-25_02-43-29_disk_analyzer.log
│   └── ...
├── core/                    # Scanner, database, file info
├── analyzers/               # Categorizer, duplicates, media, apps
├── recommendations/         # Cleanup suggestions engine
├── actions/                 # Safe cleanup executor
├── report/                  # HTML/JSON report generator
├── config/                  # Categories & app signatures
└── utils/                   # Formatting, hashing, permissions
```

## Logs

Logs are saved with timestamps in `~/YTAI/utils/disk_analyzer/logs/`:

```
logs/
├── 2026-01-25_02-43-29_disk_analyzer.log
├── 2026-01-25_03-15-00_disk_analyzer.log
└── ...
```

Each log file contains:
- Server start/stop events
- File open requests (📄 open / 📁 reveal in Finder)
- Errors and debugging info

## Troubleshooting

### Scan entire drive
```bash
sudo python3 ~/YTAI/utils/disk_analyzer/analyzer.py --full --serve
```

### Scan is slow
```bash
# Use quick mode (skips duplicate hashing)
sudo python3 ~/YTAI/utils/disk_analyzer/analyzer.py --full --quick --serve
```

### Skip pre-flight checks
```bash
sudo python3 ~/YTAI/utils/disk_analyzer/analyzer.py --full --skip-checks --serve
```

### Grant Full Disk Access (alternative to sudo)
```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
```
Then add Terminal.app and restart Terminal.

## Requirements

- macOS 10.15+
- Python 3.8+
- Optional: `brew install ffmpeg` for media analysis

## License

MIT License

---

**Built for MacBook Pro M3 Max video production workflows.**
