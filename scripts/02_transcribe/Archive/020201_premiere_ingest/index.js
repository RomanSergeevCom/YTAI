/**
 * YTAI Ingest — UXP Plugin for Adobe Premiere Pro
 *
 * Loads an ingest JSON and builds a timeline with bins, clips, SRT, and transcripts.
 */

const ppro = require("premierepro");
const uxp = require("uxp");
const uxpfs = uxp.storage.localFileSystem;

// --- Module imports ---

const { parseIngest, getUniqueSourceFiles, generateSummary } = require("./src/ingestLoader");
const { Logger } = require("./src/logger");
const { createBinStructure, BIN_NAMES } = require("./src/binManager");
const { buildIngestSequence, findProjectItemByName } = require("./src/timelineBuilder");
const { importTranscripts } = require("./src/transcriptImporter");
const { copyLutsToCreativeFolder, applyLumetriToClips } = require("./src/lutManager");

// --- Constants ---

const DEBUG_INGEST_PATH = '/Users/romansergeev/YTAI/scripts/05_editing/999_testing_project/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/Setup/YTCG37_Setup_UAE_Company_Remotely_ingest.json';

// --- State ---

let currentIngest = null;
let ingestFilePath = null;
const logger = new Logger();

// --- UI Helpers ---

function $(id) {
  return document.querySelector(`#${id}`);
}

function setStatus(text, type) {
  const statusEl = $("status");
  const dotClass = type === "error" ? "error" : type === "ready" ? "ready" : "waiting";
  statusEl.innerHTML = `<span class="status-dot ${dotClass}"></span> ${text}`;
}

function setProgress(percent, text) {
  const bar = $("progress-bar");
  const fill = $("progress-fill");
  const textEl = $("progress-text");

  bar.style.display = "block";
  textEl.style.display = "block";
  fill.style.width = `${percent}%`;
  textEl.textContent = text || "";
}

function hideProgress() {
  $("progress-bar").style.display = "none";
  $("progress-text").style.display = "none";
}

function appendLog(entry, level) {
  const panel = $("log-panel");
  const cls = level === "ERROR" ? "log-error"
    : level === "WARN" ? "log-warn"
    : level === "DEBUG" ? "log-debug"
    : "log-info";
  panel.innerHTML += `<span class="${cls}">${escapeHtml(entry)}</span>\n`;
  panel.scrollTop = panel.scrollHeight;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// Connect logger to UI
logger.onLog = (entry, level) => {
  appendLog(entry, level);
};

// --- Core Functions ---

/**
 * Load ingest JSON from a given path string (absolute) without file picker.
 */
async function loadIngestFromPath(filePath) {
  logger.info(`Loading ingest from path: ${filePath}`);

  const fileEntry = await uxpfs.getEntryWithUrl('file://' + filePath);
  const contents = await fileEntry.read();
  logger.debug(`Ingest JSON: ${contents.length} chars`);
  const ingest = parseIngest(contents);

  currentIngest = ingest;
  ingestFilePath = filePath;

  logger.setIngestInfo(filePath, ingest.source_folder || "(not set)");

  // Show summary
  const summary = generateSummary(ingest);
  const summaryPanel = $("summary-panel");
  summaryPanel.textContent = summary;
  summaryPanel.style.display = "block";

  // Show file info
  $("file-info").textContent = `File: ${filePath}`;
  if (ingest.source_folder) {
    $("file-info").textContent += `\nSource: ${ingest.source_folder}`;
  }

  // Enable build button
  $("btn-build").removeAttribute("disabled");

  setStatus("Ingest loaded. Ready to build.", "ready");
  logger.info(`Ingest loaded: ${ingest.clips.length} clips, project "${ingest.project_name}"`);
}

async function loadIngest() {
  try {
    logger.info("Opening file picker for ingest JSON...");

    const file = await uxpfs.getFileForOpening({
      types: ["json"],
      allowMultiple: false
    });

    if (!file) {
      logger.warn("File selection cancelled");
      return;
    }

    const contents = await file.read();
    const ingest = parseIngest(contents);

    currentIngest = ingest;

    ingestFilePath = file.nativePath;
    logger.info(`Ingest file nativePath: ${ingestFilePath || "(empty)"}`);

    if (!ingestFilePath) {
      ingestFilePath = file.name || "unknown";
      logger.warn(`nativePath not available, using file.name: ${ingestFilePath}`);
    }

    logger.setIngestInfo(ingestFilePath, ingest.source_folder || "(not set)");

    const summary = generateSummary(ingest);
    const summaryPanel = $("summary-panel");
    summaryPanel.textContent = summary;
    summaryPanel.style.display = "block";

    $("file-info").textContent = `File: ${ingestFilePath}`;
    if (ingest.source_folder) {
      $("file-info").textContent += `\nSource: ${ingest.source_folder}`;
    }

    $("btn-build").removeAttribute("disabled");

    setStatus("Ingest loaded. Ready to build.", "ready");
    logger.info(`Ingest loaded: ${ingest.clips.length} clips, project "${ingest.project_name}"`);

  } catch (err) {
    logger.error(`Failed to load ingest: ${err.message}`);
    if (err.stack) logger.debug(err.stack);
    setStatus(`Error: ${err.message}`, "error");
  }
}

/**
 * Clean project before rebuild: delete old sequence and clear bin contents.
 */
async function cleanBeforeBuild(project, ingest, logger) {
  const sequenceName = `${ingest.project_name} — Ingest`;
  logger.info(`=== Clean before build ===`);

  // 1. Delete existing sequence with same name
  const rootItem = await project.getRootItem();
  const allItems = await rootItem.getItems();

  for (const item of allItems) {
    // Check root-level sequences
    if (item.name === sequenceName && item.type !== 2) {
      try {
        await project.deleteSequence(item);
        logger.info(`Deleted old sequence: "${sequenceName}"`);
      } catch (e) {
        logger.debug(`Cannot delete sequence "${sequenceName}": ${e.message}`);
      }
    }
    // Check inside bins for sequences
    try {
      const folder = ppro.FolderItem.cast(item);
      if (folder) {
        const children = await folder.getItems();
        for (const child of children) {
          if (child.name === sequenceName && child.type !== 2) {
            try {
              await project.deleteSequence(child);
              logger.info(`Deleted old sequence from bin: "${sequenceName}"`);
            } catch (e) {
              logger.debug(`Cannot delete sequence from bin: ${e.message}`);
            }
          }
        }
        // Clear bin contents (media, SRT, etc.)
        if ([BIN_NAMES.SOURCE, BIN_NAMES.TRANSCRIPTS].includes(item.name)) {
          for (const child of children) {
            try {
              project.lockedAccess(() => {
                project.executeTransaction((compoundAction) => {
                  const removeAction = folder.createRemoveItemAction(child);
                  compoundAction.addAction(removeAction);
                }, `Remove ${child.name}`);
              });
              logger.debug(`Removed from ${item.name}: "${child.name}"`);
            } catch (e) {
              logger.debug(`Cannot remove "${child.name}": ${e.message}`);
            }
          }
        }
      }
    } catch (e) {
      // Not a folder, skip
    }
  }
  logger.info(`Clean complete`);
}

async function buildTimeline() {
  if (!currentIngest) {
    logger.error("No ingest loaded");
    return;
  }

  try {
    $("btn-build").setAttribute("disabled", "true");
    $("validation-panel").style.display = "none";
    setStatus("Building timeline...", "waiting");

    const project = await ppro.Project.getActiveProject();
    if (!project) {
      throw new Error("No active Premiere Pro project. Please open a project first.");
    }

    logger.setProjectInfo(project.name, project.path);

    const ingest = currentIngest;
    const totalSteps = 6;
    let step = 0;

    const buildStartTime = Date.now();

    logger.info("=== Build started ===");
    logger.info(`Project: ${project.name}`);
    logger.info(`Project path: ${project.path}`);
    logger.info(`Ingest: ${ingestFilePath}`);
    logger.info(`Clips: ${ingest.clips.length}, Resolution: ${ingest.media.width}x${ingest.media.height} @ ${ingest.media.fps}fps`);

    // Log clip details
    for (const clip of ingest.clips) {
      logger.debug(`  Clip: ${clip.clip_id} — ${clip.filename} (${clip.duration}s, path=${clip.path})`);
    }

    // Log host info
    try {
      logger.debug(`Host: ${uxp.host.name} ${uxp.host.version}`);
      logger.debug(`UXP: ${uxp.versions.uxp}`);
    } catch (e) {
      logger.debug(`Host info unavailable: ${e.message}`);
    }

    // Step 0: Clean old build
    step++;
    setProgress((step / totalSteps) * 100, `Step ${step}/${totalSteps}: Cleaning old build...`);
    await cleanBeforeBuild(project, ingest, logger);

    // Step 1: Create bins
    step++;
    setProgress((step / totalSteps) * 100, `Step ${step}/${totalSteps}: Creating bins...`);
    logger.info("=== Step 1: Creating bin structure ===");

    const bins = await createBinStructure(project, logger);

    // Step 2: Import media + build sequence
    step++;
    setProgress((step / totalSteps) * 100, `Step ${step}/${totalSteps}: Building sequence...`);
    logger.info("=== Step 2: Importing media & building sequence ===");

    const result = await buildIngestSequence(
      project,
      ingest,
      bins[BIN_NAMES.SOURCE] || null,
      bins[BIN_NAMES.SEQUENCE] || null,
      logger
    );

    // Step 3: Import transcripts
    step++;
    setProgress((step / totalSteps) * 100, `Step ${step}/${totalSteps}: Importing transcripts...`);
    logger.info("=== Step 3: Importing transcripts ===");

    const transcriptResult = await importTranscripts(
      project,
      ingest,
      bins[BIN_NAMES.TRANSCRIPTS] || null,
      logger,
      result.sequence || null
    );

    // Step 4: Copy LUTs + apply Lumetri Color
    step++;
    setProgress((step / totalSteps) * 100, `Step ${step}/${totalSteps}: Applying LUTs...`);
    logger.info("=== Step 4: Copy LUTs & apply Lumetri Color ===");

    let lumetriApplied = 0;
    try {
      const copiedLuts = await copyLutsToCreativeFolder(ingest, logger);
      if (result.sequence) {
        lumetriApplied = await applyLumetriToClips(project, result.sequence, logger);
      }
    } catch (lutErr) {
      logger.warn(`LUT step failed: ${lutErr.message}`);
    }

    // Step 5: Activate sequence + final log
    step++;
    setProgress((step / totalSteps) * 100, `Step ${step}/${totalSteps}: Activating sequence...`);
    logger.info("=== Step 5: Activating sequence ===");

    if (result.sequence) {
      await project.setActiveSequence(result.sequence);
      try {
        await project.openSequence(result.sequence.guid || result.sequence);
      } catch (openErr) {
        logger.warn(`openSequence not available: ${openErr.message}`);
      }
      logger.info(`Active sequence: "${result.sequence.name}"`);
    }

    // Done
    const buildElapsed = ((Date.now() - buildStartTime) / 1000).toFixed(1);
    setProgress(100, "Complete!");
    logger.info("=== Build complete ===");
    logger.info(`Summary: ${result.clipCount} clips on timeline, ${result.totalDuration}s total`);
    logger.info(`Transcripts: SRT=${transcriptResult.srtImported}, bound=${transcriptResult.transcriptsImported}`);
    logger.info(`Build elapsed: ${buildElapsed}s`);

    // Post-build validation
    if (result.sequence) {
      await validateBuild(result.sequence, ingest, {
        transcriptsImported: transcriptResult.transcriptsImported,
        srtImported: transcriptResult.srtImported,
        clipCount: result.clipCount,
        seqSettings: result.seqSettings,
        lumetriApplied
      });
    } else {
      setStatus("Timeline built (no sequence for validation)", "waiting");
    }

    // Auto-save to project folder
    await saveToProjectFolder();

    $("btn-build").removeAttribute("disabled");

  } catch (err) {
    logger.error(`Build failed: ${err.message}`);
    if (err.stack) logger.debug(err.stack);
    setStatus(`Build failed: ${err.message}`, "error");
    $("btn-build").removeAttribute("disabled");

    // Save logs on failure too
    await saveToProjectFolder();
  }
}

/**
 * Save logs + project to BOTH locations:
 * 1. source_folder/_transcription/ (project-specific)
 * 2. plugin/logs/ (always accessible via "Open Logs")
 */
async function saveToProjectFolder() {
  try {
    const project = await ppro.Project.getActiveProject();

    // Save Premiere project
    if (project) {
      try {
        await project.save();
        logger.info(`Premiere project saved: ${project.path}`);
      } catch (saveErr) {
        logger.warn(`Could not save Premiere project: ${saveErr.message}`);
      }
    }

    // Determine target folder
    const sourceFolder = currentIngest && currentIngest.source_folder;
    const projectName = currentIngest && currentIngest.project_name;
    if (!sourceFolder || !projectName) {
      logger.warn("No source_folder/project_name — cannot save to project folder");
      return;
    }

    // v3.0 structure: logs → 01_Media/Source/Setup/logs/; legacy fallback: _transcription/
    let logsDir = `${sourceFolder}/01_Media/Source/Setup/logs`;
    const legacyDir = `${sourceFolder}/${projectName}_transcription`;
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);

    logger.info(`Saving logs to: ${logsDir}`);

    // --- Save to project logs folder ---
    let folder;
    try {
      folder = await uxpfs.getEntryWithUrl('file://' + logsDir);
    } catch (e) {
      // Fallback to legacy path
      try {
        folder = await uxpfs.getEntryWithUrl('file://' + legacyDir);
        logger.info(`Using legacy logs path: ${legacyDir}`);
      } catch (e2) {
        logger.warn(`Cannot access logs folder: ${e.message}`);
      }
    }

    if (folder) {
      // Save log.txt
      const logFilename = `${projectName}_ingest_${ts}.log`;
      try {
        const logFile = await folder.createFile(logFilename, { overwrite: true });
        await logFile.write(logger.getReport());
        logger.info(`Log saved: ${logFilename}`);
      } catch (e) {
        logger.warn(`Cannot save log: ${e.message}`);
      }

      // Save debug snapshot (with extras if available)
      const snapshotFilename = `${projectName}_ingest_${ts}_debug.json`;
      try {
        const snapFile = await folder.createFile(snapshotFilename, { overwrite: true });
        const extras = {};
        try {
          const activeSeq = await project.getActiveSequence();
          if (activeSeq) {
            extras.sequenceName = activeSeq.name;
            extras.sequenceGuid = activeSeq.guid;
            extras.videoTrackCount = await activeSeq.getVideoTrackCount();
            extras.audioTrackCount = await activeSeq.getAudioTrackCount();
          }
        } catch (e) { /* ignore */ }
        await snapFile.write(logger.getDebugSnapshot(currentIngest, extras));
        logger.info(`Debug snapshot saved: ${snapshotFilename}`);
      } catch (e) {
        logger.warn(`Cannot save snapshot: ${e.message}`);
      }

      // Copy .prproj to transcription folder
      if (project && project.path) {
        try {
          const prprojEntry = await uxpfs.getEntryWithUrl('file://' + project.path);
          await prprojEntry.copyTo(folder, { overwrite: true });
          logger.info(`Project file copied: ${prprojEntry.name}`);
        } catch (e) {
          logger.warn(`Cannot copy .prproj: ${e.message}`);
        }
      }
    }

    // --- Also save to plugin's logs/ folder ---
    try {
      await logger.saveDebugBundle(currentIngest, project ? project.path : null);
    } catch (e) {
      logger.warn(`Cannot save to plugin logs/: ${e.message}`);
    }

  } catch (err) {
    logger.error(`Failed to save to project folder: ${err.message}`);
  }
}

/**
 * Post-build validation with strict checks.
 * @param {Object} sequence - Active sequence
 * @param {Object} ingest - Parsed ingest JSON
 * @param {Object} br - Build results { transcriptsImported, srtImported, clipCount, seqSettings }
 */
async function validateBuild(sequence, ingest, br) {
  logger.info("=== Post-build validation ===");
  const panel = $("validation-panel");
  const lines = [];
  let allOk = true;

  function ok(text) { lines.push(`<div class="val-line"><span style="color:var(--success)">●</span> ${escapeHtml(text)}</div>`); }
  function warn(text) { lines.push(`<div class="val-line"><span style="color:var(--warning)">●</span> ${escapeHtml(text)}</div>`); allOk = false; }
  function fail(text) { lines.push(`<div class="val-line"><span style="color:var(--error)">●</span> ${escapeHtml(text)}</div>`); allOk = false; }

  const expectedClips = ingest.clips;
  const expectedCount = expectedClips.length;
  const expectedDuration = Math.round(expectedClips.reduce((sum, c) => sum + c.duration, 0) * 10) / 10;

  // --- 1. V1 clips: count, order, sequential placement ---
  let v1Items = [];
  try {
    const v1Track = await sequence.getVideoTrack(0);
    const trackItems = await v1Track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
    logger.debug(`V1 track items: ${trackItems.length}`);

    for (let i = 0; i < trackItems.length; i++) {
      const ti = trackItems[i];
      const name = await ti.getName();
      const startTime = await ti.getStartTime();
      const duration = await ti.getDuration();
      const startSec = startTime.seconds !== undefined ? startTime.seconds : (startTime.ticks / 254016000000);
      const durSec = duration.seconds !== undefined ? duration.seconds : (duration.ticks / 254016000000);
      logger.debug(`  V1[${i}]: "${name}" start=${startSec.toFixed(2)}s dur=${durSec.toFixed(2)}s`);
      v1Items.push({ name, startSec, durSec });
    }

    // Count
    if (v1Items.length !== expectedCount) {
      warn(`V1: ${v1Items.length}/${expectedCount} clips`);
      logger.warn(`V1 clip count mismatch: ${v1Items.length} vs ${expectedCount}`);
    } else {
      // Order
      let orderOk = true;
      for (let i = 0; i < expectedCount; i++) {
        const actual = v1Items[i].name;
        const expected = expectedClips[i].filename;
        if (actual !== expected && actual !== expected.replace(/\.[^.]+$/, '')) {
          logger.warn(`V1[${i}] name: "${actual}" vs "${expected}"`);
          orderOk = false;
        }
      }
      // Sequential (no gaps)
      let gapsOk = true;
      for (let i = 1; i < v1Items.length; i++) {
        const prevEnd = Math.round((v1Items[i - 1].startSec + v1Items[i - 1].durSec) * 100) / 100;
        const currStart = Math.round(v1Items[i].startSec * 100) / 100;
        if (Math.abs(prevEnd - currStart) > 0.1) {
          logger.warn(`V1 gap: clip ${i - 1} ends at ${prevEnd}s, clip ${i} starts at ${currStart}s`);
          gapsOk = false;
        }
      }

      if (orderOk && gapsOk) {
        ok(`V1: ${expectedCount}/${expectedCount} clips, sequential`);
        logger.info(`V1 OK: ${expectedCount} clips, sequential, no gaps`);
      } else if (!orderOk) {
        warn(`V1: ${expectedCount} clips, order MISMATCH`);
      } else {
        warn(`V1: ${expectedCount} clips, gaps detected`);
      }
    }
  } catch (err) {
    fail(`V1: check failed — ${err.message}`);
    logger.error(`V1 validation failed: ${err.message}`);
    if (err.stack) logger.debug(err.stack);
  }

  // --- 2. V2+ strict: ANY clip is an error ---
  try {
    const vTrackCount = await sequence.getVideoTrackCount();
    let totalExtra = 0;
    for (let t = 1; t < vTrackCount; t++) {
      const track = await sequence.getVideoTrack(t);
      const items = await track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
      for (const ti of items) {
        const name = await ti.getName();
        logger.warn(`  V${t + 1} has clip: "${name}"`);
        totalExtra++;
      }
    }
    if (totalExtra === 0) {
      ok(`V2+: empty`);
      logger.info(`V2+ OK: no clips`);
    } else {
      fail(`V2+: ${totalExtra} unexpected clip(s)`);
    }
  } catch (err) {
    logger.debug(`V2+ check: ${err.message}`);
  }

  // --- 3. A1 clips match V1 ---
  try {
    const a1Track = await sequence.getAudioTrack(0);
    const a1Items = await a1Track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
    if (a1Items.length === expectedCount) {
      ok(`A1: ${a1Items.length}/${expectedCount} clips`);
      logger.info(`A1 OK: ${a1Items.length} clips`);
    } else {
      warn(`A1: ${a1Items.length}/${expectedCount} clips`);
      logger.warn(`A1 mismatch: ${a1Items.length} vs ${expectedCount}`);
    }
  } catch (err) {
    logger.debug(`A1 check: ${err.message}`);
  }

  // --- 4. Duration ---
  if (v1Items.length > 0) {
    const last = v1Items[v1Items.length - 1];
    const actualEnd = Math.round((last.startSec + last.durSec) * 10) / 10;
    if (Math.abs(actualEnd - expectedDuration) < 1) {
      ok(`Duration: ${actualEnd}s`);
      logger.info(`Duration OK: ${actualEnd}s (expected ${expectedDuration}s)`);
    } else {
      warn(`Duration: ${actualEnd}s (expected ${expectedDuration}s)`);
      logger.warn(`Duration mismatch: ${actualEnd}s vs ${expectedDuration}s`);
    }
  }

  // --- 5. Sequence settings vs ingest ---
  const ss = br.seqSettings;
  if (ss) {
    const m = ingest.media;
    const resOk = ss.width === m.width && ss.height === m.height;
    if (resOk) {
      ok(`Resolution: ${ss.width}x${ss.height}`);
      logger.info(`Resolution OK: ${ss.width}x${ss.height}`);
    } else {
      warn(`Resolution: ${ss.width}x${ss.height} (expected ${m.width}x${m.height})`);
      logger.warn(`Resolution mismatch: ${ss.width}x${ss.height} vs ${m.width}x${m.height}`);
    }
    if (ss.fps > 0) {
      const fpsOk = Math.abs(ss.fps - m.fps) < 0.5;
      if (fpsOk) {
        ok(`FPS: ${ss.fps}`);
        logger.info(`FPS OK: ${ss.fps}`);
      } else {
        fail(`FPS: ${ss.fps} (expected ${m.fps})`);
        logger.error(`FPS mismatch: ${ss.fps} vs ${m.fps}`);
      }
    } else {
      warn(`FPS: unable to read (API limitation)`);
      logger.warn(`FPS: cannot verify — API does not expose frame rate getter`);
    }
  } else {
    warn(`Sequence settings: unable to read`);
    logger.warn(`Sequence settings unavailable for validation`);
  }

  // --- 6. Transcripts ---
  const boundCount = br.transcriptsImported || 0;
  if (boundCount === expectedCount) {
    ok(`Transcripts: ${boundCount}/${expectedCount} bound`);
    logger.info(`Transcripts OK: ${boundCount}/${expectedCount}`);
  } else {
    warn(`Transcripts: ${boundCount}/${expectedCount} bound`);
    logger.warn(`Transcripts: ${boundCount}/${expectedCount}`);
  }

  // --- 7. SRT ---
  if (br.srtImported) {
    const captionsName = (ingest.files && ingest.files.captions_srt)
      ? ingest.files.captions_srt.split('/').pop() : null;
    const srtName = (ingest.files && ingest.files.transcript_srt)
      ? ingest.files.transcript_srt.split('/').pop() : 'SRT';
    if (captionsName) {
      ok(`Captions SRT: ${captionsName} (word-level)`);
      ok(`Transcript SRT: ${srtName} (sentence-level)`);
      ok(`Drag "${captionsName}" from 02_Transcripts to caption track`);
    } else {
      ok(`SRT: ${srtName}`);
      ok(`Captions: drag SRT from 02_Transcripts to caption track`);
    }
    logger.info(`SRT OK: ${captionsName || srtName}`);
  } else {
    warn(`SRT: not imported`);
  }

  // --- 8. Lumetri ---
  if (br.lumetriApplied > 0) {
    ok(`Lumetri: ${br.lumetriApplied} clip(s). Select LUT in Lumetri > Creative > Look`);
    logger.info(`Lumetri OK: ${br.lumetriApplied} clips`);
  } else {
    warn(`Lumetri: not applied. Apply Lumetri Color from Effects panel`);
    logger.warn(`Lumetri not applied to clips`);
    logger.info(`To apply manually: Effects > Video Effects > Color Correction > Lumetri Color`);
    logger.info(`LUTs location: Lumetri > Creative > Look > YTAI/ (restart Premiere if not visible)`);
  }

  // Show in panel
  panel.innerHTML = lines.join('');
  panel.style.display = "block";

  if (allOk) {
    setStatus("Build verified", "ready");
  } else {
    setStatus("Build complete (warnings)", "waiting");
  }

  logger.info(`=== Validation ${allOk ? 'PASSED' : 'has WARNINGS'} ===`);
}

/**
 * Copy logs folder path to clipboard.
 * UXP shell API does not support file:// scheme, so we copy the path
 * for the user to paste into Finder (Cmd+Shift+G).
 */
async function copyLogsPath() {
  try {
    const pluginFolder = await uxpfs.getPluginFolder();
    const logsPath = pluginFolder.nativePath + 'logs';

    await navigator.clipboard.writeText(logsPath);
    logger.info(`Copied to clipboard: ${logsPath}`);
    setStatus(`Path copied! Cmd+Shift+G in Finder`, "ready");
  } catch (err) {
    // Fallback to hardcoded path
    const fallback = '/Users/romansergeev/YTAI/scripts/02_transcribe/020201_premiere_ingest/logs';
    try {
      await navigator.clipboard.writeText(fallback);
      logger.info(`Copied fallback path: ${fallback}`);
      setStatus(`Path copied! Cmd+Shift+G in Finder`, "ready");
    } catch (e2) {
      logger.error(`copyLogsPath failed: ${err.message}`);
    }
  }
}

/**
 * Debug button: auto-load test ingest + build + save logs.
 */
async function debugRun() {
  try {
    logger.clear();
    $("log-panel").innerHTML = "";
    logger.info("=== DEBUG RUN ===");
    logger.info(`Loading: ${DEBUG_INGEST_PATH}`);

    await loadIngestFromPath(DEBUG_INGEST_PATH);
    await buildTimeline();

    logger.info("=== DEBUG RUN COMPLETE ===");
  } catch (err) {
    logger.error(`Debug run failed: ${err.message}`);
    if (err.stack) logger.debug(err.stack);
    setStatus(`Debug failed: ${err.message}`, "error");

    // Save logs on failure
    await saveToProjectFolder();
  }
}

// --- Initialization ---

document.addEventListener("DOMContentLoaded", () => {
  $("btn-load-ingest").addEventListener("click", loadIngest);
  $("btn-build").addEventListener("click", buildTimeline);
  $("btn-save-log").addEventListener("click", async () => {
    await saveToProjectFolder();
  });
  $("btn-clear-log").addEventListener("click", () => {
    $("log-panel").innerHTML = "";
    logger.clear();
  });
  $("btn-debug").addEventListener("click", debugRun);
  $("btn-open-logs").addEventListener("click", copyLogsPath);

  logger.info("020201_uxp_premiere_ingest initialized");
  logger.info("Version 1.6.0");
});
