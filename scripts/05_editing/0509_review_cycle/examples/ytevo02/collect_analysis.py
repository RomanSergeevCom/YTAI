#!/usr/bin/env python3
"""collect_analysis.py — вытащить результаты многоагентного разбора из journal.jsonl
воркфлоу в один analysis.json, который ест build_structure_html.py.

  python3 collect_analysis.py [--journal PATH]
"""
import argparse
import json
import re
from pathlib import Path

# агенты стабильно кладут в поле n мусор (число вариантов), а настоящий номер блока
# живёт в block_title — «БЛОК 11 · …», «Блок 9 — …». Тянем оттуда.
BLOCK_N_RE = re.compile(r"бло\w*\s*№?\s*(\d{1,2})", re.I)


def real_block_n(v, canon):
    m = BLOCK_N_RE.search(v.get("block_title") or "")
    if m:
        return int(m.group(1))
    # запасной путь — сопоставить по таймкоду первого варианта с границами блоков
    tcs = [o.get("tc") for o in (v.get("options") or []) if o.get("tc")]
    if tcs and canon:
        def sec(t):
            p = re.findall(r"\d+", t or "")
            return int(p[0]) * 60 + int(p[1]) if len(p) >= 2 else -1
        t0 = sec(tcs[0])
        for b in canon.get("blocks", []):
            if sec(b.get("tc_in")) <= t0 < sec(b.get("tc_out")):
                return b.get("n")
    return v.get("n")

DEF_JOURNAL = ("/Users/romansergeev/.claude/projects/-Users-romansergeev-YTAI/"
               "fd86095f-1ac7-4167-8b67-c9ca8422b968/subagents/workflows/"
               "wf_5f08f40a-568/journal.jsonl")
OUT = Path("/Volumes/T9-Black-RYA/YTEVO/YTEVO02_evolution_manifesto/00_Setup/analysis.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", default=DEF_JOURNAL)
    a = ap.parse_args()

    canon, viz, checks, lenses = None, [], [], []
    for line in Path(a.journal).read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("type") != "result":
            continue
        r = e.get("result")
        if not isinstance(r, dict):
            continue
        if "logline" in r and "blocks" in r:
            canon = r
        elif "options" in r and "block_title" in r:
            viz.append(r)
        elif "verdict" in r and "errors" in r:
            checks.append(r)
        elif "lens" in r and "blocks" in r:
            lenses.append(r)

    for v in viz:
        v["n"] = real_block_n(v, canon)
    seen = {}
    for v in viz:                       # если два результата сели на один блок — берём богаче
        k = v["n"]
        if k not in seen or len(v.get("options") or []) > len(seen[k].get("options") or []):
            seen[k] = v
    viz = sorted(seen.values(), key=lambda v: v.get("n") or 0)
    # сверка — та, что нашла больше конкретных ошибок; критик полноты — та, что про missing
    check = max(checks, key=lambda c: len(c.get("errors") or []), default=None)
    critic = max((c for c in checks if c is not check),
                 key=lambda c: len(c.get("missing") or []), default=None)

    data = {"canon": canon, "viz": viz, "check": check, "critic": critic,
            "lenses_count": len(lenses)}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    n_opts = sum(len(v.get("options") or []) for v in viz)
    print(f"canon: {'ok' if canon else 'НЕТ'} · блоков {len(canon['blocks']) if canon else 0}")
    print(f"viz: {len(viz)} блоков · {n_opts} вариантов")
    print(f"check: {'ok' if check else '—'} ({len(check.get('errors') or []) if check else 0} ошибок)")
    print(f"critic: {'ok' if critic else '—'} ({len(critic.get('missing') or []) if critic else 0} пробелов)")
    print(f"линз: {len(lenses)}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
