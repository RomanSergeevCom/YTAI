/**
 * sourceTimelines.js — keep ingest scene timelines out of the project root.
 *
 * Roman (2026-09-15, Premiere 26.x): the Project panel root was cluttered by ~18 source
 * timelines = ingest scene sequences {CODE}_{NN}_{Scene} (TWO-digit scene index, e.g.
 * YTUVI02_01_Studio … YTUVI02_17_UviStore_Showcase_Broll). They go into the top-level
 * bin 00_Source_Timelines (constants.SOURCE_TIMELINES_BIN). Working stage timelines stay:
 * {CODE}_5_Review_* / {CODE}_1_Ingest (single digit), {CODE}_part_*, {CODE}_A01_*, shorts.
 *
 *   isSceneSequenceName(name, code)       — the ONE selection rule (^{CODE}_\d{2}_)
 *   fileBuiltSceneSequences(project, …)   — ingest builders: file freshly built scenes
 *   hideSourceTimelines(project, code, …) — panel button: move every scene timeline that
 *                                            is still at ROOT; idempotent; probe-first
 *
 * Every move goes through binMove.moveItemToBinDetailed (two-arg createMoveItemAction on
 * root + read-back + duplicate guard). Nothing is ever deleted; failures stay at root.
 */

const { SOURCE_TIMELINES_BIN } = require('./constants');
const binMove = require('./binMove');

var SOURCE_TIMELINES_VERSION = '1.0.0'; // 1.0.0 (2026-09-15): 00_Source_Timelines bin — ingest post-build filing + "Hide source timelines" batch (Ingest + Doctor tabs).

function escapeRe(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** ^{CODE}_\d{2}_ — with no code, any YT{2-5 letters}{digits} project prefix. */
function sceneSequenceRegex(code) {
  if (code) return new RegExp('^' + escapeRe(code) + '_\\d{2}_');
  return /^YT[A-Z]{2,5}\d+_\d{2}_/;
}

function isSceneSequenceName(name, code) {
  if (!name) return false;
  return sceneSequenceRegex(code).test(String(name));
}

/** Normalise [{name, seq}] | [Sequence] → [{name, seq}] and keep scene timelines only. */
function selectSceneSequences(list, code) {
  var out = [];
  var re = sceneSequenceRegex(code);
  for (var i = 0; i < (list ? list.length : 0); i++) {
    var e = list[i];
    if (!e) continue;
    var entry = (e.seq !== undefined && e.name !== undefined) ? e : { name: safeSeqName(e), seq: e };
    if (entry.name && re.test(entry.name)) out.push(entry);
  }
  return out;
}

function safeSeqName(seq) {
  try { return seq && seq.name != null ? String(seq.name) : ''; } catch (e) { return ''; }
}

async function defaultListSequences(project) {
  var out = [];
  try {
    var seqs = await project.getSequences();
    for (var i = 0; i < (seqs ? seqs.length : 0); i++) {
      var n = safeSeqName(seqs[i]);
      if (n) out.push({ name: n, seq: seqs[i] });
    }
  } catch (e) { /* none */ }
  return out;
}

/**
 * Where is this sequence's ProjectItem right now?
 * → { where: 'root'|'bin'|'elsewhere'|'ambiguous'|'missing', item }
 * getProjectItem() + getId() first (25.6+, exact). Fallbacks: guid, then name — the name
 * fallback refuses when more same-named items exist than real sequences (offline
 * master-clip stubs from an imported project carry sequence names, YTUVI05 dump).
 */
async function locateSequenceItem(entry, rootItems, binItems, realCount) {
  var pi = null;
  if (entry.seq && typeof entry.seq.getProjectItem === 'function') {
    try { pi = await entry.seq.getProjectItem(); } catch (e) { pi = null; }
  }
  if (pi) {
    var key = binMove.itemKey(pi);
    var bi = binMove.indexOfItem(binItems, pi, key);
    if (bi >= 0) return { where: 'bin', item: binItems[bi] };
    var ri = binMove.indexOfItem(rootItems, pi, key);
    if (ri >= 0) return { where: 'root', item: rootItems[ri] };
    if (key) return { where: 'elsewhere', item: pi };
  }
  var g = '';
  try { g = entry.seq && entry.seq.guid ? String(entry.seq.guid) : ''; } catch (e) { g = ''; }
  if (g) {
    for (var r = 0; r < rootItems.length; r++) {
      try { if (rootItems[r].guid && String(rootItems[r].guid) === g) return { where: 'root', item: rootItems[r] }; } catch (e) { /* skip */ }
    }
    for (var b = 0; b < binItems.length; b++) {
      try { if (binItems[b].guid && String(binItems[b].guid) === g) return { where: 'bin', item: binItems[b] }; } catch (e) { /* skip */ }
    }
  }
  var rootSame = [];
  for (var k = 0; k < rootItems.length; k++) {
    if (rootItems[k] && rootItems[k].name === entry.name && rootItems[k].type !== 2) rootSame.push(rootItems[k]);
  }
  var binSame = binMove.countByName(binItems, entry.name);
  if (!rootSame.length) return { where: binSame ? 'bin' : 'missing', item: null };
  if (rootSame.length + binSame > (realCount[entry.name] || 1)) return { where: 'ambiguous', item: null };
  return { where: 'root', item: rootSame[0] };
}

/**
 * Ingest post-build: file the scene sequences that were JUST built (still at root) into
 * 00_Source_Timelines. Call after every scene is fully built (markers included).
 * Non-fatal — any failure only warns; the sequence stays at root.
 *
 * @param {Object} project
 * @param {Array<{name:string, seq:Object}>} built
 * @param {string} code  - the prefix the builder named them with ({code}_{scene})
 * @param {Object} logger
 * @returns {Promise<{moved:number, failed:number, considered:number}>}
 */
async function fileBuiltSceneSequences(project, built, code, logger) {
  var res = { moved: 0, failed: 0, considered: 0 };
  try {
    var targets = selectSceneSequences((built || []).filter(function (b) { return b && b.seq; }), code);
    res.considered = targets.length;
    if (!targets.length) return res;
    var bin = await binMove.ensureRootBin(project, SOURCE_TIMELINES_BIN, logger);
    if (!bin) {
      res.failed = targets.length;
      if (logger) logger.warn('Source timelines: bin "' + SOURCE_TIMELINES_BIN + '" unavailable — ' + targets.length + ' scene sequence(s) left in root');
      return res;
    }
    for (var i = 0; i < targets.length; i++) {
      var t = targets[i];
      var item = null;
      try { item = await binMove.findSequenceProjectItem(project, t.seq, t.name); } catch (eF) { item = null; }
      var r = await binMove.moveItemToBinDetailed(project, item, bin, logger, { name: t.name });
      if (r.ok) res.moved++;
      else {
        res.failed++;
        if (r.duplicate) {
          if (logger) logger.warn('Source timelines: duplicate guard tripped — not moving the remaining scene sequences');
          res.failed += targets.length - i - 1;
          break;
        }
      }
    }
    if (logger) {
      var msg = 'Source timelines: ' + res.moved + '/' + targets.length + ' scene sequence(s) → ' + SOURCE_TIMELINES_BIN;
      if (res.failed) logger.warn(msg + ' (' + res.failed + ' left in project root)');
      else logger.info(msg);
    }
  } catch (e) {
    if (logger) logger.warn('Source timelines filing (non-fatal): ' + e.message);
  }
  return res;
}

/**
 * Panel action: move every {CODE}_{NN}_* sequence still at project ROOT into
 * 00_Source_Timelines. Idempotent (already-filed ones are counted, not touched).
 * Probe-first: if the FIRST attempted move is not verified, stops before touching the
 * rest; a duplicate-guard trip stops the batch at once.
 *
 * @param {Object} project
 * @param {string} code
 * @param {Object} logger
 * @param {Object} [opts] { listSequences: async (project, logger) => [{name, seq}] }
 * @returns {Promise<Object>} { total, moved, already, failed, skipped, stopped, bin, names:{…} }
 */
async function hideSourceTimelines(project, code, logger, opts) {
  opts = opts || {};
  var report = {
    total: 0, moved: 0, already: 0, failed: 0, skipped: 0, stopped: null,
    bin: SOURCE_TIMELINES_BIN, names: { moved: [], already: [], failed: [], skipped: [] }
  };
  if (!project) { report.stopped = 'no open project'; return report; }
  if (!code) { report.stopped = 'no project code'; return report; }

  var list = opts.listSequences ? await opts.listSequences(project, logger) : await defaultListSequences(project);
  list = list || [];
  var targets = selectSceneSequences(list, code);
  report.total = targets.length;
  if (!targets.length) return report;

  var realCount = {};
  for (var c = 0; c < list.length; c++) {
    if (list[c] && list[c].name) realCount[list[c].name] = (realCount[list[c].name] || 0) + 1;
  }

  var bin = await binMove.ensureRootBin(project, SOURCE_TIMELINES_BIN, logger);
  if (!bin) {
    report.stopped = 'bin "' + SOURCE_TIMELINES_BIN + '" could not be found or created';
    return report;
  }
  var root = await project.getRootItem();

  for (var i = 0; i < targets.length; i++) {
    var t = targets[i];
    var rootItems = (await root.getItems()) || [];   // fresh every time — earlier moves change it
    var binItems = (await bin.getItems()) || [];
    var loc = await locateSequenceItem(t, rootItems, binItems, realCount);
    if (loc.where === 'bin') { report.already++; report.names.already.push(t.name); continue; }
    if (loc.where !== 'root') {
      report.skipped++;
      report.names.skipped.push(t.name + ' (' + loc.where + ')');
      if (logger) logger.info('Source timelines: skip "' + t.name + '" — ' +
        (loc.where === 'elsewhere' ? 'lives in another bin (only root items are moved)'
          : loc.where === 'ambiguous' ? 'several same-named items at root (offline stubs?) — move by hand'
            : 'project item not found'));
      continue;
    }
    var r = await binMove.moveItemToBinDetailed(project, loc.item, bin, logger, { name: t.name });
    if (r.ok && r.already) { report.already++; report.names.already.push(t.name); continue; }
    if (r.ok) { report.moved++; report.names.moved.push(t.name); continue; }
    report.failed++;
    report.names.failed.push(t.name);
    if (r.duplicate) { report.stopped = 'duplicate guard: ' + r.reason; break; }
    if (report.moved === 0 && report.failed === 1) {
      report.stopped = 'first move not verified (' + r.reason + ') — the rest was not touched';
      break;
    }
  }
  if (logger) {
    logger.info('Hide source timelines: ' + formatHideReport(report));
  }
  return report;
}

/** "moved N · already in bin M · failed K" (+ skipped / stop reason). */
function formatHideReport(report) {
  var s = 'moved ' + report.moved + ' · already in bin ' + report.already + ' · failed ' + report.failed;
  if (report.skipped) s += ' · skipped ' + report.skipped;
  if (report.stopped) s += ' — stopped: ' + report.stopped;
  return s;
}

module.exports = {
  SOURCE_TIMELINES_VERSION,
  SOURCE_TIMELINES_BIN,
  sceneSequenceRegex,
  isSceneSequenceName,
  selectSceneSequences,
  fileBuiltSceneSequences,
  hideSourceTimelines,
  formatHideReport
};
