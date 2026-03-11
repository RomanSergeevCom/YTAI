#!/usr/bin/env python3
"""
YTAI Utils: Formatting
Timestamp formatting, logging.
"""

import logging
from pathlib import Path
from datetime import datetime


# ============================================================================
# Timestamps
# ============================================================================

def generate_timestamp() -> str:
    """
    Generate a timestamp for file names.

    Returns:
        String like "20260112_171500"
    """
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def format_timestamp(seconds: float) -> str:
    """
    Format seconds as HH:MM:SS.

    Args:
        seconds: Time in seconds

    Returns:
        String "01:23:45"
    """
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_srt_timestamp(seconds: float) -> str:
    """
    Format seconds for SRT (HH:MM:SS,mmm).

    Args:
        seconds: Time in seconds

    Returns:
        String "01:23:45,678"
    """
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_secs = total_ms // 1000
    h, r = divmod(total_secs, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_duration(seconds: float) -> str:
    """
    Format duration in a human-readable way.

    Args:
        seconds: Time in seconds

    Returns:
        String "1h 23m 45s" or "23m 45s" or "45s"
    """
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    else:
        return f"{s}s"


# ============================================================================
# Logging
# ============================================================================

def setup_logging(
    logs_dir: Path, 
    project_name: str, 
    script_name: str
) -> logging.Logger:
    """
    Set up a logger with file and console output.

    Args:
        logs_dir: Directory for log files
        project_name: Project name
        script_name: Script name (without .py)

    Returns:
        Configured logger
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = generate_timestamp()
    log_file = logs_dir / f"{project_name}_{script_name}_{timestamp}.log"
    
    # Create a new logger with a unique name
    logger_name = f"{project_name}_{script_name}_{timestamp}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    
    # Clear handlers if any exist
    logger.handlers.clear()
    
    # File handler - all levels
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    
    # Console handler - INFO and above
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    logger.info(f"Log: {log_file}")
    
    return logger


# ============================================================================
# Output helper functions
# ============================================================================

def print_header(title: str, char: str = "=", width: int = 70) -> None:
    """Print a header."""
    print(char * width)
    print(title)
    print(char * width)


def print_section(title: str, char: str = "-", width: int = 70) -> None:
    """Print a section header."""
    print()
    print(title)
    print(char * width)
