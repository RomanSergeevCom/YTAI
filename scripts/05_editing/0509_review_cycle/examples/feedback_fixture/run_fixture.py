#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_fixture.py — «Обратная связь по кату» end-to-end на синтетике (build_fixture.py) во ВРЕМЕННОЙ папке.

0 токенов, без Google, без Telegram, без облака, без внешних дисков:
  А. модули по одному: feedback_model → feedback_call --print-call → --apply (сначала чужой пакет → отказ, затем
     канон ответа сверщика) → feedback_page → doc_tab_feedback_v1 --dump-requests → verify --from-dump;
  Б. оркестратор review.py на второй копии: без prev_pravki три стадии пропускаются; ключ задан, а файла нет —
     предупреждение с путём; ожидание облака → устаревший ответ откладывается (не удаляется) → канон вливается.
Ожидания зашиты литералами. Репозиторий не пишется: всё во tempfile, папка удаляется (кроме --keep).

    python3 run_fixture.py            # таблица проверок, exit 0 = всё сошлось
    python3 run_fixture.py --json     # + последняя строка «ROWS [[name, ok, msg], …]» (review.py selftest)
    python3 run_fixture.py --keep     # оставить временную папку (путь в выводе)
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE = HERE.parent.parent
PY = sys.executable or 'python3'
sys.path.insert(0, str(HERE))
import build_fixture as BF  # noqa: E402

# ── ожидания (литералы) ────────────────────────────────────────────────────────────────────────────────────────
BUCKETS_BUILD = {1: 'closed', 2: 'block', 3: 'open', 4: 'fund', 5: 'blur', 6: 'appendix', 7: 'open', 8: 'appendix'}
BUCKETS_APPLIED = {**BUCKETS_BUILD, 8: 'closed'}
TALLY_BUILD = dict(new=2, prev_total=8, closed=1, open=3, blur=1, fund=1, unknown=2)
TALLY_APPLIED = dict(new=2, prev_total=8, closed=2, open=3, blur=1, fund=1, unknown=1)
PACKET_NS = [1, 6, 8, 2]            # по времени в новом кате: кодовое «закрыто», два непроверенных, обязательное «осталось»
BLOCKERS = [(1, 2, '4:00'), (1, 1, '5:00'), (2, 2, '10:04')]      # первый экран: (часть, номер, таймкод), по времени
SENSITIVE_NS = [4, 5]
TC_NEW = {1: '1:19', 2: '10:04', 3: '2:49', 4: '3:29', 5: '6:09', 6: '4:47', 7: '', 8: '6:40'}
STALE_NAME = 'feedback_check.stale-PACKETSHA.json'
CAPTIONS = ['4:00', '5:00', '10:04', '2:49', '6:09']              # подписи под кадрами HTML, в порядке строк: «M:SS · кадр ката v2»
# подписи вкладки (6 колонок): у полной строки — «ошибка» (если есть время) и «как надо» (всегда); порядок — секции контракта
DOC_CAPTIONS = [c for tc in ('4:00', '5:00', '10:04', None, '2:49', '6:09', '1:19', '6:40')
                for c in ([f'{tc} · кадр ката v2'] if tc else []) + [f'{tc or "сводно"} · как надо']]
SECTIONS = ['ЧАСТЬ 1 · НОВОЕ В v2', 'ЧАСТЬ 2 · ПРОВЕРКА ТЗ v1', '🔴 БЛОКИРУЕТ ВЫПУСК', '❌ ОСТАЛОСЬ', '⚠️ БЛЮР И ОБЕЗЛИЧИВАНИЕ',
            '✅ ЗАКРЫТО', '⚠️ ЖДЁТ ОТВЕТА ФОНДА', 'Не проверено автоматически']

# Фикстура никуда не ходит, даже если код сломают (например, стадия страницы начнёт звать --send): поддельный токен
# бота и мёртвый прокси на всё. Без этого регресс в review.py отправил бы синтетическую страницу в настоящий чат.
NO_NET = {'TG_BOT_TOKEN': '0:fixture-never-sends', 'TELEGRAM_BOT_TOKEN': '0:fixture-never-sends',
          **{k: 'http://127.0.0.1:9' for k in ('http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')},
          'no_proxy': '', 'NO_PROXY': ''}

ROWS, LOG = [], []


def row(name, cond, msg=''):
    ROWS.append([name, bool(cond), '' if cond else str(msg)[:220]])
    return bool(cond)


def jload(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception:                                       # noqa: BLE001
        return default


def clean_env(card):
    """окружение без единого YTAI_* родителя: YTAI_PREV_PRAVKI / YTAI_DOC_ID снаружи увели бы фикстуру в чужой проект"""
    env = {k: v for k, v in os.environ.items() if not k.startswith('YTAI_') and k != 'TZ_TAB'}
    env['YTAI_CARD'] = str(card)
    env['PYTHONUNBUFFERED'] = '1'
    env.update(NO_NET)
    return env


def run(name, argv, card, cwd):
    p = subprocess.run([str(a) for a in argv], capture_output=True, text=True, env=clean_env(card), cwd=str(cwd), timeout=600)
    LOG.append((name, p.returncode, p.stdout + p.stderr))
    return p.returncode, p.stdout + p.stderr


def buckets(fb):
    return {r['n']: r['bucket'] for r in (fb or {}).get('part2') or []}


def _in_order(text, marks):
    """все метки есть и идут строго в этом порядке"""
    pos = [text.find(m) for m in marks]
    return all(x >= 0 for x in pos) and pos == sorted(pos) and len(set(pos)) == len(pos)


def modules(tmp):
    """А. модули по одному"""
    rv = BF.build(tmp / 'a')
    card, w = rv / 'review_card.json', rv / 'work' / BF.CUT
    SH, ST = STAGE / 'shared', STAGE / 'stages'

    rc, out = run('model', [PY, SH / 'feedback_model.py'], card, rv)
    fb = jload(w / 'feedback.json', {})
    row('обратная связь · модель: сборка rc 0, разбор без потерь 8/8', rc == 0 and 'разбор без потерь: 8/8' in out, out[-200:])
    row('обратная связь · модель: счётчики и разделы по номерам', fb.get('tally') == TALLY_BUILD and buckets(fb) == BUCKETS_BUILD,
        f'{fb.get("tally")} {buckets(fb)}')
    p2 = {r['n']: r for r in fb.get('part2') or []}
    row('обратная связь · модель: таймкоды пересчитаны на новый кат (+49 с), битый «238:03» восстановлен',
        {n: r['tc_new'] for n, r in p2.items()} == TC_NEW and p2.get(6, {}).get('tc_fixed') is True
        and not any(r['tc_fixed'] for n, r in p2.items() if n != 6), {n: (r['tc_new'], r['tc_fixed']) for n, r in p2.items()})
    row('обратная связь · модель: перестановка при нуле переставленных сцен — «осталось», не «закрыто»',
        p2.get(7, {}).get('status') == 'open' and fb.get('align', {}).get('moved') == 0, p2.get(7, {}).get('status'))
    row('обратная связь · модель: два пункта с одним key остались двумя строками (идентификатор — номер)',
        p2.get(3, {}).get('key') == p2.get(8, {}).get('key') and len(p2) == 8, sorted(p2))
    p1 = {r['n']: r for r in fb.get('part1') or []}
    row('обратная связь · модель: Часть 1 — 2 пункта, оба держат выпуск, опечатка «было → стало» на месте',
        len(p1) == 2 and all(r['blocker'] for r in p1.values()) and p1.get(1, {}).get('typo') == [{'was': 'КОРЖЕВ', 'now': 'КОРЖОВ'}]
        and [(b['part'], b['n'], b['tc']) for b in fb.get('blockers') or []] == BLOCKERS,
        ([(n, r['blocker'], r['typo']) for n, r in p1.items()], fb.get('blockers')))
    row('обратная связь · модель: чувствительные — блюр монтажёру (5) и ожидание фонда с темой (4)',
        p2.get(5, {}).get('status') == 'open' and p2.get(4, {}).get('status') == 'fund' and p2.get(4, {}).get('topic') == 'names',
        (p2.get(4, {}).get('topic'), p2.get(5, {}).get('status')))

    rc, out = run('print-call', [PY, SH / 'feedback_call.py', '--print-call'], card, rv)
    pk = jload(rv / 'cloud' / 'in' / 'feedback_items.json', {})
    last = out.strip().splitlines()[-1] if out.strip() else ''
    row('обратная связь · пакет сверщику: rc 0, последней строкой вызов Workflow', rc == 0 and last.startswith('Workflow('), last[:120])
    ns = [i['n'] for i in pk.get('items') or []]
    sent = (rv / 'cloud' / 'in' / 'feedback_items.json').read_text(encoding='utf-8') if pk else ''
    row('обратная связь · пакет сверщику: пункты 1, 6, 8, 2; чувствительных нет ни по номеру, ни по тексту',
        ns == PACKET_NS and not set(ns) & set(SENSITIVE_NS) and 'накладн' not in sent and 'номер машины' not in sent.lower(), ns)

    canned = jload(rv / 'cloud_canned.json', {})
    before = (w / 'feedback.json').read_bytes()
    rc, out = run('apply-stale', [PY, SH / 'feedback_call.py', '--apply', '--from', rv / 'cloud_canned.json'], card, rv)
    row('обратная связь · вливание: ответ по чужому пакету → rc 2, модель не тронута',
        rc == 2 and (w / 'feedback.json').read_bytes() == before, f'rc={rc} {out[-160:]}')
    good = rv / 'cloud' / 'out' / 'feedback_check.json'
    good.parent.mkdir(parents=True, exist_ok=True)
    good.write_text(json.dumps(dict(canned, packet_sha=pk.get('packet_sha')), ensure_ascii=False), encoding='utf-8')
    rc, out = run('apply', [PY, SH / 'feedback_call.py', '--apply'], card, rv)
    fb = jload(w / 'feedback.json', {})
    p2 = {r['n']: r for r in fb.get('part2') or []}
    ag = fb.get('agent') or {}
    row('обратная связь · вливание: rc 0, счётчики и разделы после ответа сверщика', rc == 0 and fb.get('tally') == TALLY_APPLIED
        and buckets(fb) == BUCKETS_APPLIED, f'rc={rc} {fb.get("tally")} {buckets(fb)}')
    row('обратная связь · вливание: честное «закрыто» (8) принято с цитатой с экрана',
        p2.get(8, {}).get('status_by') == 'agent' and (p2.get(8, {}).get('evidence') or {}).get('tc') == '6:40'
        and 'ПЕЧЬ ПОСТРОЕНА' in ((p2.get(8, {}).get('evidence') or {}).get('text') or ''), p2.get(8, {}).get('evidence'))
    row('обратная связь · вливание: выдуманная цитата (6) отброшена, чужой номер (99) отброшен',
        p2.get(6, {}).get('status') == 'unknown' and 'не принят' in (p2.get(6, {}).get('agent_note') or '')
        and ag.get('accepted') == 1 and ag.get('rejected') == 3 and ag.get('no_answer') == [2], ag)
    row('обратная связь · вливание: «закрыто» с честной цитатой, но уверенностью 0,7 (1) не принято — порог 0,8',
        p2.get(1, {}).get('status') == 'closed' and p2.get(1, {}).get('status_by') == 'code'
        and 'ниже 0.8' in json.dumps(ag, ensure_ascii=False) + (p2.get(1, {}).get('agent_note') or ''),
        (p2.get(1, {}).get('status_by'), p2.get(1, {}).get('agent_note'), ag))

    BF.make_frames(rv, fb.get('frames_wanted') or [])
    rc, out = run('page', [PY, SH / 'feedback_page.py'], card, rv)
    html_p = rv / f'{BF.CODE}_{BF.CUT}_feedback.html'
    page = html_p.read_text(encoding='utf-8') if html_p.exists() else ''
    row('обратная связь · страница: rc 0, файл на месте, без отправки в Telegram', rc == 0 and page and 'Telegram' not in out, out[-200:])
    row('обратная связь · страница: ни одного внешнего адреса, кадры внутри файла, значок вкладки есть',
        page and not re.search(r'https?://', page) and 'data:image/jpeg;base64,' in page and 'rel="icon"' in page.replace("'", '"'),
        re.findall(r'https?://[^"\' <)]+', page)[:3])

    caps = [f'{tc} · кадр ката {BF.CUT}' for tc in CAPTIONS]
    row('обратная связь · страница: под каждым кадром подпись «время · кадр ката», разделы в порядке контракта',
        re.findall(r'<div class="cap">([^<]*)</div>', page) == caps and _in_order(page, SECTIONS),
        (re.findall(r'<div class="cap">([^<]*)</div>', page), [page.find(x) for x in SECTIONS]))

    doc_caps = BF.make_visuals(rv, fb)                   # вкладка в 6 колонок: картинки «ошибка» и «как надо» из индекса визуалов
    d1, d2 = w / 'feedback_dump.json', w / 'feedback_dump2.json'
    rc, out = run('dump', [PY, ST / 'doc_tab_feedback_v1.py', '--images', 'temp', '--dump-requests', d1], card, rv)
    row('обратная связь · вкладка: офлайн-дамп rc 0, Google не вызывался', rc == 0 and d1.exists() and 'Google API не вызывался' in out, out[-200:])
    rc, out = run('verify', [PY, ST / 'doc_tab_feedback_v1_verify.py', '--from-dump', d1], card, rv)
    last = out.strip().splitlines()[-1] if out.strip() else ''
    row('обратная связь · вкладка: проверка дампа ALL PASS', rc == 0 and last == 'ALL PASS',
        '; '.join(ln.strip() for ln in out.splitlines() if ln.startswith('FAIL'))[:200] or last)
    text = (jload(d1, {}) or {}).get('final_text') or ''
    got = [m.strip() for m in re.findall(r'\[IMG\]⏎([^|⏎]*)', text)]
    row('обратная связь · вкладка: под каждой картинкой подпись «время · что видно» (ошибка у строк с временем, «как надо» '
        'у всех полных), разделы в порядке контракта',
        got == doc_caps == DOC_CAPTIONS and text.count('[IMG]') == len(doc_caps) and _in_order(text, ['[' + x for x in SECTIONS]),
        (got, doc_caps, [text.find('[' + x) for x in SECTIONS]))
    src_n = sum(1 for ln in text.splitlines() for c in ln.split(' | ') if 'Источник: ' in c)
    row('обратная связь · вкладка: 6 колонок, вердикт первой строкой цветом у полных строк, «Источник:» под каждой «как надо»',
        (jload(d1, {}) or {}).get('widths') == [40, 44, 104, 168, 160, 160] and src_n == sum(1 for c in doc_caps if 'как надо' in c)
        and text.count('❌ НЕПРАВИЛЬНО⏎') == 5 and text.count('✅ ПРАВИЛЬНО⏎') == 2 and text.count('⚠️ ЖДЁТ ФОНДА⏎') == 1
        and text.count('👁 НЕ ПРОВЕРЕНО⏎') == 1 and text.count('⚠️ БЛЮР — делает монтажёр⏎') == 1,
        (src_n, text.count('❌ НЕПРАВИЛЬНО⏎'), text.count('✅ ПРАВИЛЬНО⏎')))
    run('dump2', [PY, ST / 'doc_tab_feedback_v1.py', '--images', 'temp', '--dump-requests', d2], card, rv)
    row('обратная связь · вкладка: дамп детерминирован (два прогона побайтно равны)',
        d1.exists() and d2.exists() and d1.read_bytes() == d2.read_bytes())
    return canned


def orchestrator(tmp, canned):
    """Б. три стадии review.py: пропуск, предупреждение, ожидание облака, устаревший ответ, вливание"""
    for k in [k for k in os.environ if k.startswith('YTAI_') or k == 'TZ_TAB']:     # Review.env() копирует os.environ
        os.environ.pop(k)
    os.environ.update(NO_NET)
    spec = importlib.util.spec_from_file_location('ytai_review_cli', STAGE / 'review.py')
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    names = [s[0] for s in R.STAGES_CUT]
    row('review.py: три стадии сверки стоят в конце цепочки, после producer_page',
        names[-4:] == ['producer_page', 'feedback', 'feedback_page', 'doc_feedback']
        and all(n in R.STAGE_DESC for n in names[-3:]) and all(s[4] == 'SOFT' and s[1] == 'mac' for s in R.STAGES_CUT[-3:]), names[-4:])
    row('review.py: сверщику в автономном режиме — один облачный раунд, остальным стадиям по-прежнему 4',
        R.AUTO_CLOUD_ROUNDS_BY_STAGE == {'feedback': 1} and R.AUTO_CLOUD_ROUNDS == 4)

    def quiet(r):
        r.log = lambda msg: LOG.append(('review', 0, str(msg)))
        return r

    # без prev_pravki — все три «пропущена», гейты открыты
    rv = BF.build(tmp / 'b', prev_pravki=False)
    r = quiet(R.Review(rv.parent.parent))
    res = [fn(r) for fn in (R.st_feedback, R.st_feedback_page, R.st_doc_feedback)]
    row('review.py: без prev_pravki три стадии пропускаются, гейты открыты',
        res == [(True, R.FB_SKIP)] * 3 and all(v(r) for v in (R.v_feedback, R.v_feedback_page, R.v_doc_feedback))
        and not (rv / 'work' / BF.CUT / 'feedback.json').exists(), res)

    # ключ задан, файла нет — предупреждение с путём, без повторов, цепочка идёт дальше
    rv = BF.build(tmp / 'c')
    missing = rv / f'{BF.PREV}_review' / f'pravki_{BF.PREV}.json'
    missing.unlink()
    r = quiet(R.Review(rv.parent.parent))
    soft = R.run_stage(r, 'feedback', 'mac', R.st_feedback, R.v_feedback, 'SOFT', force=False)     # так идут resume и Memex
    stg = dict(r.st('feedback'))
    row('review.py: prev_pravki указан, файла нет → и без --only/--from стадия не «подтверждается по артефактам» молча',
        soft and stg.get('status') == 'warn' and str(missing) in stg.get('msg', '') and not R.v_feedback(r), stg)
    went = R.run_stage(r, 'feedback', 'mac', R.st_feedback, R.v_feedback, 'SOFT', force=True)
    stg = r.st('feedback')
    row('review.py: prev_pravki указан, файла нет → предупреждение с путём, не тихий пропуск',
        went and stg.get('status') == 'warn' and stg.get('msg', '').startswith('prev_pravki указан, файла нет: ')
        and str(missing) in stg.get('msg', '') and stg.get('attempts') == 1, stg)

    # полный путь: ждём облако → устаревший ответ отложен → канон влит
    rv = BF.build(tmp / 'd')
    r = quiet(R.Review(rv.parent.parent))
    out_f = rv / 'cloud' / 'out' / 'feedback_check.json'

    def step():
        try:
            return R.st_feedback(r)
        except R.AwaitCloud as e:
            return 'await', str(e)
    first = step()
    call = (rv / 'cloud' / 'CALL_feedback.txt').read_text(encoding='utf-8') if (rv / 'cloud' / 'CALL_feedback.txt').exists() else ''
    row('review.py feedback: модель собрана, вызов сверщика записан, стадия ждёт облако',
        first[0] == 'await' and any(ln.startswith('Workflow(') for ln in call.splitlines()) and not R.v_feedback(r), first)
    out_f.write_text(json.dumps(canned, ensure_ascii=False), encoding='utf-8')            # sha-заглушка = чужой пакет
    second = step()
    row('review.py feedback: устаревший ответ не удалён, а отложен; стадия снова ждёт облако',
        second[0] == 'await' and not out_f.exists() and (out_f.parent / STALE_NAME).exists(),
        (second, sorted(p.name for p in out_f.parent.glob('*'))))
    sha = (jload(rv / 'cloud' / 'in' / 'feedback_items.json', {}) or {}).get('packet_sha')
    out_f.write_text(json.dumps(dict(canned, packet_sha=sha), ensure_ascii=False), encoding='utf-8')
    third = step()
    fb = jload(rv / 'work' / BF.CUT / 'feedback.json', {})
    row('review.py feedback: сборка → вливание, гейт закрыт, счётчики как у прямого вызова',
        third[0] is True and R.v_feedback(r) and fb.get('tally') == TALLY_APPLIED and buckets(fb) == BUCKETS_APPLIED
        and fb.get('build_no') == 3, (third, fb.get('tally'), fb.get('build_no')))
    page = R.st_feedback_page(r)
    row('review.py feedback_page: страница собрана без отправки', page[0] is True and R.v_feedback_page(r)
        and 'Telegram' not in page[1], page)
    doc = R.st_doc_feedback(r)
    row('review.py doc_feedback: без doc_id вкладка пропущена (Memex и Google не трогаются)',
        doc == (True, 'doc_id пуст — вкладка обратной связи пропущена') and R.v_doc_feedback(r), doc)

    # producer_page: строки трёх стадий видны только фильму с prev_pravki (состояние стадий одинаковое у обоих)
    seen = {}
    for name, rv_x in (('без', tmp / 'b'), ('с', tmp / 'd')):
        rv_x = rv_x / f'{BF.CODE}_Feedback_Fixture' / '00_Setup' / '05_Review'
        state = jload(rv_x / 'review_state.json', {}) or {'schema': 'review-state-v1', 'stages': {}}
        for n in ('producer_page', 'feedback', 'feedback_page', 'doc_feedback'):
            state['stages'][n] = {'status': 'done', 'msg': 'фикстура', 'host': 'mac'}
        (rv_x / 'review_state.json').write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        rc, out = run(f'producer_page {name}', [PY, STAGE / 'shared' / 'producer_page.py'], rv_x / 'review_card.json', rv_x)
        html_p = rv_x / f'{BF.CODE}_{BF.CUT}_review_producer.html'
        page = html_p.read_text(encoding='utf-8') if rc == 0 and html_p.exists() else ''
        seen[name] = [page.count(f'<td>{n}</td>') for n in ('producer_page', 'feedback', 'feedback_page', 'doc_feedback')]
    row('producer_page: без prev_pravki строк feedback / feedback_page / doc_feedback нет, с ключом — есть',
        seen == {'без': [1, 0, 0, 0], 'с': [1, 1, 1, 1]}, seen)

def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--keep', action='store_true')
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix='ytai_feedback_fixture_'))
    try:
        canned = modules(tmp)
        orchestrator(tmp, canned)
    except Exception as e:                                  # noqa: BLE001  — строка FAIL, а не трейсбек в selftest
        import traceback
        row('обратная связь · фикстура: цепочка без исключений', False, f'{type(e).__name__}: {e} · {traceback.format_exc()[-300:]}')
    finally:
        if not all(r[1] for r in ROWS):
            for name, rc, out in LOG:
                if rc:
                    print(f'--- {name} rc={rc}\n{out[-800:]}')
        if a.keep:
            print(f'временная папка оставлена: {tmp}')
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    for name, good, msg in ROWS:
        print(f'{"✅" if good else "✗ "} {name}' + (f'  — {msg}' if msg else ''))
    bad = [r for r in ROWS if not r[1]]
    print('ИТОГ фикстура обратной связи:', 'OK' if not bad else f'FAIL {len(bad)}')
    if a.json:
        print('ROWS ' + json.dumps(ROWS, ensure_ascii=False))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
