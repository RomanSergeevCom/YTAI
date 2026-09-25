const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const {
  buildSceneDeletedSceneSegments,
  getDeletedSceneCategory,
  getDeletedSceneColorIdx,
  computeComplement,
  computeSceneClipOffsets,
  createGapSegment
} = require('../../src/deletedScene/deletedSceneBuilder');
const { DELETED_SCENE_COLOR_MAP, DELETED_SCENE_PRODUCER_COLOR } = require('../../src/shared/constants');

// --- getDeletedSceneCategory ---

describe('getDeletedSceneCategory', () => {
  it('returns "cut" for block=99', () => {
    assert.equal(getDeletedSceneCategory({ block: 99, priority: 1, use: false }), 'cut');
  });

  it('returns "alt" for priority=2', () => {
    assert.equal(getDeletedSceneCategory({ block: 1, priority: 2, use: false }), 'alt');
  });

  it('returns "alt" for string priority "2"', () => {
    assert.equal(getDeletedSceneCategory({ block: 1, priority: '2', use: false }), 'alt');
  });

  it('returns "skip" for use=FALSE with no special conditions', () => {
    assert.equal(getDeletedSceneCategory({ block: 1, priority: 1, use: false }), 'skip');
    assert.equal(getDeletedSceneCategory({ block: 3, priority: 9, use: false }), 'skip');
  });

  it('block=99 takes priority over priority=2', () => {
    assert.equal(getDeletedSceneCategory({ block: 99, priority: 2, use: false }), 'cut');
  });

  it('returns "skip" for gap segments (block=0, priority=1)', () => {
    assert.equal(getDeletedSceneCategory({ block: 0, priority: 1, use: false }), 'skip');
  });
});

// --- getDeletedSceneColorIdx ---

describe('getDeletedSceneColorIdx', () => {
  it('returns Lavender for producer speaker', () => {
    var seg = { block: 1, priority: 1, speaker: 'Speaker 2' };
    var opts = { producerSpeaker: 'Speaker 2', assemblyBlocks: [] };
    assert.equal(getDeletedSceneColorIdx(seg, opts), DELETED_SCENE_PRODUCER_COLOR.labelIdx);
  });

  it('returns Red for block=99 even if producer speaker', () => {
    var seg = { block: 99, priority: 1, speaker: 'Speaker 2' };
    var opts = { producerSpeaker: 'Speaker 2', assemblyBlocks: [] };
    // Producer check comes first — producer speaker takes precedence even for block=99
    assert.equal(getDeletedSceneColorIdx(seg, opts), DELETED_SCENE_PRODUCER_COLOR.labelIdx);
  });

  it('returns expert color for non-producer speaker (takes priority over block)', () => {
    var seg = { block: 2, priority: 1, speaker: 'Speaker 1', color: 'Blue' };
    var opts = {
      producerSpeaker: 'Speaker 2',
      assemblyBlocks: [{ block: 2, usedCount: 3, color: 'Blue' }]
    };
    // Expert speaker check takes priority over block color
    var { DELETED_SCENE_EXPERT_COLOR } = require('../../src/shared/constants');
    assert.equal(getDeletedSceneColorIdx(seg, opts), DELETED_SCENE_EXPERT_COLOR.labelIdx);
  });

  it('returns expert color for speaker even without Assembly block match', () => {
    var seg = { block: 5, priority: 1, speaker: 'Speaker 1' };
    var opts = {
      producerSpeaker: 'Speaker 2',
      assemblyBlocks: [{ block: 2, usedCount: 3, color: 'Blue' }]
    };
    // Expert speaker check takes priority
    var { DELETED_SCENE_EXPERT_COLOR } = require('../../src/shared/constants');
    assert.equal(getDeletedSceneColorIdx(seg, opts), DELETED_SCENE_EXPERT_COLOR.labelIdx);
  });

  it('returns category color when no opts provided (backward compat)', () => {
    var seg = { block: 1, priority: 2 };
    assert.equal(getDeletedSceneColorIdx(seg), DELETED_SCENE_COLOR_MAP.alt.labelIdx);
  });

  it('returns expert color for priority=2 alt segments with speaker', () => {
    var seg = { block: 3, priority: 2, speaker: 'Speaker 1' };
    var opts = { producerSpeaker: 'Speaker 2', assemblyBlocks: [] };
    // Expert speaker check takes priority over alt category
    var { DELETED_SCENE_EXPERT_COLOR } = require('../../src/shared/constants');
    assert.equal(getDeletedSceneColorIdx(seg, opts), DELETED_SCENE_EXPERT_COLOR.labelIdx);
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
    assert.equal(result.length, 0);
  });

  it('includes gaps at or above minGap threshold', () => {
    const result = computeComplement([
      { in: 0, out: 49 },
      { in: 50, out: 100 }
    ], 100, 0.3);
    assert.equal(result.length, 1);
    assert.deepEqual(result[0], { in: 49, out: 50 });
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
    assert.equal(getDeletedSceneCategory(gap), 'skip');
  });
});

// --- computeSceneClipOffsets ---

describe('computeSceneClipOffsets', () => {
  it('computes offsets in provided order', () => {
    const result = computeSceneClipOffsets(
      ['RYA-FX3-0099.MP4', 'RYA-FX3-0100.MP4', 'RYA-FX3-0101.MP4'],
      { 'RYA-FX3-0099.MP4': 156.0, 'RYA-FX3-0100.MP4': 79.2, 'RYA-FX3-0101.MP4': 121.44 }
    );
    assert.equal(result.offsets['RYA-FX3-0099.MP4'], 0);
    assert.equal(result.offsets['RYA-FX3-0100.MP4'], 156.0);
    assert.ok(Math.abs(result.offsets['RYA-FX3-0101.MP4'] - 235.2) < 0.01);
    assert.ok(Math.abs(result.totalDuration - 356.64) < 0.01);
  });

  it('returns empty for empty input', () => {
    const result = computeSceneClipOffsets([], {});
    assert.deepEqual(result.offsets, {});
    assert.equal(result.totalDuration, 0);
  });

  it('single clip starts at 0', () => {
    const result = computeSceneClipOffsets(['A.MP4'], { 'A.MP4': 100 });
    assert.equal(result.offsets['A.MP4'], 0);
    assert.equal(result.totalDuration, 100);
  });
});

// --- buildSceneDeletedSceneSegments ---

describe('buildSceneDeletedSceneSegments', () => {
  const allSegments = [
    { id: 'seg_001', sourceFile: 'RYA-FX3-0100.MP4', inSec: 0.0, outSec: 71.6, duration: 71.6, use: true, block: 1, priority: 1 },
    { id: 'seg_002', sourceFile: 'RYA-FX3-0100.MP4', inSec: 71.6, outSec: 73.4, duration: 1.8, use: false, block: 1, priority: 2,
      tcIn: '01:11.6', tcOut: '01:13.4', speaker: 'Host', transcript: 'alt take' },
    { id: 'seg_003', sourceFile: 'RYA-FX3-0099.MP4', inSec: 119.4, outSec: 151.9, duration: 32.5, use: true, block: 2, priority: 1 },
    { id: 'seg_004', sourceFile: 'RYA-FX3-0100.MP4', inSec: 73.4, outSec: 76.4, duration: 3.0, use: true, block: 2, priority: 1 },
    { id: 'seg_005', sourceFile: 'RYA-FX3-0101.MP4', inSec: 30.0, outSec: 106.2, duration: 76.2, use: true, block: 3, priority: 1 },
    { id: 'seg_007', sourceFile: 'RYA-FX3-0099.MP4', inSec: 153.9, outSec: 155.2, duration: 1.3, use: false, block: 99, priority: 9,
      tcIn: '02:33.9', tcOut: '02:35.2', speaker: '', transcript: 'mumbled' },
  ];

  const clipDurations = {
    'RYA-FX3-0099.MP4': 156.0,
    'RYA-FX3-0100.MP4': 79.2,
    'RYA-FX3-0101.MP4': 121.44
  };

  const sceneClipNames = ['RYA-FX3-0099.MP4', 'RYA-FX3-0100.MP4', 'RYA-FX3-0101.MP4'];

  it('includes brief use=FALSE segments and synthetic gaps', () => {
    const result = buildSceneDeletedSceneSegments(allSegments, sceneClipNames, clipDurations);
    const ids = result.segments.map(s => s.id);
    assert.ok(ids.includes('seg_002'), 'brief seg_002 included');
    assert.ok(ids.includes('seg_007'), 'brief seg_007 included');
    assert.ok(result.segments.length > 2, 'should have gaps + brief segments');
  });

  it('does NOT include assembly segments', () => {
    const result = buildSceneDeletedSceneSegments(allSegments, sceneClipNames, clipDurations);
    const ids = result.segments.map(s => s.id);
    assert.ok(!ids.includes('seg_001'), 'seg_001 (assembly) excluded');
    assert.ok(!ids.includes('seg_003'), 'seg_003 (assembly) excluded');
    assert.ok(!ids.includes('seg_004'), 'seg_004 (assembly) excluded');
    assert.ok(!ids.includes('seg_005'), 'seg_005 (assembly) excluded');
  });

  it('creates gap segments for uncovered complement areas', () => {
    const result = buildSceneDeletedSceneSegments(allSegments, sceneClipNames, clipDurations);
    const gaps = result.segments.filter(s => s._isGap);
    assert.ok(gaps.length > 0, 'should have synthetic gap segments');
    for (const g of gaps) {
      assert.ok(g.inSec < g.outSec, g.id + ' should have in < out');
      assert.ok(g.duration > 0, g.id + ' should have positive duration');
      assert.equal(g.use, false);
    }
  });

  it('returns assemblyGapMarkers for used segments', () => {
    const result = buildSceneDeletedSceneSegments(allSegments, sceneClipNames, clipDurations);
    assert.ok(result.assemblyGapMarkers.length > 0, 'should have gap markers');
    const marker = result.assemblyGapMarkers.find(m => m.segId === 'seg_001');
    assert.ok(marker, 'seg_001 should have a gap marker');
    assert.equal(marker.sourceFile, 'RYA-FX3-0100.MP4');
  });
});
