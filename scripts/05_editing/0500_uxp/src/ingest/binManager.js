/**
 * Bin (folder) management for organizing project items.
 * Single bin: 00_Source (contains scene bins, sequences, and transcript bins).
 */

// In UXP environment, this would be require("premierepro")
let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

const BIN_NAMES = {
  SOURCE: '00_Source',
  TRANSCRIPTS: '01_Transcripts'
};

/**
 * Create the standard bin structure in the project root.
 * Only 00_Source — all content lives inside it.
 * @param {Object} project - Premiere Pro project
 * @param {Object} logger - Logger instance
 * @returns {Object} Map of bin name -> FolderItem reference
 */
async function createBinStructure(project, logger) {
  const rootItem = await project.getRootItem();
  const bins = {};

  const binOrder = [BIN_NAMES.SOURCE, BIN_NAMES.TRANSCRIPTS];

  project.lockedAccess(() => {
    project.executeTransaction((compoundAction) => {
      for (const binName of binOrder) {
        const action = rootItem.createBinAction(binName, true);
        compoundAction.addAction(action);
      }
    }, 'Create bin structure');
  });

  const items = await rootItem.getItems();
  logger.debug(`Root items after bin creation: ${items.length} item(s)`);
  for (const item of items) {
    logger.debug(`  Root item: "${item.name}" (type=${item.type})`);
    if (binOrder.includes(item.name)) {
      const folder = ppro.FolderItem.cast(item);
      bins[item.name] = folder || item;
      if (folder) {
        logger.debug(`Bin "${item.name}" cast to FolderItem: OK`);
      } else {
        logger.warn(`Bin "${item.name}" could not be cast to FolderItem`);
      }
    }
  }

  const foundBins = Object.keys(bins);
  const missingBins = binOrder.filter(b => !foundBins.includes(b));
  if (missingBins.length > 0) {
    logger.warn(`Missing bins after creation: ${missingBins.join(', ')}`);
  }
  logger.info(`Created bins: ${foundBins.join(', ')}`);
  return bins;
}

/**
 * Create scene sub-bins inside 00_Source.
 * E.g. 00_Source/YTXX01_01_apartment, 00_Source/YTXX01_02_outdoor
 */
async function createSceneBins(project, sourceBin, sceneNames, logger, projectCode) {
  if (!sourceBin || !sceneNames || sceneNames.length === 0) {
    logger.debug('No scene bins to create');
    return {};
  }

  const binNameMap = {};
  for (const scene of sceneNames) {
    binNameMap[scene] = projectCode ? `${projectCode}_${scene}` : scene;
  }
  const binNames = Object.values(binNameMap);

  project.lockedAccess(() => {
    project.executeTransaction((compoundAction) => {
      for (const binName of binNames) {
        const action = sourceBin.createBinAction(binName, true);
        compoundAction.addAction(action);
      }
    }, 'Create scene sub-bins');
  });

  const sceneBins = {};
  const items = await sourceBin.getItems();
  const binNameSet = new Set(binNames);
  for (const item of items) {
    if (binNameSet.has(item.name)) {
      const folder = ppro.FolderItem.cast(item);
      const scene = sceneNames.find(s => binNameMap[s] === item.name);
      if (scene) {
        sceneBins[scene] = folder || item;
      }
    }
  }

  logger.info(`Scene sub-bins: ${binNames.join(', ')}`);
  return sceneBins;
}

/**
 * Create per-scene transcript sub-bins inside 00_Source.
 * E.g. 00_Source/YTXX01_01_apartment_transcripts
 *
 * These sit alongside scene bins and sequences for alphabetical grouping:
 *   YTXX01_01_apartment          (sequence)
 *   YTXX01_01_apartment/         (scene bin)
 *   YTXX01_01_apartment_transcripts/  (transcript bin)
 *
 * @param {Object} project
 * @param {Object} sourceBin - The 00_Source FolderItem
 * @param {string[]} sceneNames
 * @param {Object} logger
 * @param {string} [projectCode]
 * @returns {Object} Map of scene name -> transcript FolderItem
 */
async function createTranscriptSceneBins(project, sourceBin, sceneNames, logger, projectCode) {
  if (!sourceBin || !sceneNames || sceneNames.length === 0) {
    return {};
  }

  const binNameMap = {};
  for (const scene of sceneNames) {
    binNameMap[scene] = projectCode
      ? `${projectCode}_${scene}_transcripts`
      : `${scene}_transcripts`;
  }
  const binNames = Object.values(binNameMap);

  project.lockedAccess(() => {
    project.executeTransaction((compoundAction) => {
      for (const binName of binNames) {
        const action = sourceBin.createBinAction(binName, true);
        compoundAction.addAction(action);
      }
    }, 'Create transcript scene sub-bins');
  });

  const transcriptBins = {};
  const items = await sourceBin.getItems();
  const binNameSet = new Set(binNames);
  for (const item of items) {
    if (binNameSet.has(item.name)) {
      const folder = ppro.FolderItem.cast(item);
      const scene = sceneNames.find(s => binNameMap[s] === item.name);
      if (scene) {
        transcriptBins[scene] = folder || item;
      }
    }
  }

  logger.info(`Transcript sub-bins: ${binNames.join(', ')}`);
  return transcriptBins;
}

module.exports = { createBinStructure, createSceneBins, createTranscriptSceneBins, BIN_NAMES };
