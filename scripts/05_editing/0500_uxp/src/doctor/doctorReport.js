/**
 * doctorReport.js — Project Doctor report builders (pure, no Premiere API).
 *
 * Consumes the analysis result produced by analyzeForDoctor() in index.js and
 * renders a self-contained English HTML report + a machine-readable JSON.
 *
 * result schema:
 * {
 *   project: { name, code, path },
 *   generatedAt: ISO string,
 *   scopeLabel: string,                 // e.g. "Active sequence: врач" | "All sequences (30)"
 *   sequencesScanned: [string],
 *   counts: { total, present, offline, actionRequired },
 *   items: [ { name, mediaPath, present:bool, used:bool, usedIn:[{seq,count}] } ],
 *   fonts: [string],
 *   errors: [string]
 * }
 */

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function categorize(path, name) {
  var p = String(path || name || '').toLowerCase();
  if (/\.(mp3|wav|aif|aiff|m4a|aac)$/.test(p)) return 'Audio / Music';
  if (/\.(mogrt|aegraphic)$/.test(p)) return 'Graphics / Template';
  if (/\.(png|jpg|jpeg|psd|tif|tiff|gif|svg)$/.test(p)) return 'Image';
  if (/artlist|\/stock|stockfootage/.test(p)) return 'Stock video';
  if (/rya-zve|01_source|\.mxf$|\.mts$/.test(p)) return 'Footage (camera)';
  if (/\.(mp4|mov|m4v)$/.test(p)) return 'Video';
  return 'Other';
}

function usedCount(usedIn) {
  if (!usedIn || !usedIn.length) return 0;
  return usedIn.reduce(function (s, u) { return s + (u.count || 0); }, 0);
}

// bilingual span toggled by the report's RU/EN switch. Renders RU by default (PDF-safe).
function t(ru, en) {
  return '<span class="i18n" data-ru="' + esc(ru) + '" data-en="' + esc(en) + '">' + esc(ru) + '</span>';
}

function buildDoctorJson(result) {
  // enrich items with category for the JSON consumers (request list / automation)
  var out = JSON.parse(JSON.stringify(result));
  (out.items || []).forEach(function (it) { it.category = categorize(it.mediaPath, it.name); });
  return JSON.stringify(out, null, 2);
}

function buildDoctorHtml(result) {
  var c = result.counts || {};
  var items = (result.items || []).map(function (it) {
    return Object.assign({}, it, { category: categorize(it.mediaPath, it.name) });
  });
  var action = items.filter(function (i) { return !i.present && i.used; });
  var offlineUnused = items.filter(function (i) { return !i.present && !i.used; });
  var present = items.filter(function (i) { return i.present; });

  // group Action Required by category
  var byCat = {};
  action.forEach(function (i) { (byCat[i.category] = byCat[i.category] || []).push(i); });

  // sort Action Required: heaviest use first within each category
  action.sort(function (a, b) { return usedCount(b.usedIn) - usedCount(a.usedIn); });
  var needCount = action.length;

  var projName = result.project && result.project.name || '';
  var RU_CAT = { 'Audio / Music': '🎵 Музыка', 'Image': '🖼 Картинки', 'Video': '🎬 Видео',
    'Stock video': '🎬 Сток', 'Graphics / Template': '🔤 Графика/шаблоны', 'Footage (camera)': '📹 Съёмка', 'Other': '📄 Прочее' };

  // Ready-to-send summary in both languages (for Share / Copy → paste into Telegram).
  function makeSummary(lang) {
    var en = lang === 'en';
    var s = [(en ? 'Media report — ' : 'Медиа-отчёт — ') + projName,
             (en ? 'Timeline: ' : 'Таймлайн: ') + (result.scopeLabel || '')];
    if (!needCount) {
      s.push('', en ? 'All media on the timeline is present — nothing to request. ✅'
                    : 'Все медиа на таймлайне на месте — присылать ничего не нужно. ✅');
    } else {
      s.push('', en ? ('Please send ' + needCount + ' file(s) — used on the timeline but missing:')
                    : ('Нужно прислать ' + needCount + ' файл(ов) — они на таймлайне, но отсутствуют:'));
      Object.keys(byCat).sort().forEach(function (cat) {
        s.push('', (en ? cat : (RU_CAT[cat] || cat)) + ':');
        byCat[cat].slice().sort(function (a, b) { return usedCount(b.usedIn) - usedCount(a.usedIn); }).forEach(function (i) {
          s.push('• ' + i.name + ' (×' + usedCount(i.usedIn) + ') — ' + i.mediaPath);
        });
      });
      var heavy = action.filter(function (i) { return usedCount(i.usedIn) >= 10; });
      if (heavy.length) {
        s.push('', '⚠️ ' + heavy.map(function (i) { return i.name + ' (×' + usedCount(i.usedIn) + ')'; }).join(', ') +
          (en ? ' — used very many times, looks like a pre-rendered cut / another project. Please clarify what it is and where it’s from.'
              : ' — используется очень много раз, похоже на готовую сборку / другой проект. Уточни, что это и откуда.'));
      }
    }
    return s.join('\n');
  }
  var summaryRU = makeSummary('ru');
  var summaryEN = makeSummary('en');

  var H = [];
  H.push('<!doctype html><html lang="en"><head><meta charset="utf-8">');
  H.push('<meta name="viewport" content="width=device-width, initial-scale=1">');
  H.push('<title>Media Status Report — ' + esc(result.project && result.project.name) + '</title>');
  H.push('<style>');
  H.push('*{box-sizing:border-box}');
  H.push('body{background:#f4f5f7;color:#1c2230;font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;padding:24px}');
  H.push('.wrap{max-width:880px;margin:0 auto;background:#fff;border:1px solid #e3e6ea;border-radius:14px;padding:30px 34px;box-shadow:0 1px 4px rgba(0,0,0,.04)}');
  H.push('h1{font-size:23px;margin:0 0 2px}.meta{color:#6b7280;font-size:13px;margin-bottom:20px}');
  H.push('h2{font-size:17px;margin:30px 0 8px;border-top:1px solid #eef0f3;padding-top:22px}');
  H.push('.lead{font-size:14px;color:#4b5563;margin:2px 0 14px}');
  H.push('.hero{border-radius:12px;padding:18px 22px;margin:18px 0;font-size:17px}');
  H.push('.hero.need{background:#fff1f0;border:1px solid #ffccc7}.hero.ok{background:#f0fbf2;border:1px solid #c6eccf}');
  H.push('.hero b{font-size:30px;display:inline-block;vertical-align:-3px}');
  H.push('.hero.need b{color:#cf1322}.hero.ok b{color:#237804}');
  H.push('.stats{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0 4px}');
  H.push('.stat{background:#f7f8fa;border:1px solid #eceef1;border-radius:9px;padding:9px 15px;min-width:96px}');
  H.push('.stat .n{font-size:21px;font-weight:700}.stat .l{font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.4px}');
  H.push('table{border-collapse:collapse;width:100%;margin:6px 0 18px;font-size:13.5px}');
  H.push('th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #eef0f3;vertical-align:top}');
  H.push('th{color:#6b7280;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.4px;background:#fafbfc}');
  H.push('td.num{color:#9aa1ad;width:30px}.file{font-weight:600;color:#111827;word-break:break-word}');
  H.push('.path{color:#8a909c;font-size:11.5px;word-break:break-all}');
  H.push('.item{padding:9px 0;border-bottom:1px solid #eef0f3}');
  H.push('.row1{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}');
  H.push('.idx{color:#9aa1ad;font-weight:600;min-width:18px}');
  H.push('.item .file{font-weight:600;color:#111827;word-break:break-word}');
  H.push('.item .path{margin:3px 0 0 26px;font-size:12px}');
  H.push('.cat{font-weight:700;color:#1c2230;margin:20px 0 4px;font-size:14px}');
  H.push('.badge{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11px;font-weight:600}');
  H.push('.badge.hot{background:#fff1f0;color:#cf1322;border:1px solid #ffccc7}.badge.x{background:#eef1f4;color:#4b5563}');
  H.push('pre.copy{background:#f7f8fa;border:1px solid #e3e6ea;border-radius:9px;padding:14px;font-size:12.5px;white-space:pre-wrap;word-break:break-all;user-select:all;color:#1c2230}');
  H.push('details{margin:8px 0;border:1px solid #eef0f3;border-radius:9px;padding:4px 12px}summary{cursor:pointer;color:#374151;padding:8px 0;font-weight:600;font-size:13.5px}');
  H.push('.foot{margin-top:26px;color:#9aa1ad;font-size:11.5px;border-top:1px solid #eef0f3;padding-top:14px}');
  H.push('.bar{display:flex;align-items:center;gap:12px;margin:0 0 14px}');
  H.push('.bar button{cursor:pointer;font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:#fff;background:#2b6cb0;border:0;border-radius:8px;padding:9px 16px}');
  H.push('.bar button:hover{background:#2459a0}.bar .hint{color:#6b7280;font-size:12px}');
  H.push('.bar button.sec{background:#eef1f4;color:#1c2230}.bar button.sec:hover{background:#e2e6ea}');
  H.push('.lngsw{display:inline-flex;border:1px solid #d6dae0;border-radius:8px;overflow:hidden;margin-right:4px}');
  H.push('.lng{cursor:pointer;border:0;background:#fff;color:#4b5563;font:600 12px -apple-system,Segoe UI,sans-serif;padding:9px 13px}');
  H.push('.lng.on{background:#2b6cb0;color:#fff}');
  // PRINT/PDF = only the essentials (hero + stats + Files to send). Hide reference lists & screen-only blocks.
  H.push('@page{size:A4 portrait;margin:14mm}');
  H.push('@media print{.noprint{display:none!important}details{display:none!important}body{background:#fff;padding:0}.wrap{border:0;box-shadow:none;max-width:100%;border-radius:0;padding:0}}');
  H.push('</style></head><body><div class="wrap">');

  H.push('<h1>🎬 ' + t('Медиа-отчёт', 'Media Status Report') + '</h1>');
  H.push('<div class="meta"><b>' + esc(result.project && result.project.name) + '</b> &middot; ' +
    esc((result.generatedAt || '').replace('T', ' ').replace(/\..+/, ' UTC')) +
    ' &middot; ' + t('Таймлайн', 'Timeline') + ': ' + esc(result.scopeLabel) +
    (result.build ? ' &middot; build ' + esc(result.build) : '') + '</div>');
  H.push('<div class="bar noprint">' +
    '<span class="lngsw"><button class="lng on" data-l="ru" onclick="setLang(\'ru\')">Рус</button>' +
    '<button class="lng" data-l="en" onclick="setLang(\'en\')">Eng</button></span>' +
    '<button onclick="docShare()">📤 ' + t('Отправить', 'Send') + '</button>' +
    '<button class="sec" onclick="window.print()">🖨 ' + t('Сохранить PDF', 'Save PDF') + '</button>' +
    '<button class="sec" onclick="docCopy()">📋 ' + t('Скопировать список', 'Copy list') + '</button>' +
    '<span class="hint">' + t('или перетащите файл в Telegram', 'or drag this file into Telegram') + '</span></div>');

  // hero
  if (needCount) {
    H.push('<div class="hero need"><b>' + needCount + '</b> &nbsp;' +
      t('файл(ов) с этого таймлайна отсутствуют на этом компьютере.', 'file(s) used in this timeline are missing on this computer.') +
      '<br><span class="lead" style="margin:6px 0 0">' +
      t('Пришлите, пожалуйста, именно эти файлы — чтобы пересобрать и доделать проект.', 'Please send exactly the files listed below so the project can be relinked and finished.') +
      '</span></div>');
  } else {
    H.push('<div class="hero ok"><b>✓</b> &nbsp;' +
      t('Все медиа с этого таймлайна на месте — присылать ничего не нужно.', 'All media used in this timeline is present. Nothing to request.') + '</div>');
  }

  // stats
  H.push('<div class="stats">');
  H.push('<div class="stat"><div class="n" style="color:#cf1322">' + needCount + '</div><div class="l">' + t('Нужно прислать', 'Files needed') + '</div></div>');
  H.push('<div class="stat"><div class="n" style="color:#237804">' + present.length + '</div><div class="l">' + t('Есть', 'Present') + '</div></div>');
  H.push('<div class="stat"><div class="n">' + offlineUnused.length + '</div><div class="l">' + t('Нет, не нужны', 'Missing (unused)') + '</div></div>');
  H.push('<div class="stat"><div class="n">' + (c.total || 0) + '</div><div class="l">' + t('Всего медиа', 'Media total') + '</div></div>');
  H.push('</div>');

  // ── Самодостаточность + схема «где и сколько файлов лежит» ──
  var scRoot = (result.project && result.project.path || '').replace(/\\/g, '/').replace(/\/+$/, '');
  function scRel(p) { p = String(p || '').replace(/\\/g, '/'); return (scRoot && p.indexOf(scRoot + '/') === 0) ? p.slice(scRoot.length + 1) : null; }
  var scExternal = present.filter(function (i) { return scRel(i.mediaPath) === null; });
  var scInside = present.length - scExternal.length;
  var scOk = scExternal.length === 0 && needCount === 0;
  var folderN = {};
  present.forEach(function (i) {
    var r = scRel(i.mediaPath);
    var key = (r === null) ? '__EXT__' : (r.split('/').slice(0, -1).join('/') || '(root)');
    folderN[key] = (folderN[key] || 0) + 1;
  });
  // self-containment banner
  if (scOk) {
    H.push('<div class="hero ok" style="margin-top:8px"><b>📦</b> &nbsp;' +
      t('Проект самодостаточен — все ' + scInside + ' медиафайлов лежат ВНУТРИ папки проекта.',
        'Self-contained — all ' + scInside + ' media files live INSIDE the project folder.') + '</div>');
  } else if (scExternal.length) {
    H.push('<div class="hero need" style="margin-top:8px"><b>' + scExternal.length + '</b> &nbsp;' +
      t('медиафайл(ов) лежат ВНЕ папки проекта (ссылка на соседний проект). Нажми «Make self-contained», чтобы перецепить внутрь.',
        'media file(s) live OUTSIDE the project folder (linked to a sibling project). Run “Make self-contained” to re-point inside.') + '</div>');
  }
  // folder schematic — where & how many files
  H.push('<h2>📂 ' + t('Где лежат файлы', 'Where the files live') + '</h2>');
  H.push('<p class="lead">' + t('Сколько медиафайлов проекта в каждой папке (' + scInside + ' внутри' +
    (scExternal.length ? (', ' + scExternal.length + ' снаружи') : '') + ').',
    'How many of the project’s media files are in each folder (' + scInside + ' inside' +
    (scExternal.length ? (', ' + scExternal.length + ' outside') : '') + ').') + '</p>');
  var scDirs = Object.keys(folderN).sort(function (a, b) {
    if (a === '__EXT__') return 1; if (b === '__EXT__') return -1; return a < b ? -1 : 1;
  });
  H.push('<div style="font-size:13px;border:1px solid #eef0f3;border-radius:9px;padding:6px 14px;margin:6px 0 18px">');
  scDirs.forEach(function (d) {
    var ext = d === '__EXT__';
    var depth = (ext || d === '(root)') ? 0 : d.split('/').length - 1;
    var lab = ext ? t('↗ вне папки проекта', '↗ outside the project folder') : ('📁 ' + esc(d));
    H.push('<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #f4f5f7' + (ext ? ';color:#cf1322;font-weight:600' : '') + '">' +
      '<span style="padding-left:' + (depth * 16) + 'px">' + lab + '</span>' +
      '<span style="color:#6b7280;font-weight:600">' + folderN[d] + '</span></div>');
  });
  H.push('</div>');

  // Files needed (the deliverable)
  H.push('<h2>📥 ' + t('Файлы к отправке', 'Files to send') + ' (' + needCount + ')</h2>');
  if (!needCount) {
    H.push('<p class="lead">' + t('Ничего — все клипы на таймлайне на месте. ✅', 'None — every clip on the timeline is present. ✅') + '</p>');
  } else {
    H.push('<p class="lead">' + t('Есть на таймлайне, но не найдены на этом компьютере. ×N — сколько раз клип используется.', 'Used in the timeline but not found on this machine. ×N = how many times each clip appears.') + '</p>');
    Object.keys(byCat).sort().forEach(function (cat) {
      var rows = byCat[cat].slice().sort(function (a, b) { return usedCount(b.usedIn) - usedCount(a.usedIn); });
      H.push('<div class="cat">' + t(RU_CAT[cat] || cat, cat) + ' &middot; ' + rows.length + '</div>');
      rows.forEach(function (i, idx) {
        var n = usedCount(i.usedIn);
        var badge = n >= 10 ? '<span class="badge hot">×' + n + ' heavy</span>' : '<span class="badge x">×' + n + '</span>';
        H.push('<div class="item"><div class="row1"><b class="idx">' + (idx + 1) + '.</b> <span class="file">' +
          esc(i.name) + '</span> ' + badge + '</div><div class="path">' + esc(i.mediaPath) + '</div></div>');
      });
    });
    // copy-paste plain list (screen only — hidden in PDF/print)
    H.push('<div class="noprint"><div class="lead" style="margin-top:14px"><b>' + t('Список для копирования', 'Copy-paste list') + '</b> ' + t('(клик — выделить всё)', '(click to select all)') + ':</div>');
    H.push('<pre class="copy">' + action.map(function (i) {
      return esc(i.name) + '   —   ' + esc(i.mediaPath);
    }).join('\n') + '</pre></div>');
  }

  // Missing but unused
  H.push('<details><summary>' + t('Нет, но НЕ используются — можно игнорировать', 'Missing but NOT used in this timeline — you can ignore these') + ' (' + offlineUnused.length + ')</summary>');
  if (offlineUnused.length) {
    offlineUnused.sort(function (a, b) { return a.name < b.name ? -1 : 1; }).forEach(function (i) {
      H.push('<div class="item"><span class="file">' + esc(i.name) + '</span><div class="path">' + esc(i.mediaPath) + '</div></div>');
    });
  } else { H.push('<p class="lead">' + t('Нет.', 'None.') + '</p>'); }
  H.push('</details>');

  // Present
  H.push('<details><summary>' + t('Есть на этом компьютере — OK', 'Present on this computer — OK') + ' (' + present.length + ')</summary>');
  if (present.length) {
    present.sort(function (a, b) { return a.name < b.name ? -1 : 1; }).forEach(function (i) {
      H.push('<div class="item"><span class="file">' + esc(i.name) + '</span><div class="path">' + esc(i.mediaPath) + '</div></div>');
    });
  } else { H.push('<p class="lead">' + t('Нет.', 'None.') + '</p>'); }
  H.push('</details>');

  // Fonts
  if ((result.fonts || []).length) {
    H.push('<details><summary>' + t('Шрифты', 'Fonts referenced') + ' (' + result.fonts.length + ')</summary>');
    H.push('<p class="lead">' + t('Определены приблизительно — сверь в диалоге Premiere «Resolve Fonts».', 'Parsed best-effort — verify in Premiere’s Resolve Fonts dialog.') + '</p>');
    H.push('<p>' + result.fonts.map(function (f) { return '<span class="badge x">' + esc(f) + '</span>'; }).join(' ') + '</p></details>');
  }

  H.push('<div class="foot">' + t(
    'Сгенерировано YTAI Project Doctor из открытого проекта Premiere. «Файлы к отправке» = медиа с анализируемого таймлайна, отсутствующие на этом компьютере.',
    'Generated by YTAI Project Doctor from the live Premiere project. “Files to send” = media on the analyzed timeline but missing on this computer.') + '</div>');
  H.push('</div>');
  // Language toggle + Share/Copy (run in the browser the report opens in). navigator.share → macOS share sheet (Telegram).
  H.push('<script>');
  H.push('var L="ru";');
  H.push('var SUM={ru:' + JSON.stringify(summaryRU) + ',en:' + JSON.stringify(summaryEN) + '};');
  H.push('var TITLE={ru:' + JSON.stringify('Медиа-отчёт — ' + projName) + ',en:' + JSON.stringify('Media report — ' + projName) + '};');
  H.push('function setLang(l){L=l;document.documentElement.lang=l;document.querySelectorAll(".i18n").forEach(function(e){var v=e.getAttribute("data-"+l);if(v!=null)e.textContent=v;});document.querySelectorAll(".lng").forEach(function(b){b.classList.toggle("on",b.getAttribute("data-l")===l);});}');
  H.push('function docCopy(){var s=SUM[L];if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(s).then(function(){alert(L==="en"?"Copied — paste into Telegram":"Скопировано — вставьте в Telegram");},function(){window.prompt("Copy:",s);});}else{window.prompt("Copy:",s);}}');
  H.push('function docShare(){var s=SUM[L];if(navigator.share){navigator.share({title:TITLE[L],text:s}).catch(function(e){if(e&&e.name==="AbortError")return;docCopy();});}else{docCopy();}}');
  H.push('</script>');
  H.push('</body></html>');
  return H.join('\n');
}

module.exports = { buildDoctorHtml: buildDoctorHtml, buildDoctorJson: buildDoctorJson, categorize: categorize };
