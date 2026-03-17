/**
 * archiver.js — Versioning and archiving utility for project files.
 *
 * Uses UXP filesystem API (uxp.storage.localFileSystem).
 * UXP has no "move" operation — archive is implemented as copy + delete.
 *
 * Archive strategy:
 *   - Files → {folder}/_archive/{timestamp}/
 *   - Versions → {setupDir}/pre-edit_versions/{timestamp}_{label}.json
 *
 * Depends on: nothing (standalone utility module)
 */

var uxp;
var uxpfs;
try {
  uxp = require('uxp');
  uxpfs = uxp.storage.localFileSystem;
} catch (e) {
  // Running in test environment — no UXP API available
  uxp = null;
  uxpfs = null;
}

/**
 * Generate timestamp string for version/archive folder names.
 * @returns {string} e.g., "2026-03-15_1430"
 */
function versionTimestamp() {
  var d = new Date();
  var pad2 = function(n) { return (n < 10 ? '0' : '') + n; };
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) +
    '_' + pad2(d.getHours()) + pad2(d.getMinutes());
}

/**
 * Ensure a subfolder exists inside a parent folder.
 * Creates it if it doesn't exist.
 *
 * @param {Object} parentFolder - UXP folder entry
 * @param {string} subName - Subdirectory name to create/get
 * @param {Object} [logger] - Logger instance
 * @returns {Object} UXP folder entry for the subfolder
 */
async function ensureSubfolder(parentFolder, subName, logger) {
  try {
    var existing = await parentFolder.getEntry(subName);
    return existing;
  } catch (e) {
    // Doesn't exist — create it
    if (logger) logger.debug('Creating subfolder: ' + subName);
    return await parentFolder.createFolder(subName);
  }
}

/**
 * Archive files from a folder to a timestamped archive subdirectory.
 * Moves matching files to {folder}/_archive/{timestamp}/.
 *
 * UXP has no "move" — implemented as: read → create in archive → write → delete original.
 * For binary files (PNG), uses readBinary/writeBinary pattern.
 *
 * @param {string} folderPath - Native filesystem path to folder
 * @param {Function} filterFn - (filename: string) => boolean — which files to archive
 * @param {Object} [logger] - Logger instance
 * @returns {{ archived: number, archivePath: string }}
 */
async function archiveFiles(folderPath, filterFn, logger) {
  if (!uxpfs) throw new Error('archiveFiles requires UXP filesystem API');

  var folder = await uxpfs.getEntryWithUrl('file://' + folderPath);
  var entries = await folder.getEntries();
  var toArchive = [];

  for (var i = 0; i < entries.length; i++) {
    var entry = entries[i];
    if (entry.isFolder) continue;
    if (filterFn(entry.name)) {
      toArchive.push(entry);
    }
  }

  if (toArchive.length === 0) {
    if (logger) logger.debug('archiveFiles: nothing to archive in ' + folderPath);
    return { archived: 0, archivePath: '' };
  }

  var archiveFolder = await ensureSubfolder(folder, '_archive', logger);
  var ts = versionTimestamp();
  var tsFolder = await ensureSubfolder(archiveFolder, ts, logger);

  var archived = 0;
  for (var j = 0; j < toArchive.length; j++) {
    var src = toArchive[j];
    try {
      // Read content
      var isBinary = src.name.match(/\.(png|jpg|jpeg|gif|bmp|mp4|mov|wav|mp3)$/i);
      var content;
      if (isBinary) {
        content = await src.read({ format: uxp.storage.formats.binary });
      } else {
        content = await src.read();
      }

      // Write to archive
      var destFile = await tsFolder.createFile(src.name, { overwrite: true });
      if (isBinary) {
        await destFile.write(content, { format: uxp.storage.formats.binary });
      } else {
        await destFile.write(content);
      }

      // Delete original
      await src.delete();
      archived++;

      if (logger) logger.debug('  archived: ' + src.name);
    } catch (e) {
      if (logger) logger.warn('  archive failed for ' + src.name + ': ' + e.message);
    }
  }

  var archivePath = folderPath + '/_archive/' + ts;
  if (logger) logger.info('Archived ' + archived + ' file(s) → ' + archivePath);

  return { archived: archived, archivePath: archivePath };
}

/**
 * Save a versioned copy of a file (by content string).
 * Writes to {versionsDir}/{timestamp}_{label}.json (or other ext).
 *
 * @param {string} content - File content to save
 * @param {string} versionsDir - Native path to versions directory
 * @param {string} label - Version label (e.g., "brief_in", "brief_out")
 * @param {string} [ext] - File extension (default: "json")
 * @param {Object} [logger] - Logger instance
 * @returns {string} Filename of the saved version
 */
async function saveVersion(content, versionsDir, label, ext, logger) {
  if (!uxpfs) throw new Error('saveVersion requires UXP filesystem API');

  var extension = ext || 'json';
  var ts = versionTimestamp();
  var filename = ts + '_' + label + '.' + extension;

  var folder = await uxpfs.getEntryWithUrl('file://' + versionsDir);
  var file = await folder.createFile(filename, { overwrite: true });
  await file.write(content);

  if (logger) logger.info('Version saved: ' + filename);
  return filename;
}

/**
 * Save a state snapshot (latest_state.json) for quick reload.
 *
 * @param {string} versionsDir - Native path to versions directory
 * @param {Object} state - State object to save
 * @param {Object} [logger] - Logger instance
 */
async function saveState(versionsDir, state, logger) {
  if (!uxpfs) throw new Error('saveState requires UXP filesystem API');

  var folder = await uxpfs.getEntryWithUrl('file://' + versionsDir);
  var file = await folder.createFile('latest_state.json', { overwrite: true });
  await file.write(JSON.stringify(state, null, 2));

  if (logger) logger.debug('State saved to latest_state.json');
}

/**
 * Load the latest state snapshot (latest_state.json).
 *
 * @param {string} versionsDir - Native path to versions directory
 * @param {Object} [logger] - Logger instance
 * @returns {Object|null} Parsed state object, or null if not found
 */
async function loadState(versionsDir, logger) {
  if (!uxpfs) throw new Error('loadState requires UXP filesystem API');

  try {
    var folder = await uxpfs.getEntryWithUrl('file://' + versionsDir);
    var file = await folder.getEntry('latest_state.json');
    var content = await file.read();
    return JSON.parse(content);
  } catch (e) {
    if (logger) logger.debug('No latest_state.json found: ' + e.message);
    return null;
  }
}

/**
 * Load the most recent versioned file matching a label pattern.
 *
 * @param {string} versionsDir - Native path to versions directory
 * @param {string} labelPattern - Substring to match in filename (e.g., "brief_in")
 * @param {Object} [logger] - Logger instance
 * @returns {string|null} Content of the most recent matching file, or null
 */
async function loadLatestVersion(versionsDir, labelPattern, logger) {
  if (!uxpfs) throw new Error('loadLatestVersion requires UXP filesystem API');

  try {
    var folder = await uxpfs.getEntryWithUrl('file://' + versionsDir);
    var entries = await folder.getEntries();
    var matches = [];

    for (var i = 0; i < entries.length; i++) {
      if (entries[i].isFolder) continue;
      if (entries[i].name.indexOf(labelPattern) !== -1) {
        matches.push(entries[i]);
      }
    }

    if (matches.length === 0) return null;

    // Sort by name descending (timestamps sort lexicographically)
    matches.sort(function(a, b) {
      return b.name.localeCompare(a.name);
    });

    var content = await matches[0].read();
    if (logger) logger.info('Loaded version: ' + matches[0].name);
    return content;
  } catch (e) {
    if (logger) logger.debug('loadLatestVersion failed: ' + e.message);
    return null;
  }
}

/**
 * Ensure the versions directory exists under a Setup folder.
 *
 * @param {string} setupDir - Native path to Setup directory
 * @param {Object} [logger] - Logger instance
 * @returns {string} Native path to versions directory
 */
async function ensureVersionsDir(setupDir, logger) {
  if (!uxpfs) throw new Error('ensureVersionsDir requires UXP filesystem API');

  var folder = await uxpfs.getEntryWithUrl('file://' + setupDir);
  var versionsFolder = await ensureSubfolder(folder, 'pre-edit_versions', logger);
  return setupDir + '/pre-edit_versions';
}

module.exports = {
  versionTimestamp,
  ensureSubfolder,
  archiveFiles,
  saveVersion,
  saveState,
  loadState,
  loadLatestVersion,
  ensureVersionsDir
};
