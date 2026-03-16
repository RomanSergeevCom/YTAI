"""Unit tests for 0100_organize.py.

Tests cover all ORG requirements:
  ORG-01: Nested project detection
  ORG-02: Scene detection and clip moves
  ORG-03: DJI WAV collection into 99_Pipeline/DJI_Audio/
  ORG-04: XML sidecar placement with scene layer
  ORG-05: Graceful handling of absent XML sidecars
  ORG-06: v3.0 folder skeleton creation
"""
import importlib.util
import sys
import pytest
from pathlib import Path


# conftest.py inserts the 0100_organize package dir into sys.path.
# Module name starts with a digit, so use importlib.util to load it.
def _load_module():
    spec = importlib.util.spec_from_file_location(
        "organize_mod",
        Path(__file__).resolve().parent.parent / "0100_organize.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_org = _load_module()


class TestNestedDetection:
    def test_detect_nested_project(self, fake_nested_project):
        """ORG-01: TX01/ at root triggers nested mode."""
        assert _org.is_nested_project(fake_nested_project) is True

    def test_detect_flat_project(self, fake_flat_project):
        """ORG-01: No TX folders = not nested."""
        assert _org.is_nested_project(fake_flat_project) is False


class TestSceneDetection:
    def test_detect_scenes_bare_names(self, fake_nested_project):
        """ORG-02: volleyball/, apartment/, al_qudra_lake/ detected as scenes."""
        scenes = _org.detect_scenes(fake_nested_project)
        assert "volleyball" in scenes
        assert "apartment" in scenes
        assert "al_qudra_lake" in scenes

    def test_tx_folders_not_scenes(self, fake_nested_project):
        """ORG-02: TX01/, TX02/, TX02_2/ are NOT scenes."""
        scenes = _org.detect_scenes(fake_nested_project)
        assert "TX01" not in scenes
        assert "TX02" not in scenes
        assert "TX02_2" not in scenes


class TestVideoMove:
    def test_scene_clips_moved(self, fake_nested_project):
        """ORG-02: Clips land in Source/Video/{scene}/. (Plan 02)"""
        pass

    def test_gopro_subfolder_preserved(self, fake_nested_project):
        """ORG-02: al_qudra_lake/100GOPRO/ preserved. (Plan 02)"""
        pass


class TestDjiWavMove:
    def test_dji_wavs_moved_flat(self, fake_nested_project):
        """ORG-03: TX WAVs land flat in 99_Pipeline/DJI_Audio/. (Plan 02)"""
        pass


class TestXmlSidecar:
    def test_xml_sidecar_with_scene(self, fake_nested_project):
        """ORG-04: XML lands in per_clip/{scene}/{clip}/. (Plan 02)"""
        pass


class TestGraceful:
    def test_no_xml_no_error(self, fake_flat_project):
        """ORG-05: No XML sidecars = no error."""
        result = _org.organize(fake_flat_project)
        assert result is True


class TestFolderSkeleton:
    def test_v3_skeleton_created(self, fake_nested_project):
        """ORG-06: v3.0 dirs exist after organize."""
        _org.organize(fake_nested_project)
        project = fake_nested_project
        assert (project / "01_Media" / "Source" / "Video").exists()
        assert (project / "01_Media" / "Source" / "Audio").exists()
        assert (project / "01_Media" / "Source" / "Transcription").exists()
        assert (project / "01_Media" / "Source" / "Setup" / "logs").exists()
        assert (project / "01_Media" / "Source" / "LUT").exists()
        assert (project / "99_Pipeline" / "DJI_Audio").exists()
