"""Load review_analysis.json and review_transcript.json with a thin sanity layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def load_analysis(path: str | Path) -> dict:
    """Return the raw analysis dict. Includes synopsis, story_arc, themes,
    key_strengths, critical_issues, chapters[]."""
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data


def load_transcript(path: str | Path) -> dict:
    """Return Whisper transcript with segments[] containing per-word timestamps."""
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data


def keep_chapters(analysis: dict) -> list[dict]:
    """Filter chapters[] to verdict==KEEP only. Order preserved."""
    chapters = analysis.get("chapters") or []
    return [c for c in chapters if (c.get("verdict") or "").upper() == "KEEP"]


def fix_chapters(analysis: dict) -> list[dict]:
    return [c for c in (analysis.get("chapters") or []) if (c.get("verdict") or "").upper() == "FIX"]


def format_timestamp(seconds: float) -> str:
    """Seconds → M:SS (or H:MM:SS if >1h)."""
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def chapter_summary_lines(chapters: list[dict]) -> list[str]:
    """Render chapters[] as 'M:SS Title — summary' strings."""
    lines = []
    for c in chapters:
        tc_in = c.get("tc_in") or c.get("start") or 0
        # tc may be "M:SS.sss" string or float seconds
        if isinstance(tc_in, str):
            ts = tc_in.split(".")[0]
            # ensure M:SS, not 0:0:5
            if ts.count(":") == 2 and ts.startswith("0:"):
                ts = ts[2:]
        else:
            ts = format_timestamp(float(tc_in))
        title = c.get("title") or "Chapter"
        summary = c.get("summary") or ""
        lines.append(f"{ts} {title} — {summary}".strip())
    return lines


def key_quotes(analysis: dict) -> list[dict]:
    """Pull key_quote from each KEEP chapter."""
    out = []
    for c in keep_chapters(analysis):
        kq = c.get("key_quote")
        if kq:
            out.append({"tc_in": c.get("tc_in"), "title": c.get("title"), "quote": kq})
    return out


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("analysis_json")
    args = parser.parse_args()
    a = load_analysis(args.analysis_json)
    keep = keep_chapters(a)
    print(f"Analysis: {Path(args.analysis_json).name}")
    print(f"  synopsis: {a.get('synopsis', '<missing>')[:100]}")
    print(f"  chapters total: {len(a.get('chapters') or [])}")
    print(f"  chapters KEEP: {len(keep)}")
    for line in chapter_summary_lines(keep):
        print(f"    {line[:120]}")
