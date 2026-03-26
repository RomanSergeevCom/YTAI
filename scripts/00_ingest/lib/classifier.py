"""
Project classification: name, type, next available number.
"""

import json
import re
from pathlib import Path

CHANNELS_FILE = Path(__file__).parent.parent / "channels.json"
CODE_RE = re.compile(r'^(YT[A-Z]{2,4})(\d+)_')


def load_channels() -> list:
    """Load channel registry from channels.json."""
    with open(CHANNELS_FILE) as f:
        data = json.load(f)
    return data.get("channels", [])


def validate_channel(channel_code: str) -> bool:
    """Check if channel code exists in registry."""
    channels = load_channels()
    return any(ch["code"] == channel_code for ch in channels)


def _extract_hero_name(folder_name: str) -> str:
    """
    Extract hero name from raw folder name.
    '20250130_Andrey' → 'Andrey'
    'Some_Project_Name' → 'Some_Project_Name'
    """
    # Pattern: YYYYMMDD_Name or YYYY-MM-DD_Name
    m = re.match(r'^\d{4}-?\d{2}-?\d{2}_(.+)$', folder_name)
    if m:
        return m.group(1)
    return folder_name


def _find_next_number(channel_code: str, search_dir: Path) -> int:
    """
    Scan search_dir for existing projects of this channel
    and return the next available number.
    """
    existing_numbers = []
    if search_dir.is_dir():
        for entry in search_dir.iterdir():
            if not entry.is_dir():
                continue
            m = CODE_RE.match(entry.name)
            if m and m.group(1) == channel_code:
                existing_numbers.append(int(m.group(2)))

    if existing_numbers:
        return max(existing_numbers) + 1
    return 1


def classify(channel_code: str, raw_folder: Path,
             total_duration_sec: float, scene_count: int) -> dict:
    """
    Generate project classification.

    Args:
        channel_code: e.g. "YTRF"
        raw_folder: path to raw footage folder
        total_duration_sec: total video duration
        scene_count: number of detected scenes

    Returns dict with:
        - project_name: suggested name like "YTRF02_Andrey"
        - project_type: "Type1_Footage" or "Type2_Production"
        - next_number: int
        - hero_name: str
    """
    hero_name = _extract_hero_name(raw_folder.name)

    # Search parent dir for existing projects of this channel
    search_dir = raw_folder.parent
    next_num = _find_next_number(channel_code, search_dir)

    project_name = f"{channel_code}{next_num:02d}_{hero_name}"

    # Type: long session with multiple scenes = Production
    if total_duration_sec > 1800 and scene_count > 1:  # 30 min
        project_type = "Type2_Production"
    else:
        project_type = "Type1_Footage"

    return {
        "project_name": project_name,
        "project_type": project_type,
        "next_number": next_num,
        "hero_name": hero_name,
    }
