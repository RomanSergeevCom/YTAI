/**
 * Sync Spread — независимая сверка нашего синхрона родной командой Premiere.
 *
 * Модуль чистый: ни UXP, ни файлов. Тестируется под node.
 *
 * Поток:
 *   1. planSpread()  — разложить источники сцены по одному на дорожку, на сырых
 *      wall-clock позициях плюс преролл 30 с (чтобы Synchronize мог двигать
 *      клип ВЛЕВО, а не упираться в ноль), с квантованием к кадровой сетке.
 *   2. chooseSyncItems() — какие айтемы таймлайна выделить. Выделение ставит
 *      ПАНЕЛЬ (`Sequence.setSelection`), а не ⌘A.
 *   3. Человек жмёт Clip → Synchronize → Audio.
 *   4. collectDeltas() — куда Premiere подвинул каждый источник. Из дельты
 *      вычитается медиана по опорным клипам: общий сдвиг синхронно пуст.
 *   5. applyDeltasToIngest() — сложить ОСТАТКИ в wall_offset и пересобрать сцену
 *      обычным сборщиком. Раскладка одноразовая.
 *
 * ⚠️ Что здесь знание, а что — фольклор.
 * ЗНАНИЕ (измерено на YTUVIE01 24.09.2026): преднагрев дорожек сеет по
 * однокадровому огрызку на КАЖДУЮ дорожку, и в `_SYNC` их оказалось 30 при нуле
 * настоящих клипов; пакетный компаунд выполняет действия в обратном порядке;
 * вставка округляет позицию до кадра; таргетинг дорожек хранится в `.prproj`
 * как `MZ.TrackTargeted`, и у дорожек, рождённых вставкой, его нет вовсе.
 * ФОЛЬКЛОР: само правило «не больше одного выделенного клипа на дорожку» взято
 * из 18-секундного ролика (HANDOFF_audio_sync.md:37-49), у Adobe источника нет;
 * требование таргетинга — с форумов. Раскладка устроена так, чтобы оба условия
 * выполнялись по построению, но выдавать их за документированные нельзя.
 *
 * ⚠️ Разрешение всей петли — КАДР (40 мс при 25p), потому что и вставка, и наши
 * позиции квантованы. Численный синхрон (finesync + 0113 + pair_check) держит
 * 13,2 мс. Поэтому Collect сначала отчитывается и пишет только по явному
 * подтверждению: иначе эта кнопка способна лишь ухудшить хороший ингест.
 *
 * Public API:
 *   - planSpread(sceneClips, txStrips, opts) → { placements, manifest, warnings }
 *   - assertSpreadContract(manifest, opts) → true | throws L1..L9
 *   - matchItem(want, actualItems) → айтем | null   (зеркало sync_verdict.match)
 *   - chooseSyncItems(manifest, actualItems, opts) → { chosen, missing, ... }
 *   - collectDeltas(manifest, actualItems, opts) → { clips, txFiles, base, raw, ... }
 *   - applyDeltasToIngest(ingest, scene, deltas, nowIso, opts) → { ingest, applied, ... }
 */

const DEFAULT_PREROLL_SEC = 30;
const MIN_DELTA_SEC = 0.002; // below this = jitter/no move, ignore

/**
 * Anything shorter than this on a spread track is pre-warm debris, not a clip.
 * Same threshold as prproj_verify.MIN_ITEM and sync_verdict.load_actual — the
 * three must never drift apart.
 */
const MIN_SYNC_ITEM_SEC = 0.2;

/** Total tracks a spread may ask Premiere for (L9 — counted on TRACKS, not clips). */
const MAX_SPREAD_TRACKS = 40;

/**
 * Which sources are a SYNC reference and which are merely SHOWN on screen.
 *
 * ⚠️ Решает `sync_source`, а не имя камеры. Ингесты YTCH-эпохи зовут камеры
 * `FX3`/`DJI` без префикса `CAM-`, и фильтр по имени выбросил бы из раскладки
 * вообще всё. А вот `sync_source` пишет тот, кто ставил клип: `lesson_start`
 * (экран, положен человеком от начала урока) и `shown_on_screen` (ролик-пример,
 * место измерено по звуку комнаты) — это ПОКАЗ, а не опора синхрона.
 */
const SHOWN_SYNC_SOURCES = new Set(['lesson_start', 'shown_on_screen']);

function defaultRoleOf(clip) {
  if (clip && SHOWN_SYNC_SOURCES.has(String(clip.sync_source || ''))) return 'shown';
  return 'sync';
}

/** Snap to the sequence frame grid. Premiere rounds insert positions anyway. */
function quantize(sec, fps) {
  if (!fps || !isFinite(fps) || fps <= 0) return sec;
  return Math.round(sec * fps) / fps;
}

/**
 * Plan the spread sequence for one scene.
 *
 * Two shapes:
 *   mode 'video' (legacy) — every clip on its own V/A pair, lav files on trailing
 *      A-tracks. Kept for old sessions and for the FCPXML bypass.
 *   mode 'bench' (стенд) — та же геометрия, но: в раскладку идут ТОЛЬКО опоры
 *      синхрона, позиции квантованы к сетке, а манифест несёт роли.
 *
 * ⚠️ Стенд НЕ кладёт камеры audio-only, хотя это и выглядело заманчиво
 * (аудиодорожки таргетируются пресетом, видео — нет). Проверено на YTUVIE01
 * 24.09: `createInsertProjectItemAction(item, t, -1, aIdx, …)` подавляет видео
 * только у настоящих аудиофайлов. У A/V-клипа Premiere всё равно кладёт видео —
 * и кладёт ВСЁ на V1: получилось 19 айтемов на одной дорожке, обрывки по 0,04 с
 * и куски, расталканные рипплом на 2100+ с. А камерный клип A/V-связан, так что
 * выделение звука тянет за собой его видео — и Synchronize гаснет по тому же
 * правилу «один клип на дорожку». Поэтому каждому клипу нужна СВОЯ видеодорожка.
 *
 * Positions are RAW wall-clock plus a uniform preroll, then snapped to the frame
 * grid. ⚠️ Квантуем сразу и в манифест пишем УЖЕ квантованное: вставка всё равно
 * округляет позицию к ближайшему кадру (замерено YTCH13, 28/28), и если хранить
 * запрошенное, дельта Collect-а вберёт в себя наше же округление — до ±20 мс при
 * 25p, против 13,2 мс, которые уже достигнуты численно.
 *
 * @param {Array<Object>} sceneClips - v2.0 ingest clips of ONE scene
 * @param {Array<Object>} txStrips - lav files, WHOLE. Подавать tx_strips_source
 *        (срезы урока с измеренным wall_offset), а НЕ tx_strips: те после 0113
 *        уже рендер, у них wall_offset 0 и поправка запечена в звук.
 * @param {Object} [opts]  { preroll?, mode?, fps?, roleOf?, maxTracks? }
 * @returns {{ placements: Array<Object>, manifest: Object, warnings: Array<Object> }}
 */
function planSpread(sceneClips, txStrips = [], opts = {}) {
  const preroll = typeof opts.preroll === 'number' ? opts.preroll : DEFAULT_PREROLL_SEC;
  const mode = (opts.mode === 'bench' || opts.mode === 'audio') ? 'bench' : 'video';
  const fps = typeof opts.fps === 'number' && opts.fps > 0 ? opts.fps : null;
  const roleOf = typeof opts.roleOf === 'function' ? opts.roleOf : defaultRoleOf;
  const warnings = [];

  let clips = (sceneClips || []).filter(c => typeof c.wall_offset === 'number');
  const strips = (txStrips || []).filter(t => typeof t.wall_offset === 'number');
  if (clips.length !== (sceneClips || []).length) {
    warnings.push({ type: 'clips_without_offset', count: (sceneClips || []).length - clips.length });
  }
  if (strips.length !== (txStrips || []).length) {
    warnings.push({ type: 'strips_without_offset', count: (txStrips || []).length - strips.length });
  }

  // L6 — в звуковой стенд идут ТОЛЬКО опоры синхрона. Экран коррелирует со
  // студийным звуком на r≈0,23, а место роликов измерено GCC-PHAT с разбросом
  // 0,0–0,8 мс: Synchronize сдвинет их по шуму, и Collect перепишет
  // субмиллиметровое измерение кадровой догадкой. Исключённые НЕ пропадают
  // молча — они в warnings, и Collect держит их на месте вычитанием base.
  if (mode === 'bench') {
    const shown = clips.filter(c => roleOf(c) === 'shown');
    if (shown.length) {
      warnings.push({
        type: 'excluded_shown',
        count: shown.length,
        ids: shown.map(c => c.clip_id || c.filename),
      });
      clips = clips.filter(c => roleOf(c) !== 'shown');
    }
  }

  if (clips.length + strips.length === 0) {
    return { placements: [], manifest: null, warnings: warnings.concat([{ type: 'empty_scene' }]) };
  }

  const t0 = Math.min(
    ...clips.map(c => c.wall_offset),
    ...strips.map(t => t.wall_offset)
  );

  const placements = [];
  const items = [];
  const bench = mode === 'bench';

  clips
    .slice()
    .sort((a, b) => a.wall_offset - b.wall_offset)
    .forEach((c, i) => {
      const offsetSec = quantize(c.wall_offset - t0 + preroll, fps);
      placements.push({
        kind: 'video',
        clipId: c.clip_id || c.filename,
        filename: c.filename,
        // путь нужен вызывающему: файл может быть на диске, но ещё не в проекте
        path: c.path || null,
        cam: c.cam || '',
        role: roleOf(c),
        // ⚠️ Своя видеодорожка обязательна: audio-only вставка A/V-клипа
        // не работает, видео всё равно ляжет — и всё на V1.
        vIdx: i,
        aIdx: i,
        offsetSec,
        duration: c.duration,
      });
      items.push({
        id: c.clip_id || c.filename,
        kind: 'clip',
        filename: c.filename,
        cam: c.cam || '',
        role: roleOf(c),
        trackType: 'video',
        trackIdx: i,
        placedSec: offsetSec,
        duration: c.duration,
      });
    });

  const txBase = clips.length;
  strips
    .slice()
    .sort((a, b) => a.wall_offset - b.wall_offset)
    .forEach((t, j) => {
      const offsetSec = quantize(t.wall_offset - t0 + preroll, fps);
      placements.push({
        kind: 'txfull',
        txId: t.tx || 'TX',
        filename: t.filename,
        path: t.path || null,
        cam: t.tx || 'TX',
        role: 'sync',
        vIdx: -1,
        aIdx: txBase + j,
        offsetSec,
        duration: t.duration,
      });
      items.push({
        id: t.filename,
        kind: 'tx',
        filename: t.filename,
        cam: t.tx || 'TX',
        role: 'sync',
        trackType: 'audio',
        trackIdx: txBase + j,
        placedSec: offsetSec,
        duration: t.duration,
      });
    });

  const manifest = {
    version: bench ? 2 : 1,
    mode,
    fps,
    preroll,
    t0Wall: t0,
    nVideoTracks: clips.length,
    nAudioTracks: clips.length + strips.length,
    items,
  };

  return { placements, manifest, warnings };
}

/**
 * Контракт раскладки. Инварианты L1–L9 из плана; бросает с НАЗВАНИЕМ инварианта.
 *
 * Зовётся сразу после planSpread — до любого обращения к Premiere, — и ещё раз
 * над манифестом, прочитанным с диска: он мог быть написан прошлой версией или
 * вообще другим инструментом (`spread_fcpxml.py` пишет в тот же файл).
 *
 * @param {Object} manifest
 * @param {Object} [opts] { maxTracks?: number }
 * @throws {Error}
 */
function assertSpreadContract(manifest, opts = {}) {
  const maxTracks = typeof opts.maxTracks === 'number' ? opts.maxTracks : MAX_SPREAD_TRACKS;
  if (!manifest || !Array.isArray(manifest.items) || manifest.items.length === 0) {
    throw new Error('L0: empty spread manifest');
  }
  const items = manifest.items;

  // L1 — не больше одного айтема на дорожку
  const perTrack = {};
  for (const it of items) {
    const k = it.trackType + ':' + it.trackIdx;
    (perTrack[k] = perTrack[k] || []).push(it.id);
  }
  const clash = Object.keys(perTrack).filter(k => perTrack[k].length > 1);
  if (clash.length) {
    throw new Error('L1: several sources assigned to track ' + clash[0] + ': '
      + perTrack[clash[0]].join(', '));
  }

  // L2 — преролл: Synchronize должен мочь двигать клип ВЛЕВО от нуля
  const minPlaced = Math.min(...items.map(i => i.placedSec));
  if (!(minPlaced > 0)) {
    throw new Error('L2: the earliest source sits at ' + minPlaced
      + ' s — Premiere cannot move it left of zero, a pre-roll is required');
  }

  // L3 — индексы плотные.
  // ⚠️ Видео идёт с нуля, а аудио — с номера, равного числу видеоайтемов: у
  // камерного клипа звук ложится на A с индексом его же V-дорожки, отдельным
  // айтемом манифеста он не описан, но дорожку занимает. Петлички начинаются
  // сразу за ними. Проверка «аудио тоже с нуля» ловила бы здоровую раскладку.
  const nV = items.filter(i => i.trackType === 'video').length;
  const vIdx = items.filter(i => i.trackType === 'video').map(i => i.trackIdx).sort((a, b) => a - b);
  for (let k = 0; k < vIdx.length; k++) {
    if (vIdx[k] !== k) {
      throw new Error('L3: gap in video track indices: expected ' + k + ', got ' + vIdx[k]);
    }
  }
  const aIdx = items.filter(i => i.trackType === 'audio').map(i => i.trackIdx).sort((a, b) => a - b);
  for (let k = 0; k < aIdx.length; k++) {
    if (aIdx[k] !== nV + k) {
      throw new Error('L3: gap in audio track indices: expected ' + (nV + k)
        + ', got ' + aIdx[k]);
    }
  }

  // L4 — счётчики сходятся с содержимым. Аудиодорожек столько, сколько звуковых
  // айтемов ПЛЮС по одной на каждый камерный клип (его собственный звук).
  const nA = items.filter(i => i.trackType === 'audio').length;
  if (manifest.nAudioTracks !== nV + nA || manifest.nVideoTracks !== nV) {
    throw new Error('L4: manifest counts V' + manifest.nVideoTracks + '/A' + manifest.nAudioTracks
      + ' do not match the content: video ' + nV + ', audio items ' + nA
      + ' → expected V' + nV + '/A' + (nV + nA));
  }

  // L5 — каждый источник пересекается хотя бы с одним другим по времени.
  // ⚠️ Источник, не пересекающийся ни с чем, Synchronize просто не тронет, и
  // вердикт покажет «0 мс» — неотличимо от идеального совпадения.
  const withDur = items.filter(i => typeof i.duration === 'number');
  const lonely = withDur.filter(a => !withDur.some(b => b !== a
    && Math.min(a.placedSec + a.duration, b.placedSec + b.duration) - Math.max(a.placedSec, b.placedSec) > 0));
  if (lonely.length) {
    throw new Error('L5: overlap nothing: ' + lonely.map(i => i.id).join(', ')
      + ' — Synchronize will not touch them and the verdict would show a false zero');
  }

  // L7 — filename уникален внутри типа дорожек (запасная ветка matchItem иначе
  // привяжет не тот айтем)
  for (const type of ['video', 'audio']) {
    const names = items.filter(i => i.trackType === type).map(i => i.filename);
    const dup = names.find((n, k) => names.indexOf(n) !== k);
    if (dup) throw new Error('L7: name "' + dup + '" appears twice among ' + type + ' tracks');
  }

  // L9 — лимит считается по ДОРОЖКАМ, а не по клипам: сцена из 10 клипов и 30
  // петличек прошла бы проверку на клипах и родила 40 дорожек.
  const total = (manifest.nVideoTracks || 0) + (manifest.nAudioTracks || 0);
  if (total > maxTracks) {
    throw new Error('L9: the spread needs ' + total + ' tracks, the limit is ' + maxTracks
      + ' — use Fine Sync');
  }
  return true;
}

/**
 * Compare actual (post-Synchronize) positions with the manifest.
 *
 * Matching is by filename first (Synchronize moves items but never renames or
 * re-tracks them; filename is unique per source by pipeline contract), with
 * track index as a tie-breaker when the same file appears on several tracks
 * (a lav file spread once cannot, but be defensive).
 *
 * @param {Object} manifest - from planSpread()
 * @param {Array<Object>} actualItems - [{ filename, trackType, trackIdx, startSec }]
 * @param {Object} [opts]  { minDelta?: number }
 * @returns {{ clips: Object, txFiles: Object, moved: number, maxAbsSec: number, missing: Array<string> }}
 */
function matchItem(want, actualItems) {
  // candidates: same filename, prefer same trackType+trackIdx. A spread A/V
  // clip appears TWICE (video item + its linked audio item share the name),
  // so after the exact miss fall back to a same-trackType UNIQUE match —
  // that recovers a clip the user dragged to another track without ever
  // confusing the video part with its own audio twin.
  //
  // ⚠️ ЕДИНСТВЕННОЕ место этого правила. sync_verdict.match() — его зеркало на
  // Python; расходиться им нельзя, иначе Select выделит одно, а Collect соберёт
  // другое, и никто этого не заметит.
  const byName = actualItems.filter(a => a.filename === want.filename);
  let hit = byName.find(a => a.trackType === want.trackType && a.trackIdx === want.trackIdx);
  if (!hit) {
    const sameType = byName.filter(a => a.trackType === want.trackType);
    if (sameType.length === 1) hit = sameType[0];
  }
  return hit || null;
}

function median(nums) {
  if (!nums.length) return 0;
  const s = nums.slice().sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function collectDeltas(manifest, actualItems, opts = {}) {
  const minDelta = typeof opts.minDelta === 'number' ? opts.minDelta : MIN_DELTA_SEC;
  const raw = [];
  const missing = [];

  for (const want of manifest.items) {
    const actual = matchItem(want, actualItems);
    if (!actual) {
      missing.push(want.id);
      continue;
    }
    raw.push({ want, delta: actual.startSec - want.placedSec });
  }

  // ⚠️ Synchronize равняет ВСЁ по одному опорному клипу, поэтому одинаковый сдвиг
  // всех источников сам по себе пуст: смысл несёт только разброс. Вычитаем медиану
  // по опорным клипам — ровно то, что делает sync_verdict.py:140. Без вычитания
  // источники, которых в раскладке НЕТ (экран, ролики), уезжают относительно камер
  // на всю величину base при каждом Collect.
  const camDeltas = raw
    .filter(r => r.want.kind === 'clip' && (r.want.role || 'sync') === 'sync')
    .map(r => r.delta);
  let base = median(camDeltas.length ? camDeltas : raw.map(r => r.delta));

  // ⚠️ База ОБЯЗАНА лежать на кадровой сетке. Premiere кладёт клипы только на
  // целые кадры, поэтому все дельты кратны кадру — а медиана при чётном числе
  // источников встаёт МЕЖДУ двумя значениями. На YTUVIE01 сцена 01 дала базу
  // 20 мс, ровно полкадра: величину, которой нет ни у одного клипа. Вычитание
  // такой базы сдвинуло бы КАЖДЫЙ клип на полкадра — измерение, которого не
  // было. Это та же ошибка, ради отказа от которой писался pair_check
  // («шов в 233 мс выглядел бы сдвигом 116 мс — числом, которого в реальности
  // нет ни секунды»), и она приехала сюда вместе с формулой из sync_verdict.py.
  const gridFps = typeof opts.gridFps === 'number' ? opts.gridFps
    : (manifest && typeof manifest.fps === 'number' ? manifest.fps : null);
  if (gridFps && gridFps > 0) {
    const step = 1 / gridFps;
    base = Math.round(base / step) * step;
  }

  const clips = {};
  const txFiles = {};
  const rawById = {};
  let moved = 0;
  let maxAbsSec = 0;

  for (const r of raw) {
    let resid = r.delta - base;
    if (Math.abs(resid) < minDelta) resid = 0;
    if (resid !== 0) {
      moved++;
      if (Math.abs(resid) > maxAbsSec) maxAbsSec = Math.abs(resid);
    }
    rawById[r.want.id] = r.delta;
    if (r.want.kind === 'clip') clips[r.want.id] = resid;
    else txFiles[r.want.id] = resid;
  }

  return { clips, txFiles, base, raw: rawById, moved, maxAbsSec, missing };
}

/**
 * Какие айтемы таймлайна надо выделить, чтобы Synchronize не посерел.
 *
 * Панель ставит выделение сама (`Sequence.setSelection`), а не полагается на ⌘A:
 * ⌘A ловит и однокадровый мусор преднагрева, и тогда на дорожке оказывается два
 * выделенных айтема — конфигурация, при которой пункт меню гаснет.
 *
 * @param {Object} manifest - из planSpread()
 * @param {Array<{filename,trackType,trackIdx,startSec,durationSec,ref}>} actualItems
 * @param {Object} [opts] { minItemSec?, includeLinkedAudio? }
 * @returns {{chosen:Array, missing:string[], skippedShort:Array, perTrack:Object, maxPerTrack:number}}
 */
function chooseSyncItems(manifest, actualItems, opts = {}) {
  const minItem = typeof opts.minItemSec === 'number' ? opts.minItemSec : MIN_SYNC_ITEM_SEC;
  const linked = opts.includeLinkedAudio !== false;
  const all = actualItems || [];

  // ⚠️ Огрызки отсеиваем ДО сопоставления. Заглушка преднагрева носит имя того же
  // файла, что и настоящий клип (ровно случай RYA-FX3-1263), и при отборе после
  // сопоставления перехватила бы точное совпадение по (trackType, trackIdx) —
  // выделен оказался бы кадр мусора вместо клипа.
  const long = all.filter(a => typeof a.durationSec !== 'number' || a.durationSec >= minItem);
  const skippedShort = all.filter(a => typeof a.durationSec === 'number' && a.durationSec < minItem);

  const chosen = [];
  const missing = [];
  const perTrack = {};
  const take = (a) => {
    const k = (a.trackType === 'video' ? 'V' : 'A') + (a.trackIdx + 1);
    perTrack[k] = (perTrack[k] || 0) + 1;
    chosen.push(a);
  };

  for (const want of manifest.items) {
    const hit = matchItem(want, long);
    if (!hit) { missing.push(want.id); continue; }
    take(hit);
    // Звуковой близнец видеоклипа лежит на A с тем же индексом. Берём ЯВНО,
    // чтобы результат не зависел от переключателя Linked Selection.
    if (linked && want.kind === 'clip' && want.trackType === 'video') {
      const twin = long.find(a => a.filename === want.filename
        && a.trackType === 'audio' && a.trackIdx === want.trackIdx);
      if (twin) take(twin);
    }
  }

  const maxPerTrack = Object.keys(perTrack).reduce((m, k) => Math.max(m, perTrack[k]), 0);
  return { chosen, missing, skippedShort, perTrack, maxPerTrack };
}

/**
 * Fold collected deltas into a COPY of the ingest.
 *
 * Sign: Premiere moved the item to where it SHOULD be. An item that moved
 * right by +d starts later → wall_offset += d. After applying, the scene is
 * re-normalized so no wall_offset is negative (the builder throws on
 * negatives); the uniform shift is sync-neutral.
 *
 * @param {Object} ingest - full ingest JSON (not mutated)
 * @param {string} scene
 * @param {{ clips: Object, txFiles: Object }} deltas - from collectDeltas()
 * @param {string} nowIso - timestamp for fine_sync stamp
 * @returns {{ ingest: Object, applied: number, maxAbsSec: number, normalizedShift: number }}
 */
function applyDeltasToIngest(ingest, scene, deltas, nowIso, opts = {}) {
  // ⚠️ Порог записи. Вставка округляет позицию к БЛИЖАЙШЕМУ кадру (замерено
  // YTCH13, 28/28), значит любой остаток меньше кадра — это разрешение самого
  // измерения, а не рассинхрон. Численный синхрон уже держит 13,2 мс; писать
  // поверх него кадровую догадку значит ухудшать заведомо хорошее.
  const minWrite = typeof opts.minWriteSec === 'number' ? opts.minWriteSec : 0;
  // Refuse mixed scenes: a clip WITHOUT wall_offset (creation_time fallback)
  // cannot take part in the re-normalization shift, so it would silently end
  // up offset against every shifted source — the opposite of syncing. The
  // v2.0 wallclock contract requires wall_offset on every placeable clip, so
  // this only ever fires on legacy/broken ingests, where syncing is moot.
  const noOffset = (ingest.clips || []).filter(
    c => c.scene === scene && typeof c.wall_offset !== 'number');
  if (noOffset.length > 0) {
    throw new Error('applyDeltasToIngest: ' + noOffset.length + ' clip(s) in scene "' + scene
      + '" have no wall_offset — fix the ingest (0112) before collecting sync');
  }

  const out = JSON.parse(JSON.stringify(ingest));
  let applied = 0;
  let maxAbsSec = 0;
  const offsets = [];

  for (const clip of out.clips) {
    if (clip.scene !== scene) continue;
    const d = deltas.clips[clip.clip_id] !== undefined
      ? deltas.clips[clip.clip_id]
      : deltas.clips[clip.filename];
    if (typeof d === 'number' && d !== 0 && Math.abs(d) >= minWrite) {
      clip.wall_offset = Math.round((clip.wall_offset + d) * 10000) / 10000;
      clip.fine_sync = { corr: -d, method: 'premiere-synchronize' };
      applied++;
      if (Math.abs(d) > maxAbsSec) maxAbsSec = Math.abs(d);
    }
    if (typeof clip.wall_offset === 'number') offsets.push(clip.wall_offset);
  }
  // ⚠️ ПЕТЛИЧКИ НЕ ПИШЕМ. После 0113_frame_align.py `tx_strips` — это не записи
  // рекордера, а timeline-domain РЕНДЕРЫ (`…_timeline.wav`, wall_offset: 0),
  // собранные под текущую раскладку блоков. Сдвинуть им wall_offset значит молча
  // обесценить рендер: звук в файле останется на прежнем месте. Если остаток по
  // петличке велик — правильное действие «перегони 0112/0113», а не «подвинь число».
  const strips = (out.tx_strips && out.tx_strips[scene]) || [];
  const txReported = [];
  for (const tx of strips) {
    const d = deltas.txFiles[tx.filename];
    if (typeof d === 'number' && d !== 0) {
      txReported.push({ filename: tx.filename, resid: d });
    }
    if (typeof tx.wall_offset === 'number') offsets.push(tx.wall_offset);
  }

  // Re-normalize the scene: builder throws on negative wall_offset.
  // NOTE: the shift touches only sources WITH a numeric wall_offset. In the
  // v2.0 wallclock contract every placeable source has one (validate_ingest
  // fails otherwise), so the shift is uniform. A legacy clip relying on the
  // creation_time fallback would NOT be shifted — that ingest shape never
  // reaches the wallclock builder in the first place.
  let normalizedShift = 0;
  const minOff = offsets.length ? Math.min(...offsets) : 0;
  if (minOff < 0) {
    normalizedShift = -minOff;
    for (const clip of out.clips) {
      if (clip.scene === scene && typeof clip.wall_offset === 'number') {
        clip.wall_offset = Math.round((clip.wall_offset + normalizedShift) * 10000) / 10000;
      }
    }
    for (const tx of strips) {
      if (typeof tx.wall_offset === 'number') {
        tx.wall_offset = Math.round((tx.wall_offset + normalizedShift) * 10000) / 10000;
      }
    }
  }

  if (applied > 0) {
    out.fine_sync = Object.assign({}, out.fine_sync, {
      applied_at: nowIso,
      method: 'premiere-synchronize',
    });
  }

  return { ingest: out, applied, maxAbsSec, normalizedShift, txReported };
}

module.exports = {
  planSpread,
  assertSpreadContract,
  matchItem,
  chooseSyncItems,
  collectDeltas,
  applyDeltasToIngest,
  DEFAULT_PREROLL_SEC,
  MIN_SYNC_ITEM_SEC,
  MAX_SPREAD_TRACKS,
};
