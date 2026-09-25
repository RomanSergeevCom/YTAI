/**
 * colorApply — раскладка цвета из {CODE}_color_plan.json на клипы таймлайна.
 *
 * Зачем отдельно от adjustmentBuilder. Тот умеет ровно один параметр Lumetri —
 * Creative Look — и выбирает параметр ПО ИМЕНИ, беря ПОСЛЕДНЕЕ совпадение.
 * В Lumetri имена дублируются (Input LUT дважды, Look дважды, Saturation
 * четырежды), поэтому нужные слоты по имени недостижимы в принципе: последний
 * «Look» — это числовой индекс встроенных луков Adobe, он всегда 0, и попытка
 * записать туда строку выглядит как «Look мёртв».
 *
 * Здесь параметр адресуется ПО ИНДЕКСУ, но вслепую по индексу не пишем:
 *   1) снимаем полный дамп параметров компонента (индекс, имя, тип, значение);
 *   2) кандидатов ищем по имени и получаем СПИСОК индексов, а не один;
 *   3) пишем в кандидата и ЧИТАЕМ ОБРАТНО; не прилипло — берём следующего;
 *   4) не прилипло нигде — отказ с дампом, а не молчаливый успех.
 *
 * ⚠️ Читать обратно float строгим равенством нельзя: Premiere хранит float32,
 * и 1.2 возвращается как 1.2000000476837158. Отсюда допуск EPS.
 */

const AB = require('./adjustmentBuilder');

const EPS = 1e-4;                 // допуск сравнения float32
const LUMETRI = 'lumetri';

/** Полный дамп параметров компонента: то, чего в панели не было никогда. */
async function dumpComponentParams(comp) {
  const out = [];
  let n = 0;
  try { n = await comp.getParamCount(); } catch (e) { return out; }
  for (let i = 0; i < n; i++) {
    const row = { i: i, name: '', type: '', value: undefined, err: null };
    let p = null;
    try { p = await comp.getParam(i); } catch (e) { row.err = 'getParam: ' + e.message; out.push(row); continue; }
    try { row.name = await AB.readDisplayName(p); } catch (e) { /* имя не обязательно */ }
    try {
      if (p && typeof p.getStartValue === 'function') {
        const kf = await p.getStartValue();
        const v = kf ? kf.value : undefined;
        const inner = (v && typeof v === 'object' && 'value' in v) ? v.value : v;
        row.value = inner;
        row.type = typeof inner;
      }
    } catch (e) { row.err = 'getStartValue: ' + e.message; }
    out.push(row);
  }
  return out;
}

function formatDump(rows) {
  return rows.map(function (r) {
    const v = r.err ? ('ERR ' + r.err)
      : (typeof r.value === 'string' ? JSON.stringify(r.value.slice(0, 60)) : String(r.value));
    return '[' + r.i + '] ' + (r.name || '?') + ' :' + (r.type || '?') + ' = ' + v;
  }).join('\n');
}

/**
 * Развернуть обёртку, если пришла она.
 *
 * ⚠️ `collectVideoClipEntries()` отдаёт НЕ айтемы таймлайна, а записи
 * `{trackItem, name, startSec, endSec, trackIdx}`. Отдать такую обёртку в
 * `asVideoClip()` — получить «vclip.getComponentChain is not a function»,
 * ровно это и случилось на первом живом прогоне 25.09.2026. Разворачиваем
 * здесь, чтобы ошибка не могла повториться ни на одном будущем вызове.
 */
function rawItem(x) {
  if (x && typeof x.getComponentChain !== 'function' && x.trackItem) return x.trackItem;
  return x;
}

/** Имя клипа для отчёта: у обёртки оно своё, у сырого айтема — своё. */
function itemName(x) {
  if (!x) return '?';
  if (x.name) return String(x.name);
  if (x.trackItem && x.trackItem.name) return String(x.trackItem.name);
  return '?';
}

/** Компонент Lumetri в цепочке клипа. Берём ПЕРВЫЙ — он и есть клиповый. */
async function lumetriOf(trackItem) {
  const vclip = AB.asVideoClip(rawItem(trackItem));
  const chain = await vclip.getComponentChain();
  const comps = await AB.getChainComponents(chain);
  for (const c of comps) {
    let n = '';
    try { n = (await AB.readDisplayName(c)) || ''; } catch (e) { /* ignore */ }
    if (!n && c && typeof c.getMatchName === 'function') {
      try { n = String(await c.getMatchName()); } catch (e) { /* ignore */ }
    }
    if (String(n).toLowerCase().indexOf(LUMETRI) >= 0) return c;
  }
  return null;
}

function sameValue(a, b) {
  if (typeof a === 'number' && typeof b === 'number') return Math.abs(a - b) < EPS;
  return a === b;
}

/** Записать в параметр по индексу и подтвердить чтением. */
async function setParamAtIndex(project, comp, index, value, label, logger) {
  let param = null;
  try { param = await comp.getParam(index); } catch (e) {
    return { ok: false, why: 'getParam(' + index + '): ' + e.message };
  }
  if (!param || typeof param.createSetValueAction !== 'function') {
    return { ok: false, why: 'нет createSetValueAction на индексе ' + index };
  }

  let before;
  let kf = null;
  try {
    if (typeof param.getStartValue === 'function') {
      kf = await param.getStartValue();
      const v = kf ? kf.value : undefined;
      before = (v && typeof v === 'object' && 'value' in v) ? v.value : v;
    }
  } catch (e) { /* пробуем писать вслепую */ }

  // тип уже верен и значение совпало — не трогаем
  if (before !== undefined && sameValue(before, value)) {
    return { ok: true, noop: true, before: before, after: before };
  }
  // числовой слот строкой не выставить — это терминально, а не «попробуем»
  if (typeof before === 'number' && typeof value !== 'number') {
    return { ok: false, numericSlot: true,
      why: 'индекс ' + index + ' — ЧИСЛОВОЕ МЕНЮ (' + before + '), строку туда не положить' };
  }

  // ⚠️ Порядок путей важен. Сначала СВЕЖИЙ кейфрейм, и только потом мутация
  // того, что вернул getStartValue(). Мутация — путь, который на живой
  // Premiere 26 молча не прилипает: 25.09.2026 Exposure у 10 клипов
  // коммитился без исключения и читался прежним. Рабочий прецедент в этом же
  // репозитории (shortsBuilder, Motion → Position) создаёт новый кейфрейм, и
  // только он и работает.
  var paths = [];
  if (typeof param.createKeyframe === 'function') {
    paths.push({ name: 'createKeyframe', make: function () { return param.createKeyframe(value); } });
  }
  if (kf) {
    paths.push({ name: 'mutate-start', make: function () {
      if (kf.value && typeof kf.value === 'object' && 'value' in kf.value) kf.value.value = value;
      else kf.value = value;
      return kf;
    } });
  }
  if (!paths.length) return { ok: false, why: 'нечем записать: ни createKeyframe, ни getStartValue' };

  var lastWhy = '';
  for (var pi = 0; pi < paths.length; pi++) {
    try {
      var k = paths[pi].make();
      await project.lockedAccess(function () {
        return project.executeTransaction(function (ca) {
          ca.addAction(param.createSetValueAction(k, true));
        }, 'YTAI color: ' + label);
      });
    } catch (e) {
      lastWhy = paths[pi].name + ' упал: ' + e.message;
      continue;
    }
    var got;
    try {
      if (typeof param.getStartValue === 'function') {
        var kk = await param.getStartValue();
        var vv = kk ? kk.value : undefined;
        got = (vv && typeof vv === 'object' && 'value' in vv) ? vv.value : vv;
      }
    } catch (e) { /* прочитать не смогли */ }
    if (got === undefined) return { ok: true, unverified: true, path: paths[pi].name, before: before };
    if (sameValue(got, value)) return { ok: true, path: paths[pi].name, before: before, after: got };
    if (!sameValue(got, before)) {
      return { ok: true, normalized: true, path: paths[pi].name, before: before, after: got };
    }
    lastWhy = paths[pi].name + ': не прилипло, читается прежнее';
    if (logger) logger.debug('color: ' + label + ' — ' + lastWhy + ', пробую следующий путь');
  }
  return { ok: false, why: lastWhy || 'не прилипло', before: before };

}

/**
 * Записать значение в слот, названный именем: пробуем ВСЕ индексы с таким
 * именем, пока одно не прилипнет. Это и есть замена «последнего совпадения».
 */
async function setNamedSlot(project, comp, rows, name, value, logger) {
  const cands = rows.filter(function (r) {
    return String(r.name || '').toLowerCase() === String(name).toLowerCase();
  });
  if (!cands.length) {
    return { ok: false, why: 'параметра «' + name + '» нет среди ' + rows.length, tried: [] };
  }
  // ⚠️ Какую форму принимает Input LUT — полный путь, имя файла или голое имя —
  // никто никогда не проверял. Поэтому значение может прийти списком форм:
  // перебираем формы по каждому индексу, пока одна не прилипнет.
  const values = Array.isArray(value) ? value : [value];
  const tried = [];
  for (const c of cands) {
    for (const v of values) {
      const res = await setParamAtIndex(project, comp, c.i, v, name + '@' + c.i, logger);
      tried.push({ i: c.i, value: v, res: res });
      if (res.ok) {
        if (logger) {
          logger.info('color: ' + name + ' -> индекс ' + c.i + ' ok'
            + (values.length > 1 ? ' формой ' + JSON.stringify(v) : '')
            + (res.noop ? ' (уже стояло)' : '')
            + (res.normalized ? ' (нормализовано: ' + JSON.stringify(res.after) + ')' : '')
            + (res.unverified ? ' (без подтверждения)' : ''));
        }
        return { ok: true, index: c.i, value: v, res: res, tried: tried };
      }
      if (logger) logger.debug('color: ' + name + ' индекс ' + c.i + ' мимо — ' + res.why);
      // числовой слот не примет НИ ОДНУ строковую форму — сразу к следующему
      // индексу. Признак структурный: ловить это регуляркой по тексту отказа
      // уже ломалось от правки формулировки.
      if (res.numericSlot) break;
    }
  }
  return { ok: false, why: 'ни один из индексов [' + cands.map(function (c) { return c.i; }).join(', ')
    + '] не принял значение', tried: tried };
}

/**
 * Положить цвет на один клип.
 * spec = { developPath, exposure, lookName }
 */
async function applyColorToClip(project, trackItem, spec, logger) {
  const name = itemName(trackItem);
  const item = rawItem(trackItem);
  const out = { clip: name, develop: null, exposure: null, look: null, dump: null };

  let comp = await lumetriOf(item);
  if (!comp) {
    const added = await AB.applyEffect(project, item, 'Lumetri', null, null, logger);
    if (added === false && logger) logger.warn('color: ' + name + ': Lumetri не добавился');
    comp = await lumetriOf(item);
  }
  if (!comp) { out.error = 'Lumetri не в цепочке'; return out; }

  const rows = await dumpComponentParams(comp);
  out.dump = rows;
  if (!rows.length) { out.error = 'параметры Lumetri не читаются'; return out; }

  if (spec.developPath) out.develop = await setNamedSlot(project, comp, rows, 'Input LUT', spec.developPath, logger);
  if (typeof spec.exposure === 'number') out.exposure = await setNamedSlot(project, comp, rows, 'Exposure', spec.exposure, logger);
  if (spec.lookName) out.look = await setNamedSlot(project, comp, rows, 'Look', spec.lookName, logger);
  return out;
}

module.exports = {
  rawItem,
  itemName,
  dumpComponentParams,
  formatDump,
  lumetriOf,
  setParamAtIndex,
  setNamedSlot,
  applyColorToClip,
  EPS,
};
