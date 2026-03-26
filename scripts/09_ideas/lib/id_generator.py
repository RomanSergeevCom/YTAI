"""
id_generator.py — Generate sequential IDs for ideas and other entities.
"""

from __future__ import annotations

from .vault import next_idea_id


def generate_idea_id(channel_code: str) -> str:
    """Generate the next idea ID for a channel. E.g., YTCR-004."""
    return next_idea_id(channel_code)
