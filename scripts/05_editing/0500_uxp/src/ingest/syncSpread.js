/**
 * Sync Spread — Premiere-native fine sync via the built-in Synchronize command.
 *
 * Pure module: no UXP imports. Unit-testable under Node.
 *
 * The workflow (Roman, 2026-08-16, after the Katie Münch short):
 *   1. planSpread()  — lay every source of a scene on its OWN track pair at RAW
 *      wall-clock positions (no gap compression, lav strips UNCUT), plus a
 *      30 s preroll so Synchronize can move clips LEFT without hitting t=0.
 *      One clip per track is the configuration Premiere's Clip → Synchronize
 *      requires — with two selected clips on one track it greys out.
 *   2. The human selects everything and runs Clip → Synchronize (Audio).
 *   3. collectDeltas() — read back the new positions; how far Premiere moved
 *      each item IS its correction.
 *   4. applyDeltasToIngest() — fold the corrections into wall_offset and let
 *      the normal wall-clock builder rebuild the scene (sliced lav, compressed
 *      gaps — all recomputed from the numbers).
 *
 * "Возвращать на место" is therefore not a mechanical un-spread: the spread
 * sequence is disposable. The corrections land in the ingest, the rebuild
 * reproduces the scene exactly — now with Premiere-blessed offsets.
 *
 * Public API:
 *   - planSpread(sceneClips, txStrips, opts) → { placements, manifest, warnings }
 *   - collectDeltas(manifest, actualItems, opts) → { clips, txFiles, moved, maxAbsSec, missing }
 *   - applyDeltasToIngest(ingest, scene, deltas, nowIso) → { ingest, applied, maxAbsSec, normalizedShift }
 */

const DEFAULT_PREROLL_SEC = 30;
const MIN_DELTA_SEC = 0.002; // below this = jitter/no move, ignore

/**
 * Plan the spread sequence for one scene.
 *
 * Every video clip gets its own V/A pair (V1/A1, V2/A2, ...); every lav FILE
 * gets its own audio-only track after the clips — errors live per FILE
 * (proven by finesync least-squares on YTCH10), so files must move
 * independently.
 *
 * @param {Array<Object>} sceneClips - v2.0 ingest clips of ONE scene
 * @param {Array<Object>} txStrips - tx_strips[scene] (whole files)
 * @param {Object} [opts]  { preroll?: number }
 * @returns {{ placements: Array<Object>, manifest: Object, warnings: Array<Object> }}
 */
function planSpread(sceneClips, txStrips = [], opts = {}) {
  const preroll = typeof opts.preroll === 'number' ? opts.preroll : DEFAULT_PREROLL_SEC;
  const warnings = [];
  const clips = (sceneClips || []).filter(c => typeof c.wall_offset === 'number');
  const strips = (txStrips || []).filter(t => typeof t.wall_offset === 'number');
  if (clips.length !== (sceneClips || []).length) {
    warnings.push({ type: 'clips_without_offset', count: (sceneClips || []).length - clips.length });
  }
  if (strips.length !== (txStrips || []).length) {
    warnings.push({ type: 'strips_without_offset', count: (txStrips || []).length - strips.length });
  }
  if (clips.length + strips.length === 0) {
    return { placements: [], manifest: null, warnings: [{ type: 'empty_scene' }] };
  }

  const t0 = Math.min(
    ...clips.map(c => c.wall_offset),
    ...strips.map(t => t.wall_offset)
  );

  const placements = [];
  const items = [];

  clips
    .slice()
    .sort((a, b) => a.wall_offset - b.wall_offset)
    .forEach((c, i) => {
      const offsetSec = c.wall_offset - t0 + preroll;
      placements.push({
        kind: 'video',
        clipId: c.clip_id || c.filename,
        filename: c.filename,
        vIdx: i,
        aIdx: i,
        offsetSec,
        duration: c.duration,
      });
      items.push({
        id: c.clip_id || c.filename,
        kind: 'clip',
        filename: c.filename,
        trackType: 'video',
        trackIdx: i,
        placedSec: offsetSec,
      });
    });

  const txBase = clips.length;
  strips
    .slice()
    .sort((a, b) => a.wall_offset - b.wall_offset)
    .forEach((t, j) => {
      const offsetSec = t.wall_offset - t0 + preroll;
      placements.push({
        kind: 'txfull',
        txId: t.tx || 'TX',
        filename: t.filename,
        vIdx: -1,
        aIdx: txBase + j,
        offsetSec,
        duration: t.duration,
      });
      items.push({
        id: t.filename,
        kind: 'tx',
        filename: t.filename,
        trackType: 'audio',
        trackIdx: txBase + j,
        placedSec: offsetSec,
      });
    });

  return {
    placements,
    manifest: {
      version: 1,
      preroll,
      t0Wall: t0,
      nVideoTracks: clips.length,
      nAudioTracks: clips.length + strips.length,
      items,
    },
    warnings,
  };
}

/**
 * Compare actual (post-Synchronize) positions with the manifest.
 *
 * Matching is by filename first (Synchronize moves items but never renames or
 * re-tracks them; filename is unique per source by pipeline contract), with
 * track index as a tie-breaker when the same file appears on several tracks
 * (a lav file spread once cannot, but be defensive).
 *
 * @param {Object} manifest - from planSpread()
 * @param {Array<Object>} actualItems - [{ filename, trackType, trackIdx, startSec }]
 * @param {Object} [opts]  { minDelta?: number }
 * @returns {{ clips: Object, txFiles: Object, moved: number, maxAbsSec: number, missing: Array<string> }}
 */
function collectDeltas(manifest, actualItems, opts = {}) {
  const minDelta = typeof opts.minDelta === 'number' ? opts.minDelta : MIN_DELTA_SEC;
  const clips = {};
  const txFiles = {};
  const missing = [];
  let moved = 0;
  let maxAbsSec = 0;

  for (const want of manifest.items) {
    // candidates: same filename, prefer same trackType+trackIdx. A spread A/V
    // clip appears TWICE (video item + its linked audio item share the name),
    // so after the exact miss fall back to a same-trackType UNIQUE match —
    // that recovers a clip the user dragged to another track without ever
    // confusing the video part with its own audio twin.
    const byName = actualItems.filter(a => a.filename === want.filename);
    let actual = byName.find(a => a.trackType === want.trackType && a.trackIdx === want.trackIdx);
    if (!actual) {
      const sameType = byName.filter(a => a.trackType === want.trackType);
      if (sameType.length === 1) actual = sameType[0];
    }
    if (!actual) {
      missing.push(want.id);
      continue;
    }
    let delta = actual.startSec - want.placedSec;
    if (Math.abs(delta) < minDelta) delta = 0;
    if (delta !== 0) {
      moved++;
      if (Math.abs(delta) > maxAbsSec) maxAbsSec = Math.abs(delta);
    }
    if (want.kind === 'clip') clips[want.id] = delta;
    else txFiles[want.id] = delta;
  }

  return { clips, txFiles, moved, maxAbsSec, missing };
}

/**
 * Fold collected deltas into a COPY of the ingest.
 *
 * Sign: Premiere moved the item to where it SHOULD be. An item that moved
 * right by +d starts later → wall_offset += d. After applying, the scene is
 * re-normalized so no wall_offset is negative (the builder throws on
 * negatives); the uniform shift is sync-neutral.
 *
 * @param {Object} ingest - full ingest JSON (not mutated)
 * @param {string} scene
 * @param {{ clips: Object, txFiles: Object }} deltas - from collectDeltas()
 * @param {string} nowIso - timestamp for fine_sync stamp
 * @returns {{ ingest: Object, applied: number, maxAbsSec: number, normalizedShift: number }}
 */
function applyDeltasToIngest(ingest, scene, deltas, nowIso) {
  // Refuse mixed scenes: a clip WITHOUT wall_offset (creation_time fallback)
  // cannot take part in the re-normalization shift, so it would silently end
  // up offset against every shifted source — the opposite of syncing. The
  // v2.0 wallclock contract requires wall_offset on every placeable clip, so
  // this only ever fires on legacy/broken ingests, where syncing is moot.
  const noOffset = (ingest.clips || []).filter(
    c => c.scene === scene && typeof c.wall_offset !== 'number');
  if (noOffset.length > 0) {
    throw new Error('applyDeltasToIngest: ' + noOffset.length + ' clip(s) in scene "' + scene
      + '" have no wall_offset — fix the ingest (0112) before collecting sync');
  }

  const out = JSON.parse(JSON.stringify(ingest));
  let applied = 0;
  let maxAbsSec = 0;
  const offsets = [];

  for (const clip of out.clips) {
    if (clip.scene !== scene) continue;
    const d = deltas.clips[clip.clip_id] !== undefined
      ? deltas.clips[clip.clip_id]
      : deltas.clips[clip.filename];
    if (typeof d === 'number' && d !== 0) {
      clip.wall_offset = Math.round((clip.wall_offset + d) * 10000) / 10000;
      clip.fine_sync = { corr: -d, method: 'premiere-synchronize' };
      applied++;
      if (Math.abs(d) > maxAbsSec) maxAbsSec = Math.abs(d);
    }
    if (typeof clip.wall_offset === 'number') offsets.push(clip.wall_offset);
  }
  const strips = (out.tx_strips && out.tx_strips[scene]) || [];
  for (const tx of strips) {
    const d = deltas.txFiles[tx.filename];
    if (typeof d === 'number' && d !== 0) {
      tx.wall_offset = Math.round((tx.wall_offset + d) * 10000) / 10000;
      tx.fine_sync = { corr: -d, method: 'premiere-synchronize' };
      applied++;
      if (Math.abs(d) > maxAbsSec) maxAbsSec = Math.abs(d);
    }
    if (typeof tx.wall_offset === 'number') offsets.push(tx.wall_offset);
  }

  // Re-normalize the scene: builder throws on negative wall_offset.
  // NOTE: the shift touches only sources WITH a numeric wall_offset. In the
  // v2.0 wallclock contract every placeable source has one (validate_ingest
  // fails otherwise), so the shift is uniform. A legacy clip relying on the
  // creation_time fallback would NOT be shifted — that ingest shape never
  // reaches the wallclock builder in the first place.
  let normalizedShift = 0;
  const minOff = offsets.length ? Math.min(...offsets) : 0;
  if (minOff < 0) {
    normalizedShift = -minOff;
    for (const clip of out.clips) {
      if (clip.scene === scene && typeof clip.wall_offset === 'number') {
        clip.wall_offset = Math.round((clip.wall_offset + normalizedShift) * 10000) / 10000;
      }
    }
    for (const tx of strips) {
      if (typeof tx.wall_offset === 'number') {
        tx.wall_offset = Math.round((tx.wall_offset + normalizedShift) * 10000) / 10000;
      }
    }
  }

  if (applied > 0) {
    out.fine_sync = Object.assign({}, out.fine_sync, {
      applied_at: nowIso,
      method: 'premiere-synchronize',
    });
  }

  return { ingest: out, applied, maxAbsSec, normalizedShift };
}

module.exports = {
  planSpread,
  collectDeltas,
  applyDeltasToIngest,
  DEFAULT_PREROLL_SEC,
};
