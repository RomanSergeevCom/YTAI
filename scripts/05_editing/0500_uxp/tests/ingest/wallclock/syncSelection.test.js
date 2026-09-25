const { test } = require('node:test');
const assert = require('node:assert');
const ppro = require('../../../tests/mocks/premierepro');
const { planSpread } = require('../../../src/ingest/syncSpread');
const {
  readSequenceItems, selectForSync, selectStrays,
} = require('../../../src/ingest/placement/syncSelection');

const logger = { info() {}, warn() {}, debug() {}, error() {} };

const CLIPS = [
  { clip_id: 'FX', filename: 'FX.MP4', scene: 's', wall_offset: 0.4, duration: 70, cam: 'CAM-A_FX3', sync_source: 'speech' },
  { clip_id: 'ZV', filename: 'ZV.MP4', scene: 's', wall_offset: 0.44, duration: 70, cam: 'CAM-B_ZVE1', sync_source: 'speech' },
];
const STRIPS = [
  { tx: 'TX01', filename: 'TX01.wav', wall_offset: 0, duration: 80 },
  { tx: 'TX02', filename: 'TX02.wav', wall_offset: 0, duration: 80 },
];

/**
 * Секвенция стенда, как её строит панель: камерный клип на своей паре V/A
 * (Premiere сама кладёт связанный звук на A с тем же индексом), петлички —
 * audio-only на дорожках следом. Плюс, по желанию, однокадровый огрызок
 * преднагрева на каждой дорожке.
 */
async function benchSequence(manifest, { strays = true } = {}) {
  const seq = new ppro._MockSequence('BENCH',
    { videoTracks: manifest.nVideoTracks, audioTracks: manifest.nAudioTracks });
  for (const it of manifest.items) {
    if (it.trackType === 'video') {
      (await seq.getVideoTrack(it.trackIdx))._addItem(it.filename, it.placedSec, it.duration);
      // звуковой близнец — связанная половина того же клипа
      (await seq.getAudioTrack(it.trackIdx))._addItem(it.filename, it.placedSec, it.duration);
    } else {
      (await seq.getAudioTrack(it.trackIdx))._addItem(it.filename, it.placedSec, it.duration);
    }
  }
  if (strays) {
    for (let v = 0; v < manifest.nVideoTracks; v++) {
      (await seq.getVideoTrack(v))._addItem(manifest.items[0].filename, 0.08, 0.04);
    }
    for (let a = 0; a < manifest.nAudioTracks; a++) {
      (await seq.getAudioTrack(a))._addItem(manifest.items[0].filename, 0.08, 0.04);
    }
  }
  return seq;
}

/** Сколько айтемов панель обязана выделить: манифест + звуковые близнецы камер. */
function expectedSelection(manifest) {
  return manifest.items.length + manifest.items.filter(i => i.trackType === 'video').length;
}

function fakeProject() {
  return {
    async lockedAccess(fn) { return await fn(); },
  };
}

test('читатель: отдаёт имя, дорожку, позицию и ДЛИТЕЛЬНОСТЬ', async () => {
  const { manifest } = planSpread(CLIPS, STRIPS, { mode: 'bench', fps: 25 });
  const items = await readSequenceItems(await benchSequence(manifest));
  const nReal = expectedSelection(manifest);
  const nStrays = manifest.nVideoTracks + manifest.nAudioTracks;
  assert.strictEqual(items.length, nReal + nStrays);
  // камерный клип живёт на своей паре: видеополовина + связанный звук
  const vid = items.find(i => i.filename === 'ZV.MP4' && i.trackType === 'video' && i.durationSec > 1);
  const aud = items.find(i => i.filename === 'ZV.MP4' && i.trackType === 'audio' && i.durationSec > 1);
  assert.ok(vid && aud, 'обе половины камерного клипа видны читателю');
  assert.strictEqual(vid.trackIdx, aud.trackIdx, 'звук на A с индексом своей V');
  assert.ok(typeof vid.durationSec === 'number', 'без длительности огрызок не отличить');
});

test('выделение: огрызки не попадают, по одному айтему на дорожку', async () => {
  const { manifest } = planSpread(CLIPS, STRIPS, { mode: 'bench', fps: 25 });
  const seq = await benchSequence(manifest);
  const r = await selectForSync(fakeProject(), seq, manifest, logger);
  assert.strictEqual(r.selected, expectedSelection(manifest));
  assert.strictEqual(r.skippedShort, manifest.nVideoTracks + manifest.nAudioTracks);
  assert.strictEqual(r.missing.length, 0);
  assert.ok(Object.keys(r.perTrack).every(k => r.perTrack[k] === 1));
  // и то же самое читается ОБРАТНО из секвенции
  assert.strictEqual(r.verified, expectedSelection(manifest));
  const back = await (await seq.getSelection()).getTrackItems();
  assert.ok(back.every(ti => ti._durationSec > 1), 'в выделении нет ни одного огрызка');
});

test('выделение: сперва снимается прежнее (чтобы ⌘A не примешался)', async () => {
  const { manifest } = planSpread(CLIPS, STRIPS, { mode: 'bench', fps: 25 });
  ppro._recorder.reset();
  await selectForSync(fakeProject(), await benchSequence(manifest), manifest, logger);
  const calls = ppro._recorder.calls.map(c => c.method);
  assert.ok(calls.indexOf('Sequence.clearSelection') >= 0, 'clearSelection обязан быть');
  assert.ok(calls.indexOf('Sequence.clearSelection') < calls.lastIndexOf('Sequence.setSelection'),
    'снятие идёт ДО установки');
});

test('выделение: Promise-форма setSelection (до 26.3) тоже принимается', async () => {
  const { manifest } = planSpread(CLIPS, STRIPS, { mode: 'bench', fps: 25 });
  const seq = await benchSequence(manifest);
  seq._setSelectionAsync = true;   // старый API возвращал Promise<boolean>
  const r = await selectForSync(fakeProject(), seq, manifest, logger);
  assert.strictEqual(r.applied, true);
  assert.strictEqual(r.selected, expectedSelection(manifest));
});

test('выделение: два выделяемых айтема на одной дорожке — отказ, а не тихое выделение', async () => {
  const { manifest } = planSpread(CLIPS, STRIPS, { mode: 'bench', fps: 25 });
  const seq = await benchSequence(manifest, { strays: false });
  // Человек перетащил ZV на дорожку FX. Точного совпадения по (тип, индекс)
  // для ZV больше нет, и запасная ветка matchItem находит его единственным
  // кандидатом — на УЖЕ занятой дорожке. Молча выделить оба нельзя: именно
  // такая пара и гасит Synchronize.
  (await seq.getVideoTrack(1))._items.length = 0;
  (await seq.getVideoTrack(0))._addItem('ZV.MP4', 50, 70);
  await assert.rejects(
    () => selectForSync(fakeProject(), seq, manifest, logger),
    /два выделяемых айтема/
  );
});

test('выделение: лишний клип ВНЕ манифеста не мешает — он просто не выделяется', async () => {
  const { manifest } = planSpread(CLIPS, STRIPS, { mode: 'bench', fps: 25 });
  const seq = await benchSequence(manifest, { strays: false });
  (await seq.getVideoTrack(0))._addItem('ZV_extra.MP4', 50, 70);
  const r = await selectForSync(fakeProject(), seq, manifest, logger);
  assert.strictEqual(r.selected, expectedSelection(manifest));
  assert.ok(Object.keys(r.perTrack).every(k => r.perTrack[k] === 1));
});

test('выделение: пустая секвенция — внятный отказ, а не «выделено 0»', async () => {
  const { manifest } = planSpread(CLIPS, STRIPS, { mode: 'bench', fps: 25 });
  // дорожки есть, а клипов нет — ровно то, чем оказалась _SYNC на YTUVIE01
  const seq = new ppro._MockSequence('EMPTY',
    { videoTracks: manifest.nVideoTracks, audioTracks: manifest.nAudioTracks });
  await assert.rejects(
    () => selectForSync(fakeProject(), seq, manifest, logger),
    /раскладка не легла/
  );
});

test('выделение: пропавший источник попадает в missing, остальные выделяются', async () => {
  const { manifest } = planSpread(CLIPS, STRIPS, { mode: 'bench', fps: 25 });
  const seq = await benchSequence(manifest, { strays: false });
  const tr = await seq.getAudioTrack(manifest.items[3].trackIdx);
  tr._items.length = 0;
  const r = await selectForSync(fakeProject(), seq, manifest, logger);
  assert.deepStrictEqual(r.missing, [manifest.items[3].id]);
  assert.strictEqual(r.selected, expectedSelection(manifest) - 1);
});

test('чистка: выделяет весь однокадровый мусор и ничего больше', async () => {
  const { manifest } = planSpread(CLIPS, STRIPS, { mode: 'bench', fps: 25 });
  const seq = await benchSequence(manifest);
  const r = await selectStrays(fakeProject(), seq, logger);
  assert.strictEqual(r.found, manifest.nVideoTracks + manifest.nAudioTracks);
  const back = await (await seq.getSelection()).getTrackItems();
  assert.ok(back.every(ti => ti._durationSec < 0.2), 'в выделении только огрызки');
});

test('чистка: на чистой секвенции ничего не делает', async () => {
  const { manifest } = planSpread(CLIPS, STRIPS, { mode: 'bench', fps: 25 });
  const r = await selectStrays(fakeProject(), await benchSequence(manifest, { strays: false }), logger);
  assert.strictEqual(r.found, 0);
});
