// Smoke test: review-overlay mode of partsBuilder (base render kept on V1, inserts overlaid, markers).
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

test('review-overlay: base render kept on V1, inserts placed, no throw', async () => {
  const project = new ppro._MockProject('YTCR01');
  const base = mkClip('YTCR1_v9_Arty_Dzis.mp4', 855);
  const c1 = mkClip('C5280.MP4', 6);
  const c2 = mkClip('C7770.MP4', 4);
  project._rootItem._items.push(base, c1, c2); // findable in project tree (BFS)
  const clipMap = {
    'YTCR1_v9_Arty_Dzis.mp4': base,
    'C5280.MP4': c1, 'C5280': c1,
    'C7770.MP4': c2, 'C7770': c2,
  };
  const part = {
    code: 'YTCR01', name: 'Review_v1_overlay', sequence_name: 'YTCR01_5_Review_v1_overlay',
    build_model: 'overlay_on_base', base_clip: 'YTCR1_v9_Arty_Dzis.mp4',
    base_clip_path: '/abs/YTCR1_v9_Arty_Dzis.mp4', fps: 25,
  };
  const segments = [
    { segment_id: 'ins_001', track: 'V2', audio_track: 'A2', keep_audio: true, source_file: 'C5280.MP4', covers_gap: true, source_in_sec: 0, source_out_sec: 3.5, timeline_in_sec: 112, timeline_out_sec: 115.5, scene: 'dubai_driving', clip_id: 'C5280', note: '[1:52 ПРОВИСАНИЕ] x' },
    { segment_id: 'ins_002', track: 'V3', audio_track: 'A3', keep_audio: true, source_file: 'C7770.MP4', covers_gap: false, source_in_sec: 0, source_out_sec: 3, timeline_in_sec: 430, timeline_out_sec: 433, scene: '07_new_office', clip_id: 'C7770', note: '[7:09 живость] y' },
  ];
  const result = await buildPartSequence(project, clipMap, part, segments, LOG, {});
  assert.ok(result && result.sequence, 'returns a sequence');
  assert.strictEqual(result.placed, 2, 'both inserts placed');
  // V1 (track 0) must STILL hold the base render (review mode does NOT clear it)
  const v1 = await result.sequence.getVideoTrack(0);
  let items = null;
  try { items = v1.getTrackItems(1, false); } catch (e) {}
  if (!items) { try { items = v1.getTrackItems(); } catch (e) {} }
  assert.ok(items && items.length >= 1, 'V1 retains the base render clip');
});

test('review-overlay: inserts never write to A1 (render audio protected)', async () => {
  const project = new ppro._MockProject('YTCR01');
  const base = mkClip('YTCR1_v9_Arty_Dzis.mp4', 855);
  const still = mkClip('alex.png', 3); still._isStill = true;
  const vid = mkClip('C5276.MP4', 6);
  project._rootItem._items.push(base, still, vid);
  const clipMap = { 'YTCR1_v9_Arty_Dzis.mp4': base, 'alex.png': still, 'alex': still, 'C5276.MP4': vid, 'C5276': vid };
  const part = {
    code: 'YTCR01', name: 'R', sequence_name: 'YTCR01_5_Review_x_overlay',
    build_model: 'overlay_on_base', base_clip: 'YTCR1_v9_Arty_Dzis.mp4', base_clip_path: '/abs/YTCR1_v9_Arty_Dzis.mp4', fps: 25,
  };
  const segments = [
    // a still with keep_audio:false (this is the case that used to land on A1 and cut the render audio)
    { segment_id: 'ins_036', track: 'V3', audio_track: '', keep_audio: false, is_still: true, source_file: 'alex.png', source_in_sec: 0, source_out_sec: 3, timeline_in_sec: 245, timeline_out_sec: 248, scene: 'mat_meras', clip_id: 'alex' },
    { segment_id: 'ins_037', track: 'V2', audio_track: 'A2', keep_audio: true, is_still: false, source_file: 'C5276.MP4', source_in_sec: 0, source_out_sec: 3, timeline_in_sec: 250, timeline_out_sec: 253, scene: 'dubai_driving', clip_id: 'C5276' },
  ];
  const result = await buildPartSequence(project, clipMap, part, segments, LOG, {});
  var a1 = await result.sequence.getAudioTrack(0);
  var a1items = null;
  try { a1items = a1.getTrackItems(1, false); } catch (e) {}
  if (!a1items) { try { a1items = a1.getTrackItems(); } catch (e) {} }
  assert.strictEqual(a1items.length, 1, 'A1 holds ONLY the base render audio (no insert cut it)');
});

test('review-overlay: empty insert set still builds the base scaffold', async () => {
  const project = new ppro._MockProject('YTCR01');
  const base = mkClip('YTCR1_v9_Arty_Dzis.mp4', 855);
  project._rootItem._items.push(base);
  const part = {
    code: 'YTCR01', name: 'Review_scaffold', sequence_name: 'YTCR01_5_Review_scaffold',
    build_model: 'overlay_on_base', base_clip: 'YTCR1_v9_Arty_Dzis.mp4',
    base_clip_path: '/abs/YTCR1_v9_Arty_Dzis.mp4', fps: 25,
  };
  const result = await buildPartSequence(project, { 'YTCR1_v9_Arty_Dzis.mp4': base }, part, [], LOG, {});
  assert.ok(result && result.sequence, 'scaffold sequence built with 0 inserts');
});

test('non-review parts build still works (no base_clip → normal absolute placement)', async () => {
  const project = new ppro._MockProject('YTCR01');
  const c1 = mkClip('C5280.MP4', 6);
  project._rootItem._items.push(c1);
  const part = { code: 'YTCR01', name: 'Inserts', sequence_name: 'YTCR01_part_Inserts', build_model: 'absolute', fps: 25 };
  const segments = [{ segment_id: 'ins_001', track: 'V2', audio_track: 'A2', keep_audio: true, source_file: 'C5280.MP4', source_in_sec: 0, source_out_sec: 3.5, timeline_in_sec: 0, timeline_out_sec: 3.5 }];
  const result = await buildPartSequence(project, { 'C5280.MP4': c1, 'C5280': c1 }, part, segments, LOG, {});
  assert.strictEqual(result.placed, 1, 'insert placed in normal mode');
});
