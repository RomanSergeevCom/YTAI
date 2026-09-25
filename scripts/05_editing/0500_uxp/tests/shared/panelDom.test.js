/**
 * panelDom.test.js — on(): кнопка без разметки и исключение обработчика
 * больше не пропадают молча (TICKET_uxp_audit, H и задача 2).
 */
const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');

function fakeButton() {
  return { handlers: [], addEventListener(type, fn) { this.handlers.push({ type, fn }); } };
}
let buttons;
globalThis.document = { querySelector: (sel) => buttons[sel.slice(1)] || null };
const { on, $ } = require('../../src/shared/panelDom');
const ring = () => globalThis.__ytaiErrors;
const tick = () => new Promise(r => setImmediate(r));

describe('panelDom.on()', () => {
  beforeEach(() => { buttons = { 'btn-a': fakeButton() }; globalThis.__ytaiErrors = []; });

  it('$() finds by id', () => { assert.equal($('btn-a'), buttons['btn-a']); assert.equal($('nope'), null); });

  it('binds a click handler; this and the event reach it', () => {
    let seenThis = null, seenEvt = null;
    assert.equal(on('btn-a', function (e) { seenThis = this; seenEvt = e; }), true);
    const h = buttons['btn-a'].handlers[0];
    assert.equal(h.type, 'click');
    const evt = { type: 'click' };
    h.fn.call(buttons['btn-a'], evt);
    assert.equal(seenThis, buttons['btn-a']);
    assert.equal(seenEvt, evt);
    assert.equal(ring().length, 0);
  });

  it('a missing button returns false and is reported, and does not throw', () => {
    assert.doesNotThrow(() => assert.equal(on('btn-gone', () => {}), false));
    assert.match(ring()[0].text, /binding: #btn-gone is not in index\.html/);
  });

  it('a synchronous throw lands in the ring with its stack', () => {
    on('btn-a', () => { throw new Error('sync kaboom'); });
    assert.doesNotThrow(() => buttons['btn-a'].handlers[0].fn({}));
    assert.match(ring()[0].text, /^#btn-a: sync kaboom$/);
    assert.match(ring()[0].stack, /sync kaboom/);
  });

  it('a rejected async handler lands in the ring with its stack', async () => {
    on('btn-a', async () => { throw new Error('async kaboom'); });
    buttons['btn-a'].handlers[0].fn({});
    await tick();
    assert.match(ring()[0].text, /^#btn-a: async kaboom$/);
    assert.match(ring()[0].stack, /async kaboom/);
  });

  it('a rejection with a non-Error value is still reported', async () => {
    on('btn-a', () => Promise.reject(undefined));
    buttons['btn-a'].handlers[0].fn({});
    await tick();
    assert.match(ring()[0].text, /^#btn-a: undefined$/);
  });

  it('a handler that resolves reports nothing', async () => {
    on('btn-a', async () => 'fine');
    buttons['btn-a'].handlers[0].fn({});
    await tick();
    assert.equal(ring().length, 0);
  });
});
