/**
 * Utility functions for timecode parsing, track mapping, and color label conversion.
 */

/**
 * Parse a timecode string into seconds.
 * Supports formats: "MM:SS.s", "HH:MM:SS.s"
 * @param {string} tc - Timecode string
 * @returns {number} Seconds
 */
function parseTimecode(tc) {
  if (!tc || typeof tc !== 'string') {
    throw new Error('Invalid timecode: empty or not a string');
  }

  const parts = tc.split(':');
  let seconds = 0;

  if (parts.length === 2) {
    // MM:SS.s
    const mm = parseInt(parts[0], 10);
    const ss = parseFloat(parts[1]);
    if (isNaN(mm) || isNaN(ss)) throw new Error(`Invalid timecode: ${tc}`);
    seconds = mm * 60 + ss;
  } else if (parts.length === 3) {
    // HH:MM:SS.s
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
 * Convert seconds back to timecode string (MM:SS.s)
 * @param {number} seconds
 * @returns {string}
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
 * Convert track name to 0-based track index for Premiere Pro API.
 * "V1" -> 0, "V2" -> 1, "A1" -> 0, "A2" -> 1
 * @param {string} track - Track name (V1, V2, A1, A2, etc.)
 * @returns {number}
 */
function trackToIndex(track) {
  if (!track || typeof track !== 'string') {
    throw new Error('Invalid track: empty or not a string');
  }

  const match = track.match(/^([VA])(\d+)$/i);
  if (!match) {
    throw new Error(`Invalid track format: ${track}`);
  }

  const num = parseInt(match[2], 10);
  if (num < 1) throw new Error(`Invalid track number: ${track}`);

  return num - 1;
}

/**
 * Map brief color name to Premiere Pro ProjectItemColorLabel index.
 * @param {string} color - Color name from brief (Green, Blue, Orange, Red, etc.)
 * @returns {number} Color label index, or -1 if unknown
 */
function colorToLabel(color) {
  if (!color) return -1;

  const map = {
    'violet': 0,
    'blue': 1,
    'green': 2,
    'yellow': 3,
    'cerulean': 4,
    'brown': 5,
    'forest': 6,
    'iris': 7,
    'lavender': 8,
    'magenta': 9,
    'mango': 10,
    'orange': 10, // map Orange to Mango (closest match)
    'purple': 11,
    'rose': 12,
    'red': 12, // map Red to Rose (closest match)
    'tan': 13,
    'teal': 14
  };

  const result = map[color.toLowerCase()];
  return result !== undefined ? result : -1;
}

module.exports = { parseTimecode, secondsToTimecode, trackToIndex, colorToLabel };
