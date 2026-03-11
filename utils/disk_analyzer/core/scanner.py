"""
Filesystem scanner for Mac Disk Analyzer
Uses os.scandir for performance on APFS
"""

import os
import sys
from pathlib import Path
from typing import List, Optional, Set, Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import fnmatch
import time

from .file_info import FileInfo, DirectoryInfo
from config.settings import Settings
from utils.permissions import is_system_protected, is_symlink_loop, check_path_readable
from utils.formatting import format_size


class DiskScanner:
    """
    High-performance disk scanner optimized for macOS APFS
    """
    
    def __init__(self, settings: Settings, exclude_paths: List[str] = None):
        """
        Initialize scanner
        
        Args:
            settings: Scanner settings
            exclude_paths: Additional paths to exclude
        """
        self.settings = settings
        self.exclude_paths = set(exclude_paths or [])
        
        # Add default excludes from settings
        for pattern in settings.exclude_patterns:
            self.exclude_paths.add(os.path.expanduser(pattern))
        
        # Stats
        self.files_scanned = 0
        self.dirs_scanned = 0
        self.errors = []
        self.skipped_paths = []
        
        # Progress tracking
        self.last_progress_time = 0
        self.progress_interval = 0.5  # Update every 0.5 seconds
    
    def scan(self, paths: List[str]) -> List[FileInfo]:
        """
        Scan multiple paths and return all files
        
        Args:
            paths: List of paths to scan
        
        Returns:
            List of FileInfo objects
        """
        all_files = []
        
        for path in paths:
            path = os.path.expanduser(path)
            if not os.path.exists(path):
                self.errors.append(f"Path does not exist: {path}")
                continue
            
            if self.settings.verbose:
                print(f"  Scanning: {path}")
            
            files = list(self._scan_path(path))
            all_files.extend(files)
            
            if self.settings.verbose:
                print(f"\n    Found {len(files)} files")
        
        return all_files
    
    def _scan_path(self, root_path: str, depth: int = 0) -> Generator[FileInfo, None, None]:
        """
        Recursively scan a path
        
        Args:
            root_path: Root path to scan
            depth: Current recursion depth
        
        Yields:
            FileInfo objects
        """
        # Prevent infinite recursion
        if depth > 50:
            self.errors.append(f"Max depth exceeded: {root_path}")
            return
        
        # Show which directory we're scanning (top-level only)
        if depth == 0 or (depth <= 2 and self.dirs_scanned % 100 == 0):
            short_path = root_path[:60] + '...' if len(root_path) > 60 else root_path
            print(f"\r    Scanning: {short_path:<65}", end='', flush=True)
        
        try:
            entries = list(os.scandir(root_path))
        except PermissionError:
            self.errors.append(f"Permission denied: {root_path}")
            return
        except OSError as e:
            self.errors.append(f"Error scanning {root_path}: {e}")
            return
        
        for entry in entries:
            try:
                # Skip excluded paths
                if self._should_exclude(entry.path):
                    self.skipped_paths.append(entry.path)
                    continue
                
                if entry.is_file(follow_symlinks=False):
                    # Process file
                    file_info = self._process_file(entry)
                    if file_info:
                        yield file_info
                        self.files_scanned += 1
                        self._report_progress()
                
                elif entry.is_dir(follow_symlinks=False):
                    # Skip symlinks to avoid loops
                    if entry.is_symlink():
                        continue
                    
                    self.dirs_scanned += 1
                    
                    # Recurse
                    yield from self._scan_path(entry.path, depth + 1)
                
            except PermissionError:
                self.errors.append(f"Permission denied: {entry.path}")
            except OSError as e:
                self.errors.append(f"Error accessing {entry.path}: {e}")
    
    def _process_file(self, entry: os.DirEntry) -> Optional[FileInfo]:
        """
        Process a single file entry
        
        Args:
            entry: Directory entry from os.scandir
        
        Returns:
            FileInfo or None
        """
        try:
            # Get stat info (use cached stat from scandir when possible)
            try:
                stat_result = entry.stat(follow_symlinks=False)
            except OSError:
                return None
            
            # Skip if below minimum size
            if stat_result.st_size < self.settings.min_size:
                return None
            
            # Get birth time (creation time) on macOS
            try:
                created = stat_result.st_birthtime
            except AttributeError:
                created = stat_result.st_ctime
            
            file_info = FileInfo(
                path=entry.path,
                size=stat_result.st_size,
                modified_time=stat_result.st_mtime,
                created_time=created,
                accessed_time=stat_result.st_atime,
                is_symlink=entry.is_symlink(),
            )
            
            return file_info
        
        except Exception as e:
            if self.settings.debug:
                self.errors.append(f"Error processing {entry.path}: {e}")
            return None
    
    def _should_exclude(self, path: str) -> bool:
        """
        Check if path should be excluded from scan
        
        Args:
            path: Path to check
        
        Returns:
            True if path should be excluded
        """
        # Normalize path
        path = os.path.normpath(path)
        
        # Check exact matches
        if path in self.exclude_paths:
            return True
        
        # Check if any component matches exclude patterns
        path_parts = path.split(os.sep)
        
        for exclude in self.exclude_paths:
            # Handle patterns
            if '*' in exclude:
                if fnmatch.fnmatch(path, exclude):
                    return True
                # Check if any path component matches
                exclude_base = os.path.basename(exclude)
                for part in path_parts:
                    if fnmatch.fnmatch(part, exclude_base):
                        return True
            else:
                # Exact match check
                exclude_norm = os.path.normpath(os.path.expanduser(exclude))
                if path.startswith(exclude_norm):
                    return True
                # Check basename
                if os.path.basename(exclude) in path_parts:
                    # Only if it's a known directory pattern
                    base = os.path.basename(exclude)
                    if base in ['node_modules', '.git', '__pycache__', '.Trash']:
                        return True
        
        # Check for system protected paths
        if is_system_protected(path):
            return True
        
        return False
    
    def _report_progress(self):
        """Report scan progress (always shown for full scans)"""
        current_time = time.time()
        if current_time - self.last_progress_time >= self.progress_interval:
            self.last_progress_time = current_time
            print(f"\r    Files: {self.files_scanned:,} | Dirs: {self.dirs_scanned:,}    ", end='', flush=True)
    
    def get_stats(self) -> dict:
        """Get scanning statistics"""
        return {
            'files_scanned': self.files_scanned,
            'dirs_scanned': self.dirs_scanned,
            'errors_count': len(self.errors),
            'skipped_count': len(self.skipped_paths),
        }


class ParallelDiskScanner(DiskScanner):
    """
    Parallel disk scanner using thread pool for better performance
    Useful for scanning multiple top-level directories simultaneously
    """
    
    def __init__(self, settings: Settings, exclude_paths: List[str] = None,
                 max_workers: int = 4):
        """
        Initialize parallel scanner
        
        Args:
            settings: Scanner settings
            exclude_paths: Paths to exclude
            max_workers: Maximum parallel workers
        """
        super().__init__(settings, exclude_paths)
        self.max_workers = max_workers
    
    def scan(self, paths: List[str]) -> List[FileInfo]:
        """
        Scan multiple paths in parallel
        
        Args:
            paths: List of paths to scan
        
        Returns:
            List of FileInfo objects
        """
        # Expand paths and filter existing
        valid_paths = []
        for path in paths:
            path = os.path.expanduser(path)
            if os.path.exists(path):
                valid_paths.append(path)
            else:
                self.errors.append(f"Path does not exist: {path}")
        
        if not valid_paths:
            return []
        
        # For single path, use standard scan
        if len(valid_paths) == 1:
            return super().scan(valid_paths)
        
        # Parallel scan of multiple paths
        all_files = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_path = {
                executor.submit(self._scan_single_path, path): path
                for path in valid_paths
            }
            
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    files = future.result()
                    all_files.extend(files)
                    if self.settings.verbose:
                        print(f"  Completed: {path} ({len(files)} files)")
                except Exception as e:
                    self.errors.append(f"Error scanning {path}: {e}")
        
        return all_files
    
    def _scan_single_path(self, path: str) -> List[FileInfo]:
        """Scan a single path (for parallel execution)"""
        return list(self._scan_path(path))


def quick_scan_directory(path: str, min_size: int = 0) -> List[FileInfo]:
    """
    Quick utility function to scan a single directory
    
    Args:
        path: Directory path
        min_size: Minimum file size to include
    
    Returns:
        List of FileInfo objects
    """
    settings = Settings()
    settings.min_size = min_size
    settings.verbose = False
    
    scanner = DiskScanner(settings)
    return scanner.scan([path])


def get_directory_size(path: str) -> int:
    """
    Get total size of a directory
    
    Args:
        path: Directory path
    
    Returns:
        Total size in bytes
    """
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += get_directory_size(entry.path)
            except (PermissionError, OSError):
                pass
    except (PermissionError, OSError):
        pass
    return total


def find_large_directories(path: str, min_size: int = 1024**3, 
                          max_depth: int = 3) -> List[DirectoryInfo]:
    """
    Find directories larger than a threshold
    
    Args:
        path: Root path to search
        min_size: Minimum size threshold (default 1GB)
        max_depth: Maximum depth to search
    
    Returns:
        List of DirectoryInfo for large directories
    """
    large_dirs = []
    
    def scan_dir(dir_path: str, depth: int):
        if depth > max_depth:
            return
        
        try:
            total_size = 0
            file_count = 0
            
            for entry in os.scandir(dir_path):
                try:
                    if entry.is_file(follow_symlinks=False):
                        total_size += entry.stat(follow_symlinks=False).st_size
                        file_count += 1
                    elif entry.is_dir(follow_symlinks=False):
                        # Get subdir size
                        subdir_size = get_directory_size(entry.path)
                        total_size += subdir_size
                        
                        # Recurse
                        scan_dir(entry.path, depth + 1)
                except (PermissionError, OSError):
                    pass
            
            if total_size >= min_size:
                dir_info = DirectoryInfo(
                    path=dir_path,
                    total_size=total_size,
                    file_count=file_count
                )
                large_dirs.append(dir_info)
        
        except (PermissionError, OSError):
            pass
    
    scan_dir(os.path.expanduser(path), 0)
    return sorted(large_dirs, key=lambda d: d.total_size, reverse=True)
