"""
macOS permission handling utilities
"""

import os
import stat
from pathlib import Path
from typing import Tuple, Optional
import subprocess


def check_full_disk_access() -> bool:
    """
    Check if we have Full Disk Access on macOS
    
    Returns:
        True if we have access to protected directories
    """
    # Try to access a protected location
    protected_paths = [
        os.path.expanduser('~/Library/Mail'),
        os.path.expanduser('~/Library/Safari'),
        '/Library/Application Support/com.apple.TCC',
    ]
    
    for path in protected_paths:
        if os.path.exists(path):
            try:
                os.listdir(path)
                return True
            except PermissionError:
                continue
    
    return False


def check_path_readable(path: str) -> Tuple[bool, Optional[str]]:
    """
    Check if path is readable and return reason if not
    
    Args:
        path: Path to check
    
    Returns:
        Tuple of (is_readable, error_reason)
    """
    try:
        if os.path.isdir(path):
            os.listdir(path)
        else:
            with open(path, 'rb') as f:
                f.read(1)
        return True, None
    
    except PermissionError:
        return False, "Permission denied"
    except FileNotFoundError:
        return False, "File not found"
    except OSError as e:
        return False, str(e)


def is_system_protected(path: str) -> bool:
    """
    Check if path is a macOS system-protected location
    
    Args:
        path: Path to check
    
    Returns:
        True if path is system protected
    """
    protected_prefixes = [
        # macOS System
        '/System',
        '/usr',
        '/bin',
        '/sbin',
        '/etc',
        '/var',
        '/tmp',
        '/private/var',
        '/private/etc',
        '/private/tmp',
        
        # System hidden folders
        '/.Spotlight-V100',
        '/.fseventsd',
        '/.DocumentRevisions-V100',
        '/.vol',
        '/.Trashes',
        '/.file',
        '/.hotfiles.btree',
        '/.PKInstallSandboxManager',
        
        # Device files
        '/dev',
        '/cores',
        
        # Recovery and boot partitions  
        '/Volumes/Recovery',
        '/Volumes/Preboot',
        '/Volumes/VM',
        '/Volumes/Update',
        '/Volumes/xarts',
        '/Volumes/Data',
        
        # Network mounts that could hang
        '/net',
        '/Network',
        '/automount',
        
        # Time Machine
        '/.MobileBackups',
        '/Volumes/com.apple.TimeMachine',
        
        # Spotlight indexes (huge)
        '.Spotlight-V100',
        
        # Apple internal
        '/AppleInternal',
    ]
    
    # Don't resolve symlinks - could hang on network paths
    # path = os.path.realpath(path)  # REMOVED - can hang
    
    for prefix in protected_prefixes:
        if path.startswith(prefix) or path.endswith(prefix):
            return True
    
    # Check for hidden system directories at root
    if path.startswith('/.') and len(path.split('/')) == 2:
        return True
    
    return False


def is_symlink_loop(path: str, max_depth: int = 20) -> bool:
    """
    Check if following symlink would create a loop
    
    Args:
        path: Path to check
        max_depth: Maximum symlink resolution depth
    
    Returns:
        True if path is part of a symlink loop
    """
    seen = set()
    current = path
    
    for _ in range(max_depth):
        if not os.path.islink(current):
            return False
        
        if current in seen:
            return True
        
        seen.add(current)
        
        try:
            current = os.readlink(current)
            if not os.path.isabs(current):
                current = os.path.join(os.path.dirname(path), current)
        except OSError:
            return False
    
    return True  # Too many levels, assume loop


def get_file_owner(path: str) -> Tuple[str, str]:
    """
    Get file owner user and group names
    
    Args:
        path: Path to file
    
    Returns:
        Tuple of (username, groupname)
    """
    try:
        stat_info = os.stat(path)
        
        import pwd
        import grp
        
        try:
            username = pwd.getpwuid(stat_info.st_uid).pw_name
        except KeyError:
            username = str(stat_info.st_uid)
        
        try:
            groupname = grp.getgrgid(stat_info.st_gid).gr_name
        except KeyError:
            groupname = str(stat_info.st_gid)
        
        return username, groupname
    
    except (OSError, ImportError):
        return "unknown", "unknown"


def get_file_permissions_string(path: str) -> str:
    """
    Get file permissions as string like 'rwxr-xr-x'
    
    Args:
        path: Path to file
    
    Returns:
        Permission string
    """
    try:
        mode = os.stat(path).st_mode
        
        perms = ''
        for who in ('USR', 'GRP', 'OTH'):
            for what, char in (('R', 'r'), ('W', 'w'), ('X', 'x')):
                if mode & getattr(stat, f'S_I{what}{who}'):
                    perms += char
                else:
                    perms += '-'
        
        return perms
    
    except OSError:
        return '---------'


def can_delete_file(path: str) -> Tuple[bool, Optional[str]]:
    """
    Check if file can be safely deleted
    
    Args:
        path: Path to file
    
    Returns:
        Tuple of (can_delete, reason_if_not)
    """
    # Check if file exists
    if not os.path.exists(path):
        return False, "File does not exist"
    
    # Check if system protected
    if is_system_protected(path):
        return False, "System protected location"
    
    # Check if we have write permission to parent directory
    parent = os.path.dirname(path)
    if not os.access(parent, os.W_OK):
        return False, "No write permission to parent directory"
    
    # Check if file itself is writable (or if we own it)
    if not os.access(path, os.W_OK):
        # Check if we're the owner
        try:
            stat_info = os.stat(path)
            if stat_info.st_uid != os.getuid():
                return False, "No write permission and not owner"
        except OSError:
            return False, "Cannot check file permissions"
    
    # Check for macOS extended attributes that prevent deletion
    try:
        result = subprocess.run(
            ['xattr', '-l', path],
            capture_output=True,
            text=True,
            timeout=5
        )
        if 'com.apple.rootless' in result.stdout:
            return False, "Protected by System Integrity Protection"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    return True, None


def request_full_disk_access_instructions() -> str:
    """
    Get instructions for granting Full Disk Access
    
    Returns:
        Human-readable instructions
    """
    return """
To grant Full Disk Access (required for complete scan):

1. Open System Preferences (System Settings on macOS 13+)
2. Go to Privacy & Security → Privacy
3. Select 'Full Disk Access' in the left sidebar
4. Click the lock icon and enter your password
5. Click '+' and add Terminal (or your terminal app)
6. Restart Terminal and run the scan again

Alternatively, run the scan with sudo:
    sudo python analyzer.py --full
"""


def get_sip_status() -> Tuple[bool, str]:
    """
    Check System Integrity Protection status
    
    Returns:
        Tuple of (is_enabled, status_string)
    """
    try:
        result = subprocess.run(
            ['csrutil', 'status'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        output = result.stdout.strip()
        
        if 'enabled' in output.lower():
            return True, output
        elif 'disabled' in output.lower():
            return False, output
        else:
            return True, output  # Assume enabled if unclear
    
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return True, "Unable to determine SIP status"


def estimate_scannable_size() -> dict:
    """
    Estimate how much of the disk we can scan based on permissions
    
    Returns:
        Dict with size estimates
    """
    home = os.path.expanduser('~')
    
    estimates = {
        'home_accessible': True,
        'library_accessible': False,
        'applications_accessible': True,
        'full_disk_access': check_full_disk_access(),
    }
    
    # Check Library access
    library_path = os.path.join(home, 'Library')
    readable, _ = check_path_readable(library_path)
    estimates['library_accessible'] = readable
    
    # Check common locations
    test_paths = {
        'mail': os.path.join(home, 'Library/Mail'),
        'safari': os.path.join(home, 'Library/Safari'),
        'messages': os.path.join(home, 'Library/Messages'),
    }
    
    for name, path in test_paths.items():
        readable, _ = check_path_readable(path)
        estimates[f'{name}_accessible'] = readable
    
    return estimates
