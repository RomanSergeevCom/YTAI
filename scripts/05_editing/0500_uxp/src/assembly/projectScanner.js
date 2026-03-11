/**
 * projectScanner.js — Scan existing Premiere project for clips from INGEST.
 *
 * Assembly depends on INGEST having been run first (00_Source bin exists with clips).
 * This module finds those clips by filename matching — NO cross-import with ingest modules.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

const SOURCE_BIN_NAME = '00_Source';

/**
 * Find the 00_Source bin in the project root.
 * @param {Object} project - Active Premiere Pro project
 * @returns {Object} FolderItem for 00_Source
 * @throws {Error} if 00_Source not found
 */
async function findSourceBin(project) {
  const rootItem = await project.getRootItem();
  const items = await rootItem.getItems();

  for (const item of items) {
    if (item.name === SOURCE_BIN_NAME) {
      try {
        const folder = ppro.FolderItem.cast(item);
        if (folder) return folder;
      } catch (e) {
        // Not a folder, continue
      }
    }
  }

  throw new Error(
    `"${SOURCE_BIN_NAME}" bin not found. Run INGEST first to import clips.`
  );
}

/**
 * Build a map of filename -> ProjectItem from clips in 00_Source bin.
 * Scans recursively (handles subfolders inside 00_Source).
 *
 * @param {Object} sourceBin - FolderItem for 00_Source
 * @param {Object} logger - Logger instance
 * @returns {Object} clipMap: { "C5402.MP4": projectItem, ... }
 */
async function buildClipMap(sourceBin, logger) {
  const clipMap = {};

  async function scanFolder(folder, depth) {
    const items = await folder.getItems();
    for (const item of items) {
      // Skip folders at first level, recurse into subfolders
      try {
        const subFolder = ppro.FolderItem.cast(item);
        if (subFolder && depth < 3) {
          await scanFolder(subFolder, depth + 1);
          continue;
        }
      } catch (e) {
        // Not a folder — it's a media clip
      }

      const name = item.name;
      if (name) {
        // Store with and without extension for flexible matching
        clipMap[name] = item;
        const nameNoExt = name.replace(/\.[^.]+$/, '');
        if (nameNoExt !== name) {
          clipMap[nameNoExt] = item;
        }
      }
    }
  }

  await scanFolder(sourceBin, 0);
  if (logger) {
    logger.info(`Scanned ${SOURCE_BIN_NAME}: ${Object.keys(clipMap).length} entries`);
  }
  return clipMap;
}

/**
 * Validate that all source_files from the edit brief exist in the project.
 *
 * @param {Object} clipMap - Map from buildClipMap
 * @param {Array} segments - Parsed segments from edit brief
 * @param {Object} logger - Logger instance
 * @returns {{ found: number, missing: string[] }}
 */
function validateClips(clipMap, segments, logger) {
  const uniqueFiles = [...new Set(segments.map(s => s.sourceFile))];
  const missing = [];

  for (const filename of uniqueFiles) {
    if (!clipMap[filename]) {
      const nameNoExt = filename.replace(/\.[^.]+$/, '');
      if (!clipMap[nameNoExt]) {
        missing.push(filename);
      }
    }
  }

  const found = uniqueFiles.length - missing.length;
  if (logger) {
    logger.info(`Clip validation: ${found}/${uniqueFiles.length} found`);
    if (missing.length > 0) {
      for (const m of missing) {
        logger.error(`  Missing clip: ${m}`);
      }
    }
  }

  return { found, missing };
}

/**
 * Full validation: find 00_Source, build clipMap, validate all brief clips exist.
 *
 * @param {Object} project - Active Premiere project
 * @param {Array} segments - Parsed segments from edit brief
 * @param {Object} logger - Logger instance
 * @returns {{ sourceBin, clipMap, found, missing }}
 * @throws {Error} if 00_Source not found or clips missing
 */
async function validateIngestState(project, segments, logger) {
  const sourceBin = await findSourceBin(project);
  if (logger) logger.info(`Found bin: ${SOURCE_BIN_NAME}`);

  const clipMap = await buildClipMap(sourceBin, logger);

  const { found, missing } = validateClips(clipMap, segments, logger);

  if (missing.length > 0) {
    throw new Error(
      `${missing.length} clip(s) not found in ${SOURCE_BIN_NAME}: ${missing.join(', ')}. ` +
      `Run INGEST first or check source_file names in edit brief.`
    );
  }

  return { sourceBin, clipMap, found, missing };
}

module.exports = {
  SOURCE_BIN_NAME,
  findSourceBin,
  buildClipMap,
  validateClips,
  validateIngestState
};
