/**
 * panelDom.js — привязка кнопок панели. Отдельным модулем, чтобы проверять в Node.
 *
 * Два дефекта, которые это закрывает (TICKET_uxp_audit, H и задача 2):
 *   1. $('btn-x').addEventListener(...) на отсутствующей кнопке бросает на null —
 *      и тихо убивает ВСЕ привязки ниже по списку. on() переживает отсутствие
 *      кнопки и сообщает о нём в «Err».
 *   2. Обработчик — async-функция без .catch: исключение уходило в пустоту
 *      (UXP не ловит unhandledrejection без featureFlags в manifest.json).
 *      on() оборачивает обработчик: и throw, и отклонённый промис попадают
 *      в кольцо «Err» со стеком.
 * this и событие передаются обработчику как есть.
 */
const { Logger } = require('./logger');

function $(id) { return document.querySelector('#' + id); }

function errText(err) {
  try { return (err && err.message) ? err.message : String(err); } catch (e) { return '(unprintable error)'; }
}

/** Привязать клик. Возвращает true, если кнопка есть в разметке. */
function on(id, handler) {
  var el = $(id);
  if (!el) {
    Logger.pushPanelError('ERROR', 'binding: #' + id + ' is not in index.html — its handler is not attached', 'panel');
    return false;
  }
  el.addEventListener('click', function (e) {
    var r;
    try {
      r = handler.call(this, e);
    } catch (err) {
      Logger.pushPanelError('ERROR', '#' + id + ': ' + errText(err), 'panel', err);
      return undefined;
    }
    if (r && typeof r.then === 'function') {
      r.then(null, function (err) {
        Logger.pushPanelError('ERROR', '#' + id + ': ' + errText(err), 'panel', err);
      });
    }
    return r;
  });
  return true;
}

module.exports = { $, on };
