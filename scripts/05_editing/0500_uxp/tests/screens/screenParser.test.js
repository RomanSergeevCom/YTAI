const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const {
  parseScreens,
  formatMarkerComment,
  formatSrtContent,
  parseTimecode,
  truncate,
  MAX_TITLE,
  MAX_SUBTITLE,
  MAX_BODY,
  MAX_MARKER_COMMENT
} = require('../../src/screens/screenParser');

// --- Helper: create mock segments ---
function makeSegments() {
  return [
    { id: 'seg_001', sourceFile: 'RYA-FX3-0099.MP4', inSec: 0, outSec: 10, duration: 10, tcIn: '00:00.0', use: true, block: 1 },
    { id: 'seg_002', sourceFile: 'RYA-FX3-0099.MP4', inSec: 10, outSec: 25, duration: 15, tcIn: '00:10.0', use: true, block: 1 },
    { id: 'seg_003', sourceFile: 'RYA-FX3-0100.MP4', inSec: 5, outSec: 20, duration: 15, tcIn: '00:05.0', use: true, block: 2 },
    { id: 'seg_004', sourceFile: 'RYA-FX3-0100.MP4', inSec: 30, outSec: 45, duration: 15, tcIn: '00:30.0', use: false, block: 99 }
  ];
}

// --- parseTimecode ---
describe('screenParser parseTimecode', () => {
  it('parses MM:SS.s format', () => {
    assert.equal(parseTimecode('01:30.5'), 90.5);
  });
  it('parses HH:MM:SS.s format', () => {
    assert.equal(parseTimecode('01:02:03.5'), 3723.5);
  });
  it('returns number as-is', () => {
    assert.equal(parseTimecode(42.5), 42.5);
  });
  it('returns 0 for empty/null', () => {
    assert.equal(parseTimecode(null), 0);
    assert.equal(parseTimecode(''), 0);
  });
});

// --- truncate ---
describe('screenParser truncate', () => {
  it('does not truncate short strings', () => {
    assert.equal(truncate('hello', 100), 'hello');
  });
  it('truncates long strings with ellipsis', () => {
    var result = truncate('a'.repeat(110), 100);
    assert.equal(result.length, 100);
    assert.ok(result.endsWith('\u2026'));
  });
  it('returns empty string for falsy input', () => {
    assert.equal(truncate(null, 100), '');
    assert.equal(truncate('', 100), '');
  });
});

// --- parseScreens ---
describe('parseScreens', () => {
  it('parses valid screens correctly', () => {
    var segs = makeSegments();
    var raw = [
      { screen_id: 'scr_001', type: 'full_overlay', segment_id: 'seg_001', tc_in: '00:00.0', title: 'Introduction' },
      { screen_id: 'scr_002', type: 'lower_third', segment_id: 'seg_002', tc_in: '00:12.0', title: 'John Doe', subtitle: 'CEO' }
    ];
    var result = parseScreens(raw, segs);
    assert.equal(result.screens.length, 2);
    assert.equal(result.warnings.length, 0);
    assert.equal(result.screens[0].id, 'scr_001');
    assert.equal(result.screens[0].type, 'full_overlay');
    assert.equal(result.screens[0].segmentId, 'seg_001');
    assert.equal(result.screens[0].title, 'Introduction');
    assert.equal(result.screens[1].subtitle, 'CEO');
  });

  it('skips screens with invalid type', () => {
    var segs = makeSegments();
    var raw = [
      { screen_id: 'scr_001', type: 'invalid_type', segment_id: 'seg_001', title: 'Test' }
    ];
    var result = parseScreens(raw, segs);
    assert.equal(result.screens.length, 0);
    assert.equal(result.warnings.length, 1);
    assert.ok(result.warnings[0].includes('invalid type'));
  });

  it('skips screens with missing segment_id', () => {
    var segs = makeSegments();
    var raw = [
      { screen_id: 'scr_001', type: 'full_overlay', segment_id: 'seg_999', title: 'Missing' }
    ];
    var result = parseScreens(raw, segs);
    assert.equal(result.screens.length, 0);
    assert.ok(result.warnings[0].includes('not found'));
  });

  it('skips screens with missing required fields', () => {
    var segs = makeSegments();
    var raw = [
      { screen_id: 'scr_001', type: 'full_overlay', segment_id: 'seg_001' }
      // 'full_overlay' requires title — title is missing
    ];
    var result = parseScreens(raw, segs);
    assert.equal(result.screens.length, 0);
    assert.ok(result.warnings[0].includes('missing required fields'));
    assert.ok(result.warnings[0].includes('title'));
  });

  it('truncates long title/subtitle/body', () => {
    var segs = makeSegments();
    var longTitle = 'T'.repeat(200);
    var longBody = 'B'.repeat(600);
    var raw = [
      { screen_id: 'scr_001', type: 'chapter_bar', segment_id: 'seg_001', title: longTitle, body: longBody }
    ];
    var result = parseScreens(raw, segs);
    assert.equal(result.screens.length, 1);
    assert.equal(result.screens[0].title.length, MAX_TITLE);
    assert.equal(result.screens[0].body.length, MAX_BODY);
  });

  it('returns empty for null/undefined input', () => {
    var result = parseScreens(null, []);
    assert.equal(result.screens.length, 0);
    assert.ok(result.warnings[0].includes('not an array'));
  });

  it('returns empty for empty array', () => {
    var result = parseScreens([], makeSegments());
    assert.equal(result.screens.length, 0);
    assert.equal(result.warnings.length, 0);
  });

  it('auto-generates screen_id if missing', () => {
    var segs = makeSegments();
    var raw = [
      { type: 'full_overlay', segment_id: 'seg_001', title: 'No ID' }
    ];
    var result = parseScreens(raw, segs);
    assert.equal(result.screens.length, 1);
    assert.equal(result.screens[0].id, 'scr_001');
  });

  it('resolves tc_in from segment if not provided', () => {
    var segs = makeSegments();
    var raw = [
      { screen_id: 'scr_001', type: 'lower_third', segment_id: 'seg_003', title: 'Name' }
    ];
    var result = parseScreens(raw, segs);
    assert.equal(result.screens[0].tcIn, '00:05.0');
    assert.equal(result.screens[0].tcInSec, 5);
  });

  it('normalizes type to lowercase', () => {
    var segs = makeSegments();
    var raw = [
      { screen_id: 'scr_001', type: 'Full_Overlay', segment_id: 'seg_001', title: 'Hello' }
    ];
    var result = parseScreens(raw, segs);
    assert.equal(result.screens[0].type, 'full_overlay');
  });

  it('parses prompt field', () => {
    var segs = makeSegments();
    var raw = [
      { screen_id: 'scr_001', type: 'full_overlay', segment_id: 'seg_001', title: 'Skyline',
        prompt: 'Aerial view of Dubai Marina at sunset, cinematic 4K' }
    ];
    var result = parseScreens(raw, segs);
    assert.equal(result.screens[0].prompt, 'Aerial view of Dubai Marina at sunset, cinematic 4K');
  });

  it('defaults prompt to empty string when absent', () => {
    var segs = makeSegments();
    var raw = [
      { screen_id: 'scr_001', type: 'full_overlay', segment_id: 'seg_001', title: 'No Prompt' }
    ];
    var result = parseScreens(raw, segs);
    assert.equal(result.screens[0].prompt, '');
  });

  it('warns when tc_in is outside segment range', () => {
    var segs = makeSegments();
    // seg_001 has inSec=0, duration=10 → valid range [0, 10]
    var raw = [
      { screen_id: 'scr_001', type: 'full_overlay', segment_id: 'seg_001', tc_in: '00:15.0', title: 'Too Late' }
    ];
    var result = parseScreens(raw, segs);
    // Screen should still be parsed but with a warning
    assert.equal(result.screens.length, 1);
    var tcWarnings = result.warnings.filter(function(w) { return w.includes('outside segment range'); });
    assert.equal(tcWarnings.length, 1, 'Should warn about tc_in outside range');
  });

  it('does not warn when tc_in is within segment range', () => {
    var segs = makeSegments();
    var raw = [
      { screen_id: 'scr_001', type: 'full_overlay', segment_id: 'seg_001', tc_in: '00:05.0', title: 'Mid' }
    ];
    var result = parseScreens(raw, segs);
    assert.equal(result.screens.length, 1);
    var tcWarnings = result.warnings.filter(function(w) { return w.includes('outside segment range'); });
    assert.equal(tcWarnings.length, 0, 'Should not warn for valid tc_in');
  });

  it('can reference use=FALSE segments', () => {
    var segs = makeSegments();
    var raw = [
      { screen_id: 'scr_001', type: 'full_overlay', segment_id: 'seg_004', title: 'From cut segment' }
    ];
    var result = parseScreens(raw, segs);
    assert.equal(result.screens.length, 1);
    assert.equal(result.screens[0].segmentId, 'seg_004');
  });
});

// --- formatMarkerComment ---
describe('formatMarkerComment', () => {
  it('formats type + title', () => {
    var screen = { type: 'full_overlay', title: 'Introduction', subtitle: '', body: '' };
    var result = formatMarkerComment(screen);
    assert.ok(result.includes('[FULL OVERLAY]'));
    assert.ok(result.includes('Introduction'));
  });

  it('includes subtitle and body when present', () => {
    var screen = { type: 'lower_third', title: 'John', subtitle: 'CEO', body: '' };
    var result = formatMarkerComment(screen);
    assert.ok(result.includes('John'));
    assert.ok(result.includes('CEO'));
  });

  it('replaces newlines in body with slashes', () => {
    var screen = { type: 'chapter_bar', title: 'Items', subtitle: '', body: 'Line1\nLine2\nLine3' };
    var result = formatMarkerComment(screen);
    assert.ok(result.includes('Line1 / Line2 / Line3'));
  });

  it('truncates to MAX_MARKER_COMMENT chars', () => {
    var screen = { type: 'chapter_bar', title: 'T'.repeat(100), subtitle: 'S'.repeat(50), body: 'B'.repeat(100) };
    var result = formatMarkerComment(screen);
    assert.ok(result.length <= MAX_MARKER_COMMENT);
  });

  it('includes prompt with [PROMPT] prefix', () => {
    var screen = { type: 'full_overlay', title: 'Skyline', subtitle: '', body: '',
      prompt: 'Aerial view of Dubai at sunset' };
    var result = formatMarkerComment(screen);
    assert.ok(result.includes('[PROMPT] Aerial view of Dubai at sunset'));
  });

  it('omits prompt when empty', () => {
    var screen = { type: 'full_overlay', title: 'Skyline', subtitle: '', body: '', prompt: '' };
    var result = formatMarkerComment(screen);
    assert.ok(!result.includes('[PROMPT]'));
  });

  it('returns empty string for null', () => {
    assert.equal(formatMarkerComment(null), '');
  });
});

// --- formatSrtContent ---
describe('formatSrtContent', () => {
  it('formats multi-line SRT text', () => {
    var screen = { type: 'chapter_bar', title: 'Key Numbers', subtitle: '', body: 'Growth 40%\n150+ clients' };
    var result = formatSrtContent(screen);
    assert.ok(result.includes('[CHAPTER BAR]'));
    assert.ok(result.includes('Key Numbers'));
    assert.ok(result.includes('Growth 40% | 150+ clients'));
  });

  it('returns empty string for null', () => {
    assert.equal(formatSrtContent(null), '');
  });
});
