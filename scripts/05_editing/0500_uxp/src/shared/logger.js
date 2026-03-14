/**
 * Logger with in-memory buffer, optional UI callback, and file export support.
 * Works both in Node.js (tests) and UXP (Premiere Pro).
 *
 * In UXP, logs are saved to the plugin's own folder under logs/:
 *   <pluginFolder>/logs/debug_<project>_<timestamp>/
 * Fallback: ~/Library/Application Support/Adobe/UXP/PluginsStorage/...
 */

class Logger {
  /**
   * @param {string} pipeline - Pipeline identifier: 'INGEST', 'ASSEMBLY', or '' (generic)
   */
  constructor(pipeline = '') {
    this._buffer = [];
    this._pipeline = pipeline;
    this._projectName = '';
    this._projectPath = '';
    this._ingestPath = '';
    this._briefPath = '';
    this._sourceFolderPath = '';
    this._lastSavedPath = '';
    this.onLog = null; // callback: (formattedEntry: string, level: string, message: string) => void
  }

  /**
   * Set project info for log report header.
   */
  setProjectInfo(name, path) {
    this._projectName = name || '';
    this._projectPath = path || '';
  }

  /**
   * Set ingest/source info for log report header.
   */
  setIngestInfo(ingestPath, sourceFolderPath) {
    this._ingestPath = ingestPath || '';
    this._sourceFolderPath = sourceFolderPath || '';
  }

  /**
   * Set brief info for assembly log report header.
   */
  setBriefInfo(briefPath, projectName) {
    this._briefPath = briefPath || '';
    if (projectName) this._projectName = projectName;
  }

  /**
   * Get current timestamp string.
   */
  _timestamp() {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  }

  /**
   * Get timestamp suitable for filenames (no colons or spaces).
   */
  _fileTimestamp() {
    return new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  }

  /**
   * Internal log method.
   */
  _log(level, message) {
    const entry = `[${this._timestamp()}] [${level}] ${message}`;
    this._buffer.push(entry);
    if (typeof this.onLog === 'function') {
      this.onLog(entry, level, message);
    }
  }

  info(message) { this._log('INFO', message); }
  warn(message) { this._log('WARN', message); }
  error(message) { this._log('ERROR', message); }
  debug(message) { this._log('DEBUG', message); }

  /**
   * Get all log entries as array.
   */
  getBuffer() {
    return [...this._buffer];
  }

  /**
   * Clear the log buffer.
   */
  clear() {
    this._buffer = [];
  }

  /**
   * Generate a full text report with header and all log entries.
   */
  getReport() {
    const pipelineLabel = this._pipeline ? ` ${this._pipeline}` : '';
    const header = [
      `=== YTAI${pipelineLabel} — Log ===`,
      `Version: 1.9.3`,
      `Pipeline: ${this._pipeline || 'generic'}`,
      `Project: ${this._projectName || 'N/A'}`,
      `Project Path: ${this._projectPath || 'N/A'}`,
    ];
    if (this._ingestPath) header.push(`Ingest Path: ${this._ingestPath}`);
    if (this._briefPath) header.push(`Brief Path: ${this._briefPath}`);
    if (this._sourceFolderPath) header.push(`Source Folder: ${this._sourceFolderPath}`);
    header.push(
      `Report Generated: ${this._timestamp()}`,
      `Total Entries: ${this._buffer.length}`,
      '--------------------------------------'
    );
    return [...header, ...this._buffer].join('\n');
  }

  /**
   * Generate a JSON debug snapshot with all state for troubleshooting.
   */
  getDebugSnapshot(pipelineData, extras) {
    const snapshot = {
      timestamp: this._timestamp(),
      pluginVersion: '1.9.3',
      pipeline: this._pipeline || 'generic',
      projectName: this._projectName,
      projectPath: this._projectPath,
      ingestPath: this._ingestPath,
      briefPath: this._briefPath,
      sourceFolderPath: this._sourceFolderPath,
      logsFolderPath: this.getLogsFolderPath(),
      pipelineData: pipelineData || null,
      logEntries: this._buffer,
      entryCount: this._buffer.length
    };

    // Merge extras (sequence settings, track counts, timing, etc.)
    if (extras && typeof extras === 'object') {
      snapshot.extras = extras;
    }

    // Try to get UXP/OS info
    try {
      const uxp = require('uxp');
      snapshot.uxpVersion = uxp.versions ? uxp.versions.uxp : 'unknown';
      snapshot.platform = uxp.host ? `${uxp.host.name} ${uxp.host.version}` : 'unknown';
    } catch (e) {
      // Not in UXP environment
    }

    return JSON.stringify(snapshot, null, 2);
  }

  /**
   * Get the logs folder — uses plugin folder's nativePath with getEntryWithUrl
   * for write access (requires localFileSystem: "fullAccess").
   * Falls back to data folder if plugin folder approach fails.
   * @returns {Object} UXP folder entry for logs/
   */
  async _getLogsFolder() {
    const uxp = require('uxp');
    const fs = uxp.storage.localFileSystem;

    try {
      const pluginFolder = await fs.getPluginFolder();
      const pluginPath = pluginFolder.nativePath;
      this._log('DEBUG', `Plugin folder nativePath: ${pluginPath}`);

      if (pluginPath) {
        const sep = pluginPath.includes('\\') ? '\\' : '/';
        const logsPath = pluginPath.endsWith(sep)
          ? pluginPath + 'logs'
          : pluginPath + sep + 'logs';

        // Try 1: Access existing logs/ folder via absolute path
        try {
          const logsFolder = await fs.getEntryWithUrl('file://' + logsPath);
          this._log('DEBUG', `Found logs folder: ${logsPath}`);
          return logsFolder;
        } catch (e) {
          this._log('DEBUG', `logs/ not found at ${logsPath}, creating...`);
        }

        // Try 2: Get plugin folder via getEntryWithUrl (writable) and create logs/
        try {
          const writableParent = await fs.getEntryWithUrl('file://' + pluginPath);
          const logsFolder = await writableParent.createFolder('logs');
          this._log('DEBUG', `Created logs folder at: ${logsPath}`);
          return logsFolder;
        } catch (e) {
          this._log('WARN', `Cannot create logs/ via getEntryWithUrl: ${e.message}`);
        }

        // Try 3: Create via plugin folder directly (may work in dev mode)
        try {
          const logsFolder = await pluginFolder.createFolder('logs');
          return logsFolder;
        } catch (e) {
          this._log('WARN', `Plugin folder createFolder failed: ${e.message}`);
        }
      }
    } catch (e) {
      this._log('WARN', `Plugin folder access failed: ${e.message}`);
    }

    // Fallback: data folder (always writable, UXP sandbox)
    const dataFolder = await fs.getDataFolder();
    this._log('WARN', `Using data folder fallback: ${dataFolder.nativePath || 'unknown'}`);
    return dataFolder;
  }

  /**
   * Save log report + debug snapshot to plugin's logs/ folder.
   * Creates a timestamped subfolder: logs/debug_<project>_<timestamp>/
   *   |- log.txt           — human-readable log
   *   |- debug_snapshot.json — full state for debugging
   *   |- ingest_copy.json   — copy of the loaded ingest (if provided)
   *
   * @param {Object|null} pipelineData - The loaded pipeline data (ingest or brief) to include
   * @param {string|null} projectPath - Path to .prproj file to copy into bundle
   * @param {Object|null} extras - Additional data for debug snapshot (clipMap, segmentOrder, etc.)
   * @returns {{ folderPath: string, logFile: string } | null}
   */
  async saveDebugBundle(pipelineData, projectPath, extras) {
    try {
      const logsFolder = await this._getLogsFolder();

      // Create timestamped subfolder: {project}_{PIPELINE}_debug_{ts}/
      const ts = this._fileTimestamp();
      const projectSlug = (this._projectName || 'unknown').replace(/[^a-zA-Z0-9_-]/g, '_');
      const pipelineTag = this._pipeline ? `_${this._pipeline}` : '';
      const debugFolderName = `${projectSlug}${pipelineTag}_debug_${ts}`;

      const debugFolder = await logsFolder.createFolder(debugFolderName);

      // 1. Save log.txt
      const logFile = await debugFolder.createFile('log.txt', { overwrite: true });
      await logFile.write(this.getReport());

      // 2. Save debug_snapshot.json (with extras if provided)
      const snapshotFile = await debugFolder.createFile('debug_snapshot.json', { overwrite: true });
      await snapshotFile.write(this.getDebugSnapshot(pipelineData, extras));

      // 3. Save pipeline data copy (ingest or brief)
      if (pipelineData) {
        const dataLabel = (this._pipeline === 'ASSEMBLY' || this._pipeline === 'REVIEW' || this._pipeline === 'SCREENS') ? 'brief_copy' : 'ingest_copy';
        const dataFile = await debugFolder.createFile(dataLabel + '.json', { overwrite: true });
        await dataFile.write(JSON.stringify(pipelineData, null, 2));
      }

      // 4. Copy .prproj file (if project path provided)
      if (projectPath) {
        try {
          const uxp = require('uxp');
          const fs = uxp.storage.localFileSystem;
          const projectEntry = await fs.getEntryWithUrl('file://' + projectPath);
          await projectEntry.copyTo(debugFolder, { overwrite: true });
          this._log('INFO', `Project file copied to debug bundle: ${projectEntry.name}`);
        } catch (copyErr) {
          this._log('WARN', `Could not copy .prproj to debug bundle: ${copyErr.message}`);
        }
      }

      const savedPath = debugFolder.nativePath || debugFolderName;
      this._lastSavedPath = savedPath;
      this.info(`Debug bundle saved to: ${savedPath}`);

      // Log rotation: keep only last 20 debug bundles, delete older ones
      try {
        await this._rotateDebugBundles(logsFolder, 20);
      } catch (rotateErr) {
        this._log('DEBUG', `Log rotation skipped: ${rotateErr.message}`);
      }

      return { folderPath: savedPath, logFile: 'log.txt' };
    } catch (e) {
      // In test environment or if UXP APIs unavailable
      this.error(`Failed to save debug bundle: ${e.message}`);
      return null;
    }
  }

  /**
   * Rotate debug bundles — keep only the newest `keep` folders, delete the rest.
   * Folders are sorted by name (which contains timestamp) so alphabetical = chronological.
   *
   * @param {Object} logsFolder - UXP folder entry for logs/
   * @param {number} keep - Number of bundles to keep (default 20)
   */
  async _rotateDebugBundles(logsFolder, keep) {
    const entries = await logsFolder.getEntries();
    // Only consider debug bundle folders (contain "_debug_" in name)
    const debugFolders = entries
      .filter(e => e.isFolder && e.name.includes('_debug_'))
      .sort((a, b) => a.name.localeCompare(b.name));

    if (debugFolders.length <= keep) return;

    const toDelete = debugFolders.slice(0, debugFolders.length - keep);
    let deleted = 0;
    for (const folder of toDelete) {
      try {
        // Delete folder and all its contents
        await folder.delete({ recursive: true });
        deleted++;
      } catch (e) {
        this._log('DEBUG', `Cannot delete old bundle ${folder.name}: ${e.message}`);
      }
    }
    if (deleted > 0) {
      this._log('INFO', `Log rotation: deleted ${deleted} old bundle(s), kept ${keep}`);
    }
  }

  /**
   * Save just the log file to plugin's logs/ folder.
   * @returns {string|null} Saved file path or null on failure
   */
  async saveLogToDataFolder() {
    try {
      const logsFolder = await this._getLogsFolder();

      const ts = this._fileTimestamp();
      const projectSlug = (this._projectName || 'session').replace(/[^a-zA-Z0-9_-]/g, '_');
      const pipelineTag = this._pipeline ? `_${this._pipeline}` : '';
      const filename = `${projectSlug}${pipelineTag}_${ts}.log`;

      const file = await logsFolder.createFile(filename, { overwrite: true });
      await file.write(this.getReport());

      const savedPath = file.nativePath || filename;
      this._lastSavedPath = savedPath;
      this.info(`Log saved to: ${savedPath}`);
      return savedPath;
    } catch (e) {
      this.error(`Failed to save log: ${e.message}`);
      return null;
    }
  }

  /**
   * Get the path where logs were last saved.
   */
  getLastSavedPath() {
    return this._lastSavedPath;
  }

  /**
   * Get the logs folder path: {source_folder}/{project_name}_transcription
   * Used by "Open Logs" button.
   * @returns {string|null}
   */
  getLogsFolderPath() {
    if (this._sourceFolderPath && this._projectName) {
      return `${this._sourceFolderPath}/${this._projectName}_transcription`;
    }
    return null;
  }
}

module.exports = { Logger };
