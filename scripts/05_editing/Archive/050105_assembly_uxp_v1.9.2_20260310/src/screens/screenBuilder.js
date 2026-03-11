/**
 * screenBuilder.js — Build _4_ScreenCues sequence with Production Cue clips.
 *
 * Creates a separate compact sequence where each screen cue is a 2-second clip
 * placed sequentially on V1 (0s, 2s, 4s, ...). Comment markers (Orange) are
 * added for each cue with type/title/body info.
 *
 * Pattern follows assemblyBuilder.js:
 *   1. First clip → createSequenceFromMedia (inherits resolution/fps)
 *   2. Remaining clips → createInsertProjectItemAction at sequential positions
 *   3. All clips pre-trimmed via ClipProjectItem.createSetInOutPointsAction
 *
 * Does NOT depend on Assembly sequence — only needs brief + clipMap.
 *
 * Depends on: constants.js, clipActions.js, screenParser.js
 * Does NOT import assemblyBuilder.js or reviewBuilder.js.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

const { SCREEN_CUE_COLOR, MARKER_TYPE_COMMENT } = require('../shared/constants');
const { applyColorToItem, setSourceInOut, clearSourceInOut, cleanExistingSequence } = require('../shared/clipActions');
const { formatMarkerComment } = require('./screenParser');

// Default duration for cue clips (seconds)
var CUE_CLIP_DURATION = 2.0;

/**
 * Build segment position map: { segId: timelineStartSec }.
 * Recalculates cumulative positions from Assembly segment order.
 *
 * Retained for backward compatibility and potential future overlay mode.
 *
 * @param {Array} assemblySegments - Sorted USE=TRUE segments from buildAssemblySequence
 * @returns {Object} Map of { seg_001: 0.0, seg_002: 10.0, ... }
 */
function buildSegmentPositionMap(assemblySegments) {
  var positions = {};
  var cumTime = 0;
  for (var i = 0; i < assemblySegments.length; i++) {
    var seg = assemblySegments[i];
    positions[seg.id] = cumTime;
    cumTime = Math.round((cumTime + seg.duration) * 10) / 10;
  }
  return positions;
}

/**
 * Calculate screen cue timeline position on Assembly.
 *
 * Retained for backward compatibility and potential future overlay mode.
 *
 * @param {Object} screen - Parsed screen from screenParser
 * @param {Object} segPositions - { segId: timelineStartSec }
 * @returns {number|null} Timeline position in seconds, or null if segment not in Assembly
 */
function getScreenTimelinePosition(screen, segPositions) {
  var segStart = segPositions[screen.segmentId];
  if (segStart === undefined) return null;

  // Offset within segment: screen.tcInSec relative to segment.inSec
  var seg = screen.segment;
  var offset = screen.tcInSec - seg.inSec;
  if (offset < 0) offset = 0;
  if (offset > seg.duration) offset = seg.duration;

  return Math.round((segStart + offset) * 10) / 10;
}

/**
 * Build the _4_ScreenCues sequence with Production Cue clips on V1.
 *
 * Creates a compact sequential timeline: each screen cue is a CUE_CLIP_DURATION
 * clip placed one after another (0, 2, 4, 6, ...). Comment markers (Orange)
 * are created at each clip position.
 *
 * @param {Object} project - Active Premiere project
 * @param {Array} screens - Parsed screens from screenParser
 * @param {Object} clipMap - { filename: ProjectItem } from projectScanner
 * @param {string} projectName - Project name for sequence naming
 * @param {Object} [logger] - Logger instance
 * @returns {{ sequence: Object|null, clips: number, markers: number, skipped: number, warnings: string[], totalDuration: number }}
 */
async function buildScreenCues(project, screens, clipMap, projectName, logger) {
  var result = { sequence: null, clips: 0, markers: 0, skipped: 0, warnings: [], totalDuration: 0 };

  if (!screens || screens.length === 0) {
    if (logger) logger.info('No screen cues to place');
    return result;
  }

  var seqName = projectName + '_4_ScreenCues';

  // Clean old ScreenCues sequence if exists
  await cleanExistingSequence(project, seqName, logger);

  // Filter screens: only those whose source file exists in clipMap
  var validScreens = [];
  for (var i = 0; i < screens.length; i++) {
    var screen = screens[i];
    var sourceFile = screen.segment.sourceFile;
    var rawItem = clipMap[sourceFile] || clipMap[sourceFile.replace(/\.[^.]+$/, '')];
    if (!rawItem) {
      var clipWarn = screen.id + ': source "' + sourceFile + '" not in clipMap, skipped';
      result.warnings.push(clipWarn);
      if (logger) logger.warn('  ' + clipWarn);
      result.skipped++;
      continue;
    }
    validScreens.push({ screen: screen, rawItem: rawItem });
  }

  if (validScreens.length === 0) {
    if (logger) logger.warn('No valid screens to place (all skipped)');
    return result;
  }

  if (logger) logger.info('Valid screens: ' + validScreens.length + '/' + screens.length);

  // === First screen → createSequenceFromMedia (inherits resolution/fps) ===
  var first = validScreens[0];
  var firstCast = ppro.ClipProjectItem.cast(first.rawItem);
  var firstClipForTrim = firstCast || first.rawItem;

  var firstCueInSec = first.screen.tcInSec;
  var firstCueOutSec = firstCueInSec + CUE_CLIP_DURATION;
  if (firstCueOutSec > first.screen.segment.outSec) {
    firstCueOutSec = first.screen.segment.outSec;
  }
  var firstCueInTime = ppro.TickTime.createWithSeconds(firstCueInSec);
  var firstCueOutTime = ppro.TickTime.createWithSeconds(firstCueOutSec);

  // Apply Orange color BEFORE creating sequence
  applyColorToItem(project, first.rawItem, SCREEN_CUE_COLOR.label, first.screen.id, logger);

  // Set source in/out BEFORE creating sequence
  setSourceInOut(project, firstClipForTrim, firstCueInTime, firstCueOutTime, first.screen.id, logger);

  // Create sequence from first clip (inherits media settings)
  var seq = null;
  try {
    seq = await project.createSequenceFromMedia(seqName, [firstClipForTrim]);
  } catch (ex) {
    if (logger) logger.warn('createSequenceFromMedia failed, using createSequence: ' + ex.message);
    seq = await project.createSequence(seqName);
  }

  if (!seq) throw new Error('Failed to create ScreenCues sequence');

  // Clear source in/out on first clip
  clearSourceInOut(project, firstClipForTrim, first.screen.id, logger);

  result.sequence = seq;
  result.clips++;
  var firstActualDur = firstCueOutSec - firstCueInSec;
  var cumTime = Math.round(firstActualDur * 10) / 10;

  if (logger) {
    logger.info('ScreenCues sequence created: ' + seqName);
    logger.info('  [1/' + validScreens.length + '] ' + first.screen.id +
      ': ' + first.screen.type +
      ' → V1@0.0s, dur=' + firstActualDur.toFixed(1) + 's' +
      ', title="' + first.screen.title.substring(0, 25) + '"');
  }

  // Collect marker for first screen
  var markerList = [{
    name: '[SCR] ' + first.screen.type,
    type: MARKER_TYPE_COMMENT,
    startSec: 0,
    durationSec: 0,
    comment: formatMarkerComment(first.screen)
  }];

  // === Remaining screens → createInsertProjectItemAction on V1 ===
  var seqEditor = ppro.SequenceEditor.getEditor(seq);

  for (var vi = 1; vi < validScreens.length; vi++) {
    var entry = validScreens[vi];
    var scr = entry.screen;
    var rawItem = entry.rawItem;

    // Cast to ClipProjectItem for trim operations
    var castClip = ppro.ClipProjectItem.cast(rawItem);
    var clipForTrim = castClip || rawItem;

    // Pre-trim: tcInSec → tcInSec + CUE_CLIP_DURATION (clamped to segment)
    var cueInSec = scr.tcInSec;
    var cueOutSec = cueInSec + CUE_CLIP_DURATION;
    if (cueOutSec > scr.segment.outSec) {
      cueOutSec = scr.segment.outSec;
    }
    var cueInTime = ppro.TickTime.createWithSeconds(cueInSec);
    var cueOutTime = ppro.TickTime.createWithSeconds(cueOutSec);

    // Apply Orange color BEFORE insert
    applyColorToItem(project, rawItem, SCREEN_CUE_COLOR.label, scr.id, logger);

    // Set source in/out BEFORE insert
    setSourceInOut(project, clipForTrim, cueInTime, cueOutTime, scr.id, logger);

    // Insert at cumulative position on V1
    var insertTime = ppro.TickTime.createWithSeconds(cumTime);
    var insertOk = false;
    try {
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(seqEditor.createInsertProjectItemAction(
            rawItem,
            insertTime,
            0, // videoTrackIndex=0 (V1)
            0, // audioTrackIndex=0 (A1)
            true // limitShift
          ));
        }, 'ScreenCue: ' + scr.id);
      });
      insertOk = true;
      result.clips++;
    } catch (ex) {
      // Fallback: try createOverwriteItemAction
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(seqEditor.createOverwriteItemAction(rawItem, insertTime, 0, 0));
          }, 'ScreenCue overwrite: ' + scr.id);
        });
        insertOk = true;
        result.clips++;
        if (logger) logger.info('  Overwrite fallback succeeded for ' + scr.id);
      } catch (ex2) {
        var insertWarn = scr.id + ': insert failed: ' + ex2.message;
        result.warnings.push(insertWarn);
        if (logger) logger.warn('  ' + insertWarn);
      }
    }

    // Clear source in/out
    clearSourceInOut(project, clipForTrim, scr.id, logger);

    // Actual clip duration (may be < CUE_CLIP_DURATION for short segments)
    var actualDur = cueOutSec - cueInSec;

    // Collect marker data
    markerList.push({
      name: '[SCR] ' + scr.type,
      type: MARKER_TYPE_COMMENT,
      startSec: cumTime,
      durationSec: 0,
      comment: formatMarkerComment(scr)
    });

    if (logger) {
      logger.info('  [' + (vi + 1) + '/' + validScreens.length + '] ' + scr.id +
        ': ' + scr.type +
        ' → V1@' + cumTime.toFixed(1) + 's, dur=' + actualDur.toFixed(1) + 's' +
        (insertOk ? ' ✓' : ' ✗') +
        ', title="' + scr.title.substring(0, 25) + '"');
    }

    cumTime = Math.round((cumTime + actualDur) * 10) / 10;
  }

  // === Create Comment markers (Orange) — same 3-transaction pattern ===
  if (markerList.length > 0) {
    try {
      var markersOwner = await ppro.Markers.getMarkers(seq);

      // Transaction 1: Create markers
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            for (var mi = 0; mi < markerList.length; mi++) {
              var mk = markerList[mi];
              ca.addAction(markersOwner.createAddMarkerAction(
                mk.name,
                mk.type,
                ppro.TickTime.createWithSeconds(mk.startSec),
                ppro.TickTime.createWithSeconds(mk.durationSec),
                mk.comment
              ));
            }
          }, 'ScreenCue markers batch');
        });
      } catch (batchErr) {
        // Fallback: individual transactions per marker
        if (logger) logger.debug('Batch marker creation failed, trying individual: ' + batchErr.message);
        for (var mi = 0; mi < markerList.length; mi++) {
          try {
            var mk = markerList[mi];
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                ca.addAction(markersOwner.createAddMarkerAction(
                  mk.name,
                  mk.type,
                  ppro.TickTime.createWithSeconds(mk.startSec),
                  ppro.TickTime.createWithSeconds(mk.durationSec),
                  mk.comment
                ));
              }, 'ScreenCue marker: ' + mk.name);
            });
          } catch (indErr) {
            if (logger) logger.debug('  Marker failed: ' + mk.name + ': ' + indErr.message);
          }
        }
      }

      // Transaction 2: Set marker colors to Orange
      var allMarkers = markersOwner.getMarkers();
      if (allMarkers && allMarkers.length > 0) {
        try {
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) {
              for (var ci = 0; ci < allMarkers.length; ci++) {
                var marker = allMarkers[ci];
                var markerName = '';
                try { markerName = marker.getName ? marker.getName() : (marker.name || ''); } catch (e) { }
                if (markerName.indexOf('[SCR]') === 0) {
                  ca.addAction(marker.createSetColorByIndexAction(SCREEN_CUE_COLOR.markerIdx));
                }
              }
            }, 'ScreenCue marker colors');
          });
        } catch (colorErr) {
          if (logger) logger.debug('Marker color setting failed: ' + colorErr.message);
        }
      }

      result.markers = markerList.length;
    } catch (markerErr) {
      var markerWarn = 'Marker creation failed: ' + markerErr.message;
      result.warnings.push(markerWarn);
      if (logger) logger.warn(markerWarn);
    }
  }

  result.totalDuration = cumTime;

  if (logger) {
    logger.info('Screen cues done: ' + result.clips + ' V1 clips, ' +
      result.markers + ' markers, ' + result.skipped + ' skipped, total=' + cumTime.toFixed(1) + 's');
  }

  return result;
}

module.exports = {
  buildScreenCues,
  buildSegmentPositionMap,
  getScreenTimelinePosition,
  CUE_CLIP_DURATION
};
