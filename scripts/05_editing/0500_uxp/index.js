/**
 * YTAI Assembly — UXP Plugin for Adobe Premiere Pro
 *
 * Four pipelines in one panel:
 *   INGEST:      loads ingest.json → imports clips, builds Ingest sequence
 *   ASSEMBLY:    loads pre_edit_brief.json → builds Assembly sequence from existing clips
 *   REVIEW:      builds Review sequence from unused segments
 *   PRE-EDIT:    creates _4_PreEdit sequence (V1 Assembly copy + V2 PNG overlays + markers + SRT)
 *
 * INGEST, ASSEMBLY, REVIEW, and SCREEN CUES modules do NOT import each other.
 * The only connection is the 00_Source bin (created by INGEST, read by others).
 * Screen Cues is independent — creates its own sequence, does NOT need Assembly.
 */

const ppro = require('premierepro');
const uxp = require('uxp');
const uxpfs = uxp.storage.localFileSystem;

// --- Module imports: SHARED ---
const { Logger } = require('./src/shared/logger');
const { fmtTime, escapeHtml, tickSec } = require('./src/shared/utils');

// --- Module imports: INGEST ---
const { parseIngest, generateSummary } = require('./src/ingest/ingestLoader');
const { createBinStructure, BIN_NAMES } = require('./src/ingest/binManager');
const { buildIngestSequence, buildMultiSceneIngest, findProjectItemByName } = require('./src/ingest/timelineBuilder');
const { importTranscripts } = require('./src/ingest/transcriptImporter');
const { copyLutsToCreativeFolder, applyLumetriToClips } = require('./src/ingest/lutManager');

// --- Module imports: ASSEMBLY ---
const { parseBrief } = require('./src/assembly/briefParser');
const { validateIngestState } = require('./src/assembly/projectScanner');
const { buildAssemblySequence, ASSEMBLY_BUILDER_VERSION } = require('./src/assembly/assemblyBuilder');

// --- Module imports: REVIEW ---
const { buildReviewSequence, getReviewCategory } = require('./src/review/reviewBuilder');

// --- Module imports: SCREENS ---
const { parseScreens } = require('./src/screens/screenParser');
const { buildScreenCues, SCREEN_CUES_BIN_NAME, generateTranscriptSrt, generateCaptionsSrt, buildSegmentPositionMap, getScreenTimelinePosition } = require('./src/screens/screenBuilder');

// --- Module imports: ARCHIVER ---
const { versionTimestamp, ensureSubfolder, archiveFiles, saveVersion, saveState, loadState, loadLatestVersion, ensureVersionsDir } = require('./src/shared/archiver');

// --- Utility: extract short project code (YTCG49) from full name ---
function extractProjectCode(name) {
  if (!name) return 'unknown';
  var match = name.match(/^(YT[A-Z]{2,4}\d+)_/);
  return match ? match[1] : name;
}

// --- State (separate for INGEST and ASSEMBLY) ---
let ingestState = { data: null, filePath: null, building: false };
let assemblyState = { data: null, segments: [], blocks: [], screens: [], projectName: '', filePath: null, building: false, clipMap: null };

// --- State: PROJECT (folder-level project selection with auto-detection) ---
let projectState = {
  folderPath: null,      // native path to project folder
  projectName: null,     // folder name = project name
  ingestPath: null,      // resolved path to _ingest.json (null if not found)
  briefPath: null,       // resolved path to _pre_edit_brief.json (null if not found)
  ingestDetected: false,
  briefDetected: false
};

// --- Separate loggers per pipeline ---
const ingestLogger = new Logger('INGEST');
const assemblyLogger = new Logger('ASSEMBLY');
const reviewLogger = new Logger('REVIEW');
const screensLogger = new Logger('SCREENS');

// --- UI Helpers ---

function $(id) { return document.querySelector('#' + id); }

function appendToPanel(panelId, entry, level, message) {
  const panel = $(panelId);
  if (!panel) return;

  // Detect special log patterns for enhanced styling
  var msg = message || entry;
  var cls;
  if (msg.indexOf('=== ') === 0 && msg.indexOf('BUILD START') !== -1) {
    cls = 'log-header-line';
  } else if (msg.indexOf('=== ') === 0 && msg.indexOf('BUILD COMPLETE') !== -1) {
    cls = 'log-header-line';
  } else if (msg.indexOf('=== ') === 0 && msg.indexOf('COMPLETE') !== -1) {
    cls = 'log-header-line';
  } else if (msg.indexOf('=== Step ') === 0 || msg.indexOf('=== Post-build') === 0) {
    cls = 'log-step';
  } else if (msg.indexOf('Timing:') === 0) {
    cls = 'log-timing';
  } else if (msg.indexOf('Result:') === 0 || msg.indexOf('Summary:') === 0 || msg.indexOf('Assembly:') === 0 || msg.indexOf('Review:') === 0) {
    cls = 'log-result';
  } else {
    cls = level === 'ERROR' ? 'log-error'
      : level === 'WARN' ? 'log-warn'
      : level === 'DEBUG' ? 'log-debug'
      : 'log-info';
  }

  panel.innerHTML += '<span class="' + cls + '">' + escapeHtml(entry) + '</span>\n';
  panel.scrollTop = panel.scrollHeight;
}

ingestLogger.onLog = (entry, level, message) => { appendToPanel('ingest-log-panel', entry, level, message); };
assemblyLogger.onLog = (entry, level, message) => { appendToPanel('assembly-log-panel', entry, level, message); };
reviewLogger.onLog = (entry, level, message) => { appendToPanel('review-log-panel', entry, level, message); };
screensLogger.onLog = (entry, level, message) => { appendToPanel('screens-log-panel', entry, level, message); };

// --- INGEST UI helpers ---

function setIngestStatus(text, type) {
  $('ingest-status-dot').className = 'status-dot ' + (type || 'waiting');
  $('ingest-status-text').textContent = text;
}

function setIngestProgress(percent, text) {
  $('ingest-progress-bar').style.display = 'block';
  $('ingest-progress-text').style.display = 'block';
  $('ingest-progress-fill').style.width = percent + '%';
  $('ingest-progress-text').textContent = text || '';
}

function hideIngestProgress() {
  $('ingest-progress-bar').style.display = 'none';
  $('ingest-progress-text').style.display = 'none';
}

// --- ASSEMBLY UI helpers ---

function setAssemblyStatus(text, type) {
  $('assembly-status-dot').className = 'status-dot ' + (type || 'waiting');
  $('assembly-status-text').textContent = text;
}

function setAssemblyProgress(percent, text) {
  $('assembly-progress-bar').style.display = 'block';
  $('assembly-progress-text').style.display = 'block';
  $('assembly-progress-fill').style.width = percent + '%';
  $('assembly-progress-text').textContent = text || '';
}

function hideAssemblyProgress() {
  $('assembly-progress-bar').style.display = 'none';
  $('assembly-progress-text').style.display = 'none';
}

// --- SCREEN CUES UI helpers ---

function setScreensStatus(text, type) {
  $('screens-status-dot').className = 'status-dot ' + (type || 'waiting');
  $('screens-status-text').textContent = text;
}

function setScreensProgress(percent, text) {
  $('screens-progress-bar').style.display = 'block';
  $('screens-progress-text').style.display = 'block';
  $('screens-progress-fill').style.width = percent + '%';
  $('screens-progress-text').textContent = text || '';
}

function hideScreensProgress() {
  $('screens-progress-bar').style.display = 'none';
  $('screens-progress-text').style.display = 'none';
}

// --- PROJECT UI helpers ---

function setProjectStatus(text, type) {
  $('project-status-dot').className = 'status-dot ' + (type || 'waiting');
  $('project-status-text').textContent = text;
}

function showFallback(section) {
  var row = $(section + '-fallback-row');
  if (row) row.style.display = 'flex';
}

function hideAllFallbackButtons() {
  var ingestRow = $('ingest-fallback-row');
  var assemblyRow = $('assembly-fallback-row');
  if (ingestRow) ingestRow.style.display = 'none';
  if (assemblyRow) assemblyRow.style.display = 'none';
}

function resetAllPipelineStates() {
  // Reset state objects
  ingestState = { data: null, filePath: null, building: false };
  assemblyState = { data: null, segments: [], blocks: [], screens: [], projectName: '', filePath: null, building: false, clipMap: null };

  // Reset INGEST UI
  setIngestStatus('Detecting files...', 'waiting');
  $('ingest-summary').style.display = 'none';
  $('ingest-file-info').textContent = '';
  $('btn-build-ingest').setAttribute('disabled', 'true');
  $('btn-import-srts').setAttribute('disabled', 'true');
  $('btn-export-markers').setAttribute('disabled', 'true');
  $('btn-debug-export').setAttribute('disabled', 'true');
  $('ingest-validation').style.display = 'none';
  hideIngestProgress();

  // Reset ASSEMBLY UI
  setAssemblyStatus('Detecting files...', 'waiting');
  $('assembly-summary').style.display = 'none';
  $('assembly-file-info').textContent = '';
  $('btn-build-assembly').setAttribute('disabled', 'true');
  $('assembly-validation').style.display = 'none';
  hideAssemblyProgress();

  // Reset REVIEW UI
  setReviewStatus('Detecting files...', 'waiting');
  $('btn-build-review').setAttribute('disabled', 'true');
  $('review-validation').style.display = 'none';
  hideReviewProgress();

  // Reset SCREEN CUES UI
  setScreensStatus('Detecting files...', 'waiting');
  $('btn-generate-pngs').setAttribute('disabled', 'true');
  $('btn-build-screens').setAttribute('disabled', 'true');
  $('btn-export-screens').setAttribute('disabled', 'true');
  $('btn-import-screens').setAttribute('disabled', 'true');
  $('screens-validation').style.display = 'none';
  hideScreensProgress();

  // Hide all fallback buttons
  hideAllFallbackButtons();
}

// --- Log path helpers ---

function updateLogPath(pipeline, path) {
  var el = $(pipeline + '-log-path');
  if (el) { el.textContent = path || ''; el.title = path || ''; }
}

async function copyProjectPrompt() {
  if (!projectState.folderPath || !projectState.projectName) return;
  var code = extractProjectCode(projectState.projectName);
  var channel = code.replace(/\d+$/, '');  // YTRF02 → YTRF
  var path = projectState.folderPath;

  // Determine next version: scan Assembly/ for latest _in.json version
  var nextVer = 1;
  try {
    var assemblyDir = path + '/01_Media/Source/Setup/Assembly';
    var assemblyEntry = await uxpfs.getEntryWithUrl('file://' + assemblyDir);
    var files = await assemblyEntry.getEntries();
    var inRe = new RegExp('^' + code + '_Assembly_v(\\d+)_in\\.json$');
    for (var i = 0; i < files.length; i++) {
      var m = files[i].name.match(inRe);
      if (m) {
        var v = parseInt(m[1], 10);
        if (v >= nextVer) nextVer = v + 1;
      }
    }
  } catch (e) { /* Assembly/ not found, v1 */ }

  var prompt = 'Create Assembly brief:\n'
    + '- Channel: ' + channel + '\n'
    + '- Project: ' + path + '\n'
    + '\n'
    + 'Resolve from project structure:\n'
    + '- Knowledge base: ~/YTAI/scripts/05_editing/0501_brief/ (INSTRUCTIONS.md, editing_rules.md, output_format.md)\n'
    + '- Channel profile: ~/YTAI/YTs/' + channel + '.md\n'
    + '- Transcript: ' + path + '/01_Media/Source/Setup/' + code + '_Claude4_assembly.json\n'
    + '- Output JSON: ' + path + '/01_Media/Source/Setup/Assembly/' + code + '_Assembly_v' + nextVer + '_in.json\n'
    + '- Output HTML: ' + path + '/01_Media/Source/Setup/Assembly/' + code + '_review_v' + nextVer + '.html';

  try { await navigator.clipboard.writeText(prompt); } catch (err) { /* ignore */ }
}

async function copyMarkersPrompt() {
  if (!projectState.folderPath || !projectState.projectName) return;
  var code = extractProjectCode(projectState.projectName);
  var channel = code.replace(/\d+$/, '');
  var path = projectState.folderPath;
  var assemblyDir = path + '/01_Media/Source/Setup/Assembly';

  // Scan Assembly/ for latest _out.json and latest _in.json
  var latestOut = 0, latestIn = 0, latestOutName = null;
  var outRe = new RegExp('^' + code + '_.*v(\\d+)_out\\.json$');
  var inRe = new RegExp('^' + code + '_Assembly_v(\\d+)_in\\.json$');
  try {
    var assemblyEntry = await uxpfs.getEntryWithUrl('file://' + assemblyDir);
    var files = await assemblyEntry.getEntries();
    for (var i = 0; i < files.length; i++) {
      var mo = files[i].name.match(outRe);
      if (mo) { var vo = parseInt(mo[1], 10); if (vo > latestOut) { latestOut = vo; latestOutName = files[i].name; } }
      var mi = files[i].name.match(inRe);
      if (mi) { var vi = parseInt(mi[1], 10); if (vi > latestIn) latestIn = vi; }
    }
  } catch (e) { /* Assembly/ not found */ }

  var nextVer = Math.max(latestOut, latestIn) + 1;
  var markersFile = latestOutName
    ? assemblyDir + '/' + latestOutName
    : assemblyDir + '/' + code + '_Assembly_v1_out.json';
  var outJson = assemblyDir + '/' + code + '_Assembly_v' + nextVer + '_in.json';
  var outHtml = assemblyDir + '/' + code + '_review_v' + nextVer + '.html';

  var prompt = 'Update Assembly brief from editor markers:\n'
    + '- Markers: ' + markersFile + '\n'
    + '\n'
    + 'Step 1 — Analyze: Read the markers file. Parse editor comments from markers. Compare with the previous brief. Present a table of all planned changes (segment ID, change type, what was requested, what you will do). Wait for my confirmation before proceeding.\n'
    + '\n'
    + 'Step 2 — Execute: Apply the changes. Write two files:\n'
    + '- Output JSON: ' + outJson + '\n'
    + '- Output HTML (diff view): ' + outHtml + '\n'
    + '\n'
    + 'HTML must be a two-column diff grouped by chapter:\n'
    + '- LEFT column ("Before"): segment text + editor comments (highlighted yellow)\n'
    + '- RIGHT column ("After"): corrected text + change tags (CHANGED / REMOVED / MOVED / NEW)\n'
    + '- Row highlighting: white=unchanged, yellow+green=modified, red+strikethrough=removed, blue=moved, green=new\n'
    + '- Semantic blocks must be preserved\n'
    + '\n'
    + 'Resolve from project structure:\n'
    + '- Knowledge base: ~/YTAI/scripts/05_editing/0501_brief/ (INSTRUCTIONS.md, editing_rules.md, output_format.md)\n'
    + '- Channel profile: ~/YTAI/YTs/' + channel + '.md\n'
    + '- Previous brief: auto-detect latest _in.json in Assembly/';

  try { await navigator.clipboard.writeText(prompt); } catch (err) { /* ignore */ }
}

async function copyLogPath(pipeline) {
  try {
    var el = $(pipeline + '-log-path');
    var path = el ? el.textContent : '';
    if (!path) {
      var pluginFolder = await uxpfs.getPluginFolder();
      path = pluginFolder.nativePath + 'logs';
    }
    await navigator.clipboard.writeText(path);
  } catch (err) { /* ignore clipboard errors */ }
}


// ══════════════════════════════════════════════════════════════════
//  PROJECT SELECTION & AUTO-DETECTION
// ══════════════════════════════════════════════════════════════════

/**
 * Select project folder and auto-detect pipeline input files.
 *
 * Convention:
 *   {PROJECT_NAME}/01_Media/Source/{PROJECT_NAME}_ingest.json
 *   {PROJECT_NAME}/01_Media/Source/Setup/{CODE}_pre_edit_brief.json
 */
async function selectProjectFolder() {
  try {
    ingestLogger.info('Opening folder picker for project selection...');

    var folder = await uxpfs.getFolder();
    if (!folder) {
      ingestLogger.warn('Folder selection cancelled');
      return;
    }

    var folderPath = folder.nativePath;
    // Remove trailing slash for consistency
    if (folderPath.endsWith('/')) folderPath = folderPath.slice(0, -1);
    var projectName = folder.name;

    // Update project state
    projectState.folderPath = folderPath;
    projectState.projectName = projectName;
    projectState.ingestPath = null;
    projectState.briefPath = null;
    projectState.ingestDetected = false;
    projectState.briefDetected = false;

    // Update UI
    setProjectStatus('Project: ' + projectName, 'ready');
    $('btn-copy-project-prompt').removeAttribute('disabled');
    $('project-path-info').textContent = folderPath;
    $('project-checklist').innerHTML = '';
    $('project-actions-row').style.display = 'none';

    ingestLogger.info('Project folder selected: ' + projectName);
    ingestLogger.info('Path: ' + folderPath);

    // Reset all pipeline states before re-detecting
    resetAllPipelineStates();

    // Run auto-detection
    await autoDetectFiles(folderPath, projectName);

  } catch (err) {
    ingestLogger.error('Project selection failed: ' + err.message);
    setProjectStatus('Selection failed: ' + err.message, 'error');
  }
}

/**
 * Auto-detect ingest.json and pre_edit_brief.json from the known folder structure.
 * Tries CODE-based filenames first (e.g. YTCG37_ingest.json), then full-name legacy fallback.
 * Calls existing loadIngestFromPath() / loadBriefFromPath() on success.
 * Shows fallback load buttons on failure.
 */
async function autoDetectFiles(folderPath, projectName) {
  var checklistHtml = '';
  hideAllFallbackButtons();

  var code = extractProjectCode(projectName);

  // --- Ingest --- (try CODE-based first, then legacy full-name)
  var ingestCandidates = [
    folderPath + '/01_Media/Source/Setup/' + code + '_ingest.json',
    folderPath + '/01_Media/Source/Setup/' + projectName + '_ingest.json',  // legacy
    folderPath + '/01_Media/Source/' + projectName + '_ingest.json',        // legacy
  ];
  var ingestFound = false;
  for (var i = 0; i < ingestCandidates.length; i++) {
    try {
      await uxpfs.getEntryWithUrl('file://' + ingestCandidates[i]);
      projectState.ingestPath = ingestCandidates[i];
      projectState.ingestDetected = true;
      ingestFound = true;
      checklistHtml += checkItem(true, code + '_ingest.json');
      ingestLogger.info('Auto-detected ingest: ' + ingestCandidates[i]);
      await loadIngestFromPath(ingestCandidates[i]);
      break;
    } catch (e) {
      // Try next candidate
    }
  }
  if (!ingestFound) {
    projectState.ingestDetected = false;
    checklistHtml += checkItem(false, code + '_ingest.json',
      'Expected: 01_Media/Source/Setup/' + code + '_ingest.json');
    ingestLogger.warn('Ingest not found at: ' + ingestCandidates.join(', '));
    setIngestStatus('Ingest JSON not found. Load manually.', 'waiting');
    showFallback('ingest');
  }

  // --- Brief --- (search order: Assembly/ → Setup/ legacy)
  var briefFound = false;
  var inRe = new RegExp('^' + code + '_Assembly_v(\\d+)_in\\.json$');

  // Scan Assembly/ folder for latest _in.json by version number
  var assemblyDir = folderPath + '/01_Media/Source/Setup/Assembly';
  try {
    var assemblyEntry = await uxpfs.getEntryWithUrl('file://' + assemblyDir);
    var assemblyFiles = await assemblyEntry.getEntries();
    var latestVer = 0;
    var latestName = null;
    for (var ai = 0; ai < assemblyFiles.length; ai++) {
      var m = assemblyFiles[ai].name.match(inRe);
      if (m) {
        var ver = parseInt(m[1], 10);
        if (ver > latestVer) {
          latestVer = ver;
          latestName = assemblyFiles[ai].name;
        }
      }
    }
    if (latestName) {
      var latestPath = assemblyDir + '/' + latestName;
      projectState.briefPath = latestPath;
      projectState.briefDetected = true;
      briefFound = true;
      checklistHtml += checkItem(true, latestName + ' (v' + latestVer + ')');
      assemblyLogger.info('Auto-detected brief from Assembly/: ' + latestName);
      await loadBriefFromPath(latestPath);
    }
  } catch (e) {
    // Assembly/ folder not found — try legacy paths
  }

  // 3. Fallback: try legacy pre_edit_brief paths in Setup/
  if (!briefFound) {
    var briefCandidates = [
      folderPath + '/01_Media/Source/Setup/' + code + '_pre_edit_brief.json',
      folderPath + '/01_Media/Source/Setup/' + projectName + '_pre_edit_brief.json',  // legacy
      folderPath + '/01_Media/Source/Setup/' + projectName + '_edit_brief.json',       // legacy
    ];
    for (var bi = 0; bi < briefCandidates.length; bi++) {
      try {
        await uxpfs.getEntryWithUrl('file://' + briefCandidates[bi]);
        projectState.briefPath = briefCandidates[bi];
        projectState.briefDetected = true;
        briefFound = true;
        checklistHtml += checkItem(true, code + '_pre_edit_brief.json');
        assemblyLogger.info('Auto-detected brief: ' + briefCandidates[bi]);
        await loadBriefFromPath(briefCandidates[bi]);
        break;
      } catch (e) {
        // Try next candidate
      }
    }
  }

  if (!briefFound) {
    projectState.briefDetected = false;
    checklistHtml += checkItem(false, code + '_Assembly_v*_in.json',
      'Not found in Assembly/, ~/Downloads/, or Setup/');
    assemblyLogger.warn('No brief found in Assembly/, ~/Downloads/, or Setup/');
    setAssemblyStatus('Pre-edit brief not found. Load manually.', 'waiting');
    setReviewStatus('Pre-edit brief not found.', 'waiting');
    setScreensStatus('Pre-edit brief not found.', 'waiting');
    showFallback('assembly');
  }

  // Check for saved Pre-Edit state (enable Reload Last button)
  try {
    var setupDir = folderPath + '/01_Media/Source/Setup';
    var versionsDir = setupDir + '/pre-edit_versions';
    var savedState = await loadState(versionsDir, screensLogger);
    if (savedState && savedState.briefPath) {
      screensLogger.info('Saved state found (from ' + (savedState.timestamp || 'unknown') + ')');
    }
  } catch (e) {
    // No saved state — that's fine
  }

  $('project-checklist').innerHTML = checklistHtml;
  $('project-actions-row').style.display = 'flex';
  $('btn-import-srts').removeAttribute('disabled');
  $('btn-export-markers').removeAttribute('disabled');
  $('btn-debug-export').removeAttribute('disabled');
  ingestLogger.info('Auto-detection complete: ingest=' + projectState.ingestDetected + ', brief=' + projectState.briefDetected);
}

/**
 * Build a single checklist HTML row.
 * @param {boolean} ok    - true = found (green), false = missing (red)
 * @param {string}  label - filename to display
 * @param {string}  [hint] - expected path hint (only shown when !ok)
 */
function checkItem(ok, label, hint) {
  var icon = ok
    ? '<span class="checklist-icon ok">&#9679;</span>'
    : '<span class="checklist-icon miss">&#9679;</span>';
  var html = '<div class="checklist-item">' + icon + ' ' + escapeHtml(label) + '</div>';
  if (!ok && hint) {
    html += '<div class="checklist-hint">' + escapeHtml(hint) + '</div>';
  }
  return html;
}

/**
 * Re-run auto-detection on the already-selected project folder.
 * Use after placing missing files in the expected locations.
 */
async function refreshProject() {
  if (!projectState.folderPath || !projectState.projectName) return;
  ingestLogger.info('Refreshing project detection...');
  resetAllPipelineStates();
  $('project-checklist').innerHTML = '';
  await autoDetectFiles(projectState.folderPath, projectState.projectName);
}


// ══════════════════════════════════════════════════════════════════
//  INGEST PIPELINE
// ══════════════════════════════════════════════════════════════════

async function loadIngestFromPath(filePath) {
  ingestLogger.info('Loading ingest from path: ' + filePath);
  const fileEntry = await uxpfs.getEntryWithUrl('file://' + filePath);
  const contents = await fileEntry.read();
  const ingest = parseIngest(contents);
  ingest.project_code = extractProjectCode(ingest.project_name);

  ingestState.data = ingest;
  ingestState.filePath = filePath;
  ingestLogger.setIngestInfo(filePath, ingest.source_folder || '(not set)');

  $('ingest-summary').textContent = generateSummary(ingest);
  $('ingest-summary').style.display = 'block';
  $('ingest-file-info').textContent = 'File: ' + filePath;
  $('btn-build-ingest').removeAttribute('disabled');

  ingestLogger.info('Ingest loaded: ' + ingest.clips.length + ' clips, project "' + ingest.project_name + '" (code: ' + ingest.project_code + ')');

  // Check if sequences already exist in the Premiere project
  var existingSeqs = await detectExistingSequences(ingest);
  if (existingSeqs.length > 0) {
    setIngestStatus('Sequences built (' + existingSeqs.length + '). Rebuild if needed.', 'ready');
    $('btn-build-ingest').textContent = 'Rebuild Ingest';
    ingestLogger.info('Found ' + existingSeqs.length + ' existing sequence(s): ' + existingSeqs.join(', '));
  } else {
    setIngestStatus('Ingest loaded. Ready to build.', 'ready');
  }
}

/**
 * Check if ingest sequences already exist in the active Premiere project.
 * Multi-scene: looks for {code}_{sceneName} per scene.
 * Single: looks for {code}_1_Ingest.
 * @returns {string[]} names of existing sequences
 */
async function detectExistingSequences(ingest) {
  var found = [];
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) return found;

    var rootItem = await project.getRootItem();
    var allItems = await rootItem.getItems();
    var code = ingest.project_code || extractProjectCode(ingest.project_name);
    var hasScenes = ingest.clips.some(function(c) { return c.scene; });

    // Build set of expected sequence names
    var expected = {};
    if (hasScenes) {
      var scenes = {};
      ingest.clips.forEach(function(c) { if (c.scene) scenes[c.scene] = true; });
      Object.keys(scenes).forEach(function(s) { expected[code + '_' + s] = true; });
    } else {
      expected[code + '_1_Ingest'] = true;
    }

    for (var i = 0; i < allItems.length; i++) {
      if (expected[allItems[i].name]) {
        found.push(allItems[i].name);
      }
    }
  } catch (e) {
    ingestLogger.debug('Sequence detection failed: ' + e.message);
  }
  return found;
}

async function loadIngest() {
  try {
    ingestLogger.info('Opening file picker for ingest JSON...');
    const file = await uxpfs.getFileForOpening({ types: ['json'], allowMultiple: false });
    if (!file) { ingestLogger.warn('File selection cancelled'); return; }

    const contents = await file.read();
    const ingest = parseIngest(contents);
    ingest.project_code = extractProjectCode(ingest.project_name);

    ingestState.data = ingest;
    ingestState.filePath = file.nativePath || file.name || 'unknown';
    ingestLogger.setIngestInfo(ingestState.filePath, ingest.source_folder || '(not set)');

    $('ingest-summary').textContent = generateSummary(ingest);
    $('ingest-summary').style.display = 'block';
    $('ingest-file-info').textContent = 'File: ' + ingestState.filePath;
    $('btn-build-ingest').removeAttribute('disabled');

    setIngestStatus('Ingest loaded. Ready to build.', 'ready');
    ingestLogger.info('Ingest loaded: ' + ingest.clips.length + ' clips, project "' + ingest.project_name + '" (code: ' + ingest.project_code + ')');
  } catch (err) {
    ingestLogger.error('Failed to load ingest: ' + err.message);
    setIngestStatus('Error: ' + err.message, 'error');
  }
}

async function cleanBeforeBuild(project, ingest) {
  var shortCode = ingest.project_code || extractProjectCode(ingest.project_name);
  var sequenceNameShort = shortCode + '_1_Ingest';
  var sequenceNameFull = ingest.project_name + '_1_Ingest';
  ingestLogger.info('=== Clean before build ===');

  const rootItem = await project.getRootItem();
  const allItems = await rootItem.getItems();

  for (const item of allItems) {
    if ((item.name === sequenceNameShort || item.name === sequenceNameFull) && item.type !== 2) {
      try { await project.deleteSequence(item); ingestLogger.info('Deleted old sequence: "' + item.name + '"'); }
      catch (e) { ingestLogger.debug('Cannot delete sequence: ' + e.message); }
    }
    try {
      const folder = ppro.FolderItem.cast(item);
      if (folder && [BIN_NAMES.SOURCE, BIN_NAMES.TRANSCRIPTS].includes(item.name)) {
        const children = await folder.getItems();
        for (const child of children) {
          try {
            project.lockedAccess(() => {
              project.executeTransaction((ca) => {
                ca.addAction(folder.createRemoveItemAction(child));
              }, 'Remove ' + child.name);
            });
          } catch (e) { }
        }
      }
    } catch (e) { }
  }
  ingestLogger.info('Clean complete');
}

async function buildIngest() {
  if (!ingestState.data) { ingestLogger.error('No ingest loaded'); return; }
  if (ingestState.building) { ingestLogger.warn('Build already in progress'); return; }

  ingestState.building = true;
  $('btn-build-ingest').setAttribute('disabled', 'true');
  $('ingest-validation').style.display = 'none';
  setIngestStatus('Building timeline...', 'waiting');

  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');
    ingestLogger.setProjectInfo(project.name, project.path);

    const ingest = ingestState.data;
    const totalSteps = 6;
    let step = 0;
    const startTime = Date.now();

    ingestLogger.info('=== INGEST BUILD START ===');
    ingestLogger.info('Project: ' + project.name);
    ingestLogger.info('Clips: ' + ingest.clips.length + ', Resolution: ' + ingest.media.width + 'x' + ingest.media.height);

    var stepTimings = [];
    var stepStart;

    // Step 1: Clean
    step++;
    stepStart = Date.now();
    setIngestProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Cleaning...');
    await cleanBeforeBuild(project, ingest);
    stepTimings.push('clean ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 2: Create bins
    step++;
    stepStart = Date.now();
    setIngestProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Creating bins...');
    ingestLogger.info('=== Step 2: Creating bin structure ===');
    const bins = await createBinStructure(project, ingestLogger);
    stepTimings.push('bins ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 3: Import media + build sequence
    step++;
    stepStart = Date.now();
    setIngestProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Building sequence...');
    ingestLogger.info('=== Step 3: Importing media & building sequence ===');
    // Detect multi-scene mode: if any clip has a "scene" field
    const hasScenes = ingest.clips.some(c => c.scene);
    let result;
    if (hasScenes) {
      ingestLogger.info('Multi-scene mode detected — building per-scene sequences');
      const multiResult = await buildMultiSceneIngest(project, ingest, bins[BIN_NAMES.SOURCE] || null, ingestLogger);
      // Wrap multi-result to be compatible with downstream code
      result = {
        sequence: multiResult.sequences.length > 0 ? multiResult.sequences[0].sequence : null,
        sequences: multiResult.sequences,
        clipCount: multiResult.totalClipCount,
        djiCount: multiResult.totalDjiCount,
        totalDuration: multiResult.sequences.reduce((s, r) => s + r.totalDuration, 0),
      };
    } else {
      result = await buildIngestSequence(project, ingest, bins[BIN_NAMES.SOURCE] || null, null, ingestLogger);
    }
    stepTimings.push('build ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 4: Import transcripts
    step++;
    stepStart = Date.now();
    setIngestProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Importing transcripts...');
    ingestLogger.info('=== Step 4: Importing transcripts ===');
    const trResult = await importTranscripts(project, ingest, bins[BIN_NAMES.TRANSCRIPTS] || null, ingestLogger, result.sequence || null, ingest.project_code);
    stepTimings.push('transcripts ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 5: LUTs
    step++;
    stepStart = Date.now();
    setIngestProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Applying LUTs...');
    ingestLogger.info('=== Step 5: Copy LUTs & apply Lumetri ===');
    let lumetriApplied = 0;
    try {
      await copyLutsToCreativeFolder(ingest, ingestLogger);
      if (result.sequence) lumetriApplied = await applyLumetriToClips(project, result.sequence, ingestLogger);
    } catch (lutErr) { ingestLogger.warn('LUT step failed: ' + lutErr.message); }
    stepTimings.push('luts ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 6: Activate + save
    step++;
    stepStart = Date.now();
    setIngestProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Activating sequence...');
    if (result.sequence) {
      await project.setActiveSequence(result.sequence);
      try { await project.openSequence(result.sequence.guid || result.sequence); } catch (e) { }
    }
    stepTimings.push('activate ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    setIngestProgress(100, 'Complete!');
    ingestLogger.info('=== INGEST BUILD COMPLETE (' + elapsed + 's) ===');
    ingestLogger.info('Timing: ' + stepTimings.join(' | '));
    ingestLogger.info('Summary: ' + result.clipCount + ' clips, ' + trResult.transcriptsImported + ' transcripts');
    $('btn-build-ingest').classList.add('btn-done');

    // Post-build validation
    if (result.sequence) {
      await validateIngestBuild(result.sequence, ingest, {
        transcriptsImported: trResult.transcriptsImported,
        srtImported: trResult.srtImported,
        clipCount: result.clipCount,
        seqSettings: result.seqSettings,
        lumetriApplied,
        djiCount: result.djiCount || 0
      });
    }

    // Save logs + project
    await saveIngestLogs(project);
    setIngestStatus('Build verified', 'ready');

  } catch (err) {
    ingestLogger.error('INGEST BUILD FAILED: ' + err.message);
    if (err.stack) ingestLogger.debug(err.stack);
    setIngestStatus('Build failed: ' + err.message, 'error');
    try { await saveIngestLogs(await ppro.Project.getActiveProject()); } catch (e) { }
  }

  ingestState.building = false;
  $('btn-build-ingest').removeAttribute('disabled');
}

async function validateIngestBuild(sequence, ingest, br) {
  ingestLogger.info('=== Post-build validation ===');
  const panel = $('ingest-validation');
  const lines = [];
  let allOk = true;

  function ok(text) { lines.push('<div class="val-line"><span style="color:var(--success)">\u25CF</span> ' + escapeHtml(text) + '</div>'); }
  function warn(text) { lines.push('<div class="val-line"><span style="color:var(--warning)">\u25CF</span> ' + escapeHtml(text) + '</div>'); allOk = false; }

  // For multi-scene: br.clipCount = total placed across all sequences
  const expectedCount = br.clipCount || ingest.clips.length;

  // V1 clip count — for multi-scene uses totalClipCount
  try {
    const v1 = await sequence.getVideoTrack(0);
    const items = await v1.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
    if (items.length >= expectedCount) ok('V1: ' + expectedCount + '/' + ingest.clips.length + ' clips');
    else if (br.clipCount && br.clipCount >= ingest.clips.length) ok('V1: ' + br.clipCount + ' clips (multi-scene)');
    else warn('V1: ' + items.length + '/' + expectedCount + ' clips');
  } catch (e) { warn('V1: check failed'); }

  // Resolution
  if (br.seqSettings) {
    const m = ingest.media;
    if (br.seqSettings.width === m.width && br.seqSettings.height === m.height)
      ok('Resolution: ' + m.width + 'x' + m.height);
    else warn('Resolution mismatch');
  }

  // Transcripts
  if ((br.transcriptsImported || 0) === expectedCount) ok('Transcripts: ' + br.transcriptsImported + '/' + expectedCount);
  else warn('Transcripts: ' + (br.transcriptsImported || 0) + '/' + expectedCount);

  // Lumetri
  if (br.lumetriApplied > 0) ok('Lumetri: ' + br.lumetriApplied + ' clip(s)');
  else warn('Lumetri: not applied');

  // DJI audio
  if (br.djiCount > 0) ok('DJI audio: ' + br.djiCount + ' file(s) on A2/A3');

  panel.innerHTML = lines.join('');
  panel.style.display = 'block';
  ingestLogger.info('Validation ' + (allOk ? 'PASSED' : 'has WARNINGS'));
}

async function saveIngestLogs(project) {
  try {
    if (project) { try { await project.save(); ingestLogger.info('Project saved'); } catch (e) { } }

    const sourceFolder = ingestState.data && ingestState.data.source_folder;
    const projectName = ingestState.data && ingestState.data.project_name;
    if (sourceFolder && projectName) {
      const transcriptionDir = sourceFolder + '/' + projectName + '_transcription';
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      try {
        const folder = await uxpfs.getEntryWithUrl('file://' + transcriptionDir);
        const logFile = await folder.createFile(projectName + '_INGEST_' + ts + '.log', { overwrite: true });
        await logFile.write(ingestLogger.getReport());
        ingestLogger.info('Log saved to: ' + transcriptionDir);
      } catch (e) { ingestLogger.warn('Cannot save to transcription folder: ' + e.message); }
    }

    await ingestLogger.saveDebugBundle(ingestState.data, project ? project.path : null);
    updateLogPath('ingest', ingestLogger.getLastSavedPath());
  } catch (err) {
    ingestLogger.error('Failed to save logs: ' + err.message);
  }
}


// ══════════════════════════════════════════════════════════════════
//  ASSEMBLY PIPELINE
// ══════════════════════════════════════════════════════════════════

async function loadBriefFromPath(filePath) {
  assemblyLogger.info('Loading brief from path: ' + filePath);
  const fileEntry = await uxpfs.getEntryWithUrl('file://' + filePath);
  const contents = await fileEntry.read();
  var result = loadBriefFromString(contents, filePath);

  // Check if Assembly/Review sequences already exist
  var code = result.projectCode || extractProjectCode(result.projectName);
  var existingStages = [];
  try {
    var project = await ppro.Project.getActiveProject();
    if (project) {
      var rootItem = await project.getRootItem();
      var allItems = await rootItem.getItems();
      var stageNames = {
        '_2_Assembly': 'Assembly',
        '_3_Review': 'Review',
        '_4_PreEdit': 'PreEdit',
      };
      for (var i = 0; i < allItems.length; i++) {
        for (var suffix in stageNames) {
          if (allItems[i].name === code + suffix) {
            existingStages.push(stageNames[suffix]);
          }
        }
      }
    }
  } catch (e) { assemblyLogger.debug('Stage sequence detection failed: ' + e.message); }

  if (existingStages.length > 0) {
    assemblyLogger.info('Found existing stage sequences: ' + existingStages.join(', '));
    if (existingStages.indexOf('Assembly') >= 0) {
      setAssemblyStatus('Assembly exists. Rebuild if needed.', 'ready');
      $('btn-build-assembly').textContent = 'Rebuild Assembly';
    }
    if (existingStages.indexOf('Review') >= 0) {
      setReviewStatus('Review exists. Rebuild if needed.', 'ready');
      $('btn-build-review').textContent = 'Rebuild Review';
    }
  }

  return result;
}

function loadBriefFromString(jsonString, filePath) {
  const result = parseBrief(jsonString);

  assemblyState.data = result;
  assemblyState.segments = result.segments;
  assemblyState.blocks = result.blocks;
  assemblyState.projectName = result.projectName;
  assemblyState.projectCode = result.projectCode || extractProjectCode(result.projectName);
  assemblyState.filePath = filePath;

  // Extract brief version from filename (e.g. YTCR01_Assembly_v17_in.json → 17)
  var vMatch = filePath && filePath.match(/_v(\d+)_in\.json$/);
  assemblyState.briefVersion = vMatch ? parseInt(vMatch[1], 10) : null;

  // Parse screens[] (Production Cues) — optional, backward compatible
  var rawData = JSON.parse(jsonString);
  if (rawData.screens && Array.isArray(rawData.screens)) {
    var screenResult = parseScreens(rawData.screens, result.segments, assemblyLogger);
    assemblyState.screens = screenResult.screens;
    if (screenResult.warnings.length > 0) {
      assemblyLogger.warn('Screen parsing warnings: ' + screenResult.warnings.join('; '));
    }
  } else {
    assemblyState.screens = [];
  }

  assemblyLogger.setBriefInfo(filePath, result.projectName);

  // Show stats
  const useSegs = result.segments.filter(s => s.use && s.block !== 99);
  const totalDur = result.segments.reduce((sum, s) => sum + s.duration, 0);
  const useDur = useSegs.reduce((sum, s) => sum + s.duration, 0);
  const screenCount = assemblyState.screens.length;

  $('assembly-summary').textContent = 'Project: ' + result.projectName +
    '\nSegments: ' + useSegs.length + '/' + result.segments.length +
    ' | Blocks: ' + result.blocks.filter(b => b.id !== 99).length +
    ' | Duration: ' + fmtTime(useDur) + ' / ' + fmtTime(totalDur) +
    (screenCount > 0 ? ' | Screens: ' + screenCount : '');
  $('assembly-summary').style.display = 'block';
  $('assembly-file-info').textContent = 'File: ' + (filePath || 'unknown');
  $('btn-build-assembly').removeAttribute('disabled');
  $('btn-build-review').removeAttribute('disabled');

  // Update review status when brief is loaded
  const reviewSegs = result.segments.filter(s => !s.use || s.block === 99);
  setReviewStatus('Brief loaded. ' + reviewSegs.length + ' unused segments.', 'ready');

  // Update Screen Cues status — enabled immediately (no Assembly dependency)
  if (assemblyState.screens.length > 0) {
    setScreensStatus(assemblyState.screens.length + ' screens detected. Ready to build.', 'ready');
    $('btn-generate-pngs').removeAttribute('disabled');
    $('btn-build-screens').removeAttribute('disabled');
    $('btn-export-screens').removeAttribute('disabled');
    $('btn-import-screens').removeAttribute('disabled');
  } else {
    setScreensStatus('No screens in brief', 'waiting');
    $('btn-generate-pngs').setAttribute('disabled', 'true');
    $('btn-build-screens').setAttribute('disabled', 'true');
    $('btn-export-screens').setAttribute('disabled', 'true');
    $('btn-import-screens').setAttribute('disabled', 'true');
  }

  setAssemblyStatus('Brief loaded. Ready to build.', 'ready');
  assemblyLogger.info('Brief loaded: ' + result.segments.length + ' segments, ' + result.blocks.length + ' blocks' +
    (screenCount > 0 ? ', ' + screenCount + ' screens' : ''));

  // Save brief_in version (fire-and-forget — this function is synchronous)
  if (filePath) {
    (async function () {
      try {
        var briefDir = filePath.replace(/[/\\][^/\\]+$/, '');
        var versionsDir = await ensureVersionsDir(briefDir, assemblyLogger);
        await saveVersion(jsonString, versionsDir, 'brief_in', 'json', assemblyLogger);
      } catch (vErr) {
        assemblyLogger.debug('Version save skipped: ' + vErr.message);
      }
    })();
  }

  return result;
}

async function loadBrief() {
  try {
    assemblyLogger.info('Opening file picker for pre-edit brief...');
    const file = await uxpfs.getFileForOpening({ types: ['json'], allowMultiple: false });
    if (!file) { assemblyLogger.warn('File selection cancelled'); return; }

    const contents = await file.read();
    var sourcePath = file.nativePath || file.name || 'unknown';

    // Auto-copy to Setup/Assembly/ with version
    if (projectState.folderPath) {
      try {
        var assemblyDir = projectState.folderPath + '/01_Media/Source/Setup/Assembly';
        var assemblyEntry;
        try {
          assemblyEntry = await uxpfs.getEntryWithUrl('file://' + assemblyDir);
        } catch (e) {
          var setupEntry = await uxpfs.getEntryWithUrl('file://' + projectState.folderPath + '/01_Media/Source/Setup');
          assemblyEntry = await ensureSubfolder(setupEntry, 'Assembly', assemblyLogger);
        }

        // Find next version (shared counter across _in and _out)
        var code = extractProjectCode(projectState.projectName);
        var existingFiles = await assemblyEntry.getEntries();
        var maxVer = 0;
        var verRe = new RegExp(code + '_Assembly_v(\\d+)');
        for (var fi = 0; fi < existingFiles.length; fi++) {
          var vm = existingFiles[fi].name.match(verRe);
          if (vm) {
            var vn = parseInt(vm[1], 10);
            if (vn > maxVer) maxVer = vn;
          }
        }
        var version = maxVer + 1;
        var versionedName = code + '_Assembly_v' + version + '_in.json';

        var outFile = await assemblyEntry.createFile(versionedName, { overwrite: true });
        await outFile.write(contents);
        var savedPath = assemblyDir + '/' + versionedName;
        assemblyLogger.info('Brief saved: Setup/Assembly/' + versionedName + ' (v' + version + ')');

        // Load from the saved location
        sourcePath = savedPath;
      } catch (copyErr) {
        assemblyLogger.debug('Brief copy to Assembly/ skipped: ' + copyErr.message);
      }
    }

    loadBriefFromString(contents, sourcePath);
  } catch (err) {
    assemblyLogger.error('Failed to load brief: ' + err.message);
    setAssemblyStatus('Error: ' + err.message, 'error');
  }
}

async function buildAssembly() {
  if (assemblyState.segments.length === 0) { assemblyLogger.error('No brief loaded'); return; }
  if (assemblyState.building) { assemblyLogger.warn('Assembly build already in progress'); return; }

  assemblyState.building = true;
  $('btn-build-assembly').setAttribute('disabled', 'true');
  setAssemblyStatus('Building assembly...', 'waiting');

  let clipMap = null;
  let result = null;

  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');
    assemblyLogger.setProjectInfo(project.name, project.path);

    const totalSteps = 6;
    let step = 0;
    const startTime = Date.now();

    assemblyLogger.info('=== ASSEMBLY BUILD START ===');
    assemblyLogger.info('Project: ' + assemblyState.projectName);

    var stepTimings = [];
    var stepStart;

    // Step 1: Save backup
    step++;
    stepStart = Date.now();
    setAssemblyProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Saving backup...');
    try { await project.save(); assemblyLogger.info('Project saved'); } catch (e) { }
    stepTimings.push('save ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 2: Scan project for clips
    step++;
    stepStart = Date.now();
    setAssemblyProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Scanning project clips...');
    assemblyLogger.info('=== Step 2: Scanning project for clips ===');
    const scanResult = await validateIngestState(project, assemblyState.segments, assemblyLogger);
    clipMap = scanResult.clipMap;
    assemblyState.clipMap = clipMap;  // save for Apply Colors button
    stepTimings.push('scan ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // NOTE: Colors are applied PER SEGMENT inside buildAssemblySequence,
    // right before each clip insertion. This allows the same source file
    // to have different colors in different blocks (e.g. C5403 = Green in
    // Hook, Blue in Government Vision). See assemblyBuilder.js.

    // Step 3: Build Assembly sequence (colors applied per-segment inside builder)
    step++;
    stepStart = Date.now();
    setAssemblyProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Building Assembly sequence...');
    assemblyLogger.info('=== Step 3: Building Assembly sequence ===');
    result = await buildAssemblySequence(project, clipMap, assemblyState.segments, assemblyState.projectCode || assemblyState.projectName, assemblyLogger, assemblyState.briefVersion, assemblyState.projectSettings);
    stepTimings.push('build ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 4: Create chapter markers (block boundaries + per-segment)
    step++;
    stepStart = Date.now();
    setAssemblyProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Markers...');
    assemblyLogger.info('=== Step 4: Markers ===');
    let markerInfo = null;
    try {
      markerInfo = await createAssemblyMarkers(project, result);
    } catch (markerErr) {
      assemblyLogger.warn('Markers step failed (non-fatal): ' + markerErr.message);
    }
    stepTimings.push('markers ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 5: Activate + save + validate
    step++;
    stepStart = Date.now();
    setAssemblyProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Validating...');
    if (result.sequence) {
      await project.setActiveSequence(result.sequence);
      try { await project.openSequence(result.sequence.guid || result.sequence); } catch (e) { }
    }
    try { await project.save(); } catch (e) { }

    // Post-build validation (green/yellow/red checklist)
    if (result.sequence) {
      await validateAssemblyBuild(result.sequence, result, markerInfo);
    }
    stepTimings.push('validate ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 6: Generate + import Assembly captions & transcript SRTs
    step++;
    stepStart = Date.now();
    setAssemblyProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Captions...');
    assemblyLogger.info('=== Step 6: Assembly Captions ===');

    var projectCode = assemblyState.projectCode || assemblyState.projectName;
    var useSegsForSrt = assemblyState.segments.filter(function (s) { return s.use && s.block !== 99; });

    if (useSegsForSrt.length > 0 && assemblyState.filePath) {
      var briefDir = assemblyState.filePath.replace(/[/\\][^/\\]+$/, '');
      var sourceDir = briefDir.replace(/[/\\]Setup$/, '');
      try {
        // Ensure Transcription subdirs exist
        var transcriptionEntry = await uxpfs.getEntryWithUrl('file://' + sourceDir + '/Transcription');
        var transcriptsFolderEntry = await ensureSubfolder(transcriptionEntry, 'transcripts', assemblyLogger);
        var captionsFolderEntry = await ensureSubfolder(transcriptionEntry, 'captions', assemblyLogger);

        // 1. Transcript SRT (full text per segment, for word-based editing)
        var transcriptSrtContent = generateTranscriptSrt(useSegsForSrt);
        if (transcriptSrtContent) {
          var trFileName = projectCode + '_2_Assembly_transcript.srt';
          var trFile = await transcriptsFolderEntry.createFile(trFileName, { overwrite: true });
          await trFile.write(transcriptSrtContent);
          assemblyLogger.info('Transcript SRT written: Transcription/transcripts/' + trFileName);
        }

        // 2. Captions SRT (word-grouped, 2-line blocks for on-screen reading)
        // Only generate if Python pipeline hasn't already created one (Python has better word-level timing)
        var captionsFileName = projectCode + '_2_Assembly_captions.srt';
        var captionsDirPath = sourceDir + '/Transcription/captions';
        var pythonCaptionsExist = false;
        try {
          await uxpfs.getEntryWithUrl('file://' + captionsDirPath + '/' + captionsFileName);
          pythonCaptionsExist = true;
          assemblyLogger.info('Python captions found: ' + captionsFileName + ' (keeping)');
        } catch (e) { /* not found, will generate */ }

        if (!pythonCaptionsExist) {
          var captionsSrtContent = generateCaptionsSrt(useSegsForSrt);
          if (captionsSrtContent) {
            var capFile = await captionsFolderEntry.createFile(captionsFileName, { overwrite: true });
            await capFile.write(captionsSrtContent);
            assemblyLogger.info('Captions SRT generated: Transcription/captions/' + captionsFileName);
          }
        }
      } catch (srtWriteErr) {
        assemblyLogger.warn('SRT write failed (non-fatal): ' + srtWriteErr.message);
      }
    } else {
      assemblyLogger.info('No transcript data for SRT generation');
    }

    // Import both SRTs to 02_Transcripts bin
    await importCaptionsSrt(project, assemblyState.filePath, projectCode, '2_Assembly', 'Assembly Captions', assemblyLogger);
    await importCaptionsSrt(project, assemblyState.filePath, projectCode, '2_Assembly', 'Assembly Transcript', assemblyLogger, 'transcript');
    stepTimings.push('captions ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    setAssemblyProgress(100, 'Complete!');
    assemblyLogger.info('=== ASSEMBLY BUILD COMPLETE (' + elapsed + 's) ===');
    assemblyLogger.info('Timing: ' + stepTimings.join(' | '));
    assemblyLogger.info('Assembly: ' + result.clipCount + ' clips on V1, total=' + (result.totalDuration || 0).toFixed(1) + 's');
    $('btn-build-assembly').classList.add('btn-done');

    // ScreenCues reminder — how many screens are ready in the brief
    if (assemblyState.screens && assemblyState.screens.length > 0) {
      assemblyLogger.info('→ ' + assemblyState.screens.length + ' screens ready in brief. Click "Build Pre-Edit" to generate _4_PreEdit');
    }

    setAssemblyStatus('Assembly built (' + result.clipCount + ' clips). Building Review...', 'ready');

    await saveAssemblyLogs(project, clipMap, result);

    // Auto-build Review after Assembly
    assemblyLogger.info('=== Auto-building Review ===');
    try {
      await buildReview();
      assemblyLogger.info('Review auto-build complete');
    } catch (reviewErr) {
      assemblyLogger.warn('Review auto-build failed (non-fatal): ' + reviewErr.message);
    }

    setAssemblyStatus('Assembly + Review built (' + result.clipCount + ' clips)', 'ready');

  } catch (err) {
    assemblyLogger.error('ASSEMBLY BUILD FAILED: ' + err.message);
    if (err.stack) assemblyLogger.debug(err.stack);
    setAssemblyStatus('Build failed: ' + err.message, 'error');
    try { await saveAssemblyLogs(await ppro.Project.getActiveProject(), clipMap, result); } catch (e) { }
  }

  assemblyState.building = false;
  $('btn-build-assembly').removeAttribute('disabled');
}

/**
 * Import SRT file into the project (02_Transcripts bin).
 *
 * Looks for {project}_{suffix}_{srtType}.srt next to the brief file.
 * Non-fatal: if SRT not found or import fails, logs a message and continues.
 *
 * @param {Object} project - Active Premiere Pro project
 * @param {string} briefPath - Path to the loaded pre_edit_brief.json
 * @param {string} projectName - Project name (e.g. "YTCG49")
 * @param {string} suffix - SRT file suffix: "2_Assembly", "3_Review", "4_ScreenCues"
 * @param {string} label - Human label for logs
 * @param {Object} logger - Logger instance
 * @param {string} [srtType='captions'] - Type suffix: 'captions', 'transcript'
 */
async function importCaptionsSrt(project, briefPath, projectName, suffix, label, logger, srtType) {
  if (!briefPath || !projectName) {
    logger.debug('SRT import skipped: no brief path or project name');
    return;
  }

  // briefPath is in Setup/ — derive Source/ from it
  const briefDir = briefPath.replace(/[/\\][^/\\]+$/, '');
  const sourceDir = briefDir.replace(/[/\\]Setup$/, '');
  const srtFileName = projectName + '_' + suffix + '_' + (srtType || 'captions') + '.srt';
  // SRTs are in Transcription/captions/ (for captions) or Transcription/transcripts/ (for transcripts)
  var typeLabel = (srtType || 'captions');
  var srtSubdir = (typeLabel === 'transcript') ? 'transcripts' : 'captions';
  var srtDir = sourceDir + '/Transcription/' + srtSubdir;
  var srtCandidates = [
    srtDir + '/' + srtFileName,
    briefDir + '/' + srtFileName,  // legacy: next to brief
  ];
  const srtPath = srtCandidates[0];

  logger.info('=== Import ' + label + ' (' + typeLabel + ') ===');

  // Check if file exists (try new location first, then legacy)
  var foundSrtPath = null;
  for (var si = 0; si < srtCandidates.length; si++) {
    try {
      const entry = await uxpfs.getEntryWithUrl('file://' + srtCandidates[si]);
      if (entry) {
        foundSrtPath = srtCandidates[si];
        const content = await entry.read();
        const blockCount = (content.match(/^\d+$/gm) || []).length;
        logger.debug(label + ' ' + typeLabel + ': ' + content.length + ' chars, ' + blockCount + ' SRT blocks');
        break;
      }
    } catch (e) { /* try next */ }
  }
  if (!foundSrtPath) {
    logger.info('No ' + label + ' ' + typeLabel + ' SRT found at: ' + srtFileName);
    return;
  }

  // Find 01_Transcripts bin
  let transcriptsBin = null;
  try {
    const rootItem = await project.getRootItem();
    const allItems = await rootItem.getItems();
    for (const item of allItems) {
      if (item.name === BIN_NAMES.TRANSCRIPTS) {
        transcriptsBin = ppro.FolderItem.cast(item);
        break;
      }
    }
  } catch (e) {
    logger.debug('Cannot find 01_Transcripts bin: ' + e.message);
  }

  // Create sub-bin for this timeline stage, named after the timeline (e.g. YTXX01_2_Assembly)
  var targetBin = transcriptsBin;
  if (transcriptsBin && suffix) {
    var subBinName = projectName + '_' + suffix;
    try {
      // Check if sub-bin already exists
      var existingItems = await transcriptsBin.getItems();
      var found = false;
      for (var ei = 0; ei < existingItems.length; ei++) {
        if (existingItems[ei].name === subBinName) {
          targetBin = ppro.FolderItem.cast(existingItems[ei]) || existingItems[ei];
          found = true;
          break;
        }
      }
      if (!found) {
        project.lockedAccess(function() {
          project.executeTransaction(function(ca) {
            ca.addAction(transcriptsBin.createBinAction(subBinName, true));
          }, 'Create ' + subBinName);
        });
        // Re-fetch to get reference
        existingItems = await transcriptsBin.getItems();
        for (var ni = 0; ni < existingItems.length; ni++) {
          if (existingItems[ni].name === subBinName) {
            targetBin = ppro.FolderItem.cast(existingItems[ni]) || existingItems[ni];
            break;
          }
        }
        logger.info('Created bin: 01_Transcripts/' + subBinName);
      }
    } catch (binErr) {
      logger.debug('Sub-bin creation failed: ' + binErr.message);
    }
  }

  // Import SRT
  try {
    await project.importFiles([foundSrtPath], true, targetBin || null, false);
    logger.info(label + ' ' + typeLabel + ' imported: ' + srtFileName + ' → 01_Transcripts/' + (suffix ? projectName + '_' + suffix : ''));
  } catch (err) {
    logger.warn(label + ' ' + typeLabel + ' import failed (non-fatal): ' + err.message);
  }
}

/**
 * Import all SRT files (transcripts + captions) for every timeline stage.
 *
 * Scans Transcription/transcripts/ and Transcription/captions/ for SRT files,
 * then imports each into the 02_Transcripts bin. Also checks Setup/ for legacy SRTs.
 *
 * Can be run standalone (button) — does not require Build Ingest/Assembly.
 */
async function importAllSrts() {
  const project = await ppro.Project.getActiveProject();
  if (!project) { setIngestStatus('No active project', 'error'); return; }
  if (!projectState.folderPath) { setIngestStatus('Select project folder first', 'error'); return; }

  ingestLogger.info('=== Import All SRTs ===');
  setIngestStatus('Importing SRTs...', 'waiting');

  var sourceDir = projectState.folderPath + '/01_Media/Source';
  var imported = 0;
  var skipped = 0;

  // Find 02_Transcripts bin (create if missing)
  let transcriptsBin = null;
  try {
    const rootItem = await project.getRootItem();
    const allItems = await rootItem.getItems();
    for (const item of allItems) {
      if (item.name === BIN_NAMES.TRANSCRIPTS) {
        transcriptsBin = ppro.FolderItem.cast(item);
        break;
      }
    }
    if (!transcriptsBin) {
      ingestLogger.info('Creating ' + BIN_NAMES.TRANSCRIPTS + ' bin');
      const action = ppro.FolderItem.createAddItemAction(BIN_NAMES.TRANSCRIPTS);
      await project.applyActions([action]);
      const updatedItems = await rootItem.getItems();
      for (const item of updatedItems) {
        if (item.name === BIN_NAMES.TRANSCRIPTS) {
          transcriptsBin = ppro.FolderItem.cast(item);
          break;
        }
      }
    }
  } catch (e) {
    ingestLogger.warn('Cannot find/create 02_Transcripts bin: ' + e.message);
  }

  // Collect SRT search dirs (flat list + per-scene Video subdirs)
  var searchDirs = [
    sourceDir + '/Transcription/transcripts',
    sourceDir + '/Transcription/captions',
    sourceDir + '/Setup',
    sourceDir,
  ];

  // Also scan Video/{scene}/ directories for per-scene SRTs
  try {
    var videoDirEntry = await uxpfs.getEntryWithUrl('file://' + sourceDir + '/Video');
    if (videoDirEntry) {
      var sceneDirs = await videoDirEntry.getEntries();
      for (var si = 0; si < sceneDirs.length; si++) {
        if (sceneDirs[si].isFolder) {
          searchDirs.push(sourceDir + '/Video/' + sceneDirs[si].name);
        }
      }
    }
  } catch (e) {
    ingestLogger.debug('No Video/ dir or cannot list scenes: ' + e.message);
  }

  // Track already-imported filenames to avoid duplicates
  var importedNames = {};

  // Get existing items in 02_Transcripts to skip re-imports
  if (transcriptsBin) {
    try {
      var existingItems = await transcriptsBin.getItems();
      for (var ei = 0; ei < existingItems.length; ei++) {
        importedNames[existingItems[ei].name] = true;
      }
    } catch (e) { /* empty bin */ }
  }

  for (var di = 0; di < searchDirs.length; di++) {
    try {
      var dirEntry = await uxpfs.getEntryWithUrl('file://' + searchDirs[di]);
      if (!dirEntry) continue;
      var entries = await dirEntry.getEntries();
      for (var fi = 0; fi < entries.length; fi++) {
        var entry = entries[fi];
        if (!entry.name || !entry.name.endsWith('.srt')) continue;
        if (importedNames[entry.name]) {
          ingestLogger.debug('Skip (already in bin): ' + entry.name);
          skipped++;
          continue;
        }
        try {
          var nativePath = searchDirs[di] + '/' + entry.name;
          await project.importFiles([nativePath], true, transcriptsBin || null, false);
          importedNames[entry.name] = true;
          imported++;
          ingestLogger.info('Imported: ' + entry.name);
        } catch (importErr) {
          ingestLogger.warn('Failed to import ' + entry.name + ': ' + importErr.message);
        }
      }
    } catch (dirErr) {
      ingestLogger.debug('Dir not found: ' + searchDirs[di]);
    }
  }

  if (imported > 0) {
    setIngestStatus(imported + ' SRT(s) imported' + (skipped > 0 ? ' (' + skipped + ' already in bin)' : ''), 'ready');
  } else if (skipped > 0) {
    setIngestStatus('All ' + skipped + ' SRT(s) already in 02_Transcripts', 'ready');
  } else {
    setIngestStatus('No SRT files found in project', 'error');
  }
  ingestLogger.info('=== Import SRTs complete: ' + imported + ' imported, ' + skipped + ' skipped ===');
}

/**
 * Export markers from active sequence as JSON.
 *
 * Reads marker names and positions from the current sequence and writes
 * to Setup/{CODE}_{suffix}_markers.json. Marker names carry editor notes
 * (UXP API cannot read marker comments, only names).
 */
/**
 * Export markers by saving the project and launching Python script
 * that reads the .prproj file directly (includes comments, positions, duration).
 *
 * UXP API cannot read marker comments — but .prproj (gzip XML) contains everything.
 * Uses shell.openPath() to run run_export_markers.command in Terminal.
 */
/**
 * Export markers by reading .prproj file directly (gzip XML → DVAMarker JSON).
 * Everything runs inside UXP — no Terminal, no Python.
 * Writes to Setup/Assembly/{seq}_v{N}_out.json + ~/Downloads/.
 */
async function exportMarkers() {
  var project = await ppro.Project.getActiveProject();
  if (!project) { setAssemblyStatus('No active project', 'error'); return; }
  if (!projectState.folderPath) { setAssemblyStatus('Select project folder first', 'error'); return; }

  assemblyLogger.info('=== Export Markers (from active sequence) ===');
  setAssemblyStatus('Reading markers...', 'waiting');
  $('btn-export-markers').setAttribute('disabled', 'true');
  $('btn-debug-export').setAttribute('disabled', 'true');

  try {
    // Step 1: Get active sequence
    var seq = await project.getActiveSequence();
    if (!seq) throw new Error('No active sequence — open a sequence first');
    var seqName = seq.name;
    assemblyLogger.info('Active sequence: ' + seqName);

    // Step 2: Read markers from active sequence via UXP API
    setAssemblyStatus('Reading markers from ' + seqName + '...', 'waiting');
    var markersOwner = await ppro.Markers.getMarkers(seq);
    if (!markersOwner) throw new Error('Cannot get markers from sequence');

    var rawMarkers = markersOwner.getMarkers();
    assemblyLogger.info('Raw markers: ' + (rawMarkers ? rawMarkers.length : 0));

    var markers = [];
    if (rawMarkers && rawMarkers.length > 0) {
      // Log first marker's API shape for debugging
      try {
        var m0 = rawMarkers[0];
        var m0methods = [];
        for (var k of Object.getOwnPropertyNames(Object.getPrototypeOf(m0))) {
          if (typeof m0[k] === 'function') m0methods.push(k);
        }
        assemblyLogger.debug('Marker[0] methods: [' + m0methods.join(', ') + ']');
        var m0comment = m0.comments || '';
        if (!m0comment && m0.getComments) try { m0comment = m0.getComments(); } catch(e) {}
        if (!m0comment) m0comment = m0.comment || '';
        assemblyLogger.debug('Marker[0] name=' + m0.name + ' type=' + m0.type + ' comments="' + m0comment + '"' +
          ' | .comments=' + JSON.stringify(m0.comments) + ' .comment=' + JSON.stringify(m0.comment) +
          ' hasGetComments=' + (typeof m0.getComments === 'function'));
      } catch (e) { assemblyLogger.debug('Marker introspection failed: ' + e.message); }

      for (var mi = 0; mi < rawMarkers.length; mi++) {
        var rm = rawMarkers[mi];
        // Get start time — try getStart() then startTime property
        var startTime = null;
        try { startTime = rm.getStart(); } catch (e) {}
        if (!startTime) try { startTime = rm.startTime; } catch (e) {}
        var posSec = startTime ? Math.round(startTime.seconds * 100) / 100 : 0;

        var entry = {
          name: rm.name || '',
          position_sec: posSec,
        };

        // Get duration — try getDuration() then duration property
        var dur = null;
        try { dur = rm.getDuration(); } catch (e) {}
        if (!dur) try { dur = rm.duration; } catch (e) {}
        if (dur && dur.seconds > 0) {
          entry.duration_sec = Math.round(dur.seconds * 100) / 100;
          entry.is_chapter = true;
        }

        // Get comments — try property, then getComments(), then comment (singular)
        var commentText = rm.comments || '';
        if (!commentText) try { commentText = rm.getComments ? rm.getComments() : ''; } catch (e) {}
        if (!commentText) commentText = rm.comment || '';
        if (commentText) entry.comment = commentText;
        if (rm.type) entry.type = rm.type;
        markers.push(entry);
      }
    }

    markers.sort(function(a, b) { return a.position_sec - b.position_sec; });
    var chapters = markers.filter(function(m) { return m.is_chapter; });
    assemblyLogger.info('Parsed: ' + markers.length + ' markers (' + chapters.length + ' chapters)');

    // Step 3: Classify markers
    var assemblyMarkers = [];
    var reviewMarkers = [];
    for (var ci = 0; ci < markers.length; ci++) {
      var mName = markers[ci].name || '';
      var mCom = markers[ci].comment || '';
      if (mCom.startsWith('/')) {
        assemblyMarkers.push(markers[ci]);
      } else if (mName.indexOf('[CUT]') === 0 || mName.indexOf('[ALT]') === 0 || mName.indexOf('[SKIP]') === 0) {
        reviewMarkers.push(markers[ci]);
      } else if (mName.indexOf('Source:') === 0) {
        assemblyMarkers.push(markers[ci]);
        reviewMarkers.push(markers[ci]);
      } else {
        assemblyMarkers.push(markers[ci]);
      }
    }
    var assemblyChapters = assemblyMarkers.filter(function(m) { return m.is_chapter && (m.name || '').indexOf('Source:') !== 0; });

    assemblyLogger.info('Assembly: ' + assemblyMarkers.length + ' markers (' + assemblyChapters.length + ' chapters)');
    assemblyLogger.info('Review: ' + reviewMarkers.length + ' markers');

    var slashComments = markers.filter(function(m) { return (m.comment || '').startsWith('/'); });
    assemblyLogger.info('User / comments: ' + slashComments.length);

    var output = {
      sequence: seqName,
      exported_at: new Date().toISOString(),
      assembly: {
        markers_count: assemblyMarkers.length,
        chapters_count: assemblyChapters.length,
        markers: assemblyMarkers,
      },
      review: {
        markers_count: reviewMarkers.length,
        markers: reviewMarkers,
      },
    };

    // Step 7: Read V1 TrackItems — real timeline clips
    setAssemblyStatus('Reading timeline clips...', 'waiting');
    var timelineClips = [];
    try {
      var v1Track = await seq.getVideoTrack(0);
      var trackItems = null;
      try { trackItems = v1Track.getTrackItems(1, false); } catch (ex) {}
      if (!trackItems) try { trackItems = v1Track.getTrackItems(); } catch (ex) {}
      if (trackItems && trackItems.length > 0) {
        for (var ti = 0; ti < trackItems.length; ti++) {
          var item = trackItems[ti];
          var projItem = await item.getProjectItem();
          var clipName = projItem ? projItem.name : '';
          var clipStart = await item.getStartTime();
          var clipDur = await item.getDuration();
          var clipIn = await item.getInPoint();
          var clipOut = await item.getOutPoint();
          timelineClips.push({
            index: ti,
            source_file: clipName,
            tc_in_sec: Math.round(tickSec(clipIn) * 100) / 100,
            tc_out_sec: Math.round(tickSec(clipOut) * 100) / 100,
            timeline_start_sec: Math.round(tickSec(clipStart) * 100) / 100,
            duration_sec: Math.round(tickSec(clipDur) * 100) / 100,
          });
        }
        assemblyLogger.info('Timeline V1 clips: ' + timelineClips.length);
      }
    } catch (tlErr) {
      assemblyLogger.warn('Could not read V1 TrackItems: ' + tlErr.message);
    }

    // Step 7b: Match timeline clips with transcript_assembly.json for text
    try {
      var txPath = projectState.folderPath + '/01_Media/Source/Transcription/' + projectState.projectName + '_transcript_assembly.json';
      var txEntry = await uxpfs.getEntryWithUrl('file://' + txPath);
      var txRaw = await txEntry.read({ format: require('uxp').storage.formats.utf8 });
      var txData = JSON.parse(txRaw);
      var txClips = txData.clips || [];

      // Build lookup: filename → segments
      var txLookup = {};
      for (var tci = 0; tci < txClips.length; tci++) {
        var tc = txClips[tci];
        txLookup[tc.filename] = tc.segments || [];
      }

      // Match each timeline clip with transcript segments
      for (var mi2 = 0; mi2 < timelineClips.length; mi2++) {
        var clip = timelineClips[mi2];
        var segs = txLookup[clip.source_file] || [];
        var texts = [];
        for (var si2 = 0; si2 < segs.length; si2++) {
          var sg = segs[si2];
          // Parse start/end from M:SS.s format
          var sgStart = 0; var sgEnd = 0;
          try {
            var sp = (sg.start || '0:0').split(':');
            sgStart = parseInt(sp[0]) * 60 + parseFloat(sp[1] || 0);
            var ep = (sg.end || '0:0').split(':');
            sgEnd = parseInt(ep[0]) * 60 + parseFloat(ep[1] || 0);
          } catch (pe) {}
          // Check overlap
          if (sgStart < clip.tc_out_sec && sgEnd > clip.tc_in_sec) {
            texts.push(sg.text || '');
          }
        }
        clip.transcript_text = texts.join(' ').substring(0, 500);
        if (segs.length > 0 && texts.length > 0) {
          clip.speaker = segs.find(function(s2) {
            var s2p = (s2.start || '0:0').split(':');
            var s2s = parseInt(s2p[0]) * 60 + parseFloat(s2p[1] || 0);
            return s2s >= clip.tc_in_sec;
          });
          if (clip.speaker) clip.speaker = clip.speaker.speaker || '';
        }
      }
      assemblyLogger.info('Matched transcript text for ' + timelineClips.filter(function(c){return c.transcript_text;}).length + ' clips');
    } catch (txErr) {
      assemblyLogger.debug('Transcript matching skipped: ' + txErr.message);
    }

    output.timeline_clips = timelineClips;

    // Step 8: Find next version and write to Setup/Assembly/
    setAssemblyStatus('Writing files...', 'waiting');
    var assemblyDir = projectState.folderPath + '/01_Media/Source/Setup/Assembly';
    var assemblyEntry;
    try {
      assemblyEntry = await uxpfs.getEntryWithUrl('file://' + assemblyDir);
    } catch (e) {
      var setupEntry = await uxpfs.getEntryWithUrl('file://' + projectState.folderPath + '/01_Media/Source/Setup');
      assemblyEntry = await ensureSubfolder(setupEntry, 'Assembly', assemblyLogger);
    }

    // Strip _v{N} suffix from seqName to avoid double versioning
    // e.g. YTXX01_2_Assembly_v1 → YTXX01_2_Assembly
    var baseSeqName = seqName.replace(/_v\d+$/, '');

    var existingFiles = await assemblyEntry.getEntries();
    var maxVer = 0;
    var verRe = new RegExp(baseSeqName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '_v(\\d+)');
    for (var fi = 0; fi < existingFiles.length; fi++) {
      var vm = existingFiles[fi].name.match(verRe);
      if (vm) {
        var vn = parseInt(vm[1], 10);
        if (vn > maxVer) maxVer = vn;
      }
    }
    var version = maxVer + 1;
    output.version = version;
    output.direction = 'out';

    // Generate brief from real timeline clips + chapter markers + transcript
    // This is the single source of truth — built from what's actually on the timeline

    // Read old brief for metadata enrichment (broll_note, notes, project settings)
    var oldBrief = null;
    if (projectState.briefPath) {
      try {
        var briefEntry = await uxpfs.getEntryWithUrl('file://' + projectState.briefPath);
        var briefContent = await briefEntry.read({ format: require('uxp').storage.formats.utf8 });
        oldBrief = JSON.parse(briefContent);
        assemblyLogger.info('Read old brief for enrichment: ' + projectState.briefPath.split('/').pop());
      } catch (briefErr) {
        assemblyLogger.debug('Old brief not available: ' + briefErr.message);
      }
    }

    // Build block lookup from chapter markers
    var chMarkers = markers.filter(function(m) { return m.is_chapter && m.duration_sec > 0; });
    chMarkers.sort(function(a, b) { return a.position_sec - b.position_sec; });

    // Match chapter positions with old brief block names/colors
    var oldBlockLookup = {};
    if (oldBrief && oldBrief.segments) {
      var cumT = 0;
      var seenB = {};
      for (var obi = 0; obi < oldBrief.segments.length; obi++) {
        var obs = oldBrief.segments[obi];
        if (obs.use !== 'TRUE' || obs.block === 99) continue;
        if (!seenB[obs.block]) {
          seenB[obs.block] = { name: obs.block_name || '', color: obs.color || '', start: cumT };
        }
        var opIn = (obs.tc_in || '0:0').split(':'); var opOut = (obs.tc_out || '0:0').split(':');
        cumT += (parseInt(opOut[0]) * 60 + parseFloat(opOut[1] || 0)) - (parseInt(opIn[0]) * 60 + parseFloat(opIn[1] || 0));
      }
      for (var bk in seenB) oldBlockLookup[bk] = seenB[bk];
    }

    // Assign block info to each chapter marker
    var blockDefs = [];
    for (var chi2 = 0; chi2 < chMarkers.length; chi2++) {
      var chm = chMarkers[chi2];
      var bName2 = chm.name || '';
      var bColor2 = '';
      // Find closest old brief block by position
      var bestDist2 = Infinity;
      for (var obk in oldBlockLookup) {
        var d2 = Math.abs(oldBlockLookup[obk].start - chm.position_sec);
        if (d2 < bestDist2) { bestDist2 = d2; bName2 = oldBlockLookup[obk].name || bName2; bColor2 = oldBlockLookup[obk].color; }
      }
      blockDefs.push({ num: chi2 + 1, start: chm.position_sec, end: chm.position_sec + chm.duration_sec, name: bName2, color: bColor2 });
    }

    // Build old brief lookup for enrichment (by source_file + tc_in)
    var oldSegLookup = {};
    if (oldBrief && oldBrief.segments) {
      for (var osi = 0; osi < oldBrief.segments.length; osi++) {
        var os = oldBrief.segments[osi];
        oldSegLookup[os.source_file + '|' + os.tc_in] = os;
      }
    }

    // Collect user comment markers (non-auto-generated) keyed by position
    var userNotes = {};
    for (var uni = 0; uni < markers.length; uni++) {
      var um = markers[uni];
      if (um.is_chapter || !um.comment) continue;
      // Skip auto-generated (Speaker: X | transcript | B-roll | Notes pattern)
      if ((um.comment || '').indexOf('Speaker:') === 0 && (um.comment || '').indexOf('|') > 0) continue;
      if ((um.comment || '').indexOf('/') === 0) continue; // / markers are separate
      var upos = um.position_sec;
      if (!userNotes[upos]) userNotes[upos] = [];
      userNotes[upos].push(um.comment);
    }

    function fmtMMSS(sec) {
      var mm = Math.floor(sec / 60);
      var ss = (sec % 60).toFixed(1);
      return (mm < 10 ? '0' : '') + mm + ':' + (ss < 10 ? '0' : '') + ss;
    }

    // Generate brief segments from timeline clips
    var briefSegments = [];
    for (var bsi3 = 0; bsi3 < timelineClips.length; bsi3++) {
      var tc = timelineClips[bsi3];
      // Find block for this clip
      var clipBlock = 1;
      var clipBlockName = '';
      var clipColor = 'Green';
      var isFirst = false;
      for (var bd = 0; bd < blockDefs.length; bd++) {
        if (tc.timeline_start_sec >= blockDefs[bd].start && tc.timeline_start_sec < blockDefs[bd].end) {
          clipBlock = blockDefs[bd].num;
          clipBlockName = blockDefs[bd].name;
          clipColor = blockDefs[bd].color || 'Green';
          // Check if first clip in this block
          if (bsi3 === 0 || (bsi3 > 0 && !(timelineClips[bsi3 - 1].timeline_start_sec >= blockDefs[bd].start && timelineClips[bsi3 - 1].timeline_start_sec < blockDefs[bd].end))) {
            isFirst = true;
          }
          break;
        }
      }

      // Enrichment from old brief
      var tcInStr = fmtMMSS(tc.tc_in_sec);
      var oldSeg = oldSegLookup[tc.source_file + '|' + tcInStr];
      var brollNote = (oldSeg && oldSeg.broll_note) ? oldSeg.broll_note : '';
      var segNotes = (oldSeg && oldSeg.notes) ? oldSeg.notes : '';
      var segName = (oldSeg && oldSeg.segment_name) ? oldSeg.segment_name : '';

      // Append user notes from markers
      var clipEnd2 = tc.timeline_start_sec + tc.duration_sec;
      for (var unp in userNotes) {
        var unPos = parseFloat(unp);
        if (unPos >= tc.timeline_start_sec && unPos < clipEnd2) {
          segNotes = (segNotes ? segNotes + ' | ' : '') + userNotes[unp].join(' | ');
        }
      }

      briefSegments.push({
        segment_id: 'seg_' + String(bsi3 + 1).padStart(3, '0'),
        source_file: tc.source_file,
        tc_in: tcInStr,
        tc_out: fmtMMSS(tc.tc_out_sec),
        block: clipBlock,
        block_name: clipBlockName,
        segment_name: segName,
        speaker: tc.speaker || '',
        transcript: (tc.transcript_text || '').substring(0, 500),
        track: 'V1',
        color: clipColor,
        use: 'TRUE',
        priority: 1,
        is_chapter: isFirst ? 'TRUE' : 'FALSE',
        broll_note: brollNote,
        notes: segNotes,
      });
    }

    output.brief = {
      segments: briefSegments,
      project: (oldBrief && oldBrief.project) ? oldBrief.project : {
        project_name: projectState.projectName || seqName,
        fps: 25, width: 3840, height: 2160, sample_rate: 48000,
        create_assembly_sequence: true, cut_color: 'Red'
      },
      changelog: [{ version: 'v' + version, date: new Date().toISOString().split('T')[0], source: 'premiere_export', summary: 'Generated from timeline ' + seqName }]
    };
    output.brief_source = 'generated_from_timeline';
    assemblyLogger.info('Generated brief from timeline: ' + briefSegments.length + ' segments, ' + blockDefs.length + ' blocks');

    var fileName = baseSeqName + '_v' + version + '_out.json';
    var jsonContent = JSON.stringify(output, null, 2);

    // Write to Setup/Assembly/
    var outFile = await assemblyEntry.createFile(fileName, { overwrite: true });
    await outFile.write(jsonContent);
    assemblyLogger.info('Written: Setup/Assembly/' + fileName);

    // Write to ~/Downloads/
    try {
      var homePath = require('os').homedir();
      var dlEntry = await uxpfs.getEntryWithUrl('file://' + homePath + '/Downloads');
      var dlFile = await dlEntry.createFile(fileName, { overwrite: true });
      await dlFile.write(jsonContent);
      assemblyLogger.info('Copied: ~/Downloads/' + fileName);
    } catch (dlErr) {
      assemblyLogger.debug('Downloads copy failed: ' + dlErr.message);
    }

    // Generate HTML review alongside _out.json
    try {
      var htmlName = baseSeqName + '_v' + version + '_review.html';
      var htmlContent = generateExportReviewHtml(output, version, seqName);
      var htmlFile = await assemblyEntry.createFile(htmlName, { overwrite: true });
      await htmlFile.write(htmlContent);
      assemblyLogger.info('Written: Setup/Assembly/' + htmlName);

      // Open in browser
      try {
        var shell = require('uxp').shell;
        var htmlEntry = await uxpfs.getEntryWithUrl('file://' + assemblyDir + '/' + htmlName);
        await shell.openPath(htmlEntry.nativePath || (assemblyDir + '/' + htmlName));
      } catch (openErr) {
        assemblyLogger.debug('Could not auto-open HTML: ' + openErr.message);
      }
    } catch (htmlErr) {
      assemblyLogger.warn('HTML review generation failed: ' + htmlErr.message);
    }

    setAssemblyStatus('Exported v' + version + ': ' + markers.length + ' markers → ' + fileName, 'ready');
    $('btn-copy-markers-prompt').removeAttribute('disabled');

  } catch (err) {
    assemblyLogger.error('Marker export failed: ' + err.message);
    if (err.stack) assemblyLogger.debug(err.stack);
    setAssemblyStatus('Export failed: ' + err.message, 'error');
  }

  $('btn-export-markers').removeAttribute('disabled');
  $('btn-debug-export').removeAttribute('disabled');
}

/**
 * Debug Export — separate button for comparing Premiere actual vs brief.
 * Reads V1 clips from active sequence, matches with brief segments,
 * reads Claude4_assembly.json for word-level comparison.
 * Writes {CODE}_debug.json to Assembly/ folder.
 */
async function debugExport() {
  var DEBUG_VERSION = '1.0.0';
  var project = await ppro.Project.getActiveProject();
  if (!project) { setAssemblyStatus('No active project', 'error'); return; }
  if (!projectState.folderPath) { setAssemblyStatus('Select project folder first', 'error'); return; }

  assemblyLogger.info('=== Debug Export v' + DEBUG_VERSION + ' ===');
  setAssemblyStatus('Debug export...', 'waiting');
  $('btn-debug-export').setAttribute('disabled', 'true');

  try {
    var seq = await project.getActiveSequence();
    if (!seq) throw new Error('No active sequence');
    var seqName = seq.name;
    var seqSettings = seq.getSettings ? seq.getSettings() : {};
    var fps = assemblyState.projectSettings ? (assemblyState.projectSettings.fps || 29.97) : 29.97;

    assemblyLogger.info('Sequence: ' + seqName + ', fps=' + fps);

    // Read V1 clips
    var v1Track = await seq.getVideoTrack(0);
    var trackItems = null;
    try { trackItems = v1Track.getTrackItems(1, false); } catch (ex) {}
    if (!trackItems) try { trackItems = v1Track.getTrackItems(); } catch (ex) {}

    var clips = [];
    if (trackItems) {
      for (var ti = 0; ti < trackItems.length; ti++) {
        var item = trackItems[ti];
        var projItem = await item.getProjectItem();
        var clipStart = await item.getStartTime();
        var clipDur = await item.getDuration();
        var clipIn = await item.getInPoint();
        var clipOut = await item.getOutPoint();
        clips.push({
          index: ti,
          source_file: projItem ? projItem.name : '',
          premiere: {
            tc_in: Math.round(tickSec(clipIn) * 1000) / 1000,
            tc_out: Math.round(tickSec(clipOut) * 1000) / 1000,
            timeline_start: Math.round(tickSec(clipStart) * 1000) / 1000,
            duration: Math.round(tickSec(clipDur) * 1000) / 1000
          }
        });
      }
    }
    assemblyLogger.info('V1 clips: ' + clips.length);

    // Match with brief segments
    var briefSegs = assemblyState.segments || [];
    var useSegs = briefSegs.filter(function(s) { return s.use && s.block !== 99; });

    for (var ci = 0; ci < clips.length; ci++) {
      var clip = clips[ci];
      // Match by source tc overlap (not index — ghost clips break index matching)
      var bs = null;
      var bestOverlap = 0;
      for (var bsi = 0; bsi < useSegs.length; bsi++) {
        var candidate = useSegs[bsi];
        if (candidate.sourceFile !== clip.source_file) continue;
        var overlap = Math.min(clip.premiere.tc_out, candidate.outSec) -
                      Math.max(clip.premiere.tc_in, candidate.inSec);
        if (overlap > bestOverlap) { bestOverlap = overlap; bs = candidate; }
      }
      if (clip.premiere.duration < 0.05) {
        clip.ghost = true;
        assemblyLogger.warn('  clip[' + ci + '] GHOST (1 frame, ' + clip.premiere.duration.toFixed(3) + 's)');
      }
      if (bs) {
        clip.brief = {
          seg_id: bs.id,
          tc_in: bs.tcIn,
          tc_out: bs.tcOut,
          tc_in_sec: bs.inSec,
          tc_out_sec: bs.outSec
        };
        clip.delta_ms = {
          'in': Math.round((clip.premiere.tc_in - bs.inSec) * 1000),
          out: Math.round((clip.premiere.tc_out - bs.outSec) * 1000)
        };
        assemblyLogger.info('  clip[' + ci + '] ' + (bs.id || '') +
          ': prem_in=' + clip.premiere.tc_in.toFixed(3) +
          ' brief_in=' + bs.inSec.toFixed(3) +
          ' Δ=' + clip.delta_ms['in'] + 'ms' +
          ' | prem_out=' + clip.premiere.tc_out.toFixed(3) +
          ' brief_out=' + bs.outSec.toFixed(3) +
          ' Δ=' + clip.delta_ms.out + 'ms');
      }
    }

    // Read Claude4_assembly.json for word data
    try {
      var c4Path = projectState.folderPath + '/01_Media/Source/Setup/' +
        (projectState.projectCode || 'UNKNOWN') + '_Claude4_assembly.json';
      var c4Entry = await uxpfs.getEntryWithUrl('file://' + c4Path);
      var c4Raw = await c4Entry.read({ format: require('uxp').storage.formats.utf8 });
      var c4Data = JSON.parse(c4Raw);
      var c4Clips = c4Data.clips || [];

      // Build word lookup by filename
      var wordLookup = {};
      for (var wci = 0; wci < c4Clips.length; wci++) {
        var wc = c4Clips[wci];
        var allWords = [];
        var wcSegs = wc.segments || [];
        for (var wsi = 0; wsi < wcSegs.length; wsi++) {
          var ws = wcSegs[wsi].words || [];
          for (var wi = 0; wi < ws.length; wi++) {
            allWords.push(ws[wi]);
          }
        }
        wordLookup[wc.filename] = allWords;
      }

      // For each clip, find words in range
      for (var ci2 = 0; ci2 < clips.length; ci2++) {
        var clip2 = clips[ci2];
        var words = wordLookup[clip2.source_file] || [];
        var wordsInRange = [];
        for (var wi2 = 0; wi2 < words.length; wi2++) {
          var w = words[wi2];
          var wsParts = (w.s || '0:0').split(':');
          var wsVal = parseInt(wsParts[0]) * 60 + parseFloat(wsParts[1] || 0);
          var weParts = (w.e || '0:0').split(':');
          var weVal = parseInt(weParts[0]) * 60 + parseFloat(weParts[1] || 0);
          if (weVal > clip2.premiere.tc_in && wsVal < clip2.premiere.tc_out) {
            wordsInRange.push(w);
          }
        }
        clip2.words_in_range = wordsInRange.length;
        clip2.first_word = wordsInRange.length > 0 ? wordsInRange[0].w : '';
        clip2.last_word = wordsInRange.length > 0 ? wordsInRange[wordsInRange.length - 1].w : '';

        if (clip2.brief) {
          assemblyLogger.info('    words: ' + wordsInRange.length +
            ', first="' + clip2.first_word + '", last="' + clip2.last_word + '"');
        }
      }
    } catch (c4Err) {
      assemblyLogger.warn('Claude4_assembly.json not found: ' + c4Err.message);
    }

    // Summary
    var maxDeltaIn = 0, maxDeltaOut = 0, problemClips = 0;
    for (var si = 0; si < clips.length; si++) {
      var d = clips[si].delta_ms;
      if (d) {
        if (Math.abs(d['in']) > maxDeltaIn) maxDeltaIn = Math.abs(d['in']);
        if (Math.abs(d.out) > maxDeltaOut) maxDeltaOut = Math.abs(d.out);
        if (Math.abs(d['in']) > 10 || Math.abs(d.out) > 10) problemClips++;
      }
    }

    var output = {
      debug_version: DEBUG_VERSION,
      uxp_version: typeof ASSEMBLY_BUILDER_VERSION !== 'undefined' ? ASSEMBLY_BUILDER_VERSION : '?',
      exported_at: new Date().toISOString(),
      sequence: seqName,
      fps: fps,
      clips: clips,
      summary: {
        total_clips: clips.length,
        max_delta_in_ms: maxDeltaIn,
        max_delta_out_ms: maxDeltaOut,
        clips_with_delta_gt_10ms: problemClips
      }
    };

    // Write to Assembly/
    var assemblyDir = projectState.folderPath + '/01_Media/Source/Setup/Assembly';
    var assemblyEntry;
    try {
      assemblyEntry = await uxpfs.getEntryWithUrl('file://' + assemblyDir);
    } catch (e) {
      var setupEntry = await uxpfs.getEntryWithUrl('file://' + projectState.folderPath + '/01_Media/Source/Setup');
      assemblyEntry = await ensureSubfolder(setupEntry, 'Assembly', assemblyLogger);
    }

    var debugFileName = seqName.replace(/[^a-zA-Z0-9_-]/g, '_') + '_debug.json';
    var debugFile = await assemblyEntry.createFile(debugFileName, { overwrite: true });
    await debugFile.write(JSON.stringify(output, null, 2), { format: require('uxp').storage.formats.utf8 });
    assemblyLogger.info('Debug export → ' + debugFileName);

    // Also copy to Downloads
    try {
      var dl = await uxpfs.getEntryWithUrl('file://' + require('os').homedir() + '/Downloads');
      var dlFile = await dl.createFile(debugFileName, { overwrite: true });
      await dlFile.write(JSON.stringify(output, null, 2), { format: require('uxp').storage.formats.utf8 });
    } catch (dlErr) {}

    var status = problemClips > 0
      ? problemClips + ' clips with Δ>10ms! Check ' + debugFileName
      : 'All clips Δ<10ms ✅ → ' + debugFileName;
    setAssemblyStatus('Debug: ' + status, problemClips > 0 ? 'error' : 'ready');

  } catch (err) {
    assemblyLogger.error('Debug export failed: ' + err.message);
    if (err.stack) assemblyLogger.debug(err.stack);
    setAssemblyStatus('Debug failed: ' + err.message, 'error');
  }

  $('btn-debug-export').removeAttribute('disabled');
}

/**
 * Generate HTML review page from export data.
 * Primary source: timeline_clips[] (real V1 track items + transcript text).
 * Secondary: brief (if available) for block/color context.
 * / markers highlighted with yellow.
 */
function generateExportReviewHtml(output, version, seqName) {
  var clips = output.timeline_clips || [];
  var markers = (output.assembly || {}).markers || [];
  var brief = output.brief || {};
  var briefSegments = brief.segments || [];

  function esc(s) { return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function fmtTC(sec) {
    if (!sec && sec !== 0) return '—';
    var m = Math.floor(sec / 60);
    var s = (sec % 60).toFixed(1);
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  // Total duration from timeline clips
  var totalDur = 0;
  for (var i = 0; i < clips.length; i++) totalDur += (clips[i].duration_sec || 0);

  // Find / markers
  var slashMarkers = [];
  for (var mi = 0; mi < markers.length; mi++) {
    if ((markers[mi].comment || '').indexOf('/') === 0) slashMarkers.push(markers[mi]);
  }

  var html = '<!DOCTYPE html><html><head><meta charset="utf-8"><title>' + esc(seqName) + ' v' + version + ' — Export Review</title>';
  html += '<style>';
  html += 'body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#1a1a2e;color:#e0e0e0;margin:20px;line-height:1.5}';
  html += 'h1{color:#fff;margin-bottom:5px} .subtitle{color:#888;margin-bottom:20px}';
  html += 'table{border-collapse:collapse;width:100%;margin-bottom:30px}';
  html += 'th{background:#16213e;color:#fff;padding:8px 12px;text-align:left;font-weight:600;position:sticky;top:0}';
  html += 'td{padding:6px 12px;border-bottom:1px solid #2a2a4a;vertical-align:top}';
  html += 'tr:hover{background:#16213e}';
  html += '.slash-marker{background:#3a3000;border-left:3px solid #E6C619;padding:10px 15px;margin:8px 0;border-radius:4px}';
  html += '.slash-marker .pos{color:#E6C619;font-weight:600} .slash-marker .comment{color:#fff}';
  html += '.stats{display:flex;gap:20px;flex-wrap:wrap;margin-bottom:20px} .stat{background:#16213e;padding:12px 18px;border-radius:8px}';
  html += '.stat-value{font-size:22px;font-weight:700;color:#fff} .stat-label{color:#888;font-size:12px}';
  html += '.section{margin-bottom:30px} .section h2{color:#ccc;border-bottom:1px solid #2a2a4a;padding-bottom:8px}';
  html += '.tx{color:#bbb;font-size:12px;max-width:500px;line-height:1.4}';
  html += '.speaker{color:#4A90D9;font-size:11px;font-weight:600}';
  html += '.clip-num{color:#666;font-size:11px}';
  html += '.marker-inline{background:#3a3000;color:#E6C619;padding:2px 6px;border-radius:3px;font-size:11px;display:inline-block;margin:2px 0}';
  html += '</style></head><body>';

  // Header
  html += '<h1>' + esc(seqName) + ' — v' + version + '</h1>';
  html += '<div class="subtitle">Exported: ' + (output.exported_at || new Date().toISOString());
  if (output.brief_source) html += ' | Brief: ' + esc(output.brief_source);
  html += '</div>';

  // Stats
  html += '<div class="stats">';
  html += '<div class="stat"><div class="stat-value">' + clips.length + '</div><div class="stat-label">V1 Clips</div></div>';
  html += '<div class="stat"><div class="stat-value">' + fmtTC(totalDur) + '</div><div class="stat-label">Duration</div></div>';
  html += '<div class="stat"><div class="stat-value">' + markers.length + '</div><div class="stat-label">Markers</div></div>';
  html += '<div class="stat"><div class="stat-value">' + slashMarkers.length + '</div><div class="stat-label">/ Edits</div></div>';
  if (briefSegments.length > 0) {
    html += '<div class="stat"><div class="stat-value">' + briefSegments.length + '</div><div class="stat-label">Brief Segments</div></div>';
  }
  html += '</div>';

  // / Markers section
  if (slashMarkers.length > 0) {
    html += '<div class="section"><h2>/ Edit Markers (' + slashMarkers.length + ')</h2>';
    for (var sm = 0; sm < slashMarkers.length; sm++) {
      var mk = slashMarkers[sm];
      html += '<div class="slash-marker"><span class="pos">' + fmtTC(mk.position_sec) + '</span> ';
      if (mk.name) html += '<strong>' + esc(mk.name) + '</strong> — ';
      html += '<span class="comment">' + esc(mk.comment) + '</span></div>';
    }
    html += '</div>';
  }

  // Build block boundaries from chapter markers + brief block names
  var chapterMarkers = markers.filter(function(m) { return m.is_chapter && m.duration_sec > 0; });
  chapterMarkers.sort(function(a, b) { return a.position_sec - b.position_sec; });

  // Match chapter positions with brief blocks (by closest start time)
  var blockInfo = []; // { start, end, name, color }
  for (var chi = 0; chi < chapterMarkers.length; chi++) {
    var ch = chapterMarkers[chi];
    var bName = ch.name || '';
    var bColor = '';
    // Try to match with brief block by position
    if (briefSegments.length > 0) {
      var cumTime = 0;
      var bestBlock = null;
      var bestDist = Infinity;
      var seenBlocks = {};
      for (var bsi2 = 0; bsi2 < briefSegments.length; bsi2++) {
        var bs2 = briefSegments[bsi2];
        if (bs2.use !== 'TRUE' || bs2.block === 99) continue;
        if (!seenBlocks[bs2.block]) {
          seenBlocks[bs2.block] = { name: bs2.block_name || '', color: bs2.color || '', start: cumTime };
        }
        var bpIn = (bs2.tc_in || '0:0').split(':'); var bpOut = (bs2.tc_out || '0:0').split(':');
        cumTime += (parseInt(bpOut[0]) * 60 + parseFloat(bpOut[1] || 0)) - (parseInt(bpIn[0]) * 60 + parseFloat(bpIn[1] || 0));
      }
      for (var bk in seenBlocks) {
        var dist = Math.abs(seenBlocks[bk].start - ch.position_sec);
        if (dist < bestDist) { bestDist = dist; bestBlock = seenBlocks[bk]; }
      }
      if (bestBlock && bestDist < 30) { // within 30s tolerance
        bName = bestBlock.name;
        bColor = bestBlock.color;
      }
    }
    blockInfo.push({
      start: ch.position_sec,
      end: ch.position_sec + (ch.duration_sec || 0),
      name: bName,
      color: bColor,
    });
  }

  // Collect all comment markers (non-chapter) keyed by position
  var commentsByPos = {};
  for (var cmi2 = 0; cmi2 < markers.length; cmi2++) {
    var cm = markers[cmi2];
    if (cm.is_chapter || !cm.comment) continue;
    var pos = cm.position_sec;
    if (!commentsByPos[pos]) commentsByPos[pos] = [];
    commentsByPos[pos].push(cm);
  }

  var COLOR_HEX = {
    Cyan: '#00CED1', Blue: '#4A90D9', Green: '#4CAF50', Yellow: '#E6C619',
    Red: '#E34850', Magenta: '#E732E7', Orange: '#EDA63B', Purple: '#9B59B6'
  };

  // Timeline clips grouped by blocks
  html += '<div class="section"><h2>Timeline (' + clips.length + ' clips)</h2>';

  var currentBlock = -1;
  for (var ci = 0; ci < clips.length; ci++) {
    var c = clips[ci];
    // Check if we entered a new block
    for (var bi2 = 0; bi2 < blockInfo.length; bi2++) {
      if (c.timeline_start_sec >= blockInfo[bi2].start && c.timeline_start_sec < blockInfo[bi2].end && bi2 !== currentBlock) {
        currentBlock = bi2;
        var blk = blockInfo[bi2];
        var blkColor = COLOR_HEX[blk.color] || '#888';
        html += '<div style="margin:20px 0 8px;padding:8px 15px;background:' + blkColor + '22;border-left:4px solid ' + blkColor + ';border-radius:4px">';
        html += '<strong style="color:' + blkColor + '">' + esc(blk.name || 'Block ' + (bi2 + 1)) + '</strong>';
        html += '<span style="color:#888;margin-left:10px">' + fmtTC(blk.start) + ' — ' + fmtTC(blk.end) + '</span>';
        html += '</div>';
        break;
      }
    }

    // Find markers near this clip
    var clipEnd = c.timeline_start_sec + c.duration_sec;
    var clipNotes = [];
    var clipSlash = [];
    for (var pos in commentsByPos) {
      var p = parseFloat(pos);
      if (p >= c.timeline_start_sec && p < clipEnd) {
        var mks = commentsByPos[pos];
        for (var mki = 0; mki < mks.length; mki++) {
          var mkComment = mks[mki].comment || '';
          if (mkComment.indexOf('/') === 0) {
            clipSlash.push(mkComment);
          } else {
            clipNotes.push(mkComment);
          }
        }
      }
    }

    html += '<table style="width:100%;margin-bottom:2px"><tr>';
    html += '<td style="width:30px;color:#666;font-size:11px;padding:4px 8px">' + (ci + 1) + '</td>';
    html += '<td style="width:120px;padding:4px 8px">' + esc(c.source_file) + '</td>';
    html += '<td style="width:80px;padding:4px 8px;color:#888">' + fmtTC(c.tc_in_sec) + '–' + fmtTC(c.tc_out_sec) + '</td>';
    html += '<td style="width:50px;padding:4px 8px;color:#666">' + fmtTC(c.duration_sec) + '</td>';
    html += '<td style="padding:4px 8px">';
    if (c.speaker) html += '<span class="speaker">' + esc(c.speaker) + '</span> ';
    html += '<span class="tx">' + esc(c.transcript_text || '') + '</span>';
    // Marker notes (parsed: Speaker/B-roll/Notes)
    for (var ni = 0; ni < clipNotes.length; ni++) {
      var note = clipNotes[ni];
      // Skip auto-generated segment markers (Speaker: X | transcript...)
      if (note.indexOf('Speaker:') === 0 && note.indexOf('|') > 0) continue;
      html += '<br><span style="color:#E6C619;font-size:11px">📝 ' + esc(note) + '</span>';
    }
    // / edit markers
    for (var si2 = 0; si2 < clipSlash.length; si2++) {
      html += '<br><span class="marker-inline">/ ' + esc(clipSlash[si2].substring(1).trim()) + '</span>';
    }
    html += '</td>';
    html += '</tr></table>';
  }
  html += '</div>';

  html += '</body></html>';
  return html;
}

/**
 * Apply color labels to ProjectItems via clipMap (bin items).
 *
 * KEY INSIGHT (Adobe UXP limitation):
 *   Changing a ProjectItem's color label does NOT retroactively update
 *   existing TrackItems on the timeline. Only NEW TrackItems placed after
 *   the color change inherit the updated label. (Feature request DVAPR-4217788)
 *
 * Therefore, colors MUST be applied BEFORE creating the sequence (Step 2.5
 * in buildAssembly), so that createSequenceFromMedia / insertClip creates
 * clips that already have the correct colors.
 *
 * Does NOT rename clips — file names remain as-is.
 * NOTE: Color is per-ProjectItem (source). Same source = same color everywhere.
 */
async function applyAssemblyColors(project, clipMap, segments, logger) {
  const { LABEL_COLOR_INDEX } = require('./src/shared/constants');
  if (!logger) logger = assemblyLogger;

  if (!clipMap || Object.keys(clipMap).length === 0) {
    logger.warn('No clipMap for Apply Colors');
    return 0;
  }

  // Log real Premiere color constants (diagnostic)
  try {
    if (ppro.Constants && ppro.Constants.ProjectItemColorLabel) {
      const labels = ppro.Constants.ProjectItemColorLabel;
      const entries = Object.entries(labels).map(function (e) { return e[0] + '=' + e[1]; }).join(', ');
      logger.debug('ProjectItemColorLabel: {' + entries + '}');
    }
  } catch (e) { /* ignore */ }

  let applied = 0;
  const uniqueSources = {};

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    const colorIdx = LABEL_COLOR_INDEX[seg.color];

    if (colorIdx === undefined) {
      logger.debug('  ' + seg.id + ': no color defined, skipping');
      continue;
    }

    // Find ProjectItem in clipMap (bin items)
    const rawItem = clipMap[seg.sourceFile] || clipMap[seg.sourceFile.replace(/\.[^.]+$/, '')];
    if (!rawItem) {
      logger.debug('  ' + seg.id + ': clip not found in bin for ' + seg.sourceFile);
      continue;
    }

    uniqueSources[seg.sourceFile] = { segId: seg.id, color: seg.color, idx: colorIdx };

    try {
      // Apply color via action pattern (same as assemblyBuilder.js)
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(rawItem.createSetColorLabelAction(colorIdx));
        }, 'Color: ' + seg.id);
      });
      applied++;

      // DIAGNOSTIC: Read color back to verify it was actually set
      let readBack = '?';
      try {
        readBack = await rawItem.getColorLabelIndex();
      } catch (readErr) {
        readBack = 'err:' + readErr.message;
      }

      logger.debug('  ' + seg.id + ': color=' + seg.color + '(' + colorIdx + ') readBack=' + readBack + ' src=' + seg.sourceFile);
    } catch (ex) {
      logger.warn('  Color failed ' + seg.id + ': ' + ex.message);
    }
  }

  const uniqueCount = Object.keys(uniqueSources).length;
  logger.info('Colors applied to ' + applied + ' clips (' + uniqueCount + ' unique sources)');
  return applied;
}

/**
 * Create Chapter markers at block boundaries (with duration) + per segment (point markers).
 * ALL markers are Chapter type for consistent navigation in Premiere Pro timeline.
 *
 * Uses static API: ppro.Markers.getMarkers(seq) + action-based createAddMarkerAction()
 * with Adobe URI type strings from constants.js.
 *
 * IMPORTANT:
 * - seq.getMarkers() does NOT exist in UXP — use ppro.Markers.getMarkers(seq) (static)
 * - Marker type must be Adobe URI ('com.adobe.premiereMarkers.chapter'), NOT display name
 * - Marker color: use marker.createSetColorByIndexAction(idx) — NOT createSetColorAction!
 * - Marker type: createAddMarkerAction IGNORES type param (always creates Event).
 *   Use marker.createSetTypeAction(MARKER_TYPE_CHAPTER) in a SEPARATE transaction.
 *   (confirmed via API discovery log 2026-03-09)
 */
async function createAssemblyMarkers(project, result) {
  const { MARKER_TYPE_CHAPTER, MARKER_COLOR_INDEX, TICKS_PER_SECOND } = require('./src/shared/constants');
  const seq = result.sequence;
  const segs = result.segments;
  const TIME_ZERO = ppro.TickTime.createWithSeconds(0);

  // Static API — the ONLY working way to get markers in UXP Premiere Pro
  let markersOwner;
  try {
    markersOwner = await ppro.Markers.getMarkers(seq);
  } catch (ex) {
    assemblyLogger.warn('Cannot get sequence markers: ' + ex.message);
    return;
  }

  if (!markersOwner) {
    assemblyLogger.warn('Markers object is null');
    return;
  }

  // API discovery — log available methods on markersOwner (read-only diagnostic)
  try {
    const methods = [];
    for (const k of Object.getOwnPropertyNames(Object.getPrototypeOf(markersOwner))) {
      if (typeof markersOwner[k] === 'function') methods.push(k);
    }
    assemblyLogger.debug('markersOwner methods: [' + methods.join(', ') + ']');
  } catch (e) { /* ignore */ }

  // Diagnostic logging (read-only)
  assemblyLogger.debug('Using constants: CHAPTER=' + JSON.stringify(MARKER_TYPE_CHAPTER));

  // Step 1: Group segments by block to calculate block start/duration for chapters
  const blockInfo = {}; // { blockId: { name, startSec, durationSec, color } }
  let cumTime = 0;
  for (const seg of segs) {
    if (!blockInfo[seg.block]) {
      blockInfo[seg.block] = { name: seg.blockName || ('Chapter ' + seg.block), startSec: cumTime, durationSec: 0, color: seg.color };
    }
    blockInfo[seg.block].durationSec += seg.duration;
    cumTime += seg.duration;
  }

  // Step 2: Build marker list — chapters with FULL BLOCK DURATION, comments per segment
  const markerList = [];
  let currentTime = 0;

  for (let i = 0; i < segs.length; i++) {
    const seg = segs[i];

    // Chapter marker at block boundaries — spanning full block duration
    if (seg.isChapter) {
      const block = blockInfo[seg.block];
      markerList.push({
        name: block.name,
        type: MARKER_TYPE_CHAPTER,
        startSec: block.startSec,
        durationSec: block.durationSec,
        comment: '',
        markerColor: block.color
      });
      assemblyLogger.debug('  Chapter: "' + block.name + '" at ' + block.startSec.toFixed(1) + 's, dur=' + block.durationSec.toFixed(1) + 's');
    }

    // Chapter marker per segment (point marker, no duration)
    const comment = [
      seg.speaker ? 'Speaker: ' + seg.speaker : '',
      seg.transcript ? seg.transcript.substring(0, 200) : '',
      seg.brollNote ? 'B-roll: ' + seg.brollNote : '',
      seg.notes ? 'Notes: ' + seg.notes : ''
    ].filter(Boolean).join(' | ');

    if (comment) {
      markerList.push({
        name: seg.segmentName || seg.id,
        type: MARKER_TYPE_CHAPTER,
        startSec: currentTime,
        durationSec: 0,
        comment: comment,
        markerColor: seg.color
      });
    }

    currentTime += seg.duration;
  }

  assemblyLogger.info('Creating ' + markerList.length + ' markers...');

  // Create markers via action-based pattern inside transaction (all Chapter type)
  let chapterCount = 0;

  try {
    project.lockedAccess(() => {
      project.executeTransaction((ca) => {
        for (const mk of markerList) {
          try {
            const mkDuration = mk.durationSec > 0
              ? ppro.TickTime.createWithSeconds(mk.durationSec)
              : TIME_ZERO;
            ca.addAction(markersOwner.createAddMarkerAction(
              mk.name,
              mk.type,
              ppro.TickTime.createWithSeconds(mk.startSec),
              mkDuration,
              mk.comment
            ));
            chapterCount++;
          } catch (ex) {
            assemblyLogger.debug('Marker action failed: ' + mk.name + ' — ' + ex.message);
          }
        }
      }, 'YTAI Assembly Markers');
    });
  } catch (batchErr) {
    assemblyLogger.warn('Batch markers failed: ' + batchErr.message + ', trying individually...');

    // Fallback: create one by one
    chapterCount = 0;
    for (const mk of markerList) {
      try {
        const mkDuration = mk.durationSec > 0
          ? ppro.TickTime.createWithSeconds(mk.durationSec)
          : TIME_ZERO;
        project.lockedAccess(() => {
          project.executeTransaction((ca) => {
            ca.addAction(markersOwner.createAddMarkerAction(
              mk.name,
              mk.type,
              ppro.TickTime.createWithSeconds(mk.startSec),
              mkDuration,
              mk.comment
            ));
          }, 'Marker: ' + mk.name);
        });
        chapterCount++;
      } catch (ex) {
        assemblyLogger.debug('  Marker failed: ' + mk.name + ' — ' + ex.message);
      }
    }
  }

  assemblyLogger.info('Markers: ' + chapterCount + ' chapters (all Chapter type)');

  // Step 3: Set marker colors (SEPARATE transaction — if this fails, markers still exist)
  // MARKER_COLOR_INDEX uses different indices than LABEL_COLOR_INDEX (clip colors)
  // Green=0, Red=1, Magenta=2, Orange=3, Yellow=4, Blue=6, Cyan=7
  let coloredCount = 0;
  try {
    const allMarkers = markersOwner.getMarkers();
    if (allMarkers && allMarkers.length > 0) {
      // API discovery — log methods on first marker (read-only)
      try {
        const m0 = allMarkers[0];
        const mMethods = [];
        for (const k of Object.getOwnPropertyNames(Object.getPrototypeOf(m0))) {
          if (typeof m0[k] === 'function') mMethods.push(k);
        }
        assemblyLogger.debug('Marker methods: [' + mMethods.join(', ') + ']');
      } catch (e) { /* ignore */ }

      // Build name → markerColorIdx map
      const nameColorMap = {};
      for (const mk of markerList) {
        if (mk.markerColor && MARKER_COLOR_INDEX[mk.markerColor] !== undefined) {
          nameColorMap[mk.name] = MARKER_COLOR_INDEX[mk.markerColor];
        }
      }

      // Apply colors in a separate transaction
      // IMPORTANT: real API method is createSetColorByIndexAction (NOT createSetColorAction!)
      project.lockedAccess(() => {
        project.executeTransaction((ca) => {
          for (const marker of allMarkers) {
            try {
              const mName = marker.getName ? marker.getName() : '';
              const colorIdx = nameColorMap[mName];
              if (colorIdx !== undefined) {
                ca.addAction(marker.createSetColorByIndexAction(colorIdx));
                coloredCount++;
              }
            } catch (e) {
              assemblyLogger.debug('  Marker color failed "' + (marker.getName ? marker.getName() : '?') + '": ' + e.message);
            }
          }
        }, 'YTAI Marker Colors');
      });
      assemblyLogger.info('Marker colors: ' + coloredCount + '/' + allMarkers.length + ' colored');

      // Step 4: Set marker TYPE to Chapter (SEPARATE transaction)
      // createAddMarkerAction ignores the type parameter — always creates Event.
      // Must use createSetTypeAction on each marker to change Event → Chapter.
      let typedCount = 0;
      try {
        project.lockedAccess(() => {
          project.executeTransaction((ca) => {
            for (const marker of allMarkers) {
              try {
                ca.addAction(marker.createSetTypeAction(MARKER_TYPE_CHAPTER));
                typedCount++;
              } catch (e) {
                assemblyLogger.debug('  Marker type failed "' + (marker.getName ? marker.getName() : '?') + '": ' + e.message);
              }
            }
          }, 'YTAI Marker Types');
        });
        assemblyLogger.info('Marker types: ' + typedCount + '/' + allMarkers.length + ' set to Chapter');
      } catch (typeErr) {
        assemblyLogger.debug('Marker type change failed (non-fatal): ' + typeErr.message);
      }
    }
  } catch (colorErr) {
    assemblyLogger.debug('Marker colors/types failed (non-fatal): ' + colorErr.message);
  }

  return { chapters: chapterCount, comments: 0 };
}

/**
 * Post-build validation for Assembly — green/yellow/red checklist like Ingest.
 */
async function validateAssemblyBuild(sequence, result, markerInfo) {
  assemblyLogger.info('=== Post-build validation ===');
  const panel = $('assembly-validation');
  const lines = [];
  let allOk = true;

  function ok(text) { lines.push('<div class="val-line"><span style="color:var(--success)">●</span> ' + escapeHtml(text) + '</div>'); }
  function warn(text) { lines.push('<div class="val-line"><span style="color:var(--warning)">●</span> ' + escapeHtml(text) + '</div>'); allOk = false; }
  function err(text) { lines.push('<div class="val-line"><span style="color:var(--error)">●</span> ' + escapeHtml(text) + '</div>'); allOk = false; }

  const expectedCount = result.clipCount || 0;

  // V1 clip count
  try {
    const v1 = await sequence.getVideoTrack(0);
    let items;
    try { items = v1.getTrackItems(1, false); } catch (ex) {
      try { items = v1.getTrackItems(); } catch (ex2) { items = []; }
    }
    if (!items) items = [];
    if (items.length >= expectedCount) ok('V1: ' + items.length + ' clips');
    else warn('V1: ' + items.length + '/' + expectedCount + ' clips');
  } catch (e) { warn('V1: check failed'); }

  // Total duration
  if (result.totalDuration > 0) {
    ok('Duration: ' + fmtTime(result.totalDuration));
  }

  // Markers
  if (markerInfo) {
    const totalMarkers = (markerInfo.chapters || 0) + (markerInfo.comments || 0);
    if (markerInfo.chapters > 0) ok('Markers: ' + markerInfo.chapters + ' chapters, ' + markerInfo.comments + ' comments');
    else if (totalMarkers > 0) warn('Markers: ' + totalMarkers + ' (no chapters)');
    else err('Markers: none created');
  }

  panel.innerHTML = lines.join('');
  panel.style.display = 'block';
  assemblyLogger.info('Validation ' + (allOk ? 'PASSED' : 'has WARNINGS'));
}

async function saveAssemblyLogs(project, clipMap, result) {
  try {
    if (project) { try { await project.save(); assemblyLogger.info('Project saved'); } catch (e) { } }

    // Build extras for debug snapshot
    const extras = {
      clipMapKeys: clipMap ? Object.keys(clipMap) : [],
      segmentOrder: result && result.segments
        ? result.segments.map(function (s) { return s.id + ' [' + s.blockName + '] ' + s.sourceFile + ' ' + s.tcIn + '-' + s.tcOut; })
        : [],
      clipCount: result ? result.clipCount : 0,
      totalDuration: result ? result.totalDuration : 0
    };

    await assemblyLogger.saveDebugBundle(assemblyState.data, project ? project.path : null, extras);
    updateLogPath('assembly', assemblyLogger.getLastSavedPath());
  } catch (err) {
    assemblyLogger.error('Failed to save assembly logs: ' + err.message);
  }
}

// ══════════════════════════════════════════════════════════════════
//  REVIEW PIPELINE
// ══════════════════════════════════════════════════════════════════

function setReviewStatus(text, type) {
  $('review-status-dot').className = 'status-dot ' + (type || 'waiting');
  $('review-status-text').textContent = text;
}

function setReviewProgress(percent, text) {
  $('review-progress-bar').style.display = 'block';
  $('review-progress-text').style.display = 'block';
  $('review-progress-fill').style.width = percent + '%';
  $('review-progress-text').textContent = text || '';
}

function hideReviewProgress() {
  $('review-progress-bar').style.display = 'none';
  $('review-progress-text').style.display = 'none';
}

/**
 * Create markers for the Review sequence.
 *
 * Two types of markers:
 * - Chapter markers at source file boundaries (groups clips)
 * - Per-segment markers with transcript, speaker, notes, cut reason
 *
 * Uses same 4-transaction pattern as createAssemblyMarkers.
 */
async function createReviewMarkers(project, result) {
  const { MARKER_TYPE_CHAPTER, MARKER_COLOR_INDEX, REVIEW_COLOR_MAP } = require('./src/shared/constants');
  const seq = result.sequence;
  const segs = result.segments;
  const TIME_ZERO = ppro.TickTime.createWithSeconds(0);

  let markersOwner;
  try {
    markersOwner = await ppro.Markers.getMarkers(seq);
  } catch (ex) {
    reviewLogger.warn('Cannot get sequence markers: ' + ex.message);
    return { chapters: 0, comments: 0 };
  }

  if (!markersOwner) {
    reviewLogger.warn('Markers object is null');
    return { chapters: 0, comments: 0 };
  }

  // Build marker list using absolute positions (_timelinePosition from buildReviewSequence)
  const clipOffsets = result.clipOffsets || {};
  const markerList = [];
  let currentSource = '';

  // Block-level chapter markers: group review segments by block, create marker at first occurrence
  // Only for blocks that have Assembly content (usedCount > 0)
  var blockFirstPos = {};  // { blockNum: { pos, name, color } }
  var blockLastPos = {};   // { blockNum: lastEndPos }
  for (var bi = 0; bi < segs.length; bi++) {
    var bseg = segs[bi];
    if (bseg.block > 0 && bseg.block !== 99 && bseg.blockName) {
      var bpos = bseg._timelinePosition != null ? bseg._timelinePosition : 0;
      var bendpos = bpos + (bseg.duration || 0);
      if (!blockFirstPos[bseg.block]) {
        blockFirstPos[bseg.block] = {
          pos: bpos,
          name: bseg.blockName,
          color: bseg.color || 'Purple'
        };
        blockLastPos[bseg.block] = bendpos;
      } else {
        if (bendpos > blockLastPos[bseg.block]) {
          blockLastPos[bseg.block] = bendpos;
        }
      }
    }
  }
  // Add block chapter markers
  for (var bk in blockFirstPos) {
    var bdata = blockFirstPos[bk];
    var bColorIdx = MARKER_COLOR_INDEX[bdata.color];
    markerList.push({
      name: bdata.name,
      type: MARKER_TYPE_CHAPTER,
      startSec: bdata.pos,
      durationSec: 0.2,
      comment: 'Block ' + bk + ' — unused segments',
      markerColor: bColorIdx !== undefined ? bColorIdx : REVIEW_COLOR_MAP.skip.markerIdx
    });
  }
  if (Object.keys(blockFirstPos).length > 0) {
    reviewLogger.info('Block chapter markers: ' + Object.keys(blockFirstPos).length + ' blocks');
  }

  for (let i = 0; i < segs.length; i++) {
    const seg = segs[i];
    const cat = getReviewCategory(seg);
    const catLabel = cat === 'cut' ? 'CUT' : cat === 'alt' ? 'ALT' : 'SKIP';
    const segPosition = seg._timelinePosition != null ? seg._timelinePosition : 0;

    // Source file chapter marker at clip offset (Ingest start of this clip)
    if (seg.sourceFile !== currentSource) {
      currentSource = seg.sourceFile;
      var srcOffset = clipOffsets[currentSource] != null ? clipOffsets[currentSource] : segPosition;

      markerList.push({
        name: 'Source: ' + currentSource,
        type: MARKER_TYPE_CHAPTER,
        startSec: srcOffset,
        durationSec: 0.2,
        comment: '',
        markerColor: REVIEW_COLOR_MAP[cat].markerIdx
      });
    }

    // Per-segment marker at absolute timeline position
    const commentParts = [
      seg.speaker ? 'Speaker: ' + seg.speaker : '',
      seg.blockName ? 'Block ' + seg.block + ': ' + seg.blockName : '',
      seg.transcript ? seg.transcript.substring(0, 150) : '',
      seg.brollNote ? 'B-roll: ' + seg.brollNote : '',
      seg.notes ? 'Notes: ' + seg.notes : ''
    ].filter(Boolean).join(' | ');

    if (commentParts) {
      markerList.push({
        name: '[' + catLabel + '] ' + seg.id,
        type: MARKER_TYPE_CHAPTER,
        startSec: segPosition,
        durationSec: 0,
        comment: commentParts.substring(0, 200),
        markerColor: REVIEW_COLOR_MAP[cat].markerIdx
      });
    }
  }

  reviewLogger.info('Creating ' + markerList.length + ' review markers...');

  // Transaction 1: Create all markers
  let chapterCount = 0;
  try {
    project.lockedAccess(() => {
      project.executeTransaction((ca) => {
        for (const mk of markerList) {
          try {
            const mkDuration = mk.durationSec > 0
              ? ppro.TickTime.createWithSeconds(mk.durationSec)
              : TIME_ZERO;
            ca.addAction(markersOwner.createAddMarkerAction(
              mk.name, mk.type,
              ppro.TickTime.createWithSeconds(mk.startSec),
              mkDuration,
              mk.comment
            ));
            chapterCount++;
          } catch (ex) {
            reviewLogger.debug('Marker action failed: ' + mk.name + ' — ' + ex.message);
          }
        }
      }, 'YTAI Review Markers');
    });
  } catch (batchErr) {
    reviewLogger.warn('Batch markers failed: ' + batchErr.message + ', trying individually...');
    chapterCount = 0;
    for (const mk of markerList) {
      try {
        const mkDuration = mk.durationSec > 0
          ? ppro.TickTime.createWithSeconds(mk.durationSec)
          : TIME_ZERO;
        project.lockedAccess(() => {
          project.executeTransaction((ca) => {
            ca.addAction(markersOwner.createAddMarkerAction(
              mk.name, mk.type,
              ppro.TickTime.createWithSeconds(mk.startSec),
              mkDuration,
              mk.comment
            ));
          }, 'Marker: ' + mk.name);
        });
        chapterCount++;
      } catch (ex) {
        reviewLogger.debug('  Marker failed: ' + mk.name + ' — ' + ex.message);
      }
    }
  }

  reviewLogger.info('Markers: ' + chapterCount + ' created');

  // Transaction 2: Set marker colors
  let coloredCount = 0;
  try {
    const allMarkers = markersOwner.getMarkers();
    if (allMarkers && allMarkers.length > 0) {
      const nameColorMap = {};
      for (const mk of markerList) {
        if (mk.markerColor !== undefined) {
          nameColorMap[mk.name] = mk.markerColor;
        }
      }

      project.lockedAccess(() => {
        project.executeTransaction((ca) => {
          for (const marker of allMarkers) {
            try {
              const mName = marker.getName ? marker.getName() : '';
              const colorIdx = nameColorMap[mName];
              if (colorIdx !== undefined) {
                ca.addAction(marker.createSetColorByIndexAction(colorIdx));
                coloredCount++;
              }
            } catch (e) {
              reviewLogger.debug('  Marker color failed: ' + e.message);
            }
          }
        }, 'YTAI Review Marker Colors');
      });
      reviewLogger.info('Marker colors: ' + coloredCount + '/' + allMarkers.length);

      // Transaction 3: Set marker type to Chapter
      let typedCount = 0;
      try {
        project.lockedAccess(() => {
          project.executeTransaction((ca) => {
            for (const marker of allMarkers) {
              try {
                ca.addAction(marker.createSetTypeAction(MARKER_TYPE_CHAPTER));
                typedCount++;
              } catch (e) {
                reviewLogger.debug('  Marker type failed: ' + e.message);
              }
            }
          }, 'YTAI Review Marker Types');
        });
        reviewLogger.info('Marker types: ' + typedCount + '/' + allMarkers.length + ' set to Chapter');
      } catch (typeErr) {
        reviewLogger.debug('Marker type change failed (non-fatal): ' + typeErr.message);
      }
    }
  } catch (colorErr) {
    reviewLogger.debug('Marker colors/types failed (non-fatal): ' + colorErr.message);
  }

  return { chapters: chapterCount, comments: 0 };
}

/**
 * Get clip durations from the Ingest sequence ({project}_1_Ingest).
 * Reads V1 TrackItems and returns { filename: durationSec }.
 */
async function getClipDurationsFromIngest(project, projectName, logger) {
  var seqName = projectName + '_1_Ingest';
  logger.info('Looking for Ingest sequence: ' + seqName);

  var seqItem = await findProjectItemByName(project, seqName, logger);
  if (!seqItem) {
    logger.warn('Ingest sequence "' + seqName + '" not found');
    return null;
  }

  var sequence = null;
  try {
    sequence = await project.openSequence(seqItem.guid || seqItem);
  } catch (e) {
    logger.warn('Cannot open Ingest sequence: ' + e.message);
    return null;
  }
  if (!sequence) {
    logger.warn('openSequence returned null for ' + seqName);
    return null;
  }

  var durations = {};
  try {
    var v0 = await sequence.getVideoTrack(0);
    var items = null;
    try { items = v0.getTrackItems(1, false); } catch (ex) { }
    if (!items) try { items = v0.getTrackItems(); } catch (ex) { }
    if (!items) items = [];

    for (var i = 0; i < items.length; i++) {
      var ti = items[i];
      var projItem = await ti.getProjectItem();
      var name = projItem ? projItem.name : (await ti.getName());
      var dur = await ti.getDuration();
      var durSec = tickSec(dur);
      if (name && durSec > 0) {
        durations[name] = durSec;
      }
    }
    logger.info('Clip durations from Ingest: ' + Object.keys(durations).length + ' clips');
    for (var fn in durations) {
      logger.debug('  ' + fn + ': ' + durations[fn].toFixed(1) + 's');
    }
  } catch (e) {
    logger.warn('Failed to read Ingest TrackItems: ' + e.message);
    return null;
  }
  return durations;
}

/**
 * Fallback: compute clip durations from brief segments.
 * Uses max(outSec) per unique sourceFile.
 */
function getClipDurationsFromBrief(segments) {
  var durations = {};
  for (var i = 0; i < segments.length; i++) {
    var s = segments[i];
    var f = s.sourceFile;
    if (f && s.outSec > (durations[f] || 0)) {
      durations[f] = s.outSec;
    }
  }
  return durations;
}

/**
 * Build Review sequence from loaded edit brief.
 * Uses complement approach: Review = Ingest minus Assembly.
 */
async function buildReview() {
  if (assemblyState.segments.length === 0) {
    reviewLogger.error('No brief loaded — load Edit Brief first');
    return;
  }

  reviewLogger.clear();
  $('review-log-panel').innerHTML = '';
  $('review-validation').style.display = 'none';
  setReviewStatus('Building review...', 'waiting');

  let clipMap = null;
  let result = null;

  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');

    const totalSteps = 6;
    let step = 0;
    const startTime = Date.now();

    reviewLogger.info('=== REVIEW BUILD START ===');
    reviewLogger.info('Project: ' + assemblyState.projectName);

    var stepTimings = [];
    var stepStart;

    // Step 1: Save backup
    step++;
    stepStart = Date.now();
    setReviewProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Saving backup...');
    try { await project.save(); reviewLogger.info('Project saved'); } catch (e) { }
    stepTimings.push('save ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 2: Scan project for clips + get clip durations
    step++;
    stepStart = Date.now();
    setReviewProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Scanning project clips...');
    reviewLogger.info('=== Step 2: Scanning project for clips ===');
    const scanResult = await validateIngestState(project, assemblyState.segments, reviewLogger);
    clipMap = scanResult.clipMap;

    let clipDurations = await getClipDurationsFromIngest(project, assemblyState.projectCode || assemblyState.projectName, reviewLogger);
    if (!clipDurations || Object.keys(clipDurations).length === 0) {
      clipDurations = getClipDurationsFromBrief(assemblyState.segments);
      reviewLogger.warn('Using brief-based durations (Ingest sequence not found)');
    }
    stepTimings.push('scan ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 3: Build Review sequence
    step++;
    stepStart = Date.now();
    setReviewProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Building Review sequence...');
    reviewLogger.info('=== Step 3: Building Review sequence ===');
    var reviewOpts = {
      producerSpeaker: (assemblyState.data && assemblyState.data.producerSpeaker) || '',
      assemblyBlocks: assemblyState.blocks || [],
      fps: (assemblyState.projectSettings && assemblyState.projectSettings.fps) || 25
    };
    // Build scene map from ingest data (clip → scene)
    var sceneMap = null;
    if (ingestState.data && ingestState.data.clips) {
      var hasScenes = ingestState.data.clips.some(function(c) { return c.scene; });
      if (hasScenes) {
        sceneMap = {};
        ingestState.data.clips.forEach(function(c) {
          var scene = c.scene || 'default';
          if (!sceneMap[scene]) sceneMap[scene] = [];
          sceneMap[scene].push(c.filename || (c.clip_id + '.MP4'));
        });
        reviewLogger.info('Per-scene Review: ' + Object.keys(sceneMap).join(', '));
      }
    }
    result = await buildReviewSequence(project, clipMap, assemblyState.segments, assemblyState.projectCode || assemblyState.projectName, reviewLogger, clipDurations, reviewOpts, assemblyState.briefVersion, sceneMap);

    if (!result.sequence) {
      reviewLogger.info('Review sequence not created (no unused segments)');
      setReviewProgress(100, 'Complete — no unused segments');
      setReviewStatus('No unused segments', 'ready');
      return;
    }
    stepTimings.push('build ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 4: Create review markers
    step++;
    stepStart = Date.now();
    setReviewProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Markers...');
    reviewLogger.info('=== Step 4: Review Markers ===');
    let markerInfo = null;
    try {
      markerInfo = await createReviewMarkers(project, result);
    } catch (markerErr) {
      reviewLogger.warn('Markers step failed (non-fatal): ' + markerErr.message);
    }
    stepTimings.push('markers ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 5: Activate + save + validate
    step++;
    stepStart = Date.now();
    setReviewProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Validating...');
    if (result.sequence) {
      await project.setActiveSequence(result.sequence);
      try { await project.openSequence(result.sequence.guid || result.sequence); } catch (e) { }
    }
    try { await project.save(); } catch (e) { }

    if (result.sequence) {
      await validateReviewBuild(result.sequence, result, markerInfo);
    }
    stepTimings.push('validate ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 6: Generate + import Review captions & transcript SRTs
    step++;
    stepStart = Date.now();
    setReviewProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Captions...');
    reviewLogger.info('=== Step 6: Review Captions ===');

    var reviewProjectCode = assemblyState.projectCode || assemblyState.projectName;
    if (result.segments && result.segments.length > 0 && assemblyState.filePath) {
      var reviewBriefDir = assemblyState.filePath.replace(/[/\\][^/\\]+$/, '');
      var reviewSourceDir = reviewBriefDir.replace(/[/\\]Setup$/, '');
      try {
        // Ensure Transcription subdirs exist
        var reviewTranscriptionEntry = await uxpfs.getEntryWithUrl('file://' + reviewSourceDir + '/Transcription');
        var reviewTranscriptsFolderEntry = await ensureSubfolder(reviewTranscriptionEntry, 'transcripts', reviewLogger);
        var reviewCaptionsFolderEntry = await ensureSubfolder(reviewTranscriptionEntry, 'captions', reviewLogger);

        // 1. Transcript SRT (absolute positioning matching Ingest layout)
        var reviewTranscriptSrt = generateTranscriptSrt(result.segments, result.clipOffsets);
        if (reviewTranscriptSrt) {
          var reviewTrFileName = reviewProjectCode + '_3_Review_transcript.srt';
          var reviewTrFile = await reviewTranscriptsFolderEntry.createFile(reviewTrFileName, { overwrite: true });
          await reviewTrFile.write(reviewTranscriptSrt);
          reviewLogger.info('Transcript SRT written: Transcription/transcripts/' + reviewTrFileName);
        }

        // 2. Captions SRT (word-grouped, absolute positioning)
        var reviewCaptionsSrt = generateCaptionsSrt(result.segments, 6, result.clipOffsets);
        if (reviewCaptionsSrt) {
          var reviewCapFileName = reviewProjectCode + '_3_Review_captions.srt';
          var reviewCapFile = await reviewCaptionsFolderEntry.createFile(reviewCapFileName, { overwrite: true });
          await reviewCapFile.write(reviewCaptionsSrt);
          reviewLogger.info('Captions SRT written: Transcription/captions/' + reviewCapFileName);
        }
      } catch (reviewSrtErr) {
        reviewLogger.warn('Review SRT write failed (non-fatal): ' + reviewSrtErr.message);
      }
    }

    // Import both SRTs to 02_Transcripts bin
    await importCaptionsSrt(project, assemblyState.filePath, reviewProjectCode, '3_Review', 'Review Captions', reviewLogger);
    await importCaptionsSrt(project, assemblyState.filePath, reviewProjectCode, '3_Review', 'Review Transcript', reviewLogger, 'transcript');
    stepTimings.push('captions ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    setReviewProgress(100, 'Complete!');
    reviewLogger.info('=== REVIEW BUILD COMPLETE (' + elapsed + 's) ===');
    reviewLogger.info('Timing: ' + stepTimings.join(' | '));
    reviewLogger.info('Review: ' + result.clipCount + ' clips on V1, total=' + (result.totalDuration || 0).toFixed(1) + 's');
    $('btn-build-review').classList.add('btn-done');

    setReviewStatus('Review built (' + result.clipCount + ' clips)', 'ready');
    updateLogPath('review', reviewLogger.getLastSavedPath());

  } catch (err) {
    reviewLogger.error('REVIEW BUILD FAILED: ' + err.message);
    if (err.stack) reviewLogger.debug(err.stack);
    setReviewStatus('Build failed: ' + err.message, 'error');
  }
}

/**
 * Post-build validation for Review sequence.
 */
async function validateReviewBuild(sequence, result, markerInfo) {
  reviewLogger.info('=== Post-build validation ===');
  const panel = $('review-validation');
  const lines = [];

  function ok(text) { lines.push('<div class="val-line"><span style="color:var(--success)">\u25CF</span> ' + escapeHtml(text) + '</div>'); }
  function warn(text) { lines.push('<div class="val-line"><span style="color:var(--warning)">\u25CF</span> ' + escapeHtml(text) + '</div>'); }

  const expectedCount = result.clipCount || 0;

  // V1 clip count
  try {
    const v1 = await sequence.getVideoTrack(0);
    let items;
    try { items = v1.getTrackItems(1, false); } catch (ex) {
      try { items = v1.getTrackItems(); } catch (ex2) { items = []; }
    }
    if (!items) items = [];
    if (items.length >= expectedCount) ok('V1: ' + items.length + ' clips');
    else warn('V1: ' + items.length + '/' + expectedCount + ' clips');
  } catch (e) { warn('V1: check failed'); }

  // Duration
  if (result.totalDuration > 0) {
    ok('Duration: ' + fmtTime(result.totalDuration));
  }

  // Markers
  if (markerInfo) {
    if (markerInfo.chapters > 0) ok('Markers: ' + markerInfo.chapters + ' created');
    else warn('Markers: none created');
  }

  panel.innerHTML = lines.join('');
  panel.style.display = 'block';
}

// ══════════════════════════════════════════════════════════════════
//  SCREEN CUES PIPELINE
// ══════════════════════════════════════════════════════════════════

/**
 * Generate Screen Cues PNGs via Python script (v1.9.4).
 *
 * Uses a permanent run_generate.command (already chmod +x in repo).
 * Passes brief path via /tmp/ytai_screen_cues_brief.txt.
 * Polls for a .done marker file, then re-counts generated PNGs.
 * Fallback: copies Python command to clipboard if shell.openPath() fails.
 */
async function generateScreenPngs() {
  if (!assemblyState.screens || assemblyState.screens.length === 0) {
    screensLogger.error('No screens in loaded brief');
    return;
  }
  if (!assemblyState.filePath) {
    screensLogger.error('No brief path — load brief first');
    return;
  }

  $('btn-generate-pngs').setAttribute('disabled', 'true');
  screensLogger.info('=== GENERATE SCREEN CUES PNGs ===');
  setScreensStatus('Generating PNGs...', 'waiting');

  var briefPath = assemblyState.filePath;
  var briefDir = briefPath.replace(/[/\\][^/\\]+$/, '');
  var pngDirPath = briefDir + '/screen_cues';

  // Resolve permanent script path relative to plugin folder
  var pluginFolder = await uxpfs.getPluginFolder();
  var pluginDir = pluginFolder.nativePath.replace(/\/$/, '');
  var cmdPath = pluginDir + '/../0504_screen_cues/run_generate.command';
  var scriptPath = pluginDir + '/../0504_screen_cues/generate_screen_cues_png.py';

  // Ensure screen_cues/ directory exists
  try {
    await uxpfs.getEntryWithUrl('file://' + pngDirPath);
  } catch (e) {
    try {
      var parentFolder = await uxpfs.getEntryWithUrl('file://' + briefDir);
      await parentFolder.createFolder('screen_cues');
      screensLogger.debug('Created screen_cues/ directory');
    } catch (mkErr) {
      screensLogger.warn('Could not create screen_cues/: ' + mkErr.message);
    }
  }

  // Archive existing PNGs before regenerating
  try {
    await archiveFiles(pngDirPath, function(name) {
      return name.endsWith('.png');
    }, screensLogger);
  } catch (archiveErr) {
    screensLogger.debug('PNG archive skipped: ' + archiveErr.message);
  }

  // Write brief path to temp file (communication channel UXP → bash script)
  try {
    var tmpFolder = await uxpfs.getEntryWithUrl('file:///tmp');
    var tmpFile = await tmpFolder.createFile('ytai_screen_cues_brief.txt', { overwrite: true });
    await tmpFile.write(briefPath);
    screensLogger.debug('Wrote brief path to /tmp/ytai_screen_cues_brief.txt');
  } catch (tmpErr) {
    screensLogger.error('Failed to write temp file: ' + tmpErr.message);
    setScreensStatus('Failed to write temp file', 'error');
    return;
  }

  // Launch permanent run_generate.command (already chmod +x)
  try {
    var uxpShell = require('uxp').shell;
    await uxpShell.openPath(cmdPath);
    screensLogger.info('Launched run_generate.command via shell.openPath');
  } catch (shellErr) {
    screensLogger.warn('shell.openPath failed: ' + shellErr.message);
    // Cleanup temp file
    try {
      var tmpClean = await uxpfs.getEntryWithUrl('file:///tmp/ytai_screen_cues_brief.txt');
      await tmpClean.delete();
    } catch (e) { }
    // Fallback: copy command to clipboard
    var pyCmd = 'python3 "' + scriptPath + '" --brief "' + briefPath + '"';
    try {
      await navigator.clipboard.writeText(pyCmd);
      screensLogger.info('Fallback: Python command copied to clipboard');
    } catch (e) { }
    setScreensStatus('shell.openPath failed — command copied to clipboard. Run in Terminal.', 'error');
    $('btn-generate-pngs').removeAttribute('disabled');
    return;
  }

  // Poll for .done marker (2s interval, 60s timeout)
  screensLogger.info('Waiting for Python to finish (polling .done, timeout 60s)...');
  var donePath = pngDirPath + '/.done';
  var found = false;
  for (var attempt = 0; attempt < 30; attempt++) {
    await new Promise(function (resolve) { setTimeout(resolve, 2000); });
    try {
      var doneEntry = await uxpfs.getEntryWithUrl('file://' + donePath);
      if (doneEntry) {
        found = true;
        break;
      }
    } catch (e) {
      // Not yet — continue polling
    }
    setScreensStatus('Generating PNGs... (' + ((attempt + 1) * 2) + 's)', 'waiting');
  }

  if (!found) {
    screensLogger.warn('Timeout waiting for .done — PNGs may still be generating');
    setScreensStatus('Timeout (60s) — check Terminal. PNGs may still be generating.', 'error');
    $('btn-generate-pngs').removeAttribute('disabled');
    return;
  }

  // Cleanup .done marker
  try {
    var pngFolderClean = await uxpfs.getEntryWithUrl('file://' + pngDirPath);
    var cleanEntries = await pngFolderClean.getEntries();
    for (var ci = 0; ci < cleanEntries.length; ci++) {
      if (cleanEntries[ci].name === '.done') {
        await cleanEntries[ci].delete();
      }
    }
    screensLogger.debug('Cleaned up .done marker');
  } catch (cleanErr) {
    screensLogger.debug('Cleanup skipped: ' + cleanErr.message);
  }

  // Count generated PNGs
  try {
    var pngFolderFinal = await uxpfs.getEntryWithUrl('file://' + pngDirPath);
    var finalEntries = await pngFolderFinal.getEntries();
    var pngCount = finalEntries.filter(function (e) { return e.name.endsWith('.png'); }).length;
    screensLogger.info('PNG generation complete: ' + pngCount + ' PNGs in screen_cues/');
    setScreensStatus(pngCount + ' PNGs generated. Ready to Build Screen Cues.', 'ready');
  } catch (countErr) {
    screensLogger.warn('Could not count PNGs: ' + countErr.message);
    setScreensStatus('PNGs generated (count unknown). Ready to Build Screen Cues.', 'ready');
  }

  screensLogger.info('=== GENERATE PNGs COMPLETE ===');
  $('btn-generate-pngs').removeAttribute('disabled');
  $('btn-generate-pngs').classList.add('btn-done');

  // Save debug bundle
  await screensLogger.saveDebugBundle(assemblyState.data, null, { operation: 'generate_pngs' });
}

/**
 * Standalone Screen Cues pipeline — creates _4_ScreenCues sequence (v1.9.3).
 *
 * V1 = exact copy of Assembly (same segments, order, trims, colors)
 * V2 = PNG overlays at screen cue positions (if PNGs available)
 * Markers = Orange Chapter markers at screen cue positions
 * SRT = generated in-memory, written to disk, imported to 02_Transcripts
 *
 * Does NOT depend on Assembly sequence — only needs brief + imported clips.
 *
 * Prerequisites:
 *   - Brief loaded with screens[] (via Load Edit Brief)
 *   - Clips imported (via INGEST — 00_Source bin exists)
 *   - (Optional) PNGs generated via generate_screen_cues_png.py
 *
 * 5 steps:
 *   1. Scan clips from 00_Source
 *   2. Build ScreenCues sequence (V1 Assembly copy + V2 PNGs + SRT)
 *   3. Create markers (separate step — same 4-transaction pattern as Assembly)
 *   4. Write SRT file to brief directory
 *   5. Import Screen Cues SRT to 02_Transcripts bin
 */
/**
 * Organize project bins after Pre-Edit build.
 * Moves Ingest + Assembly sequences to "99_Archive" bin.
 * Keeps Review + Pre-Edit visible at root.
 */
async function organizeBins(project, projectCode, logger) {
  try {
    var rootItem = await project.getRootItem();
    var allItems = await rootItem.getItems();

    // Find or create 99_Archive bin
    var archiveBin = null;
    for (var i = 0; i < allItems.length; i++) {
      if (allItems[i].name === '99_Archive') {
        archiveBin = ppro.FolderItem.cast(allItems[i]);
        break;
      }
    }
    if (!archiveBin) {
      project.lockedAccess(function() {
        project.executeTransaction(function(ca) {
          ca.addAction(rootItem.createBinAction('99_Archive', true));
        }, 'Create 99_Archive bin');
      });
      allItems = await rootItem.getItems();
      for (var i = 0; i < allItems.length; i++) {
        if (allItems[i].name === '99_Archive') {
          archiveBin = ppro.FolderItem.cast(allItems[i]);
          break;
        }
      }
    }
    if (!archiveBin) {
      if (logger) logger.debug('Could not create 99_Archive bin');
      return;
    }

    // Move Ingest and Assembly sequences to archive
    allItems = await rootItem.getItems();
    var moved = 0;
    for (var j = 0; j < allItems.length; j++) {
      var itemName = allItems[j].name;
      if (itemName.indexOf('_1_Ingest') !== -1 || itemName.indexOf('_2_Assembly') !== -1) {
        // Cast to ProjectItem for full API access
        var castItem = null;
        try { castItem = ppro.ProjectItem.cast(allItems[j]); } catch (e) { /* */ }
        var moveTarget = castItem || allItems[j];
        var didMove = false;
        if (typeof moveTarget.createMoveBinItemAction === 'function') {
          try {
            project.lockedAccess(function() {
              project.executeTransaction(function(ca) {
                ca.addAction(moveTarget.createMoveBinItemAction(archiveBin));
              }, 'Archive: ' + itemName);
            });
            didMove = true;
          } catch (e) { /* */ }
        }
        if (!didMove && typeof moveTarget.moveBin === 'function') {
          try { moveTarget.moveBin(archiveBin); didMove = true; } catch (e) { /* */ }
        }
        if (didMove) {
          moved++;
          if (logger) logger.info('Archived bin item: ' + itemName);
        } else {
          if (logger) logger.debug('Could not move ' + itemName + ' — no move API available');
        }
      }
    }
    if (logger && moved > 0) logger.info('Bin organization: ' + moved + ' item(s) moved to 99_Archive');
  } catch (orgErr) {
    if (logger) logger.debug('organizeBins: ' + orgErr.message);
  }
}

/**
 * Reload last Pre-Edit state from pre-edit_versions/latest_state.json.
 * Restores brief state so user can click "Build Pre-Edit" without re-running all stages.
 */
async function buildScreenCuesPipeline() {
  if (!assemblyState.screens || assemblyState.screens.length === 0) {
    screensLogger.error('No screens in loaded brief');
    return;
  }

  setScreensStatus('Building screen cues...', 'waiting');
  $('screens-validation').style.display = 'none';

  var totalSteps = 5;
  var step = 0;
  var startTime = Date.now();

  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');
    screensLogger.setProjectInfo(project.name, project.path);
    screensLogger.setBriefInfo(assemblyState.filePath, assemblyState.projectName);

    screensLogger.info('=== SCREEN CUES BUILD START ===');
    screensLogger.info('Screens: ' + assemblyState.screens.length + ', Project: ' + assemblyState.projectName);

    // Archive existing _4_PreEdit sequence before creating new one
    try {
      var rootItem = await project.getRootItem();
      var rootItems = await rootItem.getItems();

      // Introspect first item to discover available methods
      if (rootItems.length > 0) {
        var sampleItem = rootItems[0];
        var itemMethods = [];
        for (var mk in sampleItem) {
          if (typeof sampleItem[mk] === 'function') itemMethods.push(mk);
        }
        screensLogger.debug('ProjectItem methods: [' + itemMethods.join(', ') + ']');

        // Also try casting to ProjectItem
        try {
          var castItem = ppro.ProjectItem.cast(sampleItem);
          if (castItem) {
            var castMethods = [];
            for (var ck in castItem) {
              if (typeof castItem[ck] === 'function') castMethods.push(ck);
            }
            screensLogger.debug('ProjectItem.cast methods: [' + castMethods.join(', ') + ']');
          }
        } catch (castErr) {
          screensLogger.debug('ProjectItem.cast not available: ' + castErr.message);
        }
      }

      // Find or create 99_Archive bin
      var archiveBin = null;
      for (var abi = 0; abi < rootItems.length; abi++) {
        if (rootItems[abi].name === '99_Archive') {
          archiveBin = ppro.FolderItem.cast(rootItems[abi]);
          break;
        }
      }
      if (!archiveBin) {
        project.lockedAccess(function() {
          project.executeTransaction(function(ca) {
            ca.addAction(rootItem.createBinAction('99_Archive', true));
          }, 'Create 99_Archive bin');
        });
        rootItems = await rootItem.getItems();
        for (var abi2 = 0; abi2 < rootItems.length; abi2++) {
          if (rootItems[abi2].name === '99_Archive') {
            archiveBin = ppro.FolderItem.cast(rootItems[abi2]);
            break;
          }
        }
      }

      // Find and archive old _4_PreEdit sequences (and old _4_ScreenCues)
      rootItems = await rootItem.getItems();
      for (var ai = 0; ai < rootItems.length; ai++) {
        var itemName = rootItems[ai].name;
        var isPreEdit = itemName.indexOf('_4_PreEdit') !== -1 && itemName.indexOf('_4_PreEdit_v') === -1;
        var isOldScreenCues = itemName.indexOf('_4_ScreenCues') !== -1;
        if (isPreEdit || isOldScreenCues) {
          // Cast to ProjectItem for full API access
          var castPI = null;
          try { castPI = ppro.ProjectItem.cast(rootItems[ai]); } catch (e) { /* */ }
          var targetItem = castPI || rootItems[ai];

          var archiveName = itemName + '_v' + versionTimestamp();

          // Try rename via multiple approaches
          var renamed = false;
          // Approach 1: createSetNameAction (like marker API pattern)
          if (!renamed && typeof targetItem.createSetNameAction === 'function') {
            try {
              project.lockedAccess(function() {
                project.executeTransaction(function(ca) {
                  ca.addAction(targetItem.createSetNameAction(archiveName));
                }, 'Rename: ' + itemName);
              });
              screensLogger.info('Renamed (setName): ' + itemName + ' → ' + archiveName);
              renamed = true;
            } catch (e) { screensLogger.debug('createSetNameAction failed: ' + e.message); }
          }
          // Approach 2: createRenameAction
          if (!renamed && typeof targetItem.createRenameAction === 'function') {
            try {
              project.lockedAccess(function() {
                project.executeTransaction(function(ca) {
                  ca.addAction(targetItem.createRenameAction(archiveName));
                }, 'Rename: ' + itemName);
              });
              screensLogger.info('Renamed (rename): ' + itemName + ' → ' + archiveName);
              renamed = true;
            } catch (e) { screensLogger.debug('createRenameAction failed: ' + e.message); }
          }
          // Approach 3: Direct name property
          if (!renamed) {
            try {
              project.lockedAccess(function() {
                project.executeTransaction(function(ca) {
                  targetItem.name = archiveName;
                }, 'Rename: ' + itemName);
              });
              if (targetItem.name === archiveName) {
                screensLogger.info('Renamed (direct): ' + itemName + ' → ' + archiveName);
                renamed = true;
              }
            } catch (e) { screensLogger.debug('Direct name set failed: ' + e.message); }
          }
          if (!renamed) {
            screensLogger.debug('Could not rename ' + itemName + ' — no rename API available');
          }

          // Try move to 99_Archive
          if (archiveBin) {
            var moved = false;
            if (!moved && typeof targetItem.createMoveBinItemAction === 'function') {
              try {
                project.lockedAccess(function() {
                  project.executeTransaction(function(ca) {
                    ca.addAction(targetItem.createMoveBinItemAction(archiveBin));
                  }, 'Archive: ' + itemName);
                });
                screensLogger.info('Moved to 99_Archive: ' + itemName);
                moved = true;
              } catch (e) { screensLogger.debug('createMoveBinItemAction failed: ' + e.message); }
            }
            if (!moved && typeof targetItem.moveBin === 'function') {
              try {
                targetItem.moveBin(archiveBin);
                screensLogger.info('Moved (moveBin): ' + itemName);
                moved = true;
              } catch (e) { screensLogger.debug('moveBin failed: ' + e.message); }
            }
            if (!moved) {
              screensLogger.debug('Could not move ' + itemName + ' — no move API available');
            }
          }
        }
      }
    } catch (archErr) {
      screensLogger.debug('Pre-build archive: ' + archErr.message);
    }

    var stepTimings = [];
    var stepStart;

    // Debug: list all screens being processed
    for (var si = 0; si < assemblyState.screens.length; si++) {
      var scr = assemblyState.screens[si];
      screensLogger.debug('  ' + scr.id + ': type=' + scr.type +
        ', seg=' + scr.segmentId + ', title="' + (scr.title || '').substring(0, 30) + '"');
    }

    // Step 1: Scan clips
    step++;
    stepStart = Date.now();
    setScreensProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Scanning clips...');
    screensLogger.info('=== Step 1: Scanning project clips ===');
    var scanResult = await validateIngestState(project, assemblyState.segments, screensLogger);
    var clipMap = scanResult.clipMap;
    screensLogger.info('clipMap: ' + Object.keys(clipMap).length + ' clips found');

    // Pre-flight: check for screen_cues PNGs on disk
    var pngFiles = null;
    if (assemblyState.filePath) {
      var briefDir = assemblyState.filePath.replace(/[/\\][^/\\]+$/, '');
      var pngDirPath = briefDir + '/screen_cues';
      try {
        var pngFolder = await uxpfs.getEntryWithUrl('file://' + pngDirPath);
        if (pngFolder) {
          var pngEntries = await pngFolder.getEntries();
          pngFiles = pngEntries.filter(function (e) { return e.name.endsWith('.png'); })
            .map(function (e) { return e.name; });
          screensLogger.info('PNG pre-flight: ' + pngFiles.length + ' PNGs found in screen_cues/');
        }
      } catch (e) {
        screensLogger.info('PNG pre-flight: screen_cues/ folder not found');
        screensLogger.info('  → Run: python generate_screen_cues_png.py --brief ' + assemblyState.filePath);
      }
    }

    // Create or find 01_ScreenCues bin for PNG imports
    var screenCuesBin = null;
    try {
      var rootItem = await project.getRootItem();
      var allItems = await rootItem.getItems();
      for (var bi = 0; bi < allItems.length; bi++) {
        if (allItems[bi].name === SCREEN_CUES_BIN_NAME) {
          screenCuesBin = ppro.FolderItem.cast(allItems[bi]);
          screensLogger.info('Found existing bin: ' + SCREEN_CUES_BIN_NAME);
          break;
        }
      }
      if (!screenCuesBin) {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(rootItem.createBinAction(SCREEN_CUES_BIN_NAME, true));
          }, 'Create ' + SCREEN_CUES_BIN_NAME + ' bin');
        });
        // Re-fetch to get created bin
        allItems = await rootItem.getItems();
        for (var bi = 0; bi < allItems.length; bi++) {
          if (allItems[bi].name === SCREEN_CUES_BIN_NAME) {
            screenCuesBin = ppro.FolderItem.cast(allItems[bi]);
            break;
          }
        }
        screensLogger.info('Created bin: ' + SCREEN_CUES_BIN_NAME);
      }
    } catch (binErr) {
      screensLogger.warn('Could not create ' + SCREEN_CUES_BIN_NAME + ' bin: ' + binErr.message + ' — PNGs will import to root');
    }

    stepTimings.push('scan ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 2: Build ScreenCues sequence (V1 Assembly copy + V2 PNGs + markers + SRT)
    step++;
    stepStart = Date.now();
    setScreensProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Building ScreenCues sequence...');
    screensLogger.info('=== Step 2: Building Screen Cues sequence (v1.9.3) ===');
    var screenResult = await buildScreenCues(
      project, assemblyState.screens, assemblyState.segments, clipMap,
      assemblyState.projectCode || assemblyState.projectName, screensLogger, assemblyState.filePath, pngFiles, screenCuesBin, assemblyState.projectSettings
    );
    screensLogger.info('Result: V1=' + screenResult.clips + ' clips, V2=' + screenResult.overlays + ' overlays, ' +
      screenResult.markers + ' markers, ' + screenResult.skipped + ' skipped, ' +
      'total=' + screenResult.totalDuration.toFixed(1) + 's');
    if (screenResult.warnings.length > 0) {
      for (var wi = 0; wi < screenResult.warnings.length; wi++) {
        screensLogger.warn('  ' + screenResult.warnings[wi]);
      }
    }

    stepTimings.push('build ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 3: Create markers (separate step — same pattern as Assembly)
    step++;
    stepStart = Date.now();
    setScreensProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Markers...');
    screensLogger.info('=== Step 3: Create Screen Cues markers ===');
    var markerInfo = null;
    try {
      markerInfo = await createScreenCuesMarkers(project, screenResult);
    } catch (markerErr) {
      screensLogger.warn('Markers step failed (non-fatal): ' + markerErr.message);
    }
    stepTimings.push('markers ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 4: Write SRT files to brief directory
    step++;
    stepStart = Date.now();
    setScreensProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Writing SRT...');
    screensLogger.info('=== Step 4: Write Screen Cues SRTs ===');

    var screensProjectCode = assemblyState.projectCode || assemblyState.projectName;

    if (assemblyState.filePath) {
      var briefDir = assemblyState.filePath.replace(/[/\\][^/\\]+$/, '');
      var screensSourceDir = briefDir.replace(/[/\\]Setup$/, '');
      try {
        // Ensure Transcription subdirs exist
        var screensTranscriptionEntry = await uxpfs.getEntryWithUrl('file://' + screensSourceDir + '/Transcription');
        var screensTranscriptsFolderEntry = await ensureSubfolder(screensTranscriptionEntry, 'transcripts', screensLogger);
        var screensCaptionsFolderEntry = await ensureSubfolder(screensTranscriptionEntry, 'captions', screensLogger);

        // 1. Transcript SRT (full text per segment, for word-based editing)
        if (screenResult.assemblySegments && screenResult.assemblySegments.length > 0) {
          var screensTranscriptSrt = generateTranscriptSrt(screenResult.assemblySegments);
          if (screensTranscriptSrt) {
            var screensTrFileName = screensProjectCode + '_4_PreEdit_transcript.srt';
            var screensTrFile = await screensTranscriptsFolderEntry.createFile(screensTrFileName, { overwrite: true });
            await screensTrFile.write(screensTranscriptSrt);
            screensLogger.info('Transcript SRT written: Transcription/transcripts/' + screensTrFileName);
          }

          // 2. Captions SRT (word-grouped, 2-line blocks for on-screen reading, top-positioned)
          var screensCaptionsSrt = generateCaptionsSrt(screenResult.assemblySegments, 8, null, '{\\an8}');
          if (screensCaptionsSrt) {
            var screensCapFileName = screensProjectCode + '_4_PreEdit_captions.srt';
            var screensCapFile = await screensCaptionsFolderEntry.createFile(screensCapFileName, { overwrite: true });
            await screensCapFile.write(screensCaptionsSrt);
            screensLogger.info('Captions SRT written: Transcription/captions/' + screensCapFileName);
          }
        }
      } catch (srtErr) {
        screensLogger.warn('SRT write failed (non-fatal): ' + srtErr.message);
      }
    } else {
      screensLogger.info('No SRT content to write');
    }

    stepTimings.push('srt-write ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 5: Import SRTs to 02_Transcripts bin
    step++;
    stepStart = Date.now();
    setScreensProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Importing SRT...');
    screensLogger.info('=== Step 5: Import Screen Cues SRTs ===');
    await importCaptionsSrt(project, assemblyState.filePath, screensProjectCode,
      '4_PreEdit', 'PreEdit Transcript', screensLogger, 'transcript');
    await importCaptionsSrt(project, assemblyState.filePath, screensProjectCode,
      '4_PreEdit', 'PreEdit Captions', screensLogger);

    // Activate created sequence + save
    if (screenResult.sequence) {
      await project.setActiveSequence(screenResult.sequence);
    }
    try { await project.save(); } catch (e) { }

    stepTimings.push('srt-import ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    var elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    setScreensProgress(100, 'Complete!');
    screensLogger.info('=== SCREEN CUES BUILD COMPLETE (' + elapsed + 's) ===');
    screensLogger.info('Timing: ' + stepTimings.join(' | '));
    $('btn-build-screens').classList.add('btn-done');

    // Status line — clear feedback based on V2 result
    if (screenResult.overlays > 0) {
      setScreensStatus('Screen cues built (V1=' + screenResult.clips + ', V2=' + screenResult.overlays + ', ' + screenResult.totalDuration.toFixed(1) + 's)', 'ready');
    } else {
      setScreensStatus('V1 built (' + screenResult.clips + ' clips, ' + screenResult.totalDuration.toFixed(1) + 's). V2: no PNGs — run generate_screen_cues_png.py', 'ready');
      // Copy Python command to clipboard for convenience
      if (assemblyState.filePath) {
        var pngCmd = 'python generate_screen_cues_png.py --brief ' + assemblyState.filePath;
        try { await navigator.clipboard.writeText(pngCmd); screensLogger.info('PNG command copied to clipboard'); } catch (e) { }
      }
    }

    // Validation panel
    if (screenResult.sequence) {
      await validateScreensBuild(screenResult.sequence, screenResult, markerInfo);
    }

    // --- Post-build: Versioning, archive, bin organization (non-fatal) ---
    try {
      if (assemblyState.filePath) {
        var briefDir = assemblyState.filePath.replace(/[/\\][^/\\]+$/, '');
        var versionsDir = await ensureVersionsDir(briefDir, screensLogger);

        // Save brief_out version (export data snapshot)
        var briefOutData = JSON.stringify({
          project: screensProjectCode,
          exported_at: new Date().toISOString(),
          screens: (assemblyState.screens || []).map(function(s) {
            return { screen_id: s.id, screen_type: s.type, segment_id: s.segmentId,
              tc_in: s.tcIn || '', title: s.title || '', subtitle: s.subtitle || '',
              body: s.body || null, prompt: s.prompt || '' };
          })
        }, null, 2);
        await saveVersion(briefOutData, versionsDir, 'brief_out', 'json', screensLogger);

        // Save latest_state.json for Reload Last
        await saveState(versionsDir, {
          timestamp: new Date().toISOString(),
          briefPath: assemblyState.filePath,
          stage: 'preedit',
          projectCode: screensProjectCode
        }, screensLogger);

        // Archive old SRTs (keep only current _4_PreEdit_ files)
        await archiveFiles(briefDir, function(name) {
          if (!name.endsWith('.srt')) return false;
          if (name.indexOf(screensProjectCode + '_4_PreEdit_') === 0) return false;
          return name.indexOf('_transcript.srt') !== -1 ||
            name.indexOf('_captions.srt') !== -1;
        }, screensLogger);

        // Organize bins: move Ingest/Assembly to 99_Archive
        await organizeBins(project, screensProjectCode, screensLogger);
      }
    } catch (postErr) {
      screensLogger.debug('Post-build operations: ' + postErr.message);
    }

    // Save debug bundle
    await saveScreensLogs(project, screenResult);

  } catch (err) {
    screensLogger.error('SCREEN CUES BUILD FAILED: ' + err.message);
    if (err.stack) screensLogger.debug(err.stack);
    setScreensStatus('Build failed: ' + err.message, 'error');
    try { await saveScreensLogs(await ppro.Project.getActiveProject(), null); } catch (e) { }
  }
}

/**
 * Save Screen Cues debug bundle (log.txt + debug_snapshot.json + brief_copy.json).
 */
async function saveScreensLogs(project, screenResult) {
  try {
    if (project) { try { await project.save(); screensLogger.info('Project saved'); } catch (e) { } }

    var extras = {
      screensCount: assemblyState.screens ? assemblyState.screens.length : 0,
      clipsPlaced: screenResult ? screenResult.clips : 0,
      overlaysPlaced: screenResult ? screenResult.overlays : 0,
      markersCreated: screenResult ? screenResult.markers : 0,
      skipped: screenResult ? screenResult.skipped : 0,
      totalDuration: screenResult ? screenResult.totalDuration : 0,
      assemblySegmentsUsed: screenResult && screenResult.assemblySegments ? screenResult.assemblySegments.length : 0,
      srtGenerated: screenResult ? !!screenResult.srtContent : false,
      warnings: screenResult ? screenResult.warnings : []
    };

    await screensLogger.saveDebugBundle(assemblyState.data, project ? project.path : null, extras);
    updateLogPath('screens', screensLogger.getLastSavedPath());
  } catch (err) {
    screensLogger.error('Failed to save screens logs: ' + err.message);
  }
}

/**
 * Create Screen Cues markers on the sequence.
 *
 * Follows the SAME 4-transaction pattern as createAssemblyMarkers():
 *   0. Activate sequence (CRITICAL — buildScreenCues does importFiles which may deactivate it)
 *   1. Transaction 1: Create all markers (batch)
 *   2. Read markers ONCE: markersOwner.getMarkers()
 *   3. Transaction 2: Set colors (using SAME marker references)
 *   4. Transaction 3: Set types to Chapter (using SAME marker references)
 *
 * KEY DIFFERENCE from Assembly: buildScreenCues() does project.importFiles() for PNGs,
 * which changes Premiere's internal state and may deactivate/close the sequence.
 * Assembly has NO such operations between sequence creation and markers.
 * Fix: explicitly activate + open sequence before marker operations.
 *
 * @param {Object} project - Active Premiere project
 * @param {Object} screenResult - Result from buildScreenCues() with .sequence and .markerList
 * @returns {{ chapters: number, comments: number }}
 */
async function createScreenCuesMarkers(project, screenResult) {
  const { MARKER_TYPE_CHAPTER, MARKER_COLOR_INDEX, SCREEN_CUE_COLOR } = require('./src/shared/constants');
  const seq = screenResult.sequence;
  const markerList = screenResult.markerList || [];

  if (!seq || markerList.length === 0) {
    screensLogger.info('No markers to create');
    return { chapters: 0, comments: 0 };
  }

  // CRITICAL: Activate the ScreenCues sequence before marker operations.
  // buildScreenCues() does project.importFiles() for PNGs, which can deactivate/close
  // the sequence. Assembly doesn't have this problem because it does NOTHING between
  // sequence creation and markers. This is why Assembly markers work but ScreenCues didn't.
  try {
    await project.setActiveSequence(seq);
    screensLogger.debug('Activated ScreenCues sequence for markers');
  } catch (e) {
    screensLogger.warn('setActiveSequence failed: ' + e.message);
  }
  try {
    await project.openSequence(seq.guid || seq);
    screensLogger.debug('Opened ScreenCues sequence for markers');
  } catch (e) {
    screensLogger.debug('openSequence failed (non-fatal): ' + e.message);
  }

  // Static API — the ONLY working way to get markers in UXP Premiere Pro
  let markersOwner;
  try {
    markersOwner = await ppro.Markers.getMarkers(seq);
  } catch (ex) {
    screensLogger.warn('Cannot get sequence markers: ' + ex.message);
    return { chapters: 0, comments: 0 };
  }

  if (!markersOwner) {
    screensLogger.warn('Markers object is null');
    return { chapters: 0, comments: 0 };
  }

  // API discovery — log available methods (same as Assembly, for diagnostics)
  try {
    var methods = [];
    for (var k of Object.getOwnPropertyNames(Object.getPrototypeOf(markersOwner))) {
      if (typeof markersOwner[k] === 'function') methods.push(k);
    }
    screensLogger.debug('markersOwner methods: [' + methods.join(', ') + ']');
  } catch (e) { /* ignore */ }

  // Transaction 1: Create all markers (batch)
  let chapterCount = 0;
  try {
    project.lockedAccess(function () {
      project.executeTransaction(function (ca) {
        for (var mk_i = 0; mk_i < markerList.length; mk_i++) {
          var mk = markerList[mk_i];
          try {
            ca.addAction(markersOwner.createAddMarkerAction(
              mk.name, mk.type,
              ppro.TickTime.createWithSeconds(mk.startSec),
              ppro.TickTime.createWithSeconds(mk.durationSec),
              mk.comment
            ));
            chapterCount++;
          } catch (ex) {
            screensLogger.debug('Marker action failed: ' + mk.name + ' — ' + ex.message);
          }
        }
      }, 'YTAI ScreenCue Markers');
    });
  } catch (batchErr) {
    screensLogger.warn('Batch markers failed: ' + batchErr.message + ', trying individually...');
    chapterCount = 0;
    for (var mk_i = 0; mk_i < markerList.length; mk_i++) {
      try {
        var mk = markerList[mk_i];
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(markersOwner.createAddMarkerAction(
              mk.name, mk.type,
              ppro.TickTime.createWithSeconds(mk.startSec),
              ppro.TickTime.createWithSeconds(mk.durationSec),
              mk.comment
            ));
          }, 'Marker: ' + mk.name);
        });
        chapterCount++;
      } catch (ex) {
        screensLogger.debug('  Marker failed: ' + mk.name + ' — ' + ex.message);
      }
    }
  }

  screensLogger.info('Markers created: ' + chapterCount + '/' + markerList.length);

  // Read markers ONCE — use same references for both color and type transactions
  let coloredCount = 0;
  let typedCount = 0;
  try {
    var allMarkers = markersOwner.getMarkers();
    screensLogger.debug('markersOwner.getMarkers() returned ' + (allMarkers ? allMarkers.length : 'null') + ' markers');

    if (allMarkers && allMarkers.length > 0) {
      // API discovery — log methods on first marker
      try {
        var m0 = allMarkers[0];
        var mMethods = [];
        for (var k of Object.getOwnPropertyNames(Object.getPrototypeOf(m0))) {
          if (typeof m0[k] === 'function') mMethods.push(k);
        }
        screensLogger.debug('Marker methods: [' + mMethods.join(', ') + ']');
      } catch (e) { /* ignore */ }

      // Transaction 2: Set marker colors — per-marker (block colors + Orange for screen cues)
      // Build name → markerColorIdx map from markerList
      var nameColorMap = {};
      for (var nci = 0; nci < markerList.length; nci++) {
        var mkEntry = markerList[nci];
        if (mkEntry.markerColor && MARKER_COLOR_INDEX[mkEntry.markerColor] !== undefined) {
          nameColorMap[mkEntry.name] = MARKER_COLOR_INDEX[mkEntry.markerColor];
        }
      }

      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            for (var ci = 0; ci < allMarkers.length; ci++) {
              var marker = allMarkers[ci];
              try {
                var mName = marker.getName ? marker.getName() : '';
                var colorIdx = nameColorMap[mName];
                if (colorIdx !== undefined) {
                  ca.addAction(marker.createSetColorByIndexAction(colorIdx));
                } else {
                  // Fallback: screen cue orange for unknown markers
                  ca.addAction(marker.createSetColorByIndexAction(SCREEN_CUE_COLOR.markerIdx));
                }
                coloredCount++;
              } catch (e) {
                screensLogger.debug('  Marker color failed: ' + e.message);
              }
            }
          }, 'YTAI ScreenCue Marker Colors');
        });
        screensLogger.info('Marker colors: ' + coloredCount + '/' + allMarkers.length + ' colored (block colors + Orange)');
      } catch (colorErr) {
        screensLogger.warn('Marker color setting failed: ' + colorErr.message);
      }

      // Transaction 3: Set marker TYPE per-marker (using SAME allMarkers refs)
      // createAddMarkerAction ignores the type param — always creates Event.
      // Must use createSetTypeAction on each marker to change Event → Chapter/Segmentation.
      // Build nameTypeMap from markerList for per-marker type
      var nameTypeMap = {};
      for (var nti = 0; nti < markerList.length; nti++) {
        nameTypeMap[markerList[nti].name] = markerList[nti].type;
      }

      var chapterTyped = 0;
      var segTyped = 0;
      try {
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            for (var ti = 0; ti < allMarkers.length; ti++) {
              var marker = allMarkers[ti];
              try {
                var mName = marker.getName ? marker.getName() : '';
                var typeUri = nameTypeMap[mName] || MARKER_TYPE_CHAPTER;
                ca.addAction(marker.createSetTypeAction(typeUri));
                typedCount++;
                if (typeUri === MARKER_TYPE_CHAPTER) chapterTyped++;
                else segTyped++;
              } catch (e) {
                screensLogger.debug('  Marker type failed: ' + e.message);
              }
            }
          }, 'YTAI ScreenCue Marker Types');
        });
        screensLogger.info('Marker types: ' + chapterTyped + ' Chapter + ' + segTyped + ' Segmentation (' + typedCount + '/' + allMarkers.length + ')');
      } catch (typeErr) {
        screensLogger.warn('Marker type change failed: ' + typeErr.message);
      }
    }
  } catch (readErr) {
    screensLogger.warn('Marker read-back failed: ' + readErr.message);
  }

  return { chapters: chapterCount, colored: coloredCount, typed: typedCount };
}

/**
 * Export Pre-Edit — full timeline data (JSON + HTML review table) to project exports folder.
 * Creates Setup/exports/{code}_PreEdit_{timestamp}/ with timeline_data.json + timeline_review.html.
 * Opens folder in Finder after export.
 */
async function exportPreEdit() {
  screensLogger.info('=== Export Pre-Edit ===');
  try {
    if (!assemblyState.data && !assemblyState.segments) {
      screensLogger.warn('No brief data loaded');
      setScreensStatus('No brief loaded — select project first', 'error');
      return;
    }

    setScreensStatus('Exporting Pre-Edit...', 'waiting');

    var projectCode = assemblyState.projectCode || assemblyState.projectName;
    var projectName = assemblyState.projectName || projectCode;
    var ts = versionTimestamp();
    var exportDirName = projectCode + '_PreEdit_' + ts;

    // Compute timeline positions for segments
    var useSegs = (assemblyState.segments || []).filter(function(s) { return s.use; });
    var segPositions = buildSegmentPositionMap(useSegs);

    // Build cumulative timeline positions for all segments
    var cumTime = 0;
    var segmentsExport = [];
    for (var si = 0; si < useSegs.length; si++) {
      var seg = useSegs[si];
      segmentsExport.push({
        id: seg.id,
        sourceFile: seg.sourceFile,
        inSec: seg.inSec,
        outSec: seg.outSec,
        duration: seg.duration,
        block: seg.block,
        blockName: seg.blockName,
        speaker: seg.speaker || '',
        transcript: seg.transcript || '',
        color: seg.color,
        use: seg.use,
        timelineStartSec: cumTime,
        timelineEndSec: cumTime + seg.duration
      });
      cumTime += seg.duration;
    }
    var totalDuration = cumTime;

    // Build blocks export
    var blockMap = {};
    var blockCum = 0;
    for (var bi = 0; bi < useSegs.length; bi++) {
      var bSeg = useSegs[bi];
      if (!blockMap[bSeg.block]) {
        blockMap[bSeg.block] = {
          id: bSeg.block,
          name: bSeg.blockName || ('Block ' + bSeg.block),
          color: bSeg.color,
          startSec: blockCum,
          durationSec: 0,
          segmentCount: 0
        };
      }
      blockMap[bSeg.block].durationSec += bSeg.duration;
      blockMap[bSeg.block].segmentCount++;
      blockCum += bSeg.duration;
    }
    var blocksExport = Object.keys(blockMap).sort(function(a,b) { return Number(a) - Number(b); }).map(function(k) { return blockMap[k]; });

    // Build screens export with timeline positions
    var screensExport = (assemblyState.screens || []).map(function(s) {
      var pos = getScreenTimelinePosition(s, segPositions);
      return {
        screen_id: s.id,
        screen_type: s.type,
        segment_id: s.segmentId,
        tc_in: s.tcIn || '',
        title: s.title || '',
        subtitle: s.subtitle || '',
        body: s.body || null,
        prompt: s.prompt || '',
        timelinePositionSec: pos !== null ? Math.round(pos * 100) / 100 : null
      };
    });

    // Build markers export (chapters + screen cues)
    var markersExport = [];
    for (var mk = 0; mk < blocksExport.length; mk++) {
      var blk = blocksExport[mk];
      markersExport.push({
        name: blk.name,
        type: 'chapter',
        startSec: Math.round(blk.startSec * 100) / 100,
        durationSec: Math.round(blk.durationSec * 100) / 100,
        color: blk.color,
        comment: ''
      });
    }
    for (var sm = 0; sm < screensExport.length; sm++) {
      var scr = screensExport[sm];
      var comment = '[' + (scr.screen_type || '').toUpperCase().replace(/_/g, ' ') + '] ' + (scr.title || '');
      if (scr.prompt) comment += ' | [PROMPT] ' + scr.prompt;
      markersExport.push({
        name: '[SCR] ' + (scr.screen_type || ''),
        type: 'segmentation',
        startSec: scr.timelinePositionSec,
        durationSec: 0,
        color: 'Orange',
        comment: comment
      });
    }

    // Generate SRT content
    var transcriptSrt = generateTranscriptSrt(useSegs);
    var captionsSrt = generateCaptionsSrt(useSegs);

    // Full export JSON
    var exportData = {
      project: projectCode,
      projectName: projectName,
      exported_at: new Date().toISOString(),
      brief_path: assemblyState.filePath || '',
      blocks: blocksExport,
      segments: segmentsExport,
      screens: screensExport,
      markers: markersExport,
      srt: {
        transcript: transcriptSrt,
        captions: captionsSrt
      },
      timeline: {
        totalDuration: Math.round(totalDuration * 10) / 10,
        v1SegmentCount: useSegs.length,
        v2OverlayCount: screensExport.length,
        markerCount: markersExport.length
      }
    };

    // Generate HTML review page
    var html = generateReviewHtml(exportData);

    // Save to exports folder
    var briefDir = assemblyState.filePath ? assemblyState.filePath.replace(/[/\\][^/\\]+$/, '') : null;
    if (!briefDir) {
      screensLogger.warn('No brief directory — using file picker');
      var file = await uxpfs.getFileForSaving(exportDirName + '_timeline.json', { types: ['json'] });
      if (!file) { screensLogger.info('Export cancelled'); return; }
      await file.write(JSON.stringify(exportData, null, 2));
      setScreensStatus('Exported → ' + file.name, 'ready');
      return;
    }

    var setupFolder = await uxpfs.getEntryWithUrl('file://' + briefDir);
    var exportsFolder = await ensureSubfolder(setupFolder, 'exports', screensLogger);
    var exportFolder = await ensureSubfolder(exportsFolder, exportDirName, screensLogger);

    // Write JSON
    var jsonFile = await exportFolder.createFile('timeline_data.json', { overwrite: true });
    await jsonFile.write(JSON.stringify(exportData, null, 2));
    screensLogger.info('Written: timeline_data.json');

    // Write HTML
    var htmlFile = await exportFolder.createFile('timeline_review.html', { overwrite: true });
    await htmlFile.write(html);
    screensLogger.info('Written: timeline_review.html');

    var exportPath = briefDir + '/exports/' + exportDirName;
    var htmlPath = exportPath + '/timeline_review.html';
    screensLogger.info('Export complete → ' + exportPath);

    // Open HTML review in default browser
    // UXP shell.openPath works for executable files (.command).
    // For HTML/folders we need openExternal with file:// URL.
    var opened = false;
    var uxpShell = require('uxp').shell;

    // Approach 1: openExternal with file:// URL (opens HTML in browser)
    if (!opened && typeof uxpShell.openExternal === 'function') {
      try {
        var htmlUrl = 'file://' + htmlPath;
        await uxpShell.openExternal(htmlUrl);
        screensLogger.info('Opened via openExternal: ' + htmlUrl);
        opened = true;
      } catch (e1) {
        screensLogger.debug('openExternal(html) failed: ' + e1.message);
      }
    }

    // Approach 2: openPath with HTML file
    if (!opened) {
      try {
        await uxpShell.openPath(htmlPath);
        screensLogger.info('Opened via openPath(html): ' + htmlPath);
        opened = true;
      } catch (e2) {
        screensLogger.debug('openPath(html) failed: ' + e2.message);
      }
    }

    // Approach 3: openExternal with folder URL
    if (!opened && typeof uxpShell.openExternal === 'function') {
      try {
        await uxpShell.openExternal('file://' + exportPath);
        screensLogger.info('Opened via openExternal(folder)');
        opened = true;
      } catch (e3) {
        screensLogger.debug('openExternal(folder) failed: ' + e3.message);
      }
    }

    // Approach 4: openPath with folder
    if (!opened) {
      try {
        await uxpShell.openPath(exportPath);
        screensLogger.info('Opened via openPath(folder)');
        opened = true;
      } catch (e4) {
        screensLogger.debug('openPath(folder) failed: ' + e4.message);
      }
    }

    // Approach 5: openPath with nativePath from entry
    if (!opened) {
      try {
        var nativePath = htmlFile.nativePath || exportFolder.nativePath;
        if (nativePath) {
          await uxpShell.openPath(nativePath);
          screensLogger.info('Opened via nativePath: ' + nativePath);
          opened = true;
        }
      } catch (e5) {
        screensLogger.debug('nativePath failed: ' + e5.message);
      }
    }

    // Log all shell methods for future debugging
    var shellMethods = [];
    for (var sk in uxpShell) {
      if (typeof uxpShell[sk] === 'function') shellMethods.push(sk);
    }
    screensLogger.debug('uxp.shell methods: [' + shellMethods.join(', ') + ']');

    // Last resort: copy path to clipboard
    if (!opened) {
      screensLogger.debug('All open methods failed — path copied to clipboard');
      try { await navigator.clipboard.writeText(exportPath); } catch (e) { /* ignore */ }
    }

    setScreensStatus('Exported: ' + segmentsExport.length + ' segs, ' + screensExport.length + ' screens, ' + markersExport.length + ' markers → ' + exportDirName, 'ready');

    // Save debug bundle
    await screensLogger.saveDebugBundle(exportData, null, { operation: 'export', exportPath: exportPath });
  } catch (err) {
    screensLogger.error('Export failed: ' + err.message);
    if (err.stack) screensLogger.debug(err.stack);
    setScreensStatus('Export failed: ' + err.message, 'error');
    // Save log even on failure
    await screensLogger.saveDebugBundle(null, null, { operation: 'export_failed', error: err.message });
  }
}

/**
 * Generate self-contained HTML review page with dark theme tables.
 */
function generateReviewHtml(data) {
  var h = function(s) { return escapeHtml(String(s || '')); };
  var ft = function(sec) {
    if (sec === null || sec === undefined) return '—';
    var m = Math.floor(sec / 60);
    var s = (sec % 60).toFixed(1);
    return m + ':' + (s < 10 ? '0' : '') + s;
  };

  var colorCss = {
    Green: '#4caf50', Blue: '#2196f3', Cyan: '#00bcd4', Yellow: '#ffeb3b',
    Red: '#f44336', Magenta: '#e91e63', Purple: '#9c27b0', Orange: '#ff9800',
    Lavender: '#b39ddb', Rose: '#f48fb1', Mango: '#ffb74d', Cerulean: '#4dd0e1'
  };

  var lines = [];
  lines.push('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">');
  lines.push('<title>' + h(data.projectName) + ' — Pre-Edit Review</title>');
  lines.push('<style>');
  lines.push('*{box-sizing:border-box;margin:0;padding:0}');
  lines.push('body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#1a1a2e;color:#e0e0e0;padding:24px;line-height:1.5}');
  lines.push('h1{color:#fff;margin-bottom:8px;font-size:1.6em}');
  lines.push('h2{color:#64b5f6;margin:32px 0 12px;font-size:1.2em;border-bottom:1px solid #333;padding-bottom:6px}');
  lines.push('.summary{background:#16213e;padding:16px 20px;border-radius:8px;margin:16px 0 24px;display:flex;gap:32px;flex-wrap:wrap}');
  lines.push('.summary .item{display:flex;flex-direction:column}.summary .label{font-size:.75em;color:#888;text-transform:uppercase}.summary .value{font-size:1.3em;font-weight:600;color:#fff}');
  lines.push('table{width:100%;border-collapse:collapse;margin-bottom:24px;font-size:.85em}');
  lines.push('th{background:#0f3460;color:#e0e0e0;padding:8px 10px;text-align:left;position:sticky;top:0;font-weight:600}');
  lines.push('td{padding:6px 10px;border-bottom:1px solid #222;vertical-align:top}');
  lines.push('tr:nth-child(even){background:#16213e}tr:hover{background:#1a1a40}');
  lines.push('.color-dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle}');
  lines.push('.transcript{max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}');
  lines.push('.prompt{color:#ffb74d;font-style:italic}');
  lines.push('.tc{font-family:"SF Mono",Menlo,monospace;font-size:.85em;color:#80cbc4}');
  lines.push('.tag{display:inline-block;padding:2px 6px;border-radius:4px;font-size:.75em;font-weight:600}');
  lines.push('.tag-chapter{background:#0f3460;color:#64b5f6}.tag-screen{background:#4a1a00;color:#ffb74d}');
  lines.push('@media print{body{background:#fff;color:#000}th{background:#ddd;color:#000}tr:nth-child(even){background:#f5f5f5}}');
  lines.push('</style></head><body>');

  // Header + Summary
  lines.push('<h1>' + h(data.projectName) + '</h1>');
  lines.push('<p style="color:#888;margin-bottom:4px">Pre-Edit Export — ' + h(data.exported_at) + '</p>');
  lines.push('<div class="summary">');
  lines.push('<div class="item"><span class="label">Duration</span><span class="value">' + ft(data.timeline.totalDuration) + '</span></div>');
  lines.push('<div class="item"><span class="label">Segments</span><span class="value">' + data.timeline.v1SegmentCount + '</span></div>');
  lines.push('<div class="item"><span class="label">Screens</span><span class="value">' + data.timeline.v2OverlayCount + '</span></div>');
  lines.push('<div class="item"><span class="label">Markers</span><span class="value">' + data.timeline.markerCount + '</span></div>');
  lines.push('<div class="item"><span class="label">Blocks</span><span class="value">' + data.blocks.length + '</span></div>');
  lines.push('</div>');

  // Table 1: Blocks
  lines.push('<h2>Blocks (Chapters)</h2>');
  lines.push('<table><thead><tr><th>#</th><th>Name</th><th>Start</th><th>Duration</th><th>Color</th><th>Segments</th></tr></thead><tbody>');
  for (var bi = 0; bi < data.blocks.length; bi++) {
    var b = data.blocks[bi];
    var cc = colorCss[b.color] || '#888';
    lines.push('<tr><td>' + b.id + '</td><td>' + h(b.name) + '</td><td class="tc">' + ft(b.startSec) + '</td><td class="tc">' + ft(b.durationSec) + '</td>');
    lines.push('<td><span class="color-dot" style="background:' + cc + '"></span>' + h(b.color) + '</td><td>' + b.segmentCount + '</td></tr>');
  }
  lines.push('</tbody></table>');

  // Table 2: Segments
  lines.push('<h2>Segments (Timeline)</h2>');
  lines.push('<table><thead><tr><th>#</th><th>Block</th><th>Source</th><th>In→Out</th><th>Dur</th><th>Speaker</th><th>Transcript</th><th>Timeline</th></tr></thead><tbody>');
  for (var si = 0; si < data.segments.length; si++) {
    var s = data.segments[si];
    var sc = colorCss[s.color] || '#888';
    var trunc = (s.transcript || '').substring(0, 120);
    if ((s.transcript || '').length > 120) trunc += '...';
    lines.push('<tr><td>' + (si + 1) + '</td>');
    lines.push('<td><span class="color-dot" style="background:' + sc + '"></span>' + h(s.blockName) + '</td>');
    lines.push('<td>' + h(s.sourceFile) + '</td>');
    lines.push('<td class="tc">' + ft(s.inSec) + '→' + ft(s.outSec) + '</td>');
    lines.push('<td class="tc">' + ft(s.duration) + '</td>');
    lines.push('<td>' + h(s.speaker) + '</td>');
    lines.push('<td class="transcript">' + h(trunc) + '</td>');
    lines.push('<td class="tc">' + ft(s.timelineStartSec) + '→' + ft(s.timelineEndSec) + '</td></tr>');
  }
  lines.push('</tbody></table>');

  // Table 3: Screens
  if (data.screens.length > 0) {
    lines.push('<h2>Screens (Pre-Edit Cues)</h2>');
    lines.push('<table><thead><tr><th>#</th><th>Type</th><th>Title</th><th>Subtitle</th><th>Prompt</th><th>Segment</th><th>TC In</th><th>Timeline</th></tr></thead><tbody>');
    for (var sci = 0; sci < data.screens.length; sci++) {
      var scr = data.screens[sci];
      lines.push('<tr><td>' + (sci + 1) + '</td>');
      lines.push('<td>' + h(scr.screen_type) + '</td>');
      lines.push('<td>' + h(scr.title) + '</td>');
      lines.push('<td>' + h(scr.subtitle) + '</td>');
      lines.push('<td class="prompt">' + h(scr.prompt) + '</td>');
      lines.push('<td>' + h(scr.segment_id) + '</td>');
      lines.push('<td class="tc">' + h(scr.tc_in) + '</td>');
      lines.push('<td class="tc">' + ft(scr.timelinePositionSec) + '</td></tr>');
    }
    lines.push('</tbody></table>');
  }

  // Table 4: Markers
  lines.push('<h2>Markers</h2>');
  lines.push('<table><thead><tr><th>#</th><th>Name</th><th>Type</th><th>Start</th><th>Duration</th><th>Color</th><th>Comment</th></tr></thead><tbody>');
  for (var mi = 0; mi < data.markers.length; mi++) {
    var m = data.markers[mi];
    var mc = colorCss[m.color] || '#888';
    var tagClass = m.type === 'chapter' ? 'tag-chapter' : 'tag-screen';
    var commentTrunc = (m.comment || '').substring(0, 100);
    if ((m.comment || '').length > 100) commentTrunc += '...';
    lines.push('<tr><td>' + (mi + 1) + '</td>');
    lines.push('<td>' + h(m.name) + '</td>');
    lines.push('<td><span class="tag ' + tagClass + '">' + h(m.type) + '</span></td>');
    lines.push('<td class="tc">' + ft(m.startSec) + '</td>');
    lines.push('<td class="tc">' + (m.durationSec > 0 ? ft(m.durationSec) : '—') + '</td>');
    lines.push('<td><span class="color-dot" style="background:' + mc + '"></span>' + h(m.color) + '</td>');
    lines.push('<td>' + h(commentTrunc) + '</td></tr>');
  }
  lines.push('</tbody></table>');

  lines.push('</body></html>');
  return lines.join('\n');
}

/**
 * Import Pre-Edit — user picks a JSON via file picker.
 * File is copied to project folder with correct name, then merged into brief.
 */
async function importPreEdit() {
  screensLogger.info('=== Import Pre-Edit ===');
  try {
    if (!assemblyState.filePath) {
      screensLogger.warn('No brief loaded — filePath is null');
      setScreensStatus('No brief loaded', 'error');
      return;
    }

    // 1. File picker — user chooses which JSON to import
    var reviewFile = await uxpfs.getFileForOpening({ types: ['json'], allowMultiple: false });
    if (!reviewFile) {
      screensLogger.info('Import cancelled by user');
      return;
    }
    screensLogger.info('Importing from: ' + (reviewFile.nativePath || reviewFile.name));
    var reviewContent = await reviewFile.read();
    var reviewData = JSON.parse(reviewContent);

    if (!reviewData.screens || !Array.isArray(reviewData.screens)) {
      setScreensStatus('Invalid file: no screens[] array', 'error');
      screensLogger.warn('File has no screens[] array');
      return;
    }
    screensLogger.info('Read: ' + reviewData.screens.length + ' screens from ' + reviewFile.name);

    setScreensStatus('Importing ' + reviewData.screens.length + ' screens...', 'waiting');

    // 2. Copy imported file to project folder with correct name
    var projectCode = assemblyState.projectCode || assemblyState.projectName;
    var briefDir = assemblyState.filePath.replace(/[/\\][^/\\]+$/, '');
    var correctName = projectCode + '_screen_cues_review.json';

    try {
      var setupFolder = await uxpfs.getEntryWithUrl('file://' + briefDir);
      var copyFile = await setupFolder.createFile(correctName, { overwrite: true });
      await copyFile.write(JSON.stringify(reviewData, null, 2));
      screensLogger.info('Copied to project: ' + briefDir + '/' + correctName);
    } catch (copyErr) {
      screensLogger.debug('Copy to project folder skipped: ' + copyErr.message);
    }

    // 3. Read current brief
    var briefEntry = await uxpfs.getEntryWithUrl('file://' + assemblyState.filePath);
    var briefContent = await briefEntry.read();
    var briefJson = JSON.parse(briefContent);

    // 4. Archive current brief version before merge
    try {
      var versionsDir = await ensureVersionsDir(briefDir, screensLogger);
      await saveVersion(briefContent, versionsDir, 'brief_before_import', 'json', screensLogger);
    } catch (vErr) {
      screensLogger.debug('Pre-import version save skipped: ' + vErr.message);
    }

    // 5. Merge review screens into brief
    var briefScreens = briefJson.screens || [];
    var changed = 0;
    var added = 0;
    var removed = 0;

    // Build map of review screens by id
    var reviewMap = {};
    for (var ri = 0; ri < reviewData.screens.length; ri++) {
      reviewMap[reviewData.screens[ri].screen_id] = reviewData.screens[ri];
    }

    // Update existing screens
    for (var bsi = briefScreens.length - 1; bsi >= 0; bsi--) {
      var bScreen = briefScreens[bsi];
      var bId = bScreen.screen_id || bScreen.id;
      var reviewScreen = reviewMap[bId];

      if (reviewScreen) {
        var fields = ['title', 'subtitle', 'body', 'screen_type', 'prompt'];
        for (var fi = 0; fi < fields.length; fi++) {
          var field = fields[fi];
          if (reviewScreen[field] !== undefined && reviewScreen[field] !== bScreen[field]) {
            screensLogger.debug('  ' + bId + '.' + field + ': "' + (bScreen[field] || '') + '" \u2192 "' + (reviewScreen[field] || '') + '"');
            bScreen[field] = reviewScreen[field];
            changed++;
          }
        }
        delete reviewMap[bId];
      } else {
        screensLogger.info('  Removed: ' + bId);
        briefScreens.splice(bsi, 1);
        removed++;
      }
    }

    // Add new screens from review
    var newIds = Object.keys(reviewMap);
    for (var ni = 0; ni < newIds.length; ni++) {
      var newScreen = reviewMap[newIds[ni]];
      briefScreens.push({
        screen_id: newScreen.screen_id,
        screen_type: newScreen.screen_type,
        segment_id: newScreen.segment_id,
        tc_in: newScreen.tc_in,
        title: newScreen.title,
        subtitle: newScreen.subtitle || '',
        body: newScreen.body || null,
        prompt: newScreen.prompt || ''
      });
      screensLogger.info('  Added: ' + newScreen.screen_id);
      added++;
    }

    briefJson.screens = briefScreens;

    // 6. Save updated brief
    var updatedContent = JSON.stringify(briefJson, null, 2);
    var briefFolder = await uxpfs.getEntryWithUrl('file://' + briefDir);
    var briefFileName = assemblyState.filePath.split('/').pop();
    var briefOut = await briefFolder.createFile(briefFileName, { overwrite: true });
    await briefOut.write(updatedContent);

    screensLogger.info('Brief updated: ' + changed + ' changed, ' + added + ' added, ' + removed + ' removed');

    // 7. Re-parse brief
    loadBriefFromString(updatedContent, assemblyState.filePath);

    var summary = changed + ' changed, ' + added + ' added, ' + removed + ' removed';
    setScreensStatus('Imported (' + fmtTime(0) + '): ' + summary + '. Generate PNGs \u2192 Build.', 'ready');
    screensLogger.info('Import complete (' + summary + '). Run: Generate PNGs \u2192 Build Pre-Edit');

    // Save debug bundle
    await screensLogger.saveDebugBundle(assemblyState.data, null, { operation: 'import', summary: summary });
  } catch (err) {
    screensLogger.error('Import failed: ' + err.message);
    if (err.stack) screensLogger.debug(err.stack);
    setScreensStatus('Import failed: ' + err.message, 'error');
    await screensLogger.saveDebugBundle(null, null, { operation: 'import_failed', error: err.message });
  }
}

/**
 * Post-build validation for Screen Cues — V1 clips, V2 overlays, markers, SRT.
 */
async function validateScreensBuild(sequence, screenResult, markerInfo) {
  screensLogger.info('=== Post-build validation ===');
  var panel = $('screens-validation');
  var lines = [];

  function ok(text) { lines.push('<div class="val-line"><span style="color:var(--success)">●</span> ' + escapeHtml(text) + '</div>'); }
  function warn(text) { lines.push('<div class="val-line"><span style="color:var(--warning)">●</span> ' + escapeHtml(text) + '</div>'); }

  // V1 clip count check (Assembly copy)
  var expectedV1 = screenResult.assemblySegments ? screenResult.assemblySegments.length : 0;
  try {
    var v1 = await sequence.getVideoTrack(0);
    var items;
    try { items = v1.getTrackItems(1, false); } catch (ex) {
      try { items = v1.getTrackItems(); } catch (ex2) { items = []; }
    }
    if (!items) items = [];
    if (items.length >= screenResult.clips) ok('V1 Assembly: ' + items.length + ' segments');
    else warn('V1 Assembly: ' + items.length + '/' + screenResult.clips + ' segments');
  } catch (e) { warn('V1 Assembly: check failed — ' + e.message); }

  // V2 overlays
  if (screenResult.overlays > 0) ok('V2 Overlays: ' + screenResult.overlays + ' PNG screens');
  else warn('V2 Overlays: 0 — run: python generate_screen_cues_png.py --brief <path>');

  // Markers — use actual markerInfo if available (from createScreenCuesMarkers)
  var markerCreated = markerInfo ? (markerInfo.chapters || 0) : 0;
  var markerTyped = markerInfo ? (markerInfo.typed || 0) : 0;
  if (markerCreated > 0 && markerTyped > 0) {
    ok('Markers: ' + markerCreated + ' Chapter markers (typed=' + markerTyped + ')');
  } else if (markerCreated > 0) {
    warn('Markers: ' + markerCreated + ' created, but type change failed (typed=' + markerTyped + ')');
  } else if (screenResult.markers > 0) {
    warn('Markers: planned ' + screenResult.markers + ', but creation failed (0 created)');
  } else {
    warn('Markers: none');
  }

  // SRT
  if (screenResult.srtContent && screenResult.srtContent.length > 0) ok('SRT: generated (' + screenResult.srtContent.length + ' chars)');
  else warn('SRT: empty');

  // Skipped
  if (screenResult.skipped > 0) warn('Skipped: ' + screenResult.skipped + ' screens');
  else ok('All screens placed');

  // Duration
  if (screenResult.totalDuration > 0) ok('Duration: ' + screenResult.totalDuration.toFixed(1) + 's (Assembly copy)');

  panel.innerHTML = lines.join('');
  panel.style.display = 'block';
  screensLogger.info('Validation complete');
}

// --- Initialization ---

document.addEventListener('DOMContentLoaded', () => {
  // PROJECT buttons
  $('btn-select-project').addEventListener('click', selectProjectFolder);
  $('btn-copy-project-prompt').addEventListener('click', copyProjectPrompt);
  $('btn-copy-markers-prompt').addEventListener('click', copyMarkersPrompt);
  $('btn-refresh-project').addEventListener('click', refreshProject);

  // INGEST buttons (btn-load-ingest is fallback — hidden by default)
  $('btn-load-ingest').addEventListener('click', loadIngest);
  $('btn-build-ingest').addEventListener('click', buildIngest);
  $('btn-import-srts').addEventListener('click', importAllSrts);

  // ASSEMBLY buttons (btn-load-brief is fallback — hidden by default)
  $('btn-load-brief').addEventListener('click', loadBrief);
  $('btn-build-assembly').addEventListener('click', buildAssembly);
  $('btn-export-markers').addEventListener('click', exportMarkers);
  $('btn-debug-export').addEventListener('click', debugExport);

  // REVIEW buttons
  $('btn-build-review').addEventListener('click', buildReview);

  // PRE-EDIT buttons (wrap async to catch unhandled rejections)
  $('btn-export-screens').addEventListener('click', function() {
    exportPreEdit().catch(function(e) { screensLogger.error('Export error: ' + e.message); setScreensStatus('Export error: ' + e.message, 'error'); });
  });
  $('btn-import-screens').addEventListener('click', function() {
    screensLogger.info('Import Pre-Edit button clicked');
    setScreensStatus('Importing...', 'waiting');
    importPreEdit().catch(function(e) { screensLogger.error('Import error: ' + e.message); setScreensStatus('Import error: ' + e.message, 'error'); });
  });
  $('btn-generate-pngs').addEventListener('click', generateScreenPngs);
  $('btn-build-screens').addEventListener('click', buildScreenCuesPipeline);

  // LOG: copy path buttons
  $('btn-copy-ingest-log-path').addEventListener('click', () => copyLogPath('ingest'));
  $('btn-copy-assembly-log-path').addEventListener('click', () => copyLogPath('assembly'));
  $('btn-copy-review-log-path').addEventListener('click', () => copyLogPath('review'));
  $('btn-copy-screens-log-path').addEventListener('click', () => copyLogPath('screens'));

  // LOG: clear buttons
  $('btn-clear-ingest-log').addEventListener('click', () => {
    $('ingest-log-panel').innerHTML = '';
    ingestLogger.clear();
  });
  $('btn-clear-assembly-log').addEventListener('click', () => {
    $('assembly-log-panel').innerHTML = '';
    assemblyLogger.clear();
  });
  $('btn-clear-review-log').addEventListener('click', () => {
    $('review-log-panel').innerHTML = '';
    reviewLogger.clear();
  });
  $('btn-clear-screens-log').addEventListener('click', () => {
    $('screens-log-panel').innerHTML = '';
    screensLogger.clear();
  });

  ingestLogger.info('0500_uxp initialized');
  ingestLogger.info('Version 2.1.0');
  assemblyLogger.info('0500_uxp initialized');
  assemblyLogger.info('Version 2.1.0');
  reviewLogger.info('0500_uxp initialized');
  reviewLogger.info('Version 2.1.0');
  screensLogger.info('0500_uxp initialized');
  screensLogger.info('Version 2.1.0');
});
