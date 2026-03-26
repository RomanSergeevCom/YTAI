#!/usr/bin/env python3
"""
YTAI Stage 05: Diff two Assembly Brief versions → HTML report.

Compares v1_in.json and v2_in.json segment-by-segment, detects
trim / cut / split / add / remove / recolor changes, and renders
a color-coded HTML diff report with word-level transcript diffs,
timeline positions, and block structure overview.

Usage:
    python diff_briefs.py --v1 YTXX01_Assembly_v1_in.json --v2 YTXX01_Assembly_v2_in.json
    python diff_briefs.py --v1 v1.json --v2 v2.json --output diff.html
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from datetime import datetime


# ---------------------------------------------------------------------------
# Utilities (shared with generate_review.py)
# ---------------------------------------------------------------------------

COLOR_HEX = {
    "Cyan": "#00CED1", "Blue": "#4A90D9", "Green": "#4CAF50",
    "Yellow": "#E6C619", "Red": "#E34850", "Magenta": "#E732E7",
    "Orange": "#EDA63B", "Purple": "#9B59B6",
}
COLOR_HEX_DARK = {
    "Cyan": "#00807E", "Blue": "#2A5A8A", "Green": "#2E7D32",
    "Yellow": "#9E8A00", "Red": "#A3282E", "Magenta": "#8E1E8E",
    "Orange": "#B87A20", "Purple": "#6A3D7D",
}

CHANGE_BADGE = {
    "cut":     ("CUT",     "#A3282E"),
    "add":     ("ADD",     "#2E7D32"),
    "trim":    ("TRIM",    "#9E8A00"),
    "split":   ("SPLIT",   "#2A5A8A"),
    "move":    ("MOVE",    "#6A3D7D"),
    "reorder": ("REORDER", "#6A3D7D"),
    "merge":   ("MERGE",   "#00807E"),
    "recolor": ("RECOLOR", "#B87A20"),
}

COMPARE_FIELDS = [
    "use", "block", "block_name", "tc_in", "tc_out",
    "color", "priority", "is_chapter",
    "segment_name", "speaker", "notes", "broll_note",
]


def parse_tc(tc_str: str) -> float:
    tc_str = tc_str.strip().replace(",", ".")
    parts = tc_str.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return float(tc_str)
    except (ValueError, TypeError):
        return 0.0


def fmt_dur(seconds: float) -> str:
    m, s = divmod(int(abs(seconds)), 60)
    return f"{m}:{s:02d}"


def esc(text) -> str:
    return (str(text)
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def seg_dur(seg: dict) -> float:
    return parse_tc(seg.get("tc_out", "0")) - parse_tc(seg.get("tc_in", "0"))


# ---------------------------------------------------------------------------
# Word-level diff
# ---------------------------------------------------------------------------

def word_diff_html(old_text: str, new_text: str) -> str:
    """Generate HTML with word-level diff highlighting."""
    old_words = old_text.split()
    new_words = new_text.split()
    sm = difflib.SequenceMatcher(None, old_words, new_words)
    parts = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            parts.append(esc(" ".join(old_words[i1:i2])))
        elif op == "delete":
            parts.append(f'<span class="word-cut">{esc(" ".join(old_words[i1:i2]))}</span>')
        elif op == "insert":
            parts.append(f'<span class="word-added">{esc(" ".join(new_words[j1:j2]))}</span>')
        elif op == "replace":
            parts.append(f'<span class="word-cut">{esc(" ".join(old_words[i1:i2]))}</span>')
            parts.append(f'<span class="word-added">{esc(" ".join(new_words[j1:j2]))}</span>')
    return " ".join(parts)


def split_transcript_html(parent_text: str, children_texts: list) -> str:
    """Highlight which words from parent ended up in which child, and what was cut."""
    combined = " ".join(children_texts)
    parent_words = parent_text.split()
    combined_words = combined.split()
    sm = difflib.SequenceMatcher(None, parent_words, combined_words)

    parts = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            parts.append(f'<span class="word-kept">{esc(" ".join(parent_words[i1:i2]))}</span>')
        elif op == "delete":
            parts.append(f'<span class="word-cut">{esc(" ".join(parent_words[i1:i2]))}</span>')
        elif op == "insert":
            parts.append(f'<span class="word-added">{esc(" ".join(combined_words[j1:j2]))}</span>')
        elif op == "replace":
            parts.append(f'<span class="word-cut">{esc(" ".join(parent_words[i1:i2]))}</span>')
            parts.append(f'<span class="word-added">{esc(" ".join(combined_words[j1:j2]))}</span>')
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Timeline positions
# ---------------------------------------------------------------------------

def compute_timeline_positions(brief: dict) -> dict:
    """Return {segment_id: position_sec} for used segments in assembly order."""
    segs = brief.get("segments", [])
    used = [s for s in segs
            if str(s.get("use", "")).upper() == "TRUE" and s.get("block", 99) != 99]
    used.sort(key=lambda s: (s.get("block", 0), segs.index(s)))
    pos = {}
    t = 0.0
    for s in used:
        pos[s["segment_id"]] = t
        t += seg_dur(s)
    return pos


def compute_block_durations(brief: dict) -> list:
    """Return [(block_num, block_name, color, duration)] for used segments."""
    segs = brief.get("segments", [])
    used = [s for s in segs
            if str(s.get("use", "")).upper() == "TRUE" and s.get("block", 99) != 99]
    blocks = {}
    for s in used:
        b = s.get("block", 0)
        if b not in blocks:
            blocks[b] = {"name": s.get("block_name", f"Block {b}"),
                         "color": s.get("color", "Cyan"), "dur": 0.0}
        blocks[b]["dur"] += seg_dur(s)
    return [(b, blocks[b]["name"], blocks[b]["color"], blocks[b]["dur"])
            for b in sorted(blocks)]


# ---------------------------------------------------------------------------
# Segment matching
# ---------------------------------------------------------------------------

def match_segments(v1_segs: list, v2_segs: list) -> dict:
    """Match segments between v1 and v2 by segment_id with split detection."""
    v1_map = {s["segment_id"]: s for s in v1_segs}
    v2_map = {s["segment_id"]: s for s in v2_segs}
    v1_ids = set(v1_map)
    v2_ids = set(v2_map)

    matched = []      # (v1_seg, v2_seg, changed_fields{})
    added = []         # v2_seg
    removed = []       # v1_seg
    splits = []        # (v1_seg, [v2_children])

    # Detect splits: seg_012 in v1, seg_012a/seg_012b in v2
    split_parents = set()
    for rid in sorted(v1_ids - v2_ids):
        children = sorted([cid for cid in (v2_ids - v1_ids)
                           if cid.startswith(rid) and len(cid) > len(rid)])
        if children:
            splits.append((v1_map[rid], [v2_map[c] for c in children]))
            split_parents.add(rid)
            for c in children:
                v2_ids.discard(c)

    # Matched (same id in both)
    for sid in sorted(v1_ids & v2_ids):
        s1, s2 = v1_map[sid], v2_map[sid]
        changes = {}
        for f in COMPARE_FIELDS:
            old, new = str(s1.get(f, "")), str(s2.get(f, ""))
            if old != new:
                changes[f] = (old, new)
        matched.append((s1, s2, changes))

    # Added (in v2 only, not split children)
    for sid in sorted(v2_ids - v1_ids):
        added.append(v2_map[sid])

    # Removed (in v1 only, not split parents)
    for sid in sorted(v1_ids - v2_ids - split_parents):
        removed.append(v1_map[sid])

    return {
        "matched": matched,
        "added": added,
        "removed": removed,
        "splits": splits,
    }


def match_screens(v1_screens: list, v2_screens: list) -> dict:
    v1_map = {s["screen_id"]: s for s in v1_screens}
    v2_map = {s["screen_id"]: s for s in v2_screens}
    v1_ids, v2_ids = set(v1_map), set(v2_map)

    matched = []
    for sid in sorted(v1_ids & v2_ids):
        s1, s2 = v1_map[sid], v2_map[sid]
        changes = {}
        for f in ("type", "segment_id", "title", "subtitle", "body"):
            old, new = str(s1.get(f, "")), str(s2.get(f, ""))
            if old != new:
                changes[f] = (old, new)
        if changes:
            matched.append((s1, s2, changes))

    added = [v2_map[s] for s in sorted(v2_ids - v1_ids)]
    removed = [v1_map[s] for s in sorted(v1_ids - v2_ids)]
    return {"matched": matched, "added": added, "removed": removed}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def compute_stats(brief: dict) -> dict:
    segs = brief.get("segments", [])
    used = [s for s in segs if str(s.get("use", "")).upper() == "TRUE"]
    blocks = {s.get("block") for s in segs}
    sel_dur = sum(seg_dur(s) for s in used)
    return {
        "total_segs": len(segs),
        "used_segs": len(used),
        "blocks": len(blocks),
        "duration": sel_dur,
        "screens": len(brief.get("screens", [])),
    }


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: #1a1a2e; color: #e0e0e0; line-height: 1.5;
    padding: 20px; max-width: 1200px; margin: 0 auto;
}
h1 { color: #fff; font-size: 1.8em; margin-bottom: 5px; }
.subtitle { color: #888; font-size: 0.9em; margin-bottom: 20px; }

/* Stats */
.stats-grid {
    display: grid; grid-template-columns: 1fr 1fr 1fr;
    gap: 2px; background: #16213e; border-radius: 8px;
    overflow: hidden; margin-bottom: 20px;
}
.stats-col { padding: 12px 16px; }
.stats-col-header { font-size: 0.7em; color: #888; text-transform: uppercase; margin-bottom: 6px; }
.stat-row { display: flex; justify-content: space-between; padding: 2px 0; font-size: 0.85em; }
.stat-label { color: #aaa; }
.stat-value { color: #fff; font-weight: bold; font-family: monospace; }
.stat-delta-pos { color: #4CAF50; }
.stat-delta-neg { color: #E34850; }
.stat-delta-zero { color: #555; }

/* Timeline bar */
.timeline-bar {
    display: flex; height: 32px; border-radius: 6px; overflow: hidden;
    margin-bottom: 20px; position: relative; background: #111;
}
.tl-block {
    position: relative; display: flex; align-items: center;
    justify-content: center; font-size: 0.65em; font-weight: bold;
    color: rgba(255,255,255,0.8); overflow: hidden; white-space: nowrap;
    border-right: 1px solid #1a1a2e; cursor: default;
}
.tl-marker {
    position: absolute; bottom: 0; width: 3px; height: 100%;
    background: #fff; opacity: 0.9;
}

/* Changelog */
.changelog { background: #16213e; border-radius: 8px; padding: 15px 20px; margin-bottom: 20px; }
.changelog h2 { font-size: 1.1em; margin-bottom: 10px; color: #fff; }
.changelog-table { width: 100%; border-collapse: collapse; }
.changelog-table td { padding: 6px 10px; border-bottom: 1px solid #2a2a4a; font-size: 0.85em; vertical-align: top; }
.changelog-table tr:last-child td { border-bottom: none; }

/* Badges */
.badge {
    display: inline-block; padding: 1px 8px; border-radius: 3px;
    font-size: 0.75em; font-weight: bold; text-transform: uppercase;
    white-space: nowrap;
}

/* Block sections */
details { margin-bottom: 12px; border-radius: 8px; overflow: hidden; }
summary {
    padding: 12px 20px; cursor: pointer; font-weight: bold;
    font-size: 1.1em; display: flex; align-items: center;
    gap: 10px; user-select: none; list-style: none;
}
summary::-webkit-details-marker { display: none; }
summary::before { content: '\\25B6'; font-size: 0.7em; transition: transform 0.2s; }
details[open] summary::before { transform: rotate(90deg); }
.block-content { padding: 0 20px 15px; background: #16213e; }

/* Segments */
.segment {
    display: grid; grid-template-columns: 4px 1fr;
    gap: 0 12px; padding: 10px 0; border-bottom: 1px solid #2a2a4a;
}
.segment:last-child { border-bottom: none; }
.seg-stripe { border-radius: 2px; }
.seg-body { display: flex; flex-direction: column; gap: 4px; }
.seg-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 0.85em; }
.seg-id { font-weight: bold; color: #fff; }
.seg-clip { color: #888; }
.seg-time { color: #888; font-family: monospace; }
.seg-duration { background: #2a2a4a; padding: 1px 6px; border-radius: 3px; font-size: 0.8em; color: #aaa; }
.seg-name { color: #bbb; font-size: 0.85em; font-style: italic; }
.seg-tl-pos { color: #4A90D9; font-family: monospace; font-size: 0.8em; }

/* Diff-specific */
.diff-fields { display: flex; flex-direction: column; gap: 3px; margin-top: 4px; }
.diff-field {
    display: inline-flex; gap: 6px; font-size: 0.8em;
    padding: 2px 8px; border-radius: 3px; background: #2a2a1a;
    flex-wrap: wrap;
}
.diff-label { color: #888; min-width: 70px; }
.diff-was { color: #E34850; text-decoration: line-through; }
.diff-arrow { color: #555; }
.diff-now { color: #4CAF50; }
.unchanged { opacity: 0.35; }
.section-title { font-size: 1.2em; color: #fff; margin: 25px 0 10px; padding-bottom: 5px; border-bottom: 1px solid #333; }

/* Transcript diff */
.transcript-diff {
    font-size: 0.85em; line-height: 1.6; padding: 8px 10px;
    background: #0d1117; border-radius: 4px; margin-top: 6px;
}
.word-kept { color: #bbb; }
.word-cut { color: #E34850; text-decoration: line-through; background: #3a1a1a; padding: 0 2px; border-radius: 2px; }
.word-added { color: #4CAF50; background: #1a3a1a; padding: 0 2px; border-radius: 2px; }
.split-divider {
    display: inline-block; color: #4A90D9; font-weight: bold;
    margin: 0 4px; padding: 0 4px; border-left: 2px solid #4A90D9;
}

/* Notes diff */
.notes-diff {
    font-size: 0.8em; padding: 6px 10px; margin-top: 4px;
    background: #1a1a1a; border-radius: 4px; border-left: 2px solid #555;
}
.notes-diff summary { font-size: 0.85em; padding: 4px 0; color: #888; }
.notes-diff-content { padding: 4px 0; }

/* Screens */
.screen-table { width: 100%; border-collapse: collapse; background: #16213e; border-radius: 8px; overflow: hidden; }
.screen-table th { background: #2a2a4a; padding: 8px 12px; text-align: left; font-size: 0.8em; color: #888; text-transform: uppercase; }
.screen-table td { padding: 8px 12px; border-bottom: 1px solid #2a2a4a; font-size: 0.85em; }

@media print {
    body { background: #fff; color: #333; }
    .stats-grid, .changelog, details { break-inside: avoid; }
    summary { color: #333; }
    .word-cut { color: #c00; background: #fdd; }
    .word-added { color: #060; background: #dfd; }
}
"""


def render_badge(label: str, bg: str) -> str:
    return f'<span class="badge" style="background:{bg};color:#fff">{esc(label)}</span>'


def render_changelog(changelog: list) -> str:
    """Render changelog[] entries from v2 JSON."""
    parts = []
    for entry in changelog:
        changes = entry.get("changes", [])
        if not changes:
            continue
        ver = entry.get("version", "?")
        date = entry.get("date", "")
        source = entry.get("source", "")
        summary = entry.get("summary", "")

        parts.append(f'<div class="changelog"><h2>{esc(ver)} — {len(changes)} changes ({esc(date)}, {esc(source)})</h2>')
        if summary:
            parts.append(f'<p style="color:#aaa;font-size:0.85em;margin-bottom:10px">{esc(summary)}</p>')
        parts.append('<table class="changelog-table">')
        for ch in changes:
            ctype = ch.get("type", "?")
            badge_label, badge_bg = CHANGE_BADGE.get(ctype, (ctype.upper(), "#555"))
            seg_id = ch.get("segment_id", "")
            desc = ch.get("description", "")
            reason = ch.get("reason", "")
            was = ch.get("was", "")
            now = ch.get("now", "")

            delta = ""
            if was and now:
                delta = f' <span class="diff-was">{esc(was)}</span> <span class="diff-arrow">&rarr;</span> <span class="diff-now">{esc(now)}</span>'

            parts.append(f'<tr>'
                         f'<td>{render_badge(badge_label, badge_bg)}</td>'
                         f'<td style="color:#fff;font-family:monospace">{esc(seg_id)}</td>'
                         f'<td>{esc(desc)}{delta}</td>'
                         f'<td style="color:#888">{esc(reason)}</td>'
                         f'</tr>')
        parts.append('</table></div>')
    return "\n".join(parts)


def render_timeline_bar(v2_blocks: list, changed_seg_ids: set, v2_positions: dict,
                        total_dur: float) -> str:
    """Render a colored timeline bar with block segments and change markers."""
    if total_dur <= 0:
        return ""
    parts = ['<div class="timeline-bar">']
    for block_num, block_name, color, dur in v2_blocks:
        pct = dur / total_dur * 100
        if pct < 1:
            continue
        hex_c = COLOR_HEX_DARK.get(color, "#2a2a4a")
        label = f"B{block_num}" if pct > 4 else ""
        title = f"Block {block_num}: {block_name} ({fmt_dur(dur)})"
        parts.append(f'<div class="tl-block" style="width:{pct:.1f}%;background:{hex_c}" title="{esc(title)}">{label}</div>')
    parts.append('</div>')
    return "\n".join(parts)


def render_diff_field(label: str, old: str, new: str) -> str:
    return (f'<div class="diff-field">'
            f'<span class="diff-label">{esc(label)}:</span>'
            f'<span class="diff-was">{esc(old)}</span>'
            f'<span class="diff-arrow">&rarr;</span>'
            f'<span class="diff-now">{esc(new)}</span>'
            f'</div>')


def render_notes_diff(old_notes: str, new_notes: str) -> str:
    """Render full notes diff in a collapsible block."""
    diff_html = word_diff_html(old_notes, new_notes)
    return (f'<details class="notes-diff" open>'
            f'<summary>Notes changed</summary>'
            f'<div class="notes-diff-content">{diff_html}</div>'
            f'</details>')


def render_segment_card(seg: dict, stripe_color: str, extra_badges: str = "",
                        diff_fields: dict = None, css_class: str = "",
                        transcript_html: str = "", notes_html: str = "",
                        tl_position: float = None) -> str:
    sid = seg.get("segment_id", "?")
    source = seg.get("source_file", "?")
    tc_in = seg.get("tc_in", "?")
    tc_out = seg.get("tc_out", "?")
    dur = seg_dur(seg)
    name = seg.get("segment_name", "")

    tl_badge = ""
    if tl_position is not None:
        tl_badge = f'<span class="seg-tl-pos">@ {fmt_dur(tl_position)}</span>'

    parts = [f'<div class="segment {css_class}">',
             f'  <div class="seg-stripe" style="background:{stripe_color}"></div>',
             f'  <div class="seg-body">',
             f'    <div class="seg-header">',
             f'      <span class="seg-id">{esc(sid)}</span>',
             f'      <span class="seg-clip">{esc(source)}</span>',
             f'      <span class="seg-time">{esc(tc_in)} &rarr; {esc(tc_out)}</span>',
             f'      <span class="seg-duration">{dur:.0f}s</span>',
             f'      {tl_badge}',
             f'      {extra_badges}',
             f'    </div>']
    if name:
        parts.append(f'    <div class="seg-name">{esc(name)}</div>')

    # Diff fields (excluding notes — those get their own section)
    if diff_fields:
        display_fields = {k: v for k, v in diff_fields.items() if k != "notes"}
        if display_fields:
            parts.append('    <div class="diff-fields">')
            for field, (old, new) in display_fields.items():
                parts.append(f'      {render_diff_field(field, old, new)}')
            parts.append('    </div>')

    # Transcript diff
    if transcript_html:
        parts.append(f'    <div class="transcript-diff">{transcript_html}</div>')

    # Notes diff (full, collapsible)
    if notes_html:
        parts.append(f'    {notes_html}')
    elif diff_fields and "notes" in diff_fields:
        old_n, new_n = diff_fields["notes"]
        parts.append(f'    {render_notes_diff(old_n, new_n)}')

    parts.extend(['  </div>', '</div>'])
    return "\n".join(parts)


def generate_diff_html(v1: dict, v2: dict) -> str:
    """Generate full HTML diff report."""
    s1 = compute_stats(v1)
    s2 = compute_stats(v2)

    result = match_segments(v1.get("segments", []), v2.get("segments", []))
    screen_result = match_screens(v1.get("screens", []), v2.get("screens", []))

    # Timeline positions for v2
    v2_positions = compute_timeline_positions(v2)
    v2_blocks = compute_block_durations(v2)

    # Collect all changed segment IDs
    changed_ids = set()
    for _, v2_seg, ch in result["matched"]:
        if ch:
            changed_ids.add(v2_seg["segment_id"])
    for _, children in result["splits"]:
        for c in children:
            changed_ids.add(c["segment_id"])
    for seg in result["added"]:
        changed_ids.add(seg["segment_id"])

    # Count changes
    n_modified = sum(1 for _, _, ch in result["matched"] if ch)
    n_unchanged = sum(1 for _, _, ch in result["matched"] if not ch)
    n_total_changes = n_modified + len(result["added"]) + len(result["removed"]) + len(result["splits"])

    project = v2.get("project", {}).get("project_name", v1.get("project", {}).get("project_name", ""))

    parts = [f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Brief Diff: {esc(project)}</title>
<style>{CSS}</style>
</head>
<body>
<h1>Brief Diff: {esc(project)}</h1>
<div class="subtitle">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} | {n_total_changes} changes, {n_unchanged} unchanged</div>
"""]

    # --- Stats delta ---
    def delta_str(d):
        if d > 0:
            return f'<span class="stat-delta-pos">+{d}</span>'
        elif d < 0:
            return f'<span class="stat-delta-neg">{d}</span>'
        return '<span class="stat-delta-zero">-</span>'

    def delta_dur(d):
        sign = "+" if d >= 0 else "-"
        cls = "stat-delta-pos" if d >= 0 else "stat-delta-neg"
        if d == 0:
            return '<span class="stat-delta-zero">-</span>'
        return f'<span class="{cls}">{sign}{fmt_dur(d)}</span>'

    parts.append(f"""
<div class="stats-grid">
  <div class="stats-col">
    <div class="stats-col-header">v1</div>
    <div class="stat-row"><span class="stat-label">Segments</span><span class="stat-value">{s1["used_segs"]}/{s1["total_segs"]}</span></div>
    <div class="stat-row"><span class="stat-label">Duration</span><span class="stat-value">{fmt_dur(s1["duration"])}</span></div>
    <div class="stat-row"><span class="stat-label">Blocks</span><span class="stat-value">{s1["blocks"]}</span></div>
    <div class="stat-row"><span class="stat-label">Screens</span><span class="stat-value">{s1["screens"]}</span></div>
  </div>
  <div class="stats-col">
    <div class="stats-col-header">v2</div>
    <div class="stat-row"><span class="stat-label">Segments</span><span class="stat-value">{s2["used_segs"]}/{s2["total_segs"]}</span></div>
    <div class="stat-row"><span class="stat-label">Duration</span><span class="stat-value">{fmt_dur(s2["duration"])}</span></div>
    <div class="stat-row"><span class="stat-label">Blocks</span><span class="stat-value">{s2["blocks"]}</span></div>
    <div class="stat-row"><span class="stat-label">Screens</span><span class="stat-value">{s2["screens"]}</span></div>
  </div>
  <div class="stats-col">
    <div class="stats-col-header">Delta</div>
    <div class="stat-row"><span class="stat-label">Segments</span><span class="stat-value">{delta_str(s2["used_segs"] - s1["used_segs"])}</span></div>
    <div class="stat-row"><span class="stat-label">Duration</span><span class="stat-value">{delta_dur(s2["duration"] - s1["duration"])}</span></div>
    <div class="stat-row"><span class="stat-label">Blocks</span><span class="stat-value">{delta_str(s2["blocks"] - s1["blocks"])}</span></div>
    <div class="stat-row"><span class="stat-label">Screens</span><span class="stat-value">{delta_str(s2["screens"] - s1["screens"])}</span></div>
  </div>
</div>
""")

    # --- Timeline bar ---
    parts.append(render_timeline_bar(v2_blocks, changed_ids, v2_positions, s2["duration"]))

    # --- Changelog from v2 ---
    changelog = v2.get("changelog", [])
    if changelog:
        parts.append(render_changelog(changelog))

    # --- Per-block segment diffs ---
    block_items = {}  # block_num -> {"name", "items": [(sort_key, html)]}

    def add_to_block(block_num, block_name, sort_key, html):
        if block_num not in block_items:
            block_items[block_num] = {"name": block_name, "items": []}
        block_items[block_num]["items"].append((sort_key, html))

    # Matched segments
    for v1_seg, v2_seg, changes in result["matched"]:
        block = v2_seg.get("block", 0)
        block_name = v2_seg.get("block_name", f"Block {block}")
        sid = v2_seg.get("segment_id", "")
        tl_pos = v2_positions.get(sid)

        if changes:
            badges = render_badge("MODIFIED", "#9E8A00")

            # Transcript diff if transcript changed
            tx_html = ""
            old_tx = v1_seg.get("transcript", "")
            new_tx = v2_seg.get("transcript", "")
            if old_tx != new_tx and old_tx and new_tx:
                tx_html = word_diff_html(old_tx, new_tx)

            html = render_segment_card(v2_seg, "#E6C619", badges,
                                       diff_fields=changes, transcript_html=tx_html,
                                       tl_position=tl_pos)
        else:
            html = render_segment_card(v2_seg, "#555", css_class="unchanged")

        add_to_block(block, block_name, sid, html)

    # Splits — show parent with word-level diff
    for v1_seg, children in result["splits"]:
        parent_id = v1_seg.get("segment_id", "")
        parent_tx = v1_seg.get("transcript", "")
        children_txs = [c.get("transcript", "") for c in children]

        # Build split transcript HTML with dividers between children
        if parent_tx:
            tx_html = split_transcript_html(parent_tx, children_txs)
            # Add dividers showing where each child starts
            child_labels = " ".join(
                f'<span class="split-divider">{c.get("segment_id", "")}</span>'
                for c in children
            )
        else:
            tx_html = ""

        for i, child in enumerate(children):
            block = child.get("block", 0)
            block_name = child.get("block_name", f"Block {block}")
            badges = render_badge(f"SPLIT from {parent_id}", "#2A5A8A")
            tl_pos = v2_positions.get(child.get("segment_id", ""))

            # Show full split transcript only on first child
            child_tx = tx_html if i == 0 else ""
            # Show notes if they differ from parent
            notes_html = ""
            child_notes = child.get("notes", "")
            parent_notes = v1_seg.get("notes", "")
            if child_notes and child_notes != parent_notes:
                notes_html = f'<div class="notes-diff"><div class="notes-diff-content" style="color:#aaa">{esc(child_notes)}</div></div>'

            html = render_segment_card(child, "#4A90D9", badges,
                                       transcript_html=child_tx,
                                       notes_html=notes_html,
                                       tl_position=tl_pos)
            add_to_block(block, block_name, child.get("segment_id", ""), html)

    # Added
    for seg in result["added"]:
        block = seg.get("block", 0)
        block_name = seg.get("block_name", f"Block {block}")
        badges = render_badge("ADDED", "#2E7D32")
        tl_pos = v2_positions.get(seg.get("segment_id", ""))
        # Show transcript for added segments
        tx = seg.get("transcript", "")
        tx_html = f'<span class="word-added">{esc(tx)}</span>' if tx else ""
        html = render_segment_card(seg, "#4CAF50", badges,
                                   transcript_html=tx_html, tl_position=tl_pos)
        add_to_block(block, block_name, seg.get("segment_id", ""), html)

    # Removed — show full transcript as cut
    for seg in result["removed"]:
        block = seg.get("block", 0)
        block_name = seg.get("block_name", f"Block {block}")
        badges = render_badge("REMOVED", "#A3282E")
        tx = seg.get("transcript", "")
        tx_html = f'<span class="word-cut">{esc(tx)}</span>' if tx else ""
        html = render_segment_card(seg, "#E34850", badges,
                                   transcript_html=tx_html)
        add_to_block(block, block_name, seg.get("segment_id", ""), html)

    # Render blocks
    if block_items:
        parts.append('<div class="section-title">Segments by Block</div>')
        for block_num in sorted(block_items):
            bi = block_items[block_num]
            block_name = bi["name"]
            items = sorted(bi["items"], key=lambda x: x[0])

            n_changed = sum(1 for _, html in items if 'unchanged' not in html)

            if block_num == 99:
                hex_dark = COLOR_HEX_DARK.get("Red", "#A3282E")
            else:
                hex_dark = "#2a2a4a"

            change_note = f" | {n_changed} changed" if n_changed else ""
            is_open = "open" if n_changed > 0 else ""

            parts.append(f"""
<details {is_open}>
    <summary style="background:{hex_dark};color:#fff;">
        Block {block_num}: {esc(block_name)}
        <span style="font-size:0.75em;font-weight:normal;color:rgba(255,255,255,0.7)">
            ({len(items)} segments{change_note})
        </span>
    </summary>
    <div class="block-content">
""")
            for _, html in items:
                parts.append(html)

            parts.append('    </div>\n</details>')

    # --- Screens diff ---
    if screen_result["matched"] or screen_result["added"] or screen_result["removed"]:
        parts.append('<div class="section-title">Screen Cues</div>')
        parts.append('<table class="screen-table"><thead><tr>'
                     '<th>Status</th><th>ID</th><th>Type</th><th>Segment</th><th>Details</th>'
                     '</tr></thead><tbody>')

        for s1_scr, s2_scr, changes in screen_result["matched"]:
            detail = " | ".join(f"{f}: {esc(old)}&rarr;{esc(new)}" for f, (old, new) in changes.items())
            parts.append(f'<tr><td>{render_badge("MODIFIED", "#9E8A00")}</td>'
                         f'<td>{esc(s2_scr.get("screen_id", ""))}</td>'
                         f'<td>{esc(s2_scr.get("type", ""))}</td>'
                         f'<td>{esc(s2_scr.get("segment_id", ""))}</td>'
                         f'<td>{detail}</td></tr>')

        for s in screen_result["added"]:
            parts.append(f'<tr><td>{render_badge("ADDED", "#2E7D32")}</td>'
                         f'<td>{esc(s.get("screen_id", ""))}</td>'
                         f'<td>{esc(s.get("type", ""))}</td>'
                         f'<td>{esc(s.get("segment_id", ""))}</td>'
                         f'<td>{esc(s.get("title", ""))}</td></tr>')

        for s in screen_result["removed"]:
            parts.append(f'<tr><td>{render_badge("REMOVED", "#A3282E")}</td>'
                         f'<td>{esc(s.get("screen_id", ""))}</td>'
                         f'<td>{esc(s.get("type", ""))}</td>'
                         f'<td>{esc(s.get("segment_id", ""))}</td>'
                         f'<td>{esc(s.get("title", ""))}</td></tr>')

        parts.append('</tbody></table>')

    # Footer
    parts.append(f"""
<div style="margin-top:30px;padding:15px;text-align:center;color:#555;font-size:0.8em;">
    YTAI Brief Diff | {esc(project)} | {datetime.now().strftime('%Y-%m-%d %H:%M')}
</div>
</body></html>""")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="YTAI 05_editing: Diff two assembly brief versions → HTML report")
    parser.add_argument("--v1", required=True, help="Path to v1 brief JSON")
    parser.add_argument("--v2", required=True, help="Path to v2 brief JSON")
    parser.add_argument("--output", default=None, help="Output HTML path (default: auto-named in v2's directory)")
    args = parser.parse_args()

    v1_path = Path(args.v1)
    v2_path = Path(args.v2)

    if not v1_path.exists():
        print(f"Error: v1 file not found: {v1_path}", file=sys.stderr)
        sys.exit(1)
    if not v2_path.exists():
        print(f"Error: v2 file not found: {v2_path}", file=sys.stderr)
        sys.exit(1)

    with open(v1_path) as f:
        v1 = json.load(f)
    with open(v2_path) as f:
        v2 = json.load(f)

    html = generate_diff_html(v1, v2)

    if args.output:
        out_path = Path(args.output)
    else:
        m1 = re.search(r'v(\d+)', v1_path.stem)
        m2 = re.search(r'v(\d+)', v2_path.stem)
        v1_label = f"v{m1.group(1)}" if m1 else "v1"
        v2_label = f"v{m2.group(1)}" if m2 else "v2"
        prefix = v2_path.stem.split("_Assembly")[0] if "_Assembly" in v2_path.stem else v2_path.stem
        out_path = v2_path.parent / f"{prefix}_Assembly_{v1_label}_vs_{v2_label}_diff.html"

    out_path.write_text(html, encoding="utf-8")
    print(f"Diff report: {out_path}")
    print(f"  {len(v1.get('segments', []))} -> {len(v2.get('segments', []))} segments")


if __name__ == "__main__":
    main()
