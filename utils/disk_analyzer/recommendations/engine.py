"""
Recommendation engine for Mac Disk Analyzer
Generates intelligent cleanup suggestions
"""

import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from core.file_info import FileInfo, Recommendation
from config.settings import Settings, CATEGORIES
from utils.formatting import format_size


class RecommendationEngine:
    """
    Generates cleanup recommendations based on analysis results
    
    Tiers:
    - 🟢 safe: Auto-deletable (caches, logs, temp files)
    - 🟡 review: Should review before deleting (old downloads, duplicates)
    - 🟠 archive: Consider moving to external storage (finished projects)
    - 🔴 caution: Manual decision required (unique files)
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize engine
        
        Args:
            settings: Application settings
        """
        self.settings = settings
    
    def generate(self, files: List[FileInfo],
                 categories: Dict[str, Any],
                 duplicates: Dict[str, Any],
                 temporal_data: Dict[str, Any],
                 app_footprints: Dict[str, Any],
                 cloud_data: Dict[str, Any],
                 dev_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate all recommendations
        
        Args:
            files: All scanned files
            categories: Category analysis results
            duplicates: Duplicate analysis results
            temporal_data: Temporal analysis results
            app_footprints: App footprint analysis
            cloud_data: Cloud storage analysis
            dev_data: Dev tools analysis
        
        Returns:
            Dictionary with recommendations
        """
        recommendations = {
            'items': [],
            'total_reclaimable': 0,
            'safe_to_delete_size': 0,
            'review_size': 0,
            'archive_size': 0,
            'by_category': {
                'safe': [],
                'review': [],
                'archive': [],
                'caution': [],
            },
        }
        
        # Generate recommendations from each source
        self._add_cache_recommendations(recommendations, categories)
        self._add_duplicate_recommendations(recommendations, duplicates)
        self._add_temporal_recommendations(recommendations, temporal_data)
        self._add_app_recommendations(recommendations, app_footprints)
        self._add_dev_recommendations(recommendations, dev_data)
        self._add_download_recommendations(recommendations, categories, files)
        self._add_trash_recommendations(recommendations, categories)
        
        # Sort recommendations by size within each category
        for cat in recommendations['by_category']:
            recommendations['by_category'][cat].sort(
                key=lambda x: x['size'],
                reverse=True
            )
        
        # Sort all items by size
        recommendations['items'].sort(key=lambda x: x['size'], reverse=True)
        
        # Calculate totals
        recommendations['total_reclaimable'] = sum(
            r['size'] for r in recommendations['items']
        )
        
        recommendations['safe_to_delete_size'] = sum(
            r['size'] for r in recommendations['by_category']['safe']
        )
        
        recommendations['review_size'] = sum(
            r['size'] for r in recommendations['by_category']['review']
        )
        
        recommendations['archive_size'] = sum(
            r['size'] for r in recommendations['by_category']['archive']
        )
        
        return recommendations
    
    def _add_recommendation(self, recommendations: Dict[str, Any], rec: Dict[str, Any]):
        """Add a recommendation to the results"""
        recommendations['items'].append(rec)
        category = rec.get('category', 'review')
        if category in recommendations['by_category']:
            recommendations['by_category'][category].append(rec)
    
    def _add_cache_recommendations(self, recommendations: Dict[str, Any],
                                   categories: Dict[str, Any]):
        """Add recommendations for cache cleanup"""
        cache_categories = ['cache_adobe', 'cache_resolve', 'cache_fcpx', 'cache_system', 'logs']
        
        for cat_id in cache_categories:
            if cat_id not in categories:
                continue
            
            cat_data = categories[cat_id]
            if cat_data['size'] < 100 * 1024 * 1024:  # Skip if < 100MB
                continue
            
            cat_info = CATEGORIES.get(cat_id, {})
            
            # Determine required app closure
            requires_closed = None
            if cat_id == 'cache_adobe':
                requires_closed = 'Adobe applications'
            elif cat_id == 'cache_resolve':
                requires_closed = 'DaVinci Resolve'
            elif cat_id == 'cache_fcpx':
                requires_closed = 'Final Cut Pro'
            
            rec = {
                'title': f"Clean {cat_info.get('name', cat_id)}",
                'description': f"Remove {cat_info.get('description', 'cache files')} to free {format_size(cat_data['size'])}",
                'category': 'safe',
                'priority': cat_info.get('priority', 'medium'),
                'size': cat_data['size'],
                'paths': [f['path'] for f in cat_data.get('files', [])[:50]],
                'action_type': 'delete',
                'safe_to_auto_clean': True,
                'requires_app_closed': requires_closed,
                'icon': cat_info.get('icon', '🗄️'),
            }
            
            self._add_recommendation(recommendations, rec)
    
    def _add_duplicate_recommendations(self, recommendations: Dict[str, Any],
                                       duplicates: Dict[str, Any]):
        """Add recommendations for duplicate removal"""
        if not duplicates:
            return
        
        total_wasted = sum(d.get('wasted_space', 0) for d in duplicates.values())
        
        if total_wasted < 100 * 1024 * 1024:  # Skip if < 100MB
            return
        
        # Group duplicates by size tier
        large_dups = []
        medium_dups = []
        
        for hash_val, dup_data in duplicates.items():
            wasted = dup_data.get('wasted_space', 0)
            if wasted >= 100 * 1024 * 1024:  # >= 100MB
                large_dups.append(dup_data)
            elif wasted >= 10 * 1024 * 1024:  # >= 10MB
                medium_dups.append(dup_data)
        
        if large_dups:
            large_wasted = sum(d['wasted_space'] for d in large_dups)
            rec = {
                'title': f"Review Large Duplicate Files",
                'description': f"{len(large_dups)} groups of large duplicate files wasting {format_size(large_wasted)}",
                'category': 'review',
                'priority': 'high',
                'size': large_wasted,
                'paths': [],
                'action_type': 'review',
                'safe_to_auto_clean': False,
                'duplicates': large_dups[:20],
                'icon': '🔄',
            }
            
            # Collect paths
            for dup in large_dups[:20]:
                rec['paths'].extend(dup.get('paths', [])[:5])
            
            self._add_recommendation(recommendations, rec)
        
        if medium_dups:
            medium_wasted = sum(d['wasted_space'] for d in medium_dups)
            rec = {
                'title': f"Review Medium Duplicate Files",
                'description': f"{len(medium_dups)} groups of duplicate files wasting {format_size(medium_wasted)}",
                'category': 'review',
                'priority': 'medium',
                'size': medium_wasted,
                'paths': [],
                'action_type': 'review',
                'safe_to_auto_clean': False,
                'icon': '🔄',
            }
            
            self._add_recommendation(recommendations, rec)
    
    def _add_temporal_recommendations(self, recommendations: Dict[str, Any],
                                      temporal_data: Dict[str, Any]):
        """Add recommendations based on file age"""
        dead_files = temporal_data.get('dead_files', [])
        total_dead = temporal_data.get('total_dead_size', 0)
        
        if total_dead < 500 * 1024 * 1024:  # Skip if < 500MB
            return
        
        # Group by category
        dead_by_cat = {}
        for f in dead_files:
            cat = f.get('category', 'other')
            if cat not in dead_by_cat:
                dead_by_cat[cat] = {'size': 0, 'count': 0, 'files': []}
            dead_by_cat[cat]['size'] += f['size']
            dead_by_cat[cat]['count'] += 1
            if len(dead_by_cat[cat]['files']) < 50:
                dead_by_cat[cat]['files'].append(f)
        
        # Create recommendation for significant categories
        for cat, data in dead_by_cat.items():
            if data['size'] < 100 * 1024 * 1024:
                continue
            
            cat_info = CATEGORIES.get(cat, {'name': cat})
            
            rec = {
                'title': f"Archive Unused {cat_info.get('name', cat)}",
                'description': f"{data['count']} files not accessed in {self.settings.dead_file_days}+ days ({format_size(data['size'])})",
                'category': 'archive',
                'priority': 'medium',
                'size': data['size'],
                'paths': [f['path'] for f in data['files']],
                'action_type': 'archive',
                'safe_to_auto_clean': False,
                'icon': '📅',
            }
            
            self._add_recommendation(recommendations, rec)
    
    def _add_app_recommendations(self, recommendations: Dict[str, Any],
                                 app_footprints: Dict[str, Any]):
        """Add recommendations for app cleanup"""
        for app_name, footprint in app_footprints.items():
            if not isinstance(footprint, dict):
                footprint = footprint.to_dict() if hasattr(footprint, 'to_dict') else {}
            
            cleanable = footprint.get('cleanable_size', 0)
            if cleanable < 100 * 1024 * 1024:  # Skip if < 100MB
                continue
            
            rec = {
                'title': f"Clean {app_name} Cache",
                'description': f"Remove cache and log files for {app_name} ({format_size(cleanable)})",
                'category': 'safe',
                'priority': 'high',
                'size': cleanable,
                'paths': footprint.get('cache_paths', []),
                'action_type': 'delete',
                'safe_to_auto_clean': True,
                'requires_app_closed': app_name,
                'icon': '📱',
            }
            
            self._add_recommendation(recommendations, rec)
    
    def _add_dev_recommendations(self, recommendations: Dict[str, Any],
                                 dev_data: Dict[str, Any]):
        """Add recommendations for dev tools cleanup"""
        # Node modules
        node = dev_data.get('node_modules', {})
        if node.get('total_size', 0) >= 1024 * 1024 * 1024:  # >= 1GB
            rec = {
                'title': "Clean Node Modules",
                'description': f"{node.get('project_count', 0)} projects with node_modules ({format_size(node['total_size'])}). Can be reinstalled with npm install.",
                'category': 'review',
                'priority': 'medium',
                'size': node['total_size'],
                'paths': [p['path'] for p in node.get('projects', [])[:20]],
                'action_type': 'delete',
                'safe_to_auto_clean': False,
                'icon': '📦',
            }
            self._add_recommendation(recommendations, rec)
        
        # Xcode
        xcode = dev_data.get('xcode', {})
        if xcode.get('cleanable_size', 0) >= 500 * 1024 * 1024:  # >= 500MB
            rec = {
                'title': "Clean Xcode Derived Data",
                'description': f"Remove Xcode build cache ({format_size(xcode['cleanable_size'])}). Will rebuild on next compile.",
                'category': 'safe',
                'priority': 'high',
                'size': xcode['cleanable_size'],
                'paths': [xcode.get('breakdown', {}).get('derived_data', {}).get('path', '')],
                'action_type': 'delete',
                'safe_to_auto_clean': True,
                'requires_app_closed': 'Xcode',
                'icon': '🔨',
            }
            self._add_recommendation(recommendations, rec)
        
        # Homebrew cache
        brew = dev_data.get('homebrew', {})
        if brew.get('cache_size', 0) >= 500 * 1024 * 1024:  # >= 500MB
            rec = {
                'title': "Clean Homebrew Cache",
                'description': f"Remove old package downloads ({format_size(brew['cache_size'])}). Run 'brew cleanup'.",
                'category': 'safe',
                'priority': 'medium',
                'size': brew['cache_size'],
                'paths': [],
                'action_type': 'command',
                'command': 'brew cleanup',
                'safe_to_auto_clean': True,
                'icon': '🍺',
            }
            self._add_recommendation(recommendations, rec)
        
        # pip cache
        python = dev_data.get('python_envs', {})
        if python.get('pip_cache_size', 0) >= 200 * 1024 * 1024:  # >= 200MB
            rec = {
                'title': "Clean pip Cache",
                'description': f"Remove pip package cache ({format_size(python['pip_cache_size'])}). Run 'pip cache purge'.",
                'category': 'safe',
                'priority': 'low',
                'size': python['pip_cache_size'],
                'paths': [],
                'action_type': 'command',
                'command': 'pip cache purge',
                'safe_to_auto_clean': True,
                'icon': '🐍',
            }
            self._add_recommendation(recommendations, rec)
    
    def _add_download_recommendations(self, recommendations: Dict[str, Any],
                                      categories: Dict[str, Any],
                                      files: List[FileInfo]):
        """Add recommendations for Downloads folder"""
        downloads = categories.get('downloads', {})
        installers = categories.get('installers', {})
        
        # Old installers
        if installers.get('size', 0) >= 500 * 1024 * 1024:  # >= 500MB
            rec = {
                'title': "Remove Old Installers",
                'description': f"DMG and PKG files that may no longer be needed ({format_size(installers['size'])})",
                'category': 'review',
                'priority': 'medium',
                'size': installers['size'],
                'paths': [f['path'] for f in installers.get('files', [])[:30]],
                'action_type': 'review',
                'safe_to_auto_clean': False,
                'icon': '💿',
            }
            self._add_recommendation(recommendations, rec)
        
        # Old downloads
        if downloads.get('size', 0) >= 1024 * 1024 * 1024:  # >= 1GB
            rec = {
                'title': "Review Downloads Folder",
                'description': f"Downloads folder contains {format_size(downloads['size'])} of files",
                'category': 'review',
                'priority': 'low',
                'size': downloads['size'],
                'paths': [f['path'] for f in downloads.get('files', [])[:50]],
                'action_type': 'review',
                'safe_to_auto_clean': False,
                'icon': '📥',
            }
            self._add_recommendation(recommendations, rec)
    
    def _add_trash_recommendations(self, recommendations: Dict[str, Any],
                                   categories: Dict[str, Any]):
        """Add recommendation for Trash"""
        trash = categories.get('trash', {})
        
        if trash.get('size', 0) >= 100 * 1024 * 1024:  # >= 100MB
            rec = {
                'title': "Empty Trash",
                'description': f"Trash contains {format_size(trash['size'])} ready to be permanently deleted",
                'category': 'safe',
                'priority': 'high',
                'size': trash['size'],
                'paths': [],
                'action_type': 'command',
                'command': 'rm -rf ~/.Trash/*',
                'safe_to_auto_clean': True,
                'icon': '🗑️',
            }
            self._add_recommendation(recommendations, rec)


def generate_recommendations(files: List[FileInfo], **analysis_results) -> Dict[str, Any]:
    """
    Quick utility to generate recommendations
    
    Args:
        files: List of files
        **analysis_results: Results from various analyzers
    
    Returns:
        Recommendations dict
    """
    settings = Settings()
    engine = RecommendationEngine(settings)
    
    return engine.generate(
        files=files,
        categories=analysis_results.get('categories', {}),
        duplicates=analysis_results.get('duplicates', {}),
        temporal_data=analysis_results.get('temporal_data', {}),
        app_footprints=analysis_results.get('app_footprints', {}),
        cloud_data=analysis_results.get('cloud_data', {}),
        dev_data=analysis_results.get('dev_data', {}),
    )
