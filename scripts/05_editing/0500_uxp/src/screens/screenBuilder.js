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
 * Depends on: constants.js, clipActions.js, screenParser.js, frameSnap.js
 * Does NOT import assemblyBuilder.js or reviewBuilder.js.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

const { SCREEN_CUE_COLOR, MARKER_TYPE_CHAPTER, MARKER_TYPE_SEGMENTATION, BLOCK_VALID_COLORS, MARKER_COLOR_INDEX } = require('../shared/constants');
const { applyColorToItem, setSourceInOut, clearSourceInOut, cleanExistingSequence, insertDjiAudio } = require('../shared/clipActions');
const { formatMarkerComment, formatSrtContent } = require('./screenParser');
const { snapToFrame, getFps } = require('../shared/frameSnap');

// Default duration for PNG overlay on V2 (seconds)
var OVERLAY_DURATION = 5.0;

// Bin name for Pre-Edit PNG imports (uses freed 01_ slot after 01_Sequence removal)
var SCREEN_CUES_BIN_NAME = '01_PreEdit';

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
function buildSegmentPositionMap(assemblySegments, fps) {
  var positions = {};
  var cumTime = 0;
  for (var i = 0; i < assemblySegments.length; i++) {
    var seg = assemblySegments[i];
    positions[seg.id] = cumTime;
    cumTime += seg.duration;
  }
  return positions;
}

/**
 * Calculate screen cue timeline position on Assembly.
 *
 * Placement rules:
 *   - Block chapter markers are placed at block boundaries (start of first segment).
 *   - Screen markers can be placed ANYWHERE within a segment, not just at block start.
 *   - Position = segment's timeline start + offset within segment (tc_in - segment.inSec).
 *   - Offset is clamped to [0, segment.duration] for safety.
 *
 * This allows screens to appear mid-block (e.g., center of a segment) when the
 * brief specifies a tc_in value within the segment's time range.
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
 * Generate transcript SRT content from segments for word-based editing.
 * Uses cumulative timeline positions by default (Assembly/ScreenCues).
 * With clipOffsets, uses absolute positioning (Review = Ingest layout).
 *
 * @param {Array} assemblySegments - Sorted segments
 * @param {Object} [clipOffsets] - { filename: offsetSec } for absolute positioning (Review)
 * @returns {string} SRT file content with speaker + transcript text
 */
function generateTranscriptSrt(assemblySegments, clipOffsets) {
  if (!assemblySegments || assemblySegments.length === 0) return '';

  var blocks = [];
  var blockNum = 0;
  var cumTime = 0;

  for (var i = 0; i < assemblySegments.length; i++) {
    var seg = assemblySegments[i];
    if (!seg.transcript) {
      cumTime += seg.duration;
      continue;
    }

    blockNum++;
    var startSec, endSec;
    if (clipOffsets && seg.sourceFile && clipOffsets[seg.sourceFile] !== undefined) {
      startSec = clipOffsets[seg.sourceFile] + seg.inSec;
      endSec = clipOffsets[seg.sourceFile] + seg.outSec;
    } else {
      startSec = cumTime;
      endSec = cumTime + seg.duration;
    }

    var text = '';
    if (seg.speaker) text += seg.speaker + ': ';
    text += seg.transcript;

    blocks.push(
      blockNum + '\n' +
      formatSrtTimecode(startSec) + ' --> ' + formatSrtTimecode(endSec) + '\n' +
      text + '\n'
    );

    cumTime += seg.duration;
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
 * Generate caption SRT content (word-grouped, 2-line blocks for on-screen subtitles).
 *
 * Splits each segment's transcript into words, groups into chunks of N words,
 * distributes timing evenly across the segment's duration, and formats as
 * 2-line SRT blocks. Unlike generateTranscriptSrt() which creates one block per segment,
 * this creates multiple smaller blocks suitable for on-screen reading.
 *
 * @param {Array} segments - Sorted segments with .transcript and .duration
 * @param {number} [wordsPerBlock=6] - Target words per SRT block (clamped to 4-10)
 * @param {Object} [clipOffsets] - { filename: offsetSec } for absolute positioning (Review layout)
 * @param {string} [positionTag] - Optional SSA/ASS position tag, e.g. '{\\an8}' for top-center
 * @returns {string} SRT file content
 */
function generateCaptionsSrt(segments, wordsPerBlock, clipOffsets, positionTag) {
  if (!segments || segments.length === 0) return '';

  var wpb = wordsPerBlock || 6;
  if (wpb < 4) wpb = 4;
  if (wpb > 10) wpb = 10;

  var srtBlocks = [];
  var blockNum = 0;
  var cumTime = 0;

  for (var i = 0; i < segments.length; i++) {
    var seg = segments[i];
    var text = (seg.transcript || '').trim();

    // Compute start position: absolute (Review) or cumulative (Assembly/ScreenCues)
    var segStart;
    if (clipOffsets && seg.sourceFile && clipOffsets[seg.sourceFile] !== undefined) {
      segStart = clipOffsets[seg.sourceFile] + seg.inSec;
    } else {
      segStart = cumTime;
    }

    if (!text) {
      cumTime += seg.duration;
      continue;
    }

    var words = text.split(/\s+/).filter(function (w) { return w.length > 0; });
    if (words.length === 0) {
      cumTime += seg.duration;
      continue;
    }

    // Group words into chunks of wpb
    var chunks = [];
    for (var w = 0; w < words.length; w += wpb) {
      chunks.push(words.slice(w, w + wpb));
    }

    // Distribute timing evenly across chunks
    var chunkDuration = seg.duration / chunks.length;

    for (var c = 0; c < chunks.length; c++) {
      var chunkWords = chunks[c];
      var startSec = segStart + c * chunkDuration;
      var endSec = segStart + (c + 1) * chunkDuration;

      // Split chunk into 2 lines (half/half)
      var mid = Math.ceil(chunkWords.length / 2);
      var line1 = chunkWords.slice(0, mid).join(' ');
      var line2 = chunkWords.slice(mid).join(' ');
      var srtText = line2 ? line1 + '\n' + line2 : line1;
      if (positionTag) srtText = positionTag + srtText;

      blockNum++;
      srtBlocks.push(
        blockNum + '\n' +
        formatSrtTimecode(startSec) + ' --> ' + formatSrtTimecode(endSec) + '\n' +
        srtText + '\n'
      );
    }

    cumTime += seg.duration;
  }

  return srtBlocks.length > 0 ? srtBlocks.join('\n') + '\n' : '';
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
 * @param {string} [briefPath] - Path to pre_edit_brief.json (for PNG lookup)
 * @param {Array|null} [pngFiles] - Filenames of PNGs found on disk (pre-checked by pipeline), or null
 * @param {Object|null} [screenCuesBin] - Target bin for PNG imports (01_ScreenCues), or null for project root
 * @returns {{ sequence, clips, markers, overlays, skipped, warnings, totalDuration, assemblySegments, srtContent, markerList }}
 */
async function buildScreenCues(project, screens, segments, clipMap, projectName, logger, briefPath, pngFiles, screenCuesBin, projectSettings) {
  var fps = getFps(projectSettings);
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

  var seqName = projectName + '_4_PreEdit';

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
      cumulativePosition += seg.duration;
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

    cumulativePosition += seg.duration;
  }

  result.totalDuration = cumulativePosition;

  if (logger) {
    logger.info('V1 Assembly copy: ' + result.clips + '/' + useSegs.length + ' clips, total=' + cumulativePosition.toFixed(1) + 's');
    if (totalDjiCount > 0) {
      logger.info('DJI audio: ' + totalDjiCount + ' segment(s) placed on A2');
    }
  }

  // === Phase D: Import + place PNG overlays on V2 ===
  var segPositions = buildSegmentPositionMap(useSegs, fps);
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
      logger.warn('  Run: python generate_screen_cues_png.py --brief <path_to_pre_edit_brief.json>');
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

  // E.1: Block-boundary chapter markers (like Assembly) — with block colors (NOT orange)
  var blockInfo = {};
  var cumTimeBlock = 0;
  for (var bi = 0; bi < useSegs.length; bi++) {
    var bSeg = useSegs[bi];
    if (!blockInfo[bSeg.block]) {
      blockInfo[bSeg.block] = {
        name: bSeg.blockName || ('Chapter ' + bSeg.block),
        startSec: cumTimeBlock,
        durationSec: 0,
        color: bSeg.color,
        isChapter: bSeg.isChapter
      };
    }
    blockInfo[bSeg.block].durationSec += bSeg.duration;
    cumTimeBlock += bSeg.duration;
  }

  var blockKeys = Object.keys(blockInfo).sort(function (a, b) { return Number(a) - Number(b); });
  for (var bk = 0; bk < blockKeys.length; bk++) {
    var block = blockInfo[blockKeys[bk]];
    // Orange is reserved for screen cue markers — pick a different color for block chapters
    var blockMarkerColor = block.color;
    if (blockMarkerColor === 'Orange') {
      // Pick first BLOCK_VALID_COLORS entry with a different marker index from neighbors
      var prevMIdx = (bk > 0) ? MARKER_COLOR_INDEX[blockInfo[blockKeys[bk - 1]].color] : -1;
      var nextMIdx = (bk + 1 < blockKeys.length) ? MARKER_COLOR_INDEX[blockInfo[blockKeys[bk + 1]].color] : -1;
      for (var ci = 0; ci < BLOCK_VALID_COLORS.length; ci++) {
        var cand = BLOCK_VALID_COLORS[ci];
        var candIdx = MARKER_COLOR_INDEX[cand];
        if (candIdx !== undefined && candIdx !== prevMIdx && candIdx !== nextMIdx) {
          blockMarkerColor = cand;
          break;
        }
      }
    }
    markerList.push({
      name: block.name,
      type: MARKER_TYPE_CHAPTER,
      startSec: block.startSec,
      durationSec: block.durationSec,
      comment: '',
      markerColor: blockMarkerColor
    });
  }

  // E.2: Screen cue markers — Orange, Segmentation type
  for (var mi = 0; mi < screens.length; mi++) {
    var screen = screens[mi];
    var markerPos = getScreenTimelinePosition(screen, segPositions);
    if (markerPos === null) continue;

    markerList.push({
      name: '[SCR] ' + screen.type,
      type: MARKER_TYPE_SEGMENTATION,
      startSec: markerPos,
      durationSec: 0,
      comment: formatMarkerComment(screen),
      markerColor: 'Orange'
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
  generateTranscriptSrt,
  generateCaptionsSrt,
  formatSrtTimecode,
  sortSegments,
  OVERLAY_DURATION,
  SCREEN_CUES_BIN_NAME
};
