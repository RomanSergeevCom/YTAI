/**
 * audioMap.js — Export Audio Map: точный снимок таймлайна КАК ОН ЕСТЬ.
 *
 * Зачем (Роман, 25.09.2026): карта нужна, чтобы показать расхождение — значит,
 * она обязана отражать таймлайн целиком, а не выборку из него. Прежняя карта
 * (index.js, формат 1.2) была неполной и местами ложной:
 *   - звук брался только ПОД СЕРЕДИНОЙ видеоклипа — звук без картинки над ним
 *     в карту не попадал вовсе;
 *   - source in/out видео читался и выбрасывался;
 *   - выключенные клипы (Clip → Enable) и однокадровые огрызки молча терялись;
 *   - media path был всегда пуст (getMediaPath() не работает — getMediaFilePath());
 *   - код проекта не определялся (у YTCR02 вышел файл «01_audio_map.json»),
 *     вторая сцена перезаписывала первую.
 *
 * Формат 1.3: файл {CODE}_audio_map.json хранит карты ВСЕХ выгруженных
 * секвенций (sequences[имя]); в каждой — tracks (каждый айтем каждой дорожки,
 * ничего не отброшено, особые помечены) и scenes (прежнее сопоставление
 * видео → звук по середине клипа, для формулы 0103). Описание —
 * scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio_spec.md.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}
const { tickSec } = require('../shared/utils');

const FORMAT = '1.3';
const TICKS_PER_SECOND = 254016000000;
const STRAY_SEC = 0.2;      // короче — однокадровый мусор преднагрева: в карте, но с пометкой

const r6 = (x) => Math.round(x * 1000000) / 1000000;
const ticksOf = (tt) => String((tt && tt.ticks) || '');

function parseTxMic(filename) {
  const txm = String(filename).match(/(?:^|_)TX(\d+)/);
  const micm = String(filename).match(/(?:^|_)(MIC\d+)/);
  return { tx: txm ? 'TX' + txm[1] : null, mic: micm ? micm[1] : null };
}
const stem = (f) => String(f || '').replace(/\.\w+$/, '');

/**
 * Код проекта по имени папки: /…/YTCR01_Arty_Dzis → YTCR01.
 * Каналы бывают длиннее четырёх букв и в смешанном регистре (YTRSCEN01,
 * YTMSEN02, YTAgeFree05) — ревью 6fe3cc6: узкий шаблон давал «project».
 */
const PROJECT_CODE_RE = /^(YT[A-Za-z]{2,8}\d+)(?:_|\.|$)/;
function projectCodeOf(folderPath, seqName) {
  const base = String(folderPath || '').replace(/\\/g, '/').replace(/\/+$/, '').split('/').pop();
  let m = base.match(PROJECT_CODE_RE);
  if (m) return m[1];
  m = String(seqName || '').match(PROJECT_CODE_RE);
  return m ? m[1] : 'project';
}

/** Сцена: из пути медиа (…/Video/<сцена>/файл), иначе из имени секвенции — с номером NN_. */
function sceneOf(mediaPath, seqName) {
  if (mediaPath) {
    const parts = String(mediaPath).replace(/\\/g, '/').split('/');
    for (let i = 0; i < parts.length - 2; i++) {
      if (parts[i] === 'Video' || parts[i] === 'Source') return parts[i + 1];
    }
  }
  const m = String(seqName || '').match(/^YT[A-Za-z]{2,8}\d+_(.+?)(?:_\d+_Ingest|_SYNC)?$/);
  return m ? m[1] : '_unknown';
}

async function readItem(ti, label, index) {
  const item = { track: label, index: index, filename: '', media_path: '', disabled: null, nested: null };
  let pi = null;
  try { pi = await ti.getProjectItem(); } catch (e) { /* synthetic item: no project item */ }
  if (pi) {
    item.filename = String(pi.name || '');
    let cpi = pi;
    try { if (ppro.ClipProjectItem && typeof ppro.ClipProjectItem.cast === 'function') cpi = ppro.ClipProjectItem.cast(pi) || pi; }
    catch (e) { /* not a clip project item */ }
    try { item.media_path = String((await cpi.getMediaFilePath()) || ''); } catch (e) {
      try { item.media_path = String(cpi.getMediaPath() || ''); } catch (e2) { /* no media path (synthetic/adjustment) */ }
    }
    try { if (typeof cpi.isSequence === 'function') item.nested = !!(await cpi.isSequence()); } catch (e) { /* unknown */ }
  }
  if (!item.filename) { try { item.filename = String((await ti.getName()) || ti.name || ''); } catch (e) { /* nameless */ } }
  const st = await ti.getStartTime();
  const du = await ti.getDuration();
  let ip = null, op = null;
  try { ip = await ti.getInPoint(); } catch (e) { /* synthetic */ }
  try { op = await ti.getOutPoint(); } catch (e) { /* synthetic */ }
  item.timeline_start_sec = r6(tickSec(st));
  item.duration_sec = r6(tickSec(du));
  item.timeline_end_sec = r6(item.timeline_start_sec + item.duration_sec);
  item.source_in_sec = ip ? r6(tickSec(ip)) : null;
  item.source_out_sec = op ? r6(tickSec(op)) : null;
  item.timeline_start_ticks = ticksOf(st);
  item.duration_ticks = ticksOf(du);
  item.source_in_ticks = ticksOf(ip);
  item.source_out_ticks = ticksOf(op);
  try { if (typeof ti.isDisabled === 'function') item.disabled = !!(await ti.isDisabled()); } catch (e) { /* optional API (25.0+) */ }
  item.stray = item.duration_sec < STRAY_SEC;
  return item;
}

async function readTrack(track, label, logger) {
  const out = [];
  if (!track) return { items: out, muted: null, error: 'track not available' };
  let tis = null;
  let lastErr = null;
  try { tis = await track.getTrackItems(1, false); } catch (e) { lastErr = e; /* signature differs per build */ }
  if (!tis) {
    try { tis = await track.getTrackItems(); lastErr = null; } catch (e) { lastErr = e; }
  }
  // Both forms threw: the track's clips are NOT in the map. That is an
  // incomplete map, not an empty track (review of 6fe3cc6) — count it as unreadable.
  if (!tis && lastErr) {
    const msg = 'getTrackItems failed: ' + (lastErr && lastErr.message);
    if (logger) logger.warn('Audio map: ' + label + ' — ' + msg + ' — this track is missing from the map', lastErr);
    return { items: out, muted: null, error: msg };
  }
  for (let i = 0; i < (tis || []).length; i++) {
    try { out.push(await readItem(tis[i], label, i)); }
    catch (e) { out.push({ track: label, index: i, error: String(e && e.message) }); if (logger) logger.warn('Audio map: ' + label + ' item ' + i + ' unreadable: ' + (e && e.message), e); }
  }
  let muted = null;
  try { if (typeof track.isMuted === 'function') muted = !!(await track.isMuted()); } catch (e) { /* optional API */ }
  return { items: out, muted };
}

/** Прочитать живую секвенцию целиком: все V и A дорожки, все айтемы. */
async function readSequence(seq, logger) {
  const name = String(seq.name || '');
  let fps = null;
  try {
    const tb = await seq.getTimebase();
    if (tb) fps = Math.round((TICKS_PER_SECOND / Number(tb)) * 1000) / 1000;
  } catch (e) { if (logger) logger.warn('Audio map: getTimebase failed (' + (e && e.message) + ') — fps unknown'); }
  const vCount = await seq.getVideoTrackCount();
  const aCount = await seq.getAudioTrackCount();
  const tracks = {};
  const trackState = {};
  for (let v = 0; v < vCount; v++) {
    const r = await readTrack(await seq.getVideoTrack(v), 'V' + (v + 1), logger);
    tracks['V' + (v + 1)] = r.items || [];
    trackState['V' + (v + 1)] = r.error ? { muted: null, error: r.error } : { muted: r.muted === undefined ? null : r.muted };
  }
  for (let a = 0; a < aCount; a++) {
    const r = await readTrack(await seq.getAudioTrack(a), 'A' + (a + 1), logger);
    tracks['A' + (a + 1)] = r.items || [];
    trackState['A' + (a + 1)] = r.error ? { muted: null, error: r.error } : { muted: r.muted === undefined ? null : r.muted };
  }
  return { name, fps, videoTracks: vCount, audioTracks: aCount, tracks, trackState };
}

function atPos(items, sec) {
  return items.find(c => !c.error && sec >= c.timeline_start_sec && sec < c.timeline_end_sec) || null;
}

/**
 * Классифицировать звуковой айтем. Звук камеры — это тот же файл, что и
 * видеоклип, ПЕРЕКРЫВАЮЩИЙ его где угодно, а не только в середине звука:
 * видео обрезали или отвязали и сдвинули — его звук не становится «внешним»
 * (ревью 6fe3cc6: иначе он выглядел как петличка ровно в ручных правках).
 */
function classifyAudio(a, tracks) {
  const tm = parseTxMic(a.filename);
  if (tm.tx) return { kind: 'dji', tx: tm.tx, mic: tm.mic };
  for (const [label, items] of Object.entries(tracks)) {
    if (label[0] !== 'V') continue;
    const v = items.find(c => !c.error && stem(c.filename) === stem(a.filename)
      && c.timeline_start_sec < a.timeline_end_sec && a.timeline_start_sec < c.timeline_end_sec);
    if (v) return { kind: 'camera_embed', of_track: label };
  }
  return { kind: 'external' };
}

/**
 * Карта одной секвенции (чистая функция — тестируется без Premiere).
 * @param {object} read — результат readSequence
 */
function buildSequenceMap(read, exportedAt) {
  const tracks = {};
  for (const [label, items] of Object.entries(read.tracks)) {
    tracks[label] = items.map(it => (label[0] === 'A' && !it.error) ? Object.assign({}, it, classifyAudio(it, read.tracks)) : it);
  }
  // scenes — прежнее сопоставление (формула 0103): каждый видеоклип и звук
  // каждой A-дорожки под его серединой. Огрызки сюда не идут, выключенные — идут с пометкой.
  const scenes = {};
  const txSet = {};
  const trackUsage = {};
  let withDji = 0, withoutDji = 0;
  const vLabels = Object.keys(tracks).filter(l => l[0] === 'V');
  const aLabels = Object.keys(tracks).filter(l => l[0] === 'A');
  for (const vl of vLabels) {
    for (const vc of tracks[vl]) {
      if (vc.error || vc.stray) continue;
      const scene = sceneOf(vc.media_path, read.name);
      if (!scenes[scene]) scenes[scene] = { clips: [] };
      const mid = vc.timeline_start_sec + vc.duration_sec * 0.5;
      const audio = {};
      let hasDji = false;
      for (const al of aLabels) {
        const m = atPos(tracks[al], mid);
        if (!m || m.stray) continue;
        // Type against THIS clip (the 1.2 rule): same file as vc → its own camera
        // audio, wherever the audio's own midpoint happens to fall.
        let type = m.kind;
        let ofTrack = m.of_track;
        if (m.kind !== 'dji') {
          if (stem(m.filename) === stem(vc.filename)) {
            type = 'camera_embed'; ofTrack = vl;
          } else {
            const ov = vLabels.find(l => l !== vl && (atPos(tracks[l], mid) || {}).filename
              && stem(atPos(tracks[l], mid).filename) === stem(m.filename));
            if (ov) { type = 'other_camera_embed'; ofTrack = ov; }
            else if (m.kind === 'camera_embed') type = 'other_camera_embed';
          }
        }
        const a = {
          type: type,
          filename: m.filename,
          source_in_sec: m.source_in_sec, source_out_sec: m.source_out_sec,
          timeline_start_sec: m.timeline_start_sec, duration_sec: m.duration_sec,
          source_in_ticks: m.source_in_ticks, source_out_ticks: m.source_out_ticks,
          timeline_start_ticks: m.timeline_start_ticks,
        };
        if (a.type === 'other_camera_embed') a.of_track = ofTrack;
        if (m.kind === 'dji') { a.tx = m.tx; a.mic = m.mic; a.path = m.media_path; }
        if (a.type === 'external') a.path = m.media_path;
        if (m.disabled) a.disabled = true;
        audio[al] = a;
        if (m.kind === 'dji') {
          hasDji = true;
          trackUsage[al] = (trackUsage[al] || 0) + 1;
          txSet[m.tx + (m.mic ? '/' + m.mic : '')] = true;
        }
      }
      if (hasDji) withDji++; else withoutDji++;
      const clip = {
        clip_id: stem(vc.filename), filename: vc.filename, video_path: vc.media_path, v_track: vl,
        timeline_start_sec: vc.timeline_start_sec, duration_sec: vc.duration_sec,
        source_in_sec: vc.source_in_sec, source_out_sec: vc.source_out_sec,
        timeline_start_ticks: vc.timeline_start_ticks, duration_ticks: vc.duration_ticks,
        source_in_ticks: vc.source_in_ticks, source_out_ticks: vc.source_out_ticks,
        audio: audio,
      };
      if (vc.disabled) clip.disabled = true;
      scenes[scene].clips.push(clip);
    }
  }
  for (const s of Object.values(scenes)) {
    s.clips.sort((a, b) => a.timeline_start_sec - b.timeline_start_sec || a.v_track.localeCompare(b.v_track));
  }
  const all = Object.values(tracks).flat();
  const count = (pred) => all.filter(pred).length;
  const itemsPerTrack = {};
  for (const [l, items] of Object.entries(tracks)) itemsPerTrack[l] = items.length;
  const audioOnly = aLabels.reduce((n, al) => n + tracks[al].filter(a => !a.error && !a.stray
    && !vLabels.some(vl => atPos(tracks[vl], a.timeline_start_sec + a.duration_sec * 0.5))).length, 0);
  return {
    exported_at: exportedAt,
    fps: read.fps,
    ticks_per_second: TICKS_PER_SECOND,
    video_tracks: read.videoTracks,
    audio_tracks: read.audioTracks,
    track_state: read.trackState,
    tracks: tracks,
    scenes: scenes,
    summary: {
      items_total: all.length,
      items_per_track: itemsPerTrack,
      disabled: count(i => i.disabled === true),
      strays: count(i => i.stray === true),
      nested: count(i => i.nested === true),
      // unreadable items + whole tracks whose items could not be listed
      unreadable: count(i => !!i.error)
        + Object.values(read.trackState || {}).filter(s => s && s.error).length,
      unreadable_tracks: Object.keys(read.trackState || {}).filter(l => read.trackState[l] && read.trackState[l].error),
      audio_without_video: audioOnly,
      total_video_clips: Object.values(scenes).reduce((n, s) => n + s.clips.length, 0),
      clips_with_dji: withDji,
      clips_without_dji: withoutDji,
      tx_channels: Object.keys(txSet).sort(),
      track_usage: trackUsage,
    },
  };
}

/**
 * Слить карту секвенции в файл проекта. Прежние секвенции сохраняются; файл
 * старого формата (1.0–1.2, одна секвенция на верхнем уровне) переносится
 * внутрь sequences под своим именем, а не затирается.
 */
function mergeAudioMapFile(existing, seqName, seqMap, meta) {
  const out = { version: FORMAT, type: 'audio_map', project_code: meta.projectCode,
    project_folder: meta.projectFolder, updated_at: seqMap.exported_at, last_sequence: seqName, sequences: {} };
  if (existing && typeof existing === 'object') {
    if (existing.sequences && typeof existing.sequences === 'object') Object.assign(out.sequences, existing.sequences);
    else if (existing.type === 'audio_map' && existing.sequence) {
      out.sequences[existing.sequence] = Object.assign({ format: existing.version || 'legacy' }, existing);
    }
  }
  out.sequences[seqName] = seqMap;
  return out;
}

/** Строка статуса для человека. */
function statusLine(seqName, map, fileName) {
  const s = map.summary;
  const bits = ['V' + map.video_tracks + '/A' + map.audio_tracks, s.items_total + ' items'];
  if (s.disabled) bits.push(s.disabled + ' disabled');
  if (s.strays) bits.push(s.strays + ' one-frame strays');
  if (s.nested) bits.push(s.nested + ' nested');
  if (s.audio_without_video) bits.push(s.audio_without_video + ' audio without video');
  if (s.unreadable) {
    bits.push(s.unreadable + ' UNREADABLE'
      + (s.unreadable_tracks && s.unreadable_tracks.length ? ' (whole track ' + s.unreadable_tracks.join(', ') + ')' : ''));
  }
  return seqName + ': ' + bits.join(' · ') + ' → ' + fileName;
}

module.exports = {
  FORMAT, STRAY_SEC,
  projectCodeOf, sceneOf, readSequence, buildSequenceMap, mergeAudioMapFile, statusLine,
};
