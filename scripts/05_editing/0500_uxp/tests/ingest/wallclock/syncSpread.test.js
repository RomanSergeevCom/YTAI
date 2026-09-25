const { test } = require('node:test');
const assert = require('node:assert');
const {
  planSpread,
  assertSpreadContract,
  chooseSyncItems,
  collectDeltas,
  applyDeltasToIngest,
} = require('../../../src/ingest/syncSpread');

const CLIPS = [
  { clip_id: 'C1', filename: 'C1.MP4', scene: 's', wall_offset: 100.0, duration: 10, creation_time: '2026-04-02T09:01:40Z' },
  { clip_id: 'C2', filename: 'C2.MP4', scene: 's', wall_offset: 130.5, duration: 20, creation_time: '2026-04-02T09:02:10Z' },
];
const STRIPS = [
  { tx: 'TX01', filename: 'T1.wav', wall_offset: 95.0, duration: 1800, creation_time: '2026-04-02T09:01:35Z' },
  { tx: 'TX02', filename: 'T2.wav', wall_offset: 96.0, duration: 1800, creation_time: '2026-04-02T09:01:36Z' },
];

// ─── planSpread ──────────────────────────────────────────────────────────

test('spread: one source per track, raw offsets, preroll', () => {
  const { placements, manifest } = planSpread(CLIPS, STRIPS);
  // t0 = 95 (earliest strip), preroll 30
  const c1 = placements.find(p => p.clipId === 'C1');
  assert.strictEqual(c1.vIdx, 0);
  assert.strictEqual(c1.aIdx, 0);
  assert.ok(Math.abs(c1.offsetSec - (100.0 - 95.0 + 30)) < 1e-9);
  const c2 = placements.find(p => p.clipId === 'C2');
  assert.strictEqual(c2.vIdx, 1);
  // lav files: own audio tracks AFTER the clips, whole files (no source in point)
  const t1 = placements.find(p => p.filename === 'T1.wav');
  assert.strictEqual(t1.vIdx, -1);
  assert.strictEqual(t1.aIdx, 2);
  assert.ok(Math.abs(t1.offsetSec - 30) < 1e-9);
  assert.strictEqual(t1.sourceInPoint, undefined);
  // manifest mirrors every placement
  assert.strictEqual(manifest.items.length, 4);
  assert.strictEqual(manifest.nVideoTracks, 2);
  assert.strictEqual(manifest.nAudioTracks, 4);
});

test('spread: empty scene → warning, no manifest', () => {
  const r = planSpread([], []);
  assert.strictEqual(r.manifest, null);
  assert.strictEqual(r.warnings[0].type, 'empty_scene');
});

// ─── collectDeltas ───────────────────────────────────────────────────────

function actualFromManifest(manifest, moves = {}) {
  return manifest.items.map(it => ({
    filename: it.filename,
    trackType: it.trackType,
    trackIdx: it.trackIdx,
    startSec: it.placedSec + (moves[it.id] || 0),
  }));
}

test('collect: unmoved items give zero delta', () => {
  const { manifest } = planSpread(CLIPS, STRIPS);
  const d = collectDeltas(manifest, actualFromManifest(manifest));
  assert.strictEqual(d.moved, 0);
  assert.strictEqual(d.clips.C1, 0);
  assert.strictEqual(d.txFiles['T1.wav'], 0);
});

test('collect: moved lav is captured with sign (right = +), minus the group base', () => {
  const { manifest } = planSpread(CLIPS, STRIPS);
  const d = collectDeltas(manifest, actualFromManifest(manifest, { 'T1.wav': -0.312, C2: 0.044 }));
  // опорные клипы сдвинулись на 0 и +0.044 → база = медиана = 0.022
  assert.ok(Math.abs(d.base - 0.022) < 1e-9, `base=${d.base}`);
  // сырая дельта сохранена для отчёта…
  assert.ok(Math.abs(d.raw['T1.wav'] + 0.312) < 1e-9);
  // …а в ингест пойдёт ОСТАТОК: -0.312 - 0.022
  assert.ok(Math.abs(d.txFiles['T1.wav'] + 0.334) < 1e-9);
  assert.ok(Math.abs(d.clips.C2 - 0.022) < 1e-9);
  assert.ok(Math.abs(d.clips.C1 + 0.022) < 1e-9);
  assert.ok(Math.abs(d.maxAbsSec - 0.334) < 1e-9);
});

test('collect: одинаковый сдвиг ВСЕХ источников синхронно пуст — не двигается ничего', () => {
  const { manifest } = planSpread(CLIPS, STRIPS);
  const moves = {};
  manifest.items.forEach(i => { moves[i.id] = 1.0; });
  const d = collectDeltas(manifest, actualFromManifest(manifest, moves));
  assert.strictEqual(d.moved, 0, 'общий сдвиг не должен порождать правок');
  assert.ok(Math.abs(d.base - 1.0) < 1e-9);
});

test('collect: sub-2ms jitter is treated as no move', () => {
  const { manifest } = planSpread(CLIPS, STRIPS);
  const d = collectDeltas(manifest, actualFromManifest(manifest, { C1: 0.0015 }));
  assert.strictEqual(d.clips.C1, 0);
  assert.strictEqual(d.moved, 0);
});

test('collect: deleted item lands in missing, not in deltas', () => {
  const { manifest } = planSpread(CLIPS, STRIPS);
  const actual = actualFromManifest(manifest).filter(a => a.filename !== 'T2.wav');
  const d = collectDeltas(manifest, actual);
  assert.deepStrictEqual(d.missing, ['T2.wav']);
  assert.strictEqual(d.txFiles['T2.wav'], undefined);
});

// ─── applyDeltasToIngest ─────────────────────────────────────────────────

function fakeIngest() {
  return {
    project_name: 'X', clips: JSON.parse(JSON.stringify(CLIPS)),
    tx_strips: { s: JSON.parse(JSON.stringify(STRIPS)) },
    media: { fps: 25 },
  };
}

test('apply: клипу wall_offset двигается, петличку НЕ пишем — только отчёт', () => {
  const r = applyDeltasToIngest(fakeIngest(), 's',
    { clips: { C2: 0.044 }, txFiles: { 'T1.wav': -0.312 } }, '2026-08-16T21:00:00');
  const c2 = r.ingest.clips.find(c => c.clip_id === 'C2');
  assert.ok(Math.abs(c2.wall_offset - 130.544) < 1e-9);
  // ⚠️ tx_strips — это рендеры 0113. Двигать им число значит обесценить рендер.
  const t1 = r.ingest.tx_strips.s.find(t => t.filename === 'T1.wav');
  assert.strictEqual(t1.wall_offset, 95.0, 'петличка обязана остаться нетронутой');
  assert.strictEqual(t1.fine_sync, undefined);
  assert.deepStrictEqual(r.txReported, [{ filename: 'T1.wav', resid: -0.312 }]);
  const c1 = r.ingest.clips.find(c => c.clip_id === 'C1');
  assert.strictEqual(c1.wall_offset, 100.0);
  assert.strictEqual(r.ingest.fine_sync.method, 'premiere-synchronize');
  assert.strictEqual(r.applied, 1);
});

test('apply: negative offsets re-normalized, whole scene shifts together', () => {
  const r = applyDeltasToIngest(fakeIngest(), 's',
    { clips: { C1: -101.0 }, txFiles: {} }, '2026-08-16T21:00:00');
  // C1 ушёл в -1.0 → сцена целиком сдвигается на +1.0
  assert.strictEqual(r.normalizedShift, 1.0);
  const c1 = r.ingest.clips.find(c => c.clip_id === 'C1');
  assert.ok(Math.abs(c1.wall_offset - 0) < 1e-9);
  const c2 = r.ingest.clips.find(c => c.clip_id === 'C2');
  assert.ok(Math.abs(c2.wall_offset - 131.5) < 1e-9, 'нетронутый клип едет вместе со сценой');
  const t1 = r.ingest.tx_strips.s.find(t => t.filename === 'T1.wav');
  assert.ok(Math.abs(t1.wall_offset - 96.0) < 1e-9, 'петличка едет общим сдвигом, но не своей дельтой');
});

test('apply: порог записи гасит правку меньше кадра', () => {
  const r = applyDeltasToIngest(fakeIngest(), 's',
    { clips: { C2: 0.012 }, txFiles: {} }, 'now', { minWriteSec: 1 / 25 });
  assert.strictEqual(r.applied, 0);
  assert.strictEqual(r.ingest.clips.find(c => c.clip_id === 'C2').wall_offset, 130.5);
});

test('apply: no moves → no stamp, ingest equal to source', () => {
  const src = fakeIngest();
  const r = applyDeltasToIngest(src, 's', { clips: { C1: 0 }, txFiles: {} }, 'now');
  assert.strictEqual(r.applied, 0);
  assert.strictEqual(r.ingest.fine_sync, undefined);
});

test('apply: does not mutate the input ingest', () => {
  const src = fakeIngest();
  applyDeltasToIngest(src, 's', { clips: { C2: 5 }, txFiles: {} }, 'now');
  assert.strictEqual(src.clips.find(c => c.clip_id === 'C2').wall_offset, 130.5);
});

// ─── review-confirmed edge cases (adversarial workflow 2026-08-16) ───────

test('spread: strip without wall_offset raises its own warning', () => {
  const strips = JSON.parse(JSON.stringify(STRIPS));
  delete strips[1].wall_offset;
  const { warnings, manifest } = planSpread(CLIPS, strips);
  assert.ok(warnings.some(w => w.type === 'strips_without_offset' && w.count === 1));
  assert.strictEqual(manifest.nAudioTracks, 3); // 2 clips + 1 remaining strip
});

test('collect: clip dragged to another track is recovered via same-type unique match', () => {
  const { manifest } = planSpread(CLIPS, STRIPS);
  const actual = actualFromManifest(manifest, { C2: 0.1 }).map(a => {
    // C2 lives as video/1 AND (linked audio) — simulate both entries, with the
    // video part dragged to track 3
    if (a.filename === 'C2.MP4' && a.trackType === 'video') return { ...a, trackIdx: 3 };
    return a;
  });
  // add the linked-audio twin of C2 (same filename, audio track, unmoved index)
  actual.push({ filename: 'C2.MP4', trackType: 'audio', trackIdx: 1, startSec: manifest.items.find(i => i.id === 'C2').placedSec + 0.1 });
  const d = collectDeltas(manifest, actual);
  // сырая дельта — то, что проверял этот тест до вычитания базы
  assert.ok(Math.abs(d.raw.C2 - 0.1) < 1e-9, `C2 delta lost: ${d.raw.C2}`);
  assert.strictEqual(d.missing.length, 0);
});

test('apply: throws on a scene with clips lacking wall_offset (partial-shift guard)', () => {
  const src = fakeIngest();
  delete src.clips[1].wall_offset;
  assert.throws(
    () => applyDeltasToIngest(src, 's', { clips: {}, txFiles: { 'T1.wav': -96.0 } }, 'now'),
    /no wall_offset/
  );
});

// ─── звуковой стенд: режим audio, контракт, отбор выделения ──────────────

/** Сцена как на YTUVIE01: две камеры, экран и ролик-пример, две петлички. */
const BENCH_CLIPS = [
  { clip_id: 'FX', filename: 'FX.MP4', scene: 's', wall_offset: 0.418, duration: 70, cam: 'CAM-A_FX3', sync_source: 'speech' },
  { clip_id: 'ZV', filename: 'ZV.MP4', scene: 's', wall_offset: 0.438, duration: 70, cam: 'CAM-B_ZVE1', sync_source: 'speech' },
  { clip_id: 'SCR', filename: 'scr.mov', scene: 's', wall_offset: 0.0, duration: 60, cam: 'Screencast', sync_source: 'lesson_start' },
  { clip_id: 'REF', filename: 'ref.mp4', scene: 's', wall_offset: 30.0, duration: 20, cam: 'Referensy', sync_source: 'shown_on_screen' },
];
const BENCH_STRIPS = [
  { tx: 'TX01', filename: 'TX01.wav', wall_offset: 0.0, duration: 80 },
  { tx: 'TX02', filename: 'TX02.wav', wall_offset: 0.0, duration: 80 },
];

test('стенд: экран и ролик исключены, камеры на своих парах V/A, петлички audio-only', () => {
  const { placements, manifest, warnings } = planSpread(BENCH_CLIPS, BENCH_STRIPS,
    { mode: 'bench', fps: 25 });
  assert.strictEqual(manifest.mode, 'bench');
  assert.strictEqual(manifest.version, 2);
  // 2 камеры → V1/V2 + A1/A2, две петлички → A3/A4
  assert.strictEqual(manifest.nVideoTracks, 2);
  assert.strictEqual(manifest.nAudioTracks, 4);
  // ⚠️ Камере нужна СВОЯ видеодорожка: audio-only вставка A/V-клипа не работает,
  // Premiere кладёт видео на V1 — и тогда на одной дорожке оказывается всё сразу.
  const cams = placements.filter(p => p.kind === 'video');
  assert.deepStrictEqual(cams.map(p => p.vIdx), [0, 1]);
  assert.deepStrictEqual(cams.map(p => p.aIdx), [0, 1]);
  const lav = placements.filter(p => p.kind === 'txfull');
  assert.ok(lav.every(p => p.vIdx === -1), 'петличка — настоящий WAV, audio-only работает');
  // исключённые не пропали молча
  const ex = warnings.find(w => w.type === 'excluded_shown');
  assert.deepStrictEqual(ex.ids.sort(), ['REF', 'SCR']);
  assert.ok(!manifest.items.some(i => i.id === 'SCR' || i.id === 'REF'));
});

test('стенд: позиции квантованы к кадровой сетке', () => {
  const { manifest } = planSpread(BENCH_CLIPS, BENCH_STRIPS, { mode: 'bench', fps: 25 });
  for (const it of manifest.items) {
    const frames = it.placedSec * 25;
    assert.ok(Math.abs(frames - Math.round(frames)) < 1e-9,
      `${it.id} стоит вне сетки: ${it.placedSec}`);
  }
});

test('контракт: чистая раскладка проходит', () => {
  const { manifest } = planSpread(BENCH_CLIPS, BENCH_STRIPS, { mode: 'bench', fps: 25 });
  assert.strictEqual(assertSpreadContract(manifest), true);
});

test('контракт L1: два источника на одной дорожке — отказ', () => {
  const { manifest } = planSpread(BENCH_CLIPS, BENCH_STRIPS, { mode: 'bench', fps: 25 });
  manifest.items[1].trackIdx = manifest.items[0].trackIdx;
  assert.throws(() => assertSpreadContract(manifest), /^Error: L1:/);
});

test('контракт L2: без преролла Premiere не сдвинет клип влево — отказ', () => {
  const { manifest } = planSpread(BENCH_CLIPS, BENCH_STRIPS,
    { mode: 'bench', fps: 25, preroll: 0 });
  assert.throws(() => assertSpreadContract(manifest), /^Error: L2:/);
});

test('контракт L5: источник, не пересекающийся ни с чем — отказ', () => {
  const clips = JSON.parse(JSON.stringify(BENCH_CLIPS));
  clips.push({ clip_id: 'LONE', filename: 'lone.MP4', scene: 's',
    wall_offset: 5000, duration: 10, cam: 'CAM-A_FX3', sync_source: 'speech' });
  const { manifest } = planSpread(clips, BENCH_STRIPS, { mode: 'bench', fps: 25 });
  assert.throws(() => assertSpreadContract(manifest), /^Error: L5:.*LONE/);
});

test('контракт L9: предел считается по ДОРОЖКАМ, а не по клипам', () => {
  // 4 клипа (из них 2 опорных) и 45 петличек: старая гвардия стояла на КЛИПАХ
  // и такую сцену пропустила бы, а дорожек тут 49 (V2 + A2 под камеры + A45)
  // при пределе 40.
  const strips = [];
  for (let i = 0; i < 45; i++) {
    strips.push({ tx: 'TX' + i, filename: 'T' + i + '.wav', wall_offset: 0, duration: 80 });
  }
  const { manifest } = planSpread(BENCH_CLIPS, strips, { mode: 'bench', fps: 25 });
  assert.ok(manifest.items.filter(i => i.kind === 'clip').length < 40, 'клипов мало');
  assert.throws(() => assertSpreadContract(manifest), /^Error: L9:.*49 tracks/);
});

// ─── chooseSyncItems ────────────────────────────────────────────────────

/** Таймлайн, каким его читает панель: манифестные клипы + мусор преднагрева. */
function benchTimeline(manifest, { withStrays = true } = {}) {
  const items = manifest.items.map((it, n) => ({
    filename: it.filename, trackType: it.trackType, trackIdx: it.trackIdx,
    startSec: it.placedSec, durationSec: it.duration, ref: 'real' + n,
  }));
  if (withStrays) {
    // ⚠️ Огрызок носит имя НАСТОЯЩЕГО клипа и лежит на его же дорожке —
    // ровно как RYA-FX3-1263 на YTUVIE01.
    manifest.items.forEach((it, n) => {
      items.push({ filename: manifest.items[0].filename, trackType: it.trackType,
        trackIdx: it.trackIdx, startSec: 0.08, durationSec: 0.04, ref: 'stray' + n });
    });
  }
  return items;
}

test('отбор: огрызок с именем настоящего клипа не перехватывает выделение', () => {
  const { manifest } = planSpread(BENCH_CLIPS, BENCH_STRIPS, { mode: 'bench', fps: 25 });
  const r = chooseSyncItems(manifest, benchTimeline(manifest));
  assert.strictEqual(r.chosen.length, manifest.items.length);
  assert.strictEqual(r.maxPerTrack, 1, 'по одному айтему на дорожку');
  assert.strictEqual(r.missing.length, 0);
  assert.ok(r.chosen.every(c => String(c.ref).startsWith('real')),
    'в выделение попали только настоящие клипы');
  assert.strictEqual(r.skippedShort.length, manifest.items.length);
});

test('отбор: удалённый источник попадает в missing, а не молча теряется', () => {
  const { manifest } = planSpread(BENCH_CLIPS, BENCH_STRIPS, { mode: 'bench', fps: 25 });
  const tl = benchTimeline(manifest, { withStrays: false })
    .filter(a => a.filename !== 'TX02.wav');
  const r = chooseSyncItems(manifest, tl);
  assert.deepStrictEqual(r.missing, ['TX02.wav']);
  assert.strictEqual(r.chosen.length, manifest.items.length - 1);
});

test('отбор: два настоящих клипа на одной дорожке видны как maxPerTrack > 1', () => {
  const { manifest } = planSpread(BENCH_CLIPS, BENCH_STRIPS, { mode: 'bench', fps: 25 });
  const tl = benchTimeline(manifest, { withStrays: false });
  // второй айтем переехал на дорожку первого
  tl[1].trackIdx = tl[0].trackIdx;
  const r = chooseSyncItems(manifest, tl);
  assert.ok(r.maxPerTrack > 1, 'конфликт обязан быть виден вызывающему');
});

test('отбор: исключённый из раскладки источник не выделяется вовсе', () => {
  const { manifest } = planSpread(BENCH_CLIPS, BENCH_STRIPS, { mode: 'bench', fps: 25 });
  const tl = benchTimeline(manifest, { withStrays: false });
  tl.push({ filename: 'scr.mov', trackType: 'video', trackIdx: 0,
            startSec: 30, durationSec: 60, ref: 'screen' });
  const r = chooseSyncItems(manifest, tl);
  assert.ok(!r.chosen.some(c => c.filename === 'scr.mov'));
});

test('collect: база ложится на кадровую сетку, а не между кадрами', () => {
  // Premiere кладёт клипы только на целые кадры. При чётном числе источников
  // медиана встаёт МЕЖДУ двумя значениями — и вычитание такой базы сдвинуло бы
  // каждый клип на полкадра, чего не показывал ни один замер.
  const { manifest } = planSpread(BENCH_CLIPS, BENCH_STRIPS, { mode: 'bench', fps: 25 });
  const frame = 1 / 25;
  const moves = {};
  // две камеры: одна не сдвинулась, вторая ровно на кадр → медиана = полкадра
  const cams = manifest.items.filter(i => i.kind === 'clip');
  moves[cams[0].id] = 0;
  moves[cams[1].id] = frame;
  const d = collectDeltas(manifest, actualFromManifest(manifest, moves));
  assert.ok(Math.abs(d.base / frame - Math.round(d.base / frame)) < 1e-9,
    `база ${d.base * 1000} мс не на сетке`);
  // и остатки тоже целокадровые
  for (const id of Object.keys(d.clips)) {
    const f = d.clips[id] / frame;
    assert.ok(Math.abs(f - Math.round(f)) < 1e-9, `остаток ${id} = ${f} кадра`);
  }
});
