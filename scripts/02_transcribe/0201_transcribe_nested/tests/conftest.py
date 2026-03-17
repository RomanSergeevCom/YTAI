"""Shared pytest fixtures for 0201_transcribe_nested tests.

Provides:
  - fake_nested_project: post-Phase-1 organized project structure for transcription tests
  - sample_transcript_json: a valid {scene}_transcript.json with clips and words_data
"""
import json
from pathlib import Path

import pytest


@pytest.fixture
def fake_nested_project(tmp_path):
    """Create a fake nested project structure with three scene subfolders.

    Mirrors what 0100_organize + 0104_sync_audio_nested produce for a nested project:
      01_Media/Source/Video/{scene}/{clip}.MP4
      01_Media/Source/Transcription/  (empty)

    Returns tmp_path (project root).
    """
    # Scene: volleyball
    volleyball_dir = tmp_path / "01_Media" / "Source" / "Video" / "volleyball"
    volleyball_dir.mkdir(parents=True)
    (volleyball_dir / "C5001.MP4").write_bytes(b"\x00")

    # Scene: apartment
    apartment_dir = tmp_path / "01_Media" / "Source" / "Video" / "apartment"
    apartment_dir.mkdir(parents=True)
    (apartment_dir / "C5040.MP4").write_bytes(b"\x00")

    # Scene: drive_home
    drive_home_dir = tmp_path / "01_Media" / "Source" / "Video" / "drive_home"
    drive_home_dir.mkdir(parents=True)
    (drive_home_dir / "C5300.MP4").write_bytes(b"\x00")

    # Transcription dir (empty)
    (tmp_path / "01_Media" / "Source" / "Transcription").mkdir(parents=True)

    return tmp_path


@pytest.fixture
def sample_transcript_json(tmp_path):
    """Create a valid volleyball_transcript.json with 2 clips and 3 words total.

    Structure matches the transcript.json schema from transcribe_project.py:
      { "project": str, "clips": [{ "clip_id": str, "transcript_segments": [{ "words_data": [...], "speaker": str }] }] }

    Returns path to the written file.
    """
    data = {
        "project": "volleyball",
        "structure": {"work_dir": str(tmp_path)},
        "clips": [
            {
                "clip_id": "C5001",
                "filename": "C5001.MP4",
                "duration": 45.0,
                "offset": 0.0,
                "transcript_segments": [
                    {
                        "speaker": "SPEAKER_00",
                        "words_data": [
                            {"word": "hello", "start": 1.46, "end": 1.82, "duration": 0.36, "confidence": 0.987},
                            {"word": "world", "start": 1.90, "end": 2.30, "duration": 0.40, "confidence": 0.954},
                        ],
                    }
                ],
            },
            {
                "clip_id": "C5002",
                "filename": "C5002.MP4",
                "duration": 30.0,
                "offset": 45.0,
                "transcript_segments": [
                    {
                        "speaker": "SPEAKER_01",
                        "words_data": [
                            {"word": "test", "start": 0.50, "end": 0.80, "duration": 0.30, "confidence": 0.912},
                        ],
                    }
                ],
            },
        ],
    }
    path = tmp_path / "volleyball_transcript.json"
    path.write_text(json.dumps(data, indent=2))
    return path
