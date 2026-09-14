#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recover_from_session_log.py — восстановить файлы, написанные в прошлых сессиях Claude Code, из их логов.

Каждый Write-вызов сессии хранит полный текст файла в
~/.claude/projects/-Users-romansergeev-YTAI/<session>.jsonl (tool_use Write → input.file_path + input.content).
Edit-вызовы хранят только old_string/new_string — применяются поверх последнего Write в порядке лога.

    recover_from_session_log.py <session|path.jsonl> [<session2> …] --prefix <path prefix> --out <dir>
        [--seed <session>:<prefix>]… [--base <dir>]… [--map <dst_name>=<src_name>]… [--list] [--dry-run]

  session…   — одна или несколько сессий; события всех сессий сливаются по timestamp (файл, скопированный
               в одной сессии и правленный в другой, восстанавливается целиком).
  --seed     — «донор» для файлов, у которых в основных сессиях есть только Edit без Write (скопированы
               через Bash `cp`): берём последнее состояние файла с тем же именем из сессии-донора
               под её префиксом (часто это scratchpad прошлой сессии).
  --base     — то же, но из папки на диске (например, уже восстановленный examples/ytch11_v2).
  --map      — файл переименован при копировании (`sed … b_risk.py > b_risk_v2.py`): donor-имя для dst.
  --list     — только показать, что найдено (размер, источник, непримененные правки), ничего не писать.

Что учитывается:
  • Edit, который провалился и в исходной сессии (tool_result is_error), не считается «неприменившимся»;
  • правки через Bash (`sed -i`, `cp`, `mv`, heredoc-патчи) воспроизвести нельзя — команды, трогавшие
    файлы под префиксом, перечисляются в RECOVERED.md как предупреждение;
  • в RECOVERED.md для каждого файла: откуда взят (Write@сессия / seed / base) и число правок, которые
    не легли (old_string не найден) — такие файлы нужно вычитать глазами.

Пример: восстановить тулинг YTCH12 v4 (SSD T7-Beige не смонтирован); u_frames.py и notes_sync.py там
были скопированы из YTCH11 v2_review, поэтому сначала восстанавливаем YTCH11, потом YTCH12 с --base:
    recover_from_session_log.py dbd19194-53c5-4a23-beb9-6e7408dfbbef 7c6f6f58-2b04-40d5-9077-3eaa44a56535 \
        --prefix /Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik/00_Setup/05_Review/v2_review --out examples/ytch11_v2 \
        --seed d364a110-a45c-43fb-94cf-d493925502fd:/private/tmp/claude-501/-Users-romansergeev-YTAI/d364a110-a45c-43fb-94cf-d493925502fd/scratchpad/ytch12_v2 \
        --seed d364a110-a45c-43fb-94cf-d493925502fd:/private/tmp/claude-501/-Users-romansergeev-YTAI/d364a110-a45c-43fb-94cf-d493925502fd/scratchpad/ytch12_review \
        --map b_risk_v2.py=b_risk.py
    recover_from_session_log.py 4de45847-b922-401d-971c-97057cf921d5 \
        --prefix /Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/v4_review --out examples/ytch12_v4 \
        --base examples/ytch11_v2
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

PROJ = Path.home() / '.claude/projects/-Users-romansergeev-YTAI'
BASH_TOUCH = re.compile(r"(sed\s+-i|\bcp\b|\bmv\b|\brsync\b|\bditto\b|\btee\b|cat\s*>|>\s*\S+\.(py|sh|json|md|js)|open\([^)]*['\"]w)")


def resolve_session(s):
    """id или путь → путь к .jsonl"""
    p = Path(s).expanduser()
    if p.exists():
        return p
    p = PROJ / f'{s}.jsonl'
    if p.exists():
        return p
    hits = list(Path.home().glob(f'.claude/projects/*/{s}.jsonl'))
    if hits:
        return hits[0]
    raise SystemExit(f'нет лога сессии {s}')


def load_events(path):
    """→ (events, failed_ids, bash): events = [(ts, name, input, tool_use_id, session)];
    failed_ids — tool_use_id, чьи tool_result вернули ошибку (Edit не применился и в оригинале)."""
    events, failed, bash = [], set(), []
    sess = path.stem[:8]
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            if '"tool_use"' not in line and '"tool_result"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = d.get('timestamp') or ''
            m = d.get('message') or {}
            content = m.get('content') if isinstance(m.get('content'), list) else []
            if d.get('type') == 'assistant':
                for c in content:
                    if not (isinstance(c, dict) and c.get('type') == 'tool_use'):
                        continue
                    inp = c.get('input') or {}
                    if c.get('name') in ('Write', 'Edit'):
                        events.append((ts, c['name'], inp, c.get('id'), sess))
                    elif c.get('name') == 'Bash':
                        bash.append((ts, inp.get('command', ''), sess))
            elif d.get('type') == 'user':
                for c in content:
                    if not (isinstance(c, dict) and c.get('type') == 'tool_result'):
                        continue
                    body = c.get('content')
                    txt = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
                    if c.get('is_error') or '<tool_use_error>' in (txt or '')[:200]:
                        failed.add(c.get('tool_use_id'))
    return events, failed, bash


def replay(events, failed, prefix, seeds=None, bases=None, names=None, log=None):
    """Проигрывает Write/Edit под префиксом. seeds/bases — источники базового текста для Edit-only файлов.
    → files{fp: text}, source{fp: str}, unapplied{fp: [old_string[:60], …]}, orphan{fp: n}"""
    files, source, unapplied, orphan = {}, {}, {}, {}
    seeds, bases, names = seeds or {}, bases or [], names or {}

    def base_for(fp):
        rel = fp[len(prefix):].lstrip('/')
        name = os.path.basename(fp)
        cands = [name, names.get(name, '')]
        for b in bases:
            for c in ([rel] + cands):
                if c and (Path(b) / c).is_file():
                    return (Path(b) / c).read_text(encoding='utf-8'), f'base:{Path(b).name}/{c}'
        for c in cands:
            if c and c in seeds:
                return seeds[c][0], f'seed:{seeds[c][1]}'
        return None, None

    for ts, name, inp, tid, sess in sorted(events, key=lambda e: e[0]):
        fp = inp.get('file_path', '')
        if not fp.startswith(prefix):
            continue
        if tid in failed:
            if log is not None:
                log.append(f'{sess} {ts[:19]} {name} {os.path.basename(fp)}: провалился и в оригинале — пропущен')
            continue
        if name == 'Write':
            files[fp] = inp.get('content', '')
            source[fp] = f'Write@{sess}'
            continue
        if fp not in files:
            txt, src = base_for(fp)
            if txt is None:
                orphan[fp] = orphan.get(fp, 0) + 1
                continue
            files[fp], source[fp] = txt, src
        old, new = inp.get('old_string', ''), inp.get('new_string', '')
        if old and old in files[fp]:
            files[fp] = files[fp].replace(old, new, -1 if inp.get('replace_all') else 1)
        else:
            unapplied.setdefault(fp, []).append(old[:60].replace('\n', '⏎'))
    return files, source, unapplied, orphan


def load_seed(spec):
    """'session:prefix' → {basename: (text, 'session/basename')} — последнее состояние файлов донора."""
    if ':' not in spec:
        raise SystemExit(f'--seed ждёт <session>:<prefix>, получил {spec}')
    sess, pref = spec.split(':', 1)
    path = resolve_session(sess)
    ev, failed, _ = load_events(path)
    files, _, _, _ = replay(ev, failed, pref)
    return {os.path.basename(fp): (txt, f'{path.stem[:8]}/{os.path.basename(fp)}') for fp, txt in files.items()}


def bash_hints(bash, prefix, files):
    """Команды Bash, которые могли менять файлы под префиксом (sed -i / cp / mv / heredoc) — не воспроизводимы."""
    names = {os.path.basename(fp) for fp in files}
    out = []
    for ts, cmd, sess in sorted(bash, key=lambda b: b[0]):
        if prefix not in cmd and not any(n in cmd for n in names):
            continue
        if not BASH_TOUCH.search(cmd):
            continue
        touched = sorted(n for n in names if n in cmd)
        out.append((ts[:19], sess, touched, re.sub(r'\s+', ' ', cmd)[:220]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('sessions', nargs='+')
    ap.add_argument('--prefix', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--seed', action='append', default=[], help='<session>:<prefix> — донор базового текста')
    ap.add_argument('--base', action='append', default=[], help='папка с базовыми версиями файлов')
    ap.add_argument('--map', action='append', default=[], help='<dst_name>=<src_name> для переименованных копий')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    events, failed, bash = [], set(), []
    for s in a.sessions:
        ev, fl, bs = load_events(resolve_session(s))
        events += ev
        failed |= fl
        bash += bs
    seeds = {}
    for spec in a.seed:
        seeds.update(load_seed(spec))
    names = dict(x.split('=', 1) for x in a.map)
    log = []
    files, source, unapplied, orphan = replay(events, failed, a.prefix, seeds, a.base, names, log)
    hints = bash_hints(bash, a.prefix, files)

    def rel(fp):
        return fp[len(a.prefix):].lstrip('/') or os.path.basename(fp)

    for fp, txt in sorted(files.items()):
        flag = f'  ⚠️ {len(unapplied[fp])} правок не применились' if fp in unapplied else ''
        print(f'{len(txt):8d}  {rel(fp):40s} {source[fp]}{flag}')
    if orphan:
        print(f'только-Edit без базы (дай --seed/--base): {[rel(k) for k in orphan]}')
    print(f'{len(files)} файлов · сессий {len(a.sessions)} · пропущено Edit с ошибкой в оригинале: {len(log)} · '
          f'Bash-правок под префиксом: {len(hints)}')
    if a.list or a.dry_run:
        return 0

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for fp, txt in files.items():
        dst = out / rel(fp)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(txt, encoding='utf-8')
    L = [f'# Восстановлено из логов сессий {", ".join(Path(resolve_session(s)).stem[:8] for s in a.sessions)}', '',
         f'Префикс: `{a.prefix}`', '',
         '| файл | байт | источник | не легло правок |', '|---|---:|---|---:|']
    for fp, txt in sorted(files.items()):
        L.append(f'| `{rel(fp)}` | {len(txt)} | {source[fp]} | {len(unapplied.get(fp, []))} |')
    if orphan:
        L += ['', '## Не восстановлены (только Edit, базы нет)', ''] + [f'- `{rel(k)}` — правок {v}' for k, v in orphan.items()]
    if unapplied:
        L += ['', '## Правки, которые не легли (old_string не найден — файл вычитать глазами)', '']
        for fp, olds in unapplied.items():
            L += [f'- `{rel(fp)}`:'] + [f'  - `{o}…`' for o in olds]
    if log:
        L += ['', '## Edit, провалившиеся ещё в исходной сессии (пропущены — это не потеря)', ''] + [f'- {x}' for x in log]
    if hints:
        L += ['', '## Bash-команды, трогавшие эти файлы (sed -i / cp / mv — НЕ воспроизводятся, проверить вручную)', '']
        for ts, sess, touched, cmd in hints:
            L.append(f'- {ts} {sess} [{", ".join(touched) or "по префиксу"}]: `{cmd}`')
    (out / 'RECOVERED.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print(f'восстановлено {len(files)} файлов → {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
