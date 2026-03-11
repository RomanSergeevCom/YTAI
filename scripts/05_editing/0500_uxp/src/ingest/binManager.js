/**
 * Bin (folder) management for organizing project items.
 * Simplified for ingest: 2 bins (00_Source, 02_Transcripts).
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
  TRANSCRIPTS: '02_Transcripts'
};

/**
 * Create the standard bin structure in the project root.
 * Casts bins to FolderItem so getItems() works on them.
 * @param {Object} project - Premiere Pro project
 * @param {Object} logger - Logger instance
 * @returns {Object} Map of bin name -> FolderItem reference
 */
async function createBinStructure(project, logger) {
  const rootItem = await project.getRootItem();
  const bins = {};

  const binOrder = [
    BIN_NAMES.SOURCE,
    BIN_NAMES.TRANSCRIPTS
  ];

  project.lockedAccess(() => {
    project.executeTransaction((compoundAction) => {
      for (const binName of binOrder) {
        const action = rootItem.createBinAction(binName, true);
        compoundAction.addAction(action);
      }
    }, 'Create bin structure');
  });

  // Get created bins — cast to FolderItem for proper API access
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

module.exports = { createBinStructure, BIN_NAMES };
