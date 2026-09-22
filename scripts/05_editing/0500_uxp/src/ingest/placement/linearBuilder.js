/**
 * Linear (back-to-back) ingest builder — legacy behaviour for v1.x JSON.
 *
 * Extracted verbatim from timelineBuilder.js during Phase 4.1 of wall-clock refactor.
 * Routes here when ingest.layout_mode !== 'wallclock' OR clips lack creation_time.
 *
 * Behaviour:
 *   - Imports all media into scene bins (00_Source/{scene}/)
 *   - Creates sequence per scene via createSequenceFromMedia
 *   - Places clips back-to-back via cumulativePosition counter
 *   - Handles 2-cam multicam via ingest.multicam[scene].pairs
 *   - Places per-clip dji_audio on A-tracks
 *
 * For wall-clock layout (v2.0), see wallClockBuilder.js.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../../tests/mocks/premierepro');
}

const { findProjectItemByName, listBinItems } = require('../../shared/projectItemFinder');
const { SEQUENCE_DEFAULTS, applyMediaSettings, logSequenceSettings } = require('../../shared/mediaSettings');
const { addSceneMarkers } = require('./sceneMarkers');
const { fileBuiltSceneSequences } = require('../../shared/sourceTimelines');

/**
 * Build an ingest sequence from the ingest JSON data.
 * Imports clips into source bin, creates a sequence from the first clip,
 * and places ALL clips sequentially on V1/A1 (no in/out points — whole clips).
 *
 * @param {Object} project - Premiere Pro project
 * @param {Object} ingest - Parsed ingest JSON object
 * @param {Object|null} sourceBin - Target bin for imported media (00_Source)
 * @param {Object|null} sequenceBin - Unused, kept for backward compatibility (always null)
 * @param {Object} logger - Logger instance
 * @returns {{ sequence: Object, clipCount: number, totalDuration: number }}
 */
async function buildIngestSequence(project, ingest, sourceBin, sequenceBin, logger) {
  const clips = ingest.clips;
  const sourceFiles = clips.map(c => c.path);

  // Step 1: Import media files into source bin
  logger.info(`Importing ${sourceFiles.length} media file(s) into ${sourceBin ? sourceBin.name : 'project root'}`);
  for (const fp of sourceFiles) {
    logger.debug(`  -> ${fp}`);
  }

  try {
    await project.importFiles(sourceFiles, true, sourceBin || null, false);
    logger.info(`Import complete: ${clips.map(c => c.filename).join(', ')}`);
  } catch (importErr) {
    logger.error(`importFiles failed: ${importErr.message}`);
    throw importErr;
  }

  // Debug: list what's in the source bin after import
  if (sourceBin) {
    await listBinItems(sourceBin, logger);
  }

  // Step 2: Create sequence — try createSequenceFromMedia, fallback to preset, then default
  const sequenceName = `${ingest.project_code || ingest.project_name}_1_Ingest`;
  const firstClipName = clips[0].filename;
  const firstClip = await findProjectItemByName(project, firstClipName, logger);

  let sequence;
  let sequenceMethod = 'unknown';
  if (firstClip) {
    // Primary: create from media — inherits resolution, FPS, audio from clip
    logger.info(`First clip found: "${firstClip.name}" (type=${firstClip.type})`);
    const castFirst = ppro.ClipProjectItem.cast(firstClip);
    logger.debug(`ClipProjectItem.cast: ${castFirst ? 'success' : 'failed (using raw item)'}`);
    logger.info(`Creating sequence from media: "${sequenceName}" (cast=${!!castFirst})`);
    sequence = await project.createSequenceFromMedia(sequenceName, castFirst ? [castFirst] : [firstClip]);
    sequenceMethod = 'createSequenceFromMedia';
  } else {
    // Fallback: try system preset for correct settings
    logger.warn(`First clip "${firstClipName}" not found in project`);

    let usedPreset = false;
    try {
      logger.debug(`Trying preset: ${SEQUENCE_DEFAULTS.presetPath}`);
      sequence = await project.createSequence(sequenceName, SEQUENCE_DEFAULTS.presetPath);
      logger.info(`Created sequence from preset: UHD 4K 25fps`);
      sequenceMethod = 'preset';
      usedPreset = true;
    } catch (presetErr) {
      logger.debug(`Preset not available: ${presetErr.message}`);
    }

    if (!usedPreset) {
      sequence = await project.createSequence(sequenceName);
      sequenceMethod = 'default';
      logger.warn(`Created sequence with Premiere defaults (may not match media)`);

      // Apply settings from ingest JSON media info
      if (ingest.media) {
        await applyMediaSettings(project, sequence, ingest.media, logger);
      }
    }
  }
  logger.info(`Sequence created: "${sequenceName}" (method=${sequenceMethod}, guid=${sequence.guid || 'N/A'})`);

  // Log sequence settings for verification (also used by validation)
  const seqSettings = await logSequenceSettings(sequence, logger);

  const seqEditor = ppro.SequenceEditor.getEditor(sequence);
  logger.info(`SequenceEditor obtained: ${!!seqEditor}`);

  // Step 3: Place remaining clips sequentially on V1/A1
  // createSequenceFromMedia already placed the first clip at 0s
  const startIndex = sequenceMethod === 'createSequenceFromMedia' ? 1 : 0;
  let cumulativePosition = startIndex > 0 ? clips[0].duration : 0;
  let placedCount = startIndex > 0 ? 1 : 0;

  if (startIndex > 0) {
    logger.info(`[1/${clips.length}] First clip "${clips[0].filename}" already on V1 (from createSequenceFromMedia)`);
  }

  for (let i = startIndex; i < clips.length; i++) {
    const clip = clips[i];
    const duration = clip.duration;

    const clipItem = await findProjectItemByName(project, clip.filename, logger);
    if (!clipItem) {
      logger.error(`Clip not found in project: ${clip.filename} (${clip.clip_id})`);
      cumulativePosition = Math.round((cumulativePosition + duration) * 10) / 10;
      continue;
    }

    const insertTime = ppro.TickTime.createWithSeconds(cumulativePosition);
    logger.debug(`Inserting "${clip.filename}" at ${cumulativePosition}s (ticks=${insertTime.ticks || 'N/A'})`);

    // Insert clip at timeline position on V1/A1 (0-based track indices)
    try {
      project.lockedAccess(() => {
        project.executeTransaction((compoundAction) => {
          const insertAction = seqEditor.createInsertProjectItemAction(
            clipItem,
            insertTime,
            0, // video track 0 (V1)
            0, // audio track 0 (A1)
            true // limitShift
          );
          compoundAction.addAction(insertAction);
        }, `Insert ${clip.clip_id}`);
      });
      placedCount++;
      logger.info(`[${i + 1}/${clips.length}] Placed "${clip.filename}" (${duration}s) @ ${cumulativePosition}s`);
    } catch (insertErr) {
      logger.error(`Failed to insert "${clip.filename}": ${insertErr.message}`);
      if (insertErr.stack) logger.debug(insertErr.stack);
    }

    cumulativePosition = Math.round((cumulativePosition + duration) * 10) / 10;
  }

  // Log track counts after all clips placed
  try {
    const vCount = await sequence.getVideoTrackCount();
    const aCount = await sequence.getAudioTrackCount();
    logger.debug(`After clip placement: V=${vCount} A=${aCount} tracks, ${placedCount}/${clips.length} placed`);
  } catch (e) {
    logger.debug(`Cannot read track counts: ${e.message}`);
  }

  // Final track count
  try {
    const finalV = await sequence.getVideoTrackCount();
    const finalA = await sequence.getAudioTrackCount();
    logger.info(`Final tracks: V=${finalV} A=${finalA}`);
  } catch (e) {
    logger.debug(`Cannot read final track counts: ${e.message}`);
  }

  logger.info(`Sequence "${sequenceName}" complete: ${placedCount}/${clips.length} clip(s) placed, total ${cumulativePosition}s`);

  // Step 4: Import and place DJI audio on A2/A3 (if available)
  let djiPlaced = 0;
  const djiClips = clips.filter(c => c.dji_audio && c.dji_audio.length > 0);
  if (djiClips.length > 0) {
    // Collect all DJI audio files
    const allDjiFiles = [];
    for (const clip of djiClips) {
      for (const dji of clip.dji_audio) {
        allDjiFiles.push(dji.path);
      }
    }

    logger.info(`Importing ${allDjiFiles.length} DJI audio file(s)`);
    try {
      await project.importFiles(allDjiFiles, true, sourceBin || null, false);
    } catch (djiImportErr) {
      logger.error(`DJI audio import failed: ${djiImportErr.message}`);
    }

    // Place each DJI WAV on A2 (first TX) / A3 (second TX)
    let djiInsertTime = 0;
    for (const clip of clips) {
      if (clip.dji_audio && clip.dji_audio.length > 0) {
        for (let i = 0; i < clip.dji_audio.length; i++) {
          const dji = clip.dji_audio[i];
          const audioTrack = 1 + i; // A2=1, A3=2
          const djiStem = dji.path.replace(/^.*[\\/]/, '').replace(/\.[^.]+$/, '');
          const djiItem = await findProjectItemByName(project, djiStem, logger);
          if (!djiItem) {
            logger.warn(`DJI audio not found in project: ${djiStem}`);
            continue;
          }

          const insertTime = ppro.TickTime.createWithSeconds(djiInsertTime);
          try {
            project.lockedAccess(() => {
              project.executeTransaction((compoundAction) => {
                const action = seqEditor.createInsertProjectItemAction(
                  djiItem,
                  insertTime,
                  -1,         // no video track
                  audioTrack, // A2 or A3
                  true
                );
                compoundAction.addAction(action);
              }, `Insert DJI ${dji.tx} for ${clip.clip_id}`);
            });
            djiPlaced++;
            logger.info(`DJI ${dji.tx}: "${djiStem}" → A${audioTrack + 1} @ ${djiInsertTime}s`);
          } catch (djiErr) {
            logger.error(`Failed to place DJI audio "${djiStem}": ${djiErr.message}`);
          }
        }
      }
      djiInsertTime = Math.round((djiInsertTime + clip.duration) * 10) / 10;
    }
    logger.info(`DJI audio: ${djiPlaced} file(s) placed on timeline`);
  }

  return {
    sequence,
    sequenceMethod,
    seqSettings,
    clipCount: placedCount,
    djiCount: djiPlaced,
    totalDuration: cumulativePosition
  };
}

/**
 * Build multiple ingest sequences — one per scene folder.
 * Groups clips by clip.scene, imports all media once, then creates
 * separate sequences per scene with proper DJI audio track layout.
 *
 * @param {Object} project - Premiere Pro project
 * @param {Object} ingest - Parsed ingest JSON (clips must have .scene field)
 * @param {Object|null} sourceBin - Target bin for imported media (00_Source)
 * @param {Object} logger - Logger instance
 * @returns {{ sequences: Object[], totalClipCount: number, totalDjiCount: number }}
 */
async function buildMultiSceneIngest(project, ingest, sourceBin, logger) {
  const clips = ingest.clips;

  // ── Group clips by scene ──
  const sceneMap = {};
  for (const clip of clips) {
    const scene = clip.scene || '_all';
    if (!sceneMap[scene]) sceneMap[scene] = [];
    sceneMap[scene].push(clip);
  }
  const sceneNames = Object.keys(sceneMap).sort();
  logger.info(`Multi-scene ingest: ${sceneNames.length} scene(s): ${sceneNames.join(', ')}`);

  // ── Step 1: Create scene sub-bins and import media per scene ──
  const { createSceneBins } = require('../binManager');
  let sceneBins = {};
  if (sourceBin) {
    try {
      const projectCode = ingest.project_code || ingest.project_name;
      sceneBins = await createSceneBins(project, sourceBin, sceneNames, logger, projectCode);
    } catch (binErr) {
      logger.warn(`Scene sub-bins creation failed: ${binErr.message} — using flat import`);
    }
  }

  // Import media per scene into its sub-bin (or flat into sourceBin if no sub-bins)
  let totalImported = 0;
  for (const sceneName of sceneNames) {
    const sceneClipList = sceneMap[sceneName];
    const targetBin = sceneBins[sceneName] || sourceBin || null;

    const sceneSourceFiles = sceneClipList.map(c => c.path);
    const sceneDjiFiles = [];
    for (const clip of sceneClipList) {
      if (clip.dji_audio) {
        for (const dji of clip.dji_audio) {
          sceneDjiFiles.push(dji.path);
        }
      }
    }

    const allSceneFiles = sceneSourceFiles.concat(sceneDjiFiles);
    logger.info(`Importing ${sceneName}: ${sceneSourceFiles.length} video + ${sceneDjiFiles.length} DJI → ${targetBin ? targetBin.name : 'root'}`);
    try {
      await project.importFiles(allSceneFiles, true, targetBin, false);
      totalImported += allSceneFiles.length;
    } catch (importErr) {
      logger.error(`importFiles failed for ${sceneName}: ${importErr.message}`);
      throw importErr;
    }
  }
  logger.info(`Import complete: ${totalImported} file(s) across ${sceneNames.length} scene(s)`);

  if (sourceBin) {
    await listBinItems(sourceBin, logger);
  }

  // ── Step 2: Build one sequence per scene ──
  const results = [];
  let totalClipCount = 0;
  let totalDjiCount = 0;

  for (const sceneName of sceneNames) {
    const sceneClips = sceneMap[sceneName];
    const projectCode = ingest.project_code || ingest.project_name;
    // {code}_{scene} — the convention detection/badges/clean expect (matches
    // wallClockBuilder); a bare scene name here makes every rebuild stack a
    // duplicate sequence the panel can never see.
    const sequenceName = `${projectCode}_${sceneName}`;

    logger.info(`\n=== Scene: ${sceneName} (${sceneClips.length} clips) ===`);

    // Determine TX channels in this scene for consistent track assignment
    const sceneTxIds = new Set();
    for (const clip of sceneClips) {
      if (clip.dji_audio) {
        for (const dji of clip.dji_audio) {
          sceneTxIds.add(dji.tx);
        }
      }
    }
    const sortedTx = [...sceneTxIds].sort(); // e.g. ["TX01", "TX02"]
    logger.info(`Scene TX channels: ${sortedTx.join(', ') || 'none'}`);

    // Create sequence from first clip
    const firstClipName = sceneClips[0].filename;
    const firstClip = await findProjectItemByName(project, firstClipName, logger);

    let sequence;
    let sequenceMethod = 'unknown';
    if (firstClip) {
      const castFirst = ppro.ClipProjectItem.cast(firstClip);
      sequence = await project.createSequenceFromMedia(
        sequenceName, castFirst ? [castFirst] : [firstClip]);
      sequenceMethod = 'createSequenceFromMedia';
    } else {
      logger.warn(`First clip "${firstClipName}" not found, using preset`);
      let usedPreset = false;
      try {
        sequence = await project.createSequence(sequenceName, SEQUENCE_DEFAULTS.presetPath);
        sequenceMethod = 'preset';
        usedPreset = true;
      } catch (presetErr) {
        logger.debug(`Preset not available: ${presetErr.message}`);
      }
      if (!usedPreset) {
        sequence = await project.createSequence(sequenceName);
        sequenceMethod = 'default';
        if (ingest.media) {
          await applyMediaSettings(project, sequence, ingest.media, logger);
        }
      }
    }
    logger.info(`Sequence "${sequenceName}" created (method=${sequenceMethod})`);

    const seqSettings = await logSequenceSettings(sequence, logger);
    const seqEditor = ppro.SequenceEditor.getEditor(sequence);

    // ── Detect multicam scene ──
    const isMulticam = sceneClips.some(c => c.camera === 2);
    const multicamPairs = (ingest.multicam && ingest.multicam[sceneName])
      ? ingest.multicam[sceneName].pairs || []
      : [];

    let placedCount = 0;
    let djiPlaced = 0;
    let sceneTotalDuration = 0;

    if (isMulticam && multicamPairs.length > 0) {
      // ═══ MULTICAM: V1=cam1, V2=cam2, A1=cam1 audio, A2=cam2 audio, A3+=TX ═══
      logger.info(`MULTICAM scene: ${multicamPairs.length} pair(s)`);

      const cam1Clips = sceneClips.filter(c => c.camera !== 2);
      const cam2Clips = sceneClips.filter(c => c.camera === 2);

      // Build pair map: cam1_id → cam2_id
      const pairMap = {};
      for (const [cam1Id, cam2Id] of multicamPairs) {
        pairMap[cam1Id] = cam2Id;
      }

      // Build cam2 position map: cam2_clip_id → timeline offset (from cam1 pair position)
      const cam2Positions = {};

      // Place cam1 clips on V1 sequentially
      const startIndex = sequenceMethod === 'createSequenceFromMedia' ? 1 : 0;
      let cumulativePosition = startIndex > 0 ? cam1Clips[0].duration : 0;
      placedCount = startIndex > 0 ? 1 : 0;

      if (startIndex > 0) {
        logger.info(`[cam1 1/${cam1Clips.length}] First clip "${cam1Clips[0].filename}" already on V1`);
        // Record position for paired cam2 clip
        if (pairMap[cam1Clips[0].clip_id]) {
          cam2Positions[pairMap[cam1Clips[0].clip_id]] = 0;
        }
      }

      for (let i = startIndex; i < cam1Clips.length; i++) {
        const clip = cam1Clips[i];
        const clipItem = await findProjectItemByName(project, clip.filename, logger);
        if (!clipItem) {
          logger.error(`Cam1 clip not found: ${clip.filename}`);
          // Record position even on failure so cam2 can still be placed
          if (pairMap[clip.clip_id]) {
            cam2Positions[pairMap[clip.clip_id]] = cumulativePosition;
          }
          cumulativePosition = Math.round((cumulativePosition + clip.duration) * 10) / 10;
          continue;
        }

        const insertTime = ppro.TickTime.createWithSeconds(cumulativePosition);
        try {
          project.lockedAccess(() => {
            project.executeTransaction((compoundAction) => {
              const action = seqEditor.createInsertProjectItemAction(
                clipItem, insertTime, 0, 0, true);  // V1=0, A1=0
              compoundAction.addAction(action);
            }, `Insert cam1 ${clip.clip_id}`);
          });
          placedCount++;
          logger.info(`[cam1] "${clip.filename}" → V1 @ ${cumulativePosition}s`);
        } catch (err) {
          logger.error(`Failed cam1 "${clip.filename}": ${err.message}`);
        }

        // Record cam2 pair position
        if (pairMap[clip.clip_id]) {
          cam2Positions[pairMap[clip.clip_id]] = cumulativePosition;
        }
        cumulativePosition = Math.round((cumulativePosition + clip.duration) * 10) / 10;
      }

      // Place cam2 clips on V2 at paired positions (use overwrite to avoid shifting)
      for (const clip of cam2Clips) {
        const pos = cam2Positions[clip.clip_id];
        if (pos === undefined) {
          logger.warn(`Cam2 "${clip.clip_id}" has no paired position, skipping`);
          continue;
        }

        const clipItem = await findProjectItemByName(project, clip.filename, logger);
        if (!clipItem) {
          logger.error(`Cam2 clip not found: ${clip.filename}`);
          continue;
        }

        const insertTime = ppro.TickTime.createWithSeconds(pos);
        try {
          project.lockedAccess(() => {
            project.executeTransaction((compoundAction) => {
              const action = seqEditor.createOverwriteItemAction(
                clipItem, insertTime, 1, 1);  // V2=1, A2=1
              compoundAction.addAction(action);
            }, `Insert cam2 ${clip.clip_id}`);
          });
          placedCount++;
          logger.info(`[cam2] "${clip.filename}" → V2 @ ${pos}s`);
        } catch (err) {
          logger.error(`Failed cam2 "${clip.filename}": ${err.message}`);
        }
      }

      // Place DJI audio on A3+ (offset by 2 for multicam: A3=2, A4=3)
      const djiTrackOffset = 2;
      if (sortedTx.length > 0) {
        const txToTrack = {};
        for (let t = 0; t < sortedTx.length; t++) {
          txToTrack[sortedTx[t]] = djiTrackOffset + t; // A3=2, A4=3
        }

        // DJI insert times follow cam1 timeline positions
        let djiInsertTime = 0;
        for (const clip of cam1Clips) {
          if (clip.dji_audio && clip.dji_audio.length > 0) {
            for (const dji of clip.dji_audio) {
              const audioTrack = txToTrack[dji.tx];
              if (audioTrack === undefined) continue;

              const djiStem = dji.path.replace(/^.*[\\/]/, '').replace(/\.[^.]+$/, '');
              const djiItem = await findProjectItemByName(project, djiStem, logger);
              if (!djiItem) {
                logger.warn(`DJI audio not found: ${djiStem}`);
                continue;
              }

              const insertTime = ppro.TickTime.createWithSeconds(djiInsertTime);
              try {
                project.lockedAccess(() => {
                  project.executeTransaction((compoundAction) => {
                    const action = seqEditor.createInsertProjectItemAction(
                      djiItem, insertTime, -1, audioTrack, true);
                    compoundAction.addAction(action);
                  }, `Insert DJI ${dji.tx} for ${clip.clip_id}`);
                });
                djiPlaced++;
                logger.info(`DJI ${dji.tx}: "${djiStem}" → A${audioTrack + 1} @ ${djiInsertTime}s`);
              } catch (djiErr) {
                logger.error(`Failed DJI "${djiStem}": ${djiErr.message}`);
              }
            }
          }
          djiInsertTime = Math.round((djiInsertTime + clip.duration) * 10) / 10;
        }
        logger.info(`DJI audio (multicam): ${djiPlaced} file(s) on A3+ (${sortedTx.join(', ')})`);
      }
      sceneTotalDuration = cumulativePosition;

    } else {
      // ═══ SINGLE CAM: existing behavior — V1/A1 + DJI on A2/A3 ═══
      const startIndex = sequenceMethod === 'createSequenceFromMedia' ? 1 : 0;
      let cumulativePosition = startIndex > 0 ? sceneClips[0].duration : 0;
      placedCount = startIndex > 0 ? 1 : 0;

      if (startIndex > 0) {
        logger.info(`[1/${sceneClips.length}] First clip "${sceneClips[0].filename}" already on V1`);
      }

      for (let i = startIndex; i < sceneClips.length; i++) {
        const clip = sceneClips[i];
        const clipItem = await findProjectItemByName(project, clip.filename, logger);
        if (!clipItem) {
          logger.error(`Clip not found: ${clip.filename}`);
          cumulativePosition = Math.round((cumulativePosition + clip.duration) * 10) / 10;
          continue;
        }

        const insertTime = ppro.TickTime.createWithSeconds(cumulativePosition);
        try {
          project.lockedAccess(() => {
            project.executeTransaction((compoundAction) => {
              const action = seqEditor.createInsertProjectItemAction(
                clipItem, insertTime, 0, 0, true);
              compoundAction.addAction(action);
            }, `Insert ${clip.clip_id}`);
          });
          placedCount++;
          logger.info(`[${i + 1}/${sceneClips.length}] "${clip.filename}" (${clip.duration}s) @ ${cumulativePosition}s`);
        } catch (insertErr) {
          logger.error(`Failed to insert "${clip.filename}": ${insertErr.message}`);
        }
        cumulativePosition = Math.round((cumulativePosition + clip.duration) * 10) / 10;
      }

      // Place DJI audio — TX01 → A2 (track 1), TX02 → A3 (track 2), etc.
      if (sortedTx.length > 0) {
        const txToTrack = {};
        for (let t = 0; t < sortedTx.length; t++) {
          txToTrack[sortedTx[t]] = 1 + t; // A2=1, A3=2
        }

        let djiInsertTime = 0;
        for (const clip of sceneClips) {
          if (clip.dji_audio && clip.dji_audio.length > 0) {
            for (const dji of clip.dji_audio) {
              const audioTrack = txToTrack[dji.tx];
              if (audioTrack === undefined) continue;

              const djiStem = dji.path.replace(/^.*[\\/]/, '').replace(/\.[^.]+$/, '');
              const djiItem = await findProjectItemByName(project, djiStem, logger);
              if (!djiItem) {
                logger.warn(`DJI audio not found: ${djiStem}`);
                continue;
              }

              const insertTime = ppro.TickTime.createWithSeconds(djiInsertTime);
              try {
                project.lockedAccess(() => {
                  project.executeTransaction((compoundAction) => {
                    const action = seqEditor.createInsertProjectItemAction(
                      djiItem, insertTime, -1, audioTrack, true);
                    compoundAction.addAction(action);
                  }, `Insert DJI ${dji.tx} for ${clip.clip_id}`);
                });
                djiPlaced++;
                logger.info(`DJI ${dji.tx}: "${djiStem}" → A${audioTrack + 1} @ ${djiInsertTime}s`);
              } catch (djiErr) {
                logger.error(`Failed DJI "${djiStem}": ${djiErr.message}`);
              }
            }
          }
          djiInsertTime = Math.round((djiInsertTime + clip.duration) * 10) / 10;
        }
        logger.info(`DJI audio: ${djiPlaced} file(s) placed (${sortedTx.join(', ')})`);
      }
      sceneTotalDuration = cumulativePosition;
    }

    totalClipCount += placedCount;
    totalDjiCount += djiPlaced;

    // createSequence/createSequenceFromMedia always place the sequence at project root.
    // Scene timelines ({code}_{NN}_{Scene}) are filed into 00_Source_Timelines AFTER the
    // loop (every scene fully built, markers included) via shared/sourceTimelines —
    // two-arg FolderItem.createMoveItemAction on root + read-back (2026-09-15). The old
    // "moveBin creates duplicates" note was about the legacy ProjectItem.moveBin API.

    // Chapter markers ("какой камень") from ingest.markers[scene]
    const chapterMarkers = ingest.markers && ingest.markers[sceneName];
    if (chapterMarkers && sequence) {
      await addSceneMarkers(project, sequence, chapterMarkers, logger);
    }

    results.push({
      sceneName,
      sequence,
      sequenceMethod,
      seqSettings,
      clipCount: placedCount,
      djiCount: djiPlaced,
      totalDuration: sceneTotalDuration,
    });
  }

  // File the fully built scene timelines into 00_Source_Timelines (non-fatal, verified).
  const filingCode = ingest.project_code || ingest.project_name;
  await fileBuiltSceneSequences(project, results.map(r => ({
    name: `${filingCode}_${r.sceneName}`,
    seq: r.sequence,
  })), filingCode, logger);

  logger.info(`\nMulti-scene ingest complete: ${results.length} sequence(s), ${totalClipCount} clips, ${totalDjiCount} DJI`);
  return { sequences: results, totalClipCount, totalDjiCount };
}

module.exports = {
  build: buildMultiSceneIngest,    // unified API name for dispatcher
  buildIngestSequence,             // legacy single-scene path
  buildMultiSceneIngest,           // legacy multi-scene path
};
