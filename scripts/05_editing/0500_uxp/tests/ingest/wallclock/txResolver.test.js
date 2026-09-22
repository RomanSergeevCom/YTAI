const { test } = require('node:test');
const assert = require('node:assert');
const {
  validateTxStrip,
  prepareTxStrips,
} = require('../../../src/ingest/layout/txResolver');

const VALID_TX = {
  tx: 'TX00',
  filename: 'TX00_MIC044_20260402_130310_orig.wav',
  path: '/a/b/TX00_MIC044_20260402_130310_orig.wav',
  creation_time: '2026-04-02T09:03:10.000Z',
  duration: 1651.6,
  sample_rate: 48000,
};

test('validateTxStrip: valid input passes', () => {
  const result = validateTxStrip(VALID_TX, 48000);
  assert.strictEqual(result.ok, true);
});

test('validateTxStrip: missing filename fails', () => {
  const result = validateTxStrip({ ...VALID_TX, filename: undefined }, 48000);
  assert.strictEqual(result.ok, false);
  assert.match(result.reason, /filename/);
});

test('validateTxStrip: missing path fails', () => {
  const result = validateTxStrip({ ...VALID_TX, path: undefined }, 48000);
  assert.strictEqual(result.ok, false);
  assert.match(result.reason, /path/);
});

test('validateTxStrip: missing creation_time fails', () => {
  const result = validateTxStrip({ ...VALID_TX, creation_time: undefined }, 48000);
  assert.strictEqual(result.ok, false);
  assert.match(result.reason, /creation_time/);
});

test('validateTxStrip: zero duration fails', () => {
  const result = validateTxStrip({ ...VALID_TX, duration: 0 }, 48000);
  assert.strictEqual(result.ok, false);
  assert.match(result.reason, /duration/);
});

test('validateTxStrip: negative duration fails', () => {
  const result = validateTxStrip({ ...VALID_TX, duration: -5 }, 48000);
  assert.strictEqual(result.ok, false);
});

test('validateTxStrip: sample_rate mismatch fails (hard error reason)', () => {
  const result = validateTxStrip({ ...VALID_TX, sample_rate: 44100 }, 48000);
  assert.strictEqual(result.ok, false);
  assert.match(result.reason, /sample_rate mismatch/);
  assert.match(result.reason, /44100/);
  assert.match(result.reason, /48000/);
});

test('validateTxStrip: sample_rate within tolerance passes', () => {
  const result = validateTxStrip(
    { ...VALID_TX, sample_rate: 48000 },
    48001,
    { sampleRateTolerance: 5 }
  );
  assert.strictEqual(result.ok, true);
});

test('validateTxStrip: strict mode requires sample_rate', () => {
  const tx = { ...VALID_TX };
  delete tx.sample_rate;
  const result = validateTxStrip(tx, 48000, { strict: true });
  assert.strictEqual(result.ok, false);
  assert.match(result.reason, /sample_rate/);
});

test('validateTxStrip: non-strict mode tolerates missing sample_rate', () => {
  const tx = { ...VALID_TX };
  delete tx.sample_rate;
  const result = validateTxStrip(tx, 48000);
  assert.strictEqual(result.ok, true);
});

// ─── prepareTxStrips ─────────────────────────────────────────────────────

test('prepareTxStrips: filters invalid and warns', () => {
  const txStrips = [
    VALID_TX,
    { ...VALID_TX, tx: 'TX01', sample_rate: 44100 },  // mismatched
    { ...VALID_TX, tx: 'TX02', duration: 0 },         // invalid duration
  ];
  const { valid, warnings } = prepareTxStrips(txStrips, 48000);
  assert.strictEqual(valid.length, 1);
  assert.strictEqual(valid[0].tx, 'TX00');
  assert.strictEqual(warnings.length, 2);
  assert.strictEqual(warnings[0].type, 'tx_invalid');
});

test('prepareTxStrips: empty/null input → empty result', () => {
  assert.deepStrictEqual(prepareTxStrips(null, 48000), { valid: [], warnings: [] });
  assert.deepStrictEqual(prepareTxStrips([], 48000), { valid: [], warnings: [] });
});

test('prepareTxStrips: all valid → all pass', () => {
  const txStrips = [
    VALID_TX,
    { ...VALID_TX, tx: 'TX01' },
  ];
  const { valid, warnings } = prepareTxStrips(txStrips, 48000);
  assert.strictEqual(valid.length, 2);
  assert.strictEqual(warnings.length, 0);
});
