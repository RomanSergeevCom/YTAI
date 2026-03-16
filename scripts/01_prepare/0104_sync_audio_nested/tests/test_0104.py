"""Unit tests for 0104_sync_audio_nested core functions.

Tests cover AUD-01 through AUD-06:
  AUD-01: detect_scenes (scene discovery)
  AUD-02: extract_clip_audio (per-clip WAV extraction)
  AUD-03: build_scene_concat (concat per-clip WAVs into scene audio)
  AUD-04: find_best_tx_candidate (cross-correlation candidate selection)
  AUD-05: trim_tx_to_clip (trim TX WAV to clip duration at offset)
  AUD-06: residual_to_frames (convert sync residual seconds to frame delta)

TDD RED phase: these tests are written before the implementation exists.
"""
import importlib.util
import unittest.mock
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Load module under test via importlib (handles digit-prefixed name)
# ---------------------------------------------------------------------------
_MOD_PATH = Path(__file__).resolve().parent.parent / "0104_sync_audio_nested.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location("_sync_nested", _MOD_PATH)
    _mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_mod)
    return _mod


@pytest.fixture(scope="module")
def mod():
    """Load the module under test. Fails with ImportError if not yet created."""
    return _load_mod()


# ---------------------------------------------------------------------------
# AUD-01: detect_scenes
# ---------------------------------------------------------------------------

def test_detect_scenes(fake_nested_organized, mod):
    """detect_scenes returns sorted list of scene directory Paths.

    Given the fake organized structure with volleyball, apartment, and
    al_qudra_lake scenes, should detect 3 scenes without requiring numeric
    prefix.
    """
    project = fake_nested_organized
    scenes = mod.detect_scenes(project)

    assert len(scenes) == 3
    scene_names = [s.name for s in scenes]
    assert "volleyball" in scene_names
    assert "apartment" in scene_names
    assert "al_qudra_lake" in scene_names
    # Should be sorted
    assert scenes == sorted(scenes, key=lambda p: p.name)
    # All should be Path objects
    for s in scenes:
        assert isinstance(s, Path)
        assert s.is_dir()


# ---------------------------------------------------------------------------
# AUD-02: extract_clip_audio
# ---------------------------------------------------------------------------

def test_extract_clip_audio_path(fake_nested_organized, mod):
    """extract_clip_audio writes to correct path under per_clip/{scene}/{clip}/.

    The output path should be:
      Transcription/per_clip/{scene_name}/{clip_stem}/{clip_stem}_AUDIO.wav
    Mock subprocess.run to avoid actual ffmpeg calls.
    """
    project = fake_nested_organized
    clip_path = project / "01_Media" / "Source" / "Video" / "volleyball" / "C5210.MP4"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        out_path = mod.extract_clip_audio(clip_path, project, "volleyball")

    expected = (
        project / "01_Media" / "Source" / "Transcription"
        / "per_clip" / "volleyball" / "C5210" / "C5210_AUDIO.wav"
    )
    assert out_path == expected
    # Parent dir should exist
    assert expected.parent.exists()
    # ffmpeg was called
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "ffmpeg" in cmd[0]
    assert str(clip_path) in cmd
    assert str(out_path) in cmd


# ---------------------------------------------------------------------------
# AUD-03: build_scene_concat
# ---------------------------------------------------------------------------

def test_build_scene_concat(fake_nested_organized, mod):
    """build_scene_concat concatenates per-clip WAVs into scene FULL_AUDIO.wav.

    Given 3 per-clip WAV paths for scene "volleyball", should call ffmpeg
    concat and write to {scene}_FULL_AUDIO.wav. Mock subprocess.run.
    """
    project = fake_nested_organized
    per_clip_base = (
        project / "01_Media" / "Source" / "Transcription" / "per_clip"
    )

    # Create stub per-clip WAV files
    clip_audio_paths = []
    for clip in ["C5209", "C5210", "C5211"]:
        clip_dir = per_clip_base / "volleyball" / clip
        clip_dir.mkdir(parents=True, exist_ok=True)
        wav = clip_dir / f"{clip}_AUDIO.wav"
        wav.write_bytes(b"\x00")
        clip_audio_paths.append(wav)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        out_path = mod.build_scene_concat(clip_audio_paths, "volleyball", project)

    expected = per_clip_base / "volleyball" / "volleyball_FULL_AUDIO.wav"
    assert out_path == expected
    # ffmpeg was called
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "ffmpeg" in cmd[0]
    assert str(out_path) in cmd


# ---------------------------------------------------------------------------
# AUD-04: find_best_tx_candidate (pure numpy/scipy, no mocks)
# ---------------------------------------------------------------------------

def test_find_best_tx_candidate(synthetic_cam_audio, synthetic_tx_with_cam_embedded,
                                 synthetic_tx_noise_only, mod):
    """find_best_tx_candidate returns correct TX path with correct offset.

    Given a dict with one TX containing the camera signal at offset 10.0s and
    one TX with pure noise, should select the signal TX with offset within
    0.05s of 10.0 and confidence > 3.0.
    """
    tx_with_signal, embed_offset = synthetic_tx_with_cam_embedded

    tx_cache = {
        "/fake/tx1.wav": tx_with_signal,
        "/fake/tx2.wav": synthetic_tx_noise_only,
    }

    best_path, best_offset, best_conf = mod.find_best_tx_candidate(
        synthetic_cam_audio, tx_cache
    )

    assert best_path == "/fake/tx1.wav", f"Expected tx1.wav, got {best_path}"
    assert abs(best_offset - embed_offset) <= 0.05, (
        f"Offset {best_offset:.3f}s not within 0.05s of {embed_offset}s"
    )
    assert best_conf > 3.0, f"Confidence {best_conf:.1f} should be > 3.0"


def test_find_best_tx_candidate_picks_correct_wav(synthetic_cam_audio,
                                                   synthetic_tx_noise_only, mod):
    """find_best_tx_candidate selects the one TX containing the camera signal.

    Given 3 TX WAVs where only one contains the camera signal, function selects
    the correct one.
    """
    sr = 8000
    duration = 30

    # TX with camera signal embedded at offset 15.0s
    rng = np.random.RandomState(7)
    tx_with_signal = (rng.randn(sr * duration) * 0.01).astype(np.float32)
    embed_start = int(15.0 * sr)
    tx_with_signal[embed_start: embed_start + len(synthetic_cam_audio)] += synthetic_cam_audio

    noise1 = (np.random.RandomState(11).randn(sr * duration) * 0.01).astype(np.float32)
    noise2 = (np.random.RandomState(22).randn(sr * duration) * 0.01).astype(np.float32)

    tx_cache = {
        "/fake/tx_noise_a.wav": noise1,
        "/fake/tx_signal.wav": tx_with_signal,
        "/fake/tx_noise_b.wav": noise2,
    }

    best_path, best_offset, best_conf = mod.find_best_tx_candidate(
        synthetic_cam_audio, tx_cache
    )

    assert best_path == "/fake/tx_signal.wav", (
        f"Expected tx_signal.wav but got {best_path}"
    )
    assert abs(best_offset - 15.0) <= 0.05, (
        f"Offset {best_offset:.3f}s not within 0.05s of 15.0s"
    )


# ---------------------------------------------------------------------------
# AUD-05: trim_tx_to_clip
# ---------------------------------------------------------------------------

def test_trim_tx_to_clip(fake_nested_organized, mod):
    """trim_tx_to_clip builds ffmpeg command with -ss and -t flags.

    Given tx_path, offset_sec=10.0, clip_duration=5.0, the function should
    run ffmpeg with -ss 10.0 -t 5.0. Mock subprocess.run.
    """
    project = fake_nested_organized
    tx_path = project / "99_Pipeline" / "DJI_Audio" / "TX01_MIC001.wav"
    output_path = (
        project / "01_Media" / "Source" / "Transcription"
        / "per_clip" / "volleyball" / "C5210" / "C5210_TX01.wav"
    )

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = mod.trim_tx_to_clip(tx_path, 10.0, 5.0, output_path)

    assert result == output_path
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "ffmpeg" in cmd[0]

    cmd_str = " ".join(str(c) for c in cmd)
    assert "-ss" in cmd_str
    assert "10.0" in cmd_str or "10.000000" in cmd_str
    assert "-t" in cmd_str
    assert "5.0" in cmd_str or "5.000000" in cmd_str


# ---------------------------------------------------------------------------
# AUD-06: residual_to_frames
# ---------------------------------------------------------------------------

def test_residual_to_frames_25fps(mod):
    """residual_to_frames(0.025, 25.0) returns 0.625 frames."""
    result = mod.residual_to_frames(0.025, 25.0)
    assert result == pytest.approx(0.625)


def test_residual_to_frames_30fps(mod):
    """residual_to_frames(0.033, 30.0) returns 0.99 frames."""
    result = mod.residual_to_frames(0.033, 30.0)
    assert result == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# preload_tx_cache
# ---------------------------------------------------------------------------

def test_preload_tx_cache(fake_nested_organized, mod):
    """preload_tx_cache returns dict with numpy float32 arrays for each WAV.

    Given a DJI dir with TX01 and TX02 files, with tx_prefix="TX01", should
    return dict with only TX01 entries, each a numpy float32 array.
    Mock extract_mono_8k from the module.
    """
    project = fake_nested_organized
    dji_dir = project / "99_Pipeline" / "DJI_Audio"

    wav1 = dji_dir / "TX01_MIC001.wav"

    fake_audio_1 = np.zeros(8000 * 10, dtype=np.float32)

    with patch.object(mod, "extract_mono_8k") as mock_extract:
        mock_extract.return_value = fake_audio_1
        cache = mod.preload_tx_cache(dji_dir, "TX01")

    # Only TX01 files should be loaded (tx_prefix="TX01")
    assert len(cache) == 1
    key = str(wav1)
    assert key in cache
    arr = cache[key]
    assert isinstance(arr, np.ndarray)
    assert arr.dtype == np.float32


# ---------------------------------------------------------------------------
# AUD-07: generate_ingest_json
# ---------------------------------------------------------------------------

def test_generate_ingest_json(tmp_path, mod):
    """generate_ingest_json writes per-scene ingest.json with A1/A2/A3 tracks.

    Given a list of clip_results with tx01 and tx02 paths, should write
    Setup/{scene}_ingest.json with correct structure.
    """
    import json

    # Create the Setup dir (would exist in real projects)
    (tmp_path / "01_Media" / "Source" / "Setup").mkdir(parents=True)

    clip_results = [
        {
            "clip_id": "C5089",
            "clip_path": "01_Media/Source/Video/volleyball/C5089.MP4",
            "duration_sec": 4.5,
            "fps": 25.0,
            "tx01_path": "01_Media/Source/Audio/C5089_TX01.wav",
            "tx01_delta_frames": 0.3,
            "tx02_path": "01_Media/Source/Audio/C5089_TX02.wav",
            "tx02_delta_frames": 0.5,
        }
    ]

    out_path = mod.generate_ingest_json("volleyball", clip_results, tmp_path)

    expected_path = tmp_path / "01_Media" / "Source" / "Setup" / "volleyball_ingest.json"
    assert out_path == expected_path
    assert expected_path.exists()

    with open(expected_path) as f:
        data = json.load(f)

    assert data["scene"] == "volleyball"
    assert len(data["clips"]) == 1
    clip = data["clips"][0]
    assert clip["clip_id"] == "C5089"
    assert clip["duration_sec"] == 4.5
    assert clip["fps"] == 25.0
    assert clip["tracks"]["A1"]["type"] == "camera_embed"
    assert clip["tracks"]["A2"]["type"] == "TX01_SYNC"
    assert clip["tracks"]["A2"]["sync_delta_frames"] == 0.3
    assert clip["tracks"]["A3"]["type"] == "TX02_SYNC"
    assert clip["tracks"]["A3"]["sync_delta_frames"] == 0.5


def test_generate_ingest_json_low_conf(tmp_path, mod):
    """generate_ingest_json marks LOW_CONF when tx01_path is None.

    When tx01_path is None (low confidence), A2 track should have
    type=LOW_CONF and path=null.
    """
    import json

    (tmp_path / "01_Media" / "Source" / "Setup").mkdir(parents=True)

    clip_results = [
        {
            "clip_id": "C5089",
            "clip_path": "01_Media/Source/Video/volleyball/C5089.MP4",
            "duration_sec": 4.5,
            "fps": 25.0,
            "tx01_path": None,
            "tx01_delta_frames": None,
            "tx02_path": "01_Media/Source/Audio/C5089_TX02.wav",
            "tx02_delta_frames": 0.5,
        }
    ]

    out_path = mod.generate_ingest_json("volleyball", clip_results, tmp_path)

    with open(out_path) as f:
        data = json.load(f)

    assert data["clips"][0]["tracks"]["A2"]["type"] == "LOW_CONF"
    assert data["clips"][0]["tracks"]["A2"]["path"] is None
