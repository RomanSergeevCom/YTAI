const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const ppro = require('../mocks/premierepro');
const { sortSegments } = require('../../src/assembly/assemblyBuilder');

// --- sortSegments (pure function, no Premiere API needed) ---

describe('sortSegments', () => {
  it('sorts segments by block number', () => {
    const segs = [
      { block: 3, inSec: 0 },
      { block: 1, inSec: 0 },
      { block: 2, inSec: 0 }
    ];
    const sorted = sortSegments(segs);
    assert.equal(sorted[0].block, 1);
    assert.equal(sorted[1].block, 2);
    assert.equal(sorted[2].block, 3);
  });

  it('preserves brief order within same block', () => {
    const segs = [
      { block: 1, inSec: 30 },
      { block: 1, inSec: 10 },
      { block: 1, inSec: 20 }
    ];
    const sorted = sortSegments(segs);
    // Brief order preserved (not sorted by inSec — inSec is source timecode, not assembly order)
    assert.equal(sorted[0].inSec, 30);
    assert.equal(sorted[1].inSec, 10);
    assert.equal(sorted[2].inSec, 20);
  });

  it('puts block 99 last', () => {
    const segs = [
      { block: 99, inSec: 0 },
      { block: 1, inSec: 0 },
      { block: 2, inSec: 0 }
    ];
    const sorted = sortSegments(segs);
    assert.equal(sorted[0].block, 1);
    assert.equal(sorted[1].block, 2);
    assert.equal(sorted[2].block, 99);
  });

  it('does not mutate original array', () => {
    const segs = [
      { block: 2, inSec: 0 },
      { block: 1, inSec: 0 }
    ];
    const sorted = sortSegments(segs);
    assert.equal(segs[0].block, 2); // original unchanged
    assert.equal(sorted[0].block, 1); // sorted copy
  });

  it('handles empty array', () => {
    const sorted = sortSegments([]);
    assert.equal(sorted.length, 0);
  });

  it('handles single element', () => {
    const segs = [{ block: 1, inSec: 5 }];
    const sorted = sortSegments(segs);
    assert.equal(sorted.length, 1);
    assert.equal(sorted[0].block, 1);
  });
});

// --- Integration: verify module exports ---

describe('assemblyBuilder module', () => {
  it('exports buildAssemblySequence function', () => {
    const mod = require('../../src/assembly/assemblyBuilder');
    assert.equal(typeof mod.buildAssemblySequence, 'function');
  });

  it('does not export getCleanTrackItems (removed in pre-trim approach)', () => {
    const mod = require('../../src/assembly/assemblyBuilder');
    assert.equal(typeof mod.getCleanTrackItems, 'undefined');
  });

  it('exports sortSegments function', () => {
    const mod = require('../../src/assembly/assemblyBuilder');
    assert.equal(typeof mod.sortSegments, 'function');
  });
});
