const { test } = require('node:test');
const assert = require('node:assert');
const tb = require('../../../src/ingest/timelineBuilder');

// resolveLayoutMode is the regression guard for NEW-2: a v1.x ingest that only
// carries creation_time (no wall_offset / no tx_strips) must NOT auto-select
// wallclock — that would silently drop all lavalier audio.

test('resolveLayoutMode: v1.1 with creation_time only → linear', () => {
  assert.strictEqual(
    tb.resolveLayoutMode({ version: '1.1', clips: [{ creation_time: '2026-01-01T00:00:00Z' }] }),
    'linear'
  );
});

test('resolveLayoutMode: v2.0 + wall_offset on all clips → wallclock', () => {
  assert.strictEqual(
    tb.resolveLayoutMode({ version: '2.0', clips: [{ creation_time: 'x', wall_offset: 0 }] }),
    'wallclock'
  );
});

test('resolveLayoutMode: explicit layout_mode wallclock wins', () => {
  assert.strictEqual(tb.resolveLayoutMode({ layout_mode: 'wallclock', clips: [] }), 'wallclock');
});

test('resolveLayoutMode: explicit layout_mode linear overrides v2.0', () => {
  assert.strictEqual(
    tb.resolveLayoutMode({ layout_mode: 'linear', version: '2.0', clips: [{ wall_offset: 0 }] }),
    'linear'
  );
});

test('resolveLayoutMode: v2.0 but one clip missing wall_offset → linear', () => {
  assert.strictEqual(
    tb.resolveLayoutMode({ version: '2.0', clips: [{ wall_offset: 0 }, { creation_time: 'x' }] }),
    'linear'
  );
});

test('resolveLayoutMode: no version, no wall_offset → linear', () => {
  assert.strictEqual(tb.resolveLayoutMode({ clips: [{ filename: 'a.MP4' }] }), 'linear');
});

test('timelineBuilder: back-compat exports present', () => {
  for (const fn of ['buildIngestSequence', 'buildMultiSceneIngest', 'findProjectItemByName',
    'applyMediaSettings', 'logSequenceSettings', 'listBinItems', 'resolveLayoutMode']) {
    assert.ok(tb[fn], `export ${fn} present`);
  }
});
