/**
 * reviewAssembler.js — Build _5_Review sequence from review_brief.json.
 *
 * Creates a Premiere sequence that combines:
 *   V1: Edited video segments (trimmed to keep regions) + source clip insertions
 *
 * All clips placed sequentially on V1 via insert (not overwrite).
 * Markers at insertion points (Green) and user comments (Yellow).
 *
 * Depends on: clipActions (shared trim/color/insert operations)
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

const { LABEL_COLOR_INDEX, MARKER_TYPE_COMMENT, MARKER_COLOR_INDEX } = require('../shared/constants');
const { applyColorByIndex, setSourceInOut, clearSourceInOut, cleanExistingSequence, insertDjiAudio } = require('../shared/clipActions');
const { snapToFrame } = require('../shared/frameSnap');

// Color constants for Review pipeline
var REVIEW_EDITED_COLOR_IDX = LABEL_COLOR_INDEX.Cyan;     // 10 — edited video segments
var REVIEW_INSERT_COLOR_IDX = LABEL_COLOR_INDEX.Green;     // 13 — insertion segments from source
var REVIEW_MARKER_INSERT_IDX = MARKER_COLOR_INDEX.Green;   // 0 — insertion point markers
var REVIEW_MARKER_COMMENT_IDX = MARKER_COLOR_INDEX.Yellow; // 4 — comment markers

/**
 * Parse timecode string (MM:SS.sss) to seconds.
 */
function parseTc(tc) {
  if (!tc) return 0;
  var parts = tc.replace(',', '.').split(':');
  if (parts.length === 2) return parseInt(parts[0]) * 60 + parseFloat(parts[1]);
  if (parts.length === 3) return parseInt(parts[0]) * 3600 + parseInt(parts[1]) * 60 + parseFloat(parts[2]);
  return parseFloat(tc) || 0;
}

/**
 * Import the edited video file into the Premiere project.
 *
 * @param {Object} project - Premiere project
 * @param {string} videoPath - Full path to the edited video file
 * @param {Object} logger
 * @returns {Object} Project item for the imported video
 */
async function importEditedVideo(project, videoPath, logger) {
  if (logger) logger.info('Importing edited video: ' + videoPath);

  // Check if already imported
  var rootItem = await project.getRootItem();
  var children = await rootItem.getItems();

  for (var i = 0; i < children.length; i++) {
    var item = children[i];
    if (item.name && item.name === videoPath.split('/').pop()) {
      if (logger) logger.info('Edited video already in project: ' + item.name);
      return item;
    }
  }

  // Import
  var imported = await project.importFiles([videoPath]);
  if (!imported || imported.length === 0) {
    throw new Error('Failed to import edited video: ' + videoPath);
  }

  if (logger) logger.info('Imported: ' + imported[0].name);
  return imported[0];
}

/**
 * Build the _5_Review sequence.
 *
 * @param {Object} project - Premiere project
 * @param {Object} editedVideoItem - Project item for the edited video
 * @param {Object} clipMap - { filename: projectItem } for source clips
 * @param {Object} parsedBrief - Output from parseReviewBrief()
 * @param {string} projectCode - e.g. 'YTCR01'
 * @param {Object} logger
 * @returns {{ sequence, clipCount, insertionCount }}
 */
async function buildReviewSequence(project, editedVideoItem, clipMap, parsedBrief, projectCode, logger) {
  var fps = parsedBrief.fps || 25;
  var vSuffix = '_v' + (parsedBrief.reviewVersion || 1);
  var seqName = projectCode + '_5_Review' + vSuffix;

  if (logger) logger.info('=== Building Review sequence: ' + seqName + ' ===');

  // Build ordered list of clips to place on V1
  var clipList = [];

  // Merge timeline entries and insertions in order
  // Timeline entries are already in order; insertions go after their target tc
  var timeline = parsedBrief.timeline;
  var insertions = parsedBrief.insertions;

  // Index insertions by their insert_after_tc
  var insertionsByTc = {};
  for (var ii = 0; ii < insertions.length; ii++) {
    var ins = insertions[ii];
    var key = ins.insertAfterTc;
    if (!insertionsByTc[key]) insertionsByTc[key] = [];
    insertionsByTc[key].push(ins);
  }

  // Build clip list
  for (var ti = 0; ti < timeline.length; ti++) {
    var entry = timeline[ti];

    // Edited video segment
    clipList.push({
      type: 'edited',
      projectItem: editedVideoItem,
      inSec: parseTc(entry.tcIn),
      outSec: parseTc(entry.tcOut),
      colorIdx: REVIEW_EDITED_COLOR_IDX,
      label: 'Edit:' + entry.tcIn + '-' + entry.tcOut,
      comment: entry.comment || '',
      matchedSegments: entry.matchedSegments || []
    });

    // Check for insertions after this entry's tc_out
    var afterTc = entry.tcOut;
    if (insertionsByTc[afterTc]) {
      for (var ij = 0; ij < insertionsByTc[afterTc].length; ij++) {
        var insEntry = insertionsByTc[afterTc][ij];
        var sourceItem = clipMap[insEntry.sourceFile] ||
                         clipMap[insEntry.sourceFile.replace(/\.[^.]+$/, '')];

        if (!sourceItem) {
          if (logger) logger.warn('Source clip not found for insertion: ' + insEntry.sourceFile);
          continue;
        }

        clipList.push({
          type: 'insertion',
          projectItem: sourceItem,
          inSec: parseTc(insEntry.sourceTcIn),
          outSec: parseTc(insEntry.sourceTcOut),
          colorIdx: REVIEW_INSERT_COLOR_IDX,
          label: 'Insert:' + insEntry.originalSegmentId + ' ' + insEntry.originalBlockName,
          comment: insEntry.comment || '',
          sourceFile: insEntry.sourceFile,
          originalSegmentId: insEntry.originalSegmentId
        });
      }
    }
  }

  if (clipList.length === 0) {
    if (logger) logger.warn('No clips to place in Review sequence');
    return { sequence: null, clipCount: 0, insertionCount: 0 };
  }

  if (logger) {
    var editCount = clipList.filter(function(c) { return c.type === 'edited'; }).length;
    var insCount = clipList.filter(function(c) { return c.type === 'insertion'; }).length;
    logger.info('Clip list: ' + editCount + ' edited + ' + insCount + ' insertions = ' + clipList.length + ' total');
  }

  // Clean existing sequence
  await cleanExistingSequence(project, seqName, logger);

  // Create sequence from first clip
  var first = clipList[0];
  var firstCast = ppro.ClipProjectItem.cast(first.projectItem);
  var firstClip = firstCast || first.projectItem;

  applyColorByIndex(project, first.projectItem, first.colorIdx, first.label, logger);

  var firstInTime = ppro.TickTime.createWithSeconds(first.inSec);
  var firstOutTime = ppro.TickTime.createWithSeconds(first.outSec);
  setSourceInOut(project, firstClip, firstInTime, firstOutTime, first.label, logger);

  var seq = null;
  try {
    seq = await project.createSequenceFromMedia(seqName, [firstClip]);
  } catch (ex) {
    if (logger) logger.warn('createSequenceFromMedia failed: ' + ex.message);
    seq = await project.createSequence(seqName);
  }
  if (!seq) throw new Error('Failed to create Review sequence: ' + seqName);

  clearSourceInOut(project, firstClip, first.label, logger);

  var seqEditor = ppro.SequenceEditor.getEditor(seq);
  var clipCount = 1;
  var insertionCount = first.type === 'insertion' ? 1 : 0;
  var timelinePos = first.outSec - first.inSec; // Current end position

  if (logger) {
    logger.info('[1/' + clipList.length + '] ' + first.label +
      ' [' + first.type.toUpperCase() + '] ' + first.inSec.toFixed(1) + '-' + first.outSec.toFixed(1) + 's');
  }

  // Insert remaining clips sequentially
  for (var ci = 1; ci < clipList.length; ci++) {
    var clip = clipList[ci];
    var rawItem = clip.projectItem;
    var castClip = ppro.ClipProjectItem.cast(rawItem);
    var clipForTrim = castClip || rawItem;

    applyColorByIndex(project, rawItem, clip.colorIdx, clip.label, logger);

    var inTime = ppro.TickTime.createWithSeconds(clip.inSec);
    var outTime = ppro.TickTime.createWithSeconds(clip.outSec);
    setSourceInOut(project, clipForTrim, inTime, outTime, clip.label, logger);

    var insertTime = ppro.TickTime.createWithSeconds(snapToFrame(timelinePos, fps, 'round'));
    var insertOk = false;

    try {
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(seqEditor.createOverwriteItemAction(rawItem, insertTime, 0, 0));
        }, 'Review: ' + clip.label);
      });
      insertOk = true;
      clipCount++;
      if (clip.type === 'insertion') insertionCount++;
    } catch (ex) {
      if (logger) logger.error('Insert failed ' + clip.label + ': ' + ex.message);
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(seqEditor.createInsertProjectItemAction(rawItem, insertTime, 0, 0, true));
          }, 'Review fallback: ' + clip.label);
        });
        insertOk = true;
        clipCount++;
        if (clip.type === 'insertion') insertionCount++;
      } catch (ex2) {
        if (logger) logger.error('Insert also failed: ' + ex2.message);
      }
    }

    clearSourceInOut(project, clipForTrim, clip.label, logger);

    // Insert DJI audio for source clips (insertions)
    if (insertOk && clip.type === 'insertion' && clip.sourceFile) {
      insertDjiAudio(project, seqEditor, clipMap, clip.sourceFile,
        timelinePos, clip.inSec, clip.outSec, clip.label, logger,
        { colorIdx: clip.colorIdx });
    }

    if (insertOk) {
      timelinePos += (clip.outSec - clip.inSec);
    }

    if (logger) {
      logger.info('[' + (ci + 1) + '/' + clipList.length + '] ' + clip.label +
        ' [' + clip.type.toUpperCase() + '] ' + clip.inSec.toFixed(1) + '-' + clip.outSec.toFixed(1) + 's' +
        ' @' + timelinePos.toFixed(1) + 's' +
        (insertOk ? '' : ' FAILED'));
    }
  }

  if (logger) {
    logger.info(seqName + ': ' + clipCount + ' clips placed (' + insertionCount + ' insertions)');
  }

  return {
    sequence: seq,
    clipCount: clipCount,
    insertionCount: insertionCount,
    seqName: seqName
  };
}

// Color for deleted scene clips
var REVIEW_DELETED_COLOR_IDX = LABEL_COLOR_INDEX.Red; // 6

/**
 * Build the _5_Review_v{N}_DeletedScene sequence from deleted_segments.
 *
 * Places all removed clips sequentially on V1 in Red.
 * Each clip gets a comment marker with the removal reason.
 *
 * @param {Object} project - Premiere project
 * @param {Object} clipMap - { filename: projectItem }
 * @param {Array} deletedSegments - from parsedBrief.deletedSegments
 * @param {string} projectCode - e.g. 'YTCR01'
 * @param {number} version - review version number
 * @param {number} fps - frames per second
 * @param {Object} logger
 * @returns {{ sequence, clipCount, seqName }}
 */
async function buildReviewDeletedScene(project, clipMap, deletedSegments, projectCode, version, fps, logger) {
  fps = fps || 25;
  var seqName = projectCode + '_5_Review_v' + version + '_DeletedScene';

  if (!deletedSegments || deletedSegments.length === 0) {
    if (logger) logger.info('=== Creating empty DeletedScene: ' + seqName + ' (0 clips) ===');

    // Clean existing
    await cleanExistingSequence(project, seqName, logger);

    // Create empty sequence
    var emptySeq = null;
    try {
      emptySeq = await project.createSequence(seqName);
    } catch (ex) {
      if (logger) logger.warn('Empty DeletedScene creation failed: ' + ex.message);
    }
    if (emptySeq && logger) logger.info('Empty DeletedScene created: ' + seqName);
    return { sequence: emptySeq, clipCount: 0, seqName: seqName };
  }

  if (logger) logger.info('=== Building DeletedScene: ' + seqName + ' (' + deletedSegments.length + ' clips) ===');

  // Find first valid clip to create sequence
  var firstSeg = null;
  var firstItem = null;
  for (var fi = 0; fi < deletedSegments.length; fi++) {
    var sf = deletedSegments[fi].sourceFile;
    var item = clipMap[sf] || clipMap[sf.replace(/\.[^.]+$/, '')];
    if (item) {
      firstSeg = deletedSegments[fi];
      firstItem = item;
      break;
    }
  }

  if (!firstItem) {
    if (logger) logger.warn('No source clips found for DeletedScene segments');
    return { sequence: null, clipCount: 0, seqName: seqName };
  }

  // Clean existing sequence
  await cleanExistingSequence(project, seqName, logger);

  // Create sequence from first clip
  var firstCast = ppro.ClipProjectItem.cast(firstItem);
  var firstClip = firstCast || firstItem;

  applyColorByIndex(project, firstItem, REVIEW_DELETED_COLOR_IDX, firstSeg.segmentId, logger);

  var firstInTime = ppro.TickTime.createWithSeconds(parseTc(firstSeg.sourceTcIn));
  var firstOutTime = ppro.TickTime.createWithSeconds(parseTc(firstSeg.sourceTcOut));
  setSourceInOut(project, firstClip, firstInTime, firstOutTime, firstSeg.segmentId, logger);

  var seq = null;
  try {
    seq = await project.createSequenceFromMedia(seqName, [firstClip]);
  } catch (ex) {
    if (logger) logger.warn('createSequenceFromMedia failed: ' + ex.message);
    seq = await project.createSequence(seqName);
  }
  if (!seq) throw new Error('Failed to create DeletedScene sequence: ' + seqName);

  clearSourceInOut(project, firstClip, firstSeg.segmentId, logger);

  var seqEditor = ppro.SequenceEditor.getEditor(seq);
  var clipCount = 1;
  var timelinePos = parseTc(firstSeg.sourceTcOut) - parseTc(firstSeg.sourceTcIn);

  if (logger) {
    logger.info('[1/' + deletedSegments.length + '] ' + firstSeg.segmentId + ' ' +
      firstSeg.sourceFile + ' ' + firstSeg.sourceTcIn + '-' + firstSeg.sourceTcOut +
      ' (removed ' + firstSeg.removedIn + ')');
  }

  // Add comment marker for first clip
  try {
    var markersOwner = await ppro.Markers.getMarkers(seq);
    var markerTime = ppro.TickTime.createWithSeconds(0);
    markersOwner.createMarker(markerTime, MARKER_TYPE_COMMENT, MARKER_COLOR_INDEX.Red,
      firstSeg.segmentId + ' | ' + (firstSeg.reason || 'removed'));
  } catch (mkErr) {
    if (logger) logger.debug('Marker creation skipped: ' + mkErr.message);
  }

  // Insert remaining deleted clips sequentially
  for (var di = 1; di < deletedSegments.length; di++) {
    var seg = deletedSegments[di];
    var rawItem = clipMap[seg.sourceFile] || clipMap[seg.sourceFile.replace(/\.[^.]+$/, '')];
    if (!rawItem) {
      if (logger) logger.warn('Source not found for ' + seg.segmentId + ': ' + seg.sourceFile);
      continue;
    }

    var castClip = ppro.ClipProjectItem.cast(rawItem);
    var clipForTrim = castClip || rawItem;

    applyColorByIndex(project, rawItem, REVIEW_DELETED_COLOR_IDX, seg.segmentId, logger);

    var inTime = ppro.TickTime.createWithSeconds(parseTc(seg.sourceTcIn));
    var outTime = ppro.TickTime.createWithSeconds(parseTc(seg.sourceTcOut));
    setSourceInOut(project, clipForTrim, inTime, outTime, seg.segmentId, logger);

    var insertTime = ppro.TickTime.createWithSeconds(snapToFrame(timelinePos, fps, 'round'));
    var insertOk = false;

    try {
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(seqEditor.createOverwriteItemAction(rawItem, insertTime, 0, 0));
        }, 'DeletedScene: ' + seg.segmentId);
      });
      insertOk = true;
      clipCount++;
    } catch (ex) {
      if (logger) logger.error('Overwrite failed ' + seg.segmentId + ': ' + ex.message);
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(seqEditor.createInsertProjectItemAction(rawItem, insertTime, 0, 0, true));
          }, 'DeletedScene fallback: ' + seg.segmentId);
        });
        insertOk = true;
        clipCount++;
      } catch (ex2) {
        if (logger) logger.error('Insert also failed: ' + ex2.message);
      }
    }

    clearSourceInOut(project, clipForTrim, seg.segmentId, logger);

    if (insertOk) {
      timelinePos += (parseTc(seg.sourceTcOut) - parseTc(seg.sourceTcIn));

      // Add comment marker
      try {
        var mOwner = await ppro.Markers.getMarkers(seq);
        var mTime = ppro.TickTime.createWithSeconds(snapToFrame(timelinePos - (parseTc(seg.sourceTcOut) - parseTc(seg.sourceTcIn)), fps, 'round'));
        mOwner.createMarker(mTime, MARKER_TYPE_COMMENT, MARKER_COLOR_INDEX.Red,
          seg.segmentId + ' | ' + (seg.reason || 'removed'));
      } catch (mkErr2) {
        if (logger) logger.debug('Marker skipped: ' + mkErr2.message);
      }
    }

    if (logger) {
      logger.info('[' + (di + 1) + '/' + deletedSegments.length + '] ' + seg.segmentId + ' ' +
        seg.sourceFile + ' ' + seg.sourceTcIn + '-' + seg.sourceTcOut +
        ' (removed ' + seg.removedIn + ')' + (insertOk ? '' : ' FAILED'));
    }
  }

  if (logger) {
    logger.info(seqName + ': ' + clipCount + ' deleted clips placed');
  }

  return {
    sequence: seq,
    clipCount: clipCount,
    seqName: seqName
  };
}

module.exports = {
  buildReviewSequence,
  buildReviewDeletedScene,
  importEditedVideo,
  parseTc,
  REVIEW_EDITED_COLOR_IDX,
  REVIEW_INSERT_COLOR_IDX,
  REVIEW_DELETED_COLOR_IDX,
  REVIEW_MARKER_INSERT_IDX,
  REVIEW_MARKER_COMMENT_IDX
};
