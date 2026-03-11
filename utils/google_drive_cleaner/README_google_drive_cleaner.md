# Google Drive Cache Analyzer & Cleaner v3.2

A comprehensive tool for analyzing and cleaning Google Drive cache on macOS.

## Overview

When using Google Drive for Desktop on macOS, the application stores cached files, sync data, and metadata that can consume significant disk space (often 10-300+ GB). This tool helps you:

1. **Analyze** - Identify all Google Drive related files and their sizes
2. **Report** - Generate detailed HTML reports with clickable links
3. **Clean** - Safely remove cache with confirmation

## Features

- 🔍 Scans all known Google Drive cache locations
- 👤 Identifies connected Google accounts
- 📊 **Auto-generates HTML report** with every run
- 🖱️ **Click paths to open in Finder** (with `--serve` mode)
- 📝 **Auto-generates timestamped log file** with every run
- 🧹 Safe cleanup with dry-run option
- ⚠️ Risk assessment for each location
- 📅 Timestamped reports for history tracking

## Installation

No dependencies required - uses only Python standard library.

```bash
# Create dedicated folder in utils
mkdir -p ~/YTAI/utils/google_drive_cleaner

# Copy files
cp google_drive_cleaner_v3.py ~/YTAI/utils/google_drive_cleaner/
cp README.md ~/YTAI/utils/google_drive_cleaner/

# Make executable (optional)
chmod +x ~/YTAI/utils/google_drive_cleaner/google_drive_cleaner_v3.py
```

### Folder Structure

```
~/YTAI/utils/
├── google_drive_cleaner/           # This tool
│   ├── google_drive_cleaner_v3.py  # Main script
│   ├── README.md                   # Documentation
│   └── reports/                    # Auto-created on first run
│       ├── 2026-01-25_00-54-57_google_drive_report.html
│       ├── 2026-01-25_00-54-57_google_drive_cleaner.log
│       └── ...
│
├── disk_analyzer/                  # Other tools...
└── ...
```

**Note:** Each run creates new files with timestamp prefix (YYYY-MM-DD_HH-MM-SS).

**Requirements:**
- Python 3.7+
- macOS 10.15+ (Catalina or later)

## Usage

### Interactive Mode (Recommended) ⭐

```bash
cd ~/YTAI/utils/google_drive_cleaner
python3 google_drive_cleaner_v3.py --serve
```

This:
1. Analyzes Google Drive cache
2. Generates HTML report
3. Opens report in browser
4. **Click any path → Opens in Finder!**

Press `Ctrl+C` to stop the server.

### Basic Analysis

```bash
# Analyze and generate HTML report
python3 google_drive_cleaner_v3.py

# Output:
# 🔍 Analyzing Google Drive cache...
# ✅ Found 3.02 GB of data (1,099 files)
# 📄 HTML report: reports/2026-01-25_00-54-57_google_drive_report.html
# ✅ Done!
```

### Generate JSON Report

```bash
python3 google_drive_cleaner_v3.py --json
```

### Cleanup

```bash
# Preview what would be deleted (safe)
python3 google_drive_cleaner_v3.py --dry-run

# Delete cache (with confirmation)
python3 google_drive_cleaner_v3.py --clean

# Delete without confirmation
python3 google_drive_cleaner_v3.py --clean --force
```

### All Options

```
usage: google_drive_cleaner_v3.py [-h] [--version] [--serve] [--no-html] 
                                   [--json] [--dry-run] [--clean] [--force] 
                                   [--skip-checks] [--verbose]

Options:
  --serve        ⭐ Start interactive mode with clickable Finder links
  --version      Show version number
  --no-html      Skip HTML report generation
  --json         Also generate JSON report
  --dry-run      Show what would be deleted without deleting
  --clean        Delete safe cache locations
  --force        Skip confirmation prompts
  --skip-checks  Skip pre-flight safety checks
  --verbose, -v  Verbose output with debug information
```

**Default behavior:** Each run automatically creates:
- HTML report with timestamp
- Log file with timestamp

## Scanned Locations

The tool scans these Google Drive related locations:

| Location | Description | Risk Level |
|----------|-------------|------------|
| `~/Library/Application Support/Google/DriveFS` | Main cache, sync data, metadata | ✅ Safe |
| `~/Library/CloudStorage/GoogleDrive-*` | Virtual mounts for each account | ✅ Safe |
| `~/Library/Caches/Google` | General Google cache | ✅ Safe |
| `~/Library/Caches/com.google.drivefs` | DriveFS specific cache | ✅ Safe |
| `~/Library/Logs/Google` | Google application logs | ✅ Safe |
| `~/Library/Preferences/com.google.drivefs.plist` | App preferences | ⚠️ Low |
| `~/Library/Application Support/Google/Drive` | Legacy Backup & Sync | ✅ Safe |

### Risk Levels

- **✅ SAFE** - Can delete without any concerns. Data will be re-downloaded/recreated.
- **⚠️ LOW** - Safe but may require app reconfiguration.
- **🟡 MEDIUM** - Review contents before deleting.
- **🔴 HIGH** - Do not delete automatically.

## Output Files

**Every run automatically creates timestamped files** in the `reports/` subfolder:

```
~/YTAI/utils/google_drive_cleaner/
├── google_drive_cleaner_v3.py          # Main script
├── README.md                           # Documentation
└── reports/                            # Auto-created
    ├── 2026-01-25_00-54-57_google_drive_report.html    # HTML report
    ├── 2026-01-25_00-54-57_google_drive_cleaner.log    # Debug log
    ├── 2026-01-25_00-54-57_google_drive_report.json    # JSON (if --json)
    ├── 2026-01-25_01-30-00_google_drive_report.html    # Next run
    ├── 2026-01-25_01-30-00_google_drive_cleaner.log
    └── ...
```

| File | Created | Contains |
|------|---------|----------|
| `*_report.html` | Always (default) | Visual report for browser |
| `*_cleaner.log` | Always | Technical debug information |
| `*_report.json` | Only with `--json` | Machine-readable data |

## Architecture

### Code Structure

```
google_drive_cleaner.py
│
├── Configuration
│   ├── VERSION, HOME, paths
│   ├── RiskLevel (Enum)
│   └── CACHE_LOCATIONS (list)
│
├── Data Classes
│   ├── CacheLocation - Represents a cache directory
│   ├── GoogleAccount - Represents a connected account
│   └── AnalysisResult - Complete analysis data
│
├── Utility Functions
│   ├── format_size() - Bytes to human-readable
│   ├── get_folder_size() - Fast folder size (uses 'du')
│   ├── get_disk_free_space() - Available disk space
│   ├── is_google_drive_running() - Check if app is active
│   ├── quit_google_drive()
│   ├── is_time_machine_running()
│   ├── check_network_connection()
│   ├── find_matching_paths()
│   ├── get_file_category()
│   ├── scan_directory_detailed()
│   ├── detect_sync_mode()
│   ├── get_last_sync_time()
│   └── estimate_cleanup_time()
│
├── Pre-Flight Checks (Lines 450-550)
│   └── run_preflight_checks()
│
├── GoogleDriveCleaner Class (Lines 550-1200)
│   ├── __init__()
│   ├── run_checks()
│   ├── analyze()
│   ├── _analyze_location()
│   ├── _get_directory_contents()
│   ├── _find_accounts()
│   ├── _analyze_account_structure()
│   ├── clean()
│   ├── print_report()
│   ├── generate_html_report()
│   └── generate_json_report()
│
└── CLI (Lines 1200+)
    └── main() - argparse setup and execution

```

### Execution Flow

```
┌─────────────────────┐
│     START           │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Parse CLI args     │
│  (argparse)         │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Setup logging      │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Create Cleaner     │
│  instance           │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────────┐
│  run_preflight_checks()         │
│  ├── Python version             │
│  ├── macOS check                │
│  ├── Google Drive status        │
│  ├── Disk space                 │
│  ├── Time Machine               │
│  ├── Network                    │
│  ├── Accounts                   │
│  ├── Permissions                │
│  └── Sync status                │
└──────────┬──────────────────────┘
           │
           ▼
     ┌─────┴─────┐
     │ Critical  │───No──→ Continue
     │ Failed?   │
     └─────┬─────┘
           │Yes
           ▼
     ┌───────────┐
     │ --skip-   │───Yes──→ Continue
     │ checks?   │
     └─────┬─────┘
           │No
           ▼
     ┌───────────┐
     │   EXIT    │
     └───────────┘
           
           │ (Continue)
           ▼
┌─────────────────────────────────┐
│  analyze()                       │
│  ├── Scan each CACHE_LOCATION   │
│  │   ├── Get size               │
│  │   ├── Count files            │
│  │   ├── Scan file types        │
│  │   ├── Get age distribution   │
│  │   └── Find largest files     │
│  ├── Find Google accounts       │
│  │   ├── Detect sync mode       │
│  │   ├── Get last sync          │
│  │   ├── Analyze My Drive       │
│  │   ├── Analyze Shared Drives  │
│  │   └── Count offline files    │
│  └── Aggregate all stats        │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│  Output based on flags:              │
│                                      │
│  --html    → generate_html_report() │
│  --json    → generate_json_report() │
│  --dry-run → clean(dry_run=True)    │
│  --clean   → confirm → clean()      │
│  (default) → print_report()         │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────┐
│       DONE          │
└─────────────────────┘
```

---

## Examples

### Example 1: Basic Analysis

```bash
$ python3 google_drive_cleaner.py

Google Drive Cache Analyzer v3.0.0
==================================================

======================================================================
GOOGLE DRIVE CACHE ANALYSIS REPORT
======================================================================
Version: 3.0.0
Timestamp: 2026-01-25T22:30:00

----------------------------------------------------------------------
PRE-FLIGHT CHECKS
----------------------------------------------------------------------
✅ Python Version: Python 3.11 detected
✅ Operating System: Darwin detected
✅ macOS Version: macOS 14.2
✅ Google Drive Status: Not running
✅ Disk Space: 45.50 GB free (4.5%)
✅ Time Machine: Not running
✅ Network Connection: Connected
✅ Google Accounts: 2 active, 1 backup folders
✅ Permissions: Read access OK
✅ Sync Status: No active sync

----------------------------------------------------------------------
DISK STATUS
----------------------------------------------------------------------
Total Disk: 1.00 TB
Used: 954.50 GB (95.5%)
Free: 45.50 GB (4.5%)

----------------------------------------------------------------------
SUMMARY
----------------------------------------------------------------------
Total Google Drive data: 267.45 GB
Safe to delete:          265.80 GB
Total files scanned:     12,456
Estimated cleanup time:  ~4 minutes

----------------------------------------------------------------------
FILE TYPES BREAKDOWN
----------------------------------------------------------------------
  video        ████████████████████ 180.50 GB (67.5%)
  image        ████░░░░░░░░░░░░░░░░  45.20 GB (16.9%)
  document     ██░░░░░░░░░░░░░░░░░░  25.30 GB ( 9.5%)
  other        █░░░░░░░░░░░░░░░░░░░  16.45 GB ( 6.1%)

----------------------------------------------------------------------
CACHE AGE DISTRIBUTION
----------------------------------------------------------------------
  < 7 days         12.50 GB ( 4.7%)
  7-30 days        45.30 GB (16.9%)
  30-180 days     120.65 GB (45.1%)
  > 180 days       89.00 GB (33.3%)
```

### Example 2: Dry Run

```bash
$ python3 google_drive_cleaner.py --dry-run

======================================================================
DRY RUN - No files will be deleted
======================================================================
[DRY RUN] Would delete: /Users/user/Library/Application Support/Google/DriveFS (970.00 MB)
[DRY RUN] Would delete: /Users/user/Library/CloudStorage/GoogleDrive-email@gmail.com (259.00 GB)
[DRY RUN] Would delete: /Users/user/Library/Caches/Google (1.70 GB)

Would delete 3 items (261.67 GB)
```

### Example 3: Generate HTML Report

```bash
$ python3 google_drive_cleaner.py --html

Google Drive Cache Analyzer v3.0.0
==================================================
...analysis output...

📄 HTML report: /Users/user/YTAI/utils/google_drive_report.html

✅ Done!

# Open in browser
$ open ~/YTAI/utils/google_drive_report.html
```

---

## Troubleshooting

### "Critical pre-flight checks failed"

```bash
# Override with --skip-checks (use with caution)
python3 google_drive_cleaner.py --skip-checks
```

### "Google Drive is still running"

```bash
# Manually quit
osascript -e 'quit app "Google Drive"'

# Or force quit
killall "Google Drive"

# Or use Force Quit dialog
# Press ⌘⌥Esc
```

### "Permission denied" errors

```bash
# Run with sudo for full access
sudo python3 google_drive_cleaner.py --clean
```

### Cache reappears after cleaning

This is normal behavior. Google Drive recreates cache when running. To minimize:

1. Use **Stream mode** instead of Mirror in Google Drive preferences
2. Disconnect unused accounts
3. Keep Google Drive closed when not needed

### Script runs slowly

Large caches (100GB+) may take several minutes to scan. Use `--verbose` to see progress:

```bash
python3 google_drive_cleaner.py --verbose
```

---

## Safety & Risk Levels

### Risk Levels Explained

| Level | Icon | Description | Auto-Clean? |
|-------|------|-------------|-------------|
| SAFE | ✅ | Can delete without any concerns | Yes |
| LOW | ✅ | Safe but may need app reconfiguration | Yes |
| MEDIUM | ⚠️ | Review contents before deleting | No |
| HIGH | 🔴 | Do not delete automatically | No |

### What Gets Deleted

Only **SAFE** and **LOW** risk items are deleted with `--clean`:

- DriveFS cache and metadata
- CloudStorage virtual mounts
- Google application caches
- Log files
- Preferences (LOW risk)

### What Is Preserved

- Your actual Google Drive files (they're in the cloud)
- Other applications' data
- System files
- User documents

### Recovery

All deleted files can be recovered by:

1. Opening Google Drive app (cache will rebuild)
2. Files will re-download as you access them

---

## License

MIT License - Feel free to modify and distribute.

---

## Changelog

### v3.0.0 (January 2026)

**Added:**
- 10 pre-flight safety checks
- File types breakdown analysis
- Cache age distribution
- Per-account detailed breakdown (My Drive vs Shared Drives)
- Sync mode detection (Stream/Mirror)
- Last sync time tracking
- Offline files counting
- Largest files identification
- Estimated cleanup time
- Enhanced HTML report with visualizations
- Comprehensive JSON export
- `--skip-checks` option

**Improved:**
- Better error handling
- More detailed console output
- Responsive HTML design

### v2.0.0

- Initial release with basic analysis
- HTML and JSON reports
- Dry-run and clean modes

---

## Author

Created by Claude for Roman Sergeev, January 2026.drive() - Attempt to close app
│   └── find_matching_paths() - Glob pattern matching
│
├── GoogleDriveCleaner Class
│   ├── analyze() - Perform full analysis
│   ├── clean() - Delete cache files
│   ├── print_report() - Console output
│   ├── generate_html_report() - HTML file
│   └── generate_json_report() - JSON file
│
└── CLI (main)
    └── argparse setup and execution flow
```

### Flow Diagram

```
┌─────────────┐
│   START     │
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│  Parse CLI args     │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│  Initialize Logger  │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│  analyze()          │
│  - Scan locations   │
│  - Find accounts    │
│  - Calculate sizes  │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│  Output based on flags:                  │
│  --html → generate_html_report()        │
│  --json → generate_json_report()        │
│  --dry-run → clean(dry_run=True)        │
│  --clean → clean(dry_run=False)         │
│  (default) → print_report()             │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────┐
│    END      │
└─────────────┘
```

## Examples

### Example Console Output

```
======================================================================
GOOGLE DRIVE CACHE ANALYSIS REPORT
======================================================================
Timestamp: 2026-01-25T10:30:00
Disk Free Space: 15.50 GB

✅ STATUS: Google Drive is not running

----------------------------------------------------------------------
SUMMARY
----------------------------------------------------------------------
Total Google Drive data: 267.45 GB
Safe to delete:          265.80 GB

----------------------------------------------------------------------
GOOGLE ACCOUNTS
----------------------------------------------------------------------

📁 ACTIVE 1@romansergeev.com
   Path: /Users/romansergeev/Library/CloudStorage/GoogleDrive-1@romansergeev.com
   Size: 259.00 GB

📦 BACKUP rs@rya.ae (14-01-2025 12:16 PM)
   Path: /Users/romansergeev/Library/CloudStorage/GoogleDrive-rs@rya.ae (14-01-2025 12:16 PM)
   Size: 3.50 MB

----------------------------------------------------------------------
CACHE LOCATIONS
----------------------------------------------------------------------

✅ DriveFS Main Cache: 970.00 MB
   Path: /Users/romansergeev/Library/Application Support/Google/DriveFS
   Risk: safe
   Contents:
      • Logs: 133.00 MB
      • cef_cache: 328.00 MB
      • Resources: 157.00 MB

✅ CloudStorage Virtual Mounts: 259.58 GB
   Path: /Users/romansergeev/Library/CloudStorage
   Risk: safe
   Matched paths:
      • GoogleDrive-1@romansergeev.com: 259.00 GB
      • GoogleDrive-rs@rya.ae: 585.00 MB

======================================================================
CLEANUP COMMANDS
======================================================================

# Step 1: Quit Google Drive
osascript -e 'quit app "Google Drive"' && sleep 3

# Step 2: Delete cache locations
rm -rf "/Users/romansergeev/Library/Application Support/Google/DriveFS"
rm -rf "/Users/romansergeev/Library/CloudStorage/GoogleDrive-1@romansergeev.com"
rm -rf "/Users/romansergeev/Library/CloudStorage/GoogleDrive-rs@rya.ae"

# Step 3: Verify freed space
df -h /

======================================================================
POTENTIAL SPACE SAVINGS: 265.80 GB
======================================================================
```

### Example JSON Output

```json
{
  "version": "2.0.0",
  "timestamp": "2026-01-25T10:30:00",
  "google_drive_running": false,
  "total_size": 287234567890,
  "total_size_formatted": "267.45 GB",
  "safe_to_delete_size": 285456789012,
  "safe_to_delete_formatted": "265.80 GB",
  "locations": [
    {
      "name": "DriveFS Main Cache",
      "path": "/Users/romansergeev/Library/Application Support/Google/DriveFS",
      "size": 1017118720,
      "size_formatted": "970.00 MB",
      "risk": "safe",
      "description": "Primary Google Drive for Desktop cache...",
      "exists": true,
      "contents": [...],
      "matched_paths": []
    }
  ],
  "accounts": [
    {
      "email": "1@romansergeev.com",
      "path": "/Users/romansergeev/Library/CloudStorage/GoogleDrive-1@romansergeev.com",
      "size": 278118891520,
      "size_formatted": "259.00 GB",
      "is_backup": false
    }
  ]
}
```

## Safety

- **No automatic deletion** - The tool never deletes files unless explicitly requested with `--clean`
- **Dry-run mode** - Use `--dry-run` to see what would be deleted
- **Confirmation prompt** - `--clean` requires typing "yes" to confirm
- **Risk assessment** - Each location has a risk level; only SAFE and LOW are auto-cleaned
- **Logging** - All actions are logged to `google_drive_cleaner.log`

## Troubleshooting

### "Permission denied" errors

```bash
# Some cache directories may have restricted permissions
sudo python3 google_drive_cleaner.py --clean
```

### Google Drive won't quit

```bash
# Force quit if needed
killall "Google Drive"
# Or use Force Quit (⌘⌥Esc)
```

### Cache reappears after cleaning

This is normal! Google Drive recreates its cache when running. If you want to minimize cache:
1. Use "Stream" mode instead of "Mirror" mode in Google Drive preferences
2. Or disconnect accounts you don't actively use

## License

MIT License - Feel free to modify and distribute.

## Author

Created by Claude for Roman Sergeev, January 2026.
