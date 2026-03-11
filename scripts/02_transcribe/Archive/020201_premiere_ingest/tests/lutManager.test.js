const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const ppro = require('./mocks/premierepro');
const { Logger } = require('../src/logger');
const { applyLumetriToClips } = require('../src/lutManager');

describe('applyLumetriToClips', () => {
  let project;
  let sequence;
  let logger;

  beforeEach(() => {
    ppro._recorder.reset();
    project = new ppro._MockProject('TestProject');
    sequence = new ppro._MockSequence('Test — Ingest');
    logger = new Logger();

    // Add 3 mock track items to V1
    const v1 = sequence._videoTracks[0];
    v1._items = [
      new ppro._MockTrackItem('C5402.MP4'),
      new ppro._MockTrackItem('C5403.MP4'),
      new ppro._MockTrackItem('C5404.MP4')
    ];
  });

  it('finds Lumetri Color in VideoFilterFactory', async () => {
    await applyLumetriToClips(project, sequence, logger);
    const logs = logger.getBuffer();
    assert.ok(logs.some(e => e.includes('Found Lumetri Color')));
  });

  it('applies Lumetri to all V1 clips', async () => {
    const count = await applyLumetriToClips(project, sequence, logger);
    assert.equal(count, 3);
  });

  it('calls VideoFilterFactory.createComponent for each clip', async () => {
    await applyLumetriToClips(project, sequence, logger);
    const calls = ppro._recorder.getCalls('VideoFilterFactory.createComponent');
    assert.equal(calls.length, 3);
    assert.equal(calls[0].args[0], 'AE.ADBE Lumetri');
  });

  it('calls createAppendComponentAction for each clip', async () => {
    await applyLumetriToClips(project, sequence, logger);
    const calls = ppro._recorder.getCalls('VideoComponentChain.createAppendComponentAction');
    assert.equal(calls.length, 3);
  });

  it('wraps in lockedAccess and executeTransaction', async () => {
    await applyLumetriToClips(project, sequence, logger);
    const lockCalls = ppro._recorder.getCalls('Project.lockedAccess');
    const txCalls = ppro._recorder.getCalls('Project.executeTransaction');
    assert.ok(lockCalls.length >= 3, 'Should use lockedAccess for each clip');
    assert.ok(txCalls.length >= 3, 'Should use executeTransaction for each clip');
  });

  it('logs each applied clip', async () => {
    await applyLumetriToClips(project, sequence, logger);
    const logs = logger.getBuffer();
    assert.ok(logs.some(e => e.includes('Lumetri applied: "C5402.MP4"')));
    assert.ok(logs.some(e => e.includes('Lumetri applied: "C5403.MP4"')));
    assert.ok(logs.some(e => e.includes('Lumetri applied: "C5404.MP4"')));
  });

  it('returns 0 when V1 has no clips', async () => {
    sequence._videoTracks[0]._items = [];
    const count = await applyLumetriToClips(project, sequence, logger);
    assert.equal(count, 0);
  });

  it('returns 0 when Lumetri not found', async () => {
    // Override factory to have no Lumetri
    const origDisplayNames = ppro.VideoFilterFactory._displayNames;
    ppro.VideoFilterFactory._displayNames = ['Gaussian Blur', 'Motion'];
    ppro.VideoFilterFactory._matchNames = ['AE.ADBE Gaussian Blur 2', 'AE.ADBE Motion'];

    const count = await applyLumetriToClips(project, sequence, logger);
    assert.equal(count, 0);
    const logs = logger.getBuffer();
    assert.ok(logs.some(e => e.includes('Lumetri Color effect not found')));

    // Restore
    ppro.VideoFilterFactory._displayNames = origDisplayNames;
    ppro.VideoFilterFactory._matchNames = ['AE.ADBE Lumetri', 'AE.ADBE Gaussian Blur 2', 'AE.ADBE Motion'];
  });

  it('handles Array.from on non-array matchNames', async () => {
    // Simulate UXP returning a non-array collection
    const origGetMatchNames = ppro.VideoFilterFactory.getMatchNames;
    const origGetDisplayNames = ppro.VideoFilterFactory.getDisplayNames;

    // Create iterable (not an array) to simulate UXP behavior — must be async
    ppro.VideoFilterFactory.getMatchNames = async () => {
      return { 0: 'AE.ADBE Lumetri', length: 1, [Symbol.iterator]: function*() { yield 'AE.ADBE Lumetri'; } };
    };
    ppro.VideoFilterFactory.getDisplayNames = async () => {
      return { 0: 'Lumetri Color', length: 1, [Symbol.iterator]: function*() { yield 'Lumetri Color'; } };
    };

    const count = await applyLumetriToClips(project, sequence, logger);
    assert.equal(count, 3);

    // Restore
    ppro.VideoFilterFactory.getMatchNames = origGetMatchNames;
    ppro.VideoFilterFactory.getDisplayNames = origGetDisplayNames;
  });
});
