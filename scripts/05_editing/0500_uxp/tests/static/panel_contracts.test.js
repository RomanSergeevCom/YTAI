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

describe('panel contracts — every on-screen error reaches «Err»', () => {
  const src = read('index.js');

  it('every set*Status setter forwards type=error to the logger / ring', () => {
    const re = /^function (set\w+Status)\(([^)]*)\) \{\n([\s\S]*?)^\}$/gm;
    const setters = [...src.matchAll(re)];
    assert.ok(setters.length >= 11, 'found ' + setters.length + ' setters');
    for (const [, name, params, body] of setters) {
      assert.match(params, /\berr\b/, name + ' takes err as its third argument');
      assert.match(body, /if \(type === 'error'\) (\w+Logger\.errorShown|recordPanelError)\(text, [^)]*err\)/,
        name + ' routes errors with their stack');
    }
  });

  it('recordPanelError writes through the logger (one writer of the ring)', () => {
    const body = src.match(/^function recordPanelError\([^)]*\) \{\n([\s\S]*?)^\}$/m)[1];
    assert.match(body, /Logger\.pushPanelError\(/);
    assert.doesNotMatch(src.replace(/\/\/.*$/gm, ''), /__ytaiErrors\s*(\.push|=\s*\[)/, 'nobody else pushes into the ring');
  });

  it('catch handlers in the binding block pass the error on (stack survives)', () => {
    const block = src.slice(src.indexOf("document.addEventListener('DOMContentLoaded'"));
    const bad = [...block.matchAll(/\.catch\(function \((\w+)\) \{[^}]*?set\w+Status\([^;]*?'error'(?:, (\w+))?\);/g)]
      .filter(m => m[2] !== m[1]).map(m => m[0].slice(0, 90));
    assert.deepEqual(bad, []);
  });
});

describe('panel contracts — bindings', () => {
  const src = read('index.js');
  const html = read('index.html');
  const htmlIds = [...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]);
  // Elements the code creates at runtime (not in index.html). Keep empty unless proven.
  const DYNAMIC_IDS = new Set([]);

  it('no bare $("id").addEventListener — buttons bind only through on()', () => {
    assert.deepEqual(src.match(/\$\('[^']+'\)\.addEventListener\(/g) || [], []);
  });

  it('index.html has no duplicate ids', () => {
    const seen = new Set(), dup = [];
    for (const id of htmlIds) { if (seen.has(id)) dup.push(id); seen.add(id); }
    assert.deepEqual(dup, []);
  });

  it('every id the code references by literal exists in index.html', () => {
    const refs = new Set();
    for (const re of [/\bon\('([^']+)'/g, /\$\('([^']+)'\)/g, /getElementById\('([^']+)'\)/g]) {
      for (const m of src.matchAll(re)) refs.add(m[1]);
    }
    const missing = [...refs].filter(id => !htmlIds.includes(id) && !DYNAMIC_IDS.has(id)).sort();
    assert.deepEqual(missing, [], 'referenced but not in index.html');
  });

  it('removing a button from index.html means removing its on() in the same commit', () => {
    const bound = [...src.matchAll(/\bon\('([^']+)'/g)].map(m => m[1]);
    assert.ok(bound.length >= 90, 'bindings found: ' + bound.length);
    assert.deepEqual(bound.filter(id => !htmlIds.includes(id)), []);
  });
});

describe('panel contracts — readback stops the build (task 5)', () => {
  const src = read('index.js');
  const start = src.indexOf('async function buildIngest(');
  const body = src.slice(start, src.indexOf('\n}\n', start));

  it('buildIngest fails on result.ok === false BEFORE «complete», btn-done and «Build verified»', () => {
    const iVerdict = body.indexOf('if (result.ok === false)');
    const iThrow = body.indexOf('if (readbackFailure) throw');
    assert.ok(iVerdict > 0 && iThrow > iVerdict, 'verdict read, then thrown');
    for (const later of ["'=== INGEST BUILD COMPLETE", "classList.add('btn-done')", "'Build verified'"]) {
      const i = body.indexOf(later);
      assert.ok(i > iThrow, later + ' comes after the readback throw');
    }
  });

  it('the scene list is refreshed after the catch, so a failed scene gets its badge', () => {
    const iCatch = body.lastIndexOf('} catch (err) {');
    assert.ok(body.indexOf('renderIngestSceneList(', iCatch) > iCatch);
    assert.ok(read('index.js').includes("'readback ✗'") || read('index.js').includes('readback ✗'));
  });
});

describe('panel contracts — one verified parameter write (task 4)', () => {
  it('createSetValueAction is called only in src/adjust/paramWrite.js', () => {
    const offenders = PANEL_CODE.filter(rel => rel !== path.join('src', 'adjust', 'paramWrite.js'))
      .filter(rel => /\.createSetValueAction\(/.test(read(rel).replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, '')));
    assert.deepEqual(offenders, [], 'write a param through writeParamVerified — it reads back and knows float32');
  });

  it('no strict-equality readback survives in the adjust code', () => {
    assert.doesNotMatch(read('src/adjust/adjustmentBuilder.js'), /postInner === paramValue/);
  });
});

describe('panel contracts — English UI (Roman 25.09: all button and function names in English)', () => {
  const CY = /[А-Яа-яЁё]/;

  it('index.html: no Cyrillic in anything visible (labels, titles, info text)', () => {
    const html = read('index.html')
      .replace(/<!--[\s\S]*?-->/g, '').replace(/<style[\s\S]*?<\/style>/g, '');
    const bad = html.split('\n').filter(l => CY.test(l)).map(l => l.trim().slice(0, 100));
    assert.deepEqual(bad, []);
  });

  it('index.js: no Cyrillic string reaches a status line, panel text or tooltip', () => {
    const acorn = require('acorn');
    const src = read('index.js');
    const ast = acorn.parse(src, { ecmaVersion: 2022, sourceType: 'script', locations: true });
    const each = (n, fn) => { if (!n || typeof n.type !== 'string') return; fn(n);
      for (const k of Object.keys(n)) { const c = n[k];
        if (Array.isArray(c)) c.forEach(x => each(x, fn)); else if (c && typeof c.type === 'string') each(c, fn); } };
    const cyr = (n) => { const out = []; each(n, m => {
      if (m.type === 'Literal' && typeof m.value === 'string' && CY.test(m.value)) out.push(m.loc.start.line + ': ' + m.value);
      if (m.type === 'TemplateElement' && CY.test(m.value.raw)) out.push(m.loc.start.line + ': ' + m.value.raw); }); return out; };
    const bad = [];
    each(ast, fnNode => {
      if (!/Function/.test(fnNode.type)) return;
      const assigns = {};
      each(fnNode.body, m => {
        if (m.type === 'VariableDeclarator' && m.id.type === 'Identifier' && m.init) (assigns[m.id.name] = assigns[m.id.name] || []).push(m.init);
        if (m.type === 'AssignmentExpression' && m.left.type === 'Identifier') (assigns[m.left.name] = assigns[m.left.name] || []).push(m.right);
      });
      each(fnNode.body, n => {
        let sink = null;
        if (n.type === 'CallExpression' && n.callee.type === 'Identifier' && /^set\w+(Status|Progress|Validation)$/.test(n.callee.name)) sink = n.arguments[0];
        if (n.type === 'AssignmentExpression' && n.left.type === 'MemberExpression' && n.left.property
          && /^(textContent|innerHTML|innerText|title|placeholder)$/.test(n.left.property.name)) sink = n.right;
        if (!sink) return;
        bad.push(...cyr(sink));
        each(sink, m => { if (m.type === 'Identifier') for (const rhs of (assigns[m.name] || [])) bad.push(...cyr(rhs)); });
      });
    });
    assert.deepEqual([...new Set(bad)], []);
  });

  it('no Cyrillic in thrown error messages (they end up in status lines)', () => {
    const bad = PANEL_CODE.flatMap(rel => read(rel).split('\n')
      .map((l, i) => (/throw new Error\(/.test(l) && CY.test(l.replace(/\/\/.*$/, ''))) ? rel + ':' + (i + 1) : null)
      .filter(Boolean));
    assert.deepEqual(bad, []);
  });
});
