"""
Cloud sync detector for Mac Disk Analyzer
Identifies files synced with cloud services
"""

import os
import subprocess
from typing import List, Dict, Any, Optional
from pathlib import Path

from core.file_info import FileInfo
from config.settings import Settings
from utils.formatting import format_size


class CloudSyncDetector:
    """
    Detects files that are synced with cloud services:
    - iCloud Drive
    - Dropbox
    - Google Drive
    - OneDrive
    
    Identifies redundant local copies and cloud-only files
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize detector
        
        Args:
            settings: Application settings
        """
        self.settings = settings
        self.home = os.path.expanduser('~')
        
        # Cloud service paths
        self.cloud_paths = {
            'icloud': os.path.join(self.home, 'Library/Mobile Documents'),
            'dropbox': os.path.join(self.home, 'Dropbox'),
            'google_drive': os.path.join(self.home, 'Google Drive'),
            'onedrive': os.path.join(self.home, 'OneDrive'),
        }
    
    def analyze(self, files: List[FileInfo]) -> Dict[str, Any]:
        """
        Analyze cloud-synced files
        
        Args:
            files: List of FileInfo objects
        
        Returns:
            Dictionary with cloud sync analysis
        """
        results = {
            'services': {},
            'total_cloud_size': 0,
            'local_only': [],
            'cloud_only': [],
            'redundant': [],
            'icloud_status': {},
        }
        
        # Analyze each cloud service
        for service, path in self.cloud_paths.items():
            if os.path.exists(path):
                service_files = [f for f in files if f.path.startswith(path)]
                
                total_size = sum(f.size for f in service_files)
                
                results['services'][service] = {
                    'path': path,
                    'file_count': len(service_files),
                    'total_size': total_size,
                    'files': [
                        {'path': f.path, 'size': f.size}
                        for f in sorted(service_files, key=lambda x: x.size, reverse=True)[:100]
                    ]
                }
                
                results['total_cloud_size'] += total_size
        
        # Special handling for iCloud
        if os.path.exists(self.cloud_paths['icloud']):
            results['icloud_status'] = self._analyze_icloud(files)
        
        return results
    
    def _analyze_icloud(self, files: List[FileInfo]) -> Dict[str, Any]:
        """
        Detailed iCloud analysis including evicted (cloud-only) files
        
        Args:
            files: List of files
        
        Returns:
            iCloud status breakdown
        """
        icloud_path = self.cloud_paths['icloud']
        icloud_files = [f for f in files if f.path.startswith(icloud_path)]
        
        status = {
            'local': {'count': 0, 'size': 0},
            'cloud_only': {'count': 0, 'size': 0},
            'downloading': {'count': 0, 'size': 0},
            'unknown': {'count': 0, 'size': 0},
        }
        
        for f in icloud_files:
            # Check for iCloud extended attributes
            file_status = self._get_icloud_file_status(f.path)
            
            if file_status in status:
                status[file_status]['count'] += 1
                status[file_status]['size'] += f.size
            else:
                status['unknown']['count'] += 1
                status['unknown']['size'] += f.size
        
        return status
    
    def _get_icloud_file_status(self, path: str) -> str:
        """
        Get iCloud sync status for a file
        
        Args:
            path: File path
        
        Returns:
            Status string: 'local', 'cloud_only', 'downloading', or 'unknown'
        """
        try:
            # Use brctl to check iCloud status (macOS Catalina+)
            result = subprocess.run(
                ['brctl', 'download', '-e', path],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            # brctl returns 0 if file is downloaded, non-zero if cloud-only
            if result.returncode == 0:
                return 'local'
            else:
                return 'cloud_only'
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
            pass
        
        # Fallback: check for .icloud placeholder files
        if path.endswith('.icloud') or '/.icloud/' in path:
            return 'cloud_only'
        
        # Check extended attributes
        try:
            result = subprocess.run(
                ['xattr', '-l', path],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if 'com.apple.icloud' in result.stdout:
                if 'evicted' in result.stdout.lower():
                    return 'cloud_only'
                return 'local'
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        return 'unknown'
    
    def find_redundant_copies(self, files: List[FileInfo]) -> List[Dict[str, Any]]:
        """
        Find files that exist both locally and in cloud storage
        
        Args:
            files: List of files
        
        Returns:
            List of redundant file info
        """
        redundant = []
        
        # Build a map of filenames to paths
        name_to_paths = {}
        for f in files:
            filename = os.path.basename(f.path)
            if filename not in name_to_paths:
                name_to_paths[filename] = []
            name_to_paths[filename].append(f)
        
        # Find files with same name in cloud and non-cloud locations
        for filename, file_list in name_to_paths.items():
            if len(file_list) < 2:
                continue
            
            cloud_copies = []
            local_copies = []
            
            for f in file_list:
                is_cloud = any(
                    f.path.startswith(cloud_path)
                    for cloud_path in self.cloud_paths.values()
                )
                
                if is_cloud:
                    cloud_copies.append(f)
                else:
                    local_copies.append(f)
            
            # If same file exists in both cloud and local
            if cloud_copies and local_copies:
                # Check if sizes match (likely same file)
                for cloud_f in cloud_copies:
                    for local_f in local_copies:
                        if cloud_f.size == local_f.size:
                            redundant.append({
                                'filename': filename,
                                'size': cloud_f.size,
                                'cloud_path': cloud_f.path,
                                'local_path': local_f.path,
                                'potential_savings': cloud_f.size,
                            })
        
        return sorted(redundant, key=lambda x: x['size'], reverse=True)


def analyze_cloud_storage(files: List[FileInfo]) -> Dict[str, Any]:
    """
    Quick utility to analyze cloud storage
    
    Args:
        files: List of files
    
    Returns:
        Cloud analysis results
    """
    settings = Settings()
    detector = CloudSyncDetector(settings)
    return detector.analyze(files)
