"""
Pre-flight checks for Mac Disk Analyzer
Validates system state before analysis/cleanup
"""

import os
import sys
import platform
import subprocess
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum
from pathlib import Path


class CheckStatus(Enum):
    """Status of a pre-flight check"""
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class PreflightCheck:
    """Result of a pre-flight check"""
    name: str
    status: CheckStatus
    message: str
    is_critical: bool = False
    suggestion: Optional[str] = None
    
    @property
    def icon(self) -> str:
        return {
            CheckStatus.PASS: "✅",
            CheckStatus.WARN: "⚠️",
            CheckStatus.FAIL: "❌"
        }.get(self.status, "❓")


def check_python_version(min_version: tuple = (3, 8)) -> PreflightCheck:
    """Check Python version"""
    current = sys.version_info[:2]
    if current >= min_version:
        return PreflightCheck(
            name="Python Version",
            status=CheckStatus.PASS,
            message=f"Python {current[0]}.{current[1]}"
        )
    return PreflightCheck(
        name="Python Version",
        status=CheckStatus.FAIL,
        message=f"Python {current[0]}.{current[1]} (need {min_version[0]}.{min_version[1]}+)",
        is_critical=True,
        suggestion=f"Upgrade to Python {min_version[0]}.{min_version[1]} or higher"
    )


def check_macos() -> PreflightCheck:
    """Check if running on macOS"""
    if platform.system() == "Darwin":
        version = platform.mac_ver()[0]
        return PreflightCheck(
            name="macOS",
            status=CheckStatus.PASS,
            message=f"macOS {version}"
        )
    return PreflightCheck(
        name="macOS",
        status=CheckStatus.WARN,
        message=f"Running on {platform.system()}",
        suggestion="This tool is optimized for macOS"
    )


def check_disk_space(path: str = "/", warn_threshold: int = 10, critical_threshold: int = 5) -> PreflightCheck:
    """Check available disk space"""
    try:
        result = subprocess.run(['df', '-k', path], capture_output=True, text=True)
        lines = result.stdout.strip().split('\n')
        if len(lines) >= 2:
            parts = lines[1].split()
            total = int(parts[1]) * 1024
            free = int(parts[3]) * 1024
            percent_free = (free / total) * 100 if total > 0 else 0
            
            free_gb = free / (1024**3)
            
            if percent_free < critical_threshold:
                return PreflightCheck(
                    name="Disk Space",
                    status=CheckStatus.FAIL,
                    message=f"{free_gb:.1f} GB free ({percent_free:.1f}%)",
                    is_critical=True,
                    suggestion="Critical! Free up space immediately"
                )
            elif percent_free < warn_threshold:
                return PreflightCheck(
                    name="Disk Space",
                    status=CheckStatus.WARN,
                    message=f"{free_gb:.1f} GB free ({percent_free:.1f}%)",
                    suggestion="Low disk space - cleanup recommended"
                )
            return PreflightCheck(
                name="Disk Space",
                status=CheckStatus.PASS,
                message=f"{free_gb:.1f} GB free ({percent_free:.1f}%)"
            )
    except Exception as e:
        return PreflightCheck(
            name="Disk Space",
            status=CheckStatus.WARN,
            message=f"Could not check: {e}"
        )
    
    return PreflightCheck(
        name="Disk Space",
        status=CheckStatus.WARN,
        message="Could not determine disk space"
    )


def check_app_running(app_name: str) -> PreflightCheck:
    """Check if an application is running"""
    try:
        result = subprocess.run(
            ['pgrep', '-f', app_name],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return PreflightCheck(
                name=f"{app_name} Status",
                status=CheckStatus.WARN,
                message="Running",
                suggestion=f"Close {app_name} before cleaning its cache"
            )
        return PreflightCheck(
            name=f"{app_name} Status",
            status=CheckStatus.PASS,
            message="Not running"
        )
    except Exception:
        return PreflightCheck(
            name=f"{app_name} Status",
            status=CheckStatus.PASS,
            message="Unknown"
        )


def check_time_machine() -> PreflightCheck:
    """Check if Time Machine backup is in progress"""
    try:
        result = subprocess.run(
            ['tmutil', 'currentphase'],
            capture_output=True, text=True
        )
        if 'BackupNotRunning' in result.stdout:
            return PreflightCheck(
                name="Time Machine",
                status=CheckStatus.PASS,
                message="Not running"
            )
        return PreflightCheck(
            name="Time Machine",
            status=CheckStatus.WARN,
            message="Backup in progress",
            suggestion="Wait for backup to complete before cleaning"
        )
    except Exception:
        return PreflightCheck(
            name="Time Machine",
            status=CheckStatus.PASS,
            message="Not available"
        )


def check_full_disk_access() -> PreflightCheck:
    """Check if we have Full Disk Access permission"""
    test_paths = [
        os.path.expanduser("~/Library/Mail"),
        os.path.expanduser("~/Library/Messages"),
        "/Library/Application Support",
    ]
    
    accessible = 0
    for path in test_paths:
        if os.path.exists(path):
            try:
                os.listdir(path)
                accessible += 1
            except PermissionError:
                pass
    
    if accessible == len(test_paths):
        return PreflightCheck(
            name="Full Disk Access",
            status=CheckStatus.PASS,
            message="Available"
        )
    elif accessible > 0:
        return PreflightCheck(
            name="Full Disk Access",
            status=CheckStatus.WARN,
            message="Partial access",
            suggestion="Grant Full Disk Access in System Preferences for complete scan"
        )
    return PreflightCheck(
        name="Full Disk Access",
        status=CheckStatus.WARN,
        message="Limited access",
        suggestion="Grant Full Disk Access in System Preferences → Privacy & Security"
    )


def check_sudo() -> PreflightCheck:
    """Check if running with sudo"""
    if os.geteuid() == 0:
        return PreflightCheck(
            name="Root Access",
            status=CheckStatus.PASS,
            message="Running as root"
        )
    return PreflightCheck(
        name="Root Access",
        status=CheckStatus.PASS,
        message="Normal user (use sudo for full system scan)"
    )


def quit_application(app_name: str) -> bool:
    """Attempt to quit an application using osascript"""
    try:
        subprocess.run(
            ['osascript', '-e', f'quit app "{app_name}"'],
            capture_output=True, timeout=10
        )
        import time
        time.sleep(2)
        
        # Verify it's closed
        result = subprocess.run(
            ['pgrep', '-f', app_name],
            capture_output=True
        )
        return result.returncode != 0
    except Exception:
        return False


def run_preflight_checks(check_apps: List[str] = None) -> List[PreflightCheck]:
    """
    Run all pre-flight checks
    
    Args:
        check_apps: List of application names to check if running
    
    Returns:
        List of PreflightCheck results
    """
    checks = []
    
    # System checks
    checks.append(check_python_version())
    checks.append(check_macos())
    checks.append(check_disk_space())
    checks.append(check_time_machine())
    checks.append(check_full_disk_access())
    checks.append(check_sudo())
    
    # App checks
    if check_apps:
        for app in check_apps:
            checks.append(check_app_running(app))
    else:
        # Default apps to check for video production
        default_apps = [
            "Adobe Premiere Pro",
            "After Effects",
            "DaVinci Resolve",
            "Final Cut Pro",
        ]
        for app in default_apps:
            checks.append(check_app_running(app))
    
    return checks


def print_preflight_report(checks: List[PreflightCheck]) -> bool:
    """
    Print preflight check results
    
    Args:
        checks: List of check results
    
    Returns:
        True if all critical checks passed
    """
    print("\n" + "=" * 60)
    print("PRE-FLIGHT CHECKS")
    print("=" * 60)
    
    critical_failed = False
    
    for check in checks:
        status_str = f"{check.icon} {check.name}: {check.message}"
        print(status_str)
        
        if check.suggestion:
            print(f"   💡 {check.suggestion}")
        
        if check.is_critical and check.status == CheckStatus.FAIL:
            critical_failed = True
    
    print("=" * 60)
    
    if critical_failed:
        print("❌ Critical checks failed!")
        return False
    
    warnings = sum(1 for c in checks if c.status == CheckStatus.WARN)
    if warnings:
        print(f"⚠️  {warnings} warning(s) - proceed with caution")
    else:
        print("✅ All checks passed")
    
    return True


def estimate_cleanup_time(total_bytes: int) -> str:
    """
    Estimate time to delete files based on size
    
    Args:
        total_bytes: Total size to delete
    
    Returns:
        Human-readable time estimate
    """
    # Rough estimate: ~1GB per second on SSD, slower on HDD
    gb = total_bytes / (1024**3)
    seconds = max(1, gb)  # At least 1 second
    
    if seconds < 60:
        return f"~{int(seconds)} seconds"
    elif seconds < 3600:
        return f"~{int(seconds / 60)} minutes"
    else:
        return f"~{seconds / 3600:.1f} hours"
