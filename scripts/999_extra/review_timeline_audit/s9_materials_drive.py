#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6 S9: материалы → Drive-папка проекта Review_materials/ (+ КОММЕНТ на каждом файле) и
кадры для =IMAGE листа → gdrive:YTUVI_plan_v3_shots (shots_ids.json).

Что грузим (подпапки в Review_materials):
  v6_audit_screens/  — кадры ошибок С НАРИСОВАННОЙ СТРЕЛКОЙ (композит ann_tz*.png на кадр 1920) + fix_* драфты
  v6_graphics/       — новые драфты V3/V6: термины (term_*/termgrp_*), мини-карты (map_*/mapfull_*),
                        прозрачные панели (*_t.png), подглавы (sub_*), прогресс (prog_*), новые LT (tz_lt_33+)
Идемпотентно: файл с тем же именем в подпапке — обновляется (files.update media), коммент добавляется
только если на файле ещё нет нашего коммента с тем же префиксом «ТЗ-…»/«V3 ·»/«V6 ·».
→ montage/proj_material_ids.json (имя → id) дополняется.
usage: s9_materials_drive.py [--dry-run] [--only screens|graphics]
"""
import json, mimetypes, re, subprocess, sys, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path.home() / 'YTAI/scripts/999_extra/ytuvi_doctabs'))
from doctab_lib import access_token  # noqa: E402
sys.path.insert(0, str(Path(__file__).parent))
from terms_catalog import TERMS, LOCS  # noqa: E402
from make_infographics_v6_data import SUB, PROG  # noqa: E402
from PIL import Image  # noqa: E402

W6 = Path(__file__).parent
M = W6.parent / 'montage'
MOCK = Path('/Volumes/T7-Blue-2-RYA/YTUVI-Projects/YTUVI01_Corundum_Ruby/00_Setup/05_Review/mockups')
MATERIALS_ID = '1s6KJ3ka4L98hwur23KtAraucneMRQN7w'
SHOTS_REMOTE = 'gdrive:YTUVI_plan_v3_shots'
DRY = '--dry-run' in sys.argv
ONLY = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else 'all'
COMP = W6 / 'err_frames_annotated'
COMP.mkdir(exist_ok=True)


def api(method, url, body=None, raw=None, ctype='application/json'):
    headers = {'Authorization': f'Bearer {access_token()}'}
    data = None
    if raw is not None:
        data = raw
        headers['Content-Type'] = ctype
    elif body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print('API ERROR:', method, url[:90], e.read().decode()[:400])
        raise


def find_child(parent, name, folder=False, meta=False):
    qn = name.replace("'", "\\'")
    q = f"'{parent}' in parents and name = '{qn}' and trashed = false"
    if folder:
        q += " and mimeType = 'application/vnd.google-apps.folder'"
    r = api('GET', 'https://www.googleapis.com/drive/v3/files?' + urllib.parse.urlencode(
        {'q': q, 'fields': 'files(id,name,mimeType,md5Checksum)', 'supportsAllDrives': 'true', 'includeItemsFromAllDrives': 'true'}))
    if meta:
        return (r['files'][0]['id'], r['files'][0].get('md5Checksum')) if r['files'] else (None, None)
    return r['files'][0]['id'] if r['files'] else None


def ensure_folder(parent, name):
    fid = find_child(parent, name, folder=True)
    if fid or DRY:
        return fid or f'DRY-{name}'
    r = api('POST', 'https://www.googleapis.com/drive/v3/files?supportsAllDrives=true',
            {'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent]})
    return r['id']


def upload(parent, path, name=None):
    name = name or Path(path).name
    mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    data = Path(path).read_bytes()
    existing, md5 = (None, None) if str(parent).startswith('DRY-') else find_child(parent, name, meta=True)
    import hashlib
    if existing and md5 == hashlib.md5(data).hexdigest():     # v7: неизменённый файл не перезаливаем
        SKIPPED.append(name)
        return existing
    if DRY:
        print('  [dry] upload', name, f'{len(data) / 1e6:.1f} MB', '(update)' if existing else '(new)')
        return existing or f'DRY-{name}'
    boundary = 'ytai_v6_boundary'
    meta = json.dumps({'name': name} if existing else {'name': name, 'parents': [parent]}).encode()
    body = (b'--' + boundary.encode() + b'\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n' + meta +
            b'\r\n--' + boundary.encode() + b'\r\nContent-Type: ' + mime.encode() + b'\r\n\r\n' + data +
            b'\r\n--' + boundary.encode() + b'--')
    if existing:
        r = api('PATCH', f'https://www.googleapis.com/upload/drive/v3/files/{existing}?uploadType=multipart&supportsAllDrives=true',
                raw=body, ctype=f'multipart/related; boundary={boundary}')
    else:
        r = api('POST', 'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true',
                raw=body, ctype=f'multipart/related; boundary={boundary}')
    return r['id']


def comment(file_id, text):
    if DRY or file_id.startswith('DRY-'):
        print('  [dry] comment:', text[:100])
        return
    have = api('GET', f'https://www.googleapis.com/drive/v3/files/{file_id}/comments?fields=comments(content)&pageSize=50')
    head = text.split('·')[0].strip()
    if any(c.get('content', '').split('·')[0].strip() == head for c in have.get('comments', [])):
        return
    api('POST', f'https://www.googleapis.com/drive/v3/files/{file_id}/comments?fields=id', {'content': text})


def tc(sec):
    return f'{int(sec) // 60}:{int(sec) % 60:02d}'


proj_ids = json.load(open(M / 'proj_material_ids.json')) if (M / 'proj_material_ids.json').exists() else {}
audit = json.load(open(W6 / 'audit_v6.json')) if (W6 / 'audit_v6.json').exists() else {'annotations': []}
terms = json.load(open(W6 / 'terms_v6.json'))
pravki = json.load(open(M / 'pravki_v2.json'))['all']
jobs = []   # (subfolder, local_path, name, comment, also_shots)
SKIPPED = []   # v7: файлы, которые на Drive уже байт-в-байт (md5) — не перезаливались

# ── 1. кадры ошибок с стрелкой + fix-драфты ──
if ONLY in ('all', 'screens'):
    for a in audit['annotations']:
        fn = a['tz'].replace('ТЗ-', 'tz')
        ann = MOCK / f'ann_{fn}.png'
        frame = Path(a['frame'])
        out = COMP / f'v6_err_{a["screen_id"]}.jpg'
        if ann.exists() and frame.exists():
            bg = Image.open(frame).convert('RGBA')
            ov = Image.open(ann).convert('RGBA').resize(bg.size, Image.LANCZOS)
            Image.alpha_composite(bg, ov).convert('RGB').save(out, quality=90)
        elif frame.exists():
            subprocess.run(['cp', str(frame), str(out)], check=True)
        else:
            continue
        num = a['tz']
        jobs.append(('v6_audit_screens', out, out.name,
                     f'{num} · {tc(a["t0"])} · {a["kind"]}: {a["text"]} — кадр рендера v1 с отметкой места ошибки (стрелка = слой V5 секвенции Review_v6).', True))
        fix = MOCK / f'fix_{fn}.png'
        if a.get('fix') and fix.exists():
            jobs.append(('v6_audit_screens', fix, fix.name,
                         f'{num} · {tc(a["t0"])} · драфт ИСПРАВЛЕННОГО титра (слой V3): {a["fix"]["text"]}. Перерисовать в стиле канала.', True))
        # v7: варианты оформления (ТЗ-21 цены: А — все цифры, Б — «$X,X МЛН» + мелко цифрами) — Роман выбирает
        for vf in (sorted(MOCK.glob(f'fix_{fn}_*.png')) if a.get('fix') else []):
            jobs.append(('v6_audit_screens', vf, vf.name,
                         f'{num} · {tc(a["t0"])} · драфт ИСПРАВЛЕНИЯ (слой V3), вариант {vf.stem.rsplit("_", 1)[1]} — '
                         f'сумма цифрами. Роман выбирает А или Б; перерисовать в стиле канала.', True))

# ── 2. новая графика ──
if ONLY in ('all', 'graphics'):
    by_key = {}
    for g in terms['term_groups']:
        for k in g['keys']:
            by_key.setdefault(k, []).append(g['tc'])
    for key, rx, title, sub, definition in TERMS:
        p = MOCK / f'term_{key}.png'
        if p.exists() and key in by_key:
            jobs.append(('v6_graphics', p, p.name,
                         f'V3 · термин «{title}» ({sub}) — плашка-определение при каждом упоминании: {", ".join(by_key[key])}. Прозрачный PNG 4K, драфт — перерисовать в стиле канала.', False))
    seen = set()
    for g in terms['term_groups']:
        if len(g['keys']) < 2:
            continue
        name = 'termgrp_' + '_'.join(g['keys']) + '.png'
        if name in seen or not (MOCK / name).exists():
            continue
        seen.add(name)
        jobs.append(('v6_graphics', MOCK / name, name, f'V3 · группа терминов {" + ".join(g["keys"])} @ {g["tc"]} — одна плашка на 2–3 определения, прозрачный PNG 4K.', False))
    loc_tc = {}
    for m in terms['locs']:
        loc_tc.setdefault(m['key'], []).append(m['tc'])
    for key, rx, region, pts, label in LOCS:
        p = MOCK / f'map_{key}.png'
        if p.exists() and key in loc_tc:
            jobs.append(('v6_graphics', p, p.name,
                         f'V3 · мини-карта «{label}» — при каждом упоминании локации: {", ".join(loc_tc[key])}. География Natural Earth 50m (public domain), координаты месторождений сверены (GIA/Lotus). Прозрачный PNG 4K.', False))
    # карта со сноской «одна страна — два имени» ставится только на первом упоминании места
    for m in terms['locs']:
        if not m.get('note'):
            continue
        nm = f"map_{m['key']}_note.png"
        if (MOCK / nm).exists():
            jobs.append(('v6_graphics', MOCK / nm, nm,
                         f"V3 · мини-карта со сноской про переименование — только на первом упоминании @{m['tc']}. Прозрачный PNG 4K.", False))
    for name, txt in (('mapfull_burma.png', 'V3 · Мьянма (Бирма): Могок и Монг Су на реальной карте @17:27 (замена рисованной схемы 052).'),
                      ('mapfull_belt.png', 'V3 · «Рубиновый пояс», шаг 1 из 3 @19:30 — Мьянма, Мозамбик, Таиланд и Камбоджа (замена английского титра).'),
                      ('mapfull_belt_2.png', 'V3 · «Рубиновый пояс», шаг 2 из 3 @19:33 — Вьетнам, Таджикистан, Афганистан, Пакистан, Шри-Ланка.'),
                      ('mapfull_belt_3.png', 'V3 · «Рубиновый пояс», шаг 3 из 3 @19:37 — Танзания, Мадагаскар, Кения, Малави.'),
                      ('info_mohs_what_t.png', 'V3 · «Что такое шкала Мооса» — прозрачная панель по центру (видео видно) @13:56.'),
                      ('info_synthesis_list_t.png', 'V3 · «3 способа вырастить рубин» — прозрачная панель @30:04.'),
                      ('info_treatments_scheme_t.png', 'V3 · «Обработка рубинов: 6 способов» — прозрачная панель @33:45 и @38:20.')):
        if (MOCK / name).exists():
            jobs.append(('v6_graphics', MOCK / name, name, txt, False))
    # сводные карты названий — нужны и в доке, поэтому also_shots=True (в док картинка идёт из shots_ids)
    for name, txt in (('info_namemap_places.png', 'Справочник монтажёру · КАРТА НАЗВАНИЙ: места — что звучит в озвучке и что ставим на экран (ТЗ-76).'),
                      ('info_namemap_terms.png', 'Справочник монтажёру · КАРТА НАЗВАНИЙ: термины, часть 1 (ТЗ-75).'),
                      ('info_namemap_terms_2.png', 'Справочник монтажёру · КАРТА НАЗВАНИЙ: термины, часть 2 (ТЗ-75).')):
        if (MOCK / name).exists():
            jobs.append(('v6_graphics', MOCK / name, name, txt, True))
    for i, (sec, ch, label) in enumerate(SUB):
        p = MOCK / f'sub_{i + 1:02d}.png'
        if p.exists():
            jobs.append(('v6_graphics', p, p.name, f'V6 · подглава «{label}» (глава {ch:02d}) @{tc(sec)} — прозрачная плашка, левый борт.', False))
    for ch, (title, items, acc) in PROG.items():
        for k in range(1, len(items) + 1):
            p = MOCK / f'prog_{ch}_{k}.png'
            if p.exists():
                jobs.append(('v6_graphics', p, p.name, f'V6 · прогресс перечисления гл.{ch} «{title}»: шаг {k} из {len(items)} — {items[k - 1]}.', False))
    start = int(audit.get('new_tz_from', 33))
    for i, p in enumerate(pravki):
        if i + 1 >= start:
            lt = MOCK / f'tz_lt_{i + 1:02d}.png'
            if lt.exists():
                jobs.append(('v6_graphics', lt, lt.name, f'ТЗ-{i + 1:02d} · {p["v1_tc"]} · плашка ТЗ (слой V4): {p["title"]}.', False))

print(f'jobs: {len(jobs)}  (dry={DRY})')
folders = {}
for sub in sorted({j[0] for j in jobs}):
    folders[sub] = ensure_folder(MATERIALS_ID, sub)
    print('folder', sub, folders[sub])
shots_files = []
for n, (sub, path, name, text, also_shots) in enumerate(jobs, 1):
    fid = upload(folders[sub], path, name)
    comment(fid, text)
    proj_ids[name] = fid
    if also_shots:
        shots_files.append(path)
    if n % 20 == 0:
        print(f'  {n}/{len(jobs)}', flush=True)
if not DRY:
    json.dump(proj_ids, open(M / 'proj_material_ids.json', 'w'), ensure_ascii=False, indent=1)
    print('proj_material_ids.json:', len(proj_ids))
    if shots_files:
        tmp = W6 / '_shots_tmp'
        tmp.mkdir(exist_ok=True)
        for p in shots_files:
            subprocess.run(['cp', str(p), str(tmp / Path(p).name)], check=True)
        subprocess.run(['rclone', 'copy', str(tmp), SHOTS_REMOTE, '--transfers', '4'], check=True)
        ls = subprocess.run(['rclone', 'lsjson', SHOTS_REMOTE, '--files-only'], capture_output=True, text=True, check=True)
        ids = {f['Name']: f['ID'] for f in json.loads(ls.stdout)}
        shots = json.load(open(M / 'shots_ids.json'))
        shots.update({Path(p).name: ids[Path(p).name] for p in shots_files if Path(p).name in ids})
        json.dump(shots, open(M / 'shots_ids.json', 'w'), ensure_ascii=False, indent=1)
        print('shots_ids.json:', len(shots), '| без ID:', [Path(p).name for p in shots_files if Path(p).name not in ids])
print(f'не перезаливались (md5 совпал): {len(SKIPPED)} из {len(jobs)}')
print('done')
