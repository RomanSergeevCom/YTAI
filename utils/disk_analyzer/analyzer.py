#!/usr/bin/env python3
"""
Mac Disk Analyzer - Deep Analysis Tool for macOS
Designed for MacBook Pro M3 Max with video production workflows

Usage:
    python analyzer.py                    # Standard scan of home directory
    python analyzer.py --full             # Full system scan (may need sudo)
    python analyzer.py --quick            # Quick scan (skip hashing)
    python analyzer.py --report html      # Generate interactive HTML report
    python analyzer.py --compare-last     # Compare with previous scan
"""

import argparse
import sys
import os
import time
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.scanner import DiskScanner
from core.database import ScanDatabase
from analyzers.categorizer import FileCategorizer
from analyzers.duplicates import DuplicateFinder
from analyzers.media_analyzer import MediaAnalyzer
from analyzers.app_footprint import AppFootprintAnalyzer
from analyzers.temporal import TemporalAnalyzer
from analyzers.cloud_sync import CloudSyncDetector
from analyzers.dev_tools import DevToolsAnalyzer
from recommendations.engine import RecommendationEngine
from report.generator import ReportGenerator
from utils.formatting import format_size, format_duration
from utils.preflight import run_preflight_checks, print_preflight_report, estimate_cleanup_time
from actions.cleaner import Cleaner
from config.settings import Settings


def print_banner():
    """Print application banner"""
    banner = """
╔══════════════════════════════════════════════════════════════════╗
║                    🍎 MAC DISK ANALYZER                          ║
║           Deep Analysis Tool for macOS                           ║
║           Optimized for Video Production Workflows               ║
╚══════════════════════════════════════════════════════════════════╝
    """
    print(banner)


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Mac Disk Analyzer - Deep disk analysis for macOS',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analyzer.py                      # Scan home directory
  python analyzer.py --full               # Full system scan
  python analyzer.py --scan-path ~/Projects --scan-path ~/Movies
  python analyzer.py --report html --output ~/Desktop/report.html
  python analyzer.py --duplicates-only --min-size 100MB
  python analyzer.py --find-dead-files --days 180
        """
    )
    
    # Scan options
    parser.add_argument('--full', action='store_true',
                        help='Full system scan (includes /Applications, /Library)')
    parser.add_argument('--quick', action='store_true',
                        help='Quick scan - skip file hashing for duplicates')
    parser.add_argument('--scan-path', action='append', dest='scan_paths',
                        help='Custom paths to scan (can be used multiple times)')
    parser.add_argument('--exclude', action='append', dest='exclude_paths',
                        help='Paths to exclude from scan')
    
    # Analysis options
    parser.add_argument('--duplicates-only', action='store_true',
                        help='Only run duplicate file detection')
    parser.add_argument('--media-analysis', action='store_true',
                        help='Deep media file analysis (slower)')
    parser.add_argument('--find-dead-files', action='store_true',
                        help='Find files not accessed in a long time')
    parser.add_argument('--days', type=int, default=180,
                        help='Days threshold for dead files (default: 180)')
    
    # Output options
    parser.add_argument('--report', choices=['html', 'json', 'terminal'],
                        default='html', help='Report format (default: html)')
    parser.add_argument('--output', '-o', type=str,
                        help='Output file path for report')
    parser.add_argument('--generate-cleanup-script', action='store_true',
                        help='Generate shell script for cleanup actions')
    
    # History options
    parser.add_argument('--compare-last', action='store_true',
                        help='Compare with previous scan')
    parser.add_argument('--history', action='store_true',
                        help='Show scan history')
    
    # Filter options
    parser.add_argument('--min-size', type=str, default='1MB',
                        help='Minimum file size to include (e.g., 1MB, 500KB, 1GB)')
    parser.add_argument('--max-results', type=int, default=1000,
                        help='Maximum number of items in detailed lists')
    
    # Cleanup options
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be deleted without deleting')
    parser.add_argument('--clean', action='store_true',
                        help='Delete safe cache locations')
    parser.add_argument('--force', action='store_true',
                        help='Skip confirmation prompts')
    
    # Server mode
    parser.add_argument('--serve', action='store_true',
                        help='Start local server with clickable Finder links')
    
    # Misc options
    parser.add_argument('--skip-checks', action='store_true',
                        help='Skip pre-flight safety checks')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')
    parser.add_argument('--debug', action='store_true',
                        help='Debug mode with detailed logging')
    
    return parser.parse_args()


def parse_size(size_str: str) -> int:
    """Parse size string like '1GB', '500MB' to bytes"""
    size_str = size_str.strip().upper()
    units = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
    
    for unit, multiplier in units.items():
        if size_str.endswith(unit):
            try:
                return int(float(size_str[:-len(unit)]) * multiplier)
            except ValueError:
                pass
    
    # Try parsing as plain number (bytes)
    try:
        return int(size_str)
    except ValueError:
        return 1024 * 1024  # Default 1MB


def get_default_scan_paths(full_scan: bool) -> list:
    """Get default paths to scan based on scan type"""
    home = str(Path.home())
    
    if full_scan:
        # Scan entire drive - use root but exclude system-protected paths
        # The scanner will skip /System, /private/var/vm, etc.
        return ['/']
    
    # Default: just home directory
    return [home]


def run_analysis(args):
    """Main analysis workflow"""
    settings = Settings()
    settings.verbose = args.verbose
    settings.debug = args.debug
    settings.min_size = parse_size(args.min_size)
    settings.quick_mode = args.quick
    settings.dead_file_days = args.days
    
    # Determine scan paths
    if args.scan_paths:
        scan_paths = args.scan_paths
    else:
        scan_paths = get_default_scan_paths(args.full)
    
    # Validate paths
    valid_paths = []
    for path in scan_paths:
        if os.path.exists(path):
            valid_paths.append(path)
        else:
            print(f"⚠️  Path does not exist: {path}")
    
    if not valid_paths:
        print("❌ No valid paths to scan!")
        sys.exit(1)
    
    # Initialize database
    db = ScanDatabase()
    
    # Show scan history if requested
    if args.history:
        history = db.get_scan_history()
        if history:
            print("\n📊 Scan History:")
            print("-" * 60)
            for scan in history:
                print(f"  {scan['timestamp']} - {scan['total_files']:,} files, {format_size(scan['total_size'])}")
        else:
            print("No previous scans found.")
        return
    
    print(f"\n🔍 Scanning paths:")
    for path in valid_paths:
        print(f"   • {path}")
    print()
    
    start_time = time.time()
    
    # Phase 1: Scan filesystem
    print("📁 Phase 1/6: Scanning filesystem...")
    scanner = DiskScanner(settings, args.exclude_paths or [])
    files = scanner.scan(valid_paths)
    print(f"   Found {len(files):,} files ({format_size(sum(f.size for f in files))})")
    
    # Phase 2: Categorize files
    print("🏷️  Phase 2/6: Categorizing files...")
    categorizer = FileCategorizer(settings)
    categories = categorizer.categorize(files)
    print(f"   Categorized into {len(categories)} categories")
    
    # Phase 3: Analyze applications
    print("📱 Phase 3/6: Analyzing application footprints...")
    app_analyzer = AppFootprintAnalyzer(settings)
    app_footprints = app_analyzer.analyze(files)
    print(f"   Analyzed {len(app_footprints)} applications")
    
    # Phase 4: Find duplicates (unless quick mode or duplicates-only not set)
    duplicates = {}
    if not args.quick or args.duplicates_only:
        print("🔄 Phase 4/6: Finding duplicates...")
        dup_finder = DuplicateFinder(settings)
        duplicates = dup_finder.find_duplicates(files)
        wasted = sum(d['wasted_space'] for d in duplicates.values())
        print(f"   Found {len(duplicates)} duplicate groups ({format_size(wasted)} wasted)")
    else:
        print("⏭️  Phase 4/6: Skipping duplicate detection (quick mode)")
    
    # Phase 5: Temporal analysis
    print("📅 Phase 5/6: Temporal analysis...")
    temporal = TemporalAnalyzer(settings)
    temporal_data = temporal.analyze(files)
    dead_files = temporal_data.get('dead_files', [])
    print(f"   Found {len(dead_files)} potentially unused files")
    
    # Phase 6: Additional analyzers
    print("🔬 Phase 6/6: Running specialized analyzers...")
    
    # Media analysis (if requested or has media files)
    media_data = {}
    if args.media_analysis:
        media_analyzer = MediaAnalyzer(settings)
        media_data = media_analyzer.analyze(files)
        print(f"   Analyzed {len(media_data.get('videos', []))} video files")
    
    # Cloud sync detection
    cloud_detector = CloudSyncDetector(settings)
    cloud_data = cloud_detector.analyze(files)
    
    # Dev tools analysis
    dev_analyzer = DevToolsAnalyzer(settings)
    dev_data = dev_analyzer.analyze(files)
    
    elapsed = time.time() - start_time
    print(f"\n✅ Analysis complete in {format_duration(elapsed)}")
    
    # Generate recommendations
    print("\n💡 Generating recommendations...")
    recommender = RecommendationEngine(settings)
    recommendations = recommender.generate(
        files=files,
        categories=categories,
        duplicates=duplicates,
        temporal_data=temporal_data,
        app_footprints=app_footprints,
        cloud_data=cloud_data,
        dev_data=dev_data
    )
    
    # Store scan in database
    scan_id = db.store_scan(
        paths=valid_paths,
        files=files,
        categories=categories,
        duplicates=duplicates,
        recommendations=recommendations
    )
    
    # Compare with previous scan if requested
    comparison = None
    if args.compare_last:
        comparison = db.compare_with_previous(scan_id)
    
    # Generate report
    print("\n📄 Generating report...")
    
    output_path = args.output
    if not output_path:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if args.report == 'html':
            output_path = os.path.expanduser(f'~/Desktop/disk_report_{timestamp}.html')
        elif args.report == 'json':
            output_path = os.path.expanduser(f'~/Desktop/disk_report_{timestamp}.json')
    
    report_data = {
        'scan_id': scan_id,
        'scan_paths': valid_paths,
        'total_files': len(files),
        'total_size': sum(f.size for f in files),
        'categories': categories,
        'duplicates': duplicates,
        'temporal_data': temporal_data,
        'app_footprints': app_footprints,
        'cloud_data': cloud_data,
        'dev_data': dev_data,
        'media_data': media_data,
        'recommendations': recommendations,
        'comparison': comparison,
        'scan_duration': elapsed,
        'timestamp': datetime.now().isoformat(),
    }
    
    generator = ReportGenerator(settings)
    
    if args.report == 'html':
        generator.generate_html(report_data, output_path)
        print(f"\n🎉 HTML report saved to: {output_path}")
        print(f"   Open in browser: file://{output_path}")
    elif args.report == 'json':
        generator.generate_json(report_data, output_path)
        print(f"\n🎉 JSON report saved to: {output_path}")
    else:
        generator.print_terminal(report_data)
    
    # Generate cleanup script if requested
    if args.generate_cleanup_script:
        script_path = output_path.replace('.html', '_cleanup.sh').replace('.json', '_cleanup.sh')
        if script_path == output_path:
            script_path = os.path.expanduser('~/Desktop/disk_cleanup.sh')
        generator.generate_cleanup_script(recommendations, script_path)
        print(f"🧹 Cleanup script saved to: {script_path}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    print(f"   Total scanned:     {len(files):,} files")
    print(f"   Total size:        {format_size(sum(f.size for f in files))}")
    print(f"   Reclaimable:       {format_size(recommendations['total_reclaimable'])}")
    print(f"   Safe to delete:    {format_size(recommendations['safe_to_delete_size'])}")
    print("=" * 60)


def main():
    """Main entry point"""
    print_banner()
    
    args = parse_arguments()
    
    # Run pre-flight checks unless skipped
    if not args.skip_checks:
        checks = run_preflight_checks()
        if not print_preflight_report(checks):
            if not args.force:
                print("\nUse --skip-checks to override or --force to continue anyway")
                sys.exit(1)
    
    try:
        run_analysis(args)
        
        # Start local server if requested
        if args.serve:
            output_path = args.output
            if not output_path:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_path = os.path.expanduser(f'~/Desktop/disk_report_{timestamp}.html')
            
            if os.path.exists(output_path):
                print(f"\n💡 Tip: Run 'python3 serve_report.py {output_path}' for clickable links")
                # Import and run server
                try:
                    from serve_report import serve_report
                    serve_report(output_path)
                except ImportError:
                    print("   serve_report.py not found in current directory")
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Scan interrupted by user")
        sys.exit(1)
    except PermissionError as e:
        print(f"\n❌ Permission denied: {e}")
        print("   Try running with sudo for full system access")
        sys.exit(1)
    except Exception as e:
        if args.debug:
            import traceback
            traceback.print_exc()
        else:
            print(f"\n❌ Error: {e}")
            print("   Run with --debug for more details")
        sys.exit(1)


if __name__ == '__main__':
    main()
