/**
 * Scene chapter markers — "какой камень обсуждаем/показываем" поверх таймлайна.
 *
 * Contract (заполняется тулингом вне панели, см. HANDOFF_UXP.md):
 *   ingest.markers = { "<sceneName>": [{ offset_sec, duration_sec?, name, comment?, color? }, ...] }
 * offset_sec   — секунды от начала секвенции сцены
 * duration_sec — длительность главы (диапазон до следующей главы); 0/нет = точка
 * color        — имя из MARKER_COLOR_INDEX (Red/Blue/Magenta/Cyan/Orange/Green/Yellow)
 *
 * API-паттерн скопирован с проверенного Assembly-флоу (index.js ~4900-5140):
 *  - markersOwner = await ppro.Markers.getMarkers(sequence)  (НЕ sequence.getMarkers()!)
 *  - createAddMarkerAction(name, type, start, duration, comment) — параметр type
 *    ИГНОРИРУЕТСЯ (всегда Event) → отдельный createSetTypeAction(MARKER_TYPE_CHAPTER)
 *  - цвет: marker.createSetColorByIndexAction(idx) отдельной транзакцией
 * Всё best-effort: сбой любого шага не роняет сборку.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../../tests/mocks/premierepro');
}

const { MARKER_TYPE_CHAPTER, MARKER_COLOR_INDEX } = require('../../shared/constants');

async function getMarkersOwner(sequence, logger) {
  try {
    if (ppro.Markers && typeof ppro.Markers.getMarkers === 'function') {
      const owner = await ppro.Markers.getMarkers(sequence);
      if (owner) return owner;
    }
  } catch (e) {
    logger.debug(`ppro.Markers.getMarkers failed: ${e.message}`);
  }
  try {
    if (typeof sequence.getMarkers === 'function') {
      return await sequence.getMarkers();
    }
  } catch (e) {
    logger.debug(`sequence.getMarkers failed: ${e.message}`);
  }
  return null;
}

/**
 * Markers this tooling generates — and ONLY those. Anything the editor placed by
 * hand must survive a re-run, so the sweep is name-scoped, never "delete all".
 *   "[4] ★ Taekwondo referee course bought the visa"  (current PART markers)
 *   "✗ NO PART · crew chatter"                        (stretches outside every part)
 *   "Ch07 ★ Adam brings him into Core"                (previous chapter naming)
 *   "Ch-- · …"                                        (pre-1.1 fallback name)
 *   "✗ NO CHAPTER · crew chatter"
 *   "Chapter 7 — The Pivot → Why Core"                (story-timeline style)
 * NOTE: a bare "[N]" prefix is deliberate — Roman names parts "[1] Hook", "[2] Setup".
 */
const GENERATED_MARKER_RE =
  /^(?:\[\d{1,2}\]\s|✗\s*NO (?:PART|CHAPTER)|Ch\d{2}\s|Ch--\s|Chapter\s+\d)/;

/** Отдать управление Premiere между пачками — без этого длинный прогон роняет приложение. */
function breathe(ms) {
  return new Promise(function (r) { setTimeout(r, ms || 30); });
}

/**
 * Имена уже лежащих НАШИХ маркеров — по ним видно, сделана ли сцена.
 * Нужно для докладки после падения: совпало — сцену пропускаем, не трогая Premiere.
 */
async function generatedMarkerNames(sequence, logger) {
  const owner = await getMarkersOwner(sequence, logger || console);
  if (!owner || !owner.getMarkers) return null;
  try {
    const all = await owner.getMarkers();
    const out = [];
    for (const m of all || []) {
      try {
        const nm = m.getName ? m.getName() : '';
        if (nm && GENERATED_MARKER_RE.test(nm)) out.push(nm);
      } catch (e) { /* per-marker guard */ }
    }
    return out;
  } catch (e) {
    return null;
  }
}

/**
 * Remove previously generated chapter markers so a re-run REPLACES instead of
 * duplicating. Best-effort: a failure here never blocks the add pass.
 *
 * @returns {Promise<number>} number of markers removed
 */
async function clearGeneratedMarkers(project, markersOwner, logger) {
  if (!markersOwner || typeof markersOwner.createRemoveMarkerAction !== 'function') {
    logger.debug('Chapter markers: remove API unavailable — skipping the sweep');
    return 0;
  }
  let existing = null;
  try {
    existing = markersOwner.getMarkers ? await markersOwner.getMarkers() : null;
  } catch (e) {
    logger.debug(`Chapter markers: getMarkers before sweep failed: ${e.message}`);
  }
  if (!existing || !existing.length) return 0;

  const stale = [];
  for (const marker of existing) {
    try {
      const nm = marker.getName ? marker.getName() : '';
      if (nm && GENERATED_MARKER_RE.test(nm)) stale.push(marker);
    } catch (e) { /* per-marker guard */ }
  }
  if (!stale.length) return 0;

  // One transaction for the whole sweep; fall back to per-marker on failure.
  try {
    await project.lockedAccess(function () {
      return project.executeTransaction(function (ca) {
        for (const marker of stale) {
          ca.addAction(markersOwner.createRemoveMarkerAction(marker));
        }
      }, `Clear ${stale.length} chapter marker(s)`);
    });
    logger.info(`Chapter markers: removed ${stale.length} previous marker(s)`);
    return stale.length;
  } catch (e) {
    logger.debug(`Chapter markers: batch remove failed (${e.message}) — retrying one by one`);
  }

  let removed = 0;
  for (const marker of stale) {
    try {
      await project.lockedAccess(function () {
        return project.executeTransaction(function (ca) {
          ca.addAction(markersOwner.createRemoveMarkerAction(marker));
        }, 'Clear chapter marker');
      });
      removed++;
    } catch (e) { /* per-marker guard */ }
  }
  logger.info(`Chapter markers: removed ${removed}/${stale.length} previous marker(s)`);
  return removed;
}

/**
 * @param {Object} project
 * @param {Object} sequence - target scene sequence
 * @param {Array<{offset_sec:number,duration_sec?:number,name:string,comment?:string,color?:string}>} markerList
 * @param {Object} logger
 * @param {{replace?: boolean}} [opts] - replace (default true): sweep previously
 *   generated chapter markers first, so re-running is idempotent instead of doubling up.
 * @returns {Promise<number>} number of markers added
 */
async function addSceneMarkers(project, sequence, markerList, logger, opts) {
  if (!sequence || !Array.isArray(markerList) || markerList.length === 0) return 0;

  const valid = markerList.filter(m => m && typeof m.offset_sec === 'number' && m.name);
  if (valid.length === 0) return 0;

  const markersOwner = await getMarkersOwner(sequence, logger);
  if (!markersOwner || typeof markersOwner.createAddMarkerAction !== 'function') {
    logger.warn('Chapter markers: markers API unavailable on this sequence');
    return 0;
  }

  if (!opts || opts.replace !== false) {
    await clearGeneratedMarkers(project, markersOwner, logger);
    await breathe(60);            // дать Premiere переварить удаление
  }

  // Step 1: add markers (with duration = глава-диапазон).
  // ⚠️ По одной транзакции на маркер Premiere роняет: на 433 маркерах проекта приложение
  // падало посреди прогона (Роман, 21.08). Кладём ПАЧКАМИ и отдаём управление между
  // ними, чтобы Premiere успевал прожевать очередь. Пачка падает целиком — тогда
  // откатываемся на поштучную укладку именно этой пачки, чтобы не терять всё.
  let added = 0;
  const CHUNK = 20;
  function mkAction(m) {
    const start = ppro.TickTime.createWithSeconds(m.offset_sec);
    const dur = (typeof m.duration_sec === 'number' && m.duration_sec > 0)
      ? ppro.TickTime.createWithSeconds(m.duration_sec)
      : ppro.TickTime.TIME_ZERO;
    return markersOwner.createAddMarkerAction(m.name, 'Comment', start, dur, m.comment || '');
  }
  for (let i = 0; i < valid.length; i += CHUNK) {
    const batch = valid.slice(i, i + CHUNK);
    let batchOk = false;
    try {
      await project.lockedAccess(function () {
        return project.executeTransaction(function (ca) {
          for (const m of batch) ca.addAction(mkAction(m));
        }, `Chapter markers ${i + 1}-${i + batch.length}`);
      });
      added += batch.length;
      batchOk = true;
    } catch (e) {
      logger.debug(`marker batch ${i + 1}-${i + batch.length} failed: ${e.message}`);
    }
    if (!batchOk) {
      for (const m of batch) {
        try {
          await project.lockedAccess(function () {
            return project.executeTransaction(function (ca) {
              ca.addAction(mkAction(m));
            }, `Chapter marker ${m.name}`);
          });
          added++;
        } catch (e2) {
          logger.debug(`marker "${m.name}" failed at ${m.offset_sec}s: ${e2.message}`);
        }
        await breathe();
      }
    }
    await breathe();
  }
  if (!added) {
    logger.warn(`Chapter markers: 0/${valid.length} placed`);
    return 0;
  }

  // Step 2: colors + Chapter type on the created markers (separate guarded transactions,
  // matched by name — как в Assembly-флоу)
  try {
    const allMarkers = markersOwner.getMarkers ? await markersOwner.getMarkers() : null;
    if (allMarkers && allMarkers.length) {
      const colorByName = {};
      const noType = new Set();
      for (const m of valid) {
        const idx = MARKER_COLOR_INDEX[m.color];
        if (idx !== undefined) colorByName[m.name] = idx;
        if (m.no_chapter_type) noType.add(m.name);
      }
      let colored = 0;
      let typed = 0;
      await project.lockedAccess(function () {
        return project.executeTransaction(function (ca) {
          for (const marker of allMarkers) {
            try {
              const nm = marker.getName ? marker.getName() : '';
              const idx = colorByName[nm];
              if (idx !== undefined && typeof marker.createSetColorByIndexAction === 'function') {
                ca.addAction(marker.createSetColorByIndexAction(idx));
                colored++;
              }
            } catch (e) { /* per-marker guard */ }
          }
        }, 'Chapter marker colors');
      });
      await project.lockedAccess(function () {
        return project.executeTransaction(function (ca) {
          for (const marker of allMarkers) {
            try {
              const nm = marker.getName ? marker.getName() : '';
              // no_chapter_type: цветной, но НЕ Chapter (review-заметки RS/001 — Comment)
              if (nm && colorByName[nm] !== undefined && !noType.has(nm) && typeof marker.createSetTypeAction === 'function') {
                ca.addAction(marker.createSetTypeAction(MARKER_TYPE_CHAPTER));
                typed++;
              }
            } catch (e) { /* per-marker guard */ }
          }
        }, 'Chapter marker types');
      });
      logger.info(`Chapter markers: ${added}/${valid.length} placed, ${colored} colored, ${typed} typed`);
      return added;
    }
  } catch (e) {
    logger.debug(`marker colors/types failed (non-fatal): ${e.message}`);
  }
  logger.info(`Chapter markers: ${added}/${valid.length} placed`);
  return added;
}

module.exports = { addSceneMarkers, clearGeneratedMarkers, generatedMarkerNames,
                   GENERATED_MARKER_RE };
