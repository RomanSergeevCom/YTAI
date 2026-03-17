/* briefParser.js — Load & normalize pre_edit_brief.json (supports 2 formats) */

var constants = require('../shared/constants');
var MARKER_COLOR_INDEX = constants.MARKER_COLOR_INDEX;
var BLOCK_VALID_COLORS = constants.BLOCK_VALID_COLORS;

// Parse timecode string "MM:SS.s" or "HH:MM:SS.s" → seconds
function parseTimecode(tc) {
  if (typeof tc === 'number') return tc;
  if (!tc) return 0;
  var str = String(tc).trim().replace(',', '.');
  var parts = str.split(':');
  try {
    if (parts.length === 2) {
      return parseInt(parts[0], 10) * 60 + parseFloat(parts[1]);
    }
    if (parts.length === 3) {
      return parseInt(parts[0], 10) * 3600 + parseInt(parts[1], 10) * 60 + parseFloat(parts[2]);
    }
    return parseFloat(str) || 0;
  } catch (ex) {
    return 0;
  }
}

// Seconds → "MM:SS.s" format
function formatTimecode(sec) {
  if (!sec || sec < 0) return '00:00.0';
  var m = Math.floor(sec / 60);
  var s = sec % 60;
  var sStr = s < 10 ? '0' + s.toFixed(1) : s.toFixed(1);
  return String(m).padStart(2, '0') + ':' + sStr;
}

/**
 * Parse and normalize edit brief JSON.
 * Supports two formats:
 *   Format A: { segments[], project{} } — from Claude edit brief
 *   Format B: { clips[{ segments[] }] } — from transcript
 *
 * @param {string} jsonString - Raw JSON string
 * @returns {{ segments: Array, blocks: Array, projectName: string, projectSettings: Object, transcriptionDir: string }}
 */
function parseBrief(jsonString) {
  var raw = JSON.parse(jsonString);
  var segments;
  var projectName = '';
  var projectCode = '';
  var projectSettings = {};
  var transcriptionDir = '';
  var producerSpeaker = '';

  if (raw.segments && Array.isArray(raw.segments)) {
    var resultA = normalizeFormatA(raw);
    segments = resultA.segments;
    projectName = resultA.projectName;
    projectCode = resultA.projectCode;
    projectSettings = resultA.projectSettings;
    transcriptionDir = resultA.transcriptionDir;
    producerSpeaker = resultA.producerSpeaker || '';
  } else if (raw.clips && Array.isArray(raw.clips)) {
    var resultB = normalizeFormatB(raw);
    segments = resultB.segments;
    projectName = resultB.projectName;
    projectCode = resultB.projectCode;
    projectSettings = resultB.projectSettings;
    transcriptionDir = resultB.transcriptionDir;
    producerSpeaker = resultB.producerSpeaker || '';
  } else {
    throw new Error('Unknown brief format: expected "segments" or "clips" array');
  }

  var blocks = buildBlocks(segments);
  fixAdjacentColors(blocks);

  return {
    segments: segments,
    blocks: blocks,
    projectName: projectName,
    projectCode: projectCode,
    projectSettings: projectSettings,
    transcriptionDir: transcriptionDir,
    producerSpeaker: producerSpeaker,
    raw: raw
  };
}

// Format A: { segments[], project{} } — from Claude edit brief
function normalizeFormatA(raw) {
  var proj = raw.project || {};
  var projectName = proj.project_name || 'Untitled';
  var projectSettings = proj;
  var transcriptionDir = proj._transcription_dir || '';

  var segments = raw.segments.map(function (s, i) {
    var inSec = parseTimecode(s.tc_in);
    var outSec = parseTimecode(s.tc_out);
    return {
      id: s.segment_id || ('seg_' + String(i + 1).padStart(3, '0')),
      sourceFile: s.source_file || '',
      inSec: inSec,
      outSec: outSec,
      tcIn: s.tc_in || formatTimecode(inSec),
      tcOut: s.tc_out || formatTimecode(outSec),
      block: s.block || 1,
      blockName: s.block_name || ('Block ' + (s.block || 1)),
      segmentName: s.segment_name || '',
      speaker: s.speaker || '',
      transcript: (s.transcript || '').slice(0, 500),
      track: s.track || 'V1',
      color: s.color || 'Cyan',
      use: String(s.use).toUpperCase() === 'TRUE',
      priority: s.priority || 1,
      isChapter: String(s.is_chapter || '').toUpperCase() === 'TRUE',
      brollNote: s.broll_note || '',
      notes: s.notes || '',
      duration: Math.max(0, outSec - inSec)
    };
  });

  var projectCode = (projectName.match(/^[A-Z]+\d+/) || [projectName])[0];
  var producerSpeaker = (raw.project && raw.project.producer_speaker) || '';
  return { segments: segments, projectName: projectName, projectCode: projectCode, projectSettings: projectSettings, transcriptionDir: transcriptionDir, producerSpeaker: producerSpeaker };
}

// Format B: { clips[{ segments[] }] } — from transcript
function normalizeFormatB(raw) {
  var projectName = raw.project || 'Untitled';
  var projectSettings = {};
  var transcriptionDir = '';

  // Try detect transcription dir from first clip
  try {
    var firstClip = (raw.clips || [])[0];
    if (firstClip && firstClip.files && firstClip.files.premiere_transcript) {
      var tp = firstClip.files.premiere_transcript;
      var slashIdx = tp.indexOf('/');
      if (slashIdx > 0) transcriptionDir = tp.substring(0, slashIdx);
    }
  } catch (ex) { /* ignore */ }

  var segments = [];
  var segIdx = 1;

  raw.clips.forEach(function (clip) {
    var filename = clip.filename || (clip.clip_id + '.MP4');
    (clip.segments || []).forEach(function (s) {
      var startSec = s.start || 0;
      var endSec = (s.start != null && s.duration != null)
        ? s.start + s.duration
        : (s.end || startSec);
      segments.push({
        id: s.segment_id || ('seg_' + String(segIdx).padStart(3, '0')),
        sourceFile: filename,
        inSec: startSec,
        outSec: endSec,
        tcIn: s.timecode || formatTimecode(startSec),
        tcOut: formatTimecode(endSec),
        block: s._block || s.block || 1,
        blockName: s._blockName || s.block_name || ('Block ' + segIdx),
        segmentName: s._chapterName || s.segment_name || '',
        speaker: s.speaker || '',
        transcript: (s.text || s.transcript || '').slice(0, 500),
        track: s._track || s.track || 'V1',
        color: s._color || s.color || 'Cyan',
        use: s.use === true || String(s.use || '').toUpperCase() === 'TRUE',
        priority: s._priority || s.priority || 1,
        isChapter: s._isChapter === true || String(s._isChapter || '').toUpperCase() === 'TRUE',
        brollNote: s._brollNote || s.broll_note || '',
        notes: s.notes || '',
        duration: Math.max(0, endSec - startSec)
      });
      segIdx++;
    });
  });

  var projectCode = (projectName.match(/^[A-Z]+\d+/) || [projectName])[0];
  var producerSpeaker = '';  // Format B doesn't have project section
  return { segments: segments, projectName: projectName, projectCode: projectCode, projectSettings: projectSettings, transcriptionDir: transcriptionDir, producerSpeaker: producerSpeaker };
}

// Group segments into blocks, compute stats
function buildBlocks(segments) {
  var map = {};
  segments.forEach(function (seg) {
    var key = seg.block;
    if (!map[key]) {
      map[key] = {
        id: key,
        name: seg.blockName,
        color: seg.color,
        segments: [],
        usedCount: 0,
        totalDuration: 0,
        usedDuration: 0
      };
    }
    map[key].segments.push(seg);
    map[key].totalDuration += seg.duration;
    if (seg.use) {
      map[key].usedCount++;
      map[key].usedDuration += seg.duration;
    }
  });

  return Object.keys(map)
    .sort(function (a, b) { return Number(a) - Number(b); })
    .map(function (k) { return map[k]; });
}

/**
 * Fix adjacent blocks that share the same MARKER_COLOR_INDEX value.
 * Today this affects Purple/Magenta (both index 2).
 * Swaps the second block's color to a different BLOCK_VALID_COLORS entry
 * that has a different marker index from both its left and right neighbors.
 *
 * Mutates blocks[].color and propagates to blocks[].segments[].color.
 */
function fixAdjacentColors(blocks) {
  if (blocks.length < 2) return blocks;

  // Pre-pass: Replace Orange (reserved for Screen Cues) with a valid block color
  for (var oi = 0; oi < blocks.length; oi++) {
    if (blocks[oi].color === 'Orange') {
      var prevOIdx = (oi > 0) ? MARKER_COLOR_INDEX[blocks[oi - 1].color] : -1;
      var nextOIdx = (oi + 1 < blocks.length) ? MARKER_COLOR_INDEX[blocks[oi + 1].color] : -1;
      for (var c = 0; c < BLOCK_VALID_COLORS.length; c++) {
        var candidate = BLOCK_VALID_COLORS[c];
        var candidateIdx = MARKER_COLOR_INDEX[candidate];
        if (candidateIdx !== undefined && candidateIdx !== prevOIdx && candidateIdx !== nextOIdx) {
          blocks[oi].color = candidate;
          for (var si = 0; si < blocks[oi].segments.length; si++) {
            blocks[oi].segments[si].color = candidate;
          }
          break;
        }
      }
    }
  }

  for (var i = 1; i < blocks.length; i++) {
    var prevIdx = MARKER_COLOR_INDEX[blocks[i - 1].color];
    var currIdx = MARKER_COLOR_INDEX[blocks[i].color];

    if (prevIdx === undefined || currIdx === undefined) continue;
    if (prevIdx !== currIdx) continue;

    // Collision found — pick a replacement color
    // Avoid left neighbor's marker index AND right neighbor's (if exists)
    var rightIdx = (i + 1 < blocks.length) ? MARKER_COLOR_INDEX[blocks[i + 1].color] : -1;

    var newColor = null;
    for (var c = 0; c < BLOCK_VALID_COLORS.length; c++) {
      var candidate = BLOCK_VALID_COLORS[c];
      var candidateIdx = MARKER_COLOR_INDEX[candidate];
      if (candidateIdx !== undefined && candidateIdx !== prevIdx && candidateIdx !== rightIdx) {
        newColor = candidate;
        break;
      }
    }

    if (newColor && newColor !== blocks[i].color) {
      blocks[i].color = newColor;
      // Propagate to all segments in this block
      for (var s = 0; s < blocks[i].segments.length; s++) {
        blocks[i].segments[s].color = newColor;
      }
    }
  }

  return blocks;
}

module.exports = { parseBrief, parseTimecode, formatTimecode, buildBlocks, fixAdjacentColors };
