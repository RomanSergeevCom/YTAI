/**
 * reviewBuilder.js — Build per-scene Review sequences.
 *
 * For each scene, creates a Review sequence that mirrors the Ingest timeline
 * with Assembly-used segments removed (gaps). Editor sees full footage
 * minus what's already in Assembly.
 *
 * Per-scene sequences:
 *   {CODE}_3_Review_01_apartment
 *   {CODE}_3_Review_02_outdoor
 *
 * Color scheme:
 *   Red      — block=99 (explicitly cut: noise, errors, repeats)
 *   Yellow   — priority=2 (alternative take)
 *   Purple   — synthetic gap / uncategorized footage
 *   Teal     — expert/talent speaking
 *   Lavender — producer/interviewer speaking
 *
 * Assembly gap markers show block name + color of the Assembly segment
 * that was taken, so editor knows what's already used and where it went.
 *
 * Depends on: clipActions (shared trim/color/insert operations)
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

const { REVIEW_COLOR_MAP, REVIEW_PRODUCER_COLOR, REVIEW_EXPERT_COLOR, LABEL_COLOR_INDEX } = require('../shared/constants');
const { applyColorByIndex, setSourceInOut, clearSourceInOut, cleanExistingSequence, insertDjiAudio } = require('../shared/clipActions');
const { snapToFrame, getFps } = require('../shared/frameSnap');

// Minimum gap duration (seconds) — gaps shorter than this are skipped
var MIN_GAP_DURATION = 0.3;

/**
 * Determine review category for a segment.
 */
function getReviewCategory(seg) {
  if (seg.block === 99) return 'cut';
  if (seg.priority === 2 || seg.priority === '2') return 'alt';
  return 'skip';
}

/**
 * Determine label color index for a review segment.
 */
function getReviewColorIdx(seg, opts) {
  if (opts && opts.producerSpeaker && seg.speaker === opts.producerSpeaker) {
    return REVIEW_PRODUCER_COLOR.labelIdx;
  }
  if (seg.speaker && seg.speaker !== '') {
    return REVIEW_EXPERT_COLOR.labelIdx;
  }
  if (seg.block === 99) return REVIEW_COLOR_MAP.cut.labelIdx;
  if (opts && opts.assemblyBlocks && seg.block > 0) {
    for (var i = 0; i < opts.assemblyBlocks.length; i++) {
      var bd = opts.assemblyBlocks[i];
      if (bd.block === seg.block && bd.usedCount > 0 && bd.color) {
        var idx = LABEL_COLOR_INDEX[bd.color];
        if (idx !== undefined) return idx;
      }
    }
  }
  var cat = getReviewCategory(seg);
  return REVIEW_COLOR_MAP[cat].labelIdx;
}

/**
 * Compute complement of assembly ranges within [0, clipDuration].
 * Returns ranges NOT covered by any assembly segment.
 */
function computeComplement(assemblyRanges, clipDuration, minGap) {
  if (typeof minGap !== 'number') minGap = MIN_GAP_DURATION;
  var complement = [];
  var pos = 0;

  for (var i = 0; i < assemblyRanges.length; i++) {
    var range = assemblyRanges[i];
    if (range.in > pos) {
      if (range.in - pos >= minGap) {
        complement.push({ in: pos, out: range.in });
      }
    }
    if (range.out > pos) pos = range.out;
  }

  if (clipDuration > pos && clipDuration - pos >= minGap) {
    complement.push({ in: pos, out: clipDuration });
  }
  return complement;
}

/**
 * Format seconds to timecode string (MM:SS.s).
 */
function secToTc(seconds) {
  var mm = Math.floor(seconds / 60);
  var ss = Math.round((seconds - mm * 60) * 10) / 10;
  var ssWhole = Math.floor(ss);
  var ssFrac = Math.round((ss - ssWhole) * 10);
  return String(mm).padStart(2, '0') + ':' + String(ssWhole).padStart(2, '0') + '.' + ssFrac;
}

/**
 * Create a synthetic "gap" segment for uncategorized footage.
 */
function createGapSegment(sourceFile, inSec, outSec) {
  return {
    id: 'gap_' + sourceFile.replace(/\.[^.]+$/, '') + '_' + inSec.toFixed(1),
    sourceFile: sourceFile,
    inSec: inSec,
    outSec: outSec,
    duration: Math.round((outSec - inSec) * 10) / 10,
    tcIn: secToTc(inSec),
    tcOut: secToTc(outSec),
    use: false,
    block: 0,
    blockName: '',
    segmentName: '',
    speaker: '',
    transcript: '',
    track: 'V1',
    color: 'Purple',
    priority: 1,
    isChapter: false,
    brollNote: '',
    notes: '',
    _isGap: true
  };
}

/**
 * Build review segments for a single scene (complement approach).
 *
 * @param {Array} allSegments - All brief segments
 * @param {Array<string>} sceneClipNames - Clip filenames in this scene (e.g. ['C5402.MP4', 'C5403.MP4'])
 * @param {Object} clipDurations - { 'C5402.MP4': 156.0, ... }
 * @returns {Array} Review segments sorted by sourceFile + inSec
 */
function buildSceneReviewSegments(allSegments, sceneClipNames, clipDurations) {
  // 1. Group Assembly segments by clip (use=TRUE, block!=99)
  var assemblyByClip = {};
  for (var i = 0; i < allSegments.length; i++) {
    var seg = allSegments[i];
    if (seg.use && seg.block !== 99 && sceneClipNames.indexOf(seg.sourceFile) >= 0) {
      if (!assemblyByClip[seg.sourceFile]) assemblyByClip[seg.sourceFile] = [];
      assemblyByClip[seg.sourceFile].push({ in: seg.inSec, out: seg.outSec, block: seg.block, blockName: seg.blockName, color: seg.color, id: seg.id });
    }
  }
  for (var f in assemblyByClip) {
    assemblyByClip[f].sort(function (a, b) { return a.in - b.in; });
  }

  // 2. Group brief review segments (use=FALSE or block=99) by clip
  var briefByClip = {};
  for (var j = 0; j < allSegments.length; j++) {
    var s = allSegments[j];
    if ((!s.use || s.block === 99) && sceneClipNames.indexOf(s.sourceFile) >= 0) {
      if (!briefByClip[s.sourceFile]) briefByClip[s.sourceFile] = [];
      briefByClip[s.sourceFile].push(s);
    }
  }
  for (var bf in briefByClip) {
    briefByClip[bf].sort(function (a, b) { return a.inSec - b.inSec; });
  }

  // 3. For each clip, compute complement and build review segments
  var allReviewSegs = [];
  var assemblyGapMarkers = []; // markers for assembly gaps

  for (var ci = 0; ci < sceneClipNames.length; ci++) {
    var clipName = sceneClipNames[ci];
    var clipDur = clipDurations[clipName] || 0;
    if (clipDur <= 0) continue;

    var assemblyRanges = assemblyByClip[clipName] || [];
    var briefSegs = briefByClip[clipName] || [];

    // Complement = parts NOT in Assembly
    var complementRanges = computeComplement(
      assemblyRanges.map(function(r) { return { in: r.in, out: r.out }; }),
      clipDur, MIN_GAP_DURATION
    );

    // For each complement range, collect brief segments + fill gaps
    for (var ri = 0; ri < complementRanges.length; ri++) {
      var range = complementRanges[ri];

      // Brief segments overlapping this range
      var briefInRange = briefSegs.filter(function(bs) {
        return bs.inSec < range.out && bs.outSec > range.in;
      });

      // Add brief segments (clamped to range)
      for (var bri = 0; bri < briefInRange.length; bri++) {
        var bs = Object.assign({}, briefInRange[bri]);
        if (bs.inSec < range.in) { bs.inSec = range.in; bs.tcIn = secToTc(range.in); }
        if (bs.outSec > range.out) { bs.outSec = range.out; bs.tcOut = secToTc(range.out); }
        bs.duration = Math.round((bs.outSec - bs.inSec) * 10) / 10;
        if (bs.duration >= MIN_GAP_DURATION) allReviewSegs.push(bs);
      }

      // Fill uncovered gaps with synthetic segments
      var pos = range.in;
      var sortedBrief = briefInRange.slice().sort(function(a, b) { return a.inSec - b.inSec; });
      for (var gi = 0; gi < sortedBrief.length; gi++) {
        var bSeg = sortedBrief[gi];
        var bIn = Math.max(bSeg.inSec, range.in);
        if (bIn > pos && bIn - pos >= MIN_GAP_DURATION) {
          allReviewSegs.push(createGapSegment(clipName, pos, bIn));
        }
        pos = Math.max(pos, Math.min(bSeg.outSec, range.out));
      }
      if (range.out > pos && range.out - pos >= MIN_GAP_DURATION) {
        allReviewSegs.push(createGapSegment(clipName, pos, range.out));
      }
    }

    // Record assembly gap markers (where Assembly took content)
    for (var ai = 0; ai < assemblyRanges.length; ai++) {
      var ar = assemblyRanges[ai];
      assemblyGapMarkers.push({
        sourceFile: clipName,
        inSec: ar.in,
        outSec: ar.out,
        block: ar.block,
        blockName: ar.blockName || 'Block ' + ar.block,
        color: ar.color || 'Green',
        segId: ar.id
      });
    }
  }

  // Sort by sourceFile + inSec
  allReviewSegs.sort(function (a, b) {
    if (a.sourceFile !== b.sourceFile) return a.sourceFile < b.sourceFile ? -1 : 1;
    return a.inSec - b.inSec;
  });

  return { segments: allReviewSegs, assemblyGapMarkers: assemblyGapMarkers };
}

/**
 * Compute clip offsets within a scene (for absolute timeline positioning).
 */
function computeSceneClipOffsets(sceneClipNames, clipDurations) {
  var offsets = {};
  var pos = 0;
  for (var i = 0; i < sceneClipNames.length; i++) {
    var name = sceneClipNames[i];
    offsets[name] = pos;
    pos += (clipDurations[name] || 0);
  }
  return { offsets: offsets, totalDuration: pos };
}

/**
 * Build a single Review sequence for one scene.
 *
 * @param {Object} project - Premiere project
 * @param {Object} clipMap - { filename: projectItem }
 * @param {Array} reviewSegs - Review segments for this scene
 * @param {Object} clipOffsets - { filename: offsetSec }
 * @param {string} seqName - Sequence name
 * @param {Object} logger
 * @param {Object} opts - { producerSpeaker, assemblyBlocks }
 * @returns {{ sequence, clipCount, totalDuration }}
 */
async function buildSingleReviewSequence(project, clipMap, reviewSegs, clipOffsets, seqName, logger, opts) {
  if (reviewSegs.length === 0) {
    if (logger) logger.info('No review segments for ' + seqName + ' — skipping');
    return { sequence: null, clipCount: 0, totalDuration: 0 };
  }

  // Calculate absolute timeline positions
  for (var pi = 0; pi < reviewSegs.length; pi++) {
    var s = reviewSegs[pi];
    s._timelinePosition = (clipOffsets[s.sourceFile] || 0) + s.inSec;
  }
  reviewSegs.sort(function (a, b) { return a._timelinePosition - b._timelinePosition; });

  // Clean existing
  await cleanExistingSequence(project, seqName, logger);

  // Create sequence from first clip
  var firstSeg = reviewSegs[0];
  var firstRawItem = clipMap[firstSeg.sourceFile] || clipMap[firstSeg.sourceFile.replace(/\.[^.]+$/, '')];
  if (!firstRawItem) throw new Error('First clip not found: ' + firstSeg.sourceFile);

  var firstCast = ppro.ClipProjectItem.cast(firstRawItem);
  var firstClip = firstCast || firstRawItem;

  var firstColorIdx = getReviewColorIdx(firstSeg, opts);
  applyColorByIndex(project, firstRawItem, firstColorIdx, firstSeg.id, logger);

  // Source in/out: EXACT (no frame-snap). Frame-snap only for timeline positions.
  var fps = (opts && opts.fps) ? opts.fps : 25;
  var firstInTime = ppro.TickTime.createWithSeconds(firstSeg.inSec);
  var firstOutTime = ppro.TickTime.createWithSeconds(firstSeg.outSec);
  setSourceInOut(project, firstClip, firstInTime, firstOutTime, firstSeg.id, logger);

  var seq = null;
  try {
    seq = await project.createSequenceFromMedia(seqName, [firstClip]);
  } catch (ex) {
    if (logger) logger.warn('createSequenceFromMedia failed: ' + ex.message);
    seq = await project.createSequence(seqName);
  }
  if (!seq) throw new Error('Failed to create Review sequence: ' + seqName);

  clearSourceInOut(project, firstClip, firstSeg.id, logger);

  var seqEditor = ppro.SequenceEditor.getEditor(seq);

  // DJI audio for first clip
  var totalDjiCount = insertDjiAudio(project, seqEditor, clipMap, firstSeg.sourceFile,
    firstSeg._timelinePosition || 0, firstSeg.inSec, firstSeg.outSec, firstSeg.id, logger,
    { colorIdx: firstColorIdx });

  if (logger) {
    var cat = getReviewCategory(firstSeg);
    logger.info('[1/' + reviewSegs.length + '] ' + firstSeg.id + ': ' + firstSeg.sourceFile +
      ' [' + cat.toUpperCase() + '] ' + firstSeg.tcIn + '-' + firstSeg.tcOut +
      ' @' + (firstSeg._timelinePosition || 0).toFixed(1) + 's');
  }

  var clipCount = 1;

  // Remaining clips — overwrite at absolute positions
  for (var i = 1; i < reviewSegs.length; i++) {
    var seg = reviewSegs[i];
    var rawItem = clipMap[seg.sourceFile] || clipMap[seg.sourceFile.replace(/\.[^.]+$/, '')];
    if (!rawItem) {
      if (logger) logger.warn('Skip ' + seg.id + ': no clip for ' + seg.sourceFile);
      continue;
    }

    var castClip = ppro.ClipProjectItem.cast(rawItem);
    var clipForTrim = castClip || rawItem;

    var colorIdx = getReviewColorIdx(seg, opts);
    applyColorByIndex(project, rawItem, colorIdx, seg.id, logger);

    var inTime = ppro.TickTime.createWithSeconds(seg.inSec);
    var outTime = ppro.TickTime.createWithSeconds(seg.outSec);
    setSourceInOut(project, clipForTrim, inTime, outTime, seg.id, logger);

    var overwriteTime = ppro.TickTime.createWithSeconds(snapToFrame(seg._timelinePosition, fps, 'round'));
    var insertOk = false;
    try {
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(seqEditor.createOverwriteItemAction(rawItem, overwriteTime, 0, 0));
        }, 'Overwrite: ' + seg.id);
      });
      insertOk = true;
      clipCount++;
    } catch (ex) {
      if (logger) logger.error('Overwrite failed ' + seg.id + ': ' + ex.message);
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(seqEditor.createInsertProjectItemAction(rawItem, overwriteTime, 0, 0, true));
          }, 'Insert fallback: ' + seg.id);
        });
        insertOk = true;
        clipCount++;
      } catch (ex2) {
        if (logger) logger.error('Insert also failed ' + seg.id + ': ' + ex2.message);
      }
    }

    clearSourceInOut(project, clipForTrim, seg.id, logger);

    if (insertOk) {
      var djiCount = insertDjiAudio(project, seqEditor, clipMap, seg.sourceFile,
        seg._timelinePosition, seg.inSec, seg.outSec, seg.id, logger,
        { colorIdx: colorIdx });
      totalDjiCount += djiCount;
    }

    if (logger) {
      var segCat = getReviewCategory(seg);
      logger.info('[' + (i + 1) + '/' + reviewSegs.length + '] ' + seg.id + ': ' + seg.sourceFile +
        ' [' + segCat.toUpperCase() + '] ' + seg.tcIn + '-' + seg.tcOut +
        ' @' + seg._timelinePosition.toFixed(1) + 's' +
        (insertOk ? '' : ' FAILED'));
    }
  }

  if (logger) {
    logger.info(seqName + ': ' + clipCount + ' clips placed' +
      (totalDjiCount > 0 ? ', ' + totalDjiCount + ' DJI on A2' : ''));
  }

  return { sequence: seq, clipCount: clipCount, totalDuration: 0 };
}

/**
 * Build per-scene Review sequences.
 *
 * Creates one Review sequence per scene:
 *   {CODE}_3_Review_{scene}  (e.g. YTXX01_3_Review_01_apartment)
 *
 * Each sequence = full scene footage minus Assembly-used segments (gaps).
 *
 * @param {Object} project - Premiere project
 * @param {Object} clipMap - { filename: projectItem }
 * @param {Array} segments - All brief segments
 * @param {string} projectCode - Project code (e.g. 'YTXX01')
 * @param {Object} logger
 * @param {Object} clipDurations - { filename: durationSec }
 * @param {Object} opts - { producerSpeaker, assemblyBlocks }
 * @param {string} briefVersion - e.g. '1'
 * @param {Object} sceneMap - { sceneName: [clipFilename, ...] } — if null, builds single Review
 * @returns {{ sequences: Array, totalClipCount, assemblyGapMarkers }}
 */
async function buildReviewSequence(project, clipMap, segments, projectCode, logger, clipDurations, opts, briefVersion, sceneMap) {
  // If no scene map, try to derive from segments or build single Review (backward compat)
  if (!sceneMap || Object.keys(sceneMap).length === 0) {
    // Derive scenes from brief segments' source files
    var clipNames = Object.keys(clipDurations || {}).sort();
    sceneMap = { 'all': clipNames };
  }

  var results = [];
  var totalClipCount = 0;
  var allGapMarkers = [];
  var sceneNames = Object.keys(sceneMap).sort();

  for (var si = 0; si < sceneNames.length; si++) {
    var sceneName = sceneNames[si];
    var sceneClips = sceneMap[sceneName].sort();
    var vSuffix = briefVersion ? '_v' + briefVersion : '';

    // Sequence name: YTXX01_3_Review_01_apartment_v1
    var seqName = sceneName === 'all'
      ? projectCode + '_3_Review' + vSuffix
      : projectCode + '_3_Review_' + sceneName + vSuffix;

    if (logger) logger.info('=== Scene: ' + sceneName + ' (' + sceneClips.length + ' clips) → ' + seqName + ' ===');

    // Build review segments for this scene
    var sceneResult = buildSceneReviewSegments(segments, sceneClips, clipDurations);
    var reviewSegs = sceneResult.segments;
    allGapMarkers = allGapMarkers.concat(sceneResult.assemblyGapMarkers);

    if (logger) {
      var gapCount = reviewSegs.filter(function(s) { return s._isGap; }).length;
      var briefCount = reviewSegs.length - gapCount;
      logger.info('Review segments: ' + briefCount + ' from brief + ' + gapCount + ' gaps = ' + reviewSegs.length + ' total');
    }

    // Compute clip offsets within this scene
    var offsetInfo = computeSceneClipOffsets(sceneClips, clipDurations);

    // Build the sequence
    var buildResult = await buildSingleReviewSequence(
      project, clipMap, reviewSegs, offsetInfo.offsets, seqName, logger, opts
    );

    buildResult.sceneName = sceneName;
    buildResult.totalDuration = offsetInfo.totalDuration;
    buildResult.segments = reviewSegs;
    buildResult.clipOffsets = offsetInfo.offsets;
    results.push(buildResult);
    totalClipCount += buildResult.clipCount;
  }

  // Return in format compatible with index.js
  // For backward compat, also expose first sequence as .sequence
  return {
    sequence: results.length > 0 ? results[0].sequence : null,
    sequences: results,
    segments: results.reduce(function(all, r) { return all.concat(r.segments || []); }, []),
    clipCount: totalClipCount,
    totalDuration: results.reduce(function(sum, r) { return sum + (r.totalDuration || 0); }, 0),
    clipOffsets: results.length > 0 ? results[0].clipOffsets : {},
    ingestDuration: results.reduce(function(sum, r) { return sum + (r.totalDuration || 0); }, 0),
    assemblyGapMarkers: allGapMarkers
  };
}

module.exports = {
  buildReviewSequence,
  buildSceneReviewSegments,
  buildSingleReviewSequence,
  getReviewCategory,
  getReviewColorIdx,
  computeComplement,
  computeSceneClipOffsets,
  createGapSegment
};
