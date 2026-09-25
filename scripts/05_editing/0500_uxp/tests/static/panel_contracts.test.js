/**
 * panel_contracts.test.js — статические контракты панели, которые без Premiere
 * иначе держатся на честном слове. Читают index.js / index.html / src как текст.
 *
 * Сюда добавляются новые инварианты по мере аудита (тикет TICKET_uxp_audit.md).
 * ⚠️ Только regex-литералы: строка-фикстура вида «v1.2.3» сама попадёт под
 * lint-правило версии.
 */
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

function jsFiles(dir) {
  const out = [];
  for (const ent of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
    const rel = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...jsFiles(rel));
    else if (ent.name.endsWith('.js')) out.push(rel);
  }
  return out;
}
const PANEL_CODE = ['index.js', ...jsFiles('src')];

describe('panel contracts — one version', () => {
  it('PANEL_VERSION is assigned a literal exactly once, in src/shared/version.js', () => {
    const hits = [];
    for (const rel of PANEL_CODE) {
      const m = read(rel).match(/PANEL_VERSION\s*[:=]\s*['"]\d+\.\d+\.\d+['"]/g);
      if (m) hits.push(...m.map(() => rel));
    }
    assert.deepEqual(hits, [path.join('src', 'shared', 'version.js')]);
  });

  it('version.js holds a semver string', () => {
    const { PANEL_VERSION } = require('../../src/shared/version');
    assert.match(PANEL_VERSION, /^\d+\.\d+\.\d+$/);
  });

  it('index.html carries no version literal (the header is filled from code)', () => {
    assert.doesNotMatch(read('index.html'), /v\d+\.\d+\.\d+/);
  });

  it('logger.js has no hardcoded semver (log.txt header and debug snapshot)', () => {
    const code = read('src/shared/logger.js').replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, '');
    assert.doesNotMatch(code, /['"`][^'"`\n]*\b\d+\.\d+\.\d+\b[^'"`\n]*['"`]/);
  });

  it('the logger reports the panel version', () => {
    const { Logger } = require('../../src/shared/logger');
    const { PANEL_VERSION } = require('../../src/shared/version');
    const log = new Logger('TEST');
    assert.ok(log.getReport().includes('Version: ' + PANEL_VERSION));
    const snap = log.getDebugSnapshot({}, {});
    assert.equal((typeof snap === 'string' ? JSON.parse(snap) : snap).pluginVersion, PANEL_VERSION);
  });
});
