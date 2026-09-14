#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""salvage.py — спасение результатов воркфлоу из сессий Claude Code + таблица стоимости прогонов.

usage:
    salvage.py [--session <id> | --latest | --all] [--name <подстрока>] [--out <dir>] [--force]
    salvage.py --cost [--session <id> | --latest | --all] [--name <подстрока>]
    salvage.py --dump [--session <id> | --latest] [--name <подстрока>]   # result + logs прогона → raw/<runId>/

Где ищет: <session>/workflows/wf_*.json (имя, agentCount, totalTokens, durationMs, status, args, result),
subagents/workflows/<runId>/journal.jsonl (возврат КАЖДОГО агента, даже если сборка после них упала),
agent-*.jsonl (последний StructuredOutput — когда журнал неполон), tasks/<taskId>.output ({summary, result}).
Результаты с batch_id (контракт §7) кладёт в P.CLOUD/out/<batch_id>.json, существующие файлы не затирает
(без --force). Результаты без batch_id (wf_audit_v6, verify-rest, listify…) только перечисляет как legacy —
их не подделываем под новую форму. Печатает найдено/потеряно по батчам каждого прогона.
--cost — та же таблица по прогонам (runId, имя, агентов, токенов, длительность, статус) = метрика экономии.
Обобщение x_wf_extract.py (YTCH12 v4_review). Сессии: ~/.claude/projects/<-slug-YTAI>/ (--projects-dir).
"""
import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault('YTAI_CLOUD_NO_CARD', '1')      # --cost и --out работают без карточки фильма
from cloudlib import (OUT, RAW, load_json, save_json, list_runs, find_run, harvest_run,  # noqa: E402
                      expected_batches, wf_meta_light, canon)


def dur(ms):
    if not ms:
        return '—'
    s = int(ms) // 1000
    return f'{s // 60}:{s % 60:02d}'


def select_runs(a):
    if a.run:
        runs = find_run(a.run, a.projects_dir)
        if not runs:
            raise SystemExit(f'прогон {a.run} не найден')
    else:
        runs = list_runs(session=a.session, latest=not a.all and not a.session, all_sessions=a.all, projects_dir=a.projects_dir)
    if a.name:
        keep = []
        for sid, rid, mp in runs:
            m = wf_meta_light(mp)
            if a.name.lower() in (m.get('name') or '').lower() or a.name.lower() in (m.get('scriptPath') or '').lower():
                keep.append((sid, rid, mp))
        runs = keep
    return runs


def cost_table(runs):
    print(f'{"runId":<18} {"session":<8} {"имя":<22} {"агентов":>7} {"токенов":>10} {"время":>7} статус')
    tot_a = tot_t = 0
    for sid, rid, mp in runs:
        m = wf_meta_light(mp)
        tot_a += m.get('agents') or 0
        tot_t += m.get('tokens') or 0
        print(f'{rid:<18} {sid[:8]:<8} {(m.get("name") or "?")[:22]:<22} {m.get("agents") or 0:>7} {m.get("tokens") or 0:>10} '
              f'{dur(m.get("durationMs")):>7} {m.get("status") or "?"}')
    print(f'{"ИТОГО":<18} {"":<8} {len(runs):<22} {tot_a:>7} {tot_t:>10}')


def salvage(runs, out_dir, force=False, dump=False, projects_dir=None):
    if not out_dir:
        raise SystemExit('нет карточки фильма (YTAI_CARD) — укажи --out <dir>, куда класть результаты')
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_root = RAW or (out_dir.parent / 'raw')
    total_found = total_lost = 0
    for sid, rid, mp in runs:
        h = harvest_run(sid, rid, mp, need=None, projects_dir=projects_dir)
        m = h['meta']
        exp = expected_batches(m)
        found = list(h['payloads'])
        lost = [x for x in exp if x not in h['payloads']]
        total_found += len(found)
        total_lost += len(lost)
        head = (f'{rid} · {m.get("name") or "?"} · агентов {m.get("agents")} · токенов {m.get("tokens")} · '
                f'{dur(m.get("durationMs"))} · {m.get("status")} · упавших агентов {h["failed"]}')
        print(head)
        if not exp and not found:
            print(f'   legacy (без batch_id): {len(h["legacy"])} результатов' + (f' — {"; ".join(h["legacy"][:4])}' if h['legacy'] else ''))
        for bid in found:
            obj, source = h['payloads'][bid]
            dst = out_dir / f'{bid}.json'
            if dst.exists():
                same = canon(load_json(dst, {})) == canon(obj)
                if same:
                    state = 'уже есть (тот же)'
                elif not force:
                    state = 'есть другой файл — оставлен (--force перезапишет)'
                else:
                    save_json(dst, obj)
                    state = 'перезаписан (--force)'
            else:
                save_json(dst, obj)
                state = 'записан'
            print(f'   ✓ {bid} ← {source}: {state}')
        for bid in lost:
            print(f'   ✗ {bid}: результата нет ни в журнале, ни в agent-файлах, ни в task-output — догнать (pack.py --print-call)')
        if h['legacy'] and (exp or found):
            print(f'   legacy-результатов без batch_id: {len(h["legacy"])}')
        if dump:
            d = raw_root / rid
            d.mkdir(parents=True, exist_ok=True)
            save_json(d / 'result.json', {'runId': rid, 'session': sid, 'name': m.get('name'), 'status': m.get('status'),
                                          'agents': m.get('agents'), 'tokens': m.get('tokens'), 'durationMs': m.get('durationMs'),
                                          'args': m.get('args'), 'logs': m.get('logs'), 'result': m.get('result')})
            print(f'   → {d / "result.json"}')
    print(f'итого: найдено {total_found}, потеряно {total_lost} (по {len(runs)} прогонам)')
    return 0 if not total_lost else 3


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--session')
    ap.add_argument('--run')
    ap.add_argument('--latest', action='store_true')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--name')
    ap.add_argument('--out', default=str(OUT) if OUT else None)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--cost', action='store_true')
    ap.add_argument('--dump', action='store_true')
    ap.add_argument('--projects-dir')
    a = ap.parse_args()
    runs = select_runs(a)
    if not runs:
        print('прогонов под фильтр нет')
        return 1
    if a.cost:
        cost_table(runs)
        return 0
    return salvage(runs, a.out, force=a.force, dump=a.dump, projects_dir=a.projects_dir)


if __name__ == '__main__':
    sys.exit(main())
