#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка «Главы · {ver}» — все главы и подглавы фильма В ОДНОМ МЕСТЕ + варианты дизайна заставки.

Зачем: Роман 22.09.2026 — «мне не нравится дизайн глав… Выдели все главы в одном месте в документе
и предложи (создай дизайн), главы + подглавы и на весь экран (может быть контраста не хватает)».
Раньше главы были размазаны: строки-заливки во вкладке ТЗ, HEADING в навигаторе, плашки на таймлайне
и картинка info_structure_map — но единого списка «вот все главы, вот как они выглядят» не было.

Структура (канон 5.6 — ОДНА таблица):
  шапка: что это + три варианта заставки крупными картинками, каждый одной строкой «за что»
         + раздел «ПОДГЛАВЫ» — панели перечислений (card.prog), по обзорному кадру на главу
  таблица: № | Кадр из ката | Глава и подглавы | ⏱ | Что сейчас | Как надо
           строка на КАЖДУЮ главу и на КАЖДУЮ подглаву, у каждой свой кадр и свой тайминг
           (Роман 22.09.2026). Кадры подглав кладёт `stages/sub_cards.py` → `card.sub_img`.

Сюда же переехала проблема «заставки глав вразнобой» (ТЗ-48 снято 22.09.2026 по просьбе Романа:
«Надо проблему с главами отдельно вынести в Главы · v2») — текст берётся из карточки:
`ch_notes` (что с заставкой в кате), `ch_state` (что сейчас / как надо), `ch_extra` (похожие на
заставку места, главами не являющиеся). Выбранная буква заставки — `ch_plate_variant`.

Картинки — через ВРЕМЕННЫЙ доступ к закрытой папке кадров (`shared/doc_images.py`, режим
`temp_grant`), как на вкладке «Обратная связь». Публичной папки у такого фильма нет и не будет:
в кадре человек, которого нельзя показывать по ссылке. Кадры глав `ch_card_NN.jpg` и подглав
`sub_card_NN.jpg` кладёт `stages/sub_cards.py`, демо заставок `ch_demo_a|b|c.jpg` и панели
`prog_NN_0.jpg` — `stages/make_infographics_v6.py`.

Страница вкладки — альбомная (`doc_table.landscape_request`): таблица шире портретной полосы,
на ней PDF-экспорт срезал бы последнюю колонку.

Первым блоком идёт структура фильма текстом (`stages/structure_text.py`) — Роман 22.09.2026:
«ты структуру написал, но не описал её текстом в начале документа».

usage: doc_tab_chapters_v1.py [--tab TITLE] [--dry-run] [--images none|temp]
exit: 0 — вкладка записана · 1 — записана, но кадры встали не все или остался открытый доступ
"""
import argparse
import json
import sys
import time
from pathlib import Path

from _bootstrap import P, W6, M, T  # noqa: E402
import doc_images as DI  # noqa: E402
import doc_table as DT  # noqa: E402
import feedback_view as V  # noqa: E402
from doctab_lib import get_doc, iter_tabs  # noqa: E402
from doctab_lib import batch_update as _batch_update  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--tab')
ap.add_argument('--dry-run', action='store_true')
ap.add_argument('--images', choices=('none', 'temp'), default='none',
                help='temp — кадры через временный доступ к закрытой папке; none (по умолчанию) — без картинок')
# Роман 25.09.2026: «нужны только названия глав». Без подглав, без предложений экранов, без
# трёх вариантов заставки и без длинного текста структуры — одна таблица глав и карта сверху
ap.add_argument('--chapters-only', action='store_true',
                help='только главы: без подглав, предложений экранов и демо вариантов заставки')
# ⚠️ Блок H считает высоту колонки без строки «подтем нет» и на 26 главах выбирает две колонки
# вместо трёх — главы 11–15 уходят за нижний край (YTCH12, 25.09.2026). Пока блок не починен,
# обрезанную карту во вкладку не ставим: текстовый список ниже полный
ap.add_argument('--no-map', action='store_true', help='не вставлять картинку карты в шапку')
# Роман 25.09.2026: «сгенерируй их, чтобы пример был, прямо крупно — главы и подглавы».
# Вместо сырого кадра — готовая заставка (`bdd_plates.py titles`), в шапке варианты названия фильма
ap.add_argument('--cards', action='store_true',
                help='в строках готовые заставки глав и подглав крупно + варианты названия фильма')
a = ap.parse_args()
CARDS = a.cards
ONLY_CH = a.chapters_only or CARDS       # без предложений экранов, демо заставки и текста структуры
SKIP_SUBS = a.chapters_only and not CARDS

DOC_ID = P.need('doc_id')
TAB_TITLE = a.tab or T('chp.tab_title', ver=P.CUT_VERSION)
HDR = ['№', T('chp.hdr_card') if CARDS else T('chp.hdr_frame'), T('chp.hdr_body'), '⏱',
       T('chp.hdr_now'), T('chp.hdr_do')]
# ⚠️ Прежние 1222 pt не влезают в альбомный лист (720 pt полезной ширины): Docs ужимает колонки
# неравномерно, и кадр переставал соотноситься со своей строкой. В режиме заставок — ровно 720
WIDTHS = [22, 322, 118, 50, 94, 114] if CARDS else [30, 262, 260, 70, 300, 300]
IMG_W = 314 if CARDS else 250
FONT = 10
DEMOS = [(v, T(f'chp.demo_{v}_t'), T(f'chp.demo_{v}_d')) for v in ('a', 'b', 'c')]
# Пресет «YTCG P01 · 1.1 Side slide», выбранный Романом 22.09.2026: боковая страница, заголовок
# сверху, список НАКАПЛИВАЕТСЯ — пункт за пунктом по ходу речи, будущих не видно. Прежние варианты
# a/b (тёмная коробка, кружки, полоса прогресса, оранжевый акцент) забракованы и сняты.
PROG_DEMOS = [(v, T(f'chp.pd_{v}_t'), T(f'chp.pd_{v}_d')) for v in ('z', 'h')]


def u16(s):
    return len(s.encode('utf-16-le')) // 2


def local_shot(name):
    """→ путь картинки на диске. Панель перечисления лежит 4K-PNG с альфой — в доке от неё остался бы
    тёмный прямоугольник без кадра, поэтому сначала ищем композит s12 («панель поверх настоящего
    кадра», dp_*.jpg), потом плоский jpg, и только потом сам PNG."""
    stem = str(name).rsplit('.', 1)[0]
    if not stem:
        return None
    for cand in (f'dp_{stem}.jpg', f'{stem}.jpg', f'{stem}.png'):
        for d in (P.MOCK, W6 / 'previews_doc'):
            f = Path(d) / cand
            if f.is_file():
                return f
    return None


def tmm(sec):
    return f'{int(sec) // 60}:{int(sec) % 60:02d}'


def batch_update(doc_id, reqs, tries=4):
    for k in range(tries):
        try:
            return _batch_update(doc_id, reqs)
        except Exception as e:                                   # noqa: BLE001
            if k == tries - 1:
                raise
            print('  batch повтор:', ' '.join(str(e).split())[:300], flush=True)
            time.sleep(8 * (k + 1))


# ── данные ────────────────────────────────────────────────────────────────
CHAP = [(int(t), n) for t, n in P.CHAPTERS]
CH_NAME = P.get('ch_name', {})
CH_IMG = P.get('ch_img', {})
SUB = [(int(s), int(c), str(t)) for s, c, t in P.get('sub', [])]
DUR = int(P.duration_sec())
STATE = P.get('ch_state', {})     # {'04': ['что сейчас', 'как надо']} — из карточки
EXTRA = P.get('ch_extra', [])     # места, похожие на заставку, но не привязанные к главе
NOTES = P.get('ch_notes', {})     # {'04': '⚠️ НЕТ НОМЕРА · 11:17 …'} — из карточки
PROG = P.get('prog', {})          # {'08': {'title': …, 'items': [...]}} — перечисления внутри главы
PICKED = str(P.get('ch_plate_variant', '')).strip().lower()   # выбранная Романом буква заставки
NO_NUM = [no for no, t in sorted(NOTES.items()) if T('chp.mark_no_num') in str(t)]
# на каком кадре нарисованы демо A/B/C: секунда из card.ch_demo_secs (как в make_infographics_v6),
# глава — та, в которую эта секунда попадает. Раньше в шапке стояло «глава 05» литералом, и на любом
# другом фильме подпись врала (22.09.2026, YTCR04 v5: демо нарисованы на кадре главы 06).
_DEMO_SEC = next((int(x) for x in (P.get('ch_demo_secs') or [])), 790)
DEMO_CH = next((no for sec, no in reversed(CHAP) if int(sec) <= _DEMO_SEC), (CHAP[0][1] if CHAP else '01'))
# нумерация Романа 22.09.2026: содержательных глав восемь (01..08), хук и финал — без номера.
# В колонке «№» стоит она, в «Что сейчас» — номер, который реально стоит на заставке ката.
FINAL = P.get('ch_no_final', {})


def fin(no):
    return str(FINAL.get(no, no))


# Роман 22.09.2026: «там должны быть ВСЕ экраны глав и ВСЕ экраны подглав, с таймингом».
# Раньше подглавы шли строчками текста внутри ячейки главы — кадра у них не было. Теперь строка
# на каждую главу И на каждую подглаву, у каждой свой кадр из ката (sub_cards.py → sub_img).
SUB_IMG = P.get('sub_img', {})                           # ключ = порядковый номер подглавы в `sub`
NO_SCREEN = set(int(x) for x in P.get('sub_no_screen', []))


def _proposals(work_dir):
    """предложения экранов (`stages/screens_proposal.py`) → колонка «Как надо».

    Нет файла — колонка как была, поэтому другие фильмы и эталон эта правка не двигает
    (тот же приём, что у `feedback_view.load_structure_full`). В карточку предложения не
    пишутся: `sub_no_screen` и `sub_img` — порядковые номера, новая подглава сдвинула бы их все."""
    f = Path(work_dir) / 'screens_proposal.json'
    if ONLY_CH or not f.is_file():
        return []
    try:
        return json.loads(f.read_text(encoding='utf-8')).get('items') or []
    except (OSError, ValueError):
        print('⚠️ screens_proposal.json не читается — колонка «Как надо» останется как была', flush=True)
        return []


PROP_CH, PROP_SUB = {}, {}
for _it in _proposals(W6):
    # ключ подглавы — её ПОРЯДКОВЫЙ номер (`sub_07`), та же нумерация, что у sub_no_screen и sub_img;
    # по секундам склеивать нельзя: у двух подглав одной главы секунды разные, а номер один на всех
    if str(_it.get('role')) == 'plate_for_sub' and _it.get('spot'):
        PROP_SUB.setdefault(str(_it['spot']), []).append(_it)
    else:
        PROP_CH.setdefault(str(_it.get('ch')), []).append(_it)


def prop_lines(items):
    """→ строки для ячейки «Как надо»: что сделать и, если надо, что подтверждает фонд"""
    out = []
    for it in items or []:
        txt = str(it.get('how_it_should_be') or '').strip()
        if txt:
            out.append(f'▶ {txt}')
        if it.get('fund_confirm') and str(it.get('fund_note') or '').strip():
            out.append(f'⚠️ {str(it["fund_note"]).strip()}')
    return out


rows = []
for i, (sec, no) in enumerate(CHAP):
    end = CHAP[i + 1][0] if i + 1 < len(CHAP) else DUR
    pg = PROG.get(no) or {}
    head = (T('chp.chapter_pfx', n=fin(no)) if fin(no) != '—' else '') + str(CH_NAME.get(no, ''))
    body = head
    if pg:                                    # у главы есть панель перечисления — говорим об этом
        body += T('chp.panel_line', title=pg.get('title', ''), n=len(pg.get('items') or []))
    st = list(STATE.get(no) or ['', ''])
    if fin(no) != no:                         # номер на экране придётся перерисовать
        cut_no = T('chp.cut_no', no=no, name=CH_NAME.get(no, ''))
        want_no = (T('chp.want_no', n=fin(no)) if fin(no) != '—' else T('chp.want_no_drop'))
        st[0] = (st[0] + '\n' if st[0] else '') + cut_no
        st[1] = (st[1] + '\n' if len(st) > 1 and st[1] else '') + want_no
    # предложения экранов ДОПИСЫВАЮТСЯ под написанное руками, а не вместо него: раньше
    # непустой ch_state прятал их целиком, и глава с самой важной правкой выглядела пустой
    _pl = prop_lines(PROP_CH.get(no))
    if _pl:
        st = [st[0], ('\n'.join([x for x in [st[1] if len(st) > 1 else ''] if x] + _pl))]
    rows.append({'no': fin(no), 'img': (f'bdd/titles/title_ch_{no}.png' if CARDS else CH_IMG.get(no, '')),
                 'body': body, 'ch': True,
                 'tc': f'{tmm(sec)}–{tmm(end)}', 'now': st[0], 'do': st[1] if len(st) > 1 else ''})

    # ── строки подглав этой главы ──
    if SKIP_SUBS:
        continue
    mine = [(s, t, j) for j, (s, c, t) in enumerate(SUB, 1) if f'{c:02d}' == no]
    for n_, (s, t, j) in enumerate(mine):
        s_end = mine[n_ + 1][0] if n_ + 1 < len(mine) else end
        pan = pg and any(abs(s - int(x)) <= 6 for x in (P.get('prog_t', {}) or {}).get(no, []))
        # ⚠️ NO_SCREEN — порядковые номера подглав в `sub` (1..N), а не секунды: сравнивать надо с j
        now = T('chp.sub_no_title') if j in NO_SCREEN else T('chp.sub_has_title')
        do = T('chp.sub_by_panel') if pan else ''
        _p = prop_lines(PROP_SUB.get(f'sub_{j:02d}'))
        if _p:
            do = (do + '\n' if do else '') + '\n'.join(_p)
        rows.append({'no': '', 'img': (f'bdd/titles/title_sub_{j:02d}.png' if CARDS
                                       else SUB_IMG.get(f'{j:02d}', '')), 'body': f'▸ {t}', 'ch': False,
                     'tc': f'{tmm(s)}–{tmm(s_end)}', 'now': now, 'do': do})
    if not mine and not CARDS:
        rows.append({'no': '', 'img': '', 'body': T('chp.no_subs'), 'ch': False,
                     'tc': '', 'now': '', 'do': ''})

_no_num = T('chp.no_num_note', list=', '.join(NO_NUM)) if NO_NUM else ''
# карта фильма в начале страницы — Роман 22.09.2026: «очень помогает проверять и ориентироваться»
n_sub = sum(1 for _ in SUB) + sum(len(v.get('items') or []) for v in PROG.values())
n_ch = sum(1 for _, no in CHAP if fin(no) != '—')
map_lines = []
for i, (sec, no) in enumerate(CHAP):
    end = CHAP[i + 1][0] if i + 1 < len(CHAP) else DUR
    ttl = (T('chp.chapter_pfx', n=fin(no)) if fin(no) != '—' else '') + str(CH_NAME.get(no, ''))
    map_lines.append((0, f'{ttl}   {tmm(sec)}–{tmm(end)}', {'bold': True}))
    if SKIP_SUBS:
        continue
    pg = PROG.get(no) or {}
    for k, it in enumerate(pg.get('items') or [], 1):
        map_lines.append((0, f'        {k} · {it}', {}))
    for sc, c, t in SUB:
        if f'{c:02d}' == no:
            map_lines.append((0, f'        {tmm(sc)}  ▸ {t}', {}))
    if not pg and not any(f'{c:02d}' == no for _, c, _ in SUB):
        map_lines.append((0, '        ' + T('chp.no_subs'), {}))

# Роман 22.09.2026: «опиши структуру текстом в начале документа». Полный текст собирает
# stages/structure_text.py; нет файла — блока просто нет, вкладка как раньше
STRUCT = []
for _i, _ln in enumerate([] if ONLY_CH else V.load_structure_full(W6)):
    STRUCT.append((2 if _i == 0 else 0, _ln, {'bold': _i == 0}))
if STRUCT:
    STRUCT.append((0, '', {}))

MAP_PNG = 'info_structure_map.png'


def map_fresh():
    """→ (ставить ли картинку карты, почему нет).

    Картинка карты собирается блоком H `make_infographics_v6.py` из карточки. Если она старше
    карточки или текста структуры, во вкладке окажется 4K-лист, который противоречит таблице
    прямо под ним (замер 24.09.2026: карта была на двое суток старше 17 подглав). Молча вставлять
    такую нельзя — лучше без картинки и с внятной строкой, чем со вчерашней структурой."""
    img = local_shot(MAP_PNG)
    if not img:
        return False, f'{MAP_PNG} нет в mockups — собрать: make_infographics_v6.py H'
    srcs = [getattr(P, 'CARD_PATH', None), W6 / 'structure.json']
    newest = max((Path(s).stat().st_mtime for s in srcs if s and Path(s).is_file()), default=0.0)
    if img.stat().st_mtime < newest:
        return False, 'карта старше карточки или структуры — пересобрать: make_infographics_v6.py H'
    return True, ''


MAP_OK, MAP_WHY = map_fresh()
if MAP_WHY:
    print(f'⚠️ карта в шапку не пойдёт: {MAP_WHY}', flush=True)
# картинку вставляем только там, где кадры вообще разрешены: без temp_grant якорный абзац
# остался бы пустой строкой посреди шапки на каждом автоматическом прогоне
MAP_BLOCK = ([(0, '', {'img': MAP_PNG, 'img_w': 620})]
             if (MAP_OK and a.images == 'temp' and not a.no_map) else [])

head = [(1, T('chp.head_title', code=P.CODE, tab=TAB_TITLE), {'bold': True}),
        (0, (T('chp.lead_cards', ver=P.CUT_VERSION, dur=tmm(DUR), n=len(CHAP),
               have=len(CHAP) - len(P.get('new_ch') or []), new=len(P.get('new_ch') or []))
             if CARDS else
             T('chp.lead', ver=P.CUT_VERSION, dur=tmm(DUR)) + _no_num + T('chp.lead2') + T('chp.lead3')), {}),
        (0, '', {}),
        ] + STRUCT + MAP_BLOCK + [
        (2, T('chp.map_h', ch=n_ch, sub=n_sub), {'bold': True}),
        (0, T('chp.map_note', ch=n_ch, last=f'{n_ch:02d}'), {}),
        (0, T('chp.map_link') + 'mockups/info_structure_map.png (4K, в папке проекта)', {}),
        ] + map_lines + [(0, '', {})] + ([] if ONLY_CH else [
        (2, T('chp.var_h_picked', v=PICKED.upper()) if PICKED else T('chp.var_h_ask'), {'bold': True}),
        (0, T('chp.var_lead', ch=DEMO_CH)
            + (T('chp.var_picked', v=PICKED.upper(), n=n_ch) if PICKED
               else T('chp.var_ask', n=n_ch)), {})])


def put_images(tab_id, want, log=print):
    """Вставить все картинки вкладки ОДНОЙ операцией под временным доступом.

    want — [(имя макета, индекс-якорь, ширина pt)]. Файлы берутся с диска (mockups), уменьшаются
    до 1000 px, льются в закрытую папку кадров и открываются только на время своей пачки
    (`doc_images.insert_with_temp_grant`). Публичной папки у этого фильма нет: в кадре ребёнок."""
    ledger = W6 / 'chapters_grants.json'
    # ⚠️ машину и автономность СПРАШИВАЕМ, а не подставляем: контракт temp_grant — это четыре
    # условия разом (строка в карточке И --images temp И Мак И человек рядом). Литералы
    # 'mac', False превращали четыре условия в одно, и кадры ушли бы наружу с Memex
    mode = DI.pick_private_mode(_card_raw('images_mode'), P.SHOTS_REMOTE, a.images,
                                DI.detect_host(P.REVIEW_DIR), DI.detect_autonomous(getattr(P, 'CTL_DIR', None)),
                                log, what='вкладка «Главы»')
    if mode != 'temp_grant':
        # даже без картинок журнал прошлого (убитого) прогона надо закрыть: молча пройти мимо
        # непустого журнала нельзя — это открытые ссылки на кадры
        _closed, stuck = DI.revoke_from_ledger(ledger)
        if _closed:
            log(f'журнал временных доступов: закрыто записей прошлого прогона — {len(_closed)}', flush=True)
        if stuck:
            log(f'⚠️ в журнале временных доступов остались незакрытые записи ({len(stuck)}) — кадры прошлого '
                f'прогона могут быть открыты: python3 shared/doc_images.py --revoke-ledger {ledger}', flush=True)
            return 1
        log('картинки: вкладка собрана без кадров', flush=True)
        return 0
    folder = str(P.get('private_frames_folder_id', '') or '')
    if not folder:
        log('⚠️ в карточке нет private_frames_folder_id — вкладка без кадров', flush=True)
        return 1
    paths, miss = [], []
    for name, _at, _w in want:
        f = local_shot(name)
        (paths.append(f) if f else miss.append(name))
    if miss:
        log(f'  !! нет файлов макетов ({len(miss)}): {", ".join(sorted(set(miss))[:6])}', flush=True)
    DI.preflight(folder)
    files = DI.prepare_files(sorted({str(x) for x in paths}), W6 / 'chapters_doc_frames')
    ids = DI.upload_all(folder, files, M / 'chapters_frames_ids.json') if files else {}
    reqs = []
    for name, at, w in sorted(want, key=lambda x: -x[1]):            # с конца — индексы не едут
        f = local_shot(name)
        if not f or f.stem + '.jpg' not in ids:
            continue
        reqs.append({'name': f.stem + '.jpg',
                     'insertInlineImage': {'location': {'tabId': tab_id, 'index': at},
                                           'objectSize': {'width': {'magnitude': w, 'unit': 'PT'}}}})
    try:
        res = DI.insert_with_temp_grant(DOC_ID, reqs, ids, ledger)
    finally:
        # ревизор идёт и после падения: доступ, открытый и не закрытый, — это утечка кадров,
        # а не «неудачная попытка». Молчать о ней нельзя ни при каком исходе
        left = DI.ledger_pending(ledger)
        if left:
            log(f'⚠️ НЕ ЗАКРЫТО временных доступов: {len(left)} — закрыть немедленно: '
                f'python3 shared/doc_images.py --revoke-ledger {ledger}', flush=True)
    log(f'кадры вкладки: вставлено {res["inserted"]} из {len(want)} · окно доступа '
        f'{res["max_window_sec"]:.0f} с' + (f' · не встали {len(res["failed"])}' if res['failed'] else ''), flush=True)
    for bad in res['failed'][:5]:
        log(f'    ✗ {bad.get("name")}: {bad.get("why")}', flush=True)
    # стадия не имеет права рапортовать успех, если доступ остался открытым или кадры не встали
    return 1 if (res['failed'] or res['revoke_failed'] or DI.ledger_pending(ledger)) else 0


def _card_raw(key):
    """значение ключа из САМОЙ карточки (без подстановки окружения) — как читает его doc_tab_feedback_v1"""
    try:
        import os
        raw = json.loads(Path(os.environ.get('YTAI_CARD') or (Path(P.REVIEW_DIR) / 'review_card.json'))
                         .read_text(encoding='utf-8'))
        return raw.get(key)
    except Exception:                                                # noqa: BLE001
        return P.get(key)


def find_tab(doc):
    for t in iter_tabs(doc):
        if t['tabProperties'].get('title') == TAB_TITLE:
            return t['tabProperties']['tabId']
    return None


def tab_body(tab_id):
    for k in range(4):
        try:
            d = get_doc(DOC_ID)
            break
        except Exception as e:                                   # noqa: BLE001
            if k == 3:
                raise
            print('  get_doc повтор:', str(e)[:100], flush=True)
            time.sleep(10 * (k + 1))
    for t in iter_tabs(d):
        if t['tabProperties']['tabId'] == tab_id:
            return t['documentTab']['body']['content']
    raise SystemExit('вкладка потерялась')


def fresh_table(tab_id, nrows, empty=False, tries=6):
    """та же защита, что во вкладке-навигаторе: чтение большого дока отстаёт от записи,
    и таблица прошлой попытки приходит со старыми индексами (см. doc_tab_review_v1.fresh_table)"""
    for k in range(tries):
        tables = [el for el in tab_body(tab_id) if 'table' in el]
        ok = tables and len(tables[-1]['table']['tableRows']) == nrows
        if ok and empty:
            ok = not any(e.get('textRun', {}).get('content', '').strip()
                         for r in tables[-1]['table']['tableRows'] for c in r['tableCells']
                         for el in c['content'] if 'paragraph' in el
                         for e in el['paragraph'].get('elements', []))
        if ok:
            return tables[-1]
        print(f'  жду {"пустую " if empty else ""}таблицу {nrows} строк', flush=True)
        time.sleep(6 * (k + 1))
    raise SystemExit(f'таблица {nrows} строк не появилась в чтении вкладки')


def main():
    # ⚠️ сухой прогон не трогает док ВООБЩЕ: раньше вкладка успевала создаться до этой проверки,
    # и «посмотреть, что получится» оставляло в документе пустую вкладку
    if a.dry_run:
        for r in rows:
            print(f"  {r['no']} {r['tc']:>14}  {r['body'].splitlines()[0]}")
        for r in rows:
            if r['do']:
                print(f'   Как надо · {r["body"][:38]:<38} {r["do"].splitlines()[0][:90]}')
        print(f'сухой прогон: строк {len(rows)}, картинок {sum(1 for r in rows if r["img"])}, '
              f'абзацев шапки {len(head)}, «Как надо» заполнено у {sum(1 for r in rows if r["do"])} — '
              f'док не тронут')
        return 0
    doc = get_doc(DOC_ID)
    tab_id = find_tab(doc)
    if not tab_id:
        batch_update(DOC_ID, [{'addDocumentTab': {'tabProperties': {'title': TAB_TITLE}}}])
        tab_id = find_tab(get_doc(DOC_ID))
        print('вкладка создана', tab_id, flush=True)
    else:
        print('вкладка найдена', tab_id, flush=True)

    body = tab_body(tab_id)
    first = next(c for c in body if 'paragraph' in c)
    s, e = first['startIndex'], body[-1]['endIndex'] - 1
    if e > s:
        batch_update(DOC_ID, [{'deleteContentRange': {'range': {'tabId': tab_id, 'startIndex': s, 'endIndex': e}}}])
    print('вкладка очищена', flush=True)

    # шапка + три варианта (текст; картинки вставим следом, с конца)
    cur = tab_body(tab_id)[-1]['endIndex'] - 1
    reqs, demo_at, head_img = [], [], []
    for lvl, text, opts in head:
        t = text + '\n'
        # якорь берём ДО вставки абзаца, как это делает block(): картинка встаёт в начало
        # СВОЕГО абзаца. Взять cur позже — значит положить карту под всю таблицу
        if opts.get('img'):
            head_img.append((opts['img'], cur, int(opts.get('img_w', 620))))
        reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': t}})
        if lvl:
            reqs.append({'updateParagraphStyle': {
                'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + u16(t)},
                'paragraphStyle': {'namedStyleType': f'HEADING_{lvl}'}, 'fields': 'namedStyleType'}})
        if opts.get('bold'):
            reqs.append({'updateTextStyle': {
                'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + u16(t) - 1},
                'textStyle': {'bold': True}, 'fields': 'bold'}})
        cur += u16(t)
    def block(title, why, img):
        """жирный заголовок + строка «за что» + пустой абзац под картинку; → сдвиг cur"""
        nonlocal cur
        line = title + '\n'
        reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': line}})
        reqs.append({'updateTextStyle': {'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + u16(line) - 1},
                                         'textStyle': {'bold': True}, 'fields': 'bold'}})
        cur += u16(line)
        w = why + '\n'
        reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': w}})
        cur += u16(w)
        demo_at.append((img, cur))                     # картинка встанет своим абзацем
        reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': '\n'}})
        cur += 1

    if CARDS:
        fv = Path(P.MOCK) / 'bdd' / 'titles' / 'film_variants.json'
        film = json.loads(fv.read_text(encoding='utf-8')) if fv.is_file() else {}
        if film.get('variants'):
            for lvl, text in ((2, T('chp.film_h', title=film.get('title', ''))), (0, T('chp.film_lead'))):
                t = text + '\n'
                reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': t}})
                if lvl:
                    reqs.append({'updateParagraphStyle': {
                        'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + u16(t)},
                        'paragraphStyle': {'namedStyleType': f'HEADING_{lvl}'}, 'fields': 'namedStyleType'}})
                cur += u16(t)
            for fvar in film['variants']:
                block(f'{fvar["v"].upper()} — {fvar["name"]}', fvar['why'],
                      f'bdd/titles/title_film_{fvar["v"]}.png')
        else:
            print('⚠️ вариантов названия фильма нет — сначала bdd_plates.py titles', flush=True)
    for v, name, why in ([] if ONLY_CH else DEMOS):
        mark = T('chp.chosen') if PICKED == v else ''
        block(f'{v.upper()} — {name}{mark}', why, f'ch_demo_{v}.jpg')

    # ── подглавы: панели перечислений внутри главы (Роман 22.09.2026) ──
    if PROG and not ONLY_CH:
        for lvl, text, opts in [(2, T('chp.pan_h'), {'bold': True}),
                                (0, T('chp.pan_lead'), {}),
                                (0, T('chp.pan_ask'), {'bold': True})]:
            t = text + '\n'
            reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': t}})
            if lvl:
                reqs.append({'updateParagraphStyle': {
                    'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + u16(t)},
                    'paragraphStyle': {'namedStyleType': f'HEADING_{lvl}'}, 'fields': 'namedStyleType'}})
            if opts.get('bold'):
                reqs.append({'updateTextStyle': {
                    'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + u16(t) - 1},
                    'textStyle': {'bold': True}, 'fields': 'bold'}})
            cur += u16(t)
        for v, nm, why in PROG_DEMOS:
            block(f'{v.upper()} — {nm}', why, f'prog_demo_{v}.jpg')
        for lvl, text, opts in [(0, T('chp.pan_foot'), {})]:
            t = text + '\n'
            reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': t}})
            if lvl:
                reqs.append({'updateParagraphStyle': {
                    'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + u16(t)},
                    'paragraphStyle': {'namedStyleType': f'HEADING_{lvl}'}, 'fields': 'namedStyleType'}})
            if opts.get('bold'):
                reqs.append({'updateTextStyle': {
                    'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + u16(t) - 1},
                    'textStyle': {'bold': True}, 'fields': 'bold'}})
            cur += u16(t)
        for no, pg in sorted(PROG.items()):
            items = list(pg.get('items') or [])
            block(T('chp.pan_block', no=no, name=CH_NAME.get(no, ''), title=pg.get('title', '')),
                  T('chp.pan_items', n=len(items)) + ' · '.join(items), f'prog_{no}_0.jpg')

    batch_update(DOC_ID, reqs)
    print(f'шапка: {len(head)} абзацев + {len(DEMOS)} вариантов + подглав {len(PROG)}', flush=True)

    # картинки НЕ вставляем по ходу: под временным доступом файл открыт считанные секунды, поэтому
    # все вставки — одной пачкой в самом конце, когда весь текст вкладки уже записан
    want = [(name, at, 640 if 'title_film_' in name else 460) for name, at in demo_at] + head_img

    cur = tab_body(tab_id)[-1]['endIndex'] - 1
    batch_update(DOC_ID, [{'insertTable': {'location': {'tabId': tab_id, 'index': cur},
                                           'rows': len(rows) + len(EXTRA) + 1, 'columns': len(HDR)}}])
    tbl = fresh_table(tab_id, len(rows) + len(EXTRA) + 1, empty=True)
    cells = [r['tableCells'] for r in tbl['table']['tableRows']]
    all_cells = ([HDR] + [[r['no'], '', r['body'], r['tc'], r['now'], r['do']] for r in rows]
                 + [['—', '', T('chp.extra_now'), t, w, T('chp.extra_do')]
                    for t, w in EXTRA])
    treqs = []
    for ri in range(len(all_cells) - 1, -1, -1):
        for cj in range(len(HDR) - 1, -1, -1):
            txt = str(all_cells[ri][cj])
            if txt:
                treqs.append({'insertText': {'location': {'tabId': tab_id,
                                                          'index': cells[ri][cj]['content'][0]['startIndex']},
                                             'text': txt}})
    for i in range(0, len(treqs), 200):
        batch_update(DOC_ID, treqs[i:i + 200])
    print(f'таблица: {len(rows)} глав', flush=True)

    trows = fresh_table(tab_id, len(rows) + len(EXTRA) + 1)['table']['tableRows']
    for ri in range(1, len(rows) + 1):
        name = rows[ri - 1]['img']
        if name:
            want.append((name, trows[ri]['tableCells'][1]['content'][0]['startIndex'], IMG_W))
    rc_img = put_images(tab_id, want)

    tbl = fresh_table(tab_id, len(rows) + len(EXTRA) + 1)
    tstart = tbl['startIndex']            # начало таблицы — у элемента, а не «первая ячейка − 1»
    trows = tbl['table']['tableRows']
    sreqs = []
    for c in trows[0]['tableCells']:
        st = c['content'][0]['startIndex']
        en = c['content'][-1]['endIndex'] - 1
        if en > st:
            sreqs.append({'updateTextStyle': {'range': {'tabId': tab_id, 'startIndex': st, 'endIndex': en},
                                              'textStyle': {'bold': True}, 'fields': 'bold'}})
    for cj, w in enumerate(WIDTHS):
        sreqs.append({'updateTableColumnProperties': {
            'tableStartLocation': {'tabId': tab_id, 'index': tstart},
            'columnIndices': [cj],
            'tableColumnProperties': {'widthType': 'FIXED_WIDTH', 'width': {'magnitude': w, 'unit': 'PT'}},
            'fields': 'widthType,width'}})
    # альбомная страница ТОЛЬКО этой вкладке: таблица 1222 pt в портретную полосу (468 pt) не влезает
    sreqs.append(DT.landscape_request(tab_id))
    batch_update(DOC_ID, sreqs)
    mark = '✅' if not rc_img else '⚠️'
    print(f'{mark} вкладка «{TAB_TITLE}» собрана: '
          f'https://docs.google.com/document/d/{DOC_ID}/edit?tab={tab_id}', flush=True)
    return rc_img


if __name__ == '__main__':
    sys.exit(main())
