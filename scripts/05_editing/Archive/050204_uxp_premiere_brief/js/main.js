/* main.js — Orchestrator: UI events + 11-step build pipeline */

// UI elements
var elBtnLoad, elBtnBuild, elProjectName;
var elStats, elStatSegments, elStatBlocks, elStatDuration;
var elProgress, elProgressStep, elProgressPct, elProgressFill;
var elLog;

// Initialize UI references
function initUI() {
  elBtnLoad = document.getElementById('btnLoad');
  elBtnBuild = document.getElementById('btnBuild');
  elProjectName = document.getElementById('projectName');
  elStats = document.getElementById('stats');
  elStatSegments = document.getElementById('statSegments');
  elStatBlocks = document.getElementById('statBlocks');
  elStatDuration = document.getElementById('statDuration');
  elProgress = document.getElementById('progress');
  elProgressStep = document.getElementById('progressStep');
  elProgressPct = document.getElementById('progressPct');
  elProgressFill = document.getElementById('progressFill');
  elLog = document.getElementById('log');

  elBtnLoad.addEventListener('click', handleLoad);
  elBtnBuild.addEventListener('click', handleBuild);
}

// Progress helper
function setProgress(step, total, label) {
  elProgress.classList.remove('hidden');
  elProgressStep.textContent = 'Step ' + step + '/' + total + ': ' + label;
  var pct = Math.round((step / total) * 100);
  elProgressPct.textContent = pct + '%';
  elProgressFill.style.width = pct + '%';
  elProgressFill.className = 'progress-fill';
}

function setProgressDone(success) {
  elProgressFill.style.width = '100%';
  elProgressFill.className = 'progress-fill ' + (success ? 'done' : 'error');
  elProgressPct.textContent = success ? 'Done' : 'Error';
}

// Update stats display
function updateStats() {
  var segs = APP.segments;
  var useSegs = segs.filter(function (s) { return s.use && s.block !== 99; });
  var totalDur = 0;
  var useDur = 0;
  segs.forEach(function (s) { totalDur += s.duration; });
  useSegs.forEach(function (s) { useDur += s.duration; });

  elStatSegments.textContent = useSegs.length + '/' + segs.length + ' segs';
  elStatBlocks.textContent = APP.blocks.filter(function (b) { return b.id !== 99; }).length + ' blocks';
  elStatDuration.textContent = fmtTime(useDur) + ' / ' + fmtTime(totalDur);

  elStats.classList.remove('hidden');
  elProjectName.textContent = APP.projectName;
}

// Load brief file
async function handleLoad() {
  elLog.innerHTML = '';
  LOG_BUFFER.length = 0; // Clear log buffer for new session
  appLog('Selecting brief file...', 'step');

  var file = null;

  // 3-strategy file picker fallback
  try {
    file = await uxpFs.getFileForOpening({ types: ['json'] });
  } catch (e1) {
    try {
      file = await uxpFs.getFileForOpening({ allowedFileTypes: ['json'] });
    } catch (e2) {
      try {
        file = await uxpFs.getFileForOpening();
      } catch (e3) {
        appLog('File picker failed: ' + e3.message, 'error');
        return;
      }
    }
  }

  if (!file) {
    appLog('Cancelled', 'warn');
    return;
  }

  try {
    var text = await file.read({ format: uxpFormats.utf8 });
    APP.briefFileEntry = file;

    // Create persistent token for reload
    try {
      APP.briefFileToken = await uxpFs.createPersistentToken(file);
    } catch (ex) { }

    appLog('Loaded: ' + file.name, 'ok');

    // Parse and normalize
    var result = parseBrief(text);
    appLog('Parsed: ' + result.segments.length + ' segments, ' + result.blocks.length + ' blocks', 'ok');

    updateStats();
    elBtnBuild.disabled = false;

    // Auto-trigger build
    await handleBuild();

  } catch (ex) {
    appLog('Load error: ' + ex.message, 'error');
    if (ex.stack) appLog(ex.stack, 'error');
    await flushLogToFile();
  }
}

// Main build pipeline — 11 steps with backup, verify, logging
async function handleBuild() {
  if (APP.segments.length === 0) {
    appLog('No segments loaded', 'error');
    return;
  }

  if (APP.buildStatus === 'running') {
    appLog('Build already in progress', 'warn');
    return;
  }

  APP.buildStatus = 'running';
  elBtnBuild.disabled = true;
  var STEPS = 11;
  var fullResult = null;
  var editResult = null;

  try {
    // Get active project
    var project = await bppro.Project.getActiveProject();
    if (!project) throw new Error('No active Premiere Pro project');
    var rootItem = await project.getRootItem();

    // Step 1: Save project backup BEFORE making changes
    setProgress(1, STEPS, 'Saving project backup');
    appLog('=== BUILD START: ' + APP.projectName + ' ===', 'step');
    appLog('Timestamp: ' + new Date().toISOString(), 'info');
    appLog('Segments: ' + APP.segments.length + ' (' +
      APP.segments.filter(function (s) { return s.use; }).length + ' USE)', 'info');
    await saveProjectBackup(project, 'pre_build');

    // Step 2: Detect source folder
    setProgress(2, STEPS, 'Detecting source folder');
    await findSourceFolder(APP.briefFileEntry);

    if (!APP.sourceFolderPath) {
      appLog('Source folder not detected — trying manual picker', 'warn');
      try {
        var folder = await uxpFs.getFolder();
        if (folder) {
          APP.sourceFolderEntry = folder;
          APP.sourceFolderPath = folder.nativePath;
          appLog('Manual source folder: ' + folder.nativePath, 'ok');
        }
      } catch (ex) { }
    }

    if (!APP.sourceFolderPath) {
      throw new Error('No source folder — cannot import clips');
    }

    // Step 3: Scan existing clips
    setProgress(3, STEPS, 'Scanning project');
    var existingClips = await scanExistingClips(bppro.FolderItem.cast(rootItem));
    appLog('Existing clips in project: ' + Object.keys(existingClips).length, 'info');

    // Step 4: Create bin structure
    setProgress(4, STEPS, 'Creating bins');
    var bins = await createBinStructure(project, rootItem, APP.blocks);

    // Step 5: Import source files
    setProgress(5, STEPS, 'Importing source files');
    var clipMap = await importSourceFiles(project, APP.segments, existingClips, bins.sources);

    // Step 6: Build FULL sequence
    setProgress(6, STEPS, 'Building FULL sequence');
    fullResult = await buildFullSequence(project, clipMap);

    // Step 7: Build EDIT sequence
    setProgress(7, STEPS, 'Building EDIT sequence');
    editResult = await buildEditSequence(project, clipMap);

    // Step 8: Trim & color clips
    setProgress(8, STEPS, 'Trimming & coloring');
    await trimAllSequences(project, fullResult, editResult);
    await colorAllSequences(project, fullResult, editResult);

    // Step 9: Create markers
    setProgress(9, STEPS, 'Creating markers');
    await createAllMarkers(project, fullResult, editResult);

    // Step 10: Save project + verify sequences
    setProgress(10, STEPS, 'Saving & verifying');
    await saveProjectAfterBuild(project);
    var issues = await verifySequences(project, fullResult, editResult);

    // Step 11: Flush logs to file
    setProgress(11, STEPS, 'Saving logs');
    await flushLogToFile();

    // Done
    setProgressDone(issues.length === 0);
    APP.buildStatus = 'done';
    appLog('=== BUILD COMPLETE ===', 'ok');

    var useCount = APP.segments.filter(function (s) { return s.use && s.block !== 99; }).length;
    var useDur = 0;
    APP.segments.forEach(function (s) { if (s.use && s.block !== 99) useDur += s.duration; });
    appLog('FULL: ' + APP.segments.length + ' segments | EDIT: ' + useCount + ' segments (' + fmtTime(useDur) + ')', 'ok');
    if (issues.length > 0) {
      appLog(issues.length + ' verification issues — check log', 'warn');
    }

  } catch (ex) {
    setProgressDone(false);
    APP.buildStatus = 'error';
    appLog('BUILD ERROR: ' + ex.message, 'error');
    if (ex.stack) appLog(ex.stack, 'error');

    // Always flush logs on error
    await flushLogToFile();
  }

  elBtnBuild.disabled = false;
}

// Init on DOM ready
document.addEventListener('DOMContentLoaded', initUI);
