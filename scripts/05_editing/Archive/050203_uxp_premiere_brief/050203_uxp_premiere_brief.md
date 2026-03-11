# YTAI Brief — Changelog

## v1.0.19 (2026-03-07)

### FULL/ROUGH Timeline Toggle
- **Toggle buttons** in toolbar: switch between FULL and ROUGH timeline context
- FULL mode: all segments shown (CUT visible at 80% opacity, not muted)
- ROUGH mode: default — CUT segments muted (current behavior)
- Toggle appears after build completes

### Word Navigation Fix
- **Fixed "fallback" bug**: word clicks now find the **containing segment** (not just segment start match)
- Calculates correct timeline position: `segStart + (wordTime - segInSec)`
- Log shows `Jump (calc)` with offset instead of `Jump (fallback)`

### Dual Position Maps
- FULL timeline positions saved in `APP._fullTimelinePositions` (all 9 segments)
- ROUGH timeline positions saved in `APP._roughTimelinePositions` (5 USE segments)
- Active map (`APP._timelinePositions`) switches with FULL/ROUGH toggle

### Files Changed

| File | Changes |
|------|---------|
| `js/state.js` | Added `activeTimeline`, `_fullTimelinePositions`, `_roughTimelinePositions` |
| `js/build-sequence.js` | Save FULL positions map; ROUGH positions into `_roughTimelinePositions` |
| `js/navigator.js` | Find containing segment for word clicks; compute word offset |
| `index.html` | FULL/ROUGH toggle in toolbar row 2 |
| `index.js` | `switchTimeline()`, toggle handler, FULL-aware text rendering, v1.0.19 |
| `css/styles.css` | `.timeline-toggle`, `.tl-btn`, `.text-seg-cut-full` styles |
| `manifest.json` | Version 1.0.19 |

---

## v1.0.18 (2026-03-07)

### Auto-Build on Load Brief
- **Build runs automatically** after loading `edit_brief.json` — no manual "Build" click needed
- Flow: Load Brief → auto-load transcripts → **auto-build** (import → FULL → ROUGH → trim → color → markers)
- Build button still available for manual re-build

### ROUGH = Only USE Segments (Clean Edit)
- **ROUGH sequence** now contains **only USE segments on V1** — no CUT on V2
- User opens FULL + ROUGH side by side: FULL shows all material, ROUGH shows the final cut
- To add something, user copies manually from FULL

### Log Saving Fixed (Writable Folder Chain)
- **Problem:** `getPluginFolder()` is read-only in UXP Manifest v6
- **Fix:** Writable folder chain: brief folder → data folder → temp folder → plugin folder
- Logs now save next to `edit_brief.json` (or first writable fallback)

### Comprehensive Event Logging
- **All user actions logged:** view mode, word clicks, selection, trim/split/exclude, decisions, filters

### Default Text View
- **Text view is now default** (was Cards)
- CUT segments shown muted (0.45 opacity, red border)

### Files Modified
| File | Change |
|------|--------|
| `index.js` | Auto-build; writable folder chain; event logging; version 1.0.18 |
| `js/build-sequence.js` | ROUGH: no CUT on V2, only USE on V1 |
| `js/state.js` | Default `viewMode: 'text'` |
| `index.html` | Text button active by default |
| `css/styles.css` | CUT segment muted styling |
| `manifest.json` | Version 1.0.18 |

---

## v1.0.17 (2026-03-07)

### FIX: FULL sequence — `tickSec is not defined`

**Root cause:** `tickSec()` was defined locally inside `_trimTrack()` function scope, but called from `_createFullSequence()` which is a separate function. JavaScript scoping means the local function was invisible outside `_trimTrack`.

**Fix:** Moved `tickSec()` to **module scope** (before `_trimTrack`), removed the old local copy. Now both `_trimTrack` (ROUGH) and `_createFullSequence` (FULL) share the same helper.

### Debug Logs → UXP Plugin Folder (always accessible)

- **Reverted** log saving back to UXP plugin folder (`debug_log.txt`) — always accessible at the same path regardless of which project is open
- **New "Snapshot" button** in debug panel: saves timestamped `snapshot_YYYYMMDD_HHMMSS.txt` with full log + current brief state (all segments with decisions, colors, blocks)
- Snapshots accumulate in the plugin folder for debugging history

### Word Exclusion: X / D keys (Premiere-safe)

- **Problem:** Premiere Pro intercepts `Delete`/`Backspace` keys before they reach UXP panels
- **Fix:** Added `X` and `D` keys as reliable alternatives for excluding selected words
- `Delete`/`Backspace` still work as fallback (in case Premiere passes them through)
- Tooltip updated to show keyboard shortcut

### Test Project

- Test project synced to `/Users/romansergeev/YTAI/scripts/05_editing/999_testing_project/YTAI_Edit/`

### Files Modified
| File | Change |
|------|--------|
| `js/build-sequence.js` | `tickSec()` moved to module scope; removed old local copy inside `_trimTrack` |
| `index.js` | `saveDebugToFile()` → plugin folder; `saveSnapshot()` new; X/D keys for word exclusion; version 1.0.17 |
| `index.html` | Snapshot button in debug panel; updated Exclude tooltip |
| `manifest.json` | Version 1.0.17 |

---

## v1.0.16 (2026-03-07)

### CRITICAL FIX: createMoveAction is RELATIVE, not absolute

**Root cause of clips not packing tightly (huge gaps on timeline):**

`createMoveAction(time)` is an ADDITIVE/RELATIVE operation — it shifts the clip BY `time` seconds from its current position. It does NOT set the clip to an absolute position.

**Evidence from v1.0.15 debug log:**
- seg_004: before start=154.8, moveAction(71.6) → start=226.4 (154.8 + 71.6 = 226.4 — ADDED!)
- seg_003: before start=282.2, moveAction(74.6) → start=356.8 (282.2 + 74.6 = 356.8 — ADDED!)

**Fix:**
1. Read current start position: `curStart = await item.getStartTime()`
2. Compute delta: `delta = target - curStart`
3. Move by delta: `createMoveAction(deltaTime)`

Applied to both ROUGH sequence (`_trimTrack`) and FULL sequence (`_createFullSequence`).

**Validation improved:** after-pos check now verifies BOTH trim (in/out) AND position (start) — separate `POS-MISMATCH` and `TRIM-MISMATCH` indicators.

### API Method Semantics (updated)
| Method | Behavior |
|--------|----------|
| `createMoveAction(time)` | **RELATIVE** — shifts clip by `time` from current position. NOT absolute. |
| `createSetStartAction(time)` | **ABSOLUTE** — sets Start=time, adjusts InPoint by delta. |
| `createSetInPointAction(time)` | **ABSOLUTE** — sets source InPoint. |
| `createSetOutPointAction(time)` | **ABSOLUTE** — sets source OutPoint. |

### Debug Log: Save to Project Folder with Timestamps
- **Logs now save next to `edit_brief.json`** (in the project directory, e.g. `/Users/romansergeev/Desktop/YTAI_Edit/`)
- **Timestamped filenames**: `debug_log_183029.txt` (HHMMSS format) — each Build creates its own file, no overwrite
- **Fallback**: if no brief loaded, saves to plugin folder with overwrite (as before)
- **Visibility**: logs are now in the project folder, easily accessible from Finder

### Auto-Load Transcripts
- **Transcripts load automatically** when a brief is loaded (if `_transcription_dir` is set in the brief's project settings)
- **No more "Load Text" button needed** — word-level editing is available immediately in Text view
- "Load Text" button still works for manual re-loading

### Delete Key for Word Exclusion
- **Delete** or **Backspace** key now excludes selected words (same as the Exclude button)
- Selection at start → shifts inSec forward
- Selection at end → shifts outSec backward
- Selection in middle → splits segment
- Full selection → marks as CUT

### Files Modified
| File | Change |
|------|--------|
| `js/build-sequence.js` | createMoveAction delta fix (ROUGH + FULL); improved position validation |
| `index.js` | saveDebugToFile to project folder; auto-load transcripts; Delete key; version 1.0.16 |
| `manifest.json` | Version 1.0.16 |

---

## v1.0.15 (2026-03-07)

### FULL Sequence Ordering Fix
- **Sort by block order** (same as ROUGH) instead of source file order — segments now appear in the correct narrative sequence
- **`insertedSegs[]` parallel array** — when a clip is skipped (source file not found), trim/color/marker loops no longer misalign with track items

### Color Strategy Improvement
- **Color tag in clip names**: USE clips are named `[Green] seg_001 Hook` instead of `seg_001 Hook` — color visible even when ProjectItem color gets overwritten by shared sources
- **CUT clips** include block name: `[CUT] seg_007 Cut`
- **Shared-source warning**: log message when the same source file is used in multiple blocks with different colors (ProjectItem color = last write wins)

### UI Improvements
- **Panel size**: `minimumSize: 320x450`, `preferredDockedSize: 420x700` (was 300x400, 380x600)
- **Font size**: body 13px (was 12px), buttons 12px (was 11px), view tabs 11px (was 10px)
- **Spacing**: toolbar gap 6px (was 4px), button padding 6px 14px (was 5px 12px), segment cards 8px (was 7px)
- **Border radius**: buttons use 6px (was 4px), smooth transitions on hover
- **Stats bar**: larger values (15px), wider gaps (16px)
- **Empty state**: more spacious (60px padding, 28px icon)
- **Tooltips**: all buttons have descriptive title attributes explaining their purpose

### Word Selection + Trim (Text View)
- **Click** a word → jump to that moment in timeline, start selection
- **Shift+Click** → extend selection to form a word range
- **Escape** → clear word selection
- **Trim toolbar** appears when words are selected:
  - **Trim** — trim segment boundaries to selected word range (inSec/outSec = word boundaries)
  - **Split** — split segment into two at the selection boundary (creates `seg_XXX_b`)
  - **Exclude** — remove selected words (shifts inSec forward or outSec backward; middle selection triggers split)
- **Visual feedback**: selected words highlighted in blue, range markers on first/last word
- **State**: `APP._wordSelection = { segId, startIdx, endIdx }`

### Files Modified
| File | Change |
|------|--------|
| `js/build-sequence.js` | FULL sort by block; `insertedSegs[]` parallel array; color tags in clip names; shared-source warning |
| `js/state.js` | Added `_wordSelection` to APP state |
| `index.js` | `_getWordsForSegment()` refactor; word selection interaction; trim/split/exclude operations; version 1.0.15 |
| `index.html` | Word trim bar; tooltips on all buttons |
| `css/styles.css` | UI sizing improvements; word selection styles; trim bar styles |
| `manifest.json` | Version 1.0.15; panel size 420x700 |

---

## v1.0.14 (2026-03-07)

### CRITICAL FIX: Clip Trimming — `createMoveAction` instead of `createSetStartAction`

**Root cause of broken trim (all InPoints wrong, clips overlapping):**

In Premiere UXP 25.3, `createSetStartAction(time)` is a **left-edge trim**, not a simple move:
- It sets `Start = time` AND adjusts `InPoint += (time - oldStart)`
- This means repositioning a clip after trimming **corrupts the source InPoint**

**Evidence from YTAI_Edit_7.prproj analysis:**
- seg_001 (inSec=0): InPoint=0 ✓ (no in-point change needed, so no corruption)
- seg_004 (inSec=73.4): InPoint=-9.8 ✗ (= targetPos - insertPos = 71.6 - 81.4)
- seg_003 (inSec=119.4): InPoint=-88.2 ✗ (= targetPos - insertPos = 74.6 - 162.8)
- Pattern: every InPoint = targetPos - insertPos (NOT the correct source timecode)

**Fix:**
- Use `createMoveAction(targetPos)` for repositioning — relocates clip on timeline WITHOUT modifying InPoint/OutPoint
- `createSetStartAction` only used as fallback, with post-correction re-applying InPoint/OutPoint
- Applied to both ROUGH sequence (`_trimTrack`) and FULL sequence (`_createFullSequence`)

**After-reposition logging** now includes InPoint/OutPoint verification with ✓/✗ indicator.

### API Method Semantics (discovered)
| Method | What it does |
|--------|-------------|
| `createSetOutPointAction(time)` | Sets source OutPoint, adjusts End. Start/InPoint unchanged. **WORKS CORRECTLY** |
| `createSetInPointAction(time)` | Sets source InPoint, may adjust Start. End/OutPoint unchanged |
| `createSetStartAction(time)` | Left-edge trim: Start=time, InPoint+=delta. End/OutPoint unchanged. **DO NOT USE FOR REPOSITIONING** |
| `createMoveAction(time)` | Relocates clip to time on timeline. InPoint/OutPoint unchanged. **USE FOR REPOSITIONING** |

### Files Modified
| File | Change |
|------|--------|
| `js/build-sequence.js` | `_trimTrack()`: createMoveAction replaces createSetStartAction; `_createFullSequence()`: same fix |
| `index.js` | Version 1.0.14 |
| `manifest.json` | Version 1.0.14 |

---

## v1.0.13 (2026-03-07)

### Debug Auto-Save to Plugin Folder
- **Debug log now auto-saves** to `debug_log.txt` in the plugin folder after every Build and Transcript load
- File is overwritten each time — always contains the latest session log
- Developer can read it directly from `/Users/romansergeev/YTAI/scripts/05_editing/050203_uxp_premiere_brief/debug_log.txt`
- Also available as manual "Save" button in the Debug panel
- Clipboard copy still works as before

### UX/UI Cleanup
- **Renamed buttons** for clarity:
  - "Build Sequence" → "Build" (shorter)
  - "Transcripts" → "Load Text" with tooltip explaining what it does
  - "Set" → gear icon (&#9881;)
  - "Debug" → "Log" (shorter, with tooltip about auto-save)
- **Added tooltips** to all view mode buttons (Cards/Text/Min) explaining purpose and hotkeys
- **Added "Save" button** in Debug panel to manually save log to file
- **Removed redundant "Set" label** from first toolbar row (settings accessible via gear icon)

### Fix: Transcript Button Re-Render
- **Problem**: "Load Text" button loaded transcript data into `APP._transcriptData` but did NOT re-render the view
- **Fix**: After loading transcripts, now calls `renderTextView()` if in Text mode
- Also logs guidance: "Switch to Text view to see word-level editing"
- Debug log auto-saved after transcript loading too

### Fix: Dangling Braces in `_getTrackItems` (from v1.0.12)
- Removed stray `}` and `} catch` from old Strategy 3 code — would have caused syntax error preventing plugin from loading

### Button Reference
| Button | What it does |
|--------|-------------|
| **Load Brief** | Opens file picker to load `edit_brief.json` |
| **Save** | Saves reviewed decisions back to JSON |
| **R** | Reloads the same brief file from disk |
| **Cards** | Card view: shows segment cards with transcript preview (hotkey: 1) |
| **Text** | Text editor: word-level transcript with click-to-jump navigation (hotkey: 2) |
| **Min** | Compact list: minimal view with just headers (hotkey: 3) |
| **Build** | Builds FULL + ROUGH sequences in Premiere with trim, color, markers |
| **Load Text** | Loads transcript JSON files for word-level editing in Text view |
| &#9881; | Opens settings: Source Folder, API Test |
| **Log** | Opens debug log panel (auto-saved to plugin folder after builds) |

### Files Modified
| File | Change |
|------|--------|
| `index.js` | `saveDebugToFile()`, auto-save on build-done, transcript re-render, version 1.0.13 |
| `index.html` | Button rename, tooltips, gear icon, Save button in debug panel |
| `manifest.json` | Version bump to 1.0.13 |

---

## v1.0.12 (2026-03-07)

### CRITICAL DISCOVERY: ALL TrackItem Getters Return PROMISES

**Root cause of EVERY bug since v1.0.4** — in Premiere UXP 25.3, ALL `TrackItem` getter methods return **Promises**, not direct values:
- `getStartTime()` → Promise (not TickTime)
- `getEndTime()` → Promise
- `getInPoint()` → Promise
- `getOutPoint()` → Promise
- `getDuration()` → Promise
- `getName()` → Promise (not string)
- `getType()` → Promise (not number)
- `isDisabled()` → Promise (not boolean)
- `getProjectItem()` → Promise (not ProjectItem)

**Evidence from v1.0.11 debug log:**
```
V1 TickTime probe: proto.constructor=function, proto.then=function, proto.catch=function,
proto.finally=function, toString=[object Promise], typeof=object, JSON={}
```
The "TickTime" was actually a Promise object the whole time!

**Only `createXXXAction()` methods are synchronous** — they return Action objects immediately, which is why trim/color/disable still partially worked.

### Fix: Massive `await` Refactor

**`_getTrackItems()` → `async function`** with `await` on ALL filter checks:
- `await fItem.isDisabled()` — previously returned Promise (truthy → ALL items marked "disabled" → fell through to raw list)
- `await fItem.getName()` — was showing `[object Promise]` instead of clip name
- `await fItem.getType()` — was always a truthy Promise, never actually filtered by type
- `await fItem.getProjectItem()` — was always truthy Promise, never detected null for fillers

**All 5 call sites updated:**
- FULL sequence ghost handling
- `_trimTrack()` — before trim (line ~1107)
- `_trimTrack()` — AFTER ALL verification (line ~1390)
- `_colorTrack()` — color application (line ~1431)
- `testAPIs()` — debug probe (line ~2000)

### Fix: TickTime Probe

- Now uses `await trackItems[0].getStartTime()` — previous probe was reading properties of a Promise, not actual TickTime
- v1.0.12 probe will finally reveal real TickTime structure (`.seconds`, `.ticks`, etc.)

### Fix: BEFORE TRIM Logging

- All getters now awaited: `tickSec(await di.getStartTime())`, `await di.getName()`, etc.
- Will show actual numeric values instead of "error reading: Cannot read properties of undefined"

### Fix: After-Trim State Logging

- **after-OUT**: `tickSec(await item.getStartTime())`, etc. — actual state after `createSetOutPointAction`
- **after-IN**: `tickSec(await item.getStartTime())`, etc. — actual state after `createSetInPointAction`
- **after-pos**: `tickSec(await item.getStartTime())`, etc. — actual state after `createSetStartAction`
- **AFTER ALL**: `tickSec(await ai2.getStartTime())`, `await ai2.getName()` — final verification

### Fix: Ghost Handling (FULL + ROUGH)

- `await ghostF.getType()` / `await ghostR.getType()` — now actually gets the type value
- `await ghostF.getProjectItem()` / `await ghostR.getProjectItem()` — now actually detects null for fillers
- Previously: all checks got Promise objects (truthy) → tried to disable fillers → "Invalid parameter"

### Fix: Color Track

- `await item.getProjectItem()` in `_colorTrack()` — was getting Promise instead of actual ProjectItem
- Now correctly retrieves ProjectItem for `createSetColorLabelAction(colorIndex)`

### Impact

This fix should resolve:
1. **Clip trimming** — `_getTrackItems` now returns correct filtered list; logging shows actual before/after values
2. **Ghost "Invalid parameter"** — fillers correctly detected (getProjectItem()===null) and skipped
3. **10 items instead of 5** — filter now actually works (isDisabled returns boolean, not Promise)
4. **All logging was empty/error** — getters return actual values, tickSec() gets real TickTime

### Files Modified
| File | Change |
|------|--------|
| `js/build-sequence.js` | `_getTrackItems` → async, ALL getter calls → await, ghost handling, trim logging, color track |
| `index.js` | Version bump to 1.0.12, debug log header updated |
| `manifest.json` | Version bump to 1.0.12 |

---

## v1.0.11 (2026-03-07)

### Analysis of v1.0.10 Debug Log + prproj
- **`tickSec()` returned `undefined`** → `.toFixed()` crashed → ALL BEFORE/AFTER logging was empty
  - Root cause: `getStartTime().seconds` does NOT exist on TickTime in Premiere UXP 25.3
  - All 10 V1 items showed "error reading: Cannot read properties of undefined"
- **Ghost disable → "Invalid parameter"** — `createSetStartAction(30000s)` fails with large time values
  - Both FULL and ROUGH ghost disabling failed silently
- **Auto-inserted clip NOT removed** — `createRemoveAction` doesn't exist, log said "Cleared" but nothing happened
  - This left extra clips on V1: 10 items instead of expected 5
- **prproj analysis of YTAI_Edit_5.prproj** confirmed:
  - `createSetOutPointAction()` → OutPoints ARE correct (76.4, 151.9, 106.2, 117.7)
  - `createSetInPointAction()` → InPoints ARE WRONG (negative values: -7.6, -6.8, -51.3, 20.5)
  - `createSetStartAction()` → Timeline positions ARE correct (71.6, 74.6, 107.1, 183.3)
  - seg_001 (inSec=0) is the ONLY correctly trimmed clip — all others have wrong durations

### Fix: `tickSec()` — Robust TickTime Reading
- Now tries 5 access patterns: `.seconds`, `.secs`, `.ticks/254016000000`, `bigint ticks`, `parseFloat(String(tt))`
- Returns `-1` only if ALL patterns fail (no more `undefined`)
- **TickTime probe**: Enumerates all own+proto properties of `getStartTime()` result — will reveal exact TickTime structure

### Fix: `_getTrackItems()` — Proper Filler + Auto-Clip Filtering
- **Strategy 0**: Skip items where `isDisabled() === true` (catches disabled auto-inserted clips)
- **Strategy 0b**: Skip items named `[AUTO-SKIP]` or `[GHOST]`
- **Strategy 2 improved**: Actually CALLS `getProjectItem()` and checks for null (not just checks function existence)
- **Strategy 3 improved**: Uses same robust tick-reading as `tickSec()` for duration check
- **Detailed filter log**: Shows exactly WHY each item was filtered (disabled, name, type, projItem=null, dur=0)

### Fix: Auto-Inserted Clip Removal (FULL + ROUGH)
- **Problem**: `createRemoveAction` doesn't exist → transaction ran with 0 actions → log falsely said "Cleared"
- **Solution**: Fallback: `createSetDisabledAction(true)` + `createSetNameAction('[AUTO-SKIP]')`
- Combined with `_getTrackItems` filter, disabled auto-clips are now invisible to trim/color code
- Gets raw items directly (not via `_getTrackItems`) to avoid chicken-and-egg filtering

### Fix: Ghost Disable — Removed `createSetStartAction(30000s)`
- **Problem**: Moving ghosts to 30000+ seconds caused "Invalid parameter" (value too large for TickTime?)
- **Solution**: Just disable + rename `[GHOST]` — no move. `_getTrackItems` filter handles the rest

### Enhanced Trim Logging
- **TickTime verification**: Logs `tickSec(srcIn)` and `tickSec(srcOut)` after `createWithSeconds()` to verify values
- **after-OUT**: Logs full state (start/end/in/out/dur) immediately after `createSetOutPointAction` — reveals if OUT trim works
- **after-IN**: Logs full state after `createSetInPointAction` — reveals if IN trim works and how it affects other values
- Error messages now shown instead of silently swallowed

---

## v1.0.10 (2026-03-07)

### Detailed Per-Clip Debug Logging in `_trimTrack()`
- **BEFORE TRIM**: Logs every track item's `getStartTime()`, `getEndTime()`, `getInPoint()`, `getOutPoint()`, `getDuration()`, `getName()` — full state snapshot before any modifications
- **Per-clip trim detail**: For each segment being trimmed, logs:
  - Source in/out points (`seg.inSec → seg.outSec`)
  - Target timeline position (`seg._timelineStart`)
  - **After-trim intermediate**: actual start/end/in/out/dur after OUT+IN trim
  - **After-reposition**: actual start/end/dur after `createSetStartAction()`
- **AFTER ALL**: Re-reads all track items and logs final state — allows comparison with BEFORE to see exactly what changed
- Now shows `canSetStart` and `canMove` capability flags

### Fix: Separated Trim Transactions
- **Problem**: Setting OUT, IN, and START in a single transaction may cause conflicts
- **Solution**: Each operation now runs in its own `lockedAccess → executeTransaction` call:
  1. `createSetOutPointAction()` — shrinks from right (no position shift)
  2. `createSetInPointAction()` — moves left edge inward
  3. `createSetStartAction()` — repositions to target timeline position
- Each step has its own transaction name for easier debugging in Premiere

### Fix: Ghost Clip Removal Fallback
- **Problem**: `createRemoveAction` does NOT exist on `TrackItem` proto — confirmed by debug enumeration in v1.0.9
- **Solution**: Explicit `typeof createRemoveAction === 'function'` check with fallback:
  - If available: use `createRemoveAction()` (future-proof)
  - If NOT available: disable ghost + rename to `[GHOST] remove` + move to position 30000s+ (far beyond real content)
- Applied in BOTH `_trimTrack()` (ROUGH) and `_createFullSequence()` (FULL)
- Logs `createRemoveAction=true/false` for diagnostics

### Files Modified
| File | Change |
|------|--------|
| `js/build-sequence.js` | `_trimTrack()` rewrite: separated transactions, before/after logging, ghost fallback |
| `js/build-sequence.js` | FULL ghost removal: same fallback approach |
| `index.js` | Version bump to 1.0.10, debug log header updated |
| `manifest.json` | Version bump to 1.0.10 |

---

## v1.0.9 (2026-03-07)

### Compared with reference project (YTCG 35_2_1)
- **Reference analysis**: 38 SubClips on V1, each with unique label color per block (8 chapters × 8 colors)
- **Root cause of color issue**: `ProjectItem.createSetColorLabelAction()` changes the SOURCE CLIP color, not the timeline instance. All instances of the same source file get the SAME color.
- **Reference solution**: Uses nested sequence → SubClips (each a unique ProjectItem) → per-instance colors

### Critical Fix: Clip Naming on Timeline (ROUGH + FULL)
- **Problem**: `_colorTrack()` only renamed clips in Strategy 3 (fallback). If `createSetColorLabelAction` succeeded, rename was SKIPPED → ROUGH clips showed "C5403.MP4" instead of "seg_001 Hook"
- **Solution**: `createSetNameAction()` now runs ALWAYS for every clip, regardless of color strategy
- ROUGH V1 clips now show: `seg_001 Hook`, `seg_004 Government Vision`, etc.
- ROUGH V2 clips now show: `[CUT] seg_002`, `[CUT] seg_007`, etc.
- **Files**: `js/build-sequence.js` → `_colorTrack()`

### Critical Fix: Ghost/Leftover Clips Removed
- **Problem**: Wide insert spacing + trim/reposition left ghost clips beyond expected segment count
  - FULL V1: 18 items instead of 9 (9 ghost clips at positions 639s-1191s)
  - ROUGH V1: 10 items instead of 5
- **Solution**: After trim+reposition, count actual track items vs expected. Remove extras via `createRemoveAction()`
- Also cleans corresponding audio track ghosts
- **Files**: `js/build-sequence.js` → `_trimTrack()`, `_createFullSequence()`

### Fix: Color Strategy Order (CUT before USE)
- **Problem**: CUT segments (Red=16) processed AFTER USE → Red color overwrote block colors on shared sources
- **Solution**: Process CUT first, then USE. Last write wins → USE block colors survive for shared ProjectItems
- Both FULL and ROUGH now apply colors in order: V2/CUT → V1/USE
- **Files**: `js/build-sequence.js` → `_applyColors()`, FULL color pass

### Debug: API Probes for SubClip Creation
- Enumerates `Project` proto methods (looking for `createSubClip`, `createBinItem`, etc.)
- Enumerates `ClipProjectItem` proto methods (looking for `createSubClipAction`, etc.)
- Results will reveal if UXP API supports per-instance coloring via SubClips

### Known Limitation: Per-Instance Color
- `createSetColorLabelAction` sets color on source clip → all instances same color
- The last USE segment's color wins for each source file
- True per-block coloring requires SubClip support (not yet confirmed in UXP 25.3)
- Clip NAMES always show block info regardless of color limitation

---

## v1.0.8 (2026-03-07)

### Block-Level Chapter Markers (like reference project)
- **Analyzed reference project** (`YTCGRU_4_3_Пять_ошибок_при_открытие_счета_1.prproj`):
  - Uses **Chapter markers** on sequence timeline with block names (HOOK, SETUP, ОШИБКА №1-5, ФИНАЛ)
  - Each chapter has a **color** and spans the **full duration** of that block
  - Clips are colored to match their chapter block
- **Before**: Markers had `duration = 1 second` → appeared as tiny dots on timeline
- **After**: Markers span the **full block duration** → appear as colored chapter blocks (like YouTube chapters)

### ROUGH Sequence Markers
- `_createMarkers()` now calculates per-block `duration` (sum of segment durations)
- Uses `MARKER_TYPE_CHAPTER` type for all block markers
- Each block marker: `start = block start`, `duration = block total duration`
- Detailed logging: block name, start, end, duration, segment count, color

### FULL Sequence Markers (2-level)
- **Level 1: Block chapter markers** — span the entire block duration (like reference)
- **Level 2: Segment comment markers** — per USE segment with speaker + transcript excerpt
- Block markers built from ALL segments (USE + CUT) to cover full timeline
- **Files**: `js/build-sequence.js` → `_createMarkers()`, `_createFullSequence()`

### Debug: Markers API Probe
- Enumerates `Markers` proto and `Marker` constants on each build
- Will reveal if marker color methods exist in UXP API

---

## v1.0.7 (2026-03-07)

### Critical Fix: REAL Color Labels! (`createSetColorLabelAction`)
- **Discovery**: Debug log revealed `createSetColorLabelAction:function` exists on `ProjectItem` proto!
- **Before**: Code checked for `setColorLabel`, `setLabelColor`, `createSetLabelAction` (wrong names) → fell through to rename fallback
- **After**: Uses `TrackItem.getProjectItem()` → `ProjectItem.createSetColorLabelAction(colorIndex)` — sets **actual Premiere color labels**
- Now clips on the timeline show real Premiere colors (Green for Hook, Blue for Government Vision, Orange for Client Story, Red for CUT)
- Updated `LABEL_COLOR_INDEX` to match Premiere Pro 25.x actual indices (Green=13, Blue=9, Red=16, etc.)
- **Files**: `js/build-sequence.js` → `_colorTrack()`, FULL sequence coloring

### Critical Fix: Track Items Double Count (18 instead of 9)
- **Problem**: `getTrackItems(CLIP_TYPE, false)` returned **filler/gap items** between real clips, doubling the count (18 instead of 9 in FULL, 10 instead of 5 in ROUGH)
- **Cause**: Wide insert spacing created gaps between clips. `false` param included empty/filler items.
- **Solution**: `_getTrackItems()` now filters results:
  1. Check `getType()` — skip non-CLIP items
  2. Check `getProjectItem()` — filler items don't have project items
  3. Check `getDuration()` — skip zero-duration items
- Logs filter count: "18 raw → 9 clips (filtered 9 fillers)"

### Fix: Transcript Import (`clipItem not found`)
- **Problem**: `_scanBin()` stored project items only by `item.name` (e.g., "C5403.MP4"), but transcript lookup used `clipId` = "C5403" (without extension)
- **Solution**: `_scanBin()` now stores under BOTH `name` AND `name without extension`
- Also fixes transcript re-import after builds where clips move between bins

---

## v1.0.6 (2026-03-06)

### Critical Fix: Clip Positioning (gaps between clips)
- **Problem**: `createSetInPointAction(inSec)` shifts the clip's left edge on the timeline by `inSec` seconds. When inserting full-length clips at positions based on segment duration, clips ended up at wrong positions with large gaps between them.
- **Root cause**: Full source clips (e.g., 155s) were inserted at tight positions (e.g., 71.6s apart), causing overlaps. After trim, the in-point shift created gaps.
- **Solution (2-part fix)**:
  1. **Wide insert spacing**: Insert full clips with gaps = full source duration + 5s padding, preventing overlaps during insertion
  2. **Explicit repositioning**: After trim, call `createSetStartAction(targetPos)` (fallback: `createMoveAction`) to move each clip to its correct tight position
- **Files**: `js/build-sequence.js` → `_trimTrack()`, `_createFullSequence()`, `_createRoughSequence()`

### Fix: FULL Sequence auto-inserted clip
- Added removal of auto-inserted clip from `createSequenceFromMedia` in FULL sequence (same as ROUGH had)

### Debug improvements
- Logs `createSetStartAction` / `createMoveAction` availability
- Logs positioned count alongside trimmed count

---

## v1.0.5 (2026-03-06)

### Fix: Label Colors (was 0/5)
- **Problem**: `VideoClipTrackItem` does not have `createSetColorByIndexAction` or `createSetLabelAction` methods in Premiere Pro 25.3 UXP API.
- **Solution**: 3-strategy cascade:
  1. Try `TrackItem.createSetColorByIndexAction()` (in case future API adds it)
  2. Try `TrackItem.getProjectItem()` → `ProjectItem.setColorLabel()` / `createSetLabelAction()`
  3. **Fallback**: `TrackItem.createSetNameAction()` — renames clip to `[Green] seg_001 Hook / Intro / CTA` so block/color info is visible on timeline
- **File**: `js/build-sequence.js` → `_colorTrack()`

### Fix: Transcript Import (was "Failed to parse input string into JSON")
- **Problem**: Our transcript JSON had 4 Adobe schema violations:
  1. Word `start`/`duration` in **milliseconds** (100, 280) instead of **seconds** (0.1, 0.28)
  2. Segment field `speakerId` instead of `speaker` (`additionalProperties: false` rejects it)
  3. Missing segment-level `start` field (required)
  4. Missing segment-level `duration` field (required)
  5. Extra word fields (`eos`, `tags`) rejected by `additionalProperties: false`
- **Solution**: New `_normalizeTranscriptForAdobe(tData)` function:
  - Detects ms vs sec (heuristic: if any `word.start > 100` → milliseconds)
  - Converts all timestamps to seconds with 3 decimal precision
  - Renames `speakerId` → `speaker`, deletes `speakerId`
  - Calculates segment `start` (first word start) and `duration` (last word end - first word start)
  - Strips extra word fields, keeps only: `text`, `start`, `duration`, `confidence`, `type`
  - Builds `speakers[]` array from unique speaker IDs
- **File**: `js/build-sequence.js` → `_normalizeTranscriptForAdobe()`

### New: Text-Based Editing (MVP)
- Word-level transcript rendering in Text View (hotkey `2`)
- Each word rendered as `<span class="tw" data-t="0.123">word</span>`
- **Click any word** → jumps Premiere playhead to that word's timecode
- Visual indicators:
  - Hover: subtle highlight
  - Active word: blue highlight
  - Low confidence words: italic + dotted underline
  - Punctuation: dimmed, non-clickable
- Words sourced from `APP._transcriptData[clipId]` (loaded during transcript import)
- Falls back to plain text if no word-level data available
- **Files**: `index.js` → `renderTextSegment()`, `_renderWordsForSegment()`, event delegation; `css/styles.css` → `.tw` styles

### Redesign: FULL Sequence Layout
- **Before**: Full clips inserted end-to-end (no trimming)
- **After**: ALL segments inserted chronologically, each as a separate trimmed clip:
  - **USE segments**: enabled, renamed with color tag `[Green] seg_001 Block_Name`, markers added
  - **CUT segments**: disabled (greyed out on timeline), renamed `[CUT] seg_003`
  - Markers on each USE segment showing block name + transcript excerpt
- Editor can now visually see the full source material with USE segments highlighted
- **File**: `js/build-sequence.js` → `_createFullSequence()`

### Internal
- `js/state.js`: Added `APP._transcriptData = {}` and `APP._wordCuts = {}` for word-level editing data
- `BUS.emit('transcripts-loaded')` event after transcript loading completes
- Better debug logging: transcript JSON preview on error, color strategy reporting

---

## v1.0.4

### Working Features
- Auto-detect source folder from brief file path
- `createSequenceFromMedia()` for 4K/fps inheritance
- `await seq.getVideoTrack(index)` — fixed async handling
- `track.getTrackItems(Constants.TrackItemType.CLIP, false)` — correct params
- TrackItem trim via `createSetInPointAction` / `createSetOutPointAction`
- V2 disable via `createSetDisabledAction`
- Chapter markers with `Markers.getMarkers(seq)` + `createAddMarkerAction()`
- Import 3/3 clips, ROUGH sequence: V1 USE trimmed, V2 CUT disabled

### Known Issues (fixed in 1.0.5)
- Label colors: 0/5 (no color methods on TrackItem)
- Transcript import: "Failed to parse input string into JSON"
- FULL sequence: full clips not trimmed

---

## JSON Formats

### Edit Brief (Format A)
```json
{
  "project": {
    "project_name": "YTAI_Edit",
    "fps": 23.976,
    "_transcription_dir": "YTAI_Edit_transcription"
  },
  "segments": [
    {
      "segment_id": "seg_001",
      "source_file": "C5403.MP4",
      "tc_in": "00:00.0",
      "tc_out": "01:11.6",
      "block": 1,
      "block_name": "Hook",
      "color": "Green",
      "use": "TRUE",
      "transcript": "Long story short...",
      "speaker": "Roman"
    }
  ]
}
```

### Transcript for Adobe (after normalization)
```json
{
  "language": "en-us",
  "speakers": [{ "id": "UUID", "name": "Speaker 1" }],
  "segments": [
    {
      "language": "en-us",
      "speaker": "UUID",
      "start": 0.0,
      "duration": 3.79,
      "words": [
        { "text": "Long", "start": 0.0, "duration": 0.1, "confidence": 0.74 },
        { "text": "story", "start": 0.1, "duration": 0.18, "confidence": 0.97 }
      ]
    }
  ]
}
```

**Key rules**: No extra fields (Adobe uses `additionalProperties: false`). Timestamps in seconds. `speaker` not `speakerId`. Segment needs `start` + `duration`.

---

## Premiere Pro UXP API Reference (25.3+)

### TrackItem Available Methods
```
createSetInPointAction, createSetOutPointAction, createMoveAction,
createSetStartAction, createSetEndAction, createSetDisabledAction,
createSetNameAction, getProjectItem, getComponentChain,
getInPoint, getOutPoint, getStartTime, getEndTime, getDuration
```

### TrackItem NOT Available
```
createSetColorByIndexAction, createSetLabelAction
```

### Key API Patterns
- `seq.getVideoTrack(index)` → **returns Promise**, must `await`
- `track.getTrackItems(Constants.TrackItemType.CLIP, false)` → needs 2 params
- `lockedAccess(() => executeTransaction((ca) => ca.addAction(action)))` — callbacks are **synchronous**
- `project.createSequenceFromMedia(name, [clipItem])` — inherits media settings (4K, fps)
- Transcript: `importFromJSON(string)` → TextSegments, then `createImportTextSegmentsAction(textSegments, clipItem)` → Action
