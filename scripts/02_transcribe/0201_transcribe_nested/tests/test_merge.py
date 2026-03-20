"""Unit tests for merge_transcripts module.

Tests cover:
  - merge_transcripts: combines per-scene transcript JSONs into standard pipeline format
  - merged output has clips[].segments[] with scene field
  - stats are aggregated, speakers merged
  - missing scene files handled gracefully
"""
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def merge_mod():
    """Load the merge_transcripts module under test."""
    spec = importlib.util.spec_from_file_location(
        "merge_transcripts",
        Path(__file__).resolve().parent.parent / "merge_transcripts.py",
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _make_scene_transcript(scene_name, clips, language="ru", speakers=None):
    """Build a minimal per-scene transcript JSON matching transcribe_project.py output."""
    if speakers is None:
        speakers = {"SPEAKER_00": {"id": "sp0", "name": "Speaker 1"}}
    total_segs = sum(len(c.get("segments", [])) for c in clips)
    total_words = sum(
        len(s.get("text", "").split())
        for c in clips for s in c.get("segments", [])
    )
    total_dur = sum(c.get("duration", 0) for c in clips)
    return {
        "version": "3.0",
        "project": scene_name,
        "language": language,
        "speakers": speakers,
        "stats": {
            "total_duration": total_dur,
            "total_words": total_words,
            "total_segments": total_segs,
            "num_speakers": len(speakers),
            "avg_confidence": 0.85,
            "low_confidence_segments": 0,
        },
        "structure": {"transcription_dir": f"{scene_name}_transcription"},
        "clips": clips,
    }


def test_merge_produces_clips_with_segments(tmp_path, merge_mod):
    """Merged transcript has clips[] with segments[], not flat words[]."""
    tr_dir = tmp_path / "01_Media" / "Source" / "Transcription"
    tr_dir.mkdir(parents=True)

    volleyball = _make_scene_transcript("volleyball", [
        {
            "clip_id": "C5001", "filename": "C5001.MP4", "duration": 45.0, "offset": 0.0,
            "media": {"width": 3840, "height": 2160, "fps": 25.0},
            "segments": [
                {"id": 0, "start": 1.0, "end": 3.0, "text": "hello world",
                 "speaker": "SPEAKER_00", "confidence": 0.9, "low_confidence": False,
                 "words_data": [{"word": "hello", "start": 1.0, "end": 1.5},
                                {"word": "world", "start": 1.5, "end": 3.0}]},
            ],
        },
    ])
    (tr_dir / "volleyball_transcript.json").write_text(json.dumps(volleyball))

    apartment = _make_scene_transcript("apartment", [
        {
            "clip_id": "C5040", "filename": "C5040.MP4", "duration": 30.0, "offset": 0.0,
            "media": {"width": 3840, "height": 2160, "fps": 25.0},
            "segments": [
                {"id": 0, "start": 0.0, "end": 2.0, "text": "test phrase",
                 "speaker": "SPEAKER_00", "confidence": 0.8, "low_confidence": False,
                 "words_data": [{"word": "test", "start": 0.0, "end": 1.0},
                                {"word": "phrase", "start": 1.0, "end": 2.0}]},
            ],
        },
    ], language="en")
    (tr_dir / "apartment_transcript.json").write_text(json.dumps(apartment))

    result = merge_mod.merge_transcripts(tmp_path, ["volleyball", "apartment"])

    with open(result) as f:
        merged = json.load(f)

    # Standard pipeline format
    assert merged["version"] == "3.0"
    assert "clips" in merged
    assert "words" not in merged  # NOT word-level
    assert len(merged["clips"]) == 2

    # Each clip has scene field and segments
    for clip in merged["clips"]:
        assert "scene" in clip
        assert "segments" in clip
        assert len(clip["segments"]) > 0

    # Scenes are correct
    scenes = [c["scene"] for c in merged["clips"]]
    assert "apartment" in scenes
    assert "volleyball" in scenes


def test_merge_aggregates_stats(tmp_path, merge_mod):
    """Stats are aggregated across scenes."""
    tr_dir = tmp_path / "01_Media" / "Source" / "Transcription"
    tr_dir.mkdir(parents=True)

    scene_a = _make_scene_transcript("scene_a", [
        {"clip_id": "A1", "filename": "A1.MP4", "duration": 60.0, "offset": 0.0,
         "media": {}, "segments": [
             {"id": 0, "start": 0.0, "end": 5.0, "text": "one two three",
              "speaker": "SPEAKER_00", "confidence": 0.9, "low_confidence": False,
              "words_data": []}
         ]},
    ])
    (tr_dir / "scene_a_transcript.json").write_text(json.dumps(scene_a))

    scene_b = _make_scene_transcript("scene_b", [
        {"clip_id": "B1", "filename": "B1.MP4", "duration": 40.0, "offset": 0.0,
         "media": {}, "segments": [
             {"id": 0, "start": 0.0, "end": 3.0, "text": "four five",
              "speaker": "SPEAKER_00", "confidence": 0.7, "low_confidence": False,
              "words_data": []}
         ]},
    ])
    (tr_dir / "scene_b_transcript.json").write_text(json.dumps(scene_b))

    result = merge_mod.merge_transcripts(tmp_path, ["scene_a", "scene_b"])

    with open(result) as f:
        merged = json.load(f)

    assert merged["stats"]["total_duration"] == 100.0  # 60 + 40
    assert merged["stats"]["total_segments"] == 2  # 1 + 1
    assert merged["stats"]["num_speakers"] == 1


def test_merge_skips_missing_scene(tmp_path, merge_mod):
    """Missing scene transcript files are silently skipped."""
    tr_dir = tmp_path / "01_Media" / "Source" / "Transcription"
    tr_dir.mkdir(parents=True)

    scene = _make_scene_transcript("existing", [
        {"clip_id": "E1", "filename": "E1.MP4", "duration": 10.0, "offset": 0.0,
         "media": {}, "segments": [
             {"id": 0, "start": 0.0, "end": 2.0, "text": "present",
              "speaker": "SPEAKER_00", "confidence": 0.9, "low_confidence": False,
              "words_data": []}
         ]},
    ])
    (tr_dir / "existing_transcript.json").write_text(json.dumps(scene))

    # "missing" scene has no file — should not raise
    result = merge_mod.merge_transcripts(tmp_path, ["existing", "missing"])

    with open(result) as f:
        merged = json.load(f)

    assert len(merged["clips"]) == 1
    assert merged["clips"][0]["scene"] == "existing"


def test_merge_output_filename(tmp_path, merge_mod):
    """Output file is named {project.name}_transcript.json."""
    tr_dir = tmp_path / "01_Media" / "Source" / "Transcription"
    tr_dir.mkdir(parents=True)

    scene = _make_scene_transcript("s1", [
        {"clip_id": "X1", "filename": "X1.MP4", "duration": 5.0, "offset": 0.0,
         "media": {}, "segments": []},
    ])
    (tr_dir / "s1_transcript.json").write_text(json.dumps(scene))

    result = merge_mod.merge_transcripts(tmp_path, ["s1"])

    assert result.name == f"{tmp_path.name}_transcript.json"
    assert result.exists()
