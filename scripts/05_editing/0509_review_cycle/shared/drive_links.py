#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ссылки ТЗ на САМИ исходные файлы в Drive (Роман 16.09.2026: «ссылки на исходники — на сами файлы», у книжных
была только ссылка на сайт издания, у ТЗ-48 — никакой).

  картинка базы  → `_KB/index.sqlite` (records.source = PDF относительно корня базы, locator = страница) →
                   Drive-зеркало базы (профиль kb.drive_originals_root) → «весь PDF со страницей» + «папка».
  свой клип      → оригинал в Drive-футаже (kb.drive_footage_root) по имени файла: сначала в папке сцены
                   (первая часть пути после FOOT/ или корня футажа на SSD), потом по всему дереву.
  скан книги     → (запас, books_policy fallback) папка книг в зеркале.
Только чтение Drive (`rclone lsjson`); найденные id — в кэш `pravki/drive_originals_ids.json`, чтобы повторная
сборка не ходила в сеть. Не нашлось — пустая ссылка (не выдумываем).

usage (проверка): drive_links.py kb <path из picks> | clip <имя или путь>
"""
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'stages'))
from _bootstrap import P, M  # noqa: E402

KB_CFG = P.profile('kb') or {}
KB_ROOT = Path(KB_CFG.get('root') or '/nonexistent')
FOOT_ROOT = Path(KB_CFG.get('footage_root') or '/nonexistent')
ORIG_ID = KB_CFG.get('drive_originals_root') or ''
FOOT_ID = KB_CFG.get('drive_footage_root') or ''
BOOK_FOLDER = '01_SSEF/01_Book'                     # сканы книг в Drive-зеркале (на SSD вынесены в 01_ScanBook-SSEF)
CACHE = M / 'drive_originals_ids.json'
FILE_URL = 'https://drive.google.com/file/d/{}/view'
FOLDER_URL = 'https://drive.google.com/drive/folders/{}'

_cache = None
_ls_mem = {}


def _load():
    global _cache
    if _cache is None:
        _cache = json.loads(CACHE.read_text(encoding='utf-8')) if CACHE.exists() else {}
    return _cache


def _save():
    P.write_json_atomic(CACHE, _load())


def _lsjson(root_id, folder, *flags, include=None):
    key = (root_id, folder, flags, include)
    if key not in _ls_mem:
        argv = ['rclone', 'lsjson', f'gdrive:{folder}', '--drive-root-folder-id', root_id, *flags]
        if include:
            argv += ['--include', include]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=600)
        _ls_mem[key] = json.loads(r.stdout or '[]') if r.returncode == 0 else []
    return _ls_mem[key]


def _glob_escape(name):
    return re.sub(r'([\[\]{}*?\\])', r'\\\1', name)


def file_id(root_id, rel):
    """id файла по пути относительно корня зеркала"""
    c = _load()
    k = f'{root_id}:{rel}'
    if k not in c:
        rel_p = Path(rel)
        hit = [x for x in _lsjson(root_id, str(rel_p.parent) if str(rel_p.parent) != '.' else '', '--files-only',
                                  include=_glob_escape(rel_p.name)) if x['Name'] == rel_p.name]
        c[k] = hit[0]['ID'] if hit else ''
        _save()
    return c[k]


def folder_id(root_id, rel_folder):
    """id папки по пути относительно корня зеркала (корень — сам root_id)"""
    if not rel_folder or rel_folder == '.':
        return root_id
    c = _load()
    k = f'{root_id}:{rel_folder}/'
    if k not in c:
        p = Path(rel_folder)
        parent = str(p.parent) if str(p.parent) != '.' else ''
        hit = [x for x in _lsjson(root_id, parent, '--dirs-only') if x['Name'] == p.name]
        c[k] = hit[0]['ID'] if hit else ''
        _save()
    return c[k]


def kb_source(path):
    """(PDF относительно корня базы, страница) для картинки базы; None — если в индексе её нет"""
    db = KB_ROOT / '_KB' / 'index.sqlite'
    if not db.exists():
        return None
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    try:
        row = con.execute("SELECT source, locator FROM records WHERE path = ? AND kind IN ('figure','image') LIMIT 1",
                          [str(path)]).fetchone()
    finally:
        con.close()
    if not row:
        return None
    m = re.search(r'\d+', row[1] or '')
    return row[0], int(m.group(0)) if m else None


def kb_links(path):
    """→ {file, folder, page, source} для картинки базы (или скана книги-запаса)"""
    sp = str(path)
    if '01_ScanBook-SSEF' in sp or '/01_Book/' in sp:
        fid = folder_id(ORIG_ID, BOOK_FOLDER) if ORIG_ID else ''
        return {'file': '', 'folder': FOLDER_URL.format(fid) if fid else '', 'page': None, 'source': BOOK_FOLDER}
    src = kb_source(sp)
    if not ORIG_ID:
        return {'file': '', 'folder': '', 'page': None, 'source': ''}
    if (not src or '/' not in src[0]) and not sp.startswith('_KB/'):
        # картинка курса/урока лежит в базе сама (source = «course:Rubies …», не файл) — ссылка на саму картинку
        fid, did = file_id(ORIG_ID, sp), folder_id(ORIG_ID, str(Path(sp).parent))
        return {'file': FILE_URL.format(fid) if fid else '', 'folder': FOLDER_URL.format(did) if did else '',
                'page': None, 'source': sp}
    if not src:
        return {'file': '', 'folder': '', 'page': None, 'source': ''}
    pdf, page = src
    fid, did = file_id(ORIG_ID, pdf), folder_id(ORIG_ID, str(Path(pdf).parent))
    url = FILE_URL.format(fid) + (f'#page={page}' if page and pdf.lower().endswith('.pdf') else '') if fid else ''
    return {'file': url, 'folder': FOLDER_URL.format(did) if did else '', 'page': page, 'source': pdf}


def clip_links(path_or_name):
    """→ {file, folder, name} оригинала своего клипа в Drive-футаже"""
    s = str(path_or_name)
    name = Path(s).name if '.' in Path(s).name else Path(s).name + '.MP4'
    parts = Path(s).parts
    if s.startswith('FOOT/') and len(parts) > 2:
        scene = parts[1]
    elif str(FOOT_ROOT) in s:
        rel = Path(s).relative_to(FOOT_ROOT).parts
        scene = rel[0] if len(rel) > 1 else ''
    else:
        scene = ''
    c = _load()
    k = f'{FOOT_ID}:clip:{name}'
    if k not in c and FOOT_ID:
        hits = []
        for folder in ([scene] if scene else []) + ['']:
            # шаблон без «/» rclone сверяет с концом пути — находит файл на любой глубине
            hits = [x for x in _lsjson(FOOT_ID, folder, '--files-only', '--recursive', include=_glob_escape(name))
                    if x['Name'] == name]
            if hits:
                h = hits[0]
                full = f"{folder}/{h['Path']}" if folder else h['Path']
                c[k] = {'id': h['ID'], 'dir': str(Path(full).parent)}
                break
        else:
            c[k] = {'id': '', 'dir': ''}
        _save()
    hit = c.get(k) or {}
    did = folder_id(FOOT_ID, hit['dir']) if hit.get('id') and hit.get('dir') else ''
    return {'file': FILE_URL.format(hit['id']) if hit.get('id') else '', 'folder': FOLDER_URL.format(did) if did else '',
            'name': name}


def line(links, page=None):
    """«📄 файл целиком: <url> · стр. N · 📁 папка: <url>» — пусто, если ссылок нет"""
    bits = []
    if links.get('file'):
        bits.append(f"📄 файл целиком: {links['file']}")
        pg = page if page is not None else links.get('page')
        if pg:
            bits.append(f'стр. {pg}')
    if links.get('folder'):
        bits.append(f"📁 папка: {links['folder']}")
    return ' · '.join(bits)


if __name__ == '__main__':
    kind, arg = sys.argv[1], sys.argv[2]
    res = kb_links(arg) if kind == 'kb' else clip_links(arg)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    print(line(res))
