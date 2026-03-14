/**
 * Logger with in-memory buffer, optional UI callback, and file export support.
 * Works both in Node.js (tests) and UXP (Premiere Pro).
 *
 * In UXP, logs are saved to the plugin's own folder under logs/:
 *   <pluginFolder>/logs/debug_<project>_<timestamp>/
 * Fallback: ~/Library/Application Support/Adobe/UXP/PluginsStorage/...
 */

class Logger {
  constructor() {
    this._buffer = [];
    this._projectName = '';
    this._projectPath = '';
    this._ingestPath = '';
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
    const header = [
      '=== YTAI Ingest — Log ===',
      `Project: ${this._projectName || 'N/A'}`,
      `Project Path: ${this._projectPath || 'N/A'}`,
      `Ingest Path: ${this._ingestPath || 'N/A'}`,
      `Source Folder: ${this._sourceFolderPath || 'N/A'}`,
      `Report Generated: ${this._timestamp()}`,
      `Total Entries: ${this._buffer.length}`,
      '--------------------------------------'
    ];
    return [...header, ...this._buffer].join('\n');
  }

  /**
   * Generate a JSON debug snapshot with all state for troubleshooting.
   */
  getDebugSnapshot(ingestData, extras) {
    const snapshot = {
      timestamp: this._timestamp(),
      pluginVersion: '1.6.0',
      projectName: this._projectName,
      projectPath: this._projectPath,
      ingestPath: this._ingestPath,
      sourceFolderPath: this._sourceFolderPath,
      logsFolderPath: this.getLogsFolderPath(),
      ingestData: ingestData || null,
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
   * @param {Object|null} ingestData - The loaded ingest data to include in snapshot
   * @param {string|null} projectPath - Path to .prproj file to copy into bundle
   * @returns {{ folderPath: string, logFile: string } | null}
   */
  async saveDebugBundle(ingestData, projectPath) {
    try {
      const logsFolder = await this._getLogsFolder();

      // Create timestamped subfolder for this debug session
      const ts = this._fileTimestamp();
      const projectSlug = (this._projectName || 'unknown').replace(/[^a-zA-Z0-9_-]/g, '_');
      const debugFolderName = `debug_${projectSlug}_${ts}`;

      const debugFolder = await logsFolder.createFolder(debugFolderName);

      // 1. Save log.txt
      const logFile = await debugFolder.createFile('log.txt', { overwrite: true });
      await logFile.write(this.getReport());

      // 2. Save debug_snapshot.json
      const snapshotFile = await debugFolder.createFile('debug_snapshot.json', { overwrite: true });
      await snapshotFile.write(this.getDebugSnapshot(ingestData));

      // 3. Save ingest_copy.json (if ingest data available)
      if (ingestData) {
        const ingestFile = await debugFolder.createFile('ingest_copy.json', { overwrite: true });
        await ingestFile.write(JSON.stringify(ingestData, null, 2));
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

      return { folderPath: savedPath, logFile: 'log.txt' };
    } catch (e) {
      // In test environment or if UXP APIs unavailable
      this.error(`Failed to save debug bundle: ${e.message}`);
      return null;
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
      const filename = `log_${projectSlug}_${ts}.txt`;

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
   * Get the logs folder path: v3.0 → {source_folder}/01_Media/Source/Setup/logs
   * Used by "Open Logs" / "Copy Logs Path" button.
   * @returns {string|null}
   */
  getLogsFolderPath() {
    if (this._sourceFolderPath && this._projectName) {
      // v3.0 structure
      const v3path = `${this._sourceFolderPath}/01_Media/Source/Setup/logs`;
      return v3path;
    }
    return null;
  }
}

module.exports = { Logger };
