// MCAM premontage: audio-only recorder WAV segments must land on A5 (past the
// video-track count). Covers the v1.6.0 fix: ensureTracks honours audio_track,
// and audio-only sources go in via the TX pattern (insert vIdx=-1, limitShift=true)
// — overwrite against a not-yet-existing A-track silently drops the audio.
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

async function trackItems(track) {
  if (!track) return [];
  let items = null;
  try { items = track.getTrackItems(1, false); } catch (e) { /* stub */ }
  if (!items) { try { items = track.getTrackItems(); } catch (e) { /* stub */ } }
  return items || [];
}

test('MCAM: 4 cams V1-V4/A1-A4 + recorder WAV on A5, two timeline positions', async () => {
  const project = new ppro._MockProject('YTUVI05');
  const cams = ['CAM_3_2190.MP4', 'CAM_1_2182.MP4', 'CAM_4_2202.MP4', 'RYA-FX3-0519.MP4'].map(n => mkClip(n, 3000));
  const rec = mkClip('05.07.26_ROMAN_SERGEEV_5.wav', 4000);
  project._rootItem._items.push(...cams, rec);
  const clipMap = { '05.07.26_ROMAN_SERGEEV_5.wav': rec };
  cams.forEach(c => { clipMap[c.name] = c; });

  const part = {
    code: 'YTUVI05', name: 'Premontage_MCAM',
    sequence_name: 'YTUVI05_2_Assembly_MCAM_v1',
    seed_clip: 'CAM_3_2190.MP4', fps: 25,
  };
  const segments = [];
  [0, 52.48].forEach((tl, gi) => {
    cams.forEach((c, ci) => segments.push({
      segment_name: `seg_1_${gi + 1} V${ci + 1}`, source_file: c.name,
      source_in_sec: 50 + tl, source_out_sec: 100 + tl, timeline_in_sec: tl,
      track: 'V' + (ci + 1), audio_track: 'A' + (ci + 1), keep_audio: true, color: 'Green',
    }));
    segments.push({
      segment_name: `seg_1_${gi + 1} REC`, source_file: rec.name,
      source_in_sec: 693 + tl, source_out_sec: 743 + tl, timeline_in_sec: tl,
      track: 'V1', audio_track: 'A5', keep_audio: true, color: 'Yellow',
    });
  });

  const result = await buildPartSequence(project, clipMap, part, segments, LOG, {});
  assert.strictEqual(result.placed, 10, 'all 10 segments placed (8 cam + 2 REC)');

  const seq = result.sequence;
  assert.ok(await seq.getAudioTrackCount() >= 5, 'sequence has A5 (insert auto-created or pre-warmed)');

  const a5 = await trackItems(await seq.getAudioTrack(4));
  assert.strictEqual(a5.length, 2, 'both recorder strips landed on A5');

  for (let v = 0; v < 4; v++) {
    const items = await trackItems(await seq.getVideoTrack(v));
    assert.strictEqual(items.length, 2, `V${v + 1} holds exactly its 2 camera segments (no WAV, no ripple dupes)`);
  }
});

test('MCAM: audio-only + keep_audio=false is skipped, not misplaced', async () => {
  const project = new ppro._MockProject('YTUVI05');
  const cam = mkClip('CAM_3_2190.MP4', 3000);
  const rec = mkClip('rec.wav', 4000);
  project._rootItem._items.push(cam, rec);
  const part = { code: 'YTUVI05', name: 'X', sequence_name: 'YTUVI05_x', seed_clip: 'CAM_3_2190.MP4', fps: 25 };
  const segments = [
    { segment_name: 's V1', source_file: 'CAM_3_2190.MP4', source_in_sec: 0, source_out_sec: 10, timeline_in_sec: 0, track: 'V1', audio_track: 'A1', keep_audio: true },
    { segment_name: 's REC', source_file: 'rec.wav', source_in_sec: 0, source_out_sec: 10, timeline_in_sec: 0, track: 'V1', audio_track: 'A5', keep_audio: false },
  ];
  const result = await buildPartSequence(project, { 'CAM_3_2190.MP4': cam, 'rec.wav': rec }, part, segments, LOG, {});
  assert.strictEqual(result.placed, 1, 'only the camera segment placed');
  assert.strictEqual(result.skipped, 1, 'muted audio-only segment skipped');
});
