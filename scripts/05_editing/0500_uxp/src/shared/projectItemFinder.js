/**
 * Project item finder — recursive BFS through Premiere bins to find ProjectItem by name.
 *
 * Extracted from src/ingest/timelineBuilder.js (Phase 1.1 of wall-clock refactor).
 * Used by ingest, assembly, review, screens, and the new placement/* modules.
 *
 * Matching strategy (in order):
 *   1. Exact name match
 *   2. Stem match — search name has extension, item doesn't (or vice versa)
 *   3. Premiere duplicate-suffix match — `item.name === "${name} (1)"` etc.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

/**
 * Find a project item by name (recursively searches bins).
 * Uses FolderItem.cast() to traverse into bins (required by Premiere UXP API).
 *
 * @param {Object} project - Premiere Pro project
 * @param {string} name - Item name to find
 * @param {Object} [logger] - Optional logger for debug output
 * @returns {Promise<Object|null>} The found project item or null
 */
async function findProjectItemByName(project, name, logger) {
  const rootItem = await project.getRootItem();
  const items = await rootItem.getItems();

  // BFS through all items — cast to FolderItem to traverse into bins
  const queue = [...items];
  const visited = [];
  const dupSuffixRegex = /\s*\(\d+\)$/; // matches " (1)", " (2)", etc.

  while (queue.length > 0) {
    const item = queue.shift();
    if (!item || item.name == null) continue; // skip null/offline items (avoids crash on broken media)
    visited.push(`${item.name}(t=${item.type})`);

    // 1. Exact match
    if (item.name === name) {
      return item;
    }

    // 2a. Search name has extension, item doesn't
    const dotIdx = name.lastIndexOf('.');
    if (dotIdx > 0 && item.name === name.substring(0, dotIdx)) {
      if (logger) logger.debug(`Found by stem match: "${item.name}" for "${name}"`);
      return item;
    }

    // 2b. Item name has extension, search name doesn't
    const itemDotIdx = item.name.lastIndexOf('.');
    if (itemDotIdx > 0 && item.name.substring(0, itemDotIdx) === name) {
      if (logger) logger.debug(`Found by item stem match: "${item.name}" for "${name}"`);
      return item;
    }

    // 3. Premiere duplicate suffix " (1)", " (2)" — strip and retry
    const itemNoSuffix = item.name.replace(dupSuffixRegex, '');
    if (itemNoSuffix !== item.name) {
      if (itemNoSuffix === name) {
        if (logger) logger.debug(`Found by dup-suffix match: "${item.name}" for "${name}"`);
        return item;
      }
      // Also try stem-vs-dup-suffix combination
      const itemNoSuffixDotIdx = itemNoSuffix.lastIndexOf('.');
      if (itemNoSuffixDotIdx > 0 && itemNoSuffix.substring(0, itemNoSuffixDotIdx) === name) {
        if (logger) logger.debug(`Found by dup-suffix+stem match: "${item.name}" for "${name}"`);
        return item;
      }
      if (dotIdx > 0 && itemNoSuffix === name.substring(0, dotIdx)) {
        if (logger) logger.debug(`Found by stem+dup-suffix match: "${item.name}" for "${name}"`);
        return item;
      }
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
 *
 * @param {Object} bin - Premiere project item to inspect
 * @param {Object} logger - Logger for debug output
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

module.exports = { findProjectItemByName, listBinItems };
