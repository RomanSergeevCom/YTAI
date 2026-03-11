"""
File categorizer for Mac Disk Analyzer
Classifies files into meaningful categories
"""

import os
import re
from typing import List, Dict, Any, Optional
from pathlib import Path

from core.file_info import FileInfo
from config.settings import Settings, CATEGORIES, VIDEO_PRODUCTION_PATTERNS


class FileCategorizer:
    """
    Categorizes files based on extension, path, and content patterns
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize categorizer
        
        Args:
            settings: Application settings
        """
        self.settings = settings
        self.categories = CATEGORIES
        self.video_patterns = VIDEO_PRODUCTION_PATTERNS
        
        # Build lookup tables for fast matching
        self._build_lookups()
    
    def _build_lookups(self):
        """Build fast lookup tables for categorization"""
        # Extension to category mapping
        self.ext_to_category = {}
        for cat_id, cat_def in self.categories.items():
            for ext in cat_def.get('extensions', []):
                ext_lower = ext.lower().lstrip('.')
                # Don't override if already set (first category wins)
                if ext_lower not in self.ext_to_category:
                    self.ext_to_category[ext_lower] = cat_id
        
        # Compile path patterns
        self.path_patterns = {}
        for cat_id, cat_def in self.categories.items():
            patterns = []
            for path_pattern in cat_def.get('paths', []):
                expanded = os.path.expanduser(path_pattern)
                patterns.append(expanded.lower())
            for name_pattern in cat_def.get('patterns', []):
                patterns.append(name_pattern.lower())
            if patterns:
                self.path_patterns[cat_id] = patterns
    
    def categorize(self, files: List[FileInfo]) -> Dict[str, Dict[str, Any]]:
        """
        Categorize all files
        
        Args:
            files: List of FileInfo objects
        
        Returns:
            Dictionary with category summaries
        """
        # Initialize result structure
        results = {}
        for cat_id, cat_def in self.categories.items():
            results[cat_id] = {
                'name': cat_def['name'],
                'icon': cat_def.get('icon', '📁'),
                'description': cat_def.get('description', ''),
                'count': 0,
                'size': 0,
                'files': [],
                'safe_to_clean': cat_def.get('safe_to_clean', False),
                'priority': cat_def.get('priority', 'low'),
            }
        
        # Categorize each file
        for file_info in files:
            category = self._categorize_file(file_info)
            file_info.category = category
            
            results[category]['count'] += 1
            results[category]['size'] += file_info.size
            
            # Keep track of files for detailed analysis
            # Only store reference info to save memory
            if len(results[category]['files']) < 1000:
                results[category]['files'].append({
                    'path': file_info.path,
                    'size': file_info.size,
                    'modified': file_info.modified_time,
                })
        
        # Sort files in each category by size
        for cat_id in results:
            results[cat_id]['files'].sort(key=lambda x: x['size'], reverse=True)
        
        # Add computed stats
        total_size = sum(r['size'] for r in results.values())
        for cat_id in results:
            if total_size > 0:
                results[cat_id]['percentage'] = (results[cat_id]['size'] / total_size) * 100
            else:
                results[cat_id]['percentage'] = 0
        
        return results
    
    def _categorize_file(self, file_info: FileInfo) -> str:
        """
        Determine category for a single file
        
        Args:
            file_info: File to categorize
        
        Returns:
            Category ID string
        """
        path_lower = file_info.path.lower()
        ext_lower = file_info.extension.lower().lstrip('.')
        
        # Check for cache patterns first (high priority)
        if self._is_cache_file(file_info):
            # Determine which type of cache
            if '/adobe/' in path_lower or 'adobe' in path_lower:
                file_info.is_cache = True
                return 'cache_adobe'
            if '/davinci' in path_lower or 'resolve' in path_lower or '/blackmagic' in path_lower:
                file_info.is_cache = True
                return 'cache_resolve'
            if '/finalcut' in path_lower or 'fcpx' in path_lower:
                file_info.is_cache = True
                return 'cache_fcpx'
            if '/caches/' in path_lower:
                file_info.is_cache = True
                return 'cache_system'
        
        # Check Trash
        if '/.trash/' in path_lower or '/.trash' in path_lower:
            return 'trash'
        
        # Check Downloads
        if '/downloads/' in path_lower:
            # Check if it's an installer
            if ext_lower in ['dmg', 'pkg', 'iso']:
                return 'installers'
            return 'downloads'
        
        # Check for Xcode/Dev paths
        if '/developer/' in path_lower or '/deriveddata/' in path_lower:
            return 'xcode'
        if 'node_modules' in path_lower:
            return 'node_modules'
        if '/venv/' in path_lower or '/.venv/' in path_lower or '/virtualenv/' in path_lower:
            return 'python_env'
        
        # Check for Docker
        if 'docker' in path_lower:
            return 'docker'
        
        # Check for AI/ML models
        if any(p in path_lower for p in ['.ollama', 'huggingface', 'lm studio', '.lmstudio']):
            return 'ai_models'
        if ext_lower in ['gguf', 'safetensors', 'ggml']:
            return 'ai_models'
        
        # Check for Homebrew
        if '/homebrew/' in path_lower:
            return 'homebrew'
        
        # Check for cloud storage
        if any(p in path_lower for p in ['mobile documents', 'dropbox', 'google drive', 'onedrive']):
            return 'cloud_local'
        
        # Check logs
        if '/logs/' in path_lower or ext_lower in ['log', 'crash']:
            return 'logs'
        
        # Check for video project files
        if ext_lower in ['prproj', 'aep', 'drp', 'fcpbundle', 'fcpproject']:
            return 'video_projects'
        
        # Check for mail/messages
        if '/mail/' in path_lower or '/messages/' in path_lower:
            return 'mail'
        
        # Check by extension for media types
        if ext_lower in self.ext_to_category:
            cat = self.ext_to_category[ext_lower]
            
            # For media files, try to distinguish raw vs export
            if cat in ['media_raw']:
                if self._is_export_file(file_info):
                    return 'media_exports'
            
            return cat
        
        # Check for applications
        if path_lower.endswith('.app') or '/applications/' in path_lower:
            return 'applications'
        
        # Check for photos
        if '/pictures/' in path_lower or '.photoslibrary' in path_lower:
            return 'photos'
        
        # Check for music
        if '/music/' in path_lower:
            return 'music'
        
        # Check for documents
        if '/documents/' in path_lower:
            return 'documents'
        
        # Installers by extension
        if ext_lower in ['dmg', 'pkg', 'iso']:
            return 'installers'
        
        return 'other'
    
    def _is_cache_file(self, file_info: FileInfo) -> bool:
        """Check if file is a cache file"""
        path_lower = file_info.path.lower()
        
        # Common cache path patterns
        cache_indicators = [
            '/cache', 'cache/', '/caches/',
            '/temp/', '/tmp/', '.tmp',
            '/preview files/', '/render cache/',
            '/media cache/', '/peak files/',
            '/optimized media/', '/cacheclip/',
            'auto-save', 'autosave',
        ]
        
        for indicator in cache_indicators:
            if indicator in path_lower:
                return True
        
        # Check patterns from config
        for pattern in self.video_patterns['cache_patterns']:
            if pattern.lower() in path_lower:
                return True
        
        return False
    
    def _is_export_file(self, file_info: FileInfo) -> bool:
        """Check if a media file is an export/render"""
        path_lower = file_info.path.lower()
        
        for pattern in self.video_patterns['export_patterns']:
            if pattern.lower() in path_lower:
                return True
        
        return False
    
    def _is_source_file(self, file_info: FileInfo) -> bool:
        """Check if a media file is source footage"""
        path_lower = file_info.path.lower()
        
        for pattern in self.video_patterns['source_patterns']:
            if pattern.lower() in path_lower:
                return True
        
        return False
    
    def get_category_info(self, category_id: str) -> Dict[str, Any]:
        """Get information about a category"""
        if category_id in self.categories:
            return self.categories[category_id].copy()
        return {'name': category_id, 'icon': '📁', 'description': 'Unknown category'}
    
    def get_cleanable_categories(self) -> List[str]:
        """Get list of categories that are safe to clean"""
        return [
            cat_id for cat_id, cat_def in self.categories.items()
            if cat_def.get('safe_to_clean', False)
        ]


def quick_categorize(files: List[FileInfo]) -> Dict[str, int]:
    """
    Quick categorization returning just category sizes
    
    Args:
        files: List of files
    
    Returns:
        Dict of category -> total size
    """
    settings = Settings()
    categorizer = FileCategorizer(settings)
    
    sizes = {}
    for f in files:
        cat = categorizer._categorize_file(f)
        sizes[cat] = sizes.get(cat, 0) + f.size
    
    return sizes
