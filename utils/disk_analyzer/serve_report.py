#!/usr/bin/env python3
"""
Local server for Mac Disk Analyzer HTML reports
Allows clicking file paths to open them in Finder

Usage:
    python serve_report.py report.html
    python serve_report.py report.html --port 8080
"""

import os
import sys
import json
import subprocess
import webbrowser
import urllib.parse
import logging
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from datetime import datetime
import argparse


# Setup logging with timestamp
SCRIPT_DIR = Path(__file__).parent
LOGS_DIR = SCRIPT_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

SESSION_TIMESTAMP = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
LOG_FILE = LOGS_DIR / f"{SESSION_TIMESTAMP}_disk_analyzer.log"

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('disk_analyzer')


# JavaScript to inject for local server mode
INJECTED_JS = '''
<script>
// ============================================
// LOCAL SERVER MODE - Enables Finder Integration
// ============================================
(function() {
    console.log('🖥️ Local server mode initializing...');
    
    // Function to open file in Finder
    window.openInFinder = function(path, reveal) {
        const url = reveal 
            ? '/open-folder?path=' + encodeURIComponent(path)
            : '/open-file?path=' + encodeURIComponent(path);
        
        fetch(url)
            .then(r => r.json())
            .then(d => {
                if (d.success) {
                    console.log('📂 Opened:', path);
                } else {
                    console.error('Failed:', d.error);
                    alert('Could not open: ' + path);
                }
            })
            .catch(e => {
                console.error('Error:', e);
                alert('Error opening file. Is the server running?');
            });
    };
    
    // Override showCategoryFiles to use server
    const originalShowCategoryFiles = window.showCategoryFiles;
    window.showCategoryFiles = function(cat) {
        let html = '<div class="file-list">';
        cat.files.slice(0, 50).forEach(f => {
            const escapedPath = f.path.replace(/'/g, "\\'");
            html += '<div class="file-list-item">' +
                '<span class="path">' + f.path + '</span>' +
                '<span class="file-actions">' +
                    '<button onclick="openInFinder(\\'' + escapedPath + '\\', false)" class="finder-btn" title="Open file">📄</button>' +
                    '<button onclick="openInFinder(\\'' + escapedPath + '\\', true)" class="finder-btn" title="Show in Finder">📁</button>' +
                    '<span class="file-size">' + formatSize(f.size) + '</span>' +
                '</span>' +
            '</div>';
        });
        if (cat.files.length > 50) {
            html += '<div style="padding:1rem;color:var(--text-secondary);text-align:center;">Showing 50 of ' + cat.files.length + ' files</div>';
        }
        showModal(cat.icon + ' ' + cat.name + ' (' + formatSize(cat.size) + ')', html + '</div>');
    };
    
    // Override renderFiles to use server
    const originalRenderFiles = window.renderFiles;
    window.renderFiles = function() {
        const container = document.getElementById('files-list');
        if (!container) return;
        container.innerHTML = reportData.large_files.slice(0, 100).map(f => {
            const escapedPath = f.path.replace(/'/g, "\\'");
            return '<div class="list-item">' +
                '<div class="list-item-icon">📄</div>' +
                '<div class="list-item-content">' +
                    '<div class="list-item-title">' + f.path.split('/').pop() + '</div>' +
                    '<div class="list-item-subtitle path">' + f.path + '</div>' +
                '</div>' +
                '<div class="file-actions">' +
                    '<button onclick="openInFinder(\\'' + escapedPath + '\\', false)" class="finder-btn" title="Open file">📄</button>' +
                    '<button onclick="openInFinder(\\'' + escapedPath + '\\', true)" class="finder-btn" title="Show in Finder">📁</button>' +
                    '<span class="list-item-size">' + formatSize(f.size) + '</span>' +
                '</div>' +
            '</div>';
        }).join('');
    };
    
    // Add button styles
    const style = document.createElement('style');
    style.textContent = `
        .finder-btn {
            background: rgba(255,255,255,0.1);
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 6px;
            padding: 0.3rem 0.5rem;
            cursor: pointer;
            font-size: 1rem;
            transition: all 0.2s;
        }
        .finder-btn:hover {
            background: rgba(88,166,255,0.3);
            border-color: rgba(88,166,255,0.5);
            transform: scale(1.1);
        }
        .file-actions {
            display: flex;
            gap: 0.5rem;
            align-items: center;
        }
    `;
    document.head.appendChild(style);
    
    // Re-render if already loaded
    if (typeof renderFiles === 'function') {
        setTimeout(renderFiles, 100);
    }
    
    console.log('✅ Local server mode enabled - click 📄 or 📁 buttons to open in Finder!');
})();
</script>
'''


class ReportHandler(SimpleHTTPRequestHandler):
    """Custom handler that can open files in Finder"""
    
    report_path = None
    report_dir = None
    
    def do_GET(self):
        """Handle GET requests"""
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        
        logger.debug(f"GET request: {self.path}")
        
        # Handle open-file requests
        if path == '/open-file':
            file_path = query.get('path', [''])[0]
            logger.info(f"📄 Open file request: {file_path}")
            if file_path:
                success = self.open_in_finder(file_path, reveal=False)
                self.send_json_response({'success': success, 'path': file_path})
                logger.info(f"   Result: {'✓ SUCCESS' if success else '✗ FAILED'}")
                return
            else:
                logger.error("   No path provided")
                self.send_json_response({'success': False, 'error': 'No path provided'})
                return
        
        # Handle open-folder requests (reveal in Finder)
        if path == '/open-folder':
            file_path = query.get('path', [''])[0]
            logger.info(f"📁 Reveal in Finder request: {file_path}")
            if file_path:
                success = self.open_in_finder(file_path, reveal=True)
                self.send_json_response({'success': success, 'path': file_path})
                logger.info(f"   Result: {'✓ SUCCESS' if success else '✗ FAILED'}")
                return
            else:
                logger.error("   No path provided")
                self.send_json_response({'success': False, 'error': 'No path provided'})
                return
        
        # Ignore favicon
        if 'favicon' in path:
            self.send_response(204)
            self.end_headers()
            return
        
        # Serve the report file at root
        if path == '/' or path == '/index.html':
            logger.debug("Serving report HTML")
            self.serve_report()
            return
        
        # Default handler for other files
        logger.debug(f"Default handler for: {path}")
        super().do_GET()
    
    def send_json_response(self, data):
        """Send JSON response"""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def serve_report(self):
        """Serve the HTML report with injected JavaScript"""
        try:
            with open(self.report_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Inject our JavaScript before </body>
            content = content.replace('</body>', INJECTED_JS + '</body>')
            
            content_bytes = content.encode('utf-8')
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(content_bytes))
            self.end_headers()
            self.wfile.write(content_bytes)
            
        except Exception as e:
            logger.error(f"Error serving report: {e}")
            self.send_error(500, f'Error serving report: {e}')
    
    def open_in_finder(self, path, reveal=False):
        """Open a file or folder in Finder (macOS)"""
        logger.debug(f"open_in_finder called: path={path}, reveal={reveal}")
        
        # Check if path exists
        if not os.path.exists(path):
            logger.error(f"Path does not exist: {path}")
            return False
        
        try:
            if sys.platform == 'darwin':
                if reveal:
                    # Reveal file in Finder (select it)
                    # Use AppleScript for more reliable selection
                    script = f'''
                    tell application "Finder"
                        activate
                        reveal POSIX file "{path}"
                    end tell
                    '''
                    result = subprocess.run(
                        ['osascript', '-e', script],
                        capture_output=True,
                        text=True
                    )
                    logger.debug(f"AppleScript reveal result: returncode={result.returncode}, stdout={result.stdout}, stderr={result.stderr}")
                    
                    if result.returncode != 0:
                        # Fallback to open -R
                        logger.debug(f"AppleScript failed, trying open -R")
                        result = subprocess.run(['open', '-R', path], capture_output=True, text=True)
                        logger.debug(f"open -R result: returncode={result.returncode}, stderr={result.stderr}")
                    
                    return result.returncode == 0
                else:
                    # Open file with default app
                    result = subprocess.run(['open', path], capture_output=True, text=True)
                    logger.debug(f"open result: returncode={result.returncode}, stderr={result.stderr}")
                    return result.returncode == 0
                    
            elif sys.platform == 'linux':
                folder = os.path.dirname(path) if not os.path.isdir(path) else path
                result = subprocess.run(['xdg-open', folder], capture_output=True, text=True)
                return result.returncode == 0
                
            elif sys.platform == 'win32':
                if reveal:
                    result = subprocess.run(['explorer', '/select,', path], capture_output=True, text=True)
                    return result.returncode == 0
                else:
                    os.startfile(path)
                    return True
                    
        except Exception as e:
            logger.error(f"Exception opening path: {e}", exc_info=True)
            return False
            
        return False
    
    def log_message(self, format, *args):
        """Suppress default logging (we use our own)"""
        pass


def serve_report(report_path: str, port: int = 8000, open_browser: bool = True):
    """
    Start local server and serve report
    
    Args:
        report_path: Path to HTML report
        port: Port number
        open_browser: Whether to open browser automatically
    """
    report_path = os.path.abspath(report_path)
    
    if not os.path.exists(report_path):
        logger.error(f"Report not found: {report_path}")
        print(f"❌ Report not found: {report_path}")
        sys.exit(1)
    
    # Set up handler
    ReportHandler.report_path = report_path
    ReportHandler.report_dir = os.path.dirname(report_path)
    
    # Change to report directory
    os.chdir(ReportHandler.report_dir)
    
    # Find available port
    for p in range(port, port + 100):
        try:
            server_address = ('127.0.0.1', p)
            httpd = HTTPServer(server_address, ReportHandler)
            break
        except OSError:
            continue
    else:
        logger.error(f"Could not find available port in range {port}-{port+99}")
        print(f"❌ Could not find available port")
        sys.exit(1)
    
    url = f'http://127.0.0.1:{p}/'
    
    logger.info(f"Starting server for: {report_path}")
    logger.info(f"URL: {url}")
    logger.info(f"Log file: {LOG_FILE}")
    
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║              🖥️  Mac Disk Analyzer - Local Server                ║
╚══════════════════════════════════════════════════════════════════╝

  📄 Report: {os.path.basename(report_path)}
  🌐 URL:    {url}
  📋 Log:    {LOG_FILE}
  
  ✅ Click 📄 to open file, 📁 to reveal in Finder!
  
  Press Ctrl+C to stop the server.
""")
    
    if open_browser:
        webbrowser.open(url)
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped.")
        logger.info("Server stopped by user")
        httpd.shutdown()


def main():
    parser = argparse.ArgumentParser(
        description='Serve Mac Disk Analyzer report with clickable Finder links'
    )
    parser.add_argument('report', help='Path to HTML report file')
    parser.add_argument('--port', '-p', type=int, default=8000, help='Port number (default: 8000)')
    parser.add_argument('--no-browser', action='store_true', help="Don't open browser automatically")
    
    args = parser.parse_args()
    
    serve_report(args.report, args.port, not args.no_browser)


if __name__ == '__main__':
    main()
