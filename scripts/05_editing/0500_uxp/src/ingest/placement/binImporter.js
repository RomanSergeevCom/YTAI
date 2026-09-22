/**
 * Bin importer — imports all media into per-scene bins.
 *
 * Used by wallClockBuilder.js. Extracted from buildMultiSceneIngest:264-305.
 *
 * Public API:
 *   - importAllScenes(project, ingest, sourceBin, logger) → { sceneBins, totalImported }
 *
 * For wall-clock mode (v2.0), imports:
 *   - All video clips → per-scene sub-bins (or flat sourceBin if scene bins unavailable)
 *   - All tx_strips (unsplit WAVs) → into the scene bin matching `tx_strips[scene]`
 *
 * Legacy compatibility: also still imports `clip.dji_audio[].path` per-clip TX
 * fragments if they're present in the ingest. They become orphaned ProjectItems
 * but don't affect placement (wall-clock builder uses tx_strips, not dji_audio).
 */

const { createSceneBins } = require('../binManager');

/**
 * Group ingest.clips by scene name.
 *
 * @param {Array<Object>} clips
 * @returns {{ sceneMap: Object, sceneNames: Array<string> }}
 */
function groupBySceneSorted(clips) {
  const sceneMap = {};
  for (const clip of clips) {
    const scene = clip.scene || '_all';
    if (!sceneMap[scene]) sceneMap[scene] = [];
    sceneMap[scene].push(clip);
  }
  const sceneNames = Object.keys(sceneMap).sort();
  return { sceneMap, sceneNames };
}

/**
 * Import all media (video + tx strips + legacy dji_audio if any) into scene bins.
 *
 * @param {Object} project
 * @param {Object} ingest
 * @param {Object|null} sourceBin
 * @param {Object} logger
 * @returns {Promise<{ sceneBins: Object, totalImported: number, sceneMap: Object, sceneNames: Array<string> }>}
 */
async function importAllScenes(project, ingest, sourceBin, logger) {
  const { sceneMap, sceneNames } = groupBySceneSorted(ingest.clips);
  logger.info(`Multi-scene ingest: ${sceneNames.length} scene(s): ${sceneNames.join(', ')}`);

  // Create per-scene sub-bins under sourceBin
  let sceneBins = {};
  if (sourceBin) {
    try {
      const projectCode = ingest.project_code || ingest.project_name;
      sceneBins = await createSceneBins(project, sourceBin, sceneNames, logger, projectCode);
    } catch (binErr) {
      logger.warn(`Scene sub-bins creation failed: ${binErr.message} — using flat import`);
    }
  }

  let totalImported = 0;
  for (const sceneName of sceneNames) {
    const sceneClipList = sceneMap[sceneName];
    const targetBin = sceneBins[sceneName] || sourceBin || null;

    // Collect all file paths for this scene
    const sceneSourceFiles = sceneClipList.map(c => c.path);

    // Legacy: per-clip dji_audio fragments
    const sceneDjiFragments = [];
    for (const clip of sceneClipList) {
      if (clip.dji_audio && Array.isArray(clip.dji_audio)) {
        for (const dji of clip.dji_audio) {
          if (dji.path) sceneDjiFragments.push(dji.path);
        }
      }
    }

    // New: unsplit tx_strips (path B++)
    const sceneTxStrips = [];
    if (ingest.tx_strips && Array.isArray(ingest.tx_strips[sceneName])) {
      for (const tx of ingest.tx_strips[sceneName]) {
        if (tx.path) sceneTxStrips.push(tx.path);
      }
    }

    const allSceneFiles = [
      ...sceneSourceFiles,
      ...sceneDjiFragments,
      ...sceneTxStrips,
    ];

    logger.info(
      `Importing ${sceneName}: ${sceneSourceFiles.length} video + ${sceneDjiFragments.length} dji_audio + ${sceneTxStrips.length} tx_strips → ${targetBin ? targetBin.name : 'root'}`
    );

    if (allSceneFiles.length === 0) continue;

    try {
      await project.importFiles(allSceneFiles, true, targetBin, false);
      totalImported += allSceneFiles.length;
    } catch (importErr) {
      logger.error(`importFiles failed for ${sceneName}: ${importErr.message}`);
      throw importErr;
    }
  }

  logger.info(`Import complete: ${totalImported} file(s) across ${sceneNames.length} scene(s)`);

  return {
    sceneBins,
    totalImported,
    sceneMap,
    sceneNames,
  };
}

module.exports = {
  groupBySceneSorted,
  importAllScenes,
};
