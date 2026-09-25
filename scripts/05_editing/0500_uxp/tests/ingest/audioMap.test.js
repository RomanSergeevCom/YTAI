/**
 * audioMap.test.js — Export Audio Map 1.3: the map is the timeline AS IT IS
 * (Roman 25.09.2026: «чтобы показать расхождение»). Nothing on a track may be
 * missing from the map; special items are flagged, not dropped.
 */
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const ppro = require('../mocks/premierepro');
const AM = require('../../src/ingest/audioMap');

// A YTUVIE01-like layout: V1 FX3 · V2 ZV-E1 · V3 screen · lav on A5/A6.
async function scene() {
  const seq = new ppro._MockSequence('YTUVIE01_01_zachem_nuzhen', { videoTracks: 3, audioTracks: 6 });
  const put = async (kind, idx, name, start, dur, path, srcIn) => {
    const t = kind === 'V' ? await seq.getVideoTrack(idx) : await seq.getAudioTrack(idx);
    const ti = t._addItem(name, start, dur);
    ti._projectItem = new ppro._MockClipProjectItem(name, path || '/p/01_Source/Video/01_zachem_nuzhen/' + name);
    if (srcIn != null) ti._sourceInSec = srcIn;
    return ti;
  };
  await put('V', 0, 'FX3_0001.MP4', 0, 60, null, 12.5);
  await put('A', 0, 'FX3_0001.MP4', 0, 60, null, 12.5);          // linked camera audio
  await put('V', 1, 'ZVE1_0007.MP4', 10, 40);
  await put('A', 1, 'ZVE1_0007.MP4', 10, 40);
  const off = await put('V', 2, 'screen.mov', 20, 15);
  off._disabled = true;                                           // Clip → Enable off
  await put('V', 0, 'FX3_0001.MP4', 0.08, 0.04);                  // one-frame pre-warm stray
  await put('A', 4, 'TX01_01_zachem_nuzhen_timeline.wav', 0, 90, '/p/99_Pipeline/DJI_Audio/TX01.wav', 3.25);
  await put('A', 5, 'TX02_01_zachem_nuzhen_timeline.wav', 0, 90, '/p/99_Pipeline/DJI_Audio/TX02.wav', 3.25);
  return seq;
}

describe('audioMap — the map is the whole timeline', () => {
  it('every item of every track is in the map, including audio with no video above it', async () => {
    const read = await AM.readSequence(await scene(), null);
    const map = AM.buildSequenceMap(read, 'T');
    assert.equal(map.summary.items_total, 8, 'nothing dropped');
    assert.deepEqual(map.summary.items_per_track, { V1: 2, V2: 1, V3: 1, A1: 1, A2: 1, A3: 0, A4: 0, A5: 1, A6: 1 });
    // lav runs 0–90 s, video ends at 60 s: the midpoint (45 s) still has FX3 above,
    // but the lav items exist as items in their own right regardless:
    assert.equal(map.tracks.A5[0].kind, 'dji');
    assert.equal(map.tracks.A5[0].tx, 'TX01');
  });

  it('source in/out, ticks and real media paths are recorded for video too', async () => {
    const map = AM.buildSequenceMap(await AM.readSequence(await scene(), null), 'T');
    const v = map.tracks.V1.find(i => !i.stray);
    assert.equal(v.source_in_sec, 12.5);
    assert.equal(v.source_out_sec, 72.5);
    assert.ok(v.timeline_start_ticks !== undefined && v.source_in_ticks !== '');
    assert.match(v.media_path, /01_Source\/Video\/01_zachem_nuzhen\/FX3_0001\.MP4$/);
    const clip = map.scenes['01_zachem_nuzhen'].clips.find(c => c.v_track === 'V1');
    assert.equal(clip.source_in_sec, 12.5, 'the legacy scenes block keeps video in/out now');
  });

  it('disabled and one-frame items are flagged, not lost', async () => {
    const map = AM.buildSequenceMap(await AM.readSequence(await scene(), null), 'T');
    assert.equal(map.tracks.V3[0].disabled, true);
    assert.equal(map.summary.disabled, 1);
    assert.equal(map.tracks.V1.filter(i => i.stray).length, 1);
    assert.equal(map.summary.strays, 1);
    const clips = map.scenes['01_zachem_nuzhen'].clips;
    assert.ok(clips.some(c => c.v_track === 'V3' && c.disabled === true), 'disabled clip stays in scenes, marked');
    assert.ok(!clips.some(c => c.duration_sec < AM.STRAY_SEC), 'strays stay out of the pairing block');
  });

  it('camera audio is told apart from lav: own camera, other camera, TX', async () => {
    const map = AM.buildSequenceMap(await AM.readSequence(await scene(), null), 'T');
    const v2 = map.scenes['01_zachem_nuzhen'].clips.find(c => c.v_track === 'V2');
    assert.equal(v2.audio.A2.type, 'camera_embed');
    assert.equal(v2.audio.A1.type, 'other_camera_embed');
    assert.equal(v2.audio.A1.of_track, 'V1');
    assert.equal(v2.audio.A5.type, 'dji');
    assert.equal(v2.audio.A5.source_in_sec, 3.25);
  });

  it('camera audio stays camera audio when its video was trimmed away from the audio midpoint (review of 6fe3cc6)', async () => {
    const seq = new ppro._MockSequence('YTX01_01_s', { videoTracks: 1, audioTracks: 2 });
    const v = (await seq.getVideoTrack(0))._addItem('FX3_0001.MP4', 0, 25);          // trimmed / unlinked
    v._projectItem = new ppro._MockClipProjectItem('FX3_0001.MP4', '/p/01_Source/Video/01_s/FX3_0001.MP4');
    const a = (await seq.getAudioTrack(0))._addItem('FX3_0001.MP4', 0, 60);          // still 0–60, midpoint 30
    a._projectItem = new ppro._MockClipProjectItem('FX3_0001.MP4', '/p/01_Source/Video/01_s/FX3_0001.MP4');
    const map = AM.buildSequenceMap(await AM.readSequence(seq, null), 'T');
    assert.equal(map.tracks.A1[0].kind, 'camera_embed', 'not «external» — that reads as a lav');
    assert.equal(map.scenes['01_s'].clips[0].audio.A1.type, 'camera_embed');
  });

  it('a track whose items cannot be listed makes the map UNREADABLE, not silently empty', async () => {
    const seq = await scene();
    const a3 = await seq.getAudioTrack(2);
    a3.getTrackItems = () => { throw new Error('API unavailable'); };
    const map = AM.buildSequenceMap(await AM.readSequence(seq, null), 'T');
    assert.equal(map.summary.unreadable, 1);
    assert.deepEqual(map.summary.unreadable_tracks, ['A3']);
    assert.match(map.track_state.A3.error, /getTrackItems failed: API unavailable/);
    assert.match(AM.statusLine('SEQ', map, 'f.json'), /1 UNREADABLE \(whole track A3\)/);
  });

  it('audio with no video above it is counted', async () => {
    const seq = await scene();
    (await seq.getAudioTrack(4))._addItem('TX01_tail.wav', 120, 30);
    const map = AM.buildSequenceMap(await AM.readSequence(seq, null), 'T');
    assert.equal(map.summary.audio_without_video, 1);
    assert.ok(map.tracks.A5.some(i => i.timeline_start_sec === 120));
  });
});

describe('audioMap — file and names', () => {
  it('project code comes from the project folder, not the sequence', () => {
    assert.equal(AM.projectCodeOf('/Volumes/T9/YTCR/YTCR02_Kamran_Sharaf', '01_Scene'), 'YTCR02');
    assert.equal(AM.projectCodeOf('/x/whatever', 'YTUVIE01_01_scene'), 'YTUVIE01');
    assert.equal(AM.projectCodeOf('/x/whatever', '01_Scene'), 'project', 'never «01_audio_map.json» again');
    // real channels longer than four letters or in mixed case (review of 6fe3cc6)
    assert.equal(AM.projectCodeOf('/Volumes/T9/YTRSCEN01_relaunch', 'x'), 'YTRSCEN01');
    assert.equal(AM.projectCodeOf('/Volumes/T9/YTMSEN02_usa', 'x'), 'YTMSEN02');
    assert.equal(AM.projectCodeOf('/Volumes/T9/YTAgeFree05_Oleskina', 'x'), 'YTAgeFree05');
    assert.equal(AM.sceneOf('', 'YTAgeFree05_03_walk'), '03_walk');
  });

  it('scene from the sequence name keeps its NN_ prefix', () => {
    assert.equal(AM.sceneOf('', 'YTFP03_02_Kids_Session'), '02_Kids_Session');
    assert.equal(AM.sceneOf('', 'YTUVIE01_01_zachem_nuzhen_SYNC'), '01_zachem_nuzhen');
    assert.equal(AM.sceneOf('/p/01_Source/Video/03_walk/a.MP4', 'X'), '03_walk');
  });

  it('a second sequence is merged in, not written over the first; a legacy file is kept', () => {
    const m1 = { exported_at: 'T1', summary: {} };
    const legacy = { version: '1.2', type: 'audio_map', sequence: 'YTX01_01_a', scenes: { a: {} } };
    let file = AM.mergeAudioMapFile(legacy, 'YTX01_02_b', m1, { projectCode: 'YTX01', projectFolder: '/p' });
    assert.deepEqual(Object.keys(file.sequences).sort(), ['YTX01_01_a', 'YTX01_02_b']);
    assert.equal(file.sequences.YTX01_01_a.format, '1.2');
    file = AM.mergeAudioMapFile(file, 'YTX01_01_a', { exported_at: 'T2', summary: {} }, { projectCode: 'YTX01', projectFolder: '/p' });
    assert.equal(file.sequences.YTX01_01_a.exported_at, 'T2', 're-export replaces only its own sequence');
    assert.ok(file.sequences.YTX01_02_b);
    assert.equal(file.version, AM.FORMAT);
    assert.equal(file.last_sequence, 'YTX01_01_a');
  });

  it('the status line names what the human must look at', async () => {
    const map = AM.buildSequenceMap(await AM.readSequence(await scene(), null), 'T');
    const line = AM.statusLine('SEQ', map, 'YTUVIE01_audio_map.json');
    assert.match(line, /V3\/A6 · 8 items · 1 disabled · 1 one-frame strays/);
  });
});
