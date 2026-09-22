// Tests: review-CUT mode of partsBuilder (V1 rebuilt from trimmed render base_segments,
// cuttable; render voice audio kept on A1; overlays on V2/V3 never touch A1).
const test = require('node:test');
const assert = require('node:assert');
const ppro = require('../mocks/premierepro');
const { buildPartSequence } = require('../../src/parts/partsBuilder');

function mkClip(name, dur) {
  const c = new ppro._MockClipProjectItem(name, '/abs/' + name);
  c._durationSec = dur || 12;
  return c;
}
const LOG = { info() {}, warn() {}, error() {}, debug() {} };

function basePart() {
  return {
    code: 'YTCR01', name: 'Review_v3', sequence_name: 'YTCR01_5_Review_v3',
    build_model: 'review_cut_overlay', base_clip: 'YTCR1_v9_Arty_Dzis.mp4',
    base_clip_path: '/abs/YTCR1_v9_Arty_Dzis.mp4', fps: 25,
  };
}

test('review-CUT: V1 rebuilt from base_segments (one TrackItem per kept segment), overlays on V2/V3', async () => {
  const project = new ppro._MockProject('YTCR01');
  const base = mkClip('YTCR1_v9_Arty_Dzis.mp4', 855);
  const c1 = mkClip('C5280.MP4', 6);
  const c2 = mkClip('C7770.MP4', 4);
  project._rootItem._items.push(base, c1, c2);
  const clipMap = {
    'YTCR1_v9_Arty_Dzis.mp4': base,
    'C5280.MP4': c1, 'C5280': c1, 'C7770.MP4': c2, 'C7770': c2,
  };
  const part = Object.assign(basePart(), {
    // 3 kept render segments (a cut removed the middle of the render -> tightened timeline)
    base_segments: [
      { seg_id: 't000', source_file: 'YTCR1_v9_Arty_Dzis.mp4', source_in_sec: 0, source_out_sec: 100, timeline_in_sec: 0, keep_audio: true, track: 'V1', audio_track: 'A1' },
      { seg_id: 't001', source_file: 'YTCR1_v9_Arty_Dzis.mp4', source_in_sec: 102, source_out_sec: 400, timeline_in_sec: 100, keep_audio: true, track: 'V1', audio_track: 'A1' },
      { seg_id: 't002', source_file: 'YTCR1_v9_Arty_Dzis.mp4', source_in_sec: 400, source_out_sec: 855, timeline_in_sec: 398, keep_audio: true, track: 'V1', audio_track: 'A1' },
    ],
  });
  const segments = [
    { segment_id: 'ins_001', track: 'V2', audio_track: 'A2', keep_audio: true, source_file: 'C5280.MP4', covers_gap: true, source_in_sec: 0, source_out_sec: 3.5, timeline_in_sec: 50, timeline_out_sec: 53.5, scene: 'dubai_driving', clip_id: 'C5280', note: 'gap fill' },
    { segment_id: 'ins_002', track: 'V3', audio_track: 'A3', keep_audio: true, source_file: 'C7770.MP4', source_in_sec: 0, source_out_sec: 3, timeline_in_sec: 200, timeline_out_sec: 203, scene: '07_new_office', clip_id: 'C7770', note: 'liveliness' },
  ];
  const result = await buildPartSequence(project, clipMap, part, segments, LOG, {});
  assert.ok(result && result.sequence, 'returns a sequence');
  assert.strictEqual(result.cutMode, true, 'cutMode active');
  assert.strictEqual(result.basePlaced, 3, 'all 3 base render segments placed on V1');
  assert.strictEqual(result.placed, 2, 'both overlays placed');

  // V1 holds exactly the 3 base segments (NOT one full render clip)
  const v1 = await result.sequence.getVideoTrack(0);
  assert.strictEqual(v1.getTrackItems().length, 3, 'V1 = 3 trimmed render segments (cuttable)');
  // A1 holds the 3 render voice segments (audio kept)
  const a1 = await result.sequence.getAudioTrack(0);
  assert.strictEqual(a1.getTrackItems().length, 3, 'A1 = 3 render voice segments (VO preserved)');
  // overlays landed on V2 / V3
  assert.strictEqual((await result.sequence.getVideoTrack(1)).getTrackItems().length, 1, 'V2 = 1 overlay');
  assert.strictEqual((await result.sequence.getVideoTrack(2)).getTrackItems().length, 1, 'V3 = 1 overlay');
});

test('review-CUT: base_segment.disabled → V1 and A1 piece disabled (Roman marked "cut"), neighbours enabled', async () => {
  const project = new ppro._MockProject('YTUVI02');
  const base = mkClip('YTCR1_v9_Arty_Dzis.mp4', 120);
  project._rootItem._items.push(base);
  const part = Object.assign(basePart(), {
    base_segments: [
      { seg_id: 'on_01', source_in_sec: 0, source_out_sec: 40.2, timeline_in_sec: 0, timeline_out_sec: 40.2 },
      { seg_id: 'off_02', source_in_sec: 40.2, source_out_sec: 57.32, timeline_in_sec: 40.2, timeline_out_sec: 57.32, disabled: true },
      { seg_id: 'on_03', source_in_sec: 57.32, source_out_sec: 120, timeline_in_sec: 57.32, timeline_out_sec: 120 },
    ],
  });
  const result = await buildPartSequence(project, { 'YTCR1_v9_Arty_Dzis.mp4': base }, part, [], LOG, {});
  assert.strictEqual(result.basePlaced, 3, 'three V1 pieces placed');
  for (const [label, track] of [['V1', await result.sequence.getVideoTrack(0)], ['A1', await result.sequence.getAudioTrack(0)]]) {
    const items = track.getTrackItems();
    const states = [];
    for (const it of items) states.push([Number((await it.getStartTime()).seconds.toFixed(2)), await it.isDisabled()]);
    states.sort((a, b) => a[0] - b[0]);
    assert.deepStrictEqual(states.map((s) => s[1]), [false, true, false], label + ': only the 40.20–57.32 piece is disabled');
  }
});

test('review-CUT: overlay audio NEVER lands on A1 (render voice protected)', async () => {
  const project = new ppro._MockProject('YTCR01');
  const base = mkClip('YTCR1_v9_Arty_Dzis.mp4', 855);
  const still = mkClip('chart.png', 3); still._isStill = true;
  const vid = mkClip('C5276.MP4', 6);
  project._rootItem._items.push(base, still, vid);
  const clipMap = { 'YTCR1_v9_Arty_Dzis.mp4': base, 'chart.png': still, 'chart': still, 'C5276.MP4': vid, 'C5276': vid };
  const part = Object.assign(basePart(), {
    base_segments: [
      { seg_id: 't000', source_file: 'YTCR1_v9_Arty_Dzis.mp4', source_in_sec: 0, source_out_sec: 855, timeline_in_sec: 0, keep_audio: true },
    ],
  });
  const segments = [
    // still with keep_audio:false (the case that historically cut render audio when routed to A1)
    { segment_id: 'ins_036', track: 'V3', audio_track: '', keep_audio: false, is_still: true, source_file: 'chart.png', source_in_sec: 0, source_out_sec: 3, timeline_in_sec: 245, timeline_out_sec: 248, scene: 'mat_x', clip_id: 'chart' },
    { segment_id: 'ins_037', track: 'V2', audio_track: 'A2', keep_audio: true, source_file: 'C5276.MP4', source_in_sec: 0, source_out_sec: 3, timeline_in_sec: 250, timeline_out_sec: 253, scene: 'dubai_driving', clip_id: 'C5276' },
  ];
  const result = await buildPartSequence(project, clipMap, part, segments, LOG, {});
  const a1 = await result.sequence.getAudioTrack(0);
  assert.strictEqual(a1.getTrackItems().length, 1, 'A1 holds ONLY the render voice segment (no overlay audio cut it)');
});

test('review-CUT: no base_segments -> falls back to full-render overlay mode (backward compat)', async () => {
  const project = new ppro._MockProject('YTCR01');
  const base = mkClip('YTCR1_v9_Arty_Dzis.mp4', 855);
  project._rootItem._items.push(base);
  const part = Object.assign(basePart(), { build_model: 'overlay_on_base' }); // no base_segments
  const result = await buildPartSequence(project, { 'YTCR1_v9_Arty_Dzis.mp4': base }, part, [], LOG, {});
  assert.strictEqual(result.cutMode, false, 'cutMode off without base_segments');
  const v1 = await result.sequence.getVideoTrack(0);
  assert.strictEqual(v1.getTrackItems().length, 1, 'V1 keeps the single full render clip');
});

test('review-overlay: cut_suggestions become ✂ markers (NOT cuts), V1 stays the full render', async () => {
  const project = new ppro._MockProject('YTCR01');
  const base = mkClip('YTCR1_v9_Arty_Dzis.mp4', 855);
  const c1 = mkClip('C5280.MP4', 6);
  project._rootItem._items.push(base, c1);
  const clipMap = { 'YTCR1_v9_Arty_Dzis.mp4': base, 'C5280.MP4': c1, 'C5280': c1 };
  const part = Object.assign(basePart(), {
    build_model: 'overlay_on_base',
    cut_suggestions: [
      { id: 'cut_a', tc_sec: 614.2, reason: 'stutter "we we buy"', text: 'but then we we buy', confidence: 'safe' },
      { id: 'cut_b', tc_sec: 197.9, reason: 'emphatic yeah run', text: 'Yeah, yeah, yeah', confidence: 'optional' },
    ],
  });
  const segments = [
    { segment_id: 'ins_001', track: 'V3', audio_track: 'A3', keep_audio: true, source_file: 'C5280.MP4', source_in_sec: 0, source_out_sec: 3, timeline_in_sec: 100, scene: 'dubai_driving', clip_id: 'C5280', note: 'liveliness' },
  ];
  const result = await buildPartSequence(project, clipMap, part, segments, LOG, {});
  // V1 is the FULL render (one clip) — cut_suggestions do NOT remove anything
  const v1 = await result.sequence.getVideoTrack(0);
  assert.strictEqual(v1.getTrackItems().length, 1, 'V1 keeps the full render (no cuts applied)');
  assert.strictEqual(result.cutMode, false, 'not cutMode');
  // markers = 1 per overlay + 2 cut-suggestions = 3
  assert.strictEqual(result.markers, 3, 'overlay marker + 2 cut-suggestion markers placed');
});
