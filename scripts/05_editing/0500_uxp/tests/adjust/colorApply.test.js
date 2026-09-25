const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const ppro = require('../mocks/premierepro');
const CA = require('../../src/adjust/colorApply');
const { Logger } = require('../../src/shared/logger');

/**
 * Модель живого Lumetri: имена ДУБЛИРУЮТСЯ, и дубли разной природы.
 * Input LUT — на 6 (числовое меню) и 7 (путь строкой);
 * Look — на 34 (строка) и 35 (числовой индекс встроенных луков, всегда 0);
 * Exposure — одно, float.
 * Именно из-за «последнего совпадения» старый сеттер попадал в 35 и 7.
 */
function lumetriLike(overrides) {
  const P = ppro._MockComponentParam;
  const params = [];
  for (let i = 0; i < 40; i++) params.push(new P('Slot' + i, 0));
  params[6] = new P('Input LUT', 0, { type: 'number' });            // меню, не путь
  params[7] = new P('Input LUT', '');                                // сюда путь
  params[19] = new P('Exposure', 0);
  params[34] = new P('Look', '');                                    // сюда имя лука
  params[35] = new P('Look', 0, { type: 'number' });                 // индекс, всегда 0
  params[12] = new P('Saturation', 100);
  params[20] = new P('Saturation', 100);
  Object.assign(params, overrides || {});
  const comp = {
    getDisplayName: async () => 'Lumetri Color',
    getParamCount: async () => params.length,
    getParam: async (i) => params[i],
  };
  const chain = { getComponentCount: async () => 1, getComponentAtIndex: async () => comp };
  return { comp: comp, params: params, clip: { getComponentChain: async () => chain } };
}

describe('colorApply — адресация параметра Lumetri по индексу', () => {
  let project, logger, savedCast;
  beforeEach(() => {
    ppro._recorder.reset();
    project = new ppro._MockProject('P');
    logger = new Logger();
  });

  it('дамп даёт индекс, имя, тип и значение по каждому параметру', async () => {
    const L = lumetriLike();
    const rows = await CA.dumpComponentParams(L.comp);
    assert.equal(rows.length, 40);
    assert.deepEqual(
      rows.filter((r) => r.name === 'Input LUT').map((r) => r.i), [6, 7],
      'оба Input LUT должны быть видны по индексам'
    );
    assert.deepEqual(rows.filter((r) => r.name === 'Saturation').map((r) => r.i), [12, 20]);
    assert.equal(rows[19].name, 'Exposure');
    assert.equal(rows[19].type, 'number');
    assert.match(CA.formatDump(rows), /\[7\] Input LUT/);
  });

  it('Input LUT: числовой слот 6 пропускается, путь уходит в 7', async () => {
    const L = lumetriLike();
    const rows = await CA.dumpComponentParams(L.comp);
    const res = await CA.setNamedSlot(project, L.comp, rows, 'Input LUT', '/LUT/develop.cube', logger);
    assert.equal(res.ok, true);
    assert.equal(res.index, 7, 'должен выбрать второй слот, а не первый');
    assert.equal(L.params[7]._value, '/LUT/develop.cube');
    assert.equal(L.params[6]._value, 0, 'числовой слот не тронут');
  });

  it('Look: попадает в 34, а не в числовой 35 — та самая «смерть Look»', async () => {
    const L = lumetriLike();
    const rows = await CA.dumpComponentParams(L.comp);
    const res = await CA.setNamedSlot(project, L.comp, rows, 'Look', 'YTAI_look__malibu', logger);
    assert.equal(res.ok, true);
    assert.equal(res.index, 34);
    assert.equal(L.params[34]._value, 'YTAI_look__malibu');
    assert.equal(L.params[35]._value, 0, 'числовой индекс встроенных луков остаётся нулём');
  });

  it('Exposure: float32-дрейф при чтении не считается промахом', async () => {
    const L = lumetriLike();
    let stored = 0;
    L.params[19] = {
      displayName: 'Exposure',
      getStartValue: async () => ({ value: { value: stored } }),
      createKeyframe: (v) => ({ value: { value: v } }),
      // мок применяет действия по .apply() при коммите
      createSetValueAction: (kf) => ({
        apply: () => { stored = Math.fround(kf.value.value); },   // Premiere хранит float32
      }),
    };
    const rows = await CA.dumpComponentParams(L.comp);
    const res = await CA.setNamedSlot(project, L.comp, rows, 'Exposure', 1.2, logger);
    assert.equal(res.ok, true, 'строгое равенство сломалось бы здесь');
    assert.notEqual(stored, 1.2, 'мок обязан вернуть именно дрейф');
    assert.ok(Math.abs(stored - 1.2) < CA.EPS);
  });

  it('повторный прогон идемпотентен: значение уже стоит — запись не идёт', async () => {
    const L = lumetriLike();
    const rows = await CA.dumpComponentParams(L.comp);
    await CA.setNamedSlot(project, L.comp, rows, 'Exposure', 2.4, logger);
    ppro._recorder.reset();
    const rows2 = await CA.dumpComponentParams(L.comp);
    const res = await CA.setNamedSlot(project, L.comp, rows2, 'Exposure', 2.4, logger);
    assert.equal(res.ok, true);
    assert.equal(res.res.noop, true);
    assert.equal(
      ppro._recorder.getCalls('ComponentParam.createSetValueAction').length, 0,
      'второй проход не должен писать'
    );
  });

  it('не прилипло ни в один слот — честный отказ, а не тихий успех', async () => {
    const P = ppro._MockComponentParam;
    const L = lumetriLike({
      34: new P('Look', '', { ignoreSet: true }),
      35: new P('Look', '', { ignoreSet: true }),
    });
    const rows = await CA.dumpComponentParams(L.comp);
    const res = await CA.setNamedSlot(project, L.comp, rows, 'Look', 'malibu', logger);
    assert.equal(res.ok, false);
    assert.match(res.why, /34, 35/);
    assert.equal(res.tried.length, 2, 'обязан попробовать оба индекса');
  });

  it('имени нет вовсе — отказ называет, сколько параметров осмотрено', async () => {
    const L = lumetriLike();
    const rows = await CA.dumpComponentParams(L.comp);
    const res = await CA.setNamedSlot(project, L.comp, rows, 'Input Cube', '/x.cube', logger);
    assert.equal(res.ok, false);
    assert.match(res.why, /нет среди 40/);
  });

  it('клип целиком: проявка, экспозиция и покраска ложатся за один проход', async () => {
    savedCast = ppro.VideoClipTrackItem.cast;
    try {
      delete ppro.VideoClipTrackItem.cast;
      const L = lumetriLike();
      const out = await CA.applyColorToClip(project, L.clip, {
        developPath: '/LUT/sony__slog3.cube',
        exposure: 1.2,
        lookName: 'YTAI_look__malibu',
      }, logger);
      assert.equal(out.develop.ok, true);
      assert.equal(out.exposure.ok, true);
      assert.equal(out.look.ok, true);
      assert.equal(L.params[7]._value, '/LUT/sony__slog3.cube');
      assert.ok(Math.abs(L.params[19]._value - 1.2) < CA.EPS);
      assert.equal(L.params[34]._value, 'YTAI_look__malibu');
      assert.ok(out.dump.length === 40, 'дамп прикладывается к результату всегда');
    } finally {
      ppro.VideoClipTrackItem.cast = savedCast;
    }
  });

  it('exposure = 0 записывается, а не отбрасывается как falsy', async () => {
    savedCast = ppro.VideoClipTrackItem.cast;
    try {
      delete ppro.VideoClipTrackItem.cast;
      const L = lumetriLike();
      L.params[19]._value = 1.5;            // было не ноль
      const out = await CA.applyColorToClip(project, L.clip, { exposure: 0 }, logger);
      assert.equal(out.exposure.ok, true, 'ноль — валидное значение экспозиции FX3');
      assert.equal(L.params[19]._value, 0);
    } finally {
      ppro.VideoClipTrackItem.cast = savedCast;
    }
  });
});

describe('colorApply — перебор форм значения', () => {
  let project, logger;
  beforeEach(() => { ppro._recorder.reset(); project = new ppro._MockProject('P'); logger = new Logger(); });

  it('пробует формы по порядку и берёт первую прилипшую', async () => {
    const P = ppro._MockComponentParam;
    // слот принимает ТОЛЬКО голое имя: путь и имя файла игнорируются
    const only = new P('Input LUT', '');
    const realSet = only.createSetValueAction.bind(only);
    only.createSetValueAction = function (kf, safe) {
      const v = kf && kf.value && kf.value.value;
      if (typeof v === 'string' && v.indexOf('/') >= 0) return { apply: function () {} }; // путь не липнет
      return realSet(kf, safe);
    };
    const params = [new P('Slot0', 0), only];
    const comp = {
      getDisplayName: async () => 'Lumetri Color',
      getParamCount: async () => params.length,
      getParam: async (i) => params[i],
    };
    const rows = await CA.dumpComponentParams(comp);
    const res = await CA.setNamedSlot(project, comp, rows, 'Input LUT',
      ['/Users/x/YTAI_sony.cube', 'YTAI_sony.cube'], logger);
    assert.equal(res.ok, true);
    assert.equal(res.value, 'YTAI_sony.cube', 'должна выиграть вторая форма');
    assert.equal(only._value, 'YTAI_sony.cube');
    assert.ok(res.tried.length >= 2, 'обе формы должны быть в протоколе попыток');
  });

  it('числовой слот не перебирает все формы впустую', async () => {
    const P = ppro._MockComponentParam;
    const params = [new P('Input LUT', 0, { type: 'number' }), new P('Input LUT', '')];
    const comp = {
      getDisplayName: async () => 'Lumetri Color',
      getParamCount: async () => params.length,
      getParam: async (i) => params[i],
    };
    const rows = await CA.dumpComponentParams(comp);
    const res = await CA.setNamedSlot(project, comp, rows, 'Input LUT', ['/a.cube', 'a.cube', 'a'], logger);
    assert.equal(res.ok, true);
    assert.equal(res.index, 1);
    const onZero = res.tried.filter((t) => t.i === 0).length;
    assert.equal(onZero, 1, 'числовой слот пробуется один раз, а не тремя формами');
  });
});

describe('colorApply — запись collectVideoClipEntries', () => {
  let project, logger;
  beforeEach(() => { ppro._recorder.reset(); project = new ppro._MockProject('P'); logger = new Logger(); });

  it('принимает ОБЁРТКУ {item,name,...}, а не только сырой айтем', async () => {
    const saved = ppro.VideoClipTrackItem.cast;
    try {
      delete ppro.VideoClipTrackItem.cast;
      const L = lumetriLike();
      // ровно то, что отдаёт collectVideoClipEntries
      const wrapper = { trackItem: L.clip, name: 'RYA-FX3-1263.MP4', startSec: 0, endSec: 69.6, trackIdx: 0 };
      const out = await CA.applyColorToClip(project, wrapper, { exposure: 1.2 }, logger);
      assert.equal(out.error, undefined, 'обёртка не должна ронять «getComponentChain is not a function»');
      assert.equal(out.clip, 'RYA-FX3-1263.MP4', 'имя берётся из обёртки');
      assert.equal(out.exposure.ok, true);
      assert.ok(Math.abs(L.params[19]._value - 1.2) < CA.EPS);
    } finally { ppro.VideoClipTrackItem.cast = saved; }
  });

  it('сырой айтем по-прежнему работает', async () => {
    const saved = ppro.VideoClipTrackItem.cast;
    try {
      delete ppro.VideoClipTrackItem.cast;
      const L = lumetriLike();
      const out = await CA.applyColorToClip(project, L.clip, { exposure: 2.4 }, logger);
      assert.equal(out.error, undefined);
      assert.ok(Math.abs(L.params[19]._value - 2.4) < CA.EPS);
    } finally { ppro.VideoClipTrackItem.cast = saved; }
  });

  it('rawItem разворачивает только обёртку, сырой айтем не трогает', () => {
    const raw = { getComponentChain: async () => ({}) };
    assert.equal(CA.rawItem(raw), raw);
    assert.equal(CA.rawItem({ trackItem: raw, name: 'x' }), raw);
    assert.equal(CA.itemName({ trackItem: raw, name: 'x' }), 'x');
  });
});

describe('colorApply — порядок путей записи', () => {
  let project, logger;
  beforeEach(() => { ppro._recorder.reset(); project = new ppro._MockProject('P'); logger = new Logger(); });

  it('свежий кейфрейм пробуется ПЕРВЫМ — мутация на живой Premiere не липнет', async () => {
    const order = [];
    let stored = 0;
    const param = {
      displayName: 'Exposure',
      getStartValue: async () => ({ value: { value: stored } }),
      createKeyframe: (v) => { order.push('createKeyframe'); return { value: { value: v }, fresh: true }; },
      createSetValueAction: (kf) => ({ apply: () => { if (kf.fresh) stored = kf.value.value; } }),
    };
    const comp = { getDisplayName: async () => 'Lumetri Color',
                   getParamCount: async () => 1, getParam: async () => param };
    const rows = await CA.dumpComponentParams(comp);
    const res = await CA.setNamedSlot(project, comp, rows, 'Exposure', 1.2, logger);
    assert.equal(res.ok, true);
    assert.equal(res.res.path, 'createKeyframe', 'должен выиграть свежий кейфрейм');
    assert.equal(order[0], 'createKeyframe', 'и он обязан идти первым');
    assert.ok(Math.abs(stored - 1.2) < CA.EPS);
  });

  it('если свежий не прилип — откат на мутацию, а не отказ', async () => {
    let stored = 0;
    const param = {
      displayName: 'Exposure',
      getStartValue: async () => ({ value: { value: stored } }),
      createKeyframe: (v) => ({ value: { value: v }, fresh: true }),
      // свежий игнорируется, мутация принимается
      createSetValueAction: (kf) => ({ apply: () => { if (!kf.fresh) stored = kf.value.value; } }),
    };
    const comp = { getDisplayName: async () => 'Lumetri Color',
                   getParamCount: async () => 1, getParam: async () => param };
    const rows = await CA.dumpComponentParams(comp);
    const res = await CA.setNamedSlot(project, comp, rows, 'Exposure', 2.4, logger);
    assert.equal(res.ok, true);
    assert.equal(res.res.path, 'mutate-start');
    assert.ok(Math.abs(stored - 2.4) < CA.EPS);
  });

  it('числовое меню помечается флагом, а не текстом отказа', async () => {
    const P = ppro._MockComponentParam;
    const params = [new P('Input LUT', 0, { type: 'number' }), new P('Input LUT', 0, { type: 'number' })];
    const comp = { getDisplayName: async () => 'Lumetri Color',
                   getParamCount: async () => 2, getParam: async (i) => params[i] };
    const rows = await CA.dumpComponentParams(comp);
    const res = await CA.setNamedSlot(project, comp, rows, 'Input LUT', ['/a.cube', 'a.cube', 'a'], logger);
    assert.equal(res.ok, false);
    assert.equal(res.tried.length, 2, 'по одной попытке на индекс, а не по три формы');
    assert.ok(res.tried.every((t) => t.res.numericSlot === true));
  });
});
