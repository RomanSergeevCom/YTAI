/**
 * Timeline builder — imports media, creates sequence, places ALL clips on V1/A1.
 * Simplified from 050205: no in/out points, whole clips placed sequentially.
 */

// In UXP environment, this would be require("premierepro")
let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

/**
 * Default sequence settings.
 * Used as fallback when createSequenceFromMedia fails.
 */
const SEQUENCE_DEFAULTS = {
  width: 3840,
  height: 2160,
  fps: 25,
  audioSampleRate: 48000,
  // System preset for UHD 4K 25fps (Mac path)
  presetPath: '/Applications/Adobe Premiere Pro 2026/Adobe Premiere Pro 2026.app/Contents/Settings/SequencePresets/UHD (4K)/UHD (4K) 2160p 25 fps.sqpreset'
};

/**
 * Find a project item by name (recursively searches bins).
 * Uses FolderItem.cast() to traverse into bins (required by Premiere UXP API).
 * @param {Object} project - Premiere Pro project
 * @param {string} name - Item name to find
 * @param {Object} [logger] - Optional logger for debug output
 * @returns {Object|null} The found project item or null
 */
async function findProjectItemByName(project, name, logger) {
  const rootItem = await project.getRootItem();
  const items = await rootItem.getItems();

  // BFS through all items — cast to FolderItem to traverse into bins
  const queue = [...items];
  const visited = [];
  while (queue.length > 0) {
    const item = queue.shift();
    visited.push(`${item.name}(t=${item.type})`);
    if (item.name === name) {
      return item;
    }
    // Also try matching without extension on search name
    const dotIdx = name.lastIndexOf('.');
    if (dotIdx > 0 && item.name === name.substring(0, dotIdx)) {
      if (logger) logger.debug(`Found by stem match: "${item.name}" for "${name}"`);
      return item;
    }
    // Also try matching without extension on item name (e.g. search "RYA-FX3-0099_TX02", item is "RYA-FX3-0099_TX02.wav")
    const itemDotIdx = item.name.lastIndexOf('.');
    if (itemDotIdx > 0 && item.name.substring(0, itemDotIdx) === name) {
      if (logger) logger.debug(`Found by item stem match: "${item.name}" for "${name}"`);
      return item;
    }
    // Cast to FolderItem to access children (bins must be cast first)
    try {
      const folder = ppro.FolderItem.cast(item);
      if (folder) {
        const children = await folder.getItems();
        if (children && children.length > 0) {
          queue.push(...children);
        }
      }
    } catch (e) {
      // Not a container or cast failed, skip
    }
  }
  if (logger) logger.warn(`findProjectItemByName: "${name}" not found. Visited: [${visited.join(', ')}]`);
  return null;
}

/**
 * List all items in a bin (for debugging).
 * Must cast to FolderItem before calling getItems().
 */
async function listBinItems(bin, logger) {
  if (!bin) return;
  try {
    const folder = ppro.FolderItem.cast(bin);
    if (!folder) {
      logger.debug(`Bin "${bin.name}" cannot be cast to FolderItem`);
      return;
    }
    const items = await folder.getItems();
    const names = items.map(i => `"${i.name}" (type=${i.type})`);
    logger.debug(`Bin "${bin.name}" contains ${items.length} item(s): ${names.join(', ')}`);
  } catch (e) {
    logger.debug(`Cannot list bin "${bin.name}": ${e.message}`);
  }
}

/**
 * Apply media settings to a sequence from ingest JSON data.
 * Used when createSequenceFromMedia is not available (clip not found).
 */
async function applyMediaSettings(project, sequence, media, logger) {
  try {
    const settings = await sequence.getSettings();

    // Frame size
    await settings.setVideoFrameSize(media.width, media.height);

    // Frame rate
    const frameRate = ppro.FrameRate.createWithValue(media.fps);
    await settings.setVideoFrameRate(frameRate);

    // Pixel aspect ratio (square)
    try {
      await settings.setVideoPixelAspectRatio(
        ppro.Constants.PixelAspectRatio.SQUARE.toString()
      );
    } catch (e) {
      logger.debug(`setVideoPixelAspectRatio not available: ${e.message}`);
    }

    // Fields (progressive)
    try {
      await settings.setVideoFieldType(ppro.Constants.FieldType.PROGRESSIVE);
    } catch (e) {
      logger.debug(`setVideoFieldType not available: ${e.message}`);
    }

    // Audio sample rate
    if (media.sample_rate) {
      try {
        const audioRate = ppro.FrameRate.createWithValue(media.sample_rate);
        await settings.setAudioSampleRate(audioRate);
      } catch (e) {
        logger.debug(`setAudioSampleRate not available: ${e.message}`);
      }
    }

    // Commit settings
    project.lockedAccess(() => {
      project.executeTransaction((compoundAction) => {
        const action = sequence.createSetSettingsAction(settings);
        compoundAction.addAction(action);
      }, 'Apply media settings');
    });

    logger.info(`Applied settings: ${media.width}x${media.height} @ ${media.fps}fps, audio ${media.sample_rate || 'default'}Hz`);
  } catch (e) {
    logger.warn(`Could not apply media settings: ${e.message}`);
  }
}

/**
 * Read and log sequence settings. Returns settings for validation.
 * Uses fallback chain for FPS since API methods vary across Premiere versions.
 * @returns {{ width: number, height: number, fps: number, vTracks: number, aTracks: number }|null}
 */
async function logSequenceSettings(sequence, logger) {
  try {
    let width = 0, height = 0, fps = 0;

    // Resolution: sequence.getFrameSize() (discovered via API introspection)
    try {
      const frameSize = await sequence.getFrameSize();
      // UXP objects may not serialize — log individual properties
      logger.debug(`getFrameSize raw: JSON=${JSON.stringify(frameSize)}, .width=${frameSize.width}, .height=${frameSize.height}, .right=${frameSize.right}`);
      if (frameSize && frameSize.width !== undefined) {
        width = frameSize.width;
        height = frameSize.height;
      } else if (frameSize && frameSize.right !== undefined) {
        width = Math.round(frameSize.right - (frameSize.left || 0));
        height = Math.round(frameSize.bottom - (frameSize.top || 0));
      } else if (typeof frameSize === 'string') {
        const parts = frameSize.split(/[x,]/);
        if (parts.length >= 2) { width = parseInt(parts[0]); height = parseInt(parts[1]); }
      }
    } catch (e) {
      logger.debug(`getFrameSize failed: ${e.message}`);
      // Fallback: settings.getVideoFrameRect()
      try {
        const settings = await sequence.getSettings();
        const rect = await settings.getVideoFrameRect();
        logger.debug(`getVideoFrameRect raw: ${JSON.stringify(rect)}`);
        if (rect && rect.right !== undefined) {
          width = Math.round(rect.right - (rect.left || 0));
          height = Math.round(rect.bottom - (rect.top || 0));
        }
      } catch (e2) {
        logger.debug(`getVideoFrameRect also failed: ${e2.message}`);
      }
    }

    // FPS: sequence.getTimebase() (discovered via API introspection)
    try {
      const timebase = await sequence.getTimebase();
      logger.debug(`getTimebase raw: ${JSON.stringify(timebase)}, type=${typeof timebase}`);
      if (typeof timebase === 'string') {
        const tbNum = parseInt(timebase);
        if (tbNum > 1000) fps = Math.round(254016000000 / tbNum * 100) / 100;
        else fps = parseFloat(timebase);
      } else if (typeof timebase === 'number') {
        if (timebase > 1000) fps = Math.round(254016000000 / timebase * 100) / 100;
        else fps = timebase;
      } else if (timebase && timebase.value !== undefined) {
        fps = timebase.value;
      }
    } catch (e) {
      logger.debug(`getTimebase failed: ${e.message}`);
    }

    const vTracks = await sequence.getVideoTrackCount();
    const aTracks = await sequence.getAudioTrackCount();

    logger.info(`Sequence: ${width}x${height}${fps ? ` @ ${fps}fps` : ' (FPS unknown)'}, V=${vTracks} A=${aTracks} tracks`);
    return { width, height, fps, vTracks, aTracks };
  } catch (e) {
    logger.debug(`logSequenceSettings failed: ${e.message}`);
    return null;
  }
}

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
  const sequenceName = `${ingest.project_name}_1_Ingest`;
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

module.exports = { buildIngestSequence, findProjectItemByName };
