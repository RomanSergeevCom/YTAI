/**
 * logger.test.js — кольцо ошибок кнопки «Err» (TICKET_uxp_audit, задача 2):
 * у ошибки один источник истины — логгер; стек привязан к своей записи.
 */
const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const { Logger } = require('../../src/shared/logger');

const ring = () => globalThis.__ytaiErrors;
function boom(msg) { try { throw new Error(msg); } catch (e) { return e; } }

describe('Logger — panel error ring', () => {
  beforeEach(() => { globalThis.__ytaiErrors = []; });

  it('warn and error reach the ring; info and debug do not', () => {
    const log = new Logger('INGEST');
    log.info('i'); log.debug('d'); log.warn('w1'); log.error('e1');
    assert.deepEqual(ring().map(r => r.text), ['w1', 'e1']);
    assert.match(ring()[1].line, /\[ERROR\] e1  \[INGEST\]$/);
  });

  it('error(msg, err) stores the stack on that entry and in log.txt', () => {
    const log = new Logger('INGEST');
    log.error('build failed: kaboom', boom('kaboom'));
    assert.match(ring()[0].stack, /Error: kaboom\n\s+at /);
    assert.match(log.getReport(), /\[ERROR\] build failed: kaboom\n {4}Error: kaboom/);
  });

  it('paired sites (logger + status line, same error tail) make ONE entry', () => {
    const log = new Logger('INGEST');
    const err = boom('Track V3 missing on scene 04');
    log.error('INGEST BUILD FAILED: ' + err.message);          // the old paired form: no err
    log.errorShown('Build failed: ' + err.message, err);       // what setIngestStatus(…,'error', err) does
    assert.equal(ring().length, 1);
    assert.match(ring()[0].stack, /Track V3 missing/, 'stack from the second write is attached');
  });

  it('the same error object is one entry even across pipelines (on() wrapper + tab logger)', () => {
    const err = boom('x');
    Logger.pushPanelError('ERROR', 'Assembly: x', 'assembly', err);
    Logger.pushPanelError('ERROR', '#btn-build: x', 'panel', err);
    assert.equal(ring().length, 1);
  });

  it('different errors with the same detail in different pipelines stay separate', () => {
    Logger.pushPanelError('ERROR', 'Export failed: No active sequence', 'assembly');
    Logger.pushPanelError('ERROR', 'Build failed: No active sequence', 'review');
    assert.equal(ring().length, 2);
  });

  it('an exact repeat merges only with the entry right before it', () => {
    Logger.pushPanelError('ERROR', 'Load ingest first', 'ingest');
    Logger.pushPanelError('ERROR', 'Load ingest first', 'ingest');
    Logger.pushPanelError('ERROR', 'Load brief first', 'ingest');
    Logger.pushPanelError('ERROR', 'Load ingest first', 'ingest');
    assert.deepEqual(ring().map(r => r.text), ['Load ingest first', 'Load brief first', 'Load ingest first']);
  });

  it('three scenes failing with the same message are three entries (review of 568c195)', () => {
    const log = new Logger('INGEST');
    for (const sc of ['S01', 'S02', 'S03']) log.error('[' + sc + '] buildScene failed: Track V3 missing', boom('Track V3 missing'));
    assert.equal(ring().length, 3);
    for (const sc of ['S01', 'S02', 'S03']) log.warn(sc + ' A1 clip 3: would go negative, skipping');
    assert.equal(ring().length, 6, 'per-clip warnings with one detail are not merged either');
  });

  it('different error objects never merge, even with identical text', () => {
    Logger.pushPanelError('ERROR', 'x failed: same', 'a', boom('same'));
    Logger.pushPanelError('ERROR', 'x failed: same', 'a', boom('same'));
    assert.equal(ring().length, 2);
  });

  it('dedup looks only three entries back — an old identical error is logged again', () => {
    for (const t of ['same', 'a', 'b', 'c', 'same']) Logger.pushPanelError('ERROR', t, 'x');
    assert.deepEqual(ring().map(r => r.text), ['same', 'a', 'b', 'c', 'same']);
  });

  it('ring keeps the last PANEL_RING_MAX entries', () => {
    for (let i = 0; i < Logger.PANEL_RING_MAX + 5; i++) Logger.pushPanelError('WARN', 'w' + i + ' '.repeat(i % 3), 'x');
    assert.equal(ring().length, Logger.PANEL_RING_MAX);
    assert.equal(ring()[0].text.trim(), 'w5');
  });

  it('a non-Error throwable (undefined, string) never breaks the logger', () => {
    const log = new Logger('X');
    assert.doesNotThrow(() => { log.error('rejected with undefined', undefined); log.error('string', 'oops'); });
    assert.equal(ring().length, 2);
    assert.equal(ring()[0].stack, '');
  });
});

describe('Logger.formatPanelReport — the text the «Err» button copies', () => {
  beforeEach(() => { globalThis.__ytaiErrors = []; });

  it('prints every entry, each stack right under ITS entry', () => {
    Logger.pushPanelError('ERROR', 'first', 'a', boom('first'));
    Logger.pushPanelError('WARN', 'second (no stack)', 'b');
    const text = Logger.formatPanelReport(ring(), ['=== header ===']);
    const lines = text.split('\n');
    assert.equal(lines[0], '=== header ===');
    assert.match(lines[1], /errors \/ warnings this session \(2\)/);
    const iFirst = lines.findIndex(l => /\] first  \[a\]$/.test(l));
    const iSecond = lines.findIndex(l => /second \(no stack\)/.test(l));
    assert.match(lines[iFirst + 1], /^ {4}Error: first$/);
    assert.ok(lines.slice(iFirst + 1, iSecond).every(l => l.startsWith('    ')), 'stack sits between its entry and the next');
    assert.equal(iSecond, lines.length - 1, 'the stackless entry gets no stack');
  });

  it('empty ring says so', () => {
    assert.match(Logger.formatPanelReport([], []), /no errors captured this session/);
  });
});
