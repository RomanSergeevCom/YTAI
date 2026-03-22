/**
 * assemblyBuilder.js — Build {project}_Assembly sequence.
 *
 * Creates a single sequence with USE=TRUE segments on V1 in block order,
 * pre-trimmed to tc_in/tc_out before insertion. No post-insert trimming.
 *
 * Pattern follows timelineBuilder.js (INGEST):
 *   1. Cast clip to ClipProjectItem
 *   2. Set source in/out points (createSetInOutPointsAction)
 *   3. Insert clip (createInsertProjectItemAction / createSequenceFromMedia)
 *   4. Clear source in/out points (createClearInOutPointsAction)
 *
 * Depends on: projectScanner (clipMap), briefParser (segments)
 * Does NOT import any ingest modules.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

const { applyColorToItem, setSourceInOut, clearSourceInOut, cleanExistingSequence, insertDjiAudio } = require('../shared/clipActions');
const { LABEL_COLOR_INDEX } = require('../shared/constants');

/**
 * Sort segments by block (99 last), preserving brief order within each block.
 * IMPORTANT: sorts by block number only — within the same block, the original
 * brief order is preserved (not sorted by inSec, because inSec is the source
 * file timecode, not the desired assembly order).
 */
function sortSegments(segments) {
  // Tag each segment with its original brief index for stable sort
  var tagged = segments.map(function (s, i) {
    s._briefIdx = i;
    return s;
  });
  return tagged.slice().sort(function (a, b) {
    if (a.block === 99 && b.block !== 99) return 1;
    if (b.block === 99 && a.block !== 99) return -1;
    if (a.block !== b.block) return a.block - b.block;
    return a._briefIdx - b._briefIdx; // preserve brief order within block
  });
}


/**
 * Build the Assembly sequence.
 *
 * Follows the INGEST pattern (timelineBuilder.js:buildIngestSequence):
 * 1. First clip → createSequenceFromMedia (inherits resolution/fps/audio)
 * 2. Remaining clips → createInsertProjectItemAction at sequential positions
 * 3. All clips pre-trimmed via ClipProjectItem.createSetInOutPointsAction
 *
 * @param {Object} project - Active Premiere project
 * @param {Object} clipMap - { filename: projectItem } from projectScanner
 * @param {Array} segments - Parsed segments from briefParser (all segments)
 * @param {string} projectName - Project name for sequence naming
 * @param {Object} logger - Logger instance
 * @returns {{ sequence, segments: useSegs, clipCount, totalDuration }}
 */
async function buildAssemblySequence(project, clipMap, segments, projectName, logger, briefVersion) {
  const seqName = projectName + '_2_Assembly' + (briefVersion ? '_v' + briefVersion : '');

  // Filter: only USE=TRUE and block != 99
  const useSegs = sortSegments(segments.filter(function (s) {
    return s.use && s.block !== 99;
  }));

  if (logger) logger.info('Building Assembly sequence: ' + useSegs.length + ' segments');

  if (useSegs.length === 0) {
    throw new Error('No USE=TRUE segments — cannot build Assembly sequence');
  }

  // Log segment order for debugging
  if (logger) {
    for (var si = 0; si < useSegs.length; si++) {
      var seg = useSegs[si];
      logger.debug('  [' + (si + 1) + '] ' + seg.id + ' [' + seg.blockName + '] ' +
        seg.sourceFile + ' ' + seg.tcIn + '-' + seg.tcOut + ' (' + seg.duration.toFixed(1) + 's)');
    }
  }

  // Clean old Assembly sequence if exists (current + legacy name)
  await cleanExistingSequence(project, seqName, logger);
  await cleanExistingSequence(project, projectName + '_Assembly', logger);

  // === First clip: createSequenceFromMedia (inherits resolution/fps) ===
  var firstSeg = useSegs[0];
  var firstRawItem = clipMap[firstSeg.sourceFile] || clipMap[firstSeg.sourceFile.replace(/\.[^.]+$/, '')];
  if (!firstRawItem) {
    throw new Error('First clip not found in project: ' + firstSeg.sourceFile);
  }

  // Cast to ClipProjectItem (required for createSetInOutPointsAction)
  var firstCast = ppro.ClipProjectItem.cast(firstRawItem);
  var firstClipForTrim = firstCast || firstRawItem;
  var castOk = !!firstCast;

  if (logger) logger.info('First clip: "' + firstRawItem.name + '" cast=' + (castOk ? 'OK' : 'FAILED (using raw)'));

  // Set color BEFORE creating sequence — TrackItem inherits color at insertion time
  applyColorToItem(project, firstRawItem, firstSeg.color, firstSeg.id, logger);

  // Set source in/out BEFORE creating sequence
  var firstInTime = ppro.TickTime.createWithSeconds(firstSeg.inSec);
  var firstOutTime = ppro.TickTime.createWithSeconds(firstSeg.outSec);
  var trimOk = setSourceInOut(project, firstClipForTrim, firstInTime, firstOutTime, firstSeg.id, logger);

  // Create sequence from first clip (inherits media settings)
  // NOTE: createSequenceFromMedia accepts ClipProjectItem — this is correct
  var seq = null;
  try {
    seq = await project.createSequenceFromMedia(seqName, [firstClipForTrim]);
  } catch (ex) {
    if (logger) logger.warn('createSequenceFromMedia failed, using createSequence: ' + ex.message);
    seq = await project.createSequence(seqName);
  }

  if (!seq) throw new Error('Failed to create Assembly sequence');

  // Clear source in/out on first clip (so it can be reused with different points)
  clearSourceInOut(project, firstClipForTrim, firstSeg.id, logger);

  // Get SequenceEditor early — needed for DJI audio insert on first clip too
  var seqEditor = ppro.SequenceEditor.getEditor(seq);

  // Insert DJI audio for first clip on A2 (same source in/out as video, same color)
  var firstDjiCount = insertDjiAudio(project, seqEditor, clipMap, firstSeg.sourceFile,
    0, firstSeg.inSec, firstSeg.outSec, firstSeg.id, logger, { color: firstSeg.color });

  if (logger) {
    var firstColorInfo = firstSeg.color ? ', color=' + firstSeg.color + '(' + (LABEL_COLOR_INDEX[firstSeg.color] !== undefined ? LABEL_COLOR_INDEX[firstSeg.color] : '?') + ')' : '';
    logger.info('Assembly sequence created: ' + seqName);
    logger.info('[1/' + useSegs.length + '] ' + firstSeg.id + ': ' + firstSeg.sourceFile +
      ' → cast=' + (castOk ? 'OK' : 'raw') +
      firstColorInfo +
      ', in/out=' + firstSeg.inSec.toFixed(1) + '-' + firstSeg.outSec.toFixed(1) + 's' +
      ' → createSequenceFromMedia' +
      (firstDjiCount > 0 ? ' +A2' : '') +
      ' → dur=' + firstSeg.duration.toFixed(1) + 's @ 0.0s');
  }

  // === Remaining clips: sequential insert with pre-trim ===
  var cumulativePosition = firstSeg.duration; // first clip already placed at 0
  var totalDjiCount = firstDjiCount;
  var clipCount = 1;

  for (var i = 1; i < useSegs.length; i++) {
    var seg = useSegs[i];
    var rawItem = clipMap[seg.sourceFile] || clipMap[seg.sourceFile.replace(/\.[^.]+$/, '')];
    if (!rawItem) {
      if (logger) logger.warn('  Skip ' + seg.id + ': no clip for ' + seg.sourceFile);
      cumulativePosition = Math.round((cumulativePosition + seg.duration) * 10) / 10;
      continue;
    }

    // Cast to ClipProjectItem for trim operations
    // IMPORTANT: createInsertProjectItemAction needs RAW ProjectItem (not cast)
    //   - clipForTrim = cast ClipProjectItem → for setSourceInOut / clearSourceInOut
    //   - rawItem     = original ProjectItem → for createInsertProjectItemAction
    var castClip = ppro.ClipProjectItem.cast(rawItem);
    var clipForTrim = castClip || rawItem;
    var segCastOk = !!castClip;

    // Set color BEFORE insert — each TrackItem inherits the color at insertion time.
    // This allows the same source file to have different colors in different blocks.
    applyColorToItem(project, rawItem, seg.color, seg.id, logger);

    // Set source in/out points BEFORE insert (using CAST item)
    var inTime = ppro.TickTime.createWithSeconds(seg.inSec);
    var outTime = ppro.TickTime.createWithSeconds(seg.outSec);
    var segTrimOk = setSourceInOut(project, clipForTrim, inTime, outTime, seg.id, logger);

    // Insert at cumulative position on V1/A1 (using RAW item — not cast!)
    var insertTime = ppro.TickTime.createWithSeconds(cumulativePosition);
    var insertOk = false;
    try {
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(seqEditor.createInsertProjectItemAction(
            rawItem,       // RAW ProjectItem — same as INGEST pattern
            insertTime,
            0, // video track 0 (V1)
            0, // audio track 0 (A1)
            true // limitShift (same as INGEST)
          ));
        }, 'Insert: ' + seg.id);
      });
      insertOk = true;
      clipCount++;
    } catch (ex) {
      if (logger) {
        logger.error('  Insert failed ' + seg.id + ': ' + ex.message);
        logger.debug('  Item type=' + rawItem.type + ', name=' + rawItem.name +
          ', cast=' + (segCastOk ? 'OK' : 'FAIL') + ', trimOk=' + segTrimOk);
      }

      // Fallback: try createOverwriteItemAction (also uses RAW item)
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(seqEditor.createOverwriteItemAction(rawItem, insertTime, 0, 0));
          }, 'Overwrite: ' + seg.id);
        });
        insertOk = true;
        clipCount++;
        if (logger) logger.info('  Overwrite fallback succeeded for ' + seg.id);
      } catch (ex2) {
        if (logger) logger.error('  Overwrite also failed ' + seg.id + ': ' + ex2.message);
      }
    }

    // Clear source in/out (using CAST item, so clip can be reused)
    clearSourceInOut(project, clipForTrim, seg.id, logger);

    // Insert DJI audio for this segment on A2 (same source in/out as video, same color)
    var segDjiCount = 0;
    if (insertOk) {
      segDjiCount = insertDjiAudio(project, seqEditor, clipMap, seg.sourceFile,
        cumulativePosition, seg.inSec, seg.outSec, seg.id, logger, { color: seg.color });
      totalDjiCount += segDjiCount;
    }

    // Log per-clip result (includes color for debugging)
    if (logger) {
      var colorInfo = seg.color ? ', color=' + seg.color + '(' + (LABEL_COLOR_INDEX[seg.color] !== undefined ? LABEL_COLOR_INDEX[seg.color] : '?') + ')' : '';
      logger.info('[' + (i + 1) + '/' + useSegs.length + '] ' + seg.id + ': ' + seg.sourceFile +
        ' → cast=' + (segCastOk ? 'OK' : 'raw') +
        colorInfo +
        ', in/out=' + seg.inSec.toFixed(1) + '-' + seg.outSec.toFixed(1) + 's' +
        ' → ' + (insertOk ? 'insert@' + cumulativePosition.toFixed(1) + 's' : 'FAILED') +
        (segDjiCount > 0 ? ' +A2' : '') +
        ' → dur=' + seg.duration.toFixed(1) + 's');
    }

    cumulativePosition = Math.round((cumulativePosition + seg.duration) * 10) / 10;
  }

  if (logger) {
    logger.info('Assembly: ' + clipCount + '/' + useSegs.length + ' clips inserted, total=' + cumulativePosition.toFixed(1) + 's');

    // Color summary
    var colorCounts = {};
    for (var ci = 0; ci < useSegs.length; ci++) {
      var c = useSegs[ci].color || 'none';
      colorCounts[c] = (colorCounts[c] || 0) + 1;
    }
    var colorParts = Object.keys(colorCounts).map(function (k) { return colorCounts[k] + '× ' + k; });
    logger.info('Colors: ' + colorParts.join(', '));

    // DJI audio summary
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
      logger.info('V1 verification: ' + finalItems.length + ' items (expected ' + useSegs.length + ')');
      for (var fi = 0; fi < finalItems.length; fi++) {
        try {
          var ti = finalItems[fi];
          var tiStart = await ti.getStartTime();
          var tiDur = await ti.getDuration();
          var tiName = '';
          try { tiName = await ti.getName(); } catch (e) { }
          var startSec = tiStart.seconds !== undefined ? tiStart.seconds : 0;
          var durSec = tiDur.seconds !== undefined ? tiDur.seconds : 0;
          logger.debug('  [' + fi + '] start=' + startSec.toFixed(1) + 's dur=' + durSec.toFixed(1) + 's' +
            (tiName ? ' name="' + tiName + '"' : ''));
        } catch (e) {
          logger.debug('  [' + fi + '] (cannot read item: ' + e.message + ')');
        }
      }
    }
  } catch (verifyErr) {
    if (logger) logger.debug('V1 verification failed: ' + verifyErr.message);
  }

  return { sequence: seq, segments: useSegs, clipCount: clipCount, totalDuration: cumulativePosition };
}

module.exports = {
  buildAssemblySequence,
  sortSegments
};
