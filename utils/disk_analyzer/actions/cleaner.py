"""
Cleanup executor for Mac Disk Analyzer
Safely deletes files with dry-run support
"""

import os
import shutil
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass, field

from config.settings import Settings, CATEGORIES
from utils.formatting import format_size
from utils.preflight import quit_application, estimate_cleanup_time


@dataclass
class CleanupItem:
    """Represents an item to be cleaned"""
    path: str
    size: int
    category: str
    risk: str  # 'safe', 'low', 'medium', 'high'
    requires_app_closed: Optional[str] = None
    description: str = ""


@dataclass 
class CleanupResult:
    """Result of cleanup operation"""
    success: bool
    items_deleted: int = 0
    items_failed: int = 0
    bytes_freed: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    deleted_items: List[Dict[str, Any]] = field(default_factory=list)
    skipped_items: List[Dict[str, Any]] = field(default_factory=list)
    disk_free_before: int = 0
    disk_free_after: int = 0
    
    @property
    def bytes_freed_formatted(self) -> str:
        return format_size(self.bytes_freed)
    
    @property
    def actual_freed(self) -> str:
        actual = self.disk_free_after - self.disk_free_before
        return format_size(max(0, actual))


class Cleaner:
    """
    Executes cleanup operations safely
    
    Features:
    - Dry-run mode (preview without deleting)
    - Risk-based filtering
    - App quit helper
    - Before/after disk space tracking
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
    
    def get_disk_free(self) -> int:
        """Get current free disk space"""
        try:
            result = subprocess.run(['df', '-k', '/'], capture_output=True, text=True)
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                return int(parts[3]) * 1024
        except Exception:
            pass
        return 0
    
    def clean(self, items: List[CleanupItem], 
              dry_run: bool = True,
              max_risk: str = 'low',
              quit_apps: bool = False,
              force: bool = False) -> CleanupResult:
        """
        Execute cleanup
        
        Args:
            items: List of CleanupItem to process
            dry_run: If True, only preview what would be deleted
            max_risk: Maximum risk level to delete ('safe', 'low', 'medium')
            quit_apps: If True, attempt to quit required apps
            force: Skip confirmation for each item
        
        Returns:
            CleanupResult with details
        """
        result = CleanupResult(success=True)
        result.disk_free_before = self.get_disk_free()
        
        # Risk level ordering
        risk_order = {'safe': 0, 'low': 1, 'medium': 2, 'high': 3}
        max_risk_level = risk_order.get(max_risk, 1)
        
        # Filter items by risk
        eligible = []
        for item in items:
            item_risk = risk_order.get(item.risk, 3)
            if item_risk <= max_risk_level:
                eligible.append(item)
            else:
                result.skipped_items.append({
                    'path': item.path,
                    'size': item.size,
                    'reason': f'Risk too high ({item.risk})'
                })
        
        # Check for apps that need to be closed
        apps_to_quit = set()
        for item in eligible:
            if item.requires_app_closed:
                apps_to_quit.add(item.requires_app_closed)
        
        # Quit apps if requested
        if quit_apps and apps_to_quit and not dry_run:
            for app in apps_to_quit:
                print(f"  Quitting {app}...")
                if not quit_application(app):
                    print(f"  ⚠️  Could not quit {app}")
        
        # Process each item
        for item in eligible:
            if dry_run:
                # Dry run - just record what would happen
                result.deleted_items.append({
                    'path': item.path,
                    'size': item.size,
                    'category': item.category,
                    'would_delete': True
                })
                result.bytes_freed += item.size
                result.items_deleted += 1
            else:
                # Actual deletion
                try:
                    if os.path.exists(item.path):
                        if os.path.isdir(item.path):
                            shutil.rmtree(item.path)
                        else:
                            os.remove(item.path)
                        
                        result.deleted_items.append({
                            'path': item.path,
                            'size': item.size,
                            'category': item.category,
                            'deleted': True
                        })
                        result.bytes_freed += item.size
                        result.items_deleted += 1
                    else:
                        result.skipped_items.append({
                            'path': item.path,
                            'reason': 'Path does not exist'
                        })
                except PermissionError as e:
                    result.errors.append({
                        'path': item.path,
                        'error': f'Permission denied: {e}'
                    })
                    result.items_failed += 1
                except Exception as e:
                    result.errors.append({
                        'path': item.path,
                        'error': str(e)
                    })
                    result.items_failed += 1
        
        if not dry_run:
            result.disk_free_after = self.get_disk_free()
        else:
            result.disk_free_after = result.disk_free_before + result.bytes_freed
        
        result.success = result.items_failed == 0
        
        return result
    
    def generate_cleanup_items(self, recommendations: Dict[str, Any]) -> List[CleanupItem]:
        """
        Generate CleanupItems from recommendations
        
        Args:
            recommendations: Recommendations dict from RecommendationEngine
        
        Returns:
            List of CleanupItem
        """
        items = []
        
        for rec in recommendations.get('items', []):
            risk = rec.get('category', 'medium')
            if risk == 'safe':
                risk_level = 'safe' if rec.get('safe_to_auto_clean') else 'low'
            elif risk == 'review':
                risk_level = 'low'
            elif risk == 'archive':
                risk_level = 'medium'
            else:
                risk_level = 'high'
            
            for path in rec.get('paths', []):
                # Get actual size if possible
                try:
                    if os.path.isfile(path):
                        size = os.path.getsize(path)
                    elif os.path.isdir(path):
                        size = self._get_dir_size(path)
                    else:
                        size = 0
                except OSError:
                    size = 0
                
                items.append(CleanupItem(
                    path=path,
                    size=size,
                    category=rec.get('title', 'Unknown'),
                    risk=risk_level,
                    requires_app_closed=rec.get('requires_app_closed'),
                    description=rec.get('description', '')
                ))
        
        return items
    
    def _get_dir_size(self, path: str) -> int:
        """Get directory size"""
        total = 0
        try:
            for entry in os.scandir(path):
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat().st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += self._get_dir_size(entry.path)
                except OSError:
                    pass
        except OSError:
            pass
        return total
    
    def print_cleanup_preview(self, items: List[CleanupItem], max_risk: str = 'low'):
        """Print preview of what would be cleaned"""
        risk_order = {'safe': 0, 'low': 1, 'medium': 2, 'high': 3}
        max_risk_level = risk_order.get(max_risk, 1)
        
        eligible = [i for i in items if risk_order.get(i.risk, 3) <= max_risk_level]
        skipped = [i for i in items if risk_order.get(i.risk, 3) > max_risk_level]
        
        total_size = sum(i.size for i in eligible)
        
        print("\n" + "=" * 60)
        print("CLEANUP PREVIEW (DRY RUN)")
        print("=" * 60)
        
        print(f"\n📂 Items to delete: {len(eligible)}")
        print(f"💾 Space to free: {format_size(total_size)}")
        print(f"⏱️  Estimated time: {estimate_cleanup_time(total_size)}")
        
        if eligible:
            print("\n✅ Will delete:")
            for item in eligible[:20]:
                risk_icon = {'safe': '🟢', 'low': '🟡'}.get(item.risk, '🟠')
                print(f"   {risk_icon} [{format_size(item.size):>10}] {item.path}")
            
            if len(eligible) > 20:
                print(f"   ... and {len(eligible) - 20} more items")
        
        if skipped:
            print(f"\n⏭️  Skipped ({len(skipped)} items - risk too high):")
            for item in skipped[:5]:
                print(f"   🔴 {item.path} ({item.risk})")
        
        print("\n" + "=" * 60)
        
        return total_size
    
    def generate_shell_script(self, items: List[CleanupItem], 
                             max_risk: str = 'low',
                             output_path: str = None) -> str:
        """
        Generate shell script for cleanup
        
        Args:
            items: List of CleanupItem
            max_risk: Maximum risk level
            output_path: Optional path to save script
        
        Returns:
            Script content
        """
        risk_order = {'safe': 0, 'low': 1, 'medium': 2, 'high': 3}
        max_risk_level = risk_order.get(max_risk, 1)
        eligible = [i for i in items if risk_order.get(i.risk, 3) <= max_risk_level]
        
        total_size = sum(i.size for i in eligible)
        
        lines = [
            '#!/bin/bash',
            '# Mac Disk Analyzer - Cleanup Script',
            f'# Generated: {datetime.now().isoformat()}',
            f'# Items: {len(eligible)}',
            f'# Estimated space to free: {format_size(total_size)}',
            '#',
            '# ⚠️  REVIEW THIS SCRIPT BEFORE RUNNING!',
            '#',
            '',
            'set -e  # Exit on error',
            '',
            'echo "🧹 Mac Disk Analyzer Cleanup"',
            'echo "============================"',
            'echo ""',
            'echo "This script will delete files to free approximately ' + format_size(total_size) + '"',
            'echo "Press Ctrl+C to cancel, or Enter to continue..."',
            'read',
            'echo ""',
            '',
        ]
        
        # Group by app that needs to be closed
        apps_needed = set()
        for item in eligible:
            if item.requires_app_closed:
                apps_needed.add(item.requires_app_closed)
        
        if apps_needed:
            lines.append('# Quit required applications')
            for app in sorted(apps_needed):
                lines.append(f'echo "Quitting {app}..."')
                lines.append(f'osascript -e \'quit app "{app}"\' 2>/dev/null || true')
            lines.append('sleep 3')
            lines.append('')
        
        # Group items by category
        by_category = {}
        for item in eligible:
            cat = item.category
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(item)
        
        for category, cat_items in by_category.items():
            cat_size = sum(i.size for i in cat_items)
            lines.append(f'# {category} ({format_size(cat_size)})')
            lines.append(f'echo "🗑️  Cleaning {category}..."')
            
            for item in cat_items:
                escaped = item.path.replace('"', '\\"')
                lines.append(f'rm -rf "{escaped}" 2>/dev/null || true')
            
            lines.append('')
        
        lines.extend([
            'echo ""',
            'echo "✅ Cleanup complete!"',
            'echo ""',
            'echo "Disk space now:"',
            'df -h /',
        ])
        
        script = '\n'.join(lines)
        
        if output_path:
            with open(output_path, 'w') as f:
                f.write(script)
            os.chmod(output_path, 0o755)
        
        return script
