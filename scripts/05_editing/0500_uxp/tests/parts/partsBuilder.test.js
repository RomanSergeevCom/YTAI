const { test } = require('node:test');
const assert = require('node:assert');
const { buildPartSequence, trackIndex, tcToSec, PARTS_BUILDER_VERSION } = require('../../src/parts/partsBuilder');

test('partsBuilder exports', () => {
  assert.strictEqual(typeof buildPartSequence, 'function');
  assert.strictEqual(typeof trackIndex, 'function');
  assert.strictEqual(typeof tcToSec, 'function');
  assert.ok(PARTS_BUILDER_VERSION, 'has version');
});

test('trackIndex: V1/A1→0, V2/A2→1, default 0', () => {
  assert.strictEqual(trackIndex('V1'), 0);
  assert.strictEqual(trackIndex('A1'), 0);
  assert.strictEqual(trackIndex('V2'), 1);
  assert.strictEqual(trackIndex('A2'), 1);
  assert.strictEqual(trackIndex('V3'), 2);
  assert.strictEqual(trackIndex(null), 0);
  assert.strictEqual(trackIndex(undefined), 0);
});

test('tcToSec: parses M:SS.mmm and passes numbers through', () => {
  assert.strictEqual(tcToSec('1:23.5'), 83.5);
  assert.strictEqual(tcToSec('0:00.000'), 0);
  assert.strictEqual(tcToSec('48:36.000'), 48 * 60 + 36);
  assert.strictEqual(tcToSec(12.5), 12.5);
  assert.strictEqual(tcToSec(0), 0);
});
