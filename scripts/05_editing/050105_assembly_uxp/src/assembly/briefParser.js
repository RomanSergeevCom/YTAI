/* briefParser.js — Load & normalize edit_brief.json (supports 2 formats) */

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
  var projectSettings = {};
  var transcriptionDir = '';

  if (raw.segments && Array.isArray(raw.segments)) {
    var resultA = normalizeFormatA(raw);
    segments = resultA.segments;
    projectName = resultA.projectName;
    projectSettings = resultA.projectSettings;
    transcriptionDir = resultA.transcriptionDir;
  } else if (raw.clips && Array.isArray(raw.clips)) {
    var resultB = normalizeFormatB(raw);
    segments = resultB.segments;
    projectName = resultB.projectName;
    projectSettings = resultB.projectSettings;
    transcriptionDir = resultB.transcriptionDir;
  } else {
    throw new Error('Unknown brief format: expected "segments" or "clips" array');
  }

  var blocks = buildBlocks(segments);

  return {
    segments: segments,
    blocks: blocks,
    projectName: projectName,
    projectSettings: projectSettings,
    transcriptionDir: transcriptionDir,
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

  return { segments: segments, projectName: projectName, projectSettings: projectSettings, transcriptionDir: transcriptionDir };
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

  return { segments: segments, projectName: projectName, projectSettings: projectSettings, transcriptionDir: transcriptionDir };
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

module.exports = { parseBrief, parseTimecode, formatTimecode, buildBlocks };
