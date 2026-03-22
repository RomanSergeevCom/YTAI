/**
 * clipActions.js — Shared clip operations for timeline building.
 *
 * Extracted from assemblyBuilder.js to be reused by both Assembly and Review builders.
 * All functions use the UXP action-based transaction pattern.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

var LABEL_COLOR_INDEX;
try {
  LABEL_COLOR_INDEX = require('./constants').LABEL_COLOR_INDEX;
} catch (e) {
  LABEL_COLOR_INDEX = null;
}

/**
 * Apply color label to a ProjectItem BEFORE inserting it on the timeline.
 *
 * KEY INSIGHT: Colors must be applied PER SEGMENT, not in bulk.
 * When the same source file (e.g. C5403.MP4) is used in different blocks
 * with different colors (Hook=Green, Gov=Blue), we change the ProjectItem
 * color RIGHT BEFORE each insertion. Each new TrackItem inherits the color
 * that the ProjectItem has at the moment of insertion.
 *
 * @param {Object} project - Active Premiere project
 * @param {Object} item - Raw ProjectItem from clipMap
 * @param {string} color - Color name from edit brief (e.g. "Green", "Blue")
 * @param {string} label - Label for transaction log
 * @param {Object} logger - Logger instance
 */
function applyColorToItem(project, item, color, label, logger) {
  if (!color || !LABEL_COLOR_INDEX) return;
  var colorIdx = LABEL_COLOR_INDEX[color];
  if (colorIdx === undefined) {
    if (logger) logger.warn('  Color "' + color + '" not in LABEL_COLOR_INDEX for ' + label);
    return;
  }
  try {
    project.lockedAccess(function () {
      project.executeTransaction(function (ca) {
        ca.addAction(item.createSetColorLabelAction(colorIdx));
      }, 'Color: ' + label);
    });
    if (logger) logger.debug('  Color OK: ' + color + '(' + colorIdx + ') → ' + label);
  } catch (e) {
    if (logger) logger.warn('  Color failed ' + label + ': ' + color + '(' + colorIdx + ') — ' + e.message);
  }
}

/**
 * Apply color label by index directly (for Review builder).
 *
 * @param {Object} project - Active Premiere project
 * @param {Object} item - Raw ProjectItem from clipMap
 * @param {number} colorIdx - Premiere color label index (0-15)
 * @param {string} label - Label for transaction log
 * @param {Object} logger - Logger instance
 */
function applyColorByIndex(project, item, colorIdx, label, logger) {
  if (colorIdx === undefined || colorIdx === null) return;
  try {
    project.lockedAccess(function () {
      project.executeTransaction(function (ca) {
        ca.addAction(item.createSetColorLabelAction(colorIdx));
      }, 'Color: ' + label);
    });
    if (logger) logger.debug('  Color OK: idx=' + colorIdx + ' → ' + label);
  } catch (e) {
    if (logger) logger.warn('  Color failed ' + label + ': idx=' + colorIdx + ' — ' + e.message);
  }
}

/**
 * Set source in/out points on a ClipProjectItem before insertion.
 * This is the key difference from the old approach: trim BEFORE insert,
 * not after. Uses the same action-based pattern as all Premiere UXP operations.
 *
 * @param {Object} project - Active Premiere project
 * @param {Object} clipItem - ClipProjectItem (must be cast first)
 * @param {Object} inTime - TickTime for source in point
 * @param {Object} outTime - TickTime for source out point
 * @param {string} label - Label for transaction (for logging)
 * @param {Object} logger - Logger instance
 * @returns {boolean} true if successful
 */
function setSourceInOut(project, clipItem, inTime, outTime, label, logger) {
  try {
    project.lockedAccess(function () {
      project.executeTransaction(function (ca) {
        ca.addAction(clipItem.createSetInOutPointsAction(inTime, outTime));
      }, 'Pre-trim: ' + label);
    });
    return true;
  } catch (ex) {
    if (logger) {
      logger.error('Pre-trim failed for ' + label + ': ' + ex.message);
      try {
        var methods = Object.getOwnPropertyNames(Object.getPrototypeOf(clipItem))
          .filter(function (m) { return m.indexOf('create') === 0; });
        logger.debug('Available create* methods on clip: [' + methods.join(', ') + ']');
      } catch (e2) { /* ignore */ }
    }
    return false;
  }
}

/**
 * Clear source in/out points on a ClipProjectItem after insertion.
 * This ensures the same source clip can be reused with different in/out
 * points for other segments.
 */
function clearSourceInOut(project, clipItem, label, logger) {
  try {
    project.lockedAccess(function () {
      project.executeTransaction(function (ca) {
        ca.addAction(clipItem.createClearInOutPointsAction());
      }, 'Clear trim: ' + label);
    });
  } catch (ex) {
    if (logger) logger.debug('Clear in/out failed for ' + label + ': ' + ex.message);
  }
}

/**
 * Delete an existing sequence by name (for rebuild).
 *
 * @param {Object} project - Active Premiere project
 * @param {string} seqName - Sequence name to delete
 * @param {Object} logger - Logger instance
 */
async function cleanExistingSequence(project, seqName, logger) {
  var ARCHIVE_BIN = '03_Assembly';
  try {
    const rootItem = await project.getRootItem();
    const allItems = await rootItem.getItems();

    // Find or create 03_Assembly archive bin
    var archiveBin = null;
    for (var ai = 0; ai < allItems.length; ai++) {
      if (allItems[ai].name === ARCHIVE_BIN) {
        archiveBin = ppro.FolderItem.cast(allItems[ai]);
        break;
      }
    }
    if (!archiveBin) {
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(ppro.FolderItem.createAddItemAction(ARCHIVE_BIN));
          }, 'Create ' + ARCHIVE_BIN);
        });
        // Re-fetch items to find the new bin
        var updatedItems = await rootItem.getItems();
        for (var ui = 0; ui < updatedItems.length; ui++) {
          if (updatedItems[ui].name === ARCHIVE_BIN) {
            archiveBin = ppro.FolderItem.cast(updatedItems[ui]);
            break;
          }
        }
        if (logger) logger.info('Created bin: ' + ARCHIVE_BIN);
      } catch (binErr) {
        if (logger) logger.debug('Cannot create archive bin: ' + binErr.message);
      }
    }

    // Find max version number among existing _v{N} sequences (in root and archive)
    var maxVersion = 0;
    var versionRe = new RegExp('^' + seqName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '_v(\\d+)$');

    // Check root items
    for (var vi = 0; vi < allItems.length; vi++) {
      var vm = allItems[vi].name.match(versionRe);
      if (vm) maxVersion = Math.max(maxVersion, parseInt(vm[1], 10));
    }
    // Check archive bin items
    if (archiveBin) {
      try {
        var archiveItems = await archiveBin.getItems();
        for (var bi = 0; bi < archiveItems.length; bi++) {
          var bm = archiveItems[bi].name.match(versionRe);
          if (bm) maxVersion = Math.max(maxVersion, parseInt(bm[1], 10));
        }
      } catch (e) { /* empty bin */ }
    }

    for (const item of allItems) {
      if (item.name === seqName && item.type !== 2) {
        var newVersion = maxVersion + 1;
        var newName = seqName + '_v' + newVersion;
        try {
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) {
              // Rename
              ca.addAction(item.createSetNameAction(newName));
              // Move to archive bin
              if (archiveBin) {
                ca.addAction(archiveBin.createMoveItemAction(item));
              }
            }, 'Archive ' + seqName + ' → ' + ARCHIVE_BIN + '/' + newName);
          });
          if (logger) logger.info('Archived: "' + seqName + '" → ' + ARCHIVE_BIN + '/' + newName);
        } catch (renameErr) {
          // Fallback: just rename without moving
          try {
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                ca.addAction(item.createSetNameAction(newName));
              }, 'Rename ' + seqName);
            });
            if (logger) logger.info('Renamed "' + seqName + '" → "' + newName + '" (move failed: ' + renameErr.message + ')');
          } catch (e2) {
            // Last resort: delete
            try {
              await project.deleteSequence(item);
              if (logger) logger.info('Deleted "' + seqName + '" (rename+move failed)');
            } catch (e3) { }
          }
        }
      }
    }
  } catch (e) {
    if (logger) logger.warn('Clean existing sequence: ' + e.message);
  }
}

/**
 * Find and insert DJI audio on A2/A3 for a given video segment.
 *
 * DJI WAV files are named {clip_id}_TX{nn} (e.g. RYA-FX3-0100_TX02)
 * and are already imported into 00_Source by the INGEST pipeline.
 * Since DJI audio is synced 1:1 with video (same duration, same timecodes),
 * the same source in/out points apply for trimming.
 *
 * @param {Object} project - Active Premiere project
 * @param {Object} seqEditor - SequenceEditor for current sequence
 * @param {Object} clipMap - { filename: projectItem } from projectScanner
 * @param {string} sourceFile - Video source file (e.g. "RYA-FX3-0100.MP4")
 * @param {number} insertSec - Timeline position in seconds
 * @param {number} inSec - Source in point in seconds
 * @param {number} outSec - Source out point in seconds
 * @param {string} label - Segment label for logging
 * @param {Object} logger - Logger instance
 * @param {Object} [colorOpts] - Optional color to apply before insert:
 *   { color: 'Green' } → applyColorToItem (Assembly, ScreenCues)
 *   { colorIdx: 6 }    → applyColorByIndex (Review)
 *   null/undefined      → no coloring (Ingest: clips placed whole)
 * @returns {number} Number of DJI audio items placed (0 if none found)
 */
function insertDjiAudio(project, seqEditor, clipMap, sourceFile, insertSec, inSec, outSec, label, logger, colorOpts) {
  // Extract clip_id: "RYA-FX3-0100.MP4" → "RYA-FX3-0100"
  var clipId = sourceFile.replace(/\.[^.]+$/, '');

  // Find TX* items in clipMap: "RYA-FX3-0100_TX02", "RYA-FX3-0100_TX03", etc.
  // Use no-extension keys only to avoid duplicates
  var txKeys = Object.keys(clipMap).filter(function (k) {
    return k.indexOf(clipId + '_TX') === 0 && k.indexOf('.') === -1;
  }).sort(); // sorted so TX01 < TX02 < TX03

  if (txKeys.length === 0) return 0;

  var placed = 0;
  for (var ti = 0; ti < txKeys.length; ti++) {
    var txKey = txKeys[ti];
    var djiItem = clipMap[txKey];
    var audioTrack = 1 + ti; // A2=1, A3=2, ...
    var txName = txKey.substring(clipId.length + 1); // "TX02"

    // Cast for trim
    var djiCast = ppro.ClipProjectItem.cast(djiItem);
    var djiForTrim = djiCast || djiItem;

    // Apply per-segment color BEFORE insert (same pattern as V1 clips)
    if (colorOpts && colorOpts.color) {
      applyColorToItem(project, djiItem, colorOpts.color, label + ':' + txName, logger);
    } else if (colorOpts && colorOpts.colorIdx !== undefined) {
      applyColorByIndex(project, djiItem, colorOpts.colorIdx, label + ':' + txName, logger);
    }

    // Set same source in/out as video (DJI audio is synced 1:1)
    var inTime = ppro.TickTime.createWithSeconds(inSec);
    var outTime = ppro.TickTime.createWithSeconds(outSec);
    setSourceInOut(project, djiForTrim, inTime, outTime, label + ':' + txName, logger);

    // Insert on audio track only (no video)
    var insertTime = ppro.TickTime.createWithSeconds(insertSec);
    try {
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(seqEditor.createInsertProjectItemAction(
            djiItem,     // RAW item (not cast)
            insertTime,
            -1,          // no video track
            audioTrack,  // A2=1, A3=2
            true         // limitShift
          ));
        }, 'DJI ' + txName + ': ' + label);
      });
      placed++;
      if (logger) logger.debug('  DJI ' + txName + ': → A' + (audioTrack + 1) + ' @ ' + insertSec.toFixed(1) + 's');
    } catch (ex) {
      if (logger) logger.warn('  DJI ' + txName + ' insert failed for ' + label + ': ' + ex.message);
    }

    // Clear source in/out (so WAV can be reused with different trim points)
    clearSourceInOut(project, djiForTrim, label + ':' + txName, logger);
  }

  return placed;
}

module.exports = {
  applyColorToItem,
  applyColorByIndex,
  setSourceInOut,
  clearSourceInOut,
  cleanExistingSequence,
  insertDjiAudio
};
