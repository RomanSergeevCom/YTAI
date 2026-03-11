"""
File information data structures
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
import os


@dataclass
class FileInfo:
    """Represents information about a single file"""
    
    path: str
    size: int
    modified_time: float
    created_time: float
    accessed_time: float
    
    # Optional extended info
    extension: str = ""
    filename: str = ""
    parent_dir: str = ""
    
    # Analysis results (filled in later)
    category: str = "other"
    is_hidden: bool = False
    is_symlink: bool = False
    is_cache: bool = False
    is_duplicate: bool = False
    
    # Hashes (computed on demand)
    quick_hash: Optional[str] = None
    full_hash: Optional[str] = None
    
    # Media info (for video/audio files)
    media_info: Optional[Dict[str, Any]] = None
    
    # Owner info
    owner: Optional[str] = None
    group: Optional[str] = None
    permissions: Optional[str] = None
    
    def __post_init__(self):
        """Compute derived fields"""
        if not self.filename:
            self.filename = os.path.basename(self.path)
        if not self.parent_dir:
            self.parent_dir = os.path.dirname(self.path)
        if not self.extension:
            _, ext = os.path.splitext(self.filename)
            self.extension = ext.lower()
        if self.filename.startswith('.'):
            self.is_hidden = True
    
    @property
    def modified_datetime(self) -> datetime:
        """Get modification time as datetime"""
        return datetime.fromtimestamp(self.modified_time)
    
    @property
    def created_datetime(self) -> datetime:
        """Get creation time as datetime"""
        return datetime.fromtimestamp(self.created_time)
    
    @property
    def accessed_datetime(self) -> datetime:
        """Get access time as datetime"""
        return datetime.fromtimestamp(self.accessed_time)
    
    @property
    def age_days(self) -> int:
        """Get file age in days since last modification"""
        return (datetime.now() - self.modified_datetime).days
    
    @property
    def days_since_access(self) -> int:
        """Get days since last access"""
        return (datetime.now() - self.accessed_datetime).days
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'path': self.path,
            'size': self.size,
            'modified_time': self.modified_time,
            'created_time': self.created_time,
            'accessed_time': self.accessed_time,
            'extension': self.extension,
            'filename': self.filename,
            'parent_dir': self.parent_dir,
            'category': self.category,
            'is_hidden': self.is_hidden,
            'is_symlink': self.is_symlink,
            'is_cache': self.is_cache,
            'is_duplicate': self.is_duplicate,
            'quick_hash': self.quick_hash,
            'media_info': self.media_info,
        }
    
    @classmethod
    def from_path(cls, path: str) -> Optional['FileInfo']:
        """
        Create FileInfo from file path
        
        Args:
            path: Path to file
        
        Returns:
            FileInfo object or None on error
        """
        try:
            stat_result = os.stat(path)
            
            # Get birth time (creation time) on macOS
            try:
                created = stat_result.st_birthtime
            except AttributeError:
                created = stat_result.st_ctime
            
            return cls(
                path=path,
                size=stat_result.st_size,
                modified_time=stat_result.st_mtime,
                created_time=created,
                accessed_time=stat_result.st_atime,
                is_symlink=os.path.islink(path),
            )
        except (OSError, PermissionError):
            return None


@dataclass
class DirectoryInfo:
    """Represents aggregated information about a directory"""
    
    path: str
    total_size: int = 0
    file_count: int = 0
    dir_count: int = 0
    
    # Breakdown
    files: List[FileInfo] = field(default_factory=list)
    subdirs: List['DirectoryInfo'] = field(default_factory=list)
    
    # Categories within this directory
    category_sizes: Dict[str, int] = field(default_factory=dict)
    extension_sizes: Dict[str, int] = field(default_factory=dict)
    
    # Flags
    is_project: bool = False
    project_type: Optional[str] = None
    is_cache_dir: bool = False
    
    @property
    def name(self) -> str:
        """Get directory name"""
        return os.path.basename(self.path) or self.path
    
    @property
    def depth(self) -> int:
        """Get directory depth from root"""
        return self.path.count(os.sep)
    
    def add_file(self, file_info: FileInfo):
        """Add file to directory stats"""
        self.files.append(file_info)
        self.total_size += file_info.size
        self.file_count += 1
        
        # Update category breakdown
        cat = file_info.category
        self.category_sizes[cat] = self.category_sizes.get(cat, 0) + file_info.size
        
        # Update extension breakdown
        ext = file_info.extension or 'no_ext'
        self.extension_sizes[ext] = self.extension_sizes.get(ext, 0) + file_info.size
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'path': self.path,
            'name': self.name,
            'total_size': self.total_size,
            'file_count': self.file_count,
            'dir_count': self.dir_count,
            'category_sizes': self.category_sizes,
            'extension_sizes': self.extension_sizes,
            'is_project': self.is_project,
            'project_type': self.project_type,
            'is_cache_dir': self.is_cache_dir,
        }


@dataclass
class DuplicateGroup:
    """Represents a group of duplicate files"""
    
    hash_value: str
    size: int
    files: List[FileInfo] = field(default_factory=list)
    
    @property
    def count(self) -> int:
        """Number of duplicates"""
        return len(self.files)
    
    @property
    def wasted_space(self) -> int:
        """Space wasted by duplicates (total - one copy)"""
        return self.size * (self.count - 1) if self.count > 1 else 0
    
    @property
    def original(self) -> Optional[FileInfo]:
        """Get the 'original' file (oldest by creation time)"""
        if not self.files:
            return None
        return min(self.files, key=lambda f: f.created_time)
    
    @property
    def duplicates(self) -> List[FileInfo]:
        """Get list of duplicate files (excluding original)"""
        if len(self.files) <= 1:
            return []
        original = self.original
        return [f for f in self.files if f.path != original.path]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'hash': self.hash_value,
            'size': self.size,
            'count': self.count,
            'wasted_space': self.wasted_space,
            'files': [f.to_dict() for f in self.files],
            'original_path': self.original.path if self.original else None,
        }


@dataclass 
class AppFootprint:
    """Represents total footprint of an application"""
    
    name: str
    bundle_id: Optional[str] = None
    
    # Size breakdown
    app_size: int = 0
    cache_size: int = 0
    data_size: int = 0
    preferences_size: int = 0
    logs_size: int = 0
    
    # Paths found
    app_paths: List[str] = field(default_factory=list)
    cache_paths: List[str] = field(default_factory=list)
    data_paths: List[str] = field(default_factory=list)
    
    # Files
    files: List[FileInfo] = field(default_factory=list)
    
    @property
    def total_size(self) -> int:
        """Total size of all app-related data"""
        return self.app_size + self.cache_size + self.data_size + self.preferences_size + self.logs_size
    
    @property
    def cleanable_size(self) -> int:
        """Size that can be safely cleaned (caches)"""
        return self.cache_size + self.logs_size
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'name': self.name,
            'bundle_id': self.bundle_id,
            'total_size': self.total_size,
            'app_size': self.app_size,
            'cache_size': self.cache_size,
            'data_size': self.data_size,
            'preferences_size': self.preferences_size,
            'logs_size': self.logs_size,
            'cleanable_size': self.cleanable_size,
            'app_paths': self.app_paths,
            'cache_paths': self.cache_paths,
        }


@dataclass
class Recommendation:
    """A cleanup recommendation"""
    
    title: str
    description: str
    category: str  # 'safe', 'review', 'archive', 'caution'
    priority: str  # 'high', 'medium', 'low'
    
    size: int = 0
    paths: List[str] = field(default_factory=list)
    files: List[FileInfo] = field(default_factory=list)
    
    # Action info
    action_type: str = "delete"  # 'delete', 'archive', 'move', 'review'
    reversible: bool = True
    
    # Safety
    safe_to_auto_clean: bool = False
    requires_app_closed: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'title': self.title,
            'description': self.description,
            'category': self.category,
            'priority': self.priority,
            'size': self.size,
            'paths': self.paths,
            'action_type': self.action_type,
            'reversible': self.reversible,
            'safe_to_auto_clean': self.safe_to_auto_clean,
            'requires_app_closed': self.requires_app_closed,
            'file_count': len(self.files),
        }
