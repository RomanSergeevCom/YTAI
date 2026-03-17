"""Unit tests for merge_transcripts module.

Tests cover TRN-03:
  TRN-03: read_scene_words (extract words with scene_id from transcript JSON)
  TRN-03: merge_transcripts (combine scenes into merged_transcript.json)
  TRN-03: merged word fields (scene_id, local timecodes preserved)
  TRN-03: merge gracefully handles missing scene transcript files

TDD RED phase: these tests are written before the implementation exists.
"""
import importlib.util
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Load module under test via importlib (handles digit-prefixed name)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# TRN-03: read_scene_words
# ---------------------------------------------------------------------------

def test_read_scene_words(sample_transcript_json, merge_mod):
    """read_scene_words returns list of word dicts with scene_id tag.

    Given a transcript JSON with 2 clips and 3 words total (hello, world, test),
    read_scene_words("volleyball", path) returns 3 dicts each with
    scene_id="volleyball", word, start, end, duration, confidence, speaker.
    """
    words = merge_mod.read_scene_words(sample_transcript_json, "volleyball")

    assert len(words) == 3

    # Check all required fields present
    for w in words:
        assert "scene_id" in w
        assert "word" in w
        assert "start" in w
        assert "end" in w
        assert "duration" in w
        assert "confidence" in w
        assert "speaker" in w
        assert w["scene_id"] == "volleyball"

    # Check specific word values
    word_texts = [w["word"] for w in words]
    assert "hello" in word_texts
    assert "world" in word_texts
    assert "test" in word_texts

    # Verify first word timecodes are local (match source)
    hello = next(w for w in words if w["word"] == "hello")
    assert hello["start"] == pytest.approx(1.46)
    assert hello["end"] == pytest.approx(1.82)
    assert hello["duration"] == pytest.approx(0.36)
    assert hello["confidence"] == pytest.approx(0.987)
    assert hello["speaker"] == "SPEAKER_00"

    test_word = next(w for w in words if w["word"] == "test")
    assert test_word["speaker"] == "SPEAKER_01"


# ---------------------------------------------------------------------------
# TRN-03: merge_transcripts
# ---------------------------------------------------------------------------

def test_merge_transcripts(tmp_path, merge_mod):
    """merge_transcripts produces merged_transcript.json from two scene transcripts.

    Given volleyball (3 words) and apartment (2 words) transcripts under
    Transcription/, merge_transcripts writes merged_transcript.json with
    version="1.0", scenes sorted alphabetically, and 5 total word entries.
    """
    tr_dir = tmp_path / "01_Media" / "Source" / "Transcription"
    tr_dir.mkdir(parents=True)

    # volleyball: 3 words
    volleyball_data = {
        "project": "volleyball",
        "clips": [
            {
                "clip_id": "C5001",
                "transcript_segments": [
                    {
                        "speaker": "SPEAKER_00",
                        "words_data": [
                            {"word": "one", "start": 0.1, "end": 0.5, "duration": 0.4, "confidence": 0.9},
                            {"word": "two", "start": 0.6, "end": 1.0, "duration": 0.4, "confidence": 0.85},
                            {"word": "three", "start": 1.1, "end": 1.5, "duration": 0.4, "confidence": 0.8},
                        ],
                    }
                ],
            }
        ],
    }
    (tr_dir / "volleyball_transcript.json").write_text(json.dumps(volleyball_data))

    # apartment: 2 words
    apartment_data = {
        "project": "apartment",
        "clips": [
            {
                "clip_id": "C5040",
                "transcript_segments": [
                    {
                        "speaker": "SPEAKER_01",
                        "words_data": [
                            {"word": "hello", "start": 2.0, "end": 2.4, "duration": 0.4, "confidence": 0.95},
                            {"word": "there", "start": 2.5, "end": 3.0, "duration": 0.5, "confidence": 0.92},
                        ],
                    }
                ],
            }
        ],
    }
    (tr_dir / "apartment_transcript.json").write_text(json.dumps(apartment_data))

    result_path = merge_mod.merge_transcripts(tmp_path, ["volleyball", "apartment"])

    # Output file must exist at canonical path
    expected = tr_dir / "merged_transcript.json"
    assert result_path == expected
    assert expected.exists()

    with open(expected) as f:
        merged = json.load(f)

    assert merged["version"] == "1.0"
    assert merged["project"] == tmp_path.name
    # scenes sorted alphabetically
    assert merged["scenes"] == ["apartment", "volleyball"]
    # total words = 3 + 2
    assert len(merged["words"]) == 5


# ---------------------------------------------------------------------------
# TRN-03: merged word fields
# ---------------------------------------------------------------------------

def test_merged_word_fields(tmp_path, merge_mod):
    """Each word in merged output has exactly the required fields with local timecodes.

    After merge_transcripts, every word dict must have: scene_id, word, start,
    end, duration, confidence, speaker. start/end must be local (same as source),
    not summed/global values.
    """
    tr_dir = tmp_path / "01_Media" / "Source" / "Transcription"
    tr_dir.mkdir(parents=True)

    data = {
        "project": "volleyball",
        "clips": [
            {
                "clip_id": "C5001",
                "transcript_segments": [
                    {
                        "speaker": "SPEAKER_00",
                        "words_data": [
                            {"word": "check", "start": 5.0, "end": 5.4, "duration": 0.4, "confidence": 0.99},
                        ],
                    }
                ],
            }
        ],
    }
    (tr_dir / "volleyball_transcript.json").write_text(json.dumps(data))

    merge_mod.merge_transcripts(tmp_path, ["volleyball"])

    with open(tr_dir / "merged_transcript.json") as f:
        merged = json.load(f)

    assert len(merged["words"]) == 1
    word = merged["words"][0]

    required_keys = {"scene_id", "word", "start", "end", "duration", "confidence", "speaker"}
    assert set(word.keys()) == required_keys

    # Local timecodes preserved (not global)
    assert word["start"] == pytest.approx(5.0)
    assert word["end"] == pytest.approx(5.4)
    assert word["scene_id"] == "volleyball"


# ---------------------------------------------------------------------------
# TRN-03: merge handles missing scene gracefully
# ---------------------------------------------------------------------------

def test_merge_missing_scene(tmp_path, merge_mod):
    """merge_transcripts skips missing scene transcripts without raising an error.

    If one scene transcript file is missing, the function processes the existing
    ones and produces a valid merged_transcript.json with only the available words.
    """
    tr_dir = tmp_path / "01_Media" / "Source" / "Transcription"
    tr_dir.mkdir(parents=True)

    # Only volleyball transcript exists; desert_drive does not
    volleyball_data = {
        "project": "volleyball",
        "clips": [
            {
                "clip_id": "C5001",
                "transcript_segments": [
                    {
                        "speaker": "SPEAKER_00",
                        "words_data": [
                            {"word": "present", "start": 0.1, "end": 0.5, "duration": 0.4, "confidence": 0.9},
                        ],
                    }
                ],
            }
        ],
    }
    (tr_dir / "volleyball_transcript.json").write_text(json.dumps(volleyball_data))

    # Should NOT raise even though desert_drive_transcript.json is missing
    result_path = merge_mod.merge_transcripts(tmp_path, ["volleyball", "desert_drive"])

    assert result_path.exists()

    with open(result_path) as f:
        merged = json.load(f)

    # Only volleyball words present
    assert len(merged["words"]) == 1
    assert merged["words"][0]["scene_id"] == "volleyball"
