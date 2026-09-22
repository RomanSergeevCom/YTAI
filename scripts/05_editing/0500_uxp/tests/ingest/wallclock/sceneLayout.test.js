const { test } = require('node:test');
const assert = require('node:assert');
const {
  parseUtcISO,
  computeSceneT0,
  computeOffsetSec,
  computeVideoUnion,
  plan,
} = require('../../../src/ingest/layout/sceneLayout');

// ─── parseUtcISO ─────────────────────────────────────────────────────────

test('parseUtcISO: ISO with Z', () => {
  const d = parseUtcISO('2026-04-02T09:01:47.000000Z');
  assert.strictEqual(d.toISOString(), '2026-04-02T09:01:47.000Z');
});

test('parseUtcISO: ISO with offset', () => {
  const d = parseUtcISO('2026-04-02T13:01:47+04:00');
  assert.strictEqual(d.toISOString(), '2026-04-02T09:01:47.000Z');
});

test('parseUtcISO: naive timestamp assumed UTC (non-strict)', () => {
  const d = parseUtcISO('2026-04-02T09:01:47');
  assert.strictEqual(d.toISOString(), '2026-04-02T09:01:47.000Z');
});

test('parseUtcISO: strict mode throws on naive timestamp', () => {
  assert.throws(() => parseUtcISO('2026-04-02T09:01:47', { strict: true }), /naive timestamp/);
});

test('parseUtcISO: invalid input throws', () => {
  assert.throws(() => parseUtcISO(''), /invalid input/);
  assert.throws(() => parseUtcISO('not-a-date'), /unparseable/);
});

// ─── computeSceneT0 ──────────────────────────────────────────────────────

test('computeSceneT0: returns min across clips and txStrips', () => {
  const clips = [
    { creation_time: '2026-04-02T09:01:47Z' },
    { creation_time: '2026-04-02T09:03:22Z' },
  ];
  const txStrips = [{ creation_time: '2026-04-02T09:00:00Z' }];
  const t0 = computeSceneT0(clips, txStrips);
  // Should be 09:00:00 (TX is earliest)
  assert.strictEqual(t0, new Date('2026-04-02T09:00:00Z').getTime() / 1000);
});

test('computeSceneT0: clips only', () => {
  const clips = [
    { creation_time: '2026-04-02T09:01:47Z' },
    { creation_time: '2026-04-02T09:03:22Z' },
  ];
  const t0 = computeSceneT0(clips);
  assert.strictEqual(t0, new Date('2026-04-02T09:01:47Z').getTime() / 1000);
});

test('computeSceneT0: empty throws', () => {
  assert.throws(() => computeSceneT0([], []), /no clips/);
});

test('computeSceneT0: strict mode throws on missing creation_time', () => {
  assert.throws(
    () => computeSceneT0([{ filename: 'x.MP4' }], [], { strict: true }),
    /missing creation_time/
  );
});

// ─── computeOffsetSec ────────────────────────────────────────────────────

test('computeOffsetSec: prefers wall_offset when present', () => {
  assert.strictEqual(computeOffsetSec({ wall_offset: 83.5 }, 999), 83.5);
});

test('computeOffsetSec: falls back to creation_time', () => {
  const t0 = new Date('2026-04-02T09:01:47Z').getTime() / 1000;
  const offset = computeOffsetSec({ creation_time: '2026-04-02T09:03:10Z' }, t0);
  assert.strictEqual(offset, 83);
});

test('computeOffsetSec: microsecond precision preserved', () => {
  const t0 = new Date('2026-04-02T09:01:47.000000Z').getTime() / 1000;
  const offset = computeOffsetSec({ creation_time: '2026-04-02T09:01:47.123456Z' }, t0);
  assert.ok(Math.abs(offset - 0.123) < 0.001); // ms precision in JS Date
});

test('computeOffsetSec: throws on negative offset', () => {
  const t0 = new Date('2026-04-02T09:01:47Z').getTime() / 1000;
  assert.throws(
    () => computeOffsetSec({ creation_time: '2026-04-02T09:00:00Z' }, t0),
    /negative offset/
  );
});

// ─── computeVideoUnion ───────────────────────────────────────────────────

test('computeVideoUnion: single interval', () => {
  const placements = [{ offsetSec: 0, duration: 10 }];
  assert.deepStrictEqual(computeVideoUnion(placements), [[0, 10]]);
});

test('computeVideoUnion: non-overlapping → two intervals', () => {
  const placements = [
    { offsetSec: 0, duration: 10 },
    { offsetSec: 20, duration: 5 },
  ];
  assert.deepStrictEqual(computeVideoUnion(placements), [[0, 10], [20, 25]]);
});

test('computeVideoUnion: overlapping merges', () => {
  const placements = [
    { offsetSec: 0, duration: 10 },
    { offsetSec: 5, duration: 10 }, // overlaps with first
    { offsetSec: 20, duration: 5 },
  ];
  assert.deepStrictEqual(computeVideoUnion(placements), [[0, 15], [20, 25]]);
});

test('computeVideoUnion: touching intervals merge', () => {
  const placements = [
    { offsetSec: 0, duration: 10 },
    { offsetSec: 10, duration: 5 }, // touches at 10
  ];
  assert.deepStrictEqual(computeVideoUnion(placements), [[0, 15]]);
});

test('computeVideoUnion: empty → empty', () => {
  assert.deepStrictEqual(computeVideoUnion([]), []);
});

test('computeVideoUnion: nested intervals from different V-tracks', () => {
  // Simulates DJI on V1 [0,30] with iPhone on V2 [5,15] inside
  const placements = [
    { offsetSec: 0, duration: 30, vIdx: 0 },
    { offsetSec: 5, duration: 10, vIdx: 1 },
  ];
  assert.deepStrictEqual(computeVideoUnion(placements), [[0, 30]]);
});

// ─── plan: integration ──────────────────────────────────────────────────

test('plan: empty scene returns empty plan with warning', () => {
  const p = plan([]);
  assert.strictEqual(p.placements.length, 0);
  assert.deepStrictEqual(p.warnings, [{ type: 'empty_scene' }]);
});

test('plan: 1-cam scene without TX', () => {
  const clips = [
    {
      clip_id: 'A',
      filename: 'A.MP4',
      path: '/a/05_property_tour/FX3A/A.MP4',
      duration: 10,
      wall_offset: 0,
      creation_time: '2026-04-02T16:00:00Z',
    },
    {
      clip_id: 'B',
      filename: 'B.MP4',
      path: '/a/05_property_tour/FX3A/B.MP4',
      duration: 15,
      wall_offset: 30,
      creation_time: '2026-04-02T16:00:30Z',
    },
  ];
  const p = plan(clips, [], null, { compress: false }); // raw placement (compression tested separately)
  assert.deepStrictEqual(p.cam_layers, { FX3A: 0 });
  assert.strictEqual(p.tx_aIdx_base, 1);
  assert.strictEqual(p.placements.length, 2);
  assert.strictEqual(p.placements[0].vIdx, 0);
  assert.strictEqual(p.placements[0].aIdx, 0);
  assert.strictEqual(p.placements[0].offsetSec, 0);
  assert.strictEqual(p.placements[1].offsetSec, 30);
  assert.strictEqual(p.warnings.length, 0);
});

test('plan: 2-cam scene (DJI+iPhone) like S03', () => {
  const clips = [
    {
      clip_id: 'DJI_0075', filename: 'DJI_0075.MP4',
      path: '/a/03_developer_meeting/DJI/DJI_0075.MP4',
      duration: 23, wall_offset: 0,
      creation_time: '2026-04-02T09:01:47Z',
    },
    {
      clip_id: 'DJI_0076', filename: 'DJI_0076.MP4',
      path: '/a/03_developer_meeting/DJI/DJI_0076.MP4',
      duration: 5, wall_offset: 95,
      creation_time: '2026-04-02T09:03:22Z',
    },
    {
      clip_id: 'IMG_2868', filename: 'IMG_2868.MOV',
      path: '/a/03_developer_meeting/iPhone/IMG_2868.MOV',
      duration: 6, wall_offset: 2080,
      creation_time: '2026-04-02T09:36:27Z',
    },
  ];
  const p = plan(clips);
  assert.deepStrictEqual(p.cam_layers, { DJI: 0, iPhone: 1 });
  assert.strictEqual(p.tx_aIdx_base, 2);
  // DJI clips on vIdx=0, iPhone on vIdx=1
  const djiPlacements = p.placements.filter(pl => pl.cam === 'DJI');
  const iphonePlacements = p.placements.filter(pl => pl.cam === 'iPhone');
  assert.strictEqual(djiPlacements.length, 2);
  assert.strictEqual(iphonePlacements.length, 1);
  assert.strictEqual(djiPlacements[0].vIdx, 0);
  assert.strictEqual(iphonePlacements[0].vIdx, 1);
});

test('plan: 3-cam scene (FX3+FX3A+iPhone) like S04', () => {
  const clips = [
    { clip_id: 'fx3-1',  filename: 'A.MP4', path: '/a/04_with_wife/FX3/A.MP4',   duration: 10, wall_offset: 0,  creation_time: '2026-04-02T10:00:00Z' },
    { clip_id: 'fx3a-1', filename: 'B.MP4', path: '/a/04_with_wife/FX3A/B.MP4',  duration: 8,  wall_offset: 15, creation_time: '2026-04-02T10:00:15Z' },
    { clip_id: 'iph-1',  filename: 'C.MOV', path: '/a/04_with_wife/iPhone/C.MOV', duration: 5, wall_offset: 30, creation_time: '2026-04-02T10:00:30Z' },
  ];
  const p = plan(clips);
  assert.deepStrictEqual(p.cam_layers, { FX3: 0, FX3A: 1, iPhone: 2 });
  assert.strictEqual(p.tx_aIdx_base, 3);
  assert.strictEqual(p.placements.length, 3);
  assert.strictEqual(p.placements.find(pl => pl.cam === 'iPhone').vIdx, 2);
});

test('plan: TX placement video-bounded (Path B++)', () => {
  // Scene: 2 video clips with 5s gap, TX covers whole timeframe
  const clips = [
    { clip_id: 'A', filename: 'A.MP4', path: '/a/03/FX3/A.MP4', duration: 10, wall_offset: 0,  creation_time: '2026-04-02T10:00:00Z' },
    { clip_id: 'B', filename: 'B.MP4', path: '/a/03/FX3/B.MP4', duration: 5,  wall_offset: 15, creation_time: '2026-04-02T10:00:15Z' },
  ];
  const txStrips = [{
    tx: 'TX00', filename: 'tx.wav', path: '/a/tx.wav',
    duration: 100, wall_offset: 0,
    creation_time: '2026-04-02T10:00:00Z', sample_rate: 48000,
  }];
  const p = plan(clips, txStrips, null, { compress: false }); // raw offsets

  const txPlacements = p.placements.filter(pl => pl.kind === 'tx');
  // Should produce 2 TrackItems — one per video clip (gap NOT covered)
  assert.strictEqual(txPlacements.length, 2);
  assert.strictEqual(txPlacements[0].offsetSec, 0);
  assert.strictEqual(txPlacements[0].duration, 10);
  assert.strictEqual(txPlacements[0].sourceInPoint, 0);
  assert.strictEqual(txPlacements[1].offsetSec, 15);
  assert.strictEqual(txPlacements[1].duration, 5);
  assert.strictEqual(txPlacements[1].sourceInPoint, 15);
  assert.strictEqual(txPlacements[0].vIdx, -1); // audio-only
});

test('plan: TX starts later than video → only later portion has TX', () => {
  const clips = [
    { clip_id: 'A', filename: 'A.MP4', path: '/a/FX3/A.MP4', duration: 20, wall_offset: 0,  creation_time: '2026-04-02T10:00:00Z' },
  ];
  // TX starts at offset 5s (5 seconds after video start)
  const txStrips = [{
    tx: 'TX00', filename: 'tx.wav', path: '/a/tx.wav',
    duration: 100, wall_offset: 5,
    creation_time: '2026-04-02T10:00:05Z', sample_rate: 48000,
  }];
  const p = plan(clips, txStrips);
  const txPlacements = p.placements.filter(pl => pl.kind === 'tx');
  assert.strictEqual(txPlacements.length, 1);
  assert.strictEqual(txPlacements[0].offsetSec, 5);
  assert.strictEqual(txPlacements[0].duration, 15); // from 5s to 20s
  assert.strictEqual(txPlacements[0].sourceInPoint, 0); // TX source starts at its own beginning
});

test('plan: TX completely outside video → warning, no placements', () => {
  const clips = [
    { clip_id: 'A', filename: 'A.MP4', path: '/a/FX3/A.MP4', duration: 10, wall_offset: 0, creation_time: '2026-04-02T10:00:00Z' },
  ];
  const txStrips = [{
    tx: 'TX00', filename: 'tx.wav', path: '/a/tx.wav',
    duration: 20, wall_offset: 100,
    creation_time: '2026-04-02T10:01:40Z', sample_rate: 48000,
  }];
  const p = plan(clips, txStrips);
  const txPlacements = p.placements.filter(pl => pl.kind === 'tx');
  assert.strictEqual(txPlacements.length, 0);
  const warning = p.warnings.find(w => w.type === 'tx_no_video_overlap');
  assert.ok(warning);
});

test('plan: two TX strips → tx_aIdx_base + i for each', () => {
  const clips = [
    { clip_id: 'A', filename: 'A.MP4', path: '/a/FX3/A.MP4',  duration: 10, wall_offset: 0, creation_time: '2026-04-02T10:00:00Z' },
    { clip_id: 'B', filename: 'B.MOV', path: '/a/iPhone/B.MOV', duration: 10, wall_offset: 0, creation_time: '2026-04-02T10:00:00Z' },
  ];
  const txStrips = [
    { tx: 'TX01', filename: 'tx1.wav', path: '/a/tx1.wav', duration: 15, wall_offset: 0, creation_time: '2026-04-02T10:00:00Z', sample_rate: 48000 },
    { tx: 'TX02', filename: 'tx2.wav', path: '/a/tx2.wav', duration: 15, wall_offset: 0, creation_time: '2026-04-02T10:00:00Z', sample_rate: 48000 },
  ];
  const p = plan(clips, txStrips);
  assert.strictEqual(p.tx_aIdx_base, 2); // FX3=0, iPhone=1 → base=2
  const txAIdx = new Set(p.placements.filter(pl => pl.kind === 'tx').map(pl => pl.aIdx));
  assert.deepStrictEqual([...txAIdx].sort(), [2, 3]); // TX01 on A3 (aIdx=2), TX02 on A4 (aIdx=3)
});

test('plan: overlapping video clips on same cam emit warning', () => {
  const clips = [
    { clip_id: 'A', filename: 'A.MP4', path: '/a/FX3/A.MP4', duration: 30, wall_offset: 0,  creation_time: '2026-04-02T10:00:00Z' },
    { clip_id: 'B', filename: 'B.MP4', path: '/a/FX3/B.MP4', duration: 30, wall_offset: 20, creation_time: '2026-04-02T10:00:20Z' },
  ];
  const p = plan(clips);
  const overlap = p.warnings.find(w => w.type === 'overlap');
  assert.ok(overlap);
  assert.strictEqual(overlap.winner, 'B');
  assert.strictEqual(overlap.loser, 'A');
});

test('plan: explicit cam_layers override wins', () => {
  const clips = [
    { clip_id: 'A', filename: 'A.MP4', path: '/a/FX3/A.MP4',  duration: 10, wall_offset: 0, creation_time: '2026-04-02T10:00:00Z' },
    { clip_id: 'B', filename: 'B.MOV', path: '/a/iPhone/B.MOV', duration: 10, wall_offset: 0, creation_time: '2026-04-02T10:00:00Z' },
  ];
  const p = plan(clips, [], ['iPhone', 'FX3']);
  assert.strictEqual(p.cam_layers.iPhone, 0);
  assert.strictEqual(p.cam_layers.FX3, 1);
});

test('plan: placements sorted by offsetSec deterministically', () => {
  const clips = [
    { clip_id: 'C', filename: 'C.MP4', path: '/a/FX3/C.MP4', duration: 5, wall_offset: 30, creation_time: '2026-04-02T10:00:30Z' },
    { clip_id: 'A', filename: 'A.MP4', path: '/a/FX3/A.MP4', duration: 5, wall_offset: 0,  creation_time: '2026-04-02T10:00:00Z' },
    { clip_id: 'B', filename: 'B.MP4', path: '/a/FX3/B.MP4', duration: 5, wall_offset: 15, creation_time: '2026-04-02T10:00:15Z' },
  ];
  const p = plan(clips, [], null, { compress: false });
  const offsets = p.placements.map(pl => pl.offsetSec);
  assert.deepStrictEqual(offsets, [0, 15, 30]);
});

// ─── gap compression ─────────────────────────────────────────────────────

test('plan: gap compression collapses big gaps, keeps small ones, preserves order', () => {
  const clips = [
    { clip_id: 'A', filename: 'A.MP4', path: '/a/S/FX3/A.MP4', duration: 10, wall_offset: 0,    creation_time: '2026-04-02T10:00:00Z' },
    // small 2s gap (≤3s threshold) — preserved
    { clip_id: 'B', filename: 'B.MP4', path: '/a/S/FX3/B.MP4', duration: 10, wall_offset: 12,   creation_time: '2026-04-02T10:00:12Z' },
    // huge 1000s gap (>3s) — compressed to 2s
    { clip_id: 'C', filename: 'C.MP4', path: '/a/S/FX3/C.MP4', duration: 10, wall_offset: 1032, creation_time: '2026-04-02T10:17:12Z' },
  ];
  const p = plan(clips, [], null, { gapThreshold: 3, compressedGap: 2 });
  const off = p.placements.map(pl => pl.offsetSec);
  // A:[0,10] → 0 ; small 2s gap kept → B at 12 ; B end 22 ; big gap → +2 → C at 24
  assert.deepStrictEqual(off, [0, 12, 24]);
  assert.strictEqual(p.timeJumps.length, 1, 'one collapsed gap → one time-jump marker');
  // raw gap = C.start(1032) − B.end(22) = 1010 ; skipped = 1010 − compressedGap(2) = 1008
  assert.ok(Math.abs(p.timeJumps[0].skippedSec - 1008) < 0.01, 'skipped = raw gap − compressedGap');
  assert.strictEqual(p.compressed, true);
  // raw offsets preserved for reference
  assert.strictEqual(p.placements.find(x => x.clipId === 'C').rawOffsetSec, 1032);
});

test('plan: compression keeps clip durations and TX sync (slice within interval is shift-only)', () => {
  const clips = [
    { clip_id: 'A', filename: 'A.MP4', path: '/a/S/FX3/A.MP4', duration: 20, wall_offset: 0,    creation_time: '2026-04-02T10:00:00Z' },
    { clip_id: 'B', filename: 'B.MP4', path: '/a/S/FX3/B.MP4', duration: 20, wall_offset: 600,  creation_time: '2026-04-02T10:10:00Z' },
  ];
  const txStrips = [{ tx: 'TX', filename: 'tx.wav', path: '/a/tx.wav', duration: 700, wall_offset: 0, creation_time: '2026-04-02T10:00:00Z', sample_rate: 48000 }];
  const p = plan(clips, txStrips, null, { gapThreshold: 3, compressedGap: 2 });
  const tx = p.placements.filter(pl => pl.kind === 'tx');
  // 2 TX slices (one per video interval [0,20] and [600,620]); durations preserved 20 & 20
  assert.strictEqual(tx.length, 2);
  assert.deepStrictEqual(tx.map(t => t.duration), [20, 20]);
  // second slice offset = 20 (end of first interval) + 2 (compressed gap) = 22
  const second = tx.find(t => t.rawOffsetSec === 600);
  assert.strictEqual(second.offsetSec, 22);
  assert.strictEqual(second.sourceInPoint, 600, 'sourceInPoint into the WAV is unchanged by compression');
});

// ─── gridAlignPlan ───────────────────────────────────────────────────────
// Premiere's clip API has NO sub-frame lever (measured YTCH10+YTCH13,
// 16.08.2026): setSourceInOut FLOORS to the frame grid, insert positions are
// ROUNDED TO NEAREST frame. gridAlignPlan therefore puts EVERYTHING on exact
// frame ticks itself; the sub-frame lav fraction lives in the media
// (0113_frame_align.py timeline-domain render), not in the placement.

const { gridAlignPlan, ticksPerFrameForFps, TICKS_PER_SECOND } = require('../../../src/ingest/layout/sceneLayout');

function txp(offsetSec, sourceInPoint, duration, aIdx) {
  return { kind: 'tx', txId: 'TX01', filename: 'tx.wav', vIdx: -1, aIdx, offsetSec, sourceInPoint, duration };
}
function oneBlock(start, end) {
  return [{ origStart: start, origEnd: end, compStart: start }];
}
const onGrid = (sec) => Math.abs(sec / 0.04 - Math.round(sec / 0.04)) < 1e-6;

test('grid: everything lands on exact frame ticks, content_src carries the fraction', () => {
  const w = [];
  const p = [txp(100.0, 324.512, 10.0, 2)];
  gridAlignPlan([], p, oneBlock(100.0, 110.0), 25, w);
  assert.ok(onGrid(p[0].offsetSec), `position off grid: ${p[0].offsetSec}`);
  assert.ok(onGrid(p[0].sourceInPoint), `in off grid: ${p[0].sourceInPoint}`);
  assert.strictEqual(p[0].offsetTicks, String(2500 * 10160640000));
  // in 324.512 → nearest grid 324.52; the EXACT source instant for the slice
  // start is preserved for the 0113 render:
  assert.ok(Math.abs(p[0].contentSrcSec - 324.512) < 1e-6);
  // unaligned media is reported (fraction −8 ms beyond the 0.5 ms tolerance):
  // in 324.512 snaps to 324.52 → content plays 8 ms EARLY (residual −8)
  assert.ok(w.some(x => x.type === 'tx_unaligned_media'));
  assert.ok(Math.abs(p[0].residualMs + 8) < 0.5, `residual ${p[0].residualMs}`);
});

test('grid: frame-aligned media passes with zero residual and no warnings', () => {
  const w = [];
  const p = [txp(50.0, 31.96, 8.0, 2)];  // 31.96 = 799 frames @25p
  gridAlignPlan([], p, oneBlock(50.0, 60.0), 25, w);
  assert.ok(Math.abs(p[0].sourceInPoint - 31.96) < 1e-9);
  assert.ok(Math.abs(p[0].offsetSec - 50.0) < 1e-9);
  assert.ok(Math.abs(p[0].duration - 8.0) < 1e-9);
  assert.strictEqual(p[0].residualMs, 0);
  assert.strictEqual(w.length, 0);
});

test('grid: out-point floors (duration is whole frames, never overruns video)', () => {
  const w = [];
  const p = [txp(10.0, 0.0, 5.013, 2)];  // end 15.013 → floors to 15.00
  gridAlignPlan([], p, oneBlock(10.0, 15.013), 25, w);
  assert.ok(Math.abs(p[0].duration - 5.0) < 1e-9);
  assert.strictEqual(p[0].durationTicks, String(125 * 10160640000));
});

test('grid: sub-frame block anchor shifts video AND tx together (sync preserved)', () => {
  const w = [];
  // block starts at 100.013 (sub-frame, fine-sync jitter) → anchors to 100.0
  const v = [{ kind: 'video', filename: 'C.MP4', vIdx: 0, aIdx: 0, offsetSec: 100.013, duration: 10.0 }];
  const p = [txp(100.013, 200.0, 10.0, 2)];
  gridAlignPlan(v, p, oneBlock(100.013, 110.013), 25, w);
  assert.ok(Math.abs(v[0].offsetSec - 100.0) < 1e-9, `video: ${v[0].offsetSec}`);
  assert.ok(Math.abs(p[0].offsetSec - 100.0) < 1e-9, `tx: ${p[0].offsetSec}`);
  // lav slice sits EXACTLY on the video boundary — no visible step
  assert.strictEqual(v[0].offsetTicks, p[0].offsetTicks);
  // block shift moves video AND lav together → the lav-vs-video content
  // mapping is untouched: slice start still plays source instant 200.0
  assert.ok(Math.abs(p[0].contentSrcSec - 200.0) < 1e-6);
  assert.strictEqual(p[0].residualMs, 0);
});

test('grid: back-to-back slices never overlap after quantization', () => {
  const w = [];
  const prev = txp(50.0, 100.00, 10.0, 2);
  const cur  = txp(60.0, 200.030, 10.0, 2);
  gridAlignPlan([], [prev, cur], oneBlock(50.0, 70.1), 25, w);
  const prevEnd = prev.offsetSec + prev.duration;
  assert.ok(prevEnd <= cur.offsetSec + 1e-9,
    `overlap: prev ends ${prevEnd}, cur starts ${cur.offsetSec}`);
  assert.ok(onGrid(cur.offsetSec));
});

test('grid: slices on different tracks do not trim each other', () => {
  const w = [];
  const a = txp(50.0, 100.00, 10.0, 2);
  const b = txp(55.0, 200.030, 10.0, 3);   // overlaps a in time but on another track
  gridAlignPlan([], [a, b], oneBlock(50.0, 70.0), 25, w);
  assert.ok(Math.abs(a.duration - 10.0) < 1e-9);
});

test('grid: sub-frame slice is dropped with a warning', () => {
  const w = [];
  const p = [txp(10.0, 7.013, 0.02, 2)];
  gridAlignPlan([], p, oneBlock(10.0, 10.02), 25, w);
  assert.strictEqual(p.length, 0);
  assert.ok(w.some(x => x.type === 'tx_slice_dropped_subframe'));
});

test('grid: NTSC ticks per frame are exact rationals', () => {
  assert.strictEqual(ticksPerFrameForFps(25), 10160640000);
  assert.strictEqual(ticksPerFrameForFps(29.97), 8475667200);   // ×1001/30000
  assert.strictEqual(ticksPerFrameForFps(23.976), 10594584000); // 254016000000×1001/24000
  assert.strictEqual(ticksPerFrameForFps(50), 5080320000);
  assert.strictEqual(29.97 * 8475667200 / TICKS_PER_SECOND < 1.0001, true);
});

test('plan: single-block scene anchors to 0 — no dead air before the first video (YTCH13 scene 01)', () => {
  // Lav recorder rolled 10.84 s before the camera → scene_t0 = recorder start,
  // video wall_offset 10.84. The head gap is dead timeline and must collapse
  // exactly like inter-block gaps do ("Model 1, no gaps").
  const clips = [
    { clip_id: 'C1', filename: 'C1.MP4', cam: 'CAM1', wall_offset: 10.84, duration: 100.0, creation_time: '2026-04-02T09:00:10Z' },
  ];
  const tx = [{ tx: 'TX01', filename: 'tx.wav', wall_offset: 0.0073, duration: 300.0,
                creation_time: '2026-04-02T09:00:00Z', sample_rate: 48000 }];
  const p = plan(clips, tx, null, { scene: 't', fps: 25 });
  const vid = p.placements.find(x => x.kind === 'video');
  assert.strictEqual(vid.offsetSec, 0, `video pulled to 0, got ${vid.offsetSec}`);
  assert.strictEqual(vid.offsetTicks, '0');
  const slice = p.placements.find(x => x.kind === 'tx');
  assert.strictEqual(slice.offsetSec, 0, 'lav slice starts with the video');
});

test('plan: timeline-domain strip yields identity slices on the block grid', () => {
  const clips = [
    { clip_id: 'C1', filename: 'C1.MP4', cam: 'CAM1', wall_offset: 0.0, duration: 10.0, creation_time: '2026-04-02T09:00:00Z' },
    { clip_id: 'C2', filename: 'C2.MP4', cam: 'CAM1', wall_offset: 60.0, duration: 10.0, creation_time: '2026-04-02T09:01:00Z' },
  ];
  const tx = [{ tx: 'TX01', filename: 'TX01_timeline.wav', wall_offset: 0, duration: 3600,
                creation_time: '2026-04-02T09:00:00Z', sample_rate: 48000, timeline_domain: true }];
  const p = plan(clips, tx, null, { scene: 't', fps: 25 });
  const slices = p.placements.filter(x => x.kind === 'tx');
  // one identity slice per union block (2 blocks after gap compression)
  assert.strictEqual(slices.length, 2);
  for (const s of slices) {
    assert.strictEqual(s.timelineDomain, true);
    assert.strictEqual(s.offsetTicks, s.sourceInTicks, 'identity: offset == source-in');
    assert.strictEqual(s.residualMs, 0);
  }
  // slices sit exactly on the video block starts
  const vids = p.placements.filter(x => x.kind === 'video');
  assert.strictEqual(slices[0].offsetTicks, vids[0].offsetTicks);
  assert.strictEqual(slices[1].offsetTicks, vids[1].offsetTicks);
});

test('plan: TX slices come out with frame-aligned source in/out', () => {
  // Two clips + one strip with a sub-frame wall offset (fine-sync style)
  const clips = [
    { clip_id: 'C1', filename: 'C1.MP4', cam: 'CAM1', wall_offset: 0.0, duration: 10.0, creation_time: '2026-04-02T09:00:00Z' },
    { clip_id: 'C2', filename: 'C2.MP4', cam: 'CAM1', wall_offset: 20.0, duration: 10.0, creation_time: '2026-04-02T09:00:20Z' },
  ];
  const tx = [{ tx: 'TX01', filename: 'tx.wav', wall_offset: 0.0134, duration: 40.0, creation_time: '2026-04-02T09:00:00Z', sample_rate: 48000 }];
  const p = plan(clips, tx, null, { scene: 't', fps: 25 });
  const slices = p.placements.filter(x => x.kind === 'tx');
  assert.ok(slices.length >= 2);
  for (const s of slices) {
    const inFrames = s.sourceInPoint / 0.04;
    const durFrames = s.duration / 0.04;
    assert.ok(Math.abs(inFrames - Math.round(inFrames)) < 1e-6, `in not frame-aligned: ${s.sourceInPoint}`);
    assert.ok(Math.abs(durFrames - Math.round(durFrames)) < 1e-6, `dur not frame-aligned: ${s.duration}`);
  }
});

test('grid: scene-head slice at t=0 stays at 0, never negative', () => {
  const w = [];
  // slice at timeline 0 with fractional in-point — the YTCH10 scene-head case
  const p = [txp(0.0, 324.512, 10.0, 2)];
  gridAlignPlan([], p, oneBlock(0.0, 10.0), 25, w);
  assert.ok(p[0].offsetSec >= 0, `negative offset: ${p[0].offsetSec}`);
  assert.ok(Math.abs(p[0].offsetSec - 0.0) < 1e-9);
  assert.ok(onGrid(p[0].sourceInPoint));
  // exact source instant preserved for the 0113 render
  assert.ok(Math.abs(p[0].contentSrcSec - 324.512) < 1e-6);
});

test('plan: lav-rolls-first scene produces no negative TX offsets (YTCH10 head case)', () => {
  const clips = [
    { clip_id: 'C1', filename: 'C1.MP4', cam: 'CAM1', wall_offset: 10.512, duration: 60, creation_time: '2026-04-02T09:00:10Z' },
    { clip_id: 'C2', filename: 'C2.MP4', cam: 'CAM1', wall_offset: 200.0, duration: 60, creation_time: '2026-04-02T09:03:20Z' },
  ];
  const tx = [{ tx: 'TX01', filename: 'tx.wav', wall_offset: 0.0, duration: 300, creation_time: '2026-04-02T09:00:00Z', sample_rate: 48000 }];
  const p = plan(clips, tx, null, { scene: 'head', fps: 25 });
  for (const s of p.placements) {
    assert.ok(s.offsetSec >= 0, `${s.kind} ${s.filename} at negative ${s.offsetSec}`);
  }
});
