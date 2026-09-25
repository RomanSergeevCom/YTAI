/**
 * Sequence factory — creates a correctly-formatted sequence for wall-clock placement.
 *
 * Resolution/fps correctness: an EMPTY project.createSequence() inherits Premiere's
 * default format (observed 1920×1080@24 in live PP) and setVideoFrameRect refinement
 * is best-effort. So when a seed clip is available we use createSequenceFromMedia()
 * — which inherits the REAL media format (e.g. 3840×2160@50) — then REMOVE the
 * auto-seeded first clip from V1/A1 so wall-clock can place every clip (including the
 * first) at its own offset. This sidesteps the settings-API fragility entirely.
 *
 * Used by wallClockBuilder.js.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../../tests/mocks/premierepro');
}

const { applyMediaSettings, logSequenceSettings, SEQUENCE_DEFAULTS } = require('../../shared/mediaSettings');

/**
 * Create a sequence with the correct media format for wall-clock placement.
 *
 * @param {Object} project - Premiere project
 * @param {string} sequenceName - Name for the new sequence
 * @param {Object} media - { width, height, fps, sample_rate }
 * @param {Object} logger - Logger
 * @param {Object|null} [seedClipItem] - a primary-camera ProjectItem to seed format from
 * @returns {Promise<Object>} the created sequence (empty of clips)
 */
async function create(project, sequenceName, media, logger, seedClipItem) {
  let sequence;
  let method;
  let seeded = false;

  if (seedClipItem) {
    // Inherit real resolution/fps/audio from the seed media, then clear the
    // auto-placed seed clip so wall-clock can place it at its true offset.
    const cast = ppro.ClipProjectItem.cast(seedClipItem) || seedClipItem;
    // partsBuilder-1.6.2 pattern: trim the seed source to ONE FRAME before
    // seeding. createSequenceFromMedia still inherits the true format, but when
    // the post-create removal fails (25.6 "script object is no longer valid" on
    // stale TrackItem handles — the cause of stray head clips Roman saw in
    // 01_Studio), the leftover is an invisible 1-frame speck, not a full clip.
    const seedFps = (media && media.fps) || 25;
    try {
      const inT = ppro.TickTime.createWithSeconds(0);
      const outT = ppro.TickTime.createWithSeconds(1 / seedFps);
      project.lockedAccess(() => {
        project.executeTransaction((ca) => {
          ca.addAction(cast.createSetInOutPointsAction(inT, outT));
        }, 'Seed 1-frame trim');
      });
    } catch (e) { logger.debug(`seed pre-trim: ${e.message}`); }
    try {
      sequence = await project.createSequenceFromMedia(sequenceName, [cast]);
      method = 'createSequenceFromMedia';
    } catch (err) {
      logger.warn(`createSequenceFromMedia failed (${err.message}); falling back to empty createSequence`);
    }
    // Clear the trim right away — wall-clock placement sets its own in/out per
    // segment (clipPlacer), but the project item must not stay 1-frame-trimmed.
    try {
      project.lockedAccess(() => {
        project.executeTransaction((ca) => {
          ca.addAction(cast.createClearInOutPointsAction());
        }, 'Seed trim clear');
      });
    } catch (e) { logger.debug(`seed trim clear: ${e.message}`); }
    if (sequence) {
      seeded = true;
      // Remove the seeded clip from V1 and A1 (it will be re-placed by wall-clock).
      const ed = ppro.SequenceEditor.getEditor(sequence);
      const MT = ppro.Constants && ppro.Constants.MediaType ? ppro.Constants.MediaType : { VIDEO: 0, AUDIO: 1 };
      try {
        const n = await removeAllItemsOnTrack(project, ed, await sequence.getVideoTrack(0), MT.VIDEO, logger, 'seed V1');
        if (n) logger.info(`Cleared ${n} seed item(s) from V1`);
      } catch (e) { logger.debug(`seed V1 cleanup: ${e.message}`); }
      try {
        if (typeof sequence.getAudioTrack === 'function') {
          await removeAllItemsOnTrack(project, ed, await sequence.getAudioTrack(0), MT.AUDIO, logger, 'seed A1');
        }
      } catch (e) { logger.debug(`seed A1 cleanup: ${e.message}`); }
    }
  }

  if (!sequence) {
    try {
      sequence = await project.createSequence(sequenceName);
      method = 'createSequence(empty)';
    } catch (err) {
      logger.error(`createSequence failed for "${sequenceName}": ${err.message}`);
      throw err;
    }
  }
  if (!sequence) {
    throw new Error(`Sequence creation returned null for "${sequenceName}"`);
  }
  logger.info(`Created sequence: ${sequenceName} (${method})`);

  // Framerate/resolution policy:
  //  - SEEDED path: the sequence already inherits the REAL format of the primary
  //    camera (e.g. DJI/FX3A=25fps, FX3=50fps). Do NOT override with a global
  //    ingest.media.fps — that previously forced every scene to 50fps even when
  //    the primary footage was 25fps. Trust the seed.
  //  - EMPTY fallback: no media to inherit from, so apply ingest.media as a
  //    best-effort (setVideoFrameRect / setVideoFrameRate).
  if (!seeded) {
    const mediaConfig = media || {
      width: SEQUENCE_DEFAULTS.width,
      height: SEQUENCE_DEFAULTS.height,
      fps: SEQUENCE_DEFAULTS.fps,
      sample_rate: SEQUENCE_DEFAULTS.audioSampleRate,
    };
    try {
      await applyMediaSettings(project, sequence, mediaConfig, logger);
    } catch (err) {
      logger.warn(`applyMediaSettings failed for "${sequenceName}": ${err.message}`);
    }
  } else {
    logger.info(`Inheriting primary-camera format from seed (no global fps override)`);
  }

  try { await logSequenceSettings(sequence, logger); } catch (e) { /* non-fatal */ }

  return sequence;
}

/**
 * Remove every track item currently on a track (used to clean up the pre-warm
 * placeholder). Mirrors assemblyBuilder's ghost-clip removal via createRemoveAction.
 */
async function getClipItems(track) {
  // getTrackItems is ASYNC and takes the TrackItemType enum (proven pattern:
  // lutManager.js / index.js verify). Try enum, then legacy literal, then bare.
  const CLIP = (ppro.Constants && ppro.Constants.TrackItemType
    && ppro.Constants.TrackItemType.CLIP !== undefined)
    ? ppro.Constants.TrackItemType.CLIP : 1;
  let items = null;
  try { items = await track.getTrackItems(CLIP, false); } catch (e) { /* next */ }
  if (!items || !items.length) {
    try { items = await track.getTrackItems(1, false); } catch (e) { /* next */ }
  }
  if (!items || !items.length) {
    try { items = await track.getTrackItems(); } catch (e) { /* give up */ }
  }
  return items || [];
}

/**
 * 25.6 UXP DOM: TrackItemSelection.createEmptySelection(callback) delivers the
 * selection via CALLBACK — a no-arg call throws native "Not Enough Parameters"
 * (live-diagnosed on YTUVI05 MCAM build 2026-07-12). Older builds returned the
 * selection directly. Support both.
 */
async function createEmptySelectionCompat() {
  let sel = null;
  try {
    const ret = ppro.TrackItemSelection.createEmptySelection(function (s) { sel = s; });
    if (!sel && ret && typeof ret === 'object') sel = ret; // legacy direct-return builds
  } catch (e) {
    try { sel = ppro.TrackItemSelection.createEmptySelection(); } catch (e2) { /* none */ }
  }
  if (!sel) { await Promise.resolve(); } // callback may land on a microtask
  return sel;
}

async function removeAllItemsOnTrack(project, seqEditor, track, mediaType, logger, label) {
  if (!track) return 0;
  const items = await getClipItems(track);
  if (!items.length) return 0;
  if (logger) logger.info(`Pre-warm cleanup ${label}: ${items.length} placeholder item(s) found`);

  // Strategy 1: TrackItemSelection + SequenceEditor.createRemoveItemsAction.
  // NB: the ONLY removal API in 25.6 — TrackItem.createRemoveAction does not exist.
  // The selection is created AND filled INSIDE lockedAccess with freshly fetched
  // track items: live 25.6 invalidates script objects created outside the lock
  // scope ("The script object is no longer valid", seen on every 16-17.08.2026
  // build — the seed placeholder survived cleanup because of it), the same
  // context rule that makes action factories throw "Requires locked access".
  try {
    await project.lockedAccess(async function () {
      const sel = await createEmptySelectionCompat();
      if (!sel) throw new Error('TrackItemSelection unavailable');
      const fresh = await getClipItems(track);
      for (const ti of fresh) sel.addItem(ti, true);
      await project.executeTransaction(function (ca) {
        ca.addAction(seqEditor.createRemoveItemsAction(sel, false, mediaType, false));
      }, 'Remove seed/placeholder items');
    });
    const left = (await getClipItems(track)).length;
    if (!left) {
      if (logger) logger.info(`Pre-warm cleanup ${label}: removed via selection`);
      return items.length;
    }
    if (logger) logger.warn(`Pre-warm cleanup ${label}: selection removal left ${left}`);
  } catch (e) {
    if (logger) logger.warn(`Pre-warm cleanup ${label}: selection removal failed: ${e.message}`);
  }

  // Strategy 2: per-item createRemoveAction (working pattern from
  // assemblyBuilder's ghost-clip removal).
  try {
    const again = await getClipItems(track);
    await project.lockedAccess(function () {
      return project.executeTransaction(function (ca) {
        for (const ti of again) {
          if (typeof ti.createRemoveAction === 'function') {
            ca.addAction(ti.createRemoveAction());
          }
        }
      }, 'Remove seed/placeholder items (per-item)');
    });
    const left = (await getClipItems(track)).length;
    if (!left) {
      if (logger) logger.info(`Pre-warm cleanup ${label}: removed via per-item actions`);
      return items.length;
    }
    if (logger) logger.warn(`Pre-warm cleanup ${label}: ${left} item(s) REMAIN — `
      + `delete the stray head clip manually (top V/A track)`);
    return items.length - left;
  } catch (e) {
    if (logger) logger.warn(`Pre-warm cleanup ${label}: per-item removal failed: ${e.message}`);
    return 0;
  }
}


//: тиков в секунде у Premiere — та же величина, что в sceneLayout.js
const TICKS_PER_SECOND = 254016000000;

/**
 * Ensure the sequence has at least vNeeded video tracks and aNeeded audio tracks.
 *
 * Adobe docs: createInsertProjectItemAction "If you pass a track index greater
 * than the number of existing tracks, a new track will be created." We exploit
 * this: insert a throwaway placeholder at the highest needed (vIdx, aIdx) — which
 * materialises V1..Vn and A1..An in one shot — then remove the placeholder. This
 * is doc-grounded track creation (there is NO createAddTracksAction in the UXP
 * DOM API), letting the subsequent VIDEO placements use overwrite (which does NOT
 * auto-create tracks) against tracks that now exist.
 *
 * @param {Object} project
 * @param {Object} sequence
 * @param {Object} seqEditor
 * @param {Object|null} placeholderItem - any importable ProjectItem (e.g. first clip)
 * @param {number} vNeeded
 * @param {number} aNeeded
 * @param {Object} logger
 * @param {Object} [opts] - { coverAtSec } секунда, куда поставить заглушку,
 *   чтобы её перекрыл настоящий клип верхней дорожки (см. ниже про удаление)
 * @returns {Promise<{ vCount: number, aCount: number }>}
 */
async function ensureTracks(project, sequence, seqEditor, placeholderItem, vNeeded, aNeeded, logger, opts) {
  let vCurrent = await sequence.getVideoTrackCount();
  let aCurrent = await sequence.getAudioTrackCount();

  if (vNeeded <= vCurrent && aNeeded <= aCurrent) {
    return { vCount: vCurrent, aCount: aCurrent };
  }
  if (!placeholderItem) {
    logger.warn(`ensureTracks: need V${vNeeded}/A${aNeeded} (have V${vCurrent}/A${aCurrent}) but no placeholder item — relying on insert auto-create downstream`);
    return { vCount: vCurrent, aCount: aCurrent };
  }

  const vIdx = Math.max(0, vNeeded - 1);
  const aIdx = Math.max(0, aNeeded - 1);

  // ⚠️ Заглушку ставим НЕ В НОЛЬ, а туда, где потом ляжет настоящий клип этой
  // дорожки, — и он её собой перекроет. Иначе она остаётся навсегда: в живой
  // 25.6/26 ОБА способа удаления отрабатывают вхолостую (не падают, но клип
  // на месте), лог полон «1 item(s) REMAIN», и каждая сборка сеет однокадровые
  // огрызки в начало V1/V3/A1/A4/A5. Удаление ниже оставлено как было — если
  // однажды заработает, тем лучше; но правильность больше от него не зависит.
  // ⚠️ НОЛЬ — законная позиция перекрытия, а не «не задано»: у сцены, где
  // верхняя дорожка начинается с нуля (запись экрана), настоящий клип накроет
  // заглушку именно там. Поэтому отличаем null/undefined от 0, а не сравниваем
  // с нулём — поймано на сценах 02 и 03 блока 1.
  const hasCover = opts && typeof opts.coverAtSec === 'number' && isFinite(opts.coverAtSec)
    && opts.coverAtSec >= 0;
  const coverSec = hasCover ? opts.coverAtSec : 0;
  if (hasCover) {
    logger.info(`Pre-warm: заглушка на ${coverSec.toFixed(3)} с — её перекроет настоящий клип`);
  } else {
    logger.warn('Pre-warm: позиция перекрытия не задана — заглушка в 0, '
      + 'останется огрызком, если удаление не сработает');
  }
  const t0 = ppro.TickTime.createWithSeconds(coverSec);
  const MT = ppro.Constants && ppro.Constants.MediaType ? ppro.Constants.MediaType : { VIDEO: 0, AUDIO: 1 };

  logger.info(`Pre-warming tracks → V${vNeeded}/A${aNeeded} (have V${vCurrent}/A${aCurrent}) via placeholder insert+remove`);

  // partsBuilder-1.6.2 pattern: INSERT respects source in/out (unlike
  // createSequenceFromMedia), so trim the placeholder to ~1 frame BEFORE the
  // inserts. 25.6 has no reliable removal («script object is no longer valid»),
  // and a full-length leftover placeholder is what shredded YTUVI05_01_Studio:
  // it got chopped by the V4 overwrites and pushed around by TX inserts into
  // multi-minute stray fragments. A 1-frame speck at 0 is invisible and is
  // normally replaced by the first real overwrite anyway.
  const phCast = ppro.ClipProjectItem.cast(placeholderItem) || placeholderItem;

  // ⚠️ Длину кадра берём У САМОЙ СЕКВЕНЦИИ, а не пишем 0.04 (кадр при 25p).
  // На YTUVIE01 образцом секвенции оказалась запись экрана с ПЕРЕМЕННЫМ кадром
  // (797 кадров на 1106 с, в среднем 0,72 кадра/с). В секвенции 0,72 fps кадр
  // длится 1389 мс, подрезка в 40 мс короче его в 34 раза — вставка не клала
  // ничего, дорожки не рождались, и преднагрев молча отдавал V3/A3 вместо
  // V15/A17. Чтение таймбазы best-effort: не вышло — остаёмся на 0.04.
  let oneFrameSec = 0.04;
  try {
    const tpf = Number(await sequence.getTimebase());
    if (tpf > 0) {
      const fromSeq = tpf / TICKS_PER_SECOND;
      if (fromSeq > 0 && fromSeq < 10) oneFrameSec = fromSeq;
      if (fromSeq >= 0.25) {
        logger.warn(`ensureTracks: у секвенции кадр ${(fromSeq * 1000).toFixed(0)} мс ` +
          `(${(1 / fromSeq).toFixed(2)} fps) — образец почти наверняка с переменным кадром`);
      }
    }
  } catch (e) { logger.debug(`getTimebase unavailable (${e.message}) — trim stays 0.04 s`); }

  let phTrimmed = false;
  try {
    project.lockedAccess(() => {
      project.executeTransaction((ca) => {
        ca.addAction(phCast.createSetInOutPointsAction(
          ppro.TickTime.createWithSeconds(0), ppro.TickTime.createWithSeconds(oneFrameSec)));
      }, 'Pre-warm placeholder 1-frame trim');
    });
    phTrimmed = true;
  } catch (e) { logger.debug(`placeholder pre-trim failed (full-length inserts): ${e.message}`); }

  // Newly created tracks may not report their items through a stale sequence
  // handle — re-fetch the sequence by name before reading tracks back.
  async function freshSequence() {
    try {
      const seqs = await project.getSequences();
      const m = (seqs || []).find(s => s.name === sequence.name);
      if (m) return m;
    } catch (e) { /* keep original */ }
    return sequence;
  }

  async function sweep(tag) {
    const seq = await freshSequence();
    const vc = await seq.getVideoTrackCount();
    const ac = await seq.getAudioTrackCount();
    for (let v = 0; v < vc; v++) {
      try {
        await removeAllItemsOnTrack(project, seqEditor, await seq.getVideoTrack(v), MT.VIDEO, logger, `${tag} V${v + 1}`);
      } catch (e) { logger.warn(`pre-warm cleanup V${v + 1}: ${e.message}`); }
    }
    if (typeof seq.getAudioTrack === 'function') {
      for (let a = 0; a < ac; a++) {
        try {
          await removeAllItemsOnTrack(project, seqEditor, await seq.getAudioTrack(a), MT.AUDIO, logger, `${tag} A${a + 1}`);
        } catch (e) { logger.warn(`pre-warm cleanup A${a + 1}: ${e.message}`); }
      }
    }
    return { vc, ac };
  }

  // Insert placeholders until track counts are satisfied. Premiere adds at
  // most ONE new track per insert (observed: need A5 with A3 → got A4), so
  // loop — and SWEEP AFTER EVERY insert so placeholders never accumulate
  // (insert semantics would push earlier leftovers rightward into slivers).
  // Guard scales with demand: a Sync-Spread scene legitimately needs dozens
  // of tracks (one source per track), the old fixed 8 capped it at ~V9/A9.
  const guardMax = vNeeded + aNeeded + 8;
  let guard = 0;
  while ((vCurrent < vNeeded || aCurrent < aNeeded) && guard++ < guardMax) {
    try {
      await project.lockedAccess(function () {
        return project.executeTransaction(function (ca) {
          ca.addAction(seqEditor.createInsertProjectItemAction(placeholderItem, t0, vIdx, aIdx, false));
        }, 'Pre-warm tracks');
      });
    } catch (e) {
      logger.error(`Pre-warm insert failed: ${e.message}`);
      break;
    }
    const counts = await sweep(`after insert #${guard}`);
    vCurrent = counts.vc;
    aCurrent = counts.ac;
  }
  if (phTrimmed) {
    try {
      project.lockedAccess(() => {
        project.executeTransaction((ca) => {
          ca.addAction(phCast.createClearInOutPointsAction());
        }, 'Pre-warm placeholder trim clear');
      });
    } catch (e) { logger.debug(`placeholder trim clear failed: ${e.message}`); }
  }

  if (vCurrent < vNeeded || aCurrent < aNeeded) {
    logger.warn(`Pre-warm incomplete: V${vCurrent}/A${aCurrent} of V${vNeeded}/A${aNeeded} `
      + `(TX insert auto-creates its A-track downstream)`);
  }

  logger.info(`Pre-warm done: V${vCurrent}/A${aCurrent}`);
  return { vCount: vCurrent, aCount: aCurrent };
}

/**
 * Создать секвенцию ИЗ ПРЕСЕТА — путь звукового стенда.
 *
 * Чем это лучше `create()`: пресет задаёт число дорожек при рождении, поэтому
 * не нужен ни сид (`createSequenceFromMedia` кладёт образец на V1/A1 в НОЛЬ, и
 * снять его нечем — перекрыть тоже нельзя, раскладка начинается с преролла),
 * ни преднагрев (`ensureTracks` сеет по огрызку на дорожку). Плюс пресет —
 * единственное место, где можно включить цели аудиодорожек: API таргетинга в
 * UXP нет.
 *
 * ⚠️ Файл пресета пишет ВЫЗЫВАЮЩИЙ (в панели есть uxpfs, в этом модуле — нет),
 * сюда приходит готовый путь.
 *
 * @param {Object} project
 * @param {string} name
 * @param {string} presetPath  путь к .sqpreset, уже лежащему на диске
 * @param {{vTracks:number, aTracks:number}} expect  чего ждём от результата
 * @param {Object} logger
 * @returns {Promise<Object|null>} секвенция или null — тогда откатывайся на create()
 */
async function createFromPreset(project, name, presetPath, expect, logger) {
  let sequence = null;
  let how = null;
  // Справочник UXP: «Parameter presetPath is deprecated, instead use
  // createSequenceWithPresetPath()». Пробуем новый вход, затем старый —
  // он в этом репозитории уже работает (linearBuilder.js:86).
  if (typeof project.createSequenceWithPresetPath === 'function') {
    try {
      sequence = await project.createSequenceWithPresetPath(name, presetPath);
      how = 'createSequenceWithPresetPath';
    } catch (e) {
      logger.debug(`createSequenceWithPresetPath: ${e.message}`);
    }
  }
  if (!sequence) {
    try {
      sequence = await project.createSequence(name, presetPath);
      how = 'createSequence(name, preset)';
    } catch (e) {
      logger.warn(`createSequence(preset) failed: ${e.message}`);
    }
  }
  if (!sequence) return null;

  // ⚠️ ПРОВЕРЯЕМ, а не верим. applyMediaSettings глотает любые ошибки, и
  // «секвенция создана» ещё не значит «дорожки те». Не сошлось — отдаём null,
  // вызывающий уйдёт на прежний путь и скажет об этом в лог.
  let vCount = null;
  let aCount = null;
  try {
    vCount = await sequence.getVideoTrackCount();
    aCount = await sequence.getAudioTrackCount();
  } catch (e) {
    logger.warn(`createFromPreset: счётчики дорожек не читаются (${e.message})`);
    return null;
  }
  if (expect && (aCount < expect.aTracks || vCount < (expect.vTracks || 1))) {
    logger.warn(`createFromPreset: пресет дал V${vCount}/A${aCount}, а нужно `
      + `V${expect.vTracks || 1}/A${expect.aTracks} — откат на прежний путь`);
    try { await project.deleteSequence(sequence); } catch (e) { /* уберёт человек */ }
    return null;
  }
  logger.info(`Created sequence: ${name} (${how}) — V${vCount}/A${aCount} из пресета`);
  try { await logSequenceSettings(sequence, logger); } catch (e) { /* non-fatal */ }
  return sequence;
}

module.exports = {
  create,
  createFromPreset,
  ensureTracks,
  removeAllItemsOnTrack,
  createEmptySelectionCompat,
  getClipItems,
  // legacy alias — callers should use ensureTracks
  ensureTrackCount: ensureTracks,
};
