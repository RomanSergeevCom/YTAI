"""Load channel DNA from YTs/{CHANNEL}/{CHANNEL}.md.

Returns the raw markdown plus parsed sections (Overview, Target Audience,
Style & Tone, Content Pillars, etc.) so callers can pluck what they need.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

YTAI_ROOT = Path.home() / "YTAI"


class DNANotFoundError(FileNotFoundError):
    pass


def dna_path(channel_code: str) -> Path:
    return YTAI_ROOT / "YTs" / channel_code / f"{channel_code}.md"


def load(channel_code: str) -> dict:
    """Return {"raw": str, "sections": {heading: body}, "path": str}."""
    path = dna_path(channel_code)
    if not path.exists():
        raise DNANotFoundError(f"no DNA for channel {channel_code} at {path}")

    raw = path.read_text(encoding="utf-8")
    sections = _split_h2(raw)

    return {
        "channel_code": channel_code,
        "path": str(path),
        "raw": raw,
        "sections": sections,
    }


def _split_h2(md: str) -> dict[str, str]:
    """Split markdown by ## headings."""
    out: dict[str, str] = {}
    current_heading: Optional[str] = None
    current_body: list[str] = []

    for line in md.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if current_heading is not None:
                out[current_heading] = "\n".join(current_body).strip()
            current_heading = m.group(1).strip()
            current_body = []
        elif current_heading is not None:
            current_body.append(line)

    if current_heading is not None:
        out[current_heading] = "\n".join(current_body).strip()

    return out


def section(dna: dict, heading: str) -> Optional[str]:
    """Look up a section by exact heading text."""
    return dna.get("sections", {}).get(heading)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("channel_code")
    args = parser.parse_args()

    dna = load(args.channel_code)
    print(json.dumps(
        {"path": dna["path"], "sections": list(dna["sections"].keys())},
        indent=2, ensure_ascii=False,
    ))
