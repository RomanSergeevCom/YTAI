/**
 * shortsBuilder tests — pure planning + validation hard, plus mock-Premiere
 * integration for both builders (pattern: tests/parts/partsBuilder.test.js).
 */
const { test } = require('node:test');
const assert = require('node:assert');
const ppro = require('../mocks/premierepro');
const {
  SHORTS_BUILDER_VERSION,
  ROLE_COLOR_INDEX,
  boundaryTicks,
  planShort,
  planPreview,
  validateShortsBrief,
  buildPreviewSequence,
  buildShortSequence
} = require('../../src/shorts/shortsBuilder');

const TPS = 254016000000;
const FRAME25 = TPS / 25; // 10160640000

// --- fixtures ---

function mkBoundary(sec) {
  return { tc: '', sec: sec, frame: Math.round(sec * 25), ticks: Math.round(sec * TPS) };
}

function mkBlock(id, inSec, outSec, over) {
  return Object.assign({
    block_id: id,
    role: 'body',
    source: { kind: 'final_render', file: 'REN.mp4', path: '/tmp/REN.mp4', scene: null, clip_id: null },
    tc_in: mkBoundary(inSec),
    tc_out: mkBoundary(outSec),
    keep_audio: true,
    transcript: 'text of ' + id
  }, over || {});
}

function mkCand(id, slug, blocks, over) {
  return Object.assign({
    short_id: id,
    slug: slug,
    status: 'proposed',
    score: { total: 87, hook: 92, flow: 85, value: 80, emotion: 88 },
    why: 'payoff at the end',
    hook_text: 'I lost two million dollars',
    blocks: blocks
  }, over || {});
}

function mkBrief(cands, over) {
  return Object.assign({
    schema: 'ytai-shorts-v1',
    direction: 'in',
    version: 3,
    project: {
      code: 'YTCR01', channel: 'YTCR', mode: 'finished', fps: 25,
      source: { file: 'REN.mp4', path: '/tmp/REN.mp4', duration_sec: 1873 }
    },
    render_target: { width: 1080, height: 1920, fps: 25, also_horizontal: false },
    candidates: cands
  }, over || {});
}

// ═══════════════ exports ═══════════════

test('shortsBuilder exports + version', () => {
  assert.ok(SHORTS_BUILDER_VERSION, 'has version');
  assert.strictEqual(typeof planShort, 'function');
  assert.strictEqual(typeof planPreview, 'function');
  assert.strictEqual(typeof validateShortsBrief, 'function');
  assert.strictEqual(typeof buildPreviewSequence, 'function');
  assert.strictEqual(typeof buildShortSequence, 'function');
});

// ═══════════════ planShort (pure) ═══════════════

test('planShort: blocks back-to-back from 0 on the tick grid, exact cumulative ticks', () => {
  const brief = mkBrief([]);
  const cand = mkCand('S01', 'two-blocks', [mkBlock('b1', 100, 102), mkBlock('b2', 200, 201)]);
  const plan = planShort(cand, brief);
  assert.strictEqual(plan.length, 2);
  assert.strictEqual(plan[0].srcInTicks, 100 * TPS);
  assert.strictEqual(plan[0].srcOutTicks, 102 * TPS);
  assert.strictEqual(plan[0].timelineInTicks, 0);
  assert.strictEqual(plan[0].timelineOutTicks, 2 * TPS);
  assert.strictEqual(plan[1].timelineInTicks, 2 * TPS, 'second block starts exactly where the first ends');
  assert.strictEqual(plan[1].timelineOutTicks, 3 * TPS);
  assert.strictEqual(plan[0].vIdx, 0);
});

test('planShort: ticks are trusted over sec (ticks = source of truth)', () => {
  const brief = mkBrief([]);
  const b = mkBlock('b1', 100, 102);
  b.tc_in = { sec: 999.999, ticks: 100 * TPS }; // sec lies — ticks win
  const plan = planShort(mkCand('S01', 'x', [b]), brief);
  assert.strictEqual(plan[0].srcInTicks, 100 * TPS);
});

test('planShort: missing ticks → snapToFrame(sec) then round to ticks (in floor, out ceil)', () => {
  const brief = mkBrief([]);
  const b = mkBlock('b1', 0, 0);
  b.tc_in = { sec: 10.01 };  // floor → 10.00
  b.tc_out = { sec: 10.99 }; // ceil → 11.00
  const plan = planShort(mkCand('S01', 'x', [b]), brief);
  assert.strictEqual(plan[0].srcInTicks, 10 * TPS);
  assert.strictEqual(plan[0].srcOutTicks, 11 * TPS);
  assert.strictEqual(plan[0].timelineOutTicks, 1 * TPS);
});

test('planShort: keep_audio false → aIdx -1, default/true → 0', () => {
  const brief = mkBrief([]);
  const plan = planShort(mkCand('S01', 'x', [
    mkBlock('b1', 10, 11, { keep_audio: false }),
    mkBlock('b2', 20, 21),
    mkBlock('b3', 30, 31, { keep_audio: true })
  ]), brief);
  assert.strictEqual(plan[0].aIdx, -1);
  assert.strictEqual(plan[1].aIdx, 0);
  assert.strictEqual(plan[2].aIdx, 0);
});

test('planShort: color index by role (hook=Mango 7, body=Caribbean 2, broll=Lavender 3)', () => {
  const brief = mkBrief([]);
  const plan = planShort(mkCand('S01', 'x', [
    mkBlock('b1', 10, 11, { role: 'hook' }),
    mkBlock('b2', 20, 21, { role: 'body' }),
    mkBlock('b3', 30, 31, { role: 'broll' }),
    mkBlock('b4', 40, 41, { role: 'payoff' })
  ]), brief);
  assert.strictEqual(plan[0].colorIndex, 7, 'hook → Mango');
  assert.strictEqual(plan[1].colorIndex, 2, 'body → Caribbean');
  assert.strictEqual(plan[2].colorIndex, 3, 'broll → Lavender');
  assert.strictEqual(plan[3].colorIndex, 2, 'payoff rides with body');
  assert.strictEqual(ROLE_COLOR_INDEX.hook, 7);
});

test('planShort: markerReadback override lands on first-in / last-out boundaries', () => {
  const brief = mkBrief([]);
  const cand = mkCand('S03', 'moved', [mkBlock('b1', 100, 102), mkBlock('b2', 200, 201)]);
  const plan = planShort(cand, brief, {
    markerReadback: {
      tc_in: { sec: 99, ticks: 99 * TPS },
      tc_out: { sec: 203, ticks: 203 * TPS },
      moved: true
    }
  });
  assert.strictEqual(plan[0].srcInTicks, 99 * TPS, 'override in → first block');
  assert.strictEqual(plan[0].srcOutTicks, 102 * TPS, 'first block out untouched');
  assert.strictEqual(plan[1].srcInTicks, 200 * TPS, 'last block in untouched');
  assert.strictEqual(plan[1].srcOutTicks, 203 * TPS, 'override out → last block');
  assert.strictEqual(plan[1].timelineOutTicks, 6 * TPS, 'total = 3s + 3s');
});

test('boundaryTicks: string ticks accepted, tc fallback parses', () => {
  assert.strictEqual(boundaryTicks({ ticks: String(50 * TPS) }, 25, 'floor'), 50 * TPS);
  assert.strictEqual(boundaryTicks({ tc: '1:40.000' }, 25, 'floor'), 100 * TPS);
});

// ═══════════════ planPreview (pure) ═══════════════

test('planPreview: rejected excluded, name/comment format, range = min-in..max-out', () => {
  const brief = mkBrief([
    mkCand('S01', 'slug-a', [mkBlock('b1', 100, 130)]),
    mkCand('S02', 'slug-b', [mkBlock('b1', 200, 220)], { status: 'rejected' }),
    mkCand('S03', 'slug-c', [mkBlock('b1', 300, 310), mkBlock('b2', 320, 330)])
  ]);
  const markers = planPreview(brief);
  assert.strictEqual(markers.length, 2, 'rejected S02 excluded');
  assert.strictEqual(markers[0].name, 'S01 [87] slug-a');
  assert.strictEqual(markers[0].comment, 'I lost two million dollars — payoff at the end');
  assert.strictEqual(markers[0].startTicks, 100 * TPS);
  assert.strictEqual(markers[0].durationTicks, 30 * TPS);
  assert.strictEqual(markers[1].startTicks, 300 * TPS, 'multi-block: min in');
  assert.strictEqual(markers[1].durationTicks, 30 * TPS, 'multi-block: span to max out');
});

test('planPreview: panel statuses override JSON status', () => {
  const brief = mkBrief([
    mkCand('S01', 'slug-a', [mkBlock('b1', 100, 130)]),
    mkCand('S02', 'slug-b', [mkBlock('b1', 200, 220)])
  ]);
  const markers = planPreview(brief, { S01: 'rejected' });
  assert.strictEqual(markers.length, 1);
  assert.strictEqual(markers[0].shortId, 'S02');
});

// ═══════════════ validateShortsBrief (pure) ═══════════════

test('validate W01: tc_in after first word / tc_out before last word', () => {
  const bIn = mkBlock('b1', 100, 130, {
    words: { first: 'I', last: 'call', first_start_sec: 99.5, last_end_sec: 129.0 }
  });
  const bOut = mkBlock('b1', 200, 220, {
    words: { first: 'so', last: 'deal', first_start_sec: 200.2, last_end_sec: 220.61 }
  });
  const issues = validateShortsBrief(mkBrief([
    mkCand('S01', 'a', [bIn]),
    mkCand('S02', 'b', [bOut])
  ]));
  const w01 = issues.filter(i => i.code === 'W01');
  assert.strictEqual(w01.length, 2);
  assert.strictEqual(w01[0].short_id, 'S01');
  assert.match(w01[0].msg, /"I" cut/);
  assert.strictEqual(w01[1].short_id, 'S02');
  assert.match(w01[1].msg, /"deal" cut/);
});

test('validate O01: overlapping non-rejected candidates flagged; rejected side clears it', () => {
  const c1 = mkCand('S01', 'a', [mkBlock('b1', 100, 130)]);
  const c2 = mkCand('S02', 'b', [mkBlock('b1', 120, 150)]);
  let issues = validateShortsBrief(mkBrief([c1, c2]));
  const o01 = issues.filter(i => i.code === 'O01');
  assert.strictEqual(o01.length, 1);
  assert.match(o01[0].msg, /S01 overlaps S02/);
  // same brief, S02 rejected via panel statuses → gate clears
  issues = validateShortsBrief(mkBrief([c1, c2]), { S02: 'rejected' });
  assert.strictEqual(issues.filter(i => i.code === 'O01').length, 0);
  // non-overlapping stays clean
  const c3 = mkCand('S03', 'c', [mkBlock('b1', 300, 330)]);
  issues = validateShortsBrief(mkBrief([c1, c3]));
  assert.strictEqual(issues.filter(i => i.code === 'O01').length, 0);
});

test('validate S01: duplicate slug and duplicate short_id', () => {
  const issues = validateShortsBrief(mkBrief([
    mkCand('S01', 'same-slug', [mkBlock('b1', 100, 110)]),
    mkCand('S02', 'same-slug', [mkBlock('b1', 200, 210)]),
    mkCand('S02', 'other', [mkBlock('b1', 300, 310)])
  ]));
  const s01 = issues.filter(i => i.code === 'S01');
  assert.strictEqual(s01.length, 2, 'one dup slug + one dup short_id');
  assert.ok(s01.some(i => /duplicate slug/.test(i.msg)));
  assert.ok(s01.some(i => /duplicate short_id/.test(i.msg)));
});

test('validate B01: ticks/sec incoherence (>1 frame) and frame != round(sec*fps)', () => {
  const bad = mkBlock('b1', 100, 110);
  bad.tc_in = { sec: 100, frame: 2500, ticks: 100 * TPS + 2 * FRAME25 }; // ticks 2 frames off sec
  bad.tc_out = { sec: 110, frame: 2699, ticks: 110 * TPS };              // frame should be 2750
  const issues = validateShortsBrief(mkBrief([mkCand('S01', 'a', [bad])]));
  const b01 = issues.filter(i => i.code === 'B01');
  assert.strictEqual(b01.length, 2);
  assert.match(b01[0].msg, /ticks\/sec disagree/);
  assert.match(b01[1].msg, /frame 2699 != round\(sec\*fps\) 2750/);
});

test('validate: coherent brief is clean; within-1-frame ticks tolerated', () => {
  const ok = mkBlock('b1', 100, 110, {
    words: { first: 'a', last: 'z', first_start_sec: 100.2, last_end_sec: 109.8 }
  });
  ok.tc_in.ticks = 100 * TPS + Math.floor(FRAME25 / 2); // half a frame off — inside tolerance
  const issues = validateShortsBrief(mkBrief([mkCand('S01', 'a', [ok])]));
  assert.deepStrictEqual(issues, []);
});

test('validate: non-shorts schema → single SCHEMA error', () => {
  const issues = validateShortsBrief({ schema: 'ytai-part-v1' });
  assert.strictEqual(issues.length, 1);
  assert.strictEqual(issues[0].code, 'SCHEMA');
});

// ═══════════════ integration (mock Premiere) ═══════════════

function mkMockProjectWithSource() {
  const project = new ppro._MockProject();
  const src = new ppro._MockClipProjectItem('REN.mp4', '/tmp/REN.mp4');
  src._durationSec = 1873;
  src._parent = project._rootItem;
  project._rootItem._items.push(src);
  return { project, src };
}

const silentLogger = { info() {}, warn() {}, error() {}, debug() {} };

test('buildShortSequence: tick-exact placement, verify gate ok, bin + spike verdict', async () => {
  const { project } = mkMockProjectWithSource();
  const brief = mkBrief([]);
  const cand = mkCand('S03', 'poteryal-2m', [mkBlock('b1', 100, 102), mkBlock('b2', 200, 201)], {
    reframe: { mode: 'static', crop_center_x_pct: 42 }
  });
  const report = await buildShortSequence(project, cand, brief, { logger: silentLogger });

  assert.strictEqual(report.short_id, 'S03');
  assert.strictEqual(report.sequence, 'YTCR01_S03_poteryal-2m');
  assert.strictEqual(report.placed, 2);
  assert.strictEqual(report.skipped, 0);
  assert.strictEqual(report.ok, true, 'verify gate passes: ' + (report.verify_error || report.drift_ms + 'ms'));
  assert.ok(report.drift_ms <= 2, 'drift ' + report.drift_ms + 'ms within 2ms');
  assert.strictEqual(report.clips.length, 2);
  assert.strictEqual(report.clips[0].timeline_start.ticks, 0);
  assert.strictEqual(report.clips[1].timeline_start.ticks, 2 * TPS, 'second clip back-to-back');
  assert.strictEqual(report.clips[1].duration.ticks, 1 * TPS);
  assert.strictEqual(report.clips[0].source_in.ticks, 100 * TPS);
  assert.match(report.spike_s1, /^S-1 spike:/, 'spike returns a one-line verdict');

  // Sequence exists in the project; Shorts bin was created at root.
  const seqs = await project.getSequences();
  assert.ok(seqs.some(s => s.name === 'YTCR01_S03_poteryal-2m'));
  const rootItems = await (await project.getRootItem()).getItems();
  assert.ok(rootItems.some(it => it.name === 'Shorts' && it.type === 2), 'Shorts bin created');
  await assertFiledInShortsBin(project, 'YTCR01_S03_poteryal-2m');
});

// The sequence's project item must really sit INSIDE the Shorts bin (two-arg
// createMoveItemAction + verified read-back) and no longer at project root.
async function assertFiledInShortsBin(project, seqName) {
  const rootItems = await (await project.getRootItem()).getItems();
  const shorts = rootItems.find(it => it.name === 'Shorts' && it.type === 2);
  assert.ok(shorts, 'Shorts bin exists at root');
  const binItems = await shorts.getItems();
  assert.ok(binItems.some(it => it.name === seqName && it.type !== 2), seqName + ' is inside the Shorts bin');
  assert.ok(!rootItems.some(it => it.name === seqName && it.type !== 2), seqName + ' no longer at project root');
}

test('buildShortSequence: keep_audio=false block places video only (aIdx -1)', async () => {
  const { project } = mkMockProjectWithSource();
  const brief = mkBrief([]);
  const cand = mkCand('S05', 'mute-tail', [
    mkBlock('b1', 100, 101),
    mkBlock('b2', 200, 201, { keep_audio: false })
  ]);
  const report = await buildShortSequence(project, cand, brief, { logger: silentLogger });
  assert.strictEqual(report.ok, true);
  const seq = (await project.getSequences()).find(s => s.name === 'YTCR01_S05_mute-tail');
  const a1 = seq._audioTracks[0]._items;
  assert.strictEqual(a1.length, 1, 'only the keep_audio block landed on A1');
  const v1 = seq._videoTracks[0]._items;
  assert.strictEqual(v1.length, 2, 'both blocks landed on V1');
});

test('buildPreviewSequence: source kept FULL length on V1 + markers for non-rejected only', async () => {
  const { project, src } = mkMockProjectWithSource();
  const brief = mkBrief([
    mkCand('S01', 'slug-a', [mkBlock('b1', 100, 130)]),
    mkCand('S02', 'slug-b', [mkBlock('b1', 200, 220)], { status: 'rejected' }),
    mkCand('S03', 'slug-c', [mkBlock('b1', 300, 330)])
  ]);
  const r = await buildPreviewSequence(project, brief, { logger: silentLogger });
  assert.strictEqual(r.seqName, 'YTCR01_Shorts_Preview_v3');
  assert.strictEqual(r.candidates, 2, 'rejected excluded');
  assert.strictEqual(r.markers, 2, 'both markers placed');
  const seq = (await project.getSequences()).find(s => s.name === 'YTCR01_Shorts_Preview_v3');
  assert.ok(seq, 'preview sequence exists');
  const v1 = seq._videoTracks[0]._items;
  assert.strictEqual(v1.length, 1, 'seed kept on V1');
  assert.strictEqual(v1[0]._durationSec, src._durationSec, 'seed is FULL length (in/out cleared)');
  await assertFiledInShortsBin(project, 'YTCR01_Shorts_Preview_v3');
  // panel statuses override respected
  const r2 = await buildPreviewSequence(project, brief, { logger: silentLogger, statuses: { S03: 'rejected' } });
  assert.strictEqual(r2.candidates, 1);
});
