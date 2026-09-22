/**
 * Scene layout planner — pure logic for wall-clock placement.
 *
 * Pure module: no UXP imports. Unit-testable under Node.
 * Used by wallClockBuilder.js.
 *
 * Public API:
 *   - parseUtcISO(str)         → Date or throws (strict ISO 8601 with TZ)
 *   - computeSceneT0(clips, txStrips) → unix seconds (float)
 *   - computeOffsetSec(clip, t0) → seconds (float)
 *   - computeVideoUnion(videoPlacements) → [[start, end], ...] merged intervals
 *   - plan(sceneClips, txStrips, camLayersOverride) → Plan object
 *
 * Plan object shape:
 *   {
 *     scene_t0: number,              // unix seconds
 *     cam_layers: { camName: vIdx },
 *     tx_aIdx_base: number,
 *     placements: [
 *       { kind: 'video', clipId, filename, vIdx, aIdx, offsetSec, duration },
 *       { kind: 'tx',    txId,   filename, vIdx: -1, aIdx, offsetSec, duration, sourceInPoint }
 *     ],
 *     warnings: [{ type, ... }]
 *   }
 */

const { deriveCamLayers, camOfClip } = require('./cameraResolver');

const TICKS_PER_SECOND = 254016000000;

/**
 * Exact ticks-per-frame for a given fps. NTSC rates are rational (x*1000/1001)
 * and MUST use the exact tick counts Premiere uses — dividing 254016000000 by
 * the float 29.97 gives a non-integer garbage grid.
 *
 * @param {number} fps
 * @returns {number} integer ticks per frame
 */
function ticksPerFrameForFps(fps) {
  const NTSC = {
    '23.976': 10594584000,  // 254016000000 × 1001/24000
    '29.97': 8475667200,    // × 1001/30000
    '59.94': 4237833600,    // × 1001/60000
    '119.88': 2118916800,   // × 1001/120000
  };
  const key = String(Math.round(fps * 1000) / 1000);
  if (NTSC[key]) return NTSC[key];
  const r = Math.round(fps);
  if (Math.abs(fps - r) < 1e-6 && r > 0 && TICKS_PER_SECOND % r === 0) {
    return TICKS_PER_SECOND / r;
  }
  // Fallback: nearest integer tick count (non-standard rates)
  return Math.round(TICKS_PER_SECOND / (fps > 0 ? fps : 25));
}

/**
 * Strict ISO 8601 parser. Requires explicit TZ suffix (`Z` or `±HH:MM`).
 *
 * @param {string} str
 * @param {Object} [opts]  { strict?: boolean }  — if strict=true, naive timestamps throw; else assume UTC.
 * @returns {Date}
 */
function parseUtcISO(str, opts = {}) {
  if (!str || typeof str !== 'string') {
    throw new Error(`parseUtcISO: invalid input "${str}"`);
  }
  const hasTz = /[zZ]$|[+\-]\d{2}:?\d{2}$/.test(str);
  let s = str;
  if (!hasTz) {
    if (opts.strict) {
      throw new Error(`parseUtcISO: naive timestamp without TZ: "${str}"`);
    }
    s = str + 'Z'; // assume UTC for legacy timestamps
  }
  const d = new Date(s);
  if (isNaN(d.getTime())) {
    throw new Error(`parseUtcISO: unparseable "${str}"`);
  }
  return d;
}

/**
 * Compute scene_t0 = earliest creation_time across all clips and tx_strips.
 *
 * @param {Array<Object>} clips
 * @param {Array<Object>} txStrips
 * @param {Object} [opts]  { strict?: boolean }
 * @returns {number} unix seconds (float)
 */
function computeSceneT0(clips, txStrips = [], opts = {}) {
  const allSources = [...clips, ...txStrips];
  if (allSources.length === 0) {
    throw new Error('computeSceneT0: no clips or tx_strips provided');
  }
  let minMs = Infinity;
  for (const src of allSources) {
    if (!src.creation_time) {
      if (opts.strict) {
        throw new Error(`computeSceneT0: missing creation_time on ${src.clip_id || src.tx || src.filename || '?'}`);
      }
      continue;
    }
    const ms = parseUtcISO(src.creation_time, opts).getTime();
    if (ms < minMs) minMs = ms;
  }
  if (minMs === Infinity) {
    throw new Error('computeSceneT0: no parseable creation_time found');
  }
  return minMs / 1000;
}

/**
 * Compute wall-clock offset of a clip from scene_t0, in seconds.
 *
 * Prefers `clip.wall_offset` (pre-computed in Python) for precision.
 * Falls back to parsing `clip.creation_time` if `wall_offset` absent.
 *
 * @param {Object} clip - clip with `creation_time` and/or `wall_offset`
 * @param {number} t0 - scene_t0 unix seconds
 * @param {Object} [opts]  { strict?: boolean }
 * @returns {number} offset seconds (always ≥ 0 by construction)
 */
function computeOffsetSec(clip, t0, opts = {}) {
  if (typeof clip.wall_offset === 'number') {
    // Invariant: 0112 bakes wall_offset against scene_t0 = min(clips ∪ tx), so
    // every offset must be >= 0. Guard the wall_offset branch too (not only the
    // creation_time fallback) so a stale/negative value surfaces instead of
    // silently placing at a negative sequence time.
    if (clip.wall_offset < 0) {
      throw new Error(`computeOffsetSec: negative wall_offset ${clip.wall_offset} for "${clip.clip_id || clip.filename || clip.tx || '?'}" — re-run 0112 (scene_t0 must include tx_strips)`);
    }
    return clip.wall_offset;
  }
  if (!clip.creation_time) {
    throw new Error(`computeOffsetSec: clip "${clip.clip_id || clip.filename || '?'}" has neither wall_offset nor creation_time`);
  }
  const clipSec = parseUtcISO(clip.creation_time, opts).getTime() / 1000;
  const offset = clipSec - t0;
  if (offset < 0) {
    // Should be impossible if t0 = min(creation_time across all sources)
    throw new Error(`computeOffsetSec: negative offset ${offset.toFixed(3)}s for clip "${clip.clip_id || clip.filename}" — t0 may be wrong`);
  }
  return offset;
}

/**
 * Merge a list of {start, end} intervals into non-overlapping union.
 * Used for video-bounded TX placement (Path B++).
 *
 * @param {Array<Object>} videoPlacements - placements with {offsetSec, duration}
 * @returns {Array<[number, number]>}  sorted, non-overlapping [start, end] tuples
 */
function computeVideoUnion(videoPlacements) {
  if (!videoPlacements || videoPlacements.length === 0) return [];

  // Sort by start
  const intervals = videoPlacements
    .map(p => [p.offsetSec, p.offsetSec + p.duration])
    .sort((a, b) => a[0] - b[0]);

  const merged = [intervals[0].slice()];
  for (let i = 1; i < intervals.length; i++) {
    const [start, end] = intervals[i];
    const last = merged[merged.length - 1];
    if (start <= last[1]) {
      // Overlap or touch — extend
      if (end > last[1]) last[1] = end;
    } else {
      merged.push([start, end]);
    }
  }
  return merged;
}

/**
 * Resolve the frame grid (and seed clip) for a scene — the sequence inherits its
 * format from the SEED clip, so the grid Premiere quantizes against is the
 * seed's fps, not media.fps. Pure logic, shared by wallClockBuilder (live build)
 * and tools/plan_cli.js (offline plan / 0113 / verify) so all three agree.
 *
 * @param {Array<Object>} sceneClips
 * @param {Object} ingest - full ingest (scene_fps / media read here)
 * @param {string} sceneName
 * @param {Array<string>|null} camLayersOverride
 * @returns {{ seedClip: Object|null, gridFps: number, sceneFpsForPlan: number }}
 */
function resolveSceneGrid(sceneClips, ingest, sceneName, camLayersOverride) {
  const sceneFpsForPlan = (ingest.scene_fps && ingest.scene_fps[sceneName])
    || (ingest.media && ingest.media.fps) || 25;
  const preCamLayers = deriveCamLayers(sceneClips, camLayersOverride || null);
  const primaryCam = Object.keys(preCamLayers).find(k => preCamLayers[k] === 0);
  const primaryClips = sceneClips
    .filter(c => camOfClip(c) === primaryCam)
    .sort((a, b) => (a.wall_offset || 0) - (b.wall_offset || 0));
  const seedClip = (sceneFpsForPlan != null
      && primaryClips.find(c => c.probe && Math.round(c.probe.fps) === Math.round(sceneFpsForPlan)))
    || primaryClips[0]
    || sceneClips[0]
    || null;
  const gridFps = (seedClip && seedClip.probe && seedClip.probe.fps) || sceneFpsForPlan;
  return { seedClip, gridFps, sceneFpsForPlan };
}

/**
 * Main planning function. Builds a placement plan for one scene.
 *
 * @param {Array<Object>} sceneClips - all clips of a scene (v2.0 shape)
 * @param {Array<Object>} [txStrips] - TX strips for this scene
 * @param {Array<string>|null} [camLayersOverride] - explicit cam V-track order
 * @param {Object} [opts]  { strict?: boolean, scene?: string }
 * @returns {Object} Plan
 */
function plan(sceneClips, txStrips = [], camLayersOverride = null, opts = {}) {
  if (!sceneClips || sceneClips.length === 0) {
    return {
      scene_t0: 0,
      cam_layers: {},
      tx_aIdx_base: 0,
      placements: [],
      warnings: [{ type: 'empty_scene' }],
    };
  }

  const warnings = [];

  // 1. Compute scene_t0
  const scene_t0 = computeSceneT0(sceneClips, txStrips, opts);

  // 2. Resolve cam → vIdx mapping
  const cam_layers = deriveCamLayers(sceneClips, camLayersOverride);

  // 3. Build video placements
  const videoPlacements = [];
  const v_track_occupancy = {}; // {vIdx: [{start, end, clipId}]}

  for (const clip of sceneClips) {
    const cam = camOfClip(clip);
    const vIdx = cam_layers[cam];

    if (vIdx === undefined) {
      warnings.push({
        type: 'unknown_cam',
        cam,
        clipId: clip.clip_id || clip.filename,
        scene: opts.scene,
      });
      continue;
    }

    let offsetSec;
    try {
      offsetSec = computeOffsetSec(clip, scene_t0, opts);
    } catch (err) {
      warnings.push({
        type: 'offset_error',
        clipId: clip.clip_id || clip.filename,
        error: err.message,
      });
      continue;
    }

    const endSec = offsetSec + (clip.duration || 0);

    // Check overlap on same vIdx
    const existing = v_track_occupancy[vIdx] || [];
    const overlap = existing.find(e =>
      offsetSec < e.end && endSec > e.start
    );
    if (overlap) {
      warnings.push({
        type: 'overlap',
        vIdx,
        cam,
        loser: overlap.clipId,
        winner: clip.clip_id || clip.filename,
        note: 'later overwrites earlier',
      });
    }
    (v_track_occupancy[vIdx] ||= []).push({
      start: offsetSec,
      end: endSec,
      clipId: clip.clip_id || clip.filename,
    });

    videoPlacements.push({
      kind: 'video',
      clipId: clip.clip_id || clip.filename,
      filename: clip.filename,
      cam,
      vIdx,
      aIdx: vIdx,  // matching audio track for cam audio
      offsetSec,
      duration: clip.duration,
    });
  }

  // 4. Compute TX placements (Path B++ — video-bounded)
  //
  //   - Group strips by TX label so a single physical lavalier that DJI split
  //     into multiple WAV files (e.g. TX02_MIC045 + TX02_MIC046) shares ONE
  //     A-track instead of fragmenting across several (NEW-4).
  //   - Allocate A-track indices LAZILY: only a TX label that actually emits at
  //     least one video-bounded TrackItem consumes an A-track, so strips that
  //     fall entirely outside the video union leave no empty track (NEW-5).
  const camVIndices = Object.values(cam_layers);
  const tx_aIdx_base = camVIndices.length > 0 ? Math.max(...camVIndices) + 1 : 0;

  const videoIntervals = computeVideoUnion(videoPlacements);
  const txPlacements = [];

  // Group strips by TX label, preserving first-seen order.
  const txGroups = [];
  const txGroupIndex = {};
  for (const tx of (txStrips || [])) {
    const label = tx.tx || tx.filename || 'TX';
    if (!(label in txGroupIndex)) {
      txGroupIndex[label] = txGroups.length;
      txGroups.push({ label, strips: [] });
    }
    txGroups[txGroupIndex[label]].strips.push(tx);
  }

  let nextAIdx = tx_aIdx_base; // lazy allocation cursor
  const tdGroups = []; // timeline-domain (0113-rendered) labels — emitted after grid alignment
  for (const group of txGroups) {
    // Timeline-domain strip (0113_frame_align.py render): file time == final
    // timeline time, so slices are IDENTITY per union block (offset == in),
    // emitted after gridAlignPlan when the final block grid is known.
    const tdStrip = group.strips.find(s => s.timeline_domain);
    if (tdStrip) {
      if (group.strips.length > 1) {
        warnings.push({ type: 'tx_timeline_domain_extra_strips', tx: group.label,
          note: 'timeline-domain label must have exactly ONE strip — extras ignored' });
      }
      tdGroups.push({ label: group.label, strip: tdStrip, aIdx: nextAIdx++ });
      continue;
    }
    // Build the candidate placements for ALL strips of this label first; only
    // claim an A-track if at least one survives the video-union intersection.
    const groupCandidates = [];
    for (const tx of group.strips) {
      let txOffsetSec;
      try {
        txOffsetSec = computeOffsetSec(
          { wall_offset: tx.wall_offset, creation_time: tx.creation_time, clip_id: tx.tx },
          scene_t0,
          opts
        );
      } catch (err) {
        warnings.push({ type: 'tx_offset_error', tx: tx.tx, error: err.message });
        continue;
      }
      const txEndSec = txOffsetSec + (tx.duration || 0);
      for (const [vStart, vEnd] of videoIntervals) {
        const partStart = Math.max(vStart, txOffsetSec);
        const partEnd = Math.min(vEnd, txEndSec);
        if (partEnd <= partStart) continue;
        groupCandidates.push({
          kind: 'tx',
          txId: tx.tx,
          filename: tx.filename,
          vIdx: -1, // audio-only
          offsetSec: partStart,
          duration: partEnd - partStart,
          sourceInPoint: partStart - txOffsetSec,
          sampleRate: tx.sample_rate,
        });
      }
    }

    if (groupCandidates.length === 0) {
      if (videoIntervals.length > 0) {
        warnings.push({
          type: 'tx_no_video_overlap',
          tx: group.label,
          note: 'TX label recorded outside video time range — no TrackItems emitted, no A-track claimed',
        });
      }
      continue; // do NOT consume an A-track
    }

    const aIdx = nextAIdx++;
    for (const cand of groupCandidates) {
      cand.aIdx = aIdx;
      txPlacements.push(cand);
    }
  }

  // 5. Gap compression (opt-in, default ON). Collapse dead-air gaps between
  //    video-union intervals that exceed `gapThreshold` down to `compressedGap`,
  //    preserving chronological order, clip adjacency, intra-block timing, and
  //    small natural pauses. The SAME piecewise-linear remap is applied to BOTH
  //    video and TX offsets so audio/video sync is preserved. A time-jump marker
  //    is recorded per collapsed gap so the editor sees where/how much was skipped.
  // Defaults (Roman 2026-05-31): "Model 1, no gaps" — synced multicam blocks
  // packed back-to-back. compressedGap=0 + gapThreshold=0 collapses ALL dead-air
  // between video-union blocks to ZERO, while intra-block relative timing (slope 1)
  // keeps overlapping cameras stacked/synced. markerThreshold limits time-jump
  // markers to MEANINGFUL gaps so every clip boundary isn't flagged.
  const compress = opts.compress !== false; // default true
  const gapThreshold = typeof opts.gapThreshold === 'number' ? opts.gapThreshold : 0;
  const compressedGap = typeof opts.compressedGap === 'number' ? opts.compressedGap : 0;
  const markerThreshold = typeof opts.markerThreshold === 'number' ? opts.markerThreshold : 30;
  let timeJumps = [];
  let blocks; // [{origStart, origEnd, compStart}] — union intervals in final timeline coords

  for (const p of [...videoPlacements, ...txPlacements]) {
    p.rawOffsetSec = p.offsetSec; // original wall-clock, pre-remap — used for block membership
  }

  // NB: the remap ALSO anchors the FIRST block to 0 (segs[0].compStart = 0) —
  // dead air before the first video (e.g. the lav recorder rolling 10.84 s
  // before the camera on YTCH13 scene 01) is dead timeline. Single-interval
  // scenes used to skip compression entirely and kept that head gap — run the
  // remap for ANY interval count so the "no dead air" policy is uniform.
  if (compress && videoIntervals.length >= 1) {
    const remapInfo = buildGapRemap(videoIntervals, gapThreshold, compressedGap, markerThreshold);
    timeJumps = remapInfo.timeJumps;
    blocks = remapInfo.segs;
    for (const p of [...videoPlacements, ...txPlacements]) {
      p.offsetSec = remapInfo.remap(p.offsetSec);
      // duration & sourceInPoint are unchanged: a clip/slice lives entirely inside
      // one union interval, where the remap is a pure shift (slope 1).
    }
  } else {
    blocks = videoIntervals.map(([s, e]) => ({ origStart: s, origEnd: e, compStart: s }));
  }

  // 5.7 Frame-grid alignment — EVERYTHING lands on exact frame ticks.
  //
  // Measured Premiere behaviour (YTCH10 dump 16.08.2026 + YTCH13 dump 16.08.2026,
  // 54 data points, exact tick arithmetic):
  //   - setSourceInOut FLOORS source in/out to the sequence frame grid, even for
  //     audio-only WAV items;
  //   - createInsertProjectItemAction ROUNDS the timeline position to the NEAREST
  //     frame (28/28 TX slices consistent) — the position does NOT stay sub-frame,
  //     which killed the old "fraction moves into the position" compensation;
  //   - createOverwriteItemAction passes on-grid positions through exactly.
  // Conclusion: the clip API offers NO sub-frame lever. The builder therefore
  // quantizes every position/in/out to exact frame TICKS itself (Premiere's own
  // rounding becomes a no-op), and sub-frame lav precision is achieved upstream
  // by frame-aligning the WAV media (0113_frame_align.py trims the file head so
  // its wall_offset is an exact frame multiple). Residual per slice is reported
  // in placement.residualMs; unaligned media degrades gracefully to ≤½ frame.
  const fps = (opts.media && opts.media.fps) || opts.fps || 25;
  const alignmentNeeds = gridAlignPlan(videoPlacements, txPlacements, blocks, fps, warnings);

  // Final grid spans of the union blocks — used by the timeline-domain branch
  // below AND exported so 0113 can fingerprint the layout its renders encode.
  // The fingerprint must include the RAW block start (µs): gap compression
  // makes grid spans invariant to wall_offset shifts, but the CONTENT mapping
  // (which source instant lands where) depends on the raw starts — that is
  // exactly what a stale render gets wrong.
  const spans = blockGridSpans(blocks, fps);
  const spansFingerprint = blocks.map((b, i) => {
    const s = spans[i] || { startIdx: '-', durFrames: '-' };
    return `${s.startIdx}:${s.durFrames}:${Math.round(b.origStart * 1e6)}`;
  }).join(',');

  // 5.8 Timeline-domain lav renders (0113): one identity slice per union block —
  // offset == source-in == block grid start; content was rendered sample-exactly
  // at its final timeline position, so sync error is ≤ 1 audio sample.
  if (tdGroups.length) {
    const tpf = ticksPerFrameForFps(fps);
    const frame = tpf / TICKS_PER_SECOND;
    for (const g of tdGroups) {
      // STALENESS GUARD: the render encodes per-block shifts of the layout it
      // was generated from. If wall_offsets / fine-sync / compression changed
      // since (different block spans), the render's audio no longer matches —
      // placement would still LOOK perfect, so this is the only detector.
      const fa = g.strip.frame_align;
      if (fa && fa.block_spans && fa.block_spans !== spansFingerprint) {
        warnings.push({
          type: 'tx_td_render_stale',
          tx: g.label,
          filename: g.strip.filename,
          note: 'layout changed since the render was generated — re-run 0113_frame_align.py, audio content is desynced',
        });
      } else if (!fa || !fa.block_spans) {
        // Fail-open guard: a render without a fingerprint cannot be checked
        // for staleness at all — surface it instead of silently trusting it.
        warnings.push({
          type: 'tx_td_render_unverifiable',
          tx: g.label,
          filename: g.strip.filename,
          note: 'render carries no layout fingerprint — re-run 0113_frame_align.py',
        });
      }
      const fileDur = g.strip.duration || Infinity;
      let prevEndIdx = -1; // defensive: spans are non-overlapping by construction
      for (const s of spans) {
        const offSec = s.startIdx * frame;
        let durFrames = s.durFrames;
        if (s.startIdx < prevEndIdx) {
          warnings.push({ type: 'tx_td_span_overlap', tx: g.label, at: offSec,
            note: 'adjacent block spans overlap — blockGridSpans invariant broken, slice skipped' });
          continue;
        }
        // never read past the rendered file's end
        if (offSec + durFrames * frame > fileDur + 1e-6) {
          durFrames = Math.floor((fileDur - offSec) / frame + 1e-9);
          if (durFrames < 1) continue;
          warnings.push({ type: 'tx_td_render_short', tx: g.label, at: offSec,
            note: 'rendered lav file ends before the last video block — re-run 0113' });
        }
        txPlacements.push({
          kind: 'tx',
          txId: g.label,
          filename: g.strip.filename,
          vIdx: -1,
          aIdx: g.aIdx,
          offsetSec: offSec,
          offsetTicks: String(s.startIdx * tpf),
          sourceInPoint: offSec,
          sourceInTicks: String(s.startIdx * tpf),
          duration: durFrames * frame,
          durationTicks: String(durFrames * tpf),
          sampleRate: g.strip.sample_rate,
          residualMs: 0,
          timelineDomain: true,
        });
        prevEndIdx = s.startIdx + durFrames;
      }
    }
  }

  // 6. Combine and sort by offsetSec (deterministic order)
  const placements = [...videoPlacements, ...txPlacements].sort((a, b) =>
    a.offsetSec - b.offsetSec ||
    a.aIdx - b.aIdx
  );

  return {
    scene_t0,
    cam_layers,
    tx_aIdx_base,
    placements,
    warnings,
    timeJumps,           // [{ atSec (compressed timeline pos), skippedSec }]
    compressed: compress && videoIntervals.length >= 1,
    fps,
    ticksPerFrame: ticksPerFrameForFps(fps),
    alignmentNeeds,      // per-file media alignment report (residual ranges)
    blockSpans: spansFingerprint,  // "startIdx:durFrames,…" — layout fingerprint for 0113
  };
}

/**
 * Frame-grid alignment of ALL placements (video + TX) with per-block anchoring.
 *
 * Model (all "content sync" statements are relative to the VIDEO as placed):
 *   - The timeline is a chain of union BLOCKS (video-union intervals, possibly
 *     shifted left by gap compression). Block k starts at s_k (float, sub-frame
 *     in general because wall offsets / fine-sync corrections are sub-frame).
 *   - Video positions must live on the frame grid — that is physics (a video
 *     frame cannot start mid-frame), so the whole block anchors to
 *     S_k = round(s_k / frame). Every placement of the block shifts by
 *     e_k = S_k·frame − s_k (|e_k| ≤ ½ frame) and then snaps to the grid.
 *     Clips chained back-to-back inside a block keep exact relative timing
 *     (25p durations are whole frames); a multicam B-camera whose sub-frame
 *     offset differs from the block anchor gets its own snap — inherent,
 *     recorded in placement.gridSnapMs.
 *   - TX slices follow the SAME e_k, so lav content tracks the video content
 *     of its block. The source in-point is then re-derived from the content
 *     invariant and snapped to the grid:
 *       in₁ = in₀ + (P₁ − P₀ − e_k)   (P₁ = final grid position)
 *     If the TX media is frame-aligned (0113_frame_align.py), in₁ lands on the
 *     grid naturally → residual ≈ 0 (sample-exact lav-vs-video sync). If not,
 *     in₁ is snapped to NEAREST and the residual (≤ ½ frame) is recorded in
 *     placement.residualMs + reported once per (file) in alignmentNeeds so the
 *     pipeline can generate the aligned media.
 *   - All final values are exact integer TICKS (offsetTicks / sourceInTicks /
 *     durationTicks as strings) — Premiere's own rounding (insert: nearest,
 *     setSourceInOut: floor) becomes a no-op, and float noise (e.g. the double
 *     109.44 sitting 1 ulp off the grid) can no longer flip a frame.
 *
 * Slices that quantize below one frame of duration are dropped with a warning;
 * a per-track overlap sweep (integer frame arithmetic) trims predecessor tails.
 *
 * Mutates the placements in place. Exported for unit tests.
 *
 * @param {Array<Object>} videoPlacements
 * @param {Array<Object>} txPlacements
 * @param {Array<Object>} blocks - [{origStart, origEnd, compStart}] final-coord blocks
 * @param {number} fps
 * @param {Array<Object>} warnings - plan() warnings sink
 * @returns {Array<Object>} alignmentNeeds -
 *   [{txId, filename, slices, residualMsMin, residualMsMax}] per unaligned file
 */
function gridAlignPlan(videoPlacements, txPlacements, blocks, fps, warnings) {
  const tpf = ticksPerFrameForFps(fps);
  const frame = tpf / TICKS_PER_SECOND;
  const EPS = 1e-9;
  const ALIGNED_TOL_SEC = 0.0005; // ≤0.5 ms off-grid counts as frame-aligned media

  // Block anchor shifts: e_k = S_k·frame − s_k
  const anchored = blocks.map(b => {
    const frameIdx = Math.round(b.compStart / frame);
    return {
      origStart: b.origStart,
      origEnd: b.origEnd,
      shift: frameIdx * frame - b.compStart,
    };
  });
  const blockOf = (p) => {
    const t = typeof p.rawOffsetSec === 'number' ? p.rawOffsetSec : p.offsetSec;
    for (const b of anchored) {
      if (t >= b.origStart - 1e-6 && t <= b.origEnd + 1e-6) return b;
    }
    return anchored[0] || { shift: 0 };
  };

  // --- Video: shift by block anchor, snap to grid, emit exact ticks ---
  for (const p of videoPlacements) {
    const b = blockOf(p);
    const ideal = p.offsetSec + b.shift;
    const frameIdx = Math.round(ideal / frame);
    p.gridSnapMs = Math.round((frameIdx * frame - ideal) * 1e6) / 1000; // sub-frame cam offset
    p.offsetSec = frameIdx * frame;
    p.offsetTicks = String(frameIdx * tpf);
  }

  // --- TX slices: same block shift; in-point via content invariant ---
  const needByFile = {};
  for (const p of txPlacements) {
    const b = blockOf(p);
    const p0 = p.offsetSec;
    const ideal = p0 + b.shift;
    const posIdx = Math.round(ideal / frame);
    const p1 = posIdx * frame;

    // Content invariant: content instant in₀ must play at (p0 + shift); with the
    // slice at p1 the in-point becomes in₁ = in₀ + (p1 − p0 − shift).
    const in0 = p.sourceInPoint || 0;
    const in1 = in0 + (p1 - p0 - b.shift);
    const inIdx = Math.round(in1 / frame);
    const inResidual = in1 - inIdx * frame; // ≈0 for frame-aligned media
    // The EXACT source instant that must play at the slice start for perfect
    // lav-vs-video sync — 0113_frame_align.py renders it there sample-exactly.
    p.contentSrcSec = Math.round(in1 * 1e6) / 1e6;
    if (Math.abs(inResidual) > ALIGNED_TOL_SEC) {
      // Media not frame-aligned: nearest-snap costs |residual| ≤ ½ frame of
      // lav-vs-video sync PER SLICE (fine-sync jitters video clips individually,
      // so the residual varies per block — a single per-file head-trim can NOT
      // fix it; only the timeline-domain lav render of 0113 can).
      const rec = needByFile[p.filename] ||= {
        txId: p.txId, filename: p.filename, minMs: Infinity, maxMs: -Infinity, slices: 0,
      };
      rec.slices++;
      const ms = inResidual * 1000;
      if (ms < rec.minMs) rec.minMs = ms;
      if (ms > rec.maxMs) rec.maxMs = ms;
    }
    if (inIdx < 0) {
      p._drop = true;
      warnings.push({ type: 'tx_slice_dropped_negative_in', tx: p.txId, at: p0 });
      continue;
    }

    // End: never overrun the video content end → floor.
    const end0 = p0 + p.duration;
    const endIdx = Math.floor((end0 + b.shift) / frame + EPS);
    const durFrames = endIdx - posIdx;
    if (durFrames < 1) {
      p._drop = true; // shorter than one frame after quantization — pointless
      warnings.push({ type: 'tx_slice_dropped_subframe', tx: p.txId, at: p0 });
      continue;
    }

    p.offsetSec = p1;
    p.offsetTicks = String(posIdx * tpf);
    p.sourceInPoint = inIdx * frame;
    p.sourceInTicks = String(inIdx * tpf);
    p.duration = durFrames * frame;
    p.durationTicks = String(durFrames * tpf);
    p.residualMs = Math.round(inResidual * 1e5) / 100; // lav-vs-video content error
    p._posIdx = posIdx;
    p._durFrames = durFrames;
  }
  for (let i = txPlacements.length - 1; i >= 0; i--) {
    if (txPlacements[i]._drop) txPlacements.splice(i, 1);
  }

  // Overlap sweep per A-track in INTEGER frames: trim the previous slice's tail.
  const byTrack = {};
  for (const p of txPlacements) (byTrack[p.aIdx] ||= []).push(p);
  for (const track of Object.values(byTrack)) {
    track.sort((a, b) => a._posIdx - b._posIdx);
    for (let i = 1; i < track.length; i++) {
      const prev = track[i - 1];
      const cur = track[i];
      const overlapFrames = (prev._posIdx + prev._durFrames) - cur._posIdx;
      if (overlapFrames <= 0) continue;
      prev._durFrames -= overlapFrames;
      if (prev._durFrames < 1) {
        warnings.push({ type: 'tx_slice_dropped_overlap', tx: prev.txId, at: prev.offsetSec });
        prev._drop = true;
      } else {
        prev.duration = prev._durFrames * frame;
        prev.durationTicks = String(prev._durFrames * tpf);
      }
    }
  }
  for (let i = txPlacements.length - 1; i >= 0; i--) {
    if (txPlacements[i]._drop) txPlacements.splice(i, 1);
  }
  for (const p of txPlacements) { delete p._posIdx; delete p._durFrames; }

  const needs = Object.values(needByFile).map(r => ({
    txId: r.txId,
    filename: r.filename,
    slices: r.slices,
    residualMsMin: Math.round(r.minMs * 100) / 100,
    residualMsMax: Math.round(r.maxMs * 100) / 100,
  }));
  for (const n of needs) {
    warnings.push({
      type: 'tx_unaligned_media',
      tx: n.txId,
      filename: n.filename,
      residualMs: [n.residualMsMin, n.residualMsMax],
      note: 'run 0113_frame_align.py (timeline-domain lav render) — until then lav sync degrades to ≤½ frame per slice',
    });
  }
  return needs;
}

/**
 * Final grid spans of the union blocks, in frames of the given fps.
 * Uses the SAME anchoring rule as gridAlignPlan (S_k = round(compStart/frame)).
 *
 * @param {Array<Object>} blocks - [{origStart, origEnd, compStart}]
 * @param {number} fps
 * @returns {Array<Object>} [{startIdx, durFrames}]
 */
function blockGridSpans(blocks, fps) {
  const tpf = ticksPerFrameForFps(fps);
  const frame = tpf / TICKS_PER_SECOND;
  return blocks.map(b => {
    const startIdx = Math.round(b.compStart / frame);
    // Round the block END as an absolute instant, NOT the duration: with
    // compressedGap=0 the next block starts at this block's end, and rounding
    // start/duration independently makes round(a)+round(b) = round(a+b)+1
    // whenever both fractions are ≥ .5 — a 1-frame overlap between adjacent
    // spans (found in adversarial review 17.08.2026). Rounding the same
    // absolute instant on both sides keeps spans monotone and gap/overlap-free.
    const endIdx = Math.round((b.compStart + (b.origEnd - b.origStart)) / frame);
    return { startIdx, durFrames: endIdx - startIdx };
  }).filter(s => s.durFrames >= 1);
}

/**
 * Build a piecewise-linear time remap from raw wall-clock seconds → compressed
 * timeline seconds, collapsing inter-interval gaps larger than `gapThreshold`
 * down to `compressedGap`.
 *
 * @param {Array<[number,number]>} intervals - sorted, non-overlapping video union
 * @param {number} gapThreshold - gaps <= this are preserved as-is
 * @param {number} compressedGap - gaps > threshold collapse to this fixed value
 * @returns {{ remap: function(number):number, timeJumps: Array<{atSec:number,skippedSec:number}> }}
 */
function buildGapRemap(intervals, gapThreshold, compressedGap, markerThreshold) {
  const markThr = typeof markerThreshold === 'number' ? markerThreshold : 30;
  const segs = []; // { origStart, origEnd, compStart }
  const timeJumps = [];
  let compCursor = 0;
  for (let i = 0; i < intervals.length; i++) {
    const [s, e] = intervals[i];
    if (i > 0) {
      const prevEnd = intervals[i - 1][1];
      const gap = s - prevEnd;
      let keptGap = gap;
      if (gap > gapThreshold) {
        keptGap = compressedGap;
        // Only flag a time-jump marker for MEANINGFUL skips (not every clip stop).
        if (gap - keptGap >= markThr) {
          timeJumps.push({ atSec: compCursor + keptGap, skippedSec: gap - keptGap });
        }
      }
      compCursor += keptGap;
    }
    segs.push({ origStart: s, origEnd: e, compStart: compCursor });
    compCursor += (e - s);
  }
  const remap = (t) => {
    for (const seg of segs) {
      if (t >= seg.origStart - 1e-6 && t <= seg.origEnd + 1e-6) {
        return Math.round((seg.compStart + (t - seg.origStart)) * 1e6) / 1e6;
      }
    }
    // t falls in a collapsed gap (shouldn't happen for clips/slices, which live
    // inside intervals) — snap to the nearest segment boundary.
    if (t <= segs[0].origStart) return 0;
    for (let i = 0; i < segs.length - 1; i++) {
      if (t > segs[i].origEnd && t < segs[i + 1].origStart) {
        return Math.round((segs[i].compStart + (segs[i].origEnd - segs[i].origStart)) * 1e6) / 1e6;
      }
    }
    const last = segs[segs.length - 1];
    return Math.round((last.compStart + (last.origEnd - last.origStart)) * 1e6) / 1e6;
  };
  return { remap, timeJumps, segs };
}

module.exports = {
  parseUtcISO,
  computeSceneT0,
  computeOffsetSec,
  computeVideoUnion,
  buildGapRemap,
  gridAlignPlan,
  blockGridSpans,
  resolveSceneGrid,
  ticksPerFrameForFps,
  TICKS_PER_SECOND,
  plan,
};
