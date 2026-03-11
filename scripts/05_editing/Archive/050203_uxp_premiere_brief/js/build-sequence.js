/* build-sequence.js — Two-Sequence Build Pipeline + Transcripts + API Test
   UXP: uses globals APP, BUS, appLog, COLOR_MAP, IO from earlier scripts

   PREMIERE PRO 25.x UXP API (from official types.d.ts):
   ──────────────────────────────────────────────────────
   Bin:        FolderItem.cast(rootItem).createBinAction(name, makeUnique) → Action
   Sequence:   project.createSequence(name) → Promise<Sequence>
               project.createSequenceFromMedia(name, clipItems[], targetBin?) → Promise<Sequence>
   Import:     project.importFiles(paths, suppressUI, targetBin, asStills) → Promise<boolean>
   Insert:     editor.createInsertProjectItemAction(item, time, vTrackIdx, aTrackIdx, limitShift)
   Tracks:     await seq.getVideoTrack(index) → Promise<VideoTrack>  ← ASYNC!
               seq.getVideoTrackCount() → number
   TrackItems: track.getTrackItems(Constants.TrackItemType.CLIP, false) → VideoClipTrackItem[]
               Constants.TrackItemType: EMPTY=0, CLIP=1, TRANSITION=2
   Markers:    ppro.Markers.getMarkers(seq) → static
   Transcript: ppro.Transcript.importFromJSON(jsonString) → TextSegments
               ppro.Transcript.createImportTextSegmentsAction(textSegments, clipItem) → Action
   lockedAccess / executeTransaction: SYNCHRONOUS callbacks

   BUILD PIPELINE (v1.0.7):
   ────────────────────────
   1. Collect source files
   2. Scan project
   3. Create bins
   4. Import sources (auto-detect folder from brief path)
   5. Create FULL sequence from media (4K, proper fps)
   6. Create ROUGH CUT sequence from media
   7. Trim clips via TrackItem API
   8. Apply label colors + mute CUT clips
   9. Create chapter markers
*/

console.log('[YTAI] build-sequence.js loading...');

var buxpStorage, buxpFs, buxpFormats;
try {
  buxpStorage = require('uxp').storage;
  buxpFs      = buxpStorage.localFileSystem;
  buxpFormats = buxpStorage.formats;
  console.log('[YTAI] build-sequence.js: UXP storage OK');
} catch (ex) {
  console.log('[YTAI] build-sequence.js: UXP storage not available:', ex.message);
}

var bppro = null;
try {
  bppro = require('premierepro');
  console.log('[YTAI] build-sequence.js: premierepro loaded OK');
} catch (ex) {
  console.log('[YTAI] build-sequence.js: premierepro not available:', ex.message);
}

/* Premiere Pro 25.x label color indices (0-based)
   0=Violet, 1=Iris, 2=Caribbean, 3=Lavender, 4=Cerulean,
   5=Forest, 6=Rose, 7=Mango, 8=Purple, 9=Blue, 10=Teal,
   11=Magenta, 12=Tan, 13=Green, 14=Brown, 15=Yellow, 16=Red */
var LABEL_COLOR_INDEX = {
  Green: 13, Blue: 9, Cyan: 2, Yellow: 15,
  Red: 16, Magenta: 11, Orange: 7, Purple: 8,
  Teal: 10, Forest: 5, Rose: 6, Violet: 0,
  Iris: 1, Lavender: 3, Cerulean: 4, Mango: 7,
  Caribbean: 2, Tan: 12, Brown: 14
};

/* ══════════════════════════════
   MAIN BUILD PIPELINE
   ══════════════════════════════ */

async function runBuild() {
  if (!bppro) { appLog('Premiere API not available', 'error'); return; }
  if (APP.segments.length === 0) { appLog('No segments loaded', 'error'); return; }

  APP.buildStatus = 'running';
  var totalSteps = 9;
  var step = 0;

  function progress(label) {
    step++;
    BUS.emit('build-progress', { step: step, total: totalSteps, label: label });
    appLog('Build [' + step + '/' + totalSteps + ']: ' + label);
  }

  try {
    var project = await bppro.Project.getActiveProject();
    if (!project) throw new Error('No active project');
    var rootItem = await project.getRootItem();

    /* ── Step 1: Collect source files ── */
    progress('Collecting source files');
    var sourceFileSet = {};
    APP.segments.forEach(function (s) { if (s.sourceFile) sourceFileSet[s.sourceFile] = true; });
    var sourceFiles = Object.keys(sourceFileSet);
    appLog('Source files: ' + sourceFiles.join(', '));

    /* ── Step 2: Scan project for existing items ── */
    progress('Scanning project');
    var existingItems = {};
    await _scanBin(rootItem, existingItems);
    appLog('Found ' + Object.keys(existingItems).length + ' items in project');

    /* Debug: Probe project + ClipProjectItem API for SubClip creation */
    try {
      var projMethods = [];
      var projProto = Object.getPrototypeOf(project);
      if (projProto) {
        var pNames = Object.getOwnPropertyNames(projProto);
        for (var pm = 0; pm < pNames.length; pm++) {
          projMethods.push(pNames[pm] + ':' + typeof project[pNames[pm]]);
        }
      }
      appLog('Project proto: ' + projMethods.join(', '));
    } catch (ex) { /* ok */ }

    /* Check if ClipProjectItem has subclip methods */
    try {
      var firstKey = Object.keys(existingItems)[0];
      if (firstKey) {
        var firstItem = existingItems[firstKey];
        var castClip = bppro.ClipProjectItem.cast(firstItem);
        if (castClip) {
          var clipMethods = [];
          var clipProto = Object.getPrototypeOf(castClip);
          if (clipProto) {
            var cNames = Object.getOwnPropertyNames(clipProto);
            for (var cm = 0; cm < cNames.length; cm++) {
              clipMethods.push(cNames[cm] + ':' + typeof castClip[cNames[cm]]);
            }
          }
          appLog('ClipProjectItem proto: ' + clipMethods.join(', '));
        }
      }
    } catch (ex) { appLog('ClipProjectItem probe: ' + ex.message); }

    /* ── Step 3: Create bins ── */
    progress('Creating bins');
    var bins = await _createBins(project, rootItem);

    /* ── Step 4: Import source files ── */
    progress('Importing source files');
    var clipItems = await _importSources(project, sourceFiles, existingItems, bins.sources);

    /* ── Step 5: Create FULL sequence ── */
    progress('Creating FULL sequence');
    var fullSeqName = (APP.projectName || 'YTAI') + '_FULL';
    await _createFullSequence(project, fullSeqName, clipItems, sourceFiles);

    /* ── Step 6: Create ROUGH CUT sequence ── */
    progress('Creating ROUGH CUT sequence');
    var roughSeqName = (APP.projectName || 'YTAI') + '_ROUGH';
    var roughResult = await _createRoughSequence(project, roughSeqName, clipItems);

    /* ── Step 7: Trim clips on ROUGH sequence ── */
    progress('Trimming clips on timeline');
    await _trimClipsOnSequence(project, roughResult.seq, roughResult.useSegs, roughResult.cutSegs);

    /* ── Step 8: Apply label colors ── */
    progress('Applying label colors');
    await _applyColors(project, roughResult.seq, roughResult.useSegs, roughResult.cutSegs);

    /* ── Step 9: Create chapter markers ── */
    progress('Creating chapter markers');
    await _createMarkers(project, roughResult.seq, roughResult.useSegs);

    APP.buildStatus = 'done';
    appLog('Build complete! FULL + ROUGH sequences ready.');
    BUS.emit('build-done');

  } catch (e) {
    APP.buildStatus = 'error';
    appLog('Build failed: ' + e.message, 'error');
    console.error('[YTAI] Build error:', e);
    BUS.emit('build-error', { error: e.message });
  }
}

/* ══════════════════════════════
   HELPERS
   ══════════════════════════════ */

async function _scanBin(bin, result) {
  try {
    var children = await bin.getItems();
    if (!children) return;
    for (var i = 0; i < children.length; i++) {
      var item = children[i];
      try {
        var name = item.name || '';
        if (name) {
          /* Store under both full name AND without extension */
          result[name] = item;
          var noExt = name.replace(/\.[^.]+$/, '');
          if (noExt && noExt !== name) result[noExt] = item;
        }
        if (typeof item.getItems === 'function') {
          await _scanBin(item, result);
        }
      } catch (ex) { /* skip */ }
    }
  } catch (ex) {
    console.log('[YTAI] _scanBin:', ex.message);
  }
}

/* Get track items with correct API parameters.
   IMPORTANT: filters out filler/gap items — only returns real clips. */
async function _getTrackItems(track) {
  if (!track) return null;

  /* Constants.TrackItemType.CLIP = 1 */
  var CLIP_TYPE = 1;
  try {
    if (bppro.Constants && bppro.Constants.TrackItemType) {
      CLIP_TYPE = bppro.Constants.TrackItemType.CLIP;
    }
  } catch (ex) { /* use default 1 */ }

  var rawItems = null;

  /* Try with correct params first */
  try {
    rawItems = track.getTrackItems(CLIP_TYPE, false);
  } catch (ex) {
    appLog('getTrackItems(CLIP,false): ' + ex.message);
  }

  /* Try other param combos if first failed */
  if (!rawItems || rawItems.length === 0) {
    var combos = [[1, true], [1, false], [0, false], [0, true]];
    for (var c = 0; c < combos.length; c++) {
      try {
        rawItems = track.getTrackItems(combos[c][0], combos[c][1]);
        if (rawItems && rawItems.length > 0) break;
      } catch (ex) { /* next */ }
    }
  }

  /* Try no params */
  if (!rawItems || rawItems.length === 0) {
    try {
      rawItems = track.getTrackItems();
    } catch (ex) { /* skip */ }
  }

  if (!rawItems || rawItems.length === 0) return null;

  /* Filter out filler/gap items and disabled (auto-inserted) clips.
     CRITICAL: All TrackItem getters return PROMISES in Premiere UXP 25.3!
     Must AWAIT every call: isDisabled(), getName(), getType(), getProjectItem() */
  var filtered = [];
  var filterLog = [];
  for (var fi = 0; fi < rawItems.length; fi++) {
    var fItem = rawItems[fi];
    if (!fItem) continue;

    /* Strategy 0: Skip disabled items (auto-inserted clips that couldn't be removed) */
    try {
      if (typeof fItem.isDisabled === 'function') {
        var isDisabledResult = await fItem.isDisabled();
        if (isDisabledResult) {
          filterLog.push('[' + fi + '] disabled');
          continue;
        }
      }
    } catch (ex) { /* can't check, include */ }

    /* Strategy 0b: Skip items named [AUTO-SKIP] or [GHOST] */
    try {
      if (typeof fItem.getName === 'function') {
        var fName = await fItem.getName();
        if (fName && (fName.indexOf('[AUTO-SKIP]') === 0 || fName.indexOf('[GHOST]') === 0)) {
          filterLog.push('[' + fi + '] name=' + fName);
          continue;
        }
      }
    } catch (ex) { /* can't check, include */ }

    /* Strategy 1: Check getType() — real clips return type 1 (CLIP) */
    try {
      if (typeof fItem.getType === 'function') {
        var itemType = await fItem.getType();
        if (itemType !== CLIP_TYPE && itemType !== 1) {
          filterLog.push('[' + fi + '] type=' + itemType);
          continue; /* skip non-clip */
        }
      }
    } catch (ex) { /* can't check type, include it */ }

    /* Strategy 2: Real clips have getProjectItem that returns non-null */
    try {
      if (typeof fItem.getProjectItem === 'function') {
        var pi = await fItem.getProjectItem();
        if (!pi) {
          filterLog.push('[' + fi + '] projItem=null');
          continue; /* filler — getProjectItem returns null */
        }
      } else {
        filterLog.push('[' + fi + '] no getProjectItem');
        continue;
      }
    } catch (ex) { /* include if check fails */ }

    /* Strategy 3: Skipped — getDuration returns Promise<TickTime>,
       TickTime structure unknown until probe confirms actual properties */

    filtered.push(fItem);
  }

  if (filterLog.length > 0) {
    appLog('Track items: ' + rawItems.length + ' raw → ' + filtered.length + ' clips (filtered: ' + filterLog.join(', ') + ')');
  }

  return filtered.length > 0 ? filtered : rawItems;
}

/* ══════════════════════════════
   CREATE BINS
   ══════════════════════════════ */

async function _createBins(project, rootItem) {
  var bins = {};
  var rootFolder = bppro.FolderItem.cast(rootItem);

  bins.sources = await _findOrCreateBin(project, rootFolder, '01_Sources');
  var blocksRoot = await _findOrCreateBin(project, rootFolder, '02_Blocks');

  bins.blocks = {};
  for (var i = 0; i < APP.blocks.length; i++) {
    var block = APP.blocks[i];
    var padded = String(block.id).padStart(2, '0');
    var binName = 'Block_' + padded + '_' + block.name.replace(/[^a-zA-Z0-9_ -]/g, '');
    bins.blocks[block.id] = await _findOrCreateBin(project, blocksRoot, binName);
  }

  bins.alternatives = await _findOrCreateBin(project, rootFolder, '03_Alternatives');
  bins.unused = await _findOrCreateBin(project, rootFolder, '04_Unused');
  appLog('Bins ready');
  return bins;
}

async function _findOrCreateBin(project, parentFolder, name) {
  try {
    var children = await parentFolder.getItems();
    if (children) {
      for (var i = 0; i < children.length; i++) {
        var n = children[i].name || '';
        if (n === name && typeof children[i].getItems === 'function') {
          return bppro.FolderItem.cast(children[i]);
        }
      }
    }
  } catch (ex) { /* ok */ }

  try {
    var createAct = parentFolder.createBinAction(name, true);
    project.lockedAccess(function () {
      project.executeTransaction(function (ca) {
        ca.addAction(createAct);
      }, 'Create bin: ' + name);
    });
    appLog('Bin created: ' + name);
  } catch (e) {
    appLog('createBinAction error: ' + name + ' — ' + e.message, 'error');
    throw e;
  }

  try {
    var items = await parentFolder.getItems();
    if (items) {
      for (var j = items.length - 1; j >= 0; j--) {
        var nm = items[j].name || '';
        if (nm === name || nm.indexOf(name) === 0) {
          return bppro.FolderItem.cast(items[j]);
        }
      }
    }
  } catch (ex) { /* fallback */ }

  return parentFolder;
}

/* ══════════════════════════════
   IMPORT SOURCE FILES
   Auto-detects source folder from brief path
   ══════════════════════════════ */

async function _importSources(project, sourceFiles, existingItems, sourcesBin) {
  var clipItems = {};

  /* Auto-detect source folder from brief file if not set */
  var folderEntry = APP.sourceFolderEntry;
  if (!folderEntry && APP.briefFileEntry) {
    try {
      var briefPath = APP.briefFileEntry.nativePath;
      var lastSlash = Math.max(briefPath.lastIndexOf('/'), briefPath.lastIndexOf('\\'));
      if (lastSlash > 0) {
        var parentDir = briefPath.substring(0, lastSlash);
        folderEntry = await buxpFs.getEntryWithUrl('file:' + parentDir);
        if (folderEntry) {
          APP.sourceFolderEntry = folderEntry;
          appLog('Auto-detected source folder: ' + parentDir);
        }
      }
    } catch (ex) {
      appLog('Auto-detect folder: ' + ex.message);
    }
  }

  for (var i = 0; i < sourceFiles.length; i++) {
    var filename = sourceFiles[i];
    var baseName = filename.replace(/\.[^.]+$/, '');

    /* Check existing */
    if (existingItems[filename] || existingItems[baseName]) {
      clipItems[filename] = existingItems[filename] || existingItems[baseName];
      appLog('Reusing: ' + filename);
      continue;
    }

    /* Import from folder entry */
    if (folderEntry) {
      try {
        var entries = await folderEntry.getEntries();
        var fileEntry = null;
        for (var j = 0; j < entries.length; j++) {
          if (entries[j].name === filename) { fileEntry = entries[j]; break; }
        }

        if (fileEntry) {
          var filePath = fileEntry.nativePath || fileEntry.url;
          appLog('Importing: ' + filePath);
          await project.importFiles([filePath], true, sourcesBin, false);

          /* Re-scan to find the imported item */
          var newItems = {};
          await _scanBin(sourcesBin, newItems);
          if (newItems[baseName] || newItems[filename]) {
            clipItems[filename] = newItems[baseName] || newItems[filename];
            appLog('Imported: ' + filename);
          } else {
            /* Scan root too */
            var rootItem = await project.getRootItem();
            var allItems = {};
            await _scanBin(rootItem, allItems);
            if (allItems[baseName] || allItems[filename]) {
              clipItems[filename] = allItems[baseName] || allItems[filename];
              appLog('Imported (root): ' + filename);
            }
          }
          continue;
        }
      } catch (e) {
        appLog('Import error ' + filename + ': ' + e.message, 'error');
      }
    }

    /* Direct path fallback */
    if (!clipItems[filename] && APP.briefFileEntry) {
      try {
        var bPath = APP.briefFileEntry.nativePath;
        var bSlash = Math.max(bPath.lastIndexOf('/'), bPath.lastIndexOf('\\'));
        var bDir = bSlash > 0 ? bPath.substring(0, bSlash) : bPath;
        var directPath = bDir + '/' + filename;
        appLog('Trying direct path: ' + directPath);
        await project.importFiles([directPath], true, sourcesBin, false);

        var rt = await project.getRootItem();
        var rtItems = {};
        await _scanBin(rt, rtItems);
        if (rtItems[baseName] || rtItems[filename]) {
          clipItems[filename] = rtItems[baseName] || rtItems[filename];
          appLog('Imported (direct): ' + filename);
          continue;
        }
      } catch (ex) {
        appLog('Direct import ' + filename + ': ' + ex.message, 'error');
      }
    }

    if (!clipItems[filename]) {
      appLog('Not found: ' + filename, 'error');
    }
  }

  appLog('Clips resolved: ' + Object.keys(clipItems).length + '/' + sourceFiles.length);
  return clipItems;
}

/* ══════════════════════════════
   CREATE FULL SEQUENCE
   Chronological: ALL segments from all clips in source order.
   USE segments → color-labeled on V1 (enabled)
   CUT segments → V1 (disabled), so editor sees what was cut
   Markers on each USE segment for navigation
   ══════════════════════════════ */

async function _createFullSequence(project, seqName, clipItems, sourceFiles) {
  /* Find first available clip for createSequenceFromMedia */
  var firstClipItem = null;
  for (var fc = 0; fc < sourceFiles.length; fc++) {
    if (clipItems[sourceFiles[fc]]) { firstClipItem = clipItems[sourceFiles[fc]]; break; }
  }

  if (!firstClipItem) {
    appLog('FULL: no clips to create sequence from', 'error');
    return null;
  }

  /* Create sequence FROM MEDIA → inherits 4K, fps, etc. */
  var seq = null;
  try {
    var castClip = bppro.ClipProjectItem.cast(firstClipItem);
    seq = await project.createSequenceFromMedia(seqName, [castClip || firstClipItem]);
    appLog('FULL sequence created from media: ' + seqName);

    /* Remove auto-inserted clip */
    try {
      var v0 = await seq.getVideoTrack(0);
      if (v0) {
        var autoRawFull = null;
        try { autoRawFull = v0.getTrackItems(1, false); } catch (ex) { /* skip */ }
        if (!autoRawFull) try { autoRawFull = v0.getTrackItems(); } catch (ex) { /* skip */ }
        if (autoRawFull && autoRawFull.length > 0) {
          var hasRemoveFullAuto = typeof autoRawFull[0].createRemoveAction === 'function';
          appLog('FULL auto-insert: ' + autoRawFull.length + ' items, createRemoveAction=' + hasRemoveFullAuto);
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) {
              for (var ri = 0; ri < autoRawFull.length; ri++) {
                if (hasRemoveFullAuto && typeof autoRawFull[ri].createRemoveAction === 'function') {
                  ca.addAction(autoRawFull[ri].createRemoveAction());
                } else {
                  if (typeof autoRawFull[ri].createSetDisabledAction === 'function')
                    ca.addAction(autoRawFull[ri].createSetDisabledAction(true));
                  if (typeof autoRawFull[ri].createSetNameAction === 'function')
                    ca.addAction(autoRawFull[ri].createSetNameAction('[AUTO-SKIP]'));
                }
              }
            }, 'FULL: clear auto-inserted');
          });
          appLog('FULL auto-insert cleared' + (hasRemoveFullAuto ? ' (removed)' : ' (disabled)'));
        }
      }
    } catch (clearEx) {
      appLog('FULL clear auto-insert: ' + clearEx.message);
    }
  } catch (ex) {
    appLog('createSequenceFromMedia FULL: ' + ex.message + ' — fallback');
    seq = await project.createSequence(seqName);
    appLog('FULL sequence created (default): ' + seqName);
  }

  var editor = bppro.SequenceEditor.getEditor(seq);
  if (!editor) { appLog('No editor for FULL', 'error'); return seq; }

  /* Sort ALL segments by block order (same as ROUGH), then by inSec within block */
  var allSegs = APP.segments.slice().sort(function (a, b) {
    if (a.block !== b.block) return a.block - b.block;
    return a.inSec - b.inSec;
  });

  /* Estimate max source durations per file (for safe spacing during insert) */
  var maxOutPerFile = {};
  APP.segments.forEach(function (s) {
    if (!maxOutPerFile[s.sourceFile] || s.outSec > maxOutPerFile[s.sourceFile]) {
      maxOutPerFile[s.sourceFile] = s.outSec;
    }
  });

  /* Insert each segment as its own clip on V1.
     Use WIDE spacing (full source duration) to prevent overlaps during insert.
     After trim+reposition step, clips will be packed tightly.
     IMPORTANT: track insertedSegs[] in parallel — when a segment is skipped
     (no clipItem), it must not appear in the parallel array used for trim/color. */
  var insertPos = 0;       /* Wide-spaced insert position */
  var targetPos = 0;       /* Tight target position (after reposition) */
  var insertedCount = 0;
  var insertedSegs = [];    /* Parallel array: insertedSegs[i] ↔ v1Items[i] */
  var useSegIndices = [];   /* Indices of USE segments for later coloring/markers */
  var cutSegIndices = [];   /* Indices of CUT segments for disabling */

  for (var i = 0; i < allSegs.length; i++) {
    var seg = allSegs[i];
    var clipItem = clipItems[seg.sourceFile];
    if (!clipItem) {
      appLog('FULL: skip ' + seg.id + ' (no clip for ' + seg.sourceFile + ')');
      continue;
    }

    var dec = APP.decisions[seg.id];
    var isUse = (dec === 'use' || dec === 'shorts' || (!dec && seg.use));

    try {
      var insertTime = bppro.TickTime.createWithSeconds(insertPos);
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(editor.createInsertProjectItemAction(
            clipItem, insertTime, 0, 0, false
          ));
        }, 'FULL: ' + seg.id);
      });

      /* Store the CORRECT target position (tight, no gaps) */
      seg._fullTimelineStart = targetPos;
      seg._fullTimelineEnd = targetPos + seg.duration;

      /* Track in parallel array — index matches v1Items */
      insertedSegs.push(seg);

      if (isUse) {
        useSegIndices.push({ idx: insertedCount, seg: seg });
      } else {
        cutSegIndices.push({ idx: insertedCount, seg: seg });
      }

      /* Wide spacing for insert: full source duration + 5s padding */
      var fullDur = maxOutPerFile[seg.sourceFile] || 300;
      insertPos += fullDur + 5;
      /* Tight spacing for target position */
      targetPos += seg.duration;
      insertedCount++;
    } catch (ex) {
      appLog('FULL insert ' + seg.id + ': ' + ex.message, 'error');
    }
  }

  appLog('FULL: inserted ' + insertedCount + '/' + allSegs.length + ' segments');

  /* Save FULL timeline positions for navigator */
  APP._fullTimelinePositions = {};
  insertedSegs.forEach(function (s) {
    if (s._fullTimelineStart !== undefined)
      APP._fullTimelinePositions[s.id] = s._fullTimelineStart;
  });
  appLog('FULL: saved ' + Object.keys(APP._fullTimelinePositions).length + ' timeline positions');

  /* Trim all clips to their segment in/out points */
  try {
    var v1Track = await seq.getVideoTrack(0);
    if (v1Track) {
      var v1Items = await _getTrackItems(v1Track);
      if (v1Items && v1Items.length > 0) {
        appLog('FULL: trimming + positioning ' + v1Items.length + ' track items...');
        var trimmed = 0;
        var positioned = 0;

        var canSetStart = v1Items.length > 0 && typeof v1Items[0].createSetStartAction === 'function';
        var canMove = v1Items.length > 0 && typeof v1Items[0].createMoveAction === 'function';
        appLog('FULL: createSetStartAction=' + canSetStart + ', createMoveAction=' + canMove);

        for (var ti = 0; ti < v1Items.length && ti < insertedSegs.length; ti++) {
          var tItem = v1Items[ti];
          var tSeg = insertedSegs[ti];
          if (!tItem || !tSeg) continue;

          /* Step A: Trim source in/out */
          try {
            var srcIn = bppro.TickTime.createWithSeconds(tSeg.inSec);
            var srcOut = bppro.TickTime.createWithSeconds(tSeg.outSec);
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                if (typeof tItem.createSetInPointAction === 'function')
                  ca.addAction(tItem.createSetInPointAction(srcIn));
                if (typeof tItem.createSetOutPointAction === 'function')
                  ca.addAction(tItem.createSetOutPointAction(srcOut));
              }, 'FULL trim: ' + tSeg.id);
            });
            trimmed++;
          } catch (ex) {
            if (ti < 3) appLog('FULL trim ' + tSeg.id + ': ' + ex.message, 'error');
          }

          /* Step B: Reposition to correct timeline position.
             CRITICAL: createMoveAction is RELATIVE — compute delta from current position.
             DO NOT pass absolute target directly — it would ADD to current start. */
          if (tSeg._fullTimelineStart !== undefined) {
            try {
              var fCurStart = tickSec(await tItem.getStartTime());
              var fMoveDelta = tSeg._fullTimelineStart - fCurStart;
              var fDeltaTime = bppro.TickTime.createWithSeconds(fMoveDelta);

              if (canMove) {
                project.lockedAccess(function () {
                  project.executeTransaction(function (ca) {
                    ca.addAction(tItem.createMoveAction(fDeltaTime));
                  }, 'FULL move: ' + tSeg.id);
                });
                positioned++;
              } else if (canSetStart) {
                var fTargetStart = bppro.TickTime.createWithSeconds(tSeg._fullTimelineStart);
                project.lockedAccess(function () {
                  project.executeTransaction(function (ca) {
                    ca.addAction(tItem.createSetStartAction(fTargetStart));
                  }, 'FULL pos: ' + tSeg.id);
                });
                /* Re-apply source trim to fix InPoint shift */
                try {
                  var fFixIn = bppro.TickTime.createWithSeconds(tSeg.inSec);
                  var fFixOut = bppro.TickTime.createWithSeconds(tSeg.outSec);
                  project.lockedAccess(function () {
                    project.executeTransaction(function (ca) {
                      ca.addAction(tItem.createSetOutPointAction(fFixOut));
                      ca.addAction(tItem.createSetInPointAction(fFixIn));
                    }, 'FULL fixTrim: ' + tSeg.id);
                  });
                } catch (fixEx) { /* ok */ }
                positioned++;
              }
            } catch (ex) {
              if (ti < 3) appLog('FULL pos ' + tSeg.id + ': ' + ex.message, 'error');
            }
          }
        }
        appLog('FULL: trimmed ' + trimmed + ', positioned ' + positioned + '/' + v1Items.length);

        /* Name + Color + Disable segments.
           Process CUT first, then USE — so USE colors survive on shared ProjectItems
           (createSetColorLabelAction affects the source clip, last write wins) */
        var coloredUse = 0;
        var disabledCut = 0;

        /* Pass 1: CUT segments — disable + name + color Red */
        for (var ci = 0; ci < v1Items.length && ci < insertedSegs.length; ci++) {
          var cItem1 = v1Items[ci];
          var cSeg1 = insertedSegs[ci];
          if (!cItem1 || !cSeg1) continue;
          var cDec1 = APP.decisions[cSeg1.id];
          var cIsUse1 = (cDec1 === 'use' || cDec1 === 'shorts' || (!cDec1 && cSeg1.use));
          if (cIsUse1) continue; /* skip USE in this pass */

          var cutColorIdx = LABEL_COLOR_INDEX.Red || 16;
          try {
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                if (typeof cItem1.createSetDisabledAction === 'function')
                  ca.addAction(cItem1.createSetDisabledAction(true));
                if (typeof cItem1.createSetNameAction === 'function')
                  ca.addAction(cItem1.createSetNameAction('[CUT] ' + cSeg1.id + ' ' + (cSeg1.blockName || '')));
              }, 'FULL disable: ' + cSeg1.id);
            });
            var cutProjItem = typeof cItem1.getProjectItem === 'function' ? await cItem1.getProjectItem() : null;
            if (cutProjItem && typeof cutProjItem.createSetColorLabelAction === 'function') {
              project.lockedAccess(function () {
                project.executeTransaction(function (ca) {
                  ca.addAction(cutProjItem.createSetColorLabelAction(cutColorIdx));
                }, 'FULL color CUT: ' + cSeg1.id);
              });
            }
            disabledCut++;
          } catch (ex) { /* ok */ }
        }

        /* Pass 2: USE segments — name + color (overwrites Red for shared sources) */
        for (var ci2 = 0; ci2 < v1Items.length && ci2 < insertedSegs.length; ci2++) {
          var cItem2 = v1Items[ci2];
          var cSeg2 = insertedSegs[ci2];
          if (!cItem2 || !cSeg2) continue;
          var cDec2 = APP.decisions[cSeg2.id];
          var cIsUse2 = (cDec2 === 'use' || cDec2 === 'shorts' || (!cDec2 && cSeg2.use));
          if (!cIsUse2) continue; /* skip CUT in this pass */

          var tagName = '[' + (cSeg2.color || 'Cyan') + '] ' + cSeg2.id + ' ' + cSeg2.blockName;
          var cColorIdx = LABEL_COLOR_INDEX[cSeg2.color] || LABEL_COLOR_INDEX.Cyan;
          try {
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                if (typeof cItem2.createSetNameAction === 'function')
                  ca.addAction(cItem2.createSetNameAction(tagName));
              }, 'FULL name: ' + cSeg2.id);
            });
            var cProjItem = typeof cItem2.getProjectItem === 'function' ? await cItem2.getProjectItem() : null;
            if (cProjItem && typeof cProjItem.createSetColorLabelAction === 'function') {
              project.lockedAccess(function () {
                project.executeTransaction(function (ca) {
                  ca.addAction(cProjItem.createSetColorLabelAction(cColorIdx));
                }, 'FULL color: ' + cSeg2.id);
              });
            }
            coloredUse++;
          } catch (ex) { /* ok */ }
        }

        appLog('FULL: labeled ' + coloredUse + ' USE, disabled ' + disabledCut + ' CUT');

        /* ── Remove ghost/leftover clips beyond expected segment count ── */
        if (v1Items.length > insertedSegs.length) {
          var ghostCount = v1Items.length - insertedSegs.length;
          appLog('FULL: ' + ghostCount + ' ghost clips to remove');

          var hasRemoveFull = typeof v1Items[insertedSegs.length].createRemoveAction === 'function';
          appLog('FULL: createRemoveAction=' + hasRemoveFull);

          if (hasRemoveFull) {
            try {
              project.lockedAccess(function () {
                project.executeTransaction(function (ca) {
                  for (var gi = insertedSegs.length; gi < v1Items.length; gi++) {
                    ca.addAction(v1Items[gi].createRemoveAction());
                  }
                }, 'FULL: remove ghosts');
              });
              appLog('FULL: removed ' + ghostCount + ' ghost clips');
            } catch (ghostErr) {
              appLog('FULL ghost removal FAILED: ' + ghostErr.message, 'error');
            }
          } else {
            /* Fallback: disable + rename ghosts ONE BY ONE (batch fails on filler/gap items) */
            appLog('FULL: NO createRemoveAction — disabling ghosts one by one');
            var ghostOkF = 0;
            for (var gi = insertedSegs.length; gi < v1Items.length; gi++) {
              try {
                var ghostF = v1Items[gi];
                if (!ghostF) continue;
                /* Check if it's a real clip (filler/gap items cause "Invalid parameter") */
                var gTypeF = -1;
                try { gTypeF = typeof ghostF.getType === 'function' ? await ghostF.getType() : -1; } catch (ex) {}
                var gProjF = null;
                try { gProjF = typeof ghostF.getProjectItem === 'function' ? await ghostF.getProjectItem() : null; } catch (ex) {}
                appLog('FULL ghost [' + gi + ']: type=' + gTypeF + ' projItem=' + (gProjF ? 'yes' : 'null'));
                if (!gProjF) {
                  appLog('FULL ghost [' + gi + ']: skipped (filler/gap)');
                  continue;
                }
                project.lockedAccess(function () {
                  project.executeTransaction(function (ca) {
                    if (typeof ghostF.createSetDisabledAction === 'function')
                      ca.addAction(ghostF.createSetDisabledAction(true));
                    if (typeof ghostF.createSetNameAction === 'function')
                      ca.addAction(ghostF.createSetNameAction('[GHOST]'));
                  }, 'FULL: ghost ' + gi);
                });
                ghostOkF++;
              } catch (ghostErrF) {
                appLog('FULL ghost [' + gi + '] failed: ' + ghostErrF.message);
              }
            }
            appLog('FULL: disabled ' + ghostOkF + '/' + ghostCount + ' ghosts');
          }
        }
      }
    }
  } catch (trimErr) {
    appLog('FULL trim/color error: ' + trimErr.message, 'error');
  }

  /* ── Add block-level CHAPTER markers on FULL sequence ── */
  try {
    var fullMarkers = await bppro.Markers.getMarkers(seq);
    if (fullMarkers) {
      var commentType = null;
      var chapterType = null;
      try { commentType = bppro.Marker.MARKER_TYPE_COMMENT; } catch (ex) { commentType = 'Comment'; }
      try { chapterType = bppro.Marker.MARKER_TYPE_CHAPTER; } catch (ex) { /* skip */ }
      var fullUseType = chapterType || commentType || 'Comment';

      /* Build block-level chapter markers from ALL segments (USE + CUT) */
      var fullBlocks = [];
      var allWithTimeline = allSegs.filter(function (s) { return s._fullTimelineStart !== undefined; });
      allWithTimeline.sort(function (a, b) { return a._fullTimelineStart - b._fullTimelineStart; });

      var fbCur = null;
      var fbStart = 0;
      var fbEnd = 0;
      var fbSegs = [];
      for (var fbi = 0; fbi < allWithTimeline.length; fbi++) {
        var fbSeg = allWithTimeline[fbi];
        if (fbCur !== null && fbSeg.block !== fbCur) {
          fullBlocks.push({ name: fbSegs[0].blockName, color: fbSegs[0].color,
                             start: fbStart, end: fbEnd, duration: fbEnd - fbStart, segs: fbSegs });
          fbStart = fbSeg._fullTimelineStart;
          fbEnd = fbSeg._fullTimelineEnd;
          fbSegs = [fbSeg];
        } else {
          if (fbSegs.length === 0) fbStart = fbSeg._fullTimelineStart;
          fbEnd = Math.max(fbEnd, fbSeg._fullTimelineEnd);
          fbSegs.push(fbSeg);
        }
        fbCur = fbSeg.block;
      }
      if (fbSegs.length > 0) {
        fullBlocks.push({ name: fbSegs[0].blockName, color: fbSegs[0].color,
                           start: fbStart, end: fbEnd, duration: fbEnd - fbStart, segs: fbSegs });
      }

      appLog('FULL: creating ' + fullBlocks.length + ' block chapter markers + segment markers...');

      var chapterCount = 0;
      var segMarkerCount = 0;

      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          /* 1. Block-level chapter markers (span full block) */
          for (var bm = 0; bm < fullBlocks.length; bm++) {
            try {
              var fb = fullBlocks[bm];
              var bStart_t = bppro.TickTime.createWithSeconds(fb.start);
              var bDur_t = bppro.TickTime.createWithSeconds(Math.max(fb.duration, 0.5));
              var bComment = fb.segs.length + ' segments, ' + fb.duration.toFixed(1) + 's';
              ca.addAction(fullMarkers.createAddMarkerAction(fb.name, fullUseType, bStart_t, bDur_t, bComment));
              chapterCount++;
            } catch (ex) { appLog('FULL block marker ' + bm + ': ' + ex.message); }
          }

          /* 2. Per-segment comment markers (within chapters) */
          for (var mi = 0; mi < useSegIndices.length; mi++) {
            try {
              var mSeg = useSegIndices[mi].seg;
              var mStart = bppro.TickTime.createWithSeconds(mSeg._fullTimelineStart);
              var mDur = bppro.TickTime.createWithSeconds(Math.max(mSeg.duration, 0.5));
              var mComment = (mSeg.speaker ? mSeg.speaker + ': ' : '') +
                             (mSeg.transcript || '').slice(0, 60);
              ca.addAction(fullMarkers.createAddMarkerAction(
                mSeg.blockName + ' (' + mSeg.id + ')', commentType, mStart, mDur, mComment
              ));
              segMarkerCount++;
            } catch (ex) { /* skip individual marker errors */ }
          }
        }, 'FULL markers');
      });

      appLog('FULL: ' + chapterCount + ' chapter markers + ' + segMarkerCount + ' segment markers created');
    }
  } catch (markErr) {
    appLog('FULL markers error: ' + markErr.message);
  }

  appLog('FULL: complete (' + insertedCount + ' segments, ' +
         useSegIndices.length + ' USE, ' + cutSegIndices.length + ' CUT)');
  return seq;
}

/* ══════════════════════════════
   CREATE ROUGH CUT SEQUENCE
   USE=TRUE on V1, USE=FALSE on V2
   ══════════════════════════════ */

async function _createRoughSequence(project, seqName, clipItems) {
  /* Find first clip for sequence settings */
  var firstClipItem = null;
  var allKeys = Object.keys(clipItems);
  if (allKeys.length > 0) firstClipItem = clipItems[allKeys[0]];

  /* Create from media */
  var seq = null;
  if (firstClipItem) {
    try {
      var castClip = bppro.ClipProjectItem.cast(firstClipItem);
      seq = await project.createSequenceFromMedia(seqName, [castClip || firstClipItem]);
      appLog('ROUGH sequence created from media: ' + seqName);

      /* Remove the auto-inserted clip — we want clean timeline */
      try {
        var v0 = await seq.getVideoTrack(0);
        if (v0) {
          /* Get ALL raw items (don't use _getTrackItems which filters disabled) */
          var autoRaw = null;
          try { autoRaw = v0.getTrackItems(1, false); } catch (ex) { /* skip */ }
          if (!autoRaw) try { autoRaw = v0.getTrackItems(); } catch (ex) { /* skip */ }
          if (autoRaw && autoRaw.length > 0) {
            var hasRemoveAuto = typeof autoRaw[0].createRemoveAction === 'function';
            appLog('Auto-insert removal: ' + autoRaw.length + ' items, createRemoveAction=' + hasRemoveAuto);
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                for (var ri = 0; ri < autoRaw.length; ri++) {
                  if (hasRemoveAuto && typeof autoRaw[ri].createRemoveAction === 'function') {
                    ca.addAction(autoRaw[ri].createRemoveAction());
                  } else {
                    /* Fallback: disable + rename so _getTrackItems filters them out */
                    if (typeof autoRaw[ri].createSetDisabledAction === 'function')
                      ca.addAction(autoRaw[ri].createSetDisabledAction(true));
                    if (typeof autoRaw[ri].createSetNameAction === 'function')
                      ca.addAction(autoRaw[ri].createSetNameAction('[AUTO-SKIP]'));
                  }
                }
              }, 'Clear auto-inserted');
            });
            appLog('Cleared auto-inserted clip from ROUGH' + (hasRemoveAuto ? ' (removed)' : ' (disabled)'));
          }
        }
      } catch (clearEx) {
        appLog('Clear auto-insert ROUGH: ' + clearEx.message);
      }
    } catch (ex) {
      appLog('createSequenceFromMedia ROUGH: ' + ex.message + ' — fallback');
    }
  }

  if (!seq) {
    seq = await project.createSequence(seqName);
    appLog('ROUGH sequence created (default): ' + seqName);
  }

  var editor = bppro.SequenceEditor.getEditor(seq);
  if (!editor) {
    appLog('No editor for ROUGH', 'error');
    return { seq: seq, useSegs: [], cutSegs: [] };
  }

  /* Separate USE vs CUT segments */
  var useSegs = [];
  var cutSegs = [];

  APP.segments.forEach(function (s) {
    var dec = APP.decisions[s.id];
    var isUse = (dec === 'use' || dec === 'shorts' || (!dec && s.use));
    if (isUse && s.priority <= 1) {
      useSegs.push(s);
    } else {
      cutSegs.push(s);
    }
  });

  useSegs.sort(function (a, b) { return a.block - b.block || a.inSec - b.inSec; });
  cutSegs.sort(function (a, b) { return a.block - b.block || a.inSec - b.inSec; });

  appLog('ROUGH: ' + useSegs.length + ' USE, ' + cutSegs.length + ' CUT');

  /* Estimate max source durations per file (for safe spacing) */
  var maxOutPerFile = {};
  APP.segments.forEach(function (s) {
    if (!maxOutPerFile[s.sourceFile] || s.outSec > maxOutPerFile[s.sourceFile]) {
      maxOutPerFile[s.sourceFile] = s.outSec;
    }
  });

  /* Insert USE segments on V1
     Use wide spacing (full source duration) to prevent overlaps.
     _timelineStart stores the correct tight position for repositioning later. */
  var insertPos = 0;
  var targetPos = 0;
  var insertedUse = 0;

  for (var i = 0; i < useSegs.length; i++) {
    var seg = useSegs[i];
    var clipItem = clipItems[seg.sourceFile];
    if (!clipItem) { appLog('ROUGH V1: no clip for ' + seg.sourceFile); continue; }

    try {
      var insertTime = bppro.TickTime.createWithSeconds(insertPos);
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(editor.createInsertProjectItemAction(
            clipItem, insertTime, 0, 0, false
          ));
        }, 'V1: ' + seg.id);
      });
      seg._timelineStart = targetPos;
      seg._timelineEnd = targetPos + seg.duration;
      /* Wide spacing for insert */
      var fullDur = maxOutPerFile[seg.sourceFile] || 300;
      insertPos += fullDur + 5;
      /* Tight target position */
      targetPos += seg.duration;
      insertedUse++;
    } catch (ex) {
      appLog('V1 insert ' + seg.id + ': ' + ex.message, 'error');
    }
  }

  appLog('V1: inserted ' + insertedUse + '/' + useSegs.length);

  /* ROUGH = only USE on V1, no CUT segments at all.
     User opens FULL + ROUGH side by side: FULL shows all material,
     ROUGH shows the clean final edit. CUT is only in FULL. */
  appLog('ROUGH: ' + cutSegs.length + ' CUT segments skipped (ROUGH = USE only)');

  /* Store ROUGH timeline positions for navigator */
  APP._roughTimelinePositions = {};
  useSegs.forEach(function (s) {
    if (s._timelineStart !== undefined) APP._roughTimelinePositions[s.id] = s._timelineStart;
  });
  APP._timelinePositions = APP._roughTimelinePositions;
  appLog('ROUGH: saved ' + Object.keys(APP._roughTimelinePositions).length + ' timeline positions');

  return { seq: seq, useSegs: useSegs, cutSegs: [] };
}

/* ══════════════════════════════
   TRIM CLIPS ON TIMELINE
   Uses AWAIT for getVideoTrack (returns Promise!)
   Uses getTrackItems(CLIP, false) with correct params
   ══════════════════════════════ */

async function _trimClipsOnSequence(project, seq, useSegs, cutSegs) {
  if (!seq) return;
  await _trimTrack(project, seq, 0, useSegs, 'V1');
  /* Only trim V2 if there are CUT segments (ROUGH has none) */
  if (cutSegs && cutSegs.length > 0) {
    await _trimTrack(project, seq, 1, cutSegs, 'V2');
  }
}

/* ── Helper: read TickTime as seconds (robust, works across API versions) ── */
function tickSec(tickTime) {
  if (!tickTime) return -1;
  try {
    var s = tickTime.seconds;
    if (typeof s === 'number' && !isNaN(s)) return s;
    s = tickTime.secs;
    if (typeof s === 'number' && !isNaN(s)) return s;
    var t = tickTime.ticks;
    if (typeof t === 'number' && !isNaN(t)) return t / 254016000000;
    if (typeof t === 'bigint') return Number(t) / 254016000000;
    var str = String(tickTime);
    var parsed = parseFloat(str);
    if (!isNaN(parsed) && parsed > 0) return parsed;
    return -1;
  } catch (e) { return -1; }
}

async function _trimTrack(project, seq, trackIndex, segs, label) {
  if (!segs || segs.length === 0) return;

  try {
    /* CRITICAL: getVideoTrack returns Promise — must await! */
    var track = await seq.getVideoTrack(trackIndex);
    if (!track) {
      appLog(label + ': getVideoTrack(' + trackIndex + ') returned null', 'error');
      return;
    }

    /* Log track info */
    appLog(label + ': track name=' + (track.name || '?') + ', id=' + (track.id || '?'));

    /* Get track items with correct params */
    var trackItems = await _getTrackItems(track);

    if (!trackItems || trackItems.length === 0) {
      /* Enumerate track for debugging */
      var keys = [];
      try {
        var proto = Object.getPrototypeOf(track);
        if (proto) {
          var pNames = Object.getOwnPropertyNames(proto);
          for (var pk = 0; pk < pNames.length; pk++) {
            keys.push(pNames[pk] + ':' + typeof track[pNames[pk]]);
          }
        }
      } catch (ex) { /* ok */ }
      appLog(label + ' track proto: ' + (keys.join(', ') || 'none'));
      appLog(label + ': no track items found', 'error');
      return;
    }

    appLog(label + ': ' + trackItems.length + ' track items found');

    /* Log first TrackItem capabilities */
    if (trackItems.length > 0) {
      var ti0 = trackItems[0];
      var tiKeys = [];
      try {
        var tiProto = Object.getPrototypeOf(ti0);
        if (tiProto) {
          var tiNames = Object.getOwnPropertyNames(tiProto);
          for (var tn = 0; tn < tiNames.length; tn++) {
            tiKeys.push(tiNames[tn] + ':' + typeof ti0[tiNames[tn]]);
          }
        }
      } catch (ex) { /* ok */ }
      appLog(label + ' TrackItem proto: ' + (tiKeys.join(', ') || 'none'));
    }

    /* tickSec is defined at module scope (before _trimTrack) */

    /* ── Probe TickTime structure (once per label) ──
       CRITICAL: getStartTime() returns a PROMISE in UXP 25.3! Must await. */
    if (trackItems.length > 0) {
      try {
        var probeTime = await trackItems[0].getStartTime();
        var probeInfo = [];
        if (probeTime) {
          /* Own enumerable keys */
          var ownK = Object.keys(probeTime);
          for (var ok = 0; ok < ownK.length; ok++) {
            probeInfo.push(ownK[ok] + '=' + typeof probeTime[ownK[ok]] + ':' + String(probeTime[ownK[ok]]).substring(0, 30));
          }
          /* Proto methods/properties */
          var ttProto = Object.getPrototypeOf(probeTime);
          if (ttProto) {
            var ttNames = Object.getOwnPropertyNames(ttProto);
            for (var tn2 = 0; tn2 < ttNames.length; tn2++) {
              probeInfo.push('proto.' + ttNames[tn2] + '=' + typeof probeTime[ttNames[tn2]]);
            }
          }
          probeInfo.push('toString=' + String(probeTime));
          probeInfo.push('typeof=' + typeof probeTime);
          probeInfo.push('JSON=' + JSON.stringify(probeTime).substring(0, 100));
        } else {
          probeInfo.push('NULL');
        }
        appLog(label + ' TickTime probe (AWAITED): ' + probeInfo.join(', '));
      } catch (probeErr) {
        appLog(label + ' TickTime probe error: ' + probeErr.message);
      }
    }

    /* ── Log BEFORE state for each clip (ALL getters return Promises — must await) ── */
    appLog(label + ': === BEFORE TRIM ===');
    for (var d = 0; d < trackItems.length; d++) {
      try {
        var di = trackItems[d];
        var dStart = tickSec(await di.getStartTime());
        var dEnd = tickSec(await di.getEndTime());
        var dIn = tickSec(await di.getInPoint());
        var dOut = tickSec(await di.getOutPoint());
        var dDur = tickSec(await di.getDuration());
        var dName = '';
        try { dName = await di.getName(); } catch (ex) { dName = '?'; }
        appLog(label + '  [' + d + '] start=' + dStart.toFixed(1) + ' end=' + dEnd.toFixed(1) +
               ' in=' + dIn.toFixed(1) + ' out=' + dOut.toFixed(1) +
               ' dur=' + dDur.toFixed(1) + ' name="' + dName + '"');
      } catch (ex) {
        appLog(label + '  [' + d + '] error reading: ' + ex.message);
      }
    }

    /* Trim each item + reposition.
       CRITICAL FIX (v1.0.14): Use createMoveAction (not createSetStartAction) for repositioning.
       createSetStartAction ADJUSTS InPoint by the same delta → corrupts source trim.
       createMoveAction moves clip on timeline WITHOUT modifying InPoint/OutPoint. */
    var canSetStart = trackItems.length > 0 && typeof trackItems[0].createSetStartAction === 'function';
    var canMove = trackItems.length > 0 && typeof trackItems[0].createMoveAction === 'function';
    appLog(label + ': canMove=' + canMove + ', canSetStart=' + canSetStart + ' (prefer Move)');

    var trimmed = 0;
    var positioned = 0;
    for (var i = 0; i < trackItems.length && i < segs.length; i++) {
      var item = trackItems[i];
      var seg = segs[i];
      if (!item || !seg) continue;

      appLog(label + '  trim[' + i + '] ' + seg.id + ' (' + seg.sourceFile + '): ' +
             'src=' + seg.inSec.toFixed(1) + '-' + seg.outSec.toFixed(1) + ' (' + seg.duration.toFixed(1) + 's)' +
             ' → target=' + (seg._timelineStart !== undefined ? seg._timelineStart.toFixed(1) : '?'));

      /* Step A: Trim source in/out — SEPARATE transactions for reliability */
      try {
        var srcIn = bppro.TickTime.createWithSeconds(seg.inSec);
        var srcOut = bppro.TickTime.createWithSeconds(seg.outSec);

        /* Verify TickTime creation */
        appLog(label + '    TickTime: srcIn=' + tickSec(srcIn).toFixed(3) + ' srcOut=' + tickSec(srcOut).toFixed(3));

        /* Set OUT first (shrinks from right, no position shift) */
        if (typeof item.createSetOutPointAction === 'function') {
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) {
              ca.addAction(item.createSetOutPointAction(srcOut));
            }, 'TrimOut ' + seg.id);
          });
        }

        /* Log after OUT */
        try {
          var aftOutStart = tickSec(await item.getStartTime());
          var aftOutEnd = tickSec(await item.getEndTime());
          var aftOutIn = tickSec(await item.getInPoint());
          var aftOutOut = tickSec(await item.getOutPoint());
          var aftOutDur = tickSec(await item.getDuration());
          appLog(label + '    after-OUT: start=' + aftOutStart.toFixed(1) + ' end=' + aftOutEnd.toFixed(1) +
                 ' in=' + aftOutIn.toFixed(1) + ' out=' + aftOutOut.toFixed(1) + ' dur=' + aftOutDur.toFixed(1));
        } catch (exLog) {
          appLog(label + '    after-OUT log err: ' + exLog.message);
        }

        /* Set IN second (shifts left edge) */
        if (typeof item.createSetInPointAction === 'function') {
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) {
              ca.addAction(item.createSetInPointAction(srcIn));
            }, 'TrimIn ' + seg.id);
          });
        }
        trimmed++;

        /* Log after IN */
        try {
          var midStart = tickSec(await item.getStartTime());
          var midEnd = tickSec(await item.getEndTime());
          var midIn = tickSec(await item.getInPoint());
          var midOut = tickSec(await item.getOutPoint());
          var midDur = tickSec(await item.getDuration());
          appLog(label + '    after-IN: start=' + midStart.toFixed(1) + ' end=' + midEnd.toFixed(1) +
                 ' in=' + midIn.toFixed(1) + ' out=' + midOut.toFixed(1) + ' dur=' + midDur.toFixed(1));
        } catch (exLog) {
          appLog(label + '    after-IN log err: ' + exLog.message);
        }
      } catch (ex) {
        appLog(label + '  trim ' + seg.id + ' FAILED: ' + ex.message, 'error');
      }

      /* Step B: Reposition clip to correct timeline position.
         CRITICAL: createMoveAction is RELATIVE (adds delta to current position), NOT absolute.
         We must read current start and compute delta = target - current.
         DO NOT use createSetStartAction — it adjusts InPoint by the move delta. */
      if (seg._timelineStart !== undefined) {
        try {
          var curStart = tickSec(await item.getStartTime());
          var moveDelta = seg._timelineStart - curStart;
          var deltaTime = bppro.TickTime.createWithSeconds(moveDelta);
          appLog(label + '    move ' + seg.id + ': cur=' + curStart.toFixed(1) + ' target=' + seg._timelineStart.toFixed(1) + ' delta=' + moveDelta.toFixed(1));

          if (canMove) {
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                ca.addAction(item.createMoveAction(deltaTime));
              }, 'Move ' + seg.id);
            });
            positioned++;
          } else if (canSetStart) {
            /* Fallback: createSetStartAction adjusts InPoint — compensate afterward */
            var targetStart = bppro.TickTime.createWithSeconds(seg._timelineStart);
            appLog(label + '    WARNING: no createMoveAction, using createSetStartAction (may shift InPoint)');
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                ca.addAction(item.createSetStartAction(targetStart));
              }, 'Pos ' + seg.id);
            });
            /* Re-apply InPoint to fix the shift caused by createSetStartAction */
            try {
              var fixIn = bppro.TickTime.createWithSeconds(seg.inSec);
              var fixOut = bppro.TickTime.createWithSeconds(seg.outSec);
              project.lockedAccess(function () {
                project.executeTransaction(function (ca) {
                  ca.addAction(item.createSetOutPointAction(fixOut));
                  ca.addAction(item.createSetInPointAction(fixIn));
                }, 'FixTrim ' + seg.id);
              });
            } catch (fixEx) {
              appLog(label + '    fix InPoint after SetStart: ' + fixEx.message, 'error');
            }
            positioned++;
          }

          /* Log AFTER reposition — include InPoint/OutPoint to verify trim integrity */
          try {
            var aftStart = tickSec(await item.getStartTime());
            var aftEnd = tickSec(await item.getEndTime());
            var aftIn = tickSec(await item.getInPoint());
            var aftOut = tickSec(await item.getOutPoint());
            var aftDur = tickSec(await item.getDuration());
            var trimOk = (Math.abs(aftIn - seg.inSec) < 0.1 && Math.abs(aftOut - seg.outSec) < 0.1);
            var posOk = (Math.abs(aftStart - seg._timelineStart) < 0.2);
            var allOk = trimOk && posOk;
            appLog(label + '    after-pos: start=' + aftStart.toFixed(1) + ' end=' + aftEnd.toFixed(1) +
                   ' in=' + aftIn.toFixed(1) + ' out=' + aftOut.toFixed(1) +
                   ' dur=' + aftDur.toFixed(1) +
                   (allOk ? ' ✓' : ' ✗') +
                   (!posOk ? ' POS-MISMATCH(want=' + seg._timelineStart.toFixed(1) + ')' : '') +
                   (!trimOk ? ' TRIM-MISMATCH' : ''));
          } catch (ex) { /* ok */ }
        } catch (ex) {
          appLog(label + '  pos ' + seg.id + ' FAILED: ' + ex.message, 'error');
        }
      }
    }

    appLog(label + ': trimmed ' + trimmed + '/' + segs.length +
           ', positioned ' + positioned);

    /* ── Remove ghost/leftover clips beyond expected segment count ── */
    if (trackItems.length > segs.length) {
      var ghostCount = trackItems.length - segs.length;
      appLog(label + ': need to remove ' + ghostCount + ' ghost clips (total=' + trackItems.length + ', expected=' + segs.length + ')');

      /* Check what removal methods exist */
      var g0 = trackItems[segs.length];
      var hasRemove = typeof g0.createRemoveAction === 'function';
      appLog(label + ': createRemoveAction=' + hasRemove);

      if (hasRemove) {
        try {
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) {
              for (var gi = segs.length; gi < trackItems.length; gi++) {
                if (trackItems[gi] && typeof trackItems[gi].createRemoveAction === 'function') {
                  ca.addAction(trackItems[gi].createRemoveAction());
                }
              }
            }, label + ': remove ghosts');
          });
          appLog(label + ': removed ' + ghostCount + ' ghost clips');
        } catch (ghostErr) {
          appLog(label + ' ghost removal FAILED: ' + ghostErr.message, 'error');
        }
      } else {
        /* Fallback: disable + rename ghosts ONE BY ONE (batch fails on filler/gap items) */
        appLog(label + ': NO createRemoveAction — disabling ghosts one by one');
        var ghostOkR = 0;
        for (var gi = segs.length; gi < trackItems.length; gi++) {
          try {
            var ghostR = trackItems[gi];
            if (!ghostR) continue;
            /* Check if it's a real clip (filler/gap items cause "Invalid parameter") */
            var gTypeR = -1;
            try { gTypeR = typeof ghostR.getType === 'function' ? await ghostR.getType() : -1; } catch (ex) {}
            var gProjR = null;
            try { gProjR = typeof ghostR.getProjectItem === 'function' ? await ghostR.getProjectItem() : null; } catch (ex) {}
            appLog(label + ' ghost [' + gi + ']: type=' + gTypeR + ' projItem=' + (gProjR ? 'yes' : 'null'));
            if (!gProjR) {
              appLog(label + ' ghost [' + gi + ']: skipped (filler/gap)');
              continue;
            }
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                if (typeof ghostR.createSetDisabledAction === 'function')
                  ca.addAction(ghostR.createSetDisabledAction(true));
                if (typeof ghostR.createSetNameAction === 'function')
                  ca.addAction(ghostR.createSetNameAction('[GHOST]'));
              }, label + ': ghost ' + gi);
            });
            ghostOkR++;
          } catch (ghostErrR) {
            appLog(label + ' ghost [' + gi + '] failed: ' + ghostErrR.message);
          }
        }
        appLog(label + ': disabled ' + ghostOkR + '/' + ghostCount + ' ghosts');
      }
    }

    /* ── Log AFTER state ── */
    appLog(label + ': === AFTER ALL ===');
    var afterItems = await _getTrackItems(track);
    for (var a = 0; a < Math.min(afterItems.length, segs.length + 5); a++) {
      try {
        var ai2 = afterItems[a];
        var aStart = tickSec(await ai2.getStartTime());
        var aEnd = tickSec(await ai2.getEndTime());
        var aDur = tickSec(await ai2.getDuration());
        var aName = '';
        try { aName = await ai2.getName(); } catch (ex) { aName = '?'; }
        appLog(label + '  [' + a + '] start=' + aStart.toFixed(1) + ' end=' + aEnd.toFixed(1) +
               ' dur=' + aDur.toFixed(1) + ' "' + aName + '"');
      } catch (ex) { /* ok */ }
    }
  } catch (e) {
    appLog(label + ' trim error: ' + e.message, 'error');
  }
}

/* ══════════════════════════════
   APPLY LABEL COLORS
   V1 → block semantic colors
   V2 → Red (CUT) + mute
   ══════════════════════════════ */

async function _applyColors(project, seq, useSegs, cutSegs) {
  if (!seq) return;
  /* Apply CUT (V2) FIRST, then USE (V1).
     Since createSetColorLabelAction sets color on the source ProjectItem
     (not the timeline instance), the LAST write wins.
     By processing USE last, USE-block colors survive for shared source files. */
  await _colorTrack(project, seq, 1, cutSegs, true, 'V2');
  await _colorTrack(project, seq, 0, useSegs, false, 'V1');
}

async function _colorTrack(project, seq, trackIndex, segs, isCut, label) {
  if (!segs || segs.length === 0) return;

  try {
    var track = await seq.getVideoTrack(trackIndex);
    if (!track) return;

    var trackItems = await _getTrackItems(track);
    if (!trackItems || trackItems.length === 0) return;

    var colored = 0;
    var renamed = 0;
    var muted = 0;
    var colorStrategy = 'none';

    /* Warn about shared source files with different colors (ProjectItem color = last write wins) */
    if (!isCut) {
      var srcColorMap = {};
      for (var sci = 0; sci < segs.length; sci++) {
        var scSeg = segs[sci];
        if (!srcColorMap[scSeg.sourceFile]) {
          srcColorMap[scSeg.sourceFile] = scSeg.color || 'Cyan';
        } else if (srcColorMap[scSeg.sourceFile] !== (scSeg.color || 'Cyan')) {
          appLog(label + ' WARNING: ' + scSeg.sourceFile + ' used in multiple blocks with different colors (' +
                 srcColorMap[scSeg.sourceFile] + ' vs ' + (scSeg.color || 'Cyan') + '). ProjectItem color = last write wins. Clip name includes [Color] tag for disambiguation.');
        }
      }
    }

    for (var i = 0; i < trackItems.length && i < segs.length; i++) {
      var item = trackItems[i];
      var seg = segs[i];
      if (!item || !seg) continue;

      var colorIdx = isCut ? LABEL_COLOR_INDEX.Red : (LABEL_COLOR_INDEX[seg.color] || 0);
      var colorName = isCut ? 'Red' : (seg.color || 'Cyan');

      /* ── ALWAYS rename clip on timeline (block name visible to editor) ── */
      try {
        if (typeof item.createSetNameAction === 'function') {
          var clipName = isCut
            ? '[CUT] ' + seg.id + ' ' + (seg.blockName || '')
            : '[' + colorName + '] ' + seg.id + ' ' + seg.blockName;
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) {
              ca.addAction(item.createSetNameAction(clipName));
            }, 'Name: ' + seg.id);
          });
          renamed++;
        }
      } catch (ex) {
        if (i === 0) appLog('Rename ' + seg.id + ': ' + ex.message, 'error');
      }

      /* ── Color: Try TrackItem direct, then ProjectItem, then skip ── */

      /* Strategy 1: TrackItem direct color (future API) */
      if (colorStrategy === 'none' || colorStrategy === 'trackItem') {
        try {
          if (typeof item.createSetColorByIndexAction === 'function') {
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                ca.addAction(item.createSetColorByIndexAction(colorIdx));
              }, 'Color: ' + seg.id);
            });
            colored++;
            colorStrategy = 'trackItem';
          }
        } catch (ex) {
          if (i === 0) appLog('TrackItem color: ' + ex.message);
        }
      }

      /* Strategy 2: ProjectItem → createSetColorLabelAction
         NOTE: This sets color on the SOURCE CLIP, not the timeline instance!
         All instances of the same source file get the SAME color.
         Last write wins — we set USE color first, CUT (Red) may overwrite. */
      if (colorStrategy === 'none' || colorStrategy === 'projectItem') {
        try {
          if (typeof item.getProjectItem === 'function') {
            var projItem = await item.getProjectItem();
            if (projItem) {
              /* Log ProjectItem proto once + probe for SubClip creation */
              if (i === 0) {
                var piKeys = [];
                try {
                  var piProto = Object.getPrototypeOf(projItem);
                  if (piProto) {
                    var piNames = Object.getOwnPropertyNames(piProto);
                    for (var pk = 0; pk < piNames.length; pk++) {
                      piKeys.push(piNames[pk] + ':' + typeof projItem[piNames[pk]]);
                    }
                  }
                } catch (ex2) { /* ok */ }
                appLog(label + ' ProjectItem proto: ' + (piKeys.join(', ') || 'none'));
              }

              if (typeof projItem.createSetColorLabelAction === 'function') {
                project.lockedAccess(function () {
                  project.executeTransaction(function (ca) {
                    ca.addAction(projItem.createSetColorLabelAction(colorIdx));
                  }, 'Color Label: ' + seg.id);
                });
                colored++;
                colorStrategy = 'projectItem';
              } else if (i === 0) {
                appLog('ProjectItem has no createSetColorLabelAction');
              }
            }
          }
        } catch (ex) {
          if (i === 0) appLog('ProjectItem color: ' + ex.message);
        }
      }

      /* ── Mute/disable CUT clips ── */
      if (isCut) {
        try {
          if (typeof item.createSetDisabledAction === 'function') {
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                ca.addAction(item.createSetDisabledAction(true));
              }, 'Disable: ' + seg.id);
            });
            muted++;
          } else if (typeof item.createSetMutedAction === 'function') {
            project.lockedAccess(function () {
              project.executeTransaction(function (ca) {
                ca.addAction(item.createSetMutedAction(true));
              }, 'Mute: ' + seg.id);
            });
            muted++;
          }
        } catch (ex) {
          if (i === 0) appLog('Mute ' + seg.id + ': ' + ex.message);
        }
      }
    }

    appLog(label + ': renamed ' + renamed + ', colored ' + colored + '/' + segs.length +
           ' (strategy: ' + colorStrategy + ')' +
           (isCut ? ', disabled ' + muted : ''));
  } catch (e) {
    appLog(label + ' color error: ' + e.message, 'error');
  }
}

/* ══════════════════════════════
   CREATE MARKERS ON ROUGH
   ══════════════════════════════ */

async function _createMarkers(project, seq, useSegs) {
  if (!seq || !useSegs || useSegs.length === 0) return;

  try {
    var markersObj = await bppro.Markers.getMarkers(seq);
    if (!markersObj) { appLog('Markers: null', 'error'); return; }

    /* Debug: enumerate Markers and Marker API to discover color methods */
    try {
      var markersProto = [];
      for (var k in markersObj) { markersProto.push(k + ':' + typeof markersObj[k]); }
      appLog('Markers proto: ' + markersProto.join(', '));
    } catch (ex) { /* ok */ }
    try {
      var markerTypes = [];
      for (var mk in bppro.Marker) { markerTypes.push(mk + '=' + bppro.Marker[mk]); }
      appLog('Marker constants: ' + markerTypes.join(', '));
    } catch (ex) { /* ok */ }

    var markerType = null;
    var chapterType = null;
    try { markerType = bppro.Marker.MARKER_TYPE_COMMENT; } catch (ex) { /* skip */ }
    try { chapterType = bppro.Marker.MARKER_TYPE_CHAPTER; } catch (ex) { /* skip */ }

    /* Calculate block positions — group consecutive USE segs by block */
    var blocks = [];
    var curBlock = null;
    var bStart = 0;
    var bDur = 0;
    var bSegs = [];

    for (var i = 0; i < useSegs.length; i++) {
      var seg = useSegs[i];
      if (curBlock !== null && seg.block !== curBlock) {
        blocks.push({ name: bSegs[0].blockName, color: bSegs[0].color,
                       start: bStart, duration: bDur, segs: bSegs,
                       isChapter: bSegs.some(function (s) { return s.isChapter; }) });
        bStart += bDur;
        bDur = 0;
        bSegs = [];
      }
      curBlock = seg.block;
      bDur += seg.duration;
      bSegs.push(seg);
    }
    if (bSegs.length > 0) {
      blocks.push({ name: bSegs[0].blockName, color: bSegs[0].color,
                     start: bStart, duration: bDur, segs: bSegs,
                     isChapter: bSegs.some(function (s) { return s.isChapter; }) });
    }

    appLog('Creating ' + blocks.length + ' chapter markers (block-level)...');
    for (var bi = 0; bi < blocks.length; bi++) {
      appLog('  Block ' + (bi + 1) + ': "' + blocks[bi].name + '" ' +
             blocks[bi].start.toFixed(1) + 's-' + (blocks[bi].start + blocks[bi].duration).toFixed(1) + 's ' +
             '(' + blocks[bi].duration.toFixed(1) + 's, ' + blocks[bi].segs.length + ' segs, color=' + blocks[bi].color + ')');
    }
    var count = 0;

    /* Use Chapter type (shows as colored blocks in timeline) like reference project */
    var useType = chapterType || markerType || 'Comment';
    appLog('Marker type: ' + useType + ' (chapter=' + chapterType + ', comment=' + markerType + ')');

    try {
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          for (var m = 0; m < blocks.length; m++) {
            try {
              var b = blocks[m];
              /* Start at block start, duration = FULL block duration (not 1s!) */
              var mStart = bppro.TickTime.createWithSeconds(b.start);
              var mDur = bppro.TickTime.createWithSeconds(Math.max(b.duration, 0.5));
              var comment = b.segs.map(function (s) {
                return (s.speaker ? s.speaker + ': ' : '') + (s.transcript || '').slice(0, 50);
              }).join(' | ');
              ca.addAction(markersObj.createAddMarkerAction(b.name, useType, mStart, mDur, comment));
              count++;
            } catch (ex) { appLog('Marker ' + m + ': ' + ex.message); }
          }
        }, 'YTAI Chapter Markers');
      });
    } catch (e) {
      appLog('Markers batch failed: ' + e.message + ' — trying individually', 'error');
      count = 0;
      for (var f = 0; f < blocks.length; f++) {
        try {
          var fb = blocks[f];
          var fStart = bppro.TickTime.createWithSeconds(fb.start);
          var fDur = bppro.TickTime.createWithSeconds(Math.max(fb.duration, 0.5));
          var fAct = markersObj.createAddMarkerAction(
            fb.name, useType, fStart, fDur,
            fb.name + ' (' + fb.segs.length + ' segments, ' + fb.duration.toFixed(1) + 's)'
          );
          project.lockedAccess(function () {
            project.executeTransaction(function (ca) { ca.addAction(fAct); }, 'Marker: ' + fb.name);
          });
          count++;
        } catch (ex) { appLog('Marker ' + fb.name + ': ' + ex.message, 'error'); }
      }
    }

    appLog('Created ' + count + '/' + blocks.length + ' chapter markers');
  } catch (e) {
    appLog('Markers error: ' + e.message, 'error');
  }
}

/* ══════════════════════════════
   NORMALIZE TRANSCRIPT FOR ADOBE
   Fixes 4 schema violations:
   1. Word timestamps ms → seconds
   2. speakerId → speaker (delete speakerId)
   3. Add segment-level start & duration
   4. Strip extra properties (additionalProperties: false)
   5. Ensure root speakers[] array
   ══════════════════════════════ */

function _normalizeTranscriptForAdobe(tData) {
  if (!tData || !tData.segments) return tData;

  /* 1. Build speakers[] from speakerIds */
  var speakerSet = {};
  tData.segments.forEach(function (seg) {
    var sid = seg.speakerId || seg.speaker;
    if (sid && !speakerSet[sid]) speakerSet[sid] = true;
  });
  var speakerIds = Object.keys(speakerSet);
  if (speakerIds.length === 0) {
    speakerIds = ['00000000-0000-4000-0000-000000000001'];
  }
  tData.speakers = speakerIds.map(function (id, idx) {
    return { id: id, name: 'Speaker ' + (idx + 1) };
  });

  /* 2. Normalize each segment */
  var normalizedSegments = [];
  for (var si = 0; si < tData.segments.length; si++) {
    var seg = tData.segments[si];
    var words = seg.words || [];

    /* Detect ms vs seconds: if any word.start > 100, assume milliseconds */
    var isMs = false;
    for (var wi = 0; wi < words.length; wi++) {
      if (words[wi].start > 100) { isMs = true; break; }
    }

    /* Normalize words: only keep allowed fields, convert ms→sec */
    var cleanWords = [];
    var segStartSec = Infinity;
    var segEndSec = 0;

    for (var wj = 0; wj < words.length; wj++) {
      var w = words[wj];
      var wStart = isMs ? w.start / 1000.0 : w.start;
      var wDur   = isMs ? w.duration / 1000.0 : w.duration;
      var wEnd   = wStart + wDur;

      if (wStart < segStartSec) segStartSec = wStart;
      if (wEnd > segEndSec) segEndSec = wEnd;

      /* Adobe allowed word fields only: text, start, duration, confidence, type */
      var cleanWord = {
        text: w.text || '',
        start: Math.round(wStart * 1000) / 1000,
        duration: Math.round(wDur * 1000) / 1000,
        confidence: w.confidence != null ? w.confidence : 1.0,
      };
      /* Only include 'type' if it's punctuation */
      if (w.type === 'punctuation') {
        cleanWord.type = 'punctuation';
      }
      cleanWords.push(cleanWord);
    }

    if (segStartSec === Infinity) segStartSec = 0;

    /* Get speaker: rename speakerId → speaker */
    var speakerId = seg.speaker || seg.speakerId || speakerIds[0];

    /* Build clean segment: only Adobe-allowed fields */
    var cleanSeg = {
      language: seg.language || tData.language || 'en-us',
      speaker: speakerId,
      start: Math.round(segStartSec * 1000) / 1000,
      duration: Math.round((segEndSec - segStartSec) * 1000) / 1000,
      words: cleanWords,
    };

    normalizedSegments.push(cleanSeg);
  }

  /* Build clean root object */
  var result = {
    language: tData.language || 'en-us',
    speakers: tData.speakers,
    segments: normalizedSegments,
  };

  return result;
}

/* ══════════════════════════════
   LOAD TRANSCRIPTS
   Two-step: importFromJSON(string) → TextSegments
   Then createImportTextSegmentsAction(textSegments, clipItem) → Action
   Uses _normalizeTranscriptForAdobe() to fix schema
   ══════════════════════════════ */

async function loadTranscripts() {
  if (!bppro) { appLog('Premiere API not available', 'error'); return; }
  if (!APP.briefFileEntry) { appLog('No brief file loaded', 'error'); return; }

  try {
    var briefPath = APP.briefFileEntry.nativePath;
    if (!briefPath) { appLog('Brief: no nativePath', 'error'); return; }

    var lastSlash = Math.max(briefPath.lastIndexOf('/'), briefPath.lastIndexOf('\\'));
    var parentDir = lastSlash > 0 ? briefPath.substring(0, lastSlash) : briefPath;
    appLog('Brief dir: ' + parentDir);

    /* Build transcript search paths */
    var roots = [];
    if (APP.transcriptionDir) {
      roots.push(parentDir + '/' + APP.transcriptionDir + '/per_clip');
    }
    if (APP.projectName) {
      roots.push(parentDir + '/' + APP.projectName + '_transcription/per_clip');
    }
    roots.push(parentDir + '/per_clip');
    roots.push(parentDir + '/transcription/per_clip');

    /* Deduplicate */
    var seen = {};
    roots = roots.filter(function (r) { if (seen[r]) return false; seen[r] = true; return true; });

    /* Discover Transcript API */
    var transcriptMethods = [];
    if (bppro.Transcript) {
      try {
        var proto = Object.getOwnPropertyNames(bppro.Transcript);
        for (var tp = 0; tp < proto.length; tp++) {
          transcriptMethods.push(proto[tp] + ':' + typeof bppro.Transcript[proto[tp]]);
        }
      } catch (ex) { /* ok */ }
    }
    appLog('Transcript API: ' + (transcriptMethods.length > 0 ? transcriptMethods.join(', ') : 'N/A'));

    /* Get all project items for per-clip import */
    var project = await bppro.Project.getActiveProject();
    var rootItem = await project.getRootItem();
    var allProjItems = {};
    await _scanBin(rootItem, allProjItems);

    var fileSet = {};
    APP.segments.forEach(function (s) { if (s.sourceFile) fileSet[s.sourceFile] = true; });
    var sourceFiles = Object.keys(fileSet);
    var loaded = 0;
    var foundRoot = null;

    for (var i = 0; i < sourceFiles.length; i++) {
      var clipId = sourceFiles[i].replace(/\.[^.]+$/, '');
      var transcriptLoaded = false;

      var searchRoots = foundRoot ? [foundRoot] : roots;
      for (var r = 0; r < searchRoots.length; r++) {
        var tPath = searchRoots[r] + '/' + clipId + '/' + clipId + '_premiere_transcript.json';

        try {
          var tEntry = await buxpFs.getEntryWithUrl('file:' + tPath);
          if (!tEntry) continue;

          var text = await tEntry.read({ format: buxpFormats.utf8 });
          appLog('Transcript found: ' + clipId + ' (' + text.length + ' chars)');
          foundRoot = searchRoots[r];

          /* Parse original JSON */
          var rawData = null;
          try { rawData = JSON.parse(text); } catch (pe) {
            appLog('Transcript JSON parse error: ' + pe.message, 'error');
            break;
          }

          /* Store raw data for text-based editing view */
          APP._transcriptData[clipId] = rawData;

          /* Normalize for Adobe import */
          var tData = _normalizeTranscriptForAdobe(rawData);
          var jsonString = JSON.stringify(tData);
          appLog('Transcript normalized: ' + clipId +
                 ' (' + tData.segments.length + ' segs, ' +
                 tData.speakers.length + ' speakers)');

          /* Find clip project item */
          var clipProjItem = allProjItems[clipId] || allProjItems[sourceFiles[i]];

          if (bppro.Transcript) {
            /* Step 1: importFromJSON(string) → TextSegments */
            try {
              var textSegments = bppro.Transcript.importFromJSON(jsonString);
              appLog('Transcript importFromJSON OK: ' + clipId);

              /* Step 2: createImportTextSegmentsAction(textSegments, clipItem) → Action */
              if (clipProjItem && typeof bppro.Transcript.createImportTextSegmentsAction === 'function') {
                try {
                  var castClip = bppro.ClipProjectItem.cast(clipProjItem);
                  var importAction = bppro.Transcript.createImportTextSegmentsAction(
                    textSegments, castClip || clipProjItem
                  );

                  /* Execute the action */
                  project.lockedAccess(function () {
                    project.executeTransaction(function (ca) {
                      ca.addAction(importAction);
                    }, 'Transcript: ' + clipId);
                  });

                  loaded++;
                  transcriptLoaded = true;
                  appLog('Transcript imported: ' + clipId);
                } catch (actErr) {
                  appLog('Transcript action ' + clipId + ': ' + actErr.message, 'error');

                  /* Log the first few chars of JSON for debugging */
                  appLog('JSON preview: ' + jsonString.substring(0, 200));
                }
              } else {
                appLog('Transcript: no clipItem or no createImportTextSegmentsAction for ' + clipId);
              }
            } catch (parseErr) {
              appLog('importFromJSON ' + clipId + ': ' + parseErr.message, 'error');

              /* Log first segment for debugging */
              try {
                var debugSeg = tData.segments[0];
                appLog('Debug seg[0]: ' + JSON.stringify(debugSeg).substring(0, 200));
              } catch (dex) { /* ok */ }
            }
          }

          break;
        } catch (e) {
          /* Try next root */
        }
      }

      if (!transcriptLoaded) {
        appLog('Transcript ' + clipId + ': not imported to Premiere');
      }
    }

    appLog('Transcripts: ' + loaded + '/' + sourceFiles.length + ' imported');
    BUS.emit('transcripts-loaded');
  } catch (e) {
    appLog('Transcripts error: ' + e.message, 'error');
  }
}

/* ══════════════════════════════
   API TEST
   ══════════════════════════════ */

async function testAPIs() {
  var results = [];

  async function t(name, fn) {
    try { await fn(); results.push({ name: name, ok: true }); }
    catch (e) { results.push({ name: name, ok: false, err: e.message }); }
  }

  if (!bppro) return [{ name: 'premierepro', ok: false, err: 'Not available' }];

  await t('premierepro', function () { if (!bppro) throw new Error('Missing'); });

  await t('Project', async function () {
    var p = await bppro.Project.getActiveProject();
    if (!p) throw new Error('None');
  });

  await t('Sequence', async function () {
    var p = await bppro.Project.getActiveProject();
    var s = await p.getActiveSequence();
    if (!s) throw new Error('No active sequence');
  });

  await t('FolderItem.cast', async function () {
    var p = await bppro.Project.getActiveProject();
    var root = await p.getRootItem();
    var f = bppro.FolderItem.cast(root);
    if (!f) throw new Error('cast failed');
  });

  await t('SequenceEditor', async function () {
    var p = await bppro.Project.getActiveProject();
    var s = await p.getActiveSequence();
    if (!s) throw new Error('No sequence');
    var e = bppro.SequenceEditor.getEditor(s);
    if (!e) throw new Error('getEditor failed');
  });

  await t('TickTime', function () {
    var tt = bppro.TickTime.createWithSeconds(1.0);
    if (!tt) throw new Error('Failed');
  });

  await t('Constants', function () {
    if (!bppro.Constants) throw new Error('No Constants');
    if (!bppro.Constants.TrackItemType) throw new Error('No TrackItemType');
    appLog('TrackItemType: CLIP=' + bppro.Constants.TrackItemType.CLIP +
           ', EMPTY=' + bppro.Constants.TrackItemType.EMPTY);
  });

  await t('Markers', async function () {
    var p = await bppro.Project.getActiveProject();
    var s = await p.getActiveSequence();
    if (!s) throw new Error('No sequence');
    var m = await bppro.Markers.getMarkers(s);
    if (!m) throw new Error('null');
  });

  await t('Track + getTrackItems', async function () {
    var p = await bppro.Project.getActiveProject();
    var s = await p.getActiveSequence();
    if (!s) throw new Error('No sequence');
    var count = s.getVideoTrackCount();
    appLog('Video track count: ' + count);
    var track = await s.getVideoTrack(0);
    if (!track) throw new Error('getVideoTrack(0) null');

    /* Enumerate track prototype */
    var keys = [];
    try {
      var proto = Object.getPrototypeOf(track);
      var names = Object.getOwnPropertyNames(proto);
      for (var i = 0; i < names.length; i++) {
        keys.push(names[i] + ':' + typeof track[names[i]]);
      }
    } catch (ex) { /* ok */ }
    appLog('Track proto: ' + keys.join(', '));

    var items = await _getTrackItems(track);
    appLog('Track items: ' + (items ? items.length : 'null'));

    if (items && items.length > 0) {
      var tiKeys = [];
      try {
        var tiProto = Object.getPrototypeOf(items[0]);
        var tiNames = Object.getOwnPropertyNames(tiProto);
        for (var j = 0; j < tiNames.length; j++) {
          tiKeys.push(tiNames[j] + ':' + typeof items[0][tiNames[j]]);
        }
      } catch (ex) { /* ok */ }
      appLog('TrackItem proto: ' + tiKeys.join(', '));
    }
  });

  await t('Transcript API', function () {
    if (!bppro.Transcript) throw new Error('No Transcript');
    var keys = [];
    try {
      var names = Object.getOwnPropertyNames(bppro.Transcript);
      for (var i = 0; i < names.length; i++) {
        keys.push(names[i] + ':' + typeof bppro.Transcript[names[i]]);
      }
    } catch (ex) { /* ok */ }
    appLog('Transcript: ' + keys.join(', '));
  });

  await t('ClipProjectItem.cast', async function () {
    var p = await bppro.Project.getActiveProject();
    var root = await p.getRootItem();
    var items = {};
    await _scanBin(root, items);
    var keys = Object.keys(items);
    if (keys.length === 0) throw new Error('No project items');
    var first = items[keys[0]];
    var cast = bppro.ClipProjectItem.cast(first);
    appLog('ClipProjectItem.cast: ' + (cast ? 'OK' : 'null') + ' on ' + keys[0]);
  });

  await t('UXP File API', function () { if (!buxpFs) throw new Error('Missing'); });

  appLog('API: ' + results.filter(function (r) { return r.ok; }).length + '/' + results.length + ' passed');
  return results;
}

/* Global namespace */
var BUILD = {
  runBuild: runBuild,
  loadTranscripts: loadTranscripts,
  testAPIs: testAPIs,
  _normalizeTranscriptForAdobe: _normalizeTranscriptForAdobe,
};

console.log('[YTAI] build-sequence.js loaded OK. BUILD =', typeof BUILD);
