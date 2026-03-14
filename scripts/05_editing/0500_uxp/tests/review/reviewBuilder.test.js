const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const {
  sortReviewSegments,
  getReviewCategory,
  computeComplement,
  computeClipOffsets,
  subtractBriefFromRange,
  createGapSegment
} = require('../../src/review/reviewBuilder');

// --- getReviewCategory ---

describe('getReviewCategory', () => {
  it('returns "cut" for block=99', () => {
    assert.equal(getReviewCategory({ block: 99, priority: 1, use: false }), 'cut');
  });

  it('returns "alt" for priority=2', () => {
    assert.equal(getReviewCategory({ block: 1, priority: 2, use: false }), 'alt');
  });

  it('returns "alt" for string priority "2"', () => {
    assert.equal(getReviewCategory({ block: 1, priority: '2', use: false }), 'alt');
  });

  it('returns "skip" for use=FALSE with no special conditions', () => {
    assert.equal(getReviewCategory({ block: 1, priority: 1, use: false }), 'skip');
    assert.equal(getReviewCategory({ block: 3, priority: 9, use: false }), 'skip');
  });

  it('block=99 takes priority over priority=2', () => {
    assert.equal(getReviewCategory({ block: 99, priority: 2, use: false }), 'cut');
  });

  it('returns "skip" for gap segments (block=0, priority=1)', () => {
    assert.equal(getReviewCategory({ block: 0, priority: 1, use: false }), 'skip');
  });
});

// --- computeComplement ---

describe('computeComplement', () => {
  it('returns full clip when no assembly ranges', () => {
    const result = computeComplement([], 100, 0.3);
    assert.deepEqual(result, [{ in: 0, out: 100 }]);
  });

  it('returns two ranges when one assembly range in middle', () => {
    const result = computeComplement([{ in: 30, out: 70 }], 100, 0.3);
    assert.equal(result.length, 2);
    assert.deepEqual(result[0], { in: 0, out: 30 });
    assert.deepEqual(result[1], { in: 70, out: 100 });
  });

  it('returns gaps between multiple assembly ranges', () => {
    const result = computeComplement([
      { in: 10, out: 30 },
      { in: 50, out: 80 }
    ], 100, 0.3);
    assert.equal(result.length, 3);
    assert.deepEqual(result[0], { in: 0, out: 10 });
    assert.deepEqual(result[1], { in: 30, out: 50 });
    assert.deepEqual(result[2], { in: 80, out: 100 });
  });

  it('returns empty when assembly covers entire clip', () => {
    const result = computeComplement([{ in: 0, out: 100 }], 100, 0.3);
    assert.equal(result.length, 0);
  });

  it('skips gaps smaller than minGap', () => {
    const result = computeComplement([
      { in: 0, out: 49.9 },
      { in: 50, out: 100 }
    ], 100, 0.3);
    // Gap is 0.1s < 0.3s → skipped
    assert.equal(result.length, 0);
  });

  it('includes gaps at or above minGap threshold', () => {
    const result = computeComplement([
      { in: 0, out: 49 },
      { in: 50, out: 100 }
    ], 100, 0.3);
    // Gap is 1.0s > minGap → included
    assert.equal(result.length, 1);
    assert.deepEqual(result[0], { in: 49, out: 50 });
  });

  it('handles assembly starting after clip start', () => {
    const result = computeComplement([{ in: 30, out: 100 }], 100, 0.3);
    assert.equal(result.length, 1);
    assert.deepEqual(result[0], { in: 0, out: 30 });
  });

  it('handles assembly ending before clip end', () => {
    const result = computeComplement([{ in: 0, out: 70 }], 100, 0.3);
    assert.equal(result.length, 1);
    assert.deepEqual(result[0], { in: 70, out: 100 });
  });
});

// --- subtractBriefFromRange ---

describe('subtractBriefFromRange', () => {
  it('returns full range when no brief segments', () => {
    const result = subtractBriefFromRange({ in: 0, out: 100 }, []);
    assert.deepEqual(result, [{ in: 0, out: 100 }]);
  });

  it('returns gaps around a brief segment', () => {
    const result = subtractBriefFromRange(
      { in: 0, out: 100 },
      [{ inSec: 30, outSec: 50 }]
    );
    assert.equal(result.length, 2);
    assert.deepEqual(result[0], { in: 0, out: 30 });
    assert.deepEqual(result[1], { in: 50, out: 100 });
  });

  it('returns empty when brief covers entire range', () => {
    const result = subtractBriefFromRange(
      { in: 10, out: 50 },
      [{ inSec: 10, outSec: 50 }]
    );
    assert.equal(result.length, 0);
  });

  it('ignores brief segments outside the range', () => {
    const result = subtractBriefFromRange(
      { in: 20, out: 40 },
      [{ inSec: 0, outSec: 10 }, { inSec: 50, outSec: 60 }]
    );
    assert.deepEqual(result, [{ in: 20, out: 40 }]);
  });

  it('clamps brief segments to range boundaries', () => {
    const result = subtractBriefFromRange(
      { in: 20, out: 40 },
      [{ inSec: 15, outSec: 30 }]
    );
    // Brief covers [20, 30] of the range → gap is [30, 40]
    assert.equal(result.length, 1);
    assert.deepEqual(result[0], { in: 30, out: 40 });
  });
});

// --- createGapSegment ---

describe('createGapSegment', () => {
  it('creates a segment with correct structure', () => {
    const gap = createGapSegment('RYA-FX3-0099.MP4', 10.5, 30.0);
    assert.equal(gap.sourceFile, 'RYA-FX3-0099.MP4');
    assert.equal(gap.inSec, 10.5);
    assert.equal(gap.outSec, 30.0);
    assert.equal(gap.duration, 19.5);
    assert.equal(gap.use, false);
    assert.equal(gap.block, 0);
    assert.equal(gap.priority, 1);
    assert.equal(gap._isGap, true);
    assert.ok(gap.id.startsWith('gap_RYA-FX3-0099'));
  });

  it('produces "skip" category', () => {
    const gap = createGapSegment('RYA-FX3-0099.MP4', 0, 10);
    assert.equal(getReviewCategory(gap), 'skip');
  });
});

// --- computeClipOffsets ---

describe('computeClipOffsets', () => {
  it('computes offsets in alphabetical order', () => {
    const result = computeClipOffsets({
      'RYA-FX3-0099.MP4': 156.0,
      'RYA-FX3-0100.MP4': 79.2,
      'RYA-FX3-0101.MP4': 121.44
    });
    assert.equal(result.offsets['RYA-FX3-0099.MP4'], 0);
    assert.equal(result.offsets['RYA-FX3-0100.MP4'], 156.0);
    assert.ok(Math.abs(result.offsets['RYA-FX3-0101.MP4'] - 235.2) < 0.01);
    assert.ok(Math.abs(result.ingestDuration - 356.64) < 0.01);
  });

  it('returns empty for empty input', () => {
    const result = computeClipOffsets({});
    assert.deepEqual(result.offsets, {});
    assert.equal(result.ingestDuration, 0);
  });

  it('single clip starts at 0', () => {
    const result = computeClipOffsets({ 'A.MP4': 100 });
    assert.equal(result.offsets['A.MP4'], 0);
    assert.equal(result.ingestDuration, 100);
  });
});

// --- sortReviewSegments (complement approach) ---

describe('sortReviewSegments with clipDurations', () => {
  const allSegments = [
    { id: 'seg_001', sourceFile: 'RYA-FX3-0100.MP4', inSec: 0.0, outSec: 71.6, duration: 71.6, use: true, block: 1, priority: 1 },
    { id: 'seg_002', sourceFile: 'RYA-FX3-0100.MP4', inSec: 71.6, outSec: 73.4, duration: 1.8, use: false, block: 1, priority: 2,
      tcIn: '01:11.6', tcOut: '01:13.4', speaker: 'Host', transcript: 'alt take' },
    { id: 'seg_003', sourceFile: 'RYA-FX3-0099.MP4', inSec: 119.4, outSec: 151.9, duration: 32.5, use: true, block: 2, priority: 1 },
    { id: 'seg_004', sourceFile: 'RYA-FX3-0100.MP4', inSec: 73.4, outSec: 76.4, duration: 3.0, use: true, block: 2, priority: 1 },
    { id: 'seg_005', sourceFile: 'RYA-FX3-0101.MP4', inSec: 30.0, outSec: 106.2, duration: 76.2, use: true, block: 3, priority: 1 },
    { id: 'seg_006', sourceFile: 'RYA-FX3-0101.MP4', inSec: 107.7, outSec: 117.7, duration: 10.0, use: true, block: 3, priority: 1 },
    { id: 'seg_007', sourceFile: 'RYA-FX3-0099.MP4', inSec: 153.9, outSec: 155.2, duration: 1.3, use: false, block: 99, priority: 9,
      tcIn: '02:33.9', tcOut: '02:35.2', speaker: '', transcript: 'mumbled' },
    { id: 'seg_008', sourceFile: 'RYA-FX3-0101.MP4', inSec: 0.0, outSec: 0.3, duration: 0.3, use: false, block: 99, priority: 9,
      tcIn: '00:00.0', tcOut: '00:00.3', speaker: '', transcript: 'between' },
    { id: 'seg_009', sourceFile: 'RYA-FX3-0101.MP4', inSec: 119.8, outSec: 120.2, duration: 0.4, use: false, block: 99, priority: 9,
      tcIn: '01:59.8', tcOut: '02:00.2', speaker: '', transcript: 'expletive' },
  ];

  const clipDurations = {
    'RYA-FX3-0099.MP4': 156.0,
    'RYA-FX3-0100.MP4': 79.2,
    'RYA-FX3-0101.MP4': 121.44
  };

  it('includes brief use=FALSE segments and synthetic gaps', () => {
    const result = sortReviewSegments(allSegments, clipDurations);

    // Brief segments should be present
    const ids = result.map(s => s.id);
    assert.ok(ids.includes('seg_002'), 'brief seg_002 included');
    assert.ok(ids.includes('seg_007'), 'brief seg_007 included');
    assert.ok(ids.includes('seg_009'), 'brief seg_009 included');

    // Should have MORE segments than old approach (4 brief + gaps)
    assert.ok(result.length > 4, 'should have more than 4 segments (was: ' + result.length + ')');
  });

  it('does NOT include assembly segments', () => {
    const result = sortReviewSegments(allSegments, clipDurations);
    const ids = result.map(s => s.id);
    assert.ok(!ids.includes('seg_001'), 'seg_001 (assembly) excluded');
    assert.ok(!ids.includes('seg_003'), 'seg_003 (assembly) excluded');
    assert.ok(!ids.includes('seg_004'), 'seg_004 (assembly) excluded');
    assert.ok(!ids.includes('seg_005'), 'seg_005 (assembly) excluded');
    assert.ok(!ids.includes('seg_006'), 'seg_006 (assembly) excluded');
  });

  it('creates gap segments for uncovered complement areas', () => {
    const result = sortReviewSegments(allSegments, clipDurations);
    const gaps = result.filter(s => s._isGap);
    assert.ok(gaps.length > 0, 'should have synthetic gap segments');

    // All gaps should have valid structure
    for (const g of gaps) {
      assert.ok(g.inSec < g.outSec, g.id + ' should have in < out');
      assert.ok(g.duration > 0, g.id + ' should have positive duration');
      assert.equal(g.use, false);
    }
  });

  it('sorts by sourceFile then inSec', () => {
    const result = sortReviewSegments(allSegments, clipDurations);
    for (let i = 1; i < result.length; i++) {
      const prev = result[i - 1];
      const curr = result[i];
      if (prev.sourceFile === curr.sourceFile) {
        assert.ok(prev.inSec <= curr.inSec,
          prev.id + ' (' + prev.inSec + ') should be before ' + curr.id + ' (' + curr.inSec + ')');
      } else {
        assert.ok(prev.sourceFile < curr.sourceFile,
          prev.sourceFile + ' should be before ' + curr.sourceFile);
      }
    }
  });

  it('covers complement of assembly for RYA-FX3-0099', () => {
    const result = sortReviewSegments(allSegments, clipDurations);
    const clip0099 = result.filter(s => s.sourceFile === 'RYA-FX3-0099.MP4');
    // Assembly uses [119.4-151.9]. Clip is 156.0s.
    // Complement: [0, 119.4] + [151.9, 156.0]
    // Brief covers: seg_007 [153.9-155.2]
    // Gaps: [0, 119.4], [151.9, 153.9], [155.2, 156.0]
    assert.ok(clip0099.length >= 3, 'RYA-FX3-0099 should have at least 3 review segments (was: ' + clip0099.length + ')');

    // First segment should start at 0
    assert.equal(clip0099[0].inSec, 0);

    // seg_007 (brief) should be present
    assert.ok(clip0099.some(s => s.id === 'seg_007'));
  });

  it('covers complement of assembly for RYA-FX3-0100', () => {
    const result = sortReviewSegments(allSegments, clipDurations);
    const clip0100 = result.filter(s => s.sourceFile === 'RYA-FX3-0100.MP4');
    // Assembly uses [0-71.6] + [73.4-76.4]. Clip is 79.2s.
    // Complement: [71.6, 73.4] + [76.4, 79.2]
    // Brief covers: seg_002 [71.6-73.4]
    // Gaps: [76.4, 79.2]
    assert.ok(clip0100.length >= 2, 'RYA-FX3-0100 should have at least 2 review segments');
    assert.ok(clip0100.some(s => s.id === 'seg_002'), 'seg_002 should be in RYA-FX3-0100');
    assert.ok(clip0100.some(s => s._isGap && s.inSec === 76.4), 'gap at 76.4 should exist');
  });

  it('seg_008 excluded if duration < minGap (0.3s)', () => {
    const result = sortReviewSegments(allSegments, clipDurations);
    // seg_008 has duration=0.3s which is exactly at the threshold
    // It should still be included since 0.3 >= 0.3
    const seg008 = result.find(s => s.id === 'seg_008');
    assert.ok(seg008, 'seg_008 (0.3s) should be included at threshold');
  });

  it('total review duration approximates ingest minus assembly', () => {
    const result = sortReviewSegments(allSegments, clipDurations);
    const totalReview = result.reduce((sum, s) => sum + s.duration, 0);
    const totalIngest = 156.0 + 79.2 + 121.44; // 356.64
    const totalAssembly = 71.6 + 32.5 + 3.0 + 76.2 + 10.0; // 193.3
    const expectedReview = totalIngest - totalAssembly; // ~163.34
    // Allow some tolerance for minGap filtering
    assert.ok(Math.abs(totalReview - expectedReview) < 2,
      'review duration (' + totalReview.toFixed(1) + ') should be close to ' + expectedReview.toFixed(1));
  });

  it('falls back to old filter when no clipDurations', () => {
    const result = sortReviewSegments(allSegments);
    // Old behavior: just filter use=FALSE
    assert.equal(result.length, 4);
    const ids = result.map(s => s.id);
    assert.ok(ids.includes('seg_002'));
    assert.ok(ids.includes('seg_007'));
    assert.ok(ids.includes('seg_008'));
    assert.ok(ids.includes('seg_009'));
  });

  it('returns empty when all footage is in assembly', () => {
    const usedSegs = [
      { id: 'seg_001', sourceFile: 'A.MP4', inSec: 0, outSec: 100, duration: 100, use: true, block: 1, priority: 1 },
    ];
    const durations = { 'A.MP4': 100 };
    const result = sortReviewSegments(usedSegs, durations);
    assert.equal(result.length, 0);
  });
});
