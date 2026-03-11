"""
Formatting utilities for Mac Disk Analyzer
"""

from datetime import datetime, timedelta
from typing import Union
import math


def format_size(size_bytes: Union[int, float], precision: int = 1) -> str:
    """
    Format bytes into human-readable size string
    
    Args:
        size_bytes: Size in bytes
        precision: Decimal places (default 1)
    
    Returns:
        Formatted string like "1.5 GB"
    """
    if size_bytes == 0:
        return "0 B"
    
    if size_bytes < 0:
        return f"-{format_size(abs(size_bytes), precision)}"
    
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    unit_index = 0
    size = float(size_bytes)
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    if unit_index == 0:
        return f"{int(size)} B"
    
    return f"{size:.{precision}f} {units[unit_index]}"


def format_size_short(size_bytes: Union[int, float]) -> str:
    """Short format without space: 1.5GB"""
    return format_size(size_bytes).replace(' ', '')


def parse_size(size_str: str) -> int:
    """
    Parse size string to bytes
    
    Args:
        size_str: String like "1.5GB", "500 MB", "1024"
    
    Returns:
        Size in bytes
    """
    size_str = size_str.strip().upper().replace(' ', '')
    
    units = {
        'B': 1,
        'KB': 1024,
        'K': 1024,
        'MB': 1024**2,
        'M': 1024**2,
        'GB': 1024**3,
        'G': 1024**3,
        'TB': 1024**4,
        'T': 1024**4,
        'PB': 1024**5,
        'P': 1024**5,
    }
    
    for unit, multiplier in sorted(units.items(), key=lambda x: -len(x[0])):
        if size_str.endswith(unit):
            try:
                return int(float(size_str[:-len(unit)]) * multiplier)
            except ValueError:
                pass
    
    try:
        return int(float(size_str))
    except ValueError:
        return 0


def format_duration(seconds: Union[int, float]) -> str:
    """
    Format seconds into human-readable duration
    
    Args:
        seconds: Duration in seconds
    
    Returns:
        Formatted string like "2h 30m 15s"
    """
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    
    seconds = int(seconds)
    
    if seconds < 60:
        return f"{seconds}s"
    
    minutes, secs = divmod(seconds, 60)
    
    if minutes < 60:
        if secs:
            return f"{minutes}m {secs}s"
        return f"{minutes}m"
    
    hours, mins = divmod(minutes, 60)
    
    if hours < 24:
        parts = [f"{hours}h"]
        if mins:
            parts.append(f"{mins}m")
        if secs:
            parts.append(f"{secs}s")
        return " ".join(parts)
    
    days, hrs = divmod(hours, 24)
    parts = [f"{days}d"]
    if hrs:
        parts.append(f"{hrs}h")
    if mins:
        parts.append(f"{mins}m")
    return " ".join(parts)


def format_date(dt: Union[datetime, float, int, str, None], relative: bool = False) -> str:
    """
    Format datetime or timestamp
    
    Args:
        dt: datetime object, Unix timestamp, or ISO string
        relative: If True, show relative time like "2 days ago"
    
    Returns:
        Formatted date string
    """
    if dt is None:
        return "Unknown"
    
    if isinstance(dt, str):
        try:
            # Handle ISO format strings
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return dt  # Return as-is if can't parse
    
    if isinstance(dt, (int, float)):
        try:
            dt = datetime.fromtimestamp(dt)
        except (ValueError, OSError):
            return "Unknown"
    
    if relative:
        now = datetime.now()
        diff = now - dt
        
        if diff.days < 0:
            return dt.strftime("%Y-%m-%d")
        elif diff.days == 0:
            if diff.seconds < 60:
                return "Just now"
            elif diff.seconds < 3600:
                mins = diff.seconds // 60
                return f"{mins} minute{'s' if mins != 1 else ''} ago"
            else:
                hours = diff.seconds // 3600
                return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif diff.days == 1:
            return "Yesterday"
        elif diff.days < 7:
            return f"{diff.days} days ago"
        elif diff.days < 30:
            weeks = diff.days // 7
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        elif diff.days < 365:
            months = diff.days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        else:
            years = diff.days // 365
            return f"{years} year{'s' if years != 1 else ''} ago"
    
    return dt.strftime("%Y-%m-%d %H:%M")


def format_number(num: Union[int, float], precision: int = 0) -> str:
    """
    Format number with thousand separators
    
    Args:
        num: Number to format
        precision: Decimal places
    
    Returns:
        Formatted string like "1,234,567"
    """
    if precision > 0:
        return f"{num:,.{precision}f}"
    return f"{int(num):,}"


def format_percentage(value: float, total: float, precision: int = 1) -> str:
    """
    Calculate and format percentage
    
    Args:
        value: Part value
        total: Total value
        precision: Decimal places
    
    Returns:
        Formatted percentage string like "45.5%"
    """
    if total == 0:
        return "0%"
    
    pct = (value / total) * 100
    
    if pct < 0.1 and pct > 0:
        return "<0.1%"
    
    return f"{pct:.{precision}f}%"


def truncate_path(path: str, max_length: int = 60) -> str:
    """
    Truncate long paths intelligently
    
    Args:
        path: File path
        max_length: Maximum length
    
    Returns:
        Truncated path with ... in middle if needed
    """
    if len(path) <= max_length:
        return path
    
    # Try to keep filename and some context
    parts = path.split('/')
    filename = parts[-1] if parts else path
    
    if len(filename) >= max_length - 5:
        # Filename itself is too long
        return filename[:max_length-3] + "..."
    
    # Calculate how much space we have for the beginning
    available = max_length - len(filename) - 5  # 5 for "/.../"
    
    if available < 10:
        return ".../" + filename
    
    # Build truncated path
    beginning = path[:available]
    # Try to cut at a / boundary
    last_slash = beginning.rfind('/')
    if last_slash > available // 2:
        beginning = beginning[:last_slash]
    
    return beginning + "/.../" + filename


def truncate_string(s: str, max_length: int = 50, suffix: str = "...") -> str:
    """
    Truncate string with suffix
    
    Args:
        s: String to truncate
        max_length: Maximum length including suffix
        suffix: Suffix to add if truncated
    
    Returns:
        Truncated string
    """
    if len(s) <= max_length:
        return s
    
    return s[:max_length - len(suffix)] + suffix


def make_safe_filename(name: str) -> str:
    """
    Convert string to safe filename
    
    Args:
        name: Original name
    
    Returns:
        Safe filename with special chars removed
    """
    # Replace problematic characters
    unsafe = '<>:"/\\|?*'
    for char in unsafe:
        name = name.replace(char, '_')
    
    # Remove leading/trailing spaces and dots
    name = name.strip(' .')
    
    # Limit length
    if len(name) > 200:
        name = name[:200]
    
    return name or "unnamed"


def generate_color_for_category(category: str) -> str:
    """
    Generate consistent color hex for a category name
    Uses hash to always return same color for same category
    
    Args:
        category: Category name
    
    Returns:
        Hex color string like "#3498db"
    """
    # Predefined palette for known categories
    palette = {
        'video_projects': '#e74c3c',
        'media_raw': '#e67e22',
        'media_exports': '#f1c40f',
        'cache_adobe': '#9b59b6',
        'cache_resolve': '#8e44ad',
        'cache_fcpx': '#2980b9',
        'cache_system': '#3498db',
        'logs': '#1abc9c',
        'trash': '#95a5a6',
        'downloads': '#27ae60',
        'installers': '#16a085',
        'xcode': '#2c3e50',
        'node_modules': '#d35400',
        'python_env': '#f39c12',
        'docker': '#0db7ed',
        'ai_models': '#ff6b6b',
        'homebrew': '#feca57',
        'cloud_local': '#54a0ff',
        'mail': '#5f27cd',
        'applications': '#00d2d3',
        'documents': '#ff9ff3',
        'photos': '#feca57',
        'music': '#ff6b6b',
        'other': '#bdc3c7',
    }
    
    if category.lower() in palette:
        return palette[category.lower()]
    
    # Generate from hash
    hash_val = hash(category) % 0xFFFFFF
    return f"#{hash_val:06x}"


def bar_chart_ascii(value: float, max_value: float, width: int = 30, 
                   fill_char: str = "█", empty_char: str = "░") -> str:
    """
    Generate ASCII bar chart
    
    Args:
        value: Current value
        max_value: Maximum value (100%)
        width: Total bar width in characters
        fill_char: Character for filled portion
        empty_char: Character for empty portion
    
    Returns:
        ASCII bar string
    """
    if max_value == 0:
        return empty_char * width
    
    filled = int((value / max_value) * width)
    filled = min(filled, width)
    
    return fill_char * filled + empty_char * (width - filled)


def format_file_type(extension: str) -> str:
    """
    Get human-readable file type from extension
    
    Args:
        extension: File extension with or without dot
    
    Returns:
        Human-readable type name
    """
    ext = extension.lower().lstrip('.')
    
    types = {
        # Video
        'mp4': 'MP4 Video',
        'mov': 'QuickTime Movie',
        'avi': 'AVI Video',
        'mkv': 'Matroska Video',
        'webm': 'WebM Video',
        'mxf': 'MXF Video',
        'r3d': 'RED RAW',
        'braw': 'Blackmagic RAW',
        'prores': 'Apple ProRes',
        
        # Audio
        'mp3': 'MP3 Audio',
        'wav': 'WAV Audio',
        'aiff': 'AIFF Audio',
        'flac': 'FLAC Audio',
        'aac': 'AAC Audio',
        'm4a': 'M4A Audio',
        
        # Images
        'jpg': 'JPEG Image',
        'jpeg': 'JPEG Image',
        'png': 'PNG Image',
        'gif': 'GIF Image',
        'heic': 'HEIC Image',
        'tiff': 'TIFF Image',
        'raw': 'RAW Image',
        'cr2': 'Canon RAW',
        'cr3': 'Canon RAW',
        'nef': 'Nikon RAW',
        'arw': 'Sony RAW',
        'dng': 'DNG Image',
        
        # Documents
        'pdf': 'PDF Document',
        'doc': 'Word Document',
        'docx': 'Word Document',
        'xls': 'Excel Spreadsheet',
        'xlsx': 'Excel Spreadsheet',
        'ppt': 'PowerPoint',
        'pptx': 'PowerPoint',
        'txt': 'Text File',
        'md': 'Markdown',
        
        # Project files
        'prproj': 'Premiere Project',
        'aep': 'After Effects Project',
        'drp': 'DaVinci Resolve Project',
        'fcpbundle': 'Final Cut Pro Project',
        'psd': 'Photoshop File',
        'ai': 'Illustrator File',
        
        # Code
        'py': 'Python',
        'js': 'JavaScript',
        'ts': 'TypeScript',
        'jsx': 'React JSX',
        'tsx': 'React TSX',
        'html': 'HTML',
        'css': 'CSS',
        'json': 'JSON',
        'xml': 'XML',
        'yaml': 'YAML',
        'yml': 'YAML',
        
        # Archives
        'zip': 'ZIP Archive',
        'rar': 'RAR Archive',
        '7z': '7-Zip Archive',
        'tar': 'TAR Archive',
        'gz': 'GZIP Archive',
        'dmg': 'Disk Image',
        'pkg': 'Installer Package',
        'iso': 'ISO Image',
        
        # Other
        'app': 'Application',
        'log': 'Log File',
        'db': 'Database',
        'sqlite': 'SQLite Database',
    }
    
    return types.get(ext, ext.upper() if ext else 'Unknown')
