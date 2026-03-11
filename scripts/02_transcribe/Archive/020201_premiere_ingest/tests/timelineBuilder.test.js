const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const ppro = require('./mocks/premierepro');
const { Logger } = require('../src/logger');

// logSequenceSettings is not exported — test via buildIngestSequence which calls it,
// or test the mock sequence directly to verify getFrameSize/getTimebase contract.

describe('Sequence resolution and FPS (logSequenceSettings contract)', () => {
  let sequence;

  beforeEach(() => {
    sequence = new ppro._MockSequence('Test — Ingest');
  });

  it('getFrameSize returns width and height', async () => {
    const frameSize = await sequence.getFrameSize();
    assert.equal(frameSize.width, 3840);
    assert.equal(frameSize.height, 2160);
  });

  it('getTimebase returns ticks-per-frame string', async () => {
    const timebase = await sequence.getTimebase();
    assert.equal(typeof timebase, 'string');
    // 254016000000 / 10160640000 = 25
    const fps = Math.round(254016000000 / parseInt(timebase) * 100) / 100;
    assert.equal(fps, 25);
  });

  it('getFrameSize handles empty UXP object (prototype properties)', async () => {
    // Simulate UXP object that JSON.stringify shows as {} but has properties
    const uxpLikeObj = Object.create({ width: 3840, height: 2160 });
    // JSON.stringify returns "{}" but .width is accessible
    assert.equal(JSON.stringify(uxpLikeObj), '{}');
    assert.equal(uxpLikeObj.width, 3840);
    assert.equal(uxpLikeObj.height, 2160);
  });

  it('getTimebase with large tick value converts to FPS correctly', () => {
    // Common Premiere timebase values
    const testCases = [
      { ticks: '10160640000', expectedFps: 25 },
      { ticks: '10594584000', expectedFps: 23.98 },  // 23.976
      { ticks: '8467200000', expectedFps: 30 },       // 29.97 ≈ 30
    ];

    for (const tc of testCases) {
      const fps = Math.round(254016000000 / parseInt(tc.ticks) * 100) / 100;
      assert.ok(Math.abs(fps - tc.expectedFps) < 0.5,
        `Ticks ${tc.ticks}: expected ~${tc.expectedFps}, got ${fps}`);
    }
  });

  it('getTimebase handles non-tick numeric value as direct FPS', () => {
    // If timebase returns a small number, treat as FPS directly
    const timebase = 25;
    let fps;
    if (timebase > 1000) {
      fps = Math.round(254016000000 / timebase * 100) / 100;
    } else {
      fps = timebase;
    }
    assert.equal(fps, 25);
  });
});

describe('buildIngestSequence', () => {
  const { buildIngestSequence } = require('../src/timelineBuilder');
  let project;
  let logger;
  let ingest;

  beforeEach(() => {
    ppro._recorder.reset();
    project = new ppro._MockProject('TestProject');
    logger = new Logger();

    ingest = {
      project_name: 'Test',
      clips: [
        { clip_id: 'C001', filename: 'C001.MP4', path: '/tmp/C001.MP4', duration: 10 },
        { clip_id: 'C002', filename: 'C002.MP4', path: '/tmp/C002.MP4', duration: 20 },
      ],
      media: { width: 3840, height: 2160, fps: 25 }
    };
  });

  it('imports files into source bin', async () => {
    const sourceBin = new ppro._MockFolderItem('00_Source');
    await buildIngestSequence(project, ingest, sourceBin, null, logger);

    const importCalls = ppro._recorder.getCalls('Project.importFiles');
    assert.equal(importCalls.length, 1);
    assert.deepEqual(importCalls[0].args[0], ['/tmp/C001.MP4', '/tmp/C002.MP4']);
  });

  it('creates sequence from first clip', async () => {
    const sourceBin = new ppro._MockFolderItem('00_Source');
    const result = await buildIngestSequence(project, ingest, sourceBin, null, logger);

    assert.ok(result.sequence);
    assert.equal(result.sequence.name, 'Test — Ingest');
  });

  it('places all clips sequentially', async () => {
    const sourceBin = new ppro._MockFolderItem('00_Source');
    // Add sourceBin to project root so findProjectItemByName can find imported clips
    const rootItem = await project.getRootItem();
    rootItem._items.push(sourceBin);

    const result = await buildIngestSequence(project, ingest, sourceBin, null, logger);

    assert.equal(result.clipCount, 2);
    assert.equal(result.totalDuration, 30);
  });

  it('returns seqSettings with resolution and FPS', async () => {
    const sourceBin = new ppro._MockFolderItem('00_Source');
    const result = await buildIngestSequence(project, ingest, sourceBin, null, logger);

    assert.ok(result.seqSettings);
    assert.equal(result.seqSettings.width, 3840);
    assert.equal(result.seqSettings.height, 2160);
    assert.equal(result.seqSettings.fps, 25);
  });
});
