# Phase 1: Organize - Research

**Researched:** 2026-03-17
**Domain:** Python file organization, path manipulation, v3.0 folder template
**Confidence:** HIGH

---

## Summary

Phase 1 adds support for nested multi-scene projects to the existing `run_pipeline.py` organize logic. The existing code handles a large portion of the requirements already: it creates the v3.0 folder skeleton via `_deep_merge_template()`, discovers video/DJI/LUT/XML files via `discover_media_files()`, and moves them to correct v3.0 locations via `organize_media_files()`.

The critical gap is scene detection. The current `_get_scene_name()` function only recognizes scene folders with a numeric prefix (`SCENE_DIR_RE = re.compile(r'^\d{2}_')`), matching patterns like `01_Interview/` or `02_Car/`. The reference project uses bare lowercase names (`volleyball/`, `apartment/`, `al_qudra_lake/`, etc.) with no numeric prefix. These are invisible to the current detection — their MP4 clips would land flat in `Source/Video/` with no scene subfolder. Additionally, TX folders (`TX01/`, `TX02/`, `TX02_2/`) are WAV-source folders sitting at the project root; the DJI_RAW_RE pattern correctly identifies the WAV files inside them by filename, but only if those files are discovered — and they will be, since `discover_media_files()` walks the full project tree excluding v3.0 managed directories.

The new script should be a standalone `scripts/01_prepare/0100_organize/0100_organize.py` (not an extension of `run_pipeline.py`), following the pattern of existing stage scripts. The `run_pipeline.py` init stage will then call this script, mirroring how it calls `0102_extract_audio.py`. This preserves the "scripts are independent" design principle.

**Primary recommendation:** Write `0100_organize.py` as a standalone Python script. Extend `_get_scene_name()` logic to detect any immediate child directory containing video files (not just `\d{2}_`-prefixed ones). TX folder WAVs are already discovered correctly by `DJI_RAW_RE`. XML per-clip path must add scene layer: `per_clip/{scene}/{clip}/`.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ORG-01 | Detect nested project by presence of TX01/ and/or TX02/ folders in project root | `DJI_RAW_RE = re.compile(r'^TX\d{2}_MIC\d{3}_\d{8}_\d{6}')` already identifies DJI WAVs. Detection predicate: `any(d for d in project.iterdir() if d.is_dir() and re.match(r'^TX\d+', d.name))` |
| ORG-02 | Move MP4/MOV clips per scene into `01_Media/Source/Video/{scene}/`; preserve scene subfolder structure | Current code preserves subfolders for `^\d{2}_` scenes; must extend to bare-name folders (volleyball/, apartment/, etc.) |
| ORG-03 | TX01/, TX02/, TX02_2/ WAVs merge flat into `99_Pipeline/DJI_Audio/`; filenames preserved | DJI_RAW_RE already matches `TX02_MIC037_*.wav` filenames. `discover_media_files()` walks TX folders. Destination is already `dji_dir` (flat). |
| ORG-04 | Sony XML sidecars (`C5089M01.XML`) move to `Transcription/per_clip/{scene}/{clip}/` | Current code puts XML at `per_clip/{clip}/` with no scene layer. Must add scene layer matching the clip's scene. |
| ORG-05 | Absent XML sidecars do not block pipeline (graceful) | Already implemented: `discovered["sidecars"]` is an empty list → loop is a no-op. |
| ORG-06 | Create standard v3.0 folder skeleton from `YTAI_Folder_Templates/Type2_Production` | Already implemented: `_deep_merge_template()` + `run_init()`. Reuse as-is. |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pathlib.Path` | stdlib | Path manipulation, directory creation | Project-wide standard; all existing scripts use it |
| `shutil` | stdlib | `shutil.move()` for cross-device file moves | Used throughout `run_pipeline.py`; handles cross-filesystem moves transparently |
| `re` | stdlib | TX folder detection, DJI filename matching | Already defined patterns in codebase |
| `os.walk` | stdlib | Recursive directory traversal | Used in `discover_media_files()` and `_deep_merge_template()` |
| `argparse` | stdlib | CLI interface | All existing pipeline scripts use argparse |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `ffmpeg` / system | system | Not needed for organize phase | Only needed in extract_audio/sync_dji stages |

**Installation:** No new dependencies. All stdlib.

---

## Architecture Patterns

### Recommended Project Structure

New script location:
```
scripts/01_prepare/
├── 0100_organize/
│   └── 0100_organize.py      ← new standalone script
├── 0101_init_folders/
│   ├── 0101_init_folders_spec.md
│   └── RYA_example.prproj
├── 0102_extract_audio/
│   └── 0102_extract_audio.py
└── 0103_sync_dji_audio/
    └── 0103_sync_dji_audio.py
```

The `run_pipeline.py` init stage currently does init+organize inline. After this phase, it will call `0100_organize.py` for the organize portion, or the init stage remains inline but adds nested-project awareness.

### Pattern 1: Nested-Project Detection (ORG-01)

**What:** Detect if a project is "nested" (multi-scene) by checking for TX folder(s) at the root.
**When to use:** At script entry, before any file moves.
**Example:**
```python
TX_FOLDER_RE = re.compile(r'^TX\d+', re.IGNORECASE)

def is_nested_project(project: Path) -> bool:
    """True if project has TX01/, TX02/, etc. folders at root."""
    return any(
        d.is_dir() and TX_FOLDER_RE.match(d.name)
        for d in project.iterdir()
    )
```

### Pattern 2: Scene Detection for Bare-Name Folders (ORG-02)

**What:** Identify scene folders in the project root — folders that contain video files directly.
**Critical gap:** Current `SCENE_DIR_RE = re.compile(r'^\d{2}_')` only matches `01_Interview/` style. Reference project uses `volleyball/`, `apartment/`, `al_qudra_lake/` — no numeric prefix.

**New logic:** A folder at the project root is a scene if it:
1. Is a directory
2. Is not a v3.0 managed dir (`V3_MANAGED_DIRS`)
3. Is not a TX folder (`TX\d+` pattern)
4. Is not a system/hidden/archive folder
5. Contains at least one video file (recursively)

```python
VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.mts', '.avi', '.mkv'}
V3_MANAGED_DIRS = {'01_Media', '02_Exports', '03_Shorts', '04_Thumbnail', 'YouTube', '99_Pipeline'}
TX_FOLDER_RE = re.compile(r'^TX\d+', re.IGNORECASE)
SYSTEM_DIRS = {'.Spotlight-V100', '.fseventsd', '.Trashes', '.TemporaryItems', '__MACOSX'}
ARCHIVE_PREFIXES = ('archive', 'old_', 'backup', '_old', '_backup')

def detect_scenes(project: Path) -> list[str]:
    """Return list of scene folder names found at project root."""
    scenes = []
    for d in sorted(project.iterdir()):
        if not d.is_dir():
            continue
        if d.name in V3_MANAGED_DIRS:
            continue
        if d.name in SYSTEM_DIRS or d.name.startswith('.'):
            continue
        if d.name.lower().startswith(ARCHIVE_PREFIXES):
            continue
        if TX_FOLDER_RE.match(d.name):
            continue
        # Must contain video files
        if any(f.suffix.lower() in VIDEO_EXTS
               for f in d.rglob('*') if f.is_file()):
            scenes.append(d.name)
    return scenes
```

### Pattern 3: Video Move with Scene Preservation (ORG-02)

**What:** Move each scene's clips into `Source/Video/{scene}/` preserving any sub-structure.
**Note:** The reference project has clips directly inside scene folders (`volleyball/C5089.MP4`). `al_qudra_lake/` also contains a GoPro subfolder (`100GOPRO/`). Relative path from scene root should be preserved.

```python
def move_scene_clips(scene_name: str, scene_dir: Path,
                     video_dir: Path, dry_run: bool = False):
    dest_scene = video_dir / scene_name
    for clip in scene_dir.rglob('*'):
        if not clip.is_file() or clip.suffix.lower() not in VIDEO_EXTS:
            continue
        rel = clip.relative_to(scene_dir)   # e.g. C5089.MP4 or 100GOPRO/GX010001.MP4
        dest = dest_scene / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dry_run:
            shutil.move(str(clip), str(dest))
```

### Pattern 4: DJI WAV Collection (ORG-03)

**What:** Collect all WAV files from TX01/, TX02/, TX02_2/ folders flat into `99_Pipeline/DJI_Audio/`.
**How existing code handles it:** `discover_media_files()` walks the full project tree, and for any WAV matching `DJI_RAW_RE = re.compile(r'^TX\d{2}_MIC\d{3}_\d{8}_\d{6}')`, it adds to `dji_audio` list. Destination is `dji_dir` (flat). This works correctly for the reference project because `TX01_MIC001_20260228_102211_orig.wav` matches the pattern.

**No code change needed for this part.** The existing discovery + move logic handles it.

### Pattern 5: XML Sidecars with Scene Layer (ORG-04)

**What:** Sony XML sidecars (`C5089M01.XML`) currently land at `per_clip/{clip}/`. With nested projects, they must land at `per_clip/{scene}/{clip}/`.

**Current code** (`organize_media_files`):
```python
per_clip = tr_dir / "per_clip" / clip_id        # flat — no scene
```

**New code** must add scene lookup:
```python
# After detecting scene from video_stems + scene_map:
scene = clip_scene_map.get(clip_id)
if scene:
    per_clip = tr_dir / "per_clip" / scene / clip_id
else:
    per_clip = tr_dir / "per_clip" / clip_id
```

The `clip_scene_map` must be built from the `detected_scenes` dict before any moves happen.

### Pattern 6: Idempotency

**What:** Running the script twice on the same project must produce the same result without errors.
**How existing code handles it:** `dst.exists() → log.warn + skip`. This pattern must be preserved.

### Anti-Patterns to Avoid

- **Using `SCENE_DIR_RE = r'^\d{2}_'` for scene detection in nested projects:** The reference project's scenes have no numeric prefix. Using the old regex alone will result in all clips landing flat in `Source/Video/` with no subfolders.
- **Hardcoding TX folder names (`TX01`, `TX02`):** Use regex `r'^TX\d+'` to handle any TX variant (TX01, TX02, TX02_2, TX03, etc.).
- **Using `shutil.copy` instead of `shutil.move`:** Files must move, not copy — source drive space is limited.
- **Assuming `per_clip/{clip}/` is always flat:** The new multi-scene structure adds a `{scene}/` layer. Downstream consumers (0102_extract_audio, 0103_sync_dji_audio) must also be updated to write to the scene-aware path.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-filesystem moves | Custom copy+delete | `shutil.move()` | Handles cross-device (e.g. external SSD to SSD) transparently; already in codebase |
| Template directory merging | Custom recursive mkdir | `_deep_merge_template()` in run_pipeline.py | Already handles `.gitkeep` skip, skips existing dirs, counts created dirs |
| Natural sort of filenames | Custom comparator | `natural_sort_key()` in run_pipeline.py | Handles `clip1, clip2, clip10` correctly; already defined |
| v3.0 structure existence check | Scanning for dirs | `check_init()` in run_pipeline.py | Already checks `Source/Video` as proxy |

---

## Common Pitfalls

### Pitfall 1: Scene Detection Too Narrow
**What goes wrong:** Using `SCENE_DIR_RE = re.compile(r'^\d{2}_')` on the reference project. `volleyball/`, `apartment/`, `al_qudra_lake/` all fail the match. All 325 clips land flat in `Source/Video/` with no scene prefix.
**Why it happens:** Old codebase assumed scenes were numbered like `01_Interview`. The new project uses bare names.
**How to avoid:** New detection: any non-system, non-managed, non-TX directory at project root containing video files is treated as a scene.
**Warning signs:** `Source/Video/` contains 325 flat MP4s instead of scene subfolders.

### Pitfall 2: TX Folder Regex Mismatch
**What goes wrong:** DJI WAVs in TX02_2/ not detected because regex checks `TX\d{2}` (two digits only) and `TX02_2` has a suffix.
**Why it happens:** `TX02_2` is a second recording session for TX02.
**How to avoid:** TX folder detection regex: `r'^TX\d+'` (one or more digits, stops before `_`). The DJI filename regex `DJI_RAW_RE = r'^TX\d{2}_MIC\d{3}_\d{8}_\d{6}'` already matches the filenames correctly (files inside TX02_2/ are named `TX02_MIC033_...` not `TX02_2_...`).
**Confirmed from reference project:** TX02_2/ contains `TX02_MIC033_20260302_162711_orig.wav` — the filename starts with `TX02_`, which matches `DJI_RAW_RE`. No change needed to the file regex, only to folder detection for nested-project identification.

### Pitfall 3: XML Sidecar Path Missing Scene Layer
**What goes wrong:** XML sidecar `C5089M01.XML` lands at `per_clip/C5089/` instead of `per_clip/volleyball/C5089/`.
**Why it happens:** Current `organize_media_files()` constructs `per_clip / clip_id` with no scene layer.
**How to avoid:** Build `clip_scene_map: dict[str, str]` before organizing — maps each clip stem to its scene. Use it when constructing the sidecar destination path.
**Warning signs:** Downstream `0102_extract_audio` writes `per_clip/C5089/C5089_AUDIO.wav` but sidecars are at `per_clip/volleyball/C5089/C5089M01.XML` — they're in different locations.

### Pitfall 4: GoPro Sub-subfolder in al_qudra_lake
**What goes wrong:** `al_qudra_lake/100GOPRO/GX010001.MP4` — the GoPro files are in a nested subfolder within the scene. Using `clip.relative_to(scene_dir)` correctly preserves this as `al_qudra_lake/100GOPRO/GX010001.MP4` in `Source/Video/`. But a flat rglob without relative path preservation would flatten it.
**How to avoid:** When moving clips, use `rel = clip.relative_to(scene_dir)` and construct `dest = video_dir / scene_name / rel` to preserve the GoPro subfolder.
**Warning signs:** `al_qudra_lake/100GOPRO/` subfolder missing after organize.

### Pitfall 5: Empty TX Folders Left Behind
**What goes wrong:** After moving all WAVs out of TX01/, TX02/, TX02_2/, those folders remain empty. The `_cleanup_empty_dirs()` function in run_pipeline.py handles this — but only if called.
**How to avoid:** Call `_cleanup_empty_dirs()` (or equivalent) after all moves. Alternatively, include TX folder cleanup explicitly after WAV moves.
**Warning signs:** Empty TX01/, TX02/, TX02_2/ folders remain in project root.

### Pitfall 6: Overwriting Without Backup
**What goes wrong:** If organize is run twice and destination already has files, `shutil.move()` on macOS will overwrite without warning for directories but not for files.
**How to avoid:** Check `dst.exists()` before each move and skip with a warning (already done in existing code). Do NOT overwrite silently.

---

## Code Examples

### Existing: DJI Filename Pattern (run_pipeline.py:90)
```python
# Source: run_pipeline.py line 90
DJI_RAW_RE = re.compile(r'^TX\d{2}_MIC\d{3}_\d{8}_\d{6}', re.IGNORECASE)
# Matches: TX01_MIC001_20260228_102211_orig.wav
# Matches: TX02_MIC033_20260302_162711_orig.wav (from TX02_2/ folder)
```

### Existing: v3.0 Managed Directories Skip (run_pipeline.py:99)
```python
# Source: run_pipeline.py line 99
V3_MANAGED_DIRS = {
    '01_Media', '02_Exports', '03_Shorts', '04_Thumbnail',
    'YouTube', '99_Pipeline',
}
```

### Existing: Scene-Folder Aware Move (run_pipeline.py:531-537)
```python
# Source: run_pipeline.py lines 531-537
for f in discovered["videos"]:
    scene = _get_scene_name(f, project)
    if scene:
        dest = video_dir / scene
    else:
        dest = video_dir
    dest.mkdir(parents=True, exist_ok=True)
```

### Existing: Deep Template Merge (run_pipeline.py:1043-1068)
```python
# Source: run_pipeline.py lines 1043-1068
def _deep_merge_template(template_path: Path, project: Path,
                         log: PipelineLogger) -> int:
    created = 0
    for root, dirs, files in os.walk(template_path):
        rel = Path(root).relative_to(template_path)
        dst_dir = project / rel
        if not dst_dir.exists():
            dst_dir.mkdir(parents=True, exist_ok=True)
            created += 1
        for fname in files:
            if fname == ".gitkeep":
                continue
            # ... copy non-gitkeep files
    return created
```

### New: TX Folder Detection (ORG-01)
```python
TX_FOLDER_RE = re.compile(r'^TX\d+', re.IGNORECASE)

def detect_nested_project(project: Path) -> bool:
    """True when TX01/, TX02/, TX02_2/ etc. exist at project root."""
    return any(
        d.is_dir() and TX_FOLDER_RE.match(d.name)
        for d in project.iterdir()
        if not d.name.startswith('.')
    )
```

### New: Scene Detection for Bare-Name Folders (ORG-02)
```python
def detect_scenes(project: Path) -> list[str]:
    """Return scene folder names: volleyball, apartment, al_qudra_lake, ..."""
    scenes = []
    for d in sorted(project.iterdir()):
        if not d.is_dir(): continue
        if d.name in V3_MANAGED_DIRS: continue
        if d.name in SYSTEM_DIRS or d.name.startswith('.'): continue
        if d.name.lower().startswith(ARCHIVE_PREFIXES): continue
        if TX_FOLDER_RE.match(d.name): continue
        if any(f.suffix.lower() in VIDEO_EXTS
               for f in d.rglob('*') if f.is_file()):
            scenes.append(d.name)
    return scenes
```

---

## v3.0 Folder Template (Complete)

From `YTAI_Folder_Templates/Type2_Production/` (verified by directory scan):

```
ProjectName/
├── 01_Media/
│   ├── Assets/
│   │   ├── Fonts/
│   │   ├── Graphics/
│   │   ├── Music/
│   │   ├── SFX/
│   │   └── Stock/
│   └── Source/
│       ├── Audio/
│       ├── LUT/               ← bright.cube, dark.cube, normal.cube copied here
│       ├── Setup/
│       │   └── logs/
│       ├── Transcription/
│       └── Video/
├── 02_Exports/
├── 03_Shorts/
├── 04_Thumbnail/
│   ├── drafts/
│   └── prompts/
├── 99_Pipeline/
│   └── DJI_Audio/
├── YouTube/
└── PROJECT_NAME.gdoc          ← renamed to {project_name}.gdoc
```

Note: The template does NOT include `Transcription/per_clip/` — that directory is created on-demand by `0102_extract_audio.py` and the XML sidecar mover.

---

## Integration Architecture

### Current State (run_pipeline.py)

```
run_init() [inline in run_pipeline.py]
  ├── _deep_merge_template()       ← creates v3.0 skeleton
  ├── discover_media_files()       ← finds files to organize
  ├── organize_media_files()       ← moves files to v3.0 locations
  ├── create Premiere .prproj      ← copies RYA_example.prproj
  └── rename PROJECT_NAME.gdoc    ← renames gdoc placeholder
```

### Recommended Approach: New Standalone Script

Write `scripts/01_prepare/0100_organize/0100_organize.py` as a standalone script following the pattern of `0102_extract_audio.py`:
- Takes `--project PATH` argument
- Has `--dry-run` flag
- Has `--nested` flag (or auto-detects via TX folder presence)
- Logs to `01_Media/Source/Setup/logs/{project}_organize_{ts}.log`

The existing `run_init()` in `run_pipeline.py` can call this script OR the script can be run independently. Since `run_pipeline.py` already has `run_init()` inline, the lowest-risk approach for Phase 1 is to **extend `run_init()` in-place** with nested-project awareness, while also providing `0100_organize.py` as a standalone script for direct invocation.

**Key decision for planner:** Two valid approaches:
1. Extend `run_init()` inline — less code, one place to change, risk: `run_pipeline.py` grows larger
2. New `0100_organize.py` + call from `run_init()` — follows script-per-stage pattern, testable independently

Either works. The codebase convention is "scripts are independent" which favors option 2.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Scene detection: `^\d{2}_` prefix only | Must extend to bare-name folders | This phase | Core change needed |
| XML sidecar: `per_clip/{clip}/` | New: `per_clip/{scene}/{clip}/` | This phase | Downstream scripts must also use scene layer |
| Init inline in `run_pipeline.py` | No separate organize script | Pre-existing | New `0100_organize.py` adds standalone entry point |

**Not deprecated (still needed):**
- `DJI_RAW_RE` filename pattern — still correct for TX WAV filenames
- `V3_MANAGED_DIRS` skip set — still correct
- `_deep_merge_template()` — no changes needed
- `shutil.move()` for cross-device moves — no changes needed

---

## Open Questions

1. **Approach: extend `run_init()` vs new `0100_organize.py`?**
   - What we know: Both are viable. New script follows existing convention better.
   - What's unclear: Whether `run_pipeline.py` should call the new script as subprocess (like it calls `0102_extract_audio.py`) or import as module.
   - Recommendation: New standalone script, called as subprocess from `run_pipeline.py` in a follow-up (Phase 5 PIPE-01). For Phase 1, the organize script is standalone.

2. **Should scene detection require TX folders to be present (ORG-01), or should it also support projects with bare-name scene folders but no TX?**
   - What we know: ORG-01 says detection is "by presence of TX01/ and/or TX02/". No TX = not nested.
   - Recommendation: TX detection as the trigger for nested mode. If no TX folders, fall back to flat-project behavior (backward compatible).

3. **GoPro subfolder `100GOPRO/` inside `al_qudra_lake/` — preserve as-is or flatten?**
   - What we know: The `100GOPRO/` subfolder structure is a GoPro camera artifact. Preserving it keeps camera-model grouping visible.
   - Recommendation: Preserve relative path from scene root (`al_qudra_lake/100GOPRO/GX01*.MP4` → `Source/Video/al_qudra_lake/100GOPRO/GX01*.MP4`).

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (Python stdlib-friendly; already used in project pattern) |
| Config file | none — needs creation in Wave 0 |
| Quick run command | `python -m pytest scripts/01_prepare/0100_organize/tests/ -x -q` |
| Full suite command | `python -m pytest scripts/01_prepare/0100_organize/tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ORG-01 | TX01/ at root triggers nested mode | unit | `pytest tests/test_organize.py::test_detect_nested_project -x` | Wave 0 |
| ORG-01 | No TX folders → not nested | unit | `pytest tests/test_organize.py::test_detect_flat_project -x` | Wave 0 |
| ORG-02 | volleyball/ clips → Source/Video/volleyball/ | unit | `pytest tests/test_organize.py::test_scene_clips_moved -x` | Wave 0 |
| ORG-02 | al_qudra_lake/100GOPRO/ preserved | unit | `pytest tests/test_organize.py::test_gopro_subfolder_preserved -x` | Wave 0 |
| ORG-03 | TX01/*.wav → 99_Pipeline/DJI_Audio/ flat | unit | `pytest tests/test_organize.py::test_dji_wavs_moved_flat -x` | Wave 0 |
| ORG-04 | C5089M01.XML → per_clip/volleyball/C5089/ | unit | `pytest tests/test_organize.py::test_xml_sidecar_with_scene -x` | Wave 0 |
| ORG-05 | No XML → no error | unit | `pytest tests/test_organize.py::test_no_xml_no_error -x` | Wave 0 |
| ORG-06 | v3.0 folder skeleton created | unit | `pytest tests/test_organize.py::test_folder_skeleton -x` | Wave 0 |

Tests use `tmp_path` (pytest fixture) to create a fake project with minimal files.

### Sampling Rate
- **Per task commit:** `python -m pytest scripts/01_prepare/0100_organize/tests/ -x -q`
- **Per wave merge:** `python -m pytest scripts/01_prepare/0100_organize/tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `scripts/01_prepare/0100_organize/tests/test_organize.py` — covers ORG-01 through ORG-06
- [ ] `scripts/01_prepare/0100_organize/tests/conftest.py` — shared `fake_nested_project` fixture
- [ ] Framework install: `pip install pytest` (in `.venv_ytai`)

---

## Sources

### Primary (HIGH confidence)
- `/Users/romansergeev/YTAI/scripts/run_pipeline.py` — full organize logic, `discover_media_files()`, `organize_media_files()`, `_get_scene_name()`, `DJI_RAW_RE`, `V3_MANAGED_DIRS`, `_deep_merge_template()`, `run_init()`
- `/Users/romansergeev/YTAI/YTAI_Folder_Templates/Type2_Production/` — verified complete folder structure via `find`
- `/Volumes/RYA T7 Black/YTCR01_Arty_Dzis/` — verified reference project structure: 7 scene folders, TX01/TX02/TX02_2/ with exact WAV filenames, `al_qudra_lake/100GOPRO/` subfolder confirmed
- `/Users/romansergeev/YTAI/scripts/01_prepare/0102_extract_audio/0102_extract_audio.py` — per_clip path convention, VIDEO_EXTS set
- `/Users/romansergeev/YTAI/scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py` — DJI_SUBDIR, AUDIO_SUBDIR, CLIPS_SUBDIR constants

### Secondary (MEDIUM confidence)
- `scripts/00_init/01_create_template.py` and `02_apply_template.py` — confirmed as stubs (TODO only), init logic is entirely in `run_pipeline.py`
- `scripts/01_prepare/0101_init_folders/` — confirmed as spec file + `.prproj` template only, no Python script

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all stdlib, all verified in existing codebase
- Architecture: HIGH — core patterns verified by reading actual code; critical gap (SCENE_DIR_RE) confirmed by regex inspection + reference project directory listing
- Pitfalls: HIGH — derived directly from code inspection and reference project structure verification

**Research date:** 2026-03-17
**Valid until:** 2026-04-17 (stable codebase, no external dependencies)
