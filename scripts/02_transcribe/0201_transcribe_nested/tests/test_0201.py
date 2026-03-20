"""Unit tests for 0201_transcribe_nested core functions.

Tests cover TRN-01 and TRN-02:
  TRN-01: detect_scenes (scene discovery)
  TRN-01: transcribe_scene (subprocess invocation with correct args)
  TRN-01: should_transcribe_scene (skip already-existing transcripts)
  TRN-02: collect_scene_transcript (copy to canonical Transcription/ path)

TDD RED phase: these tests are written before the implementation exists.
"""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Load module under test via importlib (handles digit-prefixed name)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mod():
    """Load the module under test. Fails with ImportError if not yet created."""
    spec = importlib.util.spec_from_file_location(
        "transcribe_nested",
        Path(__file__).resolve().parent.parent / "0201_transcribe_nested.py",
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------------------
# TRN-01: detect_scenes
# ---------------------------------------------------------------------------

def test_detect_scenes(fake_nested_project, mod):
    """detect_scenes returns sorted list of scene directory Paths.

    Given a project with volleyball, apartment, and drive_home scenes (each with
    a video file), detect_scenes returns 3 Path objects sorted alphabetically.
    Hidden dirs (.DS_Store) and non-dirs are excluded.
    """
    project = fake_nested_project
    scenes = mod.detect_scenes(project)

    assert len(scenes) == 3
    scene_names = [s.name for s in scenes]
    assert "volleyball" in scene_names
    assert "apartment" in scene_names
    assert "drive_home" in scene_names
    # Should be sorted
    assert scenes == sorted(scenes, key=lambda p: p.name)
    # All should be Path objects pointing to existing dirs
    for s in scenes:
        assert isinstance(s, Path)
        assert s.is_dir()


def test_detect_scenes_empty(tmp_path, mod):
    """detect_scenes returns empty list when Source/Video/ has no subdirs."""
    # Create the video dir but leave it empty
    video_dir = tmp_path / "01_Media" / "Source" / "Video"
    video_dir.mkdir(parents=True)

    scenes = mod.detect_scenes(tmp_path)
    assert scenes == []


# ---------------------------------------------------------------------------
# TRN-01: transcribe_scene (subprocess invocation)
# ---------------------------------------------------------------------------

def test_transcribe_scene_cmd(fake_nested_project, mod):
    """transcribe_scene calls subprocess.run with correct args (no dry_run).

    Given a scene_dir Path and num_speakers=2, the function should call
    subprocess.run with [venv_python, script_path, "--project", str(scene_dir),
    "-n", "2", "-y"]. --dry-run must NOT be present.
    """
    project = fake_nested_project
    scene_dir = project / "01_Media" / "Source" / "Video" / "apartment"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = None
        mod.transcribe_scene(scene_dir, num_speakers=2, dry_run=False)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]

    # Should include venv python (path contains .venv_transcribe)
    assert ".venv_transcribe" in cmd[0]
    # Should include transcribe_project.py script
    assert "transcribe_project.py" in cmd[1]
    # Should have --project pointing at scene_dir
    assert "--project" in cmd
    project_idx = cmd.index("--project")
    assert cmd[project_idx + 1] == str(scene_dir)
    # Should have -n 2
    assert "-n" in cmd
    n_idx = cmd.index("-n")
    assert cmd[n_idx + 1] == "2"
    # Should have -y
    assert "-y" in cmd
    # Should NOT have --dry-run
    assert "--dry-run" not in cmd


def test_transcribe_scene_dry_run(fake_nested_project, mod):
    """transcribe_scene includes --dry-run flag when dry_run=True."""
    project = fake_nested_project
    scene_dir = project / "01_Media" / "Source" / "Video" / "volleyball"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = None
        mod.transcribe_scene(scene_dir, num_speakers=2, dry_run=True)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "--dry-run" in cmd


# ---------------------------------------------------------------------------
# TRN-02: collect_scene_transcript
# ---------------------------------------------------------------------------

def test_collect_scene_transcript(tmp_path, mod):
    """collect_scene_transcript copies transcript to canonical Transcription/ path.

    Given scene_dir=tmp/Source/Video/apartment with
    apartment/apartment_transcription/apartment_transcript.json existing,
    collect_scene_transcript copies it to
    tmp/01_Media/Source/Transcription/apartment_transcript.json.
    Asserts destination exists and content matches source.
    """
    import json

    # Set up scene dir with transcript at scene root (as written by transcribe_project.py)
    scene_dir = tmp_path / "01_Media" / "Source" / "Video" / "apartment"
    scene_dir.mkdir(parents=True)

    src_data = {"project": "apartment", "clips": []}
    src_path = scene_dir / "apartment_transcript.json"
    src_path.write_text(json.dumps(src_data))

    # Canonical destination dir (would exist in real project)
    dst_dir = tmp_path / "01_Media" / "Source" / "Transcription"
    dst_dir.mkdir(parents=True)

    result = mod.collect_scene_transcript(scene_dir, tmp_path)

    expected_dst = dst_dir / "scenes" / "apartment_transcript.json"
    assert result == expected_dst
    assert expected_dst.exists()

    # Content must match
    with open(expected_dst) as f:
        dst_data = json.load(f)
    assert dst_data == src_data


# ---------------------------------------------------------------------------
# TRN-01: should_transcribe_scene (skip existing)
# ---------------------------------------------------------------------------

def test_skip_existing_transcript(fake_nested_project, mod):
    """should_transcribe_scene returns False when transcript already exists.

    Given Transcription/apartment_transcript.json already present,
    should_transcribe_scene(project, "apartment") must return False.
    """
    project = fake_nested_project
    # Create the existing transcript
    dst = project / "01_Media" / "Source" / "Transcription" / "apartment_transcript.json"
    dst.write_text('{"project": "apartment", "clips": []}')

    result = mod.should_transcribe_scene(project, "apartment")
    assert result is False


def test_should_transcribe_scene_missing(fake_nested_project, mod):
    """should_transcribe_scene returns True when transcript does not exist."""
    project = fake_nested_project
    # volleyball transcript is not created in fake_nested_project fixture
    result = mod.should_transcribe_scene(project, "volleyball")
    assert result is True
