#!/usr/bin/env node
/**
 * plan_cli.js — offline wall-clock layout plan (single source of truth).
 *
 * Runs the EXACT same pure layout code the UXP "Build Ingest" runs
 * (sceneLayout.plan + resolveSceneGrid + prepareTxStrips + groupBySceneSorted),
 * so Python tooling can know, tick-exactly, what the builder will ask Premiere
 * to do — WITHOUT opening Premiere.
 *
 * Consumers:
 *   - 0113_frame_align.py  — renders timeline-domain lav WAVs from the
 *     per-slice contentSrcSec/offsetTicks emitted here;
 *   - verify_build_sync.py — compares a post-build sequence dump against the
 *     expected tick positions emitted here (the sync gate).
 *
 * Usage:
 *   node plan_cli.js --ingest /path/to/{CODE}_ingest.json [--out plan.json] [--pretty]
 *
 * Output (stdout or --out): {
 *   generator, ingest, project_code, ticks_per_second,
 *   scenes: {
 *     <sceneName>: {
 *       sequence_name, grid_fps, ticks_per_frame, seed,
 *       warnings: [...], alignment_needs: [...], time_jumps: [...],
 *       placements: [ { kind, track, filename, txId?, vIdx, aIdx,
 *                       offset_sec, offset_ticks, duration_sec, duration_ticks,
 *                       source_in_sec?, source_in_ticks?, content_src_sec?,
 *                       residual_ms?, grid_snap_ms?, timeline_domain? } ]
 *     }
 *   }
 * }
 */

const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', 'src');
const sceneLayout = require(path.join(SRC, 'ingest', 'layout', 'sceneLayout.js'));
const { prepareTxStrips } = require(path.join(SRC, 'ingest', 'layout', 'txResolver.js'));
const { groupBySceneSorted } = require(path.join(SRC, 'ingest', 'placement', 'binImporter.js'));

function parseArgs(argv) {
  const args = { pretty: false };
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === '--ingest') args.ingest = argv[++i];
    else if (argv[i] === '--out') args.out = argv[++i];
    else if (argv[i] === '--pretty') args.pretty = true;
    else throw new Error(`unknown arg: ${argv[i]}`);
  }
  if (!args.ingest) throw new Error('usage: plan_cli.js --ingest <ingest.json> [--out plan.json] [--pretty]');
  return args;
}

function main() {
  const args = parseArgs(process.argv);
  const ingest = JSON.parse(fs.readFileSync(args.ingest, 'utf8'));

  const { sceneMap, sceneNames } = groupBySceneSorted(ingest.clips || []);
  const mediaSampleRate = ingest.media && ingest.media.sample_rate;
  const projectCode = ingest.project_code || ingest.project_name || 'YT';

  const out = {
    generator: 'plan_cli.js',
    ingest: path.resolve(args.ingest),
    project_code: projectCode,
    ticks_per_second: sceneLayout.TICKS_PER_SECOND,
    scenes: {},
  };

  for (const sceneName of sceneNames) {
    if (sceneName === '_all' || sceneName === 'unknown') continue;
    const sceneClips = sceneMap[sceneName];
    const rawTxStrips = (ingest.tx_strips && ingest.tx_strips[sceneName]) || [];
    const { valid: validTxStrips, warnings: txWarnings } = prepareTxStrips(rawTxStrips, mediaSampleRate);
    const camLayersOverride = (ingest.cam_layers && ingest.cam_layers[sceneName]) || null;

    const { seedClip, gridFps } = sceneLayout.resolveSceneGrid(
      sceneClips, ingest, sceneName, camLayersOverride
    );
    const plan = sceneLayout.plan(sceneClips, validTxStrips, camLayersOverride,
      { scene: sceneName, fps: gridFps });

    // TD-source cross-check: the block-spans fingerprint covers only the VIDEO
    // layout; a lav wall_offset edit in tx_strips_source after 0113 would leave
    // the render silently desynced. 0113 stores each source's wall_offset in
    // frame_align.sources — compare against the CURRENT tx_strips_source.
    const srcStrips = (ingest.tx_strips_source && ingest.tx_strips_source[sceneName]) || null;
    if (srcStrips) {
      const srcByFile = {};
      for (const s of srcStrips) srcByFile[s.filename] = s;
      for (const strip of validTxStrips) {
        const fa = strip.timeline_domain && strip.frame_align;
        if (!fa || !Array.isArray(fa.sources)) continue;
        for (const src of fa.sources) {
          if (typeof src !== 'object' || src.wall_offset === undefined) continue; // pre-upgrade format
          const cur = srcByFile[src.filename];
          if (!cur || Math.abs((cur.wall_offset || 0) - src.wall_offset) > 0.0005) {
            plan.warnings.push({
              type: 'tx_td_sources_changed',
              tx: strip.tx,
              filename: strip.filename,
              source: src.filename,
              note: 'tx_strips_source wall_offset differs from the one baked into the render — re-run 0113',
            });
          }
        }
      }
    }

    out.scenes[sceneName] = {
      sequence_name: `${projectCode}_${sceneName}`,
      grid_fps: gridFps,
      ticks_per_frame: plan.ticksPerFrame,
      seed: seedClip ? seedClip.filename : null,
      warnings: [...txWarnings, ...plan.warnings],
      alignment_needs: plan.alignmentNeeds || [],
      block_spans: plan.blockSpans,
      time_jumps: plan.timeJumps || [],
      placements: plan.placements.map(p => ({
        kind: p.kind,
        track: p.kind === 'video' ? `V${p.vIdx + 1}` : `A${p.aIdx + 1}`,
        filename: p.filename,
        txId: p.txId,
        vIdx: p.vIdx,
        aIdx: p.aIdx,
        offset_sec: p.offsetSec,
        offset_ticks: p.offsetTicks,
        duration_sec: p.duration,
        duration_ticks: p.durationTicks,
        source_in_sec: p.kind === 'tx' ? p.sourceInPoint : undefined,
        source_in_ticks: p.sourceInTicks,
        content_src_sec: p.contentSrcSec,
        residual_ms: p.residualMs,
        grid_snap_ms: p.gridSnapMs,
        timeline_domain: p.timelineDomain || undefined,
        raw_offset_sec: p.rawOffsetSec,
      })),
    };
  }

  const json = JSON.stringify(out, null, args.pretty ? 2 : 0);
  if (args.out) {
    fs.writeFileSync(args.out, json);
    process.stderr.write(`plan written: ${args.out} (${Object.keys(out.scenes).length} scenes)\n`);
  } else {
    process.stdout.write(json + '\n');
  }
}

main();
