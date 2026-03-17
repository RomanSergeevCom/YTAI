#!/usr/bin/env python3
"""
YTAI Stage 05: Generate HTML Review from Pre-Edit Brief
Converts {project}_pre_edit_brief.json → {project}_pre_edit_brief_review.html

Usage:
    python generate_review.py --brief YTAI_Edit_pre_edit_brief.json
    python generate_review.py --brief YTAI_Edit_pre_edit_brief.json --output review.html
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

# --- Color mapping (matches Premiere Pro label colors) ---

COLOR_HEX = {
    "Cyan":    "#00CED1",
    "Blue":    "#4A90D9",
    "Green":   "#4CAF50",
    "Yellow":  "#E6C619",
    "Red":     "#E34850",
    "Magenta": "#E732E7",
    "Orange":  "#EDA63B",
    "Purple":  "#9B59B6",
}

COLOR_HEX_DARK = {
    "Cyan":    "#00807E",
    "Blue":    "#2A5A8A",
    "Green":   "#2E7D32",
    "Yellow":  "#9E8A00",
    "Red":     "#A3282E",
    "Magenta": "#8E1E8E",
    "Orange":  "#B87A20",
    "Purple":  "#6A3D7D",
}


def parse_timecode(tc_str: str) -> float:
    """Parse MM:SS.s or MM:SS or HH:MM:SS format to seconds."""
    tc_str = tc_str.strip().replace(",", ".")
    parts = tc_str.split(":")
    try:
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        elif len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        else:
            return float(tc_str)
    except (ValueError, TypeError):
        return 0.0


def format_duration(seconds: float) -> str:
    """Format seconds to MM:SS."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def generate_html(brief: dict) -> str:
    """Generate HTML review document from {project}_pre_edit_brief.json."""

    segments = brief.get("segments", [])
    project = brief.get("project", {})
    project_name = project.get("project_name", "Untitled")

    # --- Compute stats ---
    used = [s for s in segments if s.get("use", "").upper() == "TRUE"]
    skipped = [s for s in segments if s.get("use", "").upper() == "FALSE"]

    total_duration = 0.0
    selected_duration = 0.0
    for seg in segments:
        dur = parse_timecode(seg.get("tc_out", "0")) - parse_timecode(seg.get("tc_in", "0"))
        total_duration += dur
        if seg.get("use", "").upper() == "TRUE":
            selected_duration += dur

    # Group by blocks
    blocks = {}
    for seg in segments:
        b = seg.get("block", 0)
        if b not in blocks:
            blocks[b] = {
                "name": seg.get("block_name", f"Block {b}"),
                "color": seg.get("color", "Cyan"),
                "segments": [],
            }
        blocks[b]["segments"].append(seg)

    # Find chapters
    chapters = []
    timeline_pos = 0.0
    for seg in used:
        if seg.get("is_chapter", "").upper() == "TRUE":
            chapters.append({
                "time": format_duration(timeline_pos),
                "name": seg.get("block_name", ""),
            })
        dur = parse_timecode(seg.get("tc_out", "0")) - parse_timecode(seg.get("tc_in", "0"))
        timeline_pos += dur

    # --- Build HTML ---
    html_parts = []

    # Header
    html_parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Edit Brief: {escape_html(project_name)}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: #1a1a2e;
    color: #e0e0e0;
    line-height: 1.5;
    padding: 20px;
    max-width: 1200px;
    margin: 0 auto;
}}
h1 {{ color: #fff; font-size: 1.8em; margin-bottom: 5px; }}
.subtitle {{ color: #888; font-size: 0.9em; margin-bottom: 20px; }}
.stats-bar {{
    display: flex; gap: 20px; flex-wrap: wrap;
    background: #16213e; border-radius: 8px; padding: 15px 20px;
    margin-bottom: 20px;
}}
.stat {{ text-align: center; }}
.stat-value {{ font-size: 1.4em; font-weight: bold; color: #fff; }}
.stat-label {{ font-size: 0.75em; color: #888; text-transform: uppercase; }}
.progress-bar {{
    width: 100%; height: 8px; background: #333;
    border-radius: 4px; margin: 15px 0; overflow: hidden;
}}
.progress-fill {{
    height: 100%; border-radius: 4px;
    background: linear-gradient(90deg, #4CAF50, #2196F3);
}}
details {{
    margin-bottom: 12px;
    border-radius: 8px;
    overflow: hidden;
}}
summary {{
    padding: 12px 20px;
    cursor: pointer;
    font-weight: bold;
    font-size: 1.1em;
    display: flex;
    align-items: center;
    gap: 10px;
    user-select: none;
    list-style: none;
}}
summary::-webkit-details-marker {{ display: none; }}
summary::before {{
    content: '\\25B6';
    font-size: 0.7em;
    transition: transform 0.2s;
}}
details[open] summary::before {{ transform: rotate(90deg); }}
.block-content {{ padding: 0 20px 15px; background: #16213e; }}
.segment {{
    display: grid;
    grid-template-columns: 4px 1fr;
    gap: 0 12px;
    padding: 10px 0;
    border-bottom: 1px solid #2a2a4a;
}}
.segment:last-child {{ border-bottom: none; }}
.seg-stripe {{ border-radius: 2px; }}
.seg-body {{ display: flex; flex-direction: column; gap: 4px; }}
.seg-header {{
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    font-size: 0.85em;
}}
.seg-id {{ font-weight: bold; color: #fff; }}
.seg-clip {{ color: #888; }}
.seg-speaker {{ color: #aaa; }}
.seg-time {{ color: #888; font-family: monospace; }}
.seg-duration {{
    background: #2a2a4a; padding: 1px 6px; border-radius: 3px;
    font-size: 0.8em; color: #aaa;
}}
.badge {{
    display: inline-block; padding: 1px 8px; border-radius: 3px;
    font-size: 0.75em; font-weight: bold; text-transform: uppercase;
}}
.badge-use {{ background: #2E7D32; color: #fff; }}
.badge-skip {{ background: #5a2a2a; color: #E34850; }}
.badge-chapter {{ background: #1a3a5a; color: #4A90D9; }}
.badge-priority {{ background: #4a3a1a; color: #EDA63B; }}
.seg-text {{
    color: #bbb; font-size: 0.85em; font-style: italic;
    max-height: 3em; overflow: hidden;
    text-overflow: ellipsis;
}}
.seg-meta {{ display: flex; flex-wrap: wrap; gap: 8px; font-size: 0.8em; }}
.meta-broll {{ color: #EDA63B; }}
.meta-notes {{ color: #888; }}
.skipped-table {{
    width: 100%; border-collapse: collapse;
    background: #16213e; border-radius: 8px;
    overflow: hidden; margin-bottom: 20px;
}}
.skipped-table th {{
    background: #2a2a4a; padding: 8px 12px;
    text-align: left; font-size: 0.8em; color: #888;
    text-transform: uppercase;
}}
.skipped-table td {{
    padding: 8px 12px; border-bottom: 1px solid #2a2a4a;
    font-size: 0.85em;
}}
.chapters {{
    background: #16213e; border-radius: 8px; padding: 15px 20px;
    margin-bottom: 20px;
}}
.chapters h2 {{ font-size: 1.1em; margin-bottom: 10px; color: #fff; }}
.chapter-item {{
    display: flex; gap: 15px; padding: 3px 0;
    font-family: monospace; font-size: 0.9em;
}}
.chapter-time {{ color: #4A90D9; min-width: 50px; }}
.chapter-name {{ color: #ccc; }}
.section-title {{
    font-size: 1.2em; color: #fff; margin: 25px 0 10px;
    padding-bottom: 5px; border-bottom: 1px solid #333;
}}
@media print {{
    body {{ background: #fff; color: #333; }}
    .stats-bar, .chapters, details {{ break-inside: avoid; }}
    summary {{ color: #333; }}
    .seg-text {{ color: #555; }}
}}
</style>
</head>
<body>
""")

    # Title and stats
    pct = int(selected_duration / total_duration * 100) if total_duration > 0 else 0
    html_parts.append(f"""
<h1>Edit Brief: {escape_html(project_name)}</h1>
<div class="subtitle">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(segments)} segments across {len(blocks)} blocks</div>

<div class="stats-bar">
    <div class="stat">
        <div class="stat-value">{format_duration(total_duration)}</div>
        <div class="stat-label">Total Footage</div>
    </div>
    <div class="stat">
        <div class="stat-value">{format_duration(selected_duration)}</div>
        <div class="stat-label">Selected</div>
    </div>
    <div class="stat">
        <div class="stat-value">{pct}%</div>
        <div class="stat-label">Kept</div>
    </div>
    <div class="stat">
        <div class="stat-value">{len(used)}/{len(segments)}</div>
        <div class="stat-label">Segments</div>
    </div>
    <div class="stat">
        <div class="stat-value">{len(blocks)}</div>
        <div class="stat-label">Blocks</div>
    </div>
    <div class="stat">
        <div class="stat-value">{len(chapters)}</div>
        <div class="stat-label">Chapters</div>
    </div>
</div>

<div class="progress-bar">
    <div class="progress-fill" style="width: {pct}%"></div>
</div>
""")

    # YouTube Chapters
    if chapters:
        html_parts.append('<div class="chapters"><h2>YouTube Chapters</h2>')
        for ch in chapters:
            html_parts.append(f'<div class="chapter-item"><span class="chapter-time">{ch["time"]}</span><span class="chapter-name">{escape_html(ch["name"])}</span></div>')
        html_parts.append('</div>')

    # Blocks
    html_parts.append('<div class="section-title">Blocks</div>')
    for block_num in sorted(blocks.keys()):
        block = blocks[block_num]
        color = block["color"]
        hex_color = COLOR_HEX.get(color, "#888")
        hex_dark = COLOR_HEX_DARK.get(color, "#444")
        block_used = [s for s in block["segments"] if s.get("use", "").upper() == "TRUE"]
        block_dur = sum(
            parse_timecode(s.get("tc_out", "0")) - parse_timecode(s.get("tc_in", "0"))
            for s in block_used
        )

        html_parts.append(f"""
<details open>
    <summary style="background: {hex_dark}; color: #fff;">
        Block {block_num}: {escape_html(block["name"])}
        <span style="font-size: 0.75em; font-weight: normal; color: rgba(255,255,255,0.7);">
            ({color}) | {len(block_used)}/{len(block["segments"])} segments | ~{format_duration(block_dur)}
        </span>
    </summary>
    <div class="block-content">
""")

        for seg in block["segments"]:
            is_used = seg.get("use", "").upper() == "TRUE"
            seg_id = seg.get("segment_id", "?")
            source = seg.get("source_file", "?")
            speaker = seg.get("speaker", "")
            tc_in = seg.get("tc_in", "?")
            tc_out = seg.get("tc_out", "?")
            dur = parse_timecode(tc_out) - parse_timecode(tc_in)
            transcript = seg.get("transcript", "")
            broll = seg.get("broll_note", "")
            notes = seg.get("notes", "")
            priority = seg.get("priority", 1)
            is_chapter = seg.get("is_chapter", "").upper() == "TRUE"

            use_badge = '<span class="badge badge-use">USE</span>' if is_used else '<span class="badge badge-skip">SKIP</span>'
            chapter_badge = ' <span class="badge badge-chapter">CHAPTER</span>' if is_chapter else ''
            priority_badge = f' <span class="badge badge-priority">ALT {priority}</span>' if priority > 1 else ''

            opacity = "1" if is_used else "0.5"

            html_parts.append(f"""
        <div class="segment" style="opacity: {opacity};">
            <div class="seg-stripe" style="background: {hex_color};"></div>
            <div class="seg-body">
                <div class="seg-header">
                    <span class="seg-id">{escape_html(seg_id)}</span>
                    <span class="seg-clip">{escape_html(source)}</span>
                    <span class="seg-speaker">{escape_html(speaker)}</span>
                    <span class="seg-time">{escape_html(tc_in)} → {escape_html(tc_out)}</span>
                    <span class="seg-duration">{dur:.0f}s</span>
                    {use_badge}{chapter_badge}{priority_badge}
                </div>
""")
            if transcript:
                display_text = transcript[:200] + ("..." if len(transcript) > 200 else "")
                html_parts.append(f'                <div class="seg-text">"{escape_html(display_text)}"</div>')

            if broll or notes:
                html_parts.append('                <div class="seg-meta">')
                if broll:
                    html_parts.append(f'                    <span class="meta-broll">B-roll: {escape_html(broll)}</span>')
                if notes:
                    html_parts.append(f'                    <span class="meta-notes">{escape_html(notes)}</span>')
                html_parts.append('                </div>')

            html_parts.append("""
            </div>
        </div>""")

        html_parts.append("""
    </div>
</details>""")

    # Skipped segments table
    if skipped:
        html_parts.append("""
<div class="section-title">Skipped Segments</div>
<table class="skipped-table">
<thead><tr><th>Segment</th><th>Clip</th><th>Time</th><th>Duration</th><th>Reason</th></tr></thead>
<tbody>
""")
        for seg in skipped:
            seg_id = seg.get("segment_id", "?")
            source = seg.get("source_file", "?")
            tc_in = seg.get("tc_in", "?")
            dur = parse_timecode(seg.get("tc_out", "0")) - parse_timecode(seg.get("tc_in", "0"))
            notes = seg.get("notes", "—")
            html_parts.append(f'<tr><td>{escape_html(seg_id)}</td><td>{escape_html(source)}</td><td>{escape_html(tc_in)}</td><td>{dur:.0f}s</td><td>{escape_html(notes)}</td></tr>')

        html_parts.append("</tbody></table>")

    # Footer
    html_parts.append(f"""
<div style="margin-top: 30px; padding: 15px; text-align: center; color: #555; font-size: 0.8em;">
    YTAI Edit Brief Review | {escape_html(project_name)} | {datetime.now().strftime('%Y-%m-%d %H:%M')}
</div>
</body>
</html>
""")

    return "\n".join(html_parts)


def main():
    parser = argparse.ArgumentParser(
        description="YTAI 05_editing: Generate HTML review from {project}_pre_edit_brief.json"
    )
    parser.add_argument(
        "--brief", required=True,
        help="Path to {project}_pre_edit_brief.json"
    )
    parser.add_argument(
        "--output", default=None,
        help="Output HTML path (default: same dir as brief, _review.html)"
    )
    args = parser.parse_args()

    brief_path = Path(args.brief)
    if not brief_path.exists():
        print(f"Error: {brief_path} not found")
        sys.exit(1)

    with open(brief_path, "r", encoding="utf-8") as f:
        brief = json.load(f)

    html = generate_html(brief)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = brief_path.with_name(brief_path.stem + "_review.html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Review generated: {output_path}")
    print(f"  Segments: {len(brief.get('segments', []))}")
    used = sum(1 for s in brief.get("segments", []) if s.get("use", "").upper() == "TRUE")
    print(f"  Used: {used} | Skipped: {len(brief.get('segments', [])) - used}")
    print(f"\nOpen in browser: file://{output_path.resolve()}")


if __name__ == "__main__":
    main()
