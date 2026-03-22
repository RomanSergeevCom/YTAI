/**
 * reviewBuilder.js — Build {project}_3_Review sequence.
 *
 * Creates a sequence with ALL footage NOT used in Assembly (complement approach):
 * 1. For each clip, compute complement of Assembly segments within [0, clipDuration]
 * 2. Within complement, keep existing brief use=FALSE segments (retain metadata)
 * 3. Fill gaps (complement portions not covered by brief) with synthetic segments
 * 4. Sort by sourceFile + inSec for natural Ingest-like viewing order
 *
 * Result: "Ingest minus Assembly" — Review timeline = Ingest length,
 * Assembly segments are empty gaps. Editor sees WHERE content was removed.
 *
 * Color scheme by exclusion category:
 *   Teal     — expert/talent speaking (non-producer speaker with name)
 *   Lavender — producer/interviewer speaking
 *   Red      — block=99 (explicitly cut: noise, errors, repeats)
 *   Yellow   — priority=2 (alternative take, might be useful)
 *   Purple   — use=FALSE, no specific reason / synthetic gap (review candidate)
 *
 * Pattern mirrors assemblyBuilder.js — same pre-trim + insert flow,
 * reuses shared clipActions for trim/color operations.
 *
 * Depends on: projectScanner (clipMap), briefParser (segments), clipActions
 * Does NOT import any ingest or assembly modules.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

const { REVIEW_COLOR_MAP, REVIEW_PRODUCER_COLOR, REVIEW_EXPERT_COLOR, LABEL_COLOR_INDEX } = require('../shared/constants');
const { applyColorByIndex, setSourceInOut, clearSourceInOut, cleanExistingSequence, insertDjiAudio } = require('../shared/clipActions');

// Minimum gap duration (seconds) — gaps shorter than this are skipped
var MIN_GAP_DURATION = 0.3;

/**
 * Determine review category for a segment.
 *
 * @param {Object} seg - Normalized segment from briefParser
 * @returns {'cut'|'alt'|'skip'}
 */
function getReviewCategory(seg) {
  if (seg.block === 99) return 'cut';
  if (seg.priority === 2 || seg.priority === '2') return 'alt';
  return 'skip';
}

/**
 * Determine label color index for a review segment.
 * Priority: producer speaker → block=99 cut → block-based color → category fallback.
 *
 * @param {Object} seg - Normalized segment
 * @param {Object} [opts] - { producerSpeaker: string, assemblyBlocks: Array }
 * @returns {number} Premiere label color index
 */
function getReviewColorIdx(seg, opts) {
  // 1. Producer speaker → Lavender (context only, not for final edit)
  if (opts && opts.producerSpeaker && seg.speaker === opts.producerSpeaker) {
    return REVIEW_PRODUCER_COLOR.labelIdx;
  }
  // 1.5. Expert/talent on camera — any non-empty, non-producer speaker → Teal
  if (seg.speaker && seg.speaker !== '') {
    return REVIEW_EXPERT_COLOR.labelIdx;
  }
  // 2. block=99 → Red (always — explicitly cut content)
  if (seg.block === 99) return REVIEW_COLOR_MAP.cut.labelIdx;
  // 3. Segment from a block that has Assembly content → use block's own color
  if (opts && opts.assemblyBlocks && seg.block > 0) {
    for (var i = 0; i < opts.assemblyBlocks.length; i++) {
      var bd = opts.assemblyBlocks[i];
      if (bd.block === seg.block && bd.usedCount > 0 && bd.color) {
        var idx = LABEL_COLOR_INDEX[bd.color];
        if (idx !== undefined) return idx;
      }
    }
  }
  // 4. Fallback → category-based (Yellow for alt, Purple for skip)
  var cat = getReviewCategory(seg);
  return REVIEW_COLOR_MAP[cat].labelIdx;
}

/**
 * Compute the complement of assembly ranges within [0, clipDuration].
 * Returns ranges NOT covered by any assembly segment.
 *
 * @param {Array<{in: number, out: number}>} assemblyRanges - Sorted by .in ascending
 * @param {number} clipDuration - Total clip duration in seconds
 * @param {number} minGap - Minimum gap duration to include (default: MIN_GAP_DURATION)
 * @returns {Array<{in: number, out: number}>} Complement ranges
 */
function computeComplement(assemblyRanges, clipDuration, minGap) {
  if (typeof minGap !== 'number') minGap = MIN_GAP_DURATION;
  var complement = [];
  var pos = 0;

  for (var i = 0; i < assemblyRanges.length; i++) {
    var range = assemblyRanges[i];
    if (range.in > pos) {
      var gapDur = range.in - pos;
      if (gapDur >= minGap) {
        complement.push({ in: pos, out: range.in });
      }
    }
    if (range.out > pos) {
      pos = range.out;
    }
  }

  // Tail: from last assembly end to clip end
  if (clipDuration > pos) {
    var tailDur = clipDuration - pos;
    if (tailDur >= minGap) {
      complement.push({ in: pos, out: clipDuration });
    }
  }

  return complement;
}

/**
 * Subtract brief segments from a range, returning uncovered gaps.
 * Both the range and briefSegs should be for the same sourceFile.
 *
 * @param {{in: number, out: number}} range - A complement range
 * @param {Array} briefSegs - Brief use=FALSE segments for this clip, sorted by inSec
 * @returns {Array<{in: number, out: number}>} Uncovered gap ranges within the complement range
 */
function subtractBriefFromRange(range, briefSegs) {
  var gaps = [];
  var pos = range.in;

  for (var i = 0; i < briefSegs.length; i++) {
    var seg = briefSegs[i];
    // Skip segments entirely outside this range
    if (seg.outSec <= range.in || seg.inSec >= range.out) continue;

    // Clamp segment to range boundaries
    var segIn = Math.max(seg.inSec, range.in);
    var segOut = Math.min(seg.outSec, range.out);

    if (segIn > pos) {
      var gapDur = segIn - pos;
      if (gapDur >= MIN_GAP_DURATION) {
        gaps.push({ in: pos, out: segIn });
      }
    }
    if (segOut > pos) {
      pos = segOut;
    }
  }

  // Tail gap
  if (range.out > pos) {
    var tailDur = range.out - pos;
    if (tailDur >= MIN_GAP_DURATION) {
      gaps.push({ in: pos, out: range.out });
    }
  }

  return gaps;
}

/**
 * Format seconds to timecode string (MM:SS.s).
 * Local copy to avoid circular dependency on utils.js.
 */
function secToTc(seconds) {
  var mm = Math.floor(seconds / 60);
  var ss = Math.round((seconds - mm * 60) * 10) / 10;
  var mmStr = String(mm).padStart(2, '0');
  var ssWhole = Math.floor(ss);
  var ssFrac = Math.round((ss - ssWhole) * 10);
  var ssStr = String(ssWhole).padStart(2, '0') + '.' + ssFrac;
  return mmStr + ':' + ssStr;
}

/**
 * Create a synthetic "gap" segment for uncategorized footage.
 *
 * @param {string} sourceFile - Clip filename
 * @param {number} inSec - Gap start (seconds)
 * @param {number} outSec - Gap end (seconds)
 * @returns {Object} Segment with same structure as briefParser output
 */
function createGapSegment(sourceFile, inSec, outSec) {
  var duration = Math.round((outSec - inSec) * 10) / 10;
  return {
    id: 'gap_' + sourceFile.replace(/\.[^.]+$/, '') + '_' + inSec.toFixed(1),
    sourceFile: sourceFile,
    inSec: inSec,
    outSec: outSec,
    duration: duration,
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
 * Filter and sort segments for Review sequence using complement approach.
 *
 * Algorithm: "Ingest minus Assembly"
 * 1. For each clip, compute complement of Assembly segments within [0, clipDuration]
 * 2. Within complement, keep existing brief use=FALSE segments (retain metadata)
 * 3. Fill uncovered gaps with synthetic "gap" segments
 * 4. Sort all by sourceFile (alphabetical) + inSec (chronological)
 *
 * @param {Array} segments - All segments from briefParser
 * @param {Object} clipDurations - { "C5402.MP4": 156.0, ... } clip total durations
 * @returns {Array} Review segments (brief + synthetic gaps), sorted
 */
function sortReviewSegments(segments, clipDurations) {
  // If no clip durations provided, fall back to old filter approach
  if (!clipDurations || Object.keys(clipDurations).length === 0) {
    var fallbackSegs = segments.filter(function (s) {
      return !s.use || s.block === 99;
    });
    fallbackSegs.sort(function (a, b) {
      if (a.sourceFile !== b.sourceFile) return a.sourceFile < b.sourceFile ? -1 : 1;
      return a.inSec - b.inSec;
    });
    return fallbackSegs;
  }

  // 1. Group Assembly segments by sourceFile
  var assemblyByClip = {};
  for (var i = 0; i < segments.length; i++) {
    var seg = segments[i];
    if (seg.use && seg.block !== 99) {
      if (!assemblyByClip[seg.sourceFile]) assemblyByClip[seg.sourceFile] = [];
      assemblyByClip[seg.sourceFile].push({ in: seg.inSec, out: seg.outSec });
    }
  }

  // Sort assembly ranges per clip by in-point
  for (var file in assemblyByClip) {
    assemblyByClip[file].sort(function (a, b) { return a.in - b.in; });
  }

  // 2. Group brief review segments (use=FALSE or block=99) by sourceFile
  var briefReviewByClip = {};
  for (var j = 0; j < segments.length; j++) {
    var s = segments[j];
    if (!s.use || s.block === 99) {
      if (!briefReviewByClip[s.sourceFile]) briefReviewByClip[s.sourceFile] = [];
      briefReviewByClip[s.sourceFile].push(s);
    }
  }

  // Sort brief review segments per clip by inSec
  for (var f in briefReviewByClip) {
    briefReviewByClip[f].sort(function (a, b) { return a.inSec - b.inSec; });
  }

  // 3. For each clip with known duration, compute complement and fill gaps
  var allReviewSegs = [];
  var clipNames = Object.keys(clipDurations).sort();

  for (var ci = 0; ci < clipNames.length; ci++) {
    var clipName = clipNames[ci];
    var clipDur = clipDurations[clipName];
    var assemblyRanges = assemblyByClip[clipName] || [];
    var briefReviewSegs = briefReviewByClip[clipName] || [];

    // Compute complement of Assembly within [0, clipDuration]
    var complementRanges = computeComplement(assemblyRanges, clipDur, MIN_GAP_DURATION);

    // For each complement range, find gaps not covered by brief segments
    for (var ri = 0; ri < complementRanges.length; ri++) {
      var range = complementRanges[ri];

      // Collect brief segments that fall within this complement range
      var briefInRange = [];
      for (var bi = 0; bi < briefReviewSegs.length; bi++) {
        var bs = briefReviewSegs[bi];
        // Segment overlaps with range if its in < range.out AND its out > range.in
        if (bs.inSec < range.out && bs.outSec > range.in) {
          briefInRange.push(bs);
        }
      }

      // Add brief segments that are within complement (they have metadata)
      for (var bri = 0; bri < briefInRange.length; bri++) {
        var briefSeg = briefInRange[bri];
        // Clamp to complement range boundaries
        var clampedSeg = Object.assign({}, briefSeg);
        if (clampedSeg.inSec < range.in) {
          clampedSeg.inSec = range.in;
          clampedSeg.tcIn = secToTc(range.in);
        }
        if (clampedSeg.outSec > range.out) {
          clampedSeg.outSec = range.out;
          clampedSeg.tcOut = secToTc(range.out);
        }
        clampedSeg.duration = Math.round((clampedSeg.outSec - clampedSeg.inSec) * 10) / 10;
        if (clampedSeg.duration >= MIN_GAP_DURATION) {
          allReviewSegs.push(clampedSeg);
        }
      }

      // Find gaps within this complement range not covered by brief segments
      var gapRanges = subtractBriefFromRange(range, briefInRange);
      for (var gi = 0; gi < gapRanges.length; gi++) {
        allReviewSegs.push(createGapSegment(clipName, gapRanges[gi].in, gapRanges[gi].out));
      }
    }
  }

  // 4. Sort by sourceFile + inSec
  allReviewSegs.sort(function (a, b) {
    if (a.sourceFile !== b.sourceFile) {
      return a.sourceFile < b.sourceFile ? -1 : 1;
    }
    return a.inSec - b.inSec;
  });

  return allReviewSegs;
}

/**
 * Compute clip offsets for Ingest-like timeline layout.
 * Clips are ordered alphabetically; each offset = sum of prior durations.
 *
 * @param {Object} clipDurations - { "C5402.MP4": 156.0, ... }
 * @returns {{ offsets: Object, ingestDuration: number }}
 */
function computeClipOffsets(clipDurations) {
  var clipNames = Object.keys(clipDurations).sort();
  var offsets = {};
  var pos = 0;
  for (var i = 0; i < clipNames.length; i++) {
    offsets[clipNames[i]] = pos;
    pos += clipDurations[clipNames[i]];
  }
  return { offsets: offsets, ingestDuration: pos };
}

/**
 * Build the Review sequence (Ingest minus Assembly).
 *
 * Layout mirrors the Ingest sequence: timeline length = total Ingest duration.
 * Clips are placed at absolute positions (clipOffset + inSec) via overwrite.
 * Assembly segments stay as empty gaps — editor sees WHERE content was removed.
 *
 * Assembly pipeline is NOT touched — only Review.
 *
 * @param {Object} project - Active Premiere project
 * @param {Object} clipMap - { filename: projectItem } from projectScanner
 * @param {Array} segments - Parsed segments from briefParser (all segments)
 * @param {string} projectName - Project name for sequence naming
 * @param {Object} logger - Logger instance
 * @param {Object} clipDurations - { filename: durationSec } for complement calculation
 * @param {Object} [opts] - { producerSpeaker: string, assemblyBlocks: Array } for color logic
 * @returns {{ sequence, segments, clipCount, totalDuration, clipOffsets, ingestDuration }}
 */
async function buildReviewSequence(project, clipMap, segments, projectName, logger, clipDurations, opts, briefVersion) {
  const seqName = projectName + '_3_Review' + (briefVersion ? '_v' + briefVersion : '');

  // Compute review segments using complement approach
  const reviewSegs = sortReviewSegments(segments, clipDurations);

  if (logger) logger.info('Building Review sequence: ' + reviewSegs.length + ' segments');

  if (reviewSegs.length === 0) {
    if (logger) logger.info('No unused segments — all footage is in Assembly. Review skipped.');
    return { sequence: null, segments: [], clipCount: 0, totalDuration: 0, clipOffsets: {}, ingestDuration: 0 };
  }

  // Compute clip offsets for absolute positioning (Ingest layout)
  var offsetInfo = clipDurations ? computeClipOffsets(clipDurations) : null;
  var clipOffsets = offsetInfo ? offsetInfo.offsets : {};
  var ingestDuration = offsetInfo ? offsetInfo.ingestDuration : 0;

  // Calculate absolute timeline position for each segment
  for (var pi = 0; pi < reviewSegs.length; pi++) {
    var s = reviewSegs[pi];
    s._timelinePosition = (clipOffsets[s.sourceFile] || 0) + s.inSec;
  }

  // Sort by absolute position
  reviewSegs.sort(function (a, b) { return a._timelinePosition - b._timelinePosition; });

  // Log segment order for debugging
  if (logger) {
    var gapCount = 0;
    var briefCount = 0;
    for (var si = 0; si < reviewSegs.length; si++) {
      var seg = reviewSegs[si];
      var cat = getReviewCategory(seg);
      var label = seg._isGap ? 'GAP' : cat.toUpperCase();
      logger.debug('  [' + (si + 1) + '] ' + seg.id + ' [' + label + '] ' +
        seg.sourceFile + ' ' + seg.tcIn + '-' + seg.tcOut +
        ' (' + seg.duration.toFixed(1) + 's) @' + seg._timelinePosition.toFixed(1) + 's');
      if (seg._isGap) gapCount++;
      else briefCount++;
    }
    logger.info('Review segments: ' + briefCount + ' from brief + ' + gapCount + ' gaps = ' + reviewSegs.length + ' total');
    if (ingestDuration > 0) {
      logger.info('Ingest duration: ' + ingestDuration.toFixed(1) + 's (timeline mirrors Ingest)');
    }
  }

  // Clean old Review sequence if exists
  await cleanExistingSequence(project, seqName, logger);

  // === First clip: createSequenceFromMedia (inherits resolution/fps) ===
  var firstSeg = reviewSegs[0];
  var firstRawItem = clipMap[firstSeg.sourceFile] || clipMap[firstSeg.sourceFile.replace(/\.[^.]+$/, '')];
  if (!firstRawItem) {
    throw new Error('First clip not found in project: ' + firstSeg.sourceFile);
  }

  // Cast to ClipProjectItem (required for createSetInOutPointsAction)
  var firstCast = ppro.ClipProjectItem.cast(firstRawItem);
  var firstClipForTrim = firstCast || firstRawItem;
  var castOk = !!firstCast;

  if (logger) logger.info('First clip: "' + firstRawItem.name + '" cast=' + (castOk ? 'OK' : 'FAILED (using raw)'));

  // Set color by review logic (speaker → block → category) BEFORE creating sequence
  var firstCat = getReviewCategory(firstSeg);
  var firstColorIdx = getReviewColorIdx(firstSeg, opts);
  applyColorByIndex(project, firstRawItem, firstColorIdx, firstSeg.id, logger);

  // Set source in/out BEFORE creating sequence
  var firstInTime = ppro.TickTime.createWithSeconds(firstSeg.inSec);
  var firstOutTime = ppro.TickTime.createWithSeconds(firstSeg.outSec);
  setSourceInOut(project, firstClipForTrim, firstInTime, firstOutTime, firstSeg.id, logger);

  // Create sequence from first clip (inherits media settings)
  // Note: createSequenceFromMedia places the clip at position 0.
  // This is correct when the first complement segment starts at 0
  // (typical case: beginning of first alphabetical clip is not in Assembly).
  var seq = null;
  try {
    seq = await project.createSequenceFromMedia(seqName, [firstClipForTrim]);
  } catch (ex) {
    if (logger) logger.warn('createSequenceFromMedia failed, using createSequence: ' + ex.message);
    seq = await project.createSequence(seqName);
  }

  if (!seq) throw new Error('Failed to create Review sequence');

  // Clear source in/out on first clip (so it can be reused)
  clearSourceInOut(project, firstClipForTrim, firstSeg.id, logger);

  // Get SequenceEditor early — needed for DJI audio insert on first clip too
  var seqEditor = ppro.SequenceEditor.getEditor(seq);

  // Insert DJI audio for first clip on A2 (same source in/out as video, same color)
  var firstDjiCount = insertDjiAudio(project, seqEditor, clipMap, firstSeg.sourceFile,
    firstSeg._timelinePosition || 0, firstSeg.inSec, firstSeg.outSec, firstSeg.id, logger,
    { colorIdx: firstColorIdx });

  if (logger) {
    logger.info('Review sequence created: ' + seqName);
    logger.info('[1/' + reviewSegs.length + '] ' + firstSeg.id + ': ' + firstSeg.sourceFile +
      ' [' + firstCat.toUpperCase() + ']' +
      ' → in/out=' + firstSeg.inSec.toFixed(1) + '-' + firstSeg.outSec.toFixed(1) + 's' +
      ' → createSequenceFromMedia' +
      (firstDjiCount > 0 ? ' +A2' : '') +
      ' → dur=' + firstSeg.duration.toFixed(1) + 's @' + (firstSeg._timelinePosition || 0).toFixed(1) + 's');
  }

  // === Remaining clips: overwrite at absolute positions (Ingest layout) ===
  var totalDjiCount = firstDjiCount;
  var clipCount = 1;

  for (var i = 1; i < reviewSegs.length; i++) {
    var seg = reviewSegs[i];
    var rawItem = clipMap[seg.sourceFile] || clipMap[seg.sourceFile.replace(/\.[^.]+$/, '')];
    if (!rawItem) {
      if (logger) logger.warn('  Skip ' + seg.id + ': no clip for ' + seg.sourceFile);
      continue;
    }

    // Cast to ClipProjectItem for trim operations
    var castClip = ppro.ClipProjectItem.cast(rawItem);
    var clipForTrim = castClip || rawItem;

    // Set color by review logic (speaker → block → category) BEFORE insert
    var cat = getReviewCategory(seg);
    var colorIdx = getReviewColorIdx(seg, opts);
    applyColorByIndex(project, rawItem, colorIdx, seg.id, logger);

    // Set source in/out points BEFORE insert (using CAST item)
    var inTime = ppro.TickTime.createWithSeconds(seg.inSec);
    var outTime = ppro.TickTime.createWithSeconds(seg.outSec);
    setSourceInOut(project, clipForTrim, inTime, outTime, seg.id, logger);

    // Overwrite at absolute timeline position (gaps stay empty)
    var overwriteTime = ppro.TickTime.createWithSeconds(seg._timelinePosition);
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
      if (logger) logger.error('  Overwrite failed ' + seg.id + ': ' + ex.message);

      // Fallback: try insert
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(seqEditor.createInsertProjectItemAction(
              rawItem, overwriteTime, 0, 0, true
            ));
          }, 'Insert fallback: ' + seg.id);
        });
        insertOk = true;
        clipCount++;
        if (logger) logger.info('  Insert fallback succeeded for ' + seg.id);
      } catch (ex2) {
        if (logger) logger.error('  Insert also failed ' + seg.id + ': ' + ex2.message);
      }
    }

    // Clear source in/out (using CAST item, so clip can be reused)
    clearSourceInOut(project, clipForTrim, seg.id, logger);

    // Insert DJI audio for this segment on A2 (same source in/out as video, same color)
    var segDjiCount = 0;
    if (insertOk) {
      segDjiCount = insertDjiAudio(project, seqEditor, clipMap, seg.sourceFile,
        seg._timelinePosition, seg.inSec, seg.outSec, seg.id, logger,
        { colorIdx: colorIdx });
      totalDjiCount += segDjiCount;
    }

    if (logger) {
      logger.info('[' + (i + 1) + '/' + reviewSegs.length + '] ' + seg.id + ': ' + seg.sourceFile +
        ' [' + cat.toUpperCase() + ']' +
        ' → in/out=' + seg.inSec.toFixed(1) + '-' + seg.outSec.toFixed(1) + 's' +
        ' → ' + (insertOk ? 'overwrite@' + seg._timelinePosition.toFixed(1) + 's' : 'FAILED') +
        (segDjiCount > 0 ? ' +A2' : '') +
        ' → dur=' + seg.duration.toFixed(1) + 's');
    }
  }

  // Total duration = Ingest timeline length (includes empty gaps for Assembly)
  var totalDuration = ingestDuration > 0 ? ingestDuration : reviewSegs.reduce(function (sum, s) { return sum + s.duration; }, 0);

  if (logger) {
    logger.info('Review: ' + clipCount + '/' + reviewSegs.length + ' clips placed, timeline=' + totalDuration.toFixed(1) + 's (Ingest layout)');
    if (totalDjiCount > 0) {
      logger.info('DJI audio: ' + totalDjiCount + ' segment(s) placed on A2');
    }
  }

  // === Post-build verification: read back V1 track items ===
  try {
    var v0 = await seq.getVideoTrack(0);
    var finalItems = null;
    try { finalItems = v0.getTrackItems(1, false); } catch (ex) { }
    if (!finalItems) try { finalItems = v0.getTrackItems(); } catch (ex) { }

    if (finalItems && logger) {
      logger.info('V1 verification: ' + finalItems.length + ' items (expected ' + reviewSegs.length + ')');
    }
  } catch (verifyErr) {
    if (logger) logger.debug('V1 verification failed: ' + verifyErr.message);
  }

  return {
    sequence: seq,
    segments: reviewSegs,
    clipCount: clipCount,
    totalDuration: totalDuration,
    clipOffsets: clipOffsets,
    ingestDuration: ingestDuration
  };
}

module.exports = {
  buildReviewSequence,
  sortReviewSegments,
  getReviewCategory,
  getReviewColorIdx,
  computeComplement,
  computeClipOffsets,
  subtractBriefFromRange,
  createGapSegment
};
