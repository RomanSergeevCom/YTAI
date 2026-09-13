#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6: результат догоняющей проверки (wf_verify_rest_v6.js) → обратно в audit_findings_v6.json.

Зачем отдельным скриптом: у воркфлоу нет доступа к файловой системе, его результат живёт только
в task-output прогона. 11.09 так потерялись 51 находка из 79 — поэтому слияние сразу и с отчётом.

Вход:  --result <файл> — либо task-output воркфлоу ({"summary":…,"result":{…}}), либо сам result.
       Голоса возвращаются на место по полю vid (его ставит s6b_pack_verify.py).
Выход: audit_findings_v6.json обновлён (votes/status/confirmed/fix_text_final/bbox_final,
       находки критика добавлены), рядом — бэкап .bak-merge-<n>; отчёт по главам в stdout.

usage: python3 merge_verify_v6.py --result ~/.../tasks/xxxx.output [--findings audit_findings_v6.json] [--dry-run]
"""
import argparse
import collections
import json
import shutil
import sys
from pathlib import Path

from _bootstrap import P, W6, M, HERE, ROOT  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--result', required=True)
ap.add_argument('--findings', default=str(W6 / 'audit_findings_v6.json'))
ap.add_argument('--dry-run', action='store_true')
a = ap.parse_args()

raw = json.load(open(a.result, encoding='utf-8'))
res = raw.get('result', raw) if isinstance(raw, dict) else raw
if not isinstance(res, dict) or 'verdicts' not in res:
    raise SystemExit(f'{a.result}: не похоже на результат wf_verify_rest_v6 (нет поля verdicts)')

fp = Path(a.findings)
data = json.load(open(fp, encoding='utf-8'))
findings = data['findings']
by_vid = {f['vid']: f for f in findings if f.get('vid')}

CH = {e['id']: e['chapter'] for e in json.load(open(W6 / 'screens_v6.json', encoding='utf-8'))}

# ── 1. голоса по догоняемым находкам ──────────────────────────────────────
lost = [v['id'] for v in res['verdicts'] if v.get('id') not in by_vid]
if lost:
    raise SystemExit(f'вердикты без находки в {fp.name}: {", ".join(lost)} — '
                     'переупакуй (s6b_pack_verify.py) или проверь, тот ли файл результата')
upd = 0
for v in res['verdicts']:
    f = by_vid[v['id']]
    f.update({k: v[k] for k in ('confirmed', 'status', 'votes', 'fix_text_final', 'bbox_final') if k in v})
    upd += 1

# ── 2. находки критика полноты ────────────────────────────────────────────
def key(f):
    return (f.get('screen_id'), f.get('kind'), (f.get('on_screen_text') or '')[:40])


seen = {key(f) for f in findings}
new = [f for f in (res.get('critic_findings') or []) if key(f) not in seen]
dup = len(res.get('critic_findings') or []) - len(new)
for i, f in enumerate(new, 1):
    f.setdefault('from_critic', True)
    f.setdefault('status', 'verified' if f.get('votes') else 'unverified')
    f['vid'] = f'c{i:03d}'
findings += new

data['findings'] = findings
data['confirmed'] = [f for f in findings if f.get('confirmed')]
data['critic_done'] = bool(res.get('critic_done'))
data['critic_notes'] = res.get('critic_notes', '')
data['critic_clean'] = res.get('critic_clean', [])
data['note'] = (f'Аудит 11.09 (6 паков, 79 находок) + догоняющая проверка 12.09: '
                f'{upd} находок получили голоса, критик полноты '
                f'{"прошёл" if data["critic_done"] else "НЕ прошёл"}, новых находок от критика {len(new)}.')

# ── 3. отчёт ──────────────────────────────────────────────────────────────
rows = collections.defaultdict(lambda: collections.Counter())
for f in findings:
    ch = CH.get(f.get('screen_id'), '??')
    st = 'подтверждено' if f.get('confirmed') else ('без проверки' if f.get('status') == 'unverified' else 'отпало')
    rows[ch][st] += 1
    if f.get('from_critic'):
        rows[ch]['от критика'] += 1
print(f'{"глава":>6} {"подтверждено":>13} {"отпало":>7} {"без проверки":>13} {"от критика":>11}')
tot = collections.Counter()
for ch in sorted(rows):
    r = rows[ch]
    tot.update(r)
    print(f'{ch:>6} {r["подтверждено"]:>13} {r["отпало"]:>7} {r["без проверки"]:>13} {r["от критика"]:>11}')
print(f'{"ИТОГО":>6} {tot["подтверждено"]:>13} {tot["отпало"]:>7} {tot["без проверки"]:>13} {tot["от критика"]:>11}')
if dup:
    print(f'дублей от критика отброшено: {dup}')
still = [f'{f.get("vid")} {f.get("screen_id")} {f.get("tc")}' for f in findings if f.get('status') == 'unverified']
if still:
    print(f'⚠️ всё ещё без голосов ({len(still)}): {", ".join(still[:12])}{" …" if len(still) > 12 else ""}')

if a.dry_run:
    print('--dry-run: файл не изменён')
else:
    n = len(list(fp.parent.glob(fp.name + '.bak-merge-*'))) + 1
    shutil.copy(fp, f'{fp}.bak-merge-{n}')
    json.dump(data, open(fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'→ {fp.name}: находок {len(findings)}, подтверждено {len(data["confirmed"])} '
          f'(бэкап .bak-merge-{n}) · проект {P.PROJECT}')
