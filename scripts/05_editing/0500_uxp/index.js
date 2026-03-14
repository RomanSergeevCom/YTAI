/**
 * YTAI Assembly — UXP Plugin for Adobe Premiere Pro
 *
 * Four pipelines in one panel:
 *   INGEST:      loads ingest.json → imports clips, builds Ingest sequence
 *   ASSEMBLY:    loads edit_brief.json → builds Assembly sequence from existing clips
 *   REVIEW:      builds Review sequence from unused segments
 *   SCREEN CUES: creates _4_ScreenCues sequence (V1 Assembly copy + V2 PNG overlays + markers + SRT)
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
const { buildIngestSequence, findProjectItemByName } = require('./src/ingest/timelineBuilder');
const { importTranscripts } = require('./src/ingest/transcriptImporter');
const { copyLutsToCreativeFolder, applyLumetriToClips } = require('./src/ingest/lutManager');

// --- Module imports: ASSEMBLY ---
const { parseBrief } = require('./src/assembly/briefParser');
const { validateIngestState } = require('./src/assembly/projectScanner');
const { buildAssemblySequence } = require('./src/assembly/assemblyBuilder');

// --- Module imports: REVIEW ---
const { buildReviewSequence, getReviewCategory } = require('./src/review/reviewBuilder');

// --- Module imports: SCREENS ---
const { parseScreens } = require('./src/screens/screenParser');
const { buildScreenCues, SCREEN_CUES_BIN_NAME } = require('./src/screens/screenBuilder');

// --- State (separate for INGEST and ASSEMBLY) ---
let ingestState = { data: null, filePath: null, building: false };
let assemblyState = { data: null, segments: [], blocks: [], screens: [], projectName: '', filePath: null, building: false, clipMap: null };

// --- State: PROJECT (folder-level project selection with auto-detection) ---
let projectState = {
  folderPath: null,      // native path to project folder
  projectName: null,     // folder name = project name
  ingestPath: null,      // resolved path to _ingest.json (null if not found)
  briefPath: null,       // resolved path to _edit_brief.json (null if not found)
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

function appendToPanel(panelId, entry, level) {
  const panel = $(panelId);
  if (!panel) return;
  const cls = level === 'ERROR' ? 'log-error'
    : level === 'WARN' ? 'log-warn'
    : level === 'DEBUG' ? 'log-debug'
    : 'log-info';
  panel.innerHTML += '<span class="' + cls + '">' + escapeHtml(entry) + '</span>\n';
  panel.scrollTop = panel.scrollHeight;
}

ingestLogger.onLog = (entry, level) => { appendToPanel('ingest-log-panel', entry, level); };
assemblyLogger.onLog = (entry, level) => { appendToPanel('assembly-log-panel', entry, level); };
reviewLogger.onLog = (entry, level) => { appendToPanel('review-log-panel', entry, level); };
screensLogger.onLog = (entry, level) => { appendToPanel('screens-log-panel', entry, level); };

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
 *   {PROJECT_NAME}/01_Media/Source/Setup/{PROJECT_NAME}_edit_brief.json
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
 * Auto-detect ingest.json and edit_brief.json from the known folder structure.
 * Calls existing loadIngestFromPath() / loadBriefFromPath() on success.
 * Shows fallback load buttons on failure.
 */
async function autoDetectFiles(folderPath, projectName) {
  var checklistHtml = '';
  hideAllFallbackButtons();

  // --- Ingest ---
  var ingestPath = folderPath + '/01_Media/Source/' + projectName + '_ingest.json';
  try {
    await uxpfs.getEntryWithUrl('file://' + ingestPath);
    projectState.ingestPath = ingestPath;
    projectState.ingestDetected = true;
    checklistHtml += checkItem(true, projectName + '_ingest.json');
    ingestLogger.info('Auto-detected ingest: ' + ingestPath);
    await loadIngestFromPath(ingestPath);
  } catch (e) {
    projectState.ingestDetected = false;
    checklistHtml += checkItem(false, projectName + '_ingest.json',
      'Expected: 01_Media/Source/' + projectName + '_ingest.json');
    ingestLogger.warn('Ingest not found at expected path: ' + ingestPath);
    setIngestStatus('Ingest JSON not found. Load manually.', 'waiting');
    showFallback('ingest');
  }

  // --- Brief ---
  var briefPath = folderPath + '/01_Media/Source/Setup/' + projectName + '_edit_brief.json';
  try {
    await uxpfs.getEntryWithUrl('file://' + briefPath);
    projectState.briefPath = briefPath;
    projectState.briefDetected = true;
    checklistHtml += checkItem(true, projectName + '_edit_brief.json');
    assemblyLogger.info('Auto-detected brief: ' + briefPath);
    await loadBriefFromPath(briefPath);
  } catch (e) {
    projectState.briefDetected = false;
    checklistHtml += checkItem(false, projectName + '_edit_brief.json',
      'Expected: 01_Media/Source/Setup/' + projectName + '_edit_brief.json');
    assemblyLogger.warn('Brief not found at expected path: ' + briefPath);
    setAssemblyStatus('Edit brief not found. Load manually.', 'waiting');
    setReviewStatus('Edit brief not found.', 'waiting');
    setScreensStatus('Edit brief not found.', 'waiting');
    showFallback('assembly');
  }

  $('project-checklist').innerHTML = checklistHtml;
  $('project-actions-row').style.display = 'flex';
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

  ingestState.data = ingest;
  ingestState.filePath = filePath;
  ingestLogger.setIngestInfo(filePath, ingest.source_folder || '(not set)');

  $('ingest-summary').textContent = generateSummary(ingest);
  $('ingest-summary').style.display = 'block';
  $('ingest-file-info').textContent = 'File: ' + filePath;
  $('btn-build-ingest').removeAttribute('disabled');

  setIngestStatus('Ingest loaded. Ready to build.', 'ready');
  ingestLogger.info('Ingest loaded: ' + ingest.clips.length + ' clips, project "' + ingest.project_name + '"');
}

async function loadIngest() {
  try {
    ingestLogger.info('Opening file picker for ingest JSON...');
    const file = await uxpfs.getFileForOpening({ types: ['json'], allowMultiple: false });
    if (!file) { ingestLogger.warn('File selection cancelled'); return; }

    const contents = await file.read();
    const ingest = parseIngest(contents);

    ingestState.data = ingest;
    ingestState.filePath = file.nativePath || file.name || 'unknown';
    ingestLogger.setIngestInfo(ingestState.filePath, ingest.source_folder || '(not set)');

    $('ingest-summary').textContent = generateSummary(ingest);
    $('ingest-summary').style.display = 'block';
    $('ingest-file-info').textContent = 'File: ' + ingestState.filePath;
    $('btn-build-ingest').removeAttribute('disabled');

    setIngestStatus('Ingest loaded. Ready to build.', 'ready');
    ingestLogger.info('Ingest loaded: ' + ingest.clips.length + ' clips, project "' + ingest.project_name + '"');
  } catch (err) {
    ingestLogger.error('Failed to load ingest: ' + err.message);
    setIngestStatus('Error: ' + err.message, 'error');
  }
}

async function cleanBeforeBuild(project, ingest) {
  const sequenceName = ingest.project_name + '_1_Ingest';
  ingestLogger.info('=== Clean before build ===');

  const rootItem = await project.getRootItem();
  const allItems = await rootItem.getItems();

  for (const item of allItems) {
    if (item.name === sequenceName && item.type !== 2) {
      try { await project.deleteSequence(item); ingestLogger.info('Deleted old sequence: "' + sequenceName + '"'); }
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
    const result = await buildIngestSequence(project, ingest, bins[BIN_NAMES.SOURCE] || null, null, ingestLogger);
    stepTimings.push('build ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 4: Import transcripts
    step++;
    stepStart = Date.now();
    setIngestProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Importing transcripts...');
    ingestLogger.info('=== Step 4: Importing transcripts ===');
    const trResult = await importTranscripts(project, ingest, bins[BIN_NAMES.TRANSCRIPTS] || null, ingestLogger, result.sequence || null);
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

  const expectedCount = ingest.clips.length;

  // V1 clip count
  try {
    const v1 = await sequence.getVideoTrack(0);
    const items = await v1.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
    if (items.length >= expectedCount) ok('V1: ' + items.length + ' clips');
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
  return loadBriefFromString(contents, filePath);
}

function loadBriefFromString(jsonString, filePath) {
  const result = parseBrief(jsonString);

  assemblyState.data = result;
  assemblyState.segments = result.segments;
  assemblyState.blocks = result.blocks;
  assemblyState.projectName = result.projectName;
  assemblyState.filePath = filePath;

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
  } else {
    setScreensStatus('No screens in brief', 'waiting');
    $('btn-generate-pngs').setAttribute('disabled', 'true');
    $('btn-build-screens').setAttribute('disabled', 'true');
  }

  setAssemblyStatus('Brief loaded. Ready to build.', 'ready');
  assemblyLogger.info('Brief loaded: ' + result.segments.length + ' segments, ' + result.blocks.length + ' blocks' +
    (screenCount > 0 ? ', ' + screenCount + ' screens' : ''));

  return result;
}

async function loadBrief() {
  try {
    assemblyLogger.info('Opening file picker for edit brief...');
    const file = await uxpfs.getFileForOpening({ types: ['json'], allowMultiple: false });
    if (!file) { assemblyLogger.warn('File selection cancelled'); return; }

    const contents = await file.read();
    loadBriefFromString(contents, file.nativePath || file.name || 'unknown');
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
    result = await buildAssemblySequence(project, clipMap, assemblyState.segments, assemblyState.projectName, assemblyLogger);
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

    // Step 6: Import Assembly captions SRT (if exists alongside brief)
    step++;
    stepStart = Date.now();
    setAssemblyProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Captions...');
    await importCaptionsSrt(project, assemblyState.filePath, assemblyState.projectName, '2_Assembly', 'Assembly', assemblyLogger);
    stepTimings.push('captions ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    setAssemblyProgress(100, 'Complete!');
    assemblyLogger.info('=== ASSEMBLY BUILD COMPLETE (' + elapsed + 's) ===');
    assemblyLogger.info('Timing: ' + stepTimings.join(' | '));
    assemblyLogger.info('Assembly: ' + result.clipCount + ' clips on V1, total=' + (result.totalDuration || 0).toFixed(1) + 's');

    // ScreenCues reminder — how many screens are ready in the brief
    if (assemblyState.screens && assemblyState.screens.length > 0) {
      assemblyLogger.info('→ ' + assemblyState.screens.length + ' screens ready in brief. Click "Build Screen Cues" to generate _4_ScreenCues');
    }

    setAssemblyStatus('Assembly built (' + result.clipCount + ' clips)', 'ready');

    await saveAssemblyLogs(project, clipMap, result);

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
 * Import captions SRT into the project (02_Transcripts bin).
 *
 * Looks for {project}_{suffix}_captions.srt next to the brief file.
 * Generated by generate_assembly_captions.py — word-level captions with
 * timecodes remapped to the timeline.
 *
 * Non-fatal: if SRT not found or import fails, logs a message and continues.
 *
 * @param {Object} project - Active Premiere Pro project
 * @param {string} briefPath - Path to the loaded edit_brief.json
 * @param {string} projectName - Project name (e.g. "YTAI_Edit")
 * @param {string} suffix - SRT file suffix: "2_Assembly" or "3_Review"
 * @param {string} label - Human label for logs: "Assembly" or "Review"
 * @param {Object} logger - Logger instance
 */
async function importCaptionsSrt(project, briefPath, projectName, suffix, label, logger) {
  if (!briefPath || !projectName) {
    logger.debug('Captions import skipped: no brief path or project name');
    return;
  }

  const briefDir = briefPath.replace(/[/\\][^/\\]+$/, '');
  const srtFileName = projectName + '_' + suffix + '_captions.srt';
  const srtPath = briefDir + '/' + srtFileName;

  logger.info('=== Import ' + label + ' Captions ===');

  // Check if file exists
  try {
    const entry = await uxpfs.getEntryWithUrl('file://' + srtPath);
    if (!entry) {
      logger.info('No ' + label + ' captions SRT found (generate with generate_assembly_captions.py' + (suffix === '3_Review' ? ' --review' : '') + ')');
      return;
    }
    const content = await entry.read();
    const blockCount = (content.match(/^\d+$/gm) || []).length;
    logger.debug(label + ' captions: ' + content.length + ' chars, ' + blockCount + ' SRT blocks');
  } catch (e) {
    logger.info('No ' + label + ' captions SRT found at: ' + srtFileName);
    return;
  }

  // Find 02_Transcripts bin
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
    logger.debug('Cannot find 02_Transcripts bin: ' + e.message);
  }

  // Import SRT
  try {
    await project.importFiles([srtPath], true, transcriptsBin || null, false);
    logger.info(label + ' captions imported: ' + srtFileName + ' → 02_Transcripts');
    logger.info('To add captions: drag "' + srtFileName + '" from 02_Transcripts to timeline caption track');
  } catch (err) {
    logger.warn(label + ' captions import failed (non-fatal): ' + err.message);
  }
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

    let clipDurations = await getClipDurationsFromIngest(project, assemblyState.projectName, reviewLogger);
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
    result = await buildReviewSequence(project, clipMap, assemblyState.segments, assemblyState.projectName, reviewLogger, clipDurations);

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

    // Step 6: Import Review captions SRT (if exists alongside brief)
    step++;
    stepStart = Date.now();
    setReviewProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Captions...');
    await importCaptionsSrt(project, assemblyState.filePath, assemblyState.projectName, '3_Review', 'Review', reviewLogger);
    stepTimings.push('captions ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    setReviewProgress(100, 'Complete!');
    reviewLogger.info('=== REVIEW BUILD COMPLETE (' + elapsed + 's) ===');
    reviewLogger.info('Timing: ' + stepTimings.join(' | '));
    reviewLogger.info('Review: ' + result.clipCount + ' clips on V1, total=' + (result.totalDuration || 0).toFixed(1) + 's');

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
}

/**
 * Standalone Screen Cues pipeline — creates _4_ScreenCues sequence (v1.9.3).
 *
 * V1 = exact copy of Assembly (same segments, order, trims, colors)
 * V2 = PNG overlays at screen cue positions (if PNGs available)
 * Markers = Orange Comment markers at screen cue positions
 * SRT = generated in-memory, written to disk, imported to 02_Transcripts
 *
 * Does NOT depend on Assembly sequence — only needs brief + imported clips.
 *
 * Prerequisites:
 *   - Brief loaded with screens[] (via Load Edit Brief)
 *   - Clips imported (via INGEST — 00_Source bin exists)
 *   - (Optional) PNGs generated via generate_screen_cues_png.py
 *
 * 4 steps:
 *   1. Scan clips from 00_Source
 *   2. Build ScreenCues sequence (V1 Assembly copy + V2 PNGs + markers + SRT)
 *   3. Write SRT file to brief directory
 *   4. Import Screen Cues SRT to 02_Transcripts bin
 */
async function buildScreenCuesPipeline() {
  if (!assemblyState.screens || assemblyState.screens.length === 0) {
    screensLogger.error('No screens in loaded brief');
    return;
  }

  setScreensStatus('Building screen cues...', 'waiting');
  $('screens-validation').style.display = 'none';

  var totalSteps = 4;
  var step = 0;
  var startTime = Date.now();

  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');
    screensLogger.setProjectInfo(project.name, project.path);
    screensLogger.setBriefInfo(assemblyState.filePath, assemblyState.projectName);

    screensLogger.info('=== SCREEN CUES BUILD START ===');
    screensLogger.info('Screens: ' + assemblyState.screens.length + ', Project: ' + assemblyState.projectName);

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
      assemblyState.projectName, screensLogger, assemblyState.filePath, pngFiles, screenCuesBin
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

    // Step 3: Write SRT file to brief directory
    step++;
    stepStart = Date.now();
    setScreensProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Writing SRT...');
    screensLogger.info('=== Step 3: Write Screen Cues SRT ===');
    if (screenResult.srtContent && assemblyState.filePath) {
      try {
        var briefDir = assemblyState.filePath.replace(/[/\\][^/\\]+$/, '');
        var srtFileName = assemblyState.projectName + '_4_ScreenCues_captions.srt';
        var folder = await uxpfs.getEntryWithUrl('file://' + briefDir);
        var srtFile = await folder.createFile(srtFileName, { overwrite: true });
        await srtFile.write(screenResult.srtContent);
        screensLogger.info('SRT written: ' + srtFileName + ' (' + screenResult.srtContent.length + ' chars)');
      } catch (srtErr) {
        screensLogger.warn('SRT write failed (non-fatal): ' + srtErr.message);
      }
    } else {
      screensLogger.info('No SRT content to write');
    }

    stepTimings.push('srt-write ' + ((Date.now() - stepStart) / 1000).toFixed(1) + 's');

    // Step 4: Import SRT to 02_Transcripts bin
    step++;
    stepStart = Date.now();
    setScreensProgress((step / totalSteps) * 100, 'Step ' + step + '/' + totalSteps + ': Importing SRT...');
    screensLogger.info('=== Step 4: Import Screen Cues SRT ===');
    await importCaptionsSrt(project, assemblyState.filePath, assemblyState.projectName,
      '4_ScreenCues', 'ScreenCues', screensLogger);

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
      await validateScreensBuild(screenResult.sequence, screenResult);
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
 * Post-build validation for Screen Cues — V1 clips, V2 overlays, markers, SRT.
 */
async function validateScreensBuild(sequence, screenResult) {
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

  // Markers
  if (screenResult.markers > 0) ok('Markers: ' + screenResult.markers + ' Comment markers');
  else warn('Markers: none created');

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
  $('btn-refresh-project').addEventListener('click', refreshProject);

  // INGEST buttons (btn-load-ingest is fallback — hidden by default)
  $('btn-load-ingest').addEventListener('click', loadIngest);
  $('btn-build-ingest').addEventListener('click', buildIngest);

  // ASSEMBLY buttons (btn-load-brief is fallback — hidden by default)
  $('btn-load-brief').addEventListener('click', loadBrief);
  $('btn-build-assembly').addEventListener('click', buildAssembly);

  // REVIEW buttons
  $('btn-build-review').addEventListener('click', buildReview);

  // SCREEN CUES buttons
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
