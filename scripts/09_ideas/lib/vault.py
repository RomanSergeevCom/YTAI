"""
vault.py — Read/write Obsidian markdown files with YAML frontmatter.

Core library for the YTAI Ideas system. All data lives as markdown files
in the Obsidian vault. This module handles parsing and writing them.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

import yaml

VAULT_PATH = Path(os.environ.get("YTAI_VAULT", "~/YTAI_Ideas")).expanduser()


def read_note(path: Path | str) -> dict:
    """
    Read a markdown file with YAML frontmatter.

    Returns:
        {"frontmatter": {...}, "body": "markdown content", "path": Path}
    """
    path = _resolve(path)
    text = path.read_text(encoding="utf-8")

    fm, body = _split_frontmatter(text)
    return {"frontmatter": fm, "body": body, "path": path}


def write_note(path: Path | str, frontmatter: dict, body: str) -> Path:
    """
    Write a markdown file with YAML frontmatter.
    Creates parent directories if needed.

    Returns the absolute path written.
    """
    path = _resolve(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure clean YAML output
    fm_text = yaml.dump(
        frontmatter,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=200,
    )

    content = f"---\n{fm_text}---\n\n{body}"
    path.write_text(content, encoding="utf-8")
    return path


def update_frontmatter(path: Path | str, updates: dict) -> Path:
    """
    Update specific frontmatter fields without changing the body.
    Automatically sets 'updated' to today.
    """
    note = read_note(path)
    fm = note["frontmatter"]
    fm.update(updates)
    fm["updated"] = str(date.today())
    return write_note(note["path"], fm, note["body"])


def find_notes(
    folder: str = "",
    *,
    type: Optional[str] = None,
    channel: Optional[str] = None,
    status: Optional[str] = None,
    **kwargs: Any,
) -> list[dict]:
    """
    Find all markdown notes in a folder, filtered by frontmatter fields.

    Args:
        folder: Subfolder within vault (e.g. "Ideas/YTCR", "Competitors")
        type: Filter by frontmatter 'type' field
        channel: Filter by frontmatter 'channel' field
        status: Filter by frontmatter 'status' field
        **kwargs: Any additional frontmatter field to filter on

    Returns:
        List of {"frontmatter": {...}, "body": "...", "path": Path}
    """
    search_dir = VAULT_PATH / folder if folder else VAULT_PATH
    if not search_dir.is_dir():
        return []

    filters = {}
    if type is not None:
        filters["type"] = type
    if channel is not None:
        filters["channel"] = channel
    if status is not None:
        filters["status"] = status
    filters.update(kwargs)

    results = []
    for md_file in search_dir.rglob("*.md"):
        # Skip templates and dashboards
        rel = md_file.relative_to(VAULT_PATH)
        if str(rel).startswith(("Templates/", "Dashboards/", ".obsidian/")):
            continue

        try:
            note = read_note(md_file)
        except Exception:
            continue

        fm = note["frontmatter"]
        if not fm:
            continue

        # Apply filters
        match = True
        for key, value in filters.items():
            if fm.get(key) != value:
                match = False
                break

        if match:
            results.append(note)

    return results


def next_idea_id(channel_code: str) -> str:
    """
    Scan Ideas/{channel}/ and return the next available ID.
    E.g., if YTCR-001 and YTCR-003 exist, returns "YTCR-004".
    """
    ideas_dir = VAULT_PATH / "Ideas" / channel_code
    if not ideas_dir.is_dir():
        return f"{channel_code}-001"

    pattern = re.compile(rf"^{re.escape(channel_code)}-(\d+)")
    max_num = 0

    for md_file in ideas_dir.glob("*.md"):
        m = pattern.match(md_file.stem)
        if m:
            max_num = max(max_num, int(m.group(1)))

    # Also check frontmatter 'id' fields
    for note in find_notes(f"Ideas/{channel_code}", type="idea"):
        fm_id = note["frontmatter"].get("id", "")
        m = pattern.match(str(fm_id))
        if m:
            max_num = max(max_num, int(m.group(1)))

    return f"{channel_code}-{max_num + 1:03d}"


# ── Internal helpers ────────────────────────────────────────────────


def _resolve(path: Path | str) -> Path:
    """Resolve path relative to vault or as absolute."""
    path = Path(path)
    if not path.is_absolute():
        path = VAULT_PATH / path
    return path


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """
    Split markdown text into YAML frontmatter dict and body string.
    Returns ({}, full_text) if no frontmatter found.
    """
    text = text.lstrip()
    if not text.startswith("---"):
        return {}, text

    # Find closing ---
    end = text.find("---", 3)
    if end == -1:
        return {}, text

    yaml_block = text[3:end].strip()
    body = text[end + 3:].lstrip("\n")

    try:
        fm = yaml.safe_load(yaml_block) or {}
    except yaml.YAMLError:
        fm = {}

    return fm, body
