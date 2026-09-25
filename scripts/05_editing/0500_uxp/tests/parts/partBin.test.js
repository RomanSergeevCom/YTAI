// part.bin (partsBuilder v1.7.0): built sequence moves into a top-level bin —
// found by exact name at project root or created via the instance createBinAction
// (_Part_media pattern; the STATIC FolderItem.createAddItemAction is absent in 25.6).
// Every step is non-fatal: any failure warns and leaves the sequence in root.
// Also covers UNCOMPRESSED (recorder-relative) placement for DeletedScene-style parts.
const test = require('node:test');
const assert = require('node:assert');
const ppro = require('../mocks/premierepro');
const { buildPartSequence } = require('../../src/parts/partsBuilder');

function mkClip(name, dur) {
  const c = new ppro._MockClipProjectItem(name, '/abs/' + name);
  c._durationSec = dur || 60;
  return c;
}
const LOG = { info() {}, warn() {}, error() {}, debug() {} };

function rootFolder(project, name) {
  return project._rootItem._items.find(i => i && i.type === 2 && i.name === name);
}
function inRoot(project, name) {
  return project._rootItem._items.some(i => i && i.name === name && i.type !== 2);
}

async function trackItems(track) {
  if (!track) return [];
  let items = null;
  try { items = track.getTrackItems(1, false); } catch (e) { /* stub */ }
  if (!items) { try { items = track.getTrackItems(); } catch (e) { /* stub */ } }
  return items || [];
}

function basicPart(bin) {
  const part = {
    code: 'YTUVI05', name: 'A01_Studio',
    sequence_name: 'YTUVI05_A01_Studio',
    seed_clip: 'CAM_3_2190.MP4', fps: 25,
  };
  if (bin) part.bin = bin;
  return part;
}
const basicSegments = [
  { segment_name: 's1 V1', source_file: 'CAM_3_2190.MP4', source_in_sec: 0, source_out_sec: 10, timeline_in_sec: 0, track: 'V1', audio_track: 'A1', keep_audio: true, color: 'Green' },
];

test('part.bin: bin auto-created and built sequence moved into it', async () => {
  const project = new ppro._MockProject('YTUVI05');
  const cam = mkClip('CAM_3_2190.MP4', 3000);
  project._rootItem._items.push(cam);

  ppro._recorder.reset();
  const result = await buildPartSequence(project, { 'CAM_3_2190.MP4': cam }, basicPart('02_Assembly'), basicSegments, LOG, {});

  assert.strictEqual(result.bin, '02_Assembly', 'result.bin reports the bin');
  const binCalls = ppro._recorder.getCalls('FolderItem.createBinAction').filter(c => c.args[0] === '02_Assembly');
  assert.strictEqual(binCalls.length, 1, 'bin created exactly once');
  assert.strictEqual(binCalls[0].args[1], true, 'createBinAction(name, true)');
  assert.strictEqual(ppro._recorder.getCalls('FolderItem.createMoveItemAction').length, 1, 'one move action');

  const bin = rootFolder(project, '02_Assembly');
  assert.ok(bin, '02_Assembly bin exists at project root');
  assert.ok(bin._items.some(i => i.name === 'YTUVI05_A01_Studio'), 'sequence item inside the bin');
  assert.ok(!inRoot(project, 'YTUVI05_A01_Studio'), 'sequence item no longer at project root');
});

test('part.bin absent: zero behavior change (no bin/move calls, bin=null)', async () => {
  const project = new ppro._MockProject('YTUVI05');
  const cam = mkClip('CAM_3_2190.MP4', 3000);
  project._rootItem._items.push(cam);

  ppro._recorder.reset();
  const result = await buildPartSequence(project, { 'CAM_3_2190.MP4': cam }, basicPart(null), basicSegments, LOG, {});

  assert.strictEqual(result.bin, null, 'result.bin is null');
  // cleanExistingSequence may legitimately create its 03_Assembly ARCHIVE bin —
  // "no part.bin" only means no TARGET bin and no move of the built sequence.
  const targetBinCalls = ppro._recorder.getCalls('FolderItem.createBinAction')
    .filter(c => c.args[0] !== '03_Assembly');
  assert.strictEqual(targetBinCalls.length, 0, 'no target bin created');
  assert.strictEqual(ppro._recorder.getCalls('FolderItem.createMoveItemAction').length, 0, 'no move');
  assert.ok(inRoot(project, 'YTUVI05_A01_Studio'), 'sequence item stays at project root');
});

test('part.bin: existing bin reused (no duplicate createBinAction)', async () => {
  const project = new ppro._MockProject('YTUVI05');
  const cam = mkClip('CAM_3_2190.MP4', 3000);
  const bin = new ppro._MockFolderItem('02_Assembly');
  project._rootItem._items.push(cam, bin);

  ppro._recorder.reset();
  const result = await buildPartSequence(project, { 'CAM_3_2190.MP4': cam }, basicPart('02_Assembly'), basicSegments, LOG, {});

  assert.strictEqual(result.bin, '02_Assembly');
  const binCalls = ppro._recorder.getCalls('FolderItem.createBinAction').filter(c => c.args[0] === '02_Assembly');
  assert.strictEqual(binCalls.length, 0, 'no createBinAction on an existing name (dup "02_Assembly 2" trap)');
  assert.ok(bin._items.some(i => i.name === 'YTUVI05_A01_Studio'), 'sequence moved into the pre-existing bin');
});

test('part.bin: move failure is non-fatal — build succeeds, sequence left in root', async () => {
  const project = new ppro._MockProject('YTUVI05');
  const cam = mkClip('CAM_3_2190.MP4', 3000);
  const bin = new ppro._MockFolderItem('02_Assembly');
  // v1.12.0: the move is called on the project ROOT with (item, newParent) — stub THAT.
  project._rootItem.createMoveItemAction = function () { throw new Error('move denied'); };
  project._rootItem._items.push(cam, bin);

  const warns = [];
  const log = { info() {}, warn(m) { warns.push(m); }, error() {}, debug() {} };
  const result = await buildPartSequence(project, { 'CAM_3_2190.MP4': cam }, basicPart('02_Assembly'), basicSegments, log, {});

  assert.strictEqual(result.placed, 1, 'build itself succeeded');
  assert.strictEqual(result.bin, null, 'bin=null on move failure');
  assert.ok(inRoot(project, 'YTUVI05_A01_Studio'), 'sequence item still at project root');
  assert.ok(warns.some(w => /move to bin failed|left in project root/.test(w)), 'failure warned');
});

test('part.bin 00_Source_Timelines (SSEF scene 18): two-arg move on ROOT, verified, rebuild archives the binned copy', async () => {
  const project = new ppro._MockProject('YTUVI02');
  const cam = mkClip('CAM_3_2190.MP4', 3000);
  project._rootItem._items.push(cam);
  const part = { code: 'YTUVI02', name: 'SSEF', sequence_name: 'YTUVI02_18_SSEF_Commentary',
    seed_clip: 'CAM_3_2190.MP4', fps: 25, bin: '00_Source_Timelines' };

  ppro._recorder.reset();
  const r1 = await buildPartSequence(project, { 'CAM_3_2190.MP4': cam }, part, basicSegments, LOG, {});
  assert.strictEqual(r1.bin, '00_Source_Timelines');
  const move = ppro._recorder.getCalls('FolderItem.createMoveItemAction')[0];
  assert.strictEqual(move.args[1], rootFolder(project, '00_Source_Timelines'), 'destination passed as 2nd arg');
  assert.ok(!inRoot(project, 'YTUVI02_18_SSEF_Commentary'), 'not at root');

  // Rebuild: the copy inside the bin is archived (renamed _v1 → 03_Assembly), new one filed.
  const r2 = await buildPartSequence(project, { 'CAM_3_2190.MP4': cam }, part, basicSegments, LOG, {});
  assert.strictEqual(r2.bin, '00_Source_Timelines');
  const bin = rootFolder(project, '00_Source_Timelines');
  assert.strictEqual(bin._items.filter(i => i.name === 'YTUVI02_18_SSEF_Commentary').length, 1, 'exactly one live copy in the bin');
  const archive = rootFolder(project, '03_Assembly');
  assert.ok(archive && archive._items.some(i => i.name === 'YTUVI02_18_SSEF_Commentary_v1'), 'old build archived as _v1');
});

test('UNCOMPRESSED DeletedScene-style: exact recorder-relative positions, WAV on A5, no extra items', async () => {
  const project = new ppro._MockProject('YTUVI05');
  const cam1 = mkClip('CAM_3_2190.MP4', 3100);
  const cam2 = mkClip('CAM_1_2182.MP4', 3100);
  const rec = mkClip('05.07.26_ROMAN_SERGEEV_5.wav', 4000);
  project._rootItem._items.push(cam1, cam2, rec);
  const clipMap = { 'CAM_3_2190.MP4': cam1, 'CAM_1_2182.MP4': cam2, '05.07.26_ROMAN_SERGEEV_5.wav': rec };

  const part = {
    code: 'YTUVI05', name: 'A01_Studio__DeletedScene',
    sequence_name: 'YTUVI05_A01_Studio__DeletedScene',
    seed_clip: 'CAM_3_2190.MP4', fps: 25, bin: '02_Assembly',
  };
  // Two pieces, absolute REC-relative timeline (leading gap, big hole between).
  const pieces = [
    { tl: 639.53, dur: 53.89 },
    { tl: 3096.2, dur: 47.52 },
  ];
  const segments = [];
  pieces.forEach((p, gi) => {
    segments.push({
      segment_name: `cut_${gi} V1`, source_file: 'CAM_3_2190.MP4',
      source_in_sec: 100 + gi * 500, source_out_sec: 100 + gi * 500 + p.dur, timeline_in_sec: p.tl,
      track: 'V1', audio_track: 'A1', keep_audio: true, color: 'Green',
    });
    segments.push({
      segment_name: `cut_${gi} V2`, source_file: 'CAM_1_2182.MP4',
      source_in_sec: 200 + gi * 500, source_out_sec: 200 + gi * 500 + p.dur, timeline_in_sec: p.tl,
      track: 'V2', audio_track: 'A2', keep_audio: true, color: 'Cyan',
    });
    // REC-local identity: source_in == timeline_in
    segments.push({
      segment_name: `cut_${gi} REC`, source_file: '05.07.26_ROMAN_SERGEEV_5.wav',
      source_in_sec: p.tl, source_out_sec: p.tl + p.dur, timeline_in_sec: p.tl,
      track: 'V1', audio_track: 'A5', keep_audio: true, color: 'Yellow',
    });
  });

  ppro._recorder.reset();
  const result = await buildPartSequence(project, clipMap, part, segments, LOG, {});
  assert.strictEqual(result.placed, 6, 'all 6 segments placed (4 cam + 2 REC)');
  assert.strictEqual(result.bin, '02_Assembly');

  const seq = result.sequence;
  const near = (a, b) => Math.abs(a - b) < 1e-6;

  // Camera overwrites recorded at the ABSOLUTE positions (never compressed to 0).
  const ow = ppro._recorder.getCalls('SequenceEditor.createOverwriteItemAction')
    .filter(c => c.args[0] === cam1 || c.args[0] === cam2);
  assert.strictEqual(ow.length, 4);
  pieces.forEach(p => {
    assert.strictEqual(ow.filter(c => near(c.args[1].seconds, p.tl)).length, 2, `2 cam overwrites @ ${p.tl}`);
  });

  // WAV via TX pattern: insert vIdx=-1, A5 (idx 4), limitShift=true, at REC positions.
  const recIns = ppro._recorder.getCalls('SequenceEditor.createInsertProjectItemAction')
    .filter(c => c.args[0] === rec);
  assert.strictEqual(recIns.length, 2);
  recIns.forEach(c => {
    assert.strictEqual(c.args[2], -1, 'no video track');
    assert.strictEqual(c.args[3], 4, 'A5');
    assert.strictEqual(c.args[4], true, 'limitShift');
  });
  assert.ok(pieces.every(p => recIns.some(c => near(c.args[1].seconds, p.tl))), 'REC strips at piece positions');

  // Structure: each track holds EXACTLY its pieces at exact positions, nothing at 0.
  for (const [trGet, idx, label] of [[seq.getVideoTrack.bind(seq), 0, 'V1'], [seq.getVideoTrack.bind(seq), 1, 'V2'], [seq.getAudioTrack.bind(seq), 4, 'A5']]) {
    const items = await trackItems(await trGet(idx));
    assert.strictEqual(items.length, 2, `${label} holds exactly 2 pieces (seed/pre-warm cleared)`);
    const starts = items.map(i => i._startTimeSec).sort((a, b) => a - b);
    // 639.53 is sub-frame @25p — real Premiere (and the mock since 17.08.2026)
    // rounds the insert position to the NEAREST frame: 639.52.
    assert.ok(near(starts[0], 639.52) && near(starts[1], 3096.2), `${label} pieces at 639.52/3096.2, got ${starts}`);
    assert.ok(items.every(i => i._startTimeSec > 0), `${label} has no item at 0`);
  }
  const a5 = (await trackItems(await seq.getAudioTrack(4))).sort((a, b) => a._startTimeSec - b._startTimeSec);
  // in=639.53/out=693.42 are sub-frame — real Premiere FLOORS setSourceInOut
  // to the frame grid (mock models it since 17.08.2026): 639.52/693.40 → 53.88.
  assert.ok(near(a5[0]._durationSec, 53.88) && near(a5[1]._durationSec, 47.52), 'REC strips carry the trimmed source ranges');
});
