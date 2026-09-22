/**
 * binMove.js — move a ProjectItem into a bin the ONE correct way, then PROVE it moved.
 *
 * Why this exists (2026-09-15): partsBuilder, shortsBuilder and clipActions called
 * bin.createMoveItemAction(item) with ONE argument. The real 25.6+ signature is
 *   FolderItem.createMoveItemAction(item: ProjectItem, newParent: FolderItem): Action
 * The one-arg form moved nothing, threw nothing, and was logged as success — the
 * YTUVI02 auto-save (15.09) had YTUVI02_SSEF_sources_v1 and _5_Review_v6_tz_v1/_v2 at
 * project ROOT with an empty 05_Review bin.
 *
 * Canon (Adobe docs + premiere-api sample projectPanel.ts + Adobe staff forum answer):
 *   - call on the project ROOT: rootItem.createMoveItemAction(item, FolderItem.cast(bin));
 *     item.getParentBin() is only the fallback for items already inside a sub-bin.
 *   - resolve everything async BEFORE lockedAccess; lockedAccess/executeTransaction
 *     callbacks must be SYNCHRONOUS ("The script object is no longer valid" otherwise).
 *   - one transaction per move; never create a bin and move in the same transaction.
 *   - executeTransaction returns a boolean — false = not applied.
 *   - READ-BACK after every move on fresh getItems() arrays (id via ProjectItem.getId(),
 *     25.6+); the sequence count must not grow (a copy instead of a move). Returns true
 *     ONLY when verified. Never deletes anything; on failure the item stays where it was.
 *
 * Also home of ensureRootBin (exact-name check BEFORE createBinAction — a taken name
 * spawns "name 01" duplicates) and collectTakenNames (versioning must see sequences in
 * every bin, not only root).
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

var BIN_MOVE_VERSION = '1.0.0'; // 1.0.0 (2026-09-15): two-arg createMoveItemAction on ROOT (parent-bin fallback) + read-back by getId/guid/name + sequence-count duplicate guard; replaces the one-arg moves in partsBuilder/shortsBuilder/clipActions.

var BIN_TYPE = 2;

function safeName(item) {
  try { return item && item.name != null ? String(item.name) : ''; } catch (e) { return ''; }
}

function isBinItem(item) {
  try { return !!item && item.type === BIN_TYPE; } catch (e) { return false; }
}

/** Stable identity of a ProjectItem: getId() (25.6+), else guid, else null. */
function itemKey(item) {
  if (!item) return null;
  try {
    if (typeof item.getId === 'function') {
      var id = item.getId();
      if (id != null && id !== '') return 'id:' + String(id);
    }
  } catch (e) { /* getter may throw on stale wrappers */ }
  try { if (item.guid) return 'guid:' + String(item.guid); } catch (e) { /* ignore */ }
  return null;
}

/** Index of `item` in `list` by identity, else by key (when the key is known). */
function indexOfItem(list, item, key) {
  if (!list || !item) return -1;
  for (var i = 0; i < list.length; i++) if (list[i] === item) return i;
  if (!key) return -1;
  for (var j = 0; j < list.length; j++) if (itemKey(list[j]) === key) return j;
  return -1;
}

/** How many NON-bin items carry exactly this name. */
function countByName(list, name) {
  var n = 0;
  for (var i = 0; i < (list ? list.length : 0); i++) {
    if (safeName(list[i]) === name && !isBinItem(list[i])) n++;
  }
  return n;
}

async function countSequences(project) {
  try {
    var s = await project.getSequences();
    return s ? s.length : null;
  } catch (e) { return null; }
}

function asFolder(bin) {
  if (!bin) return null;
  try { return ppro.FolderItem.cast(bin) || bin; } catch (e) { return bin; }
}

/** Existing top-level bin by exact name (FolderItem) or null — never creates. */
async function findRootBin(project, name) {
  var items = await (await project.getRootItem()).getItems();
  for (var i = 0; i < (items ? items.length : 0); i++) {
    if (items[i] && items[i].name === name) {
      var f = null;
      try { f = ppro.FolderItem.cast(items[i]); } catch (e) { f = null; }
      if (f) return f;
    }
  }
  return null;
}

/**
 * Find (exact-name at project ROOT, FolderItem.cast) or create a top-level bin.
 * 25.6: STATIC ppro.FolderItem.createAddItemAction is ABSENT — bins ONLY via the
 * instance createBinAction inside lockedAccess/executeTransaction (the proven
 * _Part_media pattern); the Action does NOT return the bin → re-fetch + cast.
 * NEVER create over a taken name (makeUnique would spawn "02_Assembly 2").
 * (Extracted from partsBuilder.ensureBin / shortsBuilder.ensureBin, 2026-09-15.)
 */
async function ensureRootBin(project, name, logger) {
  var root = await project.getRootItem();
  var items = await root.getItems();
  for (var i = 0; i < items.length; i++) {
    if (items[i].name === name) {
      var existing = ppro.FolderItem.cast(items[i]);
      if (existing) return existing;
      if (logger) logger.warn('"' + name + '" exists but is not a bin');
      return null;
    }
  }
  try {
    project.lockedAccess(function () {
      project.executeTransaction(function (ca) {
        ca.addAction(root.createBinAction(name, true));
      }, 'Create bin ' + name);
    });
  } catch (e) {
    if (logger) logger.warn('create bin "' + name + '" failed: ' + e.message);
    return null;
  }
  items = await root.getItems();
  for (var j = 0; j < items.length; j++) {
    if (items[j].name === name) return ppro.FolderItem.cast(items[j]);
  }
  if (logger) logger.warn('bin "' + name + '" not found after createBinAction');
  return null;
}

/**
 * ProjectItem of a Sequence. Sequence.getProjectItem() (25.6+) first — precise, works
 * wherever the item lives. Fallback: ROOT scan, guid match then name + non-bin (freshly
 * built sequences always land at root). NOT findProjectItemByName — its fuzzy BFS hits
 * the same-named 00_Source/{CODE}_{scene} BIN or archived _v{N} copies.
 */
async function findSequenceProjectItem(project, seq, seqName) {
  if (seq && typeof seq.getProjectItem === 'function') {
    try {
      var pi = await seq.getProjectItem();
      if (pi) return pi;
    } catch (e) { /* older build — fall back to the root scan */ }
  }
  var items = await (await project.getRootItem()).getItems();
  var byName = null;
  var want = seqName || safeName(seq);
  for (var i = 0; i < (items ? items.length : 0); i++) {
    var it = items[i];
    try { if (seq && seq.guid && it.guid && String(it.guid) === String(seq.guid)) return it; } catch (e) { /* guid getter may throw */ }
    if (!byName && it && it.name === want && !isBinItem(it)) byName = it;
  }
  return byName;
}

/**
 * Every name a new "<base>_v{N}" must not collide with: ALL real sequences
 * (project.getSequences() — bin-agnostic) ∪ root item names (stubs etc.). Once builds
 * really land in bins, a root-only scan restarts numbering at _v1 (audit 2026-09-15).
 */
async function collectTakenNames(project, logger) {
  var taken = {};
  try {
    var seqs = await project.getSequences();
    for (var i = 0; i < (seqs ? seqs.length : 0); i++) {
      var n = safeName(seqs[i]);
      if (n) taken[n] = 1;
    }
  } catch (e) { if (logger) logger.debug('collectTakenNames getSequences: ' + e.message); }
  try {
    var rootItems = await (await project.getRootItem()).getItems();
    for (var j = 0; j < (rootItems ? rootItems.length : 0); j++) {
      var rn = safeName(rootItems[j]);
      if (rn) taken[rn] = 1;
    }
  } catch (e2) { if (logger) logger.debug('collectTakenNames root: ' + e2.message); }
  return taken;
}

/** Fresh read-back: is the item in the bin, and has it left its source container? */
async function readBack(item, key, name, bin, source, srcNameCount, binNameCount) {
  var binAfter;
  try { binAfter = (await bin.getItems()) || []; }
  catch (e) { return { inBin: false, inSrc: null, reason: 'bin read-back failed: ' + e.message }; }
  var srcAfter = null;
  if (source) {
    try { srcAfter = (await source.getItems()) || []; } catch (e2) { srcAfter = null; }
  }
  var inBin;
  if (indexOfItem(binAfter, item, key) >= 0) inBin = true;
  else if (key) inBin = false;
  else inBin = countByName(binAfter, name) > binNameCount;       // no id/guid: the bin gained one
  var inSrc;
  if (!srcAfter) inSrc = null;                                   // unknown source — cannot check
  else if (indexOfItem(srcAfter, item, key) >= 0) inSrc = true;
  else if (key) inSrc = false;
  else inSrc = countByName(srcAfter, name) >= srcNameCount;      // no id/guid: the source lost one?
  return { inBin: inBin, inSrc: inSrc, reason: '' };
}

/**
 * Move `item` into `bin` and verify.
 *
 * @param {Object} project
 * @param {Object} item    ProjectItem (e.g. from findSequenceProjectItem)
 * @param {Object} bin     FolderItem target
 * @param {Object} [logger]
 * @param {Object} [opts]  { name: display/read-back name (after a rename),
 *                           fromBin: FolderItem the item currently sits in (when not root),
 *                           guardSequences: false to skip the sequence-count guard,
 *                           quiet: true to suppress the failure warn }
 * @returns {Promise<{ok:boolean, already:boolean, duplicate:boolean, reason:string}>}
 */
async function moveItemToBinDetailed(project, item, bin, logger, opts) {
  opts = opts || {};
  var name = opts.name || safeName(item) || '?';
  bin = asFolder(bin);
  var binName = safeName(bin) || '?';

  function fail(reason, duplicate) {
    if (logger && !opts.quiet) {
      logger.warn('Move "' + name + '" → bin "' + binName + '" NOT verified: ' + reason +
        ' — item left where it was, nothing deleted');
    }
    return { ok: false, already: false, duplicate: !!duplicate, reason: reason };
  }

  if (!project) return fail('no project');
  if (!item) return fail('item not found');
  if (!bin) return fail('bin not found');

  var key = itemKey(item);
  var root, rootItems, binItems;
  try {
    root = await project.getRootItem();
    rootItems = (await root.getItems()) || [];
    binItems = (await bin.getItems()) || [];
  } catch (eRead) {
    return fail('cannot read project/bin items: ' + eRead.message);
  }

  if (indexOfItem(binItems, item, key) >= 0) {
    return { ok: true, already: true, duplicate: false, reason: 'already in bin' };
  }

  // Where does it live now? Root → call on root (every official example). Otherwise the
  // given fromBin / item.getParentBin() — needed both as fallback caller and for read-back.
  var atRoot = indexOfItem(rootItems, item, key) >= 0;
  var source = atRoot ? root : (opts.fromBin ? asFolder(opts.fromBin) : null);
  if (!source) {
    try {
      if (typeof item.getParentBin === 'function') {
        var pb = await item.getParentBin();
        if (pb) source = asFolder(pb);
      }
    } catch (ePb) { source = null; }
  }
  var sourceItems = atRoot ? rootItems : null;
  if (!sourceItems && source) {
    try { sourceItems = (await source.getItems()) || []; } catch (eSi) { sourceItems = null; }
  }
  if (!atRoot && !source && !key) {
    // No id, not at root, unknown parent: a name-based read-back could not tell a move
    // from a coincidence — refuse rather than report a guess.
    return fail('item is neither at root nor in a known bin and has no id');
  }
  var srcNameCount = sourceItems ? countByName(sourceItems, name) : 0;
  var binNameCount = countByName(binItems, name);
  var seqBefore = opts.guardSequences === false ? null : await countSequences(project);

  var callers = [{ label: 'root', folder: root }];
  if (!atRoot && source && source !== root) callers.push({ label: 'parent bin', folder: source });

  var lastReason = 'no move attempted';
  for (var ci = 0; ci < callers.length; ci++) {
    var caller = callers[ci].folder;
    var label = callers[ci].label;
    var txOk;
    var noAction = false;
    try {
      // Callbacks MUST stay synchronous — no await inside (Adobe staff, forum 11935).
      project.lockedAccess(function () {
        txOk = project.executeTransaction(function (ca) {
          var action = caller.createMoveItemAction(item, bin);
          if (action) ca.addAction(action);
          else noAction = true;
        }, 'Move ' + name + ' → ' + binName);
      });
    } catch (eMove) {
      lastReason = label + '.createMoveItemAction threw: ' + eMove.message;
      continue;
    }
    if (noAction) { lastReason = label + '.createMoveItemAction returned no action'; continue; }
    if (txOk === false) { lastReason = 'executeTransaction returned false (not applied)'; continue; }

    if (seqBefore != null) {
      var seqAfter = await countSequences(project);
      if (seqAfter != null && seqAfter > seqBefore) {
        return fail('sequence count grew ' + seqBefore + ' → ' + seqAfter +
          ' — Premiere COPIED instead of moving; check the bin by hand', true);
      }
    }
    var rb = await readBack(item, key, name, bin, source, srcNameCount, binNameCount);
    if (rb.inBin && rb.inSrc === true) {
      return fail('item is now in the bin AND still in its source container (copy?)', true);
    }
    if (rb.inBin) {
      if (logger) logger.info('Moved "' + name + '" → bin "' + binName + '" (verified' + (key ? '' : ' by name') + ')');
      return { ok: true, already: false, duplicate: false, reason: '' };
    }
    lastReason = rb.reason || ('transaction ran via ' + label + ' but the item is not in the bin (read-back)');
  }
  return fail(lastReason);
}

/** Boolean wrapper: true ONLY when the move was verified (or the item already was in the bin). */
async function moveItemToBin(project, item, bin, logger, opts) {
  var r = await moveItemToBinDetailed(project, item, bin, logger, opts);
  return !!r.ok;
}

module.exports = {
  BIN_MOVE_VERSION,
  itemKey,
  indexOfItem,
  countByName,
  findRootBin,
  ensureRootBin,
  findSequenceProjectItem,
  collectTakenNames,
  moveItemToBin,
  moveItemToBinDetailed
};
