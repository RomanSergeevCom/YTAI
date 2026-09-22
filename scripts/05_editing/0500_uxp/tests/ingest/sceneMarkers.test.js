const { test, beforeEach } = require('node:test');
const assert = require('node:assert');

const ppro = require('../../tests/mocks/premierepro');
const { addSceneMarkers } = require('../../src/ingest/placement/sceneMarkers');
const { MARKER_COLOR_INDEX, MARKER_TYPE_CHAPTER } = require('../../src/shared/constants');

const recorder = ppro._recorder;

function makeLogger() {
  const lines = [];
  return {
    lines,
    info: (m) => lines.push(['info', m]),
    warn: (m) => lines.push(['warn', m]),
    debug: (m) => lines.push(['debug', m]),
    error: (m) => lines.push(['error', m]),
  };
}

function makeProject() {
  return {
    lockedAccess(fn) { return fn(); },
    executeTransaction(fn) { fn({ addAction() {} }); return Promise.resolve(); },
  };
}

beforeEach(() => { recorder.calls.length = 0; });

function calls(method) {
  return recorder.calls.filter(c => c.method === method);
}

test('places range markers with duration, color and Chapter type', async () => {
  const n = await addSceneMarkers(makeProject(), {}, [
    { offset_sec: 21, duration_sec: 300, name: 'Чёрный опал', comment: 'RYA-FX3-0545', color: 'Orange' },
    { offset_sec: 321, duration_sec: 195.5, name: 'Рубин: Бирма vs Мозамбик', color: 'Red' },
  ], makeLogger());
  assert.equal(n, 2);

  const adds = calls('Markers.createAddMarkerAction');
  assert.equal(adds.length, 2);
  // duration argument = TickTime with our seconds (диапазон-глава, не точка)
  assert.equal(adds[0].args[3].seconds, 300);
  assert.equal(adds[1].args[3].seconds, 195.5);

  const colorCalls = calls('Marker.createSetColorByIndexAction');
  assert.deepEqual(colorCalls.map(c => c.args[0]).sort(),
    [MARKER_COLOR_INDEX.Orange, MARKER_COLOR_INDEX.Red].sort());

  const typeCalls = calls('Marker.createSetTypeAction');
  assert.equal(typeCalls.length, 2);
  assert.equal(typeCalls[0].args[0], MARKER_TYPE_CHAPTER);
});

test('point marker without duration uses TIME_ZERO and no color when unset', async () => {
  const n = await addSceneMarkers(makeProject(), {}, [
    { offset_sec: 5, name: 'без цвета' },
  ], makeLogger());
  assert.equal(n, 1);
  const adds = calls('Markers.createAddMarkerAction');
  assert.equal(adds[0].args[3].seconds, 0);
  assert.equal(calls('Marker.createSetColorByIndexAction').length, 0);
});

test('skips invalid entries and tolerates empty/null input', async () => {
  const n = await addSceneMarkers(makeProject(), {}, [
    { offset_sec: 'nope', name: 'bad' },
    { name: 'no offset' },
    null,
    { offset_sec: 5, name: 'ok' },
  ], makeLogger());
  assert.equal(n, 1);
  assert.equal(await addSceneMarkers(makeProject(), {}, [], makeLogger()), 0);
  assert.equal(await addSceneMarkers(makeProject(), null, [{ offset_sec: 1, name: 'x' }], makeLogger()), 0);
});

test('falls back to sequence.getMarkers when ppro.Markers is unavailable', async () => {
  const orig = ppro.Markers.getMarkers;
  ppro.Markers.getMarkers = async () => { throw new Error('api gone'); };
  try {
    const owner = await orig({});
    const sequence = { getMarkers: async () => owner };
    const n = await addSceneMarkers(makeProject(), sequence, [{ offset_sec: 1, name: 'x' }], makeLogger());
    assert.equal(n, 1);
  } finally {
    ppro.Markers.getMarkers = orig;
  }
});

test('survives total markers API absence', async () => {
  const orig = ppro.Markers.getMarkers;
  ppro.Markers.getMarkers = async () => { throw new Error('api gone'); };
  try {
    const n = await addSceneMarkers(makeProject(), {}, [{ offset_sec: 1, name: 'x' }], makeLogger());
    assert.equal(n, 0);
  } finally {
    ppro.Markers.getMarkers = orig;
  }
});

// ── replace semantics: re-running must RE-SYNC the sequence, not double it up ──

test('re-run replaces previously generated markers and keeps the editor own ones', async () => {
  const seq = {};                                   // one object == one markers owner
  const owner = await ppro.Markers.getMarkers(seq);
  await owner.createMarker({ seconds: 5 }, 'Comment', 'Aymen: fix audio here', '');

  const list = [
    { offset_sec: 0, duration_sec: 60, name: 'Ch03 ★ Taekwondo visa', color: 'Yellow' },
    { offset_sec: 100, duration_sec: 40, name: '✗ NO CHAPTER · chatter', color: 'Red' },
  ];

  assert.equal(await addSceneMarkers(makeProject(), seq, list, makeLogger()), 2);
  assert.equal(owner.getMarkers().length, 3);       // editor's one + our two

  assert.equal(await addSceneMarkers(makeProject(), seq, list, makeLogger()), 2);
  const names = owner.getMarkers().map(m => m.getName());
  assert.equal(names.length, 3, 'second pass must not duplicate: ' + names.join(' | '));
  assert.equal(new Set(names).size, 3, 'no duplicate names');
  assert.ok(names.includes('Aymen: fix audio here'), 'hand-placed marker must survive');
  assert.ok(calls('Markers.createRemoveMarkerAction').length >= 2, 'stale markers were swept');
});

test('replace:false keeps the old behaviour (append only)', async () => {
  const seq = {};
  const owner = await ppro.Markers.getMarkers(seq);
  const list = [{ offset_sec: 0, duration_sec: 10, name: 'Ch01 ▦ b-roll', color: 'Blue' }];

  await addSceneMarkers(makeProject(), seq, list, makeLogger(), { replace: false });
  await addSceneMarkers(makeProject(), seq, list, makeLogger(), { replace: false });
  assert.equal(owner.getMarkers().length, 2);
  assert.equal(calls('Markers.createRemoveMarkerAction').length, 0);
});

test('sweep never touches markers this tooling did not write', async () => {
  const seq = {};
  const owner = await ppro.Markers.getMarkers(seq);
  for (const nm of ['Chapters ahead', 'ch03 lowercase', 'Ch3 single digit', 'NO CHAPTER no glyph']) {
    await owner.createMarker({ seconds: 1 }, 'Comment', nm, '');
  }
  await addSceneMarkers(makeProject(), seq,
    [{ offset_sec: 0, duration_sec: 5, name: 'Ch09 ✓ used', color: 'Blue' }], makeLogger());
  await addSceneMarkers(makeProject(), seq,
    [{ offset_sec: 0, duration_sec: 5, name: 'Ch09 ✓ used', color: 'Blue' }], makeLogger());

  const names = owner.getMarkers().map(m => m.getName());
  assert.equal(names.length, 5, 'four foreign + one ours: ' + names.join(' | '));
  assert.equal(calls('Markers.createRemoveMarkerAction').length, 1);
});

test('sweep recognises the new "[N] …" part naming and NO PART markers', async () => {
  const seq = {};
  const owner = await ppro.Markers.getMarkers(seq);
  await owner.createMarker({ seconds: 1 }, 'Comment', 'Aymen: check colour here', '');
  const list = [
    { offset_sec: 0, duration_sec: 30, name: '[4] ★ Taekwondo referee course bought the visa', color: 'Green' },
    { offset_sec: 40, duration_sec: 25, name: '✗ NO PART · crew chatter', color: 'Orange' },
    { offset_sec: 80, duration_sec: 20, name: '[1] ▦ Moody over-shoulder driving', color: 'Blue' },
  ];
  await addSceneMarkers(makeProject(), seq, list, makeLogger());
  await addSceneMarkers(makeProject(), seq, list, makeLogger());
  const names = owner.getMarkers().map(m => m.getName());
  assert.equal(names.length, 4, 'three ours + one hand-placed: ' + names.join(' | '));
  assert.ok(names.includes('Aymen: check colour here'));
  assert.equal(new Set(names).size, 4);
});

test('a bracket that is not a part number is left alone', async () => {
  const seq = {};
  const owner = await ppro.Markers.getMarkers(seq);
  for (const nm of ['[note] fix audio', '[] empty', '[123456] weird']) {
    await owner.createMarker({ seconds: 1 }, 'Comment', nm, '');
  }
  await addSceneMarkers(makeProject(), seq,
    [{ offset_sec: 0, duration_sec: 5, name: '[2] · setup', color: 'Cyan' }], makeLogger());
  await addSceneMarkers(makeProject(), seq,
    [{ offset_sec: 0, duration_sec: 5, name: '[2] · setup', color: 'Cyan' }], makeLogger());
  const names = owner.getMarkers().map(m => m.getName());
  assert.equal(names.length, 4, names.join(' | '));
  assert.equal(calls('Markers.createRemoveMarkerAction').length, 1);
});

// ── Premiere падал на длинном прогоне: маркеры должны идти пачками, а не по одному ──

test('markers go in batches, not one transaction per marker', async () => {
  const seq = {};
  const list = Array.from({ length: 45 }, (_, i) =>
    ({ offset_sec: i * 10, duration_sec: 9, name: `[1] ★ marker ${i}`, color: 'Blue' }));
  const n = await addSceneMarkers(makeProject(), seq, list, makeLogger());
  assert.equal(n, 45);
  const adds = calls('Markers.createAddMarkerAction');
  assert.equal(adds.length, 45, 'every marker still created');
  // 45 маркеров пачками по 20 → 3 транзакции, а не 45
  const tx = recorder.calls.filter(c => c.method === 'Project.executeTransaction');
  if (tx.length) assert.ok(tx.length <= 6, 'batched into a few transactions, got ' + tx.length);
});

test('generatedMarkerNames sees only our markers — that is how a crashed run resumes', async () => {
  const { generatedMarkerNames } = require('../../src/ingest/placement/sceneMarkers');
  const seq = {};
  const owner = await ppro.Markers.getMarkers(seq);
  await owner.createMarker({ seconds: 1 }, 'Comment', 'Aymen: regrade', '');
  await addSceneMarkers(makeProject(), seq, [
    { offset_sec: 0, duration_sec: 5, name: '[4] ★ Sudan', color: 'Green' },
    { offset_sec: 10, duration_sec: 5, name: '✗ NO PART · chatter', color: 'Red' },
  ], makeLogger());
  const names = await generatedMarkerNames(seq, makeLogger());
  assert.deepEqual(names.sort(), ['[4] ★ Sudan', '✗ NO PART · chatter']);
});
