/**
 * Adjustment Layer builder — "AL over selection" (NACGunner-style) + "AL over ranges".
 *
 * UXP CANNOT create an Adjustment Layer project item: verified against the official
 * @adobe/premierepro typings 26.5.0-beta.73 — there is no synthetic-item factory
 * (no bars/tone, black, matte, adjustment layer); the only "adjustment" API is the
 * read-only VideoClipTrackItem.isAdjustmentLayer() (25.6+). The layer therefore
 * comes from a DONOR ProjectItem that already exists in the project:
 *   1. preferred — the master template .prproj ships an item named "YTAI_ADJ"
 *      (create once by hand: File > New > Adjustment Layer, rename), so every
 *      project cloned from the template has it;
 *   2. fallback — importFiles() of a donor .prproj (opts.donorPrproj).
 *
 * Placement itself is proven panel machinery: selection bounds → ensureTracks →
 * setSourceInOut (trim donor source to the range length) → overwrite at exact
 * ticks (clipPlacer canon: overwrite passes positions through exactly, insert
 * rounds) → clearSourceInOut. Effects (Transform / Lumetri) are best-effort
 * add-ons via VideoFilterFactory; setting the Lumetri Look by param is UNPROVEN
 * on live builds (their param API exposes createSetValueAction, but whether the
 * Look accepts a string value must be tested empirically) — failures are logged,
 * never thrown.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

const clipActions = require('../shared/clipActions');
const { findProjectItemByName } = require('../shared/projectItemFinder');
const { removeAllItemsOnTrack } = require('../ingest/placement/sequenceFactory');

const TICKS_PER_SEC = 254016000000;
const DONOR_NAMES = ['YTAI_ADJ', 'Adjustment Layer'];

/** Seconds from a TickTime-ish object (live and mock both carry .seconds). */
function secondsOf(t) {
  if (!t) return 0;
  if (t.seconds !== undefined && t.seconds !== null) return Number(t.seconds);
  if (t.ticks !== undefined && t.ticks !== null) return Number(t.ticks) / TICKS_PER_SEC;
  if (t.ticksNumber !== undefined) return Number(t.ticksNumber) / TICKS_PER_SEC;
  return 0;
}

function tickTimeOfSeconds(sec) {
  return ppro.TickTime.createWithSeconds(sec);
}

/**
 * Bounds of the current timeline selection: earliest start, latest end, topmost
 * video track index holding a selected item, and the selected-video-item count.
 *
 * Track index comes from identity-scanning the sequence's video tracks (the
 * trackItem itself exposes no track index in 25.6/26.x), so cost is O(tracks).
 *
 * @returns {Promise<{startSec:number,endSec:number,topTrackIndex:number,count:number}|null>}
 *          null when nothing (or nothing usable) is selected.
 */
async function selectionBounds(sequence, logger) {
  let items = [];
  try {
    const sel = await sequence.getSelection();
    items = (sel && (await sel.getTrackItems())) || [];
  } catch (e) {
    if (logger) logger.warn('selectionBounds: getSelection failed: ' + e.message);
    return null;
  }
  if (!items.length) return null;

  let startSec = Infinity, endSec = -Infinity;
  const selectedSet = [];
  for (const it of items) {
    try {
      const s = secondsOf(await it.getStartTime());
      const d = secondsOf(await it.getDuration());
      // Audio items count toward bounds too — an A/V-linked selection should
      // still produce the full range even if only audio halves report cleanly.
      startSec = Math.min(startSec, s);
      endSec = Math.max(endSec, s + d);
      selectedSet.push(it);
    } catch (e) { /* skip unreadable item */ }
  }
  if (!isFinite(startSec) || endSec <= startSec) return null;

  // Topmost VIDEO track containing a selected item (identity match).
  let topTrackIndex = 0;
  try {
    const vCount = await sequence.getVideoTrackCount();
    for (let vi = 0; vi < vCount; vi++) {
      const track = await sequence.getVideoTrack(vi);
      let trackItems = null;
      try { trackItems = await track.getTrackItems(1, false); } catch (e) { /* no-arg */ }
      if (!trackItems) { try { trackItems = await track.getTrackItems(); } catch (e) { /* none */ } }
      if (!trackItems) continue;
      for (const ti of trackItems) {
        if (selectedSet.indexOf(ti) >= 0) { topTrackIndex = vi; break; }
      }
    }
  } catch (e) {
    if (logger) logger.warn('selectionBounds: track scan failed: ' + e.message);
  }

  return { startSec, endSec, topTrackIndex, count: selectedSet.length };
}

/**
 * Find the donor Adjustment Layer ProjectItem; optionally import a donor .prproj
 * when it is missing (then re-find). Returns the RAW ProjectItem or null.
 */
async function ensureDonorAdjustment(project, opts, logger) {
  const names = (opts && opts.donorNames) || DONOR_NAMES;
  for (const name of names) {
    const found = await findProjectItemByName(project, name, logger);
    if (found) return found;
  }
  const donorPaths = [].concat((opts && opts.donorPrproj) || []);
  for (const donorPrproj of donorPaths) {
    if (logger) logger.info('Donor ADJ not in project — importing ' + donorPrproj);
    try {
      await project.importFiles([donorPrproj], true, null, false);
    } catch (e) {
      if (logger) logger.error('Donor import failed: ' + e.message);
      continue;
    }
    for (const name of names) {
      const found = await findProjectItemByName(project, name, logger);
      if (found) return found;
    }
  }
  return null;
}

/**
 * Grow the sequence to vNeeded VIDEO tracks — SAFE for sequences that already
 * carry content. sequenceFactory.ensureTracks is NOT usable here: its sweep
 * removes items from EVERY track (Build-Ingest pre-warm semantics, empty
 * sequence assumed) — live it would eat the timeline whenever the track count
 * is short (caught by the lane-stacking test; the live YTCH13 run survived
 * only because enough tracks already existed).
 *
 * Mechanism per new track: 1-frame donor speck INSERTED with limitShift=true
 * (only the target track shifts — and it is new/empty), then the speck is
 * removed from THAT track only.
 */
async function growVideoTracks(project, sequence, seqEditor, donorItem, vNeeded, logger) {
  let vCurrent = await sequence.getVideoTrackCount();
  if (vCurrent >= vNeeded) return vCurrent;
  const cast = ppro.ClipProjectItem.cast(donorItem) || donorItem;
  clipActions.setSourceInOut(project, cast,
    tickTimeOfSeconds(0), tickTimeOfSeconds(0.04), 'track-grow speck', logger);
  const t0 = tickTimeOfSeconds(0);
  let guard = 0;
  while (vCurrent < vNeeded && guard++ < vNeeded + 4) {
    try {
      await project.lockedAccess(function () {
        return project.executeTransaction(function (ca) {
          ca.addAction(seqEditor.createInsertProjectItemAction(
            donorItem, t0, vNeeded - 1, -1, true));
        }, 'Grow video tracks');
      });
    } catch (e) {
      if (logger) logger.error('growVideoTracks insert failed: ' + e.message);
      break;
    }
    const newCount = await sequence.getVideoTrackCount();
    // Clean the speck(s) ONLY on freshly created tracks.
    for (let v = vCurrent; v < newCount; v++) {
      try {
        await removeAllItemsOnTrack(project, seqEditor,
          await sequence.getVideoTrack(v), 0 /* MediaType.VIDEO */, logger, 'grow V' + (v + 1));
      } catch (e) {
        if (logger) logger.warn('growVideoTracks cleanup V' + (v + 1) + ': ' + e.message);
      }
    }
    if (newCount <= vCurrent) break; // no progress — stop, overwrite will fail loudly
    vCurrent = newCount;
  }
  clipActions.clearSourceInOut(project, cast, 'track-grow speck', logger);
  if (vCurrent < vNeeded && logger) {
    logger.warn('growVideoTracks: only V' + vCurrent + ' of V' + vNeeded);
  }
  return vCurrent;
}

/**
 * Place ONE trimmed adjustment-layer instance over [startSec, endSec] on video
 * track vIdx. Mirrors clipPlacer's 3-transaction canon: trim donor source →
 * overwrite (exact position, never shifts) → clear donor trim.
 */
async function placeAdjustment(project, sequence, adjItem, startSec, endSec, vIdx, logger, ensure) {
  const seqEditor = ppro.SequenceEditor.getEditor(sequence);
  const durSec = endSec - startSec;
  const label = 'ADJ@' + startSec.toFixed(2) + 's+' + durSec.toFixed(2) + 's→V' + (vIdx + 1);

  // Overwrite does NOT auto-create tracks — grow them content-safely first.
  // Batch callers grow ONCE themselves and pass ensure=false.
  if (ensure !== false) {
    try {
      await growVideoTracks(project, sequence, seqEditor, adjItem, vIdx + 1, logger);
    } catch (e) {
      if (logger) logger.warn(label + ': growVideoTracks failed (' + e.message + ') — trying anyway');
    }
  }

  const cast = ppro.ClipProjectItem.cast(adjItem);
  const itemForTrim = cast || adjItem;

  // 1. Trim donor source to the range length (donor media starts at 0).
  clipActions.setSourceInOut(project, itemForTrim,
    tickTimeOfSeconds(0), tickTimeOfSeconds(durSec), label, logger);

  // 2. Overwrite at the exact start tick. Adjustment layer is video-only —
  //    audio index -1 (mirror of clipPlacer's audio-only "-1 video" pattern).
  let ok = false;
  try {
    await project.lockedAccess(function () {
      return project.executeTransaction(function (ca) {
        ca.addAction(seqEditor.createOverwriteItemAction(
          adjItem, tickTimeOfSeconds(startSec), vIdx, -1));
      }, 'Add adjustment layer');
    });
    ok = true;
  } catch (e) {
    if (logger) logger.error(label + ': overwrite failed: ' + e.message);
  }

  // 3. Clear donor trim so the next placement re-trims cleanly.
  clipActions.clearSourceInOut(project, itemForTrim, label, logger);

  if (!ok) return null;
  if (logger) logger.info('Added continuous adjustment layer ' + label);

  // Locate the placed trackItem (for optional effects): the item on vIdx whose
  // start is closest to startSec.
  try {
    const track = await sequence.getVideoTrack(vIdx);
    let items = null;
    try { items = await track.getTrackItems(1, false); } catch (e) { /* no-arg */ }
    if (!items) { try { items = await track.getTrackItems(); } catch (e) { /* none */ } }
    let best = null, bestDelta = Infinity;
    for (const ti of (items || [])) {
      const s = secondsOf(await ti.getStartTime());
      const delta = Math.abs(s - startSec);
      if (delta < bestDelta) { best = ti; bestDelta = delta; }
    }
    return best;
  } catch (e) {
    return null;
  }
}

/**
 * VideoClipTrackItem view of a track item. Live 26.x has NO
 * VideoClipTrackItem.cast static (measured YTCH13 18.08.2026: «cast is not a
 * function» — the same call sits in lutManager and silently fails there too);
 * items from getTrackItems(CLIP) already expose getComponentChain directly.
 * Older builds (and the test mock) still need the cast — try it, fall back.
 */
function asVideoClip(trackItem) {
  try {
    if (ppro.VideoClipTrackItem && typeof ppro.VideoClipTrackItem.cast === 'function') {
      const v = ppro.VideoClipTrackItem.cast(trackItem);
      if (v) return v;
    }
  } catch (e) { /* fall through to the raw item */ }
  return trackItem;
}

/**
 * Components of a chain across API generations: live 26.x exposes
 * getComponentCount()/getComponentAtIndex(i) (measured YTCH13 18.08.2026:
 * «getComponents is not a function»); the mock (and possibly older builds)
 * expose getComponents(). Defensive awaits — some builds return plain values.
 */
async function getChainComponents(chain) {
  if (typeof chain.getComponents === 'function') {
    return (await chain.getComponents()) || [];
  }
  const out = [];
  const count = await chain.getComponentCount();
  for (let i = 0; i < count; i++) {
    try { out.push(await chain.getComponentAtIndex(i)); } catch (e) { /* skip */ }
  }
  return out;
}

/** Display name of a component/param across API generations. */
async function readDisplayName(obj) {
  try {
    if (obj && typeof obj.getDisplayName === 'function') return String(await obj.getDisplayName());
  } catch (e) { /* fall through */ }
  return String((obj && (obj.displayName || obj.name)) || '');
}

/**
 * Does the trackItem's component chain contain an effect whose name includes
 * the substring? Returns true/false, or null when the chain is unreadable
 * (callers must NOT append on null — risk of duplicates).
 */
async function hasEffect(trackItem, displaySubstring, logger) {
  try {
    const vclip = asVideoClip(trackItem);
    const chain = await vclip.getComponentChain();
    const comps = await getChainComponents(chain);
    const needle = displaySubstring.toLowerCase();
    for (const comp of comps) {
      let n = await readDisplayName(comp);
      if (!n && comp && typeof comp.getMatchName === 'function') {
        try { n = String(await comp.getMatchName()); } catch (e) { /* none */ }
      }
      if (!n && comp && comp.matchName) n = String(comp.matchName);
      if (n.toLowerCase().indexOf(needle) >= 0) return true;
    }
    return false;
  } catch (e) {
    if (logger) logger.debug('hasEffect(' + displaySubstring + ') unreadable: ' + e.message);
    return null;
  }
}

/** Find a video filter matchName by display name substring (case-insensitive). */
async function findFilterMatchName(displaySubstring, logger) {
  try {
    const matchNames = await ppro.VideoFilterFactory.getMatchNames();
    const displayNames = await ppro.VideoFilterFactory.getDisplayNames();
    if (logger) logger.debug('VideoFilterFactory: ' + (matchNames && matchNames.length) + ' matchNames, '
      + (displayNames && displayNames.length) + ' displayNames (isArray=' + Array.isArray(displayNames) + ')');
    const needle = displaySubstring.toLowerCase();
    for (let i = 0; i < displayNames.length; i++) {
      if (String(displayNames[i]).toLowerCase().indexOf(needle) >= 0) {
        if (logger) logger.debug('Filter match: "' + displayNames[i] + '" → ' + matchNames[i]);
        return matchNames[i];
      }
    }
    if (logger) {
      const sample = [];
      for (let i = 0; i < displayNames.length && sample.length < 25; i++) {
        const dn = String(displayNames[i]);
        if (dn.toLowerCase().indexOf('lu') >= 0 || dn.toLowerCase().indexOf('color') >= 0
            || dn.toLowerCase().indexOf('transform') >= 0) sample.push(dn);
      }
      logger.warn('No display name contains "' + displaySubstring + '"; related names: '
        + (sample.join(' | ') || '(none)'));
    }
  } catch (e) {
    if (logger) logger.warn('findFilterMatchName(' + displaySubstring + '): ' + e.message);
  }
  return null;
}

/**
 * Append an effect to a placed trackItem and best-effort set ONE numeric/string
 * param by display name. Never throws — returns {applied, paramSet}.
 *
 * Param setting path (26.x docs): ComponentParam.createKeyframe(value) →
 * createSetValueAction(keyframe). The Lumetri "Look" param accepting a string is
 * EMPIRICALLY UNVERIFIED — treat paramSet:false as "apply by hand".
 */
async function applyEffect(project, trackItem, displayName, paramDisplayName, paramValue, logger) {
  const out = { applied: false, paramSet: false };
  if (!trackItem) { if (logger) logger.warn('applyEffect(' + displayName + '): no trackItem'); return out; }
  try {
    const matchName = await findFilterMatchName(displayName, logger);
    if (!matchName) { if (logger) logger.warn('Effect not found: ' + displayName); return out; }
    let component;
    try {
      component = await ppro.VideoFilterFactory.createComponent(matchName);
    } catch (e) {
      if (logger) logger.warn(displayName + ': createComponent failed: ' + e.message);
      return out;
    }
    const vclip = asVideoClip(trackItem);
    let chain;
    try {
      chain = await vclip.getComponentChain();
    } catch (e) {
      if (logger) logger.warn(displayName + ': getComponentChain failed: ' + e.message
        + ' (cast=' + (vclip !== trackItem) + ')');
      return out;
    }
    await project.lockedAccess(function () {
      return project.executeTransaction(function (ca) {
        ca.addAction(chain.createAppendComponentAction(component));
      }, 'Apply ' + displayName);
    });
    out.applied = true;
    if (logger) logger.info('Effect applied: ' + displayName);

    if (paramDisplayName === undefined || paramDisplayName === null) return out;

    out.paramSet = await setEffectParam(
      project, trackItem, displayName, paramDisplayName, paramValue, logger);
  } catch (e) {
    if (logger) logger.warn('applyEffect(' + displayName + ') failed: ' + e.message);
  }
  return out;
}

/** Compact JSON for logs — never throws, truncates long values. */
function safeJson(v) {
  try {
    const s = JSON.stringify(v);
    return s === undefined ? String(v) : (s.length > 160 ? s.slice(0, 160) + '…' : s);
  } catch (e) { return String(v); }
}

/**
 * Set ONE param (by display name) on the LAST component whose name contains
 * displaySubstring. Safe to call repeatedly — re-setting the same value is a
 * no-op visually. Returns true when the set action executed.
 *
 * Every native call is step-tagged: a failure logs «failed @ <step>», so a
 * single live run pinpoints the exact API that threw (the 18.08 blocker:
 * «Illegal Parameter type» with no step info). Value-set order:
 *   A. getStartValue() → mutate keyframe.value(.value) → createSetValueAction —
 *      the canonical Adobe UXP-sample path; bypasses createKeyframe's own
 *      value-type validation and lets the probe log the param's REAL type.
 *   B. createKeyframe(value) → createSetValueAction — typings say createKeyframe
 *      THROWS on a value/param type mismatch (prime suspect for the blocker).
 */
async function setEffectParam(project, trackItem, displaySubstring, paramDisplayName, paramValue, logger) {
  let step = 'init';
  try {
    const vclip = asVideoClip(trackItem);
    step = 'getComponentChain';
    const chain = await vclip.getComponentChain();
    step = 'getChainComponents';
    const components = await getChainComponents(chain);
    if (!components.length) { if (logger) logger.warn(displaySubstring + ': chain empty'); return false; }
    step = 'readDisplayName(component)';
    let comp = null;
    const needle = displaySubstring.toLowerCase();
    for (const c of components) {
      // Same matching chain as hasEffect — displayName, then matchName
      // fallback (a chain readable only by matchName must not report
      // «Lumetri present» in the heal path and then «not in chain» here).
      let n = await readDisplayName(c);
      if (!n && c && typeof c.getMatchName === 'function') {
        try { n = String(await c.getMatchName()); } catch (e) { /* none */ }
      }
      if (!n && c && c.matchName) n = String(c.matchName);
      if (n.toLowerCase().indexOf(needle) >= 0) comp = c; // keep LAST match
    }
    if (!comp) { if (logger) logger.warn(displaySubstring + ': component not in chain'); return false; }
    step = 'getParamCount';
    const paramCount = await comp.getParamCount();
    const paramNames = [];
    let param = null, pname = '';
    for (let p = 0; p < paramCount; p++) {
      let cand = null, cname = '';
      try {
        cand = await comp.getParam(p);
      } catch (e) {
        paramNames.push('#' + p + '!');
        if (logger) logger.debug(displaySubstring + ': getParam(' + p + ') threw: ' + e.message);
        continue;
      }
      try { cname = await readDisplayName(cand); } catch (e) { /* keep '' */ }
      paramNames.push(cname || ('#' + p));
      if (cname && cname.toLowerCase() === String(paramDisplayName).toLowerCase()) {
        param = cand; pname = cname; // keep LAST match, mirror component rule
      }
    }
    if (!param) {
      if (logger) logger.warn(displaySubstring + ': param "' + paramDisplayName + '" not found among ['
        + paramNames.join(', ') + ']');
      return false;
    }
    if (typeof param.createSetValueAction !== 'function') {
      if (logger) logger.warn(displaySubstring + '.' + pname + ': param set API unavailable on this build');
      return false;
    }

    // Probe the CURRENT value — its runtime type is the ground truth for what
    // the param accepts (e.g. is Lumetri "Look" a string or a menu index?).
    step = 'getStartValue(' + pname + ')';
    let startKf = null;
    let preInner;
    try {
      if (typeof param.getStartValue === 'function') {
        startKf = await param.getStartValue();
        const v = startKf ? startKf.value : undefined;
        preInner = (v && typeof v === 'object' && 'value' in v) ? v.value : v;
        if (logger) logger.info(displaySubstring + '.' + pname + ' current: type=' + (typeof preInner)
          + ' value=' + safeJson(preInner) + ' kf.value=' + safeJson(v));
      } else if (logger) {
        logger.info(displaySubstring + '.' + pname + ': no getStartValue on this build');
      }
    } catch (e) {
      if (logger) logger.warn(displaySubstring + '.' + pname + ': getStartValue probe failed: ' + e.message);
      startKf = null;
    }

    // Path A: mutate the start keyframe (canonical UXP-sample pattern).
    if (startKf) {
      step = 'mutate-set(' + pname + ')';
      try {
        if (startKf.value && typeof startKf.value === 'object' && 'value' in startKf.value) {
          startKf.value.value = paramValue;
        } else {
          startKf.value = paramValue;
        }
        await project.lockedAccess(function () {
          return project.executeTransaction(function (ca) {
            ca.addAction(param.createSetValueAction(startKf, true));
          }, 'Set ' + pname);
        });
        // No-throw ≠ value landed (measured YTCH13 18.08 16:30: Look is a
        // NUMERIC menu index, the string «set» commits fine and readback stays
        // 0). Verify: success = readback equals what we wrote, or at least
        // moved off the pre-set value (normalisation, e.g. name → path).
        let verified = null; // null = could not read back, trust the commit
        try {
          if (typeof param.getStartValue === 'function') {
            const postKf = await param.getStartValue();
            const pv = postKf ? postKf.value : undefined;
            const postInner = (pv && typeof pv === 'object' && 'value' in pv) ? pv.value : pv;
            if (logger) logger.info(displaySubstring + '.' + pname + ' post-set readback: ' + safeJson(postInner));
            verified = (postInner === paramValue) || (postInner !== preInner);
          }
        } catch (e) { /* readback is best-effort */ }
        if (verified !== false) {
          if (logger) logger.info(displaySubstring + '.' + pname + ' = ' + paramValue + ' (start-keyframe path'
            + (verified === null ? ', unverified' : '') + ')');
          return true;
        }
        if (logger) logger.warn(displaySubstring + '.' + pname + ': set did NOT stick (readback unchanged)'
          + ' — param is a menu index, a string cannot select it; use the donor-clone path');
        if (typeof preInner === 'number' && typeof paramValue !== 'number') {
          return false; // type mismatch is terminal — createKeyframe would only throw
        }
      } catch (e) {
        if (logger) logger.warn(displaySubstring + '.' + pname + ': start-keyframe set failed: ' + e.message
          + ' — falling back to createKeyframe');
      }
    }

    // Path B: fresh keyframe from the raw value.
    if (typeof param.createKeyframe !== 'function') {
      if (logger) logger.warn(displaySubstring + '.' + pname + ': createKeyframe unavailable on this build');
      return false;
    }
    step = 'createKeyframe(' + pname + ')';
    const kf = param.createKeyframe(paramValue);
    step = 'setValueAction(' + pname + ')';
    await project.lockedAccess(function () {
      return project.executeTransaction(function (ca) {
        ca.addAction(param.createSetValueAction(kf, true));
      }, 'Set ' + pname);
    });
    if (logger) logger.info(displaySubstring + '.' + pname + ' = ' + paramValue + ' (createKeyframe path)');
    return true;
  } catch (e) {
    if (logger) logger.warn('setEffectParam(' + displaySubstring + ') failed @ ' + step + ': ' + e.message);
  }
  return false;
}

/**
 * NACGunner-style: one continuous adjustment layer over the CURRENT timeline
 * selection, on the first track above the topmost selected clip.
 *
 * @param {Object} project
 * @param {Object} opts { donorNames?, donorPrproj?, transformScale? (e.g. 101),
 *                        lumetriLook? (Creative Look name — EMPIRICAL) }
 * @param {Object} logger
 * @returns {Promise<{ok:boolean, reason?:string, startSec?, endSec?, vIdx?, count?,
 *                    transform?:{applied,paramSet}, lumetri?:{applied,paramSet}}>}
 */
async function addAdjustmentOverSelection(project, opts, logger) {
  opts = opts || {};
  const sequence = await project.getActiveSequence();
  if (!sequence) return { ok: false, reason: 'no-sequence' };

  const bounds = await selectionBounds(sequence, logger);
  if (!bounds) return { ok: false, reason: 'no-selection' };

  const adjItem = await ensureDonorAdjustment(project, opts, logger);
  if (!adjItem) return { ok: false, reason: 'no-donor' };

  const vIdx = bounds.topTrackIndex + 1;
  const placed = await placeAdjustment(
    project, sequence, adjItem, bounds.startSec, bounds.endSec, vIdx, logger);
  if (placed === null) return { ok: false, reason: 'place-failed' };

  const result = {
    ok: true,
    startSec: bounds.startSec, endSec: bounds.endSec,
    vIdx, count: bounds.count,
  };
  if (opts.transformScale) {
    result.transform = await applyEffect(
      project, placed, 'Transform', 'Scale', opts.transformScale, logger);
  }
  if (opts.lumetriLook) {
    result.lumetri = await applyEffect(
      project, placed, 'Lumetri', 'Look', opts.lumetriLook, logger);
  }
  return result;
}

/**
 * Pipeline mode: one adjustment layer per range (e.g. scene ranges from
 * ingest.json with a per-scene LUT plan), all on the same track index.
 *
 * @param {Object} project
 * @param {Object} sequence
 * @param {Array<{startSec:number, endSec:number, lumetriLook?:string}>} ranges
 * @param {Object} opts { vIdx (default 3), donorNames?, donorPrproj?, transformScale? }
 * @param {Object} logger
 * @returns {Promise<{ok:boolean, placed:number, total:number, reason?:string}>}
 */
async function addAdjustmentOverRanges(project, sequence, ranges, opts, logger) {
  opts = opts || {};
  const vIdx = (opts.vIdx === undefined) ? 3 : opts.vIdx;
  const adjItem = await ensureDonorAdjustment(project, opts, logger);
  if (!adjItem) return { ok: false, placed: 0, total: ranges.length, reason: 'no-donor' };

  let placedCount = 0;
  for (const r of ranges) {
    const placed = await placeAdjustment(project, sequence, adjItem, r.startSec, r.endSec, vIdx, logger);
    if (placed === null) continue;
    placedCount++;
    if (opts.transformScale) {
      await applyEffect(project, placed, 'Transform', 'Scale', opts.transformScale, logger);
    }
    if (r.lumetriLook) {
      await applyEffect(project, placed, 'Lumetri', 'Look', r.lumetriLook, logger);
    }
  }
  return { ok: placedCount === ranges.length, placed: placedCount, total: ranges.length };
}

/** All clip trackItems across a sequence's video tracks: {item, name, startSec, endSec, trackIdx}. */
async function collectVideoClipItems(sequence, logger) {
  const out = [];
  let vCount = 0;
  try { vCount = await sequence.getVideoTrackCount(); } catch (e) { return out; }
  for (let vi = 0; vi < vCount; vi++) {
    let track = null;
    try { track = await sequence.getVideoTrack(vi); } catch (e) { continue; }
    if (!track) continue;
    let items = null;
    try { items = await track.getTrackItems(1, false); } catch (e) { /* no-arg */ }
    if (!items) { try { items = await track.getTrackItems(); } catch (e) { /* none */ } }
    for (const it of (items || [])) {
      try {
        const name = String(await it.getName());
        const s = secondsOf(await it.getStartTime());
        const d = secondsOf(await it.getDuration());
        out.push({ item: it, name, startSec: s, endSec: s + d, trackIdx: vi });
      } catch (e) { /* unreadable item */ }
    }
  }
  return out;
}

/**
 * PIPELINE MODE — one adjustment layer over EVERY matched clip of the sequence,
 * LUT chosen by plan. Fully automatic, no selection involved.
 *
 * @param {Object} project
 * @param {Object} sequence
 * @param {Object} planByClip  {"RYA-FX3-1015.MP4": "dark_scene", ...} — basename → lut
 * @param {Object} opts { donorNames?, donorPrproj?, applyLumetri (default true),
 *                        lutNames? (skip-list of layer names; default plan values) }
 * @param {Object} logger
 * @returns {Promise<{ok, placed, total, lumetriApplied, lookSet, skipped, reason?}>}
 *
 * Layers land on the first track ABOVE everything already on the timeline
 * (existing content incl. manual ALs is never touched); overlapping matched
 * clips get greedy lane-stacking one track higher. The placed layer is renamed
 * to its LUT (createSetNameAction) so the editor sees the intent instantly;
 * Lumetri is appended, and setting its Look by param is ATTEMPTED (empirical
 * API — lookSet counts successes; on 0 the editor picks the Look from the
 * dropdown by the layer's name).
 */
async function addAdjustmentPerClipFromPlan(project, sequence, planByClip, opts, logger) {
  opts = opts || {};
  const applyLumetri = opts.applyLumetri !== false;
  const lutNames = (opts.lutNames
    || Array.from(new Set(Object.values(planByClip || {}))))
    .map((v) => LEGACY_LUT_ALIASES[v] || v);
  const skipNames = new Set(
    [].concat(opts.donorNames || DONOR_NAMES, lutNames, Object.keys(LEGACY_LUT_ALIASES)));

  const all = await collectVideoClipItems(sequence, logger);
  if (!all.length) return { ok: false, placed: 0, total: 0, lumetriApplied: 0, lookSet: 0, skipped: 0, reason: 'empty-sequence' };

  // Matched = plan hit by basename; existing LUT-named layers are collected
  // separately — a clip whose correct layer already covers its range is left
  // alone, so rerunning REPAIRS missing layers without duplicating the rest.
  // Plan values are CANONICALISED through the alias map, so pre-rename plans
  // (YTCH10-12 era «dark_scene») keep working and converge on the canonical 01_/02_/03_ names.
  const existing = [];
  const matched = [];
  let skipped = 0;
  for (const c of all) {
    if (skipNames.has(c.name)) { existing.push(c); skipped++; continue; }
    const lut = planByClip[c.name];
    if (lut) matched.push({ ...c, lut: LEGACY_LUT_ALIASES[lut] || lut });
  }
  if (!matched.length) return { ok: false, placed: 0, total: 0, already: 0, lumetriApplied: 0, lookSet: 0, skipped, reason: 'no-plan-match' };

  const EPS = 0.5; // sec — layer counts as "this clip's" when both edges match
  const findExisting = (c) => existing.find((e) =>
    (e.name === c.lut || LEGACY_LUT_ALIASES[e.name] === c.lut)
    && Math.abs(e.startSec - c.startSec) < EPS && Math.abs(e.endSec - c.endSec) < EPS);

  // CLONE MODE (primary): the YTAI_LUT_DONOR sequence is available — layers
  // are CLONES of its hand-configured AL clips, arriving with Lumetri+Look
  // (the Look param is a numeric menu index the API cannot set — measured
  // 18.08). LEGACY MODE (fallback): donor sequence unavailable — place bare
  // ALs + Lumetri, the editor picks the Look by the layer's name.
  const donor = await ensureLutDonorSequence(project, opts, logger);
  const mode = donor ? 'clone' : 'legacy';
  if (logger) logger.info('AL per clip: mode=' + mode);

  // Layer manifest — the ONLY reliable clone-health record (the Creative Look
  // is not readable via the param API). opts.layerManifest carries the prior
  // run's entries for THIS sequence; the fresh map is returned as
  // result.layerManifest for the caller to persist.
  const priorManifest = (opts.layerManifest && typeof opts.layerManifest === 'object')
    ? opts.layerManifest : {};
  const manifestOut = {};

  let already = 0, lumetriApplied = 0, lookSet = 0;
  const toPlace = [];
  for (const c of matched) {
    const ex = findExisting(c);
    if (!ex) { toPlace.push(c); continue; }
    if (mode === 'clone') {
      // Heal. The Creative Look is NOT readable via the param API (binary
      // Blob; the numeric "Look" param indexes only built-in looks) — health
      // is judged by the LAYER MANIFEST instead: a canonical-named layer whose
      // (clip → lut, bounds) entry matches a previous clone run is a clone we
      // placed; anything else (alias name, no manifest entry = legacy/manual
      // leftovers) is replaced by a donor clone.
      const aliased = ex.name !== c.lut;
      const mEntry = priorManifest[c.name];
      const manifested = !aliased && mEntry && mEntry.lut === c.lut
        && Math.abs(mEntry.startSec - c.startSec) < EPS
        && Math.abs(mEntry.endSec - c.endSec) < EPS;
      if (manifested) {
        already++; lookSet++;
        manifestOut[c.name] = { lut: c.lut, startSec: c.startSec, endSec: c.endSec };
        continue;
      }
      // NEVER remove what the donor cannot replace — a broken layer beats a
      // destroyed one.
      if (!donor.byName[c.lut]) {
        already++;
        if (logger) logger.warn(c.name + ': layer "' + ex.name + '" needs replacing, but the donor'
          + ' cannot serve "' + c.lut + '" — layer kept (fix the donor in the template)');
        continue;
      }
      if (logger) logger.info(c.name + ': layer "' + ex.name + '" '
        + (aliased ? 'is pre-rename (broken Look)' : 'is not a tracked clone (no Look underneath)')
        + ' — replacing with donor clone');
      const removed = await removeLayerItem(project, sequence, ex, logger);
      if (!removed) { already++; continue; } // couldn't remove — leave it be
      toPlace.push(c);
      continue;
    }
    already++;
    // Legacy heal: an alias-named layer converges on the canonical name (the
    // Look stays hand-work either way in legacy mode).
    if (ex.name !== c.lut) {
      try {
        await project.lockedAccess(function () {
          return project.executeTransaction(function (ca) {
            ca.addAction(ex.item.createSetNameAction(c.lut));
          }, 'Rename LUT layer');
        });
      } catch (e) {
        if (logger) logger.warn('legacy rename "' + ex.name + '"→"' + c.lut + '" failed: ' + e.message);
      }
    }
    // Legacy heal: append Lumetri when it is missing; re-try the Look param
    // (honest now — counts only when the value actually lands).
    if (applyLumetri) {
      const has = await hasEffect(ex.item, 'Lumetri', logger);
      if (has === false) {
        const r = await applyEffect(project, ex.item, 'Lumetri', 'Look', c.lut, logger);
        if (r.applied) lumetriApplied++;
        if (r.paramSet) lookSet++;
      } else if (has === true) {
        if (await setEffectParam(project, ex.item, 'Lumetri', 'Look', c.lut, logger)) lookSet++;
      }
    }
  }
  if (!toPlace.length) {
    return { ok: true, mode, placed: 0, total: matched.length, already,
             lumetriApplied, lookSet, skipped, layerManifest: manifestOut };
  }

  const adjItem = await ensureDonorAdjustment(project, opts, logger);
  if (!adjItem) return { ok: false, placed: 0, total: matched.length, lumetriApplied: 0, lookSet: 0, skipped, reason: 'no-donor' };

  // Base track: above all CONTENT (existing LUT layers excluded — a replaced
  // layer's clone then lands on the same track instead of drifting upward).
  const contentClips = all.filter((c) => !skipNames.has(c.name));
  const baseIdx = (contentClips.length
    ? Math.max(...contentClips.map((c) => c.trackIdx))
    : Math.max(...all.map((c) => c.trackIdx))) + 1;

  // Greedy lanes for overlapping matched clips (per-scene layouts are usually
  // single-track → lane 0 for everyone). Lanes are assigned BEFORE any
  // placement so the track grow can run exactly once (see placeAdjustment).
  toPlace.sort((a, b) => a.startSec - b.startSec || a.endSec - b.endSec);
  const laneEnds = [];
  for (const c of toPlace) {
    let lane = laneEnds.findIndex((end) => end <= c.startSec + 1e-6);
    if (lane < 0) { lane = laneEnds.length; laneEnds.push(0); }
    laneEnds[lane] = c.endSec;
    c.lane = lane;
  }
  try {
    const seqEditor = ppro.SequenceEditor.getEditor(sequence);
    await growVideoTracks(project, sequence, seqEditor, adjItem,
      baseIdx + laneEnds.length, logger);
  } catch (e) {
    if (logger) logger.warn('per-clip track grow failed: ' + e.message + ' — trying anyway');
  }

  let placed = 0;
  for (const c of toPlace) {
    if (mode === 'clone') {
      const clone = await placeDonorClone(project, sequence, donor, c, baseIdx + c.lane, logger);
      if (!clone) continue;
      placed++;
      if (await hasEffect(clone, 'Lumetri', logger)) lumetriApplied++;
      // The clone is a copy of a hand-Look'ed donor clip — the Look rides
      // along (proven live 18.08); the param API cannot re-verify it.
      lookSet++;
      manifestOut[c.name] = { lut: c.lut, startSec: c.startSec, endSec: c.endSec };
      if (logger) logger.info(c.name + ' → ' + c.lut + ' (clone) @ V' + (baseIdx + c.lane + 1));
      continue;
    }

    const placedItem = await placeAdjustment(
      project, sequence, adjItem, c.startSec, c.endSec, baseIdx + c.lane, logger, false);
    if (placedItem === null) continue;
    placed++;

    // Name the layer after its LUT — the editor sees intent at a glance.
    try {
      await project.lockedAccess(function () {
        return project.executeTransaction(function (ca) {
          ca.addAction(placedItem.createSetNameAction(c.lut));
        }, 'Name adjustment layer');
      });
    } catch (e) {
      if (logger) logger.warn('rename failed for ' + c.name + ': ' + e.message);
    }

    if (applyLumetri) {
      const r = await applyEffect(project, placedItem, 'Lumetri', 'Look', c.lut, logger);
      if (r.applied) lumetriApplied++;
      if (r.paramSet) lookSet++;
    }
    if (logger) logger.info(c.name + ' → ' + c.lut + ' @ V' + (baseIdx + c.lane + 1));
  }

  return { ok: placed === toPlace.length, mode, placed, total: matched.length, already,
           lumetriApplied, lookSet, skipped, layerManifest: manifestOut };
}

/**
 * Place ONE donor clone over [c.startSec, c.endSec] on track vIdx. The donor
 * clip sits @0 on its own track (canonical layout), so timeOffset =
 * c.startSec is position-exact under both shift and absolute readings.
 * Returns the clone trackItem or null (never throws).
 */
async function placeDonorClone(project, sequence, donor, c, vIdx, logger) {
  const d = donor.byName[c.lut];
  if (!d) {
    if (logger) logger.warn(c.name + ': no donor clip "' + c.lut + '" in ' + LUT_DONOR_SEQUENCE
      + ' (have: ' + Object.keys(donor.byName).join(', ') + ')');
    return null;
  }
  const seqEditor = ppro.SequenceEditor.getEditor(sequence);
  const label = c.lut + '@' + c.startSec.toFixed(2) + 's→V' + (vIdx + 1);
  try {
    await project.lockedAccess(function () {
      return project.executeTransaction(function (ca) {
        ca.addAction(seqEditor.createCloneTrackItemAction(
          d.item, tickTimeOfSeconds(c.startSec), vIdx - d.trackIdx, 0, true, false));
      }, 'Clone LUT layer');
    });
  } catch (e) {
    if (logger) logger.warn(label + ': clone failed: ' + e.message);
    return null;
  }
  // Locate the clone: nearest same-name item to startSec on the lane track.
  let clone = null, bestDelta = Infinity;
  try {
    const track = await sequence.getVideoTrack(vIdx);
    let items = null;
    try { items = await track.getTrackItems(1, false); } catch (e) { /* no-arg */ }
    if (!items) { try { items = await track.getTrackItems(); } catch (e) { /* none */ } }
    for (const ti of (items || [])) {
      let n = '';
      try { n = String(await ti.getName()); } catch (e) { /* skip */ }
      // Accept the target name AND its pre-rename alias — a not-yet-refreshed
      // donor clones under the old clip name.
      if (n !== c.lut && LEGACY_LUT_ALIASES[n] !== c.lut) continue;
      const s = secondsOf(await ti.getStartTime());
      const delta = Math.abs(s - c.startSec);
      if (delta < bestDelta) { clone = ti; bestDelta = delta; }
    }
  } catch (e) { /* fall through */ }
  if (!clone) {
    if (logger) logger.warn(label + ': clone not found after action');
    return null;
  }
  if (bestDelta > 0.5 && logger) {
    logger.warn(label + ': clone landed ' + bestDelta.toFixed(2) + 's off target — timeOffset semantics differ?');
  }
  // The layer's name IS the interface (plan matching, repair, the editor's
  // eyes) — normalise it to the plan's LUT name when the donor's differs.
  try {
    let cname = '';
    try { cname = String(await clone.getName()); } catch (e) { /* keep '' */ }
    if (cname !== c.lut && typeof clone.createSetNameAction === 'function') {
      await project.lockedAccess(function () {
        return project.executeTransaction(function (ca) {
          ca.addAction(clone.createSetNameAction(c.lut));
        }, 'Name LUT layer');
      });
    }
  } catch (e) {
    if (logger) logger.warn(label + ': clone rename failed: ' + e.message);
  }
  // Trim to the clip's range (the donor clip is LUT_DONOR_CLIP_SEC long; an AL
  // is synthetic, so extending far beyond it is legal — placeAdjustment placed
  // 19-minute layers from the same donor item).
  try {
    const curStart = secondsOf(await clone.getStartTime());
    const curEnd = curStart + secondsOf(await clone.getDuration());
    if (Math.abs(curEnd - c.endSec) > 0.02) {
      if (typeof clone.createSetEndAction !== 'function') {
        if (logger) logger.warn(label + ': createSetEndAction unavailable — layer left at donor length');
        return clone;
      }
      await project.lockedAccess(function () {
        return project.executeTransaction(function (ca) {
          ca.addAction(clone.createSetEndAction(tickTimeOfSeconds(c.endSec)));
        }, 'Trim LUT layer');
      });
      const newEnd = secondsOf(await clone.getStartTime()) + secondsOf(await clone.getDuration());
      if (Math.abs(newEnd - c.endSec) > 0.06 && logger) {
        logger.warn(label + ': setEnd did not verify — got end ' + newEnd.toFixed(2)
          + 's, want ' + c.endSec.toFixed(2) + 's');
      }
    }
  } catch (e) {
    if (logger) logger.warn(label + ': trim failed: ' + e.message);
  }
  return clone;
}

/**
 * Remove ONE layer trackItem (selection-based — the only removal API).
 * The selection is created and filled INSIDE lockedAccess with a freshly
 * fetched item (stale handles die across transactions on live builds).
 */
async function removeLayerItem(project, sequence, layer, logger) {
  try {
    const seqEditor = ppro.SequenceEditor.getEditor(sequence);
    const track = await sequence.getVideoTrack(layer.trackIdx);
    if (!track) return false;
    let removed = false;
    await project.lockedAccess(async function () {
      let sel = null;
      if (ppro.TrackItemSelection && typeof ppro.TrackItemSelection.createEmptySelection === 'function') {
        const maybe = ppro.TrackItemSelection.createEmptySelection(function (s) { sel = s; });
        if (!sel && maybe && typeof maybe.then === 'function') sel = await maybe;
      }
      if (!sel) throw new Error('TrackItemSelection unavailable');
      let items = null;
      try { items = await track.getTrackItems(1, false); } catch (e) { /* no-arg */ }
      if (!items) { try { items = await track.getTrackItems(); } catch (e) { /* none */ } }
      let target = null;
      for (const ti of (items || [])) {
        let n = '';
        try { n = String(await ti.getName()); } catch (e) { /* skip */ }
        if (n !== layer.name) continue;
        const s = secondsOf(await ti.getStartTime());
        if (Math.abs(s - layer.startSec) < 0.5) { target = ti; break; }
      }
      if (!target) throw new Error('layer item not re-found on track');
      sel.addItem(target, true);
      const mtVideo = (ppro.Constants && ppro.Constants.MediaType) ? ppro.Constants.MediaType.VIDEO : 0;
      await project.executeTransaction(function (ca) {
        ca.addAction(seqEditor.createRemoveItemsAction(sel, false, mtVideo, false));
      }, 'Remove stale LUT layer');
      removed = true;
    });
    return removed;
  } catch (e) {
    if (logger) logger.warn('removeLayerItem "' + layer.name + '": ' + e.message);
    return false;
  }
}

const LUT_DONOR_SEQUENCE = 'YTAI_LUT_DONOR';
// Digit prefix sorts the trio to the TOP of the Lumetri Look dropdown (digits
// collate before letters) and fixes the group order bright → normal → dark.
const LUT_DONOR_CLIPS = ['01_bright_scene', '02_normal_scene', '03_dark_scene'];
// Earlier LUT-name generations (plain *_scene 17-18.08, ytai_* 18.08 evening).
// A layer/donor clip carrying an alias name has a BROKEN Look underneath (the
// Look references the old filename) — alias matches are always replaced.
const LEGACY_LUT_ALIASES = {
  bright_scene: '01_bright_scene',
  normal_scene: '02_normal_scene',
  dark_scene: '03_dark_scene',
  ytai_bright_scene: '01_bright_scene',
  ytai_normal_scene: '02_normal_scene',
  ytai_dark_scene: '03_dark_scene',
};

const LUT_DONOR_CLIP_SEC = 5; // donor clip length — irrelevant, clones get re-trimmed

/**
 * Build (or repair) the YTAI_LUT_DONOR template sequence programmatically.
 *
 * LAYOUT v2 (canonical): each LUT clip sits on its OWN track at t=0 —
 * bright_scene V1@0, normal_scene V2@0, dark_scene V3@0. With donorStart=0 the
 * clone's timeOffset is position-invariant (shift and absolute readings agree),
 * which is what makes clone-mode placement deterministic. A sequence in the old
 * sequential layout (clips at 0/5/10 on V1) is REBUILT — the hand-picked Looks
 * are lost and must be re-picked (3 clicks).
 *
 * The API cannot set the Look itself (numeric menu index, measured 18.08) —
 * clips needing the hand-picked Look are returned in needLook.
 *
 * Run this with the MASTER TEMPLATE open in Premiere — the sequence then ships
 * to every new project; existing projects get it via auto-import.
 *
 * @returns {Promise<{ok:boolean, reason?:string, created?:boolean, rebuilt?:boolean,
 *                    placed?:number, lumetri?:number, needLook?:string[]}>}
 */
async function buildLutDonorSequence(project, opts, logger) {
  opts = opts || {};
  const donorSeqName = opts.donorSequence || LUT_DONOR_SEQUENCE;
  const clipNames = opts.clipNames || LUT_DONOR_CLIPS;
  let step = 'find sequence';
  try {
    let seq = null;
    const seqs = (await project.getSequences()) || [];
    for (const s of seqs) {
      let n = '';
      try { n = String(await s.getName()); } catch (e) { try { n = String(s.name || ''); } catch (e2) { /* last resort; n stays '' and simply never matches */ } }
      if (n === donorSeqName) { seq = s; break; }
    }
    let created = false;
    if (!seq) {
      step = 'createSequence';
      seq = await project.createSequence(donorSeqName);
      if (!seq) return { ok: false, reason: 'create-failed' };
      created = true;
      if (logger) logger.info('buildLutDonor: created sequence ' + donorSeqName);
    }

    step = 'ensure donor ADJ item';
    const adjItem = await ensureDonorAdjustment(project, opts, logger);
    if (!adjItem) return { ok: false, reason: 'no-donor' };

    step = 'scan existing clips';
    let existing = await collectVideoClipItems(seq, logger);

    // Old sequential layout (any clip off t=0, or two clips sharing a track) →
    // wipe and rebuild in the canonical per-track@0 layout.
    let rebuilt = false;
    const offZero = existing.some((c) => c.startSec > 0.02);
    const tracksSeen = new Set(existing.map((c) => c.trackIdx));
    if (existing.length && (offZero || tracksSeen.size < existing.length)) {
      if (logger) logger.warn('buildLutDonor: layout outdated (clips must sit @0 on own tracks) — rebuilding;'
        + ' re-pick the 3 Looks after this');
      step = 'wipe outdated layout';
      const seqEditor = ppro.SequenceEditor.getEditor(seq);
      const vCount = await seq.getVideoTrackCount();
      for (let v = 0; v < vCount; v++) {
        try {
          await removeAllItemsOnTrack(project, seqEditor,
            await seq.getVideoTrack(v), 0 /* MediaType.VIDEO */, logger, 'donor V' + (v + 1));
        } catch (e) {
          if (logger) logger.warn('buildLutDonor: wipe V' + (v + 1) + ': ' + e.message);
        }
      }
      existing = [];
      rebuilt = true;
    }

    // Alias-named clips (pre-rename): their hand-picked Look references the
    // OLD .cube filename and is broken — remove, fresh clips land below on the
    // same tracks (the Look must be re-picked from the canonical group). A clip
    // whose removal FAILED blocks its replacement (overwrite would leave a
    // sliver of the old clip) — that LUT is skipped with a warn.
    const stale = existing.filter((c) => LEGACY_LUT_ALIASES[c.name]);
    const blocked = new Set();
    for (const s of stale) {
      if (logger) logger.info('buildLutDonor: "' + s.name + '" carries a pre-rename Look — replacing with ' + LEGACY_LUT_ALIASES[s.name]);
      const removed = await removeLayerItem(project, seq, s, logger);
      if (!removed) {
        blocked.add(LEGACY_LUT_ALIASES[s.name]);
        if (logger) logger.warn('buildLutDonor: could not remove "' + s.name + '" — skipping ' + LEGACY_LUT_ALIASES[s.name]);
      }
    }
    if (stale.length) existing = existing.filter((c) => !LEGACY_LUT_ALIASES[c.name]);

    let placed = 0, lumetri = 0;
    const needLook = [];
    for (let i = 0; i < clipNames.length; i++) {
      const name = clipNames[i];
      if (blocked.has(name)) { needLook.push(name); continue; }
      const found = existing.find((c) => c.name === name);
      let item = found ? found.item : null;
      if (!item) {
        step = 'place ' + name;
        item = await placeAdjustment(project, seq, adjItem, 0, LUT_DONOR_CLIP_SEC, i, logger, true);
        if (!item) { if (logger) logger.warn('buildLutDonor: place failed for ' + name); needLook.push(name); continue; }
        placed++;
        step = 'rename ' + name;
        try {
          await project.lockedAccess(function () {
            return project.executeTransaction(function (ca) {
              ca.addAction(item.createSetNameAction(name));
            }, 'Name donor AL');
          });
        } catch (e) {
          if (logger) logger.warn('buildLutDonor: rename failed for ' + name + ': ' + e.message);
        }
      }
      step = 'lumetri ' + name;
      const has = await hasEffect(item, 'Lumetri', logger);
      let lookOk = false;
      if (has === false) {
        const r = await applyEffect(project, item, 'Lumetri', 'Look', name, logger);
        if (r.applied) lumetri++;
        lookOk = !!r.paramSet;
      } else if (has === true) {
        lumetri++;
        // Existing clip with Lumetri: a picked CREATIVE Look is not readable
        // via the param API (binary Blob) — trust it, verify by eye once.
        lookOk = true;
      }
      if (!lookOk) needLook.push(name);
    }
    if (logger) logger.info('buildLutDonor: sequence ' + (created ? 'CREATED' : (rebuilt ? 'REBUILT' : 'existed'))
      + ', placed ' + placed + '/' + clipNames.length + ', lumetri ' + lumetri
      + (needLook.length
        ? ' — set Look BY HAND (Lumetri > Creative > Look) for: ' + needLook.join(', ')
        : ' — nothing left to do by hand'));
    return { ok: true, created, rebuilt, placed, lumetri, needLook };
  } catch (e) {
    if (logger) logger.warn('buildLutDonorSequence failed @ ' + step + ': ' + e.message);
    return { ok: false, reason: 'error @ ' + step + ': ' + e.message };
  }
}

/**
 * Read the current Lumetri "Look" value off a trackItem's chain.
 * Returns number (menu index, 0 = None) | string | null (unreadable/absent).
 */
async function readLutLookValue(trackItem, logger) {
  try {
    const vclip = asVideoClip(trackItem);
    const chain = await vclip.getComponentChain();
    const components = await getChainComponents(chain);
    let comp = null;
    for (const c of components) {
      let n = await readDisplayName(c);
      if (!n && c && typeof c.getMatchName === 'function') {
        try { n = String(await c.getMatchName()); } catch (e) { /* none */ }
      }
      if (n.toLowerCase().indexOf('lumetri') >= 0) comp = c;
    }
    if (!comp) return null;
    const paramCount = await comp.getParamCount();
    for (let p = 0; p < paramCount; p++) {
      let param = null;
      try { param = await comp.getParam(p); } catch (e) { continue; }
      let pname = '';
      try { pname = await readDisplayName(param); } catch (e) { /* skip */ }
      if (pname.toLowerCase() !== 'look') continue;
      if (typeof param.getStartValue !== 'function') return null;
      const kf = await param.getStartValue();
      const v = kf ? kf.value : undefined;
      return (v && typeof v === 'object' && 'value' in v) ? v.value : v;
    }
  } catch (e) {
    if (logger) logger.debug('readLutLookValue: ' + e.message);
  }
  return null;
}

/** Look value counts as picked: nonzero menu index or non-empty string. */
function lutLookIsSet(v) {
  return (typeof v === 'number' && v !== 0) || (typeof v === 'string' && v.length > 0);
}

// One refresh (deleteSequence + template re-import) attempt per panel session —
// a stale TEMPLATE would otherwise be deleted-and-reimported on EVERY Apply,
// duplicating template items each time. Reset by panel reload (or tests).
let _lutDonorRefreshTried = false;
function __resetLutDonorRefreshState() { _lutDonorRefreshTried = false; }

/**
 * Resolve the YTAI_LUT_DONOR sequence (project → auto-import chain) and index
 * its SERVICEABLE clips by LUT name. Returns null (→ legacy mode) when
 * unavailable, when the layout is not the canonical per-track@0, when the
 * canonical clip set is incomplete (alias/pre-rename donors included), or when
 * no clip has a picked Look.
 *
 * A donor that is complete but has SOME unpicked/broken Looks serves only the
 * picked LUTs — byName holds ONLY serviceable clips, and the heal path keeps a
 * layer whenever byName cannot serve its replacement.
 *
 * MIGRATION: an outdated local copy (old layout, alias names, incomplete) is
 * deleted and re-imported from the template ONCE per session; a post-import
 * copy that is STILL outdated → null (legacy) with a loud warn — never a
 * half-usable donor.
 */
async function ensureLutDonorSequence(project, opts, logger) {
  opts = opts || {};
  const donorSeqName = opts.donorSequence || LUT_DONOR_SEQUENCE;
  const donorPaths = [].concat(opts.donorPrproj || []);
  const findSeq = async function () {
    const seqs = (await project.getSequences()) || [];
    for (const s of seqs) {
      let n = '';
      try { n = String(await s.getName()); } catch (e) { try { n = String(s.name || ''); } catch (e2) { /* last resort; n stays '' and simply never matches */ } }
      if (n === donorSeqName) return s;
    }
    return null;
  };
  // Layout + name-set check: clips @0 on own tracks AND every canonical
  // LUT_DONOR_CLIPS name present (alias/pre-rename/partial donors fail — their
  // Looks reference renamed .cube files or cannot serve the canonical plan).
  const validate = async function (seq) {
    const clips = await collectVideoClipItems(seq, logger);
    if (!clips.length) return null;
    const byName = {};
    for (const c of clips) {
      if (c.startSec > 0.02) return null; // old sequential layout
      byName[c.name] = c;
    }
    if (!LUT_DONOR_CLIPS.every((n) => byName[n])) return null;
    return byName;
  };
  const importChain = async function () {
    for (const donorPrproj of donorPaths) {
      if (logger) logger.info('lutDonor: no "' + donorSeqName + '" in project — importing ' + donorPrproj);
      try {
        await project.importFiles([donorPrproj], true, null, false);
      } catch (e) {
        if (logger) logger.warn('lutDonor: import failed: ' + e.message);
        continue;
      }
      const seq = await findSeq();
      if (seq) return seq;
    }
    return null;
  };
  try {
    let seq = await findSeq();
    let byName = seq ? await validate(seq) : null;
    if (seq && !byName) {
      // Outdated local copy — self-heal from the template, at most once per
      // session (a stale template would churn delete+import on every Apply).
      if (donorPaths.length && typeof project.deleteSequence === 'function'
          && !_lutDonorRefreshTried) {
        _lutDonorRefreshTried = true;
        if (logger) logger.info('lutDonor: local "' + donorSeqName
          + '" is outdated (layout/names) — deleting and re-importing from the template');
        try {
          await project.deleteSequence(seq);
          seq = null;
        } catch (e) {
          if (logger) logger.warn('lutDonor: deleteSequence failed: ' + e.message);
        }
      }
      if (seq) {
        if (logger) logger.warn('lutDonor: "' + donorSeqName + '" is outdated (clips must be '
          + LUT_DONOR_CLIPS.join('/') + ' @0 on own tracks) — open the MASTER TEMPLATE, '
          + 'press Build LUT Donor, pick the Looks, save. Falling back to legacy mode');
        return null;
      }
    }
    if (!seq) {
      seq = await importChain();
      if (!seq) return null;
      byName = await validate(seq);
      if (!byName) {
        if (logger) logger.warn('lutDonor: the TEMPLATE\'s "' + donorSeqName + '" is itself outdated '
          + '(clips must be ' + LUT_DONOR_CLIPS.join('/') + ' @0 on own tracks) — open the MASTER '
          + 'TEMPLATE, press Build LUT Donor, pick the Looks, save. Falling back to legacy mode');
        return null;
      }
    }
    // NB: a hand-picked CREATIVE Look is NOT programmatically readable — it
    // lives in the Lumetri component's binary Blob/LookAsset params, while the
    // numeric "Look" param (0..71) only indexes Adobe's BUILT-IN looks and
    // stays 0 (measured 18.08 18:43: a donor with all three Looks picked read
    // as «not picked» and wrongly fell back to legacy). The donor is therefore
    // trusted by name+layout; whether its Looks are picked is verified by eye
    // once, in the template.
    return { seq, byName };
  } catch (e) {
    if (logger) logger.warn('ensureLutDonorSequence: ' + e.message);
    return null;
  }
}

/**
 * PLAN-B PROBE — answers the open question «does
 * SequenceEditor.createCloneTrackItemAction work ACROSS sequences?» in one run.
 *
 * Clones the FIRST clip of the template sequence YTAI_LUT_DONOR (AL with
 * Lumetri+Look pre-configured by hand) into the ACTIVE sequence, onto a fresh
 * empty track above all content (never touches existing items; grow refuses →
 * abort, no clamped overwrite). The result is left on the timeline for visual
 * inspection — ⌘Z removes it.
 *
 * Logs everything the decision needs: whether the action executed, where the
 * clone landed vs the donor position (answers timeOffset semantics: offset vs
 * absolute), and whether the clone kept its Lumetri.
 *
 * @returns {Promise<{ok:boolean, reason?:string, landedSec?:number,
 *                    landedTrack?:number, lumetriKept?:boolean|null}>}
 */
async function probeDonorClone(project, opts, logger) {
  opts = opts || {};
  const donorSeqName = opts.donorSequence || LUT_DONOR_SEQUENCE;
  const sig = (c) => c.name + '|' + c.startSec.toFixed(3) + '|' + c.endSec.toFixed(3) + '|' + c.trackIdx;
  const findSeqByName = async function (name) {
    const seqs = (await project.getSequences()) || [];
    for (const s of seqs) {
      let n = '';
      try { n = String(await s.getName()); } catch (e) { try { n = String(s.name || ''); } catch (e2) { /* last resort; n stays '' and simply never matches */ } }
      if (n === name) return s;
    }
    return null;
  };
  let step = 'getActiveSequence';
  try {
    const target = await project.getActiveSequence();
    if (!target) return { ok: false, reason: 'no-active-sequence' };
    step = 'find donor sequence';
    let donorSeq = await findSeqByName(donorSeqName);
    // The sequence lives in the master template — existing projects were
    // cloned BEFORE it was added, so pull it in the same way
    // ensureDonorAdjustment pulls the YTAI_ADJ item: importFiles(.prproj),
    // then re-scan. New projects get it from the template for free.
    if (!donorSeq) {
      const donorPaths = [].concat(opts.donorPrproj || []);
      for (const donorPrproj of donorPaths) {
        if (logger) logger.info('probeDonorClone: no "' + donorSeqName
          + '" in project — importing ' + donorPrproj);
        step = 'import donor prproj';
        try {
          await project.importFiles([donorPrproj], true, null, false);
        } catch (e) {
          if (logger) logger.warn('probeDonorClone: import failed: ' + e.message);
          continue;
        }
        step = 'find donor sequence (post-import)';
        donorSeq = await findSeqByName(donorSeqName);
        if (donorSeq) break;
      }
    }
    if (!donorSeq) {
      if (logger) logger.warn('probeDonorClone: no sequence "' + donorSeqName
        + '" (project + imports) — press Build LUT Donor in the master template first');
      return { ok: false, reason: 'no-donor-sequence' };
    }
    let tname = '';
    try { tname = String(await target.getName()); } catch (e) { try { tname = String(target.name || ''); } catch (e2) { /* identity check target===donorSeq still guards */ } }
    if (target === donorSeq || tname === donorSeqName) return { ok: false, reason: 'donor-is-active' };

    step = 'collect donor clips';
    let donorClips = await collectVideoClipItems(donorSeq, logger);
    if (!donorClips.length) return { ok: false, reason: 'donor-sequence-empty' };
    let donor = donorClips[0];
    if (logger) logger.info('probeDonorClone: donor "' + donor.name + '" @ '
      + donor.startSec.toFixed(2) + 's V' + (donor.trackIdx + 1) + ' of ' + donorSeqName);

    // Fresh empty track above everything — the clone must never clobber
    // content. NB: topIdx is computed from READABLE clips only; unreadable
    // items are invisible to this probe (and to the clobber gate below).
    step = 'snapshot target';
    const before = await collectVideoClipItems(target, logger);
    const topIdx = before.length ? Math.max(...before.map((c) => c.trackIdx)) + 1 : 0;
    step = 'getEditor';
    const seqEditor = ppro.SequenceEditor.getEditor(target);
    step = 'ensure donor ADJ item';
    const adjItem = await ensureDonorAdjustment(project, opts, logger);
    step = 'growVideoTracks';
    if (adjItem) {
      const grown = await growVideoTracks(project, target, seqEditor, adjItem, topIdx + 1, logger);
      if (grown < topIdx + 1) return { ok: false, reason: 'no-track' };
    } else {
      const vCount = await target.getVideoTrackCount();
      if (vCount < topIdx + 1) return { ok: false, reason: 'no-track' };
    }

    // Re-fetch the donor handle AFTER the grow transactions — script objects
    // held across transactions go stale on live builds («The script object is
    // no longer valid», measured 16-17.08; sequenceFactory re-fetches in-lock
    // for the same reason). A stale handle here would masquerade as
    // «cross-sequence clone does not work» and misroute the Plan-B decision.
    step = 'refetch donor';
    donorClips = await collectVideoClipItems(donorSeq, logger);
    if (donorClips.length) donor = donorClips[0];

    if (logger) logger.info('probeDonorClone: expecting the clone on V' + (topIdx + 1)
      + ' (fresh empty track), overwrite mode');
    step = 'createCloneTrackItemAction';
    await project.lockedAccess(function () {
      return project.executeTransaction(function (ca) {
        ca.addAction(seqEditor.createCloneTrackItemAction(
          donor.item,
          tickTimeOfSeconds(0),          // timeOffset — semantics probed via landing spot
          topIdx - donor.trackIdx,       // video vertical offset → the fresh track
          0,                              // audio vertical offset (AL is video-only)
          true,                           // alignToVideo
          false));                        // overwrite, never insert-shift
      }, 'Probe donor clone');
    });

    step = 'locate clone';
    const after = await collectVideoClipItems(target, logger);
    // Identity diffing is unreliable on live 26.x (getTrackItems may hand out
    // fresh wrapper objects per call) — the fresh track was empty, so anything
    // on trackIdx >= topIdx IS the clone; signature-count diff as fallback in
    // case the vertical-offset semantics landed it elsewhere.
    let fresh = after.filter((c) => c.trackIdx >= topIdx);
    if (!fresh.length) {
      const beforeCounts = {};
      for (const c of before) beforeCounts[sig(c)] = (beforeCounts[sig(c)] || 0) + 1;
      fresh = after.filter((c) => {
        const k = sig(c);
        if (beforeCounts[k]) { beforeCounts[k]--; return false; }
        return true;
      });
    }

    // CLOBBER GATE — the probe's semantics are exactly what is unproven, so
    // never trust the landing: every pre-existing readable item must survive
    // with identical bounds. Overwrite eats incumbents silently (measured
    // YTCH13) — a missing/trimmed clip here means the clone landed on content.
    step = 'clobber check';
    const afterCounts = {};
    for (const c of after) afterCounts[sig(c)] = (afterCounts[sig(c)] || 0) + 1;
    const clobbered = [];
    for (const c of before) {
      const k = sig(c);
      if (afterCounts[k]) { afterCounts[k]--; } else { clobbered.push(c); }
    }
    if (clobbered.length) {
      if (logger) logger.error('probeDonorClone: ⚠️ CLOBBER — ' + clobbered.length
        + ' pre-existing item(s) changed/disappeared: '
        + clobbered.slice(0, 5).map((c) => '"' + c.name + '" @ ' + c.startSec.toFixed(2) + 's V' + (c.trackIdx + 1)).join(', ')
        + ' — press ⌘Z NOW (single transaction), do NOT keep this timeline');
      return { ok: false, reason: 'clobbered-content', clobbered: clobbered.length };
    }

    if (!fresh.length) {
      if (logger) logger.warn('probeDonorClone: action executed but NO new item found — clone silently no-op?');
      return { ok: false, reason: 'clone-not-found' };
    }
    const clone = fresh[0];
    const offTarget = clone.trackIdx !== topIdx;
    let lumetriKept = null;
    try { lumetriKept = await hasEffect(clone.item, 'Lumetri', logger); } catch (e) { /* null */ }
    if (logger) logger.info('probeDonorClone: CLONE OK — "' + clone.name + '" landed @ '
      + clone.startSec.toFixed(2) + 's V' + (clone.trackIdx + 1)
      + (offTarget ? ' (⚠️ expected V' + (topIdx + 1) + ' — vertical-offset semantics differ!)' : '')
      + ' (donor was @ ' + donor.startSec.toFixed(2) + 's), Lumetri kept: ' + lumetriKept
      + ' — inspect the Look, then ⌘Z to remove');
    return { ok: true, landedSec: clone.startSec, landedTrack: clone.trackIdx, lumetriKept, offTarget };
  } catch (e) {
    const stale = /no longer valid/i.test(e.message || '');
    if (logger) logger.warn('probeDonorClone failed @ ' + step + ': ' + e.message
      + (stale ? ' — STALE HANDLE, not a cross-sequence verdict: re-run the probe' : ''));
    return { ok: false, reason: (stale ? 'stale-handle @ ' : 'error @ ') + step + ': ' + e.message };
  }
}

module.exports = {
  // ⚠️ Три хелпера ниже экспортируются ради src/adjust/colorApply.js: он тоже
  // ходит по цепочке компонентов клипа, но адресует параметр по ИНДЕКСУ.
  // Своей копии обхода цепочки заводить нельзя — разойдутся.
  asVideoClip,
  getChainComponents,
  readDisplayName,
  selectionBounds,
  ensureDonorAdjustment,
  growVideoTracks,
  placeAdjustment,
  applyEffect,
  setEffectParam,
  addAdjustmentOverSelection,
  addAdjustmentOverRanges,
  collectVideoClipItems,
  addAdjustmentPerClipFromPlan,
  probeDonorClone,
  buildLutDonorSequence,
  ensureLutDonorSequence,
  readLutLookValue,
  lutLookIsSet,
  __resetLutDonorRefreshState,
  placeDonorClone,
  removeLayerItem,
  DONOR_NAMES,
  LUT_DONOR_SEQUENCE,
  LUT_DONOR_CLIPS,
  LEGACY_LUT_ALIASES,
  TICKS_PER_SEC,
};
