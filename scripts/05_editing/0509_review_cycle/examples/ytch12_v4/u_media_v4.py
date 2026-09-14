#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Загрузка картинок для дока ревью v4 (кадры frames1s + мокапы mockups/) в ПРИВАТНУЮ папку Drive
_review_v4_frames (YTCH S3/YTCH12_Sveta) → манифест {имя: thumbnailLink=s1600}. Публично НЕ шарится:
Docs API забирает thumbnailLink и хранит свою копию (фильм с ребёнком — наружу не выставляем).
⚠️ thumbnailLink живёт ~1 ч: перед сборкой дока — `--refresh` (files.list пересобирает манифест).

Usage: u_media_v4.py <wanted.json>     # ["f0123.jpg", "card_01.png", ...] → загрузить недостающие
       u_media_v4.py --refresh         # только освежить ссылки для всего, что уже в папке
Выход: media_manifest.json
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0, os.path.expanduser('~/YTAI/scripts/999_extra/ytuvi_doctabs'))
from doctab_lib import access_token, api  # noqa: E402

WORK = os.path.dirname(os.path.abspath(__file__))
PARENT = '1NQTnpDbPMhBxc8-872xWMULS5d9AC8IY'   # YTCH S3/YTCH12_Sveta
DRIVE = '0AL5m1S49VznzUk9PVA'                  # Shared Drive «YTCH»
FOLDER_NAME = '_review_v4_frames'
MANIFEST = os.path.join(WORK, 'media_manifest.json')
DIRS = [os.path.join(WORK, 'frames1s'), os.path.join(os.path.dirname(WORK), 'mockups'), os.path.join(WORK, 'frames_ins')]
MIME = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}


def ensure_folder():
    q = urllib.parse.quote(f"name = '{FOLDER_NAME}' and '{PARENT}' in parents and trashed = false")
    r = api('GET', f'https://www.googleapis.com/drive/v3/files?q={q}&corpora=drive&driveId={DRIVE}'
                   '&includeItemsFromAllDrives=true&supportsAllDrives=true&fields=files(id)')
    if r.get('files'):
        return r['files'][0]['id']
    return api('POST', 'https://www.googleapis.com/drive/v3/files?supportsAllDrives=true&fields=id',
               {'name': FOLDER_NAME, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [PARENT]})['id']


def list_folder(fid):
    out, tok = {}, ''
    while True:
        q = urllib.parse.quote(f"'{fid}' in parents and trashed = false")
        r = api('GET', f'https://www.googleapis.com/drive/v3/files?q={q}&corpora=drive&driveId={DRIVE}'
                       '&includeItemsFromAllDrives=true&supportsAllDrives=true&pageSize=1000'
                       f'&fields=nextPageToken,files(id,name,thumbnailLink){"&pageToken=" + tok if tok else ""}')
        for f in r.get('files', []):
            out[f['name']] = f
        tok = r.get('nextPageToken')
        if not tok:
            return out


def upload(path, name, parent):
    meta = json.dumps({'name': name, 'parents': [parent]}).encode()
    data = open(path, 'rb').read()
    b = uuid.uuid4().hex
    mime = MIME.get(os.path.splitext(name)[1].lower(), 'application/octet-stream')
    body = (f'--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n').encode() + meta + \
           (f'\r\n--{b}\r\nContent-Type: {mime}\r\n\r\n').encode() + data + (f'\r\n--{b}--').encode()
    req = urllib.request.Request(
        'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true'
        '&fields=id,thumbnailLink', data=body, method='POST',
        headers={'Authorization': f'Bearer {access_token()}', 'Content-Type': f'multipart/related; boundary={b}'})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def big(t):
    return t.rsplit('=s', 1)[0] + '=s1600' if t and '=s' in t else t


def main():
    folder = ensure_folder()
    have = list_folder(folder)
    wanted = [] if sys.argv[1:] == ['--refresh'] else json.load(open(sys.argv[1], encoding='utf-8'))
    for i, name in enumerate(wanted):
        if name in have:
            continue
        path = next((os.path.join(d, name) for d in DIRS if os.path.exists(os.path.join(d, name))), None)
        if not path:
            print('!! нет файла:', name, flush=True)
            continue
        for k in range(3):
            try:
                have[name] = upload(path, name, folder)
                break
            except Exception as e:                      # noqa: BLE001
                print('  retry', name, str(e)[:100], flush=True)
                time.sleep(3 * (k + 1))
        if i % 20 == 0:
            print(f'  upload {i + 1}/{len(wanted)}', flush=True)
    time.sleep(3)
    fresh = list_folder(folder)                          # свежие thumbnailLink для всего содержимого
    for _ in range(5):
        miss = [n for n, f in fresh.items() if not f.get('thumbnailLink')]
        if not miss:
            break
        time.sleep(4)
        fresh = list_folder(folder)
    man = {n: big(f['thumbnailLink']) for n, f in fresh.items() if f.get('thumbnailLink')}
    json.dump(man, open(MANIFEST, 'w'), indent=0)
    lost = [n for n in wanted if n not in man]
    print(f'folder {folder} · в папке {len(fresh)} · манифест {len(man)} · без ссылки {len(lost)}'
          + (f': {lost[:8]}' if lost else ''), flush=True)


if __name__ == '__main__':
    main()
