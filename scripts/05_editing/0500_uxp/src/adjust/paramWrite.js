/**
 * paramWrite.js — запись параметра эффекта с обязательным чтением обратно.
 * ЕДИНСТВЕННАЯ реализация: её зовут colorApply.setParamAtIndex (цвет по
 * индексу) и adjustmentBuilder.setEffectParam (старый сеттер по имени).
 *
 * Два дефекта, которые она закрывает (TICKET_uxp_audit, D и E):
 *   D. Коммит без исключения ≠ значение записано. Измерено 25.09.2026 на живой
 *      Premiere 26, 10 клипов из 10: мутация того, что вернул getStartValue(),
 *      коммитится и НЕ применяется; createKeyframe(value) — применяется.
 *      Поэтому свежий кейфрейм пробуется ПЕРВЫМ, мутация — откат, и после
 *      КАЖДОГО пути значение читается обратно.
 *   E. Premiere хранит float32: записал 1.2 — прочитал 1.2000000476837158.
 *      Строгое равенство объявляло провал на успешной записи. Сравнение чисел —
 *      с допуском EPS.
 *
 * ⚠️ Контракт с тестами colorApply: имена путей 'createKeyframe' / 'mutate-start'
 * и поля результата { ok, path, noop, unverified, normalized, numericSlot, why,
 * before, after } проверяются — не переименовывать.
 */

const EPS = 1e-4;   // допуск сравнения float32

/** Значение из кейфрейма: у Premiere оно бывает вложенным ({ value: { value } }). */
function unwrapKf(kf) {
  const v = kf ? kf.value : undefined;
  return (v && typeof v === 'object' && 'value' in v) ? v.value : v;
}

/**
 * Равенство для readback. Числа — с допуском float32. Точки и массивы
 * ({x, y}, [x, y] — Motion.Position) — покоординатно. Непрозрачный объект, у
 * которого не видно ни ключей, ни x/y, сравнивается по тождеству: неизвестная
 * форма не должна давать ложное «не прилипло».
 */
function sameValue(a, b) {
  if (typeof a === 'number' && typeof b === 'number') return Math.abs(a - b) < EPS;
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    if (Array.isArray(a) !== Array.isArray(b)) return false;
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    if ('x' in a || 'x' in b) { keys.add('x'); keys.add('y'); }
    if (!keys.size) return a === b;
    for (const k of keys) if (!sameValue(a[k], b[k])) return false;
    return true;
  }
  return a === b;
}

/**
 * Записать value в param и подтвердить чтением.
 * @param {string} label — для лога и отчёта («Lumetri.Exposure», «индекс 19»)
 * @param {{undoLabel?: string}} [opts] — подпись транзакции в истории Premiere
 * @returns {Promise<{ok: boolean, path?: string, noop?: true, unverified?: true,
 *   normalized?: true, numericSlot?: true, why?: string, before?: *, after?: *}>}
 *   Никогда не бросает.
 */
async function writeParamVerified(project, param, value, label, logger, opts) {
  const undoLabel = (opts && opts.undoLabel) || ('YTAI: ' + label);
  if (!param || typeof param.createSetValueAction !== 'function') {
    return { ok: false, why: label + ': нет createSetValueAction' };
  }

  let before;
  let kf = null;
  try {
    if (typeof param.getStartValue === 'function') {
      kf = await param.getStartValue();
      before = unwrapKf(kf);
    }
  } catch (e) { /* прочитать не смогли — пишем вслепую, readback решит */ }

  // значение уже стоит — не трогаем (идемпотентный повтор)
  if (before !== undefined && sameValue(before, value)) {
    return { ok: true, noop: true, before: before, after: before };
  }
  // числовой слот строкой не выставить — это терминально, а не «попробуем»
  if (typeof before === 'number' && typeof value !== 'number') {
    return { ok: false, numericSlot: true,
      why: label + ' — ЧИСЛОВОЕ МЕНЮ (' + before + '), строку туда не положить' };
  }

  // ⚠️ Порядок путей важен (дефект D): свежий кейфрейм, потом мутация.
  const paths = [];
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
  if (!paths.length) return { ok: false, why: label + ': нечем записать — ни createKeyframe, ни getStartValue' };

  // Every path's outcome is kept: on live 26 createKeyframe may THROW (the real
  // cause) and the mutation then «commits» without applying — reporting only the
  // last path would blame the one that is known never to apply (review of ac7b975).
  const whys = [];
  for (const p of paths) {
    try {
      const k = p.make();
      await project.lockedAccess(function () {
        return project.executeTransaction(function (ca) {
          ca.addAction(param.createSetValueAction(k, true));
        }, undoLabel);
      });
    } catch (e) {
      whys.push(p.name + ' упал: ' + (e && e.message));
      if (logger) logger.debug(label + ' — ' + whys[whys.length - 1] + ', пробую следующий путь');
      continue;
    }
    let got;
    try {
      if (typeof param.getStartValue === 'function') got = unwrapKf(await param.getStartValue());
    } catch (e) { /* прочитать не смогли */ }
    if (got === undefined) return { ok: true, unverified: true, path: p.name, before: before };
    if (sameValue(got, value)) return { ok: true, path: p.name, before: before, after: got };
    if (!sameValue(got, before)) {
      return { ok: true, normalized: true, path: p.name, before: before, after: got };
    }
    whys.push(p.name + ': не прилипло, читается прежнее');
    if (logger) logger.debug(label + ' — ' + whys[whys.length - 1] + ', пробую следующий путь');
  }
  return { ok: false, why: label + ': ' + (whys.length ? whys.join('; ') : 'не прилипло'), before: before };
}

module.exports = { writeParamVerified, sameValue, unwrapKf, EPS };
