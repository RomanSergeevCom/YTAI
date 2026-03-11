"""
Database module for storing scan history and enabling comparisons
Uses SQLite for lightweight persistence
"""

import os
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from .file_info import FileInfo


class ScanDatabase:
    """
    SQLite database for persisting scan results and history
    """
    
    def __init__(self, db_path: str = None):
        """
        Initialize database connection
        
        Args:
            db_path: Path to SQLite database file
        """
        if db_path is None:
            db_path = os.path.expanduser('~/.disk_analyzer/scans.db')
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        self.db_path = db_path
        self.conn = None
        self._connect()
        self._init_schema()
    
    def _connect(self):
        """Establish database connection"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
    
    def _init_schema(self):
        """Initialize database schema"""
        cursor = self.conn.cursor()
        
        # Scans table - stores scan metadata
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                paths TEXT NOT NULL,
                total_files INTEGER,
                total_size INTEGER,
                total_dirs INTEGER,
                duration_seconds REAL,
                settings_json TEXT
            )
        ''')
        
        # Categories summary per scan
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scan_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                file_count INTEGER,
                total_size INTEGER,
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            )
        ''')
        
        # Large files per scan (top 1000)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS large_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                size INTEGER NOT NULL,
                category TEXT,
                extension TEXT,
                modified_time REAL,
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            )
        ''')
        
        # Duplicate groups per scan
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS duplicate_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL,
                hash_value TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                file_count INTEGER NOT NULL,
                wasted_space INTEGER NOT NULL,
                paths_json TEXT NOT NULL,
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            )
        ''')
        
        # Recommendations per scan
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT,
                priority TEXT,
                size INTEGER,
                paths_json TEXT,
                action_type TEXT,
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            )
        ''')
        
        # Create indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_scans_timestamp ON scans(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_large_files_scan ON large_files(scan_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_large_files_size ON large_files(size)')
        
        self.conn.commit()
    
    def store_scan(self, paths: List[str], files: List[FileInfo],
                   categories: Dict[str, Any], duplicates: Dict[str, Any],
                   recommendations: Dict[str, Any],
                   duration: float = 0) -> int:
        """
        Store a scan result
        
        Args:
            paths: Scanned paths
            files: All files found
            categories: Category breakdown
            duplicates: Duplicate groups
            recommendations: Generated recommendations
            duration: Scan duration in seconds
        
        Returns:
            Scan ID
        """
        cursor = self.conn.cursor()
        
        # Calculate totals
        total_files = len(files)
        total_size = sum(f.size for f in files)
        
        # Insert scan record
        cursor.execute('''
            INSERT INTO scans (timestamp, paths, total_files, total_size, duration_seconds)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            json.dumps(paths),
            total_files,
            total_size,
            duration
        ))
        
        scan_id = cursor.lastrowid
        
        # Store category breakdown
        for cat_name, cat_data in categories.items():
            if isinstance(cat_data, dict):
                cursor.execute('''
                    INSERT INTO scan_categories (scan_id, category, file_count, total_size)
                    VALUES (?, ?, ?, ?)
                ''', (
                    scan_id,
                    cat_name,
                    cat_data.get('count', 0),
                    cat_data.get('size', 0)
                ))
        
        # Store large files (top 1000)
        sorted_files = sorted(files, key=lambda f: f.size, reverse=True)[:1000]
        for f in sorted_files:
            cursor.execute('''
                INSERT INTO large_files (scan_id, path, size, category, extension, modified_time)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                scan_id,
                f.path,
                f.size,
                f.category,
                f.extension,
                f.modified_time
            ))
        
        # Store duplicate groups
        for hash_val, dup_data in duplicates.items():
            if isinstance(dup_data, dict):
                cursor.execute('''
                    INSERT INTO duplicate_groups (scan_id, hash_value, file_size, file_count, wasted_space, paths_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    scan_id,
                    hash_val,
                    dup_data.get('size', 0),
                    dup_data.get('count', 0),
                    dup_data.get('wasted_space', 0),
                    json.dumps(dup_data.get('paths', []))
                ))
        
        # Store recommendations
        if isinstance(recommendations, dict):
            for rec in recommendations.get('items', []):
                cursor.execute('''
                    INSERT INTO recommendations (scan_id, title, description, category, priority, size, paths_json, action_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    scan_id,
                    rec.get('title', ''),
                    rec.get('description', ''),
                    rec.get('category', ''),
                    rec.get('priority', ''),
                    rec.get('size', 0),
                    json.dumps(rec.get('paths', [])),
                    rec.get('action_type', 'delete')
                ))
        
        self.conn.commit()
        return scan_id
    
    def get_scan(self, scan_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a scan by ID
        
        Args:
            scan_id: Scan ID
        
        Returns:
            Scan data dictionary or None
        """
        cursor = self.conn.cursor()
        
        cursor.execute('SELECT * FROM scans WHERE id = ?', (scan_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return dict(row)
    
    def get_scan_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get recent scan history
        
        Args:
            limit: Maximum number of scans to return
        
        Returns:
            List of scan metadata dicts
        """
        cursor = self.conn.cursor()
        
        cursor.execute('''
            SELECT id, timestamp, total_files, total_size, duration_seconds
            FROM scans
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_last_scan_id(self) -> Optional[int]:
        """Get the ID of the most recent scan"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT id FROM scans ORDER BY timestamp DESC LIMIT 1')
        row = cursor.fetchone()
        return row['id'] if row else None
    
    def get_previous_scan_id(self, current_scan_id: int) -> Optional[int]:
        """Get the ID of the scan before the given one"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT id FROM scans 
            WHERE id < ? 
            ORDER BY timestamp DESC 
            LIMIT 1
        ''', (current_scan_id,))
        row = cursor.fetchone()
        return row['id'] if row else None
    
    def compare_with_previous(self, scan_id: int) -> Optional[Dict[str, Any]]:
        """
        Compare a scan with the previous one
        
        Args:
            scan_id: Current scan ID
        
        Returns:
            Comparison data or None
        """
        prev_id = self.get_previous_scan_id(scan_id)
        if not prev_id:
            return None
        
        current = self.get_scan(scan_id)
        previous = self.get_scan(prev_id)
        
        if not current or not previous:
            return None
        
        # Calculate differences
        size_diff = current['total_size'] - previous['total_size']
        files_diff = current['total_files'] - previous['total_files']
        
        # Get category changes
        cursor = self.conn.cursor()
        
        cursor.execute('''
            SELECT category, total_size, file_count 
            FROM scan_categories 
            WHERE scan_id = ?
        ''', (scan_id,))
        current_cats = {row['category']: dict(row) for row in cursor.fetchall()}
        
        cursor.execute('''
            SELECT category, total_size, file_count 
            FROM scan_categories 
            WHERE scan_id = ?
        ''', (prev_id,))
        prev_cats = {row['category']: dict(row) for row in cursor.fetchall()}
        
        category_changes = {}
        all_cats = set(current_cats.keys()) | set(prev_cats.keys())
        
        for cat in all_cats:
            curr_size = current_cats.get(cat, {}).get('total_size', 0)
            prev_size = prev_cats.get(cat, {}).get('total_size', 0)
            if curr_size != prev_size:
                category_changes[cat] = {
                    'current': curr_size,
                    'previous': prev_size,
                    'diff': curr_size - prev_size
                }
        
        return {
            'current_scan_id': scan_id,
            'previous_scan_id': prev_id,
            'current_timestamp': current['timestamp'],
            'previous_timestamp': previous['timestamp'],
            'size_diff': size_diff,
            'files_diff': files_diff,
            'category_changes': category_changes,
            'current_total_size': current['total_size'],
            'previous_total_size': previous['total_size'],
        }
    
    def get_large_files(self, scan_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Get large files from a scan"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM large_files 
            WHERE scan_id = ? 
            ORDER BY size DESC 
            LIMIT ?
        ''', (scan_id, limit))
        return [dict(row) for row in cursor.fetchall()]
    
    def get_duplicates(self, scan_id: int) -> List[Dict[str, Any]]:
        """Get duplicate groups from a scan"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM duplicate_groups 
            WHERE scan_id = ? 
            ORDER BY wasted_space DESC
        ''', (scan_id,))
        
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            d['paths'] = json.loads(d['paths_json'])
            del d['paths_json']
            results.append(d)
        
        return results
    
    def get_recommendations(self, scan_id: int) -> List[Dict[str, Any]]:
        """Get recommendations from a scan"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM recommendations 
            WHERE scan_id = ? 
            ORDER BY size DESC
        ''', (scan_id,))
        
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            d['paths'] = json.loads(d['paths_json'])
            del d['paths_json']
            results.append(d)
        
        return results
    
    def cleanup_old_scans(self, keep_count: int = 10):
        """
        Remove old scans, keeping only the most recent ones
        
        Args:
            keep_count: Number of recent scans to keep
        """
        cursor = self.conn.cursor()
        
        # Get IDs to delete
        cursor.execute('''
            SELECT id FROM scans 
            ORDER BY timestamp DESC 
            LIMIT -1 OFFSET ?
        ''', (keep_count,))
        
        ids_to_delete = [row['id'] for row in cursor.fetchall()]
        
        if not ids_to_delete:
            return
        
        # Delete related data
        placeholders = ','.join('?' * len(ids_to_delete))
        
        cursor.execute(f'DELETE FROM scan_categories WHERE scan_id IN ({placeholders})', ids_to_delete)
        cursor.execute(f'DELETE FROM large_files WHERE scan_id IN ({placeholders})', ids_to_delete)
        cursor.execute(f'DELETE FROM duplicate_groups WHERE scan_id IN ({placeholders})', ids_to_delete)
        cursor.execute(f'DELETE FROM recommendations WHERE scan_id IN ({placeholders})', ids_to_delete)
        cursor.execute(f'DELETE FROM scans WHERE id IN ({placeholders})', ids_to_delete)
        
        self.conn.commit()
        
        # Vacuum to reclaim space
        cursor.execute('VACUUM')
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
