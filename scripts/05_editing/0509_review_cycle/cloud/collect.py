#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect.py — сбор результатов облачного прохода → cloud/state.json + work/{cut}/audit_findings.json (v8).

usage:
    collect.py                        только файлы P.CLOUD/out/*.json (их пишут агенты сами, persistence-first)
    collect.py --run <runId>          + journal / agent-файлы / task-output этого прогона (сессию находит сам)
    collect.py --session <id>         + все прогоны wf_judge.js этой сессии
    collect.py --from-legacy [PATH]   старый audit_findings_v6.json ({findings|confirmed}) → находки route=legacy в v8
    collect.py --emit-legacy          записать audit_findings_v6.json в старой форме, ЕСЛИ его нет (s10/review_page читают её)
    collect.py --projects-dir DIR     где сессии Claude Code (по умолчанию ~/.claude/projects/<-slug-YTAI>)

Что делает: (1) внешние источники → out/<batch_id>.json (если агент не успел записать сам), сырьё → raw/<runId>/;
(2) out/*.json → батчи done (source: agent | journal | agent-file | wf-meta | task-output);
(3) покрытие J: каждый экран пакета обязан быть в verdicts / new_findings / clean_screens, непокрытые →
новый pending-пакет J_<nn>b_<sha8> (логика pack.py); (4) находки из всех done-батчей → audit_findings.json
{schema: review-findings-v8, run_ids, findings[...], confirmed[finding_id…]}: confirmed = вердикт confirm /
new_finding (факт wrong, кроп error_visible) и скептик не снял (T,V,C,F,D снимают; H → kind check_source).
Выход: 0 — все батчи done; 3 — есть pending (печатает какие); 1 — ошибка. Сводка ≤2 КБ.
"""
import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path

from cloudlib import (P, W6, OUT, RAW, FINDINGS_PATH, FINDINGS_SCHEMA, LEGACY_FINDINGS_PATH, ensure_dirs, warn,  # noqa: E402
                      load_json, save_json, state_load, state_save, batch_kind, pending_ids, batch_in_path,
                      batch_out_path, screens_map, candidates_load, derive_findings, summarize_findings, match_line,
                      frame_path, find_run, list_runs, harvest_run, expected_batches, is_ours, batch_id_of, tc)
import pack  # noqa: E402


def now():
    return dt.datetime.now().isoformat(timespec='seconds')


# ── 1. внешние источники (journal / agent / task-output) ───────────────────
def harvest(st, runs, projects_dir=None):
    """runs: [(session, run_id, meta_path)] → out/<bid>.json для батчей без файла; сырьё в raw/<runId>/."""
    n_new = 0
    for session, run_id, mp in runs:
        need = set(b for b in st['batches'] if st['batches'][b].get('status') != 'done')
        h = harvest_run(session, run_id, mp, need=need, projects_dir=projects_dir)
        meta = h['meta']
        if not is_ours(meta):
            print(f'{run_id}: не wf_judge ({meta.get("name") or "?"}) — {len(h["legacy"])} legacy-результатов, пропуск')
            continue
        if run_id not in st['run_ids']:
            st['run_ids'].append(run_id)
        raw = RAW / run_id
        raw.mkdir(parents=True, exist_ok=True)
        for src, name in ((h['paths'].get('journal'), 'journal.jsonl'), (h['paths'].get('task'), 'task.output'), (str(mp), 'wf_meta.json')):
            if src and Path(src).exists():
                dst = raw / name
                if not dst.exists() or dst.stat().st_size != Path(src).stat().st_size:
                    shutil.copy2(src, dst)
        for ag in h['paths'].get('agents') or []:
            dst = raw / Path(ag).name
            if not dst.exists():
                shutil.copy2(ag, dst)
        got = 0
        for bid, (obj, source) in h['payloads'].items():
            b = st['batches'].get(bid)
            if b is None:
                warn(f'{run_id}: результат {bid} не зарегистрирован в state.json — приму как батч (kind {bid[:1]})')
                b = st['batches'][bid] = {'status': 'pending', 'kind': bid[:1], 'in': str(batch_in_path(bid)) if batch_in_path(bid).exists() else None,
                                          'out': str(batch_out_path(bid)), 'adopted': True}
            b['run_id'] = run_id
            op = batch_out_path(bid, b)
            if not op.exists():
                save_json(op, obj)
                b['source'] = source
                got += 1
                n_new += 1
        exp = expected_batches(meta)
        lost = [x for x in exp if x not in h['payloads'] and not batch_out_path(x, st['batches'].get(x)).exists()]
        print(f'{run_id} ({meta.get("name")}, агентов {meta.get("agents")}, токенов {meta.get("tokens")}, {meta.get("status")}): '
              f'результатов {len(h["payloads"])}, записано новых {got}, упавших агентов {h["failed"]}'
              + (f', НЕ ВЕРНУЛИСЬ: {", ".join(lost)}' if lost else ''))
    return n_new


# ── 2. out/*.json → done ───────────────────────────────────────────────────
def scan_out(st):
    ensure_dirs()
    newly = []
    for f in sorted(OUT.glob('*.json')):
        bid = f.stem
        if not re.match(r'^[JFVS]_', bid):
            continue
        obj = load_json(f, None)
        if not isinstance(obj, dict):
            warn(f'{f.name}: не JSON-объект — батч остаётся pending')
            continue
        if obj.get('batch_id') and obj['batch_id'] != bid:
            warn(f'{f.name}: внутри batch_id={obj["batch_id"]} — файл переименован агентом? пропуск')
            continue
        b = st['batches'].get(bid)
        if b is None:
            inp = batch_in_path(bid)
            b = st['batches'][bid] = {'status': 'pending', 'kind': bid[:1], 'in': str(inp) if inp.exists() else None,
                                      'out': str(f), 'adopted': True}
            if bid[:1] == 'S' and not inp.exists():
                b['mode'] = 'run'
            warn(f'{bid}: файл результата без регистрации — принят как батч')
        if b.get('status') != 'done':
            b.update(status='done', out=str(f), done_at=now(), source=b.get('source') or 'agent')
            newly.append(bid)
    return newly


# ── 3. покрытие J ──────────────────────────────────────────────────────────
def check_coverage(st):
    cands = {c['cand_id']: c for c in (candidates_load(quiet=True) or [])}
    report = []
    for bid in sorted(list(st['batches'])):
        b = st['batches'][bid]
        if batch_kind(bid, b) != 'J' or b.get('status') != 'done' or b.get('coverage_checked'):
            continue
        pk = load_json(batch_in_path(bid, b), None)
        o = load_json(batch_out_path(bid, b), None)
        if not isinstance(pk, dict) or not isinstance(o, dict):
            continue
        sids = [s['id'] for s in pk.get('screens') or []]
        covered = set(o.get('clean_screens') or [])
        for v in o.get('verdicts') or []:
            covered.add(v.get('screen_id') or cands.get(v.get('cand_id'), {}).get('screen_id'))
        for n in o.get('new_findings') or []:
            covered.add(n.get('screen_id'))
        unc = [s for s in sids if s not in covered]
        b['coverage_checked'] = True
        b['covered'] = len(sids) - len(unc)
        if unc:
            b['uncovered'] = unc
            for s in unc:
                (b.get('screens') or {}).pop(s, None)
            m = re.match(r'^J_(\d+)', bid)
            new = pack.build_j_packs(st, ids=set(unc), tag=m.group(1) if m else None, quiet=True)
            report.append(f'{bid}: непокрыто {len(unc)}/{len(sids)} ({", ".join(unc[:6])}{"…" if len(unc) > 6 else ""}) → {", ".join(new) or "уже в pending"}')
        else:
            report.append(f'{bid}: покрытие {len(sids)}/{len(sids)}')
    return report


# ── 4. legacy → v8 ─────────────────────────────────────────────────────────
def legacy_to_v8(path):
    data = load_json(path, None)
    if not isinstance(data, dict):
        raise SystemExit(f'{path}: нет или не JSON')
    src = data.get('findings') or data.get('confirmed') or []
    scr = screens_map()
    out, per_screen = [], {}
    for f in src:
        sid = f.get('screen_id')
        k = per_screen.get(sid, 0) + 1
        per_screen[sid] = k
        e = scr.get(sid, {})
        fr = f.get('frame') or ''
        if not fr or not Path(fr).exists():
            fr = str(W6 / 'hires' / Path(fr).name) if fr else frame_path(e)
        bb = f.get('bbox_final') or f.get('bbox')
        votes = f.get('votes') or []
        conf = bool(f.get('confirmed'))
        verdict = 'confirm' if conf else ('unverified' if f.get('status') == 'unverified' else 'refute')
        g = {
            'finding_id': f'legacy.{sid}.{k:02d}', 'screen_id': sid, 'tc': f.get('tc') or e.get('tc'),
            't0': f.get('t0', e.get('t0')), 't1': f.get('t1', e.get('t1')), 'chapter': e.get('chapter'), 'frame': fr,
            'kind': f.get('kind') or 'other', 'on_screen_text': f.get('on_screen_text') or '',
            'line_idx': match_line(e, f.get('on_screen_text')), 'bbox': bb if isinstance(bb, dict) else None,
            'fix_text': f.get('fix_text_final') or f.get('fix_text') or '', 'problem': f.get('problem') or '',
            'why': f.get('evidence') or '', 'severity': f.get('severity') or 'medium', 'route': 'legacy',
            'verdict': verdict, 'confidence': f.get('confidence'),
            'skeptic': ({'real': conf, 'code': '', 'reason': 'legacy 3-lens: ' + '; '.join(
                f"{v.get('lens')}={'refute' if v.get('refuted') else 'ok'}" for v in votes), 'corrected_fix_text': ''}
                        if votes else None),
            'fact': None, 'crop': None, 'existing_tz': f.get('existing_tz') or '', 'run_id': data.get('run_id'),
            'batch_id': None, 'status': 'confirm' if conf else verdict, 'confirmed': conf,
        }
        if 'fix_draw' in f:
            g['fix_draw'] = f['fix_draw']
        out.append(g)
    return out


def emit_legacy(findings):
    """Старая форма для s10_format_tz / review_page / doc_tab_review_v1 — только если файла ещё нет."""
    if LEGACY_FINDINGS_PATH.exists():
        print(f'--emit-legacy: {LEGACY_FINDINGS_PATH.name} уже есть — не трогаю')
        return
    rows = []
    for f in findings:
        bb = f.get('bbox')
        rows.append({'screen_id': f.get('screen_id'), 'tc': f.get('tc'), 't0': f.get('t0'), 't1': f.get('t1'),
                     'frame': f.get('frame'), 'kind': f.get('kind'), 'severity': f.get('severity'),
                     'on_screen_text': f.get('on_screen_text'), 'problem': f.get('problem'), 'fix_text': f.get('fix_text'),
                     'fix_text_final': f.get('fix_text'), 'evidence': ' '.join(x for x in (f.get('why'), (f.get('fact') or {}).get('source_url')) if x),
                     'bbox': bb, 'bbox_final': bb, 'existing_tz': f.get('existing_tz') or '', 'confidence': f.get('confidence'),
                     'confirmed': bool(f.get('confirmed')), 'status': 'verified', 'votes': [], 'finding_id': f.get('finding_id')})
    save_json(LEGACY_FINDINGS_PATH, {'schema': 'legacy-from-v8', 'note': 'сгенерировано collect.py --emit-legacy из audit_findings.json',
                                     'packs': None, 'findings': rows, 'confirmed': [r for r in rows if r['confirmed']]})
    print(f'--emit-legacy → {LEGACY_FINDINGS_PATH.name}: {len(rows)} находок, подтверждено {sum(1 for r in rows if r["confirmed"])}')


# ── 5. запись v8 ───────────────────────────────────────────────────────────
def write_findings(st, legacy=None):
    prev = load_json(FINDINGS_PATH, None)
    if legacy is None:
        legacy = [f for f in ((prev or {}).get('findings') or []) if f.get('route') == 'legacy']
    findings, extras = derive_findings(st, legacy=legacy)
    summ = summarize_findings(findings)
    data = {'schema': FINDINGS_SCHEMA, 'code': P.CODE, 'cut_version': P.CUT_VERSION, 'generated': now(),
            'run_ids': list(st.get('run_ids') or []),
            'batches': {bid: {k: b.get(k) for k in ('status', 'kind', 'source', 'n', 'run_id', 'covered', 'uncovered')}
                        for bid, b in st['batches'].items()},
            'summary': summ, 'findings': findings, 'confirmed': [f['finding_id'] for f in findings if f.get('confirmed')],
            'facts_ok': extras.get('facts_ok') or [], 'unmapped': extras.get('unmapped') or []}
    save_json(FINDINGS_PATH, data)
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run')
    ap.add_argument('--session')
    ap.add_argument('--from-legacy', nargs='?', const=str(LEGACY_FINDINGS_PATH))
    ap.add_argument('--emit-legacy', action='store_true')
    ap.add_argument('--projects-dir')
    a = ap.parse_args()
    ensure_dirs()
    st = state_load()

    if a.run or a.session:
        runs = find_run(a.run, a.projects_dir) if a.run else list_runs(session=a.session, projects_dir=a.projects_dir)
        if not runs:
            print(f'прогон {a.run or a.session} не найден в сессиях', file=sys.stderr)
            return 1
        harvest(st, runs, a.projects_dir)

    newly = scan_out(st)
    cov = check_coverage(st)
    legacy = legacy_to_v8(a.from_legacy) if a.from_legacy else None
    data = write_findings(st, legacy=legacy)
    state_save(st)
    if a.emit_legacy:
        emit_legacy(data['findings'])

    # ── сводка ──
    rows = []
    for bid, b in sorted(st['batches'].items()):
        rows.append(f'{bid:<22} {batch_kind(bid, b)} {b.get("status", "?"):<8} {b.get("source") or "—":<11} '
                    + (f'n={b["n"]}' if b.get('n') is not None else f'mode={b.get("mode", "?")}')
                    + (f' run={b["run_id"]}' if b.get('run_id') else ''))
    print('\n'.join(rows))
    if cov:
        print('покрытие: ' + ' · '.join(cov))
    s = data['summary']
    lg = sum(1 for f in data['findings'] if f.get('route') == 'legacy')
    print(f'{FINDINGS_PATH.name}: находок {s["total"]} (legacy {lg}), подтверждено {s["confirmed"]}, статусы {s["by_status"]}, '
          f'без скептика {s["need_skeptic"]}' + (f', новых done {len(newly)}' if newly else ''))
    if data['unmapped']:
        print(f'⚠️ не сопоставлено: {len(data["unmapped"])} (см. unmapped в файле)')
    pend = pending_ids(st)
    if pend:
        print(f'PENDING {len(pend)}: {", ".join(pend)} → pack.py --print-call')
        return 3
    print('все батчи done' if st['batches'] else 'батчей нет (pack.py ещё не запускался)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
