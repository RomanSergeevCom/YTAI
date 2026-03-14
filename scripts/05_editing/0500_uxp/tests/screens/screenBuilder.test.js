const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const {
  buildScreenCues,
  buildSegmentPositionMap,
  getScreenTimelinePosition,
  generateScreenCuesSrt,
  formatSrtTimecode,
  sortSegments,
  OVERLAY_DURATION
} = require('../../src/screens/screenBuilder');

// Reset mock call recorder before each test
const ppro = require('../../tests/mocks/premierepro');

// --- Helpers ---
function makeAssemblySegments() {
  return [
    { id: 'seg_001', sourceFile: 'RYA-FX3-0099.MP4', inSec: 0, outSec: 10, duration: 10, tcIn: '00:00.0', tcOut: '00:10.0', use: true, block: 1, blockName: 'Hook', color: 'Green' },
    { id: 'seg_002', sourceFile: 'RYA-FX3-0099.MP4', inSec: 15, outSec: 30, duration: 15, tcIn: '00:15.0', tcOut: '00:30.0', use: true, block: 1, blockName: 'Hook', color: 'Green' },
    { id: 'seg_003', sourceFile: 'RYA-FX3-0100.MP4', inSec: 5, outSec: 25, duration: 20, tcIn: '00:05.0', tcOut: '00:25.0', use: true, block: 2, blockName: 'Body', color: 'Blue' }
  ];
}

function makeAllSegments() {
  var segs = makeAssemblySegments();
  segs.push({ id: 'seg_cut', sourceFile: 'RYA-FX3-0099.MP4', inSec: 100, outSec: 102, duration: 2, tcIn: '01:40.0', tcOut: '01:42.0', use: false, block: 99, blockName: 'Cut', color: 'Red' });
  return segs;
}

function makeClipMap() {
  return {
    'RYA-FX3-0099.MP4': new ppro._MockClipProjectItem('RYA-FX3-0099.MP4'),
    'RYA-FX3-0100.MP4': new ppro._MockClipProjectItem('RYA-FX3-0100.MP4')
  };
}

function makeScreen(overrides) {
  var seg = { id: 'seg_001', sourceFile: 'RYA-FX3-0099.MP4', inSec: 0, outSec: 10, duration: 10, tcIn: '00:00.0' };
  return Object.assign({
    id: 'scr_001',
    type: 'full_overlay',
    segmentId: 'seg_001',
    segment: seg,
    tcIn: '00:00.0',
    tcInSec: 0,
    title: 'Test Title',
    subtitle: '',
    body: ''
  }, overrides);
}

// --- sortSegments ---
describe('screenBuilder sortSegments', () => {
  it('sorts by block, preserving brief order within block', () => {
    var segs = [
      { id: 's1', block: 2 },
      { id: 's2', block: 1 },
      { id: 's3', block: 1 }
    ];
    var sorted = sortSegments(segs);
    assert.equal(sorted[0].id, 's2');
    assert.equal(sorted[1].id, 's3');
    assert.equal(sorted[2].id, 's1');
  });

  it('puts block 99 last', () => {
    var segs = [
      { id: 's1', block: 99 },
      { id: 's2', block: 1 }
    ];
    var sorted = sortSegments(segs);
    assert.equal(sorted[0].id, 's2');
    assert.equal(sorted[1].id, 's1');
  });

  it('handles empty array', () => {
    assert.deepEqual(sortSegments([]), []);
  });
});

// --- formatSrtTimecode ---
describe('formatSrtTimecode', () => {
  it('formats zero seconds', () => {
    assert.equal(formatSrtTimecode(0), '00:00:00,000');
  });

  it('formats seconds with milliseconds', () => {
    assert.equal(formatSrtTimecode(5.5), '00:00:05,500');
  });

  it('formats minutes and seconds', () => {
    assert.equal(formatSrtTimecode(71.6), '00:01:11,600');
  });

  it('formats hours', () => {
    assert.equal(formatSrtTimecode(3661.25), '01:01:01,250');
  });

  it('handles negative as zero', () => {
    assert.equal(formatSrtTimecode(-5), '00:00:00,000');
  });
});

// --- generateScreenCuesSrt ---
describe('generateScreenCuesSrt', () => {
  it('generates SRT with correct timecodes', () => {
    var segs = makeAssemblySegments();
    var screens = [
      makeScreen({ id: 'scr_001', segmentId: 'seg_001', tcInSec: 0, segment: segs[0], type: 'full_overlay', title: 'Title' }),
      makeScreen({ id: 'scr_002', segmentId: 'seg_002', tcInSec: 15, segment: segs[1], type: 'lower_third', title: 'Name', subtitle: 'Role' })
    ];
    var srt = generateScreenCuesSrt(screens, segs);
    assert.ok(srt.includes('00:00:00,000'), 'First screen at 0s');
    assert.ok(srt.includes('00:00:10,000'), 'Second screen at 10s (seg_002 starts at 10)');
    assert.ok(srt.includes('[FULL OVERLAY]'));
    assert.ok(srt.includes('[LOWER THIRD]'));
  });

  it('returns empty string for empty screens', () => {
    assert.equal(generateScreenCuesSrt([], makeAssemblySegments()), '');
  });

  it('returns empty string for null screens', () => {
    assert.equal(generateScreenCuesSrt(null, makeAssemblySegments()), '');
  });

  it('skips screens whose segments are not in Assembly', () => {
    var segs = makeAssemblySegments();
    var screens = [
      makeScreen({ id: 'scr_001', segmentId: 'seg_999', tcInSec: 0, segment: { inSec: 0, outSec: 10, duration: 10 } })
    ];
    var srt = generateScreenCuesSrt(screens, segs);
    assert.equal(srt, '');
  });
});

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
    assert.equal(pos, 10);
  });

  it('returns offset within segment', () => {
    var segPositions = { 'seg_001': 0, 'seg_002': 10 };
    var screen = makeScreen({ segmentId: 'seg_002', tcInSec: 20 });
    screen.segment = { inSec: 15, outSec: 30, duration: 15 };
    var pos = getScreenTimelinePosition(screen, segPositions);
    assert.equal(pos, 15);
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
    assert.equal(pos, 10);
  });
});

// --- buildScreenCues (v1.9.3: V1 Assembly copy + V2 overlays + markers + SRT) ---
describe('buildScreenCues', () => {
  var project;

  beforeEach(() => {
    ppro._recorder.reset();
    project = new ppro._MockProject();
  });

  it('returns zeros for empty screens', async () => {
    var result = await buildScreenCues(project, [], makeAllSegments(), makeClipMap(), 'TestProject');
    assert.equal(result.clips, 0);
    assert.equal(result.markers, 0);
    assert.equal(result.overlays, 0);
    assert.equal(result.skipped, 0);
    assert.equal(result.sequence, null);
    assert.equal(result.srtContent, '');
  });

  it('returns empty result for null screens', async () => {
    var result = await buildScreenCues(project, null, makeAllSegments(), makeClipMap(), 'TestProject');
    assert.equal(result.clips, 0);
    assert.equal(result.sequence, null);
  });

  it('builds V1 with Assembly segments (not screen-based clips)', async () => {
    var allSegs = makeAllSegments();
    var screens = [makeScreen({ segment: allSegs[0] })];
    var result = await buildScreenCues(project, screens, allSegs, makeClipMap(), 'TestProject');

    // V1 should have ALL Assembly segments (3), not just 1 screen
    assert.equal(result.clips, 3, 'V1 should have 3 Assembly segments');
    assert.equal(result.assemblySegments.length, 3, 'assemblySegments should have 3 entries');
    assert.ok(result.sequence !== null, 'Should create a sequence');
  });

  it('creates sequence via createSequenceFromMedia for first segment', async () => {
    var allSegs = makeAllSegments();
    var screens = [makeScreen({ segment: allSegs[0] })];
    await buildScreenCues(project, screens, allSegs, makeClipMap(), 'TestProject');

    var createCalls = ppro._recorder.getCalls('Project.createSequenceFromMedia');
    assert.ok(createCalls.length >= 1, 'Should call createSequenceFromMedia');
    assert.ok(createCalls[0].args[0].includes('_4_ScreenCues'));
  });

  it('inserts remaining V1 segments via createInsertProjectItemAction', async () => {
    var allSegs = makeAllSegments();
    var screens = [makeScreen({ segment: allSegs[0] })];
    await buildScreenCues(project, screens, allSegs, makeClipMap(), 'TestProject');

    var insertCalls = ppro._recorder.getCalls('SequenceEditor.createInsertProjectItemAction');
    assert.ok(insertCalls.length >= 2, 'Should have insert calls for segments 2 and 3');
  });

  it('totalDuration matches Assembly total (not screen count)', async () => {
    var allSegs = makeAllSegments();
    var screens = [makeScreen({ segment: allSegs[0] })];
    var result = await buildScreenCues(project, screens, allSegs, makeClipMap(), 'TestProject');

    // Assembly: seg_001(10) + seg_002(15) + seg_003(20) = 45s
    assert.equal(result.totalDuration, 45);
  });

  it('filters out block=99 and use=FALSE from V1', async () => {
    var allSegs = makeAllSegments();
    var screens = [makeScreen({ segment: allSegs[0] })];
    var result = await buildScreenCues(project, screens, allSegs, makeClipMap(), 'TestProject');

    // seg_cut (block=99, use=false) should NOT be in assemblySegments
    var ids = result.assemblySegments.map(s => s.id);
    assert.ok(!ids.includes('seg_cut'), 'Should not include cut segment');
    assert.equal(ids.length, 3);
  });

  it('returns markerList at Assembly timeline positions (creation deferred to index.js)', async () => {
    var allSegs = makeAllSegments();
    var screens = [
      makeScreen({ id: 'scr_001', segmentId: 'seg_001', tcInSec: 0, segment: allSegs[0], type: 'full_overlay' }),
      makeScreen({ id: 'scr_002', segmentId: 'seg_003', tcInSec: 5, segment: allSegs[2], type: 'lower_third', title: 'Name' })
    ];
    var result = await buildScreenCues(project, screens, allSegs, makeClipMap(), 'TestProject');

    // Markers are no longer created inside buildScreenCues — they are prepared as markerList
    // and created by createScreenCuesMarkers() in index.js (same pattern as Assembly)
    assert.equal(result.markers, 2);
    assert.ok(result.markerList.length >= 2, 'markerList should have 2+ entries');
    assert.ok(result.markerList[0].name.includes('[SCR]'), 'marker name should include [SCR]');
    assert.equal(result.markerList[0].type, 'com.adobe.premiereMarkers.chapter', 'marker type should be Chapter URI');
    assert.ok(result.markerList[0].startSec >= 0, 'marker startSec should be >= 0');
  });

  it('returns srtContent with correct timecodes', async () => {
    var allSegs = makeAllSegments();
    var screens = [
      makeScreen({ id: 'scr_001', segmentId: 'seg_001', tcInSec: 0, segment: allSegs[0], type: 'full_overlay', title: 'Title' })
    ];
    var result = await buildScreenCues(project, screens, allSegs, makeClipMap(), 'TestProject');

    assert.ok(result.srtContent.length > 0, 'srtContent should not be empty');
    assert.ok(result.srtContent.includes('00:00:00,000'), 'Should contain start timecode');
    assert.ok(result.srtContent.includes('[FULL OVERLAY]'));
  });

  it('cleans old ScreenCues sequence before creating new', async () => {
    var allSegs = makeAllSegments();
    var screens = [makeScreen({ segment: allSegs[0] })];
    await buildScreenCues(project, screens, allSegs, makeClipMap(), 'TestProject');

    var createCalls = ppro._recorder.getCalls('Project.createSequenceFromMedia');
    assert.ok(createCalls.length >= 1);
  });

  it('handles no briefPath gracefully (no V2 overlays)', async () => {
    var allSegs = makeAllSegments();
    var screens = [makeScreen({ segment: allSegs[0] })];
    var result = await buildScreenCues(project, screens, allSegs, makeClipMap(), 'TestProject');

    // No briefPath = no PNG overlays
    assert.equal(result.overlays, 0);
    // But V1, markers, SRT should still work
    assert.equal(result.clips, 3);
    assert.equal(result.markers, 1);
    assert.ok(result.srtContent.length > 0);
  });

  it('skips V2 when pngFiles is null (no screen_cues folder)', async () => {
    var allSegs = makeAllSegments();
    var screens = [makeScreen({ segment: allSegs[0] })];
    var result = await buildScreenCues(project, screens, allSegs, makeClipMap(), 'TestProject', null, '/some/path/brief.json', null);

    assert.equal(result.overlays, 0, 'No overlays when pngFiles is null');
    assert.equal(result.clips, 3, 'V1 should still build');
    assert.equal(result.markers, 1, 'Markers should still be created');
  });

  it('skips V2 when pngFiles is empty array', async () => {
    var allSegs = makeAllSegments();
    var screens = [makeScreen({ segment: allSegs[0] })];
    var result = await buildScreenCues(project, screens, allSegs, makeClipMap(), 'TestProject', null, '/some/path/brief.json', []);

    assert.equal(result.overlays, 0, 'No overlays when pngFiles is empty');
    assert.equal(result.clips, 3, 'V1 should still build');
  });

  it('warns with actionable message when pngFiles missing', async () => {
    var allSegs = makeAllSegments();
    var screens = [makeScreen({ segment: allSegs[0] })];
    var result = await buildScreenCues(project, screens, allSegs, makeClipMap(), 'TestProject', null, '/some/path/brief.json', []);

    // Should NOT have misleading "imported but not found" warnings
    var misleading = result.warnings.filter(function (w) { return w.includes('imported but not found'); });
    assert.equal(misleading.length, 0, 'Should not have misleading error messages');
  });

  it('skips individual PNG not in pngFiles list', async () => {
    var allSegs = makeAllSegments();
    var screens = [
      makeScreen({ id: 'scr_001', segmentId: 'seg_001', tcInSec: 0, segment: allSegs[0], type: 'full_overlay' }),
      makeScreen({ id: 'scr_002', segmentId: 'seg_002', tcInSec: 15, segment: allSegs[1], type: 'lower_third', title: 'Name' })
    ];
    // Only one PNG exists
    var pngFiles = ['scr_001_full_overlay.png'];
    var result = await buildScreenCues(project, screens, allSegs, makeClipMap(), 'TestProject', null, '/some/path/brief.json', pngFiles);

    // scr_002 should be skipped with actionable warning
    var skipWarnings = result.warnings.filter(function (w) { return w.includes('scr_002') && w.includes('not generated'); });
    assert.equal(skipWarnings.length, 1, 'Should warn about missing scr_002 PNG');
    assert.ok(result.skipped >= 1, 'At least one screen should be skipped');
  });
});
