const { test } = require('node:test');
const assert = require('node:assert');
const ppro = require('../../mocks/premierepro');
const wallClockBuilder = require('../../../src/ingest/placement/wallClockBuilder');

const silentLogger = {
  info: () => {},
  warn: () => {},
  error: () => {},
  debug: () => {},
};

function makeProjectAndBin() {
  const project = new ppro._MockProject();
  // Add a 00_Source bin so importFiles can target it
  const rootItem = project._rootItem;
  const sourceBin = new ppro._MockFolderItem('00_Source');
  rootItem._items.push(sourceBin);
  return { project, sourceBin };
}

function resetRecorder() {
  ppro._recorder.reset();
}

const SAMPLE_INGEST = {
  version: '2.0',
  layout_mode: 'wallclock',
  project_name: 'YTCR03_test',
  project_code: 'YTCR03',
  media: { width: 3840, height: 2160, fps: 50.0, sample_rate: 48000 },
  clips: [
    // S03 — 2-cam (DJI + iPhone)
    { clip_id: 'DJI_0075', filename: 'DJI_0075.MP4', path: '/a/03_developer_meeting/DJI/DJI_0075.MP4',
      duration: 23, wall_offset: 0, creation_time: '2026-04-02T09:01:47Z', scene: '03_developer_meeting' },
    { clip_id: 'DJI_0076', filename: 'DJI_0076.MP4', path: '/a/03_developer_meeting/DJI/DJI_0076.MP4',
      duration: 5, wall_offset: 95, creation_time: '2026-04-02T09:03:22Z', scene: '03_developer_meeting' },
    { clip_id: 'IMG_2868', filename: 'IMG_2868.MOV', path: '/a/03_developer_meeting/iPhone/IMG_2868.MOV',
      duration: 6, wall_offset: 200, creation_time: '2026-04-02T09:05:07Z', scene: '03_developer_meeting' },
  ],
  tx_strips: {
    '03_developer_meeting': [
      { tx: 'TX00', filename: 'TX00.wav', path: '/a/99_Pipeline/DJI_Audio/TX00.wav',
        creation_time: '2026-04-02T09:01:47Z', wall_offset: 0,
        duration: 1651, sample_rate: 48000 },
    ],
  },
};

// ─── validateV2Contract ─────────────────────────────────────────────────

test('validateV2Contract: throws on placeable clip missing creation_time', () => {
  assert.throws(
    () => wallClockBuilder.validateV2Contract({
      clips: [{ filename: 'a.MP4', scene: 'S', wall_offset: 0 }],
    }),
    /missing creation_time/
  );
});

test('validateV2Contract: throws on placeable clip missing wall_offset', () => {
  assert.throws(
    () => wallClockBuilder.validateV2Contract({
      clips: [{ filename: 'a.MP4', scene: 'S', creation_time: '2026-01-01T00:00:00Z' }],
    }),
    /missing numeric wall_offset/
  );
});

test('validateV2Contract: tolerates orphan clip (no scene) without wall_offset', () => {
  // Orphan clips are skipped at build time, so they need not be prepared.
  wallClockBuilder.validateV2Contract({
    clips: [{ filename: 'orphan.MOV', creation_time: '2026-01-01T00:00:00Z' }],
  });
});

test('validateV2Contract: passes valid ingest', () => {
  wallClockBuilder.validateV2Contract(SAMPLE_INGEST);
});

test('validateV2Contract: throws on non-array clips', () => {
  assert.throws(
    () => wallClockBuilder.validateV2Contract({ clips: 'not-array' }),
    /ingest.clips must be an array/
  );
});

// ─── build: full flow with mock UXP ──────────────────────────────────────

test('build: seeds sequence from media (createSequenceFromMedia) for correct format', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  await wallClockBuilder.build(project, SAMPLE_INGEST, sourceBin, silentLogger);

  // Seed-from-media inherits real resolution/fps (fixes the 1080p24 bug). The
  // empty createSequence path is only a fallback when no seed clip resolves.
  assert.strictEqual(ppro._recorder.getCalls('Project.createSequenceFromMedia').length, 1, 'createSequenceFromMedia used (seed)');
});

test('build: sequence name follows {project_code}_{scene} pattern', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  await wallClockBuilder.build(project, SAMPLE_INGEST, sourceBin, silentLogger);

  const seqCall = ppro._recorder.getCalls('Project.createSequenceFromMedia')[0];
  assert.strictEqual(seqCall.args[0], 'YTCR03_03_developer_meeting');
});

test('build: VIDEO via overwrite on correct V-tracks (DJI=V1, iPhone=V2); TX NOT via overwrite', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  await wallClockBuilder.build(project, SAMPLE_INGEST, sourceBin, silentLogger);

  // Video uses overwrite; TX uses insert. So overwrite calls are video-only.
  const overwriteCalls = ppro._recorder.getCalls('SequenceEditor.createOverwriteItemAction');
  assert.strictEqual(overwriteCalls.length, 3, '3 video overwrite placements (TX is NOT overwrite)');
  assert.ok(overwriteCalls.every(c => c.args[2] !== -1), 'no audio-only overwrite');

  const v0 = overwriteCalls.filter(c => c.args[2] === 0);
  const v1 = overwriteCalls.filter(c => c.args[2] === 1);
  assert.strictEqual(v0.length, 2, 'DJI ×2 on V1');
  assert.strictEqual(v1.length, 1, 'iPhone ×1 on V2');
});

test('build: TX placed via INSERT (audio-only) on A-track above cam audio', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  await wallClockBuilder.build(project, SAMPLE_INGEST, sourceBin, silentLogger);

  // TX uses createInsertProjectItemAction with vIdx=-1. There are also pre-warm
  // inserts; filter to audio-only (videoTrackIndex === -1) on the TX A-track.
  const txInserts = ppro._recorder.getCalls('SequenceEditor.createInsertProjectItemAction')
    .filter(c => c.args[2] === -1 && c.args[3] === 2);
  assert.strictEqual(txInserts.length, 3, '3 TX TrackItems on A3 (aIdx=2) via insert, video-bounded');
  assert.ok(txInserts.every(c => c.args[4] === true), 'TX insert uses limitShift=true');
});

test('build: TX TrackItem durations are video-bounded (NOT full WAV)', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  await wallClockBuilder.build(project, SAMPLE_INGEST, sourceBin, silentLogger);

  // Inspect the actual placed TX track items (A-track index 2) in the mock.
  const seq = (await project.getSequences())[0];
  const txTrack = await seq.getAudioTrack(2);
  const items = txTrack.getTrackItems();
  // Video union [0,23],[95,100],[200,206] → TX slices of 23s, 5s, 6s — NOT 1651s.
  const durations = items.map(i => Math.round(i._durationSec)).sort((a, b) => a - b);
  assert.deepStrictEqual(durations, [5, 6, 23], 'TX slices match video intervals, not full WAV (1651s)');
  assert.ok(!durations.includes(1651), 'no full-duration TX placement (the MF3 bug)');
});

test('build: pre-warm materialises tracks on an empty (1-track) sequence', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  await wallClockBuilder.build(project, SAMPLE_INGEST, sourceBin, silentLogger);

  // Empty createSequence starts with 1 V / 1 A track (realistic mock). Pre-warm
  // must grow to V2 (iPhone) and A3 (TX). Assert final track counts.
  const seq = (await project.getSequences())[0];
  assert.strictEqual(await seq.getVideoTrackCount(), 2, 'V1+V2 materialised (DJI, iPhone)');
  assert.ok((await seq.getAudioTrackCount()) >= 3, 'A1..A3 materialised (DJI, iPhone, TX)');
});

test('build: TickTime offsets match wall_offset values (exact grid ticks)', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  await wallClockBuilder.build(project, SAMPLE_INGEST, sourceBin, silentLogger);

  // Placements now travel as EXACT frame ticks (createWithTicks), not float
  // seconds — collect both channels and compare in seconds.
  const secs = ppro._recorder.getCalls('TickTime.createWithSeconds').map(c => c.args[0]);
  const tickSecs = ppro._recorder.getCalls('TickTime.createWithTicks')
    .map(c => Number(c.args[0]) / 254016000000);
  const offsets = [...secs, ...tickSecs];
  const has = (v) => offsets.some(o => Math.abs(o - v) < 1e-9);
  assert.ok(has(0), 'offset=0 present');
  assert.ok(has(95), 'offset=95 (DJI_0076) present');
  assert.ok(has(200), 'offset=200 (IMG_2868) present');
});

test('build: TX uses set/insert/clear in SEPARATE transactions (MF3)', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  await wallClockBuilder.build(project, SAMPLE_INGEST, sourceBin, silentLogger);

  // Each TX placement = setSourceInOut txn + insert txn + clearSourceInOut txn.
  // NOTE: raw createSetInOutPointsAction counts are NOT asserted — the seed
  // 1-frame trim and the pre-warm placeholder trim (sequenceFactory) also call
  // it, so the total is 3 TX + N housekeeping. The transaction-name counts
  // below are the real MF3 anti-regression guard.
  const clearInOut = ppro._recorder.getCalls('ClipProjectItem.createClearInOutPointsAction');
  assert.ok(clearInOut.length >= 3, 'clearInOut at least once per TX slice');

  // Structural anti-regression guard: prove these are THREE SEPARATE
  // transactions per slice (not one batched compoundAction). The undoString
  // namespaces are distinct: 'Pre-trim: ' (set), 'TX ' (insert), 'Clear trim: '
  // (clear). A regression to batching set→insert→clear into one transaction
  // would collapse these counts.
  const txns = ppro._recorder.getCalls('Project.executeTransaction').map(c => c.args[0] || '');
  const preTrim = txns.filter(s => s.startsWith('Pre-trim:'));
  const txInsert = txns.filter(s => s.startsWith('TX '));
  const clearTrim = txns.filter(s => s.startsWith('Clear trim:'));
  assert.strictEqual(preTrim.length, 3, '3 separate set-in/out transactions');
  assert.strictEqual(txInsert.length, 3, '3 separate TX insert transactions');
  assert.strictEqual(clearTrim.length, 3, '3 separate clear-in/out transactions');
});

test('build: 3-cam scene materialises V3 via pre-warm (S04 case)', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  const threeCamIngest = {
    ...SAMPLE_INGEST,
    project_code: 'YTCR03',
    clips: [
      { clip_id: 'fx3-1',  filename: 'A.MP4', path: '/a/04_with_wife/FX3/A.MP4',   duration: 10, wall_offset: 0,  creation_time: '2026-04-02T10:00:00Z', scene: '04_with_wife' },
      { clip_id: 'fx3a-1', filename: 'B.MP4', path: '/a/04_with_wife/FX3A/B.MP4',  duration: 8,  wall_offset: 15, creation_time: '2026-04-02T10:00:15Z', scene: '04_with_wife' },
      { clip_id: 'iph-1',  filename: 'C.MOV', path: '/a/04_with_wife/iPhone/C.MOV', duration: 5, wall_offset: 30, creation_time: '2026-04-02T10:00:30Z', scene: '04_with_wife' },
    ],
    cam_layers: { '04_with_wife': ['FX3', 'FX3A', 'iPhone'] },
    tx_strips: {},
  };
  await wallClockBuilder.build(project, threeCamIngest, sourceBin, silentLogger);

  const seq = (await project.getSequences())[0];
  assert.strictEqual(await seq.getVideoTrackCount(), 3, 'V3 materialised for 3-cam scene');

  // iPhone placed on V3 (vIdx=2) via overwrite — and the track existed (pre-warm),
  // so the overwrite actually landed an item there.
  const v3 = await seq.getVideoTrack(2);
  assert.strictEqual(v3.getTrackItems().length, 1, 'iPhone clip on V3');
});

test('build: importFiles called once per scene with all media (video + tx_strips)', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  await wallClockBuilder.build(project, SAMPLE_INGEST, sourceBin, silentLogger);

  const importCalls = ppro._recorder.getCalls('Project.importFiles');
  assert.strictEqual(importCalls.length, 1);
  const filePaths = importCalls[0].args[0];
  assert.strictEqual(filePaths.length, 4, '3 video + 1 tx');
  assert.ok(filePaths.some(p => p.includes('TX00.wav')), 'TX WAV imported');
});

test('build: VIDEO clips go one-per-transaction in ascending order (compound executes in REVERSE — batching eats successor heads)', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  await wallClockBuilder.build(project, SAMPLE_INGEST, sourceBin, silentLogger);

  const videoTxns = ppro._recorder.getCalls('Project.executeTransaction')
    .filter(c => String(c.args[0]).startsWith('Wall-clock video: '));
  assert.strictEqual(videoTxns.length, 3, 'one transaction per video clip — NOT one batched compound');
});

test('build: returns proper summary with totalDuration', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  const result = await wallClockBuilder.build(project, SAMPLE_INGEST, sourceBin, silentLogger);

  assert.strictEqual(result.sequences.length, 1);
  assert.strictEqual(result.totalClipCount, 3, '3 video clips placed');
  assert.strictEqual(result.totalTxPlaced, 3, '3 TX TrackItems (one per video-bounded interval)');
  assert.strictEqual(result.sequences[0].sceneName, '03_developer_meeting');
  // Compression default ON: raw span 206s collapses (DJI [0,23],[95,100] + iPhone
  // [200,206]; two >3s gaps → 2s each) → ~38s. totalDuration reflects the COMPRESSED
  // span, finite, and far below the raw 206.
  const td = result.sequences[0].totalDuration;
  assert.ok(Number.isFinite(td), 'totalDuration is finite (not NaN)');
  assert.ok(td > 0 && td < 60, `compressed span ~38s, got ${td}`);
});

test('build: two same-label TX files share ONE A-track (NEW-4 spanning TX)', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  const spanningIngest = {
    ...SAMPLE_INGEST,
    clips: [
      { clip_id: 'A', filename: 'A.MP4', path: '/a/07_street_outro/FX3A/A.MP4', duration: 60, wall_offset: 0, creation_time: '2026-04-02T10:00:00Z', scene: '07_street_outro' },
    ],
    tx_strips: {
      '07_street_outro': [
        { tx: 'TX02', filename: 'TX02_p1.wav', path: '/a/TX02_p1.wav', creation_time: '2026-04-02T10:00:00Z', wall_offset: 0,  duration: 25, sample_rate: 48000 },
        { tx: 'TX02', filename: 'TX02_p2.wav', path: '/a/TX02_p2.wav', creation_time: '2026-04-02T10:00:30Z', wall_offset: 30, duration: 25, sample_rate: 48000 },
      ],
    },
  };
  await wallClockBuilder.build(project, spanningIngest, sourceBin, silentLogger);

  // Both TX02 fragments must land on the SAME A-track (one logical lavalier).
  const txInserts = ppro._recorder.getCalls('SequenceEditor.createInsertProjectItemAction')
    .filter(c => c.args[2] === -1);
  const aIndices = new Set(txInserts.map(c => c.args[3]));
  assert.strictEqual(aIndices.size, 1, 'both TX02 fragments on one A-track');
  assert.strictEqual([...aIndices][0], 1, 'TX on A2 (1-cam scene → tx_aIdx_base=1)');
});

test('build: rejects v1.x JSON missing creation_time on placeable clip', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  const legacyIngest = {
    version: '1.1',
    project_name: 'legacy',
    media: { width: 3840, height: 2160, fps: 25, sample_rate: 48000 },
    clips: [
      { clip_id: 'X', filename: 'X.MP4', path: '/a/FX3/X.MP4', duration: 10, scene: 'A' },
    ],
  };
  await assert.rejects(
    wallClockBuilder.build(project, legacyIngest, sourceBin, silentLogger),
    /missing creation_time/
  );
});

test('build: skips orphan _all scene (no junk sequence)', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  const withOrphan = {
    ...SAMPLE_INGEST,
    clips: [
      ...SAMPLE_INGEST.clips,
      // orphan: no scene → binImporter buckets into '_all'
      { clip_id: 'IMG_2010', filename: 'IMG_2010.MOV', path: '/a/Video/IMG_2010.MOV', duration: 5, creation_time: '2026-04-11T10:00:00Z' },
    ],
  };
  const result = await wallClockBuilder.build(project, withOrphan, sourceBin, silentLogger);
  // Only the real scene builds; no YTCR03__all sequence.
  assert.strictEqual(result.sequences.length, 1);
  assert.ok(!result.sequences.some(s => s.sceneName === '_all'), 'no _all junk sequence');
});

test('build: skips invalid TX (sample_rate mismatch) without aborting', async () => {
  resetRecorder();
  const { project, sourceBin } = makeProjectAndBin();
  const badTxIngest = {
    ...SAMPLE_INGEST,
    tx_strips: {
      '03_developer_meeting': [{
        tx: 'TX00', filename: 'tx.wav', path: '/a/tx.wav',
        creation_time: '2026-04-02T09:01:47Z', wall_offset: 0,
        duration: 100, sample_rate: 44100,  // mismatch with media.sample_rate=48000
      }],
    },
  };
  const result = await wallClockBuilder.build(project, badTxIngest, sourceBin, silentLogger);
  assert.strictEqual(result.totalClipCount, 3);
  assert.strictEqual(result.totalTxPlaced, 0, 'mismatched TX skipped');
});
