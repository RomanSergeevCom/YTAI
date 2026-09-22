// Anti-regression guards for the MEASURED Premiere semantics the mock models
// (YTCH10 + YTCH13 dumps, 16.08.2026):
//   1. compound transactions execute their actions in REVERSE order;
//   2. overwrite REPLACES what it covers (head/tail trim, source-in advance);
//   3. insert ROUNDS the position to the nearest frame and RIPPLES;
//   4. setSourceInOut FLOORS to the frame grid.
// If someone re-batches wallClockBuilder's per-clip video transactions back
// into one compound (the pre-fix shape), the reversal+overwrite model makes
// the head-eating visible in tests instead of only on a live timeline.

const test = require('node:test');
const assert = require('node:assert');
const ppro = require('../../../tests/mocks/premierepro');

function makeSeq() {
  const project = new ppro._MockProject();
  const seq = new ppro._MockSequence('T');
  seq._ensureVideoTrack(0);
  seq._ensureAudioTrack(0);
  return { project, seq, ed: new (Object.getPrototypeOf(ppro.SequenceEditor.getEditor(seq)).constructor)(seq) };
}

function item(name, durSec) {
  const pi = new ppro._MockClipProjectItem(name);
  pi._durationSec = durSec;
  return pi;
}

test('mock: batched compound overwrites execute in REVERSE — later clip loses its head (YTCH13 1052/1053)', () => {
  const { project, seq } = makeSeq();
  const ed = ppro.SequenceEditor.getEditor(seq);
  // Plan: A [0, 10], B [10, 20] — but A's media really runs 10.04 s (1 frame over).
  const A = item('A', 10.04);
  const B = item('B', 10.0);
  project.lockedAccess(() => {
    project.executeTransaction((ca) => {
      ca.addAction(ed.createOverwriteItemAction(A, ppro.TickTime.createWithSeconds(0), 0, 0));
      ca.addAction(ed.createOverwriteItemAction(B, ppro.TickTime.createWithSeconds(10.0), 0, 0));
    }, 'batched');
  });
  const items = seq._videoTracks[0]._items.sort((a, b) => a._startTimeSec - b._startTimeSec);
  assert.strictEqual(items.length, 2);
  // Reverse execution: B applied first at [10,20], then A [0,10.04] eats B's head.
  assert.ok(Math.abs(items[1]._startTimeSec - 10.04) < 1e-9, `B starts at ${items[1]._startTimeSec} (head eaten)`);
  assert.ok(Math.abs((items[1]._sourceInSec || 0) - 0.04) < 1e-9, 'B source-in advanced by the eaten head');
});

test('mock: per-clip sequential overwrites in ascending order keep heads sacred (the fix shape)', () => {
  const { project, seq } = makeSeq();
  const ed = ppro.SequenceEditor.getEditor(seq);
  const A = item('A', 10.04);
  const B = item('B', 10.0);
  for (const [it, at] of [[A, 0], [B, 10.0]]) {
    project.lockedAccess(() => {
      project.executeTransaction((ca) => {
        ca.addAction(ed.createOverwriteItemAction(it, ppro.TickTime.createWithSeconds(at), 0, 0));
      }, `clip ${it.name}`);
    });
  }
  const items = seq._videoTracks[0]._items.sort((a, b) => a._startTimeSec - b._startTimeSec);
  assert.strictEqual(items.length, 2);
  // B (placed later) overwrote A's overrunning tail; B's head intact at 10.0.
  assert.ok(Math.abs(items[1]._startTimeSec - 10.0) < 1e-9, 'B head sacred');
  assert.ok(Math.abs(items[0]._durationSec - 10.0) < 1e-9, 'A tail trimmed to the boundary');
});

test('mock: action factories THROW outside lockedAccess (live "Requires locked access", 17.08.2026)', () => {
  const { seq } = makeSeq();
  const ed = ppro.SequenceEditor.getEditor(seq);
  const A = item('A', 5.0);
  assert.throws(
    () => ed.createOverwriteItemAction(A, ppro.TickTime.createWithSeconds(0), 0, 0),
    /Requires locked access/,
    'overwrite action created outside lockedAccess must throw like real Premiere'
  );
  assert.throws(
    () => ed.createInsertProjectItemAction(A, ppro.TickTime.createWithSeconds(0), -1, 0, true),
    /Requires locked access/
  );
});

test('mock: insert rounds to nearest frame and ripples items after the point', () => {
  const { project, seq } = makeSeq();
  const ed = ppro.SequenceEditor.getEditor(seq);
  const A = item('A', 5.0);
  const B = item('B', 2.0);
  project.lockedAccess(() => {
    project.executeTransaction((ca) => {
      ca.addAction(ed.createInsertProjectItemAction(A, ppro.TickTime.createWithSeconds(10.0), -1, 0, true));
    }, 'a');
  });
  // insert at 4.99 → nearest frame 5.00 (fraction 30 ms rounds up at 25p: 4.99→5.00? 4.99/0.04=124.75 → 125)
  project.lockedAccess(() => {
    project.executeTransaction((ca) => {
      ca.addAction(ed.createInsertProjectItemAction(B, ppro.TickTime.createWithSeconds(4.99), -1, 0, true));
    }, 'b');
  });
  const items = seq._audioTracks[0]._items.sort((a, b) => a._startTimeSec - b._startTimeSec);
  assert.strictEqual(items.length, 2);
  assert.ok(Math.abs(items[0]._startTimeSec - 5.0) < 1e-9, `B quantized to 5.0, got ${items[0]._startTimeSec}`);
  assert.ok(Math.abs(items[1]._startTimeSec - 12.0) < 1e-9, `A rippled right by B's 2 s, got ${items[1]._startTimeSec}`);
});
