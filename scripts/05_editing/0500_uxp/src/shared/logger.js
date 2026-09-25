/**
 * Logger with in-memory buffer, optional UI callback, and file export support.
 * Works both in Node.js (tests) and UXP (Premiere Pro).
 *
 * In UXP, logs are saved to the plugin's own folder under logs/:
 *   <pluginFolder>/logs/debug_<project>_<timestamp>/
 * Fallback: ~/Library/Application Support/Adobe/UXP/PluginsStorage/...
 */

const { PANEL_VERSION } = require('./version');

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
  _log(level, message, err, source) {
    const entry = `[${this._timestamp()}] [${level}] ${message}`;
    this._buffer.push(entry);
    // Стек идёт в log.txt под строкой ошибки (раньше его писали отдельным
    // debug(err.stack) — и в «Err» он не попадал никогда).
    const stack = Logger.stackOf(err);
    if (stack) this._buffer.push(stack.split('\n').map(l => '    ' + l).join('\n'));
    // WARN/ERROR → кольцо кнопки «Err». Предупреждения тоже: часто именно они улика.
    if (level === 'ERROR' || level === 'WARN') {
      Logger.pushPanelError(level, message, this._pipeline, err, source || 'logger');
    }
    if (typeof this.onLog === 'function') {
      this.onLog(entry, level, message);
    }
  }

  info(message) { this._log('INFO', message); }
  /** @param {Error} [err] — со стеком: стек уйдёт в log.txt и в отчёт «Err» */
  warn(message, err) { this._log('WARN', message, err); }
  /** @param {Error} [err] — со стеком: стек уйдёт в log.txt и в отчёт «Err» */
  error(message, err) { this._log('ERROR', message, err); }
  /** Ошибка, показанная человеку в статус-строке (set*Status(…,'error')). Отличается
   *  от error() только источником: парная запись логгера о той же ошибке сольётся с ней. */
  errorShown(message, err) { this._log('ERROR', message, err, 'status'); }
  debug(message) { this._log('DEBUG', message); }

  /** Стек ошибки или '' (не Error, пустой стек, геттер бросил). */
  static stackOf(err) {
    try { return (err && typeof err.stack === 'string') ? err.stack : ''; } catch (e) { return ''; }
  }

  /**
   * ЕДИНСТВЕННЫЙ писатель кольца ошибок панели (globalThis.__ytaiErrors) —
   * кнопка «Err» копирует его человеку. Любая ошибка, которую панель
   * показывает или логирует, приходит сюда: logger.warn/error и status(…,'error')
   * всех вкладок (index.js recordPanelError).
   *
   * Запись: { line, stack }. line — «[время] [LEVEL] текст  [pipeline]»,
   * stack — стек ЭТОЙ ошибки или ''. Стек привязан к своей записи, поэтому
   * отчёт не может склеить свежую строку статуса с чужим старым стеком.
   *
   * Дедуп: парные места пишут одну ошибку дважды разным текстом —
   * logger.error('BUILD FAILED: X') и status('Build failed: X'). Среди трёх
   * последних записей ищется «та же ошибка» (Logger.sameError); нашлась — новая
   * не добавляется, а стек, если его не было, дописывается к найденной.
   * source: 'logger' (logger.warn/error) или 'status' (строка статуса, recordPanelError).
   */
  static pushPanelError(level, message, pipeline, err, source) {
    try {
      const g = (typeof globalThis !== 'undefined') ? globalThis : window;
      if (!g.__ytaiErrors) g.__ytaiErrors = [];
      const ring = g.__ytaiErrors;
      const text = String(message);
      const stack = Logger.stackOf(err);
      const pipe = String(pipeline || '').toLowerCase();
      for (let i = ring.length - 1; i >= Math.max(0, ring.length - 3); i--) {
        const r = ring[i];
        if (r && typeof r === 'object' && Logger.sameError(r, text, pipe, err, source || 'logger', i === ring.length - 1)) {
          if (stack && !r.stack) r.stack = stack;
          // The merged entry now stands for this error object too: a later,
          // DIFFERENT error object must not fold into it (review of ad2b225).
          if (err && typeof err === 'object' && !r.err) Object.defineProperty(r, 'err', { value: err });
          return;
        }
      }
      const ts = new Date().toISOString().slice(0, 19).replace('T', ' ');
      const entry = {
        line: `[${ts}] [${level}] ${text}` + (pipeline ? `  [${pipeline}]` : ''),
        text: text,
        pipeline: pipe,
        source: source || 'logger',
        stack: stack,
      };
      // Сам объект ошибки — только для дедупа по тождеству, в отчёт не идёт.
      if (err && typeof err === 'object') Object.defineProperty(entry, 'err', { value: err });
      ring.push(entry);
      while (ring.length > Logger.PANEL_RING_MAX) ring.shift();
    } catch (eG) { /* кольцо — вспомогательное; сама ошибка уже в _buffer/на экране */ }
  }

  /**
   * «Та же ошибка» — только то, что действительно одно событие:
   *   - тот же объект ошибки → да; РАЗНЫЕ объекты ошибки → нет, при любом тексте;
   *   - другой pipeline → нет;
   *   - тот же текст: пара «логгер + статус» → да (даже через запись между ними);
   *     повтор из того же источника → да, только если это непосредственно предыдущая запись;
   *   - слившаяся запись забирает объект ошибки — следующая ДРУГАЯ ошибка к ней не прилипнет;
   *   - деталь (часть после первого «: », ≥ 8 символов) совпала → да, но ТОЛЬКО
   *     между записью логгера и строкой статуса — это пара «BUILD FAILED: X» +
   *     «Build failed: X». Две записи логгера с одной деталью — разные события:
   *     '[S01] buildScene failed: Track V3 missing' и '[S02] …' обе попадают в отчёт.
   *     (Ревью 568c195: прежнее правило схлопывало сбой трёх сцен в один.)
   */
  static sameError(entry, text, pipe, err, source, isLast) {
    const errObj = err && typeof err === 'object' ? err : null;
    if (errObj && entry.err === errObj) return true;
    if (errObj && entry.err && entry.err !== errObj) return false;
    if (entry.pipeline !== pipe) return false;
    const crossSource = (entry.source || 'logger') !== source;
    // Same text: a logger + status pair is one error even with a warning in
    // between; a same-source repeat merges only with the entry right before it.
    if (entry.text === text) return !!isLast || crossSource;
    if (!crossSource) return false;
    const detail = (t) => { const i = t.indexOf(': '); return i >= 0 ? t.slice(i + 2) : ''; };
    const dNew = detail(text), dOld = detail(entry.text);
    return (dNew.length >= 8 && entry.text.endsWith(dNew)) || (dOld.length >= 8 && text.endsWith(dOld));
  }

  /**
   * Текст отчёта кнопки «Err»: заголовок + ВСЕ записи кольца, стек — сразу
   * под своей записью. Чистая функция, тестируется без UXP.
   */
  static formatPanelReport(ring, header) {
    const entries = ring || [];
    const out = (header || []).slice();
    out.push('--- errors / warnings this session (' + entries.length + ') ---');
    if (!entries.length) out.push('(no errors captured this session)');
    for (const r of entries) {
      if (typeof r === 'string') { out.push(r); continue; }
      out.push(r.line);
      if (r.stack) out.push(r.stack.split('\n').map(l => '    ' + l).join('\n'));
    }
    return out.join('\n');
  }

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
      `Version: ${PANEL_VERSION}`,
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
      pluginVersion: PANEL_VERSION,
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
   * Get the logs folder — writes to project's 00_Setup/pipeline/logs/.
   * Falls back to plugin folder, then UXP data folder.
   * @returns {Object} UXP folder entry for logs/
   */
  async _getLogsFolder() {
    const uxp = require('uxp');
    const fs = uxp.storage.localFileSystem;

    // Primary: project's 99_Pipeline/logs/
    if (this._sourceFolderPath) {
      const projectLogsPath = this._sourceFolderPath + '/99_Pipeline/logs';
      try {
        const logsFolder = await fs.getEntryWithUrl('file://' + projectLogsPath);
        this._log('DEBUG', `Using project logs folder: ${projectLogsPath}`);
        return logsFolder;
      } catch (e) {
        // Try creating it
        try {
          const pipelinePath = this._sourceFolderPath + '/99_Pipeline';
          const pipelineFolder = await fs.getEntryWithUrl('file://' + pipelinePath);
          const logsFolder = await pipelineFolder.createFolder('logs');
          this._log('DEBUG', `Created project logs folder: ${projectLogsPath}`);
          return logsFolder;
        } catch (e2) {
          this._log('DEBUG', `Cannot create project logs: ${e2.message}`);
        }
      }
    }

    // Fallback: plugin folder logs/
    try {
      const pluginFolder = await fs.getPluginFolder();
      const pluginPath = pluginFolder.nativePath;

      if (pluginPath) {
        const sep = pluginPath.includes('\\') ? '\\' : '/';
        const logsPath = pluginPath.endsWith(sep)
          ? pluginPath + 'logs'
          : pluginPath + sep + 'logs';

        try {
          const logsFolder = await fs.getEntryWithUrl('file://' + logsPath);
          return logsFolder;
        } catch (e) {
          try {
            const writableParent = await fs.getEntryWithUrl('file://' + pluginPath);
            const logsFolder = await writableParent.createFolder('logs');
            return logsFolder;
          } catch (e2) {
            this._log('WARN', `Cannot create plugin logs/: ${e2.message}`);
          }
        }
      }
    } catch (e) {
      this._log('WARN', `Plugin folder access failed: ${e.message}`);
    }

    // Last fallback: UXP data folder
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
   * Get the logs folder path: {project}/00_Setup/pipeline/logs/
   * Used by "copy path" button in UI.
   * @returns {string|null}
   */
  getLogsFolderPath() {
    if (this._sourceFolderPath) {
      return `${this._sourceFolderPath}/99_Pipeline/logs`;
    }
    return null;
  }
}

// 60: отчёт копирует кольцо целиком, а парные места теперь не удваивают записи.
Logger.PANEL_RING_MAX = 60;

module.exports = { Logger };
