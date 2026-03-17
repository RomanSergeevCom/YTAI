# Phase 3: Transcribe — Research

**Researched:** 2026-03-17
**Domain:** Whisper/Pyannote transcription pipeline — nested multi-scene adaptation
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TRN-01 | `transcribe_project.py` runs per-scene (or across all scenes from `Source/Video/`) without changing its internal Whisper/Pyannote logic | Existing script already finds videos recursively via `find_videos(source_video_dir)`; scene subfolders are picked up automatically. Only the invoker (a new wrapper script) needs to iterate scenes. |
| TRN-02 | Each scene produces `{scene}_transcript.json` under `01_Media/Source/Transcription/` with word-level timecodes | The existing v3-path write logic already targets `01_Media/Source/Transcription/`. Scene-naming requires passing `--project` pointing at the scene video folder; the resulting transcript filename is `{scene_folder_name}_transcript.json`. |
| TRN-03 | All scenes merge into `merged_transcript.json` under `01_Media/Source/Transcription/`; every word carries `scene_id` and local timecode | No existing script does cross-scene merge. A new `merge_transcripts.py` module needs to read each `{scene}_transcript.json`, attach `scene_id`, preserve local `start`/`end`, and write `merged_transcript.json`. |
</phase_requirements>

---

## Summary

The existing `transcribe_project.py` (v3.0/v3.2) is fully capable of transcribing one scene at a time: when pointed at `01_Media/Source/Video/` it finds all videos recursively, but it produces a **single** combined transcript for the entire project — not per-scene. For nested projects with 7 scenes, we need per-scene isolation so that:

1. Each scene is transcribed independently (separate diarization, separate full_audio.wav, restartable).
2. Each scene outputs `{scene}_transcript.json` in `01_Media/Source/Transcription/`.
3. A final merge step combines all scene transcripts into `merged_transcript.json` with `scene_id` on every word.

The key insight is that `transcribe_project.py` already does everything correctly **when pointed at a single scene's video folder**. The requirement TRN-01 ("without changes to internal logic") means we write a thin wrapper/orchestrator that calls the existing script once per scene, then a separate merge script for TRN-03. This is the same additive pattern used in Phase 1 and Phase 2.

**Primary recommendation:** Write `0201_transcribe_nested.py` — a scene-aware orchestrator that iterates `Source/Video/{scene}/` subfolders, invokes `transcribe_project.py` per scene (or delegates directly via function import), then calls `merge_transcripts.py` to produce `merged_transcript.json`.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| openai-whisper | installed in `.venv_transcribe` | Word-level ASR | Already used by `transcribe_project.py`; large-v3 model in place |
| pyannote.audio | installed in `.venv_transcribe` | Speaker diarization | Already used; HuggingFace token configured |
| torch (MPS) | installed in `.venv_transcribe` | GPU acceleration | Apple Silicon MPS path already configured in `transcribe_project.py` |
| ffmpeg | system (brew) | Audio extraction | Already used in all pipeline stages |
| Python stdlib | 3.x | json, pathlib, argparse, subprocess | No new deps needed |

**No new Python dependencies required.** All libraries are already in `~/YTAI/environment/.venv_transcribe`.

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | in `.venv_transcribe` | Unit tests for new scripts | All new functions follow project TDD pattern |
| importlib.util | stdlib | Load digit-prefixed modules in tests | Established project pattern (see STATE.md decisions) |

**Installation:** None needed — venv already contains all required packages.

---

## Architecture Patterns

### What the existing script already handles

When `transcribe_project.py` is passed `--project /path/to/ProjectRoot`:

1. It detects v3.0 structure: `01_Media/Source/Video/` exists → `v3_structure = True`
2. `find_videos(source_video_dir)` recurses all subfolders — it finds clips from ALL scenes in one pass
3. `transcription_dir = work_dir / "01_Media" / "Source" / "Transcription"`
4. Output: single `{project_name}_transcript.json` + `{project_name}_ingest.json` — **not per-scene**

**When passed `--project /path/to/ProjectRoot/01_Media/Source/Video/apartment/`:**

1. It falls to flat mode (no `01_Media/Source/Video/` inside `apartment/`)
2. Finds clips directly in `apartment/`
3. `project_name = "apartment"`
4. `transcription_dir = apartment / "apartment_transcription"` (legacy path, NOT v3)

This second approach loses the v3 output path. The wrapper must handle path routing.

### Recommended Approach: Per-Scene Invocation with Project-Level Context

The correct strategy is to pass the **project root** as `--project` but add a `--scene` flag to tell the script to process only one scene's videos and write to the correct v3 output location.

**However, TRN-01 says "without changes to internal logic."** This means we need to choose between:

**Option A (recommended):** Thin wrapper script `0201_transcribe_nested.py` that:
1. Scans `Source/Video/` for scene subfolders
2. For each scene, invokes `transcribe_project.py` via `subprocess` with `--project` pointing at the **scene subfolder inside Source/Video/**
3. Post-processes the output: moves/renames `apartment_transcription/apartment_transcript.json` → `Transcription/apartment_transcript.json`
4. Or: invokes with a custom `--output-dir` (if the flag exists; it does not exist currently)

**Option B (simpler, preferred):** The wrapper creates a temporary symlink or copy mechanism — but this is fragile.

**Option C (actual correct reading of TRN-01):** TRN-01 says "existing `transcribe_project.py` runs per-scene or with `Source/Video/`". The intent is: the transcription script is called once per scene by a new orchestrator. The orchestrator handles output path management. The internal Whisper/Pyannote stages are unchanged.

**Preferred implementation:** The `transcribe_project.py` already supports `--project` pointing at any folder. When pointed at `Source/Video/apartment/`:
- It operates in flat mode (no v3 subfolder detected inside apartment/)
- It creates `apartment/apartment_transcription/apartment_transcript.json`
- The wrapper then copies this to `01_Media/Source/Transcription/apartment_transcript.json`

This is clean, additive, and respects TRN-01 perfectly.

### Recommended Project Structure

```
scripts/02_transcribe/
├── 020101_transcribe/
│   ├── transcribe_project.py       # Existing — no changes
│   ├── ingest_json.py              # Existing — no changes
│   └── 020101_transcribe_spec.md   # Existing
├── 0201_transcribe_nested.py       # NEW: scene orchestrator
├── merge_transcripts.py            # NEW: cross-scene merger
└── tests/
    └── test_transcribe_nested.py   # NEW: tests
```

Or, following the established naming pattern from Phase 2 (`0104_sync_audio_nested.py`), place under:

```
scripts/02_transcribe/0201_transcribe_nested/
├── 0201_transcribe_nested.py
├── merge_transcripts.py
└── tests/
    └── test_0201.py
```

### Pattern 1: Scene Detection (mirrors Phase 1 & 2 pattern)

```python
# Source: established project pattern (STATE.md, 0101_init_folders.py)
SCENE_DIR_RE = re.compile(r'^[A-Za-z]')  # any non-numeric prefix = scene

def detect_scenes(project: Path) -> list[Path]:
    """Return sorted scene subfolders under Source/Video/."""
    video_dir = project / "01_Media" / "Source" / "Video"
    return sorted([
        d for d in video_dir.iterdir()
        if d.is_dir() and not d.name.startswith('.')
    ])
```

Note: The reference project (YTCR_1_Arty_Dzis) has scene names like `volleyball`, `apartment`, `desert_drive` — NOT prefixed with `\d{2}_`. The `\d{2}_` pattern in `ingest_json.py` is for the **older** multi-folder style. Scene detection for nested projects should match any non-hidden subdirectory of `Source/Video/`.

### Pattern 2: Per-Scene Transcription Invocation

```python
# Source: project convention — subprocess invocation with venv activation
import subprocess
from pathlib import Path

def transcribe_scene(scene_dir: Path, num_speakers: int, dry_run: bool = False):
    """Invoke transcribe_project.py for one scene."""
    venv_python = Path("~/YTAI/environment/.venv_transcribe/bin/python").expanduser()
    script = Path("~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py").expanduser()
    cmd = [str(venv_python), str(script), "--project", str(scene_dir), "-n", str(num_speakers), "-y"]
    if dry_run:
        cmd.append("--dry-run")
    subprocess.run(cmd, check=True)
```

### Pattern 3: Transcript Output Path Management

The `transcribe_project.py` writes to `{scene_dir}/{scene_name}_transcription/{scene_name}_transcript.json` (legacy flat path). The wrapper must move/copy to the canonical v3 location:

```python
def collect_scene_transcript(scene_dir: Path, project: Path) -> Path:
    """Move per-scene transcript to canonical Transcription/ location."""
    scene_name = scene_dir.name
    src = scene_dir / f"{scene_name}_transcription" / f"{scene_name}_transcript.json"
    dst_dir = project / "01_Media" / "Source" / "Transcription"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{scene_name}_transcript.json"
    shutil.copy2(src, dst)
    return dst
```

### Pattern 4: merged_transcript.json Schema

```python
# merged_transcript.json structure (new, for Phase 4 UXP consumption)
{
    "version": "1.0",
    "project": "YTCR_1_Arty_Dzis",
    "scenes": ["volleyball", "apartment", "desert_drive", ...],
    "words": [
        {
            "scene_id": "volleyball",
            "word": "hello",
            "start": 1.46,       # local timecode within scene (seconds)
            "end": 1.82,
            "duration": 0.36,
            "confidence": 0.987,
            "speaker": "SPEAKER_00"
        },
        ...
    ]
}
```

**Critical:** `start`/`end` are LOCAL timecodes within the scene, not global. UXP (Phase 4) uses `scene_id` to route to the correct Premiere timeline, then `start` to seek within that timeline.

### Anti-Patterns to Avoid

- **Pointing the transcription script at the project root for all scenes at once:** Produces a single `YTCR_1_Arty_Dzis_transcript.json` — not per-scene, breaks TRN-02 and TRN-03 independently.
- **Hardcoding scene names:** Detect from filesystem; reference project has 7 scenes but the pattern must generalize.
- **Global timecodes in merged_transcript.json:** The UXP plugin routes by `scene_id` then seeks within scene. Global timecodes are meaningless across different Premiere timelines.
- **Re-running all scenes when only one changed:** The script must support `--scene` to process a single scene (TRN-03 success criterion 3).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Speech recognition | Custom ASR | `transcribe_project.py` Whisper large-v3 | Already validated, handles word_timestamps, disfluencies, multilingual |
| Speaker diarization | Custom speaker ID | pyannote.audio in `transcribe_project.py` | Already configured with HuggingFace token, Apple MPS |
| Audio extraction | Custom ffmpeg commands | `transcribe_project.py` Stage 1 | Already handles 16kHz mono conversion, per-clip offset tracking |
| JSON schema validation | Custom validator | Python `json.load()` + dict checks | Lightweight, consistent with rest of pipeline |

**Key insight:** The entire Whisper+Pyannote pipeline is a black box that already works. Phase 3 wraps it, routes its outputs, and merges results — it does NOT touch the transcription logic.

---

## Common Pitfalls

### Pitfall 1: scene_transcript.json Naming Mismatch
**What goes wrong:** `transcribe_project.py` names output based on the folder name passed to `--project`. If you pass `Source/Video/apartment`, the output is `apartment_transcript.json`. If you pass the project root, the output is `YTCR_1_Arty_Dzis_transcript.json`.
**Why it happens:** The script uses `input_path.name` as `project_name`.
**How to avoid:** Always pass the scene subfolder as `--project`; the wrapper controls output collection.
**Warning signs:** Output JSON named after project root, not scene.

### Pitfall 2: Output Written to Legacy Path, Not v3 Path
**What goes wrong:** When `--project` points at `Source/Video/apartment/` (no `01_Media/Source/Video/` inside), the script uses the **legacy** path `apartment/apartment_transcription/`. The v3 detection (`01_Media/Source/Video/` exists inside the target) fails.
**Why it happens:** v3 detection checks if `input_path / "01_Media" / "Source" / "Video"` exists. When input_path = `Source/Video/apartment/`, this is false.
**How to avoid:** The wrapper script MUST copy/move from `scene_dir/{scene}_transcription/{scene}_transcript.json` → `Transcription/{scene}_transcript.json`.
**Warning signs:** Per-clip data and transcript appear inside `Source/Video/apartment/` instead of `Transcription/`.

### Pitfall 3: per_clip/ Data Scattered in Scene Subfolders
**What goes wrong:** `transcribe_project.py` writes `per_clip/{clip_id}/` inside its `transcription_dir`. When run per-scene with scene_dir as project root, per_clip data lands in `Source/Video/apartment/apartment_transcription/per_clip/`.
**Why it happens:** transcription_dir is relative to the project argument.
**How to avoid:** After transcription, the wrapper can either leave per_clip inside the scene (acceptable — it was already there from Phase 2: `Transcription/per_clip/{scene}/{clip}/`), or move it. The existing ORG-04/AUD-01 put audio in `Transcription/per_clip/{scene}/{clip}/`. Consistency requires per_clip data lands under `Transcription/per_clip/{scene}/` not inside `Source/Video/`.

### Pitfall 4: Diarization Audio Sourced from Camera, Not TX
**What goes wrong:** `transcribe_project.py` Stage 1 extracts audio from video files. For nested projects, the best audio is `{clip}_TX02.wav` or `{clip}_TX01.wav` — not the camera embed.
**Why it happens:** The script's default behavior is to extract audio from the MP4.
**How to avoid:** This is a known design decision. The spec (TRN-01) says "internal logic unchanged." The TX audio is available via `clips[].dji_audio` in ingest.json, but the transcription script doesn't consume `{scene}_ingest.json` directly. **For Phase 3, transcription runs on camera audio (same as flat pipeline).** Using TX audio would require a new Stage 1 variant — explicitly out of scope per TRN-01.
**Warning signs:** N/A — this is an accepted limitation.

### Pitfall 5: Re-run Overwrites All Scenes
**What goes wrong:** Running the orchestrator with `--project` on a partially-complete project overwrites already-completed scene transcripts.
**Why it happens:** No skip logic for existing outputs.
**How to avoid:** The orchestrator must check if `Transcription/{scene}_transcript.json` already exists before invoking the sub-script. Add `--scene` flag to target a single scene (TRN-03 requirement).
**Warning signs:** Scene X overwritten after scene Y failed midway.

### Pitfall 6: merged_transcript.json Uses Global Timecodes
**What goes wrong:** Summing clip offsets across scenes produces nonsensical "global" timecodes. UXP plugin can't use them.
**Why it happens:** Tempting to concatenate offsets for a "flat" view.
**How to avoid:** `merged_transcript.json` MUST use local timecodes. The `scene_id` field is the routing key for UXP.

---

## Code Examples

### Reading per-scene transcript.json words

```python
# Source: ingest_json.py + 020101_transcribe_spec.md pattern
import json
from pathlib import Path

def read_scene_words(transcript_path: Path, scene_id: str) -> list[dict]:
    """Extract word entries from a scene transcript, tagging with scene_id."""
    with open(transcript_path) as f:
        data = json.load(f)
    words = []
    for clip in data.get("clips", []):
        for segment in clip.get("transcript_segments", []):
            for word in segment.get("words_data", []):
                words.append({
                    "scene_id": scene_id,
                    "word": word["word"],
                    "start": word["start"],   # local to scene
                    "end": word["end"],
                    "duration": word.get("duration", word["end"] - word["start"]),
                    "confidence": word.get("confidence", 0.0),
                    "speaker": segment.get("speaker", "UNKNOWN"),
                })
    return words
```

### merged_transcript.json writer

```python
# Source: project conventions (json.dump with indent=2, ensure_ascii=False)
import json
from pathlib import Path

def merge_transcripts(project: Path, scene_names: list[str]) -> Path:
    tr_dir = project / "01_Media" / "Source" / "Transcription"
    all_words = []
    for scene in scene_names:
        tp = tr_dir / f"{scene}_transcript.json"
        if tp.exists():
            all_words.extend(read_scene_words(tp, scene_id=scene))
    merged = {
        "version": "1.0",
        "project": project.name,
        "scenes": scene_names,
        "words": all_words,
    }
    out = tr_dir / "merged_transcript.json"
    with open(out, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    return out
```

### CLI interface (per Phase 2 pattern)

```python
# Source: 0104_sync_audio_nested.py pattern (established in Phase 2)
ap = argparse.ArgumentParser()
ap.add_argument("--project", required=True, help="Project root path")
ap.add_argument("--scene", default=None, help="Process single scene only")
ap.add_argument("-n", "--speakers", type=int, default=2)
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("-y", action="store_true", help="Skip confirmations")
```

---

## State of the Art (for this codebase)

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single flat project transcription | v3.0 structure detection + recursive video scan | v3.0 | Script already finds scene-subfolder videos but outputs one combined transcript |
| prproj generation (Stage 5b) | UXP plugin reads ingest.json | v3.0 | Phase 3 still produces ingest.json; Stage 6 unchanged |
| All TX audio via filename only | TX audio via ingest.json `dji_audio` field | v3.2 | ingest_json.py already picks up `{clip}_TX*.wav` via rglob |

**Key current-state facts (HIGH confidence from code reading):**

1. `transcribe_project.py` v3.0 already supports v3 folder structure. No code changes needed to it.
2. When pointed at a scene subfolder, it runs in **flat mode** — this is correct behavior for per-scene transcription.
3. The `ingest_json.py` `generate()` function already does `rglob(f"{clip_id}_TX*.wav")` — it finds TX audio in both flat and scene-subfolder layouts. This means Stage 6 already works for nested projects if pointed correctly.
4. Phase 2 (completed) produced `{scene}_ingest.json` at `Source/Setup/{scene}_ingest.json` — this is NOT the same ingest.json that `transcribe_project.py` generates. The Phase 2 ingest.json has A1/A2/A3 tracks; the transcription ingest.json has `clips[].dji_audio`.
5. The `merged_transcript.json` schema is entirely new — no existing code handles cross-scene merging.

---

## Open Questions

1. **What audio source does Whisper use per scene?**
   - What we know: Stage 1 of `transcribe_project.py` extracts 16kHz mono WAV from the MP4 video file (camera audio). TX audio is NOT automatically used as the Whisper input.
   - What's unclear: Does the human want Whisper to use TX audio (TX02) instead of camera audio? TX02 is significantly cleaner for speech.
   - Recommendation: Default to camera audio (TRN-01: no internal logic changes). If TX audio transcription is needed, it is a v2 requirement. Document this explicitly in the plan.

2. **Where should per_clip intermediate data live after nested transcription?**
   - What we know: Phase 2 already wrote `Transcription/per_clip/{scene}/{clip}/{clip}_AUDIO.wav`. Transcription Stage 1 will overwrite this WAV with a 16kHz version.
   - What's unclear: Should the transcription per_clip data merge into the existing `Transcription/per_clip/{scene}/{clip}/` hierarchy, or stay inside `Source/Video/{scene}/`?
   - Recommendation: Move/copy per_clip outputs to `Transcription/per_clip/{scene}/{clip}/` for consistency with the ORG-04 and AUD-01 established structure.

3. **Number of speakers per scene or global?**
   - What we know: `-n NUM` is passed to Whisper/Pyannote. Reference project has 1-2 speakers depending on scene.
   - What's unclear: Should speaker count be set globally (same `-n` for all scenes) or per-scene?
   - Recommendation: Accept `--speakers N` as global default; document that per-scene override can be added in v2. For the reference project, `-n 2` is the safe default.

---

## Validation Architecture

Config does not have `workflow.nyquist_validation: false`, so testing is enabled.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (in `.venv_transcribe`) |
| Config file | none — run directly |
| Quick run command | `python3 -m pytest scripts/02_transcribe/tests/test_0201.py -x -q` |
| Full suite command | `python3 -m pytest scripts/02_transcribe/tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TRN-01 | `detect_scenes()` finds all scene subfolders | unit | `pytest .../test_0201.py::test_detect_scenes -x -q` | Wave 0 |
| TRN-01 | `transcribe_scene()` invokes subprocess with correct args | unit (mock subprocess) | `pytest .../test_0201.py::test_transcribe_scene_cmd -x -q` | Wave 0 |
| TRN-01 | Skip already-transcribed scenes | unit | `pytest .../test_0201.py::test_skip_existing_transcript -x -q` | Wave 0 |
| TRN-02 | `collect_scene_transcript()` copies to `Transcription/{scene}_transcript.json` | unit | `pytest .../test_0201.py::test_collect_scene_transcript -x -q` | Wave 0 |
| TRN-03 | `merge_transcripts()` produces correct `merged_transcript.json` with `scene_id` and local timecodes | unit | `pytest .../test_0201.py::test_merge_transcripts -x -q` | Wave 0 |
| TRN-03 | Merged words have `scene_id` and local `start`/`end` | unit | `pytest .../test_0201.py::test_merged_word_fields -x -q` | Wave 0 |

### Sampling Rate

- **Per task commit:** `python3 -m pytest scripts/02_transcribe/tests/test_0201.py -x -q`
- **Per wave merge:** `python3 -m pytest scripts/02_transcribe/tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `scripts/02_transcribe/0201_transcribe_nested/tests/test_0201.py` — covers all TRN-* unit tests
- [ ] `scripts/02_transcribe/0201_transcribe_nested/0201_transcribe_nested.py` — main orchestrator
- [ ] `scripts/02_transcribe/0201_transcribe_nested/merge_transcripts.py` — cross-scene merger

---

## Sources

### Primary (HIGH confidence)

- `/Users/romansergeev/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py` — v3.0 source code, main() scene detection logic (lines 755-835), find_videos(), stage6_generate_ingest_json()
- `/Users/romansergeev/YTAI/scripts/02_transcribe/020101_transcribe/ingest_json.py` — DJI audio rglob discovery, scene detection, ingest.json generation
- `/Users/romansergeev/YTAI/scripts/02_transcribe/020101_transcribe/020101_transcribe_spec.md` — v3.2 spec, full pipeline stages, output paths
- `/Users/romansergeev/YTAI/.planning/REQUIREMENTS.md` — TRN-01, TRN-02, TRN-03 definitions
- `/Users/romansergeev/YTAI/.planning/phases/02-audio-sync/02-02-PLAN.md` — `{scene}_ingest.json` schema (A1/A2/A3 tracks), Phase 2 output contract
- `/Users/romansergeev/YTAI/scripts/run_pipeline.py` — `_validate_transcribe()`, `check_transcribe()`, `_verify_transcribe()` — current flat pipeline hooks

### Secondary (MEDIUM confidence)

- `/Users/romansergeev/YTAI/.planning/STATE.md` — Accumulated decisions: importlib pattern, module fixture scoping, Phase 2 architecture decisions
- `/Users/romansergeev/YTAI/scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio_spec.md` — Output contract: `Source/Audio/{clip}_TX{N}.wav` or `Source/Audio/{scene}/{clip}_TX{N}.wav`

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — same venv as existing pipeline, no new deps
- Architecture: HIGH — read actual source code; behavior verified by tracing execution paths
- Pitfalls: HIGH — derived from actual code behavior (v3 path detection logic at lines 766-824)
- merged_transcript.json schema: MEDIUM — schema is new; structure is derived from UXP requirements (Phase 4) not yet implemented

**Research date:** 2026-03-17
**Valid until:** 2026-04-17 (stable codebase, monthly refresh sufficient)
