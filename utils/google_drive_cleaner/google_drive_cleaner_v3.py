#!/usr/bin/env python3
"""
=============================================================================
GOOGLE DRIVE CACHE ANALYZER & CLEANER
=============================================================================
Version: 3.0
Author: Claude for Roman Sergeev
Date: January 2026

A comprehensive tool to analyze and clean Google Drive cache on macOS.
Features:
- Complete safety checks before execution
- Detailed analysis with file age, types, largest files
- Per-account breakdown (My Drive vs Shared Drives)
- Multiple report formats (Console, HTML, JSON)
- Safe cleanup with dry-run and confirmation

Usage:
    python3 google_drive_cleaner.py              # Analyze only (default)
    python3 google_drive_cleaner.py --clean      # Analyze and clean with confirmation
    python3 google_drive_cleaner.py --dry-run    # Show what would be deleted
    python3 google_drive_cleaner.py --html       # Generate HTML report
    python3 google_drive_cleaner.py --json       # Output JSON data
    python3 google_drive_cleaner.py --skip-checks # Skip pre-flight checks

See README.md for detailed documentation.
=============================================================================
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
import logging
import platform
import time
import fnmatch
import html as html_module
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
from collections import defaultdict

# =============================================================================
# CONFIGURATION
# =============================================================================

VERSION = "3.2.0"
MIN_PYTHON_VERSION = (3, 7)
SUPPORTED_OS = "Darwin"  # macOS

HOME = Path.home()
SCRIPT_DIR = Path(__file__).parent

# Create reports directory inside script folder
REPORTS_DIR = SCRIPT_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# Generate timestamp for filenames (format: 2026-01-25_00-54-57)
SESSION_TIMESTAMP = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# File paths with timestamps
LOG_FILE = REPORTS_DIR / f"{SESSION_TIMESTAMP}_google_drive_cleaner.log"
HTML_REPORT = REPORTS_DIR / f"{SESSION_TIMESTAMP}_google_drive_report.html"
JSON_REPORT = REPORTS_DIR / f"{SESSION_TIMESTAMP}_google_drive_report.json"

# Thresholds
DISK_SPACE_WARNING_THRESHOLD = 20  # Warn if more than 20% free (cleaning may not be urgent)
DISK_SPACE_CRITICAL_THRESHOLD = 5   # Critical if less than 5% free
MIN_CACHE_SIZE_TO_CLEAN = 100 * 1024 * 1024  # 100 MB minimum to bother cleaning
OLD_FILE_THRESHOLD_DAYS = 30  # Files older than 30 days
VERY_OLD_FILE_THRESHOLD_DAYS = 180  # Files older than 180 days

# File categories for analysis
FILE_CATEGORIES = {
    'video': {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.mts'},
    'image': {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp', '.tiff', '.heic', '.raw'},
    'document': {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.rtf', '.pages'},
    'audio': {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma'},
    'archive': {'.zip', '.rar', '.7z', '.tar', '.gz', '.dmg'},
    'code': {'.py', '.js', '.html', '.css', '.json', '.xml', '.swift', '.java'},
}


class RiskLevel(Enum):
    """Risk level for deletion."""
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SyncMode(Enum):
    """Google Drive sync mode."""
    STREAM = "stream"
    MIRROR = "mirror"
    UNKNOWN = "unknown"


@dataclass
class PreflightCheck:
    """Result of a pre-flight check."""
    name: str
    passed: bool
    message: str
    is_critical: bool = False
    suggestion: Optional[str] = None


@dataclass
class FileInfo:
    """Information about a single file."""
    path: Path
    size: int
    modified: datetime
    category: str
    extension: str


@dataclass
class CacheLocation:
    """Represents a Google Drive cache location."""
    name: str
    path: Path
    description: str
    risk: RiskLevel
    requires_app_closed: bool = True
    pattern: Optional[str] = None
    
    # Populated during analysis
    exists: bool = False
    size: int = 0
    file_count: int = 0
    oldest_file: Optional[datetime] = None
    newest_file: Optional[datetime] = None
    contents: List[Dict] = field(default_factory=list)
    matched_paths: List[Path] = field(default_factory=list)
    largest_files: List[Dict] = field(default_factory=list)
    file_types: Dict[str, int] = field(default_factory=dict)
    age_distribution: Dict[str, int] = field(default_factory=dict)
    
    @property
    def size_formatted(self) -> str:
        return format_size(self.size)


@dataclass
class GoogleAccount:
    """Represents a Google account found on the system."""
    email: str
    path: Path
    size: int = 0
    is_backup: bool = False
    is_active: bool = True
    sync_mode: SyncMode = SyncMode.UNKNOWN
    last_sync: Optional[datetime] = None
    
    # Breakdown
    my_drive_size: int = 0
    shared_drives_size: int = 0
    shared_drives: List[Dict] = field(default_factory=list)
    offline_files_count: int = 0
    file_count: int = 0
    largest_files: List[Dict] = field(default_factory=list)
    file_types: Dict[str, int] = field(default_factory=dict)
    
    @property
    def size_formatted(self) -> str:
        return format_size(self.size)
    
    @property
    def my_drive_formatted(self) -> str:
        return format_size(self.my_drive_size)
    
    @property
    def shared_drives_formatted(self) -> str:
        return format_size(self.shared_drives_size)


@dataclass
class DiskInfo:
    """Disk space information."""
    total: int
    used: int
    free: int
    percent_used: float
    
    @property
    def total_formatted(self) -> str:
        return format_size(self.total)
    
    @property
    def used_formatted(self) -> str:
        return format_size(self.used)
    
    @property
    def free_formatted(self) -> str:
        return format_size(self.free)


@dataclass
class AnalysisResult:
    """Complete analysis result."""
    timestamp: str
    version: str
    preflight_checks: List[PreflightCheck]
    google_drive_running: bool
    total_size: int
    safe_to_delete_size: int
    disk_info: DiskInfo
    locations: List[CacheLocation]
    accounts: List[GoogleAccount]
    
    # Aggregated stats
    total_file_count: int = 0
    largest_files_overall: List[Dict] = field(default_factory=list)
    file_types_overall: Dict[str, int] = field(default_factory=dict)
    age_distribution_overall: Dict[str, int] = field(default_factory=dict)
    estimated_cleanup_time: str = ""
    
    @property
    def total_size_formatted(self) -> str:
        return format_size(self.total_size)
    
    @property
    def safe_to_delete_formatted(self) -> str:
        return format_size(self.safe_to_delete_size)


# Define all Google Drive related locations
CACHE_LOCATIONS = [
    CacheLocation(
        name="DriveFS Main Cache",
        path=HOME / "Library/Application Support/Google/DriveFS",
        description="Primary Google Drive for Desktop cache. Contains downloaded/synced files, "
                    "metadata database, and account-specific data. This is usually the largest.",
        risk=RiskLevel.SAFE,
        requires_app_closed=True
    ),
    CacheLocation(
        name="CloudStorage Virtual Mounts",
        path=HOME / "Library/CloudStorage",
        description="Virtual mount points for each Google account. Contains streamed/mirrored files. "
                    "Safe to delete if accounts are disconnected.",
        risk=RiskLevel.SAFE,
        requires_app_closed=True,
        pattern="GoogleDrive-*"
    ),
    CacheLocation(
        name="Google Cache Directory",
        path=HOME / "Library/Caches/Google",
        description="General Google applications cache. Includes Chrome, Drive, and other Google apps.",
        risk=RiskLevel.SAFE,
        requires_app_closed=False
    ),
    CacheLocation(
        name="DriveFS Cache",
        path=HOME / "Library/Caches/com.google.drivefs",
        description="DriveFS-specific application cache.",
        risk=RiskLevel.SAFE,
        requires_app_closed=False
    ),
    CacheLocation(
        name="DriveFS Preferences",
        path=HOME / "Library/Preferences/com.google.drivefs.plist",
        description="Google Drive application preferences. Delete to reset settings.",
        risk=RiskLevel.LOW,
        requires_app_closed=True
    ),
    CacheLocation(
        name="Google Logs",
        path=HOME / "Library/Logs/Google",
        description="Log files from Google applications. Safe to delete.",
        risk=RiskLevel.SAFE,
        requires_app_closed=False
    ),
    CacheLocation(
        name="Legacy Google Drive",
        path=HOME / "Library/Application Support/Google/Drive",
        description="Legacy Backup and Sync application data. Safe to delete if not using old app.",
        risk=RiskLevel.SAFE,
        requires_app_closed=True
    ),
]


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def setup_logging(verbose: bool = False) -> logging.Logger:
    """
    Configure logging with separate handlers:
    - File: Technical debug information (always DEBUG level)
    - Console: Minimal user-friendly output (INFO or DEBUG based on --verbose)
    """
    # Create log directory if needed
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Create logger
    logger = logging.getLogger('google_drive_cleaner')
    logger.setLevel(logging.DEBUG)  # Capture all levels
    
    # Clear any existing handlers
    logger.handlers.clear()
    
    # File handler - detailed technical logging (always DEBUG)
    file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] [%(funcName)s:%(lineno)d] %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Console handler - minimal output for user
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # Log session start
    logger.debug("=" * 70)
    logger.debug(f"SESSION START - Google Drive Cache Analyzer v{VERSION}")
    logger.debug(f"Timestamp: {datetime.now().isoformat()}")
    logger.debug(f"Python: {sys.version}")
    logger.debug(f"Platform: {platform.platform()}")
    logger.debug(f"User: {HOME}")
    logger.debug(f"Script: {Path(__file__).resolve()}")
    logger.debug(f"Verbose mode: {verbose}")
    logger.debug("=" * 70)
    
    return logger


def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    if size_bytes < 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


def escape_html(text: str) -> str:
    """Escape HTML special characters in text."""
    return html_module.escape(str(text))


def make_file_link(path: str, display_text: str = None) -> str:
    """Create clickable link that reveals file in Finder."""
    escaped_path = escape_html(str(path))
    display = escape_html(display_text) if display_text else escaped_path
    # Use data attribute for the path, JavaScript will handle the reveal
    return f'<a href="#" class="file-link" data-path="{escaped_path}" title="Reveal in Finder">{display}</a>'


def make_folder_link(path: str, display_text: str = None) -> str:
    """Create clickable link that opens folder in Finder."""
    escaped_path = escape_html(str(path))
    display = escape_html(display_text) if display_text else escaped_path
    return f'<a href="#" class="folder-link" data-path="{escaped_path}" title="Open in Finder">{display}</a>'


def get_folder_size(path: Path) -> int:
    """Get folder size using 'du' command for speed."""
    if not path.exists():
        return 0
    try:
        result = subprocess.run(
            ['du', '-sk', str(path)],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            return int(result.stdout.split()[0]) * 1024
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        pass
    return 0


def get_file_size(path: Path) -> int:
    """Get single file size."""
    try:
        return path.stat().st_size if path.exists() and path.is_file() else 0
    except OSError:
        return 0


def get_disk_info() -> DiskInfo:
    """Get disk space information."""
    try:
        result = subprocess.run(['df', '-k', '/'], capture_output=True, text=True)
        lines = result.stdout.strip().split('\n')
        if len(lines) >= 2:
            parts = lines[1].split()
            total = int(parts[1]) * 1024
            used = int(parts[2]) * 1024
            free = int(parts[3]) * 1024
            percent_used = (used / total) * 100 if total > 0 else 0
            return DiskInfo(total=total, used=used, free=free, percent_used=percent_used)
    except Exception:
        pass
    return DiskInfo(total=0, used=0, free=0, percent_used=0)


def is_google_drive_running() -> bool:
    """Check if Google Drive app is running."""
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'Google Drive'],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def quit_google_drive() -> bool:
    """Attempt to quit Google Drive application."""
    try:
        subprocess.run(
            ['osascript', '-e', 'quit app "Google Drive"'],
            capture_output=True, timeout=10
        )
        time.sleep(3)
        return not is_google_drive_running()
    except Exception:
        return False


def is_time_machine_running() -> bool:
    """Check if Time Machine backup is in progress."""
    try:
        result = subprocess.run(
            ['tmutil', 'currentphase'],
            capture_output=True, text=True
        )
        return 'BackupNotRunning' not in result.stdout
    except Exception:
        return False


def check_network_connection() -> bool:
    """Check if network is available."""
    try:
        result = subprocess.run(
            ['ping', '-c', '1', '-t', '2', 'drive.google.com'],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def find_matching_paths(base_path: Path, pattern: str) -> List[Path]:
    """Find paths matching a glob pattern."""
    if not base_path.exists():
        return []
    
    matches = []
    try:
        for item in base_path.iterdir():
            if fnmatch.fnmatch(item.name, pattern):
                matches.append(item)
    except PermissionError:
        pass
    return matches


def get_file_category(extension: str) -> str:
    """Determine file category by extension."""
    ext_lower = extension.lower()
    for category, extensions in FILE_CATEGORIES.items():
        if ext_lower in extensions:
            return category
    return 'other'


def get_file_modified_time(path: Path) -> Optional[datetime]:
    """Get file modification time."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def estimate_cleanup_time(total_size: int) -> str:
    """Estimate time to delete files based on size."""
    # Rough estimate: ~1GB per second on SSD
    seconds = total_size / (1024 * 1024 * 1024)
    if seconds < 60:
        return f"~{max(1, int(seconds))} seconds"
    elif seconds < 3600:
        return f"~{int(seconds / 60)} minutes"
    else:
        return f"~{int(seconds / 3600)} hours"


def scan_directory_detailed(path: Path, max_files: int = 1000) -> Tuple[List[FileInfo], Dict[str, int], Dict[str, int]]:
    """
    Scan directory and collect detailed file information.
    Returns: (file_list, file_types_dict, age_distribution_dict)
    """
    files = []
    file_types = defaultdict(int)
    age_distribution = {'< 7 days': 0, '7-30 days': 0, '30-180 days': 0, '> 180 days': 0}
    
    now = datetime.now()
    count = 0
    
    try:
        for root, dirs, filenames in os.walk(path):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for filename in filenames:
                if filename.startswith('.'):
                    continue
                
                if count >= max_files:
                    break
                    
                filepath = Path(root) / filename
                try:
                    stat = filepath.stat()
                    size = stat.st_size
                    modified = datetime.fromtimestamp(stat.st_mtime)
                    ext = filepath.suffix.lower()
                    category = get_file_category(ext)
                    
                    files.append(FileInfo(
                        path=filepath,
                        size=size,
                        modified=modified,
                        category=category,
                        extension=ext
                    ))
                    
                    # Aggregate by type
                    file_types[category] += size
                    
                    # Aggregate by age
                    age_days = (now - modified).days
                    if age_days < 7:
                        age_distribution['< 7 days'] += size
                    elif age_days < 30:
                        age_distribution['7-30 days'] += size
                    elif age_days < 180:
                        age_distribution['30-180 days'] += size
                    else:
                        age_distribution['> 180 days'] += size
                    
                    count += 1
                except (OSError, PermissionError):
                    continue
            
            if count >= max_files:
                break
                
    except PermissionError:
        pass
    
    return files, dict(file_types), dict(age_distribution)


def detect_sync_mode(account_path: Path) -> SyncMode:
    """Detect if account is using Stream or Mirror mode."""
    # Check for .tmp directory (indicates streaming)
    tmp_dir = account_path / ".tmp"
    if tmp_dir.exists():
        return SyncMode.STREAM
    
    # Check size - very large usually means mirror
    size = get_folder_size(account_path)
    if size > 10 * 1024 * 1024 * 1024:  # > 10GB likely mirror
        return SyncMode.MIRROR
    
    return SyncMode.UNKNOWN


def get_last_sync_time(account_path: Path) -> Optional[datetime]:
    """Get last sync time from account directory."""
    try:
        # Check modification time of the account folder
        return datetime.fromtimestamp(account_path.stat().st_mtime)
    except OSError:
        return None


# =============================================================================
# PRE-FLIGHT CHECKS
# =============================================================================

def run_preflight_checks(logger: logging.Logger) -> List[PreflightCheck]:
    """Run all pre-flight safety checks."""
    checks = []
    
    # 1. Python version check
    py_version = sys.version_info[:2]
    checks.append(PreflightCheck(
        name="Python Version",
        passed=py_version >= MIN_PYTHON_VERSION,
        message=f"Python {py_version[0]}.{py_version[1]} detected",
        is_critical=True,
        suggestion=f"Upgrade to Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}+" if py_version < MIN_PYTHON_VERSION else None
    ))
    
    # 2. macOS check
    current_os = platform.system()
    checks.append(PreflightCheck(
        name="Operating System",
        passed=current_os == SUPPORTED_OS,
        message=f"{current_os} detected",
        is_critical=True,
        suggestion="This tool only works on macOS" if current_os != SUPPORTED_OS else None
    ))
    
    # 3. macOS version check
    if current_os == SUPPORTED_OS:
        mac_version = platform.mac_ver()[0]
        major_version = int(mac_version.split('.')[0]) if mac_version else 0
        checks.append(PreflightCheck(
            name="macOS Version",
            passed=major_version >= 10,
            message=f"macOS {mac_version}",
            is_critical=False,
            suggestion="macOS 10.15+ recommended" if major_version < 10 else None
        ))
    
    # 4. Google Drive running check
    gdrive_running = is_google_drive_running()
    checks.append(PreflightCheck(
        name="Google Drive Status",
        passed=not gdrive_running,
        message="Running" if gdrive_running else "Not running",
        is_critical=False,
        suggestion="Close Google Drive for best results" if gdrive_running else None
    ))
    
    # 5. Disk space check
    disk_info = get_disk_info()
    free_percent = 100 - disk_info.percent_used
    disk_critical = free_percent < DISK_SPACE_CRITICAL_THRESHOLD
    checks.append(PreflightCheck(
        name="Disk Space",
        passed=True,  # Always pass but provide info
        message=f"{disk_info.free_formatted} free ({free_percent:.1f}%)",
        is_critical=False,
        suggestion="Critical: Less than 5% free!" if disk_critical else None
    ))
    
    # 6. Time Machine check
    tm_running = is_time_machine_running()
    checks.append(PreflightCheck(
        name="Time Machine",
        passed=not tm_running,
        message="Backup in progress" if tm_running else "Not running",
        is_critical=False,
        suggestion="Wait for backup to complete" if tm_running else None
    ))
    
    # 7. Network check
    has_network = check_network_connection()
    checks.append(PreflightCheck(
        name="Network Connection",
        passed=True,  # Not critical
        message="Connected" if has_network else "Offline",
        is_critical=False,
        suggestion="Files won't re-download without network" if not has_network else None
    ))
    
    # 8. Check if any Google accounts are connected
    cloud_storage = HOME / "Library/CloudStorage"
    gdrive_accounts = list(cloud_storage.glob("GoogleDrive-*")) if cloud_storage.exists() else []
    active_accounts = [p for p in gdrive_accounts if "(" not in p.name]  # Exclude backups
    checks.append(PreflightCheck(
        name="Google Accounts",
        passed=True,
        message=f"{len(active_accounts)} active, {len(gdrive_accounts) - len(active_accounts)} backup folders",
        is_critical=False,
        suggestion="Disconnect accounts in Google Drive before cleaning" if active_accounts and gdrive_running else None
    ))
    
    # 9. Check for sufficient permissions
    test_paths = [
        HOME / "Library/Application Support/Google",
        HOME / "Library/Caches/Google",
    ]
    can_access = all(p.exists() and os.access(p, os.R_OK) for p in test_paths if p.exists())
    checks.append(PreflightCheck(
        name="Permissions",
        passed=can_access,
        message="Read access OK" if can_access else "Limited access",
        is_critical=False,
        suggestion="Run with sudo for full access" if not can_access else None
    ))
    
    # 10. Check for sync in progress
    drivefs_path = HOME / "Library/Application Support/Google/DriveFS"
    sync_in_progress = False
    if drivefs_path.exists():
        # Check for .tmp files or lock files indicating active sync
        tmp_files = list(drivefs_path.rglob("*.tmp"))
        lock_files = list(drivefs_path.rglob("*.lock"))
        sync_in_progress = len(tmp_files) > 10 or len(lock_files) > 0
    
    checks.append(PreflightCheck(
        name="Sync Status",
        passed=not sync_in_progress,
        message="Sync in progress" if sync_in_progress else "No active sync",
        is_critical=False,
        suggestion="Wait for sync to complete" if sync_in_progress else None
    ))
    
    return checks


# =============================================================================
# ANALYZER CLASS
# =============================================================================

class GoogleDriveCleaner:
    """Main analyzer and cleaner class."""
    
    def __init__(self, logger: logging.Logger, skip_checks: bool = False):
        self.logger = logger
        self.skip_checks = skip_checks
        self.result: Optional[AnalysisResult] = None
    
    def run_checks(self) -> Tuple[bool, List[PreflightCheck]]:
        """Run pre-flight checks and return (all_passed, checks)."""
        if self.skip_checks:
            self.logger.debug("Skipping pre-flight checks (--skip-checks flag)")
            return True, []
        
        self.logger.debug("Starting pre-flight checks...")
        checks = run_preflight_checks(self.logger)
        
        for check in checks:
            status = "PASS" if check.passed else "FAIL"
            self.logger.debug(f"  Check [{status}] {check.name}: {check.message}")
            if check.suggestion:
                self.logger.debug(f"    Suggestion: {check.suggestion}")
        
        critical_failed = any(c.is_critical and not c.passed for c in checks)
        self.logger.debug(f"Pre-flight checks complete. Critical failures: {critical_failed}")
        
        return not critical_failed, checks
    
    def analyze(self) -> AnalysisResult:
        """Perform full analysis of Google Drive cache."""
        start_time = time.time()
        self.logger.debug("=" * 50)
        self.logger.debug("STARTING ANALYSIS")
        self.logger.debug("=" * 50)
        
        # Run pre-flight checks
        checks_passed, preflight_checks = self.run_checks()
        
        if not checks_passed:
            self.logger.warning("Critical pre-flight checks failed!")
            for check in preflight_checks:
                if check.is_critical and not check.passed:
                    self.logger.warning(f"  {check.name}: {check.message}")
        
        locations = []
        accounts = []
        total_size = 0
        safe_size = 0
        total_files = 0
        all_largest_files = []
        all_file_types = defaultdict(int)
        all_age_distribution = defaultdict(int)
        
        # Analyze each cache location
        self.logger.debug("-" * 50)
        self.logger.debug("SCANNING CACHE LOCATIONS")
        self.logger.debug("-" * 50)
        
        for loc in CACHE_LOCATIONS:
            self.logger.debug(f"Scanning: {loc.name}")
            self.logger.debug(f"  Path: {loc.path}")
            
            analyzed = self._analyze_location(loc)
            
            if analyzed.exists and analyzed.size > 0:
                locations.append(analyzed)
                total_size += analyzed.size
                total_files += analyzed.file_count
                
                self.logger.debug(f"  Found: {analyzed.size_formatted} ({analyzed.file_count} files)")
                self.logger.debug(f"  Risk level: {analyzed.risk.value}")
                
                if analyzed.risk in (RiskLevel.SAFE, RiskLevel.LOW):
                    safe_size += analyzed.size
                
                # Aggregate stats
                all_largest_files.extend(analyzed.largest_files)
                for ft, size in analyzed.file_types.items():
                    all_file_types[ft] += size
                for age, size in analyzed.age_distribution.items():
                    all_age_distribution[age] += size
            else:
                self.logger.debug(f"  Not found or empty")
        
        # Find Google accounts
        self.logger.debug("-" * 50)
        self.logger.debug("SCANNING GOOGLE ACCOUNTS")
        self.logger.debug("-" * 50)
        
        accounts = self._find_accounts()
        
        for acc in accounts:
            status = "BACKUP" if acc.is_backup else "ACTIVE"
            self.logger.debug(f"Account [{status}]: {acc.email}")
            self.logger.debug(f"  Path: {acc.path}")
            self.logger.debug(f"  Size: {acc.size_formatted}")
            self.logger.debug(f"  Sync mode: {acc.sync_mode.value}")
            self.logger.debug(f"  My Drive: {acc.my_drive_formatted}")
            self.logger.debug(f"  Shared Drives: {acc.shared_drives_formatted}")
            if acc.shared_drives:
                for sd in acc.shared_drives[:3]:
                    self.logger.debug(f"    - {sd['name']}: {sd['size_formatted']}")
            
            all_largest_files.extend(acc.largest_files)
            for ft, size in acc.file_types.items():
                all_file_types[ft] += size
        
        # Sort largest files overall
        all_largest_files.sort(key=lambda x: x['size'], reverse=True)
        
        disk_info = get_disk_info()
        
        self.result = AnalysisResult(
            timestamp=datetime.now().isoformat(),
            version=VERSION,
            preflight_checks=preflight_checks,
            google_drive_running=is_google_drive_running(),
            total_size=total_size,
            safe_to_delete_size=safe_size,
            disk_info=disk_info,
            locations=locations,
            accounts=accounts,
            total_file_count=total_files,
            largest_files_overall=all_largest_files[:50],
            file_types_overall=dict(all_file_types),
            age_distribution_overall=dict(all_age_distribution),
            estimated_cleanup_time=estimate_cleanup_time(safe_size)
        )
        
        # Log summary
        elapsed = time.time() - start_time
        self.logger.debug("-" * 50)
        self.logger.debug("ANALYSIS SUMMARY")
        self.logger.debug("-" * 50)
        self.logger.debug(f"Total size found: {format_size(total_size)}")
        self.logger.debug(f"Safe to delete: {format_size(safe_size)}")
        self.logger.debug(f"Total files scanned: {total_files}")
        self.logger.debug(f"Locations found: {len(locations)}")
        self.logger.debug(f"Accounts found: {len(accounts)}")
        self.logger.debug(f"Disk free: {disk_info.free_formatted} ({100-disk_info.percent_used:.1f}%)")
        self.logger.debug(f"Analysis time: {elapsed:.2f} seconds")
        self.logger.debug("=" * 50)
        
        return self.result
    
    def _analyze_location(self, location: CacheLocation) -> CacheLocation:
        """Analyze a single cache location with detailed stats."""
        loc = CacheLocation(
            name=location.name,
            path=location.path,
            description=location.description,
            risk=location.risk,
            requires_app_closed=location.requires_app_closed,
            pattern=location.pattern
        )
        
        if location.pattern:
            # Handle glob patterns
            matches = find_matching_paths(location.path, location.pattern)
            loc.matched_paths = matches
            loc.size = sum(get_folder_size(p) for p in matches)
            loc.exists = len(matches) > 0
            
            # Scan matched paths for details
            all_files = []
            for match_path in matches:
                if match_path.is_dir():
                    files, file_types, age_dist = scan_directory_detailed(match_path, max_files=500)
                    all_files.extend(files)
                    for ft, size in file_types.items():
                        loc.file_types[ft] = loc.file_types.get(ft, 0) + size
                    for age, size in age_dist.items():
                        loc.age_distribution[age] = loc.age_distribution.get(age, 0) + size
            
            loc.file_count = len(all_files)
            if all_files:
                loc.largest_files = [
                    {'path': str(f.path), 'size': f.size, 'size_formatted': format_size(f.size),
                     'category': f.category, 'modified': f.modified.isoformat()}
                    for f in sorted(all_files, key=lambda x: x.size, reverse=True)[:20]
                ]
                loc.oldest_file = min(f.modified for f in all_files)
                loc.newest_file = max(f.modified for f in all_files)
        else:
            loc.exists = location.path.exists()
            if loc.exists:
                if location.path.is_dir():
                    loc.size = get_folder_size(location.path)
                    
                    # Get detailed contents
                    files, file_types, age_dist = scan_directory_detailed(location.path, max_files=500)
                    loc.file_count = len(files)
                    loc.file_types = file_types
                    loc.age_distribution = age_dist
                    
                    if files:
                        loc.largest_files = [
                            {'path': str(f.path), 'size': f.size, 'size_formatted': format_size(f.size),
                             'category': f.category, 'modified': f.modified.isoformat()}
                            for f in sorted(files, key=lambda x: x.size, reverse=True)[:20]
                        ]
                        loc.oldest_file = min(f.modified for f in files)
                        loc.newest_file = max(f.modified for f in files)
                    
                    # Get top-level contents for display
                    loc.contents = self._get_directory_contents(location.path)
                else:
                    loc.size = get_file_size(location.path)
                    loc.file_count = 1
        
        return loc
    
    def _get_directory_contents(self, path: Path, max_items: int = 10) -> List[Dict]:
        """List directory contents sorted by size."""
        contents = []
        if not path.exists() or not path.is_dir():
            return contents
        
        try:
            for item in path.iterdir():
                if item.name.startswith('.'):
                    continue
                size = get_folder_size(item) if item.is_dir() else get_file_size(item)
                contents.append({
                    'name': item.name,
                    'path': str(item),
                    'type': 'directory' if item.is_dir() else 'file',
                    'size': size,
                    'size_formatted': format_size(size)
                })
        except PermissionError:
            pass
        
        return sorted(contents, key=lambda x: x['size'], reverse=True)[:max_items]
    
    def _find_accounts(self) -> List[GoogleAccount]:
        """Find Google accounts with detailed breakdown."""
        accounts = []
        cloud_storage = HOME / "Library/CloudStorage"
        
        if not cloud_storage.exists():
            return accounts
        
        for item in cloud_storage.iterdir():
            if not item.name.startswith("GoogleDrive-"):
                continue
            
            # Parse account email
            name = item.name.replace("GoogleDrive-", "")
            is_backup = "(" in name
            email = name.split("(")[0].strip() if is_backup else name
            
            account = GoogleAccount(
                email=email,
                path=item,
                size=get_folder_size(item),
                is_backup=is_backup,
                is_active=not is_backup,
                sync_mode=detect_sync_mode(item),
                last_sync=get_last_sync_time(item)
            )
            
            # Analyze account structure
            if item.is_dir():
                self._analyze_account_structure(account, item)
            
            accounts.append(account)
        
        return sorted(accounts, key=lambda x: x.size, reverse=True)
    
    def _analyze_account_structure(self, account: GoogleAccount, path: Path) -> None:
        """Analyze account structure for My Drive vs Shared Drives."""
        try:
            for subdir in path.iterdir():
                if subdir.name == "My Drive":
                    account.my_drive_size = get_folder_size(subdir)
                elif subdir.name == "Shared drives":
                    account.shared_drives_size = get_folder_size(subdir)
                    # List individual shared drives
                    if subdir.is_dir():
                        for drive in subdir.iterdir():
                            if drive.is_dir():
                                account.shared_drives.append({
                                    'name': drive.name,
                                    'size': get_folder_size(drive),
                                    'size_formatted': format_size(get_folder_size(drive))
                                })
            
            # Scan for detailed file info
            files, file_types, _ = scan_directory_detailed(path, max_files=500)
            account.file_count = len(files)
            account.file_types = file_types
            
            if files:
                account.largest_files = [
                    {'path': str(f.path), 'size': f.size, 'size_formatted': format_size(f.size),
                     'category': f.category, 'modified': f.modified.isoformat()}
                    for f in sorted(files, key=lambda x: x.size, reverse=True)[:20]
                ]
                
                # Count offline files (files that exist locally)
                account.offline_files_count = sum(1 for f in files if f.size > 0)
                
        except PermissionError:
            pass
    
    def clean(self, dry_run: bool = False, force: bool = False) -> Dict:
        """Clean Google Drive cache."""
        self.logger.debug("=" * 50)
        self.logger.debug(f"CLEANUP {'(DRY RUN)' if dry_run else 'STARTED'}")
        self.logger.debug("=" * 50)
        
        if not self.result:
            self.analyze()
        
        if self.result.google_drive_running and not force:
            self.logger.debug("Google Drive is running, attempting to quit...")
            if not quit_google_drive():
                self.logger.debug("Failed to quit Google Drive")
                return {'success': False, 'error': 'Google Drive is still running'}
            self.logger.debug("Google Drive quit successfully")
        
        deleted = []
        errors = []
        total_freed = 0
        
        self.logger.debug(f"Processing {len(self.result.locations)} locations...")
        
        for loc in self.result.locations:
            if loc.risk in (RiskLevel.SAFE, RiskLevel.LOW):
                paths_to_delete = []
                
                if loc.pattern:
                    paths_to_delete = loc.matched_paths
                elif loc.exists:
                    paths_to_delete = [loc.path]
                
                self.logger.debug(f"Location: {loc.name} ({len(paths_to_delete)} paths)")
                
                for path in paths_to_delete:
                    size = get_folder_size(path) if path.is_dir() else get_file_size(path)
                    
                    if dry_run:
                        self.logger.debug(f"  [DRY RUN] Would delete: {path} ({format_size(size)})")
                        deleted.append({'path': str(path), 'size': size})
                        total_freed += size
                    else:
                        try:
                            self.logger.debug(f"  Deleting: {path} ({format_size(size)})")
                            if path.is_dir():
                                shutil.rmtree(path)
                            else:
                                path.unlink()
                            self.logger.debug(f"  Success: {path}")
                            deleted.append({'path': str(path), 'size': size})
                            total_freed += size
                        except Exception as e:
                            self.logger.debug(f"  ERROR: {path} - {e}")
                            errors.append({'path': str(path), 'error': str(e)})
            else:
                self.logger.debug(f"Skipping (risk={loc.risk.value}): {loc.name}")
        
        disk_info_after = get_disk_info()
        actual_freed = disk_info_after.free - self.result.disk_info.free
        
        # Log cleanup summary
        self.logger.debug("-" * 50)
        self.logger.debug("CLEANUP SUMMARY")
        self.logger.debug("-" * 50)
        self.logger.debug(f"Mode: {'DRY RUN' if dry_run else 'ACTUAL DELETE'}")
        self.logger.debug(f"Items deleted: {len(deleted)}")
        self.logger.debug(f"Errors: {len(errors)}")
        self.logger.debug(f"Expected freed: {format_size(total_freed)}")
        self.logger.debug(f"Actual freed: {format_size(actual_freed)}")
        self.logger.debug(f"Disk before: {self.result.disk_info.free_formatted}")
        self.logger.debug(f"Disk after: {disk_info_after.free_formatted}")
        self.logger.debug("=" * 50)
        
        return {
            'success': len(errors) == 0,
            'dry_run': dry_run,
            'deleted': deleted,
            'deleted_count': len(deleted),
            'errors': errors,
            'total_freed': total_freed,
            'total_freed_formatted': format_size(total_freed),
            'disk_free_before': self.result.disk_info.free_formatted,
            'disk_free_after': disk_info_after.free_formatted,
            'actual_freed': format_size(actual_freed)
        }
    
    def print_report(self) -> None:
        """Print analysis report to console."""
        if not self.result:
            self.analyze()
        
        r = self.result
        
        print("\n" + "=" * 70)
        print("GOOGLE DRIVE CACHE ANALYSIS REPORT")
        print("=" * 70)
        print(f"Version: {r.version}")
        print(f"Timestamp: {r.timestamp}")
        print()
        
        # Pre-flight checks
        if r.preflight_checks:
            print("-" * 70)
            print("PRE-FLIGHT CHECKS")
            print("-" * 70)
            for check in r.preflight_checks:
                icon = "✅" if check.passed else ("❌" if check.is_critical else "⚠️ ")
                print(f"{icon} {check.name}: {check.message}")
                if check.suggestion:
                    print(f"   → {check.suggestion}")
            print()
        
        # Disk info
        print("-" * 70)
        print("DISK STATUS")
        print("-" * 70)
        print(f"Total Disk: {r.disk_info.total_formatted}")
        print(f"Used: {r.disk_info.used_formatted} ({r.disk_info.percent_used:.1f}%)")
        print(f"Free: {r.disk_info.free_formatted} ({100 - r.disk_info.percent_used:.1f}%)")
        print()
        
        # Summary
        print("-" * 70)
        print("SUMMARY")
        print("-" * 70)
        print(f"Total Google Drive data: {r.total_size_formatted}")
        print(f"Safe to delete:          {r.safe_to_delete_formatted}")
        print(f"Total files scanned:     {r.total_file_count:,}")
        print(f"Estimated cleanup time:  {r.estimated_cleanup_time}")
        print()
        
        # File types breakdown
        if r.file_types_overall:
            print("-" * 70)
            print("FILE TYPES BREAKDOWN")
            print("-" * 70)
            sorted_types = sorted(r.file_types_overall.items(), key=lambda x: x[1], reverse=True)
            for ftype, size in sorted_types:
                pct = (size / r.total_size * 100) if r.total_size > 0 else 0
                bar_len = int(pct / 5)
                bar = "█" * bar_len + "░" * (20 - bar_len)
                print(f"  {ftype:12} {bar} {format_size(size):>10} ({pct:5.1f}%)")
            print()
        
        # Age distribution
        if r.age_distribution_overall:
            print("-" * 70)
            print("CACHE AGE DISTRIBUTION")
            print("-" * 70)
            for age, size in r.age_distribution_overall.items():
                pct = (size / r.total_size * 100) if r.total_size > 0 else 0
                print(f"  {age:15} {format_size(size):>12} ({pct:5.1f}%)")
            print()
        
        # Accounts
        if r.accounts:
            print("-" * 70)
            print("GOOGLE ACCOUNTS")
            print("-" * 70)
            for acc in r.accounts:
                icon = "📦 BACKUP" if acc.is_backup else "📁 ACTIVE"
                mode = f"[{acc.sync_mode.value.upper()}]" if acc.sync_mode != SyncMode.UNKNOWN else ""
                print(f"\n{icon} {acc.email} {mode}")
                print(f"   Path: {acc.path}")
                print(f"   Total Size: {acc.size_formatted}")
                print(f"   Files: {acc.file_count:,}")
                
                if acc.last_sync:
                    print(f"   Last Sync: {acc.last_sync.strftime('%Y-%m-%d %H:%M')}")
                
                if acc.my_drive_size or acc.shared_drives_size:
                    print(f"   ├── My Drive: {acc.my_drive_formatted}")
                    print(f"   └── Shared Drives: {acc.shared_drives_formatted}")
                    
                    if acc.shared_drives:
                        for sd in sorted(acc.shared_drives, key=lambda x: x['size'], reverse=True)[:5]:
                            print(f"       • {sd['name']}: {sd['size_formatted']}")
                
                if acc.offline_files_count:
                    print(f"   Offline files: {acc.offline_files_count:,}")
            print()
        
        # Largest files
        if r.largest_files_overall:
            print("-" * 70)
            print("LARGEST FILES (Top 20)")
            print("-" * 70)
            for f in r.largest_files_overall[:20]:
                print(f"  {format_size(f['size']):>10}  [{f['category']:8}]  {f['path']}")
            print()
        
        # Locations
        print("-" * 70)
        print("CACHE LOCATIONS")
        print("-" * 70)
        
        for loc in sorted(r.locations, key=lambda x: x.size, reverse=True):
            risk_icon = {
                RiskLevel.SAFE: "✅",
                RiskLevel.LOW: "✅",
                RiskLevel.MEDIUM: "⚠️ ",
                RiskLevel.HIGH: "🔴"
            }.get(loc.risk, "❓")
            
            print(f"\n{risk_icon} {loc.name}: {loc.size_formatted}")
            print(f"   Path: {loc.path}")
            print(f"   Risk: {loc.risk.value} | Files: {loc.file_count:,}")
            
            if loc.oldest_file and loc.newest_file:
                print(f"   Age: {loc.oldest_file.strftime('%Y-%m-%d')} to {loc.newest_file.strftime('%Y-%m-%d')}")
            
            if loc.file_types:
                types_str = ", ".join(f"{k}: {format_size(v)}" for k, v in 
                                      sorted(loc.file_types.items(), key=lambda x: x[1], reverse=True)[:3])
                print(f"   Types: {types_str}")
            
            if loc.contents:
                print("   Contents:")
                for item in loc.contents[:5]:
                    print(f"      • {item['name']}: {item['size_formatted']}")
        
        # Cleanup commands
        print("\n" + "=" * 70)
        print("CLEANUP COMMANDS")
        print("=" * 70)
        print("\nRun these commands in Terminal:\n")
        
        print("# Step 1: Quit Google Drive")
        print('osascript -e \'quit app "Google Drive"\' && sleep 3')
        print()
        
        print("# Step 2: Delete cache locations")
        for loc in r.locations:
            if loc.risk in (RiskLevel.SAFE, RiskLevel.LOW):
                if loc.matched_paths:
                    for mp in loc.matched_paths:
                        print(f'rm -rf "{mp}"')
                elif loc.exists:
                    print(f'rm -rf "{loc.path}"')
        print()
        
        print("# Step 3: Verify freed space")
        print("df -h /")
        print()
        
        print("=" * 70)
        print(f"POTENTIAL SPACE SAVINGS: {r.safe_to_delete_formatted}")
        print(f"ESTIMATED TIME: {r.estimated_cleanup_time}")
        print("=" * 70)
    
    def generate_html_report(self, output_path: Path = HTML_REPORT) -> None:
        """Generate comprehensive HTML report."""
        if not self.result:
            self.analyze()
        
        r = self.result
        
        # Generate file types chart data
        file_types_data = json.dumps([
            {'type': k, 'size': v, 'formatted': format_size(v)}
            for k, v in sorted(r.file_types_overall.items(), key=lambda x: x[1], reverse=True)
        ])
        
        # Generate age distribution data
        age_data = json.dumps([
            {'age': k, 'size': v, 'formatted': format_size(v)}
            for k, v in r.age_distribution_overall.items()
        ])
        
        html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Google Drive Cache Report - {datetime.now().strftime('%Y-%m-%d')}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 30px;
            line-height: 1.6;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{
            text-align: center;
            font-size: 2.5em;
            margin-bottom: 10px;
            color: #4285f4;
        }}
        .subtitle {{ text-align: center; color: #888; margin-bottom: 30px; }}
        
        /* Summary Cards */
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        .summary-card {{
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            padding: 20px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .summary-card .value {{
            font-size: 1.8em;
            font-weight: 700;
            color: #4285f4;
        }}
        .summary-card .label {{ color: #888; margin-top: 5px; font-size: 0.9em; }}
        .summary-card.success .value {{ color: #34a853; }}
        .summary-card.warning .value {{ color: #fbbc04; }}
        .summary-card.danger .value {{ color: #ea4335; }}
        
        /* Sections */
        .section {{
            background: rgba(255,255,255,0.03);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 25px;
            border: 1px solid rgba(255,255,255,0.08);
        }}
        .section h2 {{
            color: #4285f4;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            font-size: 1.3em;
        }}
        
        /* Pre-flight checks */
        .check-item {{
            display: flex;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }}
        .check-icon {{ font-size: 1.2em; margin-right: 12px; }}
        .check-name {{ font-weight: 500; min-width: 180px; }}
        .check-status {{ color: #888; flex: 1; }}
        .check-suggestion {{ color: #fbbc04; font-size: 0.85em; margin-left: 10px; }}
        
        /* Progress bars */
        .progress-row {{
            display: flex;
            align-items: center;
            margin-bottom: 12px;
        }}
        .progress-label {{ min-width: 100px; font-size: 0.9em; }}
        .progress-bar {{
            flex: 1;
            height: 24px;
            background: rgba(255,255,255,0.1);
            border-radius: 12px;
            overflow: hidden;
            margin: 0 15px;
        }}
        .progress-fill {{
            height: 100%;
            border-radius: 12px;
            transition: width 0.3s;
        }}
        .progress-fill.video {{ background: linear-gradient(90deg, #ea4335, #ff6b6b); }}
        .progress-fill.image {{ background: linear-gradient(90deg, #9c27b0, #e040fb); }}
        .progress-fill.document {{ background: linear-gradient(90deg, #4285f4, #64b5f6); }}
        .progress-fill.audio {{ background: linear-gradient(90deg, #34a853, #69f0ae); }}
        .progress-fill.archive {{ background: linear-gradient(90deg, #fbbc04, #ffeb3b); }}
        .progress-fill.code {{ background: linear-gradient(90deg, #00bcd4, #4dd0e1); }}
        .progress-fill.other {{ background: linear-gradient(90deg, #607d8b, #90a4ae); }}
        .progress-value {{ min-width: 100px; text-align: right; font-family: monospace; }}
        
        /* Disk usage visualization */
        .disk-visual {{
            background: rgba(255,255,255,0.1);
            border-radius: 15px;
            height: 40px;
            overflow: hidden;
            margin: 20px 0;
            position: relative;
        }}
        .disk-used {{
            height: 100%;
            background: linear-gradient(90deg, #ea4335, #fbbc04);
            display: flex;
            align-items: center;
            justify-content: center;
            color: #fff;
            font-weight: 600;
            transition: width 0.5s;
        }}
        .disk-labels {{
            display: flex;
            justify-content: space-between;
            margin-top: 8px;
            font-size: 0.85em;
            color: #888;
        }}
        
        /* Account cards */
        .account-card {{
            background: rgba(255,255,255,0.02);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 15px;
            border-left: 4px solid #4285f4;
        }}
        .account-card.backup {{ border-left-color: #fbbc04; }}
        .account-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 15px;
        }}
        .account-email {{ font-weight: 600; font-size: 1.1em; }}
        .account-badge {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 0.75em;
            font-weight: 600;
            margin-left: 10px;
        }}
        .badge-active {{ background: rgba(52,168,83,0.2); color: #34a853; }}
        .badge-backup {{ background: rgba(251,188,4,0.2); color: #fbbc04; }}
        .badge-stream {{ background: rgba(66,133,244,0.2); color: #4285f4; }}
        .badge-mirror {{ background: rgba(234,67,53,0.2); color: #ea4335; }}
        .account-size {{ font-size: 1.5em; color: #4285f4; font-weight: 600; }}
        .account-details {{ color: #aaa; font-size: 0.9em; margin-top: 10px; }}
        .account-breakdown {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid rgba(255,255,255,0.1);
        }}
        .breakdown-item {{ text-align: center; }}
        .breakdown-value {{ font-size: 1.2em; color: #4285f4; font-weight: 600; }}
        .breakdown-label {{ font-size: 0.8em; color: #888; }}
        
        /* Shared drives list */
        .shared-drives {{
            margin-top: 15px;
            padding: 15px;
            background: rgba(0,0,0,0.2);
            border-radius: 10px;
        }}
        .shared-drive-item {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }}
        .shared-drive-item:last-child {{ border-bottom: none; }}
        
        /* Location cards */
        .location-card {{
            background: rgba(255,255,255,0.02);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 15px;
            border-left: 4px solid #34a853;
        }}
        .location-card.medium {{ border-left-color: #fbbc04; }}
        .location-card.high {{ border-left-color: #ea4335; }}
        .location-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
        }}
        .location-name {{ font-weight: 600; font-size: 1.1em; }}
        .location-size {{ color: #4285f4; font-family: monospace; font-size: 1.2em; font-weight: 600; }}
        .location-path {{ font-family: monospace; font-size: 0.8em; color: #888; margin-top: 5px; }}
        .location-meta {{
            display: flex;
            gap: 20px;
            margin-top: 10px;
            font-size: 0.85em;
            color: #aaa;
        }}
        .location-desc {{ color: #aaa; margin-top: 10px; font-size: 0.9em; }}
        
        /* Largest files table */
        .files-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9em;
        }}
        .files-table th {{
            text-align: left;
            padding: 12px;
            border-bottom: 2px solid rgba(255,255,255,0.1);
            color: #4285f4;
            font-weight: 600;
        }}
        .files-table td {{
            padding: 10px 12px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }}
        .files-table tr:hover {{ background: rgba(255,255,255,0.03); }}
        .file-path {{
            font-family: monospace;
            font-size: 0.85em;
            max-width: 500px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .file-size {{ color: #4285f4; font-family: monospace; font-weight: 600; }}
        .file-category {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 8px;
            font-size: 0.8em;
            background: rgba(255,255,255,0.1);
        }}
        
        /* Clickable links */
        .file-link, .folder-link {{
            color: #8ab4f8;
            text-decoration: none;
            transition: color 0.2s, background 0.2s;
            padding: 2px 4px;
            border-radius: 4px;
        }}
        .file-link:hover, .folder-link:hover {{
            color: #4285f4;
            background: rgba(66,133,244,0.15);
            text-decoration: underline;
        }}
        .folder-link {{
            color: #aaa;
        }}
        .folder-link:hover {{
            color: #e0e0e0;
            background: rgba(255,255,255,0.1);
        }}
        .location-path a {{
            color: #888;
        }}
        .location-path a:hover {{
            color: #4285f4;
        }}
        .account-details a {{
            color: #aaa;
        }}
        .account-details a:hover {{
            color: #4285f4;
        }}
        
        /* Command box */
        .command-box {{
            background: rgba(0,0,0,0.4);
            border-radius: 10px;
            padding: 20px;
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 0.85em;
            color: #34a853;
            white-space: pre-wrap;
            overflow-x: auto;
            line-height: 1.8;
        }}
        
        /* Risk badges */
        .risk-badge {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 0.75em;
            font-weight: 600;
        }}
        .risk-safe {{ background: rgba(52,168,83,0.2); color: #34a853; }}
        .risk-low {{ background: rgba(52,168,83,0.2); color: #34a853; }}
        .risk-medium {{ background: rgba(251,188,4,0.2); color: #fbbc04; }}
        .risk-high {{ background: rgba(234,67,53,0.2); color: #ea4335; }}
        
        /* Age distribution */
        .age-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
        }}
        .age-item {{
            background: rgba(255,255,255,0.03);
            border-radius: 10px;
            padding: 15px;
            text-align: center;
        }}
        .age-value {{ font-size: 1.3em; color: #4285f4; font-weight: 600; }}
        .age-label {{ font-size: 0.85em; color: #888; margin-top: 5px; }}
        
        /* Footer */
        .footer {{
            text-align: center;
            color: #666;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid rgba(255,255,255,0.1);
        }}
        
        /* Tooltip */
        .tooltip {{
            position: absolute;
            bottom: 100%;
            left: 50%;
            transform: translateX(-50%);
            background: #34a853;
            color: white;
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 0.8em;
            white-space: nowrap;
            animation: fadeInOut 1.5s ease;
            z-index: 100;
        }}
        @keyframes fadeInOut {{
            0% {{ opacity: 0; transform: translateX(-50%) translateY(5px); }}
            20% {{ opacity: 1; transform: translateX(-50%) translateY(0); }}
            80% {{ opacity: 1; }}
            100% {{ opacity: 0; }}
        }}
        
        /* Responsive */
        @media (max-width: 768px) {{
            body {{ padding: 15px; }}
            h1 {{ font-size: 1.8em; }}
            .section {{ padding: 15px; }}
            .file-path {{ max-width: 200px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>☁️ Google Drive Cache Analysis</h1>
        <p class="subtitle">Version {r.version} | Generated: {r.timestamp}</p>
        
        <!-- Summary Cards -->
        <div class="summary-grid">
            <div class="summary-card">
                <div class="value">{r.total_size_formatted}</div>
                <div class="label">Total Found</div>
            </div>
            <div class="summary-card success">
                <div class="value">{r.safe_to_delete_formatted}</div>
                <div class="label">Safe to Delete</div>
            </div>
            <div class="summary-card">
                <div class="value">{r.total_file_count:,}</div>
                <div class="label">Files Scanned</div>
            </div>
            <div class="summary-card">
                <div class="value">{r.estimated_cleanup_time}</div>
                <div class="label">Est. Cleanup Time</div>
            </div>
            <div class="summary-card {"danger" if r.disk_info.percent_used > 90 else "warning" if r.disk_info.percent_used > 70 else ""}">
                <div class="value">{r.disk_info.percent_used:.1f}%</div>
                <div class="label">Disk Used</div>
            </div>
            <div class="summary-card {"warning" if r.google_drive_running else "success"}">
                <div class="value">{"⚠️" if r.google_drive_running else "✅"}</div>
                <div class="label">{"GDrive Running" if r.google_drive_running else "GDrive Closed"}</div>
            </div>
        </div>
'''

        # Pre-flight checks
        if r.preflight_checks:
            html += '''
        <div class="section">
            <h2>🔍 Pre-Flight Checks</h2>
'''
            for check in r.preflight_checks:
                icon = "✅" if check.passed else ("❌" if check.is_critical else "⚠️")
                suggestion_html = f'<span class="check-suggestion">→ {check.suggestion}</span>' if check.suggestion else ''
                html += f'''
            <div class="check-item">
                <span class="check-icon">{icon}</span>
                <span class="check-name">{check.name}</span>
                <span class="check-status">{check.message}</span>
                {suggestion_html}
            </div>
'''
            html += '''
        </div>
'''

        # Disk visualization
        html += f'''
        <div class="section">
            <h2>💾 Disk Usage</h2>
            <div class="disk-visual">
                <div class="disk-used" style="width: {r.disk_info.percent_used}%">
                    {r.disk_info.percent_used:.1f}% Used
                </div>
            </div>
            <div class="disk-labels">
                <span>Used: {r.disk_info.used_formatted}</span>
                <span>Total: {r.disk_info.total_formatted}</span>
                <span>Free: {r.disk_info.free_formatted}</span>
            </div>
        </div>
'''

        # File types breakdown
        if r.file_types_overall:
            html += '''
        <div class="section">
            <h2>📊 File Types Breakdown</h2>
'''
            sorted_types = sorted(r.file_types_overall.items(), key=lambda x: x[1], reverse=True)
            for ftype, size in sorted_types:
                pct = (size / r.total_size * 100) if r.total_size > 0 else 0
                html += f'''
            <div class="progress-row">
                <span class="progress-label">{ftype.title()}</span>
                <div class="progress-bar">
                    <div class="progress-fill {ftype}" style="width: {pct}%"></div>
                </div>
                <span class="progress-value">{format_size(size)}</span>
            </div>
'''
            html += '''
        </div>
'''

        # Age distribution
        if r.age_distribution_overall:
            html += '''
        <div class="section">
            <h2>📅 Cache Age Distribution</h2>
            <div class="age-grid">
'''
            for age, size in r.age_distribution_overall.items():
                pct = (size / r.total_size * 100) if r.total_size > 0 else 0
                html += f'''
                <div class="age-item">
                    <div class="age-value">{format_size(size)}</div>
                    <div class="age-label">{age} ({pct:.1f}%)</div>
                </div>
'''
            html += '''
            </div>
        </div>
'''

        # Accounts
        if r.accounts:
            html += '''
        <div class="section">
            <h2>👤 Google Accounts</h2>
'''
            for acc in r.accounts:
                card_class = "backup" if acc.is_backup else ""
                badge_class = "badge-backup" if acc.is_backup else "badge-active"
                badge_text = "BACKUP" if acc.is_backup else "ACTIVE"
                mode_badge = ""
                if acc.sync_mode != SyncMode.UNKNOWN:
                    mode_class = "badge-stream" if acc.sync_mode == SyncMode.STREAM else "badge-mirror"
                    mode_badge = f'<span class="account-badge {mode_class}">{acc.sync_mode.value.upper()}</span>'
                
                html += f'''
            <div class="account-card {card_class}">
                <div class="account-header">
                    <div>
                        <span class="account-email">{acc.email}</span>
                        <span class="account-badge {badge_class}">{badge_text}</span>
                        {mode_badge}
                    </div>
                    <span class="account-size">{acc.size_formatted}</span>
                </div>
                <div class="account-details">
                    Path: {make_folder_link(str(acc.path))}<br>
                    Files: {acc.file_count:,}
                    {f" | Last sync: {acc.last_sync.strftime('%Y-%m-%d %H:%M')}" if acc.last_sync else ""}
                    {f" | Offline files: {acc.offline_files_count:,}" if acc.offline_files_count else ""}
                </div>
'''
                if acc.my_drive_size or acc.shared_drives_size:
                    html += f'''
                <div class="account-breakdown">
                    <div class="breakdown-item">
                        <div class="breakdown-value">{acc.my_drive_formatted}</div>
                        <div class="breakdown-label">My Drive</div>
                    </div>
                    <div class="breakdown-item">
                        <div class="breakdown-value">{acc.shared_drives_formatted}</div>
                        <div class="breakdown-label">Shared Drives</div>
                    </div>
                </div>
'''
                if acc.shared_drives:
                    html += '''
                <div class="shared-drives">
                    <strong style="color: #888; font-size: 0.85em;">Shared Drives:</strong>
'''
                    for sd in sorted(acc.shared_drives, key=lambda x: x['size'], reverse=True)[:5]:
                        html += f'''
                    <div class="shared-drive-item">
                        <span>{sd['name']}</span>
                        <span style="color: #4285f4; font-family: monospace;">{sd['size_formatted']}</span>
                    </div>
'''
                    html += '''
                </div>
'''
                html += '''
            </div>
'''
            html += '''
        </div>
'''

        # Largest files
        if r.largest_files_overall:
            html += '''
        <div class="section">
            <h2>🐘 Largest Cached Files</h2>
            <table class="files-table">
                <tr>
                    <th>File</th>
                    <th>Size</th>
                    <th>Type</th>
                    <th>Modified</th>
                </tr>
'''
            for f in r.largest_files_overall[:25]:
                mod_date = f.get('modified', '')[:10] if f.get('modified') else 'N/A'
                file_link = make_file_link(f['path'])
                html += f'''
                <tr>
                    <td class="file-path">{file_link}</td>
                    <td class="file-size">{f['size_formatted']}</td>
                    <td><span class="file-category">{f['category']}</span></td>
                    <td>{mod_date}</td>
                </tr>
'''
            html += '''
            </table>
        </div>
'''

        # Cache locations
        html += '''
        <div class="section">
            <h2>📁 Cache Locations</h2>
'''
        for loc in sorted(r.locations, key=lambda x: x.size, reverse=True):
            risk_class = "safe" if loc.risk in (RiskLevel.SAFE, RiskLevel.LOW) else loc.risk.value
            card_class = "" if risk_class == "safe" else risk_class
            location_link = make_folder_link(str(loc.path))
            html += f'''
            <div class="location-card {card_class}">
                <div class="location-header">
                    <div>
                        <span class="location-name">{loc.name}</span>
                        <span class="risk-badge risk-{risk_class}">{loc.risk.value.upper()}</span>
                    </div>
                    <span class="location-size">{loc.size_formatted}</span>
                </div>
                <div class="location-path">{location_link}</div>
                <div class="location-meta">
                    <span>Files: {loc.file_count:,}</span>
'''
            if loc.oldest_file and loc.newest_file:
                html += f'''
                    <span>Age: {loc.oldest_file.strftime('%Y-%m-%d')} to {loc.newest_file.strftime('%Y-%m-%d')}</span>
'''
            html += f'''
                </div>
                <div class="location-desc">{loc.description}</div>
            </div>
'''
        html += '''
        </div>
'''
        
        html += f'''
        <div class="footer">
            <p>Generated by Google Drive Cache Analyzer v{VERSION}</p>
            <p style="color: #444; margin-top: 10px;">⚠️ Always verify before deleting. Files will re-download when needed.</p>
            <p style="color: #555; margin-top: 5px; font-size: 0.85em;">💡 Run with <code style="background:rgba(255,255,255,0.1);padding:2px 6px;border-radius:4px;">--serve</code> for clickable Finder links, or <code style="background:rgba(255,255,255,0.1);padding:2px 6px;border-radius:4px;">--clean</code> to delete cache</p>
        </div>
    </div>
    
    <script>
        // Check if running on local server (clickable mode)
        const isLocalServer = window.location.protocol === 'http:' && window.location.hostname === 'localhost';
        
        // Handle clicks on file/folder links
        document.querySelectorAll('.file-link, .folder-link').forEach(link => {{
            link.addEventListener('click', function(e) {{
                e.preventDefault();
                const path = this.getAttribute('data-path');
                const isFile = this.classList.contains('file-link');
                
                if (isLocalServer) {{
                    // Direct Finder open via local server
                    openInFinder(path, isFile, this);
                }} else {{
                    // Copy command to clipboard
                    const command = isFile ? `open -R "${{path}}"` : `open "${{path}}"`;
                    navigator.clipboard.writeText(command).then(() => {{
                        showTooltip(this, 'Copied!');
                    }});
                }}
            }});
        }});
        
        async function openInFinder(path, reveal, element) {{
            try {{
                const url = `/open-finder?path=${{encodeURIComponent(path)}}&reveal=${{reveal ? '1' : '0'}}`;
                const response = await fetch(url);
                if (!response.ok) throw new Error('Failed');
                // Visual feedback
                element.style.background = 'rgba(52,168,83,0.3)';
                setTimeout(() => element.style.background = '', 300);
            }} catch (err) {{
                const command = reveal ? `open -R "${{path}}"` : `open "${{path}}"`;
                navigator.clipboard.writeText(command);
                showTooltip(element, 'Copied!');
            }}
        }}
        
        function showTooltip(element, text) {{
            const tooltip = document.createElement('span');
            tooltip.className = 'tooltip';
            tooltip.textContent = text;
            element.style.position = 'relative';
            element.appendChild(tooltip);
            setTimeout(() => tooltip.remove(), 1500);
        }}
    </script>
</body>
</html>
'''
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        
        self.logger.info(f"HTML report saved: {output_path}")
    
    def generate_json_report(self, output_path: Path = JSON_REPORT) -> None:
        """Generate comprehensive JSON report."""
        if not self.result:
            self.analyze()
        
        r = self.result
        
        data = {
            'version': r.version,
            'timestamp': r.timestamp,
            'preflight_checks': [
                {
                    'name': c.name,
                    'passed': c.passed,
                    'message': c.message,
                    'is_critical': c.is_critical,
                    'suggestion': c.suggestion
                }
                for c in r.preflight_checks
            ],
            'system': {
                'google_drive_running': r.google_drive_running,
                'disk': {
                    'total': r.disk_info.total,
                    'total_formatted': r.disk_info.total_formatted,
                    'used': r.disk_info.used,
                    'used_formatted': r.disk_info.used_formatted,
                    'free': r.disk_info.free,
                    'free_formatted': r.disk_info.free_formatted,
                    'percent_used': r.disk_info.percent_used
                }
            },
            'summary': {
                'total_size': r.total_size,
                'total_size_formatted': r.total_size_formatted,
                'safe_to_delete_size': r.safe_to_delete_size,
                'safe_to_delete_formatted': r.safe_to_delete_formatted,
                'total_file_count': r.total_file_count,
                'estimated_cleanup_time': r.estimated_cleanup_time
            },
            'file_types': {
                k: {'size': v, 'size_formatted': format_size(v)}
                for k, v in r.file_types_overall.items()
            },
            'age_distribution': {
                k: {'size': v, 'size_formatted': format_size(v)}
                for k, v in r.age_distribution_overall.items()
            },
            'largest_files': r.largest_files_overall,
            'accounts': [
                {
                    'email': acc.email,
                    'path': str(acc.path),
                    'size': acc.size,
                    'size_formatted': acc.size_formatted,
                    'is_backup': acc.is_backup,
                    'is_active': acc.is_active,
                    'sync_mode': acc.sync_mode.value,
                    'last_sync': acc.last_sync.isoformat() if acc.last_sync else None,
                    'my_drive_size': acc.my_drive_size,
                    'my_drive_formatted': acc.my_drive_formatted,
                    'shared_drives_size': acc.shared_drives_size,
                    'shared_drives_formatted': acc.shared_drives_formatted,
                    'shared_drives': acc.shared_drives,
                    'file_count': acc.file_count,
                    'offline_files_count': acc.offline_files_count,
                    'file_types': acc.file_types,
                    'largest_files': acc.largest_files
                }
                for acc in r.accounts
            ],
            'locations': [
                {
                    'name': loc.name,
                    'path': str(loc.path),
                    'size': loc.size,
                    'size_formatted': loc.size_formatted,
                    'file_count': loc.file_count,
                    'risk': loc.risk.value,
                    'description': loc.description,
                    'exists': loc.exists,
                    'oldest_file': loc.oldest_file.isoformat() if loc.oldest_file else None,
                    'newest_file': loc.newest_file.isoformat() if loc.newest_file else None,
                    'file_types': loc.file_types,
                    'age_distribution': loc.age_distribution,
                    'contents': loc.contents,
                    'matched_paths': [str(p) for p in loc.matched_paths],
                    'largest_files': loc.largest_files
                }
                for loc in r.locations
            ]
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"JSON report saved: {output_path}")


# =============================================================================
# LOCAL SERVER FOR CLICKABLE FINDER LINKS
# =============================================================================

def start_local_server(html_path: Path, logger: logging.Logger, port: int = 8765):
    """
    Start a local HTTP server that serves the HTML report and handles
    Finder open requests. Click any path in the report to open it in Finder!
    """
    import http.server
    import socketserver
    import webbrowser
    import threading
    from urllib.parse import urlparse, parse_qs, unquote
    
    class FinderHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            # Set the directory to serve files from
            super().__init__(*args, directory=str(html_path.parent), **kwargs)
        
        def do_GET(self):
            parsed = urlparse(self.path)
            
            # Handle Finder open requests
            if parsed.path == '/open-finder':
                params = parse_qs(parsed.query)
                path = unquote(params.get('path', [''])[0])
                reveal = params.get('reveal', ['0'])[0] == '1'
                
                if path:
                    try:
                        if reveal:
                            # Reveal file in Finder (select it)
                            subprocess.run(['open', '-R', path], check=True)
                        else:
                            # Open folder in Finder
                            subprocess.run(['open', path], check=True)
                        
                        # Send success response
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(b'{"success": true}')
                        logger.debug(f"Opened in Finder: {path}")
                    except Exception as e:
                        self.send_response(500)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(f'{{"error": "{str(e)}"}}'.encode())
                        logger.debug(f"Failed to open: {path} - {e}")
                else:
                    self.send_response(400)
                    self.end_headers()
                return
            
            # Serve the HTML report at root
            if parsed.path == '/' or parsed.path == '':
                self.path = '/' + html_path.name
            
            return super().do_GET()
        
        def log_message(self, format, *args):
            # Suppress default logging
            pass
    
    # Find available port
    for p in range(port, port + 100):
        try:
            with socketserver.TCPServer(("", p), FinderHandler) as httpd:
                url = f"http://localhost:{p}/"
                
                print(f"\n🌐 Starting local server...")
                print(f"📂 Report: {html_path.name}")
                print(f"🔗 URL: {url}")
                print(f"\n✨ Click any path in the report to open it in Finder!")
                print(f"⏹  Press Ctrl+C to stop the server\n")
                
                # Open browser
                webbrowser.open(url)
                
                # Serve forever
                try:
                    httpd.serve_forever()
                except KeyboardInterrupt:
                    print("\n\n👋 Server stopped.")
                return
        except OSError:
            continue
    
    print(f"❌ Could not find available port in range {port}-{port+99}")


# =============================================================================
# CLI
# =============================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Google Drive Cache Analyzer & Cleaner for macOS (v' + VERSION + ')',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s                  Analyze and generate HTML report (default)
  %(prog)s --serve          Open report in browser with clickable Finder links
  %(prog)s --json           Also generate JSON report
  %(prog)s --no-html        Skip HTML report generation
  %(prog)s --dry-run        Show what would be deleted
  %(prog)s --clean          Delete safe cache (with confirmation)
  %(prog)s --clean --force  Delete without confirmation
  %(prog)s --skip-checks    Skip pre-flight safety checks
  %(prog)s --verbose        Show detailed progress
        '''
    )
    
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')
    parser.add_argument('--html', action='store_true', help='Generate HTML report (default: enabled)')
    parser.add_argument('--no-html', action='store_true', help='Skip HTML report generation')
    parser.add_argument('--json', action='store_true', help='Generate JSON report')
    parser.add_argument('--serve', action='store_true', help='Start local server with clickable Finder links')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted')
    parser.add_argument('--clean', action='store_true', help='Delete safe cache locations')
    parser.add_argument('--force', action='store_true', help='Skip confirmation prompts')
    parser.add_argument('--skip-checks', action='store_true', help='Skip pre-flight safety checks')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output (show debug info)')
    
    args = parser.parse_args()
    
    # Setup logging (file always gets full debug, console only shows if verbose)
    logger = setup_logging(args.verbose)
    
    # Create cleaner instance
    cleaner = GoogleDriveCleaner(logger, skip_checks=args.skip_checks)
    
    # Run analysis
    print("🔍 Analyzing Google Drive cache...")
    result = cleaner.analyze()
    print(f"✅ Found {result.total_size_formatted} of data ({result.total_file_count:,} files)")
    
    # Check if critical checks failed
    critical_failed = any(c.is_critical and not c.passed for c in result.preflight_checks)
    if critical_failed and not args.skip_checks:
        print("\n❌ Critical pre-flight checks failed. Use --skip-checks to override.")
        sys.exit(1)
    
    # Generate HTML report by default (unless --no-html specified)
    if not args.no_html:
        cleaner.generate_html_report()
        print(f"📄 HTML report: {HTML_REPORT}")
    
    # Generate JSON report if requested
    if args.json:
        cleaner.generate_json_report()
        print(f"📄 JSON report: {JSON_REPORT}")
    
    # Start local server if requested
    if args.serve:
        start_local_server(HTML_REPORT, logger)
        return
    
    # Handle cleaning
    if args.clean or args.dry_run:
        if args.dry_run:
            print("\n" + "=" * 70)
            print("DRY RUN - No files will be deleted")
            print("=" * 70)
            clean_result = cleaner.clean(dry_run=True)
            print(f"\nWould delete {clean_result['deleted_count']} items ({clean_result['total_freed_formatted']})")
            for item in clean_result['deleted']:
                print(f"  • {item['path']}")
        else:
            if not args.force:
                print(f"\n⚠️  This will delete {cleaner.result.safe_to_delete_formatted} of data.")
                print("   Files can be re-downloaded but this action cannot be undone.")
                confirm = input("\nType 'yes' to confirm: ")
                if confirm.lower() != 'yes':
                    print("Cancelled.")
                    logger.debug("User cancelled cleanup")
                    return
            
            print("\n🧹 Cleaning...")
            clean_result = cleaner.clean(dry_run=False, force=args.force)
            
            print("\n" + "=" * 70)
            print("CLEANUP COMPLETE")
            print("=" * 70)
            print(f"Items deleted: {clean_result['deleted_count']}")
            print(f"Errors: {len(clean_result['errors'])}")
            print(f"Space freed: {clean_result['actual_freed']}")
            print(f"Disk free now: {clean_result['disk_free_after']}")
            
            if clean_result['errors']:
                print("\nErrors:")
                for err in clean_result['errors']:
                    print(f"  ❌ {err['path']}: {err['error']}")
    else:
        # Just print report
        cleaner.print_report()
    
    print("\n✅ Done!")
    print(f"📋 Log: {LOG_FILE}")
    print(f"\n💡 Tip: Run with --serve to open report with clickable Finder links")


if __name__ == '__main__':
    main()
