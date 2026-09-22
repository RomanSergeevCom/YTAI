const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const ppro = require('../mocks/premierepro');
const { buildFootageReview, baseName, sanitizeName, FOOTAGE_REVIEW_VERSION } = require('../../src/footageReview/footageReviewBuilder');
const { Logger } = require('../../src/shared/logger');

const FILES = ['/Volumes/RYA-CFA-1/M4ROOT/CLIP/RYA-FX3-0329.MP4',
               '/Volumes/RYA-CFA-1/M4ROOT/CLIP/RYA-FX3-0330.MP4',
               '/Volumes/RYA-CFA-1/M4ROOT/CLIP/RYA-FX3-0331.MP4'];

describe('baseName', () => {
  it('returns the filename from a path', () => {
    assert.equal(baseName('/a/b/RYA-FX3-0329.MP4'), 'RYA-FX3-0329.MP4');
  });
});

describe('buildFootageReview — placement', () => {
  let project, logger;
  beforeEach(() => {
    ppro._recorder.reset();
    project = new ppro._MockProject('ActiveProject');
    logger = new Logger();
  });

  it('throws when no files given', async () => {
    await assert.rejects(() => buildFootageReview(project, [], { applyLut: false }, logger), /No video files/);
  });

  it('imports every clip', async () => {
    await buildFootageReview(project, FILES, { name: 'Card', applyLut: false }, logger);
    const calls = ppro._recorder.getCalls('Project.importFiles');
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].args[0], FILES);
  });

  it('creates one sequence from the first clip and places all clips', async () => {
    const r = await buildFootageReview(project, FILES, { name: 'Card', applyLut: false }, logger);
    assert.equal(r.srcSeqName, 'Card_Footage');
    assert.equal(r.total, 3);
    assert.equal(r.placed, 3);
    const seqCalls = ppro._recorder.getCalls('Project.createSequenceFromMedia');
    assert.equal(seqCalls.length, 1);
    assert.equal(seqCalls[0].args[0], 'Card_Footage');
  });

  it('sanitizes the project name into the sequence name', async () => {
    const r = await buildFootageReview(project, FILES, { name: 'RYA CFA 1', applyLut: false }, logger);
    assert.equal(r.srcSeqName, 'RYA_CFA_1_Footage');
  });

  it('reports the builder version and no LUT copy when applyLut=false', async () => {
    const r = await buildFootageReview(project, FILES, { applyLut: false }, logger);
    assert.equal(r.version, FOOTAGE_REVIEW_VERSION);
    assert.equal(r.lutFolder, null);
    assert.deepEqual(r.lutsCopied, []);
  });
});

describe('buildFootageReview — LUT', () => {
  let project, logger;
  beforeEach(() => {
    ppro._recorder.reset();
    project = new ppro._MockProject('ActiveProject');
    logger = new Logger();
  });

  it('creates ONE flat sequence (no nested _Review) and applies no Lumetri', async () => {
    // Simplified path: copy LUTs only, no auto-apply, no wrapper sequence.
    const r = await buildFootageReview(project, FILES, { name: 'Card', applyLut: true }, logger);
    assert.equal(r.srcSeqName, 'Card_Footage');
    assert.equal(r.reviewSeqName, undefined);
    const seqCalls = ppro._recorder.getCalls('Project.createSequenceFromMedia');
    assert.equal(seqCalls.length, 1, 'only the flat footage sequence, no nested wrapper');
    const lumetri = ppro._recorder.getCalls('VideoFilterFactory.createComponent');
    assert.equal(lumetri.length, 0, 'no auto-applied Lumetri');
    assert.ok('lutFolder' in r && Array.isArray(r.lutsCopied));
  });
});

describe('sanitizeName', () => {
  it('replaces spaces with underscores', () => {
    assert.equal(sanitizeName('RYA CFA 1'), 'RYA_CFA_1');
  });
  it('keeps Cyrillic letters (Unicode-aware)', () => {
    assert.equal(sanitizeName('Карта 1'), 'Карта_1');
  });
  it('trims edge underscores and falls back when empty', () => {
    assert.equal(sanitizeName('  !!  '), 'Footage');
    assert.equal(sanitizeName(''), 'Footage');
  });
});

describe('buildFootageReview — empty-sequence fallback', () => {
  let project, logger;
  beforeEach(() => {
    ppro._recorder.reset();
    project = new ppro._MockProject('ActiveProject');
    logger = new Logger();
  });

  it('places ALL clips (incl. the first) when createSequenceFromMedia fails', async () => {
    // Force the empty-sequence fallback: placed must start at 0 and the loop at i=0,
    // otherwise the first clip is silently dropped (regression guard for finding #8).
    project.createSequenceFromMedia = async function () { throw new Error('no media seed'); };
    const r = await buildFootageReview(project, FILES, { name: 'Card', applyLut: false }, logger);
    assert.equal(r.total, 3);
    assert.equal(r.placed, 3);
  });
});
