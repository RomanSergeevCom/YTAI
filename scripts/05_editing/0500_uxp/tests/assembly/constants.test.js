const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const {
  LABEL_COLOR_INDEX,
  MARKER_COLOR_INDEX,
  VALID_COLORS,
  BLOCK_VALID_COLORS,
  MARKER_TYPE_CHAPTER,
  MARKER_TYPE_COMMENT,
  TICKS_PER_SECOND,
  REVIEW_COLOR_MAP
} = require('../../src/shared/constants');
const ppro = require('../mocks/premierepro');

// --- LABEL_COLOR_INDEX (clip colors) ---

describe('LABEL_COLOR_INDEX', () => {
  it('maps Green to 13 (confirmed in real Premiere)', () => {
    assert.equal(LABEL_COLOR_INDEX.Green, 13);
  });

  it('maps Blue to 9 (confirmed in real Premiere)', () => {
    assert.equal(LABEL_COLOR_INDEX.Blue, 9);
  });

  it('maps Orange to 7 (confirmed in real Premiere, MANGO)', () => {
    assert.equal(LABEL_COLOR_INDEX.Orange, 7);
  });

  it('has all 8 colors defined', () => {
    const expected = ['Green', 'Blue', 'Orange', 'Cyan', 'Yellow', 'Red', 'Magenta', 'Purple'];
    for (const color of expected) {
      assert.ok(LABEL_COLOR_INDEX[color] !== undefined, 'Missing color: ' + color);
      assert.equal(typeof LABEL_COLOR_INDEX[color], 'number');
    }
  });

  it('all indices are in range 0-15 (Premiere has 16 label colors)', () => {
    for (const [name, idx] of Object.entries(LABEL_COLOR_INDEX)) {
      assert.ok(idx >= 0 && idx <= 15, name + ' index ' + idx + ' out of range');
    }
  });

  it('confirmed indices match mock ppro.Constants.ProjectItemColorLabel', () => {
    const labels = ppro.Constants.ProjectItemColorLabel;
    assert.equal(LABEL_COLOR_INDEX.Green, labels.GREEN);
    assert.equal(LABEL_COLOR_INDEX.Blue, labels.BLUE);
    assert.equal(LABEL_COLOR_INDEX.Orange, labels.MANGO);
  });

  it('all indices are unique (no duplicate assignments)', () => {
    const values = Object.values(LABEL_COLOR_INDEX);
    const unique = new Set(values);
    assert.equal(values.length, unique.size, 'Duplicate color indices found');
  });
});

// --- MARKER_COLOR_INDEX ---

describe('MARKER_COLOR_INDEX', () => {
  it('maps Green to 0', () => {
    assert.equal(MARKER_COLOR_INDEX.Green, 0);
  });

  it('maps Red to 1', () => {
    assert.equal(MARKER_COLOR_INDEX.Red, 1);
  });

  it('maps Blue to 6', () => {
    assert.equal(MARKER_COLOR_INDEX.Blue, 6);
  });

  it('maps Orange to 3', () => {
    assert.equal(MARKER_COLOR_INDEX.Orange, 3);
  });

  it('maps Purple to 2 (same as Magenta — no separate Purple marker in Premiere)', () => {
    assert.equal(MARKER_COLOR_INDEX.Purple, 2);
    assert.equal(MARKER_COLOR_INDEX.Purple, MARKER_COLOR_INDEX.Magenta);
  });

  it('does NOT have White (index 5 missing in real Premiere)', () => {
    assert.equal(MARKER_COLOR_INDEX.White, undefined);
  });

  it('all indices are in range 0-7', () => {
    for (const [name, idx] of Object.entries(MARKER_COLOR_INDEX)) {
      assert.ok(idx >= 0 && idx <= 7, name + ' index ' + idx + ' out of range');
    }
  });

  it('matches mock ppro.Constants.MarkerColor', () => {
    const mc = ppro.Constants.MarkerColor;
    assert.equal(MARKER_COLOR_INDEX.Green, mc.GREEN);
    assert.equal(MARKER_COLOR_INDEX.Red, mc.RED);
    assert.equal(MARKER_COLOR_INDEX.Orange, mc.ORANGE);
    assert.equal(MARKER_COLOR_INDEX.Blue, mc.BLUE);
    assert.equal(MARKER_COLOR_INDEX.Cyan, mc.CYAN);
  });
});

// --- VALID_COLORS ---

describe('VALID_COLORS', () => {
  it('is derived from LABEL_COLOR_INDEX keys', () => {
    assert.deepEqual(VALID_COLORS, Object.keys(LABEL_COLOR_INDEX));
  });

  it('includes Green, Blue, Orange (used in assembly)', () => {
    assert.ok(VALID_COLORS.includes('Green'));
    assert.ok(VALID_COLORS.includes('Blue'));
    assert.ok(VALID_COLORS.includes('Orange'));
  });
});

// --- BLOCK_VALID_COLORS ---

describe('BLOCK_VALID_COLORS', () => {
  it('does NOT include Orange (reserved for Screen Cues)', () => {
    assert.ok(!BLOCK_VALID_COLORS.includes('Orange'));
  });

  it('includes all other Assembly colors', () => {
    for (const color of ['Green', 'Blue', 'Cyan', 'Yellow', 'Red', 'Magenta', 'Purple']) {
      assert.ok(BLOCK_VALID_COLORS.includes(color), 'Missing: ' + color);
    }
  });

  it('all entries exist in MARKER_COLOR_INDEX', () => {
    for (const color of BLOCK_VALID_COLORS) {
      assert.ok(MARKER_COLOR_INDEX[color] !== undefined, color + ' not in MARKER_COLOR_INDEX');
    }
  });
});

// --- Marker type URI constants ---

describe('Marker type URI constants', () => {
  it('MARKER_TYPE_CHAPTER is Adobe URI (for creation)', () => {
    assert.equal(MARKER_TYPE_CHAPTER, 'com.adobe.premiereMarkers.chapter');
  });

  it('MARKER_TYPE_COMMENT is Adobe URI (for creation)', () => {
    assert.equal(MARKER_TYPE_COMMENT, 'com.adobe.premiereMarkers.comment');
  });

  it('ppro.Marker.MARKER_TYPE_CHAPTER is display name, NOT same as our constant', () => {
    // ppro.Marker values are display names ("Chapter", "Comment")
    // Our constants are Adobe URIs — they are DIFFERENT and MUST be different
    assert.equal(ppro.Marker.MARKER_TYPE_CHAPTER, 'Chapter');
    assert.notEqual(ppro.Marker.MARKER_TYPE_CHAPTER, MARKER_TYPE_CHAPTER);
  });

  it('ppro.Marker.MARKER_TYPE_COMMENT is display name, NOT same as our constant', () => {
    assert.equal(ppro.Marker.MARKER_TYPE_COMMENT, 'Comment');
    assert.notEqual(ppro.Marker.MARKER_TYPE_COMMENT, MARKER_TYPE_COMMENT);
  });
});

// --- REVIEW_COLOR_MAP ---

describe('REVIEW_COLOR_MAP', () => {
  it('has three categories: cut, alt, skip', () => {
    assert.ok(REVIEW_COLOR_MAP.cut);
    assert.ok(REVIEW_COLOR_MAP.alt);
    assert.ok(REVIEW_COLOR_MAP.skip);
    assert.equal(Object.keys(REVIEW_COLOR_MAP).length, 3);
  });

  it('cut uses Red label and Red marker', () => {
    assert.equal(REVIEW_COLOR_MAP.cut.label, 'Red');
    assert.equal(REVIEW_COLOR_MAP.cut.labelIdx, LABEL_COLOR_INDEX.Red);
    assert.equal(REVIEW_COLOR_MAP.cut.markerIdx, MARKER_COLOR_INDEX.Red);
  });

  it('alt uses Yellow label and Yellow marker', () => {
    assert.equal(REVIEW_COLOR_MAP.alt.label, 'Yellow');
    assert.equal(REVIEW_COLOR_MAP.alt.labelIdx, LABEL_COLOR_INDEX.Yellow);
    assert.equal(REVIEW_COLOR_MAP.alt.markerIdx, MARKER_COLOR_INDEX.Yellow);
  });

  it('skip uses Purple label and Magenta marker', () => {
    assert.equal(REVIEW_COLOR_MAP.skip.label, 'Purple');
    assert.equal(REVIEW_COLOR_MAP.skip.labelIdx, LABEL_COLOR_INDEX.Purple);
    assert.equal(REVIEW_COLOR_MAP.skip.markerIdx, MARKER_COLOR_INDEX.Magenta);
  });
});

// --- TICKS_PER_SECOND ---

describe('TICKS_PER_SECOND', () => {
  it('equals 254016000000 (Premiere standard)', () => {
    assert.equal(TICKS_PER_SECOND, 254016000000);
  });
});
