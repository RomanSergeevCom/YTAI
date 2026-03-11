/* project-io.js — Load/parse/normalize JSON, save reviewed
   UXP: uses globals APP, BUS, appLog from state.js */

console.log('[YTAI] project-io.js loading...');

var uxpStorage, uxpFs, uxpFormats;
try {
  console.log('[YTAI] project-io.js: requiring uxp...');
  var uxpModule = require('uxp');
  console.log('[YTAI] project-io.js: uxp module =', typeof uxpModule, Object.keys(uxpModule || {}));
  uxpStorage = uxpModule.storage;
  console.log('[YTAI] project-io.js: uxpStorage =', typeof uxpStorage, Object.keys(uxpStorage || {}));
  uxpFs      = uxpStorage.localFileSystem;
  console.log('[YTAI] project-io.js: uxpFs =', typeof uxpFs, uxpFs ? Object.keys(uxpFs) : 'null');
  uxpFormats = uxpStorage.formats;
  console.log('[YTAI] project-io.js: uxpFormats =', typeof uxpFormats, uxpFormats ? JSON.stringify(uxpFormats) : 'null');
  console.log('[YTAI] project-io.js: UXP storage OK');
} catch (e) {
  console.error('[YTAI] UXP storage not available:', e);
}

/* ══════════════════════════════
   TIMECODE HELPERS
   ══════════════════════════════ */

function parseTimecode(tc) {
  if (typeof tc === 'number') return tc;
  if (!tc) return 0;
  var str = String(tc).trim().replace(',', '.');
  var parts = str.split(':');
  try {
    if (parts.length === 2) return parseInt(parts[0], 10) * 60 + parseFloat(parts[1]);
    if (parts.length === 3) return parseInt(parts[0], 10) * 3600 + parseInt(parts[1], 10) * 60 + parseFloat(parts[2]);
    return parseFloat(str) || 0;
  } catch (ex) { return 0; }
}

function formatTimecode(sec) {
  if (!sec || sec < 0) return '00:00.0';
  var m = Math.floor(sec / 60);
  var s = sec % 60;
  var sStr = s < 10 ? '0' + s.toFixed(1) : s.toFixed(1);
  return String(m).padStart(2, '0') + ':' + sStr;
}

function formatDuration(sec) {
  if (!sec || sec < 0) sec = 0;
  var m = Math.floor(sec / 60);
  var s = Math.floor(sec % 60);
  return m + ':' + String(s).padStart(2, '0');
}

/* ══════════════════════════════
   NORMALIZE
   ══════════════════════════════ */

function normalize(raw) {
  if (raw.segments && Array.isArray(raw.segments) && raw.segments.length > 0) {
    return normalizeFormatA(raw);
  }
  if (raw.clips && Array.isArray(raw.clips)) {
    return normalizeFormatB(raw);
  }
  throw new Error('Unknown JSON format: expected segments[] or clips[]');
}

/* Format A: spec { segments, project } */
function normalizeFormatA(raw) {
  var proj = raw.project || {};
  APP.projectName = proj.project_name || raw.project_name || 'Untitled';
  APP.projectSettings = proj;
  APP.transcriptionDir = proj._transcription_dir || '';
  appLog('Project: ' + APP.projectName + (APP.transcriptionDir ? ', transcription: ' + APP.transcriptionDir : ''));

  return raw.segments.map(function (s, i) {
    var inSec  = parseTimecode(s.tc_in);
    var outSec = parseTimecode(s.tc_out);
    return {
      id:          s.segment_id || ('seg_' + String(i + 1).padStart(3, '0')),
      sourceFile:  s.source_file || '',
      inSec: inSec, outSec: outSec,
      tcIn:        s.tc_in  || formatTimecode(inSec),
      tcOut:       s.tc_out || formatTimecode(outSec),
      block:       s.block  || 1,
      blockName:   s.block_name || ('Block ' + (s.block || 1)),
      segmentName: s.segment_name || '',
      speaker:     s.speaker || '',
      transcript:  s.transcript || '',
      track:       s.track  || 'V1',
      color:       s.color  || 'Cyan',
      use:         String(s.use).toUpperCase() === 'TRUE',
      priority:    s.priority || 1,
      isChapter:   String(s.is_chapter || '').toUpperCase() === 'TRUE',
      brollNote:   s.broll_note || '',
      notes:       s.notes || '',
      duration:    Math.max(0, outSec - inSec),
    };
  });
}

/* Format B: brief { clips[].segments with _prefixed fields } */
function normalizeFormatB(raw) {
  APP.projectName = raw.project || raw.version || 'Untitled';
  APP.projectSettings = raw._projectSettings || {};

  /* Detect transcription dir from clip files paths */
  APP.transcriptionDir = '';
  try {
    var firstClip = (raw.clips || [])[0];
    if (firstClip && firstClip.files && firstClip.files.premiere_transcript) {
      var tp = firstClip.files.premiere_transcript;
      /* e.g. "YTAI_Edit_transcription/per_clip/C5402/C5402_premiere_transcript.json" */
      var slashIdx = tp.indexOf('/');
      if (slashIdx > 0) APP.transcriptionDir = tp.substring(0, slashIdx);
    }
  } catch (ex) { /* ok */ }
  appLog('Project: ' + APP.projectName + (APP.transcriptionDir ? ', transcription: ' + APP.transcriptionDir : ''));

  var segments = [];
  var segIdx = 1;

  raw.clips.forEach(function (clip) {
    var filename = clip.filename || (clip.clip_id + '.MP4');
    (clip.segments || []).forEach(function (s) {
      var startSec = s.start || 0;
      var endSec   = (s.start != null && s.duration != null) ? s.start + s.duration : (s.end || startSec);
      segments.push({
        id:          s.segment_id || ('seg_' + String(segIdx).padStart(3, '0')),
        sourceFile:  filename,
        inSec:       startSec,
        outSec:      endSec,
        tcIn:        s.timecode || formatTimecode(startSec),
        tcOut:       formatTimecode(endSec),
        block:       s._block  || s.block || 1,
        blockName:   s._blockName || s.block_name || clip.clip_id || ('Block ' + segIdx),
        segmentName: s._chapterName || s.segment_name || '',
        speaker:     s.speaker || '',
        transcript:  s.text || s.transcript || '',
        track:       s._track  || s.track || 'V1',
        color:       s._color  || s.color || 'Cyan',
        use:         s.use === true || String(s.use || '').toUpperCase() === 'TRUE',
        priority:    s._priority || s.priority || 1,
        isChapter:   s._isChapter === true || String(s._isChapter || '').toUpperCase() === 'TRUE',
        brollNote:   s._brollNote || s.broll_note || '',
        notes:       s.notes || '',
        duration:    Math.max(0, endSec - startSec),
      });
      segIdx++;
    });
  });

  return segments;
}

/* ══════════════════════════════
   BUILD BLOCKS
   ══════════════════════════════ */

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
        usedDuration: 0,
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

/* ══════════════════════════════
   FILE OPERATIONS
   ══════════════════════════════ */

async function pickAndLoadBrief() {
  console.log('[YTAI] pickAndLoadBrief() called');
  appLog('pickAndLoadBrief: starting...');

  if (!uxpFs) {
    console.error('[YTAI] pickAndLoadBrief: uxpFs is null/undefined');
    appLog('UXP file system not available (uxpFs=' + typeof uxpFs + ')', 'error');
    return;
  }

  console.log('[YTAI] pickAndLoadBrief: uxpFs available, type =', typeof uxpFs);
  console.log('[YTAI] pickAndLoadBrief: uxpFs methods =', Object.keys(uxpFs));
  appLog('pickAndLoadBrief: uxpFs OK, calling getFileForOpening...');

  try {
    var file = null;

    /* Try approach 1: types parameter */
    try {
      console.log('[YTAI] pickAndLoadBrief: trying getFileForOpening({ types: [json] })');
      appLog('Trying: getFileForOpening({ types: ["json"] })');
      file = await uxpFs.getFileForOpening({ types: ['json'] });
      console.log('[YTAI] pickAndLoadBrief: approach 1 result =', file, typeof file);
    } catch (e1) {
      console.error('[YTAI] pickAndLoadBrief: approach 1 failed:', e1);
      appLog('types:["json"] failed: ' + e1.message, 'error');

      /* Try approach 2: allowedFileTypes parameter */
      try {
        console.log('[YTAI] pickAndLoadBrief: trying getFileForOpening({ allowedFileTypes: [json] })');
        appLog('Trying: getFileForOpening({ allowedFileTypes: ["json"] })');
        file = await uxpFs.getFileForOpening({ allowedFileTypes: ['json'] });
        console.log('[YTAI] pickAndLoadBrief: approach 2 result =', file, typeof file);
      } catch (e2) {
        console.error('[YTAI] pickAndLoadBrief: approach 2 failed:', e2);
        appLog('allowedFileTypes failed: ' + e2.message, 'error');

        /* Try approach 3: no parameters */
        try {
          console.log('[YTAI] pickAndLoadBrief: trying getFileForOpening() no params');
          appLog('Trying: getFileForOpening() no params');
          file = await uxpFs.getFileForOpening();
          console.log('[YTAI] pickAndLoadBrief: approach 3 result =', file, typeof file);
        } catch (e3) {
          console.error('[YTAI] pickAndLoadBrief: approach 3 failed:', e3);
          appLog('No-params approach failed: ' + e3.message, 'error');
          throw e3;
        }
      }
    }

    if (!file) {
      console.log('[YTAI] pickAndLoadBrief: file is null/undefined - user cancelled?');
      appLog('No file selected (user cancelled?)');
      return;
    }

    console.log('[YTAI] pickAndLoadBrief: file selected!', file.name, typeof file);
    appLog('File selected: ' + (file.name || 'unknown'));
    return await loadFromEntry(file);

  } catch (e) {
    console.error('[YTAI] pickAndLoadBrief: FATAL error:', e);
    appLog('Load error: ' + e.message, 'error');
    throw e;
  }
}

async function loadFromEntry(entry) {
  console.log('[YTAI] loadFromEntry: reading file...');
  appLog('loadFromEntry: reading file...');
  var text = await entry.read({ format: uxpFormats.utf8 });
  console.log('[YTAI] loadFromEntry: read ' + text.length + ' chars');
  appLog('Read ' + text.length + ' characters');

  var raw = JSON.parse(text);
  console.log('[YTAI] loadFromEntry: parsed JSON, keys =', Object.keys(raw));
  appLog('Parsed JSON OK, keys: ' + Object.keys(raw).join(', '));

  APP.brief = raw;
  APP.briefFileEntry = entry;

  try { APP.briefFileToken = await uxpFs.createPersistentToken(entry); }
  catch (ex) { console.log('[YTAI] loadFromEntry: persistent token failed (non-critical):', ex.message); }

  var segments = normalize(raw);
  APP.segments = segments;
  APP.blocks = buildBlocks(segments);

  /* Initialize decisions from existing use field */
  APP.decisions = {};
  segments.forEach(function (seg) {
    if (seg.use) APP.decisions[seg.id] = 'use';
  });

  APP.activeSegmentId = segments.length > 0 ? segments[0].id : null;

  console.log('[YTAI] loadFromEntry: ' + segments.length + ' segments, ' + APP.blocks.length + ' blocks');
  appLog('Loaded ' + segments.length + ' segments in ' + APP.blocks.length + ' blocks \u2014 ' + APP.projectName);
  BUS.emit('brief-loaded');
  return segments;
}

async function reloadBrief() {
  if (APP.briefFileToken && uxpFs) {
    try {
      var entry = await uxpFs.getEntryForPersistentToken(APP.briefFileToken);
      return await loadFromEntry(entry);
    } catch (e) {
      appLog('Reload by token failed: ' + e.message, 'error');
    }
  }
  return pickAndLoadBrief();
}

async function saveReviewed() {
  if (!APP.briefFileEntry) { appLog('No file loaded', 'error'); return; }

  var output = {
    segments: APP.segments.map(function (seg) {
      var decision = APP.decisions[seg.id];
      var useVal = (decision === 'use' || decision === 'shorts') ? 'TRUE' : 'FALSE';
      return {
        segment_id:   seg.id,
        source_file:  seg.sourceFile,
        tc_in:        seg.tcIn,
        tc_out:       seg.tcOut,
        block:        seg.block,
        block_name:   seg.blockName,
        segment_name: seg.segmentName,
        speaker:      seg.speaker,
        transcript:   seg.transcript,
        track:        seg.track,
        color:        seg.color,
        use:          useVal,
        priority:     seg.priority,
        is_chapter:   seg.isChapter ? 'TRUE' : 'FALSE',
        broll_note:   seg.brollNote,
        notes:        seg.notes,
        decision_tag: decision || null,
      };
    }),
    project: APP.projectSettings || {},
    _reviewedAt: new Date().toISOString(),
  };

  try {
    var file = await uxpFs.getFileForSaving('edit_brief_reviewed.json', { types: ['json'] });
    if (!file) return;
    await file.write(JSON.stringify(output, null, 2), { format: uxpFormats.utf8 });
    appLog('Saved: ' + file.name);
    BUS.emit('brief-saved');
  } catch (e) {
    appLog('Save error: ' + e.message, 'error');
  }
}

async function pickSourceFolder() {
  if (!uxpFs) return;
  try {
    var folder = await uxpFs.getFolder();
    if (!folder) return;
    APP.sourceFolderEntry = folder;
    try { APP.sourceFolderToken = await uxpFs.createPersistentToken(folder); }
    catch (ex) { /* ok */ }
    appLog('Source folder: ' + folder.name);
    BUS.emit('source-folder-changed');
    return folder;
  } catch (e) {
    appLog('Folder error: ' + e.message, 'error');
  }
}

/* Expose as globals */
var IO = {
  parseTimecode: parseTimecode,
  formatTimecode: formatTimecode,
  formatDuration: formatDuration,
  normalize: normalize,
  buildBlocks: buildBlocks,
  pickAndLoadBrief: pickAndLoadBrief,
  reloadBrief: reloadBrief,
  loadFromEntry: loadFromEntry,
  saveReviewed: saveReviewed,
  pickSourceFolder: pickSourceFolder,
};

console.log('[YTAI] project-io.js loaded OK. IO =', typeof IO, Object.keys(IO));
