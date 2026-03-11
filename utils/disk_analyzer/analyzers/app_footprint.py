"""
Application footprint analyzer for Mac Disk Analyzer
Maps each application to all its data across the system
"""

import os
import glob
from typing import List, Dict, Any, Optional
from pathlib import Path

from core.file_info import FileInfo, AppFootprint
from config.settings import Settings, APP_SIGNATURES
from utils.formatting import format_size


class AppFootprintAnalyzer:
    """
    Analyzes the total disk footprint of applications including:
    - Application bundle
    - Caches
    - Application Support data
    - Preferences
    - Logs
    - Containers (sandboxed apps)
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize analyzer
        
        Args:
            settings: Application settings
        """
        self.settings = settings
        self.app_signatures = APP_SIGNATURES
        self.home = os.path.expanduser('~')
    
    def analyze(self, files: List[FileInfo]) -> Dict[str, AppFootprint]:
        """
        Analyze application footprints
        
        Args:
            files: List of all scanned files
        
        Returns:
            Dictionary mapping app name -> AppFootprint
        """
        # Build path index for fast lookup
        path_to_file = {f.path: f for f in files}
        
        # Known apps from signatures
        footprints = {}
        
        for app_name, signature in self.app_signatures.items():
            footprint = self._analyze_known_app(app_name, signature, path_to_file, files)
            if footprint.total_size > 0:
                footprints[app_name] = footprint
        
        # Detect additional apps from /Applications
        detected_apps = self._detect_installed_apps(files)
        
        for app_name, app_path in detected_apps.items():
            if app_name not in footprints:
                footprint = self._analyze_generic_app(app_name, app_path, path_to_file, files)
                if footprint.total_size > 0:
                    footprints[app_name] = footprint
        
        return footprints
    
    def _analyze_known_app(self, app_name: str, signature: Dict[str, Any],
                          path_to_file: Dict[str, FileInfo], 
                          all_files: List[FileInfo]) -> AppFootprint:
        """
        Analyze a known application with predefined paths
        
        Args:
            app_name: Application name
            signature: App signature from config
            path_to_file: Path lookup dict
            all_files: All scanned files
        
        Returns:
            AppFootprint object
        """
        footprint = AppFootprint(
            name=app_name,
            bundle_id=signature.get('bundle_id')
        )
        
        # Check defined paths
        for path_pattern in signature.get('paths', []):
            expanded = os.path.expanduser(path_pattern)
            
            # Handle glob patterns
            if '*' in expanded:
                matched_paths = glob.glob(expanded)
            else:
                matched_paths = [expanded]
            
            for path in matched_paths:
                # Find all files under this path
                matching_files = [
                    f for f in all_files
                    if f.path.startswith(path)
                ]
                
                for f in matching_files:
                    footprint.files.append(f)
                    
                    # Categorize the file
                    if '/Applications/' in f.path or f.path.endswith('.app'):
                        footprint.app_size += f.size
                        if path not in footprint.app_paths:
                            footprint.app_paths.append(path)
                    elif '/Caches/' in f.path or '/Cache/' in f.path:
                        footprint.cache_size += f.size
                        if path not in footprint.cache_paths:
                            footprint.cache_paths.append(path)
                    elif '/Logs/' in f.path or f.extension == '.log':
                        footprint.logs_size += f.size
                    elif '/Preferences/' in f.path or f.extension == '.plist':
                        footprint.preferences_size += f.size
                    else:
                        footprint.data_size += f.size
                        if path not in footprint.data_paths:
                            footprint.data_paths.append(path)
        
        # Also check cache paths specifically
        for cache_path in signature.get('cache_paths', []):
            expanded = os.path.expanduser(cache_path)
            
            if '*' in expanded:
                matched_paths = glob.glob(expanded)
            else:
                matched_paths = [expanded]
            
            for path in matched_paths:
                matching_files = [
                    f for f in all_files
                    if f.path.startswith(path) and f not in footprint.files
                ]
                
                for f in matching_files:
                    footprint.files.append(f)
                    footprint.cache_size += f.size
                    if path not in footprint.cache_paths:
                        footprint.cache_paths.append(path)
        
        return footprint
    
    def _analyze_generic_app(self, app_name: str, app_path: str,
                            path_to_file: Dict[str, FileInfo],
                            all_files: List[FileInfo]) -> AppFootprint:
        """
        Analyze a generic application by inferring its data locations
        
        Args:
            app_name: Application name
            app_path: Path to .app bundle
            path_to_file: Path lookup dict
            all_files: All scanned files
        
        Returns:
            AppFootprint object
        """
        footprint = AppFootprint(name=app_name)
        
        # Clean app name for path matching
        clean_name = app_name.replace('.app', '')
        
        # Common path patterns for app data
        search_patterns = [
            app_path,  # App bundle itself
            f"{self.home}/Library/Application Support/{clean_name}",
            f"{self.home}/Library/Application Support/{clean_name}*",
            f"{self.home}/Library/Caches/{clean_name}*",
            f"{self.home}/Library/Caches/com.*.{clean_name}*",
            f"{self.home}/Library/Preferences/{clean_name}*",
            f"{self.home}/Library/Preferences/com.*.{clean_name}*",
            f"{self.home}/Library/Logs/{clean_name}*",
            f"{self.home}/Library/Containers/*{clean_name}*",
            f"{self.home}/Library/Group Containers/*{clean_name}*",
        ]
        
        for pattern in search_patterns:
            if '*' in pattern:
                matched_paths = glob.glob(pattern)
            else:
                matched_paths = [pattern] if os.path.exists(pattern) else []
            
            for path in matched_paths:
                matching_files = [
                    f for f in all_files
                    if f.path.startswith(path) and f not in footprint.files
                ]
                
                for f in matching_files:
                    footprint.files.append(f)
                    
                    # Categorize
                    if f.path.startswith(app_path):
                        footprint.app_size += f.size
                        if app_path not in footprint.app_paths:
                            footprint.app_paths.append(app_path)
                    elif '/Caches/' in f.path:
                        footprint.cache_size += f.size
                        if path not in footprint.cache_paths:
                            footprint.cache_paths.append(path)
                    elif '/Logs/' in f.path:
                        footprint.logs_size += f.size
                    elif '/Preferences/' in f.path:
                        footprint.preferences_size += f.size
                    else:
                        footprint.data_size += f.size
                        if path not in footprint.data_paths:
                            footprint.data_paths.append(path)
        
        return footprint
    
    def _detect_installed_apps(self, files: List[FileInfo]) -> Dict[str, str]:
        """
        Detect installed applications from file list
        
        Args:
            files: All scanned files
        
        Returns:
            Dict of app_name -> app_path
        """
        apps = {}
        
        # Look for .app bundles
        app_locations = ['/Applications', os.path.expanduser('~/Applications')]
        
        for f in files:
            # Check if file is inside an .app bundle
            path_parts = f.path.split('/')
            
            for i, part in enumerate(path_parts):
                if part.endswith('.app'):
                    app_name = part
                    app_path = '/'.join(path_parts[:i+1])
                    
                    # Only include apps in standard locations
                    for loc in app_locations:
                        if app_path.startswith(loc):
                            if app_name not in apps:
                                apps[app_name] = app_path
                            break
                    break
        
        return apps
    
    def find_orphaned_app_data(self, files: List[FileInfo]) -> List[Dict[str, Any]]:
        """
        Find application data for apps that are no longer installed
        
        Args:
            files: All scanned files
        
        Returns:
            List of orphaned data findings
        """
        orphaned = []
        
        # Get installed apps
        installed = self._detect_installed_apps(files)
        installed_names = {
            name.replace('.app', '').lower() 
            for name in installed.keys()
        }
        
        # Check Application Support for orphans
        app_support = os.path.expanduser('~/Library/Application Support')
        
        # Find all directories in Application Support
        app_support_dirs = set()
        for f in files:
            if f.path.startswith(app_support):
                rel_path = f.path[len(app_support)+1:]
                if '/' in rel_path:
                    dir_name = rel_path.split('/')[0]
                    app_support_dirs.add(dir_name)
        
        # Check which ones don't have corresponding apps
        for dir_name in app_support_dirs:
            dir_name_lower = dir_name.lower()
            
            # Skip known system directories
            if dir_name_lower in ['addressbook', 'knowledge', 'cloudkit', 'icdd']:
                continue
            
            # Check if any installed app matches
            has_app = any(
                dir_name_lower in app_name or app_name in dir_name_lower
                for app_name in installed_names
            )
            
            if not has_app:
                dir_path = os.path.join(app_support, dir_name)
                
                # Calculate size
                size = sum(
                    f.size for f in files
                    if f.path.startswith(dir_path)
                )
                
                if size > 1024 * 1024:  # Only report if > 1MB
                    orphaned.append({
                        'name': dir_name,
                        'path': dir_path,
                        'size': size,
                        'type': 'Application Support',
                    })
        
        return sorted(orphaned, key=lambda x: x['size'], reverse=True)


def get_app_footprints(files: List[FileInfo]) -> Dict[str, Dict[str, Any]]:
    """
    Quick utility to get app footprints
    
    Args:
        files: List of files
    
    Returns:
        Dict of app_name -> footprint info
    """
    settings = Settings()
    analyzer = AppFootprintAnalyzer(settings)
    
    footprints = analyzer.analyze(files)
    
    return {
        name: fp.to_dict()
        for name, fp in footprints.items()
    }
