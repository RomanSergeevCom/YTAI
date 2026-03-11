/**
 * Shared utility functions for YTAI Assembly UXP plugin.
 * Used by both INGEST and ASSEMBLY modules.
 */

const { TICKS_PER_SECOND, LABEL_COLOR_INDEX } = require('./constants');

/**
 * Parse a timecode string into seconds.
 * Supports formats: "MM:SS.s", "HH:MM:SS.s"
 */
function parseTimecode(tc) {
  if (!tc || typeof tc !== 'string') {
    throw new Error('Invalid timecode: empty or not a string');
  }

  const parts = tc.split(':');
  let seconds = 0;

  if (parts.length === 2) {
    const mm = parseInt(parts[0], 10);
    const ss = parseFloat(parts[1]);
    if (isNaN(mm) || isNaN(ss)) throw new Error(`Invalid timecode: ${tc}`);
    seconds = mm * 60 + ss;
  } else if (parts.length === 3) {
    const hh = parseInt(parts[0], 10);
    const mm = parseInt(parts[1], 10);
    const ss = parseFloat(parts[2]);
    if (isNaN(hh) || isNaN(mm) || isNaN(ss)) throw new Error(`Invalid timecode: ${tc}`);
    seconds = hh * 3600 + mm * 60 + ss;
  } else {
    throw new Error(`Invalid timecode format: ${tc}`);
  }

  return Math.round(seconds * 10) / 10;
}

/**
 * Convert seconds to timecode string (MM:SS.s)
 */
function secondsToTimecode(seconds) {
  const mm = Math.floor(seconds / 60);
  const ss = Math.round((seconds - mm * 60) * 10) / 10;
  const mmStr = String(mm).padStart(2, '0');
  const ssWhole = Math.floor(ss);
  const ssFrac = Math.round((ss - ssWhole) * 10);
  const ssStr = String(ssWhole).padStart(2, '0') + '.' + ssFrac;
  return `${mmStr}:${ssStr}`;
}

/**
 * Convert track name to 0-based index. "V1"->0, "V2"->1, "A1"->0, "A2"->1
 */
function trackToIndex(track) {
  if (!track || typeof track !== 'string') {
    throw new Error('Invalid track: empty or not a string');
  }
  const match = track.match(/^([VA])(\d+)$/i);
  if (!match) throw new Error(`Invalid track format: ${track}`);
  const num = parseInt(match[2], 10);
  if (num < 1) throw new Error(`Invalid track number: ${track}`);
  return num - 1;
}

/**
 * Map brief color name to Premiere Pro label index.
 */
function colorToLabel(color) {
  if (!color) return -1;
  const idx = LABEL_COLOR_INDEX[color];
  return idx !== undefined ? idx : -1;
}

/**
 * Robust TickTime to seconds (handles API version differences).
 */
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

/**
 * Format seconds to M:SS display.
 */
function fmtTime(sec) {
  if (!sec || sec < 0) return '0:00';
  var m = Math.floor(sec / 60);
  var s = Math.floor(sec % 60);
  return m + ':' + (s < 10 ? '0' : '') + s;
}

/**
 * Escape HTML for safe log display.
 */
function escapeHtml(text) {
  if (typeof document !== 'undefined') {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
  return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

module.exports = {
  parseTimecode,
  secondsToTimecode,
  trackToIndex,
  colorToLabel,
  tickSec,
  fmtTime,
  escapeHtml
};
