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
  if (colorIdx === undefined) return;
  try {
    project.lockedAccess(function () {
      project.executeTransaction(function (ca) {
        ca.addAction(item.createSetColorLabelAction(colorIdx));
      }, 'Color: ' + label);
    });
  } catch (e) {
    if (logger) logger.debug('  Color failed ' + label + ': ' + e.message);
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
  } catch (e) {
    if (logger) logger.debug('  Color failed ' + label + ': ' + e.message);
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
  try {
    const rootItem = await project.getRootItem();
    const allItems = await rootItem.getItems();

    for (const item of allItems) {
      if (item.name === seqName && item.type !== 2) {
        try {
          await project.deleteSequence(item);
          if (logger) logger.info('Deleted old sequence: "' + seqName + '"');
        } catch (e) {
          if (logger) logger.debug('Cannot delete sequence "' + seqName + '": ' + e.message);
        }
      }
    }
  } catch (e) {
    if (logger) logger.warn('Clean existing sequence: ' + e.message);
  }
}

module.exports = {
  applyColorToItem,
  applyColorByIndex,
  setSourceInOut,
  clearSourceInOut,
  cleanExistingSequence
};
