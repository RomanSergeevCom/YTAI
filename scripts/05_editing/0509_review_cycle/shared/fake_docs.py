# -*- coding: utf-8 -*-
"""fake_docs — офлайн-двойник Google Docs API для дампа запросов (--dump-requests).

Зачем: сборщики вкладок (doc_tab_tz_v3/v4, doc_tab_review_v1) считают индексы по ответам get_doc,
поэтому «просто напечатать запросы» без API нельзя. Этот модуль моделирует вкладку (абзацы, таблицы,
ячейки, картинки как 1 индекс, UTF-16-индексы) достаточно точно, чтобы сборщик прошёл весь путь,
а все его batchUpdate-запросы легли в файл. Индексы самосогласованы, но не обязаны совпадать
с настоящим Google Docs байт в байт — это регрессионный дамп (golden), а не эмулятор.

    fd = FakeDocs()
    module.get_doc = fd.get_doc; module._batch_update = fd.batch_update
    ... main() ...
    fd.dump(path)
"""
import copy
import json
from pathlib import Path


def _w(ch):
    return 2 if ord(ch) > 0xFFFF else 1


def _atoms(text):
    return list(text)


class _Box:
    """контейнер текста: атомы = символ (str) или картинка (dict)"""

    def __init__(self, atoms=None):
        self.atoms = atoms if atoms is not None else ['\n']

    def width(self):
        return sum(_w(a) if isinstance(a, str) else 1 for a in self.atoms)

    def pos_of(self, start, idx):
        cur = start
        for i, a in enumerate(self.atoms):
            if cur == idx:
                return i
            cur += _w(a) if isinstance(a, str) else 1
            if cur > idx:
                raise ValueError(f'индекс {idx} внутри суррогатной пары')
        if cur == idx:
            return len(self.atoms)
        raise ValueError(f'индекс {idx} вне контейнера')

    def paragraphs(self, start):
        """→ абзацы Docs API с textRun/inlineObjectElement"""
        out, cur, para, pstart = [], start, [], start
        els, run, rstart = [], '', start

        def flush_run():
            nonlocal run, rstart
            if run:
                els.append({'startIndex': rstart, 'endIndex': rstart + sum(_w(c) for c in run),
                            'textRun': {'content': run, 'textStyle': {}}})
            run = ''

        for a in self.atoms:
            if isinstance(a, str):
                if not run:
                    rstart = cur
                run += a
                cur += _w(a)
                if a == '\n':
                    flush_run()
                    out.append({'startIndex': pstart, 'endIndex': cur, 'paragraph': {'elements': els}})
                    els, pstart = [], cur
            else:
                flush_run()
                els.append({'startIndex': cur, 'endIndex': cur + 1,
                            'inlineObjectElement': {'inlineObjectId': a['id']}})
                cur += 1
        flush_run()
        if els:
            out.append({'startIndex': pstart, 'endIndex': cur, 'paragraph': {'elements': els}})
        return out


class _Table:
    def __init__(self, rows, cols):
        self.cells = [[_Box() for _ in range(cols)] for _ in range(rows)]


class FakeDocs:
    def __init__(self):
        self.tabs = []            # [{'id', 'title', 'body': [_Box | _Table]}]
        self.batches = []         # [[request, …], …] — ровно то, что ушло бы в batchUpdate
        self.gets = 0
        self._img = 0

    # ── layout ────────────────────────────────────────────────────────────
    def _layout(self, tab):
        """→ (containers [(box, start)], content JSON)"""
        idx = 1
        conts, content = [], [{'startIndex': 0, 'endIndex': 1, 'sectionBreak': {}}]
        for seg in tab['body']:
            if isinstance(seg, _Box):
                conts.append((seg, idx))
                content += seg.paragraphs(idx)
                idx += seg.width()
                continue
            tstart = idx
            idx += 1
            rows = []
            for row in seg.cells:
                rstart = idx
                idx += 1
                cells = []
                for box in row:
                    cstart = idx
                    idx += 1
                    conts.append((box, idx))
                    paras = box.paragraphs(idx)
                    idx += box.width()
                    cells.append({'startIndex': cstart, 'endIndex': idx, 'content': paras})
                rows.append({'startIndex': rstart, 'endIndex': idx, 'tableCells': cells})
            idx += 1
            content.append({'startIndex': tstart, 'endIndex': idx,
                            'table': {'rows': len(seg.cells), 'columns': len(seg.cells[0]) if seg.cells else 0,
                                      'tableRows': rows}})
        return conts, content

    def _find(self, tab, idx):
        conts, _ = self._layout(tab)
        for box, start in conts:
            if start <= idx < start + box.width():
                return box, box.pos_of(start, idx)
        raise ValueError(f'индекс {idx} не попадает в текст вкладки «{tab["title"]}»')

    def _tab(self, tab_id):
        for t in self.tabs:
            if t['id'] == tab_id:
                return t
        raise ValueError(f'нет вкладки {tab_id}')

    # ── API ───────────────────────────────────────────────────────────────
    def get_doc(self, doc_id):
        self.gets += 1
        tabs = []
        for t in self.tabs:
            _, content = self._layout(t)
            tabs.append({'tabProperties': {'tabId': t['id'], 'title': t['title']},
                         'documentTab': {'body': {'content': content}}})
        return {'documentId': doc_id, 'tabs': tabs}

    def batch_update(self, doc_id, requests):
        self.batches.append(copy.deepcopy(requests))
        replies = []
        for q in requests:
            (op, body), = q.items()
            rep = {}
            if op == 'addDocumentTab':
                tid = f't.dump{len(self.tabs) + 1}'
                self.tabs.append({'id': tid, 'title': body['tabProperties']['title'], 'body': [_Box()]})
                rep = {'addDocumentTab': {'tabProperties': {'tabId': tid, 'title': body['tabProperties']['title']}}}
            elif op == 'insertText':
                loc = body['location']
                box, pos = self._find(self._tab(loc['tabId']), loc['index'])
                box.atoms[pos:pos] = _atoms(body['text'])
            elif op == 'insertInlineImage':
                loc = body['location']
                box, pos = self._find(self._tab(loc['tabId']), loc['index'])
                self._img += 1
                box.atoms[pos:pos] = [{'id': f'img.{self._img}', 'uri': body.get('uri', '')}]
            elif op == 'insertTable':
                loc = body['location']
                tab = self._tab(loc['tabId'])
                box, pos = self._find(tab, loc['index'])
                k = tab['body'].index(box)
                before, after = box.atoms[:pos] + ['\n'], box.atoms[pos:]
                tab['body'][k:k + 1] = [_Box(before), _Table(body['rows'], body['columns']), _Box(after)]
            elif op == 'deleteContentRange':
                rng = body['range']
                tab = self._tab(rng['tabId'])
                a, b = rng['startIndex'], rng['endIndex']
                box, pa = self._find(tab, a)
                box2, pb = self._find(tab, b)
                if box is not box2:
                    raise ValueError('deleteContentRange через границу контейнера не моделируется')
                del box.atoms[pa:pb]
            replies.append(rep)
        return {'replies': replies}

    # ── дамп ──────────────────────────────────────────────────────────────
    def tab_text(self, tab_id=None):
        out = []
        for t in self.tabs:
            if tab_id and t['id'] != tab_id:
                continue
            out.append(f'### {t["title"]}')
            for seg in t['body']:
                if isinstance(seg, _Box):
                    out.append(''.join(a if isinstance(a, str) else '[IMG]' for a in seg.atoms))
                else:
                    for row in seg.cells:
                        out.append(' | '.join(''.join(a if isinstance(a, str) else '[IMG]' for a in c.atoms)
                                              .rstrip('\n').replace('\n', '⏎') for c in row))
        return '\n'.join(out)

    def dump(self, path, extra=None):
        data = {'schema': 'fake-docs-dump-v1', 'batches': self.batches, 'final_text': self.tab_text()}
        if extra:
            data.update(extra)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        n = sum(len(b) for b in self.batches)
        print(f'--dump-requests: {len(self.batches)} batchUpdate, запросов {n} → {path} (Google API не вызывался)', flush=True)
