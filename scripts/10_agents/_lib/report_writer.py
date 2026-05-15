"""Unified {agent}_report.json schema for Draper / Sorkin / Seldon.

Writing the report is the final step of every agent run. RYA-бот (the central
producer) can then scan project folders for *_report.json to build a timeline.

Schema v1.0:
  {
    "agent": "draper" | "sorkin" | "seldon",
    "version": "1.0",
    "project_code": "YTCR01",
    "channel_code": "YTCR",
    "timestamp": "ISO-8601 UTC",
    "inputs": { "review_analysis_sha256": "...", "dna_sha256": "..." },
    "artifacts": { "titles": "path", ... },
    "summary": { "top_title": "...", ... },
    "warnings": [ ... ]
  }
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "1.0"


def sha256(path: str | Path) -> str:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def write(
    *,
    agent: str,
    project_code: str,
    channel_code: str,
    inputs: dict[str, str | None],
    artifacts: dict[str, str | None],
    summary: dict,
    warnings: list[str] | None = None,
    out_path: str | Path,
) -> Path:
    """Write report. inputs values are paths; we hash them. artifacts are paths
    as-strings (or None if not produced). Returns out_path as Path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    hashed_inputs = {
        f"{key}_sha256": sha256(value) if value else ""
        for key, value in inputs.items()
    }
    hashed_inputs["paths"] = {k: str(v) if v else None for k, v in inputs.items()}

    report = {
        "agent": agent,
        "version": SCHEMA_VERSION,
        "project_code": project_code,
        "channel_code": channel_code,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": hashed_inputs,
        "artifacts": {k: str(v) if v else None for k, v in artifacts.items()},
        "summary": summary,
        "warnings": warnings or [],
    }

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return out_path


def read(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)
