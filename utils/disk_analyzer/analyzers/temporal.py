"""
Temporal analyzer for Mac Disk Analyzer
Analyzes files based on age and access patterns
"""

import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from collections import defaultdict

from core.file_info import FileInfo
from config.settings import Settings
from utils.formatting import format_size, format_date


class TemporalAnalyzer:
    """
    Analyzes files based on temporal characteristics:
    - Age distribution
    - Last access time
    - Identifies "dead" files not accessed in a long time
    - Groups files by creation period
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize analyzer
        
        Args:
            settings: Application settings
        """
        self.settings = settings
        self.dead_file_days = settings.dead_file_days  # Default 180 days
    
    def analyze(self, files: List[FileInfo]) -> Dict[str, Any]:
        """
        Perform temporal analysis on files
        
        Args:
            files: List of FileInfo objects
        
        Returns:
            Dictionary with temporal analysis results
        """
        now = datetime.now()
        
        results = {
            'dead_files': [],
            'age_distribution': {},
            'access_distribution': {},
            'creation_timeline': {},
            'recently_modified': [],
            'oldest_files': [],
            'growth_by_period': {},
            'total_dead_size': 0,
        }
        
        # Time period buckets
        periods = {
            'today': timedelta(days=1),
            'this_week': timedelta(days=7),
            'this_month': timedelta(days=30),
            'last_3_months': timedelta(days=90),
            'last_6_months': timedelta(days=180),
            'last_year': timedelta(days=365),
            'older': timedelta(days=99999),
        }
        
        # Initialize distributions
        for period in periods:
            results['age_distribution'][period] = {'count': 0, 'size': 0, 'files': []}
            results['access_distribution'][period] = {'count': 0, 'size': 0, 'files': []}
        
        # Initialize creation timeline (by year-month)
        creation_timeline = defaultdict(lambda: {'count': 0, 'size': 0})
        
        # Dead files threshold
        dead_threshold = now - timedelta(days=self.dead_file_days)
        
        for f in files:
            try:
                modified_dt = datetime.fromtimestamp(f.modified_time)
                accessed_dt = datetime.fromtimestamp(f.accessed_time)
                created_dt = datetime.fromtimestamp(f.created_time)
            except (OSError, ValueError):
                continue
            
            # Age distribution (by modification time)
            age = now - modified_dt
            for period, threshold in periods.items():
                if age <= threshold:
                    results['age_distribution'][period]['count'] += 1
                    results['age_distribution'][period]['size'] += f.size
                    if len(results['age_distribution'][period]['files']) < 100:
                        results['age_distribution'][period]['files'].append({
                            'path': f.path,
                            'size': f.size,
                            'modified': f.modified_time
                        })
                    break
            
            # Access distribution
            access_age = now - accessed_dt
            for period, threshold in periods.items():
                if access_age <= threshold:
                    results['access_distribution'][period]['count'] += 1
                    results['access_distribution'][period]['size'] += f.size
                    break
            
            # Dead files (not accessed in dead_file_days)
            if accessed_dt < dead_threshold:
                results['dead_files'].append({
                    'path': f.path,
                    'size': f.size,
                    'last_accessed': f.accessed_time,
                    'last_modified': f.modified_time,
                    'days_since_access': (now - accessed_dt).days,
                    'category': f.category,
                })
                results['total_dead_size'] += f.size
            
            # Creation timeline
            year_month = created_dt.strftime('%Y-%m')
            creation_timeline[year_month]['count'] += 1
            creation_timeline[year_month]['size'] += f.size
        
        # Sort dead files by size
        results['dead_files'].sort(key=lambda x: x['size'], reverse=True)
        
        # Keep only top dead files
        results['dead_files'] = results['dead_files'][:500]
        
        # Convert creation timeline
        results['creation_timeline'] = dict(sorted(creation_timeline.items()))
        
        # Get recently modified files
        results['recently_modified'] = self._get_recently_modified(files, days=7)
        
        # Get oldest files
        results['oldest_files'] = self._get_oldest_files(files, count=100)
        
        # Calculate growth by period
        results['growth_by_period'] = self._calculate_growth(files)
        
        return results
    
    def _get_recently_modified(self, files: List[FileInfo], days: int = 7) -> List[Dict[str, Any]]:
        """Get files modified in the last N days"""
        threshold = datetime.now() - timedelta(days=days)
        threshold_ts = threshold.timestamp()
        
        recent = [
            {
                'path': f.path,
                'size': f.size,
                'modified': f.modified_time,
                'category': f.category,
            }
            for f in files
            if f.modified_time > threshold_ts
        ]
        
        # Sort by modification time (newest first) and limit
        recent.sort(key=lambda x: x['modified'], reverse=True)
        return recent[:200]
    
    def _get_oldest_files(self, files: List[FileInfo], count: int = 100) -> List[Dict[str, Any]]:
        """Get the oldest files by creation time"""
        # Filter out files with suspicious creation times
        valid_files = [
            f for f in files
            if f.created_time > 0 and f.created_time < datetime.now().timestamp()
        ]
        
        # Sort by creation time
        sorted_files = sorted(valid_files, key=lambda f: f.created_time)
        
        return [
            {
                'path': f.path,
                'size': f.size,
                'created': f.created_time,
                'modified': f.modified_time,
                'age_days': f.age_days,
            }
            for f in sorted_files[:count]
        ]
    
    def _calculate_growth(self, files: List[FileInfo]) -> Dict[str, Dict[str, int]]:
        """
        Calculate disk growth by time period based on file creation dates
        
        Args:
            files: List of files
        
        Returns:
            Growth data by period
        """
        now = datetime.now()
        
        periods = {
            'last_24h': timedelta(hours=24),
            'last_7d': timedelta(days=7),
            'last_30d': timedelta(days=30),
            'last_90d': timedelta(days=90),
            'last_365d': timedelta(days=365),
        }
        
        growth = {}
        
        for period_name, delta in periods.items():
            threshold = (now - delta).timestamp()
            
            period_files = [f for f in files if f.created_time >= threshold]
            
            growth[period_name] = {
                'count': len(period_files),
                'size': sum(f.size for f in period_files),
            }
        
        return growth
    
    def find_abandoned_projects(self, files: List[FileInfo], 
                                days_threshold: int = 90) -> List[Dict[str, Any]]:
        """
        Find project directories that haven't been touched in a while
        
        Args:
            files: List of files
            days_threshold: Days without activity to consider abandoned
        
        Returns:
            List of abandoned project info
        """
        # Project file extensions
        project_exts = {
            '.prproj', '.aep', '.drp', '.fcpbundle', '.xcodeproj',
            '.xcworkspace', '.pbxproj'
        }
        
        # Find project files
        project_files = [f for f in files if f.extension.lower() in project_exts]
        
        threshold = datetime.now() - timedelta(days=days_threshold)
        threshold_ts = threshold.timestamp()
        
        abandoned = []
        
        for proj_file in project_files:
            if proj_file.accessed_time < threshold_ts:
                # Get the project directory
                proj_dir = os.path.dirname(proj_file.path)
                
                # Calculate total size of project directory
                proj_size = sum(
                    f.size for f in files
                    if f.path.startswith(proj_dir)
                )
                
                # Get last activity in the project
                proj_files = [f for f in files if f.path.startswith(proj_dir)]
                if proj_files:
                    last_activity = max(f.modified_time for f in proj_files)
                else:
                    last_activity = proj_file.modified_time
                
                abandoned.append({
                    'project_file': proj_file.path,
                    'directory': proj_dir,
                    'size': proj_size,
                    'file_count': len(proj_files),
                    'last_activity': last_activity,
                    'days_inactive': (datetime.now() - datetime.fromtimestamp(last_activity)).days,
                    'project_type': proj_file.extension,
                })
        
        return sorted(abandoned, key=lambda x: x['size'], reverse=True)


def get_dead_files(files: List[FileInfo], days: int = 180) -> List[Dict[str, Any]]:
    """
    Quick utility to find dead files
    
    Args:
        files: List of files
        days: Days threshold
    
    Returns:
        List of dead file info
    """
    settings = Settings()
    settings.dead_file_days = days
    
    analyzer = TemporalAnalyzer(settings)
    results = analyzer.analyze(files)
    
    return results['dead_files']
