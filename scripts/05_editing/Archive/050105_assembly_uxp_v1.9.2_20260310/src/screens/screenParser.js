/**
 * screenParser.js — Parse and validate screens[] from edit_brief.json.
 *
 * Screens describe Production Cues (screen types + text content) for the
 * motion designer / editor. They are placed on V2 of the Assembly sequence.
 *
 * Each screen references a segment by segment_id and has a type + text fields.
 * This module validates the raw screens array and resolves segment references.
 *
 * Depends on: constants.js (SCREEN_TYPES, SCREEN_REQUIRED_FIELDS)
 * Does NOT import any other YTAI modules.
 */

const { SCREEN_TYPES, SCREEN_REQUIRED_FIELDS } = require('../shared/constants');

// Max field lengths (match output_format.md limits)
var MAX_TITLE = 100;
var MAX_SUBTITLE = 100;
var MAX_BODY = 500;
var MAX_MARKER_COMMENT = 200;

/**
 * Parse timecode string "MM:SS.s" or "HH:MM:SS.s" → seconds.
 * Same logic as briefParser.parseTimecode (duplicated to avoid circular dependency).
 */
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

/**
 * Truncate string to maxLen, adding '…' if truncated.
 */
function truncate(str, maxLen) {
  if (!str) return '';
  var s = String(str);
  if (s.length <= maxLen) return s;
  return s.substring(0, maxLen - 1) + '\u2026';
}

/**
 * Parse and validate screens[] from brief.
 *
 * @param {Array} rawScreens - Raw screens array from edit_brief.json
 * @param {Array} segments - Parsed segments from briefParser (all segments, for segment_id lookup)
 * @param {Object} [logger] - Logger instance (optional)
 * @returns {{ screens: Array, warnings: string[] }}
 */
function parseScreens(rawScreens, segments, logger) {
  var warnings = [];
  var screens = [];

  if (!rawScreens || !Array.isArray(rawScreens)) {
    return { screens: [], warnings: ['screens is not an array'] };
  }

  // Build segment lookup: { seg_001: segmentObject, ... }
  var segMap = {};
  if (segments && Array.isArray(segments)) {
    for (var i = 0; i < segments.length; i++) {
      segMap[segments[i].id] = segments[i];
    }
  }

  for (var si = 0; si < rawScreens.length; si++) {
    var raw = rawScreens[si];
    if (!raw || typeof raw !== 'object') {
      warnings.push('screens[' + si + ']: not an object, skipped');
      continue;
    }

    var screenId = raw.screen_id || ('scr_' + String(si + 1).padStart(3, '0'));

    // Validate type
    var type = String(raw.type || '').toLowerCase().trim();
    if (SCREEN_TYPES.indexOf(type) === -1) {
      warnings.push(screenId + ': invalid type "' + raw.type + '", skipped');
      continue;
    }

    // Validate segment_id reference
    var segmentId = raw.segment_id || '';
    var linkedSegment = segMap[segmentId] || null;
    if (!linkedSegment) {
      warnings.push(screenId + ': segment_id "' + segmentId + '" not found, skipped');
      continue;
    }

    // Validate required fields for this type
    var requiredFields = SCREEN_REQUIRED_FIELDS[type] || ['title'];
    var missingFields = [];
    for (var fi = 0; fi < requiredFields.length; fi++) {
      var field = requiredFields[fi];
      if (!raw[field] || String(raw[field]).trim() === '') {
        missingFields.push(field);
      }
    }
    if (missingFields.length > 0) {
      warnings.push(screenId + ': missing required fields [' + missingFields.join(', ') + '] for type "' + type + '", skipped');
      continue;
    }

    // Parse and truncate fields
    var screen = {
      id: screenId,
      type: type,
      segmentId: segmentId,
      segment: linkedSegment,
      tcIn: raw.tc_in || linkedSegment.tcIn || '00:00.0',
      tcInSec: parseTimecode(raw.tc_in || linkedSegment.tcIn || '00:00.0'),
      title: truncate(String(raw.title || '').trim(), MAX_TITLE),
      subtitle: truncate(String(raw.subtitle || '').trim(), MAX_SUBTITLE),
      body: truncate(String(raw.body || '').trim(), MAX_BODY)
    };

    screens.push(screen);

    if (logger) {
      logger.debug('  ' + screenId + ': type=' + type + ', seg=' + segmentId +
        ', tc=' + screen.tcIn + ', title="' + screen.title.substring(0, 30) + '"');
    }
  }

  if (logger) {
    logger.info('Parsed ' + screens.length + ' screens (' + warnings.length + ' warnings)');
  }

  return { screens: screens, warnings: warnings };
}

/**
 * Format screen content as marker comment (max 200 chars).
 * Priority: type > title > subtitle > body.
 *
 * @param {Object} screen - Parsed screen object
 * @returns {string} Formatted marker comment
 */
function formatMarkerComment(screen) {
  if (!screen) return '';

  var parts = [];
  var typeLabel = '[' + screen.type.toUpperCase().replace(/_/g, ' ') + ']';
  parts.push(typeLabel);

  if (screen.title) parts.push(screen.title);
  if (screen.subtitle) parts.push(screen.subtitle);
  if (screen.body) {
    // Replace newlines with ' / ' for single-line marker comment
    parts.push(screen.body.replace(/\n/g, ' / '));
  }

  var result = parts.join(' | ');
  if (result.length > MAX_MARKER_COMMENT) {
    result = result.substring(0, MAX_MARKER_COMMENT - 1) + '\u2026';
  }
  return result;
}

/**
 * Format screen content for SRT subtitle entry (full content, no truncation).
 *
 * @param {Object} screen - Parsed screen object
 * @returns {string} Formatted SRT text
 */
function formatSrtContent(screen) {
  if (!screen) return '';

  var lines = [];
  lines.push('[' + screen.type.toUpperCase().replace(/_/g, ' ') + ']');
  if (screen.title) lines.push(screen.title);
  if (screen.subtitle) lines.push(screen.subtitle);
  if (screen.body) lines.push(screen.body.replace(/\n/g, ' | '));
  return lines.join('\n');
}

module.exports = {
  parseScreens,
  formatMarkerComment,
  formatSrtContent,
  parseTimecode,
  truncate,
  MAX_TITLE,
  MAX_SUBTITLE,
  MAX_BODY,
  MAX_MARKER_COMMENT
};
