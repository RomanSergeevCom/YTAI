/**
 * screenBuilder.js — Build _4_ScreenCues sequence (v1.9.3).
 *
 * Creates a sequence that mirrors the Assembly timeline:
 *   V1 = exact copy of Assembly (same segments, order, trims, colors)
 *   V2 = PNG overlays at screen cue positions (if PNGs available)
 *   Markers = Orange Chapter markers at screen cue positions (created by index.js)
 *   SRT = generated in-memory for import
 *
 * Two-step workflow:
 *   1. Python: generate_screen_cues_png.py → {briefDir}/screen_cues/*.png
 *   2. UXP: buildScreenCues() → V1 + V2 + markers + SRT
 *
 * Pattern follows assemblyBuilder.js for V1:
 *   1. Cast clip to ClipProjectItem
 *   2. Set source in/out points (createSetInOutPointsAction)
 *   3. Insert clip (createInsertProjectItemAction / createSequenceFromMedia)
 *   4. Clear source in/out points (createClearInOutPointsAction)
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

const { SCREEN_CUE_COLOR, MARKER_TYPE_CHAPTER } = require('../shared/constants');
const { applyColorToItem, setSourceInOut, clearSourceInOut, cleanExistingSequence, insertDjiAudio } = require('../shared/clipActions');
const { formatMarkerComment, formatSrtContent } = require('./screenParser');

// Default duration for PNG overlay on V2 (seconds)
var OVERLAY_DURATION = 5.0;

// Bin name for Screen Cues PNG imports (uses freed 01_ slot after 01_Sequence removal)
var SCREEN_CUES_BIN_NAME = '01_ScreenCues';

/**
 * Sort segments by block (99 last), preserving brief order within each block.
 * Duplicated from assemblyBuilder.js (modules don't import each other).
 */
function sortSegments(segments) {
  var tagged = segments.map(function (s, i) {
    s._briefIdx = i;
    return s;
  });
  return tagged.slice().sort(function (a, b) {
    if (a.block === 99 && b.block !== 99) return 1;
    if (b.block === 99 && a.block !== 99) return -1;
    if (a.block !== b.block) return a.block - b.block;
    return a._briefIdx - b._briefIdx;
  });
}

/**
 * Build segment position map: { segId: timelineStartSec }.
 * Recalculates cumulative positions from Assembly segment order.
 *
 * @param {Array} assemblySegments - Sorted USE=TRUE segments
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
 * @param {Object} screen - Parsed screen from screenParser
 * @param {Object} segPositions - { segId: timelineStartSec }
 * @returns {number|null} Timeline position in seconds, or null if segment not in Assembly
 */
function getScreenTimelinePosition(screen, segPositions) {
  var segStart = segPositions[screen.segmentId];
  if (segStart === undefined) return null;

  var seg = screen.segment;
  var offset = screen.tcInSec - seg.inSec;
  if (offset < 0) offset = 0;
  if (offset > seg.duration) offset = seg.duration;

  return Math.round((segStart + offset) * 10) / 10;
}

/**
 * Format seconds to SRT timecode: HH:MM:SS,mmm
 *
 * @param {number} seconds
 * @returns {string} SRT timecode
 */
function formatSrtTimecode(seconds) {
  if (seconds < 0) seconds = 0;
  var h = Math.floor(seconds / 3600);
  var m = Math.floor((seconds % 3600) / 60);
  var s = seconds % 60;
  var ms = Math.round((s - Math.floor(s)) * 1000);
  return String(h).padStart(2, '0') + ':' +
    String(m).padStart(2, '0') + ':' +
    String(Math.floor(s)).padStart(2, '0') + ',' +
    String(ms).padStart(3, '0');
}

/**
 * Generate SRT content for screen cues with Assembly timeline positions.
 *
 * @param {Array} screens - Parsed screens from screenParser
 * @param {Array} assemblySegments - Sorted USE=TRUE segments
 * @returns {string} SRT file content
 */
function generateScreenCuesSrt(screens, assemblySegments) {
  if (!screens || screens.length === 0) return '';

  var segPositions = buildSegmentPositionMap(assemblySegments);
  var blocks = [];
  var blockNum = 0;

  for (var i = 0; i < screens.length; i++) {
    var screen = screens[i];
    var pos = getScreenTimelinePosition(screen, segPositions);
    if (pos === null) continue;

    var endPos = pos + OVERLAY_DURATION;
    blockNum++;

    var srtText = formatSrtContent(screen);
    blocks.push(
      blockNum + '\n' +
      formatSrtTimecode(pos) + ' --> ' + formatSrtTimecode(endPos) + '\n' +
      srtText + '\n'
    );
  }

  return blocks.length > 0 ? blocks.join('\n') + '\n' : '';
}

/**
 * Find a recently imported item in the project by filename.
 * Searches target bin first (if provided), then root items and one level of bins.
 *
 * @param {Object} project - Active Premiere project
 * @param {string} filename - Filename to search for
 * @param {Object|null} [targetBin] - Bin to search first (e.g. 01_ScreenCues)
 * @returns {Object|null} ProjectItem or null
 */
async function findImportedItem(project, filename, targetBin) {
  // Search in target bin first (if provided)
  if (targetBin) {
    try {
      var binItems = await targetBin.getItems();
      for (var i = 0; i < binItems.length; i++) {
        if (binItems[i].name === filename) return binItems[i];
      }
    } catch (e) { /* bin access failed, fall through to root search */ }
  }
  // Fallback: search root + one level
  var rootItem = await project.getRootItem();
  var items = await rootItem.getItems();
  for (var i = 0; i < items.length; i++) {
    if (items[i].name === filename) return items[i];
    try {
      var folder = ppro.FolderItem.cast(items[i]);
      if (folder) {
        var subItems = await folder.getItems();
        for (var j = 0; j < subItems.length; j++) {
          if (subItems[j].name === filename) return subItems[j];
        }
      }
    } catch (e) { /* not a folder */ }
  }
  return null;
}

/**
 * Build the _4_ScreenCues sequence (v1.9.3).
 *
 * V1: Exact copy of Assembly (same segments, order, trims, colors)
 * V2: PNG overlays at screen cue positions (if PNGs available)
 * Markers: Orange Chapter markers at each screen cue position (via markerList → index.js)
 *
 * @param {Object} project - Active Premiere project
 * @param {Array} screens - Parsed screens from screenParser
 * @param {Array} segments - All parsed segments from briefParser
 * @param {Object} clipMap - { filename: ProjectItem } from projectScanner
 * @param {string} projectName - Project name for sequence naming
 * @param {Object} [logger] - Logger instance
 * @param {string} [briefPath] - Path to edit_brief.json (for PNG lookup)
 * @param {Array|null} [pngFiles] - Filenames of PNGs found on disk (pre-checked by pipeline), or null
 * @param {Object|null} [screenCuesBin] - Target bin for PNG imports (01_ScreenCues), or null for project root
 * @returns {{ sequence, clips, markers, overlays, skipped, warnings, totalDuration, assemblySegments, srtContent, markerList }}
 */
async function buildScreenCues(project, screens, segments, clipMap, projectName, logger, briefPath, pngFiles, screenCuesBin) {
  var result = {
    sequence: null, clips: 0, markers: 0, overlays: 0, skipped: 0,
    warnings: [], totalDuration: 0, assemblySegments: [], srtContent: '',
    markerList: []
  };

  if (!screens || screens.length === 0) {
    if (logger) logger.info('No screen cues to place');
    return result;
  }

  // === Phase A: Filter + sort segments (same as assemblyBuilder) ===
  var useSegs = sortSegments((segments || []).filter(function (s) {
    return s.use && s.block !== 99;
  }));

  if (useSegs.length === 0) {
    if (logger) logger.warn('No USE=TRUE segments — cannot build Screen Cues V1');
    return result;
  }

  result.assemblySegments = useSegs;

  if (logger) {
    logger.info('Screen Cues v1.9.3: ' + useSegs.length + ' Assembly segments, ' + screens.length + ' screens');
    for (var si = 0; si < useSegs.length; si++) {
      var seg = useSegs[si];
      logger.debug('  [' + (si + 1) + '] ' + seg.id + ' [' + seg.blockName + '] ' +
        seg.sourceFile + ' ' + seg.tcIn + '-' + seg.tcOut + ' (' + seg.duration.toFixed(1) + 's)');
    }
  }

  var seqName = projectName + '_4_ScreenCues';

  // === Phase B: Clean old sequence ===
  await cleanExistingSequence(project, seqName, logger);

  // === Phase C: Build V1 — exact Assembly copy ===
  // First clip → createSequenceFromMedia
  var firstSeg = useSegs[0];
  var firstRawItem = clipMap[firstSeg.sourceFile] || clipMap[firstSeg.sourceFile.replace(/\.[^.]+$/, '')];
  if (!firstRawItem) {
    throw new Error('First clip not found in project: ' + firstSeg.sourceFile);
  }

  var firstCast = ppro.ClipProjectItem.cast(firstRawItem);
  var firstClipForTrim = firstCast || firstRawItem;

  // Apply color + pre-trim
  applyColorToItem(project, firstRawItem, firstSeg.color, firstSeg.id, logger);
  var firstInTime = ppro.TickTime.createWithSeconds(firstSeg.inSec);
  var firstOutTime = ppro.TickTime.createWithSeconds(firstSeg.outSec);
  setSourceInOut(project, firstClipForTrim, firstInTime, firstOutTime, firstSeg.id, logger);

  // Create sequence from first clip
  var seq = null;
  try {
    seq = await project.createSequenceFromMedia(seqName, [firstClipForTrim]);
  } catch (ex) {
    if (logger) logger.warn('createSequenceFromMedia failed, using createSequence: ' + ex.message);
    seq = await project.createSequence(seqName);
  }

  if (!seq) throw new Error('Failed to create ScreenCues sequence');

  clearSourceInOut(project, firstClipForTrim, firstSeg.id, logger);

  result.sequence = seq;
  result.clips++;
  var cumulativePosition = firstSeg.duration;

  // Get SequenceEditor early — needed for DJI audio insert on first clip too
  var seqEditor = ppro.SequenceEditor.getEditor(seq);

  // Insert DJI audio for first clip on A2 (same source in/out as video, same color)
  var firstDjiCount = insertDjiAudio(project, seqEditor, clipMap, firstSeg.sourceFile,
    0, firstSeg.inSec, firstSeg.outSec, firstSeg.id, logger, { color: firstSeg.color });
  var totalDjiCount = firstDjiCount;

  if (logger) {
    logger.info('ScreenCues sequence created: ' + seqName);
    logger.info('[1/' + useSegs.length + '] V1: ' + firstSeg.id + ' → createSequenceFromMedia' +
      (firstDjiCount > 0 ? ' +A2' : '') +
      ', dur=' + firstSeg.duration.toFixed(1) + 's');
  }

  for (var i = 1; i < useSegs.length; i++) {
    var seg = useSegs[i];
    var rawItem = clipMap[seg.sourceFile] || clipMap[seg.sourceFile.replace(/\.[^.]+$/, '')];
    if (!rawItem) {
      if (logger) logger.warn('  Skip ' + seg.id + ': no clip for ' + seg.sourceFile);
      cumulativePosition = Math.round((cumulativePosition + seg.duration) * 10) / 10;
      continue;
    }

    var castClip = ppro.ClipProjectItem.cast(rawItem);
    var clipForTrim = castClip || rawItem;

    applyColorToItem(project, rawItem, seg.color, seg.id, logger);

    var inTime = ppro.TickTime.createWithSeconds(seg.inSec);
    var outTime = ppro.TickTime.createWithSeconds(seg.outSec);
    setSourceInOut(project, clipForTrim, inTime, outTime, seg.id, logger);

    var insertTime = ppro.TickTime.createWithSeconds(cumulativePosition);
    var insertOk = false;
    try {
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(seqEditor.createInsertProjectItemAction(
            rawItem, insertTime, 0, 0, true
          ));
        }, 'ScreenV1: ' + seg.id);
      });
      insertOk = true;
      result.clips++;
    } catch (ex) {
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(seqEditor.createOverwriteItemAction(rawItem, insertTime, 0, 0));
          }, 'ScreenV1 overwrite: ' + seg.id);
        });
        insertOk = true;
        result.clips++;
      } catch (ex2) {
        if (logger) logger.error('  V1 insert failed ' + seg.id + ': ' + ex2.message);
      }
    }

    clearSourceInOut(project, clipForTrim, seg.id, logger);

    // Insert DJI audio for this segment on A2 (same source in/out as video, same color)
    var segDjiCount = 0;
    if (insertOk) {
      segDjiCount = insertDjiAudio(project, seqEditor, clipMap, seg.sourceFile,
        cumulativePosition, seg.inSec, seg.outSec, seg.id, logger, { color: seg.color });
      totalDjiCount += segDjiCount;
    }

    if (logger) {
      logger.info('[' + (i + 1) + '/' + useSegs.length + '] V1: ' + seg.id +
        ' → ' + (insertOk ? 'insert@' + cumulativePosition.toFixed(1) + 's' : 'FAILED') +
        (segDjiCount > 0 ? ' +A2' : '') +
        ', dur=' + seg.duration.toFixed(1) + 's');
    }

    cumulativePosition = Math.round((cumulativePosition + seg.duration) * 10) / 10;
  }

  result.totalDuration = cumulativePosition;

  if (logger) {
    logger.info('V1 Assembly copy: ' + result.clips + '/' + useSegs.length + ' clips, total=' + cumulativePosition.toFixed(1) + 's');
    if (totalDjiCount > 0) {
      logger.info('DJI audio: ' + totalDjiCount + ' segment(s) placed on A2');
    }
  }

  // === Phase D: Import + place PNG overlays on V2 ===
  var segPositions = buildSegmentPositionMap(useSegs);
  var pngDir = null;

  if (briefPath) {
    pngDir = briefPath.replace(/[/\\][^/\\]+$/, '') + '/screen_cues';
  }

  // Pre-flight: check if any PNGs are available
  var hasPngs = pngFiles && pngFiles.length > 0;

  if (pngDir && hasPngs) {
    if (logger) logger.info('V2 PNGs: ' + pngFiles.length + ' files in screen_cues/');

    for (var pi = 0; pi < screens.length; pi++) {
      var screen = screens[pi];
      var pos = getScreenTimelinePosition(screen, segPositions);
      if (pos === null) {
        result.warnings.push(screen.id + ': segment not in Assembly, skipped');
        result.skipped++;
        continue;
      }

      var pngFileName = screen.id + '_' + screen.type + '.png';
      var pngPath = pngDir + '/' + pngFileName;

      // Pre-check: file verified on disk by pipeline
      if (!pngFiles.includes(pngFileName)) {
        result.warnings.push(screen.id + ': PNG not generated (' + pngFileName + ')');
        result.skipped++;
        if (logger) logger.debug('  ' + screen.id + ': PNG missing on disk, skipping');
        continue;
      }

      // File exists on disk → import to Premiere project (into 01_ScreenCues bin if available)
      var pngItem = null;
      try {
        await project.importFiles([pngPath], true, screenCuesBin || null, false);
        pngItem = await findImportedItem(project, pngFileName, screenCuesBin);
      } catch (e) {
        result.warnings.push(screen.id + ': PNG import failed: ' + e.message);
        result.skipped++;
        if (logger) logger.warn('  ' + screen.id + ': PNG import error: ' + e.message);
        continue;
      }

      if (!pngItem) {
        result.warnings.push(screen.id + ': PNG imported but Premiere did not register it');
        result.skipped++;
        continue;
      }

      // Cast + pre-trim (still image: 0 → overlayDur)
      var castPng = ppro.ClipProjectItem.cast(pngItem);
      var pngForTrim = castPng || pngItem;
      var overlayDur = Math.min(OVERLAY_DURATION, cumulativePosition - pos);
      if (overlayDur <= 0) overlayDur = OVERLAY_DURATION;

      setSourceInOut(project, pngForTrim,
        ppro.TickTime.createWithSeconds(0),
        ppro.TickTime.createWithSeconds(overlayDur),
        screen.id, logger);

      applyColorToItem(project, pngItem, SCREEN_CUE_COLOR.label, screen.id, logger);

      // Place on V2 (videoTrackIndex=1) at screen position
      var overlayTime = ppro.TickTime.createWithSeconds(pos);
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(seqEditor.createOverwriteItemAction(pngItem, overlayTime, 1, -1));
          }, 'ScreenOverlay: ' + screen.id);
        });
        result.overlays++;
      } catch (ex) {
        try {
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) {
              ca.addAction(seqEditor.createInsertProjectItemAction(pngItem, overlayTime, 1, -1, false));
            }, 'ScreenOverlay insert: ' + screen.id);
          });
          result.overlays++;
        } catch (ex2) {
          result.warnings.push(screen.id + ': V2 placement failed: ' + ex2.message);
          if (logger) logger.warn('  ' + screen.id + ': V2 placement failed');
        }
      }

      clearSourceInOut(project, pngForTrim, screen.id, logger);

      if (logger) {
        logger.info('  V2: ' + screen.id + ' (' + screen.type + ') → @' + pos.toFixed(1) + 's, dur=' + overlayDur.toFixed(1) + 's');
      }
    }

    if (logger) logger.info('V2 PNG overlays: ' + result.overlays + ' placed');
  } else if (pngDir && !hasPngs) {
    if (logger) {
      logger.warn('V2 PNGs: screen_cues/ folder empty or not found — skipping overlays');
      logger.warn('  Run: python generate_screen_cues_png.py --brief <path_to_edit_brief.json>');
    }
  } else {
    if (logger) logger.info('No briefPath provided — skipping V2 PNG overlays');
  }

  // === Phase E: Build marker list (actual creation done in index.js) ===
  // Marker creation is handled by createScreenCuesMarkers() in index.js,
  // following the same 4-transaction pattern as createAssemblyMarkers().
  // This ensures markers are read ONCE and the same references are used
  // for both color and type transactions.
  var markerList = [];
  for (var mi = 0; mi < screens.length; mi++) {
    var screen = screens[mi];
    var markerPos = getScreenTimelinePosition(screen, segPositions);
    if (markerPos === null) continue;

    markerList.push({
      name: '[SCR] ' + screen.type,
      type: MARKER_TYPE_CHAPTER,
      startSec: markerPos,
      durationSec: 0,
      comment: formatMarkerComment(screen)
    });
  }

  result.markerList = markerList;
  result.markers = markerList.length;

  if (logger) {
    logger.info('Markers: ' + markerList.length + ' prepared (will be created by pipeline)');
  }

  // === Phase F: Generate SRT ===
  result.srtContent = generateScreenCuesSrt(screens, useSegs);

  if (logger) {
    logger.info('SRT: ' + (result.srtContent ? 'generated (' + result.srtContent.split('\n\n').length + ' blocks)' : 'empty'));
    logger.info('Screen cues done: V1=' + result.clips + ' clips, V2=' + result.overlays +
      ' overlays, markers=' + result.markers + ', skipped=' + result.skipped +
      ', total=' + cumulativePosition.toFixed(1) + 's');
  }

  return result;
}

module.exports = {
  buildScreenCues,
  buildSegmentPositionMap,
  getScreenTimelinePosition,
  generateScreenCuesSrt,
  formatSrtTimecode,
  sortSegments,
  OVERLAY_DURATION,
  SCREEN_CUES_BIN_NAME
};
