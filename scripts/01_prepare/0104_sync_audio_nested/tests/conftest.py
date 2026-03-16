"""Shared pytest fixtures for 0104_sync_audio_nested tests.

Provides:
  - fake_nested_organized: post-Phase-1 organized project structure
  - synthetic_cam_audio: 5-second 440Hz sine wave at 8000Hz
  - synthetic_tx_with_cam_embedded: 30-second TX array with camera signal at offset 10s
  - synthetic_tx_noise_only: 30-second pure noise array
"""
import sys
from pathlib import Path

import numpy as np
import pytest

# Allow importing 0104_sync_audio_nested directly (module name starts with digit)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def fake_nested_organized(tmp_path):
    """Create a fake post-Phase-1 organized project structure.

    Mirrors what 0100_organize produces for a nested project:
      01_Media/Source/Video/{scene}/{clip}.MP4
      01_Media/Source/Audio/          (empty)
      01_Media/Source/Transcription/per_clip/  (empty)
      01_Media/Source/Setup/          (empty)
      99_Pipeline/DJI_Audio/TX*.wav   (stub files)
    """
    # Scene: volleyball
    volleyball_dir = tmp_path / "01_Media" / "Source" / "Video" / "volleyball"
    volleyball_dir.mkdir(parents=True)
    (volleyball_dir / "C5210.MP4").write_bytes(b"\x00")
    (volleyball_dir / "C5211.MP4").write_bytes(b"\x00")

    # Scene: apartment
    apartment_dir = tmp_path / "01_Media" / "Source" / "Video" / "apartment"
    apartment_dir.mkdir(parents=True)
    (apartment_dir / "C5089.MP4").write_bytes(b"\x00")

    # Scene: al_qudra_lake with GoPro subfolder
    al_qudra_dir = tmp_path / "01_Media" / "Source" / "Video" / "al_qudra_lake"
    al_qudra_dir.mkdir(parents=True)
    (al_qudra_dir / "C5100.MP4").write_bytes(b"\x00")
    gopro_dir = al_qudra_dir / "100GOPRO"
    gopro_dir.mkdir()
    (gopro_dir / "GX010001.MP4").write_bytes(b"\x00")

    # Audio (empty dir)
    (tmp_path / "01_Media" / "Source" / "Audio").mkdir(parents=True)

    # Transcription per_clip (empty dir)
    (tmp_path / "01_Media" / "Source" / "Transcription" / "per_clip").mkdir(parents=True)

    # Setup (empty dir)
    (tmp_path / "01_Media" / "Source" / "Setup").mkdir(parents=True)

    # DJI Audio TX WAV stubs
    dji_dir = tmp_path / "99_Pipeline" / "DJI_Audio"
    dji_dir.mkdir(parents=True)
    (dji_dir / "TX01_MIC001.wav").write_bytes(b"\x00")
    (dji_dir / "TX02_MIC024.wav").write_bytes(b"\x00")
    (dji_dir / "TX02_MIC033.wav").write_bytes(b"\x00")

    return tmp_path


@pytest.fixture
def synthetic_cam_audio():
    """Return a 5-second 440Hz sine wave as np.float32 array at 8000Hz.

    This represents camera audio that will be embedded in TX recordings for
    correlation testing.
    """
    sr = 8000
    t = np.linspace(0, 5.0, sr * 5, endpoint=False)
    return np.sin(2 * np.pi * 440 * t).astype(np.float32)


@pytest.fixture
def synthetic_tx_with_cam_embedded(synthetic_cam_audio):
    """Return (tx_array, embed_offset_sec) for a 30-second TX recording.

    The camera sine signal is embedded at offset 10.0 seconds. The rest of the
    array is low-amplitude noise (std ~0.01).
    """
    sr = 8000
    duration = 30
    rng = np.random.RandomState(42)
    tx = (rng.randn(sr * duration) * 0.01).astype(np.float32)

    embed_offset_sec = 10.0
    embed_start = int(embed_offset_sec * sr)
    tx[embed_start: embed_start + len(synthetic_cam_audio)] += synthetic_cam_audio

    return tx, embed_offset_sec


@pytest.fixture
def synthetic_tx_noise_only():
    """Return a 30-second array of pure random noise at 8000Hz.

    No camera signal embedded. Used to test that find_best_tx_candidate
    correctly rejects non-matching TX files.
    """
    sr = 8000
    return (np.random.RandomState(99).randn(30 * sr) * 0.01).astype(np.float32)
