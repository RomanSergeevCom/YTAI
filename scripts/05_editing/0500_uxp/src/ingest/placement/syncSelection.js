/**
 * Выделение под `Clip → Synchronize` — панель ставит его сама.
 *
 * Почему не ⌘A. Premiere гасит пункт меню, когда на одной дорожке выделено
 * больше одного клипа, а преднагрев дорожек сеет по однокадровому огрызку на
 * КАЖДУЮ дорожку (измерено на YTUVIE01: 30 айтемов в `_SYNC`, все 30 — мусор).
 * ⌘A ловит и мусор, и клип, и команда гаснет. `Sequence.setSelection` позволяет
 * выделить ровно то, что мы клали, и вопрос снимается независимо от мусора.
 *
 * ⚠️ Читатель здесь ОДИН на Select и на Collect. Если их развести, «что выделили»
 * и «что собрали» разойдутся молча — а это ингест, который никто не перепроверит.
 *
 * Чистая часть отбора живёт в `syncSpread.chooseSyncItems`; здесь только UXP.
 */

const { chooseSyncItems, MIN_SYNC_ITEM_SEC } = require('../syncSpread');
const { createEmptySelectionCompat, getClipItems } = require('./sequenceFactory');

/** Секунды из TickTime, какой бы формы он ни был. */
function secondsOf(t) {
  if (!t) return null;
  if (typeof t.seconds === 'number') return t.seconds;
  if (typeof t.ticks === 'number') return t.ticks / 254016000000;
  return null;
}

/**
 * Прочитать секвенцию как список айтемов.
 *
 * @returns {Promise<Array<{filename,trackType,trackIdx,startSec,durationSec,ref}>>}
 */
async function readSequenceItems(sequence) {
  const out = [];

  async function readTrack(track, trackType, trackIdx) {
    if (!track) return;
    const items = await getClipItems(track);
    for (const it of items) {
      let name = '';
      try { name = it.name || (it.getName ? await it.getName() : ''); } catch (e) { /* без имени не судим */ }
      let startSec = null;
      try { startSec = secondsOf(await it.getStartTime()); } catch (e) { /* ниже отсеется */ }
      let durationSec = null;
      try {
        if (typeof it.getDuration === 'function') durationSec = secondsOf(await it.getDuration());
      } catch (e) { /* длительности может не быть — тогда айтем считаем настоящим */ }
      if (durationSec === null && typeof it.getEndTime === 'function') {
        try {
          const end = secondsOf(await it.getEndTime());
          if (end !== null && startSec !== null) durationSec = end - startSec;
        } catch (e) { /* пусто */ }
      }
      if (name && startSec !== null) {
        out.push({
          // имя айтема Premiere иногда носит суффикс дорожки — снимаем, как это
          // делает collectFromSync
          filename: String(name).replace(/ \[V\]$| \[A\]$/, ''),
          trackType, trackIdx, startSec, durationSec, ref: it,
        });
      }
    }
  }

  const vCount = await sequence.getVideoTrackCount();
  for (let v = 0; v < vCount; v++) await readTrack(await sequence.getVideoTrack(v), 'video', v);
  if (typeof sequence.getAudioTrackCount === 'function') {
    const aCount = await sequence.getAudioTrackCount();
    for (let a = 0; a < aCount; a++) await readTrack(await sequence.getAudioTrack(a), 'audio', a);
  }
  return out;
}

/** setSelection синхронна с 26.3 и возвращала Promise до неё — покрываем обе. */
async function applySelection(sequence, handles) {
  const sel = await createEmptySelectionCompat();
  if (!sel) throw new Error('TrackItemSelection недоступен');
  for (const h of handles) sel.addItem(h, true);
  const r = sequence.setSelection(sel);
  return (r && typeof r.then === 'function') ? await r : r;
}

/**
 * Выделить ровно источники манифеста.
 *
 * @param {Object} project
 * @param {Object} sequence
 * @param {Object} manifest   из planSpread()
 * @param {Object} logger
 * @param {Object} [opts]     { minItemSec?, includeLinkedAudio? }
 * @returns {Promise<{selected:number, missing:string[], skippedShort:number,
 *                    perTrack:Object, verified:number|null, strays:Array}>}
 * @throws когда на одну дорожку пришлось больше одного выделяемого айтема
 */
async function selectForSync(project, sequence, manifest, logger, opts = {}) {
  try {
    if (typeof sequence.clearSelection === 'function') await sequence.clearSelection();
  } catch (e) {
    logger.debug(`clearSelection недоступен (${e.message}) — продолжаем`);
  }

  const items = await readSequenceItems(sequence);
  const pick = chooseSyncItems(manifest, items, opts);

  if (pick.maxPerTrack > 1) {
    const worst = Object.keys(pick.perTrack).filter(k => pick.perTrack[k] > 1);
    throw new Error('на дорожке ' + worst.join(', ') + ' два выделяемых айтема — '
      + 'нарушен контракт раскладки, выделять нельзя');
  }
  if (!pick.chosen.length) {
    throw new Error('в секвенции нет ни одного источника манифеста — '
      + 'раскладка не легла (проверь sync_ready.py)');
  }

  // ⚠️ Объекты, созданные ВНЕ lockedAccess, в живой Premiere протухают
  // («The script object is no longer valid»), поэтому айтемы перечитываем
  // внутри замка и отбор повторяем на свежих ссылках.
  let applied = null;
  let fresh = pick;
  try {
    await project.lockedAccess(async function () {
      const inLock = await readSequenceItems(sequence);
      fresh = chooseSyncItems(manifest, inLock, opts);
      applied = await applySelection(sequence, fresh.chosen.map(c => c.ref));
    });
  } catch (e) {
    // Не доказано, требует ли setSelection замка. Если внутри не вышло —
    // пробуем снаружи ОДИН раз и пишем в лог, какая форма сработала: это и есть
    // недостающий опыт, а не догадка.
    logger.warn(`selectForSync внутри lockedAccess не прошёл (${e.message}) — пробуем снаружи`);
    applied = await applySelection(sequence, fresh.chosen.map(c => c.ref));
    logger.info('selectForSync: сработала форма БЕЗ lockedAccess — запомни это');
  }

  // Обратное чтение: «применилось» без сверки числа — это вера, а не проверка.
  let verified = null;
  try {
    const back = await sequence.getSelection();
    const got = back && typeof back.getTrackItems === 'function' ? await back.getTrackItems() : null;
    if (got) verified = got.length;
  } catch (e) {
    logger.debug(`getSelection после выделения не прочитался (${e.message})`);
  }
  if (verified !== null && verified !== fresh.chosen.length) {
    logger.warn(`выделено ${fresh.chosen.length}, а секвенция отдаёт ${verified} — расхождение`);
  }

  const strays = fresh.skippedShort.map(s => ({
    track: (s.trackType === 'video' ? 'V' : 'A') + (s.trackIdx + 1),
    filename: s.filename, startSec: s.startSec, durationSec: s.durationSec,
  }));

  logger.info(`Выделено ${fresh.chosen.length} айтемов на ${Object.keys(fresh.perTrack).length} дорожках`
    + (strays.length ? `, огрызков пропущено ${strays.length}` : '')
    + (fresh.missing.length ? `, не найдено ${fresh.missing.length}` : ''));

  return {
    selected: fresh.chosen.length,
    missing: fresh.missing,
    skippedShort: fresh.skippedShort.length,
    perTrack: fresh.perTrack,
    verified,
    applied,
    strays,
  };
}

/**
 * Выделить ВЕСЬ однокадровый мусор — кнопка `Clean`.
 *
 * Снести его пытаемся тем же путём, что и заглушки преднагрева; если снос опять
 * отработает вхолостую (известное поведение живого Premiere), огрызки останутся
 * ВЫДЕЛЕННЫМИ — человеку остаётся нажать ⌫.
 */
async function selectStrays(project, sequence, logger, opts = {}) {
  const minItem = typeof opts.minItemSec === 'number' ? opts.minItemSec : MIN_SYNC_ITEM_SEC;
  const items = await readSequenceItems(sequence);
  const strays = items.filter(a => typeof a.durationSec === 'number' && a.durationSec < minItem);
  if (!strays.length) {
    logger.info('Огрызков нет — чистить нечего');
    return { found: 0, selected: 0 };
  }
  await applySelection(sequence, strays.map(s => s.ref));
  logger.info(`Огрызков ${strays.length}: выделены. Если снос не сработает — нажми ⌫`);
  return { found: strays.length, selected: strays.length,
           list: strays.map(s => ({
             track: (s.trackType === 'video' ? 'V' : 'A') + (s.trackIdx + 1),
             filename: s.filename, startSec: s.startSec, durationSec: s.durationSec })) };
}

module.exports = {
  readSequenceItems,
  applySelection,
  selectForSync,
  selectStrays,
};
