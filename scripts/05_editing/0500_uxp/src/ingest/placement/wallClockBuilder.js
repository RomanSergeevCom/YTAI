/**
 * Wall-clock multi-scene ingest builder.
 *
 * Replaces back-to-back placement with wall-clock layout:
 *   - Each clip placed at its wall_offset (seconds from scene_t0)
 *   - Cameras auto-detected and assigned to V1, V2, V3...
 *   - TX lavaliers (Path B++): unsplit WAV in bin, video-bounded TrackItems in sequence
 *
 * See docs/wallclock/WALLCLOCK_DESIGN.md for the full design.
 *
 * Used by timelineBuilder.js dispatcher (Phase 4) when ingest.layout_mode === "wallclock".
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../../tests/mocks/premierepro');
}

const sceneLayout = require('../layout/sceneLayout');
const { prepareTxStrips } = require('../layout/txResolver');
const sequenceFactory = require('./sequenceFactory');
const clipPlacer = require('./clipPlacer');
const binImporter = require('./binImporter');
const { findProjectItemByName } = require('../../shared/projectItemFinder');
const { camOfClip } = require('../layout/cameraResolver');
const { addSceneMarkers } = require('./sceneMarkers');
const { fileBuiltSceneSequences } = require('../../shared/sourceTimelines');

/**
 * Validate v2.0 ingest contract.
 *
 * @param {Object} ingest
 * @throws Error if contract violated
 */
function validateV2Contract(ingest) {
  if (!ingest || !Array.isArray(ingest.clips)) {
    throw new Error('wallClockBuilder: ingest.clips must be an array');
  }
  for (const clip of ingest.clips) {
    // Orphan clips (no scene field) are skipped during build — they need not
    // be prepared. Every PLACEABLE clip (has a scene) must carry both
    // creation_time and a numeric wall_offset baked by 0112.
    const placeable = clip.scene && clip.scene !== 'unknown';
    if (!placeable) continue;
    if (!clip.creation_time) {
      throw new Error(
        `wallClockBuilder: clip "${clip.clip_id || clip.filename || '?'}" missing creation_time (required in v2.0 wall-clock mode)`
      );
    }
    if (typeof clip.wall_offset !== 'number') {
      throw new Error(
        `wallClockBuilder: clip "${clip.clip_id || clip.filename || '?'}" missing numeric wall_offset — run 0112_collect_tx_strips.py to finalise v2.0`
      );
    }
  }
}

/**
 * Format a skipped-seconds value as a compact "Xm Ys" / "Ys" label.
 */
function formatSkip(sec) {
  const s = Math.round(sec);
  if (s >= 60) {
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}m${r ? ' ' + r + 's' : ''}`;
  }
  return `${s}s`;
}

/**
 * Add a Comment marker at each compressed gap so the editor sees the time jump.
 * Best-effort: marker APIs vary across Premiere versions, so every call is guarded
 * and a failure never aborts the build.
 *
 * @returns {Promise<number>} number of markers added
 */
async function addTimeJumpMarkers(project, sequence, timeJumps, logger) {
  let added = 0;
  let markers;
  try {
    markers = await sequence.getMarkers();
  } catch (e) {
    logger.debug(`getMarkers unavailable: ${e.message}`);
    return 0;
  }
  if (!markers) return 0;

  for (const j of timeJumps) {
    const tick = ppro.TickTime.createWithSeconds(j.atSec);
    const name = `⏱ +${formatSkip(j.skippedSec)}`;
    const comment = `Wall-clock gap: ${formatSkip(j.skippedSec)} skipped here`;
    try {
      if (typeof markers.createAddMarkerAction === 'function') {
        await project.lockedAccess(function () {
          return project.executeTransaction(function (ca) {
            ca.addAction(markers.createAddMarkerAction(name, 'Comment', tick, ppro.TickTime.TIME_ZERO, comment));
          }, `Time-jump marker ${name}`);
        });
        added++;
      } else if (typeof markers.createMarker === 'function') {
        await markers.createMarker(tick, 'Comment', name, comment);
        added++;
      }
    } catch (e) {
      logger.debug(`time-jump marker failed at ${j.atSec}s: ${e.message}`);
    }
  }
  if (added) logger.info(`Added ${added} time-jump marker(s)`);
  return added;
}

/**
 * Resolve a placement to its source ProjectItem in the project's bins.
 *
 * @param {Object} project
 * @param {Object} placement - from sceneLayout.plan().placements
 * @param {Object} sceneBin - target bin for this scene (or fallback to project root)
 * @param {Object} logger
 * @returns {Promise<Object|null>}
 */
async function resolveProjectItem(project, placement, sceneBin, logger) {
  // For both video and tx, the ProjectItem name == filename (without folder).
  const item = await findProjectItemByName(project, placement.filename, logger);
  if (!item && logger) {
    logger.error(`resolveProjectItem: "${placement.filename}" not found in project`);
  }
  return item;
}

/**
 * Build one scene sequence.
 *
 * @param {Object} project
 * @param {string} sceneName
 * @param {Array<Object>} sceneClips
 * @param {Array<Object>} sceneTxStrips (validated)
 * @param {Array<string>|null} camLayersOverride
 * @param {Object} ingest
 * @param {Object} sceneBin
 * @param {Object} logger
 * @returns {Promise<Object>}  { sceneName, sequence, placements, warnings }
 */
async function buildScene(project, sceneName, sceneClips, sceneTxStrips, camLayersOverride, ingest, sceneBin, logger) {
  logger.info(`\n=== Scene: ${sceneName} (${sceneClips.length} clips, ${sceneTxStrips.length} TX strips) ===`);

  // Scene fps + SEED CLIP: the sequence inherits its format from the seed
  // ("trust the seed" path skips applyMediaSettings), so the frame grid
  // Premiere quantizes against is the SEED's fps, not media.fps. Shared pure
  // logic with tools/plan_cli.js so offline plans match the live build exactly.
  const { seedClip, gridFps, sceneFpsForPlan } = sceneLayout.resolveSceneGrid(
    sceneClips, ingest, sceneName, camLayersOverride
  );
  if (Math.round(gridFps) !== Math.round(sceneFpsForPlan)) {
    logger.warn(`[${sceneName}] seed fps ${gridFps} ≠ scene fps ${sceneFpsForPlan} — TX quantization follows the SEED grid (sequence inherits seed format)`);
  }

  // 1. Build layout plan (pure logic, no UXP)
  const plan = sceneLayout.plan(sceneClips, sceneTxStrips, camLayersOverride,
    { scene: sceneName, fps: gridFps });

  if (plan.warnings.length > 0) {
    for (const w of plan.warnings) {
      logger.warn(`[${sceneName}] ${w.type}: ${JSON.stringify(w)}`);
    }
  }
  if (plan.alignmentNeeds && plan.alignmentNeeds.length) {
    logger.warn(
      `[${sceneName}] ${plan.alignmentNeeds.length} TX file(s) not frame-aligned — ` +
      `lav sync degrades to ≤½ frame. Run 0113_frame_align.py, then Rebuild: ` +
      plan.alignmentNeeds.map(n =>
        `${n.filename} (residual ${n.residualMsMin}…${n.residualMsMax}ms, ${n.slices} slice(s))`
      ).join(', ')
    );
  }

  logger.info(
    `Plan: cam_layers=${JSON.stringify(plan.cam_layers)}, ` +
    `tx_aIdx_base=${plan.tx_aIdx_base}, ` +
    `placements=${plan.placements.length} ` +
    `(${plan.placements.filter(p => p.kind === 'video').length} video, ` +
    `${plan.placements.filter(p => p.kind === 'tx').length} tx)`
  );

  // 2. Resolve all ProjectItems up-front (BFS once per filename)
  const itemByFilename = {};
  for (const p of plan.placements) {
    if (itemByFilename[p.filename] !== undefined) continue; // already resolved
    itemByFilename[p.filename] = await resolveProjectItem(project, p, sceneBin, logger);
  }

  const videoPlacements = plan.placements.filter(p => p.kind === 'video');
  const txPlacements = plan.placements.filter(p => p.kind === 'tx');

  // 3. Create the sequence seeded from a PRIMARY-camera clip whose framerate is
  //    the scene's DOMINANT fps (from 0106 probe), so the inherited format is the
  //    right one — NOT an outlier (e.g. a 1.9s 50fps establishing shot in an
  //    otherwise-25fps scene). createSequenceFromMedia seeds + clears that clip;
  //    wall-clock then re-places everything at its offset.
  const projectCode = ingest.project_code || ingest.project_name || 'YT';
  const sequenceName = `${projectCode}_${sceneName}`;
  const sceneFps = (ingest.scene_fps && ingest.scene_fps[sceneName])
    || (ingest.media && ingest.media.fps) || null;   // null keeps legacy media/seed behaviour

  // Seed was already selected BEFORE plan() (it drives the quantization grid).
  const seedItem = seedClip ? itemByFilename[seedClip.filename] : null;
  if (seedClip) logger.info(`Seed: ${seedClip.filename} (${seedClip.probe ? seedClip.probe.fps : '?'}fps) → scene fps target ${sceneFps}`);

  const mediaForScene = Object.assign({}, ingest.media, sceneFps ? { fps: sceneFps } : {});
  const sequence = await sequenceFactory.create(project, sequenceName, mediaForScene, logger, seedItem);
  const seqEditor = ppro.SequenceEditor.getEditor(sequence);

  // GRID ASSERT: "on-grid ticks are a no-op for Premiere's rounding" holds ONLY
  // if the created sequence's real ticks-per-frame equals the plan's grid. The
  // plan grid comes from the seed's ffprobe fps; the sequence inherits its
  // format from the same seed via Premiere's OWN media interpretation — a
  // VFR/misprobed seed would silently put every placement off-grid. Hard-fail
  // on a successful readback that disagrees; readback failure is only a warning
  // (getTimebase is best-effort across Premiere builds).
  try {
    const tb = await sequence.getTimebase();
    if (tb) {
      const seqTpf = Number(tb);
      const planTpf = plan.ticksPerFrame;
      const compatible = seqTpf === planTpf || (seqTpf > 0 && planTpf % seqTpf === 0);
      if (!compatible) {
        throw new Error(
          `[${sceneName}] sequence timebase ${seqTpf} ticks/frame != plan grid ${planTpf} ` +
          `(seed fps misprobe?) — placements would land off-grid; fix scene_fps/seed and rebuild`
        );
      }
    }
  } catch (err) {
    if (/timebase.*!= plan grid/.test(err.message)) throw err;
    logger.warn(`[${sceneName}] getTimebase readback unavailable (${err.message}) — grid unverified`);
  }

  // 4. Pre-warm tracks so VIDEO overwrite (which does NOT auto-create tracks)
  //    lands on real tracks. TX uses insert (auto-creates its A-track), but we
  //    still pre-warm audio up to the highest needed A-track for a clean layout.
  const maxVIdx = Math.max(0, ...plan.placements.filter(p => p.vIdx >= 0).map(p => p.vIdx));
  const maxAIdx = Math.max(0, ...plan.placements.map(p => p.aIdx));
  const placeholderItem = seedItem
    || (plan.placements.length ? itemByFilename[plan.placements[0].filename] : null);
  // Заглушку преднагрева ставим на место ПЕРВОГО клипа верхней видеодорожки:
  // её перекроет настоящий overwrite. Удаление заглушек в живой 25.6/26 молча
  // не срабатывает («1 item(s) REMAIN» в логе), и раньше каждая сборка сеяла
  // однокадровые огрызки в начало V1/V3/A1/A4/A5 — их видно на таймлайне и
  // они же ломали READBACK («stray items present»).
  const topOnMaxV = plan.placements
    .filter(p => p.vIdx === maxVIdx)
    .reduce((best, p) => (best === null || p.offsetSec < best ? p.offsetSec : best), null);
  await sequenceFactory.ensureTracks(project, sequence, seqEditor, placeholderItem,
    maxVIdx + 1, maxAIdx + 1, logger, { coverAtSec: topOnMaxV });

  // 5. Place VIDEO clips ONE PER TRANSACTION, in ascending timeline order.
  //    A single batched compound executes its actions in REVERSE (measured
  //    YTCH13 16.08.2026: RYA-FX3-1052's tail overwrote 1053's head — clip
  //    1053 lost its first frame, source_in 0.04). With sequential ascending
  //    transactions each overwrite can only trim the TAIL of its predecessor
  //    (video-master policy: heads are sacred), never the head of a successor.
  let placedCount = 0;
  let skippedCount = 0;
  const videoSorted = [...videoPlacements].sort((a, b) => a.offsetSec - b.offsetSec);
  for (const p of videoSorted) {
    const projectItem = itemByFilename[p.filename];
    if (!projectItem) {
      logger.warn(`[${sceneName}] Skipping video placement: ProjectItem not found for ${p.filename}`);
      skippedCount++;
      continue;
    }
    try {
      let placed = false;
      // createOverwriteItemAction REQUIRES locked access (live 25.6, measured
      // 17.08.2026: creating the action outside lockedAccess throws "Requires
      // locked access" and NO video lands) — build the action INSIDE the
      // transaction callback, never before it.
      await project.lockedAccess(async () => {
        await project.executeTransaction((compoundAction) => {
          const action = clipPlacer.buildVideoAction(seqEditor, projectItem, p, logger);
          if (action) { compoundAction.addAction(action); placed = true; }
        }, `Wall-clock video: ${p.filename}`);
      });
      if (placed) placedCount++; else skippedCount++;
    } catch (err) {
      logger.error(`[${sceneName}] video overwrite failed for ${p.filename}: ${err.message}`);
      skippedCount++;
    }
  }

  // 6. Place TX strips ONE AT A TIME (set→insert→clear, 3 separate transactions
  //    each — see clipPlacer). Ascending offset order per A-track so each insert
  //    lands after prior items on that track (behaves like exact placement).
  let txPlacedCount = 0;
  const txSorted = [...txPlacements].sort((a, b) => a.aIdx - b.aIdx || a.offsetSec - b.offsetSec);
  for (const p of txSorted) {
    const projectItem = itemByFilename[p.filename];
    if (!projectItem) {
      logger.warn(`[${sceneName}] Skipping TX placement: ProjectItem not found for ${p.filename}`);
      skippedCount++;
      continue;
    }
    const ok = clipPlacer.placeTxStrip(project, seqEditor, projectItem, p, logger);
    if (ok) txPlacedCount++; else skippedCount++;
  }

  // 7. Add time-jump markers at each compressed gap so the editor sees WHERE and
  //    HOW MUCH wall-clock time was skipped (best-effort; non-fatal if API differs).
  let markersAdded = 0;
  if (plan.timeJumps && plan.timeJumps.length) {
    markersAdded = await addTimeJumpMarkers(project, sequence, plan.timeJumps, logger);
  }

  // 8. READBACK GUARD: "transaction didn't throw" is NOT proof the item landed
  //    (measured 16.08.2026, 90_CTA: "Placed 3 TX, 0 skipped" but only 1 slice
  //    on the timeline). Count actual clip items per track and compare with the
  //    plan — a mismatch is loud at build time, not at a later dump.
  let missingAfterBuild = 0;
  try {
    const planCounts = {};
    for (const p of plan.placements) {
      if (p.vIdx >= 0) {
        planCounts[`V${p.vIdx + 1}`] = (planCounts[`V${p.vIdx + 1}`] || 0) + 1;
        // linked camera audio lands on the matching A-track (overwrite carries aIdx)
        planCounts[`A${p.aIdx + 1}`] = (planCounts[`A${p.aIdx + 1}`] || 0) + 1;
      } else {
        planCounts[`A${p.aIdx + 1}`] = (planCounts[`A${p.aIdx + 1}`] || 0) + 1;
      }
    }
    for (const [trackName, expected] of Object.entries(planCounts)) {
      const idx = parseInt(trackName.slice(1), 10) - 1;
      const track = trackName[0] === 'V'
        ? await sequence.getVideoTrack(idx)
        : await sequence.getAudioTrack(idx);
      if (!track) {
        logger.error(`[${sceneName}] READBACK: track ${trackName} MISSING (${expected} item(s) planned)`);
        missingAfterBuild += expected;
        continue;
      }
      const actual = (await sequenceFactory.getClipItems(track)).length;
      if (actual !== expected) {
        logger.error(
          `[${sceneName}] READBACK: ${trackName} has ${actual} item(s), plan says ${expected} — ` +
          `${expected > actual ? 'items VANISHED after an ok-insert' : 'stray items present (seed leftover?)'}`
        );
        missingAfterBuild += Math.abs(expected - actual);
      }
    }
  } catch (err) {
    logger.warn(`[${sceneName}] READBACK unavailable: ${err.message}`);
  }

  // 9. Total duration = furthest placement end (for the build summary; NEW-8).
  const totalDuration = plan.placements.reduce(
    (m, p) => Math.max(m, (p.offsetSec || 0) + (p.duration || 0)), 0
  );

  logger.info(
    `[${sceneName}] Placed ${placedCount} video + ${txPlacedCount} TX (${skippedCount} skipped` +
    (missingAfterBuild ? `, ⚠ ${missingAfterBuild} MISSING on readback` : '') +
    `), span ${totalDuration.toFixed(1)}s`
  );

  return {
    sceneName,
    sequence,
    placements: plan.placements,
    warnings: plan.warnings,
    placedCount,
    txPlacedCount,
    skippedCount,
    missingAfterBuild,
    totalDuration,
    markersAdded,
    timeJumps: plan.timeJumps || [],
    compressed: !!plan.compressed,
  };
}

/**
 * Main entry point. Builds N sequences, one per scene.
 *
 * @param {Object} project
 * @param {Object} ingest - v2.0 ingest JSON
 * @param {Object|null} sourceBin - 00_Source bin (or null for flat root import)
 * @param {Object} logger
 * @returns {Promise<{ sequences: Array<Object>, totalClipCount: number, totalTxPlaced: number }>}
 */
async function build(project, ingest, sourceBin, logger) {
  logger.info('Wall-clock multi-scene ingest START');
  validateV2Contract(ingest);

  // Step 1: Import all media into scene bins
  const { sceneBins, sceneMap, sceneNames } = await binImporter.importAllScenes(
    project, ingest, sourceBin, logger
  );

  // Step 2: For each scene, validate tx_strips and build the sequence
  const mediaSampleRate = ingest.media && ingest.media.sample_rate;
  const results = [];
  let totalClipCount = 0;
  let totalTxPlaced = 0;

  for (const sceneName of sceneNames) {
    // Skip the orphan bucket: clips without a `scene` field land in '_all'
    // (binImporter.groupBySceneSorted). These are stray files (e.g. a bonus
    // clip shot days later) — don't build a junk sequence for them (NEW-9).
    if (sceneName === '_all' || sceneName === 'unknown') {
      logger.warn(`Skipping orphan scene bucket "${sceneName}" (${(sceneMap[sceneName] || []).length} clip(s) without a scene field)`);
      continue;
    }
    const sceneClips = sceneMap[sceneName];

    // Validate TX strips for this scene
    const rawTxStrips = (ingest.tx_strips && ingest.tx_strips[sceneName]) || [];
    const { valid: validTxStrips, warnings: txValidationWarnings } = prepareTxStrips(
      rawTxStrips,
      mediaSampleRate
    );
    if (txValidationWarnings.length > 0) {
      for (const w of txValidationWarnings) {
        logger.warn(`[${sceneName}] TX validation: ${w.tx} — ${w.reason}`);
      }
    }

    const camLayersOverride = (ingest.cam_layers && ingest.cam_layers[sceneName]) || null;
    const sceneBin = sceneBins[sceneName] || sourceBin || null;

    try {
      const sceneResult = await buildScene(
        project, sceneName, sceneClips, validTxStrips,
        camLayersOverride, ingest, sceneBin, logger
      );
      // Chapter markers ("какой камень") from ingest.markers[scene]
      const chapterMarkers = ingest.markers && ingest.markers[sceneName];
      if (chapterMarkers && sceneResult.sequence) {
        await addSceneMarkers(project, sceneResult.sequence, chapterMarkers, logger);
      }
      results.push(sceneResult);
      totalClipCount += sceneResult.placedCount;
      totalTxPlaced += sceneResult.txPlacedCount;
    } catch (err) {
      logger.error(`[${sceneName}] buildScene failed: ${err.message}`);
      // Continue with next scene rather than aborting the whole build
    }
  }

  // File the fully built scene timelines ({code}_{NN}_{Scene}) into 00_Source_Timelines
  // (Roman 2026-09-15: ~18 of them cluttered the root). After EVERY scene incl. markers;
  // verified move, non-fatal — a failed move only warns and leaves the sequence in root.
  const filingCode = ingest.project_code || ingest.project_name || 'YT';
  await fileBuiltSceneSequences(project, results.map(r => ({
    name: `${filingCode}_${r.sceneName}`,
    seq: r.sequence,
  })), filingCode, logger);

  logger.info(`\nWall-clock ingest COMPLETE: ${results.length} sequence(s), ${totalClipCount} video clips, ${totalTxPlaced} TX TrackItems placed`);

  return {
    sequences: results,
    totalClipCount,
    totalTxPlaced,
    // legacy compat
    totalDjiCount: totalTxPlaced,
  };
}

module.exports = {
  build,
  // exposed for testing
  buildScene,
  validateV2Contract,
};
