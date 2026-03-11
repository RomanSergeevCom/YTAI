"""
Report generator for Mac Disk Analyzer
Generates HTML, JSON, and terminal reports
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path

from config.settings import Settings, CATEGORIES
from utils.formatting import format_size, format_date, format_percentage


class ReportGenerator:
    """
    Generates analysis reports in multiple formats
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
    
    def generate_html(self, report_data: Dict[str, Any], output_path: str):
        """Generate interactive HTML report"""
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        html = self._build_html(report_data)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
    
    def generate_json(self, report_data: Dict[str, Any], output_path: str):
        """Generate JSON report"""
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        json_data = self._make_json_serializable(report_data)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2)
    
    def print_terminal(self, report_data: Dict[str, Any]):
        """Print report to terminal"""
        self._print_terminal_report(report_data)
    
    def generate_cleanup_script(self, recommendations: Dict[str, Any], output_path: str):
        """Generate shell script for cleanup"""
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        script = self._build_cleanup_script(recommendations)
        with open(output_path, 'w') as f:
            f.write(script)
        os.chmod(output_path, 0o755)
    
    def _make_json_serializable(self, data: Any) -> Any:
        """Convert data to JSON-serializable format"""
        if isinstance(data, dict):
            return {k: self._make_json_serializable(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._make_json_serializable(v) for v in data]
        elif hasattr(data, 'to_dict'):
            return data.to_dict()
        elif isinstance(data, datetime):
            return data.isoformat()
        elif isinstance(data, bytes):
            return data.decode('utf-8', errors='replace')
        return data
    
    def _prepare_js_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare data for JavaScript"""
        categories = data.get('categories', {})
        category_data = []
        for cat_id, cat_info in categories.items():
            if isinstance(cat_info, dict) and cat_info.get('size', 0) > 0:
                category_data.append({
                    'id': cat_id, 'name': cat_info.get('name', cat_id),
                    'size': cat_info.get('size', 0), 'count': cat_info.get('count', 0),
                    'icon': cat_info.get('icon', '📁'),
                    'safe_to_clean': cat_info.get('safe_to_clean', False),
                    'files': cat_info.get('files', [])[:100],
                })
        
        recs = data.get('recommendations', {})
        recommendations = recs.get('items', []) if isinstance(recs, dict) else []
        
        dups = data.get('duplicates', {})
        duplicates = list(dups.values()) if isinstance(dups, dict) else []
        
        apps = data.get('app_footprints', {})
        app_list = []
        for name, fp in apps.items():
            if hasattr(fp, 'to_dict'):
                fp = fp.to_dict()
            if isinstance(fp, dict):
                app_list.append({'name': name, **fp})
        
        large_files = []
        for cat_id, cat_info in categories.items():
            if isinstance(cat_info, dict):
                for f in cat_info.get('files', [])[:50]:
                    large_files.append({'category': cat_id, 'category_name': cat_info.get('name', cat_id), **f})
        large_files.sort(key=lambda x: x.get('size', 0), reverse=True)
        
        return {
            'total_size': data.get('total_size', 0),
            'total_files': data.get('total_files', 0),
            'categories': category_data,
            'recommendations': recommendations,
            'reclaimable': recs.get('total_reclaimable', 0) if isinstance(recs, dict) else 0,
            'safe_to_delete': recs.get('safe_to_delete_size', 0) if isinstance(recs, dict) else 0,
            'duplicates': duplicates[:100],
            'apps': app_list,
            'large_files': large_files[:500],
        }
    
    def _build_html(self, data: Dict[str, Any]) -> str:
        """Build complete HTML report"""
        js_data = self._prepare_js_data(data)
        recs = data.get('recommendations', {})
        
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mac Disk Analyzer Report</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
    <style>
:root {{
    --bg-primary: #0d1117; --bg-secondary: #161b22; --bg-tertiary: #21262d;
    --text-primary: #e6edf3; --text-secondary: #8b949e;
    --accent-blue: #58a6ff; --accent-green: #3fb950; --accent-yellow: #d29922;
    --accent-orange: #db6d28; --accent-red: #f85149; --border-color: #30363d;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg-primary); color: var(--text-primary); line-height: 1.6; }}
.header {{ background: linear-gradient(135deg, var(--bg-secondary), var(--bg-tertiary)); border-bottom: 1px solid var(--border-color); padding: 1.5rem 2rem; }}
.header-content {{ max-width: 1400px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem; }}
.header h1 {{ font-size: 1.5rem; }}
.header-meta {{ display: flex; gap: 1.5rem; color: var(--text-secondary); font-size: 0.875rem; }}
.summary-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; padding: 1.5rem 2rem; max-width: 1400px; margin: 0 auto; }}
.card {{ background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 12px; padding: 1.25rem; }}
.summary-card {{ display: flex; align-items: center; gap: 1rem; }}
.summary-card.reclaimable {{ border-color: var(--accent-yellow); }}
.summary-card.safe {{ border-color: var(--accent-green); }}
.card-icon {{ font-size: 2rem; }}
.card-value {{ font-size: 1.5rem; font-weight: 700; }}
.card-label {{ color: var(--text-secondary); font-size: 0.875rem; }}
.tabs {{ display: flex; gap: 0.5rem; padding: 0 2rem; max-width: 1400px; margin: 0 auto; border-bottom: 1px solid var(--border-color); overflow-x: auto; }}
.tab {{ background: none; border: none; color: var(--text-secondary); padding: 0.75rem 1.25rem; cursor: pointer; font-size: 0.9rem; border-bottom: 2px solid transparent; white-space: nowrap; }}
.tab:hover {{ color: var(--text-primary); }}
.tab.active {{ color: var(--accent-blue); border-bottom-color: var(--accent-blue); }}
.main-content {{ max-width: 1400px; margin: 0 auto; padding: 1.5rem 2rem; }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 1.5rem; margin-bottom: 1.5rem; }}
.card h3 {{ margin-bottom: 1rem; font-size: 1.1rem; }}
.chart-container {{ height: 350px; position: relative; }}
.filter-bar {{ display: flex; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }}
.search-input, .sort-select {{ background: var(--bg-tertiary); border: 1px solid var(--border-color); border-radius: 8px; padding: 0.625rem 1rem; color: var(--text-primary); font-size: 0.9rem; }}
.search-input {{ flex: 1; min-width: 200px; }}
.list-item {{ background: var(--bg-tertiary); border: 1px solid var(--border-color); border-radius: 8px; padding: 1rem; display: flex; align-items: center; gap: 1rem; cursor: pointer; transition: all 0.2s; margin-bottom: 0.75rem; }}
.list-item:hover {{ border-color: var(--accent-blue); transform: translateX(4px); }}
.list-item-icon {{ font-size: 1.5rem; width: 40px; text-align: center; flex-shrink: 0; }}
.list-item-content {{ flex: 1; min-width: 0; }}
.list-item-title {{ font-weight: 600; margin-bottom: 0.25rem; }}
.list-item-subtitle {{ color: var(--text-secondary); font-size: 0.85rem; word-break: break-all; }}
.list-item-size {{ font-weight: 600; color: var(--accent-blue); white-space: nowrap; text-align: right; }}
.progress-bar {{ background: var(--bg-primary); height: 6px; border-radius: 3px; margin-top: 0.5rem; overflow: hidden; }}
.progress-fill {{ height: 100%; border-radius: 3px; }}
.rec-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 1rem; }}
.rec-summary {{ display: flex; gap: 1rem; flex-wrap: wrap; }}
.rec-badge {{ padding: 0.375rem 0.75rem; border-radius: 20px; font-size: 0.85rem; font-weight: 500; }}
.rec-badge.safe {{ background: rgba(63, 185, 80, 0.2); color: var(--accent-green); }}
.rec-badge.review {{ background: rgba(210, 153, 34, 0.2); color: var(--accent-yellow); }}
.rec-badge.archive {{ background: rgba(219, 109, 40, 0.2); color: var(--accent-orange); }}
.btn {{ padding: 0.625rem 1.25rem; border-radius: 8px; border: none; cursor: pointer; font-weight: 500; }}
.btn-primary {{ background: var(--accent-blue); color: white; }}
.btn-primary:hover {{ background: #4393e6; }}
.rec-item {{ border-left: 4px solid; }}
.rec-item.safe {{ border-left-color: var(--accent-green); }}
.rec-item.review {{ border-left-color: var(--accent-yellow); }}
.rec-item.archive {{ border-left-color: var(--accent-orange); }}
.dup-summary {{ display: flex; gap: 2rem; margin-bottom: 1.5rem; padding: 1rem; background: var(--bg-tertiary); border-radius: 8px; flex-wrap: wrap; }}
.dup-stat {{ text-align: center; }}
.dup-stat-value {{ font-size: 1.5rem; font-weight: 700; color: var(--accent-yellow); }}
.dup-stat-label {{ color: var(--text-secondary); font-size: 0.85rem; }}
.modal {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 1000; align-items: center; justify-content: center; padding: 1rem; }}
.modal.active {{ display: flex; }}
.modal-content {{ background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 12px; max-width: 800px; max-height: 80vh; width: 100%; overflow: hidden; }}
.modal-header {{ display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.5rem; border-bottom: 1px solid var(--border-color); }}
.modal-close {{ background: none; border: none; color: var(--text-secondary); font-size: 1.5rem; cursor: pointer; }}
.modal-body {{ padding: 1.5rem; overflow-y: auto; max-height: calc(80vh - 60px); }}
.file-list {{ font-family: monospace; font-size: 0.8rem; background: var(--bg-primary); padding: 1rem; border-radius: 8px; max-height: 400px; overflow-y: auto; }}
.file-list-item {{ padding: 0.375rem 0; display: flex; justify-content: space-between; gap: 1rem; border-bottom: 1px solid var(--border-color); align-items: center; }}
.path {{ color: var(--text-secondary); word-break: break-all; flex: 1; }}
.file-actions {{ display: flex; gap: 0.5rem; align-items: center; white-space: nowrap; }}
.file-link {{ text-decoration: none; padding: 0.25rem; border-radius: 4px; transition: background 0.2s; }}
.file-link:hover {{ background: var(--bg-tertiary); }}
.file-size {{ color: var(--accent-blue); font-weight: 500; min-width: 70px; text-align: right; }}
@media (max-width: 768px) {{
    .header-content {{ flex-direction: column; text-align: center; }}
    .summary-cards {{ grid-template-columns: repeat(2, 1fr); }}
    .grid {{ grid-template-columns: 1fr; }}
}}
    </style>
</head>
<body>
    <div class="app">
        <header class="header">
            <div class="header-content">
                <h1>🍎 Mac Disk Analyzer</h1>
                <div class="header-meta">
                    <span>Scanned: {format_date(data.get('timestamp'))}</span>
                    <span>Duration: {data.get('scan_duration', 0):.1f}s</span>
                </div>
            </div>
        </header>
        
        <div class="summary-cards">
            <div class="card summary-card">
                <div class="card-icon">📊</div>
                <div class="card-content">
                    <div class="card-value">{format_size(data.get('total_size', 0))}</div>
                    <div class="card-label">Total Scanned</div>
                </div>
            </div>
            <div class="card summary-card">
                <div class="card-icon">📁</div>
                <div class="card-content">
                    <div class="card-value">{data.get('total_files', 0):,}</div>
                    <div class="card-label">Files</div>
                </div>
            </div>
            <div class="card summary-card reclaimable">
                <div class="card-icon">♻️</div>
                <div class="card-content">
                    <div class="card-value">{format_size(recs.get('total_reclaimable', 0) if isinstance(recs, dict) else 0)}</div>
                    <div class="card-label">Reclaimable</div>
                </div>
            </div>
            <div class="card summary-card safe">
                <div class="card-icon">✅</div>
                <div class="card-content">
                    <div class="card-value">{format_size(recs.get('safe_to_delete_size', 0) if isinstance(recs, dict) else 0)}</div>
                    <div class="card-label">Safe to Delete</div>
                </div>
            </div>
        </div>
        
        <nav class="tabs">
            <button class="tab active" data-tab="overview">Overview</button>
            <button class="tab" data-tab="categories">Categories</button>
            <button class="tab" data-tab="recommendations">Recommendations</button>
            <button class="tab" data-tab="duplicates">Duplicates</button>
            <button class="tab" data-tab="applications">Applications</button>
            <button class="tab" data-tab="files">Large Files</button>
        </nav>
        
        <main class="main-content">
            <section id="overview" class="tab-content active">
                <div class="grid">
                    <div class="card"><h3>📊 Storage Breakdown</h3><div id="treemap-chart" class="chart-container"></div></div>
                    <div class="card"><h3>📈 Category Distribution</h3><div id="pie-chart" class="chart-container"></div></div>
                </div>
            </section>
            <section id="categories" class="tab-content">
                <div class="card"><h3>📂 Categories</h3><div id="categories-list"></div></div>
            </section>
            <section id="recommendations" class="tab-content">
                <div class="rec-header">
                    <div class="rec-summary">
                        <span class="rec-badge safe">🟢 Safe: <span id="safe-count">0</span></span>
                        <span class="rec-badge review">🟡 Review: <span id="review-count">0</span></span>
                        <span class="rec-badge archive">🟠 Archive: <span id="archive-count">0</span></span>
                    </div>
                    <button id="generate-script" class="btn btn-primary">📜 Generate Script</button>
                </div>
                <div class="card"><div id="recommendations-list"></div></div>
            </section>
            <section id="duplicates" class="tab-content">
                <div class="card"><h3>🔄 Duplicate Files</h3><div class="dup-summary" id="dup-summary"></div><div id="duplicates-list"></div></div>
            </section>
            <section id="applications" class="tab-content">
                <div class="card"><h3>📱 Application Footprints</h3><div id="apps-list"></div></div>
            </section>
            <section id="files" class="tab-content">
                <div class="card"><h3>📦 Largest Files</h3><div id="files-list"></div></div>
            </section>
        </main>
        
        <div id="modal" class="modal">
            <div class="modal-content">
                <div class="modal-header"><h3 id="modal-title"></h3><button class="modal-close">&times;</button></div>
                <div id="modal-body" class="modal-body"></div>
            </div>
        </div>
    </div>
    
    <script>
const reportData = {json.dumps(js_data, default=str)};
const colors = ['#58a6ff','#3fb950','#d29922','#f85149','#a371f7','#db6d28','#8b949e','#79c0ff','#7ee787','#e3b341'];

function formatSize(bytes) {{
    if (bytes === 0) return '0 B';
    const units = ['B','KB','MB','GB','TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + units[i];
}}

document.querySelectorAll('.tab').forEach(tab => {{
    tab.addEventListener('click', () => {{
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(tab.dataset.tab).classList.add('active');
    }});
}});

const modal = document.getElementById('modal');
document.querySelector('.modal-close').addEventListener('click', () => modal.classList.remove('active'));
modal.addEventListener('click', e => {{ if (e.target === modal) modal.classList.remove('active'); }});

function showModal(title, content) {{
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = content;
    modal.classList.add('active');
}}

function showCategoryFiles(cat) {{
    let html = '<div class="file-list">';
    cat.files.slice(0, 50).forEach(f => {{
        const encodedPath = encodeURI('file://' + f.path);
        const folderPath = encodeURI('file://' + f.path.substring(0, f.path.lastIndexOf('/')));
        html += '<div class="file-list-item">' +
            '<span class="path">' + f.path + '</span>' +
            '<span class="file-actions">' +
                '<a href="' + encodedPath + '" class="file-link" title="Open file">📄</a>' +
                '<a href="' + folderPath + '" class="file-link" title="Open folder">📁</a>' +
                '<span class="file-size">' + formatSize(f.size) + '</span>' +
            '</span>' +
        '</div>';
    }});
    showModal(cat.icon + ' ' + cat.name + ' (' + formatSize(cat.size) + ')', html + '</div>');
}}

function drawTreemap() {{
    const container = document.getElementById('treemap-chart');
    if (!container) return;
    const width = container.clientWidth, height = container.clientHeight;
    const data = {{ name: 'root', children: reportData.categories.map((c,i) => ({{ name: c.name, value: c.size, icon: c.icon, color: colors[i % colors.length] }})) }};
    const root = d3.hierarchy(data).sum(d => d.value).sort((a,b) => b.value - a.value);
    d3.treemap().size([width, height]).padding(2)(root);
    container.innerHTML = '';
    const svg = d3.select(container).append('svg').attr('width', width).attr('height', height);
    const nodes = svg.selectAll('g').data(root.leaves()).enter().append('g').attr('transform', d => 'translate(' + d.x0 + ',' + d.y0 + ')').style('cursor', 'pointer')
        .on('click', (e, d) => {{ const cat = reportData.categories.find(c => c.name === d.data.name); if (cat) showCategoryFiles(cat); }});
    nodes.append('rect').attr('width', d => Math.max(0, d.x1 - d.x0)).attr('height', d => Math.max(0, d.y1 - d.y0)).attr('fill', d => d.data.color).attr('opacity', 0.8).attr('rx', 4);
    nodes.append('text').attr('x', 8).attr('y', 20).attr('fill', 'white').attr('font-size', '12px').attr('font-weight', '600').text(d => d.x1 - d.x0 < 60 ? '' : d.data.icon + ' ' + d.data.name);
    nodes.append('text').attr('x', 8).attr('y', 38).attr('fill', 'rgba(255,255,255,0.8)').attr('font-size', '11px').text(d => d.x1 - d.x0 < 60 ? '' : formatSize(d.data.value));
}}

function drawPieChart() {{
    const container = document.getElementById('pie-chart');
    if (!container) return;
    const width = container.clientWidth, height = container.clientHeight, radius = Math.min(width, height) / 2 - 40;
    container.innerHTML = '';
    const svg = d3.select(container).append('svg').attr('width', width).attr('height', height).append('g').attr('transform', 'translate(' + width/2 + ',' + height/2 + ')');
    const pie = d3.pie().value(d => d.size).sort(null);
    const arc = d3.arc().innerRadius(radius * 0.5).outerRadius(radius);
    const data = reportData.categories.filter(c => c.size > 0).slice(0, 10);
    svg.selectAll('arc').data(pie(data)).enter().append('path').attr('d', arc).attr('fill', (d, i) => colors[i % colors.length]).attr('stroke', '#161b22').attr('stroke-width', 2).style('cursor', 'pointer')
        .on('click', (e, d) => showCategoryFiles(d.data));
}}

function renderCategories() {{
    const container = document.getElementById('categories-list');
    if (!container) return;
    const maxSize = Math.max(...reportData.categories.map(c => c.size));
    container.innerHTML = reportData.categories.sort((a,b) => b.size - a.size).map((cat, i) => 
        '<div class="list-item" onclick="showCategoryFiles(reportData.categories.find(c=>c.name===\\'' + cat.name + '\\'))"><div class="list-item-icon">' + cat.icon + '</div><div class="list-item-content"><div class="list-item-title">' + cat.name + '</div><div class="list-item-subtitle">' + cat.count.toLocaleString() + ' files</div><div class="progress-bar"><div class="progress-fill" style="width:' + (cat.size/maxSize*100) + '%;background:' + colors[i % colors.length] + '"></div></div></div><div class="list-item-size">' + formatSize(cat.size) + '</div></div>'
    ).join('');
}}

function renderRecommendations() {{
    const container = document.getElementById('recommendations-list');
    if (!container) return;
    let safe = 0, review = 0, archive = 0;
    container.innerHTML = reportData.recommendations.map(rec => {{
        if (rec.category === 'safe') safe++;
        else if (rec.category === 'review') review++;
        else if (rec.category === 'archive') archive++;
        return '<div class="list-item rec-item ' + rec.category + '"><div class="list-item-icon">' + (rec.icon || '💡') + '</div><div class="list-item-content"><div class="list-item-title">' + rec.title + '</div><div class="list-item-subtitle">' + rec.description + '</div></div><div class="list-item-size">' + formatSize(rec.size) + '</div></div>';
    }}).join('') || '<p style="color:var(--text-secondary)">No recommendations.</p>';
    document.getElementById('safe-count').textContent = safe;
    document.getElementById('review-count').textContent = review;
    document.getElementById('archive-count').textContent = archive;
}}

function renderDuplicates() {{
    const container = document.getElementById('duplicates-list');
    const summary = document.getElementById('dup-summary');
    if (!container) return;
    const total = reportData.duplicates.length;
    const wasted = reportData.duplicates.reduce((s, d) => s + (d.wasted_space || 0), 0);
    summary.innerHTML = '<div class="dup-stat"><div class="dup-stat-value">' + total + '</div><div class="dup-stat-label">Groups</div></div><div class="dup-stat"><div class="dup-stat-value">' + formatSize(wasted) + '</div><div class="dup-stat-label">Wasted</div></div>';
    container.innerHTML = reportData.duplicates.slice(0, 50).map(d => '<div class="list-item"><div class="list-item-icon">🔄</div><div class="list-item-content"><div class="list-item-title">' + d.count + ' identical files (' + formatSize(d.size) + ' each)</div><div class="list-item-subtitle">' + (d.paths || []).slice(0, 2).join(', ') + '</div></div><div class="list-item-size" style="color:var(--accent-yellow)">' + formatSize(d.wasted_space) + '</div></div>').join('') || '<p style="color:var(--text-secondary)">No duplicates found.</p>';
}}

function renderApps() {{
    const container = document.getElementById('apps-list');
    if (!container) return;
    container.innerHTML = reportData.apps.sort((a,b) => (b.total_size || 0) - (a.total_size || 0)).slice(0, 30).map(app => 
        '<div class="list-item"><div class="list-item-icon">📱</div><div class="list-item-content"><div class="list-item-title">' + app.name + '</div><div class="list-item-subtitle">App: ' + formatSize(app.app_size || 0) + ' | Cache: ' + formatSize(app.cache_size || 0) + ' | Data: ' + formatSize(app.data_size || 0) + '</div></div><div><div class="list-item-size">' + formatSize(app.total_size || 0) + '</div>' + ((app.cleanable_size || 0) > 0 ? '<div style="font-size:0.8rem;color:var(--accent-green)">' + formatSize(app.cleanable_size) + ' cleanable</div>' : '') + '</div></div>'
    ).join('') || '<p style="color:var(--text-secondary)">No app data.</p>';
}}

function renderFiles() {{
    const container = document.getElementById('files-list');
    if (!container) return;
    container.innerHTML = reportData.large_files.slice(0, 100).map(f => {{
        const encodedPath = encodeURI('file://' + f.path);
        const folderPath = encodeURI('file://' + f.path.substring(0, f.path.lastIndexOf('/')));
        return '<div class="list-item"><div class="list-item-icon">📄</div><div class="list-item-content"><div class="list-item-title">' + f.path.split('/').pop() + '</div><div class="list-item-subtitle path">' + f.path + '</div></div><div class="file-actions"><a href="' + encodedPath + '" class="file-link" title="Open file">📄</a><a href="' + folderPath + '" class="file-link" title="Open folder">📁</a><span class="list-item-size">' + formatSize(f.size) + '</span></div></div>';
    }}).join('');
}}

document.getElementById('generate-script')?.addEventListener('click', () => {{
    let script = '#!/bin/bash\\n# Mac Disk Analyzer Cleanup Script\\n# Generated: ' + new Date().toISOString() + '\\n#\\n# ⚠️  REVIEW CAREFULLY BEFORE RUNNING!\\n#\\n\\nset -e\\n\\necho "🧹 Starting cleanup..."\\necho ""\\n\\n';
    
    let totalSize = 0;
    reportData.recommendations.filter(r => r.category === 'safe' && r.safe_to_auto_clean).forEach(rec => {{
        script += '# ' + rec.title + ' (' + formatSize(rec.size) + ')\\n';
        script += 'echo "Cleaning: ' + rec.title + '"\\n';
        if (rec.command) {{
            script += rec.command + '\\n';
        }} else if (rec.paths && rec.paths.length > 0) {{
            rec.paths.slice(0, 20).forEach(p => {{
                script += 'rm -rf "' + p.replace(/"/g, '\\\\"') + '" 2>/dev/null || true\\n';
            }});
        }}
        script += '\\n';
        totalSize += rec.size;
    }});
    
    script += 'echo ""\\necho "✅ Cleanup complete!"\\necho "Estimated space freed: ' + formatSize(totalSize) + '"\\n';
    
    const escapedScript = script.replace(/`/g, '\\\\`').replace(/\\$/g, '\\\\$');
    
    showModal('📜 Cleanup Script', 
        '<div style="margin-bottom:1rem">' +
            '<span style="color:var(--accent-yellow)">⚠️ Review this script carefully before running!</span><br>' +
            '<span style="color:var(--text-secondary)">Estimated space to free: <strong style="color:var(--accent-green)">' + formatSize(totalSize) + '</strong></span>' +
        '</div>' +
        '<pre style="background:var(--bg-primary);padding:1rem;border-radius:8px;overflow-x:auto;white-space:pre-wrap;max-height:400px;overflow-y:auto">' + script.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</pre>' +
        '<div style="margin-top:1rem;display:flex;gap:0.5rem">' +
            '<button class="btn btn-primary" onclick="navigator.clipboard.writeText(`' + escapedScript + '`).then(() => this.textContent = \\'✅ Copied!\\')">📋 Copy Script</button>' +
            '<button class="btn" style="background:var(--bg-tertiary)" onclick="const blob = new Blob([`' + escapedScript + '`], {{type: \\'text/plain\\'}}); const a = document.createElement(\\'a\\'); a.href = URL.createObjectURL(blob); a.download = \\'cleanup.sh\\'; a.click()">💾 Download .sh</button>' +
        '</div>'
    );
}});

window.addEventListener('resize', () => {{ drawTreemap(); drawPieChart(); }});
drawTreemap(); drawPieChart(); renderCategories(); renderRecommendations(); renderDuplicates(); renderApps(); renderFiles();
    </script>
</body>
</html>'''
    
    def _print_terminal_report(self, data: Dict[str, Any]):
        """Print report to terminal"""
        print("\n" + "=" * 60)
        print("📊 DISK ANALYSIS REPORT")
        print("=" * 60)
        print(f"\n📁 Total: {data.get('total_files', 0):,} files ({format_size(data.get('total_size', 0))})")
        
        recs = data.get('recommendations', {})
        if isinstance(recs, dict):
            print(f"♻️  Reclaimable: {format_size(recs.get('total_reclaimable', 0))}")
            print(f"✅ Safe: {format_size(recs.get('safe_to_delete_size', 0))}")
        
        print("\n" + "-" * 60)
        print("TOP CATEGORIES")
        print("-" * 60)
        
        categories = data.get('categories', {})
        sorted_cats = sorted(
            [(k, v) for k, v in categories.items() if isinstance(v, dict)],
            key=lambda x: x[1].get('size', 0), reverse=True
        )[:10]
        
        for cat_id, cat_info in sorted_cats:
            icon = cat_info.get('icon', '📁')
            name = cat_info.get('name', cat_id)
            size = format_size(cat_info.get('size', 0))
            print(f"  {icon} {name:<25} {size:>12}")
        
        print("=" * 60)
    
    def _build_cleanup_script(self, recommendations: Dict[str, Any]) -> str:
        """Build cleanup shell script"""
        lines = ['#!/bin/bash', '# Mac Disk Analyzer Cleanup', '# Review before running!', '', 'set -e', '']
        items = recommendations.get('items', []) if isinstance(recommendations, dict) else []
        
        for rec in items:
            if rec.get('category') != 'safe' or not rec.get('safe_to_auto_clean'):
                continue
            lines.append(f'# {rec.get("title", "Cleanup")}')
            if rec.get('command'):
                lines.append(rec['command'])
            elif rec.get('paths'):
                for p in rec['paths'][:20]:
                    lines.append(f'rm -rf "{p}" 2>/dev/null || true')
            lines.append('')
        
        lines.append('echo "Done!"')
        return '\n'.join(lines)
