/* file-logger.js — Persistent file logging + project backup */

// Log buffer — accumulates all messages for file write
var LOG_BUFFER = [];

// Generate timestamp: YYYYMMDD_HHMMSS
function makeTimestamp() {
  var d = new Date();
  var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
  return d.getFullYear() +
    pad(d.getMonth() + 1) +
    pad(d.getDate()) + '_' +
    pad(d.getHours()) +
    pad(d.getMinutes()) +
    pad(d.getSeconds());
}

// ISO timestamp for log lines
function isoNow() {
  return new Date().toISOString();
}

// Add message to buffer (called from appLog)
function bufferLog(msg, level) {
  LOG_BUFFER.push('[' + isoNow() + '][' + (level || 'info').toUpperCase() + '] ' + msg);
}

// Get or create a subfolder inside plugin data folder
async function getOrCreateSubfolder(parentFolder, name) {
  try {
    var entries = await parentFolder.getEntries();
    for (var i = 0; i < entries.length; i++) {
      if (entries[i].name === name && entries[i].isFolder) {
        return entries[i];
      }
    }
  } catch (ex) { /* folder may not exist yet */ }

  try {
    return await parentFolder.createFolder(name);
  } catch (ex) {
    console.error('[YTAI] Cannot create folder ' + name + ': ' + ex.message);
    return parentFolder;
  }
}

// Flush log buffer to file: logs/build_YYYYMMDD_HHMMSS.log
async function flushLogToFile() {
  if (LOG_BUFFER.length === 0) return;

  try {
    var dataFolder = await uxpFs.getDataFolder();
    var logsFolder = await getOrCreateSubfolder(dataFolder, 'logs');
    var filename = 'build_' + makeTimestamp() + '.log';

    var logContent = LOG_BUFFER.join('\n') + '\n';
    var logFile = await logsFolder.createFile(filename, { overwrite: true });
    await logFile.write(logContent, { format: uxpFormats.utf8 });

    console.log('[YTAI] Log saved: ' + logsFolder.nativePath + '/' + filename);
    appLog('Log saved: ' + filename, 'ok');

    return logsFolder.nativePath + '/' + filename;
  } catch (ex) {
    console.error('[YTAI] Log flush failed: ' + ex.message);
    appLog('Log save failed: ' + ex.message, 'warn');

    // Fallback: try saving next to brief file
    try {
      if (APP.sourceFolderPath) {
        var fallbackFolder = await uxpFs.getEntryWithUrl('file:' + APP.sourceFolderPath);
        if (fallbackFolder) {
          var logsDir = await getOrCreateSubfolder(fallbackFolder, 'ytai_logs');
          var fname = 'build_' + makeTimestamp() + '.log';
          var f = await logsDir.createFile(fname, { overwrite: true });
          await f.write(LOG_BUFFER.join('\n') + '\n', { format: uxpFormats.utf8 });
          appLog('Log saved (fallback): ' + fname, 'ok');
        }
      }
    } catch (ex2) {
      console.error('[YTAI] Fallback log save failed: ' + ex2.message);
    }
  }
  return null;
}

// Save Premiere project backup to plugin data folder
async function saveProjectBackup(project, label) {
  var ts = makeTimestamp();
  label = label || 'backup';

  try {
    // Strategy 1: project.saveAs() to data folder
    var dataFolder = await uxpFs.getDataFolder();
    var backupsFolder = await getOrCreateSubfolder(dataFolder, 'backups');
    var backupName = APP.projectName + '_' + label + '_' + ts + '.prproj';
    var backupPath = backupsFolder.nativePath + '/' + backupName;

    // First save the current state
    await project.save();
    appLog('Project saved', 'ok');

    // Then save a copy as backup
    try {
      await project.saveAs(backupPath);
      appLog('Backup saved: ' + backupName, 'ok');
      return backupPath;
    } catch (saveAsErr) {
      // saveAs may change active project — save original again
      appLog('saveAs not available or failed: ' + saveAsErr.message, 'warn');

      // Strategy 2: just save the project in place
      await project.save();
      appLog('Project saved (in-place, no copy)', 'ok');
      return null;
    }
  } catch (ex) {
    appLog('Project backup failed: ' + ex.message, 'warn');

    // Strategy 3: at minimum save the project
    try {
      await project.save();
      appLog('Project saved (fallback)', 'ok');
    } catch (saveErr) {
      appLog('Even project.save() failed: ' + saveErr.message, 'error');
    }
    return null;
  }
}

// Save project after build (final state)
async function saveProjectAfterBuild(project) {
  try {
    await project.save();
    appLog('Project saved (post-build)', 'ok');
    return true;
  } catch (ex) {
    appLog('Post-build save failed: ' + ex.message, 'error');
    return false;
  }
}

// Verify sequences were created correctly
async function verifySequences(project, fullResult, editResult) {
  var issues = [];

  // Verify FULL sequence
  if (fullResult && fullResult.sequence) {
    try {
      var fullTrack = await fullResult.sequence.getVideoTrack(0);
      var fullItems = await getCleanTrackItems(fullTrack);
      var expectedFull = fullResult.segments.length;
      appLog('FULL verify: ' + fullItems.length + '/' + expectedFull + ' clips on V1', 'info');
      if (fullItems.length < expectedFull) {
        issues.push('FULL: expected ' + expectedFull + ' clips, found ' + fullItems.length);
      }

      // Check timeline duration
      var fullEnd = await fullResult.sequence.getEndTime();
      var fullDurSec = tickSec(fullEnd);
      var expectedDur = 0;
      fullResult.segments.forEach(function (s) { expectedDur += s.duration; });
      appLog('FULL duration: ' + fmtTime(fullDurSec) + ' (expected ~' + fmtTime(expectedDur) + ')', 'info');
    } catch (ex) {
      issues.push('FULL verify error: ' + ex.message);
    }
  }

  // Verify EDIT sequence
  if (editResult && editResult.sequence) {
    try {
      var editTrack = await editResult.sequence.getVideoTrack(0);
      var editItems = await getCleanTrackItems(editTrack);
      var expectedEdit = editResult.segments.length;
      appLog('EDIT verify: ' + editItems.length + '/' + expectedEdit + ' clips on V1', 'info');
      if (editItems.length < expectedEdit) {
        issues.push('EDIT: expected ' + expectedEdit + ' clips, found ' + editItems.length);
      }

      var editEnd = await editResult.sequence.getEndTime();
      var editDurSec = tickSec(editEnd);
      var expectedEditDur = 0;
      editResult.segments.forEach(function (s) { expectedEditDur += s.duration; });
      appLog('EDIT duration: ' + fmtTime(editDurSec) + ' (expected ~' + fmtTime(expectedEditDur) + ')', 'info');
    } catch (ex) {
      issues.push('EDIT verify error: ' + ex.message);
    }
  }

  if (issues.length > 0) {
    appLog('=== VERIFICATION ISSUES ===', 'warn');
    issues.forEach(function (issue) { appLog('  ⚠ ' + issue, 'warn'); });
  } else {
    appLog('Verification passed', 'ok');
  }

  return issues;
}
