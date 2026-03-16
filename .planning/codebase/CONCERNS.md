# Codebase Concerns

**Analysis Date:** 2026-03-17

## Tech Debt

**Unimplemented stub modules (8 files):**
- Issue: Several pipeline stages exist as placeholders with only `# TODO: Implement` and `pass` statements
- Files:
  - `scripts/00_init/01_create_template.py` (TODO: Перенести из ytdemo_create_template.py)
  - `scripts/00_init/02_apply_template.py` (TODO: Перенести из ytdemo_apply_to_project.py)
  - `scripts/06_thumbnails/01_title_generator.py`
  - `scripts/06_thumbnails/02_thumbnail_prompts.py`
  - `scripts/06_thumbnails/03_compose.py`
  - `scripts/07_shorts/01_find_moments.py`
  - `scripts/07_shorts/02_export_cuts.py`
  - `scripts/07_shorts/03_generate_captions.py` (TODO: Реализовать)
  - `scripts/04_video_analysis/{01-06}` (6 video analysis modules)
  - `scripts/08_youtube/{01-03}` (3 YouTube metadata modules)
- Impact: Pipeline appears complete but half the stage directories are non-functional. Users will encounter placeholder scripts if they attempt to run phases 04, 06, 07, 08
- Fix approach: Either remove stubs and mark phases as future roadmap, or implement core functionality and move complex logic to separate branches

**Excessive version history and Archive directories:**
- Issue: 15+ versioned backup files and Archive directories consuming disk space and making navigation difficult
- Files:
  - `scripts/02_transcribe/Archive/` (5 versioned transcribe_project files v2.11-2.16)
  - `scripts/05_editing/Archive/` (16 outdated UXP panel versions)
  - `scripts/999_extra/` (7 transcribe versions v2.5-2.10)
  - `scripts/backup/version01/` (nested alpha/archive subdirectories)
  - `scripts/05_editing/Archive/050204_uxp_premiere_brief/` (duplicate UXP implementation)
- Impact: Repository bloat (~5MB), confusing version history, unclear which version is canonical
- Fix approach: Archive → compress into single .tar.gz in separate branch, keep only active implementation in main

**Generated files checked into git:**
- Issue: LUT files and test artifacts appear to be generated or binary assets
- Files: `YTAI_Folder_Templates/Type2_Production/01_Media/Source/LUT/{bright,dark,normal}.cube`
- Impact: Unclear if these are templates or generated. Binary files shouldn't be committed
- Fix approach: Move to `.gitignore` or document as required assets

---

## Known Bugs

**DJI timezone auto-detection may fail silently:**
- Symptoms: DJI audio sync applies wrong timezone offset without warning, resulting in out-of-sync audio
- Files: `scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py` (lines 1060-1120, `auto_detect_tz_offset()`)
- Trigger: When DJI files have very little temporal overlap with video (e.g., short clips)
- Workaround: User must manually specify `--tz-offset` and re-run sync
- Root cause: Fallback when no overlaps found returns `(None, 0, 0)` but calling code doesn't always validate result before using default

**Unhandled async promise chains in UXP JavaScript:**
- Symptoms: Premiere may freeze or crash silently during complex operations
- Files: `scripts/05_editing/0500_uxp/src/ingest/transcriptImporter.js` (lines 94-120, nested try-catch)
- Trigger: When SRT file creation fails but fallback import succeeds without proper error propagation
- Pattern: Empty catch blocks (line 101-102) swallow errors silently
- Fix approach: Implement proper error logging and re-throw unrecoverable errors

**Empty exception handling in try-catch:**
- Symptoms: Silent failures that are hard to diagnose
- Files:
  - `scripts/05_editing/0500_uxp/src/assembly/assemblyBuilder.js` (lines 264-265: `try { ... } catch (ex) { }`)
  - `scripts/05_editing/0500_uxp/src/assembly/assemblyBuilder.js` (line 275: `try { tiName = await ti.getName(); } catch (e) { }`)
- Impact: Errors are silently ignored, making debugging difficult
- Fix approach: Log to logger even on expected errors for debugging capability

---

## Security Considerations

**Dynamic code execution via importlib.util:**
- Risk: Script loads and executes sibling Python module at runtime without validation
- Files: `scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py` (lines 1361-1365)
- Current code: `spec.loader.exec_module(_gen_mod)` for `generate_prproj.py`
- Current mitigation: Only loads from known sibling file path (not user input), file existence check, ImportError fallback
- Recommendations:
  - Keep as-is if generate_prproj.py is trusted (sibling in same directory)
  - Document clearly why dynamic load is needed (cross-compilation of Premiere XML)
  - Add checksum validation or signature verification if risk threshold is higher

**Subprocess calls lack shell escaping validation:**
- Risk: File paths from user projects could contain shell metacharacters
- Files: `scripts/01_prepare/0102_extract_audio/0102_extract_audio.py`, `scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py` (multiple subprocess.run/Popen calls)
- Current mitigation: Uses subprocess.run() with list args (not shell=True), safe from shell injection
- Status: Safe - list-based approach prevents shell injection even with special chars in paths

**No environment variable validation for external service credentials:**
- Risk: HuggingFace token and other credentials loaded but not validated for format
- Files: `scripts/02_transcribe/020101_transcribe/transcribe_project.py` (lines ~400-500, HF_TOKEN loading)
- Current mitigation: Scripts check for token existence but don't validate format
- Recommendations:
  - Add basic format validation (e.g., token length, allowed character ranges)
  - Clear error messages when token is invalid

---

## Performance Bottlenecks

**Memory bloat in transcription diarization:**
- Problem: Global diarization pipeline loads entire audio into memory before processing
- Files: `scripts/02_transcribe/020101_transcribe/transcribe_project.py` (lines ~1100-1200, pyannote pipeline)
- Cause: Pyannote loads full audio as SpeakerDiarization object before inference
- Current behavior: For 2+ hour videos, memory usage can exceed 16GB
- Improvement path: Implement sliding window diarization with overlapping chunks, discard processed segments

**Whisper inference without batching:**
- Problem: Each audio chunk transcribed individually instead of batch processing
- Files: `scripts/02_transcribe/020101_transcribe/transcribe_project.py` (lines ~1400-1500, transcription loop)
- Cause: Per-clip transcription loop, no batch aggregation
- Improvement path: Queue clips into batches of 3-5 based on total duration, feed to Whisper batch_transcribe

**Quadratic timezone offset testing:**
- Problem: Auto-detect tests 53 possible timezones sequentially for every DJI file
- Files: `scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py` (lines 1080-1120)
- Current: 53 offsets × N clips × duration check = ~1-2 min per project
- Improvement path: Binary search on timezone space (coarse grid, then refinement)

**Large file transfers without progress feedback:**
- Problem: File copying (clips to scene directories) can take minutes with no progress display
- Files: `scripts/run_pipeline.py` (lines ~550-700, file copy operations)
- Improvement path: Use shutil.copyfile with callback or implement progress bar for large transfers

---

## Fragile Areas

**DJI sync timeline reconstruction:**
- Files: `scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py` (lines 600-1000, trimming/concatenation logic)
- Why fragile: Complex state machine managing DJI file concatenation across UTC/local time boundary
- Safe modification: Test every timezone edge case (DST transitions, negative offsets, fractional hours)
- Test coverage: 0 unit tests for timezone logic - only manual testing documented
- Risk: Changes to `_build_concat_segments()` or `_apply_concat()` can silently break audio sync without clear failure indication

**JSON format normalization in UXP:**
- Files: `scripts/05_editing/0500_uxp/src/assembly/briefParser.js` (lines 40-170, format detection and normalization)
- Why fragile: Dual-format support (Format A from Claude, Format B from transcript) with ad-hoc type checking
- Safe modification: Add comprehensive tests for each format variant, test missing fields gracefully
- Test coverage: Unit tests exist but don't cover all field combinations
- Risk: Adding new JSON fields could break format detection logic

**Scene-aware directory mirroring:**
- Files: `scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py` (lines 200-400, scene directory creation); `scripts/01_prepare/0102_extract_audio/0102_extract_audio.py` (lines 100-200, parallel logic)
- Why fragile: Two independent implementations that must stay in sync for scene structure
- Safe modification: Extract to shared utility function, test with flat + scene structures
- Test coverage: Manual testing only
- Risk: Changes to either script could cause Audio/Video directory structure mismatch

**Premiere project auto-detection in UXP:**
- Files: `scripts/05_editing/0500_uxp/index.js` (lines 100-400, project detection logic)
- Why fragile: Assumes specific folder structure (01_Media/Source/Setup/), fails silently if missing
- Safe modification: Add explicit validation and clear error messages for missing directories
- Test coverage: No automated tests for path resolution
- Risk: Users with custom folder structures will encounter cryptic "project not found" errors

---

## Scaling Limits

**Single-machine transcription memory ceiling:**
- Current capacity: ~2 hours of video on 16GB RAM machine with GPU
- Limit: Pyannote diarization holds full audio in VRAM, Whisper batching is per-clip
- Scaling path: Implement distributed transcription via Ray or Celery, chunk audio into 30-min segments

**DJI sync timezone search space:**
- Current: 53 timezone candidates tested sequentially
- Limit: ~100 projects/hour on single machine, becomes slow for high-throughput pipelines
- Scaling path: Parallelize timezone testing with multiprocessing.Pool

**Premiere project file size limits:**
- Current: Tested up to 500 clips per sequence
- Limit: UXP API timeouts (~30s) when manipulating sequences >1000 clips
- Scaling path: Implement sequence sharding (A Sequences, B Sequences) at 500-clip boundaries

---

## Dependencies at Risk

**PyTorch/Torch MPS on Apple Silicon (critical):**
- Risk: Pytorch MPS backend has known memory leaks and crashes with large models
- Impact: Transcription jobs crash after ~1 hour on M1/M2/M3 Macs despite 16GB+ RAM
- Current mitigation: No mitigation - code assumes PyTorch works
- Migration plan:
  - Option A: Fall back to CPU when VRAM exhaustion detected
  - Option B: Switch to smaller Whisper model (base instead of large-v3) for Mac
  - Option C: Recommend cloud transcription service for users with limited VRAM

**Pyannote v3.0 API instability:**
- Risk: Pyannote version 3.0 API changed dramatically from v2.x, breaking user installations
- Current code: Locks to exact version in requirements via pip freeze
- Impact: Users who update environment get incompatible API
- Migration plan: Pin to Pyannote v3.x minimum version, add explicit version validation at startup

**Node.js 18+ requirement for UXP tests:**
- Risk: Older versions of Node break npm test suite silently
- Current: No version check in test runner
- Migration plan: Add `.nvmrc` file and npm pretest hook to validate Node version

---

## Missing Critical Features

**No rollback/undo capability:**
- Problem: Once DJI sync or audio extraction runs, there's no way to undo changes without manual file deletion
- Blocks: Users cannot retry with different timezone without starting over
- Workaround: Checkpoint before operations, restore from checkpoint on error
- Fix approach: Implement checkpoint system (`01_Media/Source/Setup/.checkpoints/`) with state snapshots

**No partial pipeline resume:**
- Problem: If transcription fails at stage 5, user must re-run stages 1-4
- Blocks: Long pipelines (2+ hours) fail at end, forcing full restart
- Workaround: Manually copy files and run specific script
- Fix approach: Save stage results with checksums, resume from last successful stage

**No validation of edit_brief.json schema:**
- Problem: If Claude generates invalid brief JSON, UXP silently fails with cryptic error
- Blocks: Users can't debug why Build Assembly doesn't work
- Fix approach: Add strict JSON schema validation before UXP import, report schema violations clearly

---

## Test Coverage Gaps

**DJI timezone auto-detection (high risk):**
- What's not tested: Edge cases (DST transitions, fractional timezones, negative offsets, clips at timezone boundary)
- Files: `scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py`
- Risk: Silent sync failures with wrong timestamps produce invalid audio that's hard to detect
- Priority: HIGH - implement unit tests for `auto_detect_tz_offset()` with mock data

**Scene-aware file organization:**
- What's not tested: Flat vs. scene structure, nested scenes, scene with special characters
- Files: `scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py` (line 79-120, `_scene_out_dir()`)
- Risk: Users with scene structures get wrong file paths
- Priority: MEDIUM - add pytest tests for directory structure logic

**Transcription JSON format normalization:**
- What's not tested: All combinations of optional fields, missing speakers, malformed timecodes
- Files: `scripts/05_editing/0500_uxp/src/assembly/briefParser.js`
- Risk: Edge case JSON formats crash UXP with unhelpful errors
- Priority: MEDIUM - expand test coverage to 100% field combination matrix

**UXP async error propagation:**
- What's not tested: Promise rejection handling, timeout scenarios, concurrent file I/O
- Files: `scripts/05_editing/0500_uxp/src/ingest/transcriptImporter.js`, `scripts/05_editing/0500_uxp/src/assembly/assemblyBuilder.js`
- Risk: Premise freeze/crash on network errors
- Priority: HIGH - add integration tests for async operations

**Premiere project structure validation:**
- What's not tested: Missing bins, malformed sequences, corrupted project metadata
- Files: `scripts/05_editing/0500_uxp/src/assembly/projectScanner.js`
- Risk: UXP panics on malformed projects
- Priority: MEDIUM - add defensive checks and graceful degradation

---

*Concerns audit: 2026-03-17*
