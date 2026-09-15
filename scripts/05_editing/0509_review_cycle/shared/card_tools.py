#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""card_tools — создание и проверка карточки фильма review_card.json.

    python3 card_tools.py from-prep <prep_config.json> --project-dir <dir> --channel YTUVI [--mode cut_review] [--cut-version v1]
    python3 card_tools.py check <review_card.json>
    python3 card_tools.py new --project-dir <dir> --channel YTUVI --code YTUVI03 [--mode …]

Конвертер prep_config → review_card: переносит все ключи как есть, добавляет schema/channel/mode/cut_version,
делает пути относительными к 05_Review, если они внутри проекта. Ничего не удаляет и не перезаписывает без --force.
"""
import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED = ['schema', 'project', 'code', 'channel', 'mode', 'cut_version', 'words', 'duration_sec', 'chapters', 'ch_name', 'film']
EXTERNAL = ['doc_id', 'materials_id', 'project_folder_id', 'sprint_folder_id']
CODE_RE = re.compile(r'^(YT[A-Z]{2,4}\d+)_')


def _rel(p, base):
    if not p:
        return p
    try:
        return str(Path(p).resolve().relative_to(base.resolve()))
    except Exception:
        return p


def from_prep(prep_path, project_dir, channel, mode='cut_review', cut_version='v1'):
    prep = json.loads(Path(prep_path).read_text(encoding='utf-8'))
    project_dir = Path(project_dir)
    review_dir = project_dir / '00_Setup' / '05_Review'
    code = prep.get('code') or (CODE_RE.match(project_dir.name).group(1) if CODE_RE.match(project_dir.name) else None)
    card = {'schema': 'review-card-v1', 'project': prep.get('project', (code or '').lower()), 'code': code,
            'channel': channel.upper(), 'mode': mode, 'cut_version': cut_version,
            'project_dir': str(project_dir), 'project_name': prep.get('project_name', project_dir.name)}
    for k, v in prep.items():
        if k.startswith('_') or k in card:
            continue
        card[k] = v
    for k in ('src', 'render', 'words', 'mockups_dir'):
        if card.get(k):
            card[k] = _rel(card[k], review_dir)
    card.setdefault('notes', [])
    card.setdefault('terms_file', 'review_terms.json')
    return card


def check(card_path):
    card = json.loads(Path(card_path).read_text(encoding='utf-8'))
    review_dir = Path(card_path).parent
    problems = []
    for k in REQUIRED:
        if k not in card or card[k] in ('', None, [], {}):
            problems.append(f'нет ключа «{k}»')
    if card.get('schema') != 'review-card-v1':
        problems.append(f'schema = {card.get("schema")!r}, ожидается review-card-v1')
    for k in ('src', 'words', 'render'):
        v = card.get(k)
        if v:
            p = Path(v) if Path(v).is_absolute() else review_dir / v
            if not p.exists():
                problems.append(f'{k}: файла нет — {p}')
    for k in EXTERNAL:
        if not card.get(k):
            problems.append(f'внешний id «{k}» пуст (стадии drive/doc откажутся)')
    ch = card.get('channel', '')
    prof = Path.home() / 'YTAI' / 'YTs' / ch / 'review_profile.json'
    if not prof.exists():
        problems.append(f'нет профиля канала {prof}')
    if not card.get('ocr_anchors'):
        problems.append('ocr_anchors пусты — селфчек OCR будет пропущен (заполни 2–3 фразы, которые точно есть в кате)')
    problems += soft_warnings(card)
    return card, problems


WARN = 'предупреждение: '


def soft_warnings(card):
    """мягкие проверки новых ключей (fps дробный, exclusions, lang) — предупреждения, не отказ"""
    out = []
    fps = card.get('fps')
    if fps is not None and (isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0):
        out.append(f'{WARN}fps = {fps!r} — ожидается число > 0 (25, 29.97, 23.976)')
    if 'lang' in card and card.get('lang') not in ('ru', 'en', '', None):          # пусто = как в профиле канала
        out.append(f'{WARN}lang = {card.get("lang")!r} — ожидается "ru" или "en" (иное считается ru)')
    exc = card.get('exclusions')
    if exc is not None:
        if not isinstance(exc, list):
            out.append(f'{WARN}exclusions — ожидается список {{t0, t1, reason}}, а не {type(exc).__name__}')
        else:
            for i, e in enumerate(exc):
                if not isinstance(e, dict):
                    out.append(f'{WARN}exclusions[{i}] — не объект {{t0, t1, reason}}')
                    continue
                t0, t1 = e.get('t0'), e.get('t1')
                if not str(e.get('reason') or '').strip():
                    out.append(f'{WARN}exclusions[{i}] без reason')
                if t0 is None or t1 is None:
                    out.append(f'{WARN}exclusions[{i}] без t0/t1 — игнорируется, пока не заданы таймкоды')
                    continue
                if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (t0, t1)):
                    out.append(f'{WARN}exclusions[{i}]: t0/t1 должны быть секундами (числа), а не {t0!r}/{t1!r}')
                elif t1 < t0:
                    out.append(f'{WARN}exclusions[{i}]: t1 ({t1}) < t0 ({t0})')
                elif card.get('duration_sec') and t0 > float(card['duration_sec']):
                    out.append(f'{WARN}exclusions[{i}]: t0 {t0} за концом ката ({card["duration_sec"]} с)')
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('from-prep'); a.add_argument('prep'); a.add_argument('--project-dir', required=True)
    a.add_argument('--channel', required=True); a.add_argument('--mode', default='cut_review')
    a.add_argument('--cut-version', default='v1'); a.add_argument('--force', action='store_true')
    c = sub.add_parser('check'); c.add_argument('card')
    n = sub.add_parser('new'); n.add_argument('--project-dir', required=True); n.add_argument('--channel', required=True)
    n.add_argument('--code'); n.add_argument('--mode', default='cut_review'); n.add_argument('--cut-version', default='v1')
    n.add_argument('--force', action='store_true')
    args = ap.parse_args()
    if args.cmd == 'check':
        card, problems = check(args.card)
        for p in problems:
            print('  ⚠️', p)
        print(f'{args.card}: {card.get("code")} · {card.get("channel")} · {card.get("mode")} · '
              f'{"OK" if not problems else str(len(problems)) + " замечаний"}')
        return 1 if any(not x.startswith(('ocr_anchors', 'внешний id', WARN)) for x in problems) else 0
    review_dir = Path(args.project_dir) / '00_Setup' / '05_Review'
    review_dir.mkdir(parents=True, exist_ok=True)
    out = review_dir / 'review_card.json'
    if out.exists() and not args.force:
        raise SystemExit(f'{out} уже есть — --force, чтобы перезаписать')
    if args.cmd == 'from-prep':
        card = from_prep(args.prep, args.project_dir, args.channel, args.mode, args.cut_version)
    else:
        tpl = Path(__file__).resolve().parent.parent / 'templates' / 'review_card.template.json'
        card = json.loads(tpl.read_text(encoding='utf-8'))
        code = args.code or CODE_RE.match(Path(args.project_dir).name).group(1)
        card.update({'project': code.lower(), 'code': code, 'channel': args.channel.upper(), 'mode': args.mode,
                     'cut_version': args.cut_version, 'project_dir': str(Path(args.project_dir).resolve()),
                     'project_name': Path(args.project_dir).name})
    out.write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'карточка записана: {out}')
    _, problems = check(out)
    for p in problems:
        print('  ⚠️', p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
