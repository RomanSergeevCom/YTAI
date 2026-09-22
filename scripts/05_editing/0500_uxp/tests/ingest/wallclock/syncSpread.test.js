const { test } = require('node:test');
const assert = require('node:assert');
const {
  planSpread,
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

test('collect: moved lav is captured with sign (right = +)', () => {
  const { manifest } = planSpread(CLIPS, STRIPS);
  const d = collectDeltas(manifest, actualFromManifest(manifest, { 'T1.wav': -0.312, C2: 0.044 }));
  assert.ok(Math.abs(d.txFiles['T1.wav'] + 0.312) < 1e-9);
  assert.ok(Math.abs(d.clips.C2 - 0.044) < 1e-9);
  assert.strictEqual(d.moved, 2);
  assert.ok(Math.abs(d.maxAbsSec - 0.312) < 1e-9);
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

test('apply: wall_offset moves by delta, stamp set, source untouched elsewhere', () => {
  const r = applyDeltasToIngest(fakeIngest(), 's',
    { clips: { C2: 0.044 }, txFiles: { 'T1.wav': -0.312 } }, '2026-08-16T21:00:00');
  const c2 = r.ingest.clips.find(c => c.clip_id === 'C2');
  assert.ok(Math.abs(c2.wall_offset - 130.544) < 1e-9);
  const t1 = r.ingest.tx_strips.s.find(t => t.filename === 'T1.wav');
  assert.ok(Math.abs(t1.wall_offset - 94.688) < 1e-9);
  const c1 = r.ingest.clips.find(c => c.clip_id === 'C1');
  assert.strictEqual(c1.wall_offset, 100.0);
  assert.strictEqual(r.ingest.fine_sync.method, 'premiere-synchronize');
  assert.strictEqual(r.applied, 2);
});

test('apply: negative offsets re-normalized, whole scene shifts together', () => {
  const r = applyDeltasToIngest(fakeIngest(), 's',
    { clips: {}, txFiles: { 'T1.wav': -96.0 } }, '2026-08-16T21:00:00');
  // T1 went to -1.0 → scene shifted +1.0
  assert.strictEqual(r.normalizedShift, 1.0);
  const t1 = r.ingest.tx_strips.s.find(t => t.filename === 'T1.wav');
  assert.ok(Math.abs(t1.wall_offset - 0) < 1e-9);
  const c1 = r.ingest.clips.find(c => c.clip_id === 'C1');
  assert.ok(Math.abs(c1.wall_offset - 101.0) < 1e-9);
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
  assert.ok(Math.abs(d.clips.C2 - 0.1) < 1e-9, `C2 delta lost: ${d.clips.C2}`);
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
