#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Кадры фильма во вкладке Google Doc через ВРЕМЕННЫЙ доступ по ссылке (контракт feedback-v1, §1 и §7).

Зачем это. Google Docs умеет вставить картинку только по адресу, который открывается без входа.
В кадрах фильма — ребёнок, поэтому держать их в открытой папке нельзя. Протокол здесь такой:
кадр лежит в закрытой папке → на минуту-полторы файлу выдаётся доступ «всем по ссылке» → Docs
забирает картинку к себе → доступ отзывается. Всё остальное в модуле — страховки вокруг этого окна:

  · предполётная проверка: папка кадров не должна быть открыта по ссылке (ни сама, ни через родителя) —
    иначе отзыв невозможен (Drive отвечает 403 «право унаследовано») и кадры публичны постоянно;
  · журнал выданных доступов пишется на диск ДО первой выдачи: после kill -9 следующий запуск
    (или команда --revoke-ledger) дозакроет всё, что осталось открытым;
  · отзыв — в finally, пофайлово, цикл отзыва не прерывается ничем, даже Ctrl-C / SIGTERM;
  · вставка под открытым доступом — своя обёртка: 60 с на запрос, жёсткий срок пачки, и НИКОГДА
    слепой повтор после таймаута (сервер мог уже применить запрос — будут дубли): сначала отзыв,
    затем пересчёт картинок во вкладке, и только недостающее вставляется новой выдачей;
  · ревизор (--audit): права пофайлово + запрос без входа по обоим адресам картинки.

Замер 21.09.2026: успешный отзыв = 204 с ПУСТЫМ телом; «картинка отдаётся» = Content-Type image/*,
а не код 200 (страница входа тоже 200). Поэтому здесь свой маленький Drive-клиент: клиент из
s9_materials_drive.py на пустом теле падает, и импортировать его нельзя (побочные эффекты модуля).

Остаточный риск, честно: уже вставленный кадр живёт в доке по длинному адресу googleusercontent —
любой, у кого есть доступ к доку, может его переслать. Это свойство Docs, отзыв прав его не отменяет.

CLI:
  doc_images.py --audit FOLDER_ID [--ledger PATH] [--limit N]   только чтение; код ≠ 0 при любой проблеме
  doc_images.py --revoke-ledger PATH                            дозакрыть доступы из журнала
  doc_images.py --selftest                                      офлайн, на поддельном Google
"""
import argparse
import hashlib
import http.client
import json
import os
import re
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DRIVE = 'https://www.googleapis.com/drive/v3'
UPLOAD = 'https://www.googleapis.com/upload/drive/v3'
DOCS = 'https://docs.googleapis.com/v1/documents'
URI_MAIN = 'https://drive.google.com/uc?export=view&id={id}'          # проверен на ТЗ-вкладке
URI_SPARE = 'https://lh3.googleusercontent.com/d/{id}'                # запасной (кэширующий, живёт дольше после отзыва)
RETRY_STATUS = (408, 429, 500, 502, 503, 504)
LEDGER_SCHEMA = 'feedback-grants-v1'
MSG_FOLDER_OPEN = 'папка открыта по ссылке: кадры были бы публичны постоянно'
MAX_ROUNDS = 3                     # сколько раз одну пачку можно открывать заново после срока
SETTLE = 5.0                       # пауза после отзыва перед пересчётом картинок: запоздавший запрос успевает примениться
LEDGER_KEEP_BATCHES = 200

LAST_SKIPPED = []                  # prepare(): что пропущено и почему (дублируется в out_dir/_skipped.json)

# точки подмены для самотеста
_sleep = time.sleep
_now = time.time


class Refused(RuntimeError):
    """Отказ по приватности: работать дальше нельзя."""


class InsertRejected(RuntimeError):
    """Сервер ОТВЕТИЛ отказом на вставку. Пакет Docs атомарен → ничего не применено, повтор безопасен."""


class Interrupted(KeyboardInterrupt):
    """SIGINT/SIGTERM, превращённый в исключение, чтобы отработал finally с отзывом."""


# ───────────────────────── HTTP ─────────────────────────

def _token():
    try:
        from doctab_lib import access_token
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / '999_extra' / 'ytuvi_doctabs'))
        from doctab_lib import access_token
    old = socket.getdefaulttimeout()                               # обновление токена там идёт без таймаута:
    socket.setdefaulttimeout(30)                                   # под открытым доступом зависнуть нельзя
    try:
        return access_token()
    finally:
        socket.setdefaulttimeout(old)


def _api(method, url, body=None, raw=None, ctype='application/json', timeout=60, tries=4):
    """→ (status, json|None). None — при пустом теле (204 у permissions.delete).
    Повтор только на 408/429/5xx. Сетевые сбои и таймауты НЕ глотаются и НЕ повторяются здесь:
    решает вызывающий (для вставки картинок слепой повтор запрещён)."""
    st, out = 0, None
    for k in range(max(1, tries)):
        headers = {'Authorization': f'Bearer {_token()}'}
        data = None
        if raw is not None:
            data, headers['Content-Type'] = raw, ctype
        elif body is not None:
            data, headers['Content-Type'] = json.dumps(body).encode('utf-8'), 'application/json'
        req = urllib.request.Request(url, method=method, headers=headers, data=data)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                txt = r.read()
                return r.status, (json.loads(txt) if txt and txt.strip() else None)
        except urllib.error.HTTPError as e:
            st = e.code
            try:
                detail = e.read().decode('utf-8', 'replace')
            except Exception:                                      # noqa: BLE001
                detail = ''
            try:
                detail = json.loads(detail)['error']['message']
            except Exception:                                      # noqa: BLE001
                pass
            out = {'error': str(detail)[:400]}
            if st in RETRY_STATUS and k + 1 < tries:
                _sleep(min(2 ** k, 8))
                continue
            return st, out
    return st, out


def _anon(url, timeout=30):
    """Запрос БЕЗ входа: отдаётся ли именно КАРТИНКА. Тело не читаем — хватает заголовка.
    → (True|False|None, пояснение); None = проверить не удалось (сеть)."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Cache-Control': 'no-cache'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ct = r.headers.get('Content-Type', '') or ''
            return ct.lower().startswith('image/'), f'{r.status} {ct}'
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            return False, f'HTTP {e.code}'
        return None, f'HTTP {e.code}'                              # 429/5xx: нас не пустили проверить — это не «закрыто»
    except Exception as e:                                         # noqa: BLE001
        return None, f'{type(e).__name__}'


def _err(js):
    return (js or {}).get('error', '') if isinstance(js, dict) else ''


def _write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _stamp(t=None):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(_now() if t is None else t))


# ───────────────────────── права ─────────────────────────

def _permissions(file_id):
    """Все права файла/папки (с признаком наследования). → list | raise RuntimeError."""
    out, token = [], ''
    while True:
        q = {'supportsAllDrives': 'true', 'pageSize': '100',
             'fields': 'nextPageToken,permissions(id,type,role,permissionDetails)'}
        if token:
            q['pageToken'] = token
        st, js = _api('GET', f'{DRIVE}/files/{file_id}/permissions?{urllib.parse.urlencode(q)}')
        if st != 200:
            raise RuntimeError(f'не удалось прочитать права {file_id}: {st} {_err(js)}')
        out += (js or {}).get('permissions', [])
        token = (js or {}).get('nextPageToken', '')
        if not token:
            return out


def _is_inherited(perm):
    det = perm.get('permissionDetails') or []
    return bool(det) and all(d.get('inherited') for d in det)


def _anyone(perms):
    return [p for p in perms if p.get('type') == 'anyone']


def preflight(folder_id):
    """Перед ЛЮБОЙ заливкой: у папки кадров нет ни одного права «всем по ссылке» — ни своего, ни унаследованного.
    Не удалось проверить → тоже отказ."""
    if not folder_id:
        raise Refused('не задана закрытая папка для кадров (private_frames_folder_id) — кадры в док не вставляются')
    try:
        perms = _permissions(folder_id)
    except Exception as e:                                         # noqa: BLE001
        raise Refused(f'права папки кадров проверить не удалось ({e}) — без проверки кадры не заливаются')
    bad = _anyone(perms)
    if bad:
        how = 'доступ пришёл от родительской папки' if all(_is_inherited(p) for p in bad) else 'доступ выдан на самой папке'
        raise Refused(f'{MSG_FOLDER_OPEN} ({how})')
    return None


def grant(fid):
    """Выдать файлу доступ «всем по ссылке, чтение». → perm_id | None. Наружу не бросает (кроме Ctrl-C/SIGTERM)."""
    try:
        st, js = _api('POST', f'{DRIVE}/files/{fid}/permissions?supportsAllDrives=true&fields=id,type,role',
                      {'type': 'anyone', 'role': 'reader'}, timeout=30, tries=2)
        if st == 200 and js and js.get('id'):
            return js['id']
        print(f'  доступ не выдан {fid}: {st} {_err(js)}', flush=True)
    except Exception as e:                                         # noqa: BLE001
        print(f'  доступ не выдан {fid}: {type(e).__name__} {str(e)[:120]}', flush=True)
    return None


def revoke(fid, perm_id):
    """Отозвать доступ. 204/200/404 = успех. perm_id пуст (процесс убили между выдачей и записью) →
    ищем все свои права «всем по ссылке» у файла и снимаем каждое. Наружу не бросает никогда."""
    try:
        stuck = False
        if perm_id:
            pids = [perm_id]
        else:
            pids = None
            for k in range(3):
                try:
                    found = _anyone(_permissions(fid))
                    pids = [p['id'] for p in found if not _is_inherited(p)]
                    break
                except Exception:                                  # noqa: BLE001
                    _sleep(1 + k)
            if pids is None:
                return False
            stuck = len(pids) < len(found)                         # доступ от папки-родителя отсюда не снять:
        ok = not stuck                                             # файл остаётся открытым → запись из журнала не уходит
        for pid in pids:
            done = False
            for k in range(3):                                     # сеть моргнула — пробуем ещё, DELETE безопасно повторять
                try:
                    st, _js = _api('DELETE', f'{DRIVE}/files/{fid}/permissions/{pid}?supportsAllDrives=true',
                                   timeout=30, tries=3)
                    if st in (200, 204, 404):
                        done = True
                    break                                          # сервер ответил — его ответ окончательный
                except Exception:                                  # noqa: BLE001
                    _sleep(1 + k)
            ok = ok and done
        return ok
    except Exception:                                              # noqa: BLE001
        return False


# ───────────────────────── журнал ─────────────────────────

def _ledger_load(path):
    """→ dict журнала. Нет файла → пустой. Не читается → ValueError (это проблема, а не «пусто»)."""
    path = Path(path)
    if not path.exists():
        return {'schema': LEDGER_SCHEMA, 'open': [], 'batches': [], 'result': None}
    try:
        led = json.loads(path.read_text(encoding='utf-8'))
        assert isinstance(led, dict) and isinstance(led.get('open', []), list)
        assert all(isinstance(e, dict) and e.get('fid') for e in led.get('open', []))
    except Exception as e:                                         # noqa: BLE001
        raise ValueError(f'журнал временных доступов не читается: {path} ({type(e).__name__})')
    led.setdefault('schema', LEDGER_SCHEMA)
    led.setdefault('open', [])
    led.setdefault('batches', [])
    led.setdefault('result', None)
    return led


def ledger_pending(path):
    """Записи журнала, по которым доступ мог остаться открытым. Пусто = всё закрыто."""
    return list(_ledger_load(path)['open']) if path and Path(path).exists() else []


def revoke_from_ledger(ledger_path):
    """Страховка после kill -9: закрыть всё, что числится в журнале открытым. → (revoked, failed) — списки fid.
    Вызывается в начале любого прогона и отдельной командой."""
    try:
        led = _ledger_load(ledger_path)
    except ValueError as e:
        print(f'  {e}', flush=True)
        return [], ['(журнал не читается)']
    if not led['open']:
        return [], []
    revoked, failed, keep = [], [], []
    for e in led['open']:
        if revoke(e.get('fid'), e.get('perm_id')):
            revoked.append(e.get('fid'))
        else:
            failed.append(e.get('fid'))
            keep.append(e)
    led['open'] = keep
    led['last_recovery'] = {'at': _stamp(), 'revoked': len(revoked), 'failed': len(failed)}
    _write_json_atomic(ledger_path, led)
    return revoked, failed


# ───────────────────────── подготовка и заливка ─────────────────────────

def _jpeg_bytes(path, width, quality):
    try:
        from pravki_lib import jpeg_bytes
    except BaseException:                                          # noqa: BLE001  (нет карточки и т.п.) → своя копия
        jpeg_bytes = None
    if jpeg_bytes is not None:
        return jpeg_bytes(path, width, quality)
    import io
    from PIL import Image
    im = Image.open(path).convert('RGB')
    if im.width > width:
        im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def prepare(items, out_dir, width=1000, quality=80, base_dir=None):
    """Строки feedback.json (нужны part, n, frame.file) → JPEG шириной ≤ width в out_dir.
    → [{name, path, row_key}], row_key = '{part}:{n}'. Нет исходного кадра → пропуск, причина — в LAST_SKIPPED
    и out_dir/_skipped.json. base_dir — от чего считать frame.file (по умолчанию 05_Review из карточки)."""
    global LAST_SKIPPED
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if base_dir is None:
        import proj_config as P                                    # лениво: модуль импортируется и без карточки
        base_dir = P.REVIEW_DIR
    base_dir = Path(base_dir)
    done, skipped = [], []
    for it in items or []:
        part, n = it.get('part'), it.get('n')
        key = f'{part}:{n}'
        rel = ((it.get('frame') or {}).get('file') or it.get('file') or '')
        if part is None or n is None or not rel:
            skipped.append({'row_key': key, 'why': 'у пункта нет кадра'})
            continue
        src = Path(rel) if Path(rel).is_absolute() else base_dir / rel
        if not src.is_file():
            skipped.append({'row_key': key, 'why': f'нет файла кадра: {rel}'})
            continue
        name = f'fb_p{int(part)}_{int(n):03d}.jpg'
        try:
            data = _jpeg_bytes(src, width, quality)
        except Exception as e:                                     # noqa: BLE001
            skipped.append({'row_key': key, 'why': f'кадр не читается: {rel} ({type(e).__name__})'})
            continue
        dst = out_dir / name
        if not (dst.exists() and dst.read_bytes() == data):        # те же байты → тот же md5 → повторной заливки не будет
            dst.write_bytes(data)
        done.append({'name': name, 'path': str(dst), 'row_key': key})
    LAST_SKIPPED = skipped
    _write_json_atomic(out_dir / '_skipped.json', skipped)
    return done


def _list_folder(folder_id):
    """Файлы папки (без корзины): [{id, name, md5Checksum, mimeType}]."""
    out, token = [], ''
    while True:
        q = {'q': f"'{folder_id}' in parents and trashed=false", 'pageSize': '1000',
             'supportsAllDrives': 'true', 'includeItemsFromAllDrives': 'true',
             'fields': 'nextPageToken,files(id,name,md5Checksum,mimeType)'}
        if token:
            q['pageToken'] = token
        st, js = _api('GET', f'{DRIVE}/files?{urllib.parse.urlencode(q)}')
        if st != 200:
            raise RuntimeError(f'не удалось прочитать папку {folder_id}: {st} {_err(js)}')
        out += (js or {}).get('files', [])
        token = (js or {}).get('nextPageToken', '')
        if not token:
            return out


def upload_all(folder_id, files, ids_path):
    """Залить JPEG в закрытую папку; повторный прогон ничего не льёт (сверка имя + md5). → {name: id}.
    Результат — в ids_path (pravki/feedback_frames_ids.json), атомарно, после каждого файла."""
    preflight(folder_id)
    have = {}
    for f in _list_folder(folder_id):
        have.setdefault(f.get('name'), []).append(f)
    ids_path = Path(ids_path)
    try:
        ids = json.loads(ids_path.read_text(encoding='utf-8')) if ids_path.exists() else {}
    except Exception:                                              # noqa: BLE001
        ids = {}
    up = same = 0
    for f in files:
        name, data = f['name'], Path(f['path']).read_bytes()
        md5 = hashlib.md5(data).hexdigest()
        olds = have.get(name, [])
        hit = next((o for o in olds if o.get('md5Checksum') == md5), None)
        if hit:
            ids[name] = hit['id']
            same += 1
            continue
        if olds:                                                   # имя то же, содержимое другое → обновляем тот же файл
            st, js = _api('PATCH', f'{UPLOAD}/files/{olds[0]["id"]}?uploadType=media&supportsAllDrives=true'
                                   f'&fields=id,name,md5Checksum', raw=data, ctype='image/jpeg', timeout=120)
        else:
            bnd = 'ytaiFb0undary'
            meta = json.dumps({'name': name, 'parents': [folder_id]}).encode('utf-8')
            raw = (f'--{bnd}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode() + meta +
                   f'\r\n--{bnd}\r\nContent-Type: image/jpeg\r\n\r\n'.encode() + data + f'\r\n--{bnd}--'.encode())
            st, js = _api('POST', f'{UPLOAD}/files?uploadType=multipart&supportsAllDrives=true'
                                  f'&fields=id,name,md5Checksum', raw=raw,
                          ctype=f'multipart/related; boundary={bnd}', timeout=120)
        if st != 200 or not (js or {}).get('id'):
            _write_json_atomic(ids_path, ids)
            raise RuntimeError(f'кадр {name} не залит: {st} {_err(js)}')
        if js.get('md5Checksum') and js['md5Checksum'] != md5:
            raise RuntimeError(f'кадр {name} залит с искажением (контрольная сумма не сошлась)')
        ids[name] = js['id']
        up += 1
        _write_json_atomic(ids_path, ids)
    _write_json_atomic(ids_path, ids)
    print(f'  кадры в закрытой папке: залито {up}, уже были {same}', flush=True)
    return {f['name']: ids[f['name']] for f in files if f['name'] in ids}


# ───────────────────────── вставка под временным доступом ─────────────────────────

class _SignalGuard:
    """На время работы SIGINT/SIGTERM → исключение Interrupted (чтобы отработал finally).
    Пока идёт отзыв (hold=True), сигнал только запоминается: цикл отзыва не прерывается."""

    def __init__(self):
        self.hold = False
        self.pending = None
        self._old = {}

    def _handler(self, signum, _frame):
        if self.hold:
            self.pending = signum
            return
        raise Interrupted(f'сигнал {signum}')

    def __enter__(self):
        if threading.current_thread() is threading.main_thread():
            for s in (signal.SIGINT, signal.SIGTERM):
                self._old[s] = signal.signal(s, self._handler)
        return self

    def __exit__(self, et, ev, tb):
        for s, h in self._old.items():
            signal.signal(s, h)
        if et is None and self.pending is not None:
            raise Interrupted(f'сигнал {self.pending}')
        return False


def _docs_insert(doc_id, requests, timeout=60):
    """Одна отправка, без повторов. Отказ сервера (4xx) → InsertRejected; таймаут/сеть/5xx → исключение ОС (исход неизвестен)."""
    st, js = _api('POST', f'{DOCS}/{doc_id}:batchUpdate', {'requests': requests}, timeout=timeout, tries=1)
    if st == 408 or st >= 500:                                     # сервер сломался на полпути — мог и применить:
        raise TimeoutError(f'{st} {_err(js)}')                     # это «неизвестно», а не отказ → без слепого повтора
    if st != 200:
        raise InsertRejected(f'{st} {_err(js)}')


def _count_inline(doc_id, tab_id):
    """Сколько картинок сейчас во вкладке. → int | None (не удалось узнать)."""
    try:
        st, js = _api('GET', f'{DOCS}/{doc_id}?includeTabsContent=true'
                             f'&fields=tabs(tabProperties,documentTab(inlineObjects),childTabs)', timeout=60, tries=3)
        if st != 200:
            return None

        def walk(tabs):
            for t in tabs or []:
                if (t.get('tabProperties') or {}).get('tabId') == tab_id:
                    return len((t.get('documentTab') or {}).get('inlineObjects') or {})
                r = walk(t.get('childTabs'))
                if r is not None:
                    return r
            return None
        return walk((js or {}).get('tabs'))
    except Exception:                                              # noqa: BLE001
        return None


def _jobs(img_reqs, ids):
    """Запросы вставки → задания {fid, name, req}. Запрос — {'insertInlineImage': {...}}; файл узнаём по ключу
    'name' рядом (тогда адрес подставим сами) либо по id в uri. Чужие файлы (нет в ids) не открываем.
    Порядок — по убыванию позиции: вставленное выше по индексу не сдвигает ещё не вставленное."""
    by_id = {v: k for k, v in (ids or {}).items()}
    jobs, skipped = [], []
    for q in img_reqs or []:
        ins = dict(q.get('insertInlineImage') or {})
        name = q.get('name')
        fid = (ids or {}).get(name) if name else None
        if not fid:
            m = re.search(r'(?:[?&]id=|/d/)([\w-]{10,})', ins.get('uri', '') or '')
            fid = m.group(1) if m and m.group(1) in by_id else None
            name = by_id.get(fid, name)
        if not fid or not ins.get('location'):
            skipped.append({'name': name or ins.get('uri', '?'), 'why': 'кадр не залит в закрытую папку'})
            continue
        ins['uri'] = URI_MAIN.format(id=fid)
        jobs.append({'fid': fid, 'name': name, 'req': {'insertInlineImage': ins}})
    jobs.sort(key=lambda j: -int(j['req']['insertInlineImage']['location'].get('index', 0)))
    return jobs, skipped


def _with_uri(job, tpl):
    ins = dict(job['req']['insertInlineImage'])
    ins['uri'] = tpl.format(id=job['fid'])
    return {'insertInlineImage': ins}


def _send(insert_fn, doc_id, reqs, t_end):
    """→ 'ok' | 'rejected' | 'unknown' | 'late'. unknown = таймаут/сеть: сервер мог применить, повторять вслепую нельзя."""
    left = t_end - _now()
    if left < 5:
        return 'late', 'срок пачки вышел'
    try:
        insert_fn(doc_id, reqs, timeout=max(5, min(60, left)))
        return 'ok', ''
    except (InsertRejected, urllib.error.HTTPError) as e:
        return 'rejected', str(e)[:160]
    except (TimeoutError, socket.timeout, OSError, http.client.HTTPException) as e:
        return 'unknown', f'{type(e).__name__}'


def _insert_window(insert_fn, doc_id, jobs, t_end, res):
    """Вставка одной пачки, пока открыт доступ. → (подтверждённо вставлено, спорный кусок, хвост без попытки).
    Отвергнутые сервером дописываются в res['failed']."""
    how, why = _send(insert_fn, doc_id, [j['req'] for j in jobs], t_end)
    if how == 'ok':
        return len(jobs), [], []
    if how == 'unknown':
        return 0, list(jobs), []
    if how == 'late':
        return 0, [], list(jobs)
    print(f'  пачка картинок отвергнута → по одной: {why}', flush=True)
    ok = 0
    for i, j in enumerate(jobs):                                   # по одной: битая картинка не валит пачку
        how, why = _send(insert_fn, doc_id, [j['req']], t_end)
        if how == 'rejected':                                      # вторая и последняя попытка — запасной адрес
            how, why = _send(insert_fn, doc_id, [_with_uri(j, URI_SPARE)], t_end)
        if how == 'ok':
            ok += 1
        elif how == 'rejected':
            res['failed'].append({'name': j['name'], 'why': f'Docs не принял картинку: {why}'})
        elif how == 'unknown':
            return ok, [j], jobs[i + 1:]
        else:
            return ok, [], jobs[i:]
    return ok, [], []


def insert_with_temp_grant(doc_id, img_reqs, ids, ledger_path, batch=10, insert_fn=None, deadline=90, pause=2.0):
    """Вставить картинки пачками, открывая каждый файл только на время своей пачки.
    img_reqs — запросы insertInlineImage одной вкладки (см. _jobs); ids — {name: drive id} от upload_all.
    insert_fn(doc_id, requests, timeout) — своя отправка (по умолчанию Docs batchUpdate без повторов);
    отказ сервера она сообщает исключением InsertRejected, таймаут — TimeoutError/OSError.
    → {'inserted', 'failed': [{name, why}], 'revoke_failed': [fid], 'windows': [...], 'max_window_sec'}.
    Текст вкладки должен быть записан ДО вызова: под открытым доступом делается только вставка."""
    ledger_path = Path(ledger_path)
    _rv, stuck = revoke_from_ledger(ledger_path)                   # страховка после прошлого убитого прогона
    if stuck:
        raise Refused(f'в журнале остались незакрытые доступы ({len(stuck)}) — новые кадры не открываем')
    insert_fn = insert_fn or _docs_insert
    jobs, skipped = _jobs(img_reqs, ids)
    res = {'inserted': 0, 'failed': list(skipped), 'revoke_failed': [], 'windows': [], 'max_window_sec': 0.0}
    if not jobs:
        return res
    tabs = {j['req']['insertInlineImage']['location'].get('tabId') for j in jobs}
    if len(tabs) > 1:                                              # пересчёт картинок идёт по одной вкладке
        raise ValueError('картинки одного вызова должны относиться к одной вкладке')
    tab_id = tabs.pop()
    led = _ledger_load(ledger_path)
    guard = _SignalGuard()

    def close_window(entries, win):
        """Отзыв всей пачки. Идемпотентно; сигналы на это время только запоминаются."""
        guard.hold = True
        try:
            for e in entries:
                if e.get('closed'):
                    continue
                if not e.get('tried'):                             # до выдачи дело не дошло — закрывать нечего
                    e['closed'] = True
                    continue
                e['closed'] = bool(revoke(e['fid'], e.get('perm_id')))
            bad = [e['fid'] for e in entries if not e['closed']]
            gone = {id(e) for e in entries if e['closed']}
            led['open'] = [x for x in led['open'] if id(x) not in gone]
            if 't_revoke' not in win:
                win['t_revoke'] = _stamp()
                win['window_sec'] = round(_now() - win['_t0'], 1) if win.get('_t0') else 0.0
                win['revoke_failed'] = bad
                led['batches'] = (led['batches'] + [{k: v for k, v in win.items() if not k.startswith('_')}]
                                  )[-LEDGER_KEEP_BATCHES:]
            try:
                _write_json_atomic(ledger_path, led)
            except Exception as e:                                 # noqa: BLE001
                print(f'  журнал не записан: {e}', flush=True)
            return bad
        finally:
            guard.hold = False

    finished = False
    with guard:
        try:
            for bi in range(0, len(jobs), batch):
                todo, rounds, expect = jobs[bi:bi + batch], 0, None
                while todo and rounds < MAX_ROUNDS:
                    rounds += 1
                    base = _count_inline(doc_id, tab_id)               # до выдачи: на счёт окно публичности не тратим
                    if expect is not None and base != expect:          # счёт «поплыл» уже после отзыва: запоздавший
                        res['failed'] += [{'name': j['name'], 'why': 'неизвестно, вставлен ли кадр — проверьте вкладку'}
                                          for j in todo]               # запрос мог примениться → повтор дал бы дубли
                        todo = []
                        break
                    entries = [{'fid': j['fid'], 'name': j['name'], 't_planned': _stamp()} for j in todo]
                    win = {'batch': bi // batch + 1, 'round': rounds, 'files': len(todo), 'inserted': 0}
                    led['open'] += entries
                    _write_json_atomic(ledger_path, led)               # (1) журнал — ДО первой выдачи
                    ok, doubt, rest = 0, [], []
                    try:
                        try:
                            win['_t0'] = _now()
                            win['t_grant'] = _stamp()
                            live = []
                            for e, j in zip(entries, todo):            # (2) выдача пофайлово
                                e['tried'] = True
                                pid = grant(e['fid'])
                                if pid:
                                    e['perm_id'], e['t_grant'] = pid, _stamp()
                                    live.append(j)
                                else:
                                    res['failed'].append({'name': j['name'], 'why': 'не удалось открыть кадр для вставки'})
                                _write_json_atomic(ledger_path, led)
                            if live:
                                _sleep(pause)                          # (3) доступ доезжает до отдачи ~2 с
                                ok, doubt, rest = _insert_window(insert_fn, doc_id, live, win['_t0'] + deadline, res)
                        finally:
                            bad = close_window(entries, win)           # (5) отзыв ВСЕЙ пачки
                    except Interrupted:
                        close_window(entries, win)                     # сигнал попал в щель перед отзывом — дозакрываем
                        raise
                    # доступ уже закрыт — теперь можно разбираться, что вставилось
                    expect = None
                    if doubt:
                        _sleep(SETTLE)                                 # доступ закрыт — ждать уже не страшно
                        now_n = _count_inline(doc_id, tab_id)
                        got = None if (base is None or now_n is None) else now_n - base
                        if got == ok + len(doubt):                     # сервер успел применить — повторять нельзя
                            ok, doubt = ok + len(doubt), []
                        elif got != ok:                                # счёт не сходится — не рискуем дублями
                            res['failed'] += [{'name': j['name'], 'why': 'неизвестно, вставлен ли кадр — проверьте вкладку'}
                                              for j in doubt + rest]
                            doubt, rest = [], []
                        else:
                            expect = now_n                             # «не применено»: перед новой выдачей сверим ещё раз
                    res['inserted'] += ok
                    win['inserted'] = ok
                    win['outcome'] = 'ok' if not (doubt or rest) else 'срок вышел — остаток новой выдачей'
                    if led['batches']:
                        led['batches'][-1].update(inserted=ok, outcome=win['outcome'])
                    res['windows'].append({k: v for k, v in win.items() if not k.startswith('_')})
                    res['max_window_sec'] = max(res['max_window_sec'], win.get('window_sec', 0.0))
                    todo = doubt + rest
                    if bad:
                        res['revoke_failed'] += bad
                        break
                    if guard.pending is not None:
                        break
                if todo:
                    res['failed'] += [{'name': j['name'], 'why': 'не вставлен: не уложились в срок пачки'} for j in todo]
                if res['revoke_failed'] or guard.pending is not None:  # доступ не закрывается → новых не открываем
                    break
            finished = True
        finally:                                                   # итог — в журнал и при сбое/сигнале (доступы уже закрыты)
            led['result'] = {'finished_at': _stamp(), 'complete': finished, 'inserted': res['inserted'],
                             'failed': len(res['failed']), 'revoke_failed': len(res['revoke_failed']),
                             'max_window_sec': res['max_window_sec']}
            try:
                _write_json_atomic(ledger_path, led)
            except Exception as e:                                     # noqa: BLE001
                print(f'  журнал не записан: {e}', flush=True)
    print(f'  картинки: вставлено {res["inserted"]}, не вставлено {len(res["failed"])}, '
          f'самое длинное окно доступа {res["max_window_sec"]} с, не закрыто {len(res["revoke_failed"])}', flush=True)
    return res


# ───────────────────────── ревизор ─────────────────────────

def audit(folder_id, ledger_path=None, limit=None):
    """Только чтение. → список проблем (пусто = чисто):
    открыта сама папка · у файла остался доступ по ссылке · картинка отдаётся без входа · непустой журнал."""
    problems, folder_open = [], False
    try:
        bad = _anyone(_permissions(folder_id))
        if bad:
            folder_open = True
            how = 'доступ пришёл от родительской папки' if all(_is_inherited(p) for p in bad) else 'доступ выдан на самой папке'
            problems.append(f'открыта сама папка {folder_id}: {MSG_FOLDER_OPEN} ({how})')
    except Exception as e:                                         # noqa: BLE001
        problems.append(f'права папки не проверены: {str(e)[:160]}')
    files, subfolders = [], 0
    try:
        everything = _list_folder(folder_id)
        files = [f for f in everything if f.get('mimeType') != 'application/vnd.google-apps.folder']
        subfolders = len(everything) - len(files)                  # вглубь не идём: кадры дока лежат в папке плоско
    except Exception as e:                                         # noqa: BLE001
        problems.append(f'список файлов папки не получен: {str(e)[:160]}')
    total = len(files)
    if limit:
        files = files[:limit]
    pending = []
    if ledger_path:
        try:
            pending = ledger_pending(ledger_path)
        except ValueError as e:
            problems.append(str(e))
        if pending:
            problems.append(f'журнал временных доступов не пуст: {len(pending)} записей — '
                            f'запустите doc_images.py --revoke-ledger {ledger_path}')
    seen = {f['id'] for f in files}
    files += [{'id': e['fid'], 'name': e.get('name') or e['fid']} for e in pending
              if e.get('fid') and e['fid'] not in seen]
    for f in files:                                                # у общего диска права в списке файлов не приходят
        try:
            bad = _anyone(_permissions(f['id']))
            if bad:
                tag = ' (унаследован от папки)' if all(_is_inherited(p) for p in bad) else ''
                problems.append(f'у файла {f["name"]} остался доступ по ссылке{tag}')
        except Exception as e:                                     # noqa: BLE001
            problems.append(f'права файла {f["name"]} не проверены: {str(e)[:120]}')
        for label, tpl in (('основному', URI_MAIN), ('запасному', URI_SPARE)):
            ok, info = _anon(tpl.format(id=f['id']))
            if ok:
                problems.append(f'файл {f["name"]} отдаётся как картинка без входа по {label} адресу ({info})')
            elif ok is None:
                problems.append(f'файл {f["name"]}: проверка без входа по {label} адресу не удалась ({info})')
    print(f'  ревизор: папка {"ОТКРЫТА" if folder_open else "закрыта"}, проверено файлов {len(files)} из {total}'
          f'{f" (вложенных папок {subfolders} — не проверяются)" if subfolders else ""}, проблем {len(problems)}', flush=True)
    return problems


# ───────────────────────── режим ─────────────────────────

def detect_host(review_dir=None, env=None, hostname=None):
    """'mac' | 'memex' | 'unknown'. review.py хост дочерним стадиям не передаёт, поэтому признаки свои:
    YTAI_HOST (если волна 3 начнёт его выставлять), имя машины, данные фильма под ~/YTAI_work (так они лежат
    только на Memex и в golden-прогонах). Любое сомнение — не 'mac', а значит без картинок.
    Живёт здесь, а не во вкладке: тем же признаком пользуются обе вкладки с кадрами (ТЗ и обратная связь)."""
    env = os.environ if env is None else env
    declared = str(env.get('YTAI_HOST') or '').strip().lower()
    if declared and declared != 'mac':
        return 'memex' if declared == 'memex' else 'unknown'
    try:
        name = (hostname if hostname is not None else socket.gethostname()).lower()
    except Exception:                                       # noqa: BLE001
        return 'unknown'
    if 'memex' in name:
        return 'memex'
    if review_dir is not None:
        try:
            if Path(review_dir).resolve().is_relative_to((Path.home() / 'YTAI_work').resolve()):
                return 'memex'
        except Exception:                                   # noqa: BLE001
            return 'unknown'
    return 'mac' if sys.platform == 'darwin' else 'unknown'


def detect_autonomous(ctl_dir=None, env=None):
    """автономный прогон: флаг-файл AUTONOMOUS в ~/.cache/<project>/ (его ставит review.py run --autonomous и
    держит сторож Memex) либо YTAI_AUTONOMOUS=1. Не смогли проверить — считаем автономным."""
    env = os.environ if env is None else env
    if str(env.get('YTAI_AUTONOMOUS') or '').strip().lower() in ('1', 'true', 'yes'):
        return True
    if ctl_dir is None:
        return False
    try:
        return (Path(ctl_dir) / 'AUTONOMOUS').exists()
    except Exception:                                       # noqa: BLE001
        return True


def resolve_mode(card_mode, shots_remote, cli_images, host, autonomous):
    """→ 'none' | 'public_folder' | 'temp_grant' (контракт §1).
    temp_grant сам собой не включается никогда: нужна строка в карточке И флаг --images temp И Мак И человек рядом."""
    mode = (card_mode or '').strip()
    if not mode:
        mode = 'public_folder' if shots_remote else 'none'
    if cli_images == 'none':
        return 'none'
    if mode == 'temp_grant':
        return 'temp_grant' if (cli_images == 'temp' and host == 'mac' and not autonomous) else 'none'
    if mode == 'public_folder':
        return 'public_folder' if shots_remote else 'none'
    return 'none'


def prepare_files(paths, out_dir, width=1000, quality=80):
    """Готовые картинки с диска (макеты, кадры глав) → JPEG шириной ≤ width в out_dir. → [{name, path}].

    Второй вход рядом с `prepare()`: тот берёт кадры из строк feedback.json, а вкладке «Главы» нужны
    просто файлы по именам. Имя в папке — имя исходника с расширением .jpg: по нему потом ищется id.
    Нечитаемый или отсутствующий файл не роняет запись вкладки — он попадает в LAST_SKIPPED."""
    global LAST_SKIPPED
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    done, skipped = [], []
    for src in paths or []:
        src = Path(src)
        name = src.stem + '.jpg'
        if not src.is_file():
            skipped.append({'row_key': src.name, 'why': f'нет файла: {src}'})
            continue
        try:
            data = _jpeg_bytes(src, width, quality)
        except Exception as e:                                     # noqa: BLE001
            skipped.append({'row_key': src.name, 'why': f'не читается ({type(e).__name__})'})
            continue
        dst = out_dir / name
        if not (dst.exists() and dst.read_bytes() == data):        # те же байты → тот же md5 → повторной заливки нет
            dst.write_bytes(data)
        done.append({'name': name, 'path': str(dst)})
    LAST_SKIPPED = skipped
    _write_json_atomic(out_dir / '_skipped.json', skipped)
    return done


def pick_private_mode(card_mode, shots_remote, cli_images, host, autonomous, log=print, what='вкладка'):
    """режим картинок вкладки, у которой ПУБЛИЧНОЙ папки кадров быть не должно: 'none' | 'temp_grant'.

    Такие вкладки есть у фильмов, где в кадре человек, которого нельзя показывать по ссылке
    (YTCH12 — ребёнок). Для них `public_folder` — не «чуть хуже», а запрет: постоянно открытая
    папка раздаёт кадры всем. Поэтому здесь он превращается в «без картинок», и вслух."""
    mode = resolve_mode(card_mode, shots_remote, cli_images, host, autonomous)
    if mode == 'public_folder':
        log(f'⚠️ images_mode=public_folder: {what} собирается БЕЗ картинок — открытая папка кадров '
            f'для неё не используется')
        return 'none'
    if cli_images == 'temp' and mode != 'temp_grant':
        log(f'⚠️ --images temp не сработал: в карточке images_mode={card_mode or "—"}, машина: {host}, '
            f'автономный прогон: {"да" if autonomous else "нет"} — {what} соберётся без картинок')
    return mode if mode == 'temp_grant' else 'none'


# ───────────────────────── самотест (офлайн) ─────────────────────────

class _FakeGoogle:
    """Поддельные Drive + Docs: подменяет _api и _anon, пишет порядок вызовов."""

    def __init__(self):
        self.folders = {}          # id → [perm]
        self.files = {}            # id → {'name', 'md5', 'parent', 'perms': {pid: perm}}
        self.docs = {}             # doc_id → {tab_id: [uri, …]}
        self.calls = []
        self.fail_delete = set()   # fid → DELETE отвечает 500
        self.cached = set()        # fid → картинка отдаётся без входа и без прав (кэш)
        self.on_insert = None      # hook(fake, doc_id, requests) → None | 'applied'
        self.on_delete = None
        self.on_grant = None
        self.on_count = None
        self._n = 0

    def add_file(self, folder, name, data=b'x', fid=None):
        self._n += 1
        fid = fid or f'FILE{self._n:04d}xxxxxx'
        self.files[fid] = {'name': name, 'md5': hashlib.md5(data).hexdigest(), 'parent': folder, 'perms': {}}
        return fid

    def perms_of(self, fid):
        if fid in self.folders:
            return list(self.folders[fid])
        f = self.files[fid]
        inh = [dict(p, permissionDetails=[{'inherited': True}]) for p in self.folders.get(f['parent'], [])
               if p.get('type') == 'anyone']
        return list(f['perms'].values()) + inh

    def public(self):
        return sorted(fid for fid, f in self.files.items() if any(p['type'] == 'anyone' for p in f['perms'].values()))

    def apply(self, doc_id, requests):
        for q in requests:
            ins = q['insertInlineImage']
            self.docs.setdefault(doc_id, {}).setdefault(ins['location']['tabId'], []).append(ins['uri'])

    def api(self, method, url, body=None, raw=None, ctype='application/json', timeout=60, tries=4):
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        assert 'docs.googleapis.com' in u.netloc or q.get('supportsAllDrives') == 'true', f'нет supportsAllDrives: {url}'
        m = re.search(r'/files/([^/]+)/permissions(?:/([^/?]+))?$', u.path)
        if m:
            fid, pid = m.group(1), m.group(2)
            if method == 'GET':
                self.calls.append(('perm_list', fid))
                return 200, {'permissions': self.perms_of(fid)}
            if method == 'POST':
                self.calls.append(('grant', fid))
                if self.on_grant:
                    self.on_grant(self, fid)
                self.files[fid]['perms']['anyoneWithLink'] = {'id': 'anyoneWithLink', 'type': 'anyone', 'role': 'reader',
                                                              'permissionDetails': [{'inherited': False}]}
                return 200, {'id': 'anyoneWithLink', 'type': 'anyone', 'role': 'reader'}
            if method == 'DELETE':
                self.calls.append(('revoke', fid))
                if self.on_delete:
                    self.on_delete(self, fid)
                if fid in self.fail_delete:
                    return 500, {'error': 'backend error'}
                if pid not in self.files[fid]['perms']:
                    return 404, {'error': 'Permission not found'}
                del self.files[fid]['perms'][pid]
                return 204, None                                   # как в замере: пустое тело
        if u.path.endswith('/drive/v3/files') and method == 'GET':
            folder = re.match(r"'([^']+)' in parents", q['q']).group(1)
            self.calls.append(('list', folder))
            return 200, {'files': [{'id': i, 'name': f['name'], 'md5Checksum': f['md5'], 'mimeType': 'image/jpeg'}
                                   for i, f in self.files.items() if f['parent'] == folder]}
        if '/upload/drive/v3/files' in u.path:
            if method == 'POST':
                meta = json.loads(raw.split(b'\r\n\r\n', 2)[1].split(b'\r\n--')[0])
                data = raw.split(b'Content-Type: image/jpeg\r\n\r\n', 1)[1].rsplit(b'\r\n--', 1)[0]
                fid = self.add_file(meta['parents'][0], meta['name'], data)
                self.calls.append(('upload', meta['name']))
            else:
                fid = u.path.rsplit('/', 1)[1]
                self.files[fid]['md5'] = hashlib.md5(raw).hexdigest()
                self.calls.append(('update', self.files[fid]['name']))
            return 200, {'id': fid, 'name': self.files[fid]['name'], 'md5Checksum': self.files[fid]['md5']}
        m = re.search(r'/v1/documents/([^/:]+)(:batchUpdate)?$', u.path)
        if m and m.group(2):
            self.calls.append(('insert', len(body['requests'])))
            for r in body['requests']:                             # картинка вставится, только если файл сейчас открыт
                fid = re.search(r'(?:id=|/d/)([\w-]+)', r['insertInlineImage']['uri']).group(1)
                assert fid in self.public(), 'вставка при закрытом доступе'
            if self.on_insert and self.on_insert(self, m.group(1), body['requests']) == 'applied':
                return 200, {}
            self.apply(m.group(1), body['requests'])
            return 200, {}
        if m and method == 'GET':
            self.calls.append(('count', m.group(1)))
            if self.on_count:
                self.on_count(self, m.group(1))
            return 200, {'tabs': [{'tabProperties': {'tabId': t}, 'documentTab': {'inlineObjects': {f'o{i}': {} for i in range(len(v))}}}
                                  for t, v in self.docs.get(m.group(1), {}).items()]}
        raise AssertionError(f'поддельный Google не знает запрос {method} {url}')

    def anon(self, url, timeout=30):
        fid = re.search(r'(?:id=|/d/)([\w-]+)', url).group(1)
        self.calls.append(('anon', fid))
        f = self.files.get(fid)
        if f and (fid in self.cached or any(p.get('type') == 'anyone' for p in self.perms_of(fid))):
            return True, '200 image/jpeg'
        return False, '200 text/html; charset=utf-8'                # страница входа: код 200, но не картинка


def _selftest():
    import tempfile
    g = globals()
    scratch = Path(os.environ.get('YTAI_SCRATCH') or
                   '/private/tmp/claude-501/-Users-romansergeev-YTAI/9fd8c11b-c403-4794-a26f-d2335b9adfdd/scratchpad')
    root = (scratch if scratch.is_dir() else Path(tempfile.gettempdir())) / 'doc_images'
    root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='selftest_', dir=root))
    real = {k: g[k] for k in ('_api', '_anon', '_sleep', '_now', '_token', '_write_json_atomic')}
    real_urlopen = urllib.request.urlopen
    n = [0]

    def ok(cond, what):
        assert cond, what
        n[0] += 1

    def world(n_files=10, tab='t.1'):
        fk = _FakeGoogle()
        fk.folders['PRIV'] = [{'id': 'u1', 'type': 'user', 'role': 'writer', 'permissionDetails': [{'inherited': False}]}]
        ids = {f'fb_p1_{i:03d}.jpg': fk.add_file('PRIV', f'fb_p1_{i:03d}.jpg', bytes([i])) for i in range(1, n_files + 1)}
        reqs = [{'name': nm, 'insertInlineImage': {'location': {'tabId': tab, 'index': 100 * i},
                                                    'objectSize': {'width': {'magnitude': 300, 'unit': 'PT'}}}}
                for i, nm in enumerate(ids, 1)]
        fk.docs['DOC'] = {tab: []}                                  # вкладка с текстом уже есть, картинок ещё нет
        g['_api'], g['_anon'] = fk.api, fk.anon
        led = tmp / f'ledger_{len(list(tmp.glob("ledger_*")))}.json'
        return fk, ids, reqs, led

    try:
        g['_sleep'] = lambda s: None
        g['_token'] = lambda: 'TEST'

        # ── 1. настоящий _api на поддельном urlopen: 204 с пустым телом, повторы только на 5xx ──
        class Resp:
            def __init__(self, status, data=b'', headers=None):
                self.status, self._d, self.headers = status, data, headers or {}

            def read(self):
                return self._d

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        plan, seen = [], []

        def fake_urlopen(req, timeout=None):
            seen.append((req.get_method(), req.full_url))
            r = plan.pop(0)
            if isinstance(r, int):
                import io
                raise urllib.error.HTTPError(req.full_url, r, 'x', {}, io.BytesIO(b'{"error":{"message":"boom"}}'))
            return r
        urllib.request.urlopen = fake_urlopen
        plan[:] = [Resp(204, b'')]
        ok(real['_api']('DELETE', 'https://x/y') == (204, None), '204 с пустым телом → (204, None)')
        plan[:] = [500, 503, Resp(200, b'{"a":1}')]
        ok(real['_api']('GET', 'https://x/y') == (200, {'a': 1}) and len(seen) == 4, 'повтор на 5xx')
        plan[:] = [403, Resp(200, b'{}')]
        st, js = real['_api']('DELETE', 'https://x/y')
        ok(st == 403 and js == {'error': 'boom'} and len(plan) == 1, '403 не повторяется')
        plan[:] = [Resp(204, b'')]
        ok(revoke('F', 'anyoneWithLink') is True, 'revoke на 204 с пустым телом не падает')
        # настоящий запрос без входа: решает Content-Type, а не код 200
        plan[:] = [Resp(200, b'<html>', {'Content-Type': 'text/html; charset=utf-8'})]
        ok(real['_anon']('https://x/y')[0] is False, 'страница входа с кодом 200 — не картинка')
        plan[:] = [Resp(200, b'', {'Content-Type': 'image/jpeg'})]
        ok(real['_anon']('https://x/y')[0] is True, 'image/* — картинка отдаётся')
        plan[:] = [403]
        ok(real['_anon']('https://x/y')[0] is False, '403 — не отдаётся')
        plan[:] = [429]
        ok(real['_anon']('https://x/y')[0] is None, '429 — проверить не удалось, а не «закрыто»')
        plan[:] = []
        ok(real['_anon']('https://x/y')[0] is None, 'сбой сети — проверить не удалось')
        # настоящая отправка в Docs: 4xx — отказ (повтор безопасен), 5xx — исход неизвестен (повтор запрещён)
        g['_api'] = real['_api']
        plan[:] = [400]
        try:
            _docs_insert('D', [])
            ok(False, '400 обязан стать отказом')
        except InsertRejected:
            ok(len(plan) == 0, '')
        plan[:] = [503, Resp(200, b'{}')]
        try:
            _docs_insert('D', [])
            ok(False, '503 обязан стать «неизвестно»')
        except TimeoutError:
            ok(len(plan) == 1, 'вставка на 5xx не повторяется сама')
        urllib.request.urlopen = real_urlopen

        # ── 2. штатный прогон: 25 кадров, пачки по 10; журнал ДО первой выдачи ──
        fk, ids, reqs, led = world(25)
        order = []

        def spy_write(path, data):
            if Path(path) == led:
                order.append(('ledger', [e['fid'] for e in data['open']]))
            real['_write_json_atomic'](path, data)
        g['_write_json_atomic'] = spy_write
        fk.on_grant = lambda f, fid: order.append(('grant', fid))
        peak = [0]
        fk.on_insert = lambda f, d, r: peak.__setitem__(0, max(peak[0], len(f.public())))
        res = insert_with_temp_grant('DOC', reqs, ids, led, batch=10)
        g['_write_json_atomic'] = real['_write_json_atomic']
        ok(res['inserted'] == 25 and not res['failed'] and not res['revoke_failed'], f'штатно 25: {res}')
        ok(len(fk.docs['DOC']['t.1']) == 25 == len(set(fk.docs['DOC']['t.1'])), 'нет дублей')
        ok(all(u.startswith('https://drive.google.com/uc?export=view&id=') for u in fk.docs['DOC']['t.1']), 'основной адрес')
        ok(fk.public() == [] and ledger_pending(led) == [], 'после прогона всё закрыто, журнал пуст')
        ok(peak[0] == 10, f'одновременно открыто не больше пачки: {peak[0]}')
        first_grant = next(i for i, o in enumerate(order) if o[0] == 'grant')
        ok(order[0][0] == 'ledger' and order[first_grant][1] in order[first_grant - 1][1],
           'журнал с этим файлом записан ДО первой выдачи')
        for i, o in enumerate(order):                               # и так для каждой выдачи, не только первой
            if o[0] == 'grant':
                prev = [x for x in order[:i] if x[0] == 'ledger'][-1]
                ok(o[1] in prev[1], 'файл в журнале раньше своей выдачи')
        L = json.loads(led.read_text())
        ok(len(L['batches']) == 3 and all('t_grant' in b and 't_revoke' in b and 'window_sec' in b for b in L['batches'])
           and L['result']['inserted'] == 25, 'окна публичности и итог в журнале')
        idx = [q['insertInlineImage']['location']['index'] for q in reqs]
        ok(idx == sorted(idx), 'входные запросы не тронуты')

        # ── 3. один отзыв с 500 не мешает отозвать остальные 9; запись остаётся в журнале ──
        fk, ids, reqs, led = world(10)
        bad_fid = ids['fb_p1_003.jpg']
        fk.fail_delete = {bad_fid}
        res = insert_with_temp_grant('DOC', reqs, ids, led)
        ok(fk.public() == [bad_fid] and res['revoke_failed'] == [bad_fid], 'остальные 9 отозваны')
        ok([e['fid'] for e in ledger_pending(led)] == [bad_fid], 'неотозванный остался в журнале')
        pr = audit('PRIV', led)
        ok(any('журнал' in p for p in pr) and any('остался доступ' in p for p in pr)
           and any('без входа' in p for p in pr), f'ревизор видит хвост: {pr}')
        try:
            insert_with_temp_grant('DOC', reqs, ids, led)
            ok(False, 'новый прогон при незакрытом журнале обязан отказать')
        except Refused:
            ok(True, '')
        fk.fail_delete = set()
        ok(revoke_from_ledger(led) == ([bad_fid], []) and fk.public() == [] and ledger_pending(led) == [],
           'страховка дозакрыла')
        ok(audit('PRIV', led) == [], 'после страховки ревизор чист')

        # ── 4. kill -9 между выдачей и записью perm_id: в журнале запись без perm_id ──
        fk, ids, reqs, led = world(2)
        fid = ids['fb_p1_001.jpg']
        fk.api('POST', f'{DRIVE}/files/{fid}/permissions?supportsAllDrives=true', {'type': 'anyone'})
        _write_json_atomic(led, {'schema': LEDGER_SCHEMA, 'open': [{'fid': fid, 'name': 'a', 't_planned': 'x'},
                                                                   {'fid': ids['fb_p1_002.jpg'], 'name': 'b'}]})
        ok(fk.public() == [fid], 'подготовка: файл открыт')
        rv, fl = revoke_from_ledger(led)
        ok(len(rv) == 2 and not fl and fk.public() == [] and ledger_pending(led) == [], 'отзыв без perm_id')
        led.write_text('{битый')
        ok(revoke_from_ledger(led)[1] and any('не читается' in p for p in audit('PRIV', led)), 'битый журнал — проблема')

        # ── 5. исключение посреди вставки → все выданные права отозваны, журнал пуст ──
        fk, ids, reqs, led = world(10)

        def boom(f, d, r):
            raise ZeroDivisionError('сбой посреди вставки')
        fk.on_insert = boom
        try:
            insert_with_temp_grant('DOC', reqs, ids, led)
            ok(False, 'исключение обязано выйти наружу')
        except ZeroDivisionError:
            ok(True, '')
        ok(sum(1 for c in fk.calls if c[0] == 'grant') == 10 and fk.public() == [] and ledger_pending(led) == [],
           'после исключения всё закрыто')
        L = json.loads(led.read_text())
        ok(L['result']['complete'] is False and len(L['batches']) == 1 and 't_revoke' in L['batches'][0],
           'итог и окно записаны и при сбое')

        # ── 6. SIGTERM посреди пачки → то же; обработчики сигналов возвращены ──
        fk, ids, reqs, led = world(10)
        old_term = signal.getsignal(signal.SIGTERM)

        def term(f, d, r):
            os.kill(os.getpid(), signal.SIGTERM)
            for _ in range(200):
                time.sleep(0.01)
        fk.on_insert = term
        try:
            insert_with_temp_grant('DOC', reqs, ids, led)
            ok(False, 'SIGTERM обязан выйти исключением')
        except Interrupted:
            ok(True, '')
        ok(fk.public() == [] and ledger_pending(led) == [], 'после SIGTERM всё закрыто, журнал пуст')
        ok(signal.getsignal(signal.SIGTERM) == old_term, 'обработчик SIGTERM возвращён')

        # ── 6б. SIGTERM во время самого отзыва: цикл не прерывается, исключение — после ──
        fk, ids, reqs, led = world(10)
        hit = []

        def term_in_revoke(f, fid):
            if len(hit) == 0:
                hit.append(fid)
                os.kill(os.getpid(), signal.SIGTERM)
                time.sleep(0.05)
        fk.on_delete = term_in_revoke
        try:
            insert_with_temp_grant('DOC', reqs + [dict(reqs[0])], ids, led, batch=10)
            ok(False, 'отложенный сигнал обязан выйти после отзыва')
        except Interrupted:
            ok(True, '')
        ok(fk.public() == [] and ledger_pending(led) == [], 'сигнал во время отзыва: всё закрыто')
        ok(sum(1 for c in fk.calls if c[0] == 'grant') == 10, 'после сигнала новая пачка не открывалась')

        # ── 6в. SIGINT посреди ВЫДАЧИ (открыта половина пачки) → открытое закрыто, журнал пуст ──
        fk, ids, reqs, led = world(10)
        seen_g = []

        def int_on_fifth(f, fid):
            seen_g.append(fid)
            if len(seen_g) == 5:
                os.kill(os.getpid(), signal.SIGINT)
                for _ in range(200):
                    time.sleep(0.01)
        fk.on_grant = int_on_fifth
        try:
            insert_with_temp_grant('DOC', reqs, ids, led)
            ok(False, 'SIGINT обязан выйти исключением')
        except Interrupted:
            ok(True, '')
        ok(len(seen_g) == 5 and fk.public() == [] and ledger_pending(led) == []
           and not any(c[0] == 'insert' for c in fk.calls), 'сигнал посреди выдачи: всё закрыто, вставки не было')

        # ── 6г. выдача оборвалась по таймауту, а сервер её применил → файл всё равно закрыт ──
        fk, ids, reqs, led = world(10)
        ghost = ids['fb_p1_004.jpg']

        def grant_applied_then_timeout(f, fid):
            if fid == ghost:
                f.files[fid]['perms']['anyoneWithLink'] = {'id': 'anyoneWithLink', 'type': 'anyone', 'role': 'reader',
                                                           'permissionDetails': [{'inherited': False}]}
                raise socket.timeout('timed out')
        fk.on_grant = grant_applied_then_timeout
        res = insert_with_temp_grant('DOC', reqs, ids, led)
        ok(res['inserted'] == 9 and [x['name'] for x in res['failed']] == ['fb_p1_004.jpg'], f'9 из 10: {res["failed"]}')
        ok(fk.public() == [] and ledger_pending(led) == [], 'выдача без ответа тоже отозвана')

        # ── 6д. доступ пришёл от папки-родителя: снять нельзя → запись из журнала не уходит ──
        fk, ids, reqs, led = world(1)
        fk.folders['PRIV'].append({'id': 'anyoneWithLink', 'type': 'anyone', 'role': 'reader',
                                   'permissionDetails': [{'inherited': True}]})
        _write_json_atomic(led, {'schema': LEDGER_SCHEMA, 'open': [{'fid': ids['fb_p1_001.jpg'], 'name': 'a'}]})
        ok(revoke_from_ledger(led) == ([], [ids['fb_p1_001.jpg']]) and len(ledger_pending(led)) == 1,
           'унаследованный доступ не считается закрытым')
        _write_json_atomic(led, {'schema': LEDGER_SCHEMA, 'open': [{'name': 'без id'}]})
        ok(revoke_from_ledger(led)[1] and any('не читается' in p for p in audit('PRIV', led)), 'запись без id — битый журнал')

        # ── 7. таймаут, сервер УСПЕЛ применить → отзыв раньше пересчёта, повтора нет, дублей нет ──
        fk, ids, reqs, led = world(10)

        def applied_then_timeout(f, d, r):
            f.apply(d, r)
            raise socket.timeout('timed out')
        fk.on_insert = applied_then_timeout
        res = insert_with_temp_grant('DOC', reqs, ids, led)
        kinds = [c[0] for c in fk.calls]
        i_ins = kinds.index('insert')
        ok(sum(1 for k in kinds if k == 'insert') == 1, 'слепого повтора нет')
        ok('revoke' in kinds[i_ins:] and kinds.index('count', i_ins) > max(i for i, k in enumerate(kinds) if k == 'revoke'),
           'сначала отзыв, потом пересчёт')
        ok(res['inserted'] == 10 and len(fk.docs['DOC']['t.1']) == 10 and fk.public() == [], 'нет дублей')

        # ── 7б. таймаут, сервер НЕ применил → отзыв, пересчёт, недостающее новой выдачей ──
        fk, ids, reqs, led = world(10)
        state = {'n': 0}

        def lost_once(f, d, r):
            state['n'] += 1
            if state['n'] == 1:
                raise TimeoutError('timed out')
        fk.on_insert = lost_once
        res = insert_with_temp_grant('DOC', reqs, ids, led)
        kinds = [c[0] for c in fk.calls]
        i1 = kinds.index('insert')
        i2 = kinds.index('insert', i1 + 1)
        between = kinds[i1 + 1:i2]
        ok(between.count('revoke') == 10 and 'count' in between and between.count('grant') == 10
           and between.index('revoke') < between.index('count') < between.index('grant'),
           'отзыв → пересчёт → новая выдача → повтор')
        ok(res['inserted'] == 10 and len(set(fk.docs['DOC']['t.1'])) == 10 == len(fk.docs['DOC']['t.1']), 'ровно по одной')
        ok(len(json.loads(led.read_text())['batches']) == 2 and fk.public() == [] and ledger_pending(led) == [], 'два окна')

        # ── 7в. пачка отвергнута → по одной; битый кадр пробует запасной адрес; срок вышел посреди → остаток новым окном ──
        fk, ids, reqs, led = world(10)
        clock = [1000.0]
        g['_now'] = lambda: clock[0]
        broken = ids['fb_p1_010.jpg']                               # самый большой индекс → идёт первым

        spare = []

        def picky(f, d, r):
            clock[0] += 12
            if 'lh3.googleusercontent.com/d/' in r[0]['insertInlineImage']['uri']:
                spare.append(len(r))
            if len(r) > 1 or broken in r[0]['insertInlineImage']['uri']:
                raise InsertRejected('400 bad image')
        fk.on_insert = picky

        def api_rej(method, url, body=None, **kw):
            try:
                return fk.api(method, url, body, **kw)
            except InsertRejected as e:
                return 400, {'error': str(e)}
        g['_api'] = api_rej
        res = insert_with_temp_grant('DOC', reqs, ids, led, deadline=90)
        g['_now'] = real['_now']
        ok(res['inserted'] == 9 and [x['name'] for x in res['failed']] == ['fb_p1_010.jpg'], f'9 из 10: {res["failed"]}')
        ok(len(fk.docs['DOC']['t.1']) == 9 == len(set(fk.docs['DOC']['t.1'])) and fk.public() == []
           and ledger_pending(led) == [], 'без дублей, всё закрыто')
        ok(spare == [1], 'битому кадру дана ровно одна попытка по запасному адресу')
        ok(len(res['windows']) >= 2 and all(w['window_sec'] <= 120 for w in res['windows']),
           f'срок режет окно: {[w["window_sec"] for w in res["windows"]]}')

        # ── 7г. Docs ответил 503, но успел применить → это «неизвестно»: повтора нет, дублей нет ──
        fk, ids, reqs, led = world(10)

        def api_503(method, url, body=None, **kw):
            st, js = fk.api(method, url, body, **kw)
            return (503, {'error': 'backend error'}) if url.endswith(':batchUpdate') else (st, js)
        g['_api'] = api_503
        res = insert_with_temp_grant('DOC', reqs, ids, led)
        ok(sum(1 for c in fk.calls if c[0] == 'insert') == 1 and res['inserted'] == 10
           and len(fk.docs['DOC']['t.1']) == 10 == len(set(fk.docs['DOC']['t.1'])) and fk.public() == [], '503 без дублей')

        # ── 7д. запрос применился С ОПОЗДАНИЕМ (после пересчёта) → вторая сверка ловит, повтора нет ──
        fk, ids, reqs, led = world(10)
        held = []

        def hold_then_timeout(f, d, r):
            held.append((d, r))
            raise TimeoutError('timed out')

        def late_apply(f, d):
            if held and sum(1 for c in f.calls if c[0] == 'count') == 3:    # 1 — до выдачи, 2 — после отзыва, 3 — перед повтором
                f.apply(*held.pop())
        fk.on_insert, fk.on_count = hold_then_timeout, late_apply
        res = insert_with_temp_grant('DOC', reqs, ids, led)
        ok(sum(1 for c in fk.calls if c[0] == 'insert') == 1 and sum(1 for c in fk.calls if c[0] == 'grant') == 10,
           'после «поплывшего» счёта новой выдачи и повтора нет')
        ok(len(fk.docs['DOC']['t.1']) == 10 == len(set(fk.docs['DOC']['t.1'])) and res['inserted'] == 0
           and len(res['failed']) == 10 and all('неизвестно' in x['why'] for x in res['failed'])
           and fk.public() == [] and ledger_pending(led) == [], f'опоздавший запрос: дублей нет: {res}')

        # ── 7е. запросы из двух вкладок → отказ до любой выдачи ──
        fk, ids, reqs, led = world(4)
        reqs[1] = json.loads(json.dumps(reqs[1]))
        reqs[1]['insertInlineImage']['location']['tabId'] = 't.2'
        try:
            insert_with_temp_grant('DOC', reqs, ids, led)
            ok(False, 'две вкладки обязаны дать отказ')
        except ValueError:
            ok(not any(c[0] == 'grant' for c in fk.calls), 'до выдачи дело не дошло')

        # ── 8. preflight: унаследованный и прямой anyone; закрытая папка проходит ──
        fk, ids, reqs, led = world(3)
        ok(preflight('PRIV') is None, 'закрытая папка проходит')
        fk.folders['OPEN_INH'] = [{'id': 'anyoneWithLink', 'type': 'anyone', 'role': 'reader',
                                   'permissionDetails': [{'inherited': True, 'inheritedFrom': 'SPRINT'}]}]
        fk.folders['OPEN_DIR'] = [{'id': 'anyoneWithLink', 'type': 'anyone', 'role': 'reader',
                                   'permissionDetails': [{'inherited': False}]}]
        for fo in ('OPEN_INH', 'OPEN_DIR', ''):
            try:
                preflight(fo)
                ok(False, f'preflight обязан отказать: {fo!r}')
            except Refused as e:
                ok(fo == '' or MSG_FOLDER_OPEN in str(e), str(e))
        before = len(fk.calls)
        try:
            upload_all('OPEN_INH', [{'name': 'a.jpg', 'path': __file__}], tmp / 'ids_x.json')
            ok(False, 'заливка в открытую папку обязана отказать')
        except Refused:
            ok(not any(c[0] in ('upload', 'update') for c in fk.calls[before:]), 'ничего не залито')

        # ── 9. prepare + upload_all: имена, пропуск без кадра, идемпотентность по md5 ──
        from PIL import Image
        src = tmp / 'src'
        (src / 'work/v5/hires').mkdir(parents=True)
        Image.new('RGB', (1920, 1080), (90, 120, 150)).save(src / 'work/v5/hires/h0010.jpg', 'JPEG')
        Image.new('RGB', (640, 360), (10, 20, 30)).save(src / 'work/v5/hires/h0020.jpg', 'JPEG')
        items = [{'part': 1, 'n': 4, 'frame': {'file': 'work/v5/hires/h0010.jpg'}},
                 {'part': 2, 'n': 40, 'frame': {'file': 'work/v5/hires/h0020.jpg'}},
                 {'part': 2, 'n': 41, 'frame': {'file': 'work/v5/hires/h9999.jpg'}},
                 {'part': 2, 'n': 42, 'frame': None}]
        files = prepare(items, tmp / 'frames', base_dir=src)
        ok([f['name'] for f in files] == ['fb_p1_004.jpg', 'fb_p2_040.jpg'] and files[1]['row_key'] == '2:40', 'имена')
        ok(len(LAST_SKIPPED) == 2 and len(json.loads((tmp / 'frames/_skipped.json').read_text())) == 2, 'пропуски записаны')
        ok(Image.open(files[0]['path']).width == 1000 and Image.open(files[1]['path']).width == 640, 'ширина ≤ 1000')
        idp = tmp / 'pravki' / 'feedback_frames_ids.json'
        got = upload_all('PRIV', files, idp)
        ok(set(got) == {'fb_p1_004.jpg', 'fb_p2_040.jpg'} and json.loads(idp.read_text()) == got, 'ids записаны')
        ups = sum(1 for c in fk.calls if c[0] == 'upload')
        got2 = upload_all('PRIV', prepare(items, tmp / 'frames', base_dir=src), idp)
        ok(got2 == got and sum(1 for c in fk.calls if c[0] == 'upload') == ups == 2, 'повторный прогон ничего не льёт')
        Image.new('RGB', (640, 360), (200, 20, 30)).save(src / 'work/v5/hires/h0020.jpg', 'JPEG')
        got3 = upload_all('PRIV', prepare(items, tmp / 'frames', base_dir=src), idp)
        ok(got3 == got and sum(1 for c in fk.calls if c[0] == 'update') == 1, 'изменённый кадр обновляет тот же файл')
        ok(fk.public() == [], 'заливка прав не выдаёт')

        # ── 10. ревизор: (а) оставшийся доступ, (б) картинка отдаётся без входа, (в) непустой журнал, открытая папка ──
        fk, ids, reqs, led = world(4)
        ok(audit('PRIV', led) == [], 'чистая папка — без проблем')
        fa, fb_ = ids['fb_p1_001.jpg'], ids['fb_p1_002.jpg']
        fk.files[fa]['perms']['anyoneWithLink'] = {'id': 'anyoneWithLink', 'type': 'anyone', 'role': 'reader'}
        pr = audit('PRIV')
        ok(any('fb_p1_001.jpg' in p and 'остался доступ' in p for p in pr), '(а) оставшийся доступ')
        del fk.files[fa]['perms']['anyoneWithLink']
        fk.cached = {fb_}
        pr = audit('PRIV')
        ok(len(pr) == 2 and all('fb_p1_002.jpg' in p and 'без входа' in p for p in pr), f'(б) оба адреса: {pr}')
        fk.cached = set()
        _write_json_atomic(led, {'schema': LEDGER_SCHEMA, 'open': [{'fid': fa, 'name': 'fb_p1_001.jpg'}]})
        pr = audit('PRIV', led)
        ok(len(pr) == 1 and 'журнал' in pr[0], f'(в) непустой журнал: {pr}')
        fk.folders['PRIV'].append({'id': 'anyoneWithLink', 'type': 'anyone', 'role': 'reader',
                                   'permissionDetails': [{'inherited': True}]})
        pr = audit('PRIV')
        ok(pr[0].startswith('открыта сама папка') and sum('унаследован' in p for p in pr) == 4, 'открыта сама папка')
        bad_words = re.compile(r'\b(align|OCR|VLM|overlap|status_by)\b|h\d{4}\.jpg', re.I)
        ok(not any(bad_words.search(p) for p in pr), 'в текстах проблем нет жаргона')

        # ── 11. resolve_mode: вся таблица ──
        cnt = 0
        for card in (None, '', 'none', 'public_folder', 'temp_grant', 'чушь'):
            for remote in ('', 'gdrive:x'):
                for cli in (None, 'none', 'temp'):
                    for host in ('mac', 'memex'):
                        for auto in (False, True):
                            got = resolve_mode(card, remote, cli, host, auto)
                            if cli == 'none':
                                want = 'none'
                            elif card == 'temp_grant':
                                want = 'temp_grant' if (cli == 'temp' and host == 'mac' and not auto) else 'none'
                            elif card in (None, '', 'public_folder'):
                                want = 'public_folder' if remote else 'none'
                            else:
                                want = 'none'
                            assert got == want, (card, remote, cli, host, auto, got, want)
                            if got == 'temp_grant':
                                assert card == 'temp_grant' and cli == 'temp' and host == 'mac' and not auto
                            cnt += 1
        ok(cnt == 144, 'таблица режимов')
        ok(resolve_mode('temp_grant', 'x', 'temp', 'mac', False) == 'temp_grant'
           and resolve_mode('temp_grant', 'x', 'temp', 'memex', False) == 'none'
           and resolve_mode('temp_grant', 'x', 'temp', 'mac', True) == 'none'
           and resolve_mode('temp_grant', 'x', None, 'mac', False) == 'none'
           and resolve_mode('public_folder', 'x', 'temp', 'mac', False) == 'public_folder', 'ключевые строки таблицы')
    finally:
        for k, v in real.items():
            g[k] = v
        urllib.request.urlopen = real_urlopen
    print(f'SELFTEST OK ({n[0]} проверок) · {tmp}')
    return 0


# ───────────────────────── CLI ─────────────────────────

def _default_ledger():
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import proj_config as P
        p = Path(P.WORK) / 'feedback_grants.json'
        return p if p.exists() else None
    except BaseException:                                          # noqa: BLE001  (нет карточки — журнал не ищем)
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description='Кадры в Google Doc через временный доступ: ревизор и страховка')
    ap.add_argument('--audit', metavar='FOLDER_ID', help='проверить папку кадров (только чтение)')
    ap.add_argument('--ledger', metavar='PATH', help='журнал временных доступов (по умолчанию — из карточки фильма)')
    ap.add_argument('--limit', type=int, default=0, help='проверить только первые N файлов папки')
    ap.add_argument('--revoke-ledger', metavar='PATH', help='закрыть все доступы, оставшиеся в журнале')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if a.revoke_ledger:
        rv, fl = revoke_from_ledger(a.revoke_ledger)
        print(f'закрыто доступов: {len(rv)}, не удалось закрыть: {len(fl)}')
        for f in fl:
            print(f'  ! остался открыт: {f}')
        return 1 if fl else 0
    if a.audit:
        problems = audit(a.audit, a.ledger or _default_ledger(), limit=a.limit or None)
        for p in problems[:30]:
            print(f'  ! {p}')
        if len(problems) > 30:
            print(f'  … и ещё {len(problems) - 30}')
        print('РЕВИЗОР: чисто' if not problems else f'РЕВИЗОР: проблем {len(problems)}')
        return 1 if problems else 0
    ap.print_help()
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
