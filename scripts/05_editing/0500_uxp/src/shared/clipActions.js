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
var SOURCE_TIMELINES_BIN = null;
try {
  LABEL_COLOR_INDEX = require('./constants').LABEL_COLOR_INDEX;
  SOURCE_TIMELINES_BIN = require('./constants').SOURCE_TIMELINES_BIN || null;
} catch (e) {
  LABEL_COLOR_INDEX = null;
}

// Verified bin moves (two-arg createMoveItemAction on root + read-back), 2026-09-15.
var binMove = null;
try { binMove = require('./binMove'); } catch (e) { binMove = null; }

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
async function cleanExistingSequence(project, seqName, logger, extraBin) {
  // extraBin (optional FolderItem): part.bin target — same-name sequences living
  // INSIDE it must be archived too, else every re-build duplicates the name there
  // (the root-only scan misses them once builds started landing in bins).
  // 2026-09-15: the root-level 00_Source_Timelines bin is ALWAYS scanned as well (scene
  // timelines are filed there by ingest / "Hide source timelines"), plus the project
  // items of same-named real sequences via Sequence.getProjectItem() wherever they live.
  // The archive move uses binMove (two-arg createMoveItemAction + read-back) in its OWN
  // transaction after the rename — the old one-arg move inside the rename transaction
  // never moved anything in live Premiere.
  var ARCHIVE_BIN = '03_Assembly';
  try {
    const rootItem = await project.getRootItem();
    const rootOnly = await rootItem.getItems();

    // Containers that can hold a same-name copy: root, extraBin, 00_Source_Timelines.
    var containers = [{ folder: rootItem, items: rootOnly || [], isRoot: true }];
    var seenContainer = {};
    function containerKey(f) { return (binMove && binMove.itemKey(f)) || ('name:' + (f && f.name)); }
    async function addContainer(folder) {
      if (!folder) return;
      var ck = containerKey(folder);
      if (seenContainer[ck]) return;
      seenContainer[ck] = true;
      try { containers.push({ folder: folder, items: (await folder.getItems()) || [], isRoot: false }); }
      catch (eEx) { if (logger) logger.debug('bin getItems (' + folder.name + '): ' + eEx.message); }
    }
    await addContainer(extraBin);
    if (binMove && SOURCE_TIMELINES_BIN) {
      try { await addContainer(await binMove.findRootBin(project, SOURCE_TIMELINES_BIN)); }
      catch (eSt) { if (logger) logger.debug('source timelines bin lookup: ' + eSt.message); }
    }
    var allItems = [];
    var candidates = [];   // { item, from: FolderItem|null (null = root) }
    containers.forEach(function (c) {
      c.items.forEach(function (it) {
        allItems.push(it);
        candidates.push({ item: it, from: c.isRoot ? null : c.folder });
      });
    });

    // REAL sequences only: a root item can carry the sequence's name without
    // being one (offline master-clip stubs from importing another project).
    // getSequences() is the reliable enumerator; guids identify items precisely.
    var realSeqGuids = {};   // guid → the real Sequence object (deleteSequence takes a Sequence)
    var realSeqNames = {};
    var sameNameSeqs = [];
    try {
      var realSeqs = await project.getSequences();
      for (var rq = 0; rq < (realSeqs ? realSeqs.length : 0); rq++) {
        try {
          var rqn = realSeqs[rq].name || '';
          if (rqn) realSeqNames[rqn] = true;
          if (rqn === seqName) sameNameSeqs.push(realSeqs[rq]);
          var rqg = realSeqs[rq].guid ? String(realSeqs[rq].guid) : '';
          if (rqg) realSeqGuids[rqg] = realSeqs[rq];
        } catch (eq) { /* skip */ }
      }
    } catch (eg) { if (logger) logger.debug('getSequences threw: ' + eg.message); }

    // Same-named sequences living in some OTHER bin: take their items via getProjectItem —
    // only when an id tells them apart from what the container scan already holds
    // (a stale second wrapper of the same item would be renamed twice).
    for (var sn = 0; sn < sameNameSeqs.length && binMove; sn++) {
      try {
        if (typeof sameNameSeqs[sn].getProjectItem !== 'function') continue;
        var spi = await sameNameSeqs[sn].getProjectItem();
        var sk = spi ? binMove.itemKey(spi) : null;
        if (!spi || !sk || binMove.indexOfItem(allItems, spi, sk) >= 0) continue;
        allItems.push(spi);
        candidates.push({ item: spi, from: null, viaSequence: true });
      } catch (eSp) { if (logger) logger.debug('getProjectItem: ' + eSp.message); }
    }

    // The real Sequence behind a scanned item (guid match, else Sequence.cast) — null if unknown.
    function sequenceForItem(item) {
      var g = ''; try { g = item.guid ? String(item.guid) : ''; } catch (e) { }
      if (g && realSeqGuids[g]) return realSeqGuids[g];
      var casted = null; try { casted = ppro.Sequence.cast(item); } catch (e) { }
      return casted || null;
    }

    // confirmed: guid match or Sequence.cast. nameOnly: weakest signal — enough
    // to archive (rename/move, reversible) but never to delete.
    function classifyItem(item) {
      var g = ''; try { g = item.guid ? String(item.guid) : ''; } catch (e) { }
      if (g && realSeqGuids[g]) return 'confirmed';
      var casted = null; try { casted = ppro.Sequence.cast(item); } catch (e) { }
      if (casted) return 'confirmed';
      if (realSeqNames[item.name]) return 'nameOnly';
      return 'no';
    }

    // Find or create 03_Assembly archive bin (top-level only)
    var archiveBin = null;
    for (var ai = 0; ai < rootOnly.length; ai++) {
      if (rootOnly[ai].name === ARCHIVE_BIN) {
        archiveBin = ppro.FolderItem.cast(rootOnly[ai]);
        break;
      }
    }
    if (!archiveBin) {
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            // instance createBinAction — STATIC FolderItem.createAddItemAction is absent
            // in 25.6 (this call used to throw and the archive bin was never created)
            ca.addAction(rootItem.createBinAction(ARCHIVE_BIN, true));
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

    // Find max version number among existing _v{N} sequences (every scanned container,
    // the archive bin, and ALL real sequence names — versions may live in any bin)
    var maxVersion = 0;
    var versionRe = new RegExp('^' + seqName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '_v(\\d+)$');

    // Check scanned container items
    for (var vi = 0; vi < allItems.length; vi++) {
      var vm = String(allItems[vi].name || '').match(versionRe);
      if (vm) maxVersion = Math.max(maxVersion, parseInt(vm[1], 10));
    }
    // Check every real sequence name (bin-agnostic)
    Object.keys(realSeqNames).forEach(function (rn) {
      var rm = rn.match(versionRe);
      if (rm) maxVersion = Math.max(maxVersion, parseInt(rm[1], 10));
    });
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

    for (const cand of candidates) {
      const item = cand.item;
      if (item.name === seqName && item.type !== 2) {
        // Items reached only through Sequence.getProjectItem (any bin) are archive-only:
        // they are confirmed sequences for rename/move, but never delete candidates.
        var seqConfidence = cand.viaSequence ? 'confirmed' : classifyItem(item);
        if (seqConfidence === 'no') {
          if (logger) logger.debug('Skip "' + item.name + '": name matches but it is not a sequence (imported stub?)');
          continue;
        }
        var newVersion = ++maxVersion; // bump per archived item — two same-name items must not collide
        var newName = seqName + '_v' + newVersion;
        var renamed = false;
        try {
          // 1) Rename in its OWN transaction (the proven part).
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) {
              ca.addAction(item.createSetNameAction(newName));
            }, 'Rename ' + seqName + ' → ' + newName);
          });
          renamed = true;
        } catch (renameErr) {
          // Last resort: delete — the pre-existing scope only: a CONFIRMED sequence (guid/cast)
          // at project root or in the caller's extraBin. Items found in other bins
          // (00_Source_Timelines scan, Sequence.getProjectItem in any bin) may be hand-filed
          // timelines — never deleted, left in place. A name-only match is never deleted.
          var deletable = seqConfidence === 'confirmed' && !cand.viaSequence &&
            (!cand.from || (extraBin && cand.from === extraBin));
          var seqObj = deletable ? sequenceForItem(item) : null;
          if (deletable && seqObj) {
            var deleted = false;
            try { deleted = await project.deleteSequence(seqObj); }
            catch (e3) { if (logger) logger.debug('deleteSequence threw: ' + e3.message); }
            if (logger) {
              if (deleted) logger.info('Deleted "' + seqName + '" (rename failed: ' + renameErr.message + ')');
              else logger.warn('Left "' + seqName + '" in place: rename failed (' + renameErr.message + ') and deleteSequence did not confirm');
            }
          } else if (logger) {
            var whereLeft = cand.from ? cand.from.name : (cand.viaSequence ? 'its bin' : 'project root');
            logger.warn('Left "' + seqName + '" in place (' + whereLeft + '): rename failed (' + renameErr.message + ')' +
              (seqConfidence === 'confirmed' ? ' — not deleted (outside root/extraBin or no Sequence object)' : ' and item is not a confirmed sequence'));
          }
        }
        if (!renamed) continue;
        // 2) Move to the archive bin — separate transaction, verified read-back, non-fatal.
        var where = cand.from ? cand.from.name : 'project root';
        var moved = false;
        if (archiveBin && binMove) {
          moved = await binMove.moveItemToBin(project, item, archiveBin, logger,
            { name: newName, fromBin: cand.from || null });
        }
        if (moved) {
          if (logger) logger.info('Archived: "' + seqName + '" → ' + ARCHIVE_BIN + '/' + newName);
        } else if (logger) {
          logger.info('Renamed "' + seqName + '" → "' + newName + '" (left in ' + where +
            (archiveBin ? ': move to ' + ARCHIVE_BIN + ' not verified' : ': no ' + ARCHIVE_BIN + ' bin') + ')');
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
