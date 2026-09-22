#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_fixture.py — синтетический мини-проект для «Обратной связи по кату» (контракт docs/feedback_v1.md).

Фильм выдуманный (пекарня, 26 минут), людей и фонда в нём нет. Все данные — литералы в этом файле: в репозитории
фикстура не хранит ни одного файла данных, всё раскладывается в указанную временную папку.

    build(tmp) → Path к {tmp}/FBFX01_Feedback_Fixture/00_Setup/05_Review
    python3 build_fixture.py <папка>        # собрать и напечатать путь

Что внутри:
  review_card.json            кат v2 против v1, prev_pravki, без doc_id и без канала (профиль не нужен)
  v1_review/pravki_v1.json    прошлое ТЗ, 8 пунктов — по одному на каждый случай (см. PREV ниже)
  pravki/pravki_v2.json       текущее ТЗ, 2 пункта с parts (один — опечатка, второй — провал правила канала)
  FBFX01_v2.words.json        речь нового ката, 40 сегментов, шаг 40 с
  FBFX01_v1.words.json        прошлый кат: только длительность (по имени файла находится база сверки)
  work/v2/align.json          база сверки: начало на месте, остальное сдвинуто на +49 с, перестановок нет
  work/v2/screens_v6.json, vlm_v6.jsonl, structure_checks.json (один fail)
  cloud_canned.json           ответ сверщика: честное «закрыто», выдуманная цитата, чужой номер (sha — заглушка)
"""
import base64
import json
import sys
from pathlib import Path

CODE, CUT, PREV = 'FBFX01', 'v2', 'v1'
DURATION, OLD_DURATION, SHIFT, STEP = 1600.0, 1551.0, 49.0, 40
# кат длиннее 24 минут намеренно: проверка вкладки читает «собрано … 23:47» в шапке как таймкод и на коротком кате
# даёт ложное «таймкод длиннее ката» (замечено 21.09, модуль проверки — чужой, здесь обходим длиной фильма)
SHA_PLACEHOLDER = '@PACKET_SHA@'

# 1×1 серый JPEG — запасной кадр, если PIL недоступен
_JPEG_1X1 = ('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABsSFBcUERsXFhceHBsgKEIrKCUlKFE6PTBCYFVlZF9VXVtqeJmBanGQc1tdhbWGkJ6jq62rZ4C8ybqm'
             'x5moq6T/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAAAP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AP//Z')

# ── речь нового ката: 40 сегментов, старт = i·STEP с ─────────────────────────────────────────────────────────────
SPEECH = [
    'Мы открываем пекарню в пять утра, когда город ещё спит.',
    'Первым делом я проверяю закваску, она живая и капризная.',
    'Мой дед построил эту печь своими руками после войны.',
    'Раньше здесь была обычная булочная, очередь стояла до угла.',
    'Потом всё закрылось, и здание десять лет стояло пустым.',
    'Я вернулась сюда случайно, просто шла мимо и увидела вывеску.',
    'Нам очень помог фонд, без него мы бы не открылись.',                       # 4:00 — первое упоминание фонда
    'Фонд оплатил ремонт крыши и новую проводку в цеху.',
    'Первый хлеб получился плоский, как подошва, мы смеялись до слёз.',
    'Соседи приходили просто посмотреть, что тут снова горит свет.',
    'Иван Петрович пришёл на третий день и сказал, что умеет печь.',
    'Он сорок лет проработал на хлебозаводе и знает тесто на ощупь.',
    'С ним мы впервые вышли на сто буханок в день.',
    'Зимой было тяжело, печь остывала быстрее, чем мы успевали топить.',
    'Муку привозит один и тот же поставщик уже третий год.',
    'Знаете, я тогда вообще никому не верила и всё делала назло.',              # 10:00 — реплика пункта «вырезать повтор»
    'Даже деду не верила, хотя он ни разу меня не обманул.',
    'Сейчас смешно вспоминать, а тогда я неделями ни с кем не говорила.',
    'Хлеб меня вылечил, это звучит громко, но так и есть.',
    'Когда месишь тесто, руки заняты, и голова наконец отдыхает.',
    'У нас четыре вида хлеба, и каждый требует своего времени.',
    'Ржаной стоит на закваске почти сутки, его нельзя торопить.',
    'Пшеничный капризнее, он чувствует сквозняк и хлопнувшую дверь.',
    'Люди приезжают с другого конца города за нашим бородинским.',
    'Машина с мукой обычно стоит во дворе до самого обеда.',
    'Шаги в цеху слышно отовсюду, пол здесь старый и деревянный.',
    'Печь мы разбирали дважды, меняли свод и чистили дымоход.',
    'Этой печи много лет, кирпич для неё дед возил сам.',
    'Под сводом до сих пор видна дата, выбитая на кирпиче.',
    'Я хотела повесить рядом табличку, но всё руки не доходят.',
    'Иван Петрович говорит, что печь помнит каждого пекаря.',
    'Он учит молодых не смотреть на часы, а слушать корку.',
    'Корка поёт, когда хлеб готов, это надо один раз услышать.',
    'Летом мы открываем окна, и запах стоит на всю улицу.',
    'Дети из соседней школы заходят после уроков за горбушками.',
    'Мы никогда не выбрасываем хлеб, вечером всё раздаём.',
    'Я не знаю, что будет через десять лет, но печь переживёт нас.',
    'Дед говорил, что хлеб не терпит вранья и спешки.',
    'Наверное, поэтому я здесь, мне больше негде быть честной.',
    'Приходите утром, в пять, когда город ещё спит.',
]
assert len(SPEECH) == 40

SCREENS = [
    dict(id='s001', t0=80, t1=84, tc='1:20', text='ПЕКАРНЯ НА СТАРОМ УГЛУ'),
    dict(id='s004', t0=170, t1=174, tc='2:50', text='РЖАНОЙ ХЛЕБ'),             # 2 слова из 5 нужной плашки — это не «закрыто» (пункт 3)
    dict(id='s002', t0=300, t1=304, tc='5:00', text='КОРЖЕВ И. П.\nстарший смены'),
    dict(id='s003', t0=400, t1=405, tc='6:40', text='ПЕЧЬ ПОСТРОЕНА В 1956 ГОДУ'),
]
VLM = [
    dict(id='s001', t0=80, desc='A title card over a street corner bakery at dawn.'),
    dict(id='s004', t0=170, desc='A short caption over loaves of rye bread on a rack.'),
    dict(id='s002', t0=300, desc='An elderly baker in a white apron stands by the oven; a name caption is visible.'),
    dict(id='s003', t0=400, desc='A close-up of an old brick oven with a caption about the year it was built.'),
]

_LONG_NOW = ('На 5:51 печь показана без подписи, а на 6:05 подпись стоит чужая 🥖 — зритель не понимает, что это та самая '
             'печь деда, о которой героиня говорит с самого начала фильма. ' +
             'Кадр держится долго, в нём ничего не происходит, и без подписи он читается как случайная перебивка. ' * 3 +
             'Нужна одна понятная подпись с годом постройки.')
assert 450 <= len(_LONG_NOW) <= 600

# ── прошлое ТЗ (кат v1): 8 пунктов, таймкоды — по кату v1 ──────────────────────────────────────────────────────
PREV_ITEMS = [
    # 1 · закрыт графикой: титр из ✅ стоит на экране нового ката рядом с проекцией (0:30 → 1:19)
    dict(key='must:title', title='Титр с названием пекарни в начале', category='graphics', severity='must',
         v1_tc='0:30', tc_range='0:30–0:34', sensitive=False, status='draft',
         nado='❌ СЕЙЧАС · Фильм начинается без названия места: зритель минуту не знает, где он.\n'
              '✅ СДЕЛАТЬ · Поставить титр «ПЕКАРНЯ НА СТАРОМ УГЛУ» после первых реплик.\n📍 ГДЕ · 0:30–0:34'),
    # 2 · must не сделан: вырез, реплика на месте (9:15 → 10:04)
    dict(key='must:cut-repeat', title='Вырезать повтор про недоверие', category='cut', severity='must',
         v1_tc='9:15', tc_range='9:15–9:23', sensitive=False, status='draft',
         nado='❌ СЕЙЧАС · Героиня второй раз говорит «я тогда вообще никому не верила и всё делала назло» — повтор, '
              'мысль уже прозвучала в начале.\n✅ СДЕЛАТЬ · Вырезать повтор целиком, стык закрыть перебивкой с тестом.\n'
              '📍 ГДЕ · 9:15–9:23'),
    # 3 · should не сделан: плашки на экране нет (2:00 → 2:49); key — тот же, что у пункта 8
    dict(key='should:caption', title='Плашка про время выпечки', category='graphics', severity='should',
         v1_tc='2:00', tc_range='2:00–2:05', sensitive=False, status='draft',
         nado='❌ СЕЙЧАС · Про время выпечки героиня говорит вскользь, цифра теряется.\n'
              '✅ СДЕЛАТЬ · Добавить плашку «РЖАНОЙ ХЛЕБ ЗРЕЕТ ДВАДЦАТЬ ЧАСОВ».\n📍 ГДЕ · 2:00–2:05'),
    # 4 · чувствительный, ждёт ответа фонда (2:40 → 3:29)
    dict(key='fund:supplier', title='Фамилия поставщика муки на накладной в кадре — согласовать', category='fund',
         severity='must', v1_tc='2:40', tc_range='2:40–2:44', sensitive=True, status='draft',
         nado='❌ СЕЙЧАС · На накладной в кадре читается фамилия поставщика муки.\n'
              '✅ СДЕЛАТЬ · Дождаться ответа фонда: если фонд откажет — заменить кадр.\n📍 ГДЕ · 2:40–2:44'),
    # 5 · чувствительный, но работа монтажёра уже сейчас: блюр (5:20 → 6:09)
    dict(key='fund:plate', title='Номер машины во дворе', category='fund', severity='must',
         v1_tc='5:20', tc_range='5:20–5:26', sensitive=True, status='draft',
         nado='❌ СЕЙЧАС · Во дворе виден номер машины поставщика.\n✅ СДЕЛАТЬ · Заблюрить номер машины на весь план.\n'
              '📍 ГДЕ · 5:20–5:26'),
    # 6 · без ✅ и с битым таймкодом «секунды:минуты»: 238:03 = 3:58 (→ 4:47)
    dict(key='check:steps', title='Звук шагов громче голоса', category='check', severity='should',
         v1_tc='238:03', tc_range='', sensitive=False, status='draft',
         nado='❌ СЕЙЧАС · Шаги в цеху звучат громче голоса героини, слова приходится угадывать.'),
    # 7 · перестановка TO-BE, а перестановок в новом кате ноль; времени у пункта нет
    dict(key='structure:tobe', title='Структура TO-BE: переставить сцену с печью в начало', category='structure',
         severity='should', v1_tc='', tc_range='весь фильм', sensitive=False, status='draft',
         nado='❌ СЕЙЧАС · Печь появляется только в середине, хотя героиня говорит о ней с первой минуты.\n'
              '✅ СДЕЛАТЬ · Переставить сцену с печью сразу после открытия пекарни.'),
    # 8 · два таймкода в одной строке, эмодзи вне BMP, ❌ на ~500 знаков; key дублирует пункт 3 (5:51 → 6:40)
    dict(key='should:caption', title='Подпись к печи деда', category='graphics', severity='should',
         v1_tc='5:51', tc_range='5:51–6:05', sensitive=False, status='draft',
         nado='❌ СЕЙЧАС · ' + _LONG_NOW + '\n✅ СДЕЛАТЬ · Поставить одну подпись с годом постройки печи.\n📍 ГДЕ · 5:51–6:05'),
]
assert len(PREV_ITEMS) == 8 and PREV_ITEMS[2]['key'] == PREV_ITEMS[7]['key']

# ── текущее ТЗ (кат v2): 2 пункта с parts ──────────────────────────────────────────────────────────────────────
CUR_ITEMS = [
    dict(key='typo:5:00', title='ОПЕЧАТКА: фамилия пекаря в титре написана с ошибкой', category='graphics', **{'class': 'typo'},
         severity='high', v1_tc='5:00', tc_range='5:00–5:04', timeline_in_sec=300, timeline_out_sec=304,
         parts=dict(now=['5:00 ▸ в титре написано «КОРЖЕВ»'], do=['исправить фамилию в титре на «КОРЖОВ»'],
                    where=['5:00–5:04']),
         typo=[dict(was='КОРЖЕВ', now='КОРЖОВ')], material_rich=[], decision='', status='draft',
         nado='❌ СЕЙЧАС · 5:00 ▸ в титре написано «КОРЖЕВ»\n✅ СДЕЛАТЬ · исправить фамилию в титре на «КОРЖОВ»\n📍 ГДЕ · 5:00–5:04'),
    dict(key='verdict:4:00', title='Фонд входит слишком рано: первое упоминание — на пятой минуте', category='structure',
         **{'class': 'structure'}, severity='high', v1_tc='4:00', tc_range='4:00–4:30', timeline_in_sec=240,
         timeline_out_sec=270,
         parts=dict(now=['4:00 ▸ героиня благодарит фонд раньше, чем зритель узнал её историю'],
                    do=['перенести благодарность фонду в последнюю треть фильма'], where=['4:00–4:30']),
         typo=[], material_rich=[], decision='', status='draft',
         nado='❌ СЕЙЧАС · 4:00 ▸ героиня благодарит фонд раньше, чем зритель узнал её историю\n'
              '✅ СДЕЛАТЬ · перенести благодарность фонду в последнюю треть фильма\n📍 ГДЕ · 4:00–4:30'),
]

# ── ответ сверщика: честное «закрыто» (8), выдуманная цитата (6), чужой номер (99) ─────────────────────────────
CANNED = dict(schema='feedback-check-v1', cut_version=CUT, packet_sha=SHA_PLACEHOLDER, verdicts=[
    dict(n=8, status='closed', tc='6:40', quote='ПЕЧЬ ПОСТРОЕНА В 1956 ГОДУ', source='screen', confidence=0.93,
         note='подпись с годом постройки стоит на плане с печью'),
    dict(n=6, status='closed', tc='4:47', quote='шаги теперь звучат тихо и совсем не мешают голосу', source='speech',
         confidence=0.9, note='звук выровнен'),
    dict(n=1, status='closed', tc='1:20', quote='ПЕКАРНЯ НА СТАРОМ УГЛУ', source='screen', confidence=0.7,
         note='титр стоит, но сверщик не уверен'),          # цитата честная, уверенность ниже порога — не принимается
    dict(n=99, status='open', tc='1:00', quote='Мы открываем пекарню в пять утра', source='speech', confidence=0.9,
         note='пункта с таким номером нет'),
])


def _dump(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding='utf-8')


def make_frames(review_dir, files):
    """серые плашки 320×180 на каждый путь (от 05_Review); без PIL — JPEG 1×1"""
    try:
        from PIL import Image
        img = Image.new('RGB', (320, 180), (128, 128, 128))
    except Exception:                                       # noqa: BLE001
        img = None
    for rel in files:
        p = Path(review_dir) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if img is not None:
            img.save(p, 'JPEG', quality=60)
        else:
            p.write_bytes(base64.b64decode(_JPEG_1X1))


def make_visuals(review_dir, fb):
    """индекс визуалов (контракт §9) для вкладки в 6 колонок: «ошибка» у полных строк с временем, «как надо» — у каждой
    полной строки; картинки — серые плашки. Слой визуалов (shared/feedback_visuals.py) здесь не зовётся: фикстура
    проверяет вкладку, а не рисование. → список подписей в порядке строк вкладки (для ожиданий run_fixture)"""
    full = ('new', 'block', 'open', 'blur', 'closed')
    rel = f'work/{CUT}/feedback_visuals'
    rows, caps = {}, []
    order = {b: i for i, b in enumerate(('new', 'block', 'open', 'blur', 'closed', 'fund', 'appendix'))}
    items = [r for r in (fb.get('part1') or []) + (fb.get('part2') or []) if r.get('bucket') in full and not r.get('dup_of')]
    items.sort(key=lambda r: (order[r['bucket']], r.get('sec_new') is not None, float(r.get('sec_new') or 0), int(r.get('n') or 0)))
    files = []
    for r in items:
        key, tc, stem = f'{r["part"]}:{r["n"]}', str(r.get('tc_new') or ''), f'p{r["part"]}_{r["n"]:03d}'
        d = {}
        if tc:
            d['err'] = dict(file=f'{rel}/{stem}_err.jpg', caption=f'{tc} · кадр ката {CUT}', kind='frame',
                            source=dict(text=f'кадр ката {CUT}, {tc}', url=None))
            caps.append(d['err']['caption'])
        d['fix'] = dict(file=f'{rel}/{stem}_fix.jpg', caption=f'{tc or "сводно"} · как надо', kind='draft',
                        source=dict(text=f'наш драфт по кадру {CUT}', url=None))
        caps.append(d['fix']['caption'])
        rows[key] = d
        files += [v['file'] for v in d.values()]
    _dump(Path(review_dir) / rel / 'index.json', dict(schema='feedback-visuals-v1', built_at='2026-09-22 00:00', rows=rows))
    make_frames(review_dir, files)
    return caps


def build(tmp, prev_pravki=True) -> Path:
    """→ папка 05_Review мини-проекта. prev_pravki=False — карточка без ключа (стадии сверки обязаны пропуститься)."""
    rv = Path(tmp) / f'{CODE}_Feedback_Fixture' / '00_Setup' / '05_Review'
    w = rv / 'work' / CUT
    w.mkdir(parents=True, exist_ok=True)
    card = dict(schema='review-card-v1', project='fbfx01', code=CODE, channel='', mode='cut_review', cut_version=CUT,
                project_name=f'{CODE}_Feedback_Fixture', src='', words=f'{CODE}_{CUT}.words.json', duration_sec=DURATION,
                fps=25, lang='ru', chapters=[[0, '01'], [800, '02']], align_against=[f'{CODE}_{PREV}.words.json'],
                film='синтетический фильм-фикстура про пекарню (людей и организаций из жизни в нём нет)',
                doc_id='', tab_title=f'ТЗ монтажёру · {CUT}', materials_id='', shots_remote='',
                ctl_dir=str(Path(tmp) / 'ctl'),
                risk_patterns=[dict(key='names', rx='фамили', topic='фамилии и имена')])
    if prev_pravki:
        card['prev_pravki'] = f'{PREV}_review/pravki_{PREV}.json'
    _dump(rv / 'review_card.json', card)
    _dump(rv / f'{PREV}_review' / f'pravki_{PREV}.json', {'all': PREV_ITEMS})
    _dump(rv / 'pravki' / 'pravki_v2.json', {'all': CUR_ITEMS})
    segs = [dict(id=i, start=float(i * STEP), end=float(i * STEP + 12), text=t, speaker='Speaker 1') for i, t in enumerate(SPEECH)]
    _dump(rv / f'{CODE}_{CUT}.words.json', dict(title=CODE, language='ru', duration_sec=DURATION, n_segments=len(segs), segments=segs))
    _dump(rv / f'{CODE}_{PREV}.words.json', dict(title=CODE, language='ru', duration_sec=OLD_DURATION, segments=[]))
    base = dict(file=f'{CODE}_{PREV}.words.json', kind='words', coverage_pct=98.0, covered_sec=1540.0, spans=2,
                cut_map=[dict(cut_t0=0.0, cut_t1=20.0, base_t0=0.0, base_t1=20.0, words=30, tag=f'{CODE}_{PREV}.words', text=''),
                         dict(cut_t0=20.0 + SHIFT, cut_t1=1540.0 + SHIFT, base_t0=20.0, base_t1=1540.0, words=400,
                              tag=f'{CODE}_{PREV}.words', text='')],
                moved=[], unused=[],
                new=[dict(t0=20.0, t1=20.0 + SHIFT, sec=SHIFT, words=30, text=SPEECH[1])])
    _dump(w / 'align.json', dict(cut=f'{CODE}_{CUT}.words.json', bases={f'{CODE}_{PREV}': base}))
    _dump(w / 'screens_v6.json', [dict(id=s['id'], t0=s['t0'], t1=s['t1'], dur=s['t1'] - s['t0'] + 1, tc=s['tc'],
                                       chapter='01' if s['t0'] < 800 else '02', best_sec=s['t0'],
                                       best_frame=f'h{s["t0"] + 1:04d}.jpg', text_best=s['text'], texts_all=[s['text']])
                                  for s in SCREENS])
    (w / 'vlm_v6.jsonl').write_text(''.join(json.dumps(dict(id=v['id'], t0=v['t0'], best_frame=f'h{v["t0"] + 1:04d}.jpg',
                                                            vlm_text=next(s['text'] for s in SCREENS if s['id'] == v['id']),
                                                            vlm_desc=v['desc']), ensure_ascii=False) + '\n' for v in VLM),
                                    encoding='utf-8')
    _dump(w / 'structure_checks.json', dict(schema='structure-checks-v1', code=CODE, cut_version=CUT, rules_from='fixture', checks=[
        dict(rule='fund_entry_min', status='fail', ok=False, value=4.0, threshold=17, tc='4:00', speaker='Speaker 1',
             detail='первое упоминание фонда на 4:00'),
        dict(rule='last_sound_rule', status='pass', ok=True, detail='последним звучит герой')]))
    _dump(rv / 'cloud_canned.json', CANNED)
    return rv


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(build(sys.argv[1]))
