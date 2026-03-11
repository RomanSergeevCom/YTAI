/* importer.js — Import clips, create bins, detect source folder */

var bppro = require('premierepro');
var uxpStorage = require('uxp').storage;
var uxpFs = uxpStorage.localFileSystem;
var uxpFormats = uxpStorage.formats;

// Auto-detect source folder from brief file path
async function findSourceFolder(briefEntry) {
  if (APP.sourceFolderEntry) {
    appLog('Using saved source folder');
    return APP.sourceFolderEntry;
  }

  if (!briefEntry || !briefEntry.nativePath) {
    appLog('No brief file path — select source folder manually', 'warn');
    return null;
  }

  var briefPath = briefEntry.nativePath;
  var lastSlash = Math.max(briefPath.lastIndexOf('/'), briefPath.lastIndexOf('\\'));
  if (lastSlash <= 0) return null;

  var parentDir = briefPath.substring(0, lastSlash);
  APP.sourceFolderPath = parentDir;

  try {
    var entry = await uxpFs.getEntryWithUrl('file:' + parentDir);
    if (entry) {
      APP.sourceFolderEntry = entry;
      appLog('Source folder: ' + parentDir, 'ok');
      return entry;
    }
  } catch (ex) {
    appLog('Auto-detect failed: ' + ex.message, 'warn');
  }

  return null;
}

// Recursively scan project bins for existing clips
async function scanExistingClips(rootItem) {
  var existing = {};
  await _scanBin(rootItem, existing);
  return existing;
}

async function _scanBin(folder, map) {
  var items;
  try {
    items = await folder.getItems();
  } catch (ex) {
    return;
  }
  if (!items) return;

  for (var i = 0; i < items.length; i++) {
    var item = items[i];
    var name = '';
    try { name = item.name || ''; } catch (ex) { continue; }

    // Check if it's a folder (bin)
    if (typeof item.getItems === 'function') {
      await _scanBin(bppro.FolderItem.cast(item), map);
    } else {
      // Store by full name and name without extension
      map[name] = item;
      var dotIdx = name.lastIndexOf('.');
      if (dotIdx > 0) {
        map[name.substring(0, dotIdx)] = item;
      }
    }
  }
}

// Find or create a bin under parent folder
async function findOrCreateBin(project, parentFolder, name) {
  // Try to find existing
  try {
    var children = await parentFolder.getItems();
    if (children) {
      for (var i = 0; i < children.length; i++) {
        var n = '';
        try { n = children[i].name || ''; } catch (ex) { continue; }
        if (n === name && typeof children[i].getItems === 'function') {
          return bppro.FolderItem.cast(children[i]);
        }
      }
    }
  } catch (ex) { /* ignore */ }

  // Create new bin
  try {
    var createAct = parentFolder.createBinAction(name, true);
    project.lockedAccess(function () {
      project.executeTransaction(function (ca) {
        ca.addAction(createAct);
      }, 'Create bin: ' + name);
    });
  } catch (e) {
    appLog('Bin creation failed: ' + name + ' — ' + e.message, 'error');
    return parentFolder;
  }

  // Retrieve the newly created bin
  try {
    var items = await parentFolder.getItems();
    if (items) {
      for (var j = items.length - 1; j >= 0; j--) {
        var nm = '';
        try { nm = items[j].name || ''; } catch (ex) { continue; }
        if (nm === name || nm.indexOf(name) === 0) {
          return bppro.FolderItem.cast(items[j]);
        }
      }
    }
  } catch (ex) { /* ignore */ }

  return parentFolder;
}

// Create the full bin structure
async function createBinStructure(project, rootItem, blocks) {
  var root = bppro.FolderItem.cast(rootItem);
  var bins = {};

  bins.sources = await findOrCreateBin(project, root, '01_Sources');
  var blocksParent = await findOrCreateBin(project, root, '02_Blocks');

  // Create per-block bins
  for (var i = 0; i < blocks.length; i++) {
    var b = blocks[i];
    if (b.id === 99) continue; // Skip cut block
    var blockBinName = 'Block_' + String(b.id).padStart(2, '0') + '_' + b.name.replace(/[^a-zA-Z0-9_\- ]/g, '');
    bins['block_' + b.id] = await findOrCreateBin(project, blocksParent, blockBinName);
  }

  bins.alternatives = await findOrCreateBin(project, root, '03_Alternatives');
  bins.unused = await findOrCreateBin(project, root, '04_Unused');

  appLog('Bins created: ' + Object.keys(bins).length, 'ok');
  return bins;
}

// Import source video files into project
async function importSourceFiles(project, segments, existingClips, sourcesBin) {
  // Collect unique source files
  var fileSet = {};
  segments.forEach(function (seg) {
    if (seg.sourceFile) fileSet[seg.sourceFile] = true;
  });
  var sourceFiles = Object.keys(fileSet);
  appLog('Source files to import: ' + sourceFiles.length);

  var clipMap = {};
  var imported = 0;

  for (var i = 0; i < sourceFiles.length; i++) {
    var filename = sourceFiles[i];

    // Check if already in project
    if (existingClips[filename]) {
      clipMap[filename] = existingClips[filename];
      appLog('  Already imported: ' + filename);
      imported++;
      continue;
    }

    // Build full path
    var fullPath = APP.sourceFolderPath + '/' + filename;

    try {
      await project.importFiles([fullPath], true, sourcesBin, false);
      appLog('  Imported: ' + filename, 'ok');
      imported++;

      // Re-scan to find the imported clip
      var binItems = await sourcesBin.getItems();
      if (binItems) {
        for (var j = binItems.length - 1; j >= 0; j--) {
          var itemName = '';
          try { itemName = binItems[j].name || ''; } catch (ex) { continue; }
          if (itemName === filename || itemName.indexOf(filename.split('.')[0]) === 0) {
            clipMap[filename] = binItems[j];
            break;
          }
        }
      }
    } catch (e) {
      appLog('  Import failed: ' + filename + ' — ' + e.message, 'error');
    }
  }

  if (!clipMap[sourceFiles[0]] && imported > 0) {
    // Fallback: full project re-scan
    var allClips = await scanExistingClips(bppro.FolderItem.cast(await project.getRootItem()));
    sourceFiles.forEach(function (f) {
      if (!clipMap[f] && allClips[f]) clipMap[f] = allClips[f];
    });
  }

  APP.clipMap = clipMap;
  appLog('Clips ready: ' + Object.keys(clipMap).length + '/' + sourceFiles.length, 'ok');
  return clipMap;
}
