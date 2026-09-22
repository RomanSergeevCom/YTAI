#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_table — запись ОДНОЙ таблицы во вкладку Google Doc (канон 5.6) без текстового поиска по ячейкам.

Зачем: сборщик ТЗ-вкладки (stages/doc_tab_tz_v3.py) держит всю запись одним куском в main(), стили ставит
поиском подстроки в ячейке (на повторе метки «❌ СЕЙЧАС ·» красит не то место), первый get_doc у него без
повтора, таймаут глобальный на процесс, а импортировать его нельзя (читает карточку при импорте). Здесь та же
механика, написанная заново как переиспользуемый писатель для вкладки «Обратная связь»:

- стили — по ЯВНЫМ спанам (start, end, key) в позициях python-строки ячейки; перевод в индексы дока (UTF-16:
  «📍», «🔴», «👁» занимают по ДВА индекса) делает write_tab;
- после текста — ОДИН сброс оформления на всю таблицу (иначе ячейки наследуют жирность последней строки шапки
  и стиль соседней ячейки), потом HEADING_3 секций, заливки, спаны, ширины;
- картинки write_tab сам не вставляет: отдаёт колбэку insert_images(tab_id, img_reqs) список
  {name, index, width_pt, col} — индексы пустых абзацев-якорей, ПО УБЫВАНИЮ индекса (вставляй в этом порядке,
  тогда индексы не едут). Картинки могут стоять в ЛЮБОЙ колонке — rows[i].imgs = [(col, line_idx, name)];
  старая форма [(line_idx, name)] значит колонку col_img. Колбэк зовётся последним: текст и стили к этому
  моменту записаны полностью;
- ссылка — спан (start, end, 'link', url): текст остаётся в ячейке, адрес уходит отдельным updateTextStyle;
- замороженную вкладку (правки Романа руками) не трогает ни при каком force;
- у каждого сетевого вызова свой таймаут; запрос, про который неизвестно, дошёл ли он (обрыв посреди
  вставки текста), НЕ повторяется — повтор задвоил бы текст. Вкладка пересобирается с нуля, поэтому лечение
  одно: запустить сборку ещё раз.

Docs API-клиент — scripts/999_extra/ytuvi_doctabs/doctab_lib.py (токен rscore), импортируется лениво, внутри
функций. Офлайн — shared/fake_docs.py: write_tab(..., get_doc=fd.get_doc, batch=fd.batch_update).

    with lock(review_dir):
        tab_id = write_tab(doc_id, 'Обратная связь · v5', head, hdr, rows, [48, 56, 310, 262],
                           frozen=frozen, force=True, insert_images=my_callback)

    python3 shared/doc_table.py --selftest      # офлайн, без сети и карточки фильма
"""
import contextlib
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE = HERE.parent
DOCTABS = STAGE.parent.parent / '999_extra' / 'ytuvi_doctabs'

TOTAL_W = 676                                   # ширина таблицы на странице дока, pt (канон 5.6)
CHUNK = 400                                     # запросов в одном batchUpdate
RED = {'red': 0.80, 'green': 0.05, 'blue': 0.05}
GREEN = {'red': 0.07, 'green': 0.50, 'blue': 0.16}
GREY = {'red': 0.45, 'green': 0.45, 'blue': 0.45}
ORANGE = {'red': 0.85, 'green': 0.45, 'blue': 0.0}          # «ждёт фонда», «блюр — делает монтажёр»: ни красный, ни зелёный
HEAD_KINDS = ('h1', 'meta', 'warn', 'tally', 'list_head', 'list_item', 'how')
ROW_KINDS = ('sec', 'item', 'list')
STYLE_KEYS = ('label', 'title', 'was', 'now', 'warn', 'cap', 'muted', 'sec', 'link')
RESET_FIELDS = 'bold,italic,strikethrough,underline,fontSize,foregroundColor,backgroundColor'

# insertText молча выбрасывает управляющие знаки и частную область Юникода, \v превращает в разрыв строки —
# после такого текст в доке короче отправленного и все индексы (шапка, спаны, якоря картинок) едут
BAD_CHARS = re.compile('[\x00-\x08\x0b-\x1f\ue000-\uf8ff]')

LAST = {}                                       # итог последнего write_tab: tab_id, img_reqs, stats (для проверок)
_sleep = time.sleep                             # самопроверка подменяет, чтобы не ждать backoff


# ═══════════════════ индексы ═══════════════════
def u16(s):
    """длина строки в единицах UTF-16 — в них считает индексы Docs API (эмодзи вне BMP = 2)"""
    return len(str(s).encode('utf-16-le')) // 2


def index_of(cell_start, text, offset):
    """позиция offset в python-строке text ячейки → индекс документа; cell_start — индекс первого знака ячейки"""
    if not 0 <= offset <= len(text):
        raise ValueError(f'позиция {offset} вне текста ячейки (длина {len(text)})')
    return cell_start + u16(text[:offset])


def cell_text(cell):
    """текст ячейки из ответа get_doc (только textRun; картинки текста не дают)"""
    return ''.join(e['textRun'].get('content', '') for c in cell.get('content', [])
                   for e in c.get('paragraph', {}).get('elements', []) if 'textRun' in e)


def iter_tabs(doc):
    def walk(tabs):
        for t in tabs:
            yield t
            yield from walk(t.get('childTabs', []))
    yield from walk(doc.get('tabs', []))


class CellText:
    """сборка текста ячейки вместе со спанами — чтобы позиции не считать руками и не искать подстроку потом.

        c = CellText(); c.add('❌ СЕЙЧАС ·', 'label'); c.add(' титр с ошибкой'); c.nl()
        row['cells'][2], row['spans'][2] = c.text, c.spans
    """

    def __init__(self):
        self.text, self.spans = '', []

    def add(self, s, key=None, url=None):
        s = str(s)
        if key and s:
            self.spans.append((len(self.text), len(self.text) + len(s), key) + ((url,) if url else ()))
        self.text += s
        return self

    def nl(self):
        self.text += '\n'
        return self

    def line_idx(self):
        """номер текущей строки ячейки (для imgs: пустая строка-якорь)"""
        return self.text.count('\n')


# ═══════════════════ сеть ═══════════════════
def _doctab():
    if str(DOCTABS) not in sys.path:
        sys.path.insert(0, str(DOCTABS))
    import doctab_lib  # noqa: E402  (лениво: офлайн-прогоны и самопроверка обходятся без него)
    return doctab_lib


def _token(timeout):
    """токен rscore со своим таймаутом: doctab_lib.access_token меняет refresh-токен через urlopen БЕЗ таймаута.
    Кэш общий с doctab_lib (_tok), чтобы соседние модули не обменивали токен второй раз."""
    lib = _doctab()
    if time.time() - lib._tok[1] > 2400:
        import urllib.parse
        t = json.loads(Path(lib.TOKEN_FILE).read_text(encoding='utf-8'))
        data = urllib.parse.urlencode({'client_id': t['client_id'], 'client_secret': t['client_secret'],
                                       'refresh_token': t['refresh_token'], 'grant_type': 'refresh_token'}).encode()
        req = urllib.request.Request(t.get('token_uri', 'https://oauth2.googleapis.com/token'), data=data)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            lib._tok[0] = json.load(r)['access_token']
        lib._tok[1] = time.time()
    return lib._tok[0]


class _NotSent(OSError):
    """сбой до отправки запроса в док (не получен токен): повтор безопасен для любых запросов"""


def _http(method, url, body, timeout):
    """вызов Docs API со СВОИМ таймаутом (doctab_lib.api зовёт urlopen без таймаута и может висеть вечно;
    socket.setdefaulttimeout не трогаем — он общий на процесс)"""
    try:
        token = _token(timeout)
    except OSError as e:                                    # таймаут/отказ сервера токенов: в док ещё ничего не ушло
        raise _NotSent(f'не получен токен доступа: {str(e)[:120]}') from e
    req = urllib.request.Request(url, method=method, headers={'Authorization': f'Bearer {token}',
                                                              'Content-Type': 'application/json'})
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = e.read().decode('utf-8', 'replace')[:600]
        except Exception:                                   # noqa: BLE001
            pass
        raise RuntimeError(f'Docs API {e.code}: {detail}') from e


def _never_sent(e):
    """сбой ДО отправки запроса (нет DNS, порт закрыт): повтор безопасен даже для вставки текста"""
    r = getattr(e, 'reason', e)
    return isinstance(e, _NotSent) or isinstance(r, (socket.gaierror, ConnectionRefusedError))


def get_doc_retry(doc_id, tries=4, *, timeout=300, call=None, log=print):
    """get_doc с повтором на любые сбои (чтение — повторять можно всегда). Док с десятком вкладок тянется ~30 с."""
    for k in range(tries):
        try:
            if call is not None:
                return call(doc_id)
            return _http('GET', f'https://docs.googleapis.com/v1/documents/{doc_id}?includeTabsContent=true',
                         None, timeout)
        except Exception as e:                              # noqa: BLE001
            if k == tries - 1:
                raise
            log(f'  чтение дока, повтор {k + 1}: {str(e)[:100]}')
            _sleep(10 * (k + 1))


def batch_update(doc_id, reqs, tries=5, timeout=180, *, idempotent=False, call=None, log=print):
    """batchUpdate с backoff и своим таймаутом на вызов.

    429/503 и сбои до отправки — повторяем всегда. Таймаут, обрыв соединения, 500/502/504 — запрос мог
    примениться: повторяем только idempotent=True (стили, заливки, ширины). Для вставок текста/таблицы
    повтор задвоил бы содержимое, поэтому падаем с понятным текстом: вкладку пересобрать заново.
    """
    if not reqs:
        return {'replies': []}
    for k in range(tries):
        last = k == tries - 1
        try:
            if call is not None:
                return call(doc_id, reqs)
            return _http('POST', f'https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate',
                         {'requests': reqs}, timeout)
        except RuntimeError as e:
            m = re.search(r'Docs API (\d+)', str(e))
            code = m.group(1) if m else ''
            safe = code in ('429', '503') or (idempotent and code in ('500', '502', '504'))
            if code in ('500', '502', '504') and not idempotent:
                raise RuntimeError(_AMBIG.format(why=f'ответ {code}')) from e
            if not safe or last:
                raise
        except OSError as e:                                # таймаут, обрыв, URLError
            if not (idempotent or _never_sent(e)):
                raise RuntimeError(_AMBIG.format(why=str(e)[:120])) from e
            if last:
                raise
        log(f'  запись в док, повтор {k + 1} через {6 * 2 ** k} с')
        _sleep(6 * 2 ** k)


_AMBIG = ('связь оборвалась посреди записи ({why}): неизвестно, дошёл ли запрос. Повторять его нельзя — текст '
          'задвоится. Запусти сборку вкладки заново с --force: она пересобирается с нуля.')


# ═══════════════════ замок ═══════════════════
_HELD = set()


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError, OverflowError):
        return False
    return True


@contextlib.contextmanager
def lock(review_dir, what='doc_write'):
    """PID-замок {review_dir}/logs/doc_write.lock: две записи в один док одновременно портят индексы друг другу.

    Отказ (SystemExit), если замок держит живой чужой процесс или этот же процесс уже пишет. Замок умершего
    процесса снимается молча. Замок локален для машины: прогон на Memex с Мака не виден (у замка с другого
    хоста pid не проверить — считаем его живым 2 часа).
    """
    path = Path(review_dir) / 'logs' / 'doc_write.lock'
    key = str(path.resolve())
    if key in _HELD:
        raise SystemExit(f'запись в док уже идёт в этом процессе ({path})')
    path.parent.mkdir(parents=True, exist_ok=True)
    me = {'pid': os.getpid(), 'host': socket.gethostname(), 'what': what,
          'started': time.strftime('%Y-%m-%d %H:%M:%S')}
    for attempt in (1, 2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                other = json.loads(path.read_text(encoding='utf-8'))
            except Exception:                               # noqa: BLE001  (битый/полузаписанный замок)
                other = None
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:                                 # замок сняли, пока мы смотрели — пробуем ещё раз
                if attempt == 2:
                    raise SystemExit(f'замок {path} меняется прямо сейчас — в док пишет другой процесс, повтори позже')
                continue
            if not isinstance(other, dict):                 # файл создан, но ещё не дописан: соседний процесс берёт
                other, fresh = {}, age < 10                 # замок в эту секунду; старый битый файл — мусор
            else:
                fresh = False
            try:
                pid = int(other.get('pid') or 0)
            except (TypeError, ValueError):
                pid = 0
            host = other.get('host') or me['host']
            if fresh:
                busy = True
            elif host != me['host']:
                busy = age < 7200
            else:
                busy = pid > 0 and pid != me['pid'] and _alive(pid)
            if busy or attempt == 2:
                raise SystemExit(f'в док сейчас пишет другой процесс: pid {pid}, {host}, с {other.get("started", "?")} '
                                 f'({other.get("what", "?")}). Дождись его или убери {path}, если он точно мёртв.')
            path.unlink(missing_ok=True)                    # замок умершего процесса
            continue
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(me, f, ensure_ascii=False)
        break
    _HELD.add(key)
    try:
        yield path
    finally:
        _HELD.discard(key)
        try:
            if json.loads(path.read_text(encoding='utf-8')).get('pid') == me['pid']:
                path.unlink()
        except Exception:                                   # noqa: BLE001
            pass


# ═══════════════════ стили ═══════════════════
def _pt(n):
    return {'magnitude': n, 'unit': 'PT'}


def _rgb(c):
    if isinstance(c, dict):
        return c
    r, g, b = [float(x) for x in c]
    if max(r, g, b) > 1:                                    # (217, 237, 217) → доли
        r, g, b = r / 255, g / 255, b / 255
    return {'red': round(r, 4), 'green': round(g, 4), 'blue': round(b, 4)}


def span_style(key, font=9, url=None):
    """ключ спана → (textStyle, fields). url — только для 'link' (обязателен)."""
    if key in ('label', 'title'):
        return {'bold': True}, 'bold'
    if key == 'sec':                                        # после HEADING_3: именованный стиль сбрасывает кегль
        return {'bold': True, 'fontSize': _pt(font + 1)}, 'bold,fontSize'
    if key in ('was', 'now', 'warn'):                       # «было» красным, «стало» зелёным, «ждёт» оранжевым; БЕЗ зачёркивания
        color = {'was': RED, 'now': GREEN, 'warn': ORANGE}[key]
        return ({'bold': True, 'strikethrough': False, 'foregroundColor': {'color': {'rgbColor': color}}},
                'bold,strikethrough,foregroundColor')
    if key == 'cap':
        return {'bold': True, 'fontSize': _pt(8)}, 'bold,fontSize'
    if key == 'muted':
        return {'fontSize': _pt(8), 'foregroundColor': {'color': {'rgbColor': GREY}}}, 'fontSize,foregroundColor'
    if key == 'link':                                       # мелким, адрес — в самом стиле; цвет и подчёркивание ставит Docs
        if not url or not re.match(r'^https?://\S+$', str(url)):
            raise ValueError(f'спан link без годного адреса: {url!r}')
        return {'fontSize': _pt(8), 'link': {'url': str(url)}}, 'fontSize,link'
    raise ValueError(f'неизвестный ключ стиля: {key!r} (есть: {", ".join(STYLE_KEYS)})')


def _span4(t):
    """(s, e, key) | (s, e, key, url) → (s, e, key, url|None)"""
    if len(t) == 3:
        return (t[0], t[1], t[2], None)
    if len(t) == 4:
        return (t[0], t[1], t[2], t[3] or None)
    raise ValueError(f'спан {t!r}: ожидается (start, end, key[, url])')


def _prepare(head, hdr, rows, widths, col_img):
    """проверка входа ДО любого обращения к доку + нормализация строк → [{kind, cells, spans, fill, imgs, head_col}]"""
    ncol = len(hdr)
    if len(widths) != ncol:
        raise ValueError(f'ширин {len(widths)}, колонок {ncol}')
    if sum(widths) != TOTAL_W:
        raise ValueError(f'сумма ширин колонок {sum(widths)} pt, должна быть {TOTAL_W}')
    if not 0 <= col_img < ncol:
        raise ValueError(f'колонка картинок {col_img} вне таблицы')
    for kind, text in head:
        if kind not in HEAD_KINDS:
            raise ValueError(f'неизвестный вид абзаца шапки: {kind!r}')
        if BAD_CHARS.search(str(text)):                     # индексы шапки считаем сами, сверить их потом не с чем
            raise ValueError(f'шапка, абзац «{str(text)[:40]}»: есть знак, который Docs выбросит при вставке '
                             f'({BAD_CHARS.search(str(text)).group()!r}) — индексы уедут')
    if any(BAD_CHARS.search(str(h)) for h in hdr):
        raise ValueError('заголовки колонок: есть знак, который Docs выбросит при вставке — индексы уедут')
    out = []
    for ri, r in enumerate(rows, start=1):
        where = f'строка {ri}'
        if r.get('kind') not in ROW_KINDS:
            raise ValueError(f'{where}: вид {r.get("kind")!r} (есть: {", ".join(ROW_KINDS)})')
        cells = [str(c) for c in r.get('cells') or []]
        if len(cells) != ncol:
            raise ValueError(f'{where}: ячеек {len(cells)}, колонок {ncol}')
        for cj, c in enumerate(cells):
            m = BAD_CHARS.search(c)
            if m:
                raise ValueError(f'{where}, колонка {cj}: в тексте знак {m.group()!r} — Docs его выбросит или '
                                 f'переиначит, индексы уедут')
        spans = {}
        for cj, lst in (r.get('spans') or {}).items():
            cj = int(cj)
            if not 0 <= cj < ncol:
                raise ValueError(f'{where}: спаны для колонки {cj}, которой нет')
            for t in lst:
                s, e, key, url = _span4(t)
                span_style(key, url=url)
                if not 0 <= s < e <= len(cells[cj]):
                    raise ValueError(f'{where}, колонка {cj}: спан ({s}, {e}, {key}) вне текста длиной {len(cells[cj])}')
                spans.setdefault(cj, []).append((s, e, key, url))
        lines = cells[col_img].split('\n')
        for cap in r.get('caps') or []:                     # подписи под превью: номер строки ячейки или сама строка
            li = cap if isinstance(cap, int) else next(
                (i for i, ln in enumerate(lines) if ln == cap and ln), None)
            if li is None or not -len(lines) <= li < len(lines) or not lines[li]:
                raise ValueError(f'{where}: подпись {cap!r} не найдена целой строкой в колонке картинок')
            li %= len(lines)
            s = len('\n'.join(lines[:li])) + (1 if li else 0)
            spans.setdefault(col_img, []).append((s, s + len(lines[li]), 'cap', None))
        imgs = []                                           # (col, line_idx, name); (line_idx, name) = колонка col_img
        for t in r.get('imgs') or []:
            if len(t) == 2:
                cj, li, name = col_img, t[0], t[1]
            elif len(t) == 3:
                cj, li, name = int(t[0]), t[1], t[2]
            else:
                raise ValueError(f'{where}: картинка {t!r} — ожидается (col, line_idx, name) или (line_idx, name)')
            if not 0 <= cj < ncol:
                raise ValueError(f'{where}: картинка {name} — колонки {cj} в таблице нет')
            clines = cells[cj].split('\n')
            if not -len(clines) <= li < len(clines):
                raise ValueError(f'{where}: картинка {name} — строки {li} в ячейке колонки {cj} нет')
            li %= len(clines)
            if clines[li] != '':
                raise ValueError(f'{where}: картинка {name} — строка {li} колонки {cj} не пустая, нужен пустой абзац-якорь')
            imgs.append((cj, li, name))
        if len({(cj, li) for cj, li, _ in imgs}) != len(imgs):
            raise ValueError(f'{where}: две картинки на одну строку-якорь')
        head_col = None
        if r['kind'] == 'sec':
            head_col = r.get('head_col')
            if head_col is None:
                head_col = next((j for j, c in enumerate(cells) if c.strip()), None)
            for j, c in enumerate(cells):                   # у секции без своих спанов — вся строка жирная
                if c.strip() and j not in spans:
                    spans[j] = [(0, len(c), 'sec', None)]
        out.append({'kind': r['kind'], 'cells': cells, 'spans': spans, 'imgs': imgs, 'head_col': head_col,
                    'fill': _rgb(r['fill']) if r.get('fill') else None})
    return out


# ═══════════════════ запись ═══════════════════
def write_tab(doc_id, title, head, hdr, rows, widths, *, col_img=3, img_w=250, font=9, frozen=(), force=False,
              insert_images=None, get_doc=None, batch=None, log=print, after=()):
    """вкладка title дока doc_id ← шапка head + ОДНА таблица (hdr + rows). → tab_id

    head   [(kind, text)], kind: h1|meta|warn|tally|list_head|list_item|how. h1 → HEADING_1, warn и list_head —
           жирные, meta — серый; пишется одной пачкой.
    rows   [{kind: 'sec'|'item'|'list', cells: [str]*len(hdr), spans: {col: [(start, end, key[, url])]},
             fill: (r, g, b)|None, imgs: [(col, line_idx, name)] | [(line_idx, name)], caps: [line_idx|строка],
             head_col: int|None}]
           спаны — в позициях python-строки ячейки (удобно собирать через CellText); ключи стилей: label, title,
           was, now, warn, cap, muted, sec, link (четвёртый элемент — адрес). У строки 'sec' абзац ячейки head_col
           (по умолчанию — первая непустая) становится HEADING_3 — глава в навигаторе дока.
    imgs   строка line_idx ячейки col (пара без col — колонка col_img) обязана быть пустой — это абзац-якорь
           картинки. Сам write_tab картинки не вставляет: insert_images(tab_id, [{name, index, width_pt, col}, …])
           получает индексы по убыванию. insert_images=None → картинок нет, пустые абзацы остаются.
    img_w  ширина картинок, pt: число — для всех; словарь {col: pt} — по колонке (нет колонки → col_img → 250).
    frozen пары (doc_id, заголовок вкладки): такую вкладку не трогаем НИ ПРИ КАКОМ force.
    force  разрешение перезаписать НЕпустую незамороженную вкладку.
    get_doc / batch — подмена сети (FakeDocs.get_doc / FakeDocs.batch_update).
    after — функции tab_id → запрос batchUpdate, которые идут ПОСЛЕ таблицы тем же каналом (например формат страницы
    вкладки): в офлайн-двойнике они ложатся в дамп, в самопроверке живого пути не рвутся в сеть.
    """
    rows_n = _prepare(head, hdr, rows, widths, col_img)
    hdr = [str(h) for h in hdr]
    frozen = {tuple(x) for x in (frozen or ())}
    if (doc_id, title) in frozen:
        raise SystemExit(f'вкладка «{title}» в этом доке заморожена: в ней ручные правки. force заморозку не снимает.')

    def send(reqs, idempotent=False):
        for i in range(0, len(reqs), CHUNK):
            batch_update(doc_id, reqs[i:i + CHUNK], idempotent=idempotent, call=batch, log=log)

    def tab_of(doc, tab_id):
        for t in iter_tabs(doc):
            if t['tabProperties']['tabId'] == tab_id:
                return t
        raise SystemExit(f'вкладка {tab_id} пропала из дока посреди записи')

    # ── вкладка: по имени или новая ──
    doc = get_doc_retry(doc_id, call=get_doc, log=log)
    found = [t for t in iter_tabs(doc) if t['tabProperties'].get('title') == title]
    if len(found) > 1:
        raise SystemExit(f'в доке {len(found)} вкладки с именем «{title}» — непонятно, какую писать')
    if found:
        tab = found[0]
        tab_id, now_title = tab['tabProperties']['tabId'], tab['tabProperties'].get('title')
        if (doc_id, now_title) in frozen:                   # сторож смотрит на ТЕКУЩЕЕ имя найденной вкладки
            raise SystemExit(f'вкладка «{now_title}» в этом доке заморожена: в ней ручные правки. '
                             f'force заморозку не снимает.')
        log(f'вкладка найдена: {tab_id}')
    else:
        resp = batch_update(doc_id, [{'addDocumentTab': {'tabProperties': {'title': title}}}], call=batch, log=log)
        tab_id = resp['replies'][0]['addDocumentTab']['tabProperties']['tabId']
        tab = tab_of(get_doc_retry(doc_id, call=get_doc, log=log), tab_id)
        log(f'вкладка создана: {tab_id}')

    # ── очистка ──
    body = tab['documentTab']['body']['content']
    busy = any('table' in c for c in body) or any(
        ('inlineObjectElement' in e) or e.get('textRun', {}).get('content', '').strip()
        for c in body for e in c.get('paragraph', {}).get('elements', []))
    if busy and not force:
        raise SystemExit(f'вкладка «{title}» не пустая. Перезаписать — только с force (--force).')
    start = next(c for c in body if 'paragraph' in c or 'table' in c)['startIndex']
    end = body[-1]['endIndex'] - 1
    if end > start:
        send([{'deleteContentRange': {'range': {'tabId': tab_id, 'startIndex': start, 'endIndex': end}}}])
        log('вкладка очищена')

    # ── шапка одной пачкой: индексы считаем сами ──
    cur, reqs = start, []
    for kind, text in head:
        text = str(text)
        n = u16(text) + 1
        reqs += [{'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': text + '\n'}},
                 {'updateParagraphStyle': {
                     'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + n},
                     'paragraphStyle': {'namedStyleType': 'HEADING_1' if kind == 'h1' else 'NORMAL_TEXT'},
                     'fields': 'namedStyleType'}}]
        if text and kind != 'h1':                           # явно: иначе абзац наследует жирность предыдущего
            ts = {'bold': kind in ('warn', 'list_head')}
            if kind == 'meta':
                ts['foregroundColor'] = {'color': {'rgbColor': GREY}}
            reqs.append({'updateTextStyle': {'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + n - 1},
                                             'textStyle': ts, 'fields': 'bold,foregroundColor'}})
        cur += n
    send(reqs)
    log(f'шапка: {len(head)} абзацев')

    # ── таблица + текст ячеек с конца, чтобы индексы не ехали ──
    send([{'insertTable': {'location': {'tabId': tab_id, 'index': cur}, 'rows': len(rows_n) + 1, 'columns': len(hdr)}}])

    def table_now():
        content = tab_of(get_doc_retry(doc_id, call=get_doc, log=log), tab_id)['documentTab']['body']['content']
        return [el for el in content if 'table' in el][-1]

    all_cells = [hdr] + [r['cells'] for r in rows_n]
    grid = [row['tableCells'] for row in table_now()['table']['tableRows']]
    reqs = []
    for ri in range(len(all_cells) - 1, -1, -1):
        for cj in range(len(hdr) - 1, -1, -1):
            if all_cells[ri][cj]:
                reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': grid[ri][cj]['content'][0]['startIndex']},
                                            'text': all_cells[ri][cj]}})
    send(reqs)
    log(f'текст: {len(reqs)} ячеек')

    # ── оформление ──
    tbl = table_now()
    tstart = tbl['startIndex']
    grid = [row['tableCells'] for row in tbl['table']['tableRows']]
    starts = [[c['content'][0]['startIndex'] for c in row] for row in grid]
    drift = [(ri, cj) for ri, row in enumerate(grid) for cj, c in enumerate(row)
             if cell_text(c) != all_cells[ri][cj] + '\n']
    if drift:                                               # Docs переиначил текст — спаны легли бы мимо
        raise RuntimeError(f'текст {len(drift)} ячеек в доке не совпал с отправленным (первая: строка {drift[0][0]}, '
                           f'колонка {drift[0][1]}); стили не ставлю')

    def rng(a, b):
        return {'tabId': tab_id, 'startIndex': a, 'endIndex': b}

    # 1) ОДИН сброс на всю таблицу — отдельной пачкой, строго раньше всего остального
    reset_style = {'bold': False, 'italic': False, 'strikethrough': False, 'underline': False, 'fontSize': _pt(font)}
    whole = {'updateTextStyle': {'range': rng(starts[0][0], grid[-1][-1]['endIndex']),
                                 'textStyle': reset_style, 'fields': RESET_FIELDS}}
    try:
        send([whole], idempotent=True)
    except RuntimeError as e:
        if 'Docs API 400' not in str(e):
            raise
        log('  сброс одним диапазоном не принят — сбрасываю по ячейкам')
        send([{'updateTextStyle': {'range': rng(starts[ri][cj], c['endIndex']), 'textStyle': reset_style,
                                   'fields': RESET_FIELDS}}
              for ri, row in enumerate(grid) for cj, c in enumerate(row)], idempotent=True)

    # 2) HEADING_3 секций (раньше спанов: именованный стиль сбрасывает кегль) → 3) заливки → 4) спаны → 5) ширины
    heads, fills, spans = [], [], []
    for cj, h in enumerate(hdr):                            # строка заголовков — жирная
        if h:
            spans.append({'updateTextStyle': {'range': rng(starts[0][cj], starts[0][cj] + u16(h)),
                                              'textStyle': {'bold': True}, 'fields': 'bold'}})
    for ri, r in enumerate(rows_n, start=1):
        if r['kind'] == 'sec' and r['head_col'] is not None:
            a = starts[ri][r['head_col']]
            first_line = r['cells'][r['head_col']].split('\n')[0]
            heads.append({'updateParagraphStyle': {'range': rng(a, a + u16(first_line) + 1),
                                                   'paragraphStyle': {'namedStyleType': 'HEADING_3'},
                                                   'fields': 'namedStyleType'}})
        if r['fill']:
            fills.append({'updateTableCellStyle': {
                'tableRange': {'tableCellLocation': {'tableStartLocation': {'tabId': tab_id, 'index': tstart},
                                                     'rowIndex': ri, 'columnIndex': 0},
                               'rowSpan': 1, 'columnSpan': len(hdr)},
                'tableCellStyle': {'backgroundColor': {'color': {'rgbColor': r['fill']}}},
                'fields': 'backgroundColor'}})
        for cj in sorted(r['spans']):
            for s, e, key, url in r['spans'][cj]:
                ts, fields = span_style(key, font, url)
                spans.append({'updateTextStyle': {
                    'range': rng(index_of(starts[ri][cj], r['cells'][cj], s), index_of(starts[ri][cj], r['cells'][cj], e)),
                    'textStyle': ts, 'fields': fields}})
    cols = [{'updateTableColumnProperties': {
        'tableStartLocation': {'tabId': tab_id, 'index': tstart}, 'columnIndices': [cj],
        'tableColumnProperties': {'widthType': 'FIXED_WIDTH', 'width': _pt(w)}, 'fields': 'widthType,width'}}
        for cj, w in enumerate(widths)]
    send(heads + fills + spans + cols, idempotent=True)
    log(f'оформление: секций {len(heads)}, заливок {len(fills)}, спанов {len(spans)}')

    # ── картинки: только адреса якорей, по убыванию индекса ──
    img_reqs = []
    for ri, r in enumerate(rows_n, start=1):
        for cj, li, name in r['imgs']:
            lines = r['cells'][cj].split('\n')
            off = len('\n'.join(lines[:li])) + (1 if li else 0)
            w = img_w.get(cj, img_w.get(col_img, 250)) if isinstance(img_w, dict) else img_w
            img_reqs.append({'name': name, 'index': index_of(starts[ri][cj], r['cells'][cj], off),
                             'width_pt': w, 'col': cj})
    img_reqs.sort(key=lambda q: -q['index'])
    LAST.clear()
    LAST.update({'tab_id': tab_id, 'img_reqs': img_reqs, 'images': None,
                 'stats': {'rows': len(rows_n), 'heads': len(heads), 'fills': len(fills), 'spans': len(spans)}})
    if insert_images is not None and img_reqs:
        LAST['images'] = insert_images(tab_id, img_reqs)
    elif img_reqs:
        log(f'картинки пропущены: {len(img_reqs)} пустых абзацев-якорей оставлены')
    extra = [fn(tab_id) for fn in after]
    if extra:
        send(extra, idempotent=True)
        log(f'после таблицы: запросов {len(extra)} (формат страницы вкладки и т.п.)')
    return tab_id


# ═══════════════════ самопроверка (офлайн, FakeDocs) ═══════════════════
def _atoms(tab):
    """вкладка из get_doc → [(индекс, знак|None для картинки, ширина)] по всему телу, включая ячейки"""
    out = []

    def walk(content):
        for c in content:
            for e in c.get('paragraph', {}).get('elements', []):
                i = e['startIndex']
                if 'textRun' in e:
                    for ch in e['textRun']['content']:
                        w = 2 if ord(ch) > 0xFFFF else 1
                        out.append((i, ch, w))
                        i += w
                else:
                    out.append((i, None, 1))
            for row in c.get('table', {}).get('tableRows', []):
                for cell in row['tableCells']:
                    walk(cell['content'])
    walk(tab['documentTab']['body']['content'])
    return out


def _cut(atoms, a, b):
    """текст диапазона [a, b) дока; AssertionError, если граница режет суррогатную пару или попала мимо текста"""
    edges = {i for i, _, _ in atoms} | {i + w for i, _, w in atoms}
    assert a in edges and b in edges and a < b, f'диапазон ({a}, {b}) режет знак или пуст'
    for i, _, w in atoms:
        assert not (i < a < i + w) and not (i < b < i + w), f'диапазон ({a}, {b}) режет суррогатную пару на {i}'
    return ''.join(ch or '\x00' for i, ch, _ in atoms if a <= i < b)


def selftest():
    import subprocess
    import tempfile
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from fake_docs import FakeDocs  # noqa: E402
    global _sleep
    _sleep = lambda s: None                                 # noqa: E731
    quiet = lambda *a, **k: None                            # noqa: E731
    DOC = 'doc-selftest'

    # ── индексы ──
    assert u16('абв') == 3 and u16('📍') == 2 and u16('👁 🔴') == 5 and u16('⚠️') == 2
    assert index_of(10, '📍 ГДЕ', 1) == 12 and index_of(10, '📍 ГДЕ', 0) == 10 and index_of(10, 'аб', 2) == 12
    try:
        index_of(0, 'аб', 3)
        raise AssertionError('index_of пропустил позицию вне текста')
    except ValueError:
        pass

    # ── строки всех трёх видов; эмодзи вне BMP; метка «❌ СЕЙЧАС ·» дважды в одной ячейке ──
    hdr, widths = ['№', '⏱ TC', 'Что сделать', 'Кадр'], [48, 56, 310, 262]
    want = []                                               # (строка таблицы, колонка, start, end, key, подстрока)

    def cell(ri, cj, parts):
        c = CellText()
        for p in parts:
            if p == '\n':
                c.nl()
            elif isinstance(p, tuple):
                c.add(*p)
            else:
                c.add(p)
        for s, e, k in c.spans:
            want.append((ri, cj, s, e, k, c.text[s:e]))
        return c

    rows = []
    rows.append({'kind': 'sec', 'cells': ['', '', '[ЧАСТЬ 2 · 🔴 БЛОКИРУЕТ ВЫПУСК · 1]', ''], 'fill': (217, 237, 217)})
    want.append((1, 2, 0, len(rows[0]['cells'][2]), 'sec', rows[0]['cells'][2]))
    n1 = cell(2, 0, [('ТЗ-40', 'label'), '\n', '🔴', '\n', ('из v4', 'muted')])
    t1 = cell(2, 2, [('【Фонд входит слишком рано 👁】', 'title'), '\n',
                     ('❌ СЕЙЧАС ·', 'label'), ' 📍 куратор объясняет работу фонда', '\n',
                     ('❌ СЕЙЧАС ·', 'label'), ' второй раз та же метка 🔴', '\n',
                     ('✅ СДЕЛАТЬ ·', 'label'), ' было «', ('ЖУМАГУЛ', 'was'), '» → стало «', ('ЖИМАГУЛ', 'now'), '»', '\n',
                     ('📍 ГДЕ ·', 'label'), ' 11:16–11:40'])
    k1 = cell(2, 3, ['\n', ('11:16 · кадр ката v5 👁', 'cap'), '\n', ('файл смотри в папке материалов', 'muted')])
    rows.append({'kind': 'item', 'cells': [n1.text, '11:16', t1.text, k1.text],
                 'spans': {0: n1.spans, 2: t1.spans, 3: k1.spans}, 'fill': None, 'imgs': [(0, 'fb_2_040.jpg')]})
    rows.append({'kind': 'sec', 'cells': ['👁', '', '[👁 ПРОВЕРИТЬ ГЛАЗОМ · 2]\nвторая строка секции', ''],
                 'fill': (0.99, 0.95, 0.80), 'head_col': 2, 'spans': {2: [(0, 24, 'sec')]}})
    want.append((3, 2, 0, 24, 'sec', '[👁 ПРОВЕРИТЬ ГЛАЗОМ · 2]'))
    want.append((3, 0, 0, 1, 'sec', '👁'))
    l1 = cell(4, 2, [('Тайна усыновления 📍', 'title'), '\n', '         1:05  ▸ 🔴 согласовать с фондом · ', ('ТЗ-07', 'label'),
                     '\n', '        12:30  ▸ 👁 проверить глазом · ', ('ТЗ-07', 'label')])
    k2 = cell(4, 3, [('подпись раз', 'cap'), '\n', '\n', 'подпись два', '\n'])
    rows.append({'kind': 'list', 'cells': ['', '', l1.text, k2.text], 'spans': {2: l1.spans, 3: k2.spans},
                 'imgs': [(1, 'a.jpg'), (-1, 'b.jpg')], 'caps': ['подпись два']})
    want.append((4, 3, len('подпись раз\n\n'), len('подпись раз\n\nподпись два'), 'cap', 'подпись два'))
    for cj, h in enumerate(hdr):
        want.append((0, cj, 0, len(h), 'hdr', h))
    head = [('h1', 'Обратная связь по кату v5 · YTCH12 📍'), ('meta', 'v5 против v4 · собрано 21.09.2026 22:40 · сборка 1'),
            ('tally', 'новых 8 · закрыто 120 · осталось 30'), ('list_head', 'Как читать'), ('list_item', '🔴 — блокирует выпуск'),
            ('how', ''), ('warn', 'Правки вносить во вкладке «ТЗ монтажёру · v5» — эта вкладка пересобирается кодом 👁')]

    # ── запись в двойника ──
    fd = FakeDocs()
    snap = {}

    def put_images(tab_id, img_reqs):
        snap['doc'] = fd.get_doc(DOC)                       # состояние ДО картинок: по нему сверяем диапазоны стилей
        snap['n_batches'] = len(fd.batches)
        assert [q['index'] for q in img_reqs] == sorted((q['index'] for q in img_reqs), reverse=True)
        assert all(q['width_pt'] == 250 for q in img_reqs)
        fd.batch_update(DOC, [{'insertInlineImage': {'location': {'tabId': tab_id, 'index': q['index']},
                                                     'uri': 'fake://' + q['name'],
                                                     'objectSize': {'width': _pt(q['width_pt'])}}} for q in img_reqs])
        return len(img_reqs)

    title = 'Обратная связь · v5'
    tab_id = write_tab(DOC, title, head, hdr, rows, widths, insert_images=put_images,
                       get_doc=fd.get_doc, batch=fd.batch_update, log=quiet)
    assert LAST['tab_id'] == tab_id and LAST['images'] == 3 and [q['name'] for q in LAST['img_reqs']][-1] == 'fb_2_040.jpg'
    doc0 = snap['doc']
    tab0 = next(t for t in iter_tabs(doc0) if t['tabProperties']['tabId'] == tab_id)
    atoms = _atoms(tab0)
    body = tab0['documentTab']['body']['content']
    tables = [c for c in body if 'table' in c]
    assert len(tables) == 1, 'таблица обязана быть одна'
    grid = [r['tableCells'] for r in tables[0]['table']['tableRows']]

    # 1) текст каждой ячейки посимвольно
    all_cells = [hdr] + [r['cells'] for r in rows]
    n_cells = 0
    for ri, row in enumerate(grid):
        for cj, c in enumerate(row):
            assert cell_text(c) == all_cells[ri][cj] + '\n', (ri, cj, cell_text(c), all_cells[ri][cj])
            n_cells += 1
    paras = [''.join(e.get('textRun', {}).get('content', '') for e in c['paragraph']['elements'])
             for c in body if 'paragraph' in c]
    assert paras[:len(head)] == [t + '\n' for _, t in head], paras

    # 2) каждый стилевой запрос дампа: диапазон → подстрока, ячейка, суррогаты
    flat = [q for b in fd.batches[:snap['n_batches']] for q in b]
    ops = [next(iter(q)) for q in flat]
    styles = [(i, q['updateTextStyle']) for i, q in enumerate(flat) if 'updateTextStyle' in q]
    table_a, table_b = grid[0][0]['content'][0]['startIndex'], grid[-1][-1]['endIndex']
    resets = [(i, s) for i, s in styles if s['fields'] == RESET_FIELDS]
    assert len(resets) == 1, 'сброс оформления таблицы обязан быть ровно один'
    ri_reset, reset = resets[0]
    assert (reset['range']['startIndex'], reset['range']['endIndex']) == (table_a, table_b)
    assert reset['textStyle'] == {'bold': False, 'italic': False, 'strikethrough': False, 'underline': False,
                                  'fontSize': _pt(9)} and 'foregroundColor' in reset['fields']
    _cut(atoms, table_a, table_b)

    def locate(a, b):
        for ri, row in enumerate(grid):
            for cj, c in enumerate(row):
                ca, cb = c['content'][0]['startIndex'], c['endIndex']
                if ca <= a < cb:
                    assert b <= cb - 1, f'диапазон ({a}, {b}) выходит за ячейку {ri}:{cj}'
                    return ri, cj, len(_cut(atoms, ca, a)) if a > ca else 0
        return None

    head_end = sum(u16(t) + 1 for _, t in head) + 1
    seen, n_head_styles = [], 0
    for i, s in styles:
        if i == ri_reset:
            continue
        a, b = s['range']['startIndex'], s['range']['endIndex']
        text = _cut(atoms, a, b)
        if b <= head_end:                                   # шапка над таблицей
            kind = next(k for k, t in head if t == text)
            assert s['textStyle'].get('bold') == (kind in ('warn', 'list_head')), (kind, s)
            assert i < ri_reset
            n_head_styles += 1
            continue
        assert i > ri_reset, 'спан раньше сброса оформления — сброс бы его стёр'
        loc = locate(a, b)
        assert loc, f'стилевой диапазон ({a}, {b}) вне таблицы'
        ri, cj, off = loc
        seen.append((ri, cj, off, off + len(text), text, json.dumps(s['textStyle'], sort_keys=True), s['fields']))
    exp = []
    for ri, cj, s, e, key, sub in want:
        ts, fields = ({'bold': True}, 'bold') if key == 'hdr' else span_style(key, 9)
        assert all_cells[ri][cj][s:e] == sub
        exp.append((ri, cj, s, e, sub, json.dumps(ts, sort_keys=True), fields))
    assert sorted(seen) == sorted(exp), (sorted(set(seen) - set(exp)), sorted(set(exp) - set(seen)))
    twice = [x for x in seen if x[4] == '❌ СЕЙЧАС ·']
    assert len(twice) == 2 and twice[0][2] != twice[1][2], 'повтор метки обязан дать два РАЗНЫХ диапазона'
    was = next(x for x in seen if x[4] == 'ЖУМАГУЛ')
    assert '"strikethrough": false' in was[5] and '"red": 0.8' in was[5]
    assert n_head_styles == sum(1 for k, t in head if t and k != 'h1')

    # 3) секции: HEADING_3 на первую строку нужной ячейки, после сброса; заливки на всю строку; ширины
    h3 = [(i, q['updateParagraphStyle']) for i, q in enumerate(flat) if 'updateParagraphStyle' in q
          and q['updateParagraphStyle']['paragraphStyle']['namedStyleType'] == 'HEADING_3']
    got_h3 = [_cut(atoms, p['range']['startIndex'], p['range']['endIndex']) for _, p in h3]
    assert got_h3 == ['[ЧАСТЬ 2 · 🔴 БЛОКИРУЕТ ВЫПУСК · 1]\n', '[👁 ПРОВЕРИТЬ ГЛАЗОМ · 2]\n'], got_h3
    first_span = min(i for i, s in styles if i > ri_reset)
    assert all(ri_reset < i < first_span for i, _ in h3), 'порядок: сброс → HEADING_3 → спаны'
    fills = [q['updateTableCellStyle'] for q in flat if 'updateTableCellStyle' in q]
    assert [f['tableRange']['tableCellLocation']['rowIndex'] for f in fills] == [1, 3]
    assert all(f['tableRange']['columnSpan'] == 4 and f['tableRange']['tableCellLocation']['tableStartLocation']['index']
               == tables[0]['startIndex'] for f in fills)
    assert fills[0]['tableCellStyle']['backgroundColor']['color']['rgbColor'] == _rgb((217, 237, 217))
    ws = [q['updateTableColumnProperties']['tableColumnProperties']['width']['magnitude']
          for q in flat if 'updateTableColumnProperties' in q]
    assert ws == widths and sum(ws) == TOTAL_W
    assert ops.index('insertTable') < ops.index('updateTableColumnProperties') and ops.count('insertTable') == 1

    # 3а) шапка: одна пачка, у каждого абзаца свой именованный стиль ровно на его текст; h1 → HEADING_1; meta серый
    head_batches = [b for b in fd.batches[:snap['n_batches']]
                    if any('insertText' in q and q['insertText']['location']['index'] < head_end for q in b)
                    and not any('insertTable' in q for q in b)]
    head_batches = [b for b in head_batches if any('updateParagraphStyle' in q for q in b)]
    assert len(head_batches) == 1, 'шапка обязана уйти одной пачкой'
    pstyles = [q['updateParagraphStyle'] for q in head_batches[0] if 'updateParagraphStyle' in q]
    assert [(_cut(atoms, q['range']['startIndex'], q['range']['endIndex']), q['paragraphStyle']['namedStyleType'])
            for q in pstyles] == [(t + '\n', 'HEADING_1' if k == 'h1' else 'NORMAL_TEXT') for k, t in head]
    meta = next(s for _, s in styles if _cut(atoms, s['range']['startIndex'], s['range']['endIndex']) == head[1][1])
    assert meta['textStyle'].get('foregroundColor') == {'color': {'rgbColor': GREY}} and 'foregroundColor' in meta['fields']
    plain = next(s for _, s in styles if _cut(atoms, s['range']['startIndex'], s['range']['endIndex']) == head[2][1])
    assert 'foregroundColor' not in plain['textStyle'] and 'foregroundColor' in plain['fields'], 'цвет не сброшен'

    # 3б) текст ячеек вставлялся с конца: индексы вставок строго убывают (иначе ранние вставки сдвигают поздние)
    cell_ins = [q['insertText']['location']['index'] for q in flat[ops.index('insertTable'):] if 'insertText' in q]
    assert len(cell_ins) == sum(1 for r in all_cells for c in r if c) and cell_ins == sorted(cell_ins, reverse=True)
    assert len(set(cell_ins)) == len(cell_ins)

    # 4) картинки: каждая в СВОЁМ абзаце колонки «Кадр», текст ячеек не поехал
    tab1 = next(t for t in iter_tabs(fd.get_doc(DOC)) if t['tabProperties']['tabId'] == tab_id)
    grid1 = [r['tableCells'] for r in [c for c in tab1['documentTab']['body']['content'] if 'table' in c][0]['table']['tableRows']]
    n_img = 0
    for ri, row in enumerate(grid1):
        for cj, c in enumerate(row):
            assert cell_text(c) == all_cells[ri][cj] + '\n'
            for p in c['content']:
                els = p['paragraph']['elements']
                if any('inlineObjectElement' in e for e in els):
                    assert cj == 3 and len(els) == 2 and els[1]['textRun']['content'] == '\n', (ri, cj, els)
                    n_img += 1
    assert n_img == 3

    # без колбэка — картинок нет, якоря на месте
    fd2 = FakeDocs()
    write_tab(DOC, title, head, hdr, rows, widths, get_doc=fd2.get_doc, batch=fd2.batch_update, log=quiet)
    assert not any('insertInlineImage' in q for b in fd2.batches for q in b) and len(LAST['img_reqs']) == 3

    # ── v2: картинки в ДВУХ колонках одной строки, ширина по колонке, спаны warn и link ──
    hdr6, w6 = ['№', '⏱ TC', 'Говорит', 'Вердикт и почему', 'Экран с ошибкой', 'Как надо'], [40, 44, 104, 168, 160, 160]
    v = CellText()
    v.add('⚠️ ЖДЁТ ФОНДА', 'warn').nl().add('【Тема】', 'title').nl().add('Почему:', 'label').add(' так вышло 👁')
    e5 = CellText()
    e5.nl().add('11:16 · титр с ошибкой', 'cap')
    f6 = CellText()
    f6.add('✅ СДЕЛАТЬ ·', 'label').add(' поправить').nl().nl().add('11:16 · как надо 📍', 'cap').nl()
    f6.add('Источник: ', 'muted').add('burodd.ru/team', 'link', 'https://burodd.ru/team')
    rows6 = [{'kind': 'sec', 'cells': ['', '', '', '[❌ ОСТАЛОСЬ · 1]', '', ''], 'head_col': 3, 'fill': (1.0, 0.92, 0.82)},
             {'kind': 'item', 'cells': ['ТЗ-40 · v4', '11:16', 'речь 📍 героини', v.text, e5.text, f6.text],
              'spans': {3: v.spans, 4: e5.spans, 5: f6.spans, 2: [(0, 4, 'title')]},
              'imgs': [(4, 0, 'p2_040_err.jpg'), (5, 1, 'p2_040_fix.jpg')]}]
    fd7 = FakeDocs()
    got7 = {}

    def put7(tab_id, img_reqs):
        got7['reqs'] = img_reqs
        fd7.batch_update(DOC, [{'insertInlineImage': {'location': {'tabId': tab_id, 'index': q['index']},
                                                      'uri': 'fake://' + q['name'],
                                                      'objectSize': {'width': _pt(q['width_pt'])}}} for q in img_reqs])
        return len(img_reqs)

    write_tab(DOC, 'шесть колонок', [], hdr6, rows6, w6, col_img=4, img_w={4: 150, 5: 150}, insert_images=put7,
              get_doc=fd7.get_doc, batch=fd7.batch_update, log=quiet)
    reqs7 = got7['reqs']
    assert [(q['col'], q['name'], q['width_pt']) for q in reqs7] == [(5, 'p2_040_fix.jpg', 150), (4, 'p2_040_err.jpg', 150)], reqs7
    assert reqs7[0]['index'] > reqs7[1]['index']
    tab7 = next(iter_tabs(fd7.get_doc(DOC)))
    grid7 = [r['tableCells'] for r in [c for c in tab7['documentTab']['body']['content'] if 'table' in c][0]['table']['tableRows']]
    where_img = [(cj, pi) for cj, c in enumerate(grid7[2]) for pi, p in enumerate(c['content'])
                 if any('inlineObjectElement' in e for e in p['paragraph']['elements'])]
    assert where_img == [(4, 0), (5, 1)], where_img                     # каждая — в своём пустом абзаце своей колонки
    assert all(cell_text(c) == rows6[1]['cells'][cj] + '\n' for cj, c in enumerate(grid7[2]))
    flat7 = [q for b in fd7.batches for q in b if 'updateTextStyle' in q]
    warn7 = [q['updateTextStyle'] for q in flat7 if q['updateTextStyle']['textStyle'].get('foregroundColor', {})
             .get('color', {}).get('rgbColor') == ORANGE]
    link7 = [q['updateTextStyle'] for q in flat7 if 'link' in q['updateTextStyle']['textStyle']]
    assert len(warn7) == 1 and warn7[0]['textStyle']['bold'] is True and 'foregroundColor' in warn7[0]['fields']
    assert len(link7) == 1 and link7[0]['textStyle']['link'] == {'url': 'https://burodd.ru/team'} and 'link' in link7[0]['fields']
    # tab7 снят ПОСЛЕ картинок, а диапазоны стилей считались до них → сверяем на прогоне без картинок
    pre7 = FakeDocs()
    write_tab(DOC, 'шесть колонок', [], hdr6, rows6, w6, col_img=4, img_w=150, get_doc=pre7.get_doc, batch=pre7.batch_update, log=quiet)
    atoms7 = _atoms(next(iter_tabs(pre7.get_doc(DOC))))
    assert _cut(atoms7, warn7[0]['range']['startIndex'], warn7[0]['range']['endIndex']) == '⚠️ ЖДЁТ ФОНДА'
    assert _cut(atoms7, link7[0]['range']['startIndex'], link7[0]['range']['endIndex']) == 'burodd.ru/team'
    assert all(q['width_pt'] == 150 for q in LAST['img_reqs']) and len(LAST['img_reqs']) == 2
    for bad6 in ([(4, 0, 'a.jpg'), (4, 0, 'b.jpg')], [(6, 0, 'a.jpg')], [(5, 0, 'a.jpg')], [(1, 'x')], [('a.jpg',)]):
        r6, fdx = dict(rows6[1], imgs=bad6), FakeDocs()
        try:
            write_tab(DOC, 'битые картинки', [], hdr6, [r6], w6, col_img=4, get_doc=fdx.get_doc, batch=fdx.batch_update, log=quiet)
            raise AssertionError(f'битые картинки приняты: {bad6}')
        except ValueError:
            assert not fdx.batches, 'отказ обязан быть до любого запроса'
    for bad_sp in ([(0, 4, 'link')], [(0, 4, 'link', 'burodd.ru')], [(0, 4, 'link', None)], [(0, 4)]):
        r6, fdx = dict(rows6[1], spans={2: bad_sp}, imgs=[]), FakeDocs()
        try:
            write_tab(DOC, 'битые спаны', [], hdr6, [r6], w6, col_img=4, get_doc=fdx.get_doc, batch=fdx.batch_update, log=quiet)
            raise AssertionError(f'битый спан принят: {bad_sp}')
        except ValueError:
            pass
    assert span_style('warn')[0]['foregroundColor']['color']['rgbColor'] == ORANGE and 'warn' in STYLE_KEYS and 'link' in STYLE_KEYS

    # ── перезапись вкладки, где уже лежит НАША таблица с картинками (force): результат как с чистого листа ──
    # FakeDocs не умеет удалять диапазон через таблицу; двойник ниже умеет ровно одно — снести тело целиком,
    # и только если диапазон — точно «от первого знака до последнего перевода строки»
    import fake_docs as _fk

    class WipeDocs(FakeDocs):
        wiped = 0

        def batch_update(self, doc_id, requests):
            if len(requests) == 1 and 'deleteContentRange' in requests[0]:
                r = requests[0]['deleteContentRange']['range']
                tab = self._tab(r['tabId'])
                if len(tab['body']) > 1:
                    _, content = self._layout(tab)
                    assert (r['startIndex'], r['endIndex']) == (1, content[-1]['endIndex'] - 1), r
                    self.batches.append(requests)
                    tab['body'] = [_fk._Box()]
                    self.wiped += 1
                    return {'replies': [{}]}
            return super().batch_update(doc_id, requests)

    fdw = WipeDocs()

    def put_w(tab_id, img_reqs):
        fdw.batch_update(DOC, [{'insertInlineImage': {'location': {'tabId': tab_id, 'index': q['index']},
                                                      'uri': 'fake://' + q['name']}} for q in img_reqs])
    write_tab(DOC, title, head, hdr, rows, widths, insert_images=put_w, get_doc=fdw.get_doc, batch=fdw.batch_update, log=quiet)
    first_text = fdw.tab_text()
    try:
        write_tab(DOC, title, head, hdr, rows, widths, get_doc=fdw.get_doc, batch=fdw.batch_update, log=quiet)
        raise AssertionError('вкладка с таблицей перезаписана без force')
    except SystemExit as e:
        assert 'не пустая' in str(e)
    n_before = len(fdw.batches)
    write_tab(DOC, title, head, hdr, rows, widths, force=True, insert_images=put_w,
              get_doc=fdw.get_doc, batch=fdw.batch_update, log=quiet)
    assert fdw.wiped == 1 and fdw.tab_text() == first_text and first_text.count('[IMG]') == 3
    assert len(fdw.tabs) == 1 and sum('insertTable' in q for b in fdw.batches[n_before:] for q in b) == 1

    # ── сброс одним диапазоном не принят (400) → сброс по ячейкам, всё равно раньше HEADING_3 и спанов ──
    fd5 = FakeDocs()

    def picky(doc_id, reqs):
        if any(q.get('updateTextStyle', {}).get('fields') == RESET_FIELDS
               and q['updateTextStyle']['range']['startIndex'] == table_a
               and q['updateTextStyle']['range']['endIndex'] == table_b for q in reqs):
            raise RuntimeError('Docs API 400: range spans table cells')
        return fd5.batch_update(doc_id, reqs)
    write_tab(DOC, title, head, hdr, rows, widths, get_doc=fd5.get_doc, batch=picky, log=quiet)
    flat5 = [q for b in fd5.batches for q in b]
    rs5 = [i for i, q in enumerate(flat5) if q.get('updateTextStyle', {}).get('fields') == RESET_FIELDS]
    tab5 = next(iter_tabs(fd5.get_doc(DOC)))
    atoms5 = _atoms(tab5)
    grid5 = [r['tableCells'] for r in [c for c in tab5['documentTab']['body']['content'] if 'table' in c][0]['table']['tableRows']]
    assert len(rs5) == n_cells and rs5 == list(range(rs5[0], rs5[0] + n_cells)), 'сброс по ячейкам — одной сплошной пачкой'
    assert [_cut(atoms5, flat5[i]['updateTextStyle']['range']['startIndex'], flat5[i]['updateTextStyle']['range']['endIndex'])
            for i in rs5] == [cell_text(c) for row in grid5 for c in row]
    assert rs5[-1] < min(i for i, q in enumerate(flat5) if q.get('updateParagraphStyle', {}).get('paragraphStyle', {})
                         .get('namedStyleType') == 'HEADING_3')
    assert sum(1 for i, q in enumerate(flat5) if 'updateTextStyle' in q and i > rs5[-1]) == len(seen)

    # ── пустая шапка и таблица из одной строки заголовков ──
    fd6 = FakeDocs()
    write_tab(DOC, 'пустая', [], hdr, [], widths, get_doc=fd6.get_doc, batch=fd6.batch_update, log=quiet)
    assert fd6.tab_text().splitlines()[-2] == ' | '.join(hdr), fd6.tab_text()

    # ── сумма ширин, битые входы: отказ ДО любого запроса ──
    fd3 = FakeDocs()
    bad = [
        dict(widths=[48, 56, 310, 261]),
        dict(rows=[{'kind': 'item', 'cells': ['', '', 'текст', 'не пусто'], 'imgs': [(0, 'x.jpg')]}]),
        dict(rows=[{'kind': 'item', 'cells': ['', '', 'текст', ''], 'spans': {2: [(0, 6, 'label')]}}]),
        dict(rows=[{'kind': 'item', 'cells': ['', '', 'текст', ''], 'spans': {2: [(0, 2, 'strike')]}}]),
        dict(rows=[{'kind': 'item', 'cells': ['', '', 'текст']}]),
        dict(rows=[{'kind': 'глава', 'cells': ['', '', 'текст', '']}]),
        dict(head=[('h2', 'нет такого вида')]),
        dict(head=[('meta', 'знак из частной области \ue000 Docs выбросит')]),
        dict(hdr=['№', 'TC\x07', 'Что сделать', 'Кадр']),
        dict(rows=[{'kind': 'item', 'cells': ['', '', 'возврат\rкаретки', '']}]),
        dict(rows=[{'kind': 'item', 'cells': ['', '', 'разрыв\vстроки', '']}]),
        dict(rows=[{'kind': 'item', 'cells': ['', '', 'текст', '\n'], 'imgs': [(0, 'a.jpg'), (-2, 'b.jpg')]}]),
        dict(rows=[{'kind': 'item', 'cells': ['', '', 'текст', 'подпись'], 'caps': ['нет такой']}]),
        dict(col_img=4),
    ]
    for kw in bad:
        args = dict(head=head, hdr=hdr, rows=rows, widths=widths)
        args.update(kw)
        try:
            write_tab(DOC, title, args['head'], args['hdr'], args['rows'], args['widths'], col_img=args.get('col_img', 3),
                      get_doc=fd3.get_doc, batch=fd3.batch_update, log=quiet)
            raise AssertionError(f'битый вход принят: {list(kw)}')
        except ValueError:
            pass
    assert fd3.gets == 0 and not fd3.batches

    # ── заморозка: отказ даже с force=True, в док не ушло ничего ──
    fd4 = FakeDocs()
    fd4.batch_update(DOC, [{'addDocumentTab': {'tabProperties': {'title': 'ТЗ монтажёру · v3'}}}])
    fd4.batch_update(DOC, [{'insertText': {'location': {'tabId': 't.dump1', 'index': 1}, 'text': 'правки Романа руками'}}])
    sent = len(fd4.batches)
    for fr in ({(DOC, 'ТЗ монтажёру · v3')}, [[DOC, 'ТЗ монтажёру · v3']]):
        try:
            write_tab(DOC, 'ТЗ монтажёру · v3', head, hdr, rows, widths, frozen=fr, force=True,
                      get_doc=fd4.get_doc, batch=fd4.batch_update, log=quiet)
            raise AssertionError('замороженная вкладка перезаписана')
        except SystemExit as e:
            assert 'заморожена' in str(e)
    assert len(fd4.batches) == sent and 'правки Романа руками' in fd4.tab_text()
    # та же пара в ДРУГОМ доке не мешает; непустая незамороженная: без force — отказ, с force — запись
    try:
        write_tab(DOC, 'ТЗ монтажёру · v3', head, hdr, rows, widths, frozen={('другой-док', 'ТЗ монтажёру · v3')},
                  get_doc=fd4.get_doc, batch=fd4.batch_update, log=quiet)
        raise AssertionError('непустая вкладка перезаписана без force')
    except SystemExit as e:
        assert 'не пустая' in str(e)
    assert len(fd4.batches) == sent
    write_tab(DOC, 'ТЗ монтажёру · v3', head, hdr, rows, widths, frozen={('другой-док', 'ТЗ монтажёру · v3')},
              force=True, get_doc=fd4.get_doc, batch=fd4.batch_update, log=quiet)
    assert 'правки Романа руками' not in fd4.tab_text() and 'ЖИМАГУЛ' in fd4.tab_text()
    assert len(fd4.tabs) == 1, 'вкладка найдена по имени, вторая не создаётся'

    # ── повторы сети ──
    calls = []

    def flaky(errors):
        def call(doc_id, reqs):
            calls.append(1)
            if errors:
                raise errors.pop(0)
            return {'replies': []}
        return call

    one = [{'insertText': {}}]
    del calls[:]
    batch_update(DOC, one, call=flaky([RuntimeError('Docs API 429: quota'), RuntimeError('Docs API 503: x')]), log=quiet)
    assert len(calls) == 3
    for err in (TimeoutError('timed out'), RuntimeError('Docs API 504: gateway')):
        del calls[:]
        try:
            batch_update(DOC, one, call=flaky([err]), log=quiet)
            raise AssertionError('вставка повторена после обрыва — текст бы задвоился')
        except RuntimeError as e:
            assert 'задвоится' in str(e) and len(calls) == 1
        del calls[:]
        batch_update(DOC, one, idempotent=True, call=flaky([err]), log=quiet)
        assert len(calls) == 2
    del calls[:]
    batch_update(DOC, one, call=flaky([urllib.error.URLError(socket.gaierror(8, 'нет DNS'))]), log=quiet)
    assert len(calls) == 2
    del calls[:]
    try:
        batch_update(DOC, one, call=flaky([RuntimeError('Docs API 400: bad')]), log=quiet)
        raise AssertionError('400 проглочен')
    except RuntimeError:
        assert len(calls) == 1
    del calls[:]
    assert get_doc_retry(DOC, 3, call=lambda d: (calls.append(1), {'tabs': []} if len(calls) > 2 else 1 / 0)[1],
                         log=quiet) == {'tabs': []} and len(calls) == 3

    # ── свой таймаут на КАЖДЫЙ вызов и разбор ошибок HTTP — на подставном urlopen, сети нет ──
    import io
    global _token
    real_open, real_token = urllib.request.urlopen, _token
    seen_to, plan, tok_plan = [], [], []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open(req, data=None, timeout=None):
        seen_to.append(timeout)
        assert req.get_header('Authorization') == 'Bearer tok'
        step = plan.pop(0)
        if isinstance(step, int):
            raise urllib.error.HTTPError(req.full_url, step, 'x', {}, io.BytesIO('подробности'.encode()))
        if isinstance(step, Exception):
            raise step
        if data is not None:
            assert json.loads(data) == {'requests': one}
        return Resp(json.dumps(step).encode())

    def fake_token(timeout):
        seen_to.append(('tok', timeout))
        if tok_plan:
            raise tok_plan.pop(0)
        return 'tok'

    urllib.request.urlopen, _token = fake_open, fake_token
    try:
        plan[:] = [429, {'replies': [1]}]
        assert batch_update(DOC, one, timeout=7, log=quiet) == {'replies': [1]}
        assert [t for t in seen_to if not isinstance(t, tuple)] == [7, 7] and ('tok', 7) in seen_to
        plan[:] = [{'replies': [2]}]                        # токен не получен — в док ничего не ушло, повтор безопасен
        tok_plan[:] = [TimeoutError('timed out'), urllib.error.URLError('нет сети')]
        assert batch_update(DOC, one, timeout=7, log=quiet) == {'replies': [2]}
        plan[:] = [TimeoutError('timed out')]               # а вот обрыв самого запроса вставки — не повторяем
        try:
            batch_update(DOC, one, timeout=7, log=quiet)
            raise AssertionError('вставка повторена после таймаута')
        except RuntimeError as e:
            assert 'задвоится' in str(e) and not plan
        plan[:] = [400]
        try:
            batch_update(DOC, one, timeout=7, log=quiet)
            raise AssertionError('400 проглочен')
        except RuntimeError as e:
            assert 'Docs API 400' in str(e) and 'подробности' in str(e)
        del seen_to[:]
        plan[:] = [TimeoutError('timed out'), {'tabs': []}]
        assert get_doc_retry(DOC, 2, timeout=11, log=quiet) == {'tabs': []} and 11 in seen_to
        assert socket.getdefaulttimeout() is None, 'общий таймаут процесса трогать нельзя'
    finally:
        urllib.request.urlopen, _token = real_open, real_token

    # ── замок ──
    scratch = os.environ.get('YTAI_SCRATCH') or None         # куда класть временную папку; по умолчанию — системная
    if scratch:
        Path(scratch).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        lf = Path(tmp) / 'logs' / 'doc_write.lock'
        with lock(tmp) as p:
            assert p == lf and json.loads(lf.read_text(encoding='utf-8'))['pid'] == os.getpid()
            try:
                with lock(tmp):
                    raise AssertionError('замок пустил вторую запись в том же процессе')
            except SystemExit:
                pass
            assert lf.exists(), 'отказ второй записи не должен снимать чужой замок'
        assert not lf.exists()
        other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        try:
            lf.write_text(json.dumps({'pid': other.pid, 'host': socket.gethostname(), 'what': 'чужая запись'}),
                          encoding='utf-8')
            try:
                with lock(tmp):
                    raise AssertionError('замок пустил запись при живом чужом процессе')
            except SystemExit as e:
                assert str(other.pid) in str(e)
            assert json.loads(lf.read_text(encoding='utf-8'))['pid'] == other.pid
        finally:
            other.kill()
            other.wait()
        with lock(tmp):                                     # процесс умер — замок снимается молча
            assert json.loads(lf.read_text(encoding='utf-8'))['pid'] == os.getpid()
        assert not lf.exists()
        lf.write_text('', encoding='utf-8')                 # файл создан, но не дописан: сосед берёт замок прямо сейчас
        try:
            with lock(tmp):
                raise AssertionError('замок отнят у процесса, который его ещё дописывает')
        except SystemExit:
            pass
        os.utime(lf, (time.time() - 60, time.time() - 60))  # тот же битый файл минутной давности — мусор
        with lock(tmp):
            pass
        assert not lf.exists()

    print(f'ячеек сверено {n_cells}, стилевых диапазонов {len(seen)} (+{n_head_styles} в шапке), секций {len(h3)}, '
          f'картинок {n_img}, запросов {len(flat)}')
    print('SELFTEST OK')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        print(__doc__)
