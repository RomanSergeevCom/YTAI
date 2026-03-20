"""Shared pytest fixtures for 0100_organize tests.

Provides fake project trees that replicate the reference nested project
structure (YTCR01_Arty_Dzis) and a minimal flat project.
"""
import sys
from pathlib import Path

import pytest

# Allow importing 0100_organize directly (module name starts with digit)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def fake_nested_project(tmp_path):
    """Create a fake nested (multi-scene) project with TX folders and scenes.

    Structure mirrors YTCR01_Arty_Dzis:
      TX01/TX01_MIC001_20260228_102211_orig.wav
      TX02/TX02_MIC024_20260228_100209_orig.wav
      TX02_2/TX02_MIC033_20260302_162711_orig.wav
      volleyball/C5210.MP4
      volleyball/C5211.MP4
      volleyball/C5089M01.XML  (sidecar)
      apartment/C5089.MP4
      apartment/C5089M01.XML   (sidecar for C5089)
      al_qudra_lake/C5100.MP4
      al_qudra_lake/100GOPRO/GX010001.MP4
    """
    # TX folders with DJI WAV files
    (tmp_path / "TX01").mkdir()
    (tmp_path / "TX01" / "TX01_MIC001_20260228_102211_orig.wav").touch()

    (tmp_path / "TX02").mkdir()
    (tmp_path / "TX02" / "TX02_MIC024_20260228_100209_orig.wav").touch()

    (tmp_path / "TX02_2").mkdir()
    (tmp_path / "TX02_2" / "TX02_MIC033_20260302_162711_orig.wav").touch()

    # Scene: volleyball
    (tmp_path / "volleyball").mkdir()
    (tmp_path / "volleyball" / "C5210.MP4").touch()
    (tmp_path / "volleyball" / "C5211.MP4").touch()
    (tmp_path / "volleyball" / "C5089M01.XML").touch()

    # Scene: apartment
    (tmp_path / "apartment").mkdir()
    (tmp_path / "apartment" / "C5089.MP4").touch()
    (tmp_path / "apartment" / "C5089M01.XML").touch()

    # Scene: al_qudra_lake with GoPro subfolder
    (tmp_path / "al_qudra_lake").mkdir()
    (tmp_path / "al_qudra_lake" / "C5100.MP4").touch()
    (tmp_path / "al_qudra_lake" / "100GOPRO").mkdir()
    (tmp_path / "al_qudra_lake" / "100GOPRO" / "GX010001.MP4").touch()

    return tmp_path


@pytest.fixture
def fake_flat_project(tmp_path):
    """Create a fake flat project (no TX folders, no scene subfolders).

    Structure: just clips at project root, no nested structure.
    """
    (tmp_path / "C5001.MP4").touch()
    (tmp_path / "C5002.MP4").touch()

    return tmp_path
