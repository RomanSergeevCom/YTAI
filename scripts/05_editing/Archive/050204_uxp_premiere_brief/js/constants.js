/* constants.js — Color map, label indices, marker types, helpers */

var LABEL_COLOR_INDEX = {
  Green: 13,
  Blue: 9,
  Cyan: 2,
  Yellow: 15,
  Red: 16,
  Magenta: 11,
  Orange: 7,
  Purple: 8
};

var VALID_COLORS = Object.keys(LABEL_COLOR_INDEX);

var MARKER_TYPE_CHAPTER = 'com.adobe.premiereMarkers.chapter';
var MARKER_TYPE_COMMENT = 'com.adobe.premiereMarkers.comment';

var TICKS_PER_SECOND = 254016000000;

// Global app state
var APP = {
  brief: null,
  segments: [],
  blocks: [],
  projectName: '',
  projectSettings: {},
  transcriptionDir: '',
  briefFileEntry: null,
  briefFileToken: null,
  sourceFolderEntry: null,
  sourceFolderPath: '',
  clipMap: {},
  buildStatus: 'idle'
};

// Robust TickTime → seconds (handles API version differences)
function tickSec(tt) {
  if (!tt) return -1;
  if (typeof tt === 'number') return tt;
  var s = (tt.seconds != null) ? tt.seconds : tt.secs;
  if (typeof s === 'number' && !isNaN(s)) return s;
  var t = tt.ticks;
  if (typeof t === 'number') return t / TICKS_PER_SECOND;
  if (typeof t === 'bigint') return Number(t) / TICKS_PER_SECOND;
  return parseFloat(String(tt)) || -1;
}

// Format seconds to M:SS display
function fmtTime(sec) {
  if (!sec || sec < 0) return '0:00';
  var m = Math.floor(sec / 60);
  var s = Math.floor(sec % 60);
  return m + ':' + (s < 10 ? '0' : '') + s;
}

// Log to UI + buffer for file
function appLog(msg, level) {
  level = level || 'info';

  // Buffer for file logging (file-logger.js)
  if (typeof bufferLog === 'function') {
    bufferLog(msg, level);
  }

  var log = document.getElementById('log');
  if (!log) { console.log('[YTAI] ' + msg); return; }
  var line = document.createElement('div');
  line.className = 'log-line ' + level;
  line.textContent = msg;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
  console.log('[YTAI][' + level + '] ' + msg);
}
