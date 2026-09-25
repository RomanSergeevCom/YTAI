/**
 * paramWrite.test.js — the one verified parameter write (TICKET_uxp_audit, D/E).
 */
const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const ppro = require('../mocks/premierepro');
const { writeParamVerified, sameValue, unwrapKf, EPS } = require('../../src/adjust/paramWrite');

describe('paramWrite.sameValue', () => {
  it('numbers within float32 tolerance', () => {
    assert.equal(sameValue(1.2, Math.fround(1.2)), true);
    assert.equal(sameValue(1.2, 1.2 + 2 * EPS), false);
  });
  it('points and arrays coordinate-wise', () => {
    assert.equal(sameValue({ x: 0.58, y: 0.5 }, { x: Math.fround(0.58), y: 0.5 }), true);
    assert.equal(sameValue({ x: 0.58, y: 0.5 }, { x: 0.5, y: 0.5 }), false);
    assert.equal(sameValue([0.58, 0.5], [Math.fround(0.58), 0.5]), true);
    assert.equal(sameValue([0.58], { 0: 0.58 }), false);
  });
  it('opaque objects fall back to identity', () => {
    const o = Object.create({});
    assert.equal(sameValue(o, o), true);
    assert.equal(sameValue(o, Object.create({})), false);
  });
  it('unwrapKf reads nested and flat keyframe values', () => {
    assert.equal(unwrapKf({ value: { value: 3 } }), 3);
    assert.equal(unwrapKf({ value: 'x' }), 'x');
    assert.equal(unwrapKf(null), undefined);
  });
});

describe('paramWrite.writeParamVerified', () => {
  let project;
  beforeEach(() => { ppro._recorder.reset(); project = new ppro._MockProject('P'); });

  it('a point value (Motion.Position) is written and read back', async () => {
    const pos = new ppro._MockComponentParam('Position', { x: 0.5, y: 0.5 });
    const r = await writeParamVerified(project, pos, { x: 0.58, y: 0.5 }, 'Motion.Position', null);
    assert.equal(r.ok, true);
    assert.equal(r.path, 'createKeyframe');
    assert.deepEqual(pos._value, { x: 0.58, y: 0.5 });
  });

  it('never throws, even when every path throws', async () => {
    const p = new ppro._MockComponentParam('Exposure', 0);
    p.createKeyframe = () => { throw new Error('boom 1'); };
    p.createSetValueAction = () => { throw new Error('boom 2'); };
    const r = await writeParamVerified(project, p, 1, 'X', null);
    assert.equal(r.ok, false);
    assert.match(r.why, /createKeyframe упал: boom 1; mutate-start упал: boom 2/, 'both causes reported, first one included');
  });

  it('a param without createSetValueAction is refused, not crashed on', async () => {
    const r = await writeParamVerified(project, {}, 1, 'X', null);
    assert.equal(r.ok, false);
    assert.match(r.why, /createSetValueAction/);
  });
});
