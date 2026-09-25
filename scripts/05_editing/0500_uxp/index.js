/**
 * YTAI Assembly — UXP Plugin for Adobe Premiere Pro
 *
 * Four pipelines in one panel:
 *   INGEST:      loads ingest.json → imports clips, builds Ingest sequence
 *   ASSEMBLY:    loads pre_edit_brief.json → builds Assembly sequence from existing clips
 *   DELETED SCENE: builds Deleted Scene sequence from unused segments
 *   PRE-EDIT:    creates _4_PreEdit sequence (V1 Assembly copy + V2 PNG overlays + markers + SRT)
 *
 * INGEST, ASSEMBLY, DELETED SCENE, and SCREEN CUES modules do NOT import each other.
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
// Export Audio Map 1.3 — the timeline as it is, every item of every track
const audioMapMod = require('./src/ingest/audioMap');
const { copyLutsToCreativeFolder, applyLumetriToClips } = require('./src/ingest/lutManager');
const { addSceneMarkers, generatedMarkerNames } = require('./src/ingest/placement/sceneMarkers');

// --- Module imports: FOOTAGE REVIEW (отсмотр) ---
const { buildFootageReview, FOOTAGE_REVIEW_VERSION } = require('./src/footageReview/footageReviewBuilder');
const { addAdjustmentOverSelection, addAdjustmentPerClipFromPlan, probeDonorClone,
        buildLutDonorSequence, LUT_DONOR_SEQUENCE,
        collectVideoClipEntries } = require('./src/adjust/adjustmentBuilder');
// Цвет из color_plan.json: параметр Lumetri адресуется по ИНДЕКСУ, а не по имени
const colorApply = require('./src/adjust/colorApply');

// --- Module imports: ASSEMBLY ---
const { parseBrief } = require('./src/assembly/briefParser');
const { validateIngestState, findSourceBin, buildClipMap } = require('./src/assembly/projectScanner');
const { buildAssemblySequence, ASSEMBLY_BUILDER_VERSION } = require('./src/assembly/assemblyBuilder');
const { buildPartSequence, PARTS_BUILDER_VERSION } = require('./src/parts/partsBuilder');

// --- Module imports: SHORTS ---
const { buildPreviewSequence, buildShortSequence, planShort, validateShortsBrief, SHORTS_BUILDER_VERSION } = require('./src/shorts/shortsBuilder');
const { snapToFrame } = require('./src/shared/frameSnap');
// 00_Source_Timelines (2026-09-15): scene timelines {CODE}_{NN}_{Scene} out of the root
const { SOURCE_TIMELINES_BIN } = require('./src/shared/constants');
const { collectTakenNames, findRootBin } = require('./src/shared/binMove');
const { hideSourceTimelines, formatHideReport, SOURCE_TIMELINES_VERSION } = require('./src/shared/sourceTimelines');

// --- Module imports: DELETED SCENE ---
const { buildDeletedSceneSequence, getDeletedSceneCategory } = require('./src/deletedScene/deletedSceneBuilder');

// --- Module imports: REVIEW (new — external editor review) ---
const { parseReviewBrief } = require('./src/review/reviewBriefParser');
const { buildReviewDeletedScene } = require('./src/review/reviewAssembler');

// --- Module imports: SCREENS ---
const { parseScreens } = require('./src/screens/screenParser');
const { buildScreenCues, SCREEN_CUES_BIN_NAME, generateTranscriptSrt, generateCaptionsSrt, buildSegmentPositionMap, getScreenTimelinePosition } = require('./src/screens/screenBuilder');

// --- Module imports: ARCHIVER ---
const { versionTimestamp, ensureSubfolder, archiveFiles, saveVersion, saveState, loadState, ensureVersionsDir } = require('./src/shared/archiver');

// --- Utility: extract short project code (YTCG49) from full name ---
function extractProjectCode(name) {
  if (!name) return 'unknown';
  var match = name.match(/^(YT[A-Z]{2,4}\d+)_/);
  return match ? match[1] : name;
}

// --- Project compact/expand toggle ---
function collapseProjectSection(code) {
  var section = $('project-section');
  $('project-compact-name').textContent = code;
  section.classList.add('project-compact');
}

function toggleProjectExpand() {
  var section = $('project-section');
  section.classList.toggle('project-compact');
}

// --- State (separate for INGEST and ASSEMBLY) ---
// readbackBad: {scene: reason} — scenes whose last build in THIS session failed
// readback (TICKET_uxp_audit task 5). In-session only: after a panel reload the
// badge falls back to «a sequence with this name exists».
let ingestState = { data: null, filePath: null, building: false, readbackBad: {} };
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
const deletedSceneLogger = new Logger('DELETED_SCENE');
const screensLogger = new Logger('SCREENS');
const reviewLogger = new Logger('REVIEW');

// --- State: REVIEW (external editor review) ---
let reviewState = { data: null, filePath: null, building: false, editedVideoPath: null };

// --- UI Helpers ---

// ⚠️ Версия панели — одна, в src/shared/version.js. Поднимать там при КАЖДОЙ
// правке index.js / index.html / src/: по шапке и отчёту «Err» видно,
// перезагрузил ли человек панель или смотрит на старый код.
var PANEL_VERSION = require('./src/shared/version').PANEL_VERSION;

// $() и on() — src/shared/panelDom.js: кнопки вешаются ТОЛЬКО через on() —
// он переживает отсутствие кнопки и отдаёт любое исключение обработчика в «Err».
const { $, on } = require('./src/shared/panelDom');


// Logs write to 99_Pipeline/logs/ only — no in-panel display

// --- INGEST UI helpers ---

function setIngestStatus(text, type, err) {
  $('ingest-status-dot').className = 'status-dot ' + (type || 'waiting');
  $('ingest-status-text').textContent = text;
  if (type === 'error') ingestLogger.errorShown(text, err);
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

function setAssemblyStatus(text, type, err) {
  $('assembly-status-dot').className = 'status-dot ' + (type || 'waiting');
  $('assembly-status-text').textContent = text;
  if (type === 'error') assemblyLogger.errorShown(text, err);
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

function setScreensStatus(text, type, err) {
  $('screens-status-dot').className = 'status-dot ' + (type || 'waiting');
  $('screens-status-text').textContent = text;
  if (type === 'error') screensLogger.errorShown(text, err);
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

function setProjectStatus(text, type, err) {
  $('project-status-dot').className = 'status-dot ' + (type || 'waiting');
  $('project-status-text').textContent = text;
  if (type === 'error') recordPanelError(text, 'project', err);
}

/**
 * Walk UP from a folder until the real project ROOT: a dir containing 00_Setup,
 * or whose name matches YT{XX}{NN}_ . Editors keep .prproj inside 02_Edit/ —
 * without this the panel roots at 02_Edit and every 00_Setup path misses.
 * Max 4 levels; falls back to the start path unchanged.
 */
async function resolveProjectRoot(startPath) {
  var p = String(startPath || '');
  for (var i = 0; i < 4 && p && p !== '/'; i++) {
    var base = p.split('/').pop() || '';
    if (/^YT[A-Z]{2,4}\d+_/.test(base)) return p;
    var hasSetup = false;
    try { await uxpfs.getEntryWithUrl('file://' + p + '/00_Setup'); hasSetup = true; }
    catch (e1) {
      try { await uxpfs.getEntryWithUrl('file://' + encodeURI(p + '/00_Setup')); hasSetup = true; }
      catch (e2) { /* not here */ }
    }
    if (hasSetup) return p;
    var up = p.replace(/\/[^/]*$/, '');
    if (!up || up === p) break;
    p = up;
  }
  return startPath;
}

/**
 * "⧉ Err" button: copy the last panel errors/warnings + context to the clipboard
 * so Roman can paste them straight to Claude (Roman 2026-08-20).
 */
async function copyLastError() {
  var g = (typeof globalThis !== 'undefined') ? globalThis : window;
  var errs = g.__ytaiErrors || [];
  var report = Logger.formatPanelReport(errs, [
    '=== YTAI panel — error report ===',
    'panel: v' + PANEL_VERSION + ' · ' + new Date().toISOString(),
    'project: ' + (projectState.projectName || '?') + ' @ ' + (projectState.folderPath || '?')
  ]);
  var copied = false;
  try { require('uxp').clipboard.copyText(report); copied = true; } catch (eC1) { /* fallback below handles it (navigator.clipboard) */ }
  if (!copied) {
    try { await navigator.clipboard.setContent({ 'text/plain': report }); copied = true; } catch (eC2) { /* fallback below handles it (writeText) */ }
  }
  if (!copied) {
    try { await navigator.clipboard.writeText(report); copied = true; } catch (eC3) { ingestLogger.debug('clipboard writeText: ' + (eC3 && eC3.message)); }
  }
  setProjectStatus(copied ? ('Error report copied (' + errs.length + ' entries) — paste to Claude')
    : 'Clipboard unavailable — see Debug log', copied ? 'ready' : 'error');
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
  // readbackBad must survive every reset: the build's verdict block writes into it
  // (review of eb739d2: without it every multi-scene Build Ingest threw a TypeError).
  ingestState = { data: null, filePath: null, building: false, readbackBad: {} };
  assemblyState = { data: null, segments: [], blocks: [], screens: [], projectName: '', filePath: null, building: false, clipMap: null };
  reviewState = { data: null, filePath: null, building: false, editedVideoPath: null, pipelineResult: null };

  // Reset INGEST UI
  setIngestStatus('Detecting files...', 'waiting');
  $('ingest-summary').style.display = 'none';
  $('ingest-file-info').textContent = '';
  $('btn-build-ingest').setAttribute('disabled', 'true');
  $('btn-export-audio-map').setAttribute('disabled', 'true');
  $('btn-verify-sync').setAttribute('disabled', 'true');
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
  $('assembly-scenes').style.display = 'none';
  $('assembly-scenes-list').innerHTML = '';
  asmScenesState = { entries: [], peEntry: null };
  $('btn-build-assembly-scenes').setAttribute('disabled', 'true');
  $('btn-build-premontage').setAttribute('disabled', 'true');
  hideAssemblyProgress();

  // Reset DELETED SCENE UI
  setDeletedSceneStatus('Detecting files...', 'waiting');
  $('btn-build-deleted-scene').setAttribute('disabled', 'true');
  $('ds-validation').style.display = 'none';
  hideDeletedSceneProgress();

  // Reset REVIEW UI
  setReviewStatus('Detecting files...', 'waiting');
  $('btn-process-review').removeAttribute('disabled');
  $('btn-load-review-brief').removeAttribute('disabled');
  $('btn-build-review').setAttribute('disabled', 'true');
  $('btn-build-review-overlay').removeAttribute('disabled'); // self-scans latest render + inserts
  $('btn-build-review-v3').removeAttribute('disabled'); // self-scans *_review_brief_v3.json
  $('btn-export-sequence-json').removeAttribute('disabled'); // exports active sequence for Claude
  $('btn-export-review-markers').setAttribute('disabled', 'true');
  $('review-validation').style.display = 'none';
  hideReviewProgress();

  // Reset SCREEN CUES UI
  setScreensStatus('Detecting files...', 'waiting');
  $('btn-generate-pngs').setAttribute('disabled', 'true');
  $('btn-build-screens').setAttribute('disabled', 'true');
  $('btn-export-screens').setAttribute('disabled', 'true');
  $('btn-import-pre-edit').setAttribute('disabled', 'true');
  $('btn-export-pre-edit-doc').setAttribute('disabled', 'true');
  $('btn-copy-pre-edit-prompt').setAttribute('disabled', 'true');
  $('btn-import-pre-edit').setAttribute('disabled', 'true');
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
    var assemblyDir = path + '/00_Setup/02_Assembly';
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
    + '- Transcript: ' + path + '/00_Setup/' + code + '_Claude4_assembly.json\n'
    + '- Output JSON: ' + path + '/00_Setup/02_Assembly/' + code + '_Assembly_v' + nextVer + '_in.json\n'
    + '- Output HTML: ' + path + '/00_Setup/02_Assembly/' + code + '_review_v' + nextVer + '.html';

  try { await navigator.clipboard.writeText(prompt); } catch (err) { /* ignore */ }
}

async function copyMarkersPrompt() {
  if (!projectState.folderPath || !projectState.projectName) return;
  var code = extractProjectCode(projectState.projectName);
  var channel = code.replace(/\d+$/, '');
  var path = projectState.folderPath;
  var assemblyDir = path + '/00_Setup/02_Assembly';

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



// ══════════════════════════════════════════════════════════════════
//  PROJECT SELECTION & AUTO-DETECTION
// ══════════════════════════════════════════════════════════════════

/**
 * Select project folder and auto-detect pipeline input files.
 *
 * Convention:
 *   {PROJECT_NAME}/00_Setup/01_Ingest/{CODE}_ingest.json
 *   {PROJECT_NAME}/00_Setup/{CODE}_pre_edit_brief.json
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
    // Walk up if the user picked a subfolder (e.g. 02_Edit) instead of the project root.
    folderPath = await resolveProjectRoot(folderPath);
    var projectName = folderPath.split('/').pop() || folder.name;

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

    // Collapse to compact mode
    collapseProjectSection(extractProjectCode(projectName));

  } catch (err) {
    ingestLogger.error('Project selection failed: ' + err.message);
    setProjectStatus('Selection failed: ' + err.message, 'error', err);
  }
}

/**
 * Auto-fill the project folder from the CURRENTLY OPEN Premiere project.
 * Parity with the Footage stage: derives the folder from the active project's
 * .prproj path instead of a manual picker, then runs the same auto-detection.
 *
 * An UNTITLED / unsaved project has NO path on disk (project.path is empty) — there
 * is nothing to detect, so the user must Save it (⌘S) into its folder first.
 *
 * @param {Object} [opts] { silent } — silent=true (panel init) suppresses the
 *                        "no open / unsaved project" statuses so load stays quiet.
 */
async function useOpenProjectFolder(opts) {
  var silent = opts && opts.silent;
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) {
      if (!silent) setProjectStatus('No open Premiere project — open one, then retry', 'error');
      return;
    }

    // .prproj path — empty for an untitled/unsaved project.
    var ppath = null;
    try { ppath = project.path; } catch (e) { /* getter may throw */ }
    if (!ppath) { try { ppath = await project.getPath(); } catch (e) { /* none */ } }
    if (!ppath) {
      ingestLogger.warn('useOpenProjectFolder: active project has empty path (untitled/unsaved)');
      if (!silent) setProjectStatus('Project not saved yet — Save it (⌘S) into its folder, then "Use Open Project"', 'error');
      return;
    }

    // Derive the project ROOT folder (strip the .prproj filename), then WALK UP:
    // editors keep the .prproj in 02_Edit/ (canon feedback_prproj_latest_in_02edit),
    // but the project root is the folder holding 00_Setup / matching YT{XX}{NN}_.
    var folderPath = String(ppath).replace(/\\/g, '/').replace(/\/[^/]*$/, '');
    if (folderPath.endsWith('/')) folderPath = folderPath.slice(0, -1);
    folderPath = await resolveProjectRoot(folderPath);
    var projectName = folderPath.split('/').pop() || '';

    // Touch the folder so UXP grants access (manifest has fullAccess → no picker).
    try { await uxpfs.getEntryWithUrl('file://' + folderPath); }
    catch (e) { try { await uxpfs.getEntryWithUrl('file://' + encodeURI(folderPath)); } catch (e2) { /* autoDetect retries per-file */ } }

    projectState.folderPath = folderPath;
    projectState.projectName = projectName;
    projectState.ingestPath = null;
    projectState.briefPath = null;
    projectState.ingestDetected = false;
    projectState.briefDetected = false;

    setProjectStatus('Project: ' + projectName + ' (open project)', 'ready');
    $('btn-copy-project-prompt').removeAttribute('disabled');
    $('project-path-info').textContent = folderPath;
    $('project-checklist').innerHTML = '';
    $('project-actions-row').style.display = 'none';

    ingestLogger.info('Project folder from open project: ' + projectName + ' (' + folderPath + ')');

    resetAllPipelineStates();
    await autoDetectFiles(folderPath, projectName);
    collapseProjectSection(extractProjectCode(projectName));

  } catch (err) {
    ingestLogger.error('Use-open-project failed: ' + err.message, err);
    if (!silent) setProjectStatus('Use open project failed: ' + err.message, 'error', err);
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
    folderPath + '/00_Setup/01_Ingest/' + code + '_ingest.json',
    folderPath + '/00_Setup/01_Ingest/' + projectName + '_ingest.json',  // legacy
    folderPath + '/00_Setup/' + code + '_ingest.json',                   // legacy (pre-v4.1)
    folderPath + '/01_Source/' + projectName + '_ingest.json',           // legacy
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
      'Expected: 00_Setup/01_Ingest/' + code + '_ingest.json');
    ingestLogger.warn('Ingest not found at: ' + ingestCandidates.join(', '));
    setIngestStatus('Ingest JSON not found. Load manually.', 'waiting');
    showFallback('ingest');
  }

  // --- Brief --- (search order: 02_Assembly/ → 00_Setup/ legacy)
  var briefFound = false;
  var inRe = new RegExp('^' + code + '_Assembly_v(\\d+)_in\\.json$');

  // Scan 02_Assembly/ folder for latest _in.json by version number
  var assemblyDir = folderPath + '/00_Setup/02_Assembly';
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
      assemblyLogger.info('Auto-detected brief from 02_Assembly/: ' + latestName);
      await loadBriefFromPath(latestPath);
    }
  } catch (e) {
    // 02_Assembly/ folder not found — try legacy paths
  }

  // 3. Fallback: try legacy pre_edit_brief paths in 00_Setup/
  if (!briefFound) {
    var briefCandidates = [
      folderPath + '/00_Setup/' + code + '_pre_edit_brief.json',
      folderPath + '/00_Setup/' + projectName + '_pre_edit_brief.json',  // legacy
      folderPath + '/00_Setup/' + projectName + '_edit_brief.json',       // legacy
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
      'Not found in 02_Assembly/, ~/Downloads/, or 00_Setup/');
    assemblyLogger.warn('No brief found in 02_Assembly/, ~/Downloads/, or 00_Setup/');
    setAssemblyStatus('Pre-edit brief not found. Load manually.', 'waiting');
    setDeletedSceneStatus('Pre-edit brief not found.', 'waiting');
    setScreensStatus('Pre-edit brief not found.', 'waiting');
    showFallback('assembly');
  }

  // Check for saved Pre-Edit state (enable Reload Last button)
  try {
    var setupDir = folderPath + '/00_Setup';
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
  $('btn-debug-dump').removeAttribute('disabled');
  $('btn-export-audio-map').removeAttribute('disabled');
  $('btn-verify-sync').removeAttribute('disabled');
  $('btn-export-markers').removeAttribute('disabled');
  $('btn-debug-export').removeAttribute('disabled');
  $('btn-export-pre-edit-doc').removeAttribute('disabled');
  $('btn-copy-pre-edit-prompt').removeAttribute('disabled');
  $('btn-import-pre-edit').removeAttribute('disabled');
  ingestLogger.info('Auto-detection complete: ingest=' + projectState.ingestDetected + ', brief=' + projectState.briefDetected);

  // Auto-detect Assembly scene bundles (00_Setup/02_Assembly/scenes/) — non-fatal
  try { await refreshAssemblyScenes(); } catch (e) { ingestLogger.debug('Assembly scenes scan: ' + e.message); }

  // Auto-detect Review files (00_Setup/05_Review/ + 03_Exports/)
  try {
    var reviewDir = folderPath + '/00_Setup/05_Review';
    var exportsDir = folderPath + '/03_Exports';

    // Find latest video in 03_Exports/
    var latestVideo = null;
    try {
      var expFolder = await uxpfs.getEntryWithUrl('file://' + exportsDir);
      var expEntries = await expFolder.getEntries();
      var videoFiles = expEntries.filter(function(e) {
        var n = e.name.toLowerCase();
        return n.endsWith('.mp4') || n.endsWith('.mov');
      });
      if (videoFiles.length > 0) {
        videoFiles.sort(function(a, b) { return b.name.localeCompare(a.name); });
        latestVideo = videoFiles[0];
      }
    } catch (e) { reviewLogger.debug('03_Exports scan: ' + (e && e.message)); }

    // Find latest transcript + SRT files in Review/ and Transcription/
    var latestTranscript = null;
    var captionsSrt = null;
    var transcriptSrt = null;
    try {
      var revFolder = await uxpfs.getEntryWithUrl('file://' + reviewDir);
      var revEntries = await revFolder.getEntries();
      var transcripts = revEntries.filter(function(e) {
        return e.name.endsWith('_review_transcript.json');
      });
      if (transcripts.length > 0) {
        transcripts.sort(function(a, b) { return b.name.localeCompare(a.name); });
        latestTranscript = transcripts[0];
      }
      // Find SRT files in Review/ folder
      for (var ri = 0; ri < revEntries.length; ri++) {
        var reName = revEntries[ri].name;
        if (reName.endsWith('_captions.srt') && !captionsSrt) captionsSrt = revEntries[ri];
        if (reName.endsWith('_transcript.srt') && !reName.includes('review_transcript') && !transcriptSrt) transcriptSrt = revEntries[ri];
      }
    } catch (e) { reviewLogger.debug('05_Review scan: ' + (e && e.message)); }
    // Also check Transcription/captions/ and Transcription/transcripts/
    if (!captionsSrt || !transcriptSrt) {
      try {
        var txBase = folderPath + '/01_Source/Transcription';
        if (!captionsSrt) {
          var capDir = await uxpfs.getEntryWithUrl('file://' + txBase + '/captions');
          var capFiles = await capDir.getEntries();
          for (var ci = 0; ci < capFiles.length; ci++) {
            if (capFiles[ci].name.includes('Review') && capFiles[ci].name.endsWith('_captions.srt')) {
              captionsSrt = capFiles[ci]; break;
            }
          }
        }
        if (!transcriptSrt) {
          var trDir = await uxpfs.getEntryWithUrl('file://' + txBase + '/transcripts');
          var trFiles = await trDir.getEntries();
          for (var tri = 0; tri < trFiles.length; tri++) {
            if (trFiles[tri].name.includes('Review') && trFiles[tri].name.endsWith('_transcript.srt')) {
              transcriptSrt = trFiles[tri]; break;
            }
          }
        }
      } catch (e) { /* Transcription dirs may not exist */ }
    }

    // Find latest brief
    var latestBrief = null;
    if (projectState.briefDetected && projectState.briefPath) {
      latestBrief = projectState.briefPath;
    }

    if (latestVideo && latestTranscript) {
      // Review files exist — populate pipelineResult and enable Build Review
      reviewState.pipelineResult = {
        video: latestVideo.nativePath,
        transcript: latestTranscript.nativePath,
        captions_srt: captionsSrt ? captionsSrt.nativePath : '',
        transcript_srt: transcriptSrt ? transcriptSrt.nativePath : '',
        brief: latestBrief || '',
        status: 'ok'
      };
      $('btn-build-review').removeAttribute('disabled');
      $('btn-export-review-markers').removeAttribute('disabled');
      setReviewStatus('Review files found. Build Review or Process Review.', 'ready');
      reviewLogger.info('Auto-detected review: video=' + latestVideo.name + ', transcript=' + latestTranscript.name);
      if (captionsSrt) reviewLogger.info('Auto-detected captions SRT: ' + captionsSrt.name);
      if (transcriptSrt) reviewLogger.info('Auto-detected transcript SRT: ' + transcriptSrt.name);
    } else if (latestVideo) {
      setReviewStatus('Video found in 03_Exports/. Press Process Review.', 'ready');
      reviewLogger.info('Auto-detected video: ' + latestVideo.name + ' (no transcript yet)');
    }
  } catch (revDetectErr) {
    // Non-fatal
  }
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
  collapseProjectSection(extractProjectCode(projectState.projectName));
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
  $('btn-verify-ingest').removeAttribute('disabled');
  $('btn-sync-audio').removeAttribute('disabled');

  ingestLogger.info('Ingest loaded: ' + ingest.clips.length + ' clips, project "' + ingest.project_name + '" (code: ' + ingest.project_code + ')');

  $('btn-finesync').removeAttribute('disabled');
  $('btn-sync-spread').removeAttribute('disabled');
  $('btn-sync-select').removeAttribute('disabled');
  $('btn-sync-clean').removeAttribute('disabled');
  $('btn-sync-collect').removeAttribute('disabled');

  // Check if sequences already exist in the Premiere project
  var existingSeqs = await detectExistingSequences(ingest);
  if (existingSeqs.length > 0) {
    setIngestStatus('Sequences built (' + existingSeqs.length + '). Rebuild if needed.', 'ready');
    $('btn-build-ingest').textContent = 'Rebuild Ingest';
    ingestLogger.info('Found ' + existingSeqs.length + ' existing sequence(s): ' + existingSeqs.join(', '));
  } else {
    setIngestStatus('Ingest loaded. Ready to build.', 'ready');
  }
  warnIfNoFineSync(ingest);
  await renderIngestSceneList(ingest, existingSeqs);
}

/**
 * Warn when a wall-clock ingest was never fine-synced.
 *
 * The builder places everything from wall_offset, so a coarse ingest yields a
 * coarse timeline with nothing on screen to show it — the lav just sits 15-20
 * frames off the lips. Say it out loud before the build, not after.
 */
function warnIfNoFineSync(ingest) {
  if (!ingest || ingest.layout_mode !== 'wallclock') return;
  if (ingest.fine_sync && ingest.fine_sync.applied_at) return;
  ingestLogger.warn('No fine sync in this ingest — clips sit at speech accuracy (±0.6-0.9 s = 15-20 frames). '
    + 'Press "Fine Sync" before building if you intend to cut on the lav.');
}

/**
 * Fine Sync — точный синхрон по звуку перед сборкой.
 *
 * Внутри UXP это сделать нельзя: нужен ffmpeg и разбор сотен гигабайт медиа.
 * Поэтому панель передаёт путь к ingest через /tmp и запускает .command в
 * Терминале — тот же приём, что у Screen Cues PNG и Pre-Edit .docx. Скрипт
 * правит wall_offset прямо в ingest (с бэкапом), панель дожидается этого,
 * перечитывает файл и сама обновляет сводку.
 *
 * Ничего в Premiere при этом не меняется: поправки живут в ingest, поэтому
 * после них секвенции надо ПЕРЕСОБРАТЬ.
 */
async function runFineSync() {
  if (!ingestState.filePath) {
    setIngestStatus('Load ingest first', 'error');
    return;
  }
  var target = ingestState.filePath;
  var before = (ingestState.data && ingestState.data.fine_sync && ingestState.data.fine_sync.applied_at) || '';
  var homePath = require('os').homedir();
  var toolDir = homePath + '/YTAI/scripts/999_extra/audio_finesync';

  ingestLogger.info('=== FINE SYNC (audio cross-correlation) ===');
  ingestLogger.info('Target: ' + target);
  setIngestStatus('Fine sync running in Terminal — watch that window', 'waiting');
  $('btn-finesync').setAttribute('disabled', 'true');

  try {
    var tmpDir = await uxpfs.getEntryWithUrl('file:///tmp');
    var tmpFile = await tmpDir.createFile('ytai_finesync_target.txt', { overwrite: true });
    await tmpFile.write(target);
    ingestLogger.debug('Target written to /tmp/ytai_finesync_target.txt');
  } catch (tmpErr) {
    ingestLogger.error('Cannot write /tmp/ytai_finesync_target.txt: ' + tmpErr.message);
    setIngestStatus('Cannot write temp file', 'error');
    $('btn-finesync').removeAttribute('disabled');
    return;
  }

  try {
    await require('uxp').shell.openPath(toolDir + '/finesync.command');
    ingestLogger.info('Launched finesync.command');
  } catch (shellErr) {
    ingestLogger.warn('shell.openPath failed: ' + shellErr.message);
    var manual = 'python3 "' + toolDir + '/finesync_run.py" "' + target + '" --apply';
    try { await navigator.clipboard.writeText(manual); } catch (e) { /* clipboard optional */ }
    ingestLogger.info('Manual: ' + manual);
    setIngestStatus('Launch failed — command copied to clipboard, run it in Terminal', 'error');
    $('btn-finesync').removeAttribute('disabled');
    return;
  }

  // Ждём, пока Терминал допишет поправки, и перечитываем ingest сами.
  var waitedSec = 0;
  var poll = setInterval(async function () {
    waitedSec += 5;
    if (waitedSec > 30 * 60) {
      clearInterval(poll);
      ingestLogger.warn('Fine sync: gave up waiting after 30 min — reload the ingest manually');
      $('btn-finesync').removeAttribute('disabled');
      return;
    }
    try {
      var entry = await uxpfs.getEntryWithUrl('file://' + target);
      var raw = await entry.read();
      var appliedAt = ((JSON.parse(raw) || {}).fine_sync || {}).applied_at || '';
      if (!appliedAt || appliedAt === before) return;
      clearInterval(poll);
      await loadIngestFromPath(target);
      $('btn-finesync').removeAttribute('disabled');
      setIngestStatus('Fine sync applied — REBUILD the sequences to get it', 'ready');
      ingestLogger.info('Fine sync applied ' + appliedAt + ' — ingest reloaded. Rebuild sequences.');
    } catch (readErr) {
      // файл может быть в процессе записи — просто ждём следующего тика
    }
  }, 5000);
}

// ── Premiere-native fine sync (Spread → Clip > Synchronize → Collect) ──────
//
// The pure math lives in src/ingest/syncSpread.js (unit-tested). Here is only
// the Premiere plumbing: build the disposable *_SYNC sequence, then read the
// post-Synchronize positions back and fold them into the ingest.

const syncSpread = require('./src/ingest/syncSpread');
// sceneLayout здесь больше не нужен: выбор образца секвенции ушёл вместе с сидом —
// стенд рождается из пресета, наследовать формат не от чего.
const sequenceFactoryMod = require('./src/ingest/placement/sequenceFactory');
const sequencePresetMod = require('./src/ingest/placement/sequencePreset');
const syncSelectionMod = require('./src/ingest/placement/syncSelection');
const { SEQUENCE_DEFAULTS } = require('./src/shared/mediaSettings');

/**
 * Resolve which scene the active sequence shows: "{code}_{scene}[_SYNC]".
 * Returns null (with a status message) when it cannot.
 */
async function resolveActiveScene(project) {
  const seq = await project.getActiveSequence();
  if (!seq) { setIngestStatus('Open a scene sequence first', 'error'); return null; }
  const code = ingestState.data.project_code || '';
  let name = seq.name.replace(/_SYNC$/, '');
  if (code && name.indexOf(code + '_') === 0) name = name.slice(code.length + 1);
  const known = getIngestSceneNames(ingestState.data).map(function (s) { return s.name; });
  if (known.indexOf(name) === -1) {
    setIngestStatus('Active sequence "' + seq.name + '" is not a scene of this ingest', 'error');
    return null;
  }
  return { seq: seq, scene: name };
}

/** Manifest file path for a scene's spread session. */
function syncSessionPath(scene) {
  const dir = ingestState.filePath.replace(/[/\\][^/\\]+$/, '');
  return dir + '/finesync/sync_session_' + scene + '.json';
}

/** Записать файл в 01_Ingest/finesync/ и вернуть его путь. */
async function writeFinesyncFile(name, text) {
  const dir = ingestState.filePath.replace(/[/\\][^/\\]+$/, '');
  let fsDir;
  try { fsDir = await uxpfs.getEntryWithUrl('file://' + dir + '/finesync'); }
  catch (e) {
    const parent = await uxpfs.getEntryWithUrl('file://' + dir);
    fsDir = await parent.createFolder('finesync');
  }
  const f = await fsDir.createFile(name, { overwrite: true });
  await f.write(text);
  return dir + '/finesync/' + name;
}

/**
 * SPREAD: lay every source of the active scene on its own track pair at raw
 * wall-clock positions (whole lav files, no slicing, 30 s preroll), so the
 * human can select all and run Clip → Synchronize. One clip per track is the
 * configuration Synchronize requires — with several on one track it greys out.
 */
async function spreadForSync() {
  if (!ingestState.data) { setIngestStatus('Load ingest first', 'error'); return; }
  const project = await ppro.Project.getActiveProject();
  if (!project) { setIngestStatus('No active project', 'error'); return; }
  const at = await resolveActiveScene(project);
  if (!at) return;
  const scene = at.scene;

  $('btn-sync-spread').setAttribute('disabled', 'true');
  ingestLogger.info('=== SYNC SPREAD: ' + scene + ' ===');
  try {
    const ingest = ingestState.data;
    const sceneClips = ingest.clips.filter(function (c) { return c.scene === scene; });

    // ⚠️ В стенд идёт tx_strips_source, а не tx_strips.
    // После 0113_frame_align.py tx_strips — это РЕНДЕР под текущую раскладку
    // блоков, и поправка уже запечена в сам звук: wall_offset там 0. Любая
    // дельта, снятая с такого файла, бессмысленна, а записать её — значит
    // обесценить рендер (звук-то останется на месте).
    // tx_strips_source — это НЕ записи рекордера, а срезы урока от lavcut.py
    // (`{CODE}_{урок}_TX01_timeline.wav`); у них ЕСТЬ измеренный wall_offset
    // (0,1386 с на YTUVIE01) — именно его Synchronize и может поправить.
    const txSource = (ingest.tx_strips_source && ingest.tx_strips_source[scene]) || null;
    const txStrips = txSource || (ingest.tx_strips && ingest.tx_strips[scene]) || [];
    if (!txSource && txStrips.length) {
      ingestLogger.warn('spread: tx_strips_source нет — беру tx_strips. Если 0113 уже '
        + 'отработал, в стенде окажется рендер с wall_offset 0: двигать его нечем');
    }

    const fps = (ingest.scene_fps && ingest.scene_fps[scene])
      || (ingest.media && ingest.media.fps) || 25;
    // Звуковой стенд: всё audio-only, по источнику на дорожку, позиции на
    // кадровой сетке. Экран и ролики-примеры в раскладку не идут — их место
    // не измеряется по студийному звуку (см. planSpread, инвариант L6).
    const planned = syncSpread.planSpread(sceneClips, txStrips, { mode: 'bench', fps: fps });
    if (!planned.manifest) throw new Error('Scene has no placeable sources');
    planned.warnings.forEach(function (w) { ingestLogger.warn('spread: ' + JSON.stringify(w)); });
    // Контракт проверяем ДО любого обращения к Premiere: дешевле отказаться
    // на числах, чем оставить в проекте полусобранную секвенцию.
    syncSpread.assertSpreadContract(planned.manifest);

    // Resolve ProjectItems.
    // ⚠️ Часть источников стенда в проекте ОТСУТСТВУЕТ, и это нормально: сборка
    // сцены импортирует петличку-рендер (`TX01_{сцена}_timeline.wav`), а стенду
    // нужен её предок из `tx_strips_source` (`{CODE}_{урок}_TX01_timeline.wav`) —
    // его на таймлайн никто не кладёт, и в проект он не попадал. Файл на диске
    // есть, поэтому недостающее импортируем сами, а не требуем «build first».
    const itemByFilename = {};
    const toImport = [];
    for (const p of planned.placements) {
      if (itemByFilename[p.filename] !== undefined) continue;
      itemByFilename[p.filename] = await findProjectItemByName(project, p.filename, ingestLogger);
      if (!itemByFilename[p.filename]) {
        if (!p.path) {
          throw new Error('Media not in project and no path in ingest: ' + p.filename);
        }
        toImport.push(p.path);
      }
    }
    if (toImport.length) {
      ingestLogger.info('spread: импортирую в проект ' + toImport.length + ' файл(ов): '
        + toImport.map(function (x) { return x.replace(/^.*[/\\]/, ''); }).join(', '));
      try {
        await project.importFiles(toImport, true, null, false);
      } catch (impErr) {
        // по одному: один битый файл не должен уронить весь импорт
        ingestLogger.warn('spread: пакетный импорт не прошёл (' + impErr.message + ') — по одному');
        for (const f of toImport) {
          try { await project.importFiles([f], true, null, false); }
          catch (e2) { ingestLogger.error('spread: не импортировался ' + f + ' — ' + e2.message); }
        }
      }
      for (const p of planned.placements) {
        if (itemByFilename[p.filename]) continue;
        itemByFilename[p.filename] = await findProjectItemByName(project, p.filename, ingestLogger);
        if (!itemByFilename[p.filename]) {
          throw new Error('Media not in project after import: ' + p.filename
            + ' (' + p.path + ') — check that the file is still on disk');
        }
      }
    }

    const seqName = (ingest.project_code || 'YT') + '_' + scene + '_SYNC';
    setIngestStatus('Spreading ' + planned.placements.length + ' sources → ' + seqName + '...', 'waiting');
    // ⚠️ Снести ТЁЗОК до создания. Premiere разрешает одноимённые секвенции, и
    // это не теория: автосейв YTUVIE01 от 21:36 нёс ДВЕ штуки `…_SYNC`, обе
    // пустые. Брошенная раскладка перехватывала бы поиск по имени.
    try {
      const stale = {}; stale[seqName] = true;
      await deleteSequencesByName(project, stale);
    } catch (e) {
      ingestLogger.warn(`spread: снос старой ${seqName} не удался (${e.message}) — продолжаю`);
    }

    // ── Секвенция рождается ИЗ ПРЕСЕТА ────────────────────────────────────
    // Пресет создаёт нужное число дорожек сам: ни сида, ни преднагрева, а
    // значит и ни одного огрызка. И только пресет умеет включить ЦЕЛИ
    // аудиодорожек (`mTargeted`) — API таргетинга в UXP нет, а без целей
    // Clip → Synchronize, по всем признакам, остаётся серым.
    const media = Object.assign({}, ingest.media || {});
    const aNeeded = planned.manifest.nAudioTracks;
    // ⚠️ Видеодорожек нужно столько же, сколько камерных клипов: каждому своя,
    // иначе Premiere свалит всё видео на V1 и Synchronize снова погаснет.
    const vNeeded = Math.max(1, planned.manifest.nVideoTracks);
    let sequence = null;
    try {
      let stockXml = null;
      try {
        const stock = await uxpfs.getEntryWithUrl('file://' + SEQUENCE_DEFAULTS.presetPath);
        stockXml = await stock.read();
      } catch (e) {
        ingestLogger.warn(`spread: стоковый пресет не прочитан (${e.message}) — беру встроенный`);
      }
      const xml = sequencePresetMod.buildPresetXml(stockXml, {
        aTracks: aNeeded, vTracks: vNeeded, targeted: true, syncLock: false, locked: false,
        fps: fps, width: media.width, height: media.height,
        sampleRate: media.sample_rate, name: seqName,
      });
      const presetPath = await writeFinesyncFile(seqName + '.sqpreset', xml);
      ingestLogger.info(`spread: пресет на V${vNeeded}/A${aNeeded} → ${presetPath}`);
      sequence = await sequenceFactoryMod.createFromPreset(project, seqName, presetPath,
        { vTracks: vNeeded, aTracks: aNeeded }, ingestLogger);
    } catch (e) {
      ingestLogger.warn(`spread: путь через пресет не вышел (${e.message})`);
    }

    // Откат на прежний путь: сид + преднагрев. Он оставит огрызки, но выделение
    // ставит панель, а не ⌘A, поэтому мусор в выделение всё равно не попадёт.
    let seqEditor;
    if (!sequence) {
      ingestLogger.warn('spread: откат на create()+ensureTracks — будут огрызки преднагрева');
      const seedItem = itemByFilename[planned.placements[0].filename];
      sequence = await sequenceFactoryMod.create(project, seqName, media, ingestLogger, seedItem);
      seqEditor = ppro.SequenceEditor.getEditor(sequence);
      const tracks = await sequenceFactoryMod.ensureTracks(project, sequence, seqEditor, seedItem,
        vNeeded, aNeeded, ingestLogger, { coverAtSec: null });
      if (tracks && (tracks.aCount < aNeeded || tracks.vCount < vNeeded)) {
        throw new Error('Pre-warm gave V' + tracks.vCount + '/A' + tracks.aCount
          + ' of needed V' + vNeeded + '/A' + aNeeded
          + ' — spread aborted (delete ' + seqName + ' and retry, or use Fine Sync)');
      }
    } else {
      seqEditor = ppro.SequenceEditor.getEditor(sequence);
    }

    // ── Укладка: ПО ОДНОЙ ТРАНЗАКЦИИ НА ИСТОЧНИК, по возрастанию времени ──
    // ⚠️ Пакетный компаунд выполняет действия В ОБРАТНОМ порядке (замерено
    // YTCH13 16.08.2026, см. wallClockBuilder.js). Прежний Spread складывал все
    // перезаписи в одну транзакцию — единственное такое место в репозитории, —
    // и секвенция `_SYNC` на YTUVIE01 осталась вообще без настоящих клипов.
    //
    // ⚠️ Камерный клип кладём ПЕРЕЗАПИСЬЮ на свою пару V/A. Вставка с `-1`
    // (audio-only) на A/V-клипе НЕ работает: проверено на YTUVIE01 24.09 —
    // Premiere всё равно положила видео, и всё на V1, а рипл растолкал куски на
    // 2100+ с; вышло 19 айтемов на одной дорожке и серый Synchronize.
    // Перезапись ничего не двигает и не создаёт дорожек — они уже есть из пресета.
    // Петличка — настоящий WAV, для неё `-1` работает как надо.
    const ordered = planned.placements.slice()
      .sort(function (a, b) { return a.offsetSec - b.offsetSec; });
    for (const p of ordered) {
      const t = ppro.TickTime.createWithSeconds(p.offsetSec);
      await project.lockedAccess(async function () {
        await project.executeTransaction(function (ca) {
          ca.addAction(p.vIdx >= 0
            ? seqEditor.createOverwriteItemAction(itemByFilename[p.filename], t, p.vIdx, p.aIdx)
            : seqEditor.createInsertProjectItemAction(itemByFilename[p.filename], t, -1, p.aIdx, true));
        }, 'Sync bench ' + p.filename);
      });
    }

    // Проверяем, что легло, а не верим, что легло.
    const placedItems = await syncSelectionMod.readSequenceItems(sequence);
    const placedReal = placedItems.filter(function (a) {
      return typeof a.durationSec !== 'number' || a.durationSec >= syncSpread.MIN_SYNC_ITEM_SEC;
    });
    if (placedReal.length < planned.manifest.items.length) {
      throw new Error(placedReal.length + ' of ' + planned.manifest.items.length
        + ' sources are on the timeline — the spread did not land; run sync_ready.py');
    }

    // Persist the manifest — Collect may happen after a panel reload.
    // ⚠️ `source` обязателен: в тот же файл пишет и spread_fcpxml.py, и панельный
    // прогон уже затирал скриптовый (YTUVIE01, 21:57 поверх 21:37). Без пометки
    // Collect прочитает чужой манифест и отчитается «не нашлись на таймлайне».
    planned.manifest.source = 'panel:spreadForSync';
    try {
      await writeFinesyncFile('sync_session_' + scene + '.json',
        JSON.stringify(planned.manifest, null, 2));
    } catch (mfErr) {
      ingestLogger.warn('Manifest not persisted (' + mfErr.message + ') — Collect must run in this panel session');
    }
    ingestState.syncSession = { scene: scene, manifest: planned.manifest };

    // Выделение ставит панель, а не человек: ⌘A ловит однокадровый мусор, и на
    // дорожке оказывается два выделенных айтема — ровно та конфигурация, при
    // которой Premiere гасит Clip → Synchronize.
    let sel = null;
    try {
      await project.setActiveSequence(sequence);
    } catch (e) {
      ingestLogger.debug('setActiveSequence: ' + e.message);
    }
    try {
      sel = await syncSelectionMod.selectForSync(project, sequence, planned.manifest, ingestLogger);
    } catch (selErr) {
      ingestLogger.error('Выделение не поставлено: ' + selErr.message);
    }

    const nSel = sel ? sel.selected : 0;
    const nTracks = sel ? Object.keys(sel.perTrack).length : planned.manifest.nAudioTracks;
    setIngestStatus(sel
      ? ('Sync bench ready: ' + nSel + ' sources on ' + nTracks + ' audio tracks, selection set. '
         + 'Click the timeline, then Clip > Synchronize → Audio')
      : ('Sync bench built, but the selection did not take — press Select'),
      sel ? 'ready' : 'error');
    ingestLogger.info('Spread: ' + planned.placements.length + ' источников audio-only в ' + seqName
      + (sel ? ', выделено ' + nSel : '') + '. Дальше: Clip > Synchronize, потом Collect.');
  } catch (err) {
    ingestLogger.error('Sync spread failed: ' + err.message);
    setIngestStatus('Spread failed: ' + err.message, 'error', err);
  } finally {
    $('btn-sync-spread').removeAttribute('disabled');
  }
}

/**
 * Положить в буфер готовую просьбу проверить синхрон — чтобы Роман просто
 * вставил её в чат, а не собирал путь руками.
 *
 * ⚠️ В блоке ТОЛЬКО полезная нагрузка: фраза и путь. Ни заголовков, ни рамок —
 * их потом вычищать руками. Фраза по-английски: это производственный артефакт.
 */
async function copyCheckSyncRequest() {
  // ingestState.filePath = {проект}/00_Setup/01_Ingest/{CODE}_ingest.json
  const projectRoot = (ingestState.filePath || '').replace(/\/00_Setup\/.*$/, '');
  const payload = 'check all syncs\n' + projectRoot;
  let copied = false;
  try { require('uxp').clipboard.copyText(payload); copied = true; } catch (e) { /* fallback below handles it (navigator.clipboard) */ }
  if (!copied) {
    try { await navigator.clipboard.setContent({ 'text/plain': payload }); copied = true; } catch (e) { /* warn at line 1291 reports failure with the payload */ }
  }
  if (!copied) ingestLogger.warn('Буфер недоступен, скопируй вручную:\n' + payload);
  return copied;
}

/** Манифест раскладки сцены: из памяти панели, иначе с диска. */
async function loadSyncManifest(scene) {
  if (ingestState.syncSession && ingestState.syncSession.scene === scene) {
    return ingestState.syncSession.manifest;
  }
  const entry = await uxpfs.getEntryWithUrl('file://' + syncSessionPath(scene));
  return JSON.parse(await entry.read());
}

/**
 * SELECT FOR SYNC: выделить ровно источники манифеста.
 *
 * Отдельной кнопкой — потому что выделение живёт не дольше одного щелчка по
 * таймлайну, а Spread мог быть сделан в прошлой сессии панели.
 */
async function selectForSyncClick() {
  if (!ingestState.data) { setIngestStatus('Load ingest first', 'error'); return; }
  const project = await ppro.Project.getActiveProject();
  if (!project) { setIngestStatus('No active project', 'error'); return; }
  const seq = await project.getActiveSequence();
  if (!seq || !/_SYNC$/.test(seq.name)) {
    setIngestStatus('Open the *_SYNC sequence — selection happens there', 'error');
    return;
  }
  const at = await resolveActiveScene(project);
  if (!at) return;

  $('btn-sync-select').setAttribute('disabled', 'true');
  try {
    const manifest = await loadSyncManifest(at.scene);
    const r = await syncSelectionMod.selectForSync(project, seq, manifest, ingestLogger);
    let msg = 'Selected ' + r.selected + ' on ' + Object.keys(r.perTrack).length
      + ' tracks. Click the timeline, then Clip > Synchronize → Audio';
    if (r.missing.length) msg += ' · not found: ' + r.missing.length;
    if (r.skippedShort) msg += ' · one-frame strays skipped: ' + r.skippedShort;
    setIngestStatus(msg, 'ready');
    if (r.strays.length) {
      ingestLogger.warn('Огрызки на дорожках: '
        + r.strays.map(function (s) { return s.track; }).join(', ')
        + ' — кнопка Clean их выделит');
    }
  } catch (err) {
    ingestLogger.error('Select for Sync: ' + err.message);
    setIngestStatus('Selection failed: ' + err.message, 'error', err);
  } finally {
    $('btn-sync-select').removeAttribute('disabled');
  }
}

/**
 * CLEAN: выделить весь однокадровый мусор преднагрева.
 *
 * Сносить его API в живом Premiere отказывается (removeAllItemsOnTrack
 * отрабатывает вхолостую), поэтому честный результат — оставить выделенным:
 * человек жмёт ⌫ и мусора больше нет.
 */
async function cleanStraysClick() {
  const project = await ppro.Project.getActiveProject();
  if (!project) { setIngestStatus('No active project', 'error'); return; }
  const seq = await project.getActiveSequence();
  if (!seq) { setIngestStatus('Open a sequence first', 'error'); return; }

  $('btn-sync-clean').setAttribute('disabled', 'true');
  try {
    const r = await syncSelectionMod.selectStrays(project, seq, ingestLogger);
    if (!r.found) {
      setIngestStatus('No one-frame strays — nothing to clean', 'ready');
    } else {
      setIngestStatus(r.found + ' one-frame strays selected ('
        + r.list.map(function (x) { return x.track; }).join(', ') + ') — press ⌫', 'ready');
    }
  } catch (err) {
    ingestLogger.error('Clean: ' + err.message);
    setIngestStatus('Clean failed: ' + err.message, 'error', err);
  } finally {
    $('btn-sync-clean').removeAttribute('disabled');
  }
}

/**
 * COLLECT: read the post-Synchronize positions from the *_SYNC sequence,
 * diff against the spread manifest, fold the deltas into the ingest on disk
 * (with a backup), reload it, and tell the human to rebuild the scene.
 */
async function collectFromSync() {
  if (!ingestState.data) { setIngestStatus('Load ingest first', 'error'); return; }
  const project = await ppro.Project.getActiveProject();
  if (!project) { setIngestStatus('No active project', 'error'); return; }
  const seq = await project.getActiveSequence();
  if (!seq || !/_SYNC$/.test(seq.name)) {
    setIngestStatus('Open the *_SYNC sequence first (its positions are the corrections)', 'error');
    return;
  }
  const at = await resolveActiveScene(project);
  if (!at) return;
  const scene = at.scene;

  $('btn-sync-collect').setAttribute('disabled', 'true');
  ingestLogger.info('=== SYNC COLLECT: ' + scene + ' ===');
  try {
    // Manifest: panel state, else the persisted file
    let manifest = ingestState.syncSession && ingestState.syncSession.scene === scene
      ? ingestState.syncSession.manifest : null;
    if (!manifest) {
      const entry = await uxpfs.getEntryWithUrl('file://' + syncSessionPath(scene));
      manifest = JSON.parse(await entry.read());
    }

    setIngestStatus('Reading positions from ' + seq.name + '...', 'waiting');
    const actual = await syncSelectionMod.readSequenceItems(seq);
    const deltas = syncSpread.collectDeltas(manifest, actual);
    if (deltas.missing.length) {
      ingestLogger.warn('Missing on timeline (deleted?): ' + deltas.missing.join(', '));
    }
    // ⚠️ В sync_session_{scene}.json пишут ДВОЕ — панель и spread_fcpxml.py, — и
    // панельный прогон уже затирал скриптовый (YTUVIE01, 21:57 поверх 21:37).
    // У них разная раскладка (аудио против видео), поэтому чужой манифест даёт
    // «не нашлось всё» — и это надо сказать словами, а не молча собрать нули.
    if (deltas.missing.length === manifest.items.length) {
      throw new Error('no manifest source found on the timeline. The manifest comes from "'
        + (manifest.source || 'unknown') + '", the spread in ' + seq.name
        + ' was not built from it. Rebuild Spread the same way as the manifest');
    }

    // ── Сначала ОТЧЁТ, запись потом ──────────────────────────────────────
    // ⚠️ Вставка округляет позицию до ближайшего кадра, и наши собственные
    // позиции тоже квантованы. Значит разрешение этой петли — кадр (40 мс при
    // 25p), а численный синхрон уже держит 13,2 мс. Молча писать сюда поверх
    // значит менять хорошее на худшее.
    const collectFps = manifest.fps || (ingestState.data.media && ingestState.data.media.fps) || 25;
    const frameSec = 1 / collectFps;
    const rows = Object.keys(deltas.clips).map(function (id) {
      return { id: id, resid: deltas.clips[id], raw: deltas.raw[id] };
    }).sort(function (a, b) { return Math.abs(b.resid) - Math.abs(a.resid); });
    ingestLogger.info('Collect: общий сдвиг (base) ' + (deltas.base * 1000).toFixed(1)
      + ' мс — сам по себе он синхронно пуст и вычтен');
    rows.forEach(function (r) {
      ingestLogger.info('   ' + r.id + '  остаток ' + (r.resid * 1000).toFixed(1) + ' мс ('
        + (r.resid / frameSec).toFixed(2) + ' кадра)');
    });
    Object.keys(deltas.txFiles).forEach(function (f) {
      ingestLogger.info('   петличка ' + f + '  остаток '
        + (deltas.txFiles[f] * 1000).toFixed(1) + ' мс — в ингест НЕ пишется (рендер 0113)');
    });

    // Вердикт снят — кладём в буфер просьбу проверить, чтобы её осталось вставить.
    const copied = await copyCheckSyncRequest();
    const tail = copied ? ' · «check all syncs» + path copied to the clipboard' : '';

    if (deltas.moved === 0) {
      setIngestStatus('Nothing moved — either Clip > Synchronize was not run, '
        + 'or Premiere agrees with our sync' + tail, 'ready');
      return;
    }
    // ⚠️ Порог — СОВЕТ, а не запрет. Остаток меньше кадра означает «Premiere не
    // умеет измерить точнее, чем у нас уже есть», и писать обычно не надо. Но
    // решает человек: запрет лишил бы его возможности собрать второй вариант и
    // сравнить глазами, а это единственный способ разрешить спор двух приборов.
    const below = deltas.maxAbsSec < frameSec;
    if (!(ingestState.collectArmed && ingestState.collectArmed.scene === scene)) {
      ingestState.collectArmed = { scene: scene };
      setIngestStatus(below
        ? ('Premiere agrees: worst residual ' + (deltas.maxAbsSec * 1000).toFixed(1)
           + ' ms — under one frame, NO need to write. Table in the log. To build '
           + 'a second variant anyway, press Collect again' + tail)
        : ('Worst residual ' + (deltas.maxAbsSec * 1000).toFixed(1) + ' ms ('
           + (deltas.maxAbsSec / frameSec).toFixed(2) + ' frames) across ' + deltas.moved
           + ' sources. Table in the log. Press Collect AGAIN to write it into the ingest'
           + tail),
        below ? 'ready' : 'waiting');
      return;
    }
    ingestState.collectArmed = null;
    ingestLogger.warn('Collect: пишу в ингест по второму щелчку'
      + (below ? ' — хотя остаток меньше кадра и Premiere с нами согласна' : ''));

    // Anti-stale: the deltas are RELATIVE (post-Synchronize − placed), so they
    // fold safely into whatever is on disk NOW — but only if we merge into the
    // fresh file, not the memory copy from folder-select time. Same guard as
    // buildIngest; without it Collect would silently revert e.g. a wordsync
    // re-run that happened after Spread.
    await loadIngestFromPath(ingestState.filePath);

    // ...and only if the scene's offsets still match what Spread laid out.
    // If something (finesync, wordsync re-run) already moved them, folding the
    // deltas on top would DOUBLE the correction — abort and ask to re-Spread.
    var driftCount = 0;
    for (const want of manifest.items) {
      if (want.kind !== 'clip') continue;
      const clip = ingestState.data.clips.find(function (c) {
        return c.scene === scene && (c.clip_id === want.id || c.filename === want.filename);
      });
      if (!clip || typeof clip.wall_offset !== 'number') continue;
      const expectedWall = want.placedSec - manifest.preroll + manifest.t0Wall;
      if (Math.abs(clip.wall_offset - expectedWall) > 0.001) driftCount++;
    }
    if (driftCount > 0) {
      throw new Error('Ingest changed since Spread (' + driftCount + ' clip(s) moved on disk) — delete ' + seq.name + ', re-Spread and re-Synchronize');
    }

    const nowIso = new Date().toISOString().slice(0, 19);
    // Порог записи не ставим: человек уже подтвердил вторым щелчком, и глушить
    // после этого часть поправок значило бы собрать вариант, которого он не просил.
    const result = syncSpread.applyDeltasToIngest(ingestState.data, scene, deltas, nowIso);

    // Backup + write the ingest
    const target = ingestState.filePath;
    const dir = target.replace(/[/\\][^/\\]+$/, '');
    const base = target.slice(dir.length + 1).replace(/\.json$/, '');
    const stamp = nowIso.replace(/[-:T]/g, '').slice(0, 14);
    const dirEntry = await uxpfs.getEntryWithUrl('file://' + dir);
    const oldEntry = await uxpfs.getEntryWithUrl('file://' + target);
    const backup = await dirEntry.createFile(base + '_backup_syncspread_' + stamp + '.json', { overwrite: true });
    await backup.write(await oldEntry.read());
    const mainFile = await dirEntry.createFile(base + '.json', { overwrite: true });
    await mainFile.write(JSON.stringify(result.ingest, null, 2));

    await loadIngestFromPath(target);
    const ms = Math.round(result.maxAbsSec * 1000);
    setIngestStatus('Collected ' + result.applied + ' correction(s), max ' + ms + ' ms — now REBUILD scene ' + scene, 'ready');
    ingestLogger.info('Collected ' + result.applied + ' corrections (max ' + ms + ' ms, scene shift +' + result.normalizedShift.toFixed(3) + 's). Backup: ' + base + '_backup_syncspread_' + stamp + '.json');
    ingestLogger.info('The *_SYNC sequence is disposable — delete it after the rebuild.');
  } catch (err) {
    ingestLogger.error('Sync collect failed: ' + err.message);
    setIngestStatus('Collect failed: ' + err.message, 'error', err);
  } finally {
    $('btn-sync-collect').removeAttribute('disabled');
  }
}

/**
 * Scene list of a multi-scene ingest: [{name, clips}] sorted by name.
 */
function getIngestSceneNames(ingest) {
  var counts = {};
  (ingest.clips || []).forEach(function (c) {
    if (c.scene) counts[c.scene] = (counts[c.scene] || 0) + 1;
  });
  return Object.keys(counts).sort().map(function (n) { return { name: n, clips: counts[n] }; });
}

/**
 * Render per-scene checkbox list in the Ingest tab (like Parts selections).
 * Built scenes (sequence {code}_{scene} exists) are unchecked by default —
 * so the default action builds ONLY the new/missing timelines.
 * @param {Object} ingest
 * @param {string[]|null} existingSeqs - pre-detected sequence names (optional)
 */
async function renderIngestSceneList(ingest, existingSeqs) {
  var panel = $('ingest-scenes');
  var list = $('ingest-scenes-list');
  var scenes = getIngestSceneNames(ingest);
  if (!scenes.length) { panel.style.display = 'none'; list.innerHTML = ''; return; }

  if (!existingSeqs) existingSeqs = await detectExistingSequences(ingest);
  var built = {};
  existingSeqs.forEach(function (n) { built[n] = true; });
  var code = ingest.project_code || extractProjectCode(ingest.project_name);

  // One compact line per scene: [cb] name · N clips · badge. All inline flow —
  // styles live in index.html's <style> (css/styles.css is NOT loaded by the panel).
  list.innerHTML = scenes.map(function (s) {
    var isBuilt = !!(built[code + '_' + s.name] || built[s.name]);
    // A sequence that exists is not proof the build worked: readback-failed scenes
    // (this session) are flagged and ticked for rebuild.
    var bad = ingestState.readbackBad && ingestState.readbackBad[s.name];
    var badge = bad ? '<span class="scene-badge bad" title="' + escapeHtml(bad) + '">readback ✗</span>'
      : '<span class="scene-badge' + (isBuilt ? ' built' : '') + '">' + (isBuilt ? 'built ✓' : 'new') + '</span>';
    return '<div class="scene-row">' +
      '<label class="scene-pick">' +
      '<input type="checkbox" class="ingest-scene-cb" value="' + escapeHtml(s.name) + '"' + (isBuilt && !bad ? '' : ' checked') + '>' +
      '<span class="scene-name">' + escapeHtml(s.name) + '</span>' +
      '</label>' +
      '<span class="scene-meta">' + s.clips + ' clips</span>' +
      badge +
      '</div>';
  }).join('');
  panel.style.display = 'block';
}

function getSelectedIngestScenes() {
  return Array.prototype.slice.call(document.querySelectorAll('.ingest-scene-cb'))
    .filter(function (cb) { return cb.checked; })
    .map(function (cb) { return cb.value; });
}

function setIngestSceneChecks(mode) {
  Array.prototype.slice.call(document.querySelectorAll('.ingest-scene-cb')).forEach(function (cb) {
    var row = cb.closest('.scene-row');
    var isBuilt = row && row.querySelector('.scene-badge.built');
    if (mode === 'all') cb.checked = true;
    else if (mode === 'none') cb.checked = false;
    else cb.checked = !isBuilt; // 'new'
  });
}

/**
 * Shallow copy of the ingest restricted to the given scenes.
 * clips / tx_strips / cam_layers are filtered; everything else shared.
 */
function filterIngestScenes(ingest, scenes) {
  var keep = {};
  scenes.forEach(function (s) { keep[s] = true; });
  var out = Object.assign({}, ingest);
  out.clips = (ingest.clips || []).filter(function (c) { return keep[c.scene]; });
  if (ingest.tx_strips) {
    out.tx_strips = {};
    Object.keys(ingest.tx_strips).forEach(function (s) { if (keep[s]) out.tx_strips[s] = ingest.tx_strips[s]; });
  }
  if (ingest.cam_layers) {
    out.cam_layers = {};
    Object.keys(ingest.cam_layers).forEach(function (s) { if (keep[s]) out.cam_layers[s] = ingest.cam_layers[s]; });
  }
  return out;
}

/**
 * Check if ingest sequences already exist in the active Premiere project.
 * Multi-scene: looks for {code}_{sceneName} per scene.
 * Single: looks for {code}_1_Ingest.
 * @returns {string[]} names of existing sequences
 */
/**
 * Expected sequence names for an ingest: {code}_{scene} per scene (multi-scene)
 * or {code}_1_Ingest (single). Bare legacy names are included too — older builds
 * named scene sequences without the code prefix.
 */
function expectedIngestSequenceNames(ingest) {
  var code = ingest.project_code || extractProjectCode(ingest.project_name);
  var expected = {};
  var hasScenes = ingest.clips.some(function (c) { return c.scene; });
  if (hasScenes) {
    ingest.clips.forEach(function (c) {
      if (!c.scene) return;
      expected[code + '_' + c.scene] = true;
      expected[c.scene] = true;              // legacy bare name
    });
  } else {
    expected[code + '_1_Ingest'] = true;
    expected[ingest.project_name + '_1_Ingest'] = true;
  }
  return expected;
}

async function detectExistingSequences(ingest) {
  var found = [];
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) return found;
    // Match against REAL sequences only. Root items can share a sequence's name
    // without being one (offline master-clip stubs from importing another project);
    // a bare name scan of rootItem.getItems() marks those scenes "built ✓".
    var byName = await findSequencesByName(project, expectedIngestSequenceNames(ingest));
    found = Object.keys(byName);
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
    $('btn-finesync').removeAttribute('disabled');
    $('btn-verify-ingest').removeAttribute('disabled');
    $('btn-sync-audio').removeAttribute('disabled');

    setIngestStatus('Ingest loaded. Ready to build.', 'ready');
    ingestLogger.info('Ingest loaded: ' + ingest.clips.length + ' clips, project "' + ingest.project_name + '" (code: ' + ingest.project_code + ')');
    warnIfNoFineSync(ingest);
    await renderIngestSceneList(ingest);
  } catch (err) {
    ingestLogger.error('Failed to load ingest: ' + err.message);
    setIngestStatus('Error: ' + err.message, 'error', err);
  }
}

/**
 * Every REAL sequence in the project as [{name, seq}], deduped by guid (name when
 * guid is unavailable). project.getSequences() first — the reliable enumerator
 * (ppro.Sequence.cast can return null / throw for real sequences in some Premiere
 * builds, see doctorCollectUsage) — then Sequence.cast over root items as a
 * supplement for builds where getSequences under-reports. Bare name matches of
 * root items are never trusted: offline master-clip stubs from importing another
 * project can carry a sequence's name (proven by the YTUVI05 dump).
 */
async function listProjectSequences(project, logger) {
  var out = [];
  var seenGuid = {};
  var seenName = {};
  function add(s) {
    var n = ''; try { n = s.name || (s.getName && s.getName()) || ''; } catch (e) { if (logger) logger.debug('seq name read threw: ' + (e && e.message)); }
    if (!n) return;
    var g = ''; try { g = s.guid ? String(s.guid) : ''; } catch (e) { /* guid optional; name dedupe below handles it */ }
    if (g) { if (seenGuid[g]) return; seenGuid[g] = true; }
    else if (seenName[n]) return;
    seenName[n] = true;
    out.push({ name: n, seq: s });
  }
  var allSeq = [];
  try { allSeq = await project.getSequences(); }
  catch (e) { if (logger) logger.debug('getSequences threw: ' + e.message); }
  (allSeq || []).forEach(add);
  try {
    // root + 00_Source_Timelines: scene timelines are filed there (2026-09-15) and this
    // supplement exists exactly for builds where getSequences under-reports.
    var rootItems = await rootAndSourceTimelineItems(project);
    for (var i = 0; i < rootItems.length; i++) {
      var casted = null; try { casted = ppro.Sequence.cast(rootItems[i]); } catch (e) { /* non-sequence root items throw here; supplement pass only */ }
      if (casted) add(casted);
    }
  } catch (e) { if (logger) logger.debug('Root sequence scan failed: ' + e.message); }
  return out;
}

/** Root items followed by the items of the top-level 00_Source_Timelines bin (if any). */
async function rootAndSourceTimelineItems(project) {
  var items = (await (await project.getRootItem()).getItems()) || [];
  try {
    var stBin = await findRootBin(project, SOURCE_TIMELINES_BIN);
    if (stBin) items = items.concat((await stBin.getItems()) || []);
  } catch (e) { /* no bin — root only */ }
  return items;
}

/**
 * Project code for "Hide source timelines": the OPEN Premiere project first (that is the
 * project being changed — name, then path segments), then the panel's project folder /
 * loaded ingest. Accepts "YTUVI02_Ruby…" and a bare code "YTUVI02".
 */
// 2–5 letters: YTCR01 … YTUVI02 … YTRSCEN01 (same width as sourceTimelines' fallback regex)
var OPEN_PROJECT_CODE_RE = /^(YT[A-Z]{2,5}\d+)(?:_|\.|$)/;
function resolveOpenProjectCode(project) {
  var re = OPEN_PROJECT_CODE_RE;
  var cands = [];
  if (project) {
    cands.push(String(project.name || ''));
    String(project.path || '').replace(/\\/g, '/').split('/').filter(Boolean).reverse()
      .forEach(function (seg) { cands.push(seg); });
  }
  cands.push(projectState.projectName || '');
  if (ingestState.data) cands.push(ingestState.data.project_code || '', ingestState.data.project_name || '');
  cands.push(assemblyState.projectCode || '');
  for (var i = 0; i < cands.length; i++) {
    var m = String(cands[i] || '').match(re);
    if (m) return m[1];
  }
  return null;
}

/**
 * 📁 Hide source timelines (Ingest + Doctor tabs): every sequence of the OPEN project named
 * ^{CODE}_\d{2}_ (scene timelines) that is still at project ROOT → 00_Source_Timelines.
 * Verified moves (shared/binMove), idempotent, never deletes; stops after an unverified
 * first move or a duplicate-guard trip. Status: "moved N · already in bin M · failed K".
 */
var hideSourceTimelinesBusy = false;
async function onHideSourceTimelines(setStatus) {
  var btnIds = ['btn-hide-source-timelines', 'btn-doctor-hide-source-timelines'];
  function setBtns(disabled) {
    btnIds.forEach(function (id) {
      try { if (disabled) $(id).setAttribute('disabled', 'true'); else $(id).removeAttribute('disabled'); } catch (e) { /* cosmetic; button may be absent on this tab */ }
    });
  }
  if (hideSourceTimelinesBusy) return;
  if (ingestState.building) {
    setStatus('Hide source timelines: Build Ingest is running — try again when it finishes', 'error');
    return;
  }
  // Claim the guard synchronously, BEFORE any await — a double-click or Ingest+Doctor
  // clicks must not start two batches (two createBinAction → "00_Source_Timelines 01").
  hideSourceTimelinesBusy = true;
  setBtns(true);
  try {
    var project = null;
    try { project = await ppro.Project.getActiveProject(); } catch (e) { project = null; }
    if (!project) { setStatus('Hide source timelines: open a Premiere project first', 'error'); return; }
    var code = resolveOpenProjectCode(project);
    if (!code) {
      setStatus('Hide source timelines: no project code (need a YT…NN_ project name)', 'error');
      return;
    }
    var panelMatch = String(projectState.projectName || '').match(OPEN_PROJECT_CODE_RE);
    var panelCode = panelMatch ? panelMatch[1] : null;
    if (panelCode && panelCode !== code) {
      ingestLogger.warn('Hide source timelines: open project is ' + code + ' but the panel folder is ' + panelCode + ' — using the OPEN project ' + code);
    }
    setStatus('Hiding ' + code + '_NN_* source timelines → ' + SOURCE_TIMELINES_BIN + '...', 'waiting');
    ingestLogger.info('=== HIDE SOURCE TIMELINES (' + code + ', sourceTimelines v' + SOURCE_TIMELINES_VERSION + ') ===');
    var report = await hideSourceTimelines(project, code, ingestLogger, { listSequences: listProjectSequences });
    if (!report.total) {
      setStatus('Hide source timelines: no ' + code + '_NN_* sequences in this project', report.stopped ? 'error' : 'ready');
    } else {
      setStatus('Source timelines → ' + SOURCE_TIMELINES_BIN + ': ' + formatHideReport(report),
        (report.failed || report.stopped) ? 'error' : 'ready');
    }
    if (report.names.failed.length) ingestLogger.warn('Left in root: ' + report.names.failed.join(', '));
    if (report.names.skipped.length) ingestLogger.info('Skipped: ' + report.names.skipped.join(', '));
  } catch (err) {
    ingestLogger.error('Hide source timelines failed: ' + err.message);
    setStatus('Hide source timelines: ' + err.message, 'error');
  } finally {
    hideSourceTimelinesBusy = false;
    setBtns(false);
  }
}

/**
 * Resolve wanted names to REAL Sequence objects.
 * @returns {Object} {name: [Sequence, ...]} — arrays, because Premiere allows
 * duplicate sequence names (e.g. a local build next to an imported copy) and a
 * rebuild must remove ALL of them, not just the first.
 */
async function findSequencesByName(project, wantedNames) {
  var byName = {};
  var all = await listProjectSequences(project, ingestLogger);
  all.forEach(function (e) {
    if (wantedNames[e.name]) (byName[e.name] = byName[e.name] || []).push(e.seq);
  });
  return byName;
}

async function deleteSequencesByName(project, wantedNames) {
  var seqs = await findSequencesByName(project, wantedNames);
  for (var name in seqs) {
    for (var i = 0; i < seqs[name].length; i++) {
      try { await project.deleteSequence(seqs[name][i]); ingestLogger.info('Deleted old sequence: "' + name + '"'); }
      catch (e) { ingestLogger.debug('Cannot delete sequence "' + name + '": ' + e.message); }
    }
  }
}

async function cleanBeforeBuild(project, ingest) {
  var shortCode = ingest.project_code || extractProjectCode(ingest.project_name);
  var wanted = {};
  wanted[shortCode + '_1_Ingest'] = true;
  wanted[ingest.project_name + '_1_Ingest'] = true;
  ingestLogger.info('=== Clean before build ===');

  await deleteSequencesByName(project, wanted);

  const rootItem = await project.getRootItem();
  const allItems = await rootItem.getItems();

  for (const item of allItems) {
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
          } catch (e) { ingestLogger.debug('Cannot remove ' + child.name + ': ' + (e && e.message)); }
        }
      }
    } catch (e) { ingestLogger.debug('Clean: skip root item ' + (item && item.name) + ': ' + (e && e.message)); }
  }
  ingestLogger.info('Clean complete');
}

/**
 * Selective clean for multi-scene builds: touches ONLY the given scenes.
 * Deletes their sequences ({code}_{scene}) and their per-scene bins under
 * 00_Source ({code}_{scene} and {code}_{scene}_transcripts). Other scenes'
 * sequences, bins and project items stay intact.
 */
async function cleanScenesBeforeBuild(project, ingest, scenes) {
  var code = ingest.project_code || extractProjectCode(ingest.project_name);
  ingestLogger.info('=== Clean before build (scenes: ' + scenes.join(', ') + ') ===');
  var names = {};
  scenes.forEach(function (s) {
    names[code + '_' + s] = true;
    names[s] = true;                       // legacy bare-named scene sequences
  });

  await deleteSequencesByName(project, names);

  const rootItem = await project.getRootItem();
  const allItems = await rootItem.getItems();

  for (const item of allItems) {
    try {
      const folder = ppro.FolderItem.cast(item);
      if (!folder || item.name !== BIN_NAMES.SOURCE) continue;
      const children = await folder.getItems();
      for (const child of children) {
        var base = child.name.replace(/_transcripts$/, '');
        if (!names[base]) continue;
        try {
          project.lockedAccess(() => {
            project.executeTransaction((ca) => {
              ca.addAction(folder.createRemoveItemAction(child));
            }, 'Remove ' + child.name);
          });
          ingestLogger.info('Removed bin: ' + child.name);
        } catch (e) { ingestLogger.debug('Cannot remove bin ' + child.name + ': ' + e.message); }
      }
    } catch (e) { ingestLogger.debug('Clean: skip root item ' + (item && item.name) + ': ' + (e && e.message)); }
  }
  ingestLogger.info('Clean complete (selective)');
}

async function buildIngest() {
  if (!ingestState.data) { ingestLogger.error('No ingest loaded'); return; }
  if (ingestState.building) { ingestLogger.warn('Build already in progress'); return; }

  // Anti-stale guard: the ingest on disk may be newer than the copy loaded at
  // folder-select time (fine sync, wordsync re-run, manual edit). Building
  // from a stale in-memory copy silently produces a timeline with the OLD
  // offsets — re-read the file every time; it is ~100 KB, the cost is nothing.
  if (ingestState.filePath) {
    try {
      const keepTicked = getSelectedIngestScenes();  // reload re-renders the list
      // Remember which scenes EXISTED before the reload: a scene that is new
      // on disk (wordsync re-run added it) must keep its freshly-rendered
      // default tick, not be force-unchecked by the restore below.
      const preExisting = Array.prototype.map.call(
        document.querySelectorAll('.ingest-scene-cb'), function (cb) { return cb.value; });
      const before = ingestState.data && ingestState.data.fine_sync && ingestState.data.fine_sync.applied_at;
      await loadIngestFromPath(ingestState.filePath);
      const after = ingestState.data && ingestState.data.fine_sync && ingestState.data.fine_sync.applied_at;
      if (before !== after) {
        ingestLogger.info('Ingest re-read from disk: fine_sync changed (' + before + ' → ' + after + ')');
      }
      // Restore the user's tick selection — but only for scenes that already
      // existed; new-on-disk scenes keep their rendered default.
      document.querySelectorAll('.ingest-scene-cb').forEach(function (cb) {
        if (preExisting.indexOf(cb.value) !== -1) {
          cb.checked = keepTicked.indexOf(cb.value) !== -1;
        }
      });
    } catch (reloadErr) {
      ingestLogger.warn('Could not re-read ingest from disk, building from memory: ' + reloadErr.message);
    }
  }

  ingestState.building = true;
  $('btn-build-ingest').setAttribute('disabled', 'true');
  $('ingest-validation').style.display = 'none';
  setIngestStatus('Building timeline...', 'waiting');
  var buildSucceeded = false;

  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');
    ingestLogger.setProjectInfo(project.name, project.path);

    const ingestFull = ingestState.data;
    // Multi-scene: build ONLY the scenes ticked in the scene list (Parts-style,
    // add timelines one by one; already-built ones stay untouched).
    const isMultiScene = ingestFull.clips.some(c => c.scene);
    let selectedScenes = null;
    let ingest = ingestFull;
    if (isMultiScene) {
      const allScenes = getIngestSceneNames(ingestFull).map(s => s.name);
      selectedScenes = getSelectedIngestScenes();
      if (selectedScenes.length === 0) {
        setIngestStatus('No sequences selected — tick at least one scene', 'error');
        ingestState.building = false;
        $('btn-build-ingest').removeAttribute('disabled');
        return;
      }
      if (selectedScenes.length < allScenes.length) {
        ingest = filterIngestScenes(ingestFull, selectedScenes);
        ingestLogger.info('Selective build: ' + selectedScenes.join(', ') + ' (' + ingest.clips.length + '/' + ingestFull.clips.length + ' clips)');
      }
    }
    const totalSteps = 6;
    let step = 0;
    const startTime = Date.now();

    ingestLogger.info('=== INGEST BUILD START ===');
    ingestLogger.info('Project: ' + project.name);
    ingestLogger.info('Clips: ' + ingest.clips.length + ', Resolution: ' + ingest.media.width + 'x' + ingest.media.height);

    var stepTimings = [];
    var stepStart;

    // Step 1: Clean (selective in multi-scene mode — other scenes untouched)
    step++;
    stepStart = Date.now();
    setIngestProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Cleaning...');
    if (isMultiScene) await cleanScenesBeforeBuild(project, ingestFull, selectedScenes);
    else await cleanBeforeBuild(project, ingest);
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
        // readback verdict (wall-clock builder); the linear builder has no ok field
        ok: multiResult.ok,
        missingAfterBuild: multiResult.missingAfterBuild || 0,
        failedScenes: multiResult.failedScenes || [],
      };
    } else {
      result = await buildIngestSequence(project, ingest, bins[BIN_NAMES.SOURCE] || null, null, ingestLogger);
    }
    stepTimings.push('build ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // READBACK verdict (TICKET_uxp_audit, task 5). The builder compares the
    // timeline with the plan; a mismatch used to be only a log line — the build
    // «succeeded» and the project was saved and handed on. Transcripts, LUTs and
    // activation below still run for the scenes that did build; the build is
    // failed right after them, before «complete» / btn-done / «Build verified».
    // Strict === false: the linear builder returns no ok field at all.
    var readbackFailure = null;
    if (!ingestState.readbackBad) ingestState.readbackBad = {};
    (result.sequences || []).forEach(function (r) { if (r && r.sceneName) delete ingestState.readbackBad[r.sceneName]; });
    if (result.ok === false) {
      (result.sequences || []).forEach(function (r) {
        if (r && r.missingAfterBuild) ingestState.readbackBad[r.sceneName] = r.missingAfterBuild + ' item(s) off plan';
      });
      (result.failedScenes || []).forEach(function (f) { ingestState.readbackBad[f.sceneName] = 'build failed: ' + f.error; });
      var badList = Object.keys(ingestState.readbackBad);
      readbackFailure = 'READBACK: timeline does not match the plan — ' + result.missingAfterBuild + ' item(s) off'
        + (result.failedScenes.length ? ', ' + result.failedScenes.length + ' scene(s) failed' : '')
        + (badList.length ? ' (' + badList.join(', ') + ')' : '') + '. Rebuild these scenes; do not hand this project on.';
      ingestLogger.error(readbackFailure);
    }

    // Step 4: Import transcripts
    step++;
    stepStart = Date.now();
    setIngestProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Importing transcripts...');
    ingestLogger.info('=== Step 4: Importing transcripts ===');
    const trResult = await importTranscripts(project, ingest, bins[BIN_NAMES.TRANSCRIPTS] || null, ingestLogger, result.sequence || null, ingest.project_code);

    // Step 4b: Copy + import general SRTs into 01_Transcripts/{CODE}_1_Ingest/
    try {
      var txSrtPath = ingest.files && ingest.files.transcript_srt;
      var capSrtPath = ingest.files && ingest.files.captions_srt;
      var ingestProjectCode = ingest.project_code || '';

      if ((txSrtPath || capSrtPath) && ingestProjectCode && projectState.folderPath) {
        var ingestSourceDir = projectState.folderPath + '/01_Source';
        var ingestTxEntry = await uxpfs.getEntryWithUrl('file://' + ingestSourceDir + '/Transcription');
        var ingestTxFolder = await ensureSubfolder(ingestTxEntry, 'transcripts', ingestLogger);
        var ingestCapFolder = await ensureSubfolder(ingestTxEntry, 'captions', ingestLogger);

        // Copy with standard naming: {CODE}_1_Ingest_{type}.srt
        if (txSrtPath) {
          try {
            var ingestTxSrc = await uxpfs.getEntryWithUrl('file://' + txSrtPath);
            var ingestTxContent = await ingestTxSrc.read({ format: require('uxp').storage.formats.utf8 });
            var ingestTxTarget = await ingestTxFolder.createFile(ingestProjectCode + '_1_Ingest_transcript.srt', { overwrite: true });
            await ingestTxTarget.write(ingestTxContent);
            ingestLogger.info('Ingest transcript SRT → Transcription/transcripts/' + ingestProjectCode + '_1_Ingest_transcript.srt');
          } catch (txCopyErr) { ingestLogger.debug('Ingest transcript SRT copy: ' + txCopyErr.message); }
        }
        if (capSrtPath) {
          try {
            var ingestCapSrc = await uxpfs.getEntryWithUrl('file://' + capSrtPath);
            var ingestCapContent = await ingestCapSrc.read({ format: require('uxp').storage.formats.utf8 });
            var ingestCapTarget = await ingestCapFolder.createFile(ingestProjectCode + '_1_Ingest_captions.srt', { overwrite: true });
            await ingestCapTarget.write(ingestCapContent);
            ingestLogger.info('Ingest captions SRT → Transcription/captions/' + ingestProjectCode + '_1_Ingest_captions.srt');
          } catch (capCopyErr) { ingestLogger.debug('Ingest captions SRT copy: ' + capCopyErr.message); }
        }

        // Import into 01_Transcripts/{CODE}_1_Ingest/ bin
        var ingestSetupPath = projectState.folderPath + '/00_Setup';
        await importCaptionsSrt(project, ingestSetupPath, ingestProjectCode, '1_Ingest', 'Ingest Captions', ingestLogger);
        await importCaptionsSrt(project, ingestSetupPath, ingestProjectCode, '1_Ingest', 'Ingest Transcript', ingestLogger, 'transcript');
        ingestLogger.info('Ingest SRTs copied + imported → 01_Transcripts/' + ingestProjectCode + '_1_Ingest');
      }
    } catch (ingestSrtErr) {
      ingestLogger.warn('Ingest SRT import (non-fatal): ' + ingestSrtErr.message);
    }
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
      try { await project.openSequence(result.sequence.guid || result.sequence); } catch (e) { ingestLogger.debug('openSequence (non-fatal): ' + (e && e.message)); }
    }
    stepTimings.push('activate ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    if (readbackFailure) throw new Error(readbackFailure);

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
    buildSucceeded = true;

  } catch (err) {
    ingestLogger.error('INGEST BUILD FAILED: ' + err.message, err);
    setIngestStatus('Build failed: ' + err.message, 'error', err);
    try { await saveIngestLogs(await ppro.Project.getActiveProject()); } catch (e) { /* best-effort inside the error path */ }
  }

  // Scene badges — after success AND after failure, so a readback-failed scene
  // shows «readback ✗» instead of «built ✓». After a failure the user's own
  // ticks are restored (as the reload path above does) and readback-failed
  // scenes are ticked on top, so pressing Build again retries what was meant.
  if (ingestState.data && ingestState.data.clips && ingestState.data.clips.some(function (c) { return c.scene; })) {
    var ticksBefore = buildSucceeded ? null : getSelectedIngestScenes();
    var rowsBefore = buildSucceeded ? null : Array.prototype.map.call(
      document.querySelectorAll('.ingest-scene-cb'), function (cb) { return cb.value; });
    try {
      await renderIngestSceneList(ingestState.data);
      if (!buildSucceeded) {
        document.querySelectorAll('.ingest-scene-cb').forEach(function (cb) {
          if (rowsBefore.indexOf(cb.value) !== -1) cb.checked = ticksBefore.indexOf(cb.value) !== -1;
          if (ingestState.readbackBad && ingestState.readbackBad[cb.value]) cb.checked = true;
        });
      }
    } catch (e) { ingestLogger.debug('Scene list refresh: ' + (e && e.message)); }
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

/**
 * Verify Ingest — standalone check of all built sequences against ingest JSON.
 * Works for both single-sequence and multi-scene ingest.
 * Can be run any time after Build Ingest.
 */
async function verifyIngest() {
  if (!ingestState.data) { ingestLogger.error('No ingest loaded'); return; }

  const project = await ppro.Project.getActiveProject();
  if (!project) { ingestLogger.error('No active Premiere Pro project'); return; }

  const ingest = ingestState.data;
  const panel = $('ingest-validation');
  const lines = [];
  let allOk = true;
  let totalIssues = 0;

  function ok(text)   { lines.push('<div class="val-line"><span style="color:var(--success)">\u25CF</span> ' + escapeHtml(text) + '</div>'); }
  function info(text)  { lines.push('<div class="val-line"><span style="color:var(--text-secondary)">\u25CB</span> ' + escapeHtml(text) + '</div>'); }
  function warn(text)  { lines.push('<div class="val-line"><span style="color:var(--warning)">\u25CF</span> ' + escapeHtml(text) + '</div>'); allOk = false; totalIssues++; }
  function fail(text)  { lines.push('<div class="val-line"><span style="color:var(--error)">\u25CF</span> ' + escapeHtml(text) + '</div>'); allOk = false; totalIssues++; }
  function heading(text) { lines.push('<div style="margin-top:6px;font-weight:700;color:var(--accent);font-size:11px">' + escapeHtml(text) + '</div>'); }

  ingestLogger.info('=== VERIFY INGEST START ===');
  setIngestStatus('Verifying...', 'waiting');

  // Group clips by scene
  const hasScenes = ingest.clips.some(c => c.scene);
  const sceneMap = {};
  for (const clip of ingest.clips) {
    const scene = clip.scene || '_single';
    if (!sceneMap[scene]) sceneMap[scene] = [];
    sceneMap[scene].push(clip);
  }
  const sceneNames = Object.keys(sceneMap).sort();
  const projectCode = ingest.project_code || ingest.project_name;

  // Find all sequences in the project — getSequences() is the reliable enumerator
  // (Sequence.cast can return null for real sequences in some builds, and a root
  // item can carry a sequence's name without being one — imported stubs).
  // Cast of root items kept as a fallback.
  const projectSequences = {};
  try {
    const allSeqList = await project.getSequences();
    for (const s of (allSeqList || [])) {
      let sn = ''; try { sn = s.name || (s.getName && s.getName()) || ''; } catch (e) { /* nameless handles fall through to cast below */ }
      if (sn && !projectSequences[sn]) projectSequences[sn] = s;
    }
  } catch (e) { /* fall back to cast below */ }
  // Fallback cast over root + 00_Source_Timelines (scene timelines are filed there).
  const rootItems = await rootAndSourceTimelineItems(project);
  for (const item of rootItems) {
    if (projectSequences[item.name]) continue;
    try {
      const seq = ppro.Sequence.cast(item);
      if (seq) projectSequences[item.name] = seq;
    } catch (e) { /* not a sequence */ }
  }

  heading('Sequences');

  for (const sceneName of sceneNames) {
    const sceneClips = sceneMap[sceneName];
    // Sequences are named {code}_{scene} (see buildScene/detectExistingSequences);
    // legacy ingests may have bare scene names — accept both.
    const seqName = hasScenes ? (projectCode + '_' + sceneName) : projectCode + '_1_Ingest';
    const sequence = projectSequences[seqName] || (hasScenes ? projectSequences[sceneName] : null);

    if (!sequence) {
      // Incremental flow: a scene that was never built is not an error —
      // it's just not added yet (build it via the scene list above).
      if (hasScenes) info(seqName + ': not built yet');
      else fail(seqName + ': sequence not found');
      continue;
    }

    // Check V1 clip count
    let v1Count = 0;
    let v1Duration = 0;
    try {
      const v1 = await sequence.getVideoTrack(0);
      const items = await v1.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
      v1Count = items.length;
      // Calculate total duration from last clip end
      if (items.length > 0) {
        const lastItem = items[items.length - 1];
        const endTime = await lastItem.getEndTime();
        v1Duration = endTime.seconds;
      }
    } catch (e) { warn(seqName + ': cannot read V1 track'); }

    const expectedClips = sceneClips.length;
    const expectedDuration = sceneClips.reduce((s, c) => s + c.duration, 0);

    if (v1Count === expectedClips) {
      ok(seqName + ': ' + v1Count + ' clips');
    } else {
      warn(seqName + ': V1 has ' + v1Count + '/' + expectedClips + ' clips');
    }

    // Check duration (allow 2s tolerance per clip for rounding)
    const durTolerance = expectedClips * 0.5;
    if (Math.abs(v1Duration - expectedDuration) <= durTolerance) {
      ok(seqName + ': duration ' + Math.round(v1Duration) + 's');
    } else if (v1Duration > 0) {
      warn(seqName + ': duration ' + Math.round(v1Duration) + 's (expected ~' + Math.round(expectedDuration) + 's)');
    }

    // Check DJI audio tracks
    const expectedDji = sceneClips.reduce((s, c) => s + (c.dji_audio ? c.dji_audio.length : 0), 0);
    if (expectedDji > 0) {
      let djiCount = 0;
      try {
        // Check A2 and A3 for DJI audio
        const aTrackCount = await sequence.getAudioTrackCount();
        for (let t = 1; t < Math.min(aTrackCount, 4); t++) {
          const aTrack = await sequence.getAudioTrack(t);
          const aItems = await aTrack.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
          djiCount += aItems.length;
        }
      } catch (e) { /* ignore */ }

      if (djiCount >= expectedDji) {
        ok(seqName + ': DJI ' + djiCount + ' audio clips on A2/A3');
      } else if (djiCount > 0) {
        warn(seqName + ': DJI ' + djiCount + '/' + expectedDji + ' audio clips');
      } else {
        warn(seqName + ': no DJI audio found');
      }
    }

    ingestLogger.info('Verify ' + seqName + ': V1=' + v1Count + '/' + expectedClips + ', dur=' + Math.round(v1Duration) + 's, DJI=' + expectedDji);
  }

  // Summary
  heading('Summary');
  ok('Scenes: ' + sceneNames.length + ', Total clips: ' + ingest.clips.length);
  const totalDji = ingest.clips.reduce((s, c) => s + (c.dji_audio ? c.dji_audio.length : 0), 0);
  if (totalDji > 0) ok('Total DJI audio: ' + totalDji);

  if (allOk) {
    ok('All checks passed');
    setIngestStatus('Verification passed', 'ready');
  } else {
    warn(totalIssues + ' issue(s) found');
    setIngestStatus('Verification: ' + totalIssues + ' issue(s)', 'waiting');
  }

  panel.innerHTML = lines.join('');
  panel.style.display = 'block';
  ingestLogger.info('=== VERIFY INGEST COMPLETE: ' + (allOk ? 'PASSED' : totalIssues + ' issues') + ' ===');
}

/**
 * Sync Audio — shift all DJI audio clips on A2/A3 by user-specified offset.
 * Works on ALL sequences in the project that match ingest scene names.
 * Positive offset = audio moves right (later), negative = left (earlier).
 */
async function syncAudio() {
  var offsetStr = $('sync-offset-input').value;
  var offsetSec = parseFloat(offsetStr);
  if (isNaN(offsetSec) || offsetSec === 0) {
    ingestLogger.warn('Sync Audio: enter non-zero offset in seconds');
    setIngestStatus('Enter offset (e.g. -3.0)', 'waiting');
    return;
  }

  var project = await ppro.Project.getActiveProject();
  if (!project) { ingestLogger.error('No active project'); return; }

  ingestLogger.info('=== SYNC AUDIO: offset=' + offsetSec + 's ===');
  setIngestStatus('Syncing audio (' + offsetSec + 's)...', 'waiting');

  var panel = $('ingest-validation');
  var lines = [];
  var totalMoved = 0;
  var totalSkipped = 0;

  // Find all sequences in the project (getSequences-first: root-only cast scans
  // under-report in some builds and miss sequences organized into bins)
  var seqEntries = await listProjectSequences(project, ingestLogger);
  var sequences = seqEntries.map(function (e) { return { name: e.name, sequence: e.seq }; });

  if (sequences.length === 0) {
    ingestLogger.warn('No sequences found');
    setIngestStatus('No sequences found', 'error');
    return;
  }


  for (var si = 0; si < sequences.length; si++) {
    var seqInfo = sequences[si];
    var seq = seqInfo.sequence;
    var seqName = seqInfo.name;
    var seqMoved = 0;

    // Get audio track count
    var aTrackCount = await seq.getAudioTrackCount();

    // Process A2 (index 1) and A3 (index 2) — DJI tracks
    for (var trackIdx = 1; trackIdx < Math.min(aTrackCount, 4); trackIdx++) {
      var aTrack = await seq.getAudioTrack(trackIdx);
      var trackItems;
      try {
        trackItems = await aTrack.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
      } catch (e) {
        try { trackItems = await aTrack.getTrackItems(); } catch (e2) { continue; }
      }
      if (!trackItems || trackItems.length === 0) continue;

      for (var ci = 0; ci < trackItems.length; ci++) {
        var ti = trackItems[ci];
        try {
          var currentStart = await ti.getStartTime();
          var currentSec = currentStart.seconds;

          // Calculate new position
          var newSec = currentSec + offsetSec;
          if (newSec < 0) {
            ingestLogger.warn(seqName + ' A' + (trackIdx + 1) + ' clip ' + ci + ': would go negative, skipping');
            totalSkipped++;
            continue;
          }

          var newStart = ppro.TickTime.createWithSeconds(newSec);
          await ti.setStartTime(newStart);
          seqMoved++;
        } catch (moveErr) {
          ingestLogger.warn(seqName + ' A' + (trackIdx + 1) + ' clip ' + ci + ': move failed: ' + moveErr.message);
          totalSkipped++;
        }
      }
    }

    totalMoved += seqMoved;
    if (seqMoved > 0) {
      lines.push('<div class="val-line"><span style="color:var(--success)">\u25CF</span> ' +
        escapeHtml(seqName) + ': ' + seqMoved + ' clips shifted ' + offsetSec + 's</div>');
      ingestLogger.info(seqName + ': ' + seqMoved + ' DJI clips shifted by ' + offsetSec + 's');
    }
  }

  // Summary
  if (totalMoved > 0) {
    lines.push('<div style="margin-top:4px;font-weight:700;color:var(--accent)">' +
      totalMoved + ' clips shifted by ' + offsetSec + 's' +
      (totalSkipped > 0 ? ' (' + totalSkipped + ' skipped)' : '') + '</div>');
    setIngestStatus('Synced: ' + totalMoved + ' clips shifted ' + offsetSec + 's', 'ready');
  } else {
    lines.push('<div class="val-line"><span style="color:var(--warning)">\u25CF</span> No DJI audio clips found on A2/A3</div>');
    setIngestStatus('No clips to sync', 'waiting');
  }

  panel.innerHTML = lines.join('');
  panel.style.display = 'block';

  // Save project
  try { await project.save(); } catch (e) { ingestLogger.debug('save: ' + (e && e.message)); }
  ingestLogger.info('=== SYNC AUDIO COMPLETE: ' + totalMoved + ' moved, ' + totalSkipped + ' skipped ===');
}

async function saveIngestLogs(project) {
  try {
    if (project) { try { await project.save(); ingestLogger.info('Project saved'); } catch (e) { ingestLogger.debug('save: ' + (e && e.message)); } }

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

  // Check if Assembly/Deleted Scene sequences already exist
  var code = result.projectCode || extractProjectCode(result.projectName);
  var existingStages = [];
  try {
    var project = await ppro.Project.getActiveProject();
    if (project) {
      var stageNames = {
        '_2_Assembly': 'Assembly',
        '_3_DeletedScene': 'DeletedScene',
        '_4_PreEdit': 'PreEdit',
      };
      // REAL sequences only — a root item can carry a stage sequence's name
      // without being one (imported stubs flipped the UI into "Rebuild" state).
      var stageSeqEntries = await listProjectSequences(project, assemblyLogger);
      for (var i = 0; i < stageSeqEntries.length; i++) {
        for (var suffix in stageNames) {
          if (stageSeqEntries[i].name === code + suffix) {
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
    if (existingStages.indexOf('DeletedScene') >= 0) {
      setDeletedSceneStatus('Deleted Scene exists. Rebuild if needed.', 'ready');
      $('btn-build-deleted-scene').textContent = 'Rebuild Deleted Scene';
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
  $('btn-build-deleted-scene').removeAttribute('disabled');

  // Update deleted scene status when brief is loaded
  const deletedSceneSegs = result.segments.filter(s => !s.use || s.block === 99);
  setDeletedSceneStatus('Brief loaded. ' + deletedSceneSegs.length + ' unused segments.', 'ready');

  // Update Screen Cues status — enabled immediately (no Assembly dependency)
  if (assemblyState.screens.length > 0) {
    setScreensStatus(assemblyState.screens.length + ' screens detected. Ready to build.', 'ready');
    $('btn-generate-pngs').removeAttribute('disabled');
    $('btn-build-screens').removeAttribute('disabled');
    $('btn-export-screens').removeAttribute('disabled');
    $('btn-import-pre-edit').removeAttribute('disabled');
  } else {
    setScreensStatus('No screens in brief', 'waiting');
    $('btn-generate-pngs').setAttribute('disabled', 'true');
    $('btn-build-screens').setAttribute('disabled', 'true');
    $('btn-export-screens').setAttribute('disabled', 'true');
    $('btn-import-pre-edit').setAttribute('disabled', 'true');
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

    // Auto-copy to 00_Setup/02_Assembly/ with version
    if (projectState.folderPath) {
      try {
        var assemblyDir = projectState.folderPath + '/00_Setup/02_Assembly';
        var assemblyEntry;
        try {
          assemblyEntry = await uxpfs.getEntryWithUrl('file://' + assemblyDir);
        } catch (e) {
          var setupEntry = await uxpfs.getEntryWithUrl('file://' + projectState.folderPath + '/00_Setup');
          assemblyEntry = await ensureSubfolder(setupEntry, '02_Assembly', assemblyLogger);
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
        assemblyLogger.info('Brief saved: 00_Setup/02_Assembly/' + versionedName + ' (v' + version + ')');

        // Load from the saved location
        sourcePath = savedPath;
      } catch (copyErr) {
        assemblyLogger.debug('Brief copy to 02_Assembly/ skipped: ' + copyErr.message);
      }
    }

    loadBriefFromString(contents, sourcePath);
  } catch (err) {
    assemblyLogger.error('Failed to load brief: ' + err.message);
    setAssemblyStatus('Error: ' + err.message, 'error', err);
  }
}

// ══════════════════════════ PARTS (build-by-part stage) ══════════════════════════
// Build the film one part at a time. Each part = a colour/block as its own sequence
// with 2V+2A, placed by ABSOLUTE timeline_in (voice below + shown B-roll above,
// audio kept on both). Additive — does NOT touch the Assembly path.
let partsState = { part: null, segments: [], bundle: null, filePath: null, building: false };

function setPartsStatus(text, type, err) {
  var dot = $('parts-status-dot');
  var txt = $('parts-status-text');
  if (txt) txt.textContent = text;
  if (dot) dot.className = 'status-dot ' + (type || 'waiting');
  if (type === 'error') recordPanelError(text, 'parts', err);
}

function setPartsValidation(html) {
  var el = $('parts-validation');
  if (el) { el.innerHTML = html; el.style.display = 'block'; }
}

// === LUT-слои: блок кнопок внизу вкладки Ingest (не отдельная вкладка) ===

/**
 * Записать в кольцевой буфер кнопки «Copy error report».
 *
 * ⚠️ Буфер наполнялся ТОЛЬКО через logger.warn/error (src/shared/logger.js).
 * Ошибка, показанная в статус-строке мимо логгера, в отчёт не попадала:
 * 25.09.2026 «Color failed: vclip.getComponentChain is not a function» висел
 * на экране, а отчёт про него молчал. Обещание кнопки — «здесь то, что
 * сломалось», поэтому любой статус уровня error теперь регистрируется.
 */
function recordPanelError(text, pipeline, err) {
  Logger.pushPanelError('ERROR', text, pipeline, err, 'status');
}

function setAdjustStatus(text, type, err) {
  var dot = $('adjust-status-dot');
  var txt = $('adjust-status-text');
  if (txt) txt.textContent = text;
  if (dot) dot.className = 'status-dot ' + (type || 'waiting');
  if (type === 'error') recordPanelError(text, 'adjust', err);
}

var ADJUST_REASON_TEXT = {
  'no-sequence': 'No active sequence — open one in the timeline',
  'no-selection': 'Nothing selected — select clip(s) on the timeline first',
  'no-donor': 'No donor item — create once: New Item > Adjustment Layer, rename to YTAI_ADJ',
  'place-failed': 'Placement failed — see log',
};

// eslint-disable-next-line no-unused-vars -- gen-1 donor UI, кнопки сняты 25.09; ждёт кнопку поколения 2
async function runAdjustOverSelection(opts) {
  var adjustLogger = new Logger('adjust');
  setAdjustStatus('Adding adjustment layer...', 'working');
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) { setAdjustStatus('No open Premiere project', 'error'); return; }
    opts = opts || {};
    // Auto-donor: when the project lacks a YTAI_ADJ item, import the donor
    // .prproj shipped into the project folder (00_Setup/YTAI_ADJ_donor.prproj).
    // Projects created from the master template have the item already — the
    // donor file is only touched when the by-name lookup fails.
    if (!opts.donorPrproj) {
      var folder = projectState.folderPath;
      if (!folder) {
        var ppath = null;
        try { ppath = project.path; } catch (e) { /* getter may throw */ }
        if (!ppath) { try { ppath = await project.getPath(); } catch (e) { /* none */ } }
        if (ppath) folder = String(ppath).replace(/\\/g, '/').replace(/\/[^/]*$/, '');
      }
      if (folder) opts.donorPrproj = folder + '/00_Setup/YTAI_ADJ_donor.prproj';
    }
    var r = await addAdjustmentOverSelection(project, opts, adjustLogger);
    if (!r.ok) {
      setAdjustStatus(ADJUST_REASON_TEXT[r.reason] || ('Failed: ' + r.reason), 'error');
      return;
    }
    var msg = 'Added continuous adjustment layer: ' + r.count + ' clip(s), '
      + r.startSec.toFixed(2) + 's–' + r.endSec.toFixed(2) + 's → V' + (r.vIdx + 1);
    if (r.transform) {
      msg += r.transform.applied
        ? (r.transform.paramSet ? ' + Transform 101' : ' + Transform (set Scale by hand)')
        : ' (Transform failed — see log)';
    }
    setAdjustStatus(msg, 'ready');
  } catch (err) {
    adjustLogger.error('runAdjustOverSelection: ' + err.message);
    setAdjustStatus('Error: ' + err.message, 'error', err);
  }
}

/** Persist the adjust log into the project so failures are inspectable offline. */
async function saveAdjustLog(folder, adjustLogger) {
  var text = adjustLogger._buffer.join('\n');
  var targets = ['/99_Pipeline/logs', '/00_Setup/logs'];
  for (var i = 0; i < targets.length; i++) {
    try {
      var dir = await uxpfs.getEntryWithUrl('file://' + folder + targets[i]);
      var f = await dir.createFile('adjust_last.log', { overwrite: true });
      await f.write(text, { format: uxp.storage.formats.utf8 });
      return;
    } catch (e) { /* try next target */ }
  }
}

/**
 * Layer manifest — persistent record of clone placements (the Creative Look
 * cannot be read back via the param API, so this file IS the health record).
 * {seqName: {clipName: {lut, startSec, endSec}}}
 */
var ADJUST_MANIFEST_REL = '/99_Pipeline/lut_layers_manifest.json';

async function loadLayerManifest(folder) {
  try {
    var entry = await uxpfs.getEntryWithUrl('file://' + folder + ADJUST_MANIFEST_REL);
    return JSON.parse(await entry.read()) || {};
  } catch (e) { return {}; }
}

async function saveLayerManifest(folder, manifest) {
  try {
    var dir = await uxpfs.getEntryWithUrl('file://' + folder + '/99_Pipeline');
    var f = await dir.createFile('lut_layers_manifest.json', { overwrite: true });
    await f.write(JSON.stringify(manifest, null, 2), { format: uxp.storage.formats.utf8 });
  } catch (e) { /* best effort — next run just re-places clones */ }
}

/** Resolve the project folder like the Adjust donor path does. */
async function adjustProjectFolder(project) {
  var folder = projectState.folderPath;
  if (!folder) {
    var ppath = null;
    try { ppath = project.path; } catch (e) { /* getter may throw */ }
    if (!ppath) { try { ppath = await project.getPath(); } catch (e) { /* none */ } }
    if (ppath) folder = String(ppath).replace(/\\/g, '/').replace(/\/[^/]*$/, '');
  }
  return folder || null;
}

/**
 * PIPELINE MODE — adjustment layer over EVERY clip, LUT by {CODE}_lut_plan.json
 * (00_Setup/01_Ingest/). allSequences=true → walks every sequence in the project.
 */
/**
 * Положить цвет из {CODE}_color_plan.json прямо на клипы: Input LUT + Exposure
 * + Look в ОДИН Lumetri на клипе. Порядок внутри Lumetri фиксирован
 * (Basic Correction → Creative), поэтому получается ровно та цепочка, что
 * считала витрина: проявка → экспозиция → покраска.
 *
 * ⚠️ Это НЕ старый lut_plan.json. Там значением было имя клипа-донора строкой,
 * и панель клала его прямо в имя слоя; здесь значение — объект
 * {develop, exposure, look}. Перепутать форматы = «[object Object]» на таймлайне.
 */
async function runColorFromPlan(allSequences) {
  var log = new Logger('color');
  setAdjustStatus('Color: reading plan…', 'working');
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) { setAdjustStatus('No open project', 'error'); return; }
    var folder = await adjustProjectFolder(project);
    if (!folder) { setAdjustStatus('Save the project (⌘S) first', 'error'); return; }

    var code = extractProjectCode(folder.split('/').pop() || '');
    var planPath = folder + '/01_Source/00_LUT/_build/' + code + '_color_plan.json';
    var doc;
    try {
      var entry = await uxpfs.getEntryWithUrl('file://' + planPath);
      doc = JSON.parse(await entry.read());
    } catch (e) {
      setAdjustStatus('No color_plan — run color_apply.py: ' + planPath, 'error');
      return;
    }
    if (doc.schema !== 'color-plan-v1') {
      setAdjustStatus('Wrong schema: ' + doc.schema + ' (need color-plan-v1)', 'error');
      return;
    }

    // ключ плана — «сцена/клип.MP4», таймлайн матчится по basename
    var byClip = {};
    var plan = doc.plan || {};
    Object.keys(plan).forEach(function (k) { byClip[k.split('/').pop()] = plan[k]; });

    var inputDir = (doc.install && doc.install.input_dir) || '';
    var creativeDir = (doc.install && doc.install.creative_dir) || '';
    // формы значения перебираются по убыванию конкретности — какую примет
    // Lumetri, до сих пор никем не проверено
    function developForms(id) {
      var d = (doc.develops || {})[id];
      if (!d) return null;
      var n = d.install_name;
      return [inputDir + '/' + n, n, n.replace(/\.cube$/i, '')];
    }
    var lookForms = null;
    if (doc.look && doc.look.install_name) {
      var ln = doc.look.install_name;
      lookForms = [ln.replace(/\.cube$/i, ''), ln, creativeDir + '/' + ln];
    }

    var seqs = allSequences ? await project.getSequences()
      : (await project.getActiveSequence() ? [await project.getActiveSequence()] : []);
    if (!seqs || !seqs.length) { setAdjustStatus('No sequences', 'error'); return; }

    var done = 0, miss = 0, fail = 0, expOk = 0, donorNeeded = 0, firstDump = null;
    var failures = [];
    for (var si = 0; si < seqs.length; si++) {
      var seq = seqs[si];
      var seqName = '';
      try { seqName = String(await seq.getName()); } catch (e) { seqName = String(seq.name || ''); }
      if (seqName === LUT_DONOR_SEQUENCE) continue;
      setAdjustStatus('Color: ' + (si + 1) + '/' + seqs.length + ' ' + seqName, 'working');
      var items = await collectVideoClipEntries(seq, log);
      for (var ci = 0; ci < items.length; ci++) {
        var it = items[ci];
        var nm = String((it && it.name) || '');
        var spec = byClip[nm];
        if (!spec) { miss++; continue; }
        var res = await colorApply.applyColorToClip(project, it, {
          developPath: developForms(spec.develop),
          exposure: (typeof spec.exposure === 'number') ? spec.exposure : undefined,
          lookName: lookForms,
        }, log);
        if (!firstDump && res.dump && res.dump.length) {
          firstDump = res.dump;
          log.info('ДАМП ПАРАМЕТРОВ LUMETRI (' + nm + '):\n' + colorApply.formatDump(res.dump));
        }
        // ⚠️ Три слота — три разные судьбы, и мешать их в одно «failed» нельзя.
        // Замерено 25.09.2026 дампом: Input LUT (индексы 6, 7) и Look (34, 35)
        // — ЧИСЛОВЫЕ меню, сам куб лежит в бинарном параметре Blob. Строкой
        // туда не положить никогда и ничем: это не сбой прогона, а предел API,
        // и лечится он только донор-клоном. Exposure (19) числом ставится.
        var bad = [], needDonor = false;
        if (res.error) bad.push(res.error);
        ['develop', 'look'].forEach(function (k) {
          if (res[k] && res[k].ok === false) {
            if ((res[k].tried || []).some(function (t) { return t.res && t.res.numericSlot; })) needDonor = true;
            else bad.push(k + ': ' + res[k].why);
          }
        });
        if (res.exposure && res.exposure.ok === false) bad.push('exposure: ' + res.exposure.why);
        if (res.exposure && res.exposure.ok) expOk++;
        if (needDonor) donorNeeded++;
        if (bad.length) { fail++; failures.push(nm + ' — ' + bad.join('; ')); }
        else done++;
      }
    }
    await saveAdjustLog(folder, log);

    if (!done && !fail) {
      setAdjustStatus('No timeline clip matches the plan (' + miss + ' skipped)', 'error');
      return;
    }
    var msg = 'Color: exposure on ' + expOk + '/' + (expOk + fail) + ' clips'
      + (donorNeeded ? ' · LUT+Look need donor (' + donorNeeded + ')' : '')
      + (fail ? ' · failed ' + fail : '')
      + ' · not in plan ' + miss;
    if (donorNeeded && !fail) {
      log.warn('color: Input LUT и Look — числовые меню Lumetri, куб живёт в Blob;'
        + ' значением они не ставятся ни в какой форме. Нужен донор-клон.');
    }
    if (fail) {
      log.warn('НЕ ЛЁГЛО:\n' + failures.slice(0, 20).join('\n'));
      setAdjustStatus(msg + ' — see adjust_last.log', 'error');
    } else {
      setAdjustStatus(msg, 'ok');
    }
  } catch (e) {
    // статус короткий, лог подробный: без стека такую ошибку не найти
    // Defect A of the ticket lived exactly here: the stack must reach «Err».
    try { log.error('color: упало — ' + (e && e.message ? e.message : e), e); } catch (e2) { /* logging must not mask the status line below */ }
    try { await saveAdjustLog(folder, log); } catch (e2) { /* best-effort inside the error path */ }
    setAdjustStatus('Color failed: ' + (e && e.message ? e.message : e), 'error', e);
  }
}

// eslint-disable-next-line no-unused-vars -- gen-1 donor UI, кнопки сняты 25.09; ждёт кнопку поколения 2
async function runAdjustPerClipFromPlan(allSequences) {
  var adjustLogger = new Logger('adjust');
  setAdjustStatus('AL per clip: reading lut_plan...', 'working');
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) { setAdjustStatus('No open Premiere project', 'error'); return; }
    var folder = await adjustProjectFolder(project);
    if (!folder) { setAdjustStatus('Project not saved (⌘S) — cannot find lut_plan', 'error'); return; }

    var code = extractProjectCode(folder.split('/').pop() || '');
    var planPath = folder + '/00_Setup/01_Ingest/' + code + '_lut_plan.json';
    var planRaw;
    try {
      var entry = await uxpfs.getEntryWithUrl('file://' + planPath);
      planRaw = JSON.parse(await entry.read());
    } catch (e) {
      setAdjustStatus('No lut_plan: ' + planPath + ' — run lut_face_score.py first', 'error');
      return;
    }
    // plan keys are "scene/clip.MP4" — the timeline matches by basename
    var planByClip = {};
    var plan = planRaw.plan || {};
    Object.keys(plan).forEach(function (k) {
      planByClip[k.split('/').pop()] = plan[k];
    });

    var sequences;
    if (allSequences) {
      sequences = await project.getSequences();
    } else {
      var act = await project.getActiveSequence();
      sequences = act ? [act] : [];
    }
    if (!sequences || !sequences.length) { setAdjustStatus('No sequence(s) to process', 'error'); return; }

    var opts = { donorPrproj: [
      folder + '/00_Setup/YTAI_ADJ_donor.prproj',
      '/Users/romansergeev/YTAI/scripts/01_prepare/0101_init_folders/RYA_example.prproj',
    ] };
    var placed = 0, total = 0, already = 0, lookSet = 0, lumetri = 0, seqDone = 0, noDonor = false;
    var mode = null;
    var manifestAll = await loadLayerManifest(folder);
    for (var si = 0; si < sequences.length; si++) {
      var seq = sequences[si];
      var seqName = '';
      try { seqName = String(await seq.getName()); } catch (e) { try { seqName = String(seq.name || ''); } catch (e2) { /* fallback chain; empty name is skipped safely */ } }
      // The LUT-donor template sequence is tooling, not content — never layer it.
      if (seqName === LUT_DONOR_SEQUENCE) continue;
      setAdjustStatus('AL per clip: ' + (si + 1) + '/' + sequences.length + ' ' + seqName, 'working');
      opts.layerManifest = manifestAll[seqName] || {};
      var r = await addAdjustmentPerClipFromPlan(project, seq, planByClip, opts, adjustLogger);
      if (r.mode) mode = r.mode;
      if (r.mode === 'clone' && r.layerManifest) manifestAll[seqName] = r.layerManifest;
      adjustLogger.info('Seq ' + seqName + ': placed ' + r.placed + '/' + r.total
        + ', already ' + (r.already || 0)
        + (r.reason ? ' (' + r.reason + ')' : '') + ', lumetri ' + r.lumetriApplied + ', look ' + r.lookSet);
      if (r.reason === 'no-donor') { noDonor = true; break; }
      if (r.total > 0) seqDone++;
      placed += r.placed; total += r.total; already += (r.already || 0);
      lookSet += r.lookSet; lumetri += r.lumetriApplied;
    }
    await saveAdjustLog(folder, adjustLogger);
    if (mode === 'clone') await saveLayerManifest(folder, manifestAll);
    if (noDonor) {
      setAdjustStatus(ADJUST_REASON_TEXT['no-donor'], 'error');
      return;
    }
    if (total === 0) {
      setAdjustStatus('No timeline clip matches the plan — check lut_plan', 'error');
      return;
    }
    var msg = 'LUT layers'
      + (mode === 'clone' ? ' (donor clones)' : (mode === 'legacy' ? ' (legacy — no donor seq!)' : ''))
      + ': +' + placed + ' new, ' + already + ' existing, '
      + total + ' clip(s) in ' + seqDone + ' sequence(s)'
      + ' · Lumetri ' + lumetri
      + ' · Look ' + lookSet
      + (mode === 'legacy' && placed > 0 ? ' — pick Look by layer name (or Build LUT Donor in template)' : '');
    setAdjustStatus(msg, (placed + already) === total ? 'ready' : 'error');
  } catch (err) {
    adjustLogger.error('runAdjustPerClipFromPlan: ' + err.message + (err.stack ? '\n' + err.stack : ''));
    try {
      var f2 = await adjustProjectFolder(await ppro.Project.getActiveProject());
      if (f2) await saveAdjustLog(f2, adjustLogger);
    } catch (e2) { /* best effort */ }
    setAdjustStatus('Error: ' + err.message, 'error', err);
  }
}

/**
 * PLAN-B DONOR BUILDER — programmatically build/repair the YTAI_LUT_DONOR
 * sequence in the CURRENTLY OPEN project (run it with the master template
 * open): sequence + 3 named AL clips + Lumetri, Look set automatically when
 * the API allows. Whatever the API could not set is listed for hand-picking.
 */
// eslint-disable-next-line no-unused-vars -- gen-1 donor UI, кнопки сняты 25.09; ждёт кнопку поколения 2
async function runAdjustBuildDonor() {
  var adjustLogger = new Logger('adjust');
  setAdjustStatus('Building ' + LUT_DONOR_SEQUENCE + '...', 'working');
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) { setAdjustStatus('No open Premiere project', 'error'); return; }
    var folder = await adjustProjectFolder(project);
    var opts = {};
    if (folder) {
      opts.donorPrproj = [
        folder + '/00_Setup/YTAI_ADJ_donor.prproj',
        '/Users/romansergeev/YTAI/scripts/01_prepare/0101_init_folders/RYA_example.prproj',
      ];
    }
    var r = await buildLutDonorSequence(project, opts, adjustLogger);
    if (folder) await saveAdjustLog(folder, adjustLogger);
    if (!r.ok) {
      if (r.reason === 'no-donor') {
        setAdjustStatus(ADJUST_REASON_TEXT['no-donor'], 'error');
      } else {
        setAdjustStatus('Donor build failed: ' + r.reason
          + (folder ? ' — see adjust_last.log' : ' — save the project (⌘S) to get a log file'), 'error');
      }
      return;
    }
    var msg = LUT_DONOR_SEQUENCE + ': ' + (r.created ? 'created' : (r.rebuilt ? 'REBUILT (v2 layout)' : 'existed'))
      + ', +' + r.placed + ' clip(s), Lumetri ' + r.lumetri;
    if (r.needLook && r.needLook.length) {
      msg += ' — pick Look by hand: ' + r.needLook.join(', ') + ', then ⌘S';
      setAdjustStatus(msg, 'error');
    } else {
      msg += ' — done, ⌘S to save';
      setAdjustStatus(msg, 'ready');
    }
  } catch (err) {
    adjustLogger.error('runAdjustBuildDonor: ' + err.message + (err.stack ? '\n' + err.stack : ''));
    try {
      var f2 = await adjustProjectFolder(await ppro.Project.getActiveProject());
      if (f2) await saveAdjustLog(f2, adjustLogger);
    } catch (e2) { /* best effort */ }
    setAdjustStatus('Error: ' + err.message, 'error', err);
  }
}

/**
 * PLAN-B PROBE — clone one AL from the YTAI_LUT_DONOR template sequence into
 * the active sequence (fresh track above content). Answers «does
 * createCloneTrackItemAction work across sequences?» — see HANDOFF_adjust_lut.
 */
// eslint-disable-next-line no-unused-vars -- gen-1 donor UI, кнопки сняты 25.09; ждёт кнопку поколения 2
async function runAdjustProbeClone() {
  var adjustLogger = new Logger('adjust');
  setAdjustStatus('Probe: cloning donor AL...', 'working');
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) { setAdjustStatus('No open Premiere project', 'error'); return; }
    var folder = await adjustProjectFolder(project);
    var opts = {};
    if (folder) {
      opts.donorPrproj = [
        folder + '/00_Setup/YTAI_ADJ_donor.prproj',
        '/Users/romansergeev/YTAI/scripts/01_prepare/0101_init_folders/RYA_example.prproj',
      ];
    }
    var r = await probeDonorClone(project, opts, adjustLogger);
    if (folder) await saveAdjustLog(folder, adjustLogger);
    if (r.ok) {
      setAdjustStatus('Clone OK → V' + (r.landedTrack + 1) + ' @ ' + r.landedSec.toFixed(2)
        + 's, Lumetri: ' + r.lumetriKept + ' — check Look, ⌘Z to remove', 'ready');
    } else if (r.reason === 'no-donor-sequence') {
      setAdjustStatus('No "YTAI_LUT_DONOR" sequence — add it to the template first (see log)', 'error');
    } else if (r.reason === 'clobbered-content') {
      setAdjustStatus('⚠️ Clone hit existing clips — press ⌘Z NOW (see adjust_last.log)', 'error');
    } else {
      setAdjustStatus('Probe failed: ' + r.reason
        + (folder ? ' — see adjust_last.log' : ' — save the project (⌘S) to get a log file'), 'error');
    }
  } catch (err) {
    adjustLogger.error('runAdjustProbeClone: ' + err.message + (err.stack ? '\n' + err.stack : ''));
    try {
      var f2 = await adjustProjectFolder(await ppro.Project.getActiveProject());
      if (f2) await saveAdjustLog(f2, adjustLogger);
    } catch (e2) { /* best effort */ }
    setAdjustStatus('Error: ' + err.message, 'error', err);
  }
}

async function loadPart(auto) {
  try {
    // Auto-find the newest part JSON in {project}/00_Setup/02_Assembly/parts — no picker needed
    // (parity with Review v3 auto-detect). Falls back to the file picker if the dir is empty/absent.
    // auto=true (tab open): NEVER pop the picker — quiet status instead.
    var file = null;
    if (projectState.folderPath) {
      try {
        var pDir = await uxpfs.getEntryWithUrl('file://' + projectState.folderPath + '/00_Setup/02_Assembly/parts');
        var pEntries = await pDir.getEntries();
        var pCands = [];
        for (var pe = 0; pe < pEntries.length; pe++) {
          if (pEntries[pe].isFile && /_part_.*\.json$/i.test(pEntries[pe].name)) pCands.push(pEntries[pe]);
        }
        if (pCands.length) {
          // newest by dateModified when available, else by name (higher version sorts later)
          var pBest = pCands[0], pBestT = 0;
          for (var pb = 0; pb < pCands.length; pb++) {
            var pT = 0;
            try { var pMeta = await pCands[pb].getMetadata(); pT = pMeta && pMeta.dateModified ? new Date(pMeta.dateModified).getTime() : 0; } catch (eMt) { /* dateModified optional; name order breaks the tie */ }
            if (pT > pBestT || (pT === pBestT && pCands[pb].name.localeCompare(pBest.name) > 0)) { pBest = pCands[pb]; pBestT = pT; }
          }
          file = pBest;
          assemblyLogger.info('Part auto-detected: ' + file.name + ' (of ' + pCands.length + ' in 02_Assembly/parts/)');
        }
      } catch (eAd) { assemblyLogger.debug('parts auto-detect: ' + eAd.message); }
    }
    if (!file && auto) {
      setPartsStatus('No part JSON in 02_Assembly/parts/ — ask Claude to build one', 'waiting');
      return;
    }
    if (!file) {
      assemblyLogger.info('No part JSON auto-detected — opening file picker...');
      file = await uxpfs.getFileForOpening({ types: ['json'], allowMultiple: false });
    }
    if (!file) { assemblyLogger.warn('Part selection cancelled'); return; }
    const contents = await file.read();
    var data = JSON.parse(contents);
    // Bundle: one JSON → many sequences ({schema:'ytai-parts-bundle-v1', parts:[{part,segments},...]})
    if (data.schema === 'ytai-parts-bundle-v1' && Array.isArray(data.parts) && data.parts.length) {
      partsState.bundle = data.parts;
      partsState.part = data.parts[0].part;
      partsState.segments = data.parts[0].segments;
      partsState.filePath = file.nativePath || file.name || 'unknown';
      var names = data.parts.map(function (x) { return (x.part && x.part.sequence_name) || '?'; });
      setPartsStatus('Bundle loaded: ' + data.parts.length + ' timelines', 'ready');
      setPartsValidation('<div class="val-line"><b>BUNDLE</b> — ' + data.parts.length + ' sequences:</div>' +
        names.map(function (n) { return '<div class="val-line">· ' + escapeHtml(n) + '</div>'; }).join(''));
      $('btn-build-part').removeAttribute('disabled');
      assemblyLogger.info('Parts bundle loaded: ' + names.join(', '));
      return;
    }
    partsState.bundle = null;
    if (data.schema !== 'ytai-part-v1' || !data.part || !Array.isArray(data.segments)) {
      throw new Error('Not a ytai-part-v1 file (need schema=ytai-part-v1, part{}, segments[])');
    }
    partsState.part = data.part;
    partsState.segments = data.segments;
    partsState.filePath = file.nativePath || file.name || 'unknown';
    var seqName = data.part.sequence_name || ((data.part.code || 'PART') + '_part_' + (data.part.name || 'Untitled'));
    var v2 = data.segments.filter(function (s) { return /2/.test(String(s.track || '')); }).length;
    // Which timeline will be built + which version comes next (Roman: видеть до сборки).
    var willVersion = (data.part.auto_version != null) ? !!data.part.auto_version : !!data.part.base_clip;
    var nextName = seqName;
    if (willVersion) {
      try {
        // same "taken" set as partsBuilder auto-version: ALL sequences (any bin) ∪ root names
        var taken = await collectTakenNames(await ppro.Project.getActiveProject(), assemblyLogger);
        var bn = seqName.replace(/_v\d+$/, ''), vn = 1;
        while (taken[bn + '_v' + vn]) vn++;
        nextName = bn + '_v' + vn;
      } catch (eNv) { nextName = seqName + '_v1'; }
    }
    var lastEnd = 0;
    for (var le = 0; le < data.segments.length; le++) {
      var so2 = data.segments[le].timeline_out_sec;
      if (so2 == null && data.segments[le].timeline_out) so2 = tcToSecPanel(data.segments[le].timeline_out);
      if (so2 != null && so2 > lastEnd) lastEnd = so2;
    }
    var bsegs2 = (data.part.base_segments || []);
    for (var be = 0; be < bsegs2.length; be++) if (bsegs2[be].timeline_out_sec > lastEnd) lastEnd = bsegs2[be].timeline_out_sec;
    var durTxt = Math.floor(lastEnd / 60) + ':' + (Math.round(lastEnd % 60) < 10 ? '0' : '') + Math.round(lastEnd % 60);
    var chapN = (data.part.chapter_markers || []).length;
    setPartsStatus('Ready → ' + nextName + ' · ' + data.segments.length + ' segments · ' + durTxt, 'ready');
    setPartsValidation(
      '<div class="val-line">Will build: <b>' + escapeHtml(nextName) + '</b>' +
        (willVersion ? ' <span style="opacity:.6">(new version each build)</span>' : '') + '</div>' +
      '<div class="val-line">Source JSON: ' + escapeHtml(String(file.name || '')) + '</div>' +
      '<div class="val-line">Segments: ' + data.segments.length + ' — ' + (data.segments.length - v2) + ' on V1, ' + v2 + ' on V2+' +
        (bsegs2.length ? ' · V1 base: ' + bsegs2.length + ' piece(s)' : '') + '</div>' +
      '<div class="val-line">Length: ' + durTxt + (chapN ? ' · chapters: ' + chapN : '') + '</div>' +
      '<div class="val-line">Model: ' + escapeHtml(data.part.build_model || 'absolute') + ' · keep_audio per segment</div>');
    $('btn-build-part').removeAttribute('disabled');
    assemblyLogger.info('Part loaded: ' + (data.part.name || '?') + ', ' + data.segments.length + ' segments → ' + seqName);
  } catch (err) {
    setPartsStatus('Error: ' + err.message, 'error', err);
    assemblyLogger.error('Load part failed: ' + err.message);
  }
}

// Optional explicitBundle ([{part, segments}, ...]) builds that list instead of
// partsState (Assembly scenes path); return value is additive — old callers ignore it.
async function buildParts(explicitBundle, ui) {
  // ui: optional { status, validation } — Assembly-tab builds route progress to their
  // own tab; default = the Parts-tab writers (invisible when another tab drives).
  var status = (ui && ui.status) || setPartsStatus;
  var validation = (ui && ui.validation) || setPartsValidation;
  var bundleList = explicitBundle && explicitBundle.length ? explicitBundle
    : (partsState.bundle && partsState.bundle.length ? partsState.bundle
      : [{ part: partsState.part, segments: partsState.segments }]);
  var firstPart = (bundleList[0] && bundleList[0].part) || null;
  // review parts (base_clip) may carry ZERO inserts — a watch-only timeline of the
  // render + chapter markers is valid; partsBuilder itself allows it in reviewMode.
  if (!firstPart || (!(bundleList[0].segments || []).length && !firstPart.base_clip)) { status('No part loaded', 'error'); return { ok: false, builtNames: [], error: 'No part loaded' }; }
  if (partsState.building) { assemblyLogger.warn('Part build already in progress'); return { ok: false, builtNames: [], error: 'Build already in progress' }; }
  partsState.building = true;
  $('btn-build-part').setAttribute('disabled', 'true');
  status('Building part "' + (firstPart.name || '?') + '"...', 'waiting');
  var builtNames = [];
  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');
    assemblyLogger.info('=== PART BUILD START: ' + (firstPart.name || '?') + ' (partsBuilder v' + PARTS_BUILDER_VERSION + ') ===');
    try { await project.save(); } catch (e) { assemblyLogger.debug('pre-build save: ' + (e && e.message)); }
    // clipMap WITHOUT throwing on missing — partsBuilder skips clips not in project.
    var sourceBin = await findSourceBin(project);
    if (!sourceBin) {
      // Editor's own project (e.g. Aymen's) has no 00_Source bin — create it instead of
      // failing; the auto-import below lands every missing clip into _Part_media anyway.
      assemblyLogger.warn('00_Source bin not found — creating an empty one (clips auto-import to _Part_media)');
      try {
        var sbRoot = await project.getRootItem();
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) { ca.addAction(sbRoot.createBinAction('00_Source', true)); }, 'Create 00_Source bin');
        });
        sourceBin = await findProjectItemByName(project, '00_Source', assemblyLogger);
      } catch (eSB) { assemblyLogger.warn('00_Source create failed: ' + eSB.message); }
    }
    var clipMap = sourceBin ? await buildClipMap(sourceBin, assemblyLogger) : {};
    // Auto-import media missing from the project by segment.source_path (parity with Review v3):
    // photos/renders referenced by the part JSON need no manual File>Import — they land in _Part_media.
    var pMissing = [], pSeen = {};
    var pAllSegs = bundleList.reduce(function (acc, x) { return acc.concat(x.segments || []); }, []);
    for (var pi = 0; pi < pAllSegs.length; pi++) {
      var pSf = pAllSegs[pi].source_file, pSp = pAllSegs[pi].source_path;
      if (!pSf || !pSp) continue;
      if (clipMap[pSf] || clipMap[pSf.replace(/\.[^.]+$/, '')]) continue;
      var pFound = await findProjectItemByName(project, pSf, assemblyLogger);
      if (pFound) { clipMap[pSf] = pFound; clipMap[pSf.replace(/\.[^.]+$/, '')] = pFound; continue; }
      if (pSeen[pSp]) continue; pSeen[pSp] = 1;
      pMissing.push({ sf: pSf, sp: pSp });
    }
    if (pMissing.length) {
      assemblyLogger.info('Parts auto-import: ' + pMissing.length + ' missing clip(s) → _Part_media...');
      status('Importing ' + pMissing.length + ' missing clip(s)...', 'waiting');
      var pBinCast = null;
      try {
        var pBin = await findProjectItemByName(project, '_Part_media', assemblyLogger);
        if (!pBin) {
          var pRoot = await project.getRootItem();
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) { ca.addAction(pRoot.createBinAction('_Part_media', true)); }, 'Create _Part_media bin');
          });
          pBin = await findProjectItemByName(project, '_Part_media', assemblyLogger);
        }
        pBinCast = pBin ? ppro.FolderItem.cast(pBin) : null;
      } catch (ePB) { assemblyLogger.warn('_Part_media bin skipped: ' + ePB.message); }
      var pPaths = pMissing.map(function (x) { return x.sp; });
      try {
        if (pBinCast) await project.importFiles(pPaths, true, pBinCast, false); else await project.importFiles(pPaths);
      } catch (ePImp) {
        assemblyLogger.warn('batch import failed (' + ePImp.message + ') — one-by-one');
        for (var pj = 0; pj < pPaths.length; pj++) {
          try { if (pBinCast) await project.importFiles([pPaths[pj]], true, pBinCast, false); else await project.importFiles([pPaths[pj]]); } catch (e2) { assemblyLogger.debug('import ' + pPaths[pj] + ': ' + (e2 && e2.message)); }
        }
      }
      var pGot = 0;
      for (var pk = 0; pk < pMissing.length; pk++) {
        var pIt = await findProjectItemByName(project, pMissing[pk].sf, assemblyLogger);
        if (pIt) { clipMap[pMissing[pk].sf] = pIt; clipMap[pMissing[pk].sf.replace(/\.[^.]+$/, '')] = pIt; pGot++; }
      }
      assemblyLogger.info('Parts auto-import: ' + pGot + '/' + pMissing.length + ' resolved.');
    }
    var result = null;
    for (var bx = 0; bx < bundleList.length; bx++) {
      if (!(bundleList[bx].segments || []).length && !(bundleList[bx].part && bundleList[bx].part.base_clip)) {
        // e.g. a __DeletedScene part of a scene with zero cuts — nothing to build.
        // Review parts (base_clip) build fine with ZERO inserts: base + chapter markers.
        assemblyLogger.info('Skip empty part: ' + ((bundleList[bx].part && bundleList[bx].part.sequence_name) || '?'));
        continue;
      }
      if (bundleList.length > 1) status('Building ' + (bx + 1) + '/' + bundleList.length + ': ' + (bundleList[bx].part.sequence_name || '?'), 'waiting');
      result = await buildPartSequence(project, clipMap, bundleList[bx].part, bundleList[bx].segments, assemblyLogger, assemblyState.projectSettings);
      builtNames.push(result.seqName + ' (' + result.placed + ')');
      try { await project.save(); } catch (e) { assemblyLogger.debug('save after part: ' + (e && e.message)); }
    }
    if (!result) {
      status('Nothing to build — all parts empty', 'warning');
      return { ok: false, builtNames: [], error: 'all parts empty' };
    }
    if (bundleList.length > 1) {
      status('Bundle built: ' + builtNames.length + ' timelines', 'ready');
      validation(builtNames.map(function (n) { return '<div class="val-line">✓ ' + escapeHtml(n) + '</div>'; }).join(''));
      assemblyLogger.info('=== BUNDLE DONE: ' + builtNames.join(' | ') + ' ===');
      return { ok: true, builtNames: builtNames };
    }
    var msg = 'Part built: ' + result.seqName + ' — ' + result.placed + ' placed' +
      (result.skipped ? ', ' + result.skipped + ' skipped (not imported)' : '') + ' · V' + result.tracks.v + '/A' + result.tracks.a;
    status(msg, result.skipped ? 'warning' : 'ready');
    validation(
      '<div class="val-line"><b>' + escapeHtml(result.seqName) + '</b></div>' +
      '<div class="val-line">Placed: ' + result.placed + ' / ' + (result.placed + result.skipped) +
      (result.skipped ? ' — ' + result.skipped + ' clip(s) not in project (run INGEST for scenes 09/10)' : '') + '</div>' +
      '<div class="val-line">Tracks: V' + result.tracks.v + ' / A' + result.tracks.a + ' (voice→V1/A1, B-roll→V2/A2)</div>');
    assemblyLogger.info('=== PART BUILD DONE: ' + result.seqName + ' (' + result.placed + ' placed, ' + result.skipped + ' skipped) ===');
    return { ok: true, builtNames: builtNames };
  } catch (err) {
    status('Build error: ' + err.message, 'error');
    assemblyLogger.error('Part build failed: ' + err.message);
    return { ok: false, builtNames: builtNames, error: err.message };
  } finally {
    partsState.building = false;
    $('btn-build-part').removeAttribute('disabled');
  }
}

// ══════════════════════════ PARTS: SELECTIONS (подборки) ══════════════════════════
// Thematic digest reels built by Claude on request, one JSON per topic, living in
// 00_Setup/02_Assembly/parts/selections/. Additive to the Parts flow: checkboxes pick
// which reels to (re)build; stale ones move to selections/archive/ (panel ignores it).
// Build reuses the ENTIRE buildParts() path (clipMap, auto-import, bundle loop) by
// loading the checked files into partsState as a bundle.
let selState = { entries: [] }; // [{name, path, entry, seq, segs, dur, error}]

function selDir() {
  if (!projectState.folderPath) throw new Error('Select project folder first (Project tab)');
  return projectState.folderPath + '/00_Setup/02_Assembly/parts/selections';
}

async function selRefresh() {
  var box = $('sel-list');
  try {
    var dir = await uxpfs.getEntryWithUrl('file://' + selDir());
    var entries = await dir.getEntries();
    selState.entries = [];
    for (var i = 0; i < entries.length; i++) {
      var en = entries[i];
      if (!en.isFile || !/\.json$/i.test(en.name) || /_summary/i.test(en.name)) continue;
      var row = { name: en.name, entry: en, seq: '?', segs: 0, dur: 0, mtime: 0, error: null };
      try {
        var enMeta = await en.getMetadata();
        if (enMeta && enMeta.dateModified) row.mtime = new Date(enMeta.dateModified).getTime();
      } catch (eMt) { /* mtime only orders/labels the list; non-fatal */ }
      try {
        var d = JSON.parse(await en.read());
        if (d.schema !== 'ytai-part-v1' || !d.part || !Array.isArray(d.segments)) throw new Error('not ytai-part-v1');
        row.seq = d.part.sequence_name || ((d.part.code || 'PART') + '_part_' + (d.part.name || '?'));
        row.segs = d.segments.length;
        var dEnd = 0;
        for (var s = 0; s < d.segments.length; s++) {
          var so = d.segments[s].timeline_out_sec;
          if (so == null && d.segments[s].timeline_out) so = tcToSecPanel(d.segments[s].timeline_out);
          if (so != null && so > dEnd) dEnd = so;
        }
        row.dur = dEnd;
      } catch (eR) { row.error = eR.message; }
      selState.entries.push(row);
    }
    // freshest first (Roman: свежие подборки сверху), name as tiebreaker
    selState.entries.sort(function (a, b) { return (b.mtime - a.mtime) || a.name.localeCompare(b.name); });
    if (!selState.entries.length) {
      box.innerHTML = '<div class="val-line">selections/ is empty — ask Claude to build a selection</div>';
      box.style.display = 'block';
      $('btn-sel-build').setAttribute('disabled', 'true');
      $('btn-sel-archive').setAttribute('disabled', 'true');
      return;
    }
    var html = '';
    for (var j = 0; j < selState.entries.length; j++) {
      var r = selState.entries[j];
      var mm = Math.floor(r.dur / 60), ss = Math.round(r.dur % 60);
      var when = '';
      if (r.mtime) {
        var dt = new Date(r.mtime);
        var p2 = function (n) { return (n < 10 ? '0' : '') + n; };
        when = ' <span style="opacity:.55">' + p2(dt.getDate()) + '.' + p2(dt.getMonth() + 1) + ' ' + p2(dt.getHours()) + ':' + p2(dt.getMinutes()) + '</span>';
      }
      var info = r.error ? ('<span style="color:#e66">' + escapeHtml(r.error) + '</span>')
        : (r.segs + ' seg · ' + mm + ':' + (ss < 10 ? '0' : '') + ss + ' → ' + escapeHtml(r.seq));
      html += '<div class="val-line"><label><input type="checkbox" class="sel-check" data-idx="' + j + '"' +
        (r.error ? ' disabled' : '') + '> <b>' + escapeHtml(r.name) + '</b>' + when + ' — ' + info + '</label></div>';
    }
    box.innerHTML = html;
    box.style.display = 'block';
    $('btn-sel-build').removeAttribute('disabled');
    $('btn-sel-archive').removeAttribute('disabled');
    assemblyLogger.info('Selections: ' + selState.entries.length + ' file(s) in selections/');
  } catch (err) {
    // Missing selections/ dir is NOT an error — the folder is optional per project.
    if (/Could not find an entry/i.test(err.message || '')) {
      box.innerHTML = '<div class="val-line">No selections/ in the project — ask Claude to build a selection (the folder is created automatically)</div>';
      box.style.display = 'block';
      $('btn-sel-build').setAttribute('disabled', 'true');
      $('btn-sel-archive').setAttribute('disabled', 'true');
      return;
    }
    assemblyLogger.error('Selections refresh: ' + err.message + ' (dir: ' + (projectState.folderPath || '?') + '/00_Setup/02_Assembly/parts/selections)');
    box.innerHTML = '<div class="val-line">' + escapeHtml(err.message) + '</div>';
    box.style.display = 'block';
    $('btn-sel-build').setAttribute('disabled', 'true');
    $('btn-sel-archive').setAttribute('disabled', 'true');
  }
}

/** "MM:SS.mmm" → seconds (panel-side duplicate of partsBuilder.tcToSec for list preview). */
function tcToSecPanel(tc) {
  if (tc == null) return 0;
  if (typeof tc === 'number') return tc;
  var m = String(tc).match(/(\d+):(\d+(?:\.\d+)?)/);
  return m ? parseInt(m[1], 10) * 60 + parseFloat(m[2]) : parseFloat(tc) || 0;
}

function selChecked() {
  var out = [];
  var boxes = document.querySelectorAll('.sel-check');
  for (var i = 0; i < boxes.length; i++) {
    if (boxes[i].checked) out.push(selState.entries[parseInt(boxes[i].getAttribute('data-idx'), 10)]);
  }
  return out;
}

async function selBuild() {
  var picked = selChecked();
  if (!picked.length) { setPartsStatus('Selections: nothing checked', 'error'); return; }
  var bundle = [];
  for (var i = 0; i < picked.length; i++) {
    var d = JSON.parse(await picked[i].entry.read());
    bundle.push({ part: d.part, segments: d.segments });
  }
  partsState.bundle = bundle;
  partsState.part = bundle[0].part;
  partsState.segments = bundle[0].segments;
  partsState.filePath = 'selections (' + picked.length + ' checked)';
  assemblyLogger.info('Selections build: ' + picked.map(function (p) { return p.name; }).join(', '));
  await buildParts();
}

async function selArchive() {
  var picked = selChecked();
  if (!picked.length) { setPartsStatus('Selections: nothing checked', 'error'); return; }
  try {
    var dir = await uxpfs.getEntryWithUrl('file://' + selDir());
    var arch = null;
    try { arch = await uxpfs.getEntryWithUrl('file://' + selDir() + '/archive'); }
    catch (eA) { arch = await dir.createFolder('archive'); }
    var moved = 0;
    for (var i = 0; i < picked.length; i++) {
      try { await picked[i].entry.moveTo(arch, { overwrite: true }); moved++; }
      catch (eM) { assemblyLogger.warn('archive failed ' + picked[i].name + ': ' + eM.message); }
    }
    setPartsStatus('Archived ' + moved + '/' + picked.length + ' selection(s)', moved === picked.length ? 'ready' : 'warning');
    await selRefresh();
  } catch (err) {
    setPartsStatus('Archive error: ' + err.message, 'error', err);
    assemblyLogger.error('Selections archive failed: ' + err.message);
  }
}

// ══════════════════════════ SHORTS (моменты → 9:16 секвенции) ══════════════════════════
// Claude finds candidate moments in the finished render and writes
// 00_Setup/07_Shorts/{CODE}_Shorts_v{N}_in.json (+ review HTML). The panel shows the
// candidates, builds a marker-preview timeline, reads edited markers back, builds one
// 9:16 sequence per approved candidate (tick grid + 2ms verify gate) and exports the
// panel state as {CODE}_Shorts_v{N}_out.json for the Claude round-trip.
// Engine: src/shorts/shortsBuilder.js · Spec: docs/shorts/SHORTS_SPEC.md.
const shortsLogger = new Logger('SHORTS');
var SHORTS_TPS = 254016000000;

let shortsState = {
  brief: null,           // parsed ytai-shorts-v1 _in.json
  filePath: null,
  fileName: null,
  building: false,
  statuses: {},          // {short_id: proposed|approved|rejected|built}
  editorNotes: {},       // {short_id: ''} — no notes UI in MVP-1, exported as empty strings
  markerReadback: {},    // {short_id: {tc_in:{sec,ticks}, tc_out:{sec,ticks}, moved:true}}
  buildReports: [],      // verify-gate results per built short
  b03Issues: [],         // media-offline issues (refresh-time disk check)
  issues: []             // current validation result (pure W01/O01/S01/B01 + B03 [+B02 after build])
};

function setShortsStatus(text, type, err) {
  var dot = $('shorts-status-dot');
  var txt = $('shorts-status-text');
  if (txt) txt.textContent = text;
  if (dot) dot.className = 'status-dot ' + (type || 'waiting');
  if (type === 'error') shortsLogger.errorShown(text, err);
}

function setShortsValidation(html) {
  var el = $('shorts-validation');
  if (el) { el.innerHTML = html; el.style.display = 'block'; }
}

function shortsDir() {
  if (!projectState.folderPath) throw new Error('Select project folder first (Project tab)');
  return projectState.folderPath + '/00_Setup/07_Shorts';
}

function shortsRenderValidation() {
  var issues = shortsState.issues || [];
  if (!issues.length) {
    setShortsValidation('<div class="val-line" style="color:var(--success)">✓ validation clean (W01/O01/S01/B01/B03)</div>');
    return;
  }
  var html = '';
  for (var i = 0; i < issues.length; i++) {
    var it = issues[i];
    var col = it.severity === 'error' ? 'var(--error)' : 'var(--warning)';
    html += '<div class="val-line"><span style="color:' + col + ';font-weight:700">' + escapeHtml(it.code || '?') + '</span> ' +
      escapeHtml(it.msg || '') + '</div>';
  }
  setShortsValidation(html);
}

function shortsRunValidation() {
  var brief = shortsState.brief;
  if (!brief) return;
  shortsState.issues = validateShortsBrief(brief, shortsState.statuses).concat(shortsState.b03Issues || []);
  shortsRenderValidation();
}

/** B03 — source paths missing on disk (guarded uxpfs existence probe, dedup by path). */
async function shortsCheckMediaOffline(brief) {
  var issues = [];
  var checked = {};
  async function probe(path, file, sid) {
    if (!path || checked[path]) return;
    checked[path] = 1;
    try {
      await uxpfs.getEntryWithUrl('file://' + path);
    } catch (e) {
      issues.push({ code: 'B03', short_id: sid || null, severity: 'warn', msg: 'media offline: ' + (file || path) + ' not found at ' + path });
    }
  }
  try {
    if (brief.project && brief.project.source) await probe(brief.project.source.path, brief.project.source.file, null);
    var cands = brief.candidates || [];
    for (var i = 0; i < cands.length; i++) {
      var blocks = cands[i].blocks || [];
      for (var j = 0; j < blocks.length; j++) {
        var src = blocks[j].source || {};
        await probe(src.path, src.file, cands[i].short_id);
      }
    }
  } catch (e) { shortsLogger.debug('B03 check: ' + e.message); }
  return issues;
}

/** Live candidate duration in seconds — tick-exact via planShort (honours readback overrides). */
function shortsCandDurationSec(cand) {
  try {
    var entries = planShort(cand, shortsState.brief, { markerReadback: shortsState.markerReadback[cand.short_id] });
    if (entries.length) return entries[entries.length - 1].timelineOutTicks / SHORTS_TPS;
  } catch (e) { /* fall through to declared duration */ }
  return cand.duration_sec != null ? cand.duration_sec : 0;
}

/** Candidate's current source range in seconds (min tc_in .. max tc_out over blocks). */
function shortsCandidateRangeSec(cand) {
  var lo = null, hi = null;
  var blocks = cand.blocks || [];
  for (var i = 0; i < blocks.length; i++) {
    var bIn = blocks[i].tc_in, bOut = blocks[i].tc_out;
    var s0 = bIn ? (bIn.sec != null ? bIn.sec : (bIn.ticks != null ? Number(bIn.ticks) / SHORTS_TPS : null)) : null;
    var s1 = bOut ? (bOut.sec != null ? bOut.sec : (bOut.ticks != null ? Number(bOut.ticks) / SHORTS_TPS : null)) : null;
    if (s0 != null && (lo == null || s0 < lo)) lo = s0;
    if (s1 != null && (hi == null || s1 > hi)) hi = s1;
  }
  return (lo != null && hi != null) ? { inSec: lo, outSec: hi } : null;
}

function shortsHeaderStatus() {
  var brief = shortsState.brief;
  if (!brief) return;
  var n = (brief.candidates || []).length;
  var appr = 0, built = 0;
  for (var k in shortsState.statuses) {
    if (shortsState.statuses[k] === 'approved') appr++;
    if (shortsState.statuses[k] === 'built') built++;
  }
  setShortsStatus('v' + brief.version + ' loaded · ' + n + ' candidates (' + appr + ' approved' + (built ? ', ' + built + ' built' : '') + ')', 'ready');
}

function shortsSetCandStatus(sid, st) {
  shortsState.statuses[sid] = st;
  shortsRunValidation();       // O01 respects panel statuses (rejecting one side clears the gate)
  shortsRenderCandidates();
  shortsHeaderStatus();
}

function shortsRenderCandidates() {
  var box = $('shorts-candidates');
  if (!box) return;
  var brief = shortsState.brief;
  if (!brief) {
    box.innerHTML = '<div class="val-line">No shorts brief loaded — hit Refresh.</div>';
    return;
  }
  var cands = brief.candidates || [];
  if (!cands.length) {
    box.innerHTML = '<div class="val-line">Brief has no candidates.</div>';
    return;
  }
  var html = '';
  for (var i = 0; i < cands.length; i++) {
    var c = cands[i];
    var sid = c.short_id || ('S' + (i + 1));
    var st = shortsState.statuses[sid] || 'proposed';
    var checked = (st === 'approved' || st === 'built') ? ' checked' : '';
    var total = (c.score && c.score.total != null) ? c.score.total : '—';
    var rb = shortsState.markerReadback[sid];
    var dur = fmtTime(shortsCandDurationSec(c)) + (rb && rb.moved ? '*' : '');
    var sc = c.score || {};
    var factors = [];
    if (sc.hook != null) factors.push('Hook ' + sc.hook);
    if (sc.flow != null) factors.push('Flow ' + sc.flow);
    if (sc.value != null) factors.push('Value ' + sc.value);
    if (sc.emotion != null) factors.push('Emo ' + sc.emotion);
    var sub = factors.join(' · ') + (c.why ? (factors.length ? ' — ' : '') + '“' + c.why + '”' : '');
    html += '<div class="shorts-cand' + (st === 'rejected' ? ' rejected' : '') + '" data-sid="' + escapeHtml(sid) + '">' +
      '<div class="shorts-cand-main">' +
      '<input type="checkbox" class="shorts-approve" data-sid="' + escapeHtml(sid) + '"' + checked + (st === 'built' ? ' disabled' : '') + '>' +
      '<span class="shorts-sid">' + escapeHtml(sid) + '</span>' +
      '<span class="shorts-score">' + escapeHtml(String(total)) + '</span>' +
      '<span class="shorts-dur">' + escapeHtml(dur) + '</span>' +
      '<span class="shorts-hook">«' + escapeHtml(c.hook_text || '') + '»</span>' +
      '<span class="shorts-st' + ((st === 'approved' || st === 'built') ? ' on-ok' : '') + '" data-sid="' + escapeHtml(sid) + '" data-act="approve" title="approve">✓</span>' +
      '<span class="shorts-st' + (st === 'rejected' ? ' on-no' : '') + '" data-sid="' + escapeHtml(sid) + '" data-act="reject" title="reject">✗</span>' +
      '<span class="shorts-badge' + (st === 'built' ? ' built' : '') + '">' + escapeHtml(st) + '</span>' +
      '</div>' +
      '<div class="shorts-cand-sub">' + escapeHtml(sub) + '</div>' +
      '</div>';
  }
  box.innerHTML = html;
  // Listeners wired DIRECTLY on elements — sp-button Shadow DOM breaks closest(),
  // and delegation is fragile in UXP; the list is small, re-render is cheap.
  box.querySelectorAll('input.shorts-approve').forEach(function (cb) {
    cb.addEventListener('change', function () {
      var sid = this.getAttribute('data-sid');
      if (shortsState.statuses[sid] === 'built') return;
      shortsSetCandStatus(sid, this.checked ? 'approved' : 'proposed');
    });
  });
  box.querySelectorAll('.shorts-st').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var sid = this.getAttribute('data-sid');
      var act = this.getAttribute('data-act');
      shortsSetCandStatus(sid, act === 'approve' ? 'approved' : 'rejected');
    });
  });
}

/** Load the newest {CODE}_Shorts_v{N}_in.json from 00_Setup/07_Shorts/ (loadPart pattern). */
async function shortsRefresh() {
  try {
    setShortsStatus('Scanning 00_Setup/07_Shorts/...', 'waiting');
    var dir;
    try {
      dir = await uxpfs.getEntryWithUrl('file://' + shortsDir());
    } catch (eDir) {
      setShortsStatus('No 00_Setup/07_Shorts/ — ask Claude to generate a shorts brief', 'error');
      return;
    }
    var entries = await dir.getEntries();
    var cands = [];
    for (var i = 0; i < entries.length; i++) {
      if (entries[i].isFile && /_in\.json$/i.test(entries[i].name)) cands.push(entries[i]);
    }
    if (!cands.length) {
      setShortsStatus('No *_in.json in 00_Setup/07_Shorts/ — ask Claude to generate one', 'error');
      return;
    }
    // newest by dateModified when available, else by name (higher version sorts later)
    var best = cands[0], bestT = 0;
    for (var b = 0; b < cands.length; b++) {
      var t = 0;
      try {
        var meta = await cands[b].getMetadata();
        t = meta && meta.dateModified ? new Date(meta.dateModified).getTime() : 0;
      } catch (eMt) { /* no metadata */ }
      if (t > bestT || (t === bestT && cands[b].name.localeCompare(best.name) > 0)) { best = cands[b]; bestT = t; }
    }
    var data = JSON.parse(await best.read());
    if (data.schema !== 'ytai-shorts-v1') {
      throw new Error('Not a ytai-shorts-v1 file: ' + best.name + ' (schema=' + (data.schema || '?') + ')');
    }
    shortsState.brief = data;
    shortsState.filePath = shortsDir() + '/' + best.name;
    shortsState.fileName = best.name;
    shortsState.statuses = {};
    shortsState.editorNotes = {};
    shortsState.markerReadback = {};
    shortsState.buildReports = [];
    var list = data.candidates || [];
    for (var c = 0; c < list.length; c++) {
      var sid = list[c].short_id || ('S' + (c + 1));
      shortsState.statuses[sid] = list[c].status || 'proposed';
      shortsState.editorNotes[sid] = '';
    }
    shortsState.b03Issues = await shortsCheckMediaOffline(data);
    shortsRunValidation();
    shortsRenderCandidates();
    var modeEl = $('shorts-mode');
    if (modeEl) modeEl.textContent = (data.project && data.project.mode) || 'finished';
    var infoEl = $('shorts-file-info');
    if (infoEl) {
      infoEl.textContent = best.name + ' · ' + list.length + ' candidates · fps ' +
        ((data.project && data.project.fps) || 25) + ' · source ' +
        ((data.project && data.project.source && data.project.source.file) || '?') +
        ' · shortsBuilder v' + SHORTS_BUILDER_VERSION;
    }
    shortsHeaderStatus();
    shortsLogger.info('Shorts brief loaded: ' + best.name + ' (' + list.length + ' candidates, ' +
      shortsState.issues.length + ' issue(s))');
  } catch (err) {
    setShortsStatus('Error: ' + err.message, 'error', err);
    shortsLogger.error('Shorts refresh failed: ' + err.message);
  }
}

/** Build {CODE}_Shorts_Preview_v{N} — source on V1 + range marker per non-rejected candidate. */
async function shortsBuildPreview() {
  try {
    var brief = shortsState.brief;
    if (!brief) { setShortsStatus('No shorts brief loaded — Refresh first', 'error'); return; }
    // O01 = blocking gate (Firecut pattern): no preview over unresolved overlaps.
    var overlaps = (shortsState.issues || []).filter(function (i) { return i.code === 'O01'; });
    if (overlaps.length) {
      setShortsStatus('Overlapping candidates (O01) — reject one side first', 'error');
      return;
    }
    setShortsStatus('Building preview sequence...', 'waiting');
    var project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');
    var r = await buildPreviewSequence(project, brief, { logger: shortsLogger, statuses: shortsState.statuses });
    try { await project.save(); } catch (eS) { /* non-fatal */ }
    setShortsStatus('Preview built: ' + r.seqName + ' — ' + r.markers + '/' + r.candidates + ' markers. Drag markers to fix boundaries, then Read Back.', 'ready');
  } catch (err) {
    setShortsStatus('Preview error: ' + err.message, 'error', err);
    shortsLogger.error('Shorts preview failed: ' + err.message);
  }
}

/** Read S{NN} markers from the ACTIVE sequence back into candidate boundaries. */
async function shortsReadBackMarkers() {
  try {
    var brief = shortsState.brief;
    if (!brief) { setShortsStatus('No shorts brief loaded — Refresh first', 'error'); return; }
    var project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');
    var seq = await project.getActiveSequence();
    if (!seq) throw new Error('No active sequence — open the Shorts preview sequence first');
    var fps = (brief.project && brief.project.fps) || 25;
    var halfFrame = 0.5 / fps;
    // Marker read API varies by build — guard both forms (exportMarkers pattern).
    var owner = null;
    try { if (ppro.Markers && ppro.Markers.getMarkers) owner = await ppro.Markers.getMarkers(seq); } catch (e) { /* next */ }
    if (!owner) { try { if (typeof seq.getMarkers === 'function') owner = await seq.getMarkers(); } catch (e) { /* none */ } }
    var list = null;
    if (owner) {
      try { list = (typeof owner.getMarkers === 'function') ? await owner.getMarkers() : (Array.isArray(owner) ? owner : null); } catch (e) { /* none */ }
    }
    if (!list || !list.length) { setShortsStatus('No markers on the active sequence (' + (seq.name || '?') + ')', 'error'); return; }
    var byId = {};
    (brief.candidates || []).forEach(function (c) { if (c.short_id) byId[c.short_id] = c; });
    var matched = 0, moved = 0;
    for (var mi = 0; mi < list.length; mi++) {
      var m = list[mi];
      var name = '';
      try { name = m.name || (m.getName ? m.getName() : '') || ''; } catch (e) { /* skip */ }
      var idm = String(name).match(/^(S\d+)/);
      if (!idm) continue;
      var cand = byId[idm[1]];
      if (!cand) continue;
      matched++;
      var startTT = null, durTT = null;
      try { startTT = m.getStart ? m.getStart() : null; } catch (e) { /* next */ }
      if (!startTT) { try { startTT = m.startTime || m.start; } catch (e) { /* none */ } }
      try { durTT = m.getDuration ? m.getDuration() : null; } catch (e) { /* next */ }
      if (!durTT) { try { durTT = m.duration; } catch (e) { /* none */ } }
      var mIn = tickSec(startTT);
      if (mIn < 0) continue;
      var mDur = durTT ? tickSec(durTT) : 0;
      if (!(mDur > 0)) continue; // point markers carry no range edit
      var mOut = mIn + mDur;
      var cur = shortsCandidateRangeSec(cand);
      if (!cur) continue;
      if (Math.abs(mIn - cur.inSec) > halfFrame || Math.abs(mOut - cur.outSec) > halfFrame) {
        // Snap the read-back range: in → floor, out → ceil on the frame grid.
        var inSnap = snapToFrame(mIn, fps, 'floor');
        var outSnap = snapToFrame(mOut, fps, 'ceil');
        shortsState.markerReadback[idm[1]] = {
          tc_in: { sec: inSnap, ticks: Math.round(inSnap * SHORTS_TPS) },
          tc_out: { sec: outSnap, ticks: Math.round(outSnap * SHORTS_TPS) },
          moved: true
        };
        moved++;
        shortsLogger.info('Read back ' + idm[1] + ': ' + inSnap.toFixed(3) + '–' + outSnap.toFixed(3) +
          's (was ' + cur.inSec.toFixed(3) + '–' + cur.outSec.toFixed(3) + 's)');
      }
    }
    shortsRenderCandidates();
    setShortsStatus('Read back: ' + matched + ' marker(s) matched, ' + moved + ' boundary edit(s) — durations updated', 'ready');
  } catch (err) {
    setShortsStatus('Read back error: ' + err.message, 'error', err);
    shortsLogger.error('Shorts read-back failed: ' + err.message);
  }
}

/** Build one 9:16 sequence per approved candidate; collect verify-gate reports. */
async function shortsBuildApproved() {
  var brief = shortsState.brief;
  if (!brief) { setShortsStatus('No shorts brief loaded — Refresh first', 'error'); return; }
  if (shortsState.building) { shortsLogger.warn('Shorts build already in progress'); return; }
  var picked = (brief.candidates || []).filter(function (c) {
    return shortsState.statuses[c.short_id] === 'approved';
  });
  if (!picked.length) { setShortsStatus('No approved candidates — tick ✓ first', 'error'); return; }
  shortsState.building = true;
  $('btn-shorts-build').setAttribute('disabled', 'true');
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');
    shortsLogger.info('=== SHORTS BUILD START: ' + picked.length + ' approved (shortsBuilder v' + SHORTS_BUILDER_VERSION + ') ===');
    try { await project.save(); } catch (e) { /* non-fatal */ }
    var reports = [];
    for (var i = 0; i < picked.length; i++) {
      var cand = picked[i];
      setShortsStatus('Building ' + (i + 1) + '/' + picked.length + ': ' + cand.short_id + '...', 'waiting');
      try {
        var r = await buildShortSequence(project, cand, brief, {
          logger: shortsLogger,
          markerReadback: shortsState.markerReadback[cand.short_id]
        });
        // Strip the live seq handle before persisting into panel state / _out.json.
        var clean = {
          short_id: r.short_id, sequence: r.sequence, built_at: r.built_at,
          drift_ms: r.drift_ms, ok: r.ok, clips: r.clips, spike_s1: r.spike_s1,
          placed: r.placed, skipped: r.skipped
        };
        if (r.verify_error) clean.verify_error = r.verify_error;
        reports.push(clean);
        if (r.ok) shortsState.statuses[cand.short_id] = 'built';
      } catch (eB) {
        shortsLogger.error(cand.short_id + ' build failed: ' + eB.message);
        reports.push({ short_id: cand.short_id, sequence: null, built_at: new Date().toISOString(), drift_ms: null, ok: false, error: eB.message, clips: [] });
      }
      try { await project.save(); } catch (e) { /* non-fatal */ }
    }
    // Merge into buildReports by short_id (rebuilds replace their old report).
    var byId = {};
    shortsState.buildReports.forEach(function (r) { byId[r.short_id] = r; });
    reports.forEach(function (r) { byId[r.short_id] = r; });
    shortsState.buildReports = Object.keys(byId).map(function (k) { return byId[k]; });
    // B02 — drift over 2ms after build (spec §5.2).
    shortsState.issues = (shortsState.issues || []).filter(function (i) { return i.code !== 'B02'; });
    reports.forEach(function (r) {
      if (!r.ok && r.drift_ms != null && r.drift_ms > 2) {
        shortsState.issues.push({ code: 'B02', short_id: r.short_id, severity: 'error', msg: r.short_id + ': drift ' + r.drift_ms + 'ms > 2ms after build' });
      }
    });
    var okN = reports.filter(function (r) { return r.ok; }).length;
    var lines = reports.map(function (r) {
      return '<div class="val-line">' + (r.ok ? '<span style="color:var(--success)">✓</span>' : '<span style="color:var(--error)">✗</span>') +
        ' <b>' + escapeHtml(r.short_id) + '</b>' +
        (r.sequence ? ' ' + escapeHtml(r.sequence) : '') +
        (r.drift_ms != null ? ' — drift ' + r.drift_ms + 'ms' : '') +
        (r.error ? ' — ' + escapeHtml(r.error) : '') +
        (r.verify_error ? ' — ' + escapeHtml(r.verify_error) : '') + '</div>';
    });
    if (reports.length && reports[0].spike_s1) {
      lines.push('<div class="val-line" style="color:var(--text-secondary)">' + escapeHtml(reports[0].spike_s1) + '</div>');
    }
    setShortsValidation(lines.join(''));
    setShortsStatus('Built ' + okN + '/' + reports.length + ' short(s)' + (okN === reports.length ? ' — all verified ≤2ms' : ' — see panel'), okN === reports.length ? 'ready' : 'error');
    shortsRenderCandidates();
    shortsLogger.info('=== SHORTS BUILD DONE: ' + okN + '/' + reports.length + ' ok ===');
  } catch (err) {
    setShortsStatus('Build error: ' + err.message, 'error', err);
    shortsLogger.error('Shorts build failed: ' + err.message);
  } finally {
    shortsState.building = false;
    $('btn-shorts-build').removeAttribute('disabled');
  }
}

/** Write {CODE}_Shorts_v{N}_out.json (spec §5.2) and copy its path to the clipboard. */
async function shortsExportOut() {
  try {
    var brief = shortsState.brief;
    if (!brief) { setShortsStatus('No shorts brief loaded — Refresh first', 'error'); return; }
    setShortsStatus('Exporting _out.json...', 'waiting');
    var code = (brief.project && brief.project.code) || extractProjectCode(projectState.projectName || '');
    var version = brief.version != null ? brief.version : 1;
    var fps = (brief.project && brief.project.fps) || 25;
    var editorNotes = {};
    (brief.candidates || []).forEach(function (c) {
      if (c.short_id) editorNotes[c.short_id] = shortsState.editorNotes[c.short_id] || '';
    });
    var out = {
      schema: 'ytai-shorts-v1',
      direction: 'out',
      version: version,
      based_on_in: shortsState.fileName || null,
      exported_at: new Date().toISOString(),
      panel_state: {
        statuses: shortsState.statuses,
        editor_notes: editorNotes,
        marker_readback: shortsState.markerReadback
      },
      build_report: shortsState.buildReports,
      issues: shortsState.issues,
      sequence_dumps: {}
    };
    // Full per-track dumps of every built sequence (dumpSequence — the proven extractor).
    try {
      var project = await ppro.Project.getActiveProject();
      if (project && shortsState.buildReports.length) {
        var all = await listProjectSequences(project, shortsLogger);
        var byName = {};
        all.forEach(function (e) { byName[e.name] = e.seq; });
        for (var d = 0; d < shortsState.buildReports.length; d++) {
          var rep = shortsState.buildReports[d];
          if (!rep.sequence || !byName[rep.sequence]) continue;
          try {
            out.sequence_dumps[rep.short_id] = await dumpSequence(byName[rep.sequence], fps, null);
          } catch (eDump) { shortsLogger.debug('dump ' + rep.sequence + ': ' + eDump.message); }
        }
      }
    } catch (eSeqs) { shortsLogger.warn('sequence dumps skipped: ' + eSeqs.message); }
    var fname = code + '_Shorts_v' + version + '_out.json';
    var dir = await uxpfs.getEntryWithUrl('file://' + shortsDir());
    var f = await dir.createFile(fname, { overwrite: true });
    await f.write(JSON.stringify(out, null, 2));
    var outPath = shortsDir() + '/' + fname;
    var copied = false;
    try { await navigator.clipboard.writeText(outPath); copied = true; } catch (eCb) { shortsLogger.debug('clipboard: ' + eCb.message); }
    setShortsStatus('Out → ' + fname + (copied ? ' — path copied 📋' : ''), 'ready');
    setShortsValidation('<div class="val-line"><b>Exported for Claude</b>' + (copied ? ' · 📋 path copied' : '') + '</div>' +
      '<div class="val-line">' + escapeHtml(outPath) + '</div>' +
      '<div class="val-line">' + shortsState.buildReports.length + ' build report(s) · ' +
      Object.keys(out.sequence_dumps).length + ' sequence dump(s) · ' + (shortsState.issues || []).length + ' issue(s)</div>');
    shortsLogger.info('=== SHORTS OUT → ' + outPath + ' ===');
  } catch (err) {
    setShortsStatus('Export error: ' + err.message, 'error', err);
    shortsLogger.error('Shorts export failed: ' + err.message);
  }
}

/** Open the newest {CODE}_shorts_review_v{N}.html from 07_Shorts in the browser. */
async function shortsOpenReviewHtml() {
  try {
    var dir = await uxpfs.getEntryWithUrl('file://' + shortsDir());
    var entries = await dir.getEntries();
    var best = null, bestV = -1;
    for (var i = 0; i < entries.length; i++) {
      if (!entries[i].isFile) continue;
      var m = entries[i].name.match(/_shorts_review_v(\d+)\.html$/i);
      if (!m) continue;
      var v = parseInt(m[1], 10);
      if (v > bestV) { best = entries[i]; bestV = v; }
    }
    if (!best) { setShortsStatus('No *_shorts_review_v{N}.html in 00_Setup/07_Shorts/', 'error'); return; }
    var shell = require('uxp').shell;
    await shell.openPath(best.nativePath || (shortsDir() + '/' + best.name));
    setShortsStatus('Opened ' + best.name, 'ready');
  } catch (err) {
    setShortsStatus('Open HTML error: ' + err.message, 'error', err);
    shortsLogger.error('Shorts open review HTML failed: ' + err.message);
  }
}

// ══════════════════════════ ASSEMBLY: SCENE TIMELINES (two-step assembly) ══════════════════════════
// Per-scene A-timelines + PE00 premontage generated by make_mcam_part.py --scene /
// make_master_part.py --pe into 00_Setup/02_Assembly/scenes/. Checkbox list on the
// Assembly tab (Ingest scene-list pattern); build reuses the ENTIRE buildParts() path
// (clipMap, auto-import, bundle loop) — partsBuilder handles part.bin internally.
let asmScenesState = { entries: [], peEntry: null }; // entries: [{name, entry, seqName, dsSeqName, parts, segs, error, built}]

function asmScenesDir() {
  if (!projectState.folderPath) throw new Error('Select project folder first (Project tab)');
  return projectState.folderPath + '/00_Setup/02_Assembly/scenes';
}

async function refreshAssemblyScenes() {
  var panel = $('assembly-scenes');
  var list = $('assembly-scenes-list');
  asmScenesState = { entries: [], peEntry: null };
  var entries = [];
  try {
    var dir = await uxpfs.getEntryWithUrl('file://' + asmScenesDir());
    entries = await dir.getEntries();
  } catch (e) {
    // no project selected / scenes dir absent — hide the block, non-fatal
    panel.style.display = 'none';
    list.innerHTML = '';
    $('btn-build-assembly-scenes').setAttribute('disabled', 'true');
    $('btn-build-premontage').setAttribute('disabled', 'true');
    return;
  }
  var peCands = [];
  for (var i = 0; i < entries.length; i++) {
    var en = entries[i];
    if (!en.isFile || !/\.json$/i.test(en.name)) continue;
    if (/_PE00_/i.test(en.name)) { peCands.push(en); continue; }
    var row = { name: en.name, entry: en, seqName: null, dsSeqName: null, parts: 0, segs: 0, error: null, built: false };
    try {
      var d = JSON.parse(await en.read());
      if (d.schema === 'ytai-parts-bundle-v1' && Array.isArray(d.parts) && d.parts.length) {
        // A-part = first part whose sequence_name does NOT end __DeletedScene (never by index)
        for (var p = 0; p < d.parts.length; p++) {
          var sq = String((d.parts[p].part && d.parts[p].part.sequence_name) || '');
          if (/__DeletedScene$/.test(sq)) { if (!row.dsSeqName) row.dsSeqName = sq; }
          else if (!row.seqName) row.seqName = sq;
          row.segs += (d.parts[p].segments || []).length;
        }
        row.parts = d.parts.length;
        if (!row.seqName) throw new Error('no A-part (all __DeletedScene)');
      } else if (d.schema === 'ytai-part-v1' && d.part && Array.isArray(d.segments)) {
        row.seqName = d.part.sequence_name || ((d.part.code || 'PART') + '_part_' + (d.part.name || '?'));
        row.parts = 1;
        row.segs = d.segments.length;
      } else {
        throw new Error('not ytai-part-v1 / ytai-parts-bundle-v1');
      }
    } catch (eR) { row.error = eR.message; }
    asmScenesState.entries.push(row);
  }
  asmScenesState.entries.sort(function (a, b) { return a.name.localeCompare(b.name); }); // A01..A13
  // Several *_PE00_* files (stale copy/rename) → take the newest by mtime, loudly.
  if (peCands.length) {
    var peBest = peCands[0], peBestT = 0;
    for (var pc = 0; pc < peCands.length; pc++) {
      var pcT = 0;
      try { var pcM = await peCands[pc].getMetadata(); pcT = pcM && pcM.dateModified ? new Date(pcM.dateModified).getTime() : 0; } catch (e) { assemblyLogger.debug('PE00 mtime unreadable for ' + peCands[pc].name + ': ' + (e && e.message)); }
      if (pcT > peBestT) { peBest = peCands[pc]; peBestT = pcT; }
    }
    asmScenesState.peEntry = peBest;
    if (peCands.length > 1) assemblyLogger.warn('scenes/: ' + peCands.length + ' PE00 files — using newest: ' + peBest.name);
  }
  if (!asmScenesState.entries.length && !asmScenesState.peEntry) {
    panel.style.display = 'none';
    list.innerHTML = '';
    $('btn-build-assembly-scenes').setAttribute('disabled', 'true');
    $('btn-build-premontage').setAttribute('disabled', 'true');
    return;
  }
  // Built = A-sequence exists as a REAL sequence (getSequences-backed; bare root-item
  // name scans mark offline master-clip stubs "built ✓" — YTUVI05-proven).
  try {
    var project = await ppro.Project.getActiveProject();
    if (project) {
      var wanted = {};
      asmScenesState.entries.forEach(function (r) {
        if (r.seqName) wanted[r.seqName] = true;
        if (r.dsSeqName) wanted[r.dsSeqName] = true;
      });
      var byName = await findSequencesByName(project, wanted);
      // built = A-sequence AND (когда в бандле есть DeletedScene) её секвенция тоже
      asmScenesState.entries.forEach(function (r) {
        r.built = !!(r.seqName && byName[r.seqName]) && (!r.dsSeqName || !!byName[r.dsSeqName]);
      });
    }
  } catch (eSeq) { assemblyLogger.debug('Assembly scenes sequence detection failed: ' + eSeq.message); }
  var parseable = 0;
  list.innerHTML = asmScenesState.entries.map(function (r, idx) {
    if (!r.error) parseable++;
    var meta = r.error ? '<span style="color:#e66">' + escapeHtml(r.error) + '</span>'
      : (r.parts + ' parts · ' + r.segs + ' segs');
    var badge = r.error ? 'error' : (r.built ? 'built ✓' : 'new');
    return '<div class="scene-row">' +
      '<label class="scene-pick">' +
      '<input type="checkbox" class="asm-scene-cb" value="' + idx + '"' +
      (r.error ? ' disabled' : (r.built ? '' : ' checked')) + '>' +
      '<span class="scene-name">' + escapeHtml(r.name) + '</span>' +
      '</label>' +
      '<span class="scene-meta">' + meta + '</span>' +
      '<span class="scene-badge' + (r.built ? ' built' : '') + '">' + badge + '</span>' +
      '</div>';
  }).join('');
  panel.style.display = 'block';
  if (parseable) $('btn-build-assembly-scenes').removeAttribute('disabled');
  else $('btn-build-assembly-scenes').setAttribute('disabled', 'true');
  if (asmScenesState.peEntry) {
    $('btn-build-premontage').removeAttribute('disabled');
    $('btn-build-premontage').setAttribute('title', asmScenesState.peEntry.name);
  } else {
    $('btn-build-premontage').setAttribute('disabled', 'true');
    $('btn-build-premontage').setAttribute('title', 'No *_PE00_*.json in 02_Assembly/scenes/ — generate via make_master_part.py --pe');
  }
  assemblyLogger.info('Assembly scenes: ' + asmScenesState.entries.length + ' bundle(s)' +
    (asmScenesState.peEntry ? ' + PE00 (' + asmScenesState.peEntry.name + ')' : '') + ' in scenes/');
}

function getSelectedAssemblyScenes() {
  return Array.prototype.slice.call(document.querySelectorAll('.asm-scene-cb'))
    .filter(function (cb) { return cb.checked && !cb.disabled; })
    .map(function (cb) { return asmScenesState.entries[parseInt(cb.value, 10)]; })
    .filter(function (r) { return !!r; });
}

function setAssemblySceneChecks(mode) {
  Array.prototype.slice.call(document.querySelectorAll('.asm-scene-cb')).forEach(function (cb) {
    if (cb.disabled) { cb.checked = false; return; }
    var row = cb.closest('.scene-row');
    var isBuilt = row && row.querySelector('.scene-badge.built');
    if (mode === 'all') cb.checked = true;
    else if (mode === 'none') cb.checked = false;
    else cb.checked = !isBuilt; // 'new'
  });
}

// Assembly-tab builds route progress into their own tab; the loaded Parts-tab state
// is NOT touched (the bundle goes to buildParts explicitly).
var asmScenesBuilding = false;
var asmUi = {
  status: setAssemblyStatus,
  validation: function (html) {
    var el = $('assembly-validation');
    if (el) { el.innerHTML = html; el.style.display = 'block'; }
  },
};

async function buildAssemblyScenes() {
  if (asmScenesBuilding || partsState.building) { setAssemblyStatus('Build already in progress', 'error'); return; }
  var picked = getSelectedAssemblyScenes();
  if (!picked.length) { setAssemblyStatus('No timelines selected — tick at least one', 'error'); return; }
  asmScenesBuilding = true;
  $('btn-build-assembly-scenes').setAttribute('disabled', 'true');
  $('btn-build-premontage').setAttribute('disabled', 'true');
  var okNames = [], failed = [];
  try {
    for (var i = 0; i < picked.length; i++) {
      var row = picked[i];
      setAssemblyStatus('Building ' + (i + 1) + '/' + picked.length + ': ' + row.name + '...', 'waiting');
      var bundle = [];
      try {
        // fresh read — the file may have been regenerated since the list was rendered
        var d = JSON.parse(await row.entry.read());
        if (d.schema === 'ytai-parts-bundle-v1' && Array.isArray(d.parts) && d.parts.length) {
          d.parts.forEach(function (p) { bundle.push({ part: p.part, segments: p.segments }); });
        } else if (d.schema === 'ytai-part-v1' && d.part && Array.isArray(d.segments)) {
          bundle.push({ part: d.part, segments: d.segments });
        } else {
          throw new Error('not ytai-part-v1 / ytai-parts-bundle-v1');
        }
      } catch (eR) {
        failed.push(row.name + ' (' + eR.message + ')');
        assemblyLogger.error('Assembly scene read failed ' + row.name + ': ' + eR.message);
        continue;
      }
      assemblyLogger.info('Assembly scenes build ' + (i + 1) + '/' + picked.length + ': ' + row.name);
      var res = await buildParts(bundle, asmUi);
      if (res && res.ok) okNames = okNames.concat(res.builtNames);
      else failed.push(row.name + ((res && res.error) ? ' (' + res.error + ')' : ''));
    }
    if (!failed.length) setAssemblyStatus('Built: ' + okNames.join(', '), 'ready');
    else setAssemblyStatus('Build failed: ' + failed.join(', ') + (okNames.length ? ' · built: ' + okNames.join(', ') : ''), 'error');
  } finally {
    asmScenesBuilding = false;
    await refreshAssemblyScenes(); // re-enables the buttons per current state
  }
}

async function buildPremontage() {
  if (asmScenesBuilding || partsState.building) { setAssemblyStatus('Build already in progress', 'error'); return; }
  if (!asmScenesState.peEntry) {
    setAssemblyStatus('No PE00 file in 02_Assembly/scenes/ — generate via make_master_part.py --pe', 'error');
    return;
  }
  asmScenesBuilding = true;
  $('btn-build-assembly-scenes').setAttribute('disabled', 'true');
  $('btn-build-premontage').setAttribute('disabled', 'true');
  try {
    var d = JSON.parse(await asmScenesState.peEntry.read());
    var bundle = [];
    if (d.schema === 'ytai-parts-bundle-v1' && Array.isArray(d.parts) && d.parts.length) bundle = d.parts;
    else if (d.schema === 'ytai-part-v1' && d.part && Array.isArray(d.segments)) bundle = [{ part: d.part, segments: d.segments }];
    else throw new Error(asmScenesState.peEntry.name + ': not ytai-part-v1 / ytai-parts-bundle-v1');
    setAssemblyStatus('Building premontage: ' + (bundle[0].part.sequence_name || '?') + '...', 'waiting');
    var res = await buildParts(bundle, asmUi);
    setAssemblyStatus(res && res.ok ? 'Built: ' + res.builtNames.join(', ')
      : 'Build failed: ' + ((res && res.error) || '?'), res && res.ok ? 'ready' : 'error');
  } catch (err) {
    setAssemblyStatus('Premontage: ' + err.message, 'error', err);
    assemblyLogger.error('Premontage build failed: ' + err.message);
  } finally {
    asmScenesBuilding = false;
    await refreshAssemblyScenes();
  }
}

// ══════════════════════════ FOOTAGE REVIEW (отсмотр) ══════════════════════════
// Lightweight screening path: scan inserted camera cards (or the open project's
// 01_Source/Video) for clips, lay them back-to-back on a timeline, apply a viewing
// LUT. No JSON brief, no project picker — uses the active project. Import in place.
const footageLogger = new Logger('FOOTAGE');
let footageState = { building: false };

function setFootageStatus(text, type, err) {
  var dot = $('footage-status-dot');
  var txt = $('footage-status-text');
  if (txt) txt.textContent = text;
  if (dot) dot.className = 'status-dot ' + (type || 'waiting');
  if (type === 'error') footageLogger.errorShown(text, err);
}

function setFootageValidation(html) {
  var el = $('footage-validation');
  if (el) { el.innerHTML = html; el.style.display = 'block'; }
}

var FOOTAGE_VIDEO_EXTS = ['.mp4', '.mov', '.m4v', '.mts', '.avi', '.mkv', '.mxf'];
function footageIsVideo(name) {
  var n = String(name).toLowerCase();
  for (var i = 0; i < FOOTAGE_VIDEO_EXTS.length; i++) {
    if (n.endsWith(FOOTAGE_VIDEO_EXTS[i])) return true;
  }
  return false;
}

// Walk a folder entry to `parts` (e.g. ['M4ROOT','CLIP']) — UXP getEntry takes one name.
async function footageGetNested(folder, parts) {
  var cur = folder;
  for (var i = 0; i < parts.length; i++) {
    try { cur = await cur.getEntry(parts[i]); } catch (e) { return null; }
    if (!cur) return null;
  }
  return cur;
}

// Collect video nativePaths under a folder, recursing up to maxDepth subfolders.
async function footageCollectVideos(folderEntry, maxDepth, out) {
  var entries;
  try { entries = await folderEntry.getEntries(); } catch (e) { return; }
  for (var i = 0; i < entries.length; i++) {
    var en = entries[i];
    try {
      if (en.isFile && footageIsVideo(en.name)) {
        out.push(en.nativePath);
      } else if (en.isFolder && maxDepth > 0 && String(en.name).charAt(0) !== '.') {
        await footageCollectVideos(en, maxDepth - 1, out);
      }
    } catch (e) { /* skip unreadable entry */ }
  }
}

// Scan mounted volumes for camera-card footage (Sony M4ROOT/CLIP, DCIM, loose CLIP).
async function footageScanCards() {
  var sources = [];
  var volumesEntry;
  try { volumesEntry = await uxpfs.getEntryWithUrl('file:///Volumes'); }
  catch (e) { footageLogger.warn('Cannot read /Volumes: ' + e.message); return sources; }
  var vols;
  try { vols = await volumesEntry.getEntries(); } catch (e) { return sources; }
  var cardRoots = [['M4ROOT', 'CLIP'], ['PRIVATE', 'M4ROOT', 'CLIP'], ['CLIP'], ['DCIM']];
  for (var i = 0; i < vols.length; i++) {
    var vol = vols[i];
    if (!vol.isFolder) continue;
    var files = [];
    for (var c = 0; c < cardRoots.length; c++) {
      var sub = await footageGetNested(vol, cardRoots[c]);
      if (sub && sub.isFolder) {
        // DCIM nests clips one level deeper (e.g. DCIM/100MSDCF/*)
        var depth = (cardRoots[c][cardRoots[c].length - 1] === 'DCIM') ? 1 : 0;
        await footageCollectVideos(sub, depth, files);
      }
    }
    if (files.length > 0) {
      files = Array.from(new Set(files)).sort();
      sources.push({ label: vol.name, kind: 'card', files: files });
      footageLogger.info('Card "' + vol.name + '": ' + files.length + ' clip(s)');
    }
  }
  return sources;
}

// Fallback source: video in the open project's 01_Source/Video (or its root).
async function footageScanProject(project) {
  var ppath = null;
  try { ppath = project.path; } catch (e) { /* getter may not exist */ }
  if (!ppath) { try { ppath = await project.getPath(); } catch (e) { /* none */ } }
  if (!ppath) return null;
  var dir = String(ppath).replace(/\/[^/]*$/, ''); // strip .prproj filename
  var root;
  try { root = await footageResolveFolder(dir); } catch (e) { return null; }
  var files = [];
  var srcVideo = await footageGetNested(root, ['01_Source', 'Video']);
  if (srcVideo && srcVideo.isFolder) await footageCollectVideos(srcVideo, 2, files);
  if (files.length === 0) await footageCollectVideos(root, 1, files); // loose clips
  if (files.length === 0) return null;
  files = Array.from(new Set(files)).sort();
  var label = String(dir).split('/').pop() || 'Project';
  footageLogger.info('Project folder "' + label + '": ' + files.length + ' clip(s)');
  return { label: label, kind: 'project', files: files };
}

async function footageGatherSources(project) {
  var sources = await footageScanCards();
  if (sources.length === 0) {
    var proj = await footageScanProject(project);
    if (proj) sources.push(proj);
  }
  return sources;
}

// English project name: ASCII letters/digits kept, spaces/other → hyphens (per Roman's
// rule: English letters, multi-word → hyphens). Non-ASCII (Cyrillic) is dropped, so a
// Russian entry collapses to '' and we fall back to the card label.
function footageHyphenate(s) {
  return String(s || '').trim().replace(/[^A-Za-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

// Common parent folder of the found clips (clips usually share one folder).
function footageCommonFolder(files) {
  if (!files || !files.length) return '';
  return String(files[0]).replace(/\/[^/]*$/, '');
}

// Where to write logs/LUTs, in priority order:
//   1. the folder picked via "Select Project Folder" (reliable, like the Ingest stage)
//   2. the open project's folder (project.path — can be empty for an untitled project)
//   3. the folder the clips were FOUND in (if files were found there, use that folder)
//   4. '' → caller falls back to the plugin data folder.
function footageTargetFolder(project) {
  try { if (projectState && projectState.folderPath) return String(projectState.folderPath); } catch (e) { /* ignore */ }
  try { if (project && project.path) return String(project.path).replace(/\/[^/]*$/, ''); } catch (e) { /* ignore */ }
  if (footageState.lastSourceFolder) return footageState.lastSourceFolder;
  return '';
}

// Active project's folder name (where the .prproj lives) — the default project name.
async function footageProjectFolderName(project) {
  try {
    var p = project || (await ppro.Project.getActiveProject());
    if (!p) return '';
    var pp = null;
    try { pp = p.path; } catch (e) { /* getter may throw */ }
    if (!pp) { try { pp = await p.getPath(); } catch (e) { /* none */ } }
    if (!pp) return '';
    return String(pp).replace(/\/[^/]*$/, '').split('/').pop() || '';
  } catch (e) { return ''; }
}

// Resolve a folder entry from a native path, trying multiple URL forms — different UXP
// builds accept raw paths vs encoded ones. Raw first (matches the rest of the panel).
async function footageResolveFolder(nativePath) {
  var p = String(nativePath);
  var forms = [
    'file://' + p,
    'file://' + encodeURI(p),
    'file://' + p.split('/').map(function (s) { return encodeURIComponent(s); }).join('/')
  ];
  var lastErr = null;
  for (var i = 0; i < forms.length; i++) {
    try { return await uxpfs.getEntryWithUrl(forms[i]); } catch (e) { lastErr = e; }
  }
  throw lastErr || new Error('cannot resolve folder: ' + p);
}

async function footageEnsureSub(parent, name) {
  try { return await parent.getEntry(name); } catch (e) { return await parent.createFolder(name); }
}

// Save the footage log. Primary: <projectFolder>/99_Pipeline/logs/ (same folder as the
// project). If project.path is empty (unsaved) or that write fails, fall back to the plugin
// data folder so a log ALWAYS exists. The reason is recorded in footageState.lastLogError.
async function saveFootageLog(project) {
  footageState.lastLogError = null;
  var ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  var fname = 'FOOTAGE_' + ts + '.log';
  var report;
  try { report = footageLogger.getReport(); } catch (e) { report = 'log report unavailable'; }

  // Diagnostic: raw project.path + the folder picked via "Select Project Folder".
  var rawPath = '';
  try { rawPath = project && project.path ? String(project.path) : ''; } catch (e) { rawPath = ''; }
  footageState.lastProjectPath = rawPath;
  var sel = (projectState && projectState.folderPath) || '';
  footageLogger.info('project.path="' + rawPath + '" selectedFolder="' + sel + '" name="' + ((project && project.name) || '') + '"');

  // 1. Preferred: <targetFolder>/99_Pipeline/logs/  (picked folder, else project folder)
  var dir = footageTargetFolder(project);
  if (dir) {
    try {
      var root = await footageResolveFolder(dir);
      var pipe = await footageEnsureSub(root, '99_Pipeline');
      var logsFolder = await footageEnsureSub(pipe, 'logs');
      var f = await logsFolder.createFile(fname, { overwrite: true });
      await f.write(report);
      var path = (logsFolder.nativePath || (dir + '/99_Pipeline/logs')) + '/' + fname;
      footageState.lastLogPath = path;
      try { $('btn-footage-log').removeAttribute('disabled'); } catch (e) { /* ignore */ }
      footageLogger.info('Log saved: ' + path);
      return path;
    } catch (e) {
      footageState.lastLogError = 'folder write failed: ' + e.message;
      footageLogger.warn(footageState.lastLogError);
    }
  } else {
    footageState.lastLogError = 'no project folder — Save the project (⌘S) or click "Select Project Folder" at the top';
  }

  // 2. Fallback: plugin data folder (always writable).
  try {
    var dataFolder = await uxpfs.getDataFolder();
    var f2 = await dataFolder.createFile(fname, { overwrite: true });
    await f2.write(report);
    var path2 = (dataFolder.nativePath || 'plugin data folder') + '/' + fname;
    footageState.lastLogPath = path2;
    try { $('btn-footage-log').removeAttribute('disabled'); } catch (e) { /* ignore */ }
    footageLogger.info('Log saved (fallback, plugin data folder): ' + path2);
    return path2;
  } catch (e2) {
    footageState.lastLogError = (footageState.lastLogError || '') + ' | data folder failed: ' + e2.message;
    footageLogger.error('Log save failed entirely: ' + e2.message);
    return null;
  }
}

async function buildFootage() {
  if (footageState.building) { footageLogger.warn('Footage build already in progress'); return; }
  footageState.building = true;
  $('btn-footage-build').setAttribute('disabled', 'true');
  setFootageStatus('Scanning for clips…', 'waiting');
  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No open Premiere project — open one (RYA-Premiere-Project button)');

    const sources = await footageGatherSources(project);
    if (!sources.length) {
      throw new Error('No video found: insert a card (Sony M4ROOT/CLIP, DCIM) or put clips in the project 01_Source/Video');
    }
    sources.sort(function (a, b) { return b.files.length - a.files.length; }); // most clips wins
    const src = sources[0];
    footageState.lastSourceFolder = footageCommonFolder(src.files); // anchor for logs/LUT when project.path is empty
    const applyLut = $('footage-lut') ? $('footage-lut').checked : true;
    // Project name: user field, else the PROJECT FOLDER name, else the card label.
    var typedName = $('footage-name') ? footageHyphenate($('footage-name').value) : '';
    var folderName = footageHyphenate(await footageProjectFolderName(project));
    var projName = typedName || folderName || src.label;

    setFootageStatus('Building: ' + projName + ' (' + src.files.length + ' clips)…', 'waiting');
    footageLogger.info('=== FOOTAGE REVIEW v' + FOOTAGE_REVIEW_VERSION + ': ' + projName + ' — ' + src.files.length + ' clips from ' + src.label + ', LUT=' + applyLut + ' ===');
    if (sources.length > 1) {
      footageLogger.info('Sources: ' + sources.map(function (s) { return s.label + '(' + s.files.length + ')'; }).join(', ') + ' → using ' + src.label);
    }
    try { await project.save(); } catch (e) { /* ignore */ }

    var projectFolder = footageTargetFolder(project);
    const result = await buildFootageReview(project, src.files, { name: projName, applyLut: applyLut, projectFolder: projectFolder }, footageLogger);

    var lutCount = (result.lutsCopied && result.lutsCopied.length) || 0;
    var lutMsg = (applyLut && lutCount)
      ? lutCount + ' LUT(s) copied to ' + (result.lutFolder || 'project') + ' — add an Adjustment Layer over the clips and drop a LUT onto it'
      : applyLut ? 'LUT: copy skipped (project folder not found)'
      : 'LUT: off';
    var allOk = (result.placed === result.total);
    var logPath = await saveFootageLog(project);
    setFootageStatus('Done: ' + result.srcSeqName + ' — ' + result.placed + '/' + result.total + ' clips', allOk ? 'ready' : 'warning');
    setFootageValidation(
      '<div class="val-line"><b>' + escapeHtml(projName) + '</b> (' + escapeHtml(src.kind) + ' · ' + escapeHtml(src.label) + ') → ' + result.placed + '/' + result.total + ' clips on the timeline</div>' +
      '<div class="val-line">Sequence: <b>' + escapeHtml(result.srcSeqName) + '</b></div>' +
      '<div class="val-line" style="opacity:.7">Project file: ' + escapeHtml(footageState.lastProjectPath || projectFolder || '(empty — project not saved)') + '</div>' +
      '<div class="val-line">' + escapeHtml(lutMsg) + '</div>' +
      (sources.length > 1 ? '<div class="val-line">Also found: ' + escapeHtml(sources.slice(1).map(function (s) { return s.label + '(' + s.files.length + ')'; }).join(', ')) + '</div>' : '') +
      (logPath
        ? '<div class="val-line" style="opacity:.7">Log: ' + escapeHtml(logPath) + (footageState.lastLogError ? ' — ' + escapeHtml(footageState.lastLogError) : '') + '</div>'
        : '<div class="val-line" style="color:#e88">Log NOT saved: ' + escapeHtml(footageState.lastLogError || 'unknown') + '</div>'));
    footageLogger.info('=== FOOTAGE REVIEW DONE: ' + result.srcSeqName + ' (' + result.placed + '/' + result.total + ', luts=' + lutCount + ') ===');
  } catch (err) {
    setFootageStatus('Error: ' + err.message, 'error', err);
    footageLogger.error('Footage review failed: ' + err.message, err);
    try { await saveFootageLog(await ppro.Project.getActiveProject()); } catch (e) { /* ignore */ }
  } finally {
    footageState.building = false;
    $('btn-footage-build').removeAttribute('disabled');
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
    try { await project.save(); assemblyLogger.info('Project saved'); } catch (e) { assemblyLogger.warn('Backup save before build failed: ' + (e && e.message)); }
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
      try { await project.openSequence(result.sequence.guid || result.sequence); } catch (e) { assemblyLogger.debug('openSequence failed (non-fatal): ' + (e && e.message)); }
    }
    try { await project.save(); } catch (e) { assemblyLogger.warn('Post-build project save failed: ' + (e && e.message)); }

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

    // Derive project root: strip /00_Setup/... from filePath, fallback to projectState.folderPath
    var asmProjectRoot = null;
    if (assemblyState.filePath) {
      // Brief can be in 00_Setup/, 00_Setup/02_Assembly/, or 00_Setup/03_Pre-Edit/ — strip from /00_Setup/ onwards
      asmProjectRoot = assemblyState.filePath.replace(/[/\\]00_Setup[/\\].*$/, '');
    } else if (projectState.folderPath) {
      asmProjectRoot = projectState.folderPath;
    }
    if (asmProjectRoot) {
      assemblyLogger.info('SRT projectRoot: ' + asmProjectRoot);
    }

    var asmSuffix = '2_Assembly' + (assemblyState.briefVersion ? '_v' + assemblyState.briefVersion : '');

    if (useSegsForSrt.length > 0 && asmProjectRoot) {
      try {
        // Ensure Transcription subdirs exist
        var transcriptionEntry = await uxpfs.getEntryWithUrl('file://' + asmProjectRoot + '/01_Source/Transcription');
        var transcriptsFolderEntry = await ensureSubfolder(transcriptionEntry, 'transcripts', assemblyLogger);
        var captionsFolderEntry = await ensureSubfolder(transcriptionEntry, 'captions', assemblyLogger);

        // 1. Transcript SRT (full text per segment, for word-based editing)
        var transcriptSrtContent = generateTranscriptSrt(useSegsForSrt);
        if (transcriptSrtContent) {
          var trFileName = projectCode + '_' + asmSuffix + '_transcript.srt';
          var trFile = await transcriptsFolderEntry.createFile(trFileName, { overwrite: true });
          await trFile.write("\uFEFF" + transcriptSrtContent);
          assemblyLogger.info('Transcript SRT written: Transcription/transcripts/' + trFileName);
        }

        // 2. Captions SRT (word-grouped, 2-line blocks for on-screen reading)
        // Only generate if Python pipeline hasn't already created one (Python has better word-level timing)
        var captionsFileName = projectCode + '_' + asmSuffix + '_captions.srt';
        var captionsDirPath = asmProjectRoot + '/01_Source/Transcription/captions';
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
            await capFile.write("\uFEFF" + captionsSrtContent);
            assemblyLogger.info('Captions SRT generated: Transcription/captions/' + captionsFileName);
          }
        }
      } catch (srtWriteErr) {
        assemblyLogger.warn('SRT write failed (non-fatal): ' + srtWriteErr.message);
      }
    } else {
      assemblyLogger.warn('SRT skipped: segs=' + useSegsForSrt.length + ' filePath=' + !!assemblyState.filePath + ' folderPath=' + !!projectState.folderPath);
    }

    // Import both SRTs to 02_Transcripts bin
    var asmImportPath = assemblyState.filePath || (asmProjectRoot ? asmProjectRoot + '/00_Setup' : null);
    await importCaptionsSrt(project, asmImportPath, projectCode, asmSuffix, 'Assembly Captions', assemblyLogger);
    await importCaptionsSrt(project, asmImportPath, projectCode, asmSuffix, 'Assembly Transcript', assemblyLogger, 'transcript');
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

    setAssemblyStatus('Assembly built (' + result.clipCount + ' clips). Building Deleted Scene...', 'ready');

    await saveAssemblyLogs(project, clipMap, result);

    // Auto-build Deleted Scene after Assembly
    assemblyLogger.info('=== Auto-building Deleted Scene ===');
    try {
      await buildDeletedScene();
      assemblyLogger.info('Deleted Scene auto-build complete');
    } catch (dsErr) {
      assemblyLogger.warn('Deleted Scene auto-build failed (non-fatal): ' + dsErr.message);
    }

    setAssemblyStatus('Assembly + Deleted Scene built (' + result.clipCount + ' clips)', 'ready');

  } catch (err) {
    assemblyLogger.error('ASSEMBLY BUILD FAILED: ' + err.message, err);
    setAssemblyStatus('Build failed: ' + err.message, 'error', err);
    try { await saveAssemblyLogs(await ppro.Project.getActiveProject(), clipMap, result); } catch (e) { assemblyLogger.debug('saveAssemblyLogs after failure: ' + (e && e.message)); }
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
 * @param {string} suffix - SRT file suffix: "2_Assembly", "3_DeletedScene", "4_ScreenCues"
 * @param {string} label - Human label for logs
 * @param {Object} logger - Logger instance
 * @param {string} [srtType='captions'] - Type suffix: 'captions', 'transcript'
 */
async function importCaptionsSrt(project, briefPath, projectName, suffix, label, logger, srtType) {
  if (!briefPath || !projectName) {
    logger.debug('SRT import skipped: no brief path or project name');
    return;
  }

  // briefPath is in 00_Setup/ — derive project root from it
  const briefDir = briefPath.replace(/[/\\][^/\\]+$/, '');
  const projectRoot = briefDir.replace(/[/\\]00_Setup([/\\].*)?$/, '');
  const srtFileName = projectName + '_' + suffix + '_' + (srtType || 'captions') + '.srt';
  // SRTs are in 01_Source/Transcription/captions/ or 01_Source/Transcription/transcripts/
  var typeLabel = (srtType || 'captions');
  var srtSubdir = (typeLabel === 'transcript') ? 'transcripts' : 'captions';
  var srtDir = projectRoot + '/01_Source/Transcription/' + srtSubdir;
  var srtCandidates = [
    srtDir + '/' + srtFileName,
    briefDir + '/' + srtFileName,  // legacy: next to brief
  ];

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
 * Import SRT file directly by absolute path into 01_Transcripts/{projectCode}_{suffix}/ bin.
 * Bypasses importCaptionsSrt() path derivation — used by Review where paths come from pipeline result.
 */
async function importSrtDirect(project, srtPath, projectCode, suffix, label, logger) {
  if (!srtPath) {
    logger.debug(label + ': no SRT path provided, skipping');
    return;
  }

  // Check file exists
  try {
    await uxpfs.getEntryWithUrl('file://' + srtPath);
  } catch (e) {
    logger.info(label + ': SRT not found at ' + srtPath);
    return;
  }

  var srtFileName = srtPath.split('/').pop();
  logger.info('=== Import ' + label + ' (direct) ===');
  logger.info('Path: ' + srtPath);

  // Find or create 01_Transcripts bin
  var transcriptsBin = null;
  try {
    var rootItem = await project.getRootItem();
    var allItems = await rootItem.getItems();
    for (var i = 0; i < allItems.length; i++) {
      if (allItems[i].name === BIN_NAMES.TRANSCRIPTS) {
        transcriptsBin = ppro.FolderItem.cast(allItems[i]);
        break;
      }
    }
    // Create 01_Transcripts if missing
    if (!transcriptsBin) {
      logger.info('Creating ' + BIN_NAMES.TRANSCRIPTS + ' bin');
      project.lockedAccess(function() {
        project.executeTransaction(function(ca) {
          ca.addAction(ppro.FolderItem.createAddItemAction(BIN_NAMES.TRANSCRIPTS));
        }, 'Create ' + BIN_NAMES.TRANSCRIPTS);
      });
      allItems = await rootItem.getItems();
      for (var i2 = 0; i2 < allItems.length; i2++) {
        if (allItems[i2].name === BIN_NAMES.TRANSCRIPTS) {
          transcriptsBin = ppro.FolderItem.cast(allItems[i2]);
          break;
        }
      }
      if (transcriptsBin) logger.info(BIN_NAMES.TRANSCRIPTS + ' bin created');
    }
  } catch (e) {
    logger.debug('Cannot find/create 01_Transcripts bin: ' + e.message);
  }

  // Create/find sub-bin
  var targetBin = transcriptsBin;
  if (transcriptsBin && suffix) {
    var subBinName = projectCode + '_' + suffix;
    try {
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
        existingItems = await transcriptsBin.getItems();
        var createdOk = false;
        for (var ni = 0; ni < existingItems.length; ni++) {
          if (existingItems[ni].name === subBinName) {
            targetBin = ppro.FolderItem.cast(existingItems[ni]) || existingItems[ni];
            createdOk = true;
            break;
          }
        }
        if (createdOk) {
          logger.info('Created bin: 01_Transcripts/' + subBinName);
        } else {
          logger.warn('Sub-bin ' + subBinName + ' not found after create — SRT will import to 01_Transcripts');
        }
      }
    } catch (binErr) {
      logger.debug('Sub-bin creation failed: ' + binErr.message);
    }
  }

  // Import
  try {
    await project.importFiles([srtPath], true, targetBin || null, false);
    logger.info(label + ' imported: ' + srtFileName + ' → 01_Transcripts/' + (suffix ? projectCode + '_' + suffix : ''));
  } catch (err) {
    logger.warn(label + ' import failed (non-fatal): ' + err.message);
  }
}


/**
 * Export markers from active sequence as JSON.
 *
 * Reads marker names and positions from the current sequence and writes
 * to 00_Setup/{CODE}_{suffix}_markers.json. Marker names carry editor notes
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
 * Writes to 00_Setup/02_Assembly/{seq}_v{N}_out.json + ~/Downloads/.
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
        if (!m0comment && m0.getComments) try { m0comment = m0.getComments(); } catch(e) { /* introspection only; getComments optional on this build */ }
        if (!m0comment) m0comment = m0.comment || '';
        assemblyLogger.debug('Marker[0] name=' + m0.name + ' type=' + m0.type + ' comments="' + m0comment + '"' +
          ' | .comments=' + JSON.stringify(m0.comments) + ' .comment=' + JSON.stringify(m0.comment) +
          ' hasGetComments=' + (typeof m0.getComments === 'function'));
      } catch (e) { assemblyLogger.debug('Marker introspection failed: ' + e.message); }

      for (var mi = 0; mi < rawMarkers.length; mi++) {
        var rm = rawMarkers[mi];
        // Get start time — try getStart() then startTime property
        var startTime = null;
        try { startTime = rm.getStart(); } catch (e) { /* fallback to .startTime below handles it */ }
        if (!startTime) try { startTime = rm.startTime; } catch (e) { assemblyLogger.debug('Marker ' + mi + ' start unreadable: ' + (e && e.message)); }
        var posSec = startTime ? Math.round(startTime.seconds * 100) / 100 : 0;

        var entry = {
          name: rm.name || '',
          position_sec: posSec,
        };

        // Get duration — try getDuration() then duration property
        var dur = null;
        try { dur = rm.getDuration(); } catch (e) { /* fallback to .duration below handles it */ }
        if (!dur) try { dur = rm.duration; } catch (e) { assemblyLogger.debug('Marker ' + mi + ' duration unreadable: ' + (e && e.message)); }
        if (dur && dur.seconds > 0) {
          entry.duration_sec = Math.round(dur.seconds * 100) / 100;
          entry.is_chapter = true;
        }

        // Get comments — try property, then getComments(), then comment (singular)
        var commentText = rm.comments || '';
        if (!commentText) try { commentText = rm.getComments ? rm.getComments() : ''; } catch (e) { /* fallback to .comment below handles it */ }
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
    var deletedSceneMarkers = [];
    for (var ci = 0; ci < markers.length; ci++) {
      var mName = markers[ci].name || '';
      var mCom = markers[ci].comment || '';
      if (mCom.startsWith('/')) {
        assemblyMarkers.push(markers[ci]);
      } else if (mName.indexOf('[CUT]') === 0 || mName.indexOf('[ALT]') === 0 || mName.indexOf('[SKIP]') === 0) {
        deletedSceneMarkers.push(markers[ci]);
      } else if (mName.indexOf('Source:') === 0) {
        assemblyMarkers.push(markers[ci]);
        deletedSceneMarkers.push(markers[ci]);
      } else {
        assemblyMarkers.push(markers[ci]);
      }
    }
    var assemblyChapters = assemblyMarkers.filter(function(m) { return m.is_chapter && (m.name || '').indexOf('Source:') !== 0; });

    assemblyLogger.info('Assembly: ' + assemblyMarkers.length + ' markers (' + assemblyChapters.length + ' chapters)');
    assemblyLogger.info('Deleted Scene: ' + deletedSceneMarkers.length + ' markers');

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
      deletedScene: {
        markers_count: deletedSceneMarkers.length,
        markers: deletedSceneMarkers,
      },
    };

    // Step 7: Read V1 TrackItems — real timeline clips
    setAssemblyStatus('Reading timeline clips...', 'waiting');
    var timelineClips = [];
    try {
      var v1Track = await seq.getVideoTrack(0);
      var trackItems = null;
      try { trackItems = v1Track.getTrackItems(1, false); } catch (ex) { /* signature varies by build; fallback below handles it */ }
      if (!trackItems) try { trackItems = v1Track.getTrackItems(); } catch (ex) { assemblyLogger.warn('Could not read V1 TrackItems (getTrackItems): ' + (ex && ex.message)); }
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
      var txPath = projectState.folderPath + '/01_Source/Transcription/' + projectState.projectName + '_transcript_assembly.json';
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
          } catch (pe) { /* malformed tc stays 0/0 so the segment never matches; non-fatal */ }
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

    // Step 8: Find next version and write to 00_Setup/02_Assembly/
    setAssemblyStatus('Writing files...', 'waiting');
    var assemblyDir = projectState.folderPath + '/00_Setup/02_Assembly';
    var assemblyEntry;
    try {
      assemblyEntry = await uxpfs.getEntryWithUrl('file://' + assemblyDir);
    } catch (e) {
      var setupEntry = await uxpfs.getEntryWithUrl('file://' + projectState.folderPath + '/00_Setup');
      assemblyEntry = await ensureSubfolder(setupEntry, '02_Assembly', assemblyLogger);
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
      tc = timelineClips[bsi3];
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

    // Write to 00_Setup/02_Assembly/
    var outFile = await assemblyEntry.createFile(fileName, { overwrite: true });
    await outFile.write(jsonContent);
    assemblyLogger.info('Written: 00_Setup/02_Assembly/' + fileName);

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
      assemblyLogger.info('Written: 00_Setup/02_Assembly/' + htmlName);

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
    assemblyLogger.error('Marker export failed: ' + err.message, err);
    setAssemblyStatus('Export failed: ' + err.message, 'error', err);
  }

  $('btn-export-markers').removeAttribute('disabled');
  $('btn-debug-export').removeAttribute('disabled');
}

/**
 * Debug Export — separate button for comparing Premiere actual vs brief.
 * Reads V1 clips from active sequence, matches with brief segments,
 * reads Claude4_assembly.json for word-level comparison.
 * Writes {CODE}_debug.json to 02_Assembly/ folder.
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
    var fps = assemblyState.projectSettings ? (assemblyState.projectSettings.fps || 29.97) : 29.97;

    assemblyLogger.info('Sequence: ' + seqName + ', fps=' + fps);

    // Read V1 clips
    var v1Track = await seq.getVideoTrack(0);
    var trackItems = null;
    try { trackItems = v1Track.getTrackItems(1, false); } catch (ex) { /* signature varies by build; fallback below handles it */ }
    if (!trackItems) try { trackItems = v1Track.getTrackItems(); } catch (ex) { assemblyLogger.debug('getTrackItems failed on V1: ' + (ex && ex.message)); }

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
      var c4Path = projectState.folderPath + '/00_Setup/' +
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
        if (Math.abs(d['in']) > 5 || Math.abs(d.out) > 35) problemClips++; // tc_in >5ms or tc_out >1frame = problem
      }
    }

    // Get available audio effects (for research/auto-apply)
    var audioEffectNames = [];
    try {
      audioEffectNames = await ppro.AudioFilterFactory.getDisplayNames();
      assemblyLogger.info('Audio effects available: ' + audioEffectNames.length);
      // Log effects that match channel fill / normalize patterns
      var relevant = audioEffectNames.filter(function(n) {
        var nl = n.toLowerCase();
        return nl.indexOf('fill') >= 0 || nl.indexOf('channel') >= 0 ||
               nl.indexOf('loud') >= 0 || nl.indexOf('normal') >= 0 ||
               nl.indexOf('gain') >= 0 || nl.indexOf('vocal') >= 0 ||
               nl.indexOf('compressor') >= 0 || nl.indexOf('limit') >= 0 ||
               nl.indexOf('mono') >= 0 || nl.indexOf('stereo') >= 0 ||
               nl.indexOf('denoise') >= 0 || nl.indexOf('noise') >= 0;
      });
      assemblyLogger.info('Relevant audio effects: ' + relevant.join(', '));
    } catch (aeErr) {
      assemblyLogger.warn('Cannot get audio effect names: ' + aeErr.message);
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
      },
      audio_effects: {
        total: audioEffectNames.length,
        all: audioEffectNames,
        relevant: audioEffectNames.filter(function(n) {
          var nl = n.toLowerCase();
          return nl.indexOf('fill') >= 0 || nl.indexOf('channel') >= 0 ||
                 nl.indexOf('loud') >= 0 || nl.indexOf('normal') >= 0 ||
                 nl.indexOf('gain') >= 0 || nl.indexOf('vocal') >= 0 ||
                 nl.indexOf('mono') >= 0 || nl.indexOf('stereo') >= 0 ||
                 nl.indexOf('noise') >= 0 || nl.indexOf('compressor') >= 0;
        })
      }
    };

    // Write to 02_Assembly/
    var assemblyDir = projectState.folderPath + '/00_Setup/02_Assembly';
    var assemblyEntry;
    try {
      assemblyEntry = await uxpfs.getEntryWithUrl('file://' + assemblyDir);
    } catch (e) {
      var setupEntry = await uxpfs.getEntryWithUrl('file://' + projectState.folderPath + '/00_Setup');
      assemblyEntry = await ensureSubfolder(setupEntry, '02_Assembly', assemblyLogger);
    }

    var debugFileName = seqName.replace(/[^a-zA-Z0-9_-]/g, '_') + '_debug.json';
    var debugFile = await assemblyEntry.createFile(debugFileName, { overwrite: true });
    await debugFile.write(JSON.stringify(output, null, 2), { format: require('uxp').storage.formats.utf8 });
    assemblyLogger.info('Debug export → ' + debugFileName);

    var status = problemClips > 0
      ? problemClips + ' clips with Δ>10ms! Check ' + debugFileName
      : 'All clips Δ<10ms ✅ → ' + debugFileName;
    setAssemblyStatus('Debug: ' + status, problemClips > 0 ? 'error' : 'ready');

  } catch (err) {
    assemblyLogger.error('Debug export failed: ' + err.message, err);
    setAssemblyStatus('Debug failed: ' + err.message, 'error', err);
  }

  $('btn-debug-export').removeAttribute('disabled');
}


// ─────────────────────────────────────────────────────────────────────────────
// Chapter markers → ACTIVE sequence (no rebuild)
// ingest.markers[scene] = [{ offset_sec, duration_sec?, name, comment?, color? }]
// Lets a scene timeline that already exists get its chapter map without being
// rebuilt from scratch — the same list the builders place on a fresh ingest.
// ─────────────────────────────────────────────────────────────────────────────

async function applyChapterMarkersToActive() {
  if (!ingestState.data) { setIngestStatus('Load ingest JSON first', 'error'); return; }
  var project = await ppro.Project.getActiveProject();
  if (!project) { setIngestStatus('No active project', 'error'); return; }

  var found = await resolveActiveScene(project);   // reports its own errors
  if (!found) return;

  var all = ingestState.data.markers || {};
  var list = all[found.scene];
  if (!list || !list.length) {
    var have = Object.keys(all);
    setIngestStatus('No chapter markers for "' + found.scene + '"' +
      (have.length ? ' (ingest has: ' + have.join(', ') + ')' : ' — ingest.markers is empty'), 'error');
    return;
  }

  ingestLogger.info('=== Chapter markers → ' + found.seq.name + ' (' + list.length + ') ===');
  setIngestStatus('Replacing chapter markers (' + list.length + ')...', 'waiting');
  try {
    // replace (default): previously generated chapter markers are swept first, so
    // pressing this twice re-syncs the sequence instead of doubling every marker.
    var added = await addSceneMarkers(project, found.seq, list, ingestLogger);
    setIngestStatus('Chapters: ' + added + '/' + list.length + ' → ' + found.seq.name +
      ' (old ones replaced)', added ? 'ready' : 'error');
  } catch (err) {
    ingestLogger.error('Chapter markers failed: ' + err.message);
    setIngestStatus('Chapter markers failed: ' + err.message, 'error', err);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// PARTS PICKER — список part-JSON с галочками, как «Sequences to build» в Ingest.
// Роман: «в parts и review должно быть как в ingest — выбор галочкой что собираем».
// Раньше панель молча брала САМЫЙ СВЕЖИЙ файл, и собрать второй вариант можно было
// только через Load вручную; теперь видно всё, что лежит в 02_Assembly/parts/.
// ─────────────────────────────────────────────────────────────────────────────

// Два списка на одном движке: в Review — сборки поверх рендера/мастера (у них есть
// part.base_clip), в Parts — всё остальное (сцены, подборки). Так вкладка Review больше
// НЕ угадывает файл скорингом (из-за него она стабильно брала не тот JSON) — выбор явный.
/** «01:00» для сегодняшних файлов, «20.08 23:41» для остальных — чтобы свежесть читалась. */
function fmtWhen(ms) {
  if (!ms) return '';
  var d = new Date(ms), now = new Date();
  var hh = ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
  var sameDay = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()
    && d.getDate() === now.getDate();
  if (sameDay) return hh;
  return ('0' + d.getDate()).slice(-2) + '.' + ('0' + (d.getMonth() + 1)).slice(-2) + ' ' + hh;
}

const PICKERS = {
  parts: { panel: 'parts-pick', list: 'parts-pick-list', btn: 'btn-parts-pick-build',
           status: function (m, s) { setPartsStatus(m, s); },
           want: function (isReview) { return !isReview; }, items: [] },
  review: { panel: 'review-pick', list: 'review-pick-list', btn: 'btn-review-pick-build',
            status: function (m, s) { setReviewStatus(m, s); },
            want: function (isReview) { return isReview; }, items: [] },
};

async function refreshPick(kind) {
  var P = PICKERS[kind];
  var panel = $(P.panel), list = $(P.list);
  if (!projectState.folderPath) { panel.style.display = 'none'; return; }

  // Review-сборки живут в 05_Review (Роман 07.09: «всё должно быть в review»),
  // прочие части — по-прежнему в 02_Assembly/parts. Сканируем оба; вкладку решает
  // base_clip внутри JSON (ниже), а не каталог.
  var scanDirs = [
    { dir: projectState.folderPath + '/00_Setup/05_Review', re: /_review_.*\.json$/i },
    { dir: projectState.folderPath + '/00_Setup/02_Assembly/parts', re: /_(part|review)_.*\.json$/i },
  ];
  var files = [];
  var seenNames = {};
  for (var sd = 0; sd < scanDirs.length; sd++) {
    try {
      var dEntry = await uxpfs.getEntryWithUrl('file://' + scanDirs[sd].dir);
      var entries = await dEntry.getEntries();
      for (var i = 0; i < entries.length; i++) {
        if (entries[i].isFile && scanDirs[sd].re.test(entries[i].name) && !seenNames[entries[i].name]) {
          seenNames[entries[i].name] = 1;
          files.push(entries[i]);
        }
      }
    } catch (e) { assemblyLogger.debug(kind + ' pick (' + scanDirs[sd].dir + '): ' + e.message); }
  }
  var dir = scanDirs[1].dir;   // фолбэк для nativePath ниже

  var existing = {};
  try {
    (await listProjectSequences(await ppro.Project.getActiveProject(), assemblyLogger))
      .forEach(function (s) { existing[s.name] = true; });
  } catch (e) { /* проект может быть не открыт — просто без бейджей */ }

  P.items = [];
  for (var f = 0; f < files.length; f++) {
    try {
      var data = JSON.parse(await files[f].read());
      var head = (data.parts && data.parts.length) ? data.parts[0].part : data.part;
      var segs = (data.parts && data.parts.length) ? data.parts[0].segments : data.segments;
      if (!head) continue;
      var isReview = !!head.base_clip;
      if (!P.want(isReview)) continue;
      var mtime = 0, ctime = 0;
      try {
        var meta = await files[f].getMetadata();
        mtime = meta && meta.dateModified ? new Date(meta.dateModified).getTime() : 0;
        ctime = meta && meta.dateCreated ? new Date(meta.dateCreated).getTime() : 0;
      } catch (eMt) { /* без времени — просто уедет вниз списка */ }
      // дата создания: авторитетно из JSON (part.created, пишут генераторы), иначе FS
      if (head.created) {
        var pc = Date.parse(head.created);
        if (!isNaN(pc)) ctime = pc;
      }
      var seqName = head.sequence_name || head.name || files[f].name;
      var isBuilt = !!existing[seqName];
      if (!isBuilt) {                       // auto_version строит "<name>_vN"
        for (var k in existing) {
          if (k.indexOf(seqName + '_v') === 0) { isBuilt = true; break; }
        }
      }
      P.items.push({
        name: files[f].name, path: files[f].nativePath || (dir + '/' + files[f].name),
        partName: head.name || '?', seqName: seqName, base: head.base_clip || '',
        model: head.build_model || '', segments: (segs || []).length,
        baseSegs: (head.base_segments || []).length,
        markers: (head.chapter_markers || []).length, built: isBuilt, mtime: mtime,
        created: ctime,
      });
    } catch (e) { assemblyLogger.debug(kind + ' pick read ' + files[f].name + ': ' + e.message); }
  }
  if (!P.items.length) { panel.style.display = 'none'; list.innerHTML = ''; return; }
  // свежие сверху — по этому списку Роман и решает, что собирать
  P.items.sort(function (a, b) { return (b.mtime - a.mtime) || a.name.localeCompare(b.name); });
  var newest = P.items.length ? P.items[0].mtime : 0;

  list.innerHTML = P.items.map(function (p, i) {
    // review_cut: rebuilt V1 (base_segments) + inserts — shown as "31+23 seg"
    var segTxt = (p.baseSegs ? p.baseSegs + '+' + p.segments : p.segments) + ' seg';
    var meta = (p.created ? 'created ' + fmtWhen(p.created) + ' · ' : '') +
      segTxt + (p.markers ? ' · ' + p.markers + ' parts' : '') +
      (p.base ? ' · ' + escapeHtml(p.base) : '');
    var isFresh = p.mtime && p.mtime === newest;
    // Two-line row: head (checkbox + name + badge) / sub (dates + meta) — keeps the
    // layout intact at any panel width instead of one overflowing nowrap line.
    return '<div class="scene-row">' +
      '<div class="scene-head">' +
      '<label class="scene-pick">' +
      '<input type="checkbox" class="' + kind + '-pick-cb" value="' + i + '"' + (p.built ? '' : ' checked') + '>' +
      '<span class="scene-name">' + escapeHtml(p.partName) + '</span>' +
      '</label>' +
      '<span class="scene-badge' + (p.built ? ' built' : '') + '">' +
      (p.built ? 'built ✓' : 'new') + '</span>' +
      '</div>' +
      '<div class="scene-sub">' +
      '<span class="scene-when' + (isFresh ? ' fresh' : '') + '">mod ' + fmtWhen(p.mtime) +
      (isFresh ? ' ← newest' : '') + '</span>' +
      '<span class="scene-meta">' + meta + '</span>' +
      '</div>' +
      '</div>';
  }).join('');
  panel.style.display = 'block';
  $(P.btn).removeAttribute('disabled');
  assemblyLogger.info(kind + ' pick: ' + P.items.length + ' part JSON(s)');
}

function setPickChecks(kind, mode) {
  Array.prototype.slice.call(document.querySelectorAll('.' + kind + '-pick-cb')).forEach(function (cb) {
    var row = cb.closest('.scene-row');
    var isBuilt = row && row.querySelector('.scene-badge.built');
    if (mode === 'all') cb.checked = true;
    else if (mode === 'none') cb.checked = false;
    else cb.checked = !isBuilt;
  });
}

/** Build every ticked JSON, one after another. One failure never stops the rest. */
async function buildPicked(kind) {
  var P = PICKERS[kind];
  var picked = Array.prototype.slice.call(document.querySelectorAll('.' + kind + '-pick-cb'))
    .filter(function (cb) { return cb.checked; })
    .map(function (cb) { return P.items[parseInt(cb.value, 10)]; })
    .filter(Boolean);
  if (!picked.length) { P.status('Nothing ticked', 'error'); return; }

  var okN = 0, madeAll = [], failed = [];
  for (var i = 0; i < picked.length; i++) {
    var p = picked[i];
    P.status('Building ' + (i + 1) + '/' + picked.length + ': ' + p.partName + '…', 'waiting');
    try {
      var entry = await uxpfs.getEntryWithUrl('file://' + p.path);
      var data = JSON.parse(await entry.read());
      var bundle = (data.parts && data.parts.length) ? data.parts
        : [{ part: data.part, segments: data.segments }];
      partsState.bundle = (data.parts && data.parts.length) ? data.parts : null;
      partsState.part = bundle[0].part;
      partsState.segments = bundle[0].segments;
      partsState.filePath = p.path;
      var res = await buildParts(bundle);
      if (res && res.ok) { okN++; madeAll = madeAll.concat(res.builtNames || []); }
      else failed.push(p.partName + ' (' + ((res && res.error) || 'failed') + ')');
    } catch (e) {
      failed.push(p.partName + ' (' + (e && e.message ? e.message : e) + ')');
      assemblyLogger.error('Build ' + p.partName + ': ' + (e && e.message));
    }
  }
  var msg = 'Built ' + okN + '/' + picked.length + (madeAll.length ? ' → ' + madeAll.join(', ') : '');
  if (failed.length) msg += ' · failed: ' + failed.join('; ');
  P.status(msg, okN ? 'ready' : 'error');
  assemblyLogger.info(kind + ' pick build: ' + msg);
  await refreshPick(kind);
}

// ─────────────────────────────────────────────────────────────────────────────
// REVIEW NOTES — marker @ playhead + queued JSON row for the notes Sheet.
// Панель делает МИНИМУМ: маркер на активной секвенции + файл в
// {project}/00_Setup/05_Review/notes/. Остальное (v1-TC, выдержка транскрипта,
// пуш в Google Sheet, подбор материала) — notes_sync.py + Claude локально.
// Имя маркера «RS#hhmmss» НЕ матчится GENERATED_MARKER_RE — chapter-ресинк его не сметёт.
// ─────────────────────────────────────────────────────────────────────────────

async function notesDir() {
  if (!projectState.folderPath) throw new Error('No project folder');
  var revDir = projectState.folderPath + '/00_Setup/05_Review';
  try {
    return await uxpfs.getEntryWithUrl('file://' + revDir + '/notes');
  } catch (eD) {
    var parent = await uxpfs.getEntryWithUrl('file://' + revDir);
    return await parent.createFolder('notes');
  }
}

async function readNotes(dEntry) {
  var out = [];
  var entries = await dEntry.getEntries();
  for (var i = 0; i < entries.length; i++) {
    var nm = entries[i].name;
    if (entries[i].isFile && /^(note_\d+|RS_\d+)\.json$/.test(nm)) {
      try { out.push(JSON.parse(await entries[i].read())); } catch (e) { assemblyLogger.debug('Review note ' + nm + ' unreadable: ' + (e && e.message)); }
    }
  }
  out.sort(function (a, b) { return (a.ts || '').localeCompare(b.ts || ''); });
  return out;
}

async function notesSheetBase(dEntry) {
  // notes_sync.py пишет sheet_link.txt (…edit#gid=N) — без него ссылки просто нет
  try {
    var entries = await dEntry.getEntries();
    for (var i = 0; i < entries.length; i++) {
      if (entries[i].isFile && entries[i].name === 'sheet_link.txt') {
        return (await entries[i].read()).trim();
      }
    }
  } catch (e) { /* sheet_link.txt is optional; no link is fine */ }
  return null;
}

async function copyToClipboard(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.setContent) {
      await navigator.clipboard.setContent({ 'text/plain': text });
      return true;
    }
  } catch (e) { /* fallback to writeText below handles it */ }
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (e) { assemblyLogger.warn('Clipboard unavailable: ' + (e && e.message)); }
  return false;
}

function noteLink(base, rowIndex) {
  // строка листа: 1 шапка + N заметок в хронологии (push держит тот же порядок)
  return base ? base + '&range=A' + rowIndex : null;
}

async function addReviewNote() {
  var st = $('note-status');
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere project');
    var seq = await project.getActiveSequence();
    if (!seq) throw new Error('No active sequence');
    var sec = null;
    try {
      var tt = seq.getPlayerPosition ? await seq.getPlayerPosition() : null;
      if (tt && typeof tt.seconds === 'number') sec = tt.seconds;
      else if (tt && typeof tt.seconds === 'function') sec = tt.seconds();
      else if (tt && tt.ticks !== undefined) sec = Number(tt.ticks) / 254016000000;
    } catch (eP) { assemblyLogger.debug('getPlayerPosition: ' + eP.message); }
    if (sec === null || isNaN(sec)) throw new Error('Player position unavailable on this build (getPlayerPosition)');

    var dEntry = await notesDir();
    var existing = await readNotes(dEntry);
    var maxN = 0;
    existing.forEach(function (n) {
      var m = /^(\d+)$/.exec(String(n.id || ''));
      if (m) maxN = Math.max(maxN, parseInt(m[1], 10));
    });
    var id = ('00' + (maxN + 1)).slice(-3);          // сквозная нумерация: 001, 002…
    var mm = Math.floor(sec / 60), ss = Math.floor(sec % 60);
    function p2(n) { return ('0' + n).slice(-2); }
    var comment = (($('note-comment') && $('note-comment').value) || '').trim();

    // Magenta = «специальный цвет» заметок: главы Green/Red/Yellow, S{NN} дефолтные —
    // на линейке маркеров magenta читается сразу. no_chapter_type: остаётся Comment.
    await addSceneMarkers(project, seq, [{
      offset_sec: sec, name: id, comment: comment,
      color: 'Magenta', no_chapter_type: true,
    }], assemblyLogger, { replace: false });

    var f = await dEntry.createFile('note_' + id + '.json', { overwrite: true });
    await f.write(JSON.stringify({
      id: id, ts: new Date().toISOString(), sequence: seq.name,
      tc_sec: Math.round(sec * 100) / 100, tc: mm + ':' + p2(ss),
      comment: comment, marker: id,
    }, null, 1));
    if ($('note-comment')) $('note-comment').value = '';

    var base = await notesSheetBase(dEntry);
    var link = noteLink(base, existing.length + 2);   // после записи заметок N+1, +1 шапка
    var copied = false;
    if (link) copied = await copyToClipboard(link);
    else copied = await copyToClipboard(id + ' @ ' + mm + ':' + p2(ss) + (comment ? ' · ' + comment : ''));

    st.textContent = '📌 ' + id + ' @ ' + mm + ':' + p2(ss) + ' — magenta marker' +
      (copied ? (link ? ' · Sheet link copied' : ' · text copied (the Sheet link appears after the first push)') : '') +
      (comment ? '' : ' · no comment yet — add in the Sheet');
    assemblyLogger.info('Review note ' + id + ' @ ' + sec.toFixed(2) + 's on "' + seq.name + '"' +
      (copied ? ' (link copied)' : ''));
  } catch (err) {
    if (st) st.textContent = 'Note failed: ' + err.message;
    assemblyLogger.error('Review note failed: ' + (err && err.message));
  }
}

async function openNotesSheet() {
  var st = $('note-status');
  try {
    var dEntry = await notesDir();
    var base = await notesSheetBase(dEntry);
    if (!base) { st.textContent = 'No Sheet yet — run notes_sync.py push first'; return; }
    try {
      await require('uxp').shell.openExternal(base);
      st.textContent = 'Opened notes Sheet in browser';
    } catch (eO) {
      // манифест без https-схемы (панель не перезагружена после апдейта) — хотя бы в буфер
      var copied = await copyToClipboard(base);
      st.textContent = copied ? 'Browser open blocked — Sheet link copied instead'
        : 'Open failed: ' + eO.message;
      assemblyLogger.warn('openExternal failed (' + eO.message + '), reload plugin to pick up manifest https scheme');
    }
  } catch (err) {
    if (st) st.textContent = 'Open Sheet failed: ' + err.message;
    assemblyLogger.error('Open notes Sheet failed: ' + (err && err.message));
  }
}

async function playheadSeconds(seq) {
  var sec = null;
  try {
    var tt = seq.getPlayerPosition ? await seq.getPlayerPosition() : null;
    if (tt && typeof tt.seconds === 'number') sec = tt.seconds;
    else if (tt && typeof tt.seconds === 'function') sec = tt.seconds();
    else if (tt && tt.ticks !== undefined) sec = Number(tt.ticks) / 254016000000;
  } catch (eP) { assemblyLogger.debug('getPlayerPosition: ' + eP.message); }
  if (sec === null || isNaN(sec)) throw new Error('Player position unavailable on this build (getPlayerPosition)');
  return sec;
}

/**
 * v2.17.0 «Copy ТЗ @ playhead» (Роман 07.09: текст ТЗ должен копироваться с таймлайна;
 * clip-маркер мастер-клипа на 25.x приходит без имени/коммента → надёжный путь — панель).
 * Ищет review-JSON, чей part.sequence_name — префикс активной секвенции (без _v{N}),
 * берёт ближайший сегмент с item_marker (плашка ТЗ на V4) к плейхеду и кладёт в буфер
 * ПОЛНЫЙ текст ТЗ + ссылки на материалы (item_marker.links + папка Review_materials).
 */
async function copyTzAtPlayhead() {
  var st = $('note-status');
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere project');
    var seq = await project.getActiveSequence();
    if (!seq) throw new Error('No active sequence');
    var sec = await playheadSeconds(seq);
    if (!projectState.folderPath) throw new Error('No project folder');
    var revDir = await uxpfs.getEntryWithUrl('file://' + projectState.folderPath + '/00_Setup/05_Review');
    var entries = await revDir.getEntries();
    var seqBase = String(seq.name || '').replace(/_v\d+$/, '');
    var best = null, bestMod = -1, fallback = null, fbMod = -1;
    for (var i = 0; i < entries.length; i++) {
      var en = entries[i];
      if (!en.isFile || !/_review_.*\.json$/i.test(en.name)) continue;
      var part;
      try { part = JSON.parse(await en.read()); } catch (eJ) { continue; }
      var segsIm = (part.segments || []).filter(function (s) { return s.item_marker; });
      if (!segsIm.length) continue;
      var mod = 0;
      try { var md = await en.getMetadata(); mod = md && md.dateModified ? new Date(md.dateModified).getTime() : 0; } catch (eM) { assemblyLogger.debug('getMetadata ' + en.name + ': ' + (eM && eM.message)); }
      var sn = String((part.part || {}).sequence_name || '');
      if (sn && seqBase.indexOf(sn) === 0 && mod > bestMod) { best = part; bestMod = mod; }
      if (mod > fbMod) { fallback = part; fbMod = mod; }
    }
    var part2 = best || fallback;
    if (!part2) throw new Error('No review JSON with a brief (item_marker) in 05_Review');
    var cand = part2.segments.filter(function (s) { return s.item_marker; });
    var hit = null, hitD = Infinity;
    cand.forEach(function (s) {
      var a = Number(s.timeline_in_sec), b = Number(s.timeline_out_sec);
      var d = (sec >= a && sec <= b) ? 0 : Math.min(Math.abs(sec - a), Math.abs(sec - b));
      if (d < hitD) { hitD = d; hit = s; }
    });
    if (!hit) throw new Error('No brief segments in ' + ((part2.part || {}).name || 'review JSON'));
    var im = hit.item_marker;
    var mm = Math.floor(sec / 60), ss = Math.floor(sec % 60);
    function p2(n) { return ('0' + n).slice(-2); }
    var lines = [String(im.name || hit.segment_id), '', String(im.comment || '').trim()];
    var links = Array.isArray(im.links) ? im.links : [];
    if (links.length) { lines.push(''); lines.push('🔗 Материалы:'); links.forEach(function (l) { lines.push('  ' + l); }); }
    var note = String((part2.part || {}).note || '');
    var mFolder = /https:\/\/drive\.google\.com\/drive\/folders\/[A-Za-z0-9_-]+/.exec(note);
    if (mFolder) lines.push((links.length ? '' : '\n') + '📁 Review_materials: ' + mFolder[0]);
    lines.push('', '⏱ playhead ' + mm + ':' + p2(ss) + ' · ' + seq.name + (hitD > 0 ? ' · nearest brief ' + Math.round(hitD) + ' s away' : ''));
    var ok = await copyToClipboard(lines.join('\n'));
    st.textContent = ok ? ('📋 ' + String(im.name || hit.segment_id).slice(0, 48) + (hitD > 0 ? ' (' + Math.round(hitD) + ' s away)' : '') + ' — copied')
      : 'Clipboard unavailable — see Err log';
    assemblyLogger.info('Copy ТЗ @ ' + sec.toFixed(2) + 's → ' + (im.name || hit.segment_id) + ' from ' + ((part2.part || {}).name || '?'));
  } catch (err) {
    if (st) st.textContent = 'Copy Brief failed: ' + err.message;
    assemblyLogger.error('Copy ТЗ failed: ' + (err && err.message));
  }
}

async function copyAllReviewNotes() {
  var st = $('note-status');
  try {
    var dEntry = await notesDir();
    var notes = await readNotes(dEntry);
    if (!notes.length) { st.textContent = 'No notes yet'; return; }
    var base = await notesSheetBase(dEntry);
    var lines = [(projectState.projectName || 'Project') + ' review notes (' + notes.length + '):'];
    if (base) lines.push(base);
    notes.forEach(function (n, i) {
      var l = n.id + ' · ' + n.tc + ' · ' + n.sequence + (n.comment ? ' — ' + n.comment : '');
      var link = noteLink(base, i + 2);
      if (link) l += ' · ' + link;
      lines.push(l);
    });
    var ok = await copyToClipboard(lines.join('\n'));
    st.textContent = ok ? ('Copied ' + notes.length + ' note(s) to clipboard')
      : 'Clipboard unavailable — see Err log';
    if (!ok) assemblyLogger.error('Copy all notes: clipboard API unavailable');
  } catch (err) {
    if (st) st.textContent = 'Copy all failed: ' + err.message;
    assemblyLogger.error('Copy all notes failed: ' + (err && err.message));
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// JOB QUEUE — «сделай это сам», очередь заданий из терминала.
//
// Панель уже умеет ходить наружу (finesync: пишет файл → ждёт правок). Здесь тот же
// приём в обратную сторону: снаружи кладут задание в
//   {project}/00_Setup/pipeline/ytai_job.json   → {"action": "...", "part": "...", "id": "..."}
// панель раз в 3 с проверяет файл, выполняет, пишет рядом ytai_job_result.json и удаляет
// задание. Ничего не выполняется, пока панель не открыта — это НЕ демон, а «руки»
// открытой панели. Действия ровно те же функции, что и у кнопок, — никакой второй логики.
// ─────────────────────────────────────────────────────────────────────────────

const JOB_ACTIONS = {
  'chapters_all': async function () {
    await applyChapterMarkersToAll();
    return 'chapters placed on every scene sequence';
  },
  'chapters_active': async function () {
    await applyChapterMarkersToActive();
    return 'chapters placed on the active sequence';
  },
  'build_part': async function (job) {
    if (!job.part) throw new Error('build_part needs "part": absolute path to the part JSON');
    var entry = await uxpfs.getEntryWithUrl('file://' + job.part);
    var data = JSON.parse(await entry.read());
    var bundle = data.parts && data.parts.length
      ? data.parts
      : [{ part: data.part, segments: data.segments }];
    partsState.bundle = data.parts && data.parts.length ? data.parts : null;
    partsState.part = bundle[0].part;
    partsState.segments = bundle[0].segments;
    partsState.filePath = job.part;
    var res = await buildParts(bundle);
    if (!res || !res.ok) throw new Error((res && res.error) || 'build failed');
    return 'built: ' + (res.builtNames || []).join(', ');
  },
};

let jobState = { busy: false, lastId: null };

async function jobTick() {
  if (jobState.busy || !projectState.folderPath) return;
  var dir = projectState.folderPath + '/00_Setup/pipeline';
  var jobPath = dir + '/ytai_job.json';
  var job = null;
  try {
    var e = await uxpfs.getEntryWithUrl('file://' + jobPath);
    job = JSON.parse(await e.read());
  } catch (err) {
    return;                       // нет файла — обычное состояние, молчим
  }
  if (!job || !job.action || (job.id && job.id === jobState.lastId)) return;

  jobState.busy = true;
  jobState.lastId = job.id || null;
  var started = new Date().toISOString();
  var out = { id: job.id || null, action: job.action, started: started, ok: false };
  assemblyLogger.info('=== JOB from terminal: ' + job.action + ' ' + (job.part || '') + ' ===');
  try {
    var fn = JOB_ACTIONS[job.action];
    if (!fn) throw new Error('unknown action "' + job.action + '" (have: ' +
      Object.keys(JOB_ACTIONS).join(', ') + ')');
    out.result = await fn(job);
    out.ok = true;
    assemblyLogger.info('JOB ok: ' + out.result);
  } catch (err) {
    out.error = err && err.message ? err.message : String(err);
    assemblyLogger.error('JOB failed: ' + out.error);
  }
  out.finished = new Date().toISOString();
  // сначала пишем результат, только потом убираем задание — иначе гонка на стороне CLI
  try {
    var dEntry = await uxpfs.getEntryWithUrl('file://' + dir);
    var rf = await dEntry.createFile('ytai_job_result.json', { overwrite: true });
    await rf.write(JSON.stringify(out, null, 1));
  } catch (eW) { assemblyLogger.warn('job result write failed: ' + eW.message); }
  try {
    var jf = await uxpfs.getEntryWithUrl('file://' + jobPath);
    await jf.delete();
  } catch (eD) { assemblyLogger.warn('job file delete failed: ' + eD.message); }
  jobState.busy = false;
}

/**
 * Chapter markers → EVERY scene sequence in the project, in one pass.
 * Nothing has to be opened: we walk ingest.markers, find each scene's sequence by
 * name ("{code}_{scene}" or a bare "{scene}" — the editor renames them) and replace
 * its generated markers. Per-scene failures never stop the run.
 */
async function applyChapterMarkersToAll() {
  if (!ingestState.data) { setIngestStatus('Load ingest JSON first', 'error'); return; }
  var project = await ppro.Project.getActiveProject();
  if (!project) { setIngestStatus('No active project', 'error'); return; }

  var all = ingestState.data.markers || {};
  var scenes = Object.keys(all).filter(function (s) { return (all[s] || []).length; });
  if (!scenes.length) { setIngestStatus('ingest.markers is empty — nothing to place', 'error'); return; }

  var code = ingestState.data.project_code || '';
  var found = await listProjectSequences(project, ingestLogger);
  var byName = {};
  found.forEach(function (f) { byName[f.name] = byName[f.name] || f.seq; });

  ingestLogger.info('=== Chapter markers → ALL scenes (' + scenes.length + ') ===');
  setIngestStatus('Chapters → all scenes: 0/' + scenes.length + '…', 'waiting');

  // ⚠️ Premiere падал, когда все 433 маркера клались одним прогоном без передышек
  // (Роман, 21.08: «выкидывает премьер после Chapters → ALL»). Теперь строго по одному
  // таймлайну: пауза между сценами, сохранение после каждой и ПРОПУСК уже сделанных —
  // так повторное нажатие после падения продолжает с места обрыва, а не начинает заново.
  var okScenes = 0, totalPlaced = 0, missing = [], skipped = 0;
  function pause(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  for (var i = 0; i < scenes.length; i++) {
    var scene = scenes[i];
    var want = all[scene];
    var seq = byName[code + '_' + scene] || byName[scene] || byName[code + '_' + scene + '_SYNC'];
    if (!seq) { missing.push(scene); continue; }

    setIngestStatus('Chapters ' + (i + 1) + '/' + scenes.length + ': ' + scene + '…', 'waiting');

    // уже разложено ровно то, что нужно? — не трогаем Premiere вообще
    try {
      var have = await generatedMarkerNames(seq, ingestLogger);
      if (have && have.length === want.length) {
        var wn = want.map(function (m) { return m.name; }).sort().join('\u0000');
        if (have.slice().sort().join('\u0000') === wn) {
          skipped++;
          ingestLogger.info('  ' + scene + ': уже актуально (' + have.length + ') — пропуск');
          continue;
        }
      }
    } catch (e) { /* не смогли посмотреть — просто раскладываем */ }

    try {
      var n = await addSceneMarkers(project, seq, want, ingestLogger);
      totalPlaced += n;
      if (n) okScenes++;
      ingestLogger.info('  ' + scene + ': ' + n + '/' + want.length);
    } catch (err) {
      ingestLogger.error('  ' + scene + ' failed: ' + err.message);
      missing.push(scene + ' (error)');
    }

    // сохраняем после КАЖДОЙ сцены: если Premiere всё же упадёт, сделанное не пропадёт
    try { await project.save(); } catch (e) { ingestLogger.debug('save: ' + e.message); }
    await pause(400);
  }

  var msg = 'Chapters → ' + okScenes + '/' + scenes.length + ' sequences, ' + totalPlaced + ' markers';
  if (skipped) msg += ' · ' + skipped + ' already up to date';
  if (missing.length) msg += ' · no sequence for: ' + missing.join(', ');
  ingestLogger.info(msg);
  setIngestStatus(msg, (okScenes || skipped) ? 'ready' : 'error');
}

// ─────────────────────────────────────────────────────────────────────────────
// Verify Sync — verdict in FRAMES right after Build (TICKET_uxp_audit task 7 =
// TICKET_ch4_sync_truth 5.3). Gate: worst camera↔lav pair ≤ ½ frame.
// UXP cannot measure audio (no ffmpeg), so the panel saves the project, drops an
// order in /tmp and opens tools/verify_sync/verify_sync.command, which dumps the
// saved .prproj and runs the audio arbiter (wordsync_multicam/timeline_sync_audit,
// unchanged). The verdict file carries the order's run_id — the panel waits for
// THAT run, never mistakes an old verdict for a new one.
// ─────────────────────────────────────────────────────────────────────────────

async function verifySync() {
  var project = await ppro.Project.getActiveProject();
  if (!project) { setIngestStatus('No active project', 'error'); return; }
  if (!projectState.folderPath) { setIngestStatus('Select project folder first', 'error'); return; }
  var seq = await project.getActiveSequence();
  if (!seq) { setIngestStatus('Open the scene sequence to verify', 'error'); return; }
  var seqName = String(seq.name || '');
  var fps = 25;
  try {
    var tb = await seq.getTimebase();
    if (tb) fps = Math.round((254016000000 / Number(tb)) * 1000) / 1000;
  } catch (eTb) { ingestLogger.warn('Verify Sync: getTimebase failed — assuming 25 fps', eTb); }

  $('btn-verify-sync').setAttribute('disabled', 'true');
  ingestLogger.info('=== VERIFY SYNC: ' + seqName + ' @ ' + fps + ' fps ===');
  try {
    // The arbiter reads the SAVED .prproj — unsaved moves would not be measured.
    await project.save();
    var prproj = String(project.path || '');
    if (!prproj) throw new Error('project path unknown — save the project first');
    var code = audioMapMod.projectCodeOf(projectState.folderPath, seqName);
    var runId = 'vs-' + Date.now();
    var order = {
      run_id: runId, prproj: prproj, seq: seqName, fps: fps,
      dump_out: projectState.folderPath + '/00_Setup/logs/verify_sync_dump.json',
      verdict_out: projectState.folderPath + '/00_Setup/01_Ingest/' + code + '_sync_verdict.json',
    };
    var tmpDir = await uxpfs.getEntryWithUrl('file:///tmp');
    var tmpFile = await tmpDir.createFile('ytai_verify_sync.json', { overwrite: true });
    await tmpFile.write(JSON.stringify(order));
    var cmd = require('os').homedir() + '/YTAI/scripts/05_editing/0500_uxp/tools/verify_sync/verify_sync.command';
    await require('uxp').shell.openPath(cmd);
    setIngestStatus('Verify Sync: measuring ' + seqName + ' in Terminal…', 'waiting');

    var verdict = await waitForVerdict(order.verdict_out, runId, 15 * 60);
    if (!verdict) throw new Error('no verdict after 15 min — see the Terminal window');
    var s0 = (verdict.sequences || [])[0];
    if (s0) {
      (s0.pairs || []).forEach(function (p) {
        ingestLogger.info('  ' + (p.judged ? (p.ok ? 'ok ' : '✗  ') : '·· ') + p.kind + '  ' + p.a.track + ' ' + p.a.name
          + ' ↔ ' + p.b.track + ' ' + p.b.name + '  Δ=' + p.dt_ms + ' ms (' + p.dt_frames + ' fr)  peak ' + p.peak);
      });
    }
    ingestLogger.info('Verify Sync: ' + verdict.verdict + ' — ' + verdict.summary + ' → ' + order.verdict_out);
    if (verdict.verdict === 'SYNC') setIngestStatus(verdict.summary, 'ready');
    else setIngestStatus(verdict.summary, 'error', verdict.error ? new Error(verdict.error) : undefined);
  } catch (err) {
    setIngestStatus('Verify Sync failed: ' + err.message, 'error', err);
  }
  $('btn-verify-sync').removeAttribute('disabled');
}

/**
 * Poll the verdict file until it carries runId (or give up). Returns the verdict or null.
 * Also polls the fixed /tmp fallback verify_sync.py writes when the project
 * folder cannot be written (review of aaff5ba: otherwise the panel waited 15 min).
 */
async function waitForVerdict(path, runId, maxSec) {
  var paths = [path, '/tmp/ytai_verify_sync_verdict.json'];
  for (var waited = 0; waited <= maxSec; waited += 3) {
    for (var pi = 0; pi < paths.length; pi++) {
      try {
        var entry = await uxpfs.getEntryWithUrl('file://' + paths[pi]);
        var v = JSON.parse(await entry.read());
        if (v && v.run_id === runId) return v;
      } catch (e) { /* not written yet, or mid-write — next tick */ }
    }
    await new Promise(function (r) { setTimeout(r, 3000); });
  }
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Export Audio Map — the active timeline AS IT IS (src/ingest/audioMap.js, format 1.3)
// ─────────────────────────────────────────────────────────────────────────────

async function exportAudioMap() {
  var project = await ppro.Project.getActiveProject();
  if (!project) { setIngestStatus('No active project', 'error'); return; }
  if (!projectState.folderPath) { setIngestStatus('Select project folder first', 'error'); return; }

  ingestLogger.info('=== Export Audio Map ===');
  setIngestStatus('Exporting Audio Map...', 'waiting');
  $('btn-export-audio-map').setAttribute('disabled', 'true');

  try {
    var seq = await project.getActiveSequence();
    if (!seq) throw new Error('No active sequence — open a timeline first');
    // Every item of every track, re-read from the live timeline on each click —
    // nothing dropped, disabled / one-frame / nested items flagged (Roman 25.09:
    // the map is how a discrepancy is shown, so it must be the timeline itself).
    var read = await audioMapMod.readSequence(seq, ingestLogger);
    var map = audioMapMod.buildSequenceMap(read, new Date().toISOString());
    var sm = map.summary;
    ingestLogger.info('Sequence: ' + read.name + ', fps=' + read.fps + ' · items per track '
      + JSON.stringify(sm.items_per_track) + ' · disabled ' + sm.disabled + ' · strays ' + sm.strays
      + ' · nested ' + sm.nested + ' · audio without video ' + sm.audio_without_video);

    // 00_Setup/01_Ingest/{CODE}_audio_map.json — one file per project, one entry per sequence.
    var ingestDir = projectState.folderPath + '/00_Setup/01_Ingest';
    var ingestEntry;
    try {
      ingestEntry = await uxpfs.getEntryWithUrl('file://' + ingestDir);
    } catch (e) {
      var setupEntry = await uxpfs.getEntryWithUrl('file://' + projectState.folderPath + '/00_Setup');
      ingestEntry = await ensureSubfolder(setupEntry, '01_Ingest', ingestLogger);
    }
    var code = audioMapMod.projectCodeOf(projectState.folderPath, read.name);
    var outFileName = code + '_audio_map.json';
    var utf8 = require('uxp').storage.formats.utf8;
    var existing = null;
    var prevEntry = null;
    var lostBackup = null;
    try { prevEntry = await ingestEntry.getEntry(outFileName); } catch (e) { /* first export for this project */ }
    if (prevEntry) {
      var prevText = await prevEntry.read({ format: utf8 });
      try { existing = JSON.parse(prevText); } catch (eP) {
        // Never lose other sequences' maps silently: keep the unreadable file
        // aside under a timestamped name (a second occurrence must not overwrite
        // the first backup) and make the status red (review of 6fe3cc6).
        lostBackup = outFileName.replace(/\.json$/, '.unreadable_' + new Date().toISOString().replace(/[:.]/g, '-') + '.json');
        var bak = await ingestEntry.createFile(lostBackup, { overwrite: false });
        await bak.write(prevText, { format: utf8 });
        ingestLogger.warn('Previous ' + outFileName + ' was not valid JSON — kept as ' + lostBackup + ', starting a new file', eP);
      }
    }
    var file = audioMapMod.mergeAudioMapFile(existing, read.name, map,
      { projectCode: code, projectFolder: projectState.folderPath });
    var outFile = await ingestEntry.createFile(outFileName, { overwrite: true });
    await outFile.write(JSON.stringify(file, null, 2), { format: utf8 });

    var fullPath = ingestDir + '/' + outFileName;
    try { await navigator.clipboard.writeText(fullPath); } catch (e) { ingestLogger.debug('clipboard: ' + (e && e.message)); }
    ingestLogger.info('Path copied: ' + fullPath + ' · sequences in file: ' + Object.keys(file.sequences).join(', '));

    var line = audioMapMod.statusLine(read.name, map, outFileName);
    ingestLogger.info('Audio Map: ' + line);
    if (sm.unreadable) {
      setIngestStatus('Audio Map INCOMPLETE — ' + sm.unreadable + ' item(s)/track(s) could not be read: ' + line, 'error');
    } else if (lostBackup) {
      setIngestStatus('Audio Map written, but the previous file was unreadable — other sequences\' maps are in '
        + lostBackup + ': ' + line, 'error');
    } else {
      setIngestStatus('Audio Map: ' + line + ' (path copied)', 'ready');
    }
  } catch (err) {
    ingestLogger.error('Export Audio Map failed: ' + err.message, err);
    setIngestStatus('Export Audio Map failed: ' + err.message, 'error', err);
  }

  $('btn-export-audio-map').removeAttribute('disabled');
}

// ─────────────────────────────────────────────────────────────────────────────
// Align A2/A3 — snap DJI audio clips to match V1 video start positions
// For each V1 clip, finds matching A2/A3 clip and moves it to align.

/**
 * Apply audio channel fill effect to ALL audio clips on A1 of the active sequence.
 * "Fill Right with Left" → L channel copied to R (for mono_L sources)
 * "Fill Left with Right" → R channel copied to L (for mono_R sources)
 *
 * @param {string} effectName - "Fill Right with Left" or "Fill Left with Right"
 */
async function applyAudioFill(effectName) {
  var project = await ppro.Project.getActiveProject();
  if (!project) { setAssemblyStatus('No active project', 'error'); return; }

  var seq = await project.getActiveSequence();
  if (!seq) { setAssemblyStatus('No active sequence', 'error'); return; }

  assemblyLogger.info('=== Apply Audio Fill: ' + effectName + ' ===');
  setAssemblyStatus('Applying ' + effectName + '...', 'waiting');

  try {
    // Get A1 audio track (camera audio)
    var a1Track = await seq.getAudioTrack(0);
    if (!a1Track) throw new Error('No audio track A1');

    var trackItems = null;
    try { trackItems = a1Track.getTrackItems(1, false); } catch (ex) { /* signature differs per build; fallback below handles it */ }
    if (!trackItems) try { trackItems = a1Track.getTrackItems(); } catch (ex) { assemblyLogger.debug('A1 getTrackItems: ' + (ex && ex.message)); }

    if (!trackItems || trackItems.length === 0) {
      throw new Error('No audio clips on A1');
    }

    assemblyLogger.info('A1 clips: ' + trackItems.length);
    var applied = 0;

    for (var i = 0; i < trackItems.length; i++) {
      var audioItem = trackItems[i];
      try {
        // Create the fill effect for this clip
        var effect = await ppro.AudioFilterFactory.createComponentByDisplayName(effectName, audioItem);
        if (!effect) {
          assemblyLogger.warn('  clip[' + i + ']: effect not created');
          continue;
        }

        // Get the audio component chain and append the effect
        var chain = await audioItem.getComponentChain();
        project.lockedAccess(function () {
          project.executeTransaction(function (ca) {
            ca.addAction(chain.createAppendComponentAction(effect));
          }, 'Audio fill clip[' + i + ']');
        });

        applied++;
        assemblyLogger.info('  clip[' + i + ']: ' + effectName + ' applied ✓');
      } catch (clipErr) {
        assemblyLogger.warn('  clip[' + i + ']: failed — ' + clipErr.message);
      }
    }

    setAssemblyStatus(effectName + ': ' + applied + '/' + trackItems.length + ' clips', 'ready');
    assemblyLogger.info('Applied ' + effectName + ' to ' + applied + '/' + trackItems.length + ' clips');

  } catch (err) {
    assemblyLogger.error('Audio fill failed: ' + err.message);
    setAssemblyStatus('Audio fill failed: ' + err.message, 'error', err);
  }
}

/**
 * Apply speech-optimized audio effects chain to all A1 clips.
 * Order: Noise Reduction → DeHummer → Vocal Enhancer → Hard Limiter
 */
async function applyVoiceEnhance() {
  var VOICE_EFFECTS = [
    'Vocal Enhancer',
    'Hard Limiter'
  ];

  var project = await ppro.Project.getActiveProject();
  if (!project) { setAssemblyStatus('No active project', 'error'); return; }

  var seq = await project.getActiveSequence();
  if (!seq) { setAssemblyStatus('No active sequence', 'error'); return; }

  assemblyLogger.info('=== Voice Enhance: ' + VOICE_EFFECTS.join(' → ') + ' ===');
  setAssemblyStatus('Applying Voice Enhance...', 'waiting');

  try {
    var a1Track = await seq.getAudioTrack(0);
    if (!a1Track) throw new Error('No audio track A1');

    var trackItems = null;
    try { trackItems = a1Track.getTrackItems(1, false); } catch (ex) { /* signature differs per build; fallback below handles it */ }
    if (!trackItems) try { trackItems = a1Track.getTrackItems(); } catch (ex) { assemblyLogger.debug('A1 getTrackItems: ' + (ex && ex.message)); }
    if (!trackItems || trackItems.length === 0) throw new Error('No audio clips on A1');

    assemblyLogger.info('A1 clips: ' + trackItems.length + ', effects: ' + VOICE_EFFECTS.length);
    var applied = 0;

    for (var i = 0; i < trackItems.length; i++) {
      var audioItem = trackItems[i];
      var chain = await audioItem.getComponentChain();
      var clipEffects = 0;

      for (var ei = 0; ei < VOICE_EFFECTS.length; ei++) {
        try {
          var effect = await ppro.AudioFilterFactory.createComponentByDisplayName(VOICE_EFFECTS[ei], audioItem);
          if (!effect) continue;

          project.lockedAccess(function () {
            project.executeTransaction(function (ca) {
              ca.addAction(chain.createAppendComponentAction(effect));
            }, 'Voice ' + VOICE_EFFECTS[ei] + ' clip[' + i + ']');
          });
          clipEffects++;
        } catch (efErr) {
          assemblyLogger.warn('  clip[' + i + '] ' + VOICE_EFFECTS[ei] + ': ' + efErr.message);
        }
      }

      if (clipEffects > 0) {
        applied++;
        assemblyLogger.info('  clip[' + i + ']: ' + clipEffects + '/' + VOICE_EFFECTS.length + ' effects applied');
      }
    }

    setAssemblyStatus('Voice Enhance: ' + applied + '/' + trackItems.length + ' clips (' + VOICE_EFFECTS.length + ' effects)', 'ready');
  } catch (err) {
    assemblyLogger.error('Voice Enhance failed: ' + err.message);
    setAssemblyStatus('Voice Enhance failed: ' + err.message, 'error', err);
  }
}

/**
 * Remove ALL added audio effects from A1 clips.
 * Keeps only the default components (Volume, Channel Volume, Panner).
 * Premiere clips always have 3 built-in components at indices 0-2.
 */
async function removeAudioEffects() {
  var project = await ppro.Project.getActiveProject();
  if (!project) { setAssemblyStatus('No active project', 'error'); return; }

  var seq = await project.getActiveSequence();
  if (!seq) { setAssemblyStatus('No active sequence', 'error'); return; }

  assemblyLogger.info('=== Remove Audio Effects from A1 ===');
  setAssemblyStatus('Removing audio effects...', 'waiting');

  try {
    var a1Track = await seq.getAudioTrack(0);
    if (!a1Track) throw new Error('No audio track A1');

    var trackItems = null;
    try { trackItems = a1Track.getTrackItems(1, false); } catch (ex) { /* signature differs per build; fallback below handles it */ }
    if (!trackItems) try { trackItems = a1Track.getTrackItems(); } catch (ex) { assemblyLogger.debug('A1 getTrackItems: ' + (ex && ex.message)); }
    if (!trackItems || trackItems.length === 0) throw new Error('No audio clips on A1');

    var totalRemoved = 0;

    for (var i = 0; i < trackItems.length; i++) {
      var audioItem = trackItems[i];
      var chain = await audioItem.getComponentChain();
      var count = chain.getComponentCount();

      // Built-in components are at indices 0-2 (Volume, Channel Volume, Panner)
      // Remove everything from index 3 onwards (added effects), backwards
      var removed = 0;
      for (var ci = count - 1; ci >= 3; ci--) {
        try {
          var comp = chain.getComponentAtIndex(ci);
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) {
              ca.addAction(chain.createRemoveComponentAction(comp));
            }, 'Remove FX clip[' + i + '] idx=' + ci);
          });
          removed++;
        } catch (rmErr) {
          assemblyLogger.warn('  clip[' + i + '] idx=' + ci + ': ' + rmErr.message);
        }
      }

      if (removed > 0) {
        totalRemoved += removed;
        assemblyLogger.info('  clip[' + i + ']: removed ' + removed + ' effects');
      }
    }

    setAssemblyStatus('Removed ' + totalRemoved + ' effects from ' + trackItems.length + ' clips', 'ready');
  } catch (err) {
    assemblyLogger.error('Remove FX failed: ' + err.message);
    setAssemblyStatus('Remove FX failed: ' + err.message, 'error', err);
  }
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
    for (pos in commentsByPos) {
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
  const { MARKER_TYPE_CHAPTER, MARKER_COLOR_INDEX } = require('./src/shared/constants');
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
    if (project) { try { await project.save(); assemblyLogger.info('Project saved'); } catch (e) { assemblyLogger.debug('save: ' + (e && e.message)); } }

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
//  DELETED SCENE PIPELINE
// ══════════════════════════════════════════════════════════════════

function setDeletedSceneStatus(text, type, err) {
  $('ds-status-dot').className = 'status-dot ' + (type || 'waiting');
  $('ds-status-text').textContent = text;
  if (type === 'error') deletedSceneLogger.errorShown(text, err);
}

function setDeletedSceneProgress(percent, text) {
  $('ds-progress-bar').style.display = 'block';
  $('ds-progress-text').style.display = 'block';
  $('ds-progress-fill').style.width = percent + '%';
  $('ds-progress-text').textContent = text || '';
}

function hideDeletedSceneProgress() {
  $('ds-progress-bar').style.display = 'none';
  $('ds-progress-text').style.display = 'none';
}

/**
 * Create markers for the Deleted Scene sequence.
 *
 * Two types of markers:
 * - Chapter markers at source file boundaries (groups clips)
 * - Per-segment markers with transcript, speaker, notes, cut reason
 *
 * Uses same 4-transaction pattern as createAssemblyMarkers.
 */
async function createDeletedSceneMarkers(project, result) {
  const { MARKER_TYPE_CHAPTER, MARKER_COLOR_INDEX, DELETED_SCENE_COLOR_MAP } = require('./src/shared/constants');
  const seq = result.sequence;
  const segs = result.segments;
  const TIME_ZERO = ppro.TickTime.createWithSeconds(0);

  let markersOwner;
  try {
    markersOwner = await ppro.Markers.getMarkers(seq);
  } catch (ex) {
    deletedSceneLogger.warn('Cannot get sequence markers: ' + ex.message);
    return { chapters: 0, comments: 0 };
  }

  if (!markersOwner) {
    deletedSceneLogger.warn('Markers object is null');
    return { chapters: 0, comments: 0 };
  }

  // Build marker list using absolute positions (_timelinePosition from buildDeletedSceneSequence)
  const clipOffsets = result.clipOffsets || {};
  const markerList = [];
  let currentSource = '';

  // Block-level chapter markers: group deleted scene segments by block, create marker at first occurrence
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
      markerColor: bColorIdx !== undefined ? bColorIdx : DELETED_SCENE_COLOR_MAP.skip.markerIdx
    });
  }
  if (Object.keys(blockFirstPos).length > 0) {
    deletedSceneLogger.info('Block chapter markers: ' + Object.keys(blockFirstPos).length + ' blocks');
  }

  for (let i = 0; i < segs.length; i++) {
    const seg = segs[i];
    const cat = getDeletedSceneCategory(seg);
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
        markerColor: DELETED_SCENE_COLOR_MAP[cat].markerIdx
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
        markerColor: DELETED_SCENE_COLOR_MAP[cat].markerIdx
      });
    }
  }

  deletedSceneLogger.info('Creating ' + markerList.length + ' deleted scene markers...');

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
            deletedSceneLogger.debug('Marker action failed: ' + mk.name + ' — ' + ex.message);
          }
        }
      }, 'YTAI Deleted Scene Markers');
    });
  } catch (batchErr) {
    deletedSceneLogger.warn('Batch markers failed: ' + batchErr.message + ', trying individually...');
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
        deletedSceneLogger.debug('  Marker failed: ' + mk.name + ' — ' + ex.message);
      }
    }
  }

  deletedSceneLogger.info('Markers: ' + chapterCount + ' created');

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
              deletedSceneLogger.debug('  Marker color failed: ' + e.message);
            }
          }
        }, 'YTAI Deleted Scene Marker Colors');
      });
      deletedSceneLogger.info('Marker colors: ' + coloredCount + '/' + allMarkers.length);

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
                deletedSceneLogger.debug('  Marker type failed: ' + e.message);
              }
            }
          }, 'YTAI Deleted Scene Marker Types');
        });
        deletedSceneLogger.info('Marker types: ' + typedCount + '/' + allMarkers.length + ' set to Chapter');
      } catch (typeErr) {
        deletedSceneLogger.debug('Marker type change failed (non-fatal): ' + typeErr.message);
      }
    }
  } catch (colorErr) {
    deletedSceneLogger.debug('Marker colors/types failed (non-fatal): ' + colorErr.message);
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
    try { items = v0.getTrackItems(1, false); } catch (ex) { /* signature differs per build; fallback below handles it */ }
    if (!items) try { items = v0.getTrackItems(); } catch (ex) { logger.debug('Ingest V1 getTrackItems: ' + (ex && ex.message)); }
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
 * Build Deleted Scene sequence from loaded edit brief.
 * Uses complement approach: Deleted Scene = Ingest minus Assembly.
 */
async function buildDeletedScene() {
  if (assemblyState.segments.length === 0) {
    deletedSceneLogger.error('No brief loaded — load Edit Brief first');
    return;
  }

  deletedSceneLogger.clear();
  $('ds-validation').style.display = 'none';
  setDeletedSceneStatus('Building deleted scene...', 'waiting');

  let clipMap = null;
  let result = null;

  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');

    const totalSteps = 6;
    let step = 0;
    const startTime = Date.now();

    deletedSceneLogger.info('=== DELETED SCENE BUILD START ===');
    deletedSceneLogger.info('Project: ' + assemblyState.projectName);

    var stepTimings = [];
    var stepStart;

    // Step 1: Save backup
    step++;
    stepStart = Date.now();
    setDeletedSceneProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Saving backup...');
    try { await project.save(); deletedSceneLogger.info('Project saved'); } catch (e) { deletedSceneLogger.warn('Backup save failed: ' + (e && e.message)); }
    stepTimings.push('save ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 2: Scan project for clips + get clip durations
    step++;
    stepStart = Date.now();
    setDeletedSceneProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Scanning project clips...');
    deletedSceneLogger.info('=== Step 2: Scanning project for clips ===');
    const scanResult = await validateIngestState(project, assemblyState.segments, deletedSceneLogger);
    clipMap = scanResult.clipMap;

    let clipDurations = await getClipDurationsFromIngest(project, assemblyState.projectCode || assemblyState.projectName, deletedSceneLogger);
    if (!clipDurations || Object.keys(clipDurations).length === 0) {
      clipDurations = getClipDurationsFromBrief(assemblyState.segments);
      deletedSceneLogger.warn('Using brief-based durations (Ingest sequence not found)');
    }
    stepTimings.push('scan ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 3: Build Deleted Scene sequence
    step++;
    stepStart = Date.now();
    setDeletedSceneProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Building Deleted Scene sequence...');
    deletedSceneLogger.info('=== Step 3: Building Deleted Scene sequence ===');
    var deletedSceneOpts = {
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
        deletedSceneLogger.info('Per-scene Deleted Scene: ' + Object.keys(sceneMap).join(', '));
      }
    }
    result = await buildDeletedSceneSequence(project, clipMap, assemblyState.segments, assemblyState.projectCode || assemblyState.projectName, deletedSceneLogger, clipDurations, deletedSceneOpts, assemblyState.briefVersion, sceneMap);

    if (!result.sequence) {
      deletedSceneLogger.info('Deleted Scene sequence not created (no unused segments)');
      setDeletedSceneProgress(100, 'Complete — no unused segments');
      setDeletedSceneStatus('No unused segments', 'ready');
      return;
    }
    stepTimings.push('build ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 4: Create deleted scene markers
    step++;
    stepStart = Date.now();
    setDeletedSceneProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Markers...');
    deletedSceneLogger.info('=== Step 4: Deleted Scene Markers ===');
    let markerInfo = null;
    try {
      markerInfo = await createDeletedSceneMarkers(project, result);
    } catch (markerErr) {
      deletedSceneLogger.warn('Markers step failed (non-fatal): ' + markerErr.message);
    }
    stepTimings.push('markers ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 5: Activate + save + validate
    step++;
    stepStart = Date.now();
    setDeletedSceneProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Validating...');
    if (result.sequence) {
      await project.setActiveSequence(result.sequence);
      try { await project.openSequence(result.sequence.guid || result.sequence); } catch (e) { /* opening the tab is cosmetic; active seq already set */ }
    }
    try { await project.save(); } catch (e) { deletedSceneLogger.debug('save: ' + (e && e.message)); }

    if (result.sequence) {
      await validateDeletedSceneBuild(result.sequence, result, markerInfo);
    }
    stepTimings.push('validate ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 6: Generate + import Deleted Scene captions & transcript SRTs
    step++;
    stepStart = Date.now();
    setDeletedSceneProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Captions...');
    deletedSceneLogger.info('=== Step 6: Deleted Scene Captions ===');

    var dsProjectCode = assemblyState.projectCode || assemblyState.projectName;

    // Derive project root: strip /00_Setup/... from filePath, fallback to projectState.folderPath
    var dsProjectRoot = null;
    if (assemblyState.filePath) {
      dsProjectRoot = assemblyState.filePath.replace(/[/\\]00_Setup[/\\].*$/, '');
    } else if (projectState.folderPath) {
      dsProjectRoot = projectState.folderPath;
    }
    if (dsProjectRoot) {
      deletedSceneLogger.info('Deleted Scene SRT projectRoot: ' + dsProjectRoot);
    }

    var revSuffix = '3_DeletedScene' + (assemblyState.briefVersion ? '_v' + assemblyState.briefVersion : '');

    if (result.segments && result.segments.length > 0 && dsProjectRoot) {
      try {
        // Ensure Transcription subdirs exist
        var dsTranscriptionEntry = await uxpfs.getEntryWithUrl('file://' + dsProjectRoot + '/01_Source/Transcription');
        var dsTranscriptsFolderEntry = await ensureSubfolder(dsTranscriptionEntry, 'transcripts', deletedSceneLogger);
        var dsCaptionsFolderEntry = await ensureSubfolder(dsTranscriptionEntry, 'captions', deletedSceneLogger);

        // 1. Transcript SRT (absolute positioning matching Ingest layout)
        var dsTranscriptSrt = generateTranscriptSrt(result.segments, result.clipOffsets);
        if (dsTranscriptSrt) {
          var dsTrFileName = dsProjectCode + '_' + revSuffix + '_transcript.srt';
          var dsTrFile = await dsTranscriptsFolderEntry.createFile(dsTrFileName, { overwrite: true });
          await dsTrFile.write("\uFEFF" + dsTranscriptSrt);
          deletedSceneLogger.info('Transcript SRT written: Transcription/transcripts/' + dsTrFileName);
        }

        // 2. Captions SRT (word-grouped, absolute positioning)
        var dsCaptionsSrt = generateCaptionsSrt(result.segments, 6, result.clipOffsets);
        if (dsCaptionsSrt) {
          var dsCapFileName = dsProjectCode + '_' + revSuffix + '_captions.srt';
          var dsCapFile = await dsCaptionsFolderEntry.createFile(dsCapFileName, { overwrite: true });
          await dsCapFile.write("\uFEFF" + dsCaptionsSrt);
          deletedSceneLogger.info('Captions SRT written: Transcription/captions/' + dsCapFileName);
        }
      } catch (dsSrtErr) {
        deletedSceneLogger.warn('Deleted Scene SRT write failed (non-fatal): ' + dsSrtErr.message);
      }
    } else {
      deletedSceneLogger.warn('Deleted Scene SRT skipped: segs=' + (result.segments ? result.segments.length : 0) + ' filePath=' + !!assemblyState.filePath + ' folderPath=' + !!projectState.folderPath);
    }

    // Import both SRTs to 02_Transcripts bin
    var revImportPath = assemblyState.filePath || (dsProjectRoot ? dsProjectRoot + '/00_Setup' : null);
    await importCaptionsSrt(project, revImportPath, dsProjectCode, revSuffix, 'Deleted Scene Captions', deletedSceneLogger);
    await importCaptionsSrt(project, revImportPath, dsProjectCode, revSuffix, 'Deleted Scene Transcript', deletedSceneLogger, 'transcript');
    stepTimings.push('captions ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    setDeletedSceneProgress(100, 'Complete!');
    deletedSceneLogger.info('=== DELETED SCENE BUILD COMPLETE (' + elapsed + 's) ===');
    deletedSceneLogger.info('Timing: ' + stepTimings.join(' | '));
    deletedSceneLogger.info('Deleted Scene: ' + result.clipCount + ' clips on V1, total=' + (result.totalDuration || 0).toFixed(1) + 's');
    $('btn-build-deleted-scene').classList.add('btn-done');

    setDeletedSceneStatus('Deleted Scene built (' + result.clipCount + ' clips)', 'ready');
    updateLogPath('ds', deletedSceneLogger.getLastSavedPath());

  } catch (err) {
    deletedSceneLogger.error('DELETED SCENE BUILD FAILED: ' + err.message, err);
    setDeletedSceneStatus('Build failed: ' + err.message, 'error', err);
  }
}

/**
 * Post-build validation for Deleted Scene sequence.
 */
async function validateDeletedSceneBuild(sequence, result, markerInfo) {
  deletedSceneLogger.info('=== Post-build validation ===');
  const panel = $('ds-validation');
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
    } catch (e) { /* temp-file cleanup is best-effort */ }
    // Fallback: copy command to clipboard
    var pyCmd = 'python3 "' + scriptPath + '" --brief "' + briefPath + '"';
    try {
      await navigator.clipboard.writeText(pyCmd);
      screensLogger.info('Fallback: Python command copied to clipboard');
    } catch (e) { screensLogger.warn('Clipboard fallback failed: ' + (e && e.message)); }
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
 * Keeps Deleted Scene + Pre-Edit visible at root.
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
      for (i = 0; i < allItems.length; i++) {
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
      rootItem = await project.getRootItem();
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
        for (bi = 0; bi < allItems.length; bi++) {
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
    screensLogger.info('=== Step 2: Building Screen Cues sequence ===');
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
      briefDir = assemblyState.filePath.replace(/[/\\][^/\\]+$/, '');
      var screensProjectRoot = briefDir.replace(/[/\\]00_Setup$/, '');
      try {
        // Ensure Transcription subdirs exist
        var screensTranscriptionEntry = await uxpfs.getEntryWithUrl('file://' + screensProjectRoot + '/01_Source/Transcription');
        var screensTranscriptsFolderEntry = await ensureSubfolder(screensTranscriptionEntry, 'transcripts', screensLogger);
        var screensCaptionsFolderEntry = await ensureSubfolder(screensTranscriptionEntry, 'captions', screensLogger);

        // 1. Transcript SRT (full text per segment, for word-based editing)
        if (screenResult.assemblySegments && screenResult.assemblySegments.length > 0) {
          var screensTranscriptSrt = generateTranscriptSrt(screenResult.assemblySegments);
          if (screensTranscriptSrt) {
            var screensTrFileName = screensProjectCode + '_4_PreEdit_transcript.srt';
            var screensTrFile = await screensTranscriptsFolderEntry.createFile(screensTrFileName, { overwrite: true });
            await screensTrFile.write("\uFEFF" + screensTranscriptSrt);
            screensLogger.info('Transcript SRT written: Transcription/transcripts/' + screensTrFileName);
          }

          // 2. Captions SRT (word-grouped, 2-line blocks for on-screen reading, top-positioned)
          var screensCaptionsSrt = generateCaptionsSrt(screenResult.assemblySegments, 8, null, '{\\an8}');
          if (screensCaptionsSrt) {
            var screensCapFileName = screensProjectCode + '_4_PreEdit_captions.srt';
            var screensCapFile = await screensCaptionsFolderEntry.createFile(screensCapFileName, { overwrite: true });
            await screensCapFile.write("\uFEFF" + screensCaptionsSrt);
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
    try { await project.save(); } catch (e) { screensLogger.debug('save: ' + (e && e.message)); }

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
        try { await navigator.clipboard.writeText(pngCmd); screensLogger.info('PNG command copied to clipboard'); } catch (e) { /* clipboard copy is a convenience only */ }
      }
    }

    // Validation panel
    if (screenResult.sequence) {
      await validateScreensBuild(screenResult.sequence, screenResult, markerInfo);
    }

    // --- Post-build: Versioning, archive, bin organization (non-fatal) ---
    try {
      if (assemblyState.filePath) {
        briefDir = assemblyState.filePath.replace(/[/\\][^/\\]+$/, '');
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
    screensLogger.error('SCREEN CUES BUILD FAILED: ' + err.message, err);
    setScreensStatus('Build failed: ' + err.message, 'error', err);
    try { await saveScreensLogs(await ppro.Project.getActiveProject(), null); } catch (e) { /* failure path; debug bundle save is best-effort */ }
  }
}

/**
 * Save Screen Cues debug bundle (log.txt + debug_snapshot.json + brief_copy.json).
 */
async function saveScreensLogs(project, screenResult) {
  try {
    if (project) { try { await project.save(); screensLogger.info('Project saved'); } catch (e) { screensLogger.debug('save: ' + (e && e.message)); } }

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
        for (k of Object.getOwnPropertyNames(Object.getPrototypeOf(m0))) {
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
 * Export Pre-Edit Doc — reads active Premiere sequence (V1 clips + markers + transcript)
 * and writes a structured JSON to 00_Setup/03_Pre-Edit/ for conversion to Google Docs .docx.
 *
 * Flow: UXP → _pre_edit_export.json → python export_to_gdoc.py → .docx → Google Docs
 *
 * Reuses the same timeline-reading pattern as exportMarkers().
 */
async function exportPreEditDoc() {
  var project = await ppro.Project.getActiveProject();
  if (!project) { setScreensStatus('No active project', 'error'); return; }
  if (!projectState.folderPath) { setScreensStatus('Select project folder first', 'error'); return; }

  screensLogger.info('=== Export Pre-Edit Doc ===');
  setScreensStatus('Reading timeline...', 'waiting');
  $('btn-export-pre-edit-doc').setAttribute('disabled', 'true');

  try {
    // Step 1: Get active sequence
    var seq = await project.getActiveSequence();
    if (!seq) throw new Error('No active sequence — open a sequence first');
    var seqName = seq.name;
    screensLogger.info('Active sequence: ' + seqName);

    // Step 2: Read V1 TrackItems (real timeline clips)
    setScreensStatus('Reading V1 clips from ' + seqName + '...', 'waiting');
    var timelineClips = [];
    var v1Track = await seq.getVideoTrack(0);
    var trackItems = null;
    try { trackItems = v1Track.getTrackItems(1, false); } catch (ex) { /* signature differs per build; fallback below handles it */ }
    if (!trackItems) try { trackItems = v1Track.getTrackItems(); } catch (ex) { /* last probe; throw below reports the empty track */ }
    if (!trackItems || trackItems.length === 0) throw new Error('No clips on V1 track');

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
    screensLogger.info('V1 clips: ' + timelineClips.length);

    // Step 3: Read markers (for block/chapter structure + editor notes)
    setScreensStatus('Reading markers...', 'waiting');
    var markersOwner = await ppro.Markers.getMarkers(seq);
    var rawMarkers = markersOwner ? markersOwner.getMarkers() : [];
    var chapters = [];
    var editorNotes = {};

    if (rawMarkers && rawMarkers.length > 0) {
      for (var mi = 0; mi < rawMarkers.length; mi++) {
        var rm = rawMarkers[mi];
        var startTime = null;
        try { startTime = rm.getStart(); } catch (e) { /* optional API on this build; fallback below handles it */ }
        if (!startTime) try { startTime = rm.startTime; } catch (e) { screensLogger.debug('marker start unreadable: ' + (e && e.message)); }
        var posSec = startTime ? Math.round(startTime.seconds * 100) / 100 : 0;

        var dur = null;
        try { dur = rm.getDuration(); } catch (e) { /* optional API on this build; fallback below handles it */ }
        if (!dur) try { dur = rm.duration; } catch (e) { screensLogger.debug('marker duration unreadable: ' + (e && e.message)); }

        if (dur && dur.seconds > 0) {
          // Chapter marker
          chapters.push({
            name: rm.name || '',
            position_sec: posSec,
            duration_sec: Math.round(dur.seconds * 100) / 100,
          });
        } else {
          // Point marker — collect editor notes
          var commentText = rm.comments || '';
          if (!commentText) try { commentText = rm.getComments ? rm.getComments() : ''; } catch (e) { /* optional API on this build; rm.comment fallback below */ }
          if (!commentText) commentText = rm.comment || '';
          if (commentText) {
            if (!editorNotes[posSec]) editorNotes[posSec] = [];
            editorNotes[posSec].push(commentText);
          }
        }
      }
      chapters.sort(function(a, b) { return a.position_sec - b.position_sec; });
    }
    screensLogger.info('Chapters: ' + chapters.length + ', editor notes: ' + Object.keys(editorNotes).length);

    // Warn about empty chapter names
    var emptyNames = chapters.filter(function(c) { return !c.name || !c.name.trim(); }).length;
    if (emptyNames > 0) {
      screensLogger.warn('⚠ ' + emptyNames + '/' + chapters.length + ' chapters have empty names — name them in Premiere first');
    }

    // Step 4: Match with transcript for full text
    setScreensStatus('Matching transcript...', 'waiting');
    var txLookup = {};
    try {
      var setupDir = projectState.folderPath + '/00_Setup';
      var projectCode = projectState.projectName.match(/^(YT[A-Z]{2,4}\d+)/);
      projectCode = projectCode ? projectCode[1] : projectState.projectName;
      var txPath = setupDir + '/' + projectCode + '_Claude4_assembly.json';
      var txEntry = await uxpfs.getEntryWithUrl('file://' + txPath);
      var txRaw = await txEntry.read({ format: require('uxp').storage.formats.utf8 });
      var txData = JSON.parse(txRaw);
      var txClips = txData.clips || [];
      for (var tci = 0; tci < txClips.length; tci++) {
        txLookup[txClips[tci].filename] = txClips[tci].segments || [];
      }
      screensLogger.info('Loaded transcript: ' + txClips.length + ' clips');
    } catch (txErr) {
      screensLogger.debug('Transcript not available: ' + txErr.message);
    }

    // Match transcript text + speaker to each timeline clip
    for (var ci = 0; ci < timelineClips.length; ci++) {
      var clip = timelineClips[ci];
      var segs = txLookup[clip.source_file] || [];
      var texts = [];
      var speakerName = '';
      for (var si = 0; si < segs.length; si++) {
        var sg = segs[si];
        var sgStart = 0, sgEnd = 0;
        try {
          var sp = (sg.start || '0:0').split(':');
          sgStart = parseInt(sp[0]) * 60 + parseFloat(sp[1] || 0);
          var ep = (sg.end || '0:0').split(':');
          sgEnd = parseInt(ep[0]) * 60 + parseFloat(ep[1] || 0);
        } catch (pe) { screensLogger.debug('segment time parse: ' + (pe && pe.message)); }
        if (sgStart < clip.tc_out_sec && sgEnd > clip.tc_in_sec) {
          texts.push(sg.text || '');
          if (!speakerName && sg.speaker) speakerName = sg.speaker;
        }
      }
      clip.transcript = texts.join(' ');
      clip.speaker = speakerName;
    }

    // Step 5: Build block structure from chapters
    function fmtTC(sec) {
      var mm = Math.floor(sec / 60);
      var ss = (sec % 60).toFixed(1);
      return (mm < 10 ? '0' : '') + mm + ':' + (parseFloat(ss) < 10 ? '0' : '') + ss;
    }

    // Enrich from old brief if available (block names, colors, broll_note)
    var oldBrief = null;
    var oldSegLookup = {};
    if (projectState.briefPath) {
      try {
        var briefEntry = await uxpfs.getEntryWithUrl('file://' + projectState.briefPath);
        var briefContent = await briefEntry.read({ format: require('uxp').storage.formats.utf8 });
        oldBrief = JSON.parse(briefContent);
        if (oldBrief && oldBrief.segments) {
          for (var osi = 0; osi < oldBrief.segments.length; osi++) {
            var os = oldBrief.segments[osi];
            oldSegLookup[os.source_file + '|' + os.tc_in] = os;
          }
        }
        screensLogger.info('Enrichment from brief: ' + (oldBrief.segments || []).length + ' segments');
      } catch (bErr) {
        screensLogger.debug('Brief enrichment skipped: ' + bErr.message);
      }
    }

    // Build block defs from chapters + old brief
    var blockDefs = [];
    for (var chi = 0; chi < chapters.length; chi++) {
      var ch = chapters[chi];
      var bColor = 'Green';
      if (oldBrief && oldBrief.segments) {
        for (var obi = 0; obi < oldBrief.segments.length; obi++) {
          if (oldBrief.segments[obi].block_name === ch.name && oldBrief.segments[obi].color) {
            bColor = oldBrief.segments[obi].color;
            break;
          }
        }
      }
      blockDefs.push({
        num: chi + 1, start: ch.position_sec,
        end: ch.position_sec + ch.duration_sec, name: ch.name, color: bColor,
      });
    }

    // Step 5b: Load previous Pre-Edit visual annotations if v2+
    var prevVisuals = {};
    var prevVersion = 0;
    try {
      var peSetupPath = projectState.folderPath + '/00_Setup';
      var peEntry = await uxpfs.getEntryWithUrl('file://' + peSetupPath + '/03_Pre-Edit');
      var peEntries = await peEntry.getEntries();
      // Find latest version folder (v1, v2, ...)
      for (var pei = 0; pei < peEntries.length; pei++) {
        var pvMatch = peEntries[pei].name.match(/^v(\d+)$/);
        if (pvMatch) {
          var pvNum = parseInt(pvMatch[1], 10);
          if (pvNum > prevVersion) prevVersion = pvNum;
        }
      }
      if (prevVersion > 0) {
        // Read the latest pre_edit JSON
        var pvFolder = await uxpfs.getEntryWithUrl('file://' + peSetupPath + '/03_Pre-Edit/v' + prevVersion);
        var pvFiles = await pvFolder.getEntries();
        for (var pvfi = 0; pvfi < pvFiles.length; pvfi++) {
          if (pvFiles[pvfi].name.endsWith('.json')) {
            var pvContent = await pvFiles[pvfi].read({ format: require('uxp').storage.formats.utf8 });
            var pvData = JSON.parse(pvContent);
            if (pvData.segments) {
              for (var pvsi = 0; pvsi < pvData.segments.length; pvsi++) {
                var pvs = pvData.segments[pvsi];
                if (pvs.visual_type && pvs.visual_type !== 'talking_head') {
                  prevVisuals[pvs.segment_id] = {
                    visual_type: pvs.visual_type,
                    visual_content: pvs.visual_content || '',
                    visual_file: pvs.visual_file || '',
                  };
                }
              }
            }
            break;
          }
        }
        screensLogger.info('Previous Pre-Edit v' + prevVersion + ': ' + Object.keys(prevVisuals).length + ' visuals found');
      }
    } catch (pvErr) {
      screensLogger.debug('Previous Pre-Edit not found: ' + pvErr.message);
    }

    // Collect /comments from markers (start with /)
    var slashComments = {};
    for (var enk in editorNotes) {
      var enArr = editorNotes[enk];
      for (var eni = 0; eni < enArr.length; eni++) {
        if (enArr[eni].startsWith('/')) {
          var enPos = parseFloat(enk);
          if (!slashComments[enPos]) slashComments[enPos] = [];
          slashComments[enPos].push(enArr[eni]);
        }
      }
    }
    var slashCount = Object.keys(slashComments).length;
    if (slashCount > 0) {
      screensLogger.info('/comments from markers: ' + slashCount + ' positions');
    }

    // Step 6: Build output segments FROM BRIEF (not timeline clips)
    // Brief has fine-grained segments with correct transcripts; timeline clips are coarse.
    setScreensStatus('Building segments...', 'waiting');
    var outputSegments = [];

    // Helper: parse MM:SS.s or M:SS.sss timecode to seconds
    function parseTcSec(tc) {
      if (!tc) return 0;
      var parts = String(tc).split(':');
      if (parts.length === 2) return parseInt(parts[0]) * 60 + parseFloat(parts[1] || 0);
      if (parts.length === 3) return parseInt(parts[0]) * 3600 + parseInt(parts[1]) * 60 + parseFloat(parts[2] || 0);
      return parseFloat(tc) || 0;
    }

    if (oldBrief && oldBrief.segments && oldBrief.segments.length > 0) {
      // Filter use=TRUE, block!=99 and sort by block ASC + brief order (mirrors assemblyBuilder)
      var briefSegs = [];
      for (var bsi = 0; bsi < oldBrief.segments.length; bsi++) {
        var bs = oldBrief.segments[bsi];
        var bsUse = String(bs.use || 'TRUE').toUpperCase();
        if (bsUse === 'TRUE' && bs.block !== 99) {
          bs._briefIdx = bsi;
          briefSegs.push(bs);
        }
      }
      briefSegs.sort(function(a, b) {
        if (a.block !== b.block) return a.block - b.block;
        return a._briefIdx - b._briefIdx;
      });

      var cumTimeline = 0;
      for (var oi = 0; oi < briefSegs.length; oi++) {
        var seg = briefSegs[oi];
        var tcInSec = parseTcSec(seg.tc_in);
        var tcOutSec = parseTcSec(seg.tc_out);
        var durSec = Math.round((tcOutSec - tcInSec) * 100) / 100;
        if (durSec <= 0) durSec = seg.duration || 0;

        var segId = seg.segment_id || ('seg_' + String(oi + 1).padStart(3, '0'));
        var prevVis = prevVisuals[segId];

        // Match editor notes by cumulative timeline position
        var segNotes = seg.notes || '';
        var clipEnd = cumTimeline + durSec;
        for (var np in editorNotes) {
          var nPos = parseFloat(np);
          if (nPos >= cumTimeline && nPos < clipEnd) {
            var nonSlash = editorNotes[np].filter(function(n) { return !n.startsWith('/'); });
            if (nonSlash.length > 0) {
              segNotes = (segNotes ? segNotes + ' | ' : '') + nonSlash.join(' | ');
            }
          }
        }

        // Collect /comments for this segment
        var segSlashComments = [];
        for (var scp in slashComments) {
          var scPos = parseFloat(scp);
          if (scPos >= cumTimeline && scPos < clipEnd) {
            segSlashComments = segSlashComments.concat(slashComments[scp]);
          }
        }

        outputSegments.push({
          index: oi,
          segment_id: segId,
          source_file: seg.source_file || '',
          tc_in: seg.tc_in || '', tc_out: seg.tc_out || '',
          timeline_start_sec: Math.round(cumTimeline * 100) / 100,
          duration_sec: durSec,
          block: seg.block || 1, block_name: seg.block_name || '',
          speaker: seg.speaker || '', color: seg.color || 'Green',
          transcript: seg.transcript || '',
          broll_note: seg.broll_note || '', notes: segNotes,
          visual: prevVis ? prevVis.visual_content : '',
          visual_type: prevVis ? prevVis.visual_type : '',
          visual_file: prevVis ? prevVis.visual_file : '',
          marker_comments: segSlashComments.length > 0 ? segSlashComments : undefined,
        });
        cumTimeline += durSec;
      }
      screensLogger.info('Built ' + outputSegments.length + ' segments from Assembly brief (' + briefSegs.length + ' use=TRUE)');
    } else {
      // Fallback: no brief available — use timeline clips (legacy behavior)
      screensLogger.warn('No Assembly brief loaded — falling back to timeline clips (coarse segments)');
      for (var oi2 = 0; oi2 < timelineClips.length; oi2++) {
        var tc = timelineClips[oi2];
        var tcInStr = fmtTC(tc.tc_in_sec);
        var tcOutStr = fmtTC(tc.tc_out_sec);

        var segBlock = 1, segBlockName = '', segColor = 'Green';
        for (var bd = 0; bd < blockDefs.length; bd++) {
          if (tc.timeline_start_sec >= blockDefs[bd].start && tc.timeline_start_sec < blockDefs[bd].end) {
            segBlock = blockDefs[bd].num;
            segBlockName = blockDefs[bd].name;
            segColor = blockDefs[bd].color;
            break;
          }
        }

        var fallbackNotes = '';
        var fallbackEnd = tc.timeline_start_sec + tc.duration_sec;
        for (var fnp in editorNotes) {
          var fnPos = parseFloat(fnp);
          if (fnPos >= tc.timeline_start_sec && fnPos < fallbackEnd) {
            var fnNonSlash = editorNotes[fnp].filter(function(n) { return !n.startsWith('/'); });
            if (fnNonSlash.length > 0) {
              fallbackNotes = (fallbackNotes ? fallbackNotes + ' | ' : '') + fnNonSlash.join(' | ');
            }
          }
        }

        var fallbackSlash = [];
        for (var fscp in slashComments) {
          var fscPos = parseFloat(fscp);
          if (fscPos >= tc.timeline_start_sec && fscPos < fallbackEnd) {
            fallbackSlash = fallbackSlash.concat(slashComments[fscp]);
          }
        }

        var fallbackId = 'seg_' + String(oi2 + 1).padStart(3, '0');
        var fallbackVis = prevVisuals[fallbackId];

        outputSegments.push({
          index: oi2,
          segment_id: fallbackId,
          source_file: tc.source_file,
          tc_in: tcInStr, tc_out: tcOutStr,
          timeline_start_sec: tc.timeline_start_sec,
          duration_sec: tc.duration_sec,
          block: segBlock, block_name: segBlockName,
          speaker: tc.speaker || '', color: segColor,
          transcript: tc.transcript || '',
          broll_note: '', notes: fallbackNotes,
          visual: fallbackVis ? fallbackVis.visual_content : '',
          visual_type: fallbackVis ? fallbackVis.visual_type : '',
          visual_file: fallbackVis ? fallbackVis.visual_file : '',
          marker_comments: fallbackSlash.length > 0 ? fallbackSlash : undefined,
        });
      }
    }

    // Step 7: Write JSON to 00_Setup/03_Pre-Edit/
    setScreensStatus('Writing Pre-Edit export...', 'waiting');
    var setupPath = projectState.folderPath + '/00_Setup';
    var setupEntry;
    try {
      setupEntry = await uxpfs.getEntryWithUrl('file://' + setupPath);
    } catch (e) {
      throw new Error('00_Setup folder not found: ' + setupPath);
    }
    var preEditFolder = await ensureSubfolder(setupEntry, '03_Pre-Edit', screensLogger);

    // Filename = full sequence name + _pre_edit_out (like Assembly _out.json)
    var jsonFileName = seqName + '_pre_edit_out.json';
    var docxFileName = seqName + '_pre_edit_out.docx';

    var exportData = {
      sequence: seqName,
      exported_at: new Date().toISOString(),
      project_name: projectState.projectName || seqName,
      segments: outputSegments,
      blocks: blockDefs,
      timeline: {
        totalDuration: timelineClips.length > 0 ?
          Math.round((timelineClips[timelineClips.length - 1].timeline_start_sec + timelineClips[timelineClips.length - 1].duration_sec) * 10) / 10 : 0,
        clipCount: timelineClips.length,
        blockCount: blockDefs.length,
      },
    };

    // Write JSON
    var jsonFile = await preEditFolder.createFile(jsonFileName, { overwrite: true });
    await jsonFile.write(JSON.stringify(exportData, null, 2));
    var jsonPath = setupPath + '/03_Pre-Edit/' + jsonFileName;
    var docxPath = setupPath + '/03_Pre-Edit/' + docxFileName;
    screensLogger.info('Written: 00_Setup/03_Pre-Edit/' + jsonFileName);

    // Generate .docx via pre-existing .command script (same pattern as 0504_screen_cues)
    setScreensStatus('Generating .docx...', 'waiting');

    // Write params to /tmp/ for the .command to read
    var paramsContent = jsonPath + '\n' + docxPath;
    try {
      var tmpEntry = await uxpfs.getEntryWithUrl('file:///tmp');
      var paramsFile = await tmpEntry.createFile('ytai_pre_edit_params.txt', { overwrite: true });
      await paramsFile.write(paramsContent);
      screensLogger.info('Params written to /tmp/ytai_pre_edit_params.txt');
    } catch (tmpErr) {
      screensLogger.warn('Could not write /tmp params: ' + tmpErr.message);
    }

    // Open the permanent .command script (already has +x)
    var homePath = require('os').homedir();
    var cmdPath = homePath + '/YTAI/scripts/05_editing/0507_pre_edit/run_export_docx.command';
    try {
      var uxpShell = require('uxp').shell;
      await uxpShell.openPath(cmdPath);
      screensLogger.info('Launched run_export_docx.command → generating .docx');
    } catch (cmdErr) {
      screensLogger.warn('Auto-run failed: ' + cmdErr.message);
      screensLogger.info('Manual: python3 ~/YTAI/scripts/05_editing/0507_pre_edit/export_to_gdoc.py --input "' + jsonPath + '" --output "' + docxPath + '"');
    }

    // Store paths for Copy Prompt
    projectState.preEditJsonPath = jsonPath;
    projectState.preEditDocxPath = docxPath;

    setScreensStatus('Exported ' + outputSegments.length + ' segments → ' + jsonFileName, 'ready');

  } catch (err) {
    screensLogger.error('Pre-Edit Doc export failed: ' + err.message, err);
    setScreensStatus('Export failed: ' + err.message, 'error', err);
  }

  $('btn-export-pre-edit-doc').removeAttribute('disabled');
  $('btn-copy-pre-edit-prompt').removeAttribute('disabled');
}

/**
 * Copy Pre-Edit Prompt — generates a ready-made prompt for Claude Code chat
 * with paths to all relevant files, and copies it to clipboard.
 *
 * For v1: "Process this doc, recognize /commands, generate visuals"
 * For v2+: "Apply marker /comments, update visuals"
 */
async function copyPreEditPrompt() {
  if (!projectState.folderPath) {
    setScreensStatus('Select project folder first', 'error');
    return;
  }

  screensLogger.info('=== Copy Pre-Edit Prompt ===');

  try {
    var setupPath = projectState.folderPath + '/00_Setup';
    var preEditPath = setupPath + '/03_Pre-Edit';
    var projectCode = projectState.projectName.match(/^(YT[A-Z]{2,4}\d+)/);
    var channelCode = projectCode ? projectCode[1].replace(/\d+$/, '') : '';
    projectCode = projectCode ? projectCode[1] : projectState.projectName;

    // Find latest export JSON
    var preEditEntry;
    try {
      preEditEntry = await uxpfs.getEntryWithUrl('file://' + preEditPath);
    } catch (e) {
      throw new Error('No Pre-Edit folder found. Run Export Doc first.');
    }

    var entries = await preEditEntry.getEntries();
    var exportJsonName = '';
    var docxName = '';
    var latestVersion = 0;

    for (var i = 0; i < entries.length; i++) {
      var name = entries[i].name;
      if (name.endsWith('_pre_edit_out.json') || name.endsWith('_pre_edit_export.json')) {
        exportJsonName = name;
      }
      if (name.endsWith('_pre_edit_out.docx') || name.endsWith('.docx')) {
        docxName = name;
      }
      // Check for existing version folders (v1, v2, ...)
      var vMatch = name.match(/^v(\d+)$/);
      if (vMatch) {
        var vNum = parseInt(vMatch[1], 10);
        if (vNum > latestVersion) latestVersion = vNum;
      }
    }

    if (!exportJsonName) {
      throw new Error('No _pre_edit_out.json found. Run Export Doc first.');
    }

    var nextVersion = latestVersion + 1;
    var isUpdate = latestVersion > 0;

    // Read marker /comments if this is v2+
    var markerComments = [];
    if (isUpdate) {
      try {
        var project = await ppro.Project.getActiveProject();
        var seq = await project.getActiveSequence();
        if (seq) {
          var markersOwner = await ppro.Markers.getMarkers(seq);
          var rawMarkers = markersOwner ? markersOwner.getMarkers() : [];
          for (var mi = 0; mi < rawMarkers.length; mi++) {
            var rm = rawMarkers[mi];
            var comment = rm.comments || '';
            if (!comment) try { comment = rm.getComments ? rm.getComments() : ''; } catch (e) { /* optional API on this build; rm.comment fallback below */ }
            if (!comment) comment = rm.comment || '';
            if (comment && comment.startsWith('/')) {
              var startTime = null;
              try { startTime = rm.getStart(); } catch (e) { /* optional API on this build; fallback below handles it */ }
              if (!startTime) try { startTime = rm.startTime; } catch (e) { screensLogger.debug('marker start unreadable: ' + (e && e.message)); }
              var posSec = startTime ? Math.round(startTime.seconds * 100) / 100 : 0;
              markerComments.push({ position_sec: posSec, comment: comment });
            }
          }
        }
      } catch (mErr) {
        screensLogger.debug('Marker scan skipped: ' + mErr.message);
      }
    }

    // Build prompt
    var prompt = '';
    if (!isUpdate) {
      // V1 prompt
      prompt = 'Pre-Edit обработка:\n';
      prompt += '- Channel: ' + channelCode + '\n';
      prompt += '- Project: ' + projectState.folderPath + '\n';
      if (docxName) {
        prompt += '- Doc: ' + preEditPath + '/' + docxName + '\n';
      }
      prompt += '- Export JSON: ' + preEditPath + '/' + exportJsonName + '\n';
      prompt += '- Style: ~/YTAI/scripts/05_editing/0507_pre_edit/style_config.json\n';
      prompt += '- Rules: ~/YTAI/scripts/05_editing/0501_brief/project_knowledge/editing_rules.md\n';
      prompt += '- Instructions: ~/YTAI/scripts/05_editing/0507_pre_edit/INSTRUCTIONS.md\n';
      prompt += '\n';
      prompt += 'Обработай документ, распознай /команды как задания для тебя.\n';
      prompt += 'Сгенерируй визуалы в 00_Setup/03_Pre-Edit/v' + nextVersion + '/\n';
    } else {
      // V2+ prompt (update)
      prompt = 'Pre-Edit обновление (v' + nextVersion + '):\n';
      prompt += '- Channel: ' + channelCode + '\n';
      prompt += '- Project: ' + projectState.folderPath + '\n';
      prompt += '- Предыдущая версия: ' + preEditPath + '/v' + latestVersion + '/\n';
      prompt += '- Новый экспорт: ' + preEditPath + '/' + exportJsonName + '\n';
      prompt += '- Instructions: ~/YTAI/scripts/05_editing/0507_pre_edit/INSTRUCTIONS.md\n';
      if (markerComments.length > 0) {
        prompt += '\n/comments из маркеров Premiere (' + markerComments.length + '):\n';
        for (var mc = 0; mc < markerComments.length; mc++) {
          var cm = markerComments[mc];
          prompt += '  @' + cm.position_sec + 's: ' + cm.comment + '\n';
        }
      }
      prompt += '\nПримени /comments, обнови визуалы → 03_Pre-Edit/v' + nextVersion + '/\n';
    }

    // Copy to clipboard via UXP
    var copied = false;
    try {
      // UXP clipboard API
      var clipboard = require('uxp').clipboard;
      if (clipboard && clipboard.setContent) {
        await clipboard.setContent({ text: prompt });
        copied = true;
      }
    } catch (clipErr) {
      screensLogger.debug('Clipboard API: ' + clipErr.message);
    }

    // Fallback: write to temp file
    if (!copied) {
      try {
        var promptFile = await preEditEntry.createFile('_claude_prompt.txt', { overwrite: true });
        await promptFile.write(prompt);
        screensLogger.info('Prompt saved to: 03_Pre-Edit/_claude_prompt.txt');
      } catch (writeErr) {
        screensLogger.debug('File write fallback failed: ' + writeErr.message);
      }
    }

    // Log the prompt
    screensLogger.info('--- Prompt (v' + nextVersion + ') ---');
    prompt.split('\n').forEach(function(line) { screensLogger.info(line); });
    screensLogger.info('--- End Prompt ---');

    var statusMsg = copied
      ? 'Prompt v' + nextVersion + ' copied to clipboard → paste in Claude Code'
      : 'Prompt v' + nextVersion + ' saved to 03_Pre-Edit/_claude_prompt.txt';
    setScreensStatus(statusMsg, 'ready');

  } catch (err) {
    screensLogger.error('Copy Prompt failed: ' + err.message);
    setScreensStatus('Copy Prompt failed: ' + err.message, 'error', err);
  }
}

/**
 * Export Pre-Edit — full timeline data (JSON + HTML review table) to project exports folder.
 * Creates 00_Setup/exports/{code}_PreEdit_{timestamp}/ with timeline_data.json + timeline_review.html.
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
    screensLogger.error('Export failed: ' + err.message, err);
    setScreensStatus('Export failed: ' + err.message, 'error', err);
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
    screensLogger.error('Import failed: ' + err.message, err);
    setScreensStatus('Import failed: ' + err.message, 'error', err);
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

// ══════════════════════════════════════════════════════════════════
//  REVIEW PIPELINE (external editor review)
// ══════════════════════════════════════════════════════════════════

/**
 * Find latest .mp4/.mov in 03_Exports/ folder.
 */
async function findLatestExport(projectFolderPath) {
  var exportsDir = projectFolderPath + '/03_Exports';
  try {
    var folder = await uxpfs.getEntryWithUrl('file://' + exportsDir);
    var entries = await folder.getEntries();
    var videos = entries.filter(function(e) {
      var name = e.name.toLowerCase();
      return name.endsWith('.mp4') || name.endsWith('.mov');
    });
    if (videos.length === 0) return null;
    // Sort by name descending (latest version = highest name)
    videos.sort(function(a, b) { return b.name.localeCompare(a.name); });
    return videos[0];
  } catch (e) {
    return null;
  }
}

/**
 * Find latest Assembly brief (_in.json) in 00_Setup/02_Assembly/.
 */
async function findLatestAssemblyBrief(projectFolderPath) {
  var assemblyDir = projectFolderPath + '/00_Setup/02_Assembly';
  try {
    var folder = await uxpfs.getEntryWithUrl('file://' + assemblyDir);
    var entries = await folder.getEntries();
    var briefs = entries.filter(function(e) {
      return e.name.endsWith('_in.json') && e.name.indexOf('Assembly') >= 0;
    });
    if (briefs.length === 0) return null;
    briefs.sort(function(a, b) { return b.name.localeCompare(a.name); });
    return briefs[0];
  } catch (e) {
    return null;
  }
}

/**
 * Process Review — one-click pipeline:
 * 1. Find latest .mp4 in 03_Exports/
 * 2. Find latest Assembly brief
 * 3. Launch run_review.command (transcribe + compare + HTML)
 * 4. Poll for .done marker
 * 5. Auto-load review_brief.json
 * 6. Open HTML in browser
 */
async function processReview() {
  if (!projectState.folderPath) {
    reviewLogger.error('Select project folder first');
    return;
  }

  reviewLogger.clear();
  setReviewStatus('Processing review...', 'waiting');
  $('btn-process-review').setAttribute('disabled', 'true');

  try {
    // Step 1: Find latest export video
    setReviewProgress(5, 'Finding latest export...');
    reviewLogger.info('=== PROCESS REVIEW START ===');

    var latestVideo = await findLatestExport(projectState.folderPath);
    if (!latestVideo) {
      reviewLogger.error('No .mp4/.mov found in 03_Exports/');
      setReviewStatus('No video in 03_Exports/', 'error');
      $('btn-process-review').removeAttribute('disabled');
      return;
    }
    reviewLogger.info('Latest export: ' + latestVideo.name);

    // Step 2: Find latest Assembly brief
    var latestBrief = await findLatestAssemblyBrief(projectState.folderPath);
    if (!latestBrief) {
      reviewLogger.error('No Assembly brief found in 00_Setup/02_Assembly/');
      setReviewStatus('No Assembly brief found', 'error');
      $('btn-process-review').removeAttribute('disabled');
      return;
    }
    reviewLogger.info('Assembly brief: ' + latestBrief.name);

    var videoPath = latestVideo.nativePath;
    var briefPath = latestBrief.nativePath;
    var outputDir = projectState.folderPath + '/00_Setup/05_Review';

    // Step 3: Write params to /tmp/
    setReviewProgress(10, 'Launching review pipeline...');
    var params = JSON.stringify({
      video: videoPath,
      brief: briefPath,
      output: outputDir,
      language: 'en'
    }, null, 2);

    var tmpFolder = await uxpfs.getEntryWithUrl('file:///tmp');
    var paramsFile = await tmpFolder.createFile('ytai_review_params.json', { overwrite: true });
    await paramsFile.write(params);
    reviewLogger.info('Params written to /tmp/ytai_review_params.json');

    // Clean up old markers
    try {
      var oldDone = await uxpfs.getEntryWithUrl('file:///tmp/ytai_review.done');
      await oldDone.delete();
    } catch (e) { /* stale marker is usually absent; cleanup is best-effort */ }
    try {
      var oldErr = await uxpfs.getEntryWithUrl('file:///tmp/ytai_review.error');
      await oldErr.delete();
    } catch (e) { /* stale marker is usually absent; cleanup is best-effort */ }

    // Step 4: Launch run_review.command
    var pluginFolder = await uxpfs.getPluginFolder();
    var pluginDir = pluginFolder.nativePath.replace(/\/$/, '');
    var cmdPath = pluginDir + '/../0508_review/run_review.command';

    try {
      var uxpShell = require('uxp').shell;
      await uxpShell.openPath(cmdPath);
      reviewLogger.info('Launched run_review.command');
    } catch (shellErr) {
      reviewLogger.error('shell.openPath failed: ' + shellErr.message);
      // Fallback: copy command to clipboard
      var pyCmd = 'cd "' + pluginDir + '/../0508_review" && ./run_review.command';
      try { await navigator.clipboard.writeText(pyCmd); } catch (e) { reviewLogger.warn('clipboard fallback failed: ' + (e && e.message)); }
      setReviewStatus('Launch failed — command copied to clipboard', 'error');
      $('btn-process-review').removeAttribute('disabled');
      return;
    }

    // Step 5: Poll for .done marker (5s interval, 5 min timeout for transcription)
    reviewLogger.info('Waiting for pipeline to finish (polling, timeout 15min)...');
    var donePath = '/tmp/ytai_review.done';
    var errorPath = '/tmp/ytai_review.error';
    var found = false;
    var errored = false;

    // Poll for .done marker (5s interval, 15 min timeout — transcription can take 10+ min)
    for (var attempt = 0; attempt < 180; attempt++) {
      await new Promise(function (resolve) { setTimeout(resolve, 5000); });

      // Check for error
      try {
        var errEntry = await uxpfs.getEntryWithUrl('file://' + errorPath);
        if (errEntry) {
          var errContent = await errEntry.read();
          reviewLogger.error('Pipeline failed: ' + errContent);
          errored = true;
          break;
        }
      } catch (e) { /* absent until the pipeline writes it; polled again */ }

      // Check for done
      try {
        var doneEntry = await uxpfs.getEntryWithUrl('file://' + donePath);
        if (doneEntry) {
          found = true;
          break;
        }
      } catch (e) { /* absent until the pipeline writes it; polled again */ }

      var elapsed = (attempt + 1) * 5;
      setReviewProgress(10 + (elapsed / 900 * 70), 'Processing... (' + elapsed + 's)');
    }

    if (errored) {
      setReviewStatus('Pipeline failed — check Terminal', 'error');
      $('btn-process-review').removeAttribute('disabled');
      return;
    }

    if (!found) {
      reviewLogger.warn('Timeout (15 min) — transcription may still be running');
      setReviewStatus('Timeout — check Terminal', 'error');
      $('btn-process-review').removeAttribute('disabled');
      return;
    }

    // Step 6: Read .done result
    setReviewProgress(85, 'Loading results...');
    var doneFile = await uxpfs.getEntryWithUrl('file://' + donePath);
    var doneContent = await doneFile.read();
    var doneResult = JSON.parse(doneContent);
    reviewLogger.info('Pipeline complete');
    reviewLogger.info('Transcript: ' + (doneResult.transcript || ''));
    reviewLogger.info('DOCX: ' + (doneResult.docx || ''));

    // Step 7: Save results and enable Build Review button
    reviewState.pipelineResult = doneResult;

    // Open DOCX in default app
    setReviewProgress(95, 'Opening DOCX...');
    if (doneResult.docx) {
      try {
        var uxpShell2 = require('uxp').shell;
        await uxpShell2.openPath(doneResult.docx);
        reviewLogger.info('Opened DOCX: ' + doneResult.docx);
      } catch (docxErr) {
        reviewLogger.warn('Could not open DOCX: ' + docxErr.message);
      }
    }

    setReviewProgress(100, 'Complete!');
    $('btn-build-review').removeAttribute('disabled');
    $('btn-export-review-markers').removeAttribute('disabled');
    setReviewStatus('Ready — press Build Review to load into Premiere', 'ready');
    updateLogPath('review', reviewLogger.getLastSavedPath());

  } catch (err) {
    reviewLogger.error('PROCESS REVIEW FAILED: ' + err.message, err);
    setReviewStatus('Failed: ' + err.message, 'error', err);
  } finally {
    $('btn-process-review').removeAttribute('disabled');
  }
}

function setReviewStatus(text, type, err) {
  $('review-status-dot').className = 'status-dot ' + (type || 'waiting');
  $('review-status-text').textContent = text;
  if (type === 'error') reviewLogger.errorShown(text, err);
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
 * Load review_brief.json via file picker.
 */
async function loadReviewBrief() {
  try {
    var briefFile = await uxpfs.getFileForOpening({ types: ['json'], allowMultiple: false });
    if (!briefFile) return;

    reviewLogger.info('Loading review brief: ' + (briefFile.nativePath || briefFile.name));
    var content = await briefFile.read();
    var parsed = parseReviewBrief(content, reviewLogger);

    reviewState.data = parsed;
    reviewState.filePath = briefFile.nativePath || null;

    setReviewStatus('Review brief loaded. ' + parsed.timeline.length + ' edited + ' + parsed.insertions.length + ' insertions.', 'ready');
    $('btn-build-review').removeAttribute('disabled');

    reviewLogger.info('Review brief loaded successfully');
  } catch (err) {
    reviewLogger.error('Failed to load review brief: ' + err.message);
    setReviewStatus('Load failed: ' + err.message, 'error', err);
  }
}

/**
 * Build Review — import video + create sequence + import captions/transcript SRT.
 * Activated after Process Review completes (or via Load Review Brief).
 */
// Find the latest rendered export across 02_Exports / 03_Exports (newest version by name).
async function findLatestRenderEntry(folderPath) {
  var best = null;
  var dirs = ['/02_Exports', '/03_Exports'];
  for (var d = 0; d < dirs.length; d++) {
    try {
      var folder = await uxpfs.getEntryWithUrl('file://' + folderPath + dirs[d]);
      var entries = await folder.getEntries();
      for (var i = 0; i < entries.length; i++) {
        var e = entries[i];
        if (!e.isFile) continue;
        var n = e.name.toLowerCase();
        if ((n.endsWith('.mp4') || n.endsWith('.mov')) && (!best || e.name.localeCompare(best.name) > 0)) best = e;
      }
    } catch (er) { /* dir may not exist */ }
  }
  return best;
}

/**
 * Build a REVIEW-OVERLAY sequence: latest render on V1/A1, recommendations on V2/V3 (+ markers).
 * V1 stays a normal editable clip (cut / rearrange); the whole sequence transfers to the editor's
 * project. One-click: uses the auto-detected latest render + the latest inserts JSON (or empty V2/V3).
 */
async function buildReviewOverlay() {
  if (reviewState.building) { reviewLogger.warn('Review build already in progress'); return; }
  reviewState.building = true;
  $('btn-build-review-overlay').setAttribute('disabled', 'true');
  setReviewStatus('Building review-overlay (render → V1, inserts → V2/V3)...', 'waiting');
  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');
    var folderPath = projectState.folderPath;
    var code = assemblyState.projectCode || extractProjectCode(projectState.projectName || '');

    // 1) Latest render: auto-detected pipelineResult.video, else newest in 02_Exports/03_Exports
    var renderPath = (reviewState.pipelineResult && reviewState.pipelineResult.video) || null;
    if (!renderPath) {
      var rEntry = await findLatestRenderEntry(folderPath);
      if (rEntry) renderPath = rEntry.nativePath;
    }
    if (!renderPath) throw new Error('No render found in 02_Exports/03_Exports — select project / Process Review first');
    var renderName = renderPath.split('/').pop();
    reviewLogger.info('Review-overlay base render: ' + renderName);

    // 2) Inserts: pick the BEST parts JSON in 00_Setup/02_Assembly/parts/ — score by overlay format +
    //    NUMERIC version (NB: lexicographic sort puts "v9" after "v10" — must parse the number).
    var part = {};
    var segments = [];
    try {
      var partsFolder = await uxpfs.getEntryWithUrl('file://' + folderPath + '/00_Setup/02_Assembly/parts');
      var pents = await partsFolder.getEntries();
      var jsons = pents.filter(function (e) { return e.isFile && e.name.toLowerCase().endsWith('.json'); });
      var best = null, bestScore = -1, bestName = '';
      for (var ji = 0; ji < jsons.length; ji++) {
        try {
          var pd = JSON.parse(await jsons[ji].read());
          if (!pd || !Array.isArray(pd.segments) || !pd.segments.length) continue;
          var vm = jsons[ji].name.match(/_v(\d+)/);
          var vnum = vm ? parseInt(vm[1], 10) : 0;
          var overlay = (pd.part && pd.part.build_model === 'overlay_on_base') ? 1 : 0;
          var score = overlay * 100000 + vnum * 100 + pd.segments.length; // overlay > version > size
          if (score > bestScore) { bestScore = score; best = pd; bestName = jsons[ji].name; }
        } catch (e) { /* skip unreadable */ }
      }
      if (best) {
        part = best.part || {}; segments = best.segments || [];
        reviewLogger.info('Inserts: ' + bestName + ' (' + segments.length + ' segments, V3=' +
          segments.filter(function (s) { return (s.track || '') === 'V3'; }).length + ')');
      } else {
        reviewLogger.info('No inserts JSON — scaffold render on V1 + empty V2/V3');
      }
    } catch (e) { reviewLogger.warn('No parts/ inserts found — empty V2/V3: ' + e.message); }
    // Explicit override: a part loaded in the Parts tab wins ONLY if it is overlay-compatible.
    if (partsState.part && partsState.segments && partsState.segments.length &&
        partsState.part.build_model === 'overlay_on_base') {
      part = partsState.part; segments = partsState.segments;
      reviewLogger.info('Override: using overlay inserts loaded in Parts tab (' + segments.length + ' segments)');
    }

    // 3) Version + base override
    var ver = 1;
    try {
      var rdir = await uxpfs.getEntryWithUrl('file://' + folderPath + '/00_Setup/05_Review');
      var rents = await rdir.getEntries();
      var re = new RegExp('_5_Review_v(\\d+)_overlay');
      for (var vi = 0; vi < rents.length; vi++) { var m = rents[vi].name.match(re); if (m) { var n = parseInt(m[1], 10); if (n >= ver) ver = n + 1; } }
    } catch (e) { /* no review dir yet */ }
    part = Object.assign({}, part, {
      code: code, name: 'Review_v' + ver + '_overlay',
      sequence_name: code + '_5_Review_v' + ver + '_overlay',
      build_model: 'overlay_on_base', base_clip: renderName, base_clip_path: renderPath
    });

    // 4) clipMap (don't throw on missing — base render still builds)
    var clipMap = {};
    try { var sb = await findSourceBin(project); if (sb) clipMap = await buildClipMap(sb, reviewLogger); }
    catch (e) { reviewLogger.warn('clipMap unavailable (inserts may skip): ' + e.message); }

    // 4b) Resolve the render with the PROVEN finder (casts into bins) and inject into clipMap so the
    //     builder places it on V1. importFiles does NOT return items in this API — find by name after.
    try {
      var renderItem = await findProjectItemByName(project, renderName, reviewLogger);
      if (!renderItem) {
        try { await project.importFiles([renderPath]); } catch (ie) { reviewLogger.warn('render import: ' + ie.message); }
        renderItem = await findProjectItemByName(project, renderName, reviewLogger);
      }
      if (renderItem) {
        clipMap[renderName] = renderItem;
        clipMap[renderName.replace(/\.[^.]+$/, '')] = renderItem;
        reviewLogger.info('Render resolved → V1 base: ' + renderName);
      } else {
        reviewLogger.warn('Render NOT resolved — V1 will be empty: ' + renderName);
      }
    } catch (e) { reviewLogger.warn('render resolve failed: ' + e.message); }

    // 4c) Auto-import insert media that isn't in the bin yet (so ALL inserts place), into _Review_inserts.
    try {
      var missing = [];
      var seenP = {};
      for (var qi = 0; qi < segments.length; qi++) {
        var sf = segments[qi].source_file, sp = segments[qi].source_path;
        if (!sf || !sp) continue;
        if (clipMap[sf] || clipMap[sf.replace(/\.[^.]+$/, '')]) continue;
        if (seenP[sp]) continue; seenP[sp] = 1;
        missing.push({ sf: sf, sp: sp });
      }
      if (missing.length) {
        reviewLogger.info('Auto-importing ' + missing.length + ' insert clip(s) → bin _Review_inserts...');
        setReviewProgress(20, 'Importing ' + missing.length + ' insert clips...');
        // Create/find the bin (best-effort, isolated — if it fails we still import to root).
        var binCast = null;
        try {
          var binItem = await findProjectItemByName(project, '_Review_inserts', reviewLogger);
          if (!binItem) {
            var rootItem = await project.getRootItem();
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                ca.addAction(rootItem.createBinAction('_Review_inserts', true));
              }, 'Create _Review_inserts bin');
            });
            binItem = await findProjectItemByName(project, '_Review_inserts', reviewLogger);
          }
          binCast = binItem ? ppro.FolderItem.cast(binItem) : null;
        } catch (eb) { reviewLogger.warn('bin create skipped (import to root): ' + eb.message); }
        var paths = missing.map(function (x) { return x.sp; });
        try {
          if (binCast) await project.importFiles(paths, true, binCast, false);
          else await project.importFiles(paths);
        } catch (eImp) {
          reviewLogger.warn('batch import failed (' + eImp.message + ') — one-by-one');
          for (var pj = 0; pj < paths.length; pj++) {
            try { if (binCast) await project.importFiles([paths[pj]], true, binCast, false); else await project.importFiles([paths[pj]]); } catch (e2) { reviewLogger.debug('import ' + paths[pj] + ': ' + (e2 && e2.message)); }
          }
        }
        var got = 0;
        for (var ri = 0; ri < missing.length; ri++) {
          var it = await findProjectItemByName(project, missing[ri].sf, reviewLogger);
          if (it) { clipMap[missing[ri].sf] = it; clipMap[missing[ri].sf.replace(/\.[^.]+$/, '')] = it; got++; }
        }
        reviewLogger.info('Auto-import: ' + got + '/' + missing.length + ' insert clips resolved into clipMap.');
      }
    } catch (e) { reviewLogger.warn('auto-import inserts failed: ' + e.message); }

    try { await project.save(); } catch (e) { reviewLogger.debug('save: ' + (e && e.message)); }
    setReviewProgress(30, 'Building ' + part.sequence_name + '...');
    const result = await buildPartSequence(project, clipMap, part, segments, reviewLogger, assemblyState.projectSettings);
    try { await project.save(); } catch (e) { reviewLogger.debug('save: ' + (e && e.message)); }

    var msg = 'Review-overlay: ' + result.seqName + ' — render on V1 + ' + result.placed + ' inserts on V2/V3' +
      (result.skipped ? ' (' + result.skipped + ' skipped — not in bin)' : '');
    setReviewStatus(msg, result.skipped ? 'warning' : 'ready');
    try {
      var vp = $('review-validation');
      vp.style.display = 'block';
      vp.innerHTML = '<div class="val-line"><b>' + escapeHtml(result.seqName) + '</b></div>' +
        '<div class="val-line">Base: ' + escapeHtml(renderName) + ' → V1/A1 (editable: cut / reorder)</div>' +
        '<div class="val-line">Inserts: ' + result.placed + (result.skipped ? ' (+' + result.skipped + ' not in bin)' : '') + ' on V2/V3 + markers</div>' +
        '<div class="val-line">Animator: drop your own timeline on V1 OR move the V2/V3 layer into yours</div>';
    } catch (e) { /* cosmetic panel; status line already shown */ }
    hideReviewProgress();
    reviewLogger.info('=== REVIEW-OVERLAY DONE: ' + result.seqName + ' (' + result.placed + ' placed, ' + result.skipped + ' skipped) ===');
  } catch (err) {
    setReviewStatus('Error: ' + err.message, 'error', err);
    reviewLogger.error('Review-overlay failed: ' + err.message);
    hideReviewProgress();
  } finally {
    reviewState.building = false;
    $('btn-build-review-overlay').removeAttribute('disabled');
  }
}

/**
 * Build REVIEW v3 — CUTTABLE V1 + overlay enrichment (build_model: review_cut_overlay).
 *
 * Unlike Review-Overlay (render kept FULL on V1), v3 rebuilds V1 from the render's per-line
 * keep-segments (base_segments[]) so V1 can be CUT (tech cleanup), then overlays the enrichment
 * on V2/V3 (VO on A1 preserved). Cut render regions become a red DeletedScene.
 *
 * Input: 00_Setup/05_Review/YTCR01_review_brief_v3.json (schema ytai-review-v3), produced by
 *        _analysis/ytcr01_review_v3_build.py. One-click: auto-finds the newest *_review_brief_v3.json.
 */
async function buildReviewV3() {
  if (reviewState.building) { reviewLogger.warn('Review build already in progress'); return; }
  reviewState.building = true;
  $('btn-build-review-v3').setAttribute('disabled', 'true');
  setReviewStatus('Building Review v3 (cuttable V1 + overlays)...', 'waiting');
  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');
    var folderPath = projectState.folderPath;
    var code = assemblyState.projectCode || extractProjectCode(projectState.projectName || '');

    // 1) Locate the v3 brief (newest *_review_brief_v3.json in 05_Review, else _analysis).
    var briefData = null, briefName = '';
    var searchDirs = [
      folderPath + '/00_Setup/06_Enrichment',          // canonical enrichment stage
      folderPath + '/00_Setup/02_Assembly/parts',       // UXP input mirror
      folderPath + '/00_Setup/05_Review',
      folderPath + '/01_Media/Source/Setup/Review/_analysis',
    ];
    for (var di = 0; di < searchDirs.length && !briefData; di++) {
      try {
        var dEntry = await uxpfs.getEntryWithUrl('file://' + searchDirs[di]);
        var dFiles = await dEntry.getEntries();
        var best = null;
        for (var fi = 0; fi < dFiles.length; fi++) {
          if (dFiles[fi].isFile && /review_brief_v3\.json$/i.test(dFiles[fi].name)) {
            if (!best || dFiles[fi].name.localeCompare(best.name) > 0) best = dFiles[fi];
          }
        }
        if (best) { briefData = JSON.parse(await best.read()); briefName = best.name; }
      } catch (e) { /* dir may not exist */ }
    }
    if (!briefData) throw new Error('No *_review_brief_v3.json found — run ytcr01_review_v3_build.py --mode final');
    if (!Array.isArray(briefData.overlays) || !briefData.overlays.length)
      throw new Error('Brief has no overlays[] — wrong file?');
    reviewLogger.info('Review v3 brief: ' + briefName + ' — full render V1, ' +
      briefData.overlays.length + ' overlays, ' + (briefData.cut_suggestions || []).length + ' cut-suggestions');

    var proj = briefData.project || {};
    var renderName = proj.edited_video || 'YTCR1_v9_Arty_Dzis.mp4';
    var renderPath = proj.edited_video_path || (folderPath + '/02_Exports/' + renderName);
    var overlays = briefData.overlays || [];

    // 2) clipMap (source bin) + render + overlay media (auto-import missing into _Review_inserts).
    var clipMap = {};
    try { var sb = await findSourceBin(project); if (sb) clipMap = await buildClipMap(sb, reviewLogger); }
    catch (e) { reviewLogger.warn('clipMap unavailable: ' + e.message); }

    // render
    var renderItem = await findProjectItemByName(project, renderName, reviewLogger);
    if (!renderItem) {
      try { await project.importFiles([renderPath]); } catch (ie) { reviewLogger.warn('render import: ' + ie.message); }
      renderItem = await findProjectItemByName(project, renderName, reviewLogger);
    }
    if (renderItem) { clipMap[renderName] = renderItem; clipMap[renderName.replace(/\.[^.]+$/, '')] = renderItem; }
    else throw new Error('Render not resolvable for V1: ' + renderName);

    // overlay media
    setReviewProgress(20, 'Resolving insert media...');
    var missing = [], seenP = {};
    for (var qi = 0; qi < overlays.length; qi++) {
      var sf = overlays[qi].source_file, sp = overlays[qi].source_path;
      if (!sf || !sp) continue;
      if (clipMap[sf] || clipMap[sf.replace(/\.[^.]+$/, '')]) continue;
      if (seenP[sp]) continue; seenP[sp] = 1;
      missing.push({ sf: sf, sp: sp });
    }
    if (missing.length) {
      reviewLogger.info('Auto-importing ' + missing.length + ' insert clip(s) → _Review_inserts...');
      var binCast = null;
      try {
        var binItem = await findProjectItemByName(project, '_Review_inserts', reviewLogger);
        if (!binItem) {
          var rootItem = await project.getRootItem();
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) { ca.addAction(rootItem.createBinAction('_Review_inserts', true)); }, 'Create _Review_inserts bin');
          });
          binItem = await findProjectItemByName(project, '_Review_inserts', reviewLogger);
        }
        binCast = binItem ? ppro.FolderItem.cast(binItem) : null;
      } catch (eb) { reviewLogger.warn('bin create skipped: ' + eb.message); }
      var paths = missing.map(function (x) { return x.sp; });
      try {
        if (binCast) await project.importFiles(paths, true, binCast, false); else await project.importFiles(paths);
      } catch (eImp) {
        reviewLogger.warn('batch import failed (' + eImp.message + ') — one-by-one');
        for (var pj = 0; pj < paths.length; pj++) { try { if (binCast) await project.importFiles([paths[pj]], true, binCast, false); else await project.importFiles([paths[pj]]); } catch (e2) { reviewLogger.debug('import ' + paths[pj] + ': ' + (e2 && e2.message)); } }
      }
      var got = 0;
      for (var ri = 0; ri < missing.length; ri++) {
        var it = await findProjectItemByName(project, missing[ri].sf, reviewLogger);
        if (it) { clipMap[missing[ri].sf] = it; clipMap[missing[ri].sf.replace(/\.[^.]+$/, '')] = it; got++; }
      }
      reviewLogger.info('Auto-import: ' + got + '/' + missing.length + ' insert clips resolved.');
    }

    // 3) Build the cuttable-V1 + overlay sequence via partsBuilder (review_cut_overlay).
    var part = {
      code: code, name: 'Review_v3', sequence_name: proj.sequence_name || (code + '_5_Review_v3'),
      color: 'Mango', fps: proj.fps || 25,
      build_model: 'overlay_on_base',           // FULL render on V1 (NOT cut) — proven path
      base_clip: renderName, base_clip_path: renderPath,
      markers: false,                            // NO markers (Roman: clutter; montage HTML is the ref)
    };
    try { await project.save(); } catch (e) { reviewLogger.debug('save: ' + (e && e.message)); }
    setReviewProgress(40, 'Building ' + part.sequence_name + ' (V1 cut + overlays)...');
    const result = await buildPartSequence(project, clipMap, part, overlays, reviewLogger, assemblyState.projectSettings);
    try { await project.save(); } catch (e) { reviewLogger.debug('save: ' + (e && e.message)); }

    // 4) No DeletedScene, NO markers — V1 is the full render; V2/V3 = visualization overlays.
    var msg = 'Review v3: ' + result.seqName + ' — full render V1 + ' +
      result.placed + ' overlays on V2/V3' + (result.skipped ? ' (' + result.skipped + ' skipped)' : '') + ' · no markers';
    setReviewStatus(msg, result.skipped ? 'warning' : 'ready');
    try {
      var vp = $('review-validation'); vp.style.display = 'block';
      vp.innerHTML =
        '<div class="val-line"><b>' + escapeHtml(result.seqName) + '</b> (full render V1 + V2/V3 overlays)</div>' +
        '<div class="val-line">V1/A1: full v9 render (NOT cut). VO intact.</div>' +
        '<div class="val-line">V2/V3: ' + result.placed + (result.skipped ? ' (+' + result.skipped + ' not in bin)' : '') + ' visualization overlays (no markers)</div>' +
        '<div class="val-line">Reference: YTCR01_v9_review_v3_montage.html</div>' +
        '<div class="val-line">IMPORTANT: Relink media in Premiere after import.</div>';
    } catch (e) { /* cosmetic panel; status line already shown */ }
    hideReviewProgress();
    reviewLogger.info('=== REVIEW v3 DONE: ' + result.seqName + ' (full V1, ' + result.placed + ' overlays, no markers) ===');
  } catch (err) {
    setReviewStatus('Error: ' + err.message, 'error', err);
    reviewLogger.error('Review v3 failed: ' + err.message);
    hideReviewProgress();
  } finally {
    reviewState.building = false;
    $('btn-build-review-v3').removeAttribute('disabled');
  }
}

/**
 * Export the ACTIVE sequence to a comprehensive JSON (for Claude round-trip).
 * After the editor edits the timeline (cut / move / add / remove on any track), this writes the
 * WHOLE reassembled sequence — every track, every clip with source file + media path + in/out +
 * timeline position + duration, plus markers + sequence meta — to 00_Setup/05_Review/.
 */
async function exportSequenceJson() {
  setReviewStatus('Exporting sequence → JSON...', 'waiting');
  $('btn-export-sequence-json').setAttribute('disabled', 'true');
  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');
    var seq = await project.getActiveSequence();
    if (!seq) throw new Error('No active sequence — open the review sequence in the timeline first');
    var fps = 25;
    try { var tb = await seq.getTimebase(); fps = tb ? Math.round(254016000000 / Number(tb)) : 25; } catch (e) { /* dumpSequence re-reads timebase; 25 is only a seed */ }

    // Full per-track / per-clip dump (reuses the proven dumpSequence extractor).
    var data = await dumpSequence(seq, fps, {});
    data.project_code = assemblyState.projectCode || extractProjectCode(projectState.projectName || '');
    try { data.exported_at = new Date().toISOString(); } catch (e) { data.exported_at = ''; }

    // Markers (best-effort — API varies by Premiere version).
    data.markers = [];
    try {
      var mk = null;
      try { if (ppro.Markers && ppro.Markers.getMarkers) mk = await ppro.Markers.getMarkers(seq); } catch (e) { /* optional API on this build; next probe handles it */ }
      if (!mk) { try { if (typeof seq.getMarkers === 'function') mk = await seq.getMarkers(); } catch (e) { reviewLogger.debug('seq.getMarkers: ' + (e && e.message)); } }
      var list = null;
      if (mk) { try { list = (typeof mk.getMarkers === 'function') ? await mk.getMarkers() : (Array.isArray(mk) ? mk : null); } catch (e) { reviewLogger.debug('markers list: ' + (e && e.message)); } }
      if (list && list.length) {
        for (var mi = 0; mi < list.length; mi++) {
          var m = list[mi];
          try {
            var st = m.start && (m.start.seconds != null ? m.start.seconds : (typeof m.start.ticks !== 'undefined' ? Number(m.start.ticks) / 254016000000 : undefined));
            if (st === undefined && typeof m.getStart === 'function') {
              try { var gs = await m.getStart(); st = gs && (gs.seconds != null ? gs.seconds : Number(gs.ticks) / 254016000000); } catch (e) { /* optional API on this build; start_sec stays unset */ }
            }
            var mRec = { name: m.name || '', comment: (m.comments != null ? m.comments : (m.comment || '')), start_sec: st };
            // Маркер-диапазон «вырезать/сократить»: длительность, цвет (MARKER_COLOR_INDEX: Red=1, White=5…), тип.
            try { if (typeof m.getDuration === 'function') { var md = await m.getDuration(); mRec.duration_sec = md && (md.seconds != null ? md.seconds : Number(md.ticks) / 254016000000); } } catch (e) { reviewLogger.debug('marker ' + mi + ' duration: ' + (e && e.message)); }
            try { if (typeof m.getColorIndex === 'function') mRec.color_index = await m.getColorIndex(); } catch (e) { reviewLogger.debug('marker ' + mi + ' color: ' + (e && e.message)); }
            try { if (typeof m.getType === 'function') mRec.type = await m.getType(); } catch (e) { /* marker type is informational; optional API */ }
            try { if (!mRec.name && typeof m.getName === 'function') mRec.name = await m.getName(); } catch (e) { /* fallback when .name property is empty; non-fatal */ }
            try { if (!mRec.comment && typeof m.getComments === 'function') mRec.comment = await m.getComments(); } catch (e) { reviewLogger.debug('marker ' + mi + ' comments: ' + (e && e.message)); }
            data.markers.push(mRec);
          } catch (e) { reviewLogger.debug('marker ' + mi + ' skipped: ' + (e && e.message)); }
        }
      }
    } catch (e) { reviewLogger.debug('markers read: ' + e.message); }

    var nclips = 0, ndisabled = 0;
    for (var tk in data.tracks) {
      nclips += (data.tracks[tk] || []).length;
      ndisabled += (data.tracks[tk] || []).filter(function (c) { return c && c.disabled; }).length;
    }
    data.disabled_clips = ndisabled;

    var revFolder = await uxpfs.getEntryWithUrl('file://' + projectState.folderPath + '/00_Setup/05_Review');
    var ts;
    try { ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19); } catch (e) { ts = 'export'; }
    var fname = (seq.name || 'sequence') + '_export_' + ts + '.json';
    var outFile = await revFolder.createFile(fname, { overwrite: true });
    await outFile.write(JSON.stringify(data, null, 2));
    var outPath = projectState.folderPath + '/00_Setup/05_Review/' + fname;

    // Copy the file path to clipboard so it can be pasted straight to Claude.
    var copied = false;
    try { await navigator.clipboard.writeText(outPath); copied = true; } catch (e) { reviewLogger.debug('clipboard: ' + e.message); }

    setReviewStatus('Exported: ' + fname + ' (' + nclips + ' clips, ' + (ndisabled ? ndisabled + ' disabled ✂, ' : '') + data.markers.length + ' markers)' + (copied ? ' — link copied' : ''), 'ready');
    reviewLogger.info('=== SEQUENCE EXPORTED → ' + outPath + ' (' + nclips + ' clips, ' + data.markers.length + ' markers, tracks ' + Object.keys(data.tracks).join(',') + ') ===');
    try {
      var vp = $('review-validation'); vp.style.display = 'block';
      vp.innerHTML = '<div class="val-line"><b>Exported for Claude</b>' + (copied ? ' · 📋 link copied' : '') + '</div>' +
        '<div class="val-line">' + escapeHtml(outPath) + '</div>' +
        '<div class="val-line">' + nclips + ' clips · ' + data.markers.length + ' markers · tracks ' + escapeHtml(Object.keys(data.tracks).join(', ')) + '</div>';
    } catch (e) { /* cosmetic panel; export already written and logged */ }
  } catch (err) {
    setReviewStatus('Export error: ' + err.message, 'error', err);
    reviewLogger.error('Export sequence failed: ' + err.message);
  } finally {
    var b = $('btn-export-sequence-json'); if (b) b.removeAttribute('disabled');
  }
}

async function buildReview() {
  if (reviewState.building) {
    reviewLogger.warn('Review build already in progress');
    return;
  }

  // Need either pipelineResult (from processReview) or manual data
  var pipelineResult = reviewState.pipelineResult;
  if (!pipelineResult || !pipelineResult.video) {
    reviewLogger.error('No pipeline result — run Process Review first');
    setReviewStatus('Run Process Review first', 'error');
    return;
  }

  reviewState.building = true;
  setReviewStatus('Building review...', 'waiting');
  $('btn-build-review').setAttribute('disabled', 'true');

  var startTime = Date.now();

  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere project');

    var reviewProjectCode = assemblyState.projectCode || extractProjectCode(projectState.projectName || '');

    // Determine review version: scan 00_Setup/05_Review/ for existing _out.json and _in.json
    var reviewVersion = 1;
    try {
      var revDetectDir = projectState.folderPath + '/00_Setup/05_Review';
      var revDetectEntry = await uxpfs.getEntryWithUrl('file://' + revDetectDir);
      var revDetectFiles = await revDetectEntry.getEntries();
      var revVerRe = new RegExp('_5_Review_v(\\d+)');
      for (var rvi = 0; rvi < revDetectFiles.length; rvi++) {
        var rvm = revDetectFiles[rvi].name.match(revVerRe);
        if (rvm) {
          var rvn = parseInt(rvm[1], 10);
          if (rvn > reviewVersion) reviewVersion = rvn;
        }
      }
    } catch (e) { /* Review dir may not exist yet */ }
    var reviewSeqName = reviewProjectCode + '_5_Review_v' + reviewVersion;

    reviewLogger.info('=== REVIEW BUILD START ===');
    reviewLogger.info('Project code: ' + reviewProjectCode);
    reviewLogger.info('Video: ' + pipelineResult.video);

    // Step 1: Save project
    setReviewProgress(10, 'Saving backup...');
    try { await project.save(); reviewLogger.info('Project saved'); } catch (e) { reviewLogger.debug('backup save: ' + (e && e.message)); }

    // Step 2: Import edited video
    setReviewProgress(20, 'Importing edited video...');
    var videoFileName = pipelineResult.video.split('/').pop();

    // Search in project (BFS through all bins)
    var editedVideoItem = await findProjectItemByName(project, videoFileName, reviewLogger);

    // Import if not found — into 00_Source bin (create if missing)
    if (!editedVideoItem) {
      reviewLogger.info('Importing into 00_Source: ' + videoFileName);
      try {
        var rootItem = await project.getRootItem();
        var rootItems = await rootItem.getItems();
        var sourceBin = null;
        for (var sbi = 0; sbi < rootItems.length; sbi++) {
          if (rootItems[sbi].name === BIN_NAMES.SOURCE) {
            sourceBin = ppro.FolderItem.cast(rootItems[sbi]);
            break;
          }
        }
        // Create 00_Source if it doesn't exist
        if (!sourceBin) {
          reviewLogger.info('Creating ' + BIN_NAMES.SOURCE + ' bin');
          project.lockedAccess(function() {
            project.executeTransaction(function(ca) {
              ca.addAction(ppro.FolderItem.createAddItemAction(BIN_NAMES.SOURCE));
            }, 'Create ' + BIN_NAMES.SOURCE);
          });
          rootItems = await rootItem.getItems();
          for (var sbi2 = 0; sbi2 < rootItems.length; sbi2++) {
            if (rootItems[sbi2].name === BIN_NAMES.SOURCE) {
              sourceBin = ppro.FolderItem.cast(rootItems[sbi2]);
              break;
            }
          }
          if (sourceBin) reviewLogger.info(BIN_NAMES.SOURCE + ' bin created');
        }
        await project.importFiles([pipelineResult.video], true, sourceBin, false);
        reviewLogger.info('importFiles completed, searching for item...');
        editedVideoItem = await findProjectItemByName(project, videoFileName, reviewLogger);
      } catch (importErr) {
        throw new Error('Failed to import video: ' + importErr.message);
      }
    }

    if (!editedVideoItem) {
      throw new Error('Could not find or import video: ' + videoFileName);
    }
    reviewLogger.info('Video ready: ' + editedVideoItem.name);

    // Step 3: Create sequence from video
    setReviewProgress(50, 'Creating sequence...');

    // Check if sequence already exists — REAL sequences only. findProjectItemByName
    // matches any item type incl. stem matches (the render imported at Step 2 has
    // the same stem as the sequence name), which skipped creation and left later
    // insertions targeting whatever timeline happened to be active.
    var existingSeq = null;
    try {
      var reviewSeqEntries = await listProjectSequences(project, reviewLogger);
      for (var rse = 0; rse < reviewSeqEntries.length; rse++) {
        if (reviewSeqEntries[rse].name === reviewSeqName) { existingSeq = reviewSeqEntries[rse].seq; break; }
      }
    } catch (e) { reviewLogger.debug('Sequence lookup failed: ' + e.message); }

    if (!existingSeq) {
      reviewLogger.info('Creating sequence: ' + reviewSeqName);
      var castClip = ppro.ClipProjectItem.cast(editedVideoItem);
      var clipForSeq = castClip || editedVideoItem;
      var reviewSeq = null;
      try {
        reviewSeq = await project.createSequenceFromMedia(reviewSeqName, [clipForSeq]);
      } catch (seqErr) {
        reviewLogger.warn('createSequenceFromMedia failed: ' + seqErr.message);
      }
      if (!reviewSeq) {
        // Fallback: create empty sequence then insert clip
        reviewLogger.info('Fallback: createSequence + insert clip');
        try {
          reviewSeq = await project.createSequence(reviewSeqName);
          if (reviewSeq) {
            var seqEditor = ppro.SequenceEditor.getEditor(reviewSeq);
            var insertTime = ppro.TickTime.createWithSeconds(0);
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                ca.addAction(seqEditor.createInsertProjectItemAction(editedVideoItem, insertTime, 0, 0, true));
              }, 'Review: insert video');
            });
            reviewLogger.info('Sequence created (fallback): ' + reviewSeqName);
          }
        } catch (fbErr) {
          throw new Error('Failed to create Review sequence: ' + fbErr.message);
        }
      } else {
        reviewLogger.info('Sequence created: ' + reviewSeqName);
      }
      if (!reviewSeq) {
        throw new Error('Could not create Review sequence: ' + reviewSeqName);
      }
    } else {
      reviewLogger.info('Sequence already exists: ' + reviewSeqName);
      // Make it active so the caption/insert steps below target THIS sequence.
      try { await project.setActiveSequence(existingSeq); } catch (e) { reviewLogger.warn('setActiveSequence failed, inserts may hit wrong timeline: ' + (e && e.message)); }
    }

    // Step 4: Import captions & transcript SRT (direct paths from pipeline)
    setReviewProgress(70, 'Importing captions...');
    var revSuffix = '5_Review_v' + reviewVersion;

    if (pipelineResult.captions_srt) {
      try {
        await importSrtDirect(project, pipelineResult.captions_srt, reviewProjectCode, revSuffix, 'Review Captions', reviewLogger);
      } catch (capErr) {
        reviewLogger.warn('Captions import failed (non-fatal): ' + capErr.message);
      }
    } else {
      reviewLogger.info('No captions SRT path in pipeline result — skipping');
    }

    if (pipelineResult.transcript_srt) {
      try {
        await importSrtDirect(project, pipelineResult.transcript_srt, reviewProjectCode, revSuffix, 'Review Transcript', reviewLogger);
      } catch (trErr) {
        reviewLogger.warn('Transcript import failed (non-fatal): ' + trErr.message);
      }
    } else {
      reviewLogger.info('No transcript SRT path in pipeline result — skipping');
    }

    // Step 4b: Insert source clips on V1 from insertions in _in.json
    setReviewProgress(80, 'Inserting clips on V1...');
    var insertionCount = 0;
    try {
      // Load insertions from latest _in.json in 00_Setup/05_Review/
      var insertions = [];
      try {
        var revBriefDir = projectState.folderPath + '/00_Setup/05_Review';
        var revBriefEntry = await uxpfs.getEntryWithUrl('file://' + revBriefDir);
        var revBriefFiles = await revBriefEntry.getEntries();
        var latestIn = null;
        var latestInVer = 0;
        var inJsonRe = new RegExp('_Review_v(\\d+)_in\\.json$');
        for (var rbi = 0; rbi < revBriefFiles.length; rbi++) {
          var rbm = revBriefFiles[rbi].name.match(inJsonRe);
          if (rbm) {
            var rbv = parseInt(rbm[1], 10);
            if (rbv > latestInVer) { latestInVer = rbv; latestIn = revBriefFiles[rbi]; }
          }
        }
        if (latestIn) {
          var inContent = await latestIn.read({ format: require('uxp').storage.formats.utf8 });
          var inData = JSON.parse(inContent);
          insertions = inData.insertions || [];
          reviewLogger.info('Loaded insertions from ' + latestIn.name + ': ' + insertions.length + ' total');
        }
      } catch (loadErr) {
        reviewLogger.debug('No insertions found: ' + loadErr.message);
      }

      var recommended = insertions.filter(function(ins) { return ins.recommended === true; });
      reviewLogger.info('Recommended insertions: ' + recommended.length);

      if (recommended.length > 0) {
        var activeSeq = await project.getActiveSequence();
        if (!activeSeq) activeSeq = await project.getActiveSequence();

        if (activeSeq) {
          // Anti-duplication: check if V1 already has multiple clips (inserts from prior run)
          var skipInserts = false;
          try {
            var checkTrack = await activeSeq.getVideoTrack(0);
            var checkItems = null;
            try { checkItems = checkTrack.getTrackItems(1, false); } catch (ex) { /* fallback below handles it */ }
            if (!checkItems) try { checkItems = checkTrack.getTrackItems(); } catch (ex) { reviewLogger.debug('V1 getTrackItems fallback failed: ' + (ex && ex.message)); }
            if (checkItems && checkItems.length > 1) {
              reviewLogger.warn('V1 already has ' + checkItems.length + ' clips — skipping insertions to avoid duplicates. Delete sequence and rebuild if needed.');
              skipInserts = true;
            }
          } catch (chkErr) {
            reviewLogger.debug('V1 check failed: ' + chkErr.message);
          }

          if (skipInserts) {
            reviewLogger.info('Insertions skipped (anti-duplication)');
          } else {

          var revSeqEditor = ppro.SequenceEditor.getEditor(activeSeq);

          // Build clipMap from 00_Source bin (BFS)
          var revClipMap = {};
          try {
            var revRootItem = await project.getRootItem();
            var revRootItems = await revRootItem.getItems();
            var revSourceBin = null;
            for (var rsbi = 0; rsbi < revRootItems.length; rsbi++) {
              if (revRootItems[rsbi].name === BIN_NAMES.SOURCE) {
                revSourceBin = ppro.FolderItem.cast(revRootItems[rsbi]);
                break;
              }
            }
            if (revSourceBin) {
              var scanQueue = [revSourceBin];
              while (scanQueue.length > 0) {
                var scanFolder = scanQueue.shift();
                var scanItems = await scanFolder.getItems();
                for (var sci = 0; sci < scanItems.length; sci++) {
                  var scanItem = scanItems[sci];
                  if (scanItem.name) {
                    revClipMap[scanItem.name] = scanItem;
                    var noExt = scanItem.name.replace(/\.[^.]+$/, '');
                    if (noExt !== scanItem.name) revClipMap[noExt] = scanItem;
                  }
                  try {
                    var subF = ppro.FolderItem.cast(scanItem);
                    if (subF) scanQueue.push(subF);
                  } catch (e) { /* cast throws on non-folder items; leaf handled above */ }
                }
              }
              reviewLogger.info('ClipMap: ' + Object.keys(revClipMap).length + ' items from 00_Source');
            } else {
              reviewLogger.warn('00_Source bin not found — cannot insert clips');
            }
          } catch (cmErr) {
            reviewLogger.warn('ClipMap build failed: ' + cmErr.message);
          }

          function parseTcSec(tc) {
            if (!tc) return 0;
            var parts = tc.replace(',', '.').split(':');
            if (parts.length === 2) return parseInt(parts[0]) * 60 + parseFloat(parts[1]);
            if (parts.length === 3) return parseInt(parts[0]) * 3600 + parseInt(parts[1]) * 60 + parseFloat(parts[2]);
            return parseFloat(tc) || 0;
          }

          // Sort DESCENDING by insert position — insert from end to start
          // to avoid offset shifts affecting earlier insertions.
          // For same insert_at_tc: REVERSE array order so createInsertProjectItemAction
          // (which pushes content right) produces the intended sequence.
          recommended.forEach(function(r, i) { r._origIdx = i; });
          recommended.sort(function(a, b) {
            var diff = parseTcSec(b.insert_at_tc) - parseTcSec(a.insert_at_tc);
            if (diff !== 0) return diff;
            return b._origIdx - a._origIdx; // reverse array order for same tc
          });

          // Apply color to edited video (Cyan) before insertions
          try {
            var CYAN_IDX = 10; // ppro label color index for Cyan
            project.lockedAccess(function() {
              project.executeTransaction(function(ca) {
                ca.addAction(editedVideoItem.createSetColorLabelAction(CYAN_IDX));
              }, 'Review: color edited video Cyan');
            });
            reviewLogger.info('Edited video colored Cyan');
          } catch (colErr) {
            reviewLogger.debug('Color label failed: ' + colErr.message);
          }

          var GREEN_IDX = 4; // ppro label color index for Green

          for (var ini = 0; ini < recommended.length; ini++) {
            var ins = recommended[ini];
            var rawItem = revClipMap[ins.source_file] || revClipMap[ins.source_file.replace(/\.[^.]+$/, '')];
            if (!rawItem) {
              reviewLogger.warn('[' + ins.insertion_id + '] Source not found: ' + ins.source_file);
              continue;
            }

            // Color insertion clip Green
            try {
              project.lockedAccess(function() {
                project.executeTransaction(function(ca) {
                  ca.addAction(rawItem.createSetColorLabelAction(GREEN_IDX));
                }, 'Color: ' + ins.insertion_id);
              });
            } catch (colErr2) { /* label colour is cosmetic; insert proceeds */ }

            var castClip2 = ppro.ClipProjectItem.cast(rawItem);
            var clipForTrim2 = castClip2 || rawItem;

            // Set source in/out (trim)
            var srcIn = ppro.TickTime.createWithSeconds(parseTcSec(ins.source_tc_in));
            var srcOut = ppro.TickTime.createWithSeconds(parseTcSec(ins.source_tc_out));
            try {
              project.lockedAccess(function() {
                project.executeTransaction(function(ca) {
                  ca.addAction(clipForTrim2.createSetInOutPointsAction(srcIn, srcOut));
                }, 'Trim: ' + ins.insertion_id);
              });
            } catch (trimErr) {
              reviewLogger.debug('Trim failed: ' + ins.insertion_id + ': ' + trimErr.message);
            }

            // INSERT on V1 (videoTrack=0, audioTrack=0, limitShift=true)
            // This splits existing content and pushes everything right.
            // Sorted DESCENDING: later-timeline inserts go first, so their push
            // doesn't affect earlier positions. No offset accumulation needed.
            var tlPos = ppro.TickTime.createWithSeconds(parseTcSec(ins.insert_at_tc));
            var insOk = false;
            try {
              project.lockedAccess(function() {
                project.executeTransaction(function(ca) {
                  ca.addAction(revSeqEditor.createInsertProjectItemAction(rawItem, tlPos, 0, 0, true));
                }, 'Review V1 insert: ' + ins.insertion_id);
              });
              insOk = true;
            } catch (insErr) {
              reviewLogger.error('[' + ins.insertion_id + '] V1 insert failed: ' + insErr.message);
            }

            // Clear source in/out
            try {
              project.lockedAccess(function() {
                project.executeTransaction(function(ca) {
                  ca.addAction(clipForTrim2.createClearInOutPointsAction());
                }, 'Clear: ' + ins.insertion_id);
              });
            } catch (clrErr) { /* best-effort cleanup; next insert sets its own in/out */ }

            if (insOk) {
              insertionCount++;
              reviewLogger.info('[' + ins.insertion_id + '] V1 @ ' + ins.insert_at_tc + ' ← ' + ins.source_file + ' ' + ins.source_tc_in + '-' + ins.source_tc_out + ' (' + ins.description + ')');
            }
          }

          } // end skipInserts else
        } else {
          reviewLogger.warn('No active sequence for insertions');
        }
      }
    } catch (insErr2) {
      reviewLogger.warn('Clip insertion failed (non-fatal): ' + insErr2.message);
    }
    if (insertionCount > 0) {
      reviewLogger.info('Inserted ' + insertionCount + ' clips on V1 (Green)');
    }

    // Step 4c: Build DeletedScene sequence from deleted_segments in _in.json
    try {
      var delSegments = [];
      try {
        var delBriefDir = projectState.folderPath + '/00_Setup/05_Review';
        var delBriefEntry = await uxpfs.getEntryWithUrl('file://' + delBriefDir);
        var delBriefFiles = await delBriefEntry.getEntries();
        var delLatestIn = null;
        var delLatestInVer = 0;
        var delInRe = new RegExp('_Review_v(\\d+)_in\\.json$');
        for (var dbi = 0; dbi < delBriefFiles.length; dbi++) {
          var dbm = delBriefFiles[dbi].name.match(delInRe);
          if (dbm) {
            var dbv = parseInt(dbm[1], 10);
            if (dbv > delLatestInVer) { delLatestInVer = dbv; delLatestIn = delBriefFiles[dbi]; }
          }
        }
        if (delLatestIn) {
          var delContent = await delLatestIn.read({ format: require('uxp').storage.formats.utf8 });
          var delData = JSON.parse(delContent);
          delSegments = delData.deleted_segments || [];
        }
      } catch (delLoadErr) {
        reviewLogger.debug('No deleted_segments found: ' + delLoadErr.message);
      }

      if (Object.keys(revClipMap).length > 0) {
        setReviewProgress(88, 'Building DeletedScene...');
        var delParsed = delSegments.map(function(d) {
          return {
            segmentId: d.segment_id || '',
            removedIn: d.removed_in || '',
            reason: d.reason || '',
            sourceFile: d.source_file || '',
            sourceTcIn: d.source_tc_in || '',
            sourceTcOut: d.source_tc_out || '',
            durationSec: d.duration_sec || 0,
            speaker: d.speaker || '',
            transcript: d.transcript || ''
          };
        });
        var delResult = await buildReviewDeletedScene(
          project, revClipMap, delParsed, reviewProjectCode,
          reviewVersion, 25, reviewLogger
        );
        if (delResult.clipCount > 0) {
          reviewLogger.info('DeletedScene built: ' + delResult.seqName + ' (' + delResult.clipCount + ' clips)');
        }
      } else {
        reviewLogger.info('No deleted segments — DeletedScene skipped');
      }
    } catch (delErr) {
      reviewLogger.warn('DeletedScene build failed (non-fatal): ' + delErr.message);
    }

    // Step 5: Save project
    setReviewProgress(95, 'Saving...');
    try { await project.save(); } catch (e) { reviewLogger.warn('Final project save failed: ' + (e && e.message)); }

    var elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    setReviewProgress(100, 'Complete!');
    reviewLogger.info('=== REVIEW BUILD COMPLETE (' + elapsed + 's) — ' + insertionCount + ' V2 insertions ===');
    $('btn-build-review').classList.add('btn-done');
    $('btn-export-review-markers').removeAttribute('disabled');
    setReviewStatus('Review built! Sequence: ' + reviewSeqName, 'ready');
    updateLogPath('review', reviewLogger.getLastSavedPath());

  } catch (err) {
    reviewLogger.error('REVIEW BUILD FAILED: ' + err.message, err);
    setReviewStatus('Build failed: ' + err.message, 'error', err);
  } finally {
    reviewState.building = false;
    $('btn-build-review').removeAttribute('disabled');
  }
}

/**
 * Export Review Markers — reads markers from active _5_Review sequence,
 * writes JSON + HTML to 00_Setup/05_Review/ with versioning (v{N}_out.json).
 * Same structure as Assembly exportMarkers but output goes to Review folder.
 */
async function exportReviewMarkers() {
  var project = await ppro.Project.getActiveProject();
  if (!project) { setReviewStatus('No active project', 'error'); return; }
  if (!projectState.folderPath) { setReviewStatus('Select project folder first', 'error'); return; }

  reviewLogger.info('=== Export Review Markers ===');
  setReviewStatus('Reading markers...', 'waiting');
  $('btn-export-review-markers').setAttribute('disabled', 'true');

  try {
    var seq = await project.getActiveSequence();
    if (!seq) throw new Error('No active sequence — open Review sequence first');
    var seqName = seq.name;
    reviewLogger.info('Active sequence: ' + seqName);

    // Read markers
    var markersOwner = await ppro.Markers.getMarkers(seq);
    if (!markersOwner) throw new Error('Cannot get markers from sequence');
    var rawMarkers = markersOwner.getMarkers();
    reviewLogger.info('Raw markers: ' + (rawMarkers ? rawMarkers.length : 0));

    var markers = [];
    if (rawMarkers && rawMarkers.length > 0) {
      for (var mi = 0; mi < rawMarkers.length; mi++) {
        var m = rawMarkers[mi];
        var mStart = null;
        try { mStart = m.getStart ? m.getStart() : m.startTime; } catch (e) { reviewLogger.debug('marker ' + mi + ' start: ' + (e && e.message)); }
        var mDur = null;
        try { mDur = m.getDuration ? m.getDuration() : m.duration; } catch (e) { reviewLogger.debug('marker ' + mi + ' duration: ' + (e && e.message)); }
        var mComment = '';
        try { mComment = m.comments || (m.getComments ? m.getComments() : '') || m.comment || ''; } catch (e) { reviewLogger.debug('marker ' + mi + ' comment: ' + (e && e.message)); }
        var mName = '';
        try { mName = m.name || (m.getName ? m.getName() : '') || ''; } catch (e) { reviewLogger.debug('marker ' + mi + ' name: ' + (e && e.message)); }
        var posSec = mStart ? (typeof mStart === 'object' ? tickSec(mStart) : parseFloat(mStart)) : 0;
        var durSec = mDur ? (typeof mDur === 'object' ? tickSec(mDur) : parseFloat(mDur)) : 0;
        markers.push({
          name: mName,
          position_sec: Math.round(posSec * 100) / 100,
          duration_sec: durSec > 0 ? Math.round(durSec * 100) / 100 : undefined,
          is_chapter: durSec > 0,
          comment: mComment
        });
      }
    }
    reviewLogger.info('Parsed markers: ' + markers.length);

    // Read V1 timeline clips
    var timelineClips = [];
    try {
      var v1Track = await seq.getVideoTrack(0);
      var trackItems = null;
      try { trackItems = v1Track.getTrackItems(1, false); } catch (ex) { /* fallback below handles it */ }
      if (!trackItems) try { trackItems = v1Track.getTrackItems(); } catch (ex) { reviewLogger.debug('V1 getTrackItems fallback failed: ' + (ex && ex.message)); }
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
        reviewLogger.info('Timeline V1 clips: ' + timelineClips.length);
      }
    } catch (tlErr) {
      reviewLogger.warn('Could not read V1 TrackItems: ' + tlErr.message);
    }

    // Match with review transcript for text
    try {
      var reviewDir = projectState.folderPath + '/00_Setup/05_Review';
      var revDirEntry = await uxpfs.getEntryWithUrl('file://' + reviewDir);
      var revFiles = await revDirEntry.getEntries();
      var txFile = null;
      for (var rf = 0; rf < revFiles.length; rf++) {
        if (revFiles[rf].name.endsWith('_review_transcript.json')) {
          txFile = revFiles[rf];
          break;
        }
      }
      if (txFile) {
        var txRaw = await txFile.read({ format: require('uxp').storage.formats.utf8 });
        var txData = JSON.parse(txRaw);
        var txSegs = txData.segments || [];
        // Match each timeline clip
        for (var ci = 0; ci < timelineClips.length; ci++) {
          var clip = timelineClips[ci];
          var texts = [];
          for (var si = 0; si < txSegs.length; si++) {
            var sg = txSegs[si];
            if (sg.start < (clip.timeline_start_sec + clip.duration_sec) && sg.end > clip.timeline_start_sec) {
              texts.push(sg.text || '');
            }
          }
          clip.transcript_text = texts.join(' ');
        }
        reviewLogger.info('Matched review transcript for clips');
      }
    } catch (txErr) {
      reviewLogger.debug('Review transcript matching skipped: ' + txErr.message);
    }

    // Separate / markers (editor comments) from others
    var editMarkers = markers.filter(function(m) { return (m.comment || '').indexOf('/') === 0; });

    // Build output
    function fmtMMSS(sec) {
      var mm = Math.floor(sec / 60);
      var ss = (sec % 60).toFixed(1);
      return (mm < 10 ? '0' : '') + mm + ':' + (ss < 10 ? '0' : '') + ss;
    }

    var briefSegments = [];
    for (var bsi = 0; bsi < timelineClips.length; bsi++) {
      var tc = timelineClips[bsi];
      briefSegments.push({
        segment_id: 'seg_' + String(bsi + 1).padStart(3, '0'),
        source_file: tc.source_file,
        tc_in: fmtMMSS(tc.tc_in_sec),
        tc_out: fmtMMSS(tc.tc_out_sec),
        block: 1, block_name: '', segment_name: '',
        speaker: tc.speaker || '',
        transcript: (tc.transcript_text || '').substring(0, 500),
        track: 'V1', color: 'Green', use: 'TRUE', priority: 1,
        is_chapter: 'FALSE', broll_note: '', notes: ''
      });
    }

    var output = {
      sequence: seqName,
      exported_at: new Date().toISOString(),
      assembly: { markers_count: editMarkers.length, chapters_count: markers.filter(function(m){return m.is_chapter;}).length, markers: markers },
      deletedScene: { markers_count: 0, markers: [] },
      timeline_clips: timelineClips,
      brief: {
        segments: briefSegments,
        project: {
          project_name: projectState.projectName || seqName,
          fps: 25, width: 3840, height: 2160, sample_rate: 48000,
          create_assembly_sequence: true, cut_color: 'Red'
        },
        changelog: []
      },
      brief_source: 'generated_from_timeline'
    };

    // Version scan — scan 00_Setup/05_Review/ for existing _out.json
    var reviewDirPath = projectState.folderPath + '/00_Setup/05_Review';
    var reviewEntry;
    try {
      reviewEntry = await uxpfs.getEntryWithUrl('file://' + reviewDirPath);
    } catch (e) {
      var setupEntry = await uxpfs.getEntryWithUrl('file://' + projectState.folderPath + '/00_Setup');
      reviewEntry = await ensureSubfolder(setupEntry, '05_Review', reviewLogger);
    }

    var baseSeqName = seqName.replace(/_v\d+$/, '');
    var existingFiles = await reviewEntry.getEntries();
    var maxVer = 0;
    var verRe = new RegExp(baseSeqName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '_v(\\d+)');
    for (var fi = 0; fi < existingFiles.length; fi++) {
      var vm = existingFiles[fi].name.match(verRe);
      if (vm) {
        var vn = parseInt(vm[1], 10);
        if (vn > maxVer) maxVer = vn;
      }
    }
    // Also scan for _in.json from Claude
    var projectCode = assemblyState.projectCode || extractProjectCode(projectState.projectName || '');
    var inRe = new RegExp(projectCode + '_5_Review_v(\\d+)_in\\.json$');
    for (var fi2 = 0; fi2 < existingFiles.length; fi2++) {
      var im = existingFiles[fi2].name.match(inRe);
      if (im) {
        var ivn = parseInt(im[1], 10);
        if (ivn > maxVer) maxVer = ivn;
      }
    }
    var version = maxVer + 1;
    output.version = version;
    output.direction = 'out';
    output.brief.changelog.push({ version: 'v' + version, date: new Date().toISOString().split('T')[0], source: 'premiere_export', summary: 'Generated from timeline ' + seqName });

    var fileName = baseSeqName + '_v' + version + '_out.json';
    var jsonContent = JSON.stringify(output, null, 2);

    // Write to 00_Setup/05_Review/
    var outFile = await reviewEntry.createFile(fileName, { overwrite: true });
    await outFile.write(jsonContent);
    reviewLogger.info('Written: 00_Setup/05_Review/' + fileName);

    // Copy path to clipboard
    try {
      var fullPath = reviewEntry.nativePath + '/' + fileName;
      await navigator.clipboard.writeText(fullPath);
      reviewLogger.info('Copied to clipboard: ' + fullPath);
    } catch (clipErr) {
      reviewLogger.debug('Clipboard copy failed: ' + clipErr.message);
    }

    // Write to ~/Downloads/
    try {
      var homePath = require('os').homedir();
      var dlEntry = await uxpfs.getEntryWithUrl('file://' + homePath + '/Downloads');
      var dlFile = await dlEntry.createFile(fileName, { overwrite: true });
      await dlFile.write(jsonContent);
      reviewLogger.info('Copied: ~/Downloads/' + fileName);
    } catch (dlErr) {
      reviewLogger.debug('Downloads copy failed: ' + dlErr.message);
    }

    // Generate HTML review
    try {
      var htmlName = baseSeqName + '_v' + version + '_review.html';
      var htmlContent = generateExportReviewHtml(output, version, seqName);
      var htmlFile = await reviewEntry.createFile(htmlName, { overwrite: true });
      await htmlFile.write(htmlContent);
      reviewLogger.info('Written: 00_Setup/05_Review/' + htmlName);
      try {
        var shell = require('uxp').shell;
        await shell.openPath(reviewEntry.nativePath + '/' + htmlName);
      } catch (openErr) {
        reviewLogger.debug('Could not auto-open HTML: ' + openErr.message);
      }
    } catch (htmlErr) {
      reviewLogger.warn('HTML review generation failed: ' + htmlErr.message);
    }

    setReviewStatus('Exported v' + version + ' → clipboard: ' + fileName, 'ready');

  } catch (err) {
    reviewLogger.error('Review marker export failed: ' + err.message, err);
    setReviewStatus('Export failed: ' + err.message, 'error', err);
  }

  $('btn-export-review-markers').removeAttribute('disabled');
}

// ══════════════════════════════════════════════════════════════════
//  DEBUG DUMP — full project state export
// ══════════════════════════════════════════════════════════════════

/**
 * Convert TickTime to 3-format object: timecode, seconds, ticks string.
 */
function tickToFormats(tt, fps) {
  if (!tt) return null;
  var sec = tickSec(tt);
  if (sec < 0) return null;
  var tickStr = '';
  try { tickStr = String(tt.ticks || ''); } catch (e) { /* ticks string is informational; sec already computed */ }
  // Build HH:MM:SS:FF timecode
  var f = fps || 25;
  var totalFrames = Math.round(sec * f);
  var ff = totalFrames % f;
  var totalSec = Math.floor(totalFrames / f);
  var ss = totalSec % 60;
  var totalMin = Math.floor(totalSec / 60);
  var mm = totalMin % 60;
  var hh = Math.floor(totalMin / 60);
  var tc = String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0') + ':' +
           String(ss).padStart(2, '0') + ':' + String(ff).padStart(2, '0');
  return { tc: tc, sec: Math.round(sec * 1000000) / 1000000, ticks: tickStr };
}

/**
 * Read all clips from a single track.
 */
async function dumpTrackClips(track, trackLabel, fps, ingestByName) {
  var clips = [];
  var trackItems = null;
  try { trackItems = track.getTrackItems(1, false); } catch (e) { /* fallback below handles it */ }
  if (!trackItems) try { trackItems = track.getTrackItems(); } catch (e) { /* no logger in shared helper; caller sees empty track */ }
  if (!trackItems) return clips;

  for (var i = 0; i < trackItems.length; i++) {
    var item = trackItems[i];
    var entry = { track: trackLabel, index: i };
    try {
      var pi = await item.getProjectItem();
      entry.source = pi ? pi.name : '';
      // media path — real API is getMediaFilePath(); fall back to getMediaPath()
      entry.media_path = '';
      if (pi) {
        try { entry.media_path = await pi.getMediaFilePath(); } catch (e) {
          try { entry.media_path = pi.getMediaPath(); } catch (e2) { /* blank media_path is visible in the dump itself */ }
        }
      }
    } catch (e) { entry.source = ''; entry.media_path = ''; }
    // Enrich with ingest wall-clock / sync truth (matched by source filename) so
    // the dump shows timeline position NEXT TO clock/creation_time/sync — the key
    // pairing for verifying multi-camera sync from the dump alone.
    try {
      if (ingestByName && entry.source) {
        var key = String(entry.source).replace(/\.[^.]+$/, '');
        var ic = ingestByName[entry.source] || ingestByName[key];
        if (ic) {
          entry.ingest = {
            clip_id: ic.clip_id,
            scene: ic.scene,
            creation_time: ic.creation_time,
            wall_offset: ic.wall_offset,
            clock_offset: ic.clock_offset,           // present after sync engine writes it
            probe_fps: ic.probe ? ic.probe.fps : undefined,
            camera: ic.path ? String(ic.path).replace(/\\/g, '/').split('/').slice(-2)[0] : undefined,
            sync: ic.sync || undefined               // present after 0116 sync engine
          };
        }
      }
    } catch (e) { /* enrichment best-effort */ }
    try {
      entry.timeline_start = tickToFormats(await item.getStartTime(), fps);
      entry.duration = tickToFormats(await item.getDuration(), fps);
      entry.source_in = tickToFormats(await item.getInPoint(), fps);
      entry.source_out = tickToFormats(await item.getOutPoint(), fps);
      // Compute timeline_end
      if (entry.timeline_start && entry.duration) {
        var endSec = entry.timeline_start.sec + entry.duration.sec;
        var ef = fps || 25;
        var etf = Math.round(endSec * ef);
        var eff = etf % ef;
        var ets = Math.floor(etf / ef);
        var ess = ets % 60; var etm = Math.floor(ets / 60); var emm = etm % 60; var ehh = Math.floor(etm / 60);
        entry.timeline_end = {
          tc: String(ehh).padStart(2, '0') + ':' + String(emm).padStart(2, '0') + ':' + String(ess).padStart(2, '0') + ':' + String(eff).padStart(2, '0'),
          sec: Math.round(endSec * 1000000) / 1000000
        };
      }
    } catch (e) { entry.error = e.message; }
    // Clip → Enable снят = Роман пометил кусок «вырезать» (тёмный клип на таймлайне).
    // VideoClipTrackItem/AudioClipTrackItem.isDisabled() — API с 25.0; старые сборки просто без поля.
    try { if (typeof item.isDisabled === 'function') entry.disabled = !!(await item.isDisabled()); } catch (e) { /* optional API on this build (25.0+); field omitted */ }
    clips.push(entry);
  }
  return clips;
}

/**
 * Analyze gaps and overlaps between consecutive clips on a track.
 */
function analyzeTrackGaps(clips, fps) {
  var issues = [];
  var frameDur = 1 / (fps || 25);
  for (var i = 1; i < clips.length; i++) {
    var prev = clips[i - 1];
    var curr = clips[i];
    if (!prev.timeline_end || !curr.timeline_start) continue;
    var gap = curr.timeline_start.sec - prev.timeline_end.sec;
    if (gap > frameDur * 1.5) {
      issues.push({ type: 'gap', between: [i - 1, i], frames: Math.round(gap * (fps || 25)), sec: Math.round(gap * 1000000) / 1000000 });
    } else if (gap < -frameDur * 0.5) {
      issues.push({ type: 'overlap', between: [i - 1, i], frames: Math.round(-gap * (fps || 25)), sec: Math.round(-gap * 1000000) / 1000000 });
    }
  }
  return issues;
}

/**
 * Dump complete sequence data: all tracks, all clips, gap analysis.
 */
async function dumpSequence(seq, fps, ingestByName) {
  var data = { name: seq.name };

  // Settings
  try {
    var frameSize = await seq.getFrameSize();
    data.width = frameSize.width || frameSize.right || 0;
    data.height = frameSize.height || frameSize.bottom || 0;
  } catch (e) { /* dump field is best-effort; no logger in shared helper */ }
  try {
    var tb = await seq.getTimebase();
    data.fps = tb ? Math.round(254016000000 / Number(tb)) : fps;
  } catch (e) { data.fps = fps; }

  var seqFps = data.fps || fps || 25;
  data.tracks = {};
  data.analysis = {};

  // Video tracks
  try {
    var vCount = await seq.getVideoTrackCount();
    for (var vi = 0; vi < vCount; vi++) {
      var vTrack = await seq.getVideoTrack(vi);
      var label = 'V' + (vi + 1);
      var vClips = await dumpTrackClips(vTrack, label, seqFps, ingestByName);
      if (vClips.length > 0) {
        data.tracks[label] = vClips;
        var vIssues = analyzeTrackGaps(vClips, seqFps);
        if (vIssues.length > 0) data.analysis[label] = vIssues;
      }
    }
  } catch (e) { data.video_error = e.message; }

  // Audio tracks
  try {
    var aCount = await seq.getAudioTrackCount();
    for (var ai = 0; ai < aCount; ai++) {
      var aTrack = await seq.getAudioTrack(ai);
      var aLabel = 'A' + (ai + 1);
      var aClips = await dumpTrackClips(aTrack, aLabel, seqFps, ingestByName);
      if (aClips.length > 0) {
        data.tracks[aLabel] = aClips;
        var aIssues = analyzeTrackGaps(aClips, seqFps);
        if (aIssues.length > 0) data.analysis[aLabel] = aIssues;
      }
    }
  } catch (e) { data.audio_error = e.message; }

  // Cross-track alignment (V1 vs V2, V1 vs A3)
  if (data.tracks['V1'] && data.tracks['V2']) {
    var crossIssues = [];
    var v1Clips = data.tracks['V1'];
    var v2Clips = data.tracks['V2'];
    for (var v2i = 0; v2i < v2Clips.length; v2i++) {
      var v2c = v2Clips[v2i];
      if (!v2c.timeline_start) continue;
      // Find matching V1 clip at same position
      var matched = false;
      for (var v1i = 0; v1i < v1Clips.length; v1i++) {
        if (!v1Clips[v1i].timeline_start) continue;
        if (Math.abs(v1Clips[v1i].timeline_start.sec - v2c.timeline_start.sec) < 0.5) {
          var drift = v2c.timeline_start.sec - v1Clips[v1i].timeline_start.sec;
          if (Math.abs(drift) > 1 / (seqFps * 2)) {
            crossIssues.push({ v2_clip: v2i, v1_clip: v1i, drift_frames: Math.round(drift * seqFps), drift_sec: drift });
          }
          matched = true;
          break;
        }
      }
      if (!matched) crossIssues.push({ v2_clip: v2i, issue: 'no_matching_v1_clip', v2_start: v2c.timeline_start.sec });
    }
    if (crossIssues.length > 0) data.analysis['V1_vs_V2'] = crossIssues;
  }

  return data;
}

/**
 * Recursively dump bin tree from a project item.
 */
async function dumpBinTree(item, depth) {
  if (depth > 10) return null; // safety
  var node = { name: item.name, type: item.type };
  try {
    var folder = ppro.FolderItem.cast(item);
    if (folder) {
      node.children = [];
      var children = await folder.getItems();
      for (var ci = 0; ci < children.length; ci++) {
        var child = await dumpBinTree(children[ci], depth + 1);
        if (child) node.children.push(child);
      }
    } else {
      // Leaf item — get media path
      try { node.media_path = item.getMediaPath(); } catch (e) { /* non-media leaves (sequences) have no path */ }
    }
  } catch (e) { ingestLogger.debug('dumpBinTree: "' + (item && item.name) + '" returned without children/media_path: ' + (e && e.message)); }
  return node;
}

/* ═══════════════════════════ PROJECT DOCTOR ═══════════════════════════ */
var doctorState = { lastReportPath: null, lastDebugPath: null };
var doctorLogFn = function () {};   // set by onDoctorAnalyze so analysis steps are captured

function setDoctorStatus(text, type, err) {
  $('doctor-status-dot').className = 'status-dot ' + (type || 'waiting');
  $('doctor-status-text').textContent = text;
  if (type === 'error') recordPanelError(text, 'doctor', err);
}
function setDoctorProgress(percent, text) {
  $('doctor-progress-bar').style.display = 'block';
  $('doctor-progress-text').style.display = 'block';
  $('doctor-progress-fill').style.width = percent + '%';
  if (text != null) $('doctor-progress-text').textContent = text;
}
function doctorTs() {
  var d = new Date(), p = function (n) { return n < 10 ? '0' + n : '' + n; };
  return '' + d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + '_' +
    p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds());
}
async function doctorPathExists(path) {
  if (!path) return false;
  try { await uxpfs.getEntryWithUrl('file://' + path); return true; } catch (e) { return false; }
}
// mkdir -p for an absolute path: find deepest existing ancestor, then create down.
async function doctorEnsureDir(dirPath) {
  dirPath = dirPath.replace(/\/+$/, '');
  try { return await uxpfs.getEntryWithUrl('file://' + dirPath); } catch (e) { /* missing dir is the normal case; created below */ }
  var parts = dirPath.split('/');
  var baseEntry = null, i = parts.length;
  for (; i > 1; i--) {
    try { baseEntry = await uxpfs.getEntryWithUrl('file://' + parts.slice(0, i).join('/')); break; } catch (e2) { /* ancestor missing: walk up; throws below if none */ }
  }
  if (!baseEntry) throw new Error('Cannot locate a base folder for ' + dirPath);
  for (var j = i; j < parts.length; j++) {
    if (!parts[j]) continue;
    try { baseEntry = await baseEntry.getEntry(parts[j]); }
    catch (e3) { baseEntry = await baseEntry.createFolder(parts[j]); }
  }
  return baseEntry;
}

// Every media leaf in the bin tree → {name, mediaPath}.
// NOTE: the ROOT item does not cast as FolderItem — call getItems() on it directly
// (like projectScanner/debugDump) and run dumpBinTree on each child.
async function doctorCollectMedia(project) {
  var media = [];
  var rootItem = await project.getRootItem();
  async function mediaPathOf(it) {
    var p = '';
    try { p = await it.getMediaFilePath(); } catch (e) { /* fallback below handles it */ }
    if (!p) { try { p = it.getMediaPath(); } catch (e) { /* fallback below handles it */ } }
    if (!p) {
      try { var c = ppro.ClipProjectItem.cast(it); if (c) { try { p = await c.getMediaFilePath(); } catch (e) { try { p = c.getMediaPath(); } catch (e2) { doctorLogFn('mediaPathOf: no path for "' + (it && it.name) + '": ' + (e2 && e2.message)); } } } } catch (e) { /* not a clip item (bin/sequence): no media path */ }
    }
    return p || '';
  }
  async function scan(folder, depth) {
    if (depth > 12) return;
    var items;
    try { items = await folder.getItems(); } catch (e) { return; }
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      var asFolder = null; try { asFolder = ppro.FolderItem.cast(it); } catch (e) { /* cast throws for non-folder items; null is the answer */ }
      if (asFolder) { await scan(asFolder, depth + 1); continue; }
      var asSeq = null; try { asSeq = ppro.Sequence.cast(it); } catch (e) { /* cast throws for non-sequence items; null is the answer */ }
      if (asSeq) continue;                       // sequences are not media
      var p = await mediaPathOf(it);
      var pl = (p || '').toLowerCase();
      var isCache = /\.(cfa|pek|prv)$/.test(pl) || pl.indexOf('.prv/') >= 0 ||
        pl.indexOf('audio previews') >= 0 || pl.indexOf('video previews') >= 0 || pl.indexOf('auto-save') >= 0;
      // real file paths only — skip synthetic (Color Matte) + regenerable cache (.cfa/.pek/previews/auto-save)
      if (p && /[\/\\]/.test(p) && !isCache) media.push({ name: it.name, mediaPath: p, item: it });
    }
  }
  await scan(rootItem, 0);
  doctorLogFn('media items in bin (with path) = ' + media.length);
  return media;
}

var DOCTOR_BUILD = 'D17';   // shown in the HTML report + debug log so a report self-identifies its build

// Best-effort name of a Premiere object via property or getter (UXP varies by build/type).
function doctorNameOf(obj) {
  var n = '';
  try { n = obj && obj.name ? obj.name : ''; } catch (e) { /* fallback below handles it */ }
  if (!n) { try { if (obj && typeof obj.getName === 'function') n = obj.getName() || ''; } catch (e) { /* fallback below handles it */ } }
  if (!n) { try { if (obj && typeof obj.getMatchName === 'function') n = obj.getMatchName() || ''; } catch (e) { /* last resort; '' is valid for nameless objects */ } }
  return n || '';
}


// Lightweight: {name, mediaPath} of source projectItems placed on a sequence's tracks.
// Recurses into NESTED sequences so media used only inside a nested sequence is still
// counted as "used" on the parent timeline. Without this, a clip that lives only inside
// a nested sequence renders a red "Media Offline" frame on the timeline, yet the report
// wrongly marks it used:false / actionRequired:0 and never lists it as a file to send.
// seqNameSet: { name:true } of EVERY sequence in the project. resolveSeq(name) → walkable Sequence.
async function doctorSequenceSources(seq, seqNameSet, resolveSeq) {
  seqNameSet = seqNameSet || {};
  var out = [];
  var visited = {};                                   // guard against nested-sequence cycles
  var stats = { raw: 0, nopi: 0, nested: 0, leaves: 0, probed: 0 };
  async function walkSeq(s) {
    var sname = doctorNameOf(s);
    if (sname && visited[sname]) return;
    if (sname) visited[sname] = true;
    async function walkTrack(track) {
      var items = null;
      try { items = await track.getTrackItems(1, false); } catch (e) { /* fallback below handles it */ }
      if (!items) { try { items = await track.getTrackItems(); } catch (e) { doctorLogFn('walkTrack: getTrackItems threw on "' + sname + '": ' + (e && e.message)); } }
      if (!items) return;
      for (var i = 0; i < items.length; i++) {
        stats.raw++;
        try {
          var pi = null, piErr = '';
          try { pi = await items[i].getProjectItem(); } catch (e) { piErr = (e && e.message) || 'threw'; }
          var tiName = doctorNameOf(items[i]);        // track-item name (works when projectItem is null)
          var piName = doctorNameOf(pi) || tiName;
          // Nested sequence? Match either name against the project's full sequence-name set.
          var nestedName = (seqNameSet[piName] && piName) || (seqNameSet[tiName] && tiName) || '';
          if (nestedName && nestedName !== sname) {
            var nestedSeq = await resolveSeq(nestedName);
            if (nestedSeq) { stats.nested++; await walkSeq(nestedSeq); continue; }
          }
          if (!piName) {
            stats.nopi++;
            // Probe the first few unidentifiable clips so we learn the right API next run.
            if (stats.probed < 5) {
              stats.probed++;
              var meths = '';
              try { meths = Object.getOwnPropertyNames(Object.getPrototypeOf(items[i])).filter(function (k) { return k !== 'constructor'; }).join(','); } catch (e) { /* diagnostic probe only; empty method list is fine */ }
              doctorLogFn('   ? unidentified clip: getPI=' + (piErr || '(null)') + ' tiName="' + tiName + '" methods=[' + meths + ']');
            }
            continue;
          }
          var p = '';
          if (pi) { try { p = await pi.getMediaFilePath(); } catch (e) { try { p = pi.getMediaPath(); } catch (e2) { /* name still recorded; usage matches by name */ } } }
          out.push({ name: piName, mediaPath: p || '' });
          stats.leaves++;
        } catch (e) { doctorLogFn('walkTrack: item ' + i + ' of "' + sname + '" skipped: ' + (e && e.message)); }
      }
    }
    try { var vc = await s.getVideoTrackCount(); for (var v = 0; v < vc; v++) { await walkTrack(await s.getVideoTrack(v)); } } catch (e) { doctorLogFn('WARN: video tracks of "' + sname + '" not walked: ' + (e && e.message)); }
    try { var ac = await s.getAudioTrackCount(); for (var a = 0; a < ac; a++) { await walkTrack(await s.getAudioTrack(a)); } } catch (e) { doctorLogFn('WARN: audio tracks of "' + sname + '" not walked: ' + (e && e.message)); }
  }
  await walkSeq(seq);
  try { doctorLogFn('  walk "' + doctorNameOf(seq) + '": raw=' + stats.raw + ' nopi=' + stats.nopi + ' nested=' + stats.nested + ' leaves=' + stats.leaves + ' visited=[' + Object.keys(visited).join(', ') + ']'); } catch (e) { /* stats line only; logging must not break the walk */ }
  return out;
}

// Source names placed on the target sequence(s). scope: 'active' | 'all'.
async function doctorCollectUsage(project, scope) {
  var usedByName = {}, seqNames = [], seen = {};

  // 1) EVERY sequence in the project (incl. nested) as WALKABLE objects, via getSequences().
  //    This is the reliable enumerator here — ppro.Sequence.cast() returns null and
  //    project.openSequence() throws in this Premiere build (proven by build-D9 debug log).
  var seqByName = {}, seqNameSet = {};
  var allSeq = [];
  try { allSeq = await project.getSequences(); } catch (e) { doctorLogFn('getSequences threw: ' + (e && e.message)); }
  for (var m = 0; m < (allSeq ? allSeq.length : 0); m++) {
    var nmm = doctorNameOf(allSeq[m]);
    if (nmm && !seqByName[nmm]) { seqByName[nmm] = allSeq[m]; seqNameSet[nmm] = true; }
  }
  // make sure the active sequence is in the map (and walkable)
  var savedActive = null; try { savedActive = await project.getActiveSequence(); } catch (e) { doctorLogFn('getActiveSequence threw: ' + (e && e.message)); }
  if (savedActive) { var an = doctorNameOf(savedActive); if (an && !seqByName[an]) { seqByName[an] = savedActive; seqNameSet[an] = true; } }
  doctorLogFn('getSequences = ' + Object.keys(seqByName).length + ' [' + Object.keys(seqByName).join(', ') + ']');

  // resolver: walkable Sequence straight from the map — no openSequence needed.
  function resolveSeq(name) { return seqByName[name] || null; }

  // 2) Decide which top-level sequence(s) to scan.
  var topSeqs = [];   // walkable Sequence objects
  if (scope === 'active') {
    if (savedActive) { topSeqs.push(savedActive); seen[doctorNameOf(savedActive)] = true; }
    else doctorLogFn('no active sequence');
  }
  if (!topSeqs.length || scope === 'all') {
    Object.keys(seqByName).forEach(function (k) { if (!seen[k]) { topSeqs.push(seqByName[k]); seen[k] = true; } });
  }

  // 3) Walk each top sequence (recursing into nested via resolveSeq).
  for (var si = 0; si < topSeqs.length; si++) {
    var seq = topSeqs[si];
    var nm = doctorNameOf(seq) || ('seq' + (si + 1));
    seqNames.push(nm);
    var srcs = await doctorSequenceSources(seq, seqNameSet, resolveSeq);
    for (var k = 0; k < srcs.length; k++) {
      var src = srcs[k];
      if (!usedByName[src.name]) usedByName[src.name] = { count: 0, seqs: {}, mediaPath: src.mediaPath || '' };
      usedByName[src.name].count++;
      usedByName[src.name].seqs[nm] = (usedByName[src.name].seqs[nm] || 0) + 1;
      if (!usedByName[src.name].mediaPath && src.mediaPath) usedByName[src.name].mediaPath = src.mediaPath;
    }
  }

  return { usedByName: usedByName, sequences: seqNames };
}

async function analyzeForDoctor(scope) {
  var project = await ppro.Project.getActiveProject();
  if (!project) throw new Error('No active project — open a project in Premiere first.');
  doctorLogFn('active project = ' + (project.name || '?'));
  var media = await doctorCollectMedia(project);
  doctorLogFn('media items in bin = ' + media.length);
  var usage = await doctorCollectUsage(project, scope);
  doctorLogFn('sequences scanned = ' + usage.sequences.length + ' [' + usage.sequences.join(', ') + ']');
  doctorLogFn('distinct used sources = ' + Object.keys(usage.usedByName).length);
  var seen = {}, items = [];
  for (var i = 0; i < media.length; i++) {
    var m = media[i];
    if (!m.name || seen[m.name]) continue;
    seen[m.name] = true;
    var present = await doctorPathExists(m.mediaPath);
    // D17: the disk is only half the answer. Ask Premiere too — a clip can be offline in the
    // app while its file is present (stale volume handle / importer crash). Reporting only the
    // disk check is how a "551 present · 4 offline" report coexisted with a red timeline.
    var pOff = await doctorIsOfflineInPremiere(m.item);
    var u = usage.usedByName[m.name];
    var usedIn = [];
    if (u) Object.keys(u.seqs).forEach(function (sq) { usedIn.push({ seq: sq, count: u.seqs[sq] }); });
    items.push({
      name: m.name, mediaPath: m.mediaPath, present: present,
      premiereOffline: pOff, ghostOffline: present && pOff === true,
      used: !!u, usedIn: usedIn
    });
  }
  // include any USED source not matched in the bin inventory (path taken from the timeline clip)
  var usedKeys = Object.keys(usage.usedByName);
  for (var j = 0; j < usedKeys.length; j++) {
    var un = usedKeys[j];
    if (seen[un]) continue;
    seen[un] = true;
    var uu = usage.usedByName[un];
    // skip synthetic timeline sources (Color Matte, titles, etc. — no real file path)
    if (!uu.mediaPath || !/[\/\\]/.test(uu.mediaPath)) continue;
    var uIn = []; Object.keys(uu.seqs).forEach(function (sq) { uIn.push({ seq: sq, count: uu.seqs[sq] }); });
    var pr = await doctorPathExists(uu.mediaPath);
    // No bin item behind this record (timeline-only source) → Premiere's offline flag is unreachable.
    items.push({ name: un, mediaPath: uu.mediaPath || '', present: pr, premiereOffline: null, ghostOffline: false, used: true, usedIn: uIn });
  }
  var counts = {
    total: items.length,
    present: items.filter(function (x) { return x.present; }).length,
    offline: items.filter(function (x) { return !x.present; }).length,
    // D17: file on disk, but Premiere still calls it offline — fixable in place, nothing to request.
    ghostOffline: items.filter(function (x) { return x.ghostOffline; }).length,
    actionRequired: items.filter(function (x) { return !x.present && x.used; }).length
  };
  // Premiere exposes no offline flag on some builds → detection returns null everywhere.
  // Say so in the log instead of silently reporting "0 ghost offline".
  counts.ghostDetectable = items.some(function (x) { return x.premiereOffline !== null && x.premiereOffline !== undefined; });
  if (!counts.ghostDetectable) doctorLogFn('WARN: this Premiere build exposes no offline flag — ghost-offline count is unknown, not zero');
  var scopeLabel = (scope === 'active' && usage.sequences.length === 1)
    ? ('Active sequence: ' + usage.sequences[0])
    : ('All sequences (' + usage.sequences.length + ')');

  // Derive the project root automatically from the ACTIVE project's .prproj path.
  // (Doctor needs no "Select folder" — it follows whatever project is open.)
  var projPath = '';
  try { projPath = (project.path || '').replace(/\\/g, '/').replace(/^file:\/\//, ''); } catch (e) { /* panel-folder fallback below; logged as (none) */ }
  // Doctor follows the ACTIVE project: derive root from its .prproj path first.
  // Only fall back to the panel-selected folder if the project has no saved path.
  var projectRoot = projPath
    ? projPath.replace(/\/[^\/]*$/, '')
    : (projectState.folderPath ? projectState.folderPath.replace(/\\/g, '/').replace(/\/+$/, '') : '');
  // Editors keep the .prproj in 02_Edit/ → walk UP to the folder that owns 00_Setup,
  // otherwise the report lands in 02_Edit/00_Setup and media search misses 01_Source.
  if (projectRoot) projectRoot = await resolveProjectRoot(projectRoot);
  doctorLogFn('project.path = ' + (projPath || '(none)'));
  doctorLogFn('derived projectRoot = ' + (projectRoot || '(none)'));
  doctorLogFn('counts = ' + JSON.stringify(counts));
  var rootName = projectRoot ? projectRoot.split('/').filter(Boolean).pop() : (project.name || '');
  var cm = String(rootName).match(/^(YT[A-Z]{2,4}\d+)_/) || String(project.name || '').match(/^(YT[A-Z]{2,4}\d+)_/);
  var code = cm ? cm[1] : (rootName || project.name || 'project');

  return {
    project: { name: project.name || rootName, code: code, path: projectRoot, prproj: projPath },
    generatedAt: new Date().toISOString(),
    build: DOCTOR_BUILD,
    scopeLabel: scopeLabel,
    sequencesScanned: usage.sequences,
    counts: counts, items: items, fonts: [], errors: []  // fonts: v2 (parse .prproj)
  };
}

async function onDoctorAnalyze() {
  var dbg = [];
  function log(m) {
    dbg.push(new Date().toISOString().slice(11, 19) + '  ' + m);
    try { console.log('[Doctor] ' + m); } catch (e) { /* console may be absent in UXP; dbg[] keeps the line */ }
  }
  doctorLogFn = log;
  doctorState.lastReportPath = null;
  doctorState.lastDebugPath = null;
  try { $('btn-doctor-open').setAttribute('disabled', 'true'); } catch (e) { /* cosmetic; button may not be in the DOM yet */ }
  var projectRootForLog = '';
  var scopeEl = document.querySelector('input[name="doctor-scope"]:checked');
  var scope = scopeEl ? scopeEl.value : 'active';
  log('=== Project Doctor run (build ' + DOCTOR_BUILD + ' · nested-seq aware) === scope=' + scope + ' ; panelFolder=' + (projectState.folderPath || '(none)'));
  $('btn-doctor-analyze').setAttribute('disabled', 'true');
  setDoctorStatus('Analyzing project…', 'waiting');
  setDoctorProgress(10, 'Reading project bin + timeline…');
  try {
    var result = await analyzeForDoctor(scope);
    projectRootForLog = result.project.path || '';
    setDoctorProgress(70, 'Building report…');
    var report = require('./src/doctor/doctorReport');
    var html = report.buildDoctorHtml(result);
    var json = report.buildDoctorJson(result);
    log('report built: html=' + html.length + 'B json=' + json.length + 'B');

    var projectRoot = result.project.path;
    if (!projectRoot) throw new Error('Active project has no saved path. Save the .prproj once, then retry.');
    // prefill the relink "also search" box with the channel parent (sibling-project assets live there)
    try { var _er = $('doctor-extra-root'); if (_er && !_er.value) _er.value = projectRoot.replace(/\/[^\/]*$/, ''); } catch (e) { /* prefill is a convenience; user can type the path */ }
    var outDir = projectRoot + '/00_Setup/05_Review';
    log('writing report → ' + outDir);
    var dirEntry = await doctorEnsureDir(outDir);
    var base = result.project.code + '_doctor_' + doctorTs();
    var htmlFile = await dirEntry.createFile(base + '.html', { overwrite: true });
    await htmlFile.write(html);
    var jsonFile = await dirEntry.createFile(base + '.json', { overwrite: true });
    await jsonFile.write(json);
    doctorState.lastReportPath = outDir + '/' + base + '.html';
    $('btn-doctor-open').removeAttribute('disabled');
    log('report written OK');

    var c = result.counts;
    $('doctor-summary').innerHTML =
      '<div style="padding:8px 0;line-height:1.6">' +
      '<span style="color:var(--text-secondary);font-size:11px">Analyzed (active project): </span><b>' +
      escapeHtml(result.project.name) + '</b><br>' +
      '<b style="color:#ff5252;font-size:16px">' + c.actionRequired + '</b> action required &middot; ' +
      c.offline + ' offline &middot; ' + c.present + ' present &middot; ' + c.total + ' total<br>' +
      (c.ghostDetectable
        ? (c.ghostOffline
          ? ('<b style="color:#ff9800">' + c.ghostOffline + ' ghost-offline</b> <span style="color:var(--text-secondary);font-size:11px">(file is present, Premiere says offline → 🩹 Force refresh)</span><br>')
          : '')
        : '<span style="color:var(--text-secondary);font-size:11px">ghost-offline: unknown (this Premiere build exposes no offline flag)</span><br>') +
      '<span style="color:var(--text-secondary);font-size:11px">' + escapeHtml(result.scopeLabel) +
      ' &middot; report → ' + escapeHtml(result.project.path) + '/00_Setup/05_Review/' + escapeHtml(base) + '.html</span></div>';

    setDoctorProgress(100, 'Done');
    var opened = await doctorOpen(doctorState.lastReportPath, log);
    try { await navigator.clipboard.writeText(doctorState.lastReportPath); log('report path copied to clipboard'); } catch (e) { log('clipboard copy failed: ' + (e && e.message)); }
    setDoctorStatus(c.actionRequired + ' to obtain · report ' + (opened ? 'opened' : 'saved') + ' · path copied',
      c.actionRequired ? 'error' : 'ready');
  } catch (e) {
    log('ERROR: ' + (e && e.message ? e.message : String(e)));
    if (e && e.stack) log('STACK: ' + e.stack);
    setDoctorStatus('Error: ' + (e && e.message ? e.message : String(e)) + ' — log path copied', 'error', e);
    setDoctorProgress(100, 'Error');
  } finally {
    $('btn-doctor-analyze').removeAttribute('disabled');
    doctorLogFn = function () {};
    // Debug body → FILE (not clipboard). Clipboard holds a PATH to open/send.
    var text = '=== Project Doctor debug ===\n' + dbg.join('\n') + '\n';
    try { await doctorWriteDebug(text, projectRootForLog); } catch (e3) { /* debug writer is self-guarded; nowhere left to log */ }
    if (!doctorState.lastReportPath && doctorState.lastDebugPath) {
      try { await navigator.clipboard.writeText(doctorState.lastDebugPath); } catch (e4) { /* clipboard is best-effort; path is shown in status */ }
    }
    if (doctorState.lastDebugPath) {
      try { $('btn-doctor-debug').removeAttribute('disabled'); } catch (e5) { /* cosmetic UI; button may not exist in this layout */ }
      var st = $('doctor-status-text');
      if (st) st.textContent += '  ·  log: ' + doctorState.lastDebugPath;
    }
  }
}

async function onDoctorCopyDebug() {
  if (!doctorState.lastDebugPath) { setDoctorStatus('No debug log yet — run Analyze or Relink first.', 'waiting'); return; }
  // OPEN the log in the default app (most useful), and copy its path as a bonus.
  var ok = await doctorOpen(doctorState.lastDebugPath, null);
  try { await navigator.clipboard.writeText(doctorState.lastDebugPath); } catch (e) { /* clipboard is best-effort; path is shown in status */ }
  setDoctorStatus(ok ? ('Debug log opened · ' + doctorState.lastDebugPath)
                     : ('Could not open — path copied · ' + doctorState.lastDebugPath), ok ? 'ready' : 'error');
}

// Open a file in the OS; if that fails, reveal its folder. Returns true if either worked.
async function doctorOpen(path, log) {
  if (!path) return false;
  var shell = require('uxp').shell;
  try {
    var e = await uxpfs.getEntryWithUrl('file://' + path);
    await shell.openPath(e.nativePath || path);
    if (log) log('opened report: ' + path);
    return true;
  } catch (e1) { if (log) log('open file failed: ' + (e1 && e1.message)); }
  try {
    var folder = path.replace(/\/[^\/]*$/, '');
    var fe = await uxpfs.getEntryWithUrl('file://' + folder);
    await shell.openPath(fe.nativePath || folder);
    if (log) log('opened folder: ' + folder);
    return true;
  } catch (e2) { if (log) log('open folder failed: ' + (e2 && e2.message)); }
  return false;
}

// Persist the full debug text where it can be retrieved (project logs first, plugin data folder as fallback).
async function doctorWriteDebug(text, projectRoot) {
  var ts = doctorTs();
  if (projectRoot) {
    try {
      var d = await doctorEnsureDir(projectRoot + '/00_Setup/logs');
      var f = await d.createFile('doctor_debug_' + ts + '.log', { overwrite: true });
      await f.write(text);
      doctorState.lastDebugPath = projectRoot + '/00_Setup/logs/doctor_debug_' + ts + '.log';
      try { console.log('[Doctor] debug log → ' + doctorState.lastDebugPath); } catch (e) { /* console.log guard only; nothing to report */ }
      return;
    } catch (e) { try { console.log('[Doctor] debug write (project) failed: ' + e.message); } catch (e1) { /* console.log guard; fallback below handles the write */ } }
  }
  try {
    var df = await uxpfs.getDataFolder();
    var f2 = await df.createFile('doctor_debug_' + ts + '.log', { overwrite: true });
    await f2.write(text);
    doctorState.lastDebugPath = (df.nativePath || '(plugin data folder)') + '/doctor_debug_' + ts + '.log';
    try { console.log('[Doctor] debug log → ' + doctorState.lastDebugPath); } catch (e) { /* console.log guard only; nothing to report */ }
  } catch (e3) { try { console.log('[Doctor] debug write failed entirely: ' + e3.message); } catch (e4) { /* console.log guard only; nothing to report */ } }
}

async function onDoctorOpenLast() {
  if (!doctorState.lastReportPath) { setDoctorStatus('No report yet — run Analyze first.', 'waiting'); return; }
  var ok = await doctorOpen(doctorState.lastReportPath, null);
  try { await navigator.clipboard.writeText(doctorState.lastReportPath); } catch (e) { /* clipboard is a bonus; opening the report is primary */ }
  setDoctorStatus(ok ? 'Report opened · path copied' : 'Could not open — path copied to clipboard', ok ? 'ready' : 'error');
}

/* ───────────── Doctor: find local copies of offline media + relink (v2) ─────────────
   The recurring editor-handoff case: the .prproj points media at the EDITOR'S machine
   paths (offline / red on the timeline), but an identical file already sits in THIS
   project (01_Source / 02_Edit / 03_Exports) or a sibling project. Instead of re-
   requesting, find the same-name file locally and re-point the bin clip via the live
   Premiere API ClipProjectItem.changeMediaFilePath(). One bin relink fixes every
   timeline use. Exact basename wins (project root searched first); a copy-marker alias
   ("Копия Vostorg A4344.MP4" → "Vostorg A4344.MP4") is the fallback. Not undoable → the
   target is always a SAME-NAME file, and the user reviews + ⌘S afterwards. */

var DOCTOR_MEDIA_EXT = /\.(mp4|mov|m4v|mxf|mts|avi|mkv|wav|mp3|aif|aiff|m4a|aac|flac|png|jpg|jpeg|psd|tif|tiff|gif|svg|webp|heic|aep|mogrt|aegraphic)$/i;
// folders not worth walking (regenerable / huge / irrelevant to media recovery)
var DOCTOR_SKIP_DIR = /^(.*_transcription|Adobe Premiere Pro Auto-Save|Adobe Premiere Pro Audio Previews|Adobe Premiere Pro Video Previews|node_modules|logs|per_clip)$/i;

function doctorBasename(p) {
  return String(p || '').replace(/\\/g, '/').replace(/\/+$/, '').split('/').pop() || '';
}
// normalise copy-markers so "Копия Vostorg A4344.MP4" ≈ "Vostorg A4344.MP4"
function doctorNormName(name) {
  var n = String(name || '').toLowerCase();
  var dot = n.lastIndexOf('.'), ext = dot > 0 ? n.slice(dot) : '', stem = dot > 0 ? n.slice(0, dot) : n;
  stem = stem.replace(/^(копия|copy of|copy_of|copy)\s+/i, '');
  stem = stem.replace(/\s*[—–-]\s*(копия|copy)\s*$/i, '');
  stem = stem.replace(/\s*\(\d+\)\s*$/, '');   // duplicate marker: "name (1)" ≈ "name"
  // Editor consolidate/trim suffix: "C6381-001.MP4" ≈ "C6381.MP4", "en (1)-003.mp4" ≈ "en (1).mp4".
  // 1-3 digits ONLY — camera stems like "RYA-FX3-0182" end in 4 digits and must stay intact.
  stem = stem.replace(/-\d{1,3}$/, '');
  return (stem + ext).trim();
}

// Walk the given roots once → indexes by basename (exact) and by normalised name.
// First match wins → pass the project root FIRST so in-project copies are preferred.
async function doctorBuildIndex(roots, log) {
  var exact = {}, norm = {}, files = 0;
  async function walk(folder, depth) {
    if (depth > 9) return;
    var entries; try { entries = await folder.getEntries(); } catch (e) { return; }
    for (var i = 0; i < entries.length; i++) {
      var en = entries[i], nm = en.name || '';
      if (en.isFolder) { if (nm.charAt(0) === '.' || DOCTOR_SKIP_DIR.test(nm)) continue; await walk(en, depth + 1); continue; }
      if (!DOCTOR_MEDIA_EXT.test(nm)) continue;
      var full = en.nativePath || ''; if (!full) continue;
      files++;
      var ke = nm.toLowerCase(); if (!(ke in exact)) exact[ke] = full;
      var kn = doctorNormName(nm); if (kn && !(kn in norm)) norm[kn] = full;
    }
  }
  for (var r = 0; r < roots.length; r++) {
    if (!roots[r]) continue;
    var ent = null; try { ent = await uxpfs.getEntryWithUrl('file://' + roots[r]); }
    catch (e) { if (log) log('relink: root not found — ' + roots[r]); continue; }
    if (log) log('relink: indexing ' + roots[r]);
    await walk(ent, 0);
  }
  if (log) log('relink: indexed ' + files + ' files · exact=' + Object.keys(exact).length + ' norm=' + Object.keys(norm).length);
  return { exact: exact, norm: norm };
}

// Re-point one bin item to targetPath. Returns 'ok' | 'skip' | 'fail'.
async function doctorRelinkItem(it, targetPath, log) {
  var clip = null; try { clip = ppro.ClipProjectItem.cast(it); } catch (e) { /* null check on next line handles a failed cast */ }
  if (!clip) { if (log) log('   skip (not a clip): ' + (it && it.name)); return 'skip'; }
  try { if (clip.canChangeMediaPath && (await clip.canChangeMediaPath()) === false) { if (log) log('   skip (canChangeMediaPath=false): ' + it.name); return 'skip'; } } catch (e) { /* optional API on this build; probe may throw */ }
  var ok = false;
  try { ok = await clip.changeMediaFilePath(targetPath); } catch (e) { if (log) log('   change threw: ' + (e && e.message)); }
  if (!ok) { try { ok = await clip.changeMediaFilePath(targetPath, true); } catch (e2) { if (log) log('   retry change threw: ' + (e2 && e2.message)); } }   // retry: override codec/format compat check
  return ok ? 'ok' : 'fail';
}

/* ───────────── D17: GHOST OFFLINE — Premiere says offline, the file is right there ─────────
   Failure seen live (YTUVI01, 2026-09-09): the project SSD was unplugged while Premiere held
   the project open, then re-mounted (new /dev node). Premiere latched the clips offline and
   never re-resolved them — red "Media offline" on the timeline while the path in the .prproj
   is byte-identical to a file that exists and reads at ~950 MB/s. Reopening the project does
   NOT clear it, because the stale state lives in the bin item, not in the path.

   Why the D11–D16 Doctor was structurally blind to this:
     • analyzeForDoctor decided "offline" purely by disk check (`present = doctorPathExists`),
       so the report cheerfully said "551 present / 4 offline" while the timeline was red;
     • onDoctorRelink opened with `if (await doctorPathExists(m.mediaPath)) continue;` —
       every ghost-offline clip was skipped as "already linked".
   So the one case where the editor is most stuck was the one case Doctor refused to touch.

   Fix = ask PREMIERE (not the filesystem) whether a clip is offline, then force a re-import
   in place. changeMediaFilePath(samePath) is a no-op — Premiere compares strings and does
   nothing. The bounce below re-points the clip to an OS-equivalent but textually different
   spelling of the SAME file ("/dir/name.mp4" → "/dir/./name.mp4"), then back. Premiere sees a
   genuine path change both times and re-imports, which is what clears the offline latch.
   Safety: BOTH spellings resolve to the same bytes, so an interruption mid-bounce still
   leaves the clip pointing at correct media — never at a wrong file. Not undoable → ⌘S after. */

// Ask Premiere itself whether the clip is offline. API surface varies by build, so probe every
// known spelling. Returns true | false | null (null = this build exposes no offline flag).
async function doctorIsOfflineInPremiere(it) {
  var targets = [it];
  try { var c = ppro.ClipProjectItem.cast(it); if (c) targets.push(c); } catch (e) { /* cast is a probe; the raw item is still checked */ }
  var props = ['isOffline', 'isOfflineMedia', 'isMediaOffline', 'offline'];
  var getters = ['isOffline', 'getIsOffline', 'isOfflineMedia', 'getIsOfflineMedia', 'isMediaOffline', 'getIsMediaOffline'];
  for (var t = 0; t < targets.length; t++) {
    var o = targets[t];
    if (!o) continue;
    for (var g = 0; g < getters.length; g++) {
      try {
        if (typeof o[getters[g]] === 'function') {
          var v = await o[getters[g]]();
          if (typeof v === 'boolean') return v;
        }
      } catch (e) { /* optional API on this build; next spelling is tried */ }
    }
    for (var p = 0; p < props.length; p++) {
      try { if (typeof o[props[p]] === 'boolean') return o[props[p]]; } catch (e) { /* optional API on this build; next spelling is tried */ }
    }
  }
  return null;
}

// OS-equivalent but textually different spelling of the same absolute path: "/a/b/f.mp4" →
// "/a/b/./f.mp4". Used only as the bounce waypoint — never left as the final value.
function doctorAltPathForm(p) {
  var s = String(p || '').replace(/\\/g, '/');
  var cut = s.lastIndexOf('/');
  if (cut <= 0 || cut === s.length - 1) return '';
  return s.slice(0, cut) + '/./' + s.slice(cut + 1);
}

// Force Premiere to re-import a clip that is offline despite its path being valid.
// Returns 'ok' | 'skip' | 'fail'. Always tries to leave the clip on the canonical path.
async function doctorForceRefreshItem(it, canonicalPath, log) {
  var clip = null; try { clip = ppro.ClipProjectItem.cast(it); } catch (e) { /* null check on next line handles a failed cast */ }
  if (!clip) { if (log) log('   skip (not a clip): ' + doctorNameOf(it)); return 'skip'; }
  var nm = doctorNameOf(it) || doctorBasename(canonicalPath);

  // Step 1 — the polite way, when this build offers it.
  for (var r = 0; r < 2; r++) {
    var fn = r === 0 ? 'refreshMedia' : 'refresh';
    try {
      if (typeof clip[fn] === 'function') {
        await clip[fn]();
        if (log) log('   ' + fn + '() called on ' + nm);
        if ((await doctorIsOfflineInPremiere(it)) === false) { if (log) log('   OK via ' + fn + '(): ' + nm); return 'ok'; }
      }
    } catch (e) { if (log) log('   ' + fn + '() threw: ' + (e && e.message)); }
  }

  // Step 2 — the bounce. Both spellings point at the same bytes.
  var alt = doctorAltPathForm(canonicalPath);
  if (!alt) { if (log) log('   FAIL no alt form for ' + canonicalPath); return 'fail'; }
  async function setPath(p) {
    var ok = false;
    try { ok = await clip.changeMediaFilePath(p); } catch (e) { if (log) log('   change threw: ' + (e && e.message)); }
    if (!ok) { try { ok = await clip.changeMediaFilePath(p, true); } catch (e2) { if (log) log('   retry change threw: ' + (e2 && e2.message)); } }
    return ok;
  }
  var wentOut = await setPath(alt);
  if (!wentOut && log) log('   bounce out refused for ' + nm + ' (continuing to restore canonical anyway)');
  var cameBack = await setPath(canonicalPath);
  if (!cameBack) {
    // Never leave a clip parked on the waypoint if we can help it — retry once.
    cameBack = await setPath(canonicalPath);
  }

  var finalPath = '';
  try { finalPath = (await clip.getMediaFilePath()) || ''; } catch (e) { /* readback is best-effort; used for log text only */ }
  if (!cameBack && wentOut) {
    if (log) log('   WARN ' + nm + ' left on alt spelling (same file): ' + (finalPath || alt));
  }
  var still = await doctorIsOfflineInPremiere(it);
  if (still === true) { if (log) log('   FAIL still offline after bounce: ' + nm); return 'fail'; }
  if (log) log('   OK via bounce: ' + nm + (finalPath ? ('  → ' + finalPath) : ''));
  return (wentOut || cameBack) ? 'ok' : 'fail';
}

async function onDoctorRelink() {
  var dbg = [];
  function log(m) { dbg.push(new Date().toISOString().slice(11, 19) + '  ' + m); try { console.log('[Doctor relink] ' + m); } catch (e) { /* console.log guard inside log(); nothing to report */ } }
  doctorLogFn = log;
  var relinked = 0, failed = 0, skipped = 0, refreshed = 0, missing = [], projectRootForLog = '';
  try { $('btn-doctor-relink').setAttribute('disabled', 'true'); } catch (e) { /* cosmetic UI; button may not exist in this layout */ }
  try { $('btn-doctor-analyze').setAttribute('disabled', 'true'); } catch (e) { /* cosmetic UI; button may not exist in this layout */ }
  setDoctorStatus('Searching for local copies + relinking…', 'waiting');
  setDoctorProgress(10, 'Reading project bin…');
  log('=== Project Doctor relink (build ' + DOCTOR_BUILD + ') ===');
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active project — open a project in Premiere first.');
    var projPath = ''; try { projPath = (project.path || '').replace(/\\/g, '/').replace(/^file:\/\//, ''); } catch (e) { log('project.path threw: ' + (e && e.message)); }
    var projectRoot = projPath ? projPath.replace(/\/[^\/]*$/, '')
      : (projectState.folderPath ? projectState.folderPath.replace(/\\/g, '/').replace(/\/+$/, '') : '');
    if (!projectRoot) throw new Error('Project has no saved path — save the .prproj once, then retry.');
    // .prproj usually sits in 02_Edit/ — walk up to the REAL project root, otherwise the
    // media index never sees 01_Source/Video/<scene>/ where the originals live.
    projectRoot = await resolveProjectRoot(projectRoot);
    projectRootForLog = projectRoot;
    var extra = ''; try { extra = ($('doctor-extra-root').value || '').trim().replace(/\/+$/, ''); } catch (e) { /* optional field; roots line below shows what was used */ }
    var roots = [projectRoot]; if (extra && extra !== projectRoot) roots.push(extra);
    log('roots = ' + roots.join('  |  '));

    setDoctorProgress(30, 'Indexing local media…');
    var idx = await doctorBuildIndex(roots, log);

    setDoctorProgress(55, 'Relinking offline clips…');
    var media = await doctorCollectMedia(project);   // records now carry .item (the bin ProjectItem)
    var done = {};
    for (var i = 0; i < media.length; i++) {
      var m = media[i];
      if (!m.item) continue;
      // D17: path resolving on disk no longer means "fine". A clip can be GHOST OFFLINE —
      // Premiere latched it offline (unplugged volume, importer crash) while the file sits
      // right there. D16 skipped exactly these, which is why Relink "did nothing" for them.
      if (await doctorPathExists(m.mediaPath)) {
        if ((await doctorIsOfflineInPremiere(m.item)) !== true) continue;   // genuinely linked → leave it
        log('  GHOST ' + (m.name || doctorBasename(m.mediaPath)) + ' — offline in Premiere, file present → force refresh');
        var gres = await doctorForceRefreshItem(m.item, m.mediaPath, log);
        if (gres === 'ok') refreshed++; else if (gres === 'skip') skipped++; else failed++;
        continue;
      }
      // Build candidate basenames in priority order. Editors often rename/export with a
      // DOUBLED extension ("Vostorg B4382.MP4.mp4") while the bin clip NAME stays clean
      // ("Vostorg B4382.MP4") — so try the media-path basename AND the clip name AND a
      // de-doubled-extension variant of each, before giving up.
      var pbn = doctorBasename(m.mediaPath);
      var cands = [];
      var addCand = function (x) { if (x && cands.indexOf(x) < 0) cands.push(x); };
      addCand(pbn); addCand(m.name);
      [pbn, m.name].forEach(function (x) { if (!x) return; var d = x.replace(/\.([A-Za-z0-9]{2,4})\.([A-Za-z0-9]{2,4})$/, '.$1'); addCand(d); });
      if (!cands.length) continue;
      var dkey = (m.name || pbn).toLowerCase();
      if (done[dkey]) continue;
      var target = null, via = '';
      for (var ci = 0; ci < cands.length && !target; ci++) { var ek = cands[ci].toLowerCase(); if (idx.exact[ek]) { target = idx.exact[ek]; via = 'exact'; } }
      if (!target) { for (var cj = 0; cj < cands.length && !target; cj++) { var nk = doctorNormName(cands[cj]); if (nk && idx.norm[nk]) { target = idx.norm[nk]; via = 'alias'; } } }
      if (!target) { missing.push(m.name || pbn); log('  MISS ' + (m.name || pbn) + '  [tried: ' + cands.join(' | ') + ']'); continue; }
      var res = await doctorRelinkItem(m.item, target, log);
      if (res === 'ok') { relinked++; done[dkey] = 1; log('  OK   ' + (m.name || pbn) + '  (' + via + ') → ' + target); }
      else if (res === 'skip') { skipped++; }
      else { failed++; log('  FAIL ' + (m.name || pbn) + ' → ' + target); }
    }
    log('relinked=' + relinked + ' ghostRefreshed=' + refreshed + ' failed=' + failed + ' skipped=' + skipped + ' stillMissing=' + missing.length);

    if ((relinked || refreshed) && project.save) { setDoctorProgress(75, 'Saving project…'); try { await project.save(); log('project saved'); } catch (e) { log('save threw: ' + (e && e.message)); } }

    setDoctorProgress(85, 'Re-analyzing…');
    try { await onDoctorAnalyze(); } catch (e) { log('re-analyze threw: ' + (e && e.message)); }

    var msg = 'Relinked ' + relinked + (refreshed ? (' · ' + refreshed + ' ghost-offline refreshed') : '') +
      (failed ? (' · ' + failed + ' failed') : '') +
      (missing.length ? (' · ' + missing.length + ' still need editor') : ' · all resolved ✅');
    setDoctorStatus(msg, (missing.length || failed) ? 'error' : 'ready');
    setDoctorProgress(100, 'Done');
    try {
      $('doctor-validation').innerHTML = missing.length
        ? '<div style="margin-top:8px;color:#ff9800;font-size:11px"><b>Still missing (no local copy — request from editor):</b><br>' + missing.map(escapeHtml).join('<br>') + '</div>'
        : '<div style="margin-top:8px;color:#4caf50;font-size:11px">All offline clips relinked from local copies. Review &amp; ⌘S.</div>';
    } catch (e) { /* cosmetic summary; status line carries the counts */ }
  } catch (e) {
    log('ERROR: ' + (e && e.message ? e.message : String(e)));
    if (e && e.stack) log('STACK: ' + e.stack);
    setDoctorStatus('Relink error: ' + (e && e.message ? e.message : String(e)), 'error', e);
    setDoctorProgress(100, 'Error');
  } finally {
    try { $('btn-doctor-relink').removeAttribute('disabled'); } catch (e) { /* cosmetic UI; button may not exist in this layout */ }
    try { $('btn-doctor-analyze').removeAttribute('disabled'); } catch (e) { /* cosmetic UI; button may not exist in this layout */ }
    doctorLogFn = function () {};
    try { await doctorWriteDebug('=== Project Doctor relink debug ===\n' + dbg.join('\n') + '\n', projectRootForLog); } catch (e) { /* debug writer is self-guarded; nowhere left to log */ }
    if (doctorState.lastDebugPath) { try { $('btn-doctor-debug').removeAttribute('disabled'); } catch (e) { /* cosmetic: button state only */ } }
  }
}

/* ───────────── D17: Force refresh — repair ghost-offline clips in place ─────────────────────
   Standalone counterpart to Find & Relink local. Relink answers "the file moved, where is it
   now?"; this answers "the file never moved, Premiere just stopped believing in it". Touches
   ONLY clips Premiere reports offline, and re-points each to the very path it already has.
   When the build exposes no offline flag, it refuses to guess unless the user opts in to the
   blind sweep — bouncing 500 healthy clips to fix one is not a trade worth making silently. */
async function onDoctorForceRefresh() {
  var dbg = [];
  function log(m) { dbg.push(new Date().toISOString().slice(11, 19) + '  ' + m); try { console.log('[Doctor force-refresh] ' + m); } catch (e) { /* console mirror; dbg[] already holds the line */ } }
  doctorLogFn = log;
  var refreshed = 0, failed = 0, skipped = 0, noFile = [], projectRootForLog = '';
  try { $('btn-doctor-forcerefresh').setAttribute('disabled', 'true'); } catch (e) { /* cosmetic: static button, disable only */ }
  try { $('btn-doctor-relink').setAttribute('disabled', 'true'); } catch (e) { /* cosmetic: static button, disable only */ }
  try { $('btn-doctor-analyze').setAttribute('disabled', 'true'); } catch (e) { /* cosmetic: static button, disable only */ }
  setDoctorStatus('Force-refreshing ghost-offline clips…', 'waiting');
  setDoctorProgress(10, 'Reading project bin…');
  log('=== Project Doctor force-refresh (build ' + DOCTOR_BUILD + ') ===');
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active project — open a project in Premiere first.');
    var projPath = ''; try { projPath = (project.path || '').replace(/\\/g, '/').replace(/^file:\/\//, ''); } catch (e) { log('project.path unreadable: ' + (e && e.message)); }
    var projectRoot = projPath ? projPath.replace(/\/[^\/]*$/, '')
      : (projectState.folderPath ? projectState.folderPath.replace(/\\/g, '/').replace(/\/+$/, '') : '');
    if (projectRoot) projectRoot = await resolveProjectRoot(projectRoot);
    projectRootForLog = projectRoot;

    var scopeEl = document.querySelector('input[name="doctor-scope"]:checked');
    var scope = scopeEl ? scopeEl.value : 'active';
    var blind = false; try { var cb = $('doctor-force-blind'); blind = !!(cb && (cb.checked || cb.getAttribute('checked') !== null)); } catch (e) { /* cb null-guarded; resolved value logged next line */ }
    log('scope=' + scope + ' blindSweep=' + blind);

    setDoctorProgress(30, 'Asking Premiere which clips are offline…');
    var media = await doctorCollectMedia(project);
    var usedByName = null;
    if (scope === 'active') {
      var usage = await doctorCollectUsage(project, 'active');
      usedByName = usage.usedByName || {};
      log('active-scope sequences = ' + (usage.sequences || []).join(', ') + ' · distinct used sources = ' + Object.keys(usedByName).length);
    }

    var cands = [], anyFlag = false, seenName = {};
    for (var i = 0; i < media.length; i++) {
      var m = media[i];
      if (!m.item || !m.mediaPath) continue;
      var key = (m.name || doctorBasename(m.mediaPath)).toLowerCase();
      if (seenName[key]) continue;
      if (usedByName && !usedByName[m.name]) continue;          // active scope → only what this timeline uses
      var off = await doctorIsOfflineInPremiere(m.item);
      if (off !== null) anyFlag = true;
      var exists = await doctorPathExists(m.mediaPath);
      if (off === true) { seenName[key] = 1; cands.push({ m: m, exists: exists, why: 'premiere-offline' }); }
      else if (off === null && blind && exists) { seenName[key] = 1; cands.push({ m: m, exists: exists, why: 'blind-sweep' }); }
    }
    log('candidates = ' + cands.length + ' (offline flag readable on this build: ' + (anyFlag ? 'yes' : 'NO') + ')');

    if (!cands.length) {
      var why = anyFlag
        ? 'Premiere reports no offline clips in this scope — nothing to refresh.'
        : 'This Premiere build exposes no offline flag. Tick “blind sweep” to bounce every clip in scope.';
      log(why);
      setDoctorStatus(why, anyFlag ? 'ready' : 'error');
      setDoctorProgress(100, 'Nothing to do');
      try { $('doctor-validation').innerHTML = '<div style="margin-top:8px;color:#ff9800;font-size:11px">' + escapeHtml(why) + '</div>'; } catch (e) { /* cosmetic: status line already carries the message */ }
      return;
    }

    setDoctorProgress(55, 'Re-importing ' + cands.length + ' clip(s)…');
    for (var c = 0; c < cands.length; c++) {
      var it = cands[c];
      var nm = it.m.name || doctorBasename(it.m.mediaPath);
      if (!it.exists) { noFile.push(nm); log('  SKIP ' + nm + ' — offline AND file missing → use 🔗 Find & Relink local'); skipped++; continue; }
      log('  FIX  ' + nm + '  [' + it.why + ']  ' + it.m.mediaPath);
      var res = await doctorForceRefreshItem(it.m.item, it.m.mediaPath, log);
      if (res === 'ok') refreshed++; else if (res === 'skip') skipped++; else failed++;
      setDoctorProgress(55 + Math.round(20 * (c + 1) / cands.length), 'Re-importing ' + (c + 1) + '/' + cands.length + '…');
    }
    log('refreshed=' + refreshed + ' failed=' + failed + ' skipped=' + skipped + ' missingFile=' + noFile.length);

    if (refreshed && project.save) { setDoctorProgress(78, 'Saving project…'); try { await project.save(); log('project saved'); } catch (e) { log('save threw: ' + (e && e.message)); } }

    setDoctorProgress(88, 'Re-analyzing…');
    try { await onDoctorAnalyze(); } catch (e) { log('re-analyze threw: ' + (e && e.message)); }

    var msg = 'Force-refreshed ' + refreshed + ' of ' + cands.length +
      (failed ? (' · ' + failed + ' failed') : '') +
      (noFile.length ? (' · ' + noFile.length + ' truly missing → use Relink') : '');
    setDoctorStatus(msg, (failed || noFile.length) ? 'error' : 'ready');
    setDoctorProgress(100, 'Done');
    try {
      $('doctor-validation').innerHTML = noFile.length
        ? '<div style="margin-top:8px;color:#ff9800;font-size:11px"><b>Offline AND file missing — these need 🔗 Find &amp; Relink local (or the editor):</b><br>' + noFile.map(escapeHtml).join('<br>') + '</div>'
        : '<div style="margin-top:8px;color:#4caf50;font-size:11px">Ghost-offline clips re-imported in place. Review &amp; ⌘S.</div>';
    } catch (e) { /* cosmetic: status line already carries the message */ }
  } catch (e) {
    log('ERROR: ' + (e && e.message ? e.message : String(e)));
    if (e && e.stack) log('STACK: ' + e.stack);
    setDoctorStatus('Force-refresh error: ' + (e && e.message ? e.message : String(e)), 'error', e);
    setDoctorProgress(100, 'Error');
  } finally {
    try { $('btn-doctor-forcerefresh').removeAttribute('disabled'); } catch (e) { /* cosmetic: static button re-enable */ }
    try { $('btn-doctor-relink').removeAttribute('disabled'); } catch (e) { /* cosmetic: static button re-enable */ }
    try { $('btn-doctor-analyze').removeAttribute('disabled'); } catch (e) { /* cosmetic: static button re-enable */ }
    doctorLogFn = function () {};
    try { await doctorWriteDebug('=== Project Doctor force-refresh debug ===\n' + dbg.join('\n') + '\n', projectRootForLog); } catch (e) { /* helper logs its own failure; dbg has no other sink */ }
    if (doctorState.lastDebugPath) { try { $('btn-doctor-debug').removeAttribute('disabled'); } catch (e) { /* cosmetic: button state only */ } }
  }
}

/* ───────────── Doctor: Restore structure (place files at the paths the project records) ─────
   D11 relink re-points clips via changeMediaFilePath — great for regular media, but it can't
   relink After-Effects Dynamic-Link .aep comps (and misses wrong-folder / renamed files). When
   an editor's project records media at HIS structure (e.g. /Users/user/Documents/Roman/<PROJECT>/
   01_Media/Ae_Projects/x.aep) and we downloaded the file to a different sub-folder, this places a
   same-name local COPY at the EXACT relative path the project expects (editor root → our project
   root), so Premiere resolves everything (incl. AE comps) by path on the next OPEN. Non-destructive
   (copy). Idempotent. Reopen the project after. */
function doctorTranslateToLocal(mediaPath, projectRoot, projBase) {
  var mp = String(mediaPath || '').replace(/\\/g, '/');
  var anchor = '/' + projBase + '/';
  var i = mp.indexOf(anchor);
  if (i < 0) return '';
  return projectRoot.replace(/\/+$/, '') + '/' + mp.slice(i + anchor.length);
}
async function doctorEnsureFolderAbs(absDir, log) {
  try { return await uxpfs.getEntryWithUrl('file://' + absDir); } catch (e) { /* probe: folder absent is created below */ }
  var parts = String(absDir).replace(/\/+$/, '').split('/');
  var idx = parts.length, base = null;
  for (; idx > 1; idx--) { try { base = await uxpfs.getEntryWithUrl('file://' + parts.slice(0, idx).join('/')); break; } catch (e) { /* probe: walk up to the first existing parent */ } }
  if (!base) return null;
  for (var j = idx; j < parts.length; j++) {
    try { base = await base.createFolder(parts[j]); }
    catch (e) { try { base = await uxpfs.getEntryWithUrl('file://' + parts.slice(0, j + 1).join('/')); } catch (e2) { if (log) log('   mkdir fail: ' + parts.slice(0, j + 1).join('/')); return null; } }
  }
  return base;
}
async function doctorPlaceFile(srcNativePath, destAbsPath, log) {
  var destDir = destAbsPath.replace(/\/[^\/]*$/, '');
  var destName = destAbsPath.split('/').pop();
  var folder = await doctorEnsureFolderAbs(destDir, log);
  if (!folder) return 'fail';
  var src = null; try { src = await uxpfs.getEntryWithUrl('file://' + srcNativePath); } catch (e) { if (log) log('   src missing: ' + srcNativePath); return 'fail'; }
  try { await src.copyTo(folder, { overwrite: false }); }
  catch (e) { if (log) log('   copyTo threw: ' + (e && e.message)); return 'fail'; }
  if (src.name !== destName) {   // recorded name differs (e.g. "C5391 (1).MP4") → rename the copy
    try {
      var copied = await uxpfs.getEntryWithUrl('file://' + String(folder.nativePath).replace(/\/+$/, '') + '/' + src.name);
      if (copied && copied.moveTo) await copied.moveTo(folder, { newName: destName, overwrite: false });
      else if (copied && copied.rename) await copied.rename(destName);
    } catch (e) { if (log) log('   rename after copy failed (left as ' + src.name + '): ' + (e && e.message)); }
  }
  return 'ok';
}
async function onDoctorRestoreStructure() {
  var dbg = [];
  function log(m) { dbg.push(new Date().toISOString().slice(11, 19) + '  ' + m); try { console.log('[Doctor restore] ' + m); } catch (e) { /* console mirror; dbg[] already holds the line */ } }
  doctorLogFn = log;
  var placed = 0, already = 0, failed = 0, missing = [], projectRootForLog = '';
  try { $('btn-doctor-restore').setAttribute('disabled', 'true'); } catch (e) { /* cosmetic: static button, disable only */ }
  try { $('btn-doctor-relink').setAttribute('disabled', 'true'); } catch (e) { /* cosmetic: static button, disable only */ }
  try { $('btn-doctor-analyze').setAttribute('disabled', 'true'); } catch (e) { /* cosmetic: static button, disable only */ }
  setDoctorStatus('Restoring structure — placing files at recorded paths…', 'waiting');
  setDoctorProgress(10, 'Reading project…');
  log('=== Project Doctor restore-structure (build ' + DOCTOR_BUILD + ') ===');
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active project — open a project in Premiere first.');
    var projPath = ''; try { projPath = (project.path || '').replace(/\\/g, '/').replace(/^file:\/\//, ''); } catch (e) { log('project.path unreadable: ' + (e && e.message)); }
    var projectRoot = projPath ? projPath.replace(/\/[^\/]*$/, '')
      : (projectState.folderPath ? projectState.folderPath.replace(/\\/g, '/').replace(/\/+$/, '') : '');
    if (!projectRoot) throw new Error('Project has no saved path — save the .prproj once, then retry.');
    // .prproj usually sits in 02_Edit/ — walk up to the REAL project root, otherwise the
    // media index never sees 01_Source/Video/<scene>/ where the originals live.
    projectRoot = await resolveProjectRoot(projectRoot);
    projectRootForLog = projectRoot;
    var projBase = projectRoot.split('/').pop();
    var extra = ''; try { extra = ($('doctor-extra-root').value || '').trim().replace(/\/+$/, ''); } catch (e) { log('extra root unreadable: ' + (e && e.message)); }
    var roots = [projectRoot]; if (extra && extra !== projectRoot) roots.push(extra);
    log('projectRoot = ' + projectRoot + '  projBase = ' + projBase);

    setDoctorProgress(30, 'Indexing local files (incl. .aep)…');
    var idx = await doctorBuildIndex(roots, log);

    setDoctorProgress(55, 'Placing files at recorded paths…');
    var media = await doctorCollectMedia(project);
    var seen = {};
    for (var i = 0; i < media.length; i++) {
      var m = media[i];
      if (!m.mediaPath) continue;
      if (await doctorPathExists(m.mediaPath)) continue;                 // already online
      var dkey = String(m.mediaPath).toLowerCase();
      if (seen[dkey]) continue; seen[dkey] = 1;
      var exp = doctorTranslateToLocal(m.mediaPath, projectRoot, projBase);
      if (!exp) { missing.push(m.name); log('  SKIP external (no project anchor): ' + m.name); continue; }
      if (await doctorPathExists(exp)) { already++; continue; }          // already at recorded path
      var pbn = doctorBasename(m.mediaPath);
      var cands = []; var add = function (x) { if (x && cands.indexOf(x) < 0) cands.push(x); };
      add(pbn); add(m.name);
      [pbn, m.name].forEach(function (x) { if (!x) return; add(x.replace(/\.([A-Za-z0-9]{2,4})\.([A-Za-z0-9]{2,4})$/, '.$1')); });
      var src = null;
      for (var ci = 0; ci < cands.length && !src; ci++) { var ek = cands[ci].toLowerCase(); if (idx.exact[ek]) src = idx.exact[ek]; }
      if (!src) { for (var cj = 0; cj < cands.length && !src; cj++) { var nk = doctorNormName(cands[cj]); if (nk && idx.norm[nk]) src = idx.norm[nk]; } }
      if (!src) { missing.push(m.name); log('  MISS ' + m.name + '  [no local copy — need editor]'); continue; }
      if (String(src).replace(/\\/g, '/') === exp) { already++; continue; }
      var r = await doctorPlaceFile(src, exp, log);
      if (r === 'ok') { placed++; log('  PLACED ' + doctorBasename(exp) + '  <- ' + src); }
      else { failed++; log('  FAIL ' + m.name + ' -> ' + exp); }
    }
    log('placed=' + placed + ' already=' + already + ' failed=' + failed + ' stillMissing=' + missing.length);

    setDoctorProgress(85, 'Re-analyzing…');
    try { await onDoctorAnalyze(); } catch (e) { log('re-analyze threw: ' + (e && e.message)); }

    var msg = 'Placed ' + placed + (already ? (' · ' + already + ' already') : '') +
      (failed ? (' · ' + failed + ' failed') : '') +
      (missing.length ? (' · ' + missing.length + ' need editor') : '') +
      ' — reopen the project so Premiere relinks by path.';
    setDoctorStatus(msg, (missing.length || failed) ? 'error' : 'ready');
    setDoctorProgress(100, 'Done');
    try {
      $('doctor-validation').innerHTML = (placed
        ? '<div style="margin-top:8px;color:#4caf50;font-size:11px"><b>Placed ' + placed + ' file(s) at the paths the project records.</b> Close &amp; reopen the .prproj — Premiere relinks them (incl. AE Dynamic-Link comps) by path.</div>'
        : '<div style="margin-top:8px;color:#8a94ab;font-size:11px">Nothing to place — found files are already at their recorded paths.</div>')
        + (missing.length ? '<div style="margin-top:6px;color:#ff9800;font-size:11px"><b>Still missing (no local copy — request from editor):</b><br>' + missing.map(escapeHtml).join('<br>') + '</div>' : '');
    } catch (e) { /* cosmetic: status line already carries the message */ }
  } catch (e) {
    log('ERROR: ' + (e && e.message ? e.message : String(e)));
    if (e && e.stack) log('STACK: ' + e.stack);
    setDoctorStatus('Restore error: ' + (e && e.message ? e.message : String(e)), 'error', e);
    setDoctorProgress(100, 'Error');
  } finally {
    try { $('btn-doctor-restore').removeAttribute('disabled'); } catch (e) { /* cosmetic: static button re-enable */ }
    try { $('btn-doctor-relink').removeAttribute('disabled'); } catch (e) { /* cosmetic: static button re-enable */ }
    try { $('btn-doctor-analyze').removeAttribute('disabled'); } catch (e) { /* cosmetic: static button re-enable */ }
    doctorLogFn = function () {};
    try { await doctorWriteDebug('=== Project Doctor restore-structure debug ===\n' + dbg.join('\n') + '\n', projectRootForLog); } catch (e) { /* helper logs its own failure; dbg has no other sink */ }
    if (doctorState.lastDebugPath) { try { $('btn-doctor-debug').removeAttribute('disabled'); } catch (e) { /* cosmetic: button state only */ } }
  }
}

/* ───────────── Doctor: Make self-contained ─────────────────────────────────
   Стандарт: ВСЕ исходники должны лежать ВНУТРИ папки проекта (см. project_playbook).
   Find & Relink чинит только ОФЛАЙН-клипы. Но клип может быть ОНЛАЙН и при этом
   линковаться на СОСЕДНИЙ проект (…/YTRF05_…/NewAssets/x.mov) — тогда папку нельзя
   перенести целиком. Эта операция перецепляет КАЖДУЮ ссылку, ведущую наружу проекта,
   на in-project копию того же файла (индексируется ТОЛЬКО корень проекта). Чего нет
   внутри — выводит списком «скопировать в 02_Edit/NewAssets». */
async function onDoctorSelfContain() {
  var dbg = [];
  function log(m) { dbg.push(new Date().toISOString().slice(11, 19) + '  ' + m); try { console.log('[Doctor self-contain] ' + m); } catch (e) { /* console is optional; dbg[] already holds the line */ } }
  doctorLogFn = log;
  var repoint = 0, already = 0, failed = 0, needCopy = [], projectRootForLog = '';
  try { $('btn-doctor-selfcontain').setAttribute('disabled', 'true'); } catch (e) { /* non-fatal: button disable is cosmetic */ }
  try { $('btn-doctor-analyze').setAttribute('disabled', 'true'); } catch (e) { /* non-fatal: button disable is cosmetic */ }
  setDoctorStatus('Making project self-contained…', 'waiting');
  setDoctorProgress(10, 'Reading project bin…');
  log('=== Make self-contained (build ' + DOCTOR_BUILD + ') ===');
  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active project — open a project in Premiere first.');
    var projPath = ''; try { projPath = (project.path || '').replace(/\\/g, '/').replace(/^file:\/\//, ''); } catch (e) { /* fallback below: folderPath, else explicit throw */ }
    var projectRoot = projPath ? projPath.replace(/\/[^\/]*$/, '')
      : (projectState.folderPath ? projectState.folderPath.replace(/\\/g, '/').replace(/\/+$/, '') : '');
    if (!projectRoot) throw new Error('Project has no saved path — save the .prproj once, then retry.');
    // .prproj usually sits in 02_Edit/ — walk up to the REAL project root, otherwise the
    // media index never sees 01_Source/Video/<scene>/ where the originals live.
    projectRoot = await resolveProjectRoot(projectRoot);
    projectRootForLog = projectRoot;
    var rootPrefix = projectRoot.replace(/\/+$/, '') + '/';
    log('projectRoot = ' + projectRoot);

    setDoctorProgress(30, 'Indexing IN-PROJECT media…');
    var idx = await doctorBuildIndex([projectRoot], log);   // только корень проекта — нам нужны внутренние копии

    setDoctorProgress(55, 'Re-pointing external links inside the project…');
    var media = await doctorCollectMedia(project);
    var done = {};
    for (var i = 0; i < media.length; i++) {
      var m = media[i];
      if (!m.item) continue;
      var cur = (m.mediaPath || '').replace(/\\/g, '/');
      var inside = cur && cur.indexOf(rootPrefix) === 0;
      var present = await doctorPathExists(m.mediaPath);
      if (inside && present) { already++; continue; }            // уже самодостаточно
      var pbn = doctorBasename(m.mediaPath);
      var cands = [];
      var addCand = function (x) { if (x && cands.indexOf(x) < 0) cands.push(x); };
      addCand(pbn); addCand(m.name);
      [pbn, m.name].forEach(function (x) { if (!x) return; var d = x.replace(/\.([A-Za-z0-9]{2,4})\.([A-Za-z0-9]{2,4})$/, '.$1'); addCand(d); });
      var dkey = (m.name || pbn || '').toLowerCase();
      if (!dkey || done[dkey]) continue;
      var target = null;
      for (var ci = 0; ci < cands.length && !target; ci++) { var ek = cands[ci].toLowerCase(); if (idx.exact[ek]) target = idx.exact[ek]; }
      if (!target) { for (var cj = 0; cj < cands.length && !target; cj++) { var nk = doctorNormName(cands[cj]); if (nk && idx.norm[nk]) target = idx.norm[nk]; } }
      if (!target) { needCopy.push(m.name || pbn); log('  NEED-COPY ' + (m.name || pbn) + '   cur=' + (cur || '(offline)')); continue; }
      var res = await doctorRelinkItem(m.item, target, log);
      if (res === 'ok') { repoint++; done[dkey] = 1; log('  →IN  ' + (m.name || pbn) + '  → ' + target); }
      else if (res === 'skip') { /* nothing */ }
      else { failed++; log('  FAIL ' + (m.name || pbn) + ' → ' + target); }
    }
    log('repointed=' + repoint + ' alreadyInside=' + already + ' failed=' + failed + ' needCopy=' + needCopy.length);

    if (repoint && project.save) { setDoctorProgress(80, 'Saving project…'); try { await project.save(); log('project saved'); } catch (e) { log('save threw: ' + (e && e.message)); } }

    setDoctorProgress(90, 'Re-analyzing…');
    try { await onDoctorAnalyze(); } catch (e) { log('re-analyze threw: ' + (e && e.message)); }

    var msg = 'Self-contained: ' + repoint + ' re-pointed inside · ' + already + ' already' +
      (failed ? (' · ' + failed + ' failed') : '') + (needCopy.length ? (' · ' + needCopy.length + ' NOT in project') : ' ✅');
    setDoctorStatus(msg, (needCopy.length || failed) ? 'error' : 'ready');
    setDoctorProgress(100, 'Done');
    try {
      $('doctor-validation').innerHTML = needCopy.length
        ? '<div style="margin-top:8px;color:#ff9800;font-size:11px"><b>No copy INSIDE the project — copy the file(s) to 02_Edit/NewAssets and run again:</b><br>' + needCopy.map(escapeHtml).join('<br>') + '</div>'
        : '<div style="margin-top:8px;color:#4caf50;font-size:11px">All links point inside the project — the project is self-contained. Save (⌘S).</div>';
    } catch (e) { /* cosmetic: status line already carries the result */ }
  } catch (e) {
    log('ERROR: ' + (e && e.message ? e.message : String(e)));
    if (e && e.stack) log('STACK: ' + e.stack);
    setDoctorStatus('Self-contain error: ' + (e && e.message ? e.message : String(e)), 'error', e);
    setDoctorProgress(100, 'Error');
  } finally {
    try { $('btn-doctor-selfcontain').removeAttribute('disabled'); } catch (e) { /* non-fatal: button re-enable is cosmetic */ }
    try { $('btn-doctor-analyze').removeAttribute('disabled'); } catch (e) { /* non-fatal: button re-enable is cosmetic */ }
    doctorLogFn = function () {};
    try { await doctorWriteDebug('=== Make self-contained debug ===\n' + dbg.join('\n') + '\n', projectRootForLog); } catch (e) { /* doctorWriteDebug catches and console-logs internally */ }
    if (doctorState.lastDebugPath) { try { $('btn-doctor-debug').removeAttribute('disabled'); } catch (e) { /* non-fatal: button enable is cosmetic */ } }
  }
}

/**
 * Full debug dump — exports everything to 99_Pipeline/logs/{ts}/
 */
async function debugDump() {
  if (!projectState.folderPath) {
    setProjectStatus('Select project folder first', 'error');
    return;
  }

  $('btn-debug-dump').setAttribute('disabled', 'true');
  $('btn-debug-dump-compact').setAttribute('disabled', 'true');
  var _savedCompactName = $('project-compact-name').textContent;
  $('project-compact-name').textContent = 'Dumping...';
  $('project-compact-name').style.color = '#ff9800';
  setProjectStatus('Debug dump...', 'waiting');
  ingestLogger.info('=== DEBUG DUMP START ===');

  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active project');

    var fps = 25;
    if (ingestState.data && ingestState.data.media) fps = ingestState.data.media.fps || 25;

    // ── 1. Create timestamped folder in 99_Pipeline/logs/ ──
    var ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    var slug = (projectState.projectName || 'unknown').replace(/[^a-zA-Z0-9_-]/g, '_');
    var folderName = slug + '_dump_' + ts;

    var pipelinePath = projectState.folderPath + '/99_Pipeline';
    var pipelineEntry;
    try {
      pipelineEntry = await uxpfs.getEntryWithUrl('file://' + pipelinePath);
    } catch (e) {
      throw new Error('99_Pipeline folder not found at: ' + pipelinePath);
    }
    var logsEntry = await ensureSubfolder(pipelineEntry, 'logs', ingestLogger);
    var dumpFolder = await logsEntry.createFolder(folderName);
    var dumpPath = dumpFolder.nativePath || (pipelinePath + '/logs/' + folderName);
    ingestLogger.info('Dump folder: ' + dumpPath);

    // ── 2. project_state.json ──
    var stateData = {
      exported_at: new Date().toISOString(),
      projectState: {
        folderPath: projectState.folderPath,
        projectName: projectState.projectName,
        projectCode: projectState.projectCode,
        ingestPath: projectState.ingestPath,
        briefPath: projectState.briefPath,
        ingestDetected: projectState.ingestDetected,
        briefDetected: projectState.briefDetected
      },
      ingestState: { filePath: ingestState.filePath, hasData: !!ingestState.data },
      assemblyState: { filePath: assemblyState.filePath, hasData: !!assemblyState.data, segmentCount: (assemblyState.segments || []).length },
      reviewState: { filePath: reviewState.filePath, hasData: !!reviewState.data },
      premiere: { projectName: project.name, projectPath: project.path }
    };
    var stateFile = await dumpFolder.createFile('project_state.json', { overwrite: true });
    await stateFile.write(JSON.stringify(stateData, null, 2));
    ingestLogger.info('Wrote project_state.json');

    // ── 3. All sequences ──
    // Find sequences: active + all from root items (recursive cast)
    var activeSeq = await project.getActiveSequence();
    var activeSeqName = activeSeq ? activeSeq.name : null;
    var allSequences = [];
    var seenNames = {};

    // Always include active sequence first
    if (activeSeq) {
      allSequences.push(activeSeq);
      seenNames[activeSeq.name] = true;
    }

    // Enumerate REAL sequences (getSequences-first — root-cast alone only sees the
    // active sequence in some builds and misled diagnosis of this very dump).
    var dumpSeqEntries = await listProjectSequences(project, ingestLogger);
    for (var ri = 0; ri < dumpSeqEntries.length; ri++) {
      if (!seenNames[dumpSeqEntries[ri].name]) {
        allSequences.push(dumpSeqEntries[ri].seq);
        seenNames[dumpSeqEntries[ri].name] = true;
      }
    }

    // Note expected-but-missing scene sequences instead of poking stubs with
    // openSequence (that opened/threw on name-matched non-sequences).
    if (ingestState.data) {
      var dumpExpected = expectedIngestSequenceNames(ingestState.data);
      var missingSeqs = Object.keys(dumpExpected).filter(function (n) { return !seenNames[n]; });
      if (missingSeqs.length) ingestLogger.info('Dump: expected sequences not in project: ' + missingSeqs.join(', '));
    }

    // Restore active sequence
    if (activeSeq) {
      try { await project.setActiveSequence(activeSeq); } catch (e) { ingestLogger.debug('Dump: restore active sequence failed: ' + (e && e.message)); }
    }

    ingestLogger.info('Found ' + allSequences.length + ' sequence(s): ' + Object.keys(seenNames).join(', '));

    // Build a filename → ingest-clip lookup so each TrackItem in the dump is
    // enriched with its wall-clock / sync truth (creation_time, wall_offset,
    // clock_offset, probe.fps, camera, sync{}). This is the key pairing for
    // verifying multi-camera sync directly from the dump.
    var ingestByName = {};
    try {
      var _clips = (ingestState.data && ingestState.data.clips) || [];
      for (var _ci = 0; _ci < _clips.length; _ci++) {
        var _c = _clips[_ci];
        if (_c.filename) ingestByName[_c.filename] = _c;
        if (_c.filename) ingestByName[String(_c.filename).replace(/\.[^.]+$/, '')] = _c;
        if (_c.clip_id) ingestByName[_c.clip_id] = _c;
      }
    } catch (e) { ingestLogger.warn('ingestByName build failed: ' + e.message); }

    var seqDumps = [];
    for (var si = 0; si < allSequences.length; si++) {
      ingestLogger.info('Dumping sequence: ' + allSequences[si].name);
      var seqData = await dumpSequence(allSequences[si], fps, ingestByName);
      seqData.is_active = (seqData.name === activeSeqName);
      seqDumps.push(seqData);
    }

    var seqFile = await dumpFolder.createFile('all_sequences.json', { overwrite: true });
    await seqFile.write(JSON.stringify(seqDumps, null, 2));
    ingestLogger.info('Wrote all_sequences.json (' + seqDumps.length + ' sequences)');

    // ── 4. Active sequence (separate file for quick access) ──
    var activeData = seqDumps.find(function(s) { return s.is_active; });
    if (activeData) {
      var activeFile = await dumpFolder.createFile('active_sequence.json', { overwrite: true });
      await activeFile.write(JSON.stringify(activeData, null, 2));
      ingestLogger.info('Wrote active_sequence.json: ' + activeData.name);
    }

    // ── 5. Ingest copy ──
    if (ingestState.data) {
      var ingestFile = await dumpFolder.createFile('ingest_copy.json', { overwrite: true });
      await ingestFile.write(JSON.stringify(ingestState.data, null, 2));
      ingestLogger.info('Wrote ingest_copy.json');
    }

    // ── 6. Brief copy ──
    if (assemblyState.data) {
      var briefFile = await dumpFolder.createFile('brief_copy.json', { overwrite: true });
      await briefFile.write(JSON.stringify(assemblyState.data, null, 2));
      ingestLogger.info('Wrote brief_copy.json');
    }

    // ── 7. All logs combined ──
    var allLogs = [
      ingestLogger.getReport(),
      '\\n\\n' + assemblyLogger.getReport(),
      '\\n\\n' + reviewLogger.getReport(),
      '\\n\\n' + screensLogger.getReport(),
      '\\n\\n' + deletedSceneLogger.getReport()
    ].join('');
    var logsFile = await dumpFolder.createFile('all_logs.txt', { overwrite: true });
    await logsFile.write(allLogs);
    ingestLogger.info('Wrote all_logs.txt');

    // ── 8. Filesystem check ──
    if (ingestState.data) {
      var fsCheck = { clips: [], dji_audio: [], files: {} };
      for (var fci = 0; fci < ingestState.data.clips.length; fci++) {
        var fc = ingestState.data.clips[fci];
        var clipExists = false;
        try { await uxpfs.getEntryWithUrl('file://' + fc.path); clipExists = true; } catch (e) { /* probe: absence is the recorded result (exists=false) */ }
        fsCheck.clips.push({ clip_id: fc.clip_id, path: fc.path, exists: clipExists });
        if (fc.dji_audio) {
          for (var di = 0; di < fc.dji_audio.length; di++) {
            var djiExists = false;
            try { await uxpfs.getEntryWithUrl('file://' + fc.dji_audio[di].path); djiExists = true; } catch (e) { /* probe: absence is the recorded result (exists=false) */ }
            fsCheck.dji_audio.push({ clip_id: fc.clip_id, tx: fc.dji_audio[di].tx, path: fc.dji_audio[di].path, exists: djiExists });
          }
        }
      }
      // Check key files
      var keyFiles = ['transcript_json', 'transcript_srt', 'transcript_xlsx', 'captions_srt'];
      for (var kfi = 0; kfi < keyFiles.length; kfi++) {
        var kf = keyFiles[kfi];
        var kfPath = (ingestState.data.files || {})[kf] || '';
        if (kfPath) {
          var kfExists = false;
          try { await uxpfs.getEntryWithUrl('file://' + kfPath); kfExists = true; } catch (e) { /* probe: absence is the recorded result (exists=false) */ }
          fsCheck.files[kf] = { path: kfPath, exists: kfExists };
        }
      }
      var missingClips = fsCheck.clips.filter(function(c) { return !c.exists; });
      var missingDji = fsCheck.dji_audio.filter(function(d) { return !d.exists; });
      fsCheck.summary = { total_clips: fsCheck.clips.length, missing_clips: missingClips.length, total_dji: fsCheck.dji_audio.length, missing_dji: missingDji.length };
      var fsFile = await dumpFolder.createFile('filesystem_check.json', { overwrite: true });
      await fsFile.write(JSON.stringify(fsCheck, null, 2));
      ingestLogger.info('Wrote filesystem_check.json (missing: ' + missingClips.length + ' clips, ' + missingDji.length + ' dji)');
    }

    // ── 9. Premiere bin tree ──
    var rootItem = await project.getRootItem();
    var binTree = await dumpBinTree(rootItem, 0);
    var binFile = await dumpFolder.createFile('premiere_bins.json', { overwrite: true });
    await binFile.write(JSON.stringify(binTree, null, 2));
    ingestLogger.info('Wrote premiere_bins.json');

    // ── 10. Screenshot via trigger file → screenshot_watcher.sh ──
    try {
      var screenshotPath = dumpPath + '/screenshot.png';
      var triggerEntry = await uxpfs.getEntryWithUrl('file:///tmp');
      var triggerFile = await triggerEntry.createFile('ytai_screenshot.trigger', { overwrite: true });
      await triggerFile.write(screenshotPath);
      ingestLogger.info('Screenshot trigger written → ' + screenshotPath);
    } catch (ssErr) {
      ingestLogger.warn('Screenshot trigger failed: ' + ssErr.message);
    }

    // ── Copy path to clipboard ──
    try { await navigator.clipboard.writeText(dumpPath); } catch (e) { ingestLogger.debug('Clipboard copy of dump path failed: ' + (e && e.message)); }
    ingestLogger.info('=== DEBUG DUMP COMPLETE === Path: ' + dumpPath);
    setProjectStatus('Dump → ' + folderName + ' (path copied)', 'ready');
    $('project-compact-name').textContent = _savedCompactName + ' ✓';
    $('project-compact-name').style.color = '#c8e64a';
    setTimeout(function() { $('project-compact-name').textContent = _savedCompactName; $('project-compact-name').style.color = ''; }, 3000);

  } catch (err) {
    ingestLogger.error('Debug dump failed: ' + err.message, err);
    setProjectStatus('Dump failed: ' + err.message, 'error', err);
    $('project-compact-name').textContent = _savedCompactName + ' ✗';
    $('project-compact-name').style.color = '#f44336';
    setTimeout(function() { $('project-compact-name').textContent = _savedCompactName; $('project-compact-name').style.color = ''; }, 3000);
  }

  $('btn-debug-dump').removeAttribute('disabled');
  $('btn-debug-dump-compact').removeAttribute('disabled');
}

// --- Initialization ---

document.addEventListener('DOMContentLoaded', () => {
  // PROJECT buttons
  on('btn-select-project', selectProjectFolder);
  on('btn-use-open-project', function () { useOpenProjectFolder(); });
  on('btn-copy-project-prompt', copyProjectPrompt);
  // Auto-fill the folder from the OPEN Premiere project on load (parity with Footage).
  // Silent: does nothing if no project is open or it is unsaved (untitled).
  if (!projectState.folderPath) {
    useOpenProjectFolder({ silent: true }).catch(function () { /* non-fatal */ });
  }
  on('btn-copy-markers-prompt', copyMarkersPrompt);
  on('btn-refresh-project', refreshProject);
  on('btn-debug-dump', debugDump);

  // PROJECT compact bar — toggle expand, wire compact buttons
  // sp-button uses Shadow DOM so e.target.closest('sp-button') fails.
  // Use stopPropagation on buttons to prevent toggle from firing.
  on('btn-refresh-compact', function(e) {
    e.stopPropagation();
    refreshProject();
  });
  on('btn-debug-dump-compact', function(e) {
    e.stopPropagation();
    debugDump();
  });
  on('btn-copy-error', function(e) {
    e.stopPropagation();
    copyLastError();
  });
  on('project-compact-bar', function() {
    toggleProjectExpand();
  });

  // INGEST buttons (btn-load-ingest is fallback — hidden by default)
  on('btn-load-ingest', loadIngest);
  on('btn-build-ingest', buildIngest);
  // 📁 Hide source timelines — same action on the Ingest and Doctor tabs (status → own tab)
  on('btn-hide-source-timelines', function () {
    onHideSourceTimelines(setIngestStatus).catch(function (e) {
      setIngestStatus('Hide source timelines: ' + (e && e.message ? e.message : e), 'error', e);
    });
  });
  on('btn-finesync', runFineSync);
  on('btn-sync-spread', spreadForSync);
  on('btn-sync-select', selectForSyncClick);
  on('btn-sync-clean', cleanStraysClick);
  on('btn-sync-collect', collectFromSync);
  on('btn-verify-ingest', verifyIngest);
  on('btn-sync-audio', syncAudio);
  on('btn-chapter-markers', function () {
    applyChapterMarkersToActive().catch(function (e) {
      setIngestStatus('Chapter markers: ' + (e && e.message ? e.message : e), 'error', e);
    });
  });
  on('btn-chapter-markers-all', function () {
    applyChapterMarkersToAll().catch(function (e) {
      setIngestStatus('Chapters → all: ' + (e && e.message ? e.message : e), 'error', e);
    });
  });

  // PARTS picker — тот же выбор галочками, что и «Sequences to build» в Ingest
  on('parts-pick-new', function (e) { e.preventDefault(); setPickChecks('parts','new'); });
  on('parts-pick-all', function (e) { e.preventDefault(); setPickChecks('parts','all'); });
  on('parts-pick-none', function (e) { e.preventDefault(); setPickChecks('parts','none'); });
  on('parts-pick-refresh', function (e) {
    e.preventDefault();
    refreshPick('parts').catch(function (er) { setPartsStatus('Parts list: ' + (er && er.message), 'error', er); });
  });
  on('btn-parts-pick-build', function () {
    buildPicked('parts').catch(function (e) { setPartsStatus('Build: ' + (e && e.message ? e.message : e), 'error', e); });
  });

  // REVIEW picker — тот же выбор галочками; ревью-версии собираются здесь, а не в Parts
  on('review-pick-new', function (e) { e.preventDefault(); setPickChecks('review', 'new'); });
  on('review-pick-all', function (e) { e.preventDefault(); setPickChecks('review', 'all'); });
  on('review-pick-none', function (e) { e.preventDefault(); setPickChecks('review', 'none'); });
  on('review-pick-refresh', function (e) {
    e.preventDefault();
    refreshPick('review').catch(function (er) { setReviewStatus('Review list: ' + (er && er.message), 'error', er); });
  });
  on('btn-note-add', addReviewNote);
  on('btn-note-copyall', copyAllReviewNotes);
  on('btn-note-sheet', openNotesSheet);
  on('btn-tz-copy', copyTzAtPlayhead);
  on('btn-review-pick-build', function () {
    buildPicked('review').catch(function (e) { setReviewStatus('Build: ' + (e && e.message ? e.message : e), 'error', e); });
  });
  // очередь заданий из терминала — тикаем, пока панель открыта
  setInterval(function () { jobTick().catch(function (e) { assemblyLogger.debug('jobTick: ' + (e && e.message || e)); }); }, 3000);

  // INGEST scene selection quick-links (new = only unbuilt scenes)
  on('ingest-scenes-new', function (e) { e.preventDefault(); setIngestSceneChecks('new'); });
  on('ingest-scenes-all', function (e) { e.preventDefault(); setIngestSceneChecks('all'); });
  on('ingest-scenes-none', function (e) { e.preventDefault(); setIngestSceneChecks('none'); });

  // PARTS buttons (build-by-part stage)
  on('btn-load-part', function () { loadPart().catch(function (e) { setPartsStatus('Error: ' + (e && e.message ? e.message : e), 'error', e); }); });
  on('btn-build-part', function () { buildParts().catch(function (e) { setPartsStatus('Error: ' + (e && e.message ? e.message : e), 'error', e); }); });
  // Parts "Out": same exporter as Review — dumps the ACTIVE sequence to 05_Review + copies path to clipboard.
  on('btn-export-part-out', function () {
    exportSequenceJson().catch(function (e) { setPartsStatus('Export error: ' + (e && e.message ? e.message : e), 'error', e); });
  });
  // SELECTIONS (подборки): checkbox list of parts/selections/*.json → build/archive
  // ⚠️ $() отдаёт null, и addEventListener на нём бросает — одна убранная из
  // разметки кнопка гасила бы ВСЕ привязки ниже по списку. Поэтому цветные
  // кнопки вешаем через on(): нет элемента — просто пропускаем.
  on('btn-color-plan-all', function () { runColorFromPlan(true); });
  on('btn-color-plan-active', function () { runColorFromPlan(false); });
  // Кнопки поколения 1 (Apply LUT Layers / Active Sequence Only / Probe Donor
  // Clone / Build LUT Donor) убраны 25.09.2026: они читают {CODE}_lut_plan.json,
  // которого больше никто не пишет, ставят только Look и ищут кубы прошлого
  // поколения. Код функций оставлен — на него ещё ссылается донорский путь.
  on('btn-sel-refresh', function () { selRefresh().catch(function (e) { setPartsStatus('Selections: ' + (e && e.message ? e.message : e), 'error', e); }); });
  on('btn-sel-build', function () { selBuild().catch(function (e) { setPartsStatus('Selections build: ' + (e && e.message ? e.message : e), 'error', e); }); });
  on('btn-sel-archive', function () { selArchive().catch(function (e) { setPartsStatus('Selections archive: ' + (e && e.message ? e.message : e), 'error', e); }); });
  on('btn-export-audio-map', exportAudioMap);
  on('btn-verify-sync', verifySync);

  // SHORTS buttons (moments → 9:16 sequences; wired directly — sp-button Shadow DOM breaks closest())
  on('btn-shorts-refresh', function () {
    shortsRefresh().catch(function (e) { shortsLogger.error('refresh: ' + (e && e.message ? e.message : e)); setShortsStatus('Error: ' + (e && e.message ? e.message : e), 'error', e); });
  });
  on('btn-shorts-preview', function () {
    shortsBuildPreview().catch(function (e) { shortsLogger.error('preview: ' + (e && e.message ? e.message : e)); setShortsStatus('Error: ' + (e && e.message ? e.message : e), 'error', e); });
  });
  on('btn-shorts-readback', function () {
    shortsReadBackMarkers().catch(function (e) { shortsLogger.error('read-back: ' + (e && e.message ? e.message : e)); setShortsStatus('Error: ' + (e && e.message ? e.message : e), 'error', e); });
  });
  on('btn-shorts-build', function () {
    shortsBuildApproved().catch(function (e) { shortsLogger.error('build: ' + (e && e.message ? e.message : e)); setShortsStatus('Error: ' + (e && e.message ? e.message : e), 'error', e); });
  });
  on('btn-shorts-out', function () {
    shortsExportOut().catch(function (e) { shortsLogger.error('out: ' + (e && e.message ? e.message : e)); setShortsStatus('Error: ' + (e && e.message ? e.message : e), 'error', e); });
  });
  on('btn-shorts-open-html', function () {
    shortsOpenReviewHtml().catch(function (e) { shortsLogger.error('open html: ' + (e && e.message ? e.message : e)); setShortsStatus('Error: ' + (e && e.message ? e.message : e), 'error', e); });
  });

  // ASSEMBLY buttons (btn-load-brief is fallback — hidden by default)
  on('btn-load-brief', loadBrief);
  on('btn-build-assembly', buildAssembly);
  on('btn-export-markers', exportMarkers);
  on('btn-debug-export', debugExport);
  on('btn-fill-left', function() { applyAudioFill('Fill Right with Left'); }); // L→R
  on('btn-fill-right', function() { applyAudioFill('Fill Left with Right'); }); // R→L
  on('btn-voice-enhance', applyVoiceEnhance);
  on('btn-remove-audio-fx', removeAudioEffects);

  // ASSEMBLY scene timelines (scenes/ bundles) quick-links + build buttons.
  // Wired directly on elements — sp-button Shadow DOM breaks closest().
  on('assembly-scenes-new', function (e) { e.preventDefault(); setAssemblySceneChecks('new'); });
  on('assembly-scenes-all', function (e) { e.preventDefault(); setAssemblySceneChecks('all'); });
  on('assembly-scenes-none', function (e) { e.preventDefault(); setAssemblySceneChecks('none'); });
  on('btn-build-assembly-scenes', function () { buildAssemblyScenes().catch(function (e) { setAssemblyStatus('Error: ' + (e && e.message ? e.message : e), 'error', e); }); });
  on('btn-build-premontage', function () { buildPremontage().catch(function (e) { setAssemblyStatus('Error: ' + (e && e.message ? e.message : e), 'error', e); }); });

  // DELETED SCENE buttons
  on('btn-build-deleted-scene', buildDeletedScene);

  // REVIEW buttons (external editor review)
  on('btn-process-review', processReview);
  on('btn-load-review-brief', loadReviewBrief);
  on('btn-build-review', buildReview);
  on('btn-build-review-overlay', buildReviewOverlay);
  on('btn-build-review-v3', buildReviewV3);
  on('btn-export-sequence-json', exportSequenceJson);
  on('btn-export-review-markers', exportReviewMarkers);

  // PRE-EDIT buttons (wrap async to catch unhandled rejections)
  on('btn-export-pre-edit-doc', function() {
    exportPreEditDoc().catch(function (e) { setScreensStatus('Doc export error: ' + (e && e.message || e), 'error', e); });
  });
  on('btn-copy-pre-edit-prompt', function() {
    copyPreEditPrompt().catch(function (e) { setScreensStatus('Copy Prompt error: ' + (e && e.message || e), 'error', e); });
  });
  on('btn-export-screens', function() {
    exportPreEdit().catch(function (e) { setScreensStatus('Export error: ' + (e && e.message || e), 'error', e); });
  });
  on('btn-import-pre-edit', function() {
    screensLogger.info('Import Pre-Edit button clicked');
    setScreensStatus('Importing...', 'waiting');
    importPreEdit().catch(function (e) { setScreensStatus('Import error: ' + (e && e.message || e), 'error', e); });
  });
  on('btn-generate-pngs', generateScreenPngs);
  on('btn-build-screens', buildScreenCuesPipeline);

  // DOCTOR buttons (project health — missing media vs timeline usage)
  on('btn-doctor-analyze', function () {
    onDoctorAnalyze().catch(function (e) { setDoctorStatus('Error: ' + e.message, 'error', e); });
  });
  on('btn-doctor-open', function () {
    onDoctorOpenLast().catch(function (e) { setDoctorStatus('Error: ' + (e && e.message || e), 'error', e); });
  });
  on('btn-doctor-debug', function () {
    onDoctorCopyDebug().catch(function (e) { setDoctorStatus('Error: ' + (e && e.message || e), 'error', e); });
  });
  on('btn-doctor-relink', function () {
    onDoctorRelink().catch(function (e) { setDoctorStatus('Relink error: ' + (e && e.message ? e.message : e), 'error', e); });
  });
  on('btn-doctor-forcerefresh', function () {
    onDoctorForceRefresh().catch(function (e) { setDoctorStatus('Force-refresh error: ' + (e && e.message ? e.message : e), 'error', e); });
  });
  on('btn-doctor-restore', function () {
    onDoctorRestoreStructure().catch(function (e) { setDoctorStatus('Restore error: ' + (e && e.message ? e.message : e), 'error', e); });
  });
  on('btn-doctor-selfcontain', function () {
    onDoctorSelfContain().catch(function (e) { setDoctorStatus('Self-contain error: ' + (e && e.message ? e.message : e), 'error', e); });
  });
  on('btn-doctor-hide-source-timelines', function () {
    onHideSourceTimelines(setDoctorStatus).catch(function (e) {
      setDoctorStatus('Hide source timelines: ' + (e && e.message ? e.message : e), 'error', e);
    });
  });

  // FOOTAGE REVIEW
  on('btn-footage-build', function () {
    buildFootage().catch(function (e) { setFootageStatus('Error: ' + (e && e.message ? e.message : e), 'error', e); });
  });
  on('btn-footage-log', function () {
    if (!footageState.lastLogPath) return;
    navigator.clipboard.writeText(footageState.lastLogPath)
      .then(function () { setFootageStatus('Log path copied to clipboard', 'ready'); })
      .catch(function (e) { footageLogger.warn('clipboard copy failed: ' + e.message); });
  });
  // Footage Review launch button — standalone, separate from the pipeline tabs.
  on('footage-launch', function () {
    document.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
    document.querySelectorAll('.tab-content').forEach(function (c) { c.classList.remove('active'); });
    this.classList.add('active');
    var el = document.getElementById('tab-footage');
    if (el) el.classList.add('active');
    // Pre-fill the project name with the open project's folder name (if empty).
    var nameEl = document.getElementById('footage-name');
    if (nameEl && !nameEl.value) {
      footageProjectFolderName().then(function (n) {
        if (n && !nameEl.value) nameEl.value = footageHyphenate(n);
      }).catch(function (e) { footageLogger.debug('footage name prefill: ' + (e && e.message || e)); });
    }
  });

  // LOG: copy path buttons
  // TAB switching
  document.querySelectorAll('.tab-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
      document.querySelectorAll('.tab-content').forEach(function(c) { c.classList.remove('active'); });
      var fl = document.getElementById('footage-launch'); if (fl) fl.classList.remove('active');
      btn.classList.add('active');
      var tabId = 'tab-' + btn.getAttribute('data-tab');
      var tabEl = document.getElementById(tabId);
      if (tabEl) tabEl.classList.add('active');
      // Lazy rescan of scenes/ bundles — so bundles generated after project
      // selection appear without hitting Refresh (footage-launch precedent).
      if (btn.getAttribute('data-tab') === 'assembly' && projectState.folderPath) {
        refreshAssemblyScenes().catch(function (e) { assemblyLogger.debug('Assembly scenes scan: ' + e.message); });
      }
      // Lazy first-load of the shorts brief on tab open (assembly precedent).
      if (btn.getAttribute('data-tab') === 'shorts' && projectState.folderPath && !shortsState.brief) {
        shortsRefresh().catch(function (e) { shortsLogger.debug('Shorts auto-refresh: ' + e.message); });
      }
      // Parts: auto-load the freshest part JSON on tab open — Build is one click away
      // (Roman 2026-08-20: «должно быть всё автоматом»). Manual Load stays as override.
      if (btn.getAttribute('data-tab') === 'review' && projectState.folderPath) {
        refreshPick('review').catch(function (e) { assemblyLogger.debug('Review pick: ' + e.message); });
      }
      if (btn.getAttribute('data-tab') === 'parts' && projectState.folderPath) {
        // список с галочками — всегда свежий; авто-загрузка одного JSON остаётся
        // как быстрый путь «Build в один клик», но выбор теперь виден целиком
        refreshPick('parts').catch(function (e) { assemblyLogger.debug('Parts pick: ' + e.message); });
        if (!partsState.part) {
          loadPart(true).catch(function (e) { assemblyLogger.debug('Parts auto-load: ' + e.message); });
          selRefresh().catch(function (e) { assemblyLogger.debug('Selections auto-refresh: ' + e.message); });
        }
      }
    });
  });

  // Branding: show current date+time
  var now = new Date();
  var pad = function(n) { return n < 10 ? '0' + n : '' + n; };
  var bv = $('branding-ver'); if (bv) bv.textContent = 'v' + PANEL_VERSION;
  $('branding-time').textContent = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate()) + ' ' + pad(now.getHours()) + ':' + pad(now.getMinutes());

  ingestLogger.info('0500_uxp initialized');
  ingestLogger.info('Version ' + PANEL_VERSION);
  assemblyLogger.info('0500_uxp initialized');
  deletedSceneLogger.info('0500_uxp initialized');
  screensLogger.info('0500_uxp initialized');
});
