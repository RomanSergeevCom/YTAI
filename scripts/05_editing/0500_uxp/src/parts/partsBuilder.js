/**
 * partsBuilder.js — Build ONE "part" sequence (block/colour chunk) with 2V+2A.
 *
 * NEW STAGE: "сборка по частям". Instead of assembling the whole film, build it
 * one part at a time (each part = a colour/block), as its OWN named sequence.
 *
 * Difference from assemblyBuilder.js (which it does NOT touch):
 *   - ABSOLUTE placement by `timeline_in` (createOverwriteItemAction at exact
 *     position) — NOT end-to-end cumulative. Lets a B-roll layer overlay a
 *     continuous voice layer underneath.
 *   - Honours `track`/`audio_track` per segment → 2 video + 2 audio tracks
 *     (V1/V2, A1/A2). `track` is read here (in Assembly it is dead).
 *   - keeps audio (link) — voice video on V1 with its audio on A1; shown B-roll
 *     on V2 (above) with its nat-sound on A2. keep_audio=false → audio muted (-1).
 *   - sequence name = part.sequence_name (e.g. "YTCR04_part_Hook_Setup").
 *
 * Reuses shared/clipActions + shared/constants + ingest/placement/sequenceFactory.
 * Input = the ytai-part-v1 JSON (see 02_Assembly/parts/{CODE}_part_{name}.json).
 *
 * Pattern (absolute, like ingest wallClock / review):
 *   1. createSequenceFromMedia(seed clip) → valid media settings + V1/A1
 *   2. ensureTracks → V2/A2 exist (overwrite does NOT auto-create tracks)
 *   3. per segment: cast → applyColor → setSourceInOut(tc_in,tc_out)
 *      → createOverwriteItemAction(rawItem, timeline_in, vIdx, aIdx) → clear
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

const { applyColorToItem, setSourceInOut, clearSourceInOut, cleanExistingSequence } = require('../shared/clipActions');
const { findProjectItemByName } = require('../shared/projectItemFinder');

let sequenceFactory = null;
try { sequenceFactory = require('../ingest/placement/sequenceFactory'); } catch (e) { /* optional */ }

// Chapter markers with duration + colour + Chapter type — proven module from the ingest flow.
let sceneMarkers = null;
try { sceneMarkers = require('../ingest/placement/sceneMarkers'); } catch (e) { /* optional */ }

var PARTS_BUILDER_VERSION = '1.13.0'; // 1.13.0 (2026-09-15): review-CUT base_segment.disabled → V1/A1 piece disabled via createSetDisabledAction (Роман выключил кусок ката = «вырезать»; card.disabled_ranges → make_review_v6 base_segments). 1.12.0 (2026-09-15): part.bin move FIXED — shared binMove (TWO-arg root.createMoveItemAction(item, bin) + read-back; the old one-arg call silently left every part/review sequence in root) → part.bin "00_Source_Timelines" / "05_Review" really files the sequence; auto-version "taken" names = ALL sequences (getSequences) ∪ root, so _v{N} keeps counting once versions live in bins. 1.11.1: item_marker verified after add — name/comments re-set via Marker setters when the add-action left them empty (Roman saw nameless clip markers), warn-level log when no Markers API. 1.11.0: seg.item_marker {name, comment} — best-effort MASTER-CLIP marker on the segment's projectItem (Roman: ТЗ text copyable from the clip on the timeline; unique item per ТЗ so no cross-talk) + aNeeded no longer mirrors vNeeded (6 video overlay tracks must not spawn 6 audio tracks; audio tracks = max(2, deepest audio_track)). 1.10.1: chapter_markers pass no_chapter_type through to sceneMarkers (coloured TZ-span markers stay Comment-type, chapters stay Chapter) + still images (png/jpg) keep aIdx=-1 in review mode (no audio component — the A1-protection reroute is for real audio only). 1.10.0: auto-version — every build creates a NEW "<name>_v{N}" sequence (default ON when part.base_clip; part.auto_version overrides). 1.9.0: chapter SPANS — chapter_markers via sceneMarkers (duration+colour+Chapter type) + base_segments[].color paints V1 per chapter (boundaries visible on the track). 1.8.0: part.chapter_markers[]. 1.7.0: optional part.bin — ensureBin at root + move built sequence into it (non-fatal, warn + root on any failure). 1.6.2: 25.6 has NO working naive removal (createEmptySelection needs a CALLBACK, TrackItem.createRemoveAction absent) → clear via sequenceFactory selection-removal + seed/placeholder trimmed to 1 FRAME so even failed removals leave nothing visible + audio-only tracks excluded from pre-warm (TX insert auto-creates). 1.6.1: seed cleared BEFORE ensureTracks + async getTrackItems in clear + review base re-placed explicitly. 1.6.0: audio-only via TX pattern (insert vIdx=-1, limitShift=true) + ensureTracks honours audio_track (A5). 1.5.0: seg.marker_duration_sec. 1.3.0: cut-SUGGESTION markers. 1.2.0: review-CUT base_segments. 1.1.6: inserts never write A1.

/** Audio-only source (recorder WAV etc.) — no video component; `track` is inert for these. */
function isAudioOnlyFile(name) {
  return /\.(wav|mp3|aif|aiff|m4a|flac)$/i.test(String(name || ''));
}

/** Still image (mockup PNG etc.) — no audio component at all. */
function isStillFile(name) {
  return /\.(png|jpe?g|gif|ti?f{1,2}|bmp|webp)$/i.test(String(name || ''));
}

/** "V1"/"A1" → 0, "V2"/"A2" → 1, default 0. */
function trackIndex(track) {
  if (track == null) return 0;
  var m = String(track).match(/(\d+)/);
  return m ? Math.max(0, parseInt(m[1], 10) - 1) : 0;
}

/** "MM:SS.mmm" or "M:SS.s" → seconds (fallback when *_sec missing). */
function tcToSec(tc) {
  if (tc == null) return 0;
  if (typeof tc === 'number') return tc;
  var m = String(tc).match(/(\d+):(\d+(?:\.\d+)?)/);
  return m ? parseInt(m[1], 10) * 60 + parseFloat(m[2]) : parseFloat(tc) || 0;
}

function srcIn(seg) { return seg.source_in_sec != null ? seg.source_in_sec : tcToSec(seg.tc_in); }
function srcOut(seg) { return seg.source_out_sec != null ? seg.source_out_sec : tcToSec(seg.tc_out); }
function tlIn(seg) { return seg.timeline_in_sec != null ? seg.timeline_in_sec : tcToSec(seg.timeline_in); }

// Bin helpers live in shared/binMove (2026-09-15): ensureRootBin = the former local
// ensureBin (exact-name check first, instance createBinAction, re-fetch + cast);
// findSequenceProjectItem = Sequence.getProjectItem() with the old root guid/name scan
// as fallback; moveItemToBin = TWO-arg root.createMoveItemAction(item, bin) + read-back.
// The former local "ONE-ARG call on the DESTINATION bin — live-proven" helper was NOT
// live-proven: it silently moved nothing (YTUVI02 auto-save: 05_Review sequences at root).
const { ensureRootBin, findSequenceProjectItem, moveItemToBin, collectTakenNames } = require('../shared/binMove');

/** getTrackItems is ASYNC and takes the TrackItemType enum (v2.2.7 lesson from
 *  sequenceFactory: the old sync call returned a Promise → .length undefined →
 *  the whole clear was a SILENT NO-OP and the seed stayed on the timeline). */
async function getClipItemsCompat(track) {
  var CLIP = (ppro.Constants && ppro.Constants.TrackItemType
    && ppro.Constants.TrackItemType.CLIP !== undefined)
    ? ppro.Constants.TrackItemType.CLIP : 1;
  var items = null;
  try { items = await track.getTrackItems(CLIP, false); } catch (e) { /* fallback below handles it */ }
  if (!items || !items.length) { try { items = await track.getTrackItems(1, false); } catch (e) { /* 2nd try of a 3-step fallback; last resort below */ } }
  if (!items || !items.length) { try { items = await track.getTrackItems(); } catch (e) { /* last resort; no logger here, caller treats [] as empty */ } }
  return items || [];
}

async function clearTrackItems(project, seq, tr, mediaType, label, logger) {
  if (!tr) return;
  // Preferred: the ONLY removal API in 25.6 (selection + createRemoveItemsAction),
  // via sequenceFactory (handles the createEmptySelection callback signature).
  if (sequenceFactory && sequenceFactory.removeAllItemsOnTrack) {
    try {
      var ed = ppro.SequenceEditor.getEditor(seq);
      await sequenceFactory.removeAllItemsOnTrack(project, ed, tr, mediaType, logger, label);
    } catch (e) { if (logger) logger.warn('clear ' + label + ' via selection failed: ' + e.message); }
  }
  var left = (await getClipItemsCompat(tr)).length;
  if (left && logger) logger.warn('Clear ' + label + ': ' + left + ' item(s) REMAIN (1-frame seed trim keeps them invisible)');
}

/** Remove every TrackItem currently on a video track (used to clear the seed clip). */
async function clearVideoTrack(project, seq, vIdx, logger) {
  try {
    var MT = ppro.Constants && ppro.Constants.MediaType ? ppro.Constants.MediaType : { VIDEO: 0, AUDIO: 1 };
    await clearTrackItems(project, seq, await seq.getVideoTrack(vIdx), MT.VIDEO, 'seed V' + (vIdx + 1), logger);
  } catch (e) { if (logger) logger.debug('clearVideoTrack: ' + e.message); }
}

/** Remove every TrackItem currently on an audio track (clears the seed clip's linked audio). */
async function clearAudioTrack(project, seq, aIdx, logger) {
  try {
    if (typeof seq.getAudioTrack !== 'function') return;
    var MT = ppro.Constants && ppro.Constants.MediaType ? ppro.Constants.MediaType : { VIDEO: 0, AUDIO: 1 };
    await clearTrackItems(project, seq, await seq.getAudioTrack(aIdx), MT.AUDIO, 'seed A' + (aIdx + 1), logger);
  } catch (e) { if (logger) logger.debug('clearAudioTrack: ' + e.message); }
}

/**
 * Build one part sequence.
 *
 * @param {Object} project   - Active Premiere project
 * @param {Object} clipMap   - { filename: projectItem } from projectScanner
 * @param {Object} part      - part header { code, name, color, sequence_name, seed_clip, fps }
 * @param {Array}  segments  - part segments (track, audio_track, keep_audio, source_file, tc_in/out, timeline_in/out)
 * @param {Object} logger
 * @param {Object} projectSettings
 * @returns {{ sequence, seqName, placed, skipped, tracks }}
 */
async function buildPartSequence(project, clipMap, part, segments, logger, projectSettings) {
  part = part || {};
  var code = part.code || 'PART';
  var partName = part.name || 'Untitled';
  var seqName = part.sequence_name || (code + '_part_' + partName);
  var partColor = part.color || null;

  // AUTO-VERSION (Roman 2026-08-20: «версия должна каждый раз обновляться»): every build makes a
  // NEW sequence "<name>_v{N}" instead of replacing the previous one, so versions can be compared
  // (canon: assembly versioning). Default ON for review builds (base_clip), opt-in elsewhere.
  var autoVersion = (part.auto_version != null) ? !!part.auto_version : !!part.base_clip;
  if (autoVersion) {
    try {
      // ALL sequences (any bin) ∪ root names — a root-only scan restarted at _v1 once
      // earlier versions really landed in part.bin (v1.12.0).
      var takenNames = await collectTakenNames(project, logger);
      var baseName = seqName.replace(/_v\d+$/, '');
      var vNext = 1;
      while (takenNames[baseName + '_v' + vNext]) vNext++;
      seqName = baseName + '_v' + vNext;
      if (logger) logger.info('Auto-version: building a NEW sequence → ' + seqName);
    } catch (eAV) { if (logger) logger.warn('auto-version skipped: ' + eAV.message); }
  }

  function resolveItem(sourceFile) {
    if (!sourceFile) return null;
    return clipMap[sourceFile] || clipMap[sourceFile.replace(/\.[^.]+$/, '')] || null;
  }

  if (logger) logger.info('partsBuilder v' + PARTS_BUILDER_VERSION + ' — part "' + partName + '" → ' + seqName);

  // part.min_builder: a JSON may rely on newer builder behaviour (e.g. no_chapter_type
  // pass-through) — an older copy of the plugin would silently degrade. Warn loudly.
  if (part.min_builder) {
    var need = String(part.min_builder).split('.').map(Number);
    var have = PARTS_BUILDER_VERSION.split('.').map(Number);
    var older = false;
    for (var vi = 0; vi < Math.max(need.length, have.length); vi++) {
      var n = need[vi] || 0, h = have[vi] || 0;
      if (h < n) { older = true; break; }
      if (h > n) break;
    }
    if (older && logger) logger.warn('⚠️ Part "' + partName + '" wants partsBuilder ≥' + part.min_builder +
      ', running v' + PARTS_BUILDER_VERSION + ' — build may silently degrade (reload the plugin in UDT).');
  }

  // Resolve + sort by absolute timeline position
  var segs = [];
  var missing = [];
  for (var i = 0; i < segments.length; i++) {
    if (resolveItem(segments[i].source_file)) segs.push(segments[i]);
    else missing.push(segments[i].source_file);
  }
  if (missing.length && logger) logger.warn('Parts: ' + missing.length + ' clip(s) not in project: ' + missing.join(', '));
  segs.sort(function (a, b) { return tlIn(a) - tlIn(b); });

  // === Optional REVIEW-OVERLAY base: keep the rendered video on V1, overlay inserts on V2/V3. ===
  // part.base_clip = filename of the rendered video (e.g. the v9 export); part.base_clip_path =
  // absolute path to import if it is not already in the project bin. When set, the base render is
  // placed full-length on V1 and KEPT — inserts overlay on their own tracks; an EMPTY insert set is
  // allowed (produces render on V1 + empty V2/V3 ready for manual work).
  var baseItem = null;
  if (part.base_clip) {
    // already in project? (clipMap = source bin only, so also BFS the whole tree, casting into bins)
    baseItem = resolveItem(part.base_clip) || await findProjectItemByName(project, part.base_clip, logger);
    if (!baseItem && part.base_clip_path) {
      try {
        await project.importFiles([part.base_clip_path]);
        if (logger) logger.info('Review base imported: ' + part.base_clip_path);
      } catch (eB) { if (logger) logger.warn('base import failed: ' + eB.message); }
      // importFiles does NOT return items here — resolve by name after import.
      baseItem = resolveItem(part.base_clip) || await findProjectItemByName(project, part.base_clip, logger);
    }
    if (baseItem && logger) logger.info('Review base → V1: ' + part.base_clip);
    else if (logger) logger.warn('base_clip not resolvable (overlay base skipped): ' + part.base_clip);
  }
  var reviewMode = !!baseItem;

  if (segs.length === 0 && !reviewMode) throw new Error('Parts: no resolvable segments — run INGEST first or check source_file names');

  // Resolve part.bin BEFORE archiving: same-name sequences from earlier builds live
  // INSIDE the bin, and a root-only archive scan would let the new build duplicate
  // the name there (verifier-confirmed regression of the archive guarantee).
  var targetBin = null;
  if (part.bin) {
    try { targetBin = await ensureRootBin(project, String(part.bin), logger); }
    catch (eEB) { if (logger) logger.warn('ensureRootBin(' + part.bin + '): ' + eEB.message); }
  }

  await cleanExistingSequence(project, seqName, logger, targetBin);

  // === Seed sequence. In review mode the seed IS the base render and is KEPT on V1. ===
  // Otherwise: seed placed at 0 for media settings then removed (each segment placed absolute below).
  var seedFile = (part.seed_clip && resolveItem(part.seed_clip)) ? part.seed_clip : (segs.length ? segs[0].source_file : null);
  var seedRaw = reviewMode ? baseItem : resolveItem(seedFile);
  var seedCast = ppro.ClipProjectItem.cast(seedRaw) || seedRaw;

  // Trim the seed to ONE FRAME before it ever touches the timeline: removal APIs are
  // shaky in this Premiere (25.6: no TrackItem.createRemoveAction), so even if every
  // removal fails, the auto-seeded clip and the pre-warm placeholders are 1-frame
  // specks at TL 0 that the real segments simply overwrite. Format inheritance is
  // unaffected (it comes from the media, not the in/out).
  var seedFps = (part.fps && part.fps > 0) ? part.fps : 25;
  setSourceInOut(project, seedCast, ppro.TickTime.createWithSeconds(0),
    ppro.TickTime.createWithSeconds(1 / seedFps), 'seed-trim', logger);

  var seq = null;
  try {
    seq = await project.createSequenceFromMedia(seqName, [seedCast]);
  } catch (ex) {
    if (logger) logger.warn('createSequenceFromMedia failed, using createSequence: ' + ex.message);
    seq = await project.createSequence(seqName);
  }
  if (!seq) throw new Error('Failed to create part sequence: ' + seqName);
  var seqEditor = ppro.SequenceEditor.getEditor(seq);

  // REVIEW-CUT mode: part.base_segments[] = trimmed render keep-segments (render tc -> tightened
  // timeline). V1 is REBUILT from them (cuttable) instead of holding one full render clip.
  var cutMode = reviewMode && Array.isArray(part.base_segments) && part.base_segments.length > 0;

  // The auto-seeded clip MUST leave the timeline BEFORE ensureTracks: pre-warm inserts
  // (limitShift=false) shift a non-empty timeline rightward and its sweep can orphan the
  // seed on new tracks — that produced full-length seed tails after the cut (v1.6.1 fix).
  // Review base is re-placed explicitly AFTER the tracks exist.
  await clearVideoTrack(project, seq, 0, logger);
  await clearAudioTrack(project, seq, 0, logger);

  // Ensure enough V/A tracks BEFORE placing (overwrite does NOT auto-create tracks).
  // base on V1 + overlays on the highest track any segment uses (V2/V3). Audio needs
  // its OWN max — a recorder WAV on A5 outruns the video-track count (V1-V4).
  // Audio-only segments are EXCLUDED from the pre-warm: they are placed via INSERT,
  // which auto-creates its A-track (the proven ingest TX path) — pre-warming their
  // track would only add a placeholder that inserts then push rightward.
  var maxV = 1, maxA = 1;
  for (var mi = 0; mi < segs.length; mi++) {
    maxV = Math.max(maxV, trackIndex(segs[mi].track || 'V1') + 1);
    if (segs[mi].keep_audio !== false && !isAudioOnlyFile(segs[mi].source_file)) {
      maxA = Math.max(maxA, trackIndex(segs[mi].audio_track || 'A1') + 1);
    }
  }
  var vNeeded = Math.max(2, maxV);
  var aNeeded = Math.max(2, maxA);   // v1.11.0: НЕ зеркалим vNeeded — оверлей-слоёв больше, чем звука
  if (sequenceFactory && sequenceFactory.ensureTracks) {
    try { await sequenceFactory.ensureTracks(project, seq, seqEditor, seedRaw, vNeeded, aNeeded, logger); }
    catch (e) { if (logger) logger.warn('ensureTracks: ' + e.message); }
  }

  // The 1-frame trim served the seeding + pre-warm; drop it before real placements
  // (in review mode the base is re-placed FULL-length right below).
  clearSourceInOut(project, seedCast, 'seed-trim', logger);

  // Review-overlay (non-cut): put the FULL base render back on clean V1/A1 now that
  // every track exists (it was cleared above so the pre-warm ran on an empty timeline).
  if (reviewMode && !cutMode) {
    try {
      var t0Base = ppro.TickTime.createWithSeconds(0);
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(seqEditor.createOverwriteItemAction(baseItem, t0Base, 0, 0));
        }, 'Review base full-length');
      });
      if (logger) logger.info('Review base re-placed full-length on V1/A1');
    } catch (eBase) {
      if (logger) logger.error('Review base re-place failed: ' + eBase.message);
    }
  }
  if (reviewMode && logger) {
    logger.info(cutMode
      ? 'Review-CUT: V1 rebuilt from ' + part.base_segments.length + ' render segment(s) (cuttable); overlaying ' + segs.length + ' inserts on V2/V3 (need V' + vNeeded + ').'
      : 'Review-overlay: base "' + part.base_clip + '" kept FULL on V1; overlaying ' + segs.length + ' inserts on V2/V3 (need V' + vNeeded + ').');
  }

  // 1.13.0: base_segment.disabled = Роман выключил этот кусок ката (Clip → Enable) → «вырезать».
  // После установки находим его элементы на V1/A1 по старту и выключаем одной транзакцией.
  async function disableBaseItemsAt(sec) {
    var targets = [];
    var tracks = [];
    try { tracks.push(await seq.getVideoTrack(0)); } catch (e) { if (logger) logger.debug('disableBaseItemsAt getVideoTrack(0): ' + (e && e.message)); }
    try { tracks.push(await seq.getAudioTrack(0)); } catch (e) { if (logger) logger.debug('disableBaseItemsAt getAudioTrack(0): ' + (e && e.message)); }
    for (var dt = 0; dt < tracks.length; dt++) {
      if (!tracks[dt]) continue;
      var its = await getClipItemsCompat(tracks[dt]);
      for (var di = 0; di < its.length; di++) {
        var st = null;
        try { st = await its[di].getStartTime(); } catch (e) { if (logger) logger.debug('disableBaseItemsAt getStartTime: ' + (e && e.message)); }
        var ss = st ? (typeof st.seconds === 'number' ? st.seconds : Number(st.ticks) / 254016000000) : null;
        if (ss !== null && Math.abs(ss - sec) < 0.02 && typeof its[di].createSetDisabledAction === 'function') targets.push(its[di]);
      }
    }
    if (!targets.length) return 0;
    var okD = false;
    project.lockedAccess(function () {
      okD = project.executeTransaction(function (ca) {
        for (var ti = 0; ti < targets.length; ti++) {
          var act = targets[ti].createSetDisabledAction(true);
          if (act) ca.addAction(act);
        }
      }, 'Disable base segment @' + sec.toFixed(2));
    });
    return okD === false ? 0 : targets.length;
  }

  // cutMode: place each trimmed render base_segment on V1/A1 (KEEP the render's voice audio).
  var basePlaced = 0;
  if (cutMode) {
    var bsegs = part.base_segments.slice().sort(function (a, b) { return tlIn(a) - tlIn(b); });
    var bCast = ppro.ClipProjectItem.cast(baseItem) || baseItem;
    for (var bi = 0; bi < bsegs.length; bi++) {
      var bs = bsegs[bi];
      var bid = 'base_' + (bs.seg_id || bi);
      // Chapter colour: base_segments split at chapter boundaries carry bs.color, so V1 changes
      // colour exactly where one chapter ends and the next begins (Roman 2026-08-20).
      if (bs.color) applyColorToItem(project, bCast, bs.color, bid, logger);
      setSourceInOut(project, bCast, ppro.TickTime.createWithSeconds(srcIn(bs)),
        ppro.TickTime.createWithSeconds(srcOut(bs)), bid, logger);
      var bTime = ppro.TickTime.createWithSeconds(tlIn(bs));
      var bok = false;
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(seqEditor.createOverwriteItemAction(baseItem, bTime, 0, 0));
          }, 'Review base ' + bid);
        });
        bok = true;
      } catch (eB) {
        try {
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) {
              ca.addAction(seqEditor.createInsertProjectItemAction(baseItem, bTime, 0, 0, false));
            }, 'Review base insert ' + bid);
          });
          bok = true;
        } catch (eB2) { if (logger) logger.error('  base seg place failed ' + bid + ': ' + eB2.message); }
      }
      clearSourceInOut(project, bCast, bid, logger);
      if (bok) basePlaced++;
      if (bok && bs.disabled) {
        try {
          var nDis = await disableBaseItemsAt(tlIn(bs));
          if (logger) logger[nDis ? 'info' : 'warn']('  ' + bid + ' disabled on V1/A1: ' + nDis + ' item(s) (Роман: вырезать)');
        } catch (eDis) { if (logger) logger.warn('  disable ' + bid + ' failed: ' + eDis.message); }
      }
    }
    if (logger) logger.info('Cuttable V1: ' + basePlaced + '/' + bsegs.length + ' render segment(s) placed on V1/A1.');
  }

  // Review-overlay: annotate each insert with a comment marker on the sequence timeline.
  // part.markers === false → NO markers at all (Roman: markers clutter the timeline; the montage
  // HTML is the reference instead).
  var markersOwner = null;
  var markerCount = 0;
  // markers === true also enables markers OUTSIDE review mode (thematic digest timelines):
  // then only segments carrying seg.marker_name get a marker (block headings = оглавление).
  var digestMarkers = (!reviewMode && part.markers === true);
  // Per-segment markers obey part.markers; chapter_markers are independent — they only need the owner.
  var segMarkersEnabled = (reviewMode || digestMarkers) && part.markers !== false;
  var wantChapterMarkers = Array.isArray(part.chapter_markers) && part.chapter_markers.length > 0;
  if (segMarkersEnabled || wantChapterMarkers) {
    // Marker API varies by Premiere version: try ppro.Markers.getMarkers(seq), then seq.getMarkers().
    try { if (ppro.Markers && ppro.Markers.getMarkers) markersOwner = await ppro.Markers.getMarkers(seq); }
    catch (eM) { if (logger) logger.debug('ppro.Markers.getMarkers: ' + eM.message); }
    if (!markersOwner) {
      try { if (typeof seq.getMarkers === 'function') markersOwner = await seq.getMarkers(); }
      catch (eM2) { if (logger) logger.debug('seq.getMarkers: ' + eM2.message); }
    }
    if (!markersOwner && logger) logger.warn('Review markers: no markers API available — skipping markers (inserts still placed).');
  }

  // === Place ALL segments by ABSOLUTE timeline_in on their track ===
  var placed = 0, skipped = 0;
  var itemMarked = {};   // projectItem name → уже помечен (item_marker кладём один раз)

  for (var s = 0; s < segs.length; s++) {
    var seg = segs[s];
    var segId = seg.segment_id || seg.segment_name || ('seg#' + s);
    var rawItem = resolveItem(seg.source_file);
    var castItem = ppro.ClipProjectItem.cast(rawItem) || rawItem;
    var audioOnly = isAudioOnlyFile(seg.source_file);
    var vIdx = trackIndex(seg.track || 'V1');
    var aIdx = (seg.keep_audio === false) ? -1 : trackIndex(seg.audio_track || 'A1');
    // REVIEW-OVERLAY: the render's own audio lives on A1. Inserts must NEVER write to A1 — this
    // Premiere version auto-routes audioTrackIndex=-1 (mute intent) to A1, which CUTS the render
    // audio. Force every insert's audio to A2+ matching its video track (V2→A2, V3→A3).
    // Stills have NO audio component — nothing can cut A1, keep their -1 (v1.10.1).
    if (reviewMode && aIdx < 1 && !isStillFile(seg.source_file)) aIdx = vIdx;

    if (audioOnly && aIdx < 0) {
      // Muted audio-only segment = nothing to place at all.
      if (logger) logger.info('[' + (s + 1) + '/' + segs.length + '] ' + segId + ' audio-only + keep_audio=false — skipped');
      skipped++;
      continue;
    }

    applyColorToItem(project, rawItem, partColor || seg.color, segId, logger);
    setSourceInOut(project, castItem, ppro.TickTime.createWithSeconds(srcIn(seg)),
      ppro.TickTime.createWithSeconds(srcOut(seg)), segId, logger);

    var tlTime = ppro.TickTime.createWithSeconds(tlIn(seg));
    var ok = false;
    if (audioOnly) {
      // Proven TX pattern (clipPlacer.placeTx / clipActions.insertDjiAudio): audio-only goes in
      // via INSERT with vIdx=-1 — overwrite needs the A-track to pre-exist, insert auto-creates
      // it (Adobe docs); limitShift=true confines ripple to the target track, and segments are
      // placed in ascending timeline_in order so there is never anything to the right to shift.
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(seqEditor.createInsertProjectItemAction(rawItem, tlTime, -1, aIdx, true));
          }, 'Part TX insert: ' + segId);
        });
        ok = true;
      } catch (exA) {
        if (logger) logger.error('  audio-only insert failed ' + segId + ': ' + exA.message);
      }
    } else {
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(seqEditor.createOverwriteItemAction(rawItem, tlTime, vIdx, aIdx));
          }, 'Part overwrite: ' + segId);
        });
        ok = true;
      } catch (ex) {
        if (reviewMode) {
          // NO insert fallback in review mode: insert with limitShift=false ripples EVERY
          // track and would silently cut/shift the untouched V1 base — the one guarantee
          // this mode makes. Skip loudly instead (v1.10.1).
          if (logger) logger.error('  place failed ' + segId + ' (review mode, no ripple fallback): ' + ex.message);
        } else {
          // Fallback: insert (auto-creates track; limitShift=false to keep absolute-ish)
          try {
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                ca.addAction(seqEditor.createInsertProjectItemAction(rawItem, tlTime, vIdx, aIdx, false));
              }, 'Part insert fallback: ' + segId);
            });
            ok = true;
            if (logger) logger.info('  insert fallback used for ' + segId);
          } catch (ex2) {
            if (logger) logger.error('  place failed ' + segId + ': ' + ex2.message);
          }
        }
      }
    }
    clearSourceInOut(project, castItem, segId, logger);

    if (ok && seg.item_marker && !itemMarked[seg.source_file]) {
      // v1.11.0: маркер на МАСТЕР-КЛИПЕ (projectItem) с полным текстом ТЗ — виден на
      // клипе в секвенции (Show Source Clip Markers), текст копируется из Markers panel.
      // Best-effort: не всякая сборка ppro отдаёт Markers для projectItem.
      itemMarked[seg.source_file] = 1;
      try {
        var imOwner = null;
        try { imOwner = await ppro.Markers.getMarkers(castItem); } catch (eIm1) { /* optional API on this build; rawItem fallback below */ }
        if (!imOwner) { try { imOwner = await ppro.Markers.getMarkers(rawItem); } catch (eIm2) { if (logger) logger.debug('Markers.getMarkers(rawItem) ' + segId + ': ' + (eIm2 && eIm2.message)); } }
        if (imOwner && typeof imOwner.createAddMarkerAction === 'function') {
          var imName = String(seg.item_marker.name || segId);
          var imText = String(seg.item_marker.comment || '');
          var imStart = ppro.TickTime.createWithSeconds(srcIn(seg));
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) {
              ca.addAction(imOwner.createAddMarkerAction(imName, 'Comment', imStart, ppro.TickTime.TIME_ZERO, imText));
            }, 'Item marker ' + segId);
          });
          // 1.11.1: на сборке 25.x createAddMarkerAction кладёт маркер, но имя/коммент могут
          // остаться пустыми (Роман видел клип-маркеры без имени и без комментов) —
          // дожимаем сеттерами на самом маркере и проверяем результат в лог.
          try {
            var imList = await imOwner.getMarkers();
            var imMk = null;
            for (var q = 0; q < (imList || []).length; q++) {
              var st = imList[q].getStart ? await imList[q].getStart() : null;
              if (st && Math.abs((st.seconds || 0) - srcIn(seg)) < 0.02) imMk = imList[q];
            }
            if (!imMk && imList && imList.length) imMk = imList[imList.length - 1];
            if (imMk) {
              var curName = imMk.getName ? await imMk.getName() : '';
              var curText = imMk.getComments ? await imMk.getComments() : '';
              if ((curName !== imName || curText !== imText) &&
                  typeof imMk.createSetNameAction === 'function') {
                project.lockedAccess(function () {
                  project.executeTransaction(function (ca2) {
                    ca2.addAction(imMk.createSetNameAction(imName));
                    if (typeof imMk.createSetCommentsAction === 'function') ca2.addAction(imMk.createSetCommentsAction(imText));
                  }, 'Item marker text ' + segId);
                });
                if (logger) logger.info('item_marker: name/comment set via setters for ' + segId);
              } else if (logger) logger.debug('item_marker OK ' + segId + ' name="' + curName + '" text=' + curText.length + ' chars');
            } else if (logger) logger.warn('item_marker: marker not found after add for ' + segId);
          } catch (eIm3) { if (logger) logger.warn('item_marker verify failed ' + segId + ': ' + eIm3.message); }
        } else if (logger) logger.warn('item_marker: no Markers API for ' + seg.source_file + ' — use panel button «Copy ТЗ @ playhead»');
      } catch (eIm) { if (logger) logger.debug('item_marker failed ' + segId + ': ' + eIm.message); }
    }
    if (ok) {
      placed++;
      if (logger) {
        var cInfo = (partColor || seg.color) ? ', color=' + (partColor || seg.color) : '';
        logger.info('[' + (s + 1) + '/' + segs.length + '] ' + segId + ' ' + seg.source_file +
          ' → ' + (audioOnly ? 'audio-only' : (seg.track || 'V1')) + '/' + (aIdx < 0 ? 'mute' : (seg.audio_track || 'A1')) +
          ' src ' + srcIn(seg).toFixed(2) + '-' + srcOut(seg).toFixed(2) +
          ' @ TL ' + tlIn(seg).toFixed(2) + 's' + cInfo);
      }
      if (markersOwner && segMarkersEnabled && (!digestMarkers || seg.marker_name)) {
        try {
          var mtag = seg.covers_gap ? '🔴 gap-fill' : (trackIndex(seg.track || 'V1') >= 2 ? '🎨 liveliness' : '🔵 reinforce');
          var mname = seg.marker_name || (mtag + ' · ' + ((seg.scene ? seg.scene + '/' : '') + (seg.clip_id || seg.source_file)));
          var mcomment = seg.note || '';
          var mtick = ppro.TickTime.createWithSeconds(tlIn(seg));
          // chapter markers (selections): marker_duration_sec stretches the marker over the block
          var mdur = (seg.marker_duration_sec > 0)
            ? ppro.TickTime.createWithSeconds(seg.marker_duration_sec)
            : ppro.TickTime.TIME_ZERO;
          if (typeof markersOwner.createAddMarkerAction === 'function') {
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                ca.addAction(markersOwner.createAddMarkerAction(mname, 'Comment', mtick, mdur, mcomment));
              }, 'Marker ' + segId);
            });
            markerCount++;
          } else if (typeof markersOwner.createMarker === 'function') {
            markersOwner.createMarker(mtick, 'Comment', mname, mcomment);
            markerCount++;
          }
        } catch (eMk) { if (logger) logger.debug('marker failed ' + segId + ': ' + eMk.message); }
      }
    } else { skipped++; }
  }

  // === CUT-SUGGESTION markers (review): flag spots that "would be good to cut" — NOT applied. ===
  // part.cut_suggestions[] = [{ tc_sec | timeline_in_sec, reason, text, confidence }]
  var cutMarks = 0;
  if (markersOwner && segMarkersEnabled && Array.isArray(part.cut_suggestions) && part.cut_suggestions.length) {
    for (var cs = 0; cs < part.cut_suggestions.length; cs++) {
      var sug = part.cut_suggestions[cs];
      try {
        var csec = (sug.tc_sec != null) ? sug.tc_sec : (sug.timeline_in_sec != null ? sug.timeline_in_sec : tcToSec(sug.tc_in));
        var ctick = ppro.TickTime.createWithSeconds(csec);
        var cname = '✂ CONSIDER CUT' + (sug.confidence ? ' (' + sug.confidence + ')' : '') +
          (sug.text ? ' · "' + String(sug.text).slice(0, 40) + '"' : '');
        var ccomment = (sug.reason || '') + (sug.text ? '  ::  ' + sug.text : '');
        if (typeof markersOwner.createAddMarkerAction === 'function') {
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) {
              ca.addAction(markersOwner.createAddMarkerAction(cname, 'Comment', ctick, ppro.TickTime.TIME_ZERO, ccomment));
            }, 'Cut suggestion ' + cs);
          });
          cutMarks++;
        } else if (typeof markersOwner.createMarker === 'function') {
          markersOwner.createMarker(ctick, 'Comment', cname, ccomment);
          cutMarks++;
        }
      } catch (eCs) { if (logger) logger.debug('cut-suggestion marker failed: ' + eCs.message); }
    }
    if (logger) logger.info('Cut-suggestion markers placed: ' + cutMarks + '/' + part.cut_suggestions.length);
  }
  markerCount += cutMarks;

  // === CHAPTER markers: part.chapter_markers[] = [{ tc_sec, name, comment, duration_sec, color }] ===
  // Delegated to sceneMarkers.addSceneMarkers: duration = the chapter SPAN in the marker ruler,
  // colour per chapter, Chapter marker type. Roman wants chapters readable on top of the timeline.
  var chapMarks = 0;
  if (Array.isArray(part.chapter_markers) && part.chapter_markers.length && sceneMarkers) {
    try {
      var chList = part.chapter_markers.map(function (chm, ci) {
        return {
          offset_sec: (chm.tc_sec != null) ? chm.tc_sec : tcToSec(chm.tc_in),
          duration_sec: chm.duration_sec,
          name: String(chm.name || ('Chapter ' + (ci + 1))),
          comment: String(chm.comment || ''),
          color: chm.color,
          // TZ-span review markers: coloured span WITHOUT the Chapter type (sceneMarkers
          // honours this flag) — so chapters stay chapters and ТЗ marks stay Comment.
          no_chapter_type: !!chm.no_chapter_type
        };
      });
      chapMarks = await sceneMarkers.addSceneMarkers(project, seq, chList, logger || console);
    } catch (eCh) { if (logger) logger.warn('chapter markers failed: ' + eCh.message); }
  }
  markerCount += chapMarks;

  var vCount = 0, aCount = 0;
  try { vCount = await seq.getVideoTrackCount(); aCount = await seq.getAudioTrackCount(); } catch (e) { /* counts only decorate the summary log line */ }
  if (logger) logger.info('Part "' + partName + '": ' + placed + '/' + segs.length + ' placed (' + skipped + ' skipped), tracks V' + vCount + '/A' + aCount +
    (reviewMode ? (cutMode ? ', V1 cut→' + basePlaced + ' segs' : ', base→V1') + ', markers=' + markerCount : '') + ' → ' + seqName);

  // Optional part.bin: move the built sequence into a top-level bin (resolved once
  // before the archive pass above). Every step non-fatal — any failure warns and
  // leaves the sequence in the project root. v1.12.0: moveItemToBin returns true ONLY
  // after a verified read-back (item in the bin, gone from root, no copy).
  var binName = null;
  if (part.bin) {
    try {
      if (!targetBin) targetBin = await ensureRootBin(project, String(part.bin), logger);
      var seqItem = targetBin ? await findSequenceProjectItem(project, seq, seqName) : null;
      if (targetBin && seqItem && await moveItemToBin(project, seqItem, targetBin, logger, { name: seqName })) {
        binName = String(part.bin);
        if (logger) logger.info('Sequence "' + seqName + '" → bin "' + binName + '"');
      } else if (logger) {
        logger.warn('Part "' + partName + '": sequence left in project root');
      }
    } catch (eBin) {
      if (logger) logger.warn('part.bin: ' + eBin.message);
    }
  }

  return { sequence: seq, seqName: seqName, placed: placed, skipped: skipped, markers: markerCount, reviewMode: reviewMode, cutMode: cutMode, basePlaced: basePlaced, bin: binName, tracks: { v: vCount, a: aCount } };
}

module.exports = {
  buildPartSequence,
  trackIndex,
  tcToSec,
  PARTS_BUILDER_VERSION
};
