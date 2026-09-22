/**
 * shortsBuilder.js — Shorts tab engine (MVP-1, finished mode).
 *
 * Claude writes 00_Setup/07_Shorts/{CODE}_Shorts_v{N}_in.json (schema ytai-shorts-v1,
 * see docs/shorts/SHORTS_SPEC.md §5). This module turns it into Premiere sequences:
 *
 *   PURE PLANNING (unit-testable without Premiere):
 *     planShort(candidate, brief, opts)  — tick-exact back-to-back placement plan
 *     planPreview(brief, statuses)       — range-marker list for the preview timeline
 *     validateShortsBrief(brief, statuses) — issues[] (W01/O01/S01/B01 — B03 is disk-side,
 *                                            appended by the panel)
 *
 *   IMPERATIVE BUILD (Premiere UXP):
 *     buildPreviewSequence(project, brief, opts) — {CODE}_Shorts_Preview_v{N}: source
 *       full-length on V1 + one chapter range-marker per non-rejected candidate.
 *     buildShortSequence(project, candidate, brief, opts) — {CODE}_S{NN}_{slug}:
 *       1080×1920 @ brief fps, blocks overwritten back-to-back on the tick grid,
 *       sequential ascending transactions, 2ms verify gate, S-1 motion spike.
 *
 * Canon (proven in this codebase — do not "simplify" away):
 *   - positions ONLY via TickTime.createWithTicks; ticks are the source of truth
 *     (float seconds drift: double 109.44 → +1 frame, memory frame-floor).
 *   - createSetInOutPointsAction FLOORS to the video frame grid; insert rounds the
 *     position to the nearest frame → all boundaries are frame-snapped BEFORE ticks.
 *   - one placement per transaction, ascending timeline order (compound transactions
 *     execute in REVERSE and eat successors' heads — measured YTCH13).
 *   - createBinAction on an existing name spawns duplicates → existence check first.
 *   - createAddMarkerAction IGNORES its type param → separate createSetTypeAction with
 *     the chapter URI + createSetColorByIndexAction transactions (sceneMarkers pattern).
 *   - getTrackItems is ASYNC + takes the TrackItemType enum (sync call → silent no-op).
 *   - importFiles returns nothing usable → re-resolve by name after import.
 *
 * RULE: imports ONLY from src/shared/* and src/ingest/placement/sequenceFactory.js
 * (same contract as partsBuilder.js). No other cross-module imports.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

const { TICKS_PER_SECOND, LABEL_COLOR_INDEX, MARKER_TYPE_CHAPTER, MARKER_COLOR_INDEX } = require('../shared/constants');
const { snapToFrame } = require('../shared/frameSnap');
const { applyColorByIndex, setSourceInOut, clearSourceInOut, cleanExistingSequence } = require('../shared/clipActions');
const { findProjectItemByName } = require('../shared/projectItemFinder');
const { applyMediaSettings } = require('../shared/mediaSettings');
const { findSequenceProjectItem, moveItemToBin } = require('../shared/binMove');

let sequenceFactory = null;
try { sequenceFactory = require('../ingest/placement/sequenceFactory'); } catch (e) { /* optional */ }

var SHORTS_BUILDER_VERSION = '0.1.1'; // 0.1.1 (2026-09-15): Shorts-bin filing via shared binMove (two-arg createMoveItemAction on root + read-back) — the one-arg move left every short in root.

var SHORTS_BIN = 'Shorts';

// role → ProjectItem label color index (spec §3.4: hook=Mango, body=Caribbean, broll=Lavender).
// Mango comes through LABEL_COLOR_INDEX.Orange (=7). Caribbean (2) and Lavender (3) have no
// named key in LABEL_COLOR_INDEX — raw real-API label slots are used (LAVENDER=3 confirmed in
// the enum dump; slot 2 = Caribbean, absent from the dump but a valid 0-15 label index).
var ROLE_COLOR_INDEX = {
  hook: LABEL_COLOR_INDEX.Orange, // Mango = 7
  body: 2,                        // Caribbean
  payoff: 2,                      // payoff rides with body
  broll: 3                        // Lavender
};

var noopLogger = { info: function () {}, warn: function () {}, error: function () {}, debug: function () {} };

// ═══════════════════════════════ PURE PLANNING ═══════════════════════════════

/** "MM:SS.mmm" / "HH:MM:SS.mmm" → seconds (last-resort fallback when sec/ticks absent). */
function tcToSecShorts(tc) {
  if (tc == null) return null;
  if (typeof tc === 'number') return tc;
  var parts = String(tc).split(':');
  if (parts.length === 3) {
    return parseInt(parts[0], 10) * 3600 + parseInt(parts[1], 10) * 60 + parseFloat(parts[2]);
  }
  if (parts.length === 2) {
    return parseInt(parts[0], 10) * 60 + parseFloat(parts[1]);
  }
  var f = parseFloat(tc);
  return isNaN(f) ? null : f;
}

/**
 * Boundary {tc, sec, frame, ticks} → integer ticks.
 * Ticks are TRUSTED as-is (source of truth — the finder already snapped them).
 * Without ticks: snapToFrame(sec, fps, mode) then Math.round(sec * TICKS_PER_SECOND).
 * mode: 'floor' for in-points, 'ceil' for out-points (never cut a word in zero).
 */
function boundaryTicks(boundary, fps, mode) {
  if (boundary == null) return null;
  if (typeof boundary === 'number') {
    return Math.round(snapToFrame(boundary, fps, mode) * TICKS_PER_SECOND);
  }
  if (boundary.ticks != null && boundary.ticks !== '') {
    var t = Number(boundary.ticks);
    if (!isNaN(t)) return Math.round(t);
  }
  var sec = (boundary.sec != null) ? boundary.sec : tcToSecShorts(boundary.tc);
  if (sec == null || isNaN(sec)) return null;
  return Math.round(snapToFrame(sec, fps, mode) * TICKS_PER_SECOND);
}

/**
 * PURE: placement plan for one candidate — blocks back-to-back from 0 on the tick grid.
 * Durations = (tc_out.ticks - tc_in.ticks), positions cumulative EXACT ticks.
 *
 * @param {Object} candidate - ytai-shorts-v1 candidate (short_id, slug, blocks[])
 * @param {Object} brief - the whole _in.json (fps + default source)
 * @param {Object} [opts] - { markerReadback: {tc_in:{sec,ticks}, tc_out:{sec,ticks}} }
 *   readback override applies to the candidate's outer boundaries:
 *   tc_in → first block's in, tc_out → last block's out.
 * @returns {Array} entries: {blockId, role, sourceFile, sourcePath, srcInTicks,
 *   srcOutTicks, timelineInTicks, timelineOutTicks, vIdx, aIdx, colorIndex,
 *   markerName, markerComment}
 */
function planShort(candidate, brief, opts) {
  opts = opts || {};
  var fps = (brief && brief.project && brief.project.fps) || 25;
  var defSource = (brief && brief.project && brief.project.source) || {};
  var blocks = (candidate && candidate.blocks) || [];
  var rb = opts.markerReadback || null;
  var sid = (candidate && candidate.short_id) || 'S?';
  var entries = [];
  var cursor = 0;
  for (var i = 0; i < blocks.length; i++) {
    var b = blocks[i];
    var tcIn = b.tc_in;
    var tcOut = b.tc_out;
    if (rb) {
      if (i === 0 && rb.tc_in) tcIn = rb.tc_in;
      if (i === blocks.length - 1 && rb.tc_out) tcOut = rb.tc_out;
    }
    var blockId = b.block_id || ('b' + (i + 1));
    var srcIn = boundaryTicks(tcIn, fps, 'floor');
    var srcOut = boundaryTicks(tcOut, fps, 'ceil');
    if (srcIn == null || srcOut == null) {
      throw new Error('planShort ' + sid + ' ' + blockId + ': boundary lacks ticks/sec');
    }
    if (srcOut <= srcIn) {
      throw new Error('planShort ' + sid + ' ' + blockId + ': empty/negative range (' + srcIn + '..' + srcOut + ')');
    }
    var dur = srcOut - srcIn;
    var role = b.role || 'body';
    entries.push({
      blockId: blockId,
      role: role,
      sourceFile: (b.source && b.source.file) || defSource.file || null,
      sourcePath: (b.source && b.source.path) || defSource.path || null,
      srcInTicks: srcIn,
      srcOutTicks: srcOut,
      timelineInTicks: cursor,
      timelineOutTicks: cursor + dur,
      vIdx: 0,
      aIdx: (b.keep_audio !== false) ? 0 : -1,
      colorIndex: (ROLE_COLOR_INDEX[role] != null) ? ROLE_COLOR_INDEX[role] : ROLE_COLOR_INDEX.body,
      markerName: sid + ' ' + role + ' ' + blockId,
      markerComment: String(b.transcript || '').slice(0, 200)
    });
    cursor += dur;
  }
  return entries;
}

/**
 * PURE: marker list for the preview sequence — one range marker per NON-REJECTED
 * candidate over its source range (finished mode: render timeline == source timeline).
 *
 * @param {Object} brief
 * @param {Object} [statuses] - panel status overrides {short_id: status}
 * @returns {Array} [{shortId, name: "S03 [87] slug", comment, startTicks, durationTicks}]
 */
function planPreview(brief, statuses) {
  var fps = (brief && brief.project && brief.project.fps) || 25;
  var cands = (brief && brief.candidates) || [];
  var out = [];
  for (var i = 0; i < cands.length; i++) {
    var c = cands[i];
    var sid = c.short_id || ('S' + (i + 1));
    var st = (statuses && statuses[sid]) || c.status || 'proposed';
    if (st === 'rejected') continue;
    var lo = null, hi = null;
    var blocks = c.blocks || [];
    for (var j = 0; j < blocks.length; j++) {
      var inT = boundaryTicks(blocks[j].tc_in, fps, 'floor');
      var outT = boundaryTicks(blocks[j].tc_out, fps, 'ceil');
      if (inT != null && (lo == null || inT < lo)) lo = inT;
      if (outT != null && (hi == null || outT > hi)) hi = outT;
    }
    if (lo == null || hi == null || hi <= lo) continue;
    var total = (c.score && c.score.total != null) ? c.score.total : '—';
    out.push({
      shortId: sid,
      name: sid + ' [' + total + '] ' + (c.slug || ''),
      comment: (c.hook_text || '') + (c.why ? ' — ' + c.why : ''),
      startTicks: lo,
      durationTicks: hi - lo
    });
  }
  return out;
}

/**
 * PURE validation core — W01 / O01 / S01 / B01 (spec §5.2 issue codes).
 * B03 (media offline) needs disk access — the panel appends it separately.
 *
 * @param {Object} brief - parsed _in.json
 * @param {Object} [statuses] - panel status overrides (O01 skips rejected)
 * @returns {Array} issues: [{code, short_id, severity, msg}]
 */
function validateShortsBrief(brief, statuses) {
  var issues = [];
  if (!brief || brief.schema !== 'ytai-shorts-v1') {
    issues.push({ code: 'SCHEMA', short_id: null, severity: 'error', msg: 'not a ytai-shorts-v1 brief' });
    return issues;
  }
  var fps = (brief.project && brief.project.fps) || 25;
  var ticksPerFrame = TICKS_PER_SECOND / fps;
  var defFile = (brief.project && brief.project.source && brief.project.source.file) || '';
  var cands = brief.candidates || [];

  // S01 — duplicate short_id / slug
  var seenId = {}, seenSlug = {};
  for (var si = 0; si < cands.length; si++) {
    var cs = cands[si];
    if (cs.short_id) {
      if (seenId[cs.short_id]) issues.push({ code: 'S01', short_id: cs.short_id, severity: 'error', msg: 'duplicate short_id "' + cs.short_id + '"' });
      seenId[cs.short_id] = 1;
    }
    if (cs.slug) {
      if (seenSlug[cs.slug]) issues.push({ code: 'S01', short_id: cs.short_id || null, severity: 'error', msg: 'duplicate slug "' + cs.slug + '"' });
      seenSlug[cs.slug] = 1;
    }
  }

  // Per-block: W01 (words cut) + B01 (frame/sec/ticks coherence at the brief's fps)
  for (var ci = 0; ci < cands.length; ci++) {
    var c = cands[ci];
    var blocks = c.blocks || [];
    for (var bi = 0; bi < blocks.length; bi++) {
      var b = blocks[bi];
      var bid = b.block_id || ('b' + (bi + 1));
      var w = b.words;
      if (w) {
        if (b.tc_in && b.tc_in.sec != null && w.first_start_sec != null && b.tc_in.sec > w.first_start_sec + 1e-6) {
          issues.push({
            code: 'W01', short_id: c.short_id, severity: 'error',
            msg: (c.short_id || '?') + ' ' + bid + ': tc_in ' + Number(b.tc_in.sec).toFixed(3) + ' > first word start '
              + Number(w.first_start_sec).toFixed(3) + ' — word "' + (w.first || '?') + '" cut'
          });
        }
        if (b.tc_out && b.tc_out.sec != null && w.last_end_sec != null && b.tc_out.sec < w.last_end_sec - 1e-6) {
          issues.push({
            code: 'W01', short_id: c.short_id, severity: 'error',
            msg: (c.short_id || '?') + ' ' + bid + ': tc_out ' + Number(b.tc_out.sec).toFixed(3) + ' < last word end '
              + Number(w.last_end_sec).toFixed(3) + ' — word "' + (w.last || '?') + '" cut'
          });
        }
      }
      var pairs = [['tc_in', b.tc_in], ['tc_out', b.tc_out]];
      for (var pi = 0; pi < pairs.length; pi++) {
        var bn = pairs[pi][0], bd = pairs[pi][1];
        if (!bd || bd.sec == null) continue;
        if (bd.ticks != null && bd.ticks !== '') {
          var tv = Number(bd.ticks);
          if (!isNaN(tv)) {
            var dTicks = Math.abs(tv - bd.sec * TICKS_PER_SECOND);
            if (dTicks > ticksPerFrame + 0.5) {
              issues.push({
                code: 'B01', short_id: c.short_id, severity: 'warn',
                msg: (c.short_id || '?') + ' ' + bid + ' ' + bn + ': ticks/sec disagree by '
                  + (dTicks / TICKS_PER_SECOND * 1000).toFixed(1) + 'ms — fps mismatch? (brief fps ' + fps + ')'
              });
            }
          }
        }
        if (bd.frame != null && Math.round(bd.sec * fps) !== bd.frame) {
          issues.push({
            code: 'B01', short_id: c.short_id, severity: 'warn',
            msg: (c.short_id || '?') + ' ' + bid + ' ' + bn + ': frame ' + bd.frame + ' != round(sec*fps) '
              + Math.round(bd.sec * fps) + ' (brief fps ' + fps + ')'
          });
        }
      }
    }
  }

  // O01 — overlapping block source ranges among non-rejected candidates (same source)
  var ranged = [];
  for (var oi = 0; oi < cands.length; oi++) {
    var oc = cands[oi];
    var osid = oc.short_id || ('S' + (oi + 1));
    var ost = (statuses && statuses[osid]) || oc.status || 'proposed';
    if (ost === 'rejected') continue;
    var obl = oc.blocks || [];
    for (var ob = 0; ob < obl.length; ob++) {
      var lo = boundaryTicks(obl[ob].tc_in, fps, 'floor');
      var hi = boundaryTicks(obl[ob].tc_out, fps, 'ceil');
      if (lo == null || hi == null) continue;
      ranged.push({ id: osid, file: (obl[ob].source && obl[ob].source.file) || defFile, lo: lo, hi: hi });
    }
  }
  var flagged = {};
  for (var a = 0; a < ranged.length; a++) {
    for (var z = a + 1; z < ranged.length; z++) {
      var ra = ranged[a], rz = ranged[z];
      if (ra.id === rz.id || ra.file !== rz.file) continue;
      if (ra.lo < rz.hi && rz.lo < ra.hi) {
        var key = ra.id < rz.id ? ra.id + '|' + rz.id : rz.id + '|' + ra.id;
        if (flagged[key]) continue;
        flagged[key] = 1;
        issues.push({
          code: 'O01', short_id: ra.id, severity: 'error',
          msg: ra.id + ' overlaps ' + rz.id + ' on ' + (ra.file || 'source') + ' ('
            + (Math.max(ra.lo, rz.lo) / TICKS_PER_SECOND).toFixed(2) + '–'
            + (Math.min(ra.hi, rz.hi) / TICKS_PER_SECOND).toFixed(2) + 's)'
        });
      }
    }
  }
  return issues;
}

// ═══════════════════════════════ SHARED HELPERS (imperative) ═══════════════════════════════

function tickTimeFromTicks(ticks) {
  return ppro.TickTime.createWithTicks(String(Math.round(ticks)));
}

/** Robust TickTime → integer ticks (handles .ticks string/bigint and .seconds-only builds). */
function ttTicksNum(tt) {
  if (!tt) return null;
  var t = null;
  try { t = tt.ticks; } catch (e) { /* getter may throw */ }
  if (typeof t === 'bigint') return Number(t);
  if (t != null && t !== '') {
    var n = Number(t);
    if (!isNaN(n)) return n;
  }
  var s = null;
  try { s = (tt.seconds != null) ? tt.seconds : tt.secs; } catch (e) { /* ignore */ }
  if (typeof s === 'number' && !isNaN(s)) return Math.round(s * TICKS_PER_SECOND);
  return null;
}

/**
 * Find (exact-name at project ROOT) or create a top-level bin.
 * Existence check FIRST — createBinAction on a taken name spawns "Shorts 2" dupes.
 * v0.1.1: one shared implementation (shared/binMove.ensureRootBin, ex-partsBuilder.ensureBin).
 */
var ensureBin = require('../shared/binMove').ensureRootBin;

// v0.1.1: the local findSequenceItemInRoot + ONE-ARG bin.createMoveItemAction(item) helper
// (a silent no-op in live Premiere) are replaced by shared/binMove —
// findSequenceProjectItem + moveItemToBin (two-arg call on root, verified read-back).

/** getTrackItems is ASYNC + enum in the new API — the sync no-arg call may return a
 *  Promise → .length undefined → silent no-op (partsBuilder v1.6.1 lesson). */
async function getClipItemsCompat(track) {
  var CLIP = (ppro.Constants && ppro.Constants.TrackItemType
    && ppro.Constants.TrackItemType.CLIP !== undefined)
    ? ppro.Constants.TrackItemType.CLIP : 1;
  var items = null;
  try { items = await track.getTrackItems(CLIP, false); } catch (e) { /* next */ }
  if (!items || !items.length) { try { items = await track.getTrackItems(1, false); } catch (e) { /* next */ } }
  if (!items || !items.length) { try { items = await track.getTrackItems(); } catch (e) { /* give up */ } }
  return items || [];
}

/** Remove everything on one track (seed cleanup) — sequenceFactory selection-removal,
 *  the ONLY reliable removal in 25.6. Leftovers stay invisible (1-frame seed trim). */
async function clearTrack(project, seq, track, mediaType, label, logger) {
  if (!track) return;
  if (sequenceFactory && sequenceFactory.removeAllItemsOnTrack) {
    try {
      var ed = ppro.SequenceEditor.getEditor(seq);
      await sequenceFactory.removeAllItemsOnTrack(project, ed, track, mediaType, logger, label);
    } catch (e) { if (logger) logger.warn('clear ' + label + ' via selection failed: ' + e.message); }
  }
  var left = (await getClipItemsCompat(track)).length;
  if (left && logger) logger.warn('Clear ' + label + ': ' + left + ' item(s) REMAIN (1-frame seed trim keeps them invisible)');
}

/** Resolve source ProjectItem by name; import by path + re-resolve when absent
 *  (importFiles does NOT return usable items). */
async function resolveSourceItem(project, file, path, logger) {
  var item = file ? await findProjectItemByName(project, file, logger) : null;
  if (!item && path) {
    try {
      await project.importFiles([path]);
      if (logger) logger.info('Imported source: ' + path);
    } catch (e) {
      if (logger) logger.warn('importFiles failed for ' + path + ': ' + e.message);
    }
    var name = file || String(path).replace(/\\/g, '/').split('/').pop();
    item = await findProjectItemByName(project, name, logger);
  }
  return item;
}

/** Markers owner — API varies by build: ppro.Markers.getMarkers(seq) OR seq.getMarkers(). */
async function getMarkersOwner(sequence, logger) {
  try {
    if (ppro.Markers && typeof ppro.Markers.getMarkers === 'function') {
      var owner = await ppro.Markers.getMarkers(sequence);
      if (owner) return owner;
    }
  } catch (e) { if (logger) logger.debug('ppro.Markers.getMarkers: ' + e.message); }
  try {
    if (typeof sequence.getMarkers === 'function') return await sequence.getMarkers();
  } catch (e2) { if (logger) logger.debug('seq.getMarkers: ' + e2.message); }
  return null;
}

/**
 * Add chapter markers: createAddMarkerAction (type param is IGNORED by Premiere),
 * then SEPARATE transactions for createSetTypeAction(chapter URI) + color by index
 * (sceneMarkers.js pattern). Best-effort — marker failures never fail the build.
 *
 * @param {Array} markerList - [{name, comment, startTicks, durationTicks}]
 */
async function addChapterMarkers(project, sequence, markerList, colorIdx, logger) {
  if (!markerList || !markerList.length) return 0;
  var owner = await getMarkersOwner(sequence, logger);
  if (!owner || typeof owner.createAddMarkerAction !== 'function') {
    if (logger) logger.warn('Shorts markers: markers API unavailable — skipping');
    return 0;
  }
  var added = 0;
  for (var i = 0; i < markerList.length; i++) {
    var m = markerList[i];
    try {
      var start = tickTimeFromTicks(m.startTicks || 0);
      var dur = (m.durationTicks > 0) ? tickTimeFromTicks(m.durationTicks) : ppro.TickTime.TIME_ZERO;
      (function (mm, st, du) {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(owner.createAddMarkerAction(mm.name, 'Comment', st, du, mm.comment || ''));
          }, 'Shorts marker ' + mm.name);
        });
      })(m, start, dur);
      added++;
    } catch (e) {
      if (logger) logger.debug('marker "' + m.name + '" failed: ' + e.message);
    }
  }
  if (!added) return 0;
  // Type=chapter + color — separate guarded transactions, matched by name.
  try {
    var all = (typeof owner.getMarkers === 'function') ? await owner.getMarkers() : null;
    if (all && all.length) {
      var wanted = {};
      for (var w = 0; w < markerList.length; w++) wanted[markerList[w].name] = 1;
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          for (var mi = 0; mi < all.length; mi++) {
            try {
              var nm = all[mi].getName ? all[mi].getName() : (all[mi].name || '');
              if (wanted[nm] && typeof all[mi].createSetColorByIndexAction === 'function' && colorIdx != null) {
                ca.addAction(all[mi].createSetColorByIndexAction(colorIdx));
              }
            } catch (eC) { /* per-marker guard */ }
          }
        }, 'Shorts marker colors');
      });
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          for (var mj = 0; mj < all.length; mj++) {
            try {
              var nm2 = all[mj].getName ? all[mj].getName() : (all[mj].name || '');
              if (wanted[nm2] && typeof all[mj].createSetTypeAction === 'function') {
                ca.addAction(all[mj].createSetTypeAction(MARKER_TYPE_CHAPTER));
              }
            } catch (eT) { /* per-marker guard */ }
          }
        }, 'Shorts marker types');
      });
    }
  } catch (e2) {
    if (logger) logger.debug('marker type/color pass failed (non-fatal): ' + e2.message);
  }
  return added;
}

// ═══════════════════════════════ SPIKE S-1 (static reframe probe) ═══════════════════════════════

/**
 * Probe whatever Motion/Position component APIs exist and try a STATIC horizontal
 * position shift from reframe.crop_center_x_pct. EVERYTHING guarded — never fails
 * the build; returns a one-line verdict string (also logged).
 */
async function trySetMotionStatic(project, trackItem, cropCenterXPct, logger) {
  var verdict;
  try {
    if (cropCenterXPct == null) return 'S-1 spike: skipped (no reframe.crop_center_x_pct)';
    if (!trackItem) return 'S-1 spike: motion API absent (no track item to probe)';
    var chain = null, via = '';
    try {
      if (typeof trackItem.getComponentChain === 'function') {
        chain = await trackItem.getComponentChain();
        via = 'trackItem.getComponentChain';
      }
    } catch (e) { /* next probe */ }
    if (!chain) {
      try {
        var vclip = (ppro.VideoClipTrackItem && typeof ppro.VideoClipTrackItem.cast === 'function')
          ? ppro.VideoClipTrackItem.cast(trackItem) : null;
        if (vclip && typeof vclip.getComponentChain === 'function') {
          chain = await vclip.getComponentChain();
          via = 'VideoClipTrackItem.cast';
        }
      } catch (e2) { /* next probe */ }
    }
    if (!chain) return 'S-1 spike: motion API absent (no component chain via trackItem or VideoClipTrackItem.cast)';
    var comps = [];
    try { comps = (await chain.getComponents()) || []; }
    catch (e3) { return 'S-1 spike: motion API absent (getComponents failed: ' + e3.message + ')'; }
    var motion = null;
    for (var i = 0; i < comps.length; i++) {
      var dn = '', mn = '';
      try { dn = comps[i].displayName || ''; mn = comps[i].matchName || ''; } catch (e4) { /* skip */ }
      if (/motion/i.test(dn) || /Motion/.test(mn)) { motion = comps[i]; break; }
    }
    if (!motion) return 'S-1 spike: motion API absent (no Motion component among ' + comps.length + ' in chain)';
    var pos = null;
    try {
      var n = (typeof motion.getParamCount === 'function') ? await motion.getParamCount() : 0;
      for (var p = 0; p < n; p++) {
        var prm = await motion.getParam(p);
        var pdn = '';
        try { pdn = (prm && prm.displayName) || ''; } catch (e5) { /* skip */ }
        if (/^position$/i.test(pdn)) { pos = prm; break; }
      }
    } catch (e6) { return 'S-1 spike: motion API absent (param enumeration failed: ' + e6.message + ')'; }
    if (!pos) return 'S-1 spike: motion API absent (Motion component has no Position param)';
    // Static reframe: Position x is normalized (0.5 = centered). Shift so that the
    // crop center lands mid-frame: crop 42% → x = 0.5 + (50-42)/100 = 0.58.
    var x = 0.5 + (50 - Number(cropCenterXPct)) / 100;
    var cur = null;
    try {
      var start = (typeof pos.getStartValue === 'function') ? await pos.getStartValue() : null;
      cur = start && start.value != null
        ? (start.value.value != null ? start.value.value : start.value)
        : null;
    } catch (e7) { /* value shape probe only */ }
    var newVal;
    if (cur && typeof cur === 'object' && cur.x != null) newVal = { x: x, y: (cur.y != null ? cur.y : 0.5) };
    else if (Array.isArray(cur)) newVal = [x, cur.length > 1 ? cur[1] : 0.5];
    else newVal = x;
    var kf = null;
    try {
      kf = (typeof pos.createKeyframe === 'function') ? pos.createKeyframe(newVal) : null;
    } catch (e8) { return 'S-1 spike: motion API present but createKeyframe rejected value (' + e8.message + ')'; }
    if (!kf) return 'S-1 spike: motion API absent (Position has no createKeyframe)';
    try {
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(pos.createSetValueAction(kf, true));
        }, 'S-1 Motion Position');
      });
    } catch (e9) { return 'S-1 spike: motion API present but createSetValueAction failed (' + e9.message + ')'; }
    verdict = 'S-1 spike: motion component API available — position set (x=' + x.toFixed(3) + ' via ' + via + ')';
  } catch (e) {
    verdict = 'S-1 spike: motion API absent (' + e.message + ')';
  }
  if (logger && verdict) logger.info(verdict);
  return verdict;
}

// ═══════════════════════════════ BUILDERS ═══════════════════════════════

/**
 * Preview sequence {CODE}_Shorts_Preview_v{N}: source FULL LENGTH on V1 + one
 * chapter range-marker per non-rejected candidate (boundaries edited by dragging
 * markers in the timeline; Read Back Markers collects the edits).
 *
 * createSequenceFromMedia IGNORES the seed in/out (HANDOFF_UXP) — the seed lands
 * full length, which is exactly what the preview wants; the 1-frame trim only
 * protects fallback paths and is cleared right after.
 *
 * @returns {{sequence, seqName, markers, candidates}}
 */
async function buildPreviewSequence(project, brief, opts) {
  opts = opts || {};
  var logger = opts.logger || noopLogger;
  var fps = (brief && brief.project && brief.project.fps) || 25;
  var code = (brief && brief.project && brief.project.code) || 'YT';
  var version = (brief && brief.version != null) ? brief.version : 1;
  var seqName = code + '_Shorts_Preview_v' + version;
  var src = (brief && brief.project && brief.project.source) || {};
  var markers = planPreview(brief, opts.statuses);

  logger.info('shortsBuilder v' + SHORTS_BUILDER_VERSION + ' — preview → ' + seqName
    + ' (' + markers.length + ' candidate marker(s), source ' + (src.file || '?') + ')');

  var raw = await resolveSourceItem(project, src.file, src.path, logger);
  if (!raw) throw new Error('Preview source not found/importable: ' + (src.file || src.path || '?'));

  var bin = await ensureBin(project, SHORTS_BIN, logger);
  await cleanExistingSequence(project, seqName, logger, bin);

  var cast = ppro.ClipProjectItem.cast(raw) || raw;
  setSourceInOut(project, cast, ppro.TickTime.createWithSeconds(0),
    ppro.TickTime.createWithSeconds(1 / fps), 'preview-seed', logger);
  var seq = null;
  try {
    seq = await project.createSequenceFromMedia(seqName, [cast]);
  } catch (e) {
    logger.warn('createSequenceFromMedia failed: ' + e.message);
  }
  clearSourceInOut(project, cast, 'preview-seed', logger);
  var seeded = !!seq;
  if (!seq) {
    seq = await project.createSequence(seqName);
    if (!seq) throw new Error('Failed to create preview sequence: ' + seqName);
    // Fallback: place the source full-length on V1/A1 by hand (no in/out set = full).
    try {
      var ed = ppro.SequenceEditor.getEditor(seq);
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(ed.createOverwriteItemAction(raw, ppro.TickTime.TIME_ZERO, 0, 0));
        }, 'Preview source full-length');
      });
    } catch (eP) {
      logger.error('Preview fallback placement failed: ' + eP.message);
    }
  }
  logger.info('Preview base on V1 (' + (seeded ? 'seeded full-length' : 'fallback overwrite') + ')');

  var added = await addChapterMarkers(project, seq, markers, MARKER_COLOR_INDEX.Cyan, logger);
  logger.info('Preview markers: ' + added + '/' + markers.length + ' placed');

  try {
    var seqItem = await findSequenceProjectItem(project, seq, seqName);
    if (bin && seqItem) await moveItemToBin(project, seqItem, bin, logger, { name: seqName });
  } catch (eB) { logger.warn('bin move: ' + eB.message); }

  try {
    if (typeof project.setActiveSequence === 'function') await project.setActiveSequence(seq);
  } catch (eA) { logger.debug('setActiveSequence: ' + eA.message); }

  return { sequence: seq, seqName: seqName, markers: added, candidates: markers.length };
}

/**
 * Build ONE 9:16 short sequence {CODE}_S{NN}_{slug} from an approved candidate.
 * Tick-grid placement, sequential ascending transactions, applyMediaSettings forces
 * 1080×1920 @ brief fps, chapter metadata marker at 0, S-1 spike, 2ms verify gate.
 *
 * @param {Object} project
 * @param {Object} candidate - ytai-shorts-v1 candidate
 * @param {Object} brief - the whole _in.json
 * @param {Object} [opts] - { logger, markerReadback }
 * @returns {Object} build report {short_id, sequence, built_at, drift_ms, ok, clips[],
 *   spike_s1, placed, skipped, seq} (seq = live Sequence — strip before persisting)
 */
async function buildShortSequence(project, candidate, brief, opts) {
  opts = opts || {};
  var logger = opts.logger || noopLogger;
  var fps = (brief && brief.project && brief.project.fps) || 25;
  var code = (brief && brief.project && brief.project.code) || 'YT';
  var sid = (candidate && candidate.short_id) || 'S00';
  var slug = (candidate && candidate.slug) || 'short';
  var seqName = code + '_' + sid + '_' + slug;
  var rt = (brief && brief.render_target) || {};

  var plan = planShort(candidate, brief, { markerReadback: opts.markerReadback });
  if (!plan.length) throw new Error(sid + ': no blocks to place');

  logger.info('shortsBuilder v' + SHORTS_BUILDER_VERSION + ' — ' + sid + ' → ' + seqName
    + ' (' + plan.length + ' block(s), ' + (plan[plan.length - 1].timelineOutTicks / TICKS_PER_SECOND).toFixed(2) + 's)');

  // Resolve every unique source (import + re-resolve when absent).
  var itemsByFile = {};
  for (var ri = 0; ri < plan.length; ri++) {
    var key = plan[ri].sourceFile || plan[ri].sourcePath;
    if (!key) throw new Error(sid + ' ' + plan[ri].blockId + ': block has no source');
    if (!itemsByFile[key]) {
      itemsByFile[key] = await resolveSourceItem(project, plan[ri].sourceFile, plan[ri].sourcePath, logger);
      if (!itemsByFile[key]) throw new Error(sid + ': source not found/importable: ' + key);
    }
    plan[ri]._itemKey = key;
  }

  var bin = await ensureBin(project, SHORTS_BIN, logger);
  await cleanExistingSequence(project, seqName, logger, bin);

  // Seed from the first block's media (format inheritance), trimmed to ONE FRAME so
  // any failed removal leaves an invisible speck, not a full-length clip.
  var seedRaw = itemsByFile[plan[0]._itemKey];
  var seedCast = ppro.ClipProjectItem.cast(seedRaw) || seedRaw;
  setSourceInOut(project, seedCast, ppro.TickTime.createWithSeconds(0),
    ppro.TickTime.createWithSeconds(1 / fps), 'seed-trim', logger);
  var seq = null;
  try {
    seq = await project.createSequenceFromMedia(seqName, [seedCast]);
  } catch (ex) {
    logger.warn('createSequenceFromMedia failed, using createSequence: ' + ex.message);
    seq = await project.createSequence(seqName);
  }
  if (!seq) throw new Error('Failed to create short sequence: ' + seqName);
  var seqEditor = ppro.SequenceEditor.getEditor(seq);

  // Force the vertical render target (createSequenceFromMedia inherits the SOURCE
  // format — 9:16 must be applied explicitly).
  try {
    await applyMediaSettings(project, seq, {
      width: rt.width || 1080,
      height: rt.height || 1920,
      fps: rt.fps || fps,
      sample_rate: 48000
    }, logger);
  } catch (eMS) { logger.warn('applyMediaSettings: ' + eMS.message); }

  // Clear the auto-seeded clip BEFORE placements (selection-removal — the only
  // reliable removal in 25.6).
  var MT = ppro.Constants && ppro.Constants.MediaType ? ppro.Constants.MediaType : { VIDEO: 0, AUDIO: 1 };
  try { await clearTrack(project, seq, await seq.getVideoTrack(0), MT.VIDEO, 'seed V1', logger); } catch (e) { logger.debug('seed V1 clear: ' + e.message); }
  try {
    if (typeof seq.getAudioTrack === 'function') {
      await clearTrack(project, seq, await seq.getAudioTrack(0), MT.AUDIO, 'seed A1', logger);
    }
  } catch (e) { logger.debug('seed A1 clear: ' + e.message); }

  // V1/A1 must exist before overwrite (does NOT auto-create tracks). Usually a no-op
  // after createSequenceFromMedia; load-bearing on the empty-createSequence fallback.
  if (sequenceFactory && sequenceFactory.ensureTracks) {
    try { await sequenceFactory.ensureTracks(project, seq, seqEditor, seedRaw, 1, 1, logger); }
    catch (eT) { logger.warn('ensureTracks: ' + eT.message); }
  }
  clearSourceInOut(project, seedCast, 'seed-trim', logger);

  // === Placement: ascending timeline order, ONE transaction per placement ===
  // (compound transactions execute overwrites in REVERSE — forbidden, memory frame-floor)
  var placed = 0, skipped = 0;
  for (var s = 0; s < plan.length; s++) {
    var entry = plan[s];
    var raw = itemsByFile[entry._itemKey];
    var castI = ppro.ClipProjectItem.cast(raw) || raw;
    var label = sid + '/' + entry.blockId;

    // Color BEFORE insert — TrackItems inherit the ProjectItem color at insert time;
    // colors never apply retroactively.
    applyColorByIndex(project, raw, entry.colorIndex, label, logger);
    setSourceInOut(project, castI, tickTimeFromTicks(entry.srcInTicks),
      tickTimeFromTicks(entry.srcOutTicks), label, logger);

    var tlTime = tickTimeFromTicks(entry.timelineInTicks);
    var ok = false;
    try {
      (function (rawItem, t, vIdx, aIdx, lbl) {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(seqEditor.createOverwriteItemAction(rawItem, t, vIdx, aIdx));
          }, 'Short overwrite: ' + lbl);
        });
      })(raw, tlTime, entry.vIdx, entry.aIdx, label);
      ok = true;
      if (entry.aIdx === -1) {
        logger.info('  ' + label + ': keep_audio=false → aIdx -1 (NB: some builds auto-route mute to A1 — verify)');
      }
    } catch (ePl) {
      logger.error('  place failed ' + label + ': ' + ePl.message);
    }
    clearSourceInOut(project, castI, label, logger);
    if (ok) {
      placed++;
      logger.info('[' + (s + 1) + '/' + plan.length + '] ' + label + ' ' + (entry.sourceFile || '?')
        + ' src ' + (entry.srcInTicks / TICKS_PER_SECOND).toFixed(3) + '-' + (entry.srcOutTicks / TICKS_PER_SECOND).toFixed(3)
        + ' @ TL ' + (entry.timelineInTicks / TICKS_PER_SECOND).toFixed(3) + 's'
        + ' (' + entry.role + ', color ' + entry.colorIndex + ', a' + entry.aIdx + ')');
    } else {
      skipped++;
    }
  }

  // === Self-documenting chapter marker at 0 ===
  try {
    var firstB = (candidate.blocks && candidate.blocks[0]) || {};
    var lastB = (candidate.blocks && candidate.blocks[candidate.blocks.length - 1]) || {};
    var total = (candidate.score && candidate.score.total != null) ? candidate.score.total : '?';
    var srcFile = (firstB.source && firstB.source.file)
      || (brief.project && brief.project.source && brief.project.source.file) || '?';
    var mComment = 'score:' + total
      + '|hook:' + (candidate.hook_text || '')
      + '|src:' + srcFile + '@' + ((firstB.tc_in && firstB.tc_in.tc) || '?') + '-' + ((lastB.tc_out && lastB.tc_out.tc) || '?');
    await addChapterMarkers(project, seq,
      [{ name: sid + ' [' + total + '] ' + slug, comment: mComment, startTicks: 0, durationTicks: 0 }],
      MARKER_COLOR_INDEX.Yellow, logger);
  } catch (eMk) { logger.debug('metadata marker: ' + eMk.message); }

  // === Read back V1 for spike + verify gate ===
  var withPos = [];
  try {
    var vTrack = await seq.getVideoTrack(0);
    var items = await getClipItemsCompat(vTrack);
    for (var ii = 0; ii < items.length; ii++) {
      var stT = null, duT = null;
      try { stT = await items[ii].getStartTime(); } catch (e) { /* skip */ }
      try { duT = await items[ii].getDuration(); } catch (e) { /* skip */ }
      var st = ttTicksNum(stT);
      if (st == null) continue;
      withPos.push({ item: items[ii], startTicks: st, durTicks: ttTicksNum(duT) });
    }
    withPos.sort(function (a, b) { return a.startTicks - b.startTicks; });
  } catch (eRB) { logger.warn('verify read-back failed: ' + eRB.message); }

  // Spike S-1: static reframe probe on the first placed clip (guarded, never fatal).
  var spike = 'S-1 spike: not attempted (no placed clips)';
  if (withPos.length) {
    spike = await trySetMotionStatic(project, withPos[0].item,
      candidate.reframe && candidate.reframe.crop_center_x_pct, logger);
  }

  // Verify gate: measured vs planned, tolerance 2ms.
  var maxDriftTicks = 0;
  var verifyError = null;
  if (withPos.length !== plan.length) {
    verifyError = 'expected ' + plan.length + ' clip(s) on V1, found ' + withPos.length;
  }
  var clips = [];
  var nCmp = Math.min(withPos.length, plan.length);
  for (var ci = 0; ci < nCmp; ci++) {
    var pl = plan[ci], got = withPos[ci];
    maxDriftTicks = Math.max(maxDriftTicks, Math.abs(got.startTicks - pl.timelineInTicks));
    if (got.durTicks != null) {
      maxDriftTicks = Math.max(maxDriftTicks, Math.abs(got.durTicks - (pl.timelineOutTicks - pl.timelineInTicks)));
    }
    clips.push({
      timeline_start: { sec: got.startTicks / TICKS_PER_SECOND, ticks: got.startTicks },
      duration: {
        sec: (got.durTicks != null ? got.durTicks : 0) / TICKS_PER_SECOND,
        ticks: (got.durTicks != null ? got.durTicks : 0)
      },
      source_in: { sec: pl.srcInTicks / TICKS_PER_SECOND, ticks: pl.srcInTicks },
      source_out: { sec: pl.srcOutTicks / TICKS_PER_SECOND, ticks: pl.srcOutTicks }
    });
  }
  var driftMs = Math.round(maxDriftTicks / TICKS_PER_SECOND * 1000 * 1000) / 1000;
  var okBuild = !verifyError && skipped === 0 && driftMs <= 2;
  logger.info(sid + (okBuild ? ' built ✓' : ' built ✗') + ' (drift ' + driftMs + 'ms'
    + (verifyError ? ', ' + verifyError : '') + (skipped ? ', ' + skipped + ' skipped' : '') + ')');

  // File the sequence into the Shorts bin (non-fatal).
  try {
    var seqItem = await findSequenceProjectItem(project, seq, seqName);
    if (bin && seqItem) await moveItemToBin(project, seqItem, bin, logger, { name: seqName });
  } catch (eBin) { logger.warn('bin move: ' + eBin.message); }

  var report = {
    short_id: sid,
    sequence: seqName,
    built_at: new Date().toISOString(),
    drift_ms: driftMs,
    ok: okBuild,
    clips: clips,
    spike_s1: spike,
    placed: placed,
    skipped: skipped,
    seq: seq
  };
  if (verifyError) report.verify_error = verifyError;
  return report;
}

module.exports = {
  SHORTS_BUILDER_VERSION,
  SHORTS_BIN,
  ROLE_COLOR_INDEX,
  boundaryTicks,
  planShort,
  planPreview,
  validateShortsBrief,
  buildPreviewSequence,
  buildShortSequence,
  trySetMotionStatic
};
