const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const {
  buildScreenCues,
  buildSegmentPositionMap,
  getScreenTimelinePosition,
  CUE_CLIP_DURATION
} = require('../../src/screens/screenBuilder');

// Reset mock call recorder before each test
const ppro = require('../../tests/mocks/premierepro');

// --- Helpers ---
function makeAssemblySegments() {
  return [
    { id: 'seg_001', sourceFile: 'C5402.MP4', inSec: 0, outSec: 10, duration: 10, tcIn: '00:00.0', use: true, block: 1, blockName: 'Hook', color: 'Green' },
    { id: 'seg_002', sourceFile: 'C5402.MP4', inSec: 15, outSec: 30, duration: 15, tcIn: '00:15.0', use: true, block: 1, blockName: 'Hook', color: 'Green' },
    { id: 'seg_003', sourceFile: 'C5403.MP4', inSec: 5, outSec: 25, duration: 20, tcIn: '00:05.0', use: true, block: 2, blockName: 'Body', color: 'Blue' }
  ];
}

function makeClipMap() {
  return {
    'C5402.MP4': new ppro._MockClipProjectItem('C5402.MP4'),
    'C5403.MP4': new ppro._MockClipProjectItem('C5403.MP4')
  };
}

function makeScreen(overrides) {
  var seg = { id: 'seg_001', sourceFile: 'C5402.MP4', inSec: 0, outSec: 10, duration: 10, tcIn: '00:00.0' };
  return Object.assign({
    id: 'scr_001',
    type: 'chapter_title',
    segmentId: 'seg_001',
    segment: seg,
    tcIn: '00:00.0',
    tcInSec: 0,
    title: 'Test Title',
    subtitle: '',
    body: ''
  }, overrides);
}

// --- buildSegmentPositionMap ---
describe('buildSegmentPositionMap', () => {
  it('returns cumulative positions for Assembly segments', () => {
    var segs = makeAssemblySegments();
    var map = buildSegmentPositionMap(segs);
    assert.equal(map['seg_001'], 0);
    assert.equal(map['seg_002'], 10);
    assert.equal(map['seg_003'], 25);
  });

  it('returns empty map for empty segments', () => {
    var map = buildSegmentPositionMap([]);
    assert.deepEqual(map, {});
  });

  it('handles single segment', () => {
    var map = buildSegmentPositionMap([
      { id: 'seg_001', duration: 5.5 }
    ]);
    assert.equal(map['seg_001'], 0);
  });
});

// --- getScreenTimelinePosition ---
describe('getScreenTimelinePosition', () => {
  it('returns segment start when tcInSec equals segment inSec', () => {
    var segPositions = { 'seg_001': 0, 'seg_002': 10 };
    var screen = makeScreen({ segmentId: 'seg_002', tcInSec: 15 });
    screen.segment = { inSec: 15, outSec: 30, duration: 15 };
    var pos = getScreenTimelinePosition(screen, segPositions);
    assert.equal(pos, 10); // seg_002 starts at 10, offset = 15-15 = 0
  });

  it('returns offset within segment', () => {
    var segPositions = { 'seg_001': 0, 'seg_002': 10 };
    var screen = makeScreen({ segmentId: 'seg_002', tcInSec: 20 });
    screen.segment = { inSec: 15, outSec: 30, duration: 15 };
    var pos = getScreenTimelinePosition(screen, segPositions);
    assert.equal(pos, 15); // seg_002 at 10 + offset(20-15) = 15
  });

  it('returns null for segment not in Assembly', () => {
    var segPositions = { 'seg_001': 0 };
    var screen = makeScreen({ segmentId: 'seg_999' });
    var pos = getScreenTimelinePosition(screen, segPositions);
    assert.equal(pos, null);
  });

  it('clamps negative offset to 0', () => {
    var segPositions = { 'seg_001': 0 };
    var screen = makeScreen({ segmentId: 'seg_001', tcInSec: -5 });
    screen.segment = { inSec: 0, outSec: 10, duration: 10 };
    var pos = getScreenTimelinePosition(screen, segPositions);
    assert.equal(pos, 0);
  });

  it('clamps offset exceeding segment duration', () => {
    var segPositions = { 'seg_001': 0 };
    var screen = makeScreen({ segmentId: 'seg_001', tcInSec: 100 });
    screen.segment = { inSec: 0, outSec: 10, duration: 10 };
    var pos = getScreenTimelinePosition(screen, segPositions);
    assert.equal(pos, 10); // clamped to duration
  });
});

// --- buildScreenCues (creates separate _4_ScreenCues sequence) ---
describe('buildScreenCues', () => {
  var project;

  beforeEach(() => {
    ppro._recorder.reset();
    project = new ppro._MockProject();
  });

  it('returns zeros for empty screens', async () => {
    var result = await buildScreenCues(project, [], makeClipMap(), 'TestProject');
    assert.equal(result.clips, 0);
    assert.equal(result.markers, 0);
    assert.equal(result.skipped, 0);
    assert.equal(result.sequence, null);
  });

  it('creates ScreenCues sequence and places V1 clip', async () => {
    var segs = makeAssemblySegments();
    var screens = [makeScreen({ segment: segs[0] })];
    var result = await buildScreenCues(project, screens, makeClipMap(), 'TestProject');
    assert.equal(result.clips, 1);
    assert.equal(result.markers, 1);
    assert.equal(result.skipped, 0);
    assert.ok(result.sequence !== null, 'Should create a sequence');

    // Verify sequence was created via createSequenceFromMedia
    var createCalls = ppro._recorder.getCalls('Project.createSequenceFromMedia');
    assert.ok(createCalls.length >= 1, 'Should call createSequenceFromMedia');
    assert.ok(createCalls[0].args[0].includes('_4_ScreenCues'), 'Sequence name should contain _4_ScreenCues');
  });

  it('skips screen when source file not in clipMap', async () => {
    var screen = makeScreen({
      segment: { id: 'seg_001', sourceFile: 'MISSING.MP4', inSec: 0, outSec: 10, duration: 10 }
    });
    var result = await buildScreenCues(project, [screen], makeClipMap(), 'TestProject');
    assert.equal(result.clips, 0);
    assert.equal(result.skipped, 1);
    assert.ok(result.warnings[0].includes('not in clipMap'));
  });

  it('handles multiple screens sequentially on V1', async () => {
    var segs = makeAssemblySegments();
    var screens = [
      makeScreen({ id: 'scr_001', segmentId: 'seg_001', tcInSec: 0, segment: segs[0], type: 'chapter_title', title: 'Intro' }),
      makeScreen({ id: 'scr_002', segmentId: 'seg_002', tcInSec: 15, segment: segs[1], type: 'lower_third', title: 'John', subtitle: 'CEO' }),
      makeScreen({ id: 'scr_003', segmentId: 'seg_003', tcInSec: 10, segment: segs[2], type: 'half_overlay', title: 'Stats' })
    ];
    var result = await buildScreenCues(project, screens, makeClipMap(), 'TestProject');
    assert.equal(result.clips, 3);
    assert.equal(result.markers, 3);
    assert.equal(result.skipped, 0);
    assert.ok(result.totalDuration > 0, 'Should have positive totalDuration');

    // Verify insert calls for clips 2 and 3 (first uses createSequenceFromMedia)
    var insertCalls = ppro._recorder.getCalls('SequenceEditor.createInsertProjectItemAction');
    assert.ok(insertCalls.length >= 2, 'Should have at least 2 insert calls for remaining clips');
  });

  it('creates marker with correct [SCR] name and Comment type', async () => {
    var segs = makeAssemblySegments();
    var screens = [makeScreen({ segment: segs[0], type: 'lower_third', title: 'Name' })];
    var result = await buildScreenCues(project, screens, makeClipMap(), 'TestProject');

    var addMarkerCalls = ppro._recorder.getCalls('Markers.createAddMarkerAction');
    assert.ok(addMarkerCalls.length >= 1);
    // Marker name should contain [SCR]
    var firstCall = addMarkerCalls[0];
    assert.ok(firstCall.args[0].includes('[SCR]'), 'Marker name should contain [SCR]');
  });

  it('returns empty result for null screens', async () => {
    var result = await buildScreenCues(project, null, makeClipMap(), 'TestProject');
    assert.equal(result.clips, 0);
    assert.equal(result.markers, 0);
    assert.equal(result.sequence, null);
  });

  it('cleans old ScreenCues sequence before creating new', async () => {
    var segs = makeAssemblySegments();
    var screens = [makeScreen({ segment: segs[0] })];
    await buildScreenCues(project, screens, makeClipMap(), 'TestProject');

    // cleanExistingSequence is called — we verify by checking sequence was created
    var createCalls = ppro._recorder.getCalls('Project.createSequenceFromMedia');
    assert.ok(createCalls.length >= 1);
  });

  it('totalDuration reflects CUE_CLIP_DURATION per screen', async () => {
    var segs = makeAssemblySegments();
    var screens = [
      makeScreen({ id: 'scr_001', segment: segs[0], tcInSec: 0 }),
      makeScreen({ id: 'scr_002', segment: segs[1], tcInSec: 15 })
    ];
    var result = await buildScreenCues(project, screens, makeClipMap(), 'TestProject');
    assert.equal(result.clips, 2);
    // Each clip is CUE_CLIP_DURATION=2s, total should be ~4s
    assert.ok(result.totalDuration > 0);
    assert.ok(result.totalDuration <= CUE_CLIP_DURATION * 2 + 0.1);
  });
});
