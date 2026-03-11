"""
Duplicate file finder for Mac Disk Analyzer
Uses size + hash for efficient duplicate detection
"""

import os
from typing import List, Dict, Any, Optional
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.file_info import FileInfo, DuplicateGroup
from config.settings import Settings
from utils.hashing import hash_file_quick, hash_file_md5, compare_files_binary
from utils.formatting import format_size


class DuplicateFinder:
    """
    Finds duplicate files using a multi-phase approach:
    1. Group by size (same size = potential duplicate)
    2. Quick hash (first/middle/last chunks)
    3. Full hash verification (optional)
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize finder
        
        Args:
            settings: Application settings
        """
        self.settings = settings
        self.min_size = settings.duplicate_min_size
    
    def find_duplicates(self, files: List[FileInfo]) -> Dict[str, Dict[str, Any]]:
        """
        Find all duplicate files
        
        Args:
            files: List of FileInfo objects to check
        
        Returns:
            Dictionary mapping hash -> duplicate group info
        """
        # Phase 1: Group by size
        if self.settings.verbose:
            print("    Phase 1: Grouping by size...")
        
        size_groups = self._group_by_size(files)
        potential_dups = {
            size: group for size, group in size_groups.items()
            if len(group) > 1
        }
        
        if self.settings.verbose:
            print(f"    Found {len(potential_dups)} size groups with potential duplicates")
        
        if not potential_dups:
            return {}
        
        # Phase 2: Quick hash comparison
        if self.settings.verbose:
            print("    Phase 2: Computing quick hashes...")
        
        duplicates = {}
        files_to_hash = []
        
        for size, group in potential_dups.items():
            files_to_hash.extend(group)
        
        # Create path to FileInfo lookup
        path_to_file = {f.path: f for f in files_to_hash}
        
        # Hash files (with progress)
        hash_results = self._compute_hashes(files_to_hash)
        
        # Group by hash
        hash_groups = defaultdict(list)
        for file_path, hash_val in hash_results.items():
            if hash_val and file_path in path_to_file:
                hash_groups[hash_val].append(path_to_file[file_path])
        
        # Build duplicate groups
        for hash_val, group in hash_groups.items():
            if len(group) > 1:
                size = group[0].size
                wasted = size * (len(group) - 1)
                
                duplicates[hash_val] = {
                    'hash': hash_val,
                    'size': size,
                    'count': len(group),
                    'wasted_space': wasted,
                    'paths': [f.path for f in group],
                    'files': group,
                    'original': min(group, key=lambda f: f.created_time).path,
                }
                
                # Mark files as duplicates
                for f in group:
                    f.is_duplicate = True
                    f.quick_hash = hash_val
        
        if self.settings.verbose:
            total_wasted = sum(d['wasted_space'] for d in duplicates.values())
            print(f"    Found {len(duplicates)} duplicate groups ({format_size(total_wasted)} wasted)")
        
        return duplicates
    
    def _group_by_size(self, files: List[FileInfo]) -> Dict[int, List[FileInfo]]:
        """Group files by size"""
        groups = defaultdict(list)
        
        for file_info in files:
            # Skip files below minimum size
            if file_info.size < self.min_size:
                continue
            
            groups[file_info.size].append(file_info)
        
        return groups
    
    def _compute_hashes(self, files: List[FileInfo]) -> Dict[str, Optional[str]]:
        """
        Compute quick hashes for files
        
        Args:
            files: Files to hash
        
        Returns:
            Dict mapping file path -> hash (or None on error)
        """
        results = {}
        total = len(files)
        completed = 0
        
        # Use thread pool for I/O bound hashing
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_path = {
                executor.submit(hash_file_quick, f.path): f.path
                for f in files
            }
            
            for future in as_completed(future_to_path):
                file_path = future_to_path[future]
                try:
                    hash_val = future.result()
                    results[file_path] = hash_val
                except Exception:
                    results[file_path] = None
                
                completed += 1
                if self.settings.verbose and completed % 100 == 0:
                    print(f"\r    Hashed {completed}/{total} files", end='', flush=True)
        
        if self.settings.verbose:
            print(f"\r    Hashed {total}/{total} files")
        
        return results
    
    def verify_duplicates(self, duplicate_group: Dict[str, Any]) -> bool:
        """
        Verify duplicates by full comparison
        
        Args:
            duplicate_group: A duplicate group dict
        
        Returns:
            True if all files are truly identical
        """
        paths = duplicate_group.get('paths', [])
        if len(paths) < 2:
            return False
        
        # Compare first file with all others
        first = paths[0]
        for other in paths[1:]:
            if not compare_files_binary(first, other):
                return False
        
        return True
    
    def find_near_duplicates(self, files: List[FileInfo], 
                            size_tolerance: float = 0.01) -> List[Dict[str, Any]]:
        """
        Find files that are nearly the same size (potential re-encodes)
        
        Args:
            files: Files to check
            size_tolerance: Size difference tolerance (0.01 = 1%)
        
        Returns:
            List of near-duplicate groups
        """
        # Filter to video files
        video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.m4v', '.webm', '.mxf'}
        video_files = [
            f for f in files 
            if f.extension.lower() in video_exts and f.size > 100 * 1024 * 1024  # > 100MB
        ]
        
        if not video_files:
            return []
        
        # Sort by size
        video_files.sort(key=lambda f: f.size)
        
        near_dups = []
        used = set()
        
        for i, f1 in enumerate(video_files):
            if f1.path in used:
                continue
            
            group = [f1]
            
            for f2 in video_files[i+1:]:
                if f2.path in used:
                    continue
                
                # Check if sizes are within tolerance
                size_diff = abs(f1.size - f2.size) / f1.size
                if size_diff <= size_tolerance:
                    group.append(f2)
                    used.add(f2.path)
                elif f2.size > f1.size * (1 + size_tolerance):
                    # Files are sorted by size, so no point checking further
                    break
            
            if len(group) > 1:
                used.add(f1.path)
                near_dups.append({
                    'files': group,
                    'count': len(group),
                    'total_size': sum(f.size for f in group),
                    'size_variance': max(f.size for f in group) - min(f.size for f in group),
                })
        
        return near_dups


def find_duplicates_quick(files: List[FileInfo]) -> Dict[str, int]:
    """
    Quick duplicate finding returning just wasted space by hash
    
    Args:
        files: List of files
    
    Returns:
        Dict of hash -> wasted_space
    """
    settings = Settings()
    settings.verbose = False
    finder = DuplicateFinder(settings)
    
    dups = finder.find_duplicates(files)
    return {h: d['wasted_space'] for h, d in dups.items()}
