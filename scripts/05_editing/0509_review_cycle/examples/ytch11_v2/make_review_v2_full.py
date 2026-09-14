#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Review_v2_full: смотровой таймлайн YTCH11 — рендер v2 ЦЕЛИКОМ (ничего не
вырезано, ничего не переставлено), V1/A1 в блоках по границам 15 глав-карточек
(стык-в-стык, только для навигации), chapter-span маркеры с названиями глав.
Главы: chapters_cards.json (карточки из OCR s2_ocr + Тизер с 0:00).
Образец: YTUVI01 make_review_v1_full.py / YTUVI01_part_Review_v1_full.json."""
import json
import subprocess
from datetime import datetime
from pathlib import Path

M = Path(__file__).parent
PROJECT = Path('/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik')
RENDER = PROJECT / '03_Exports/YTCH11_v2_Liza_Vitalik.mp4'
PARTS = PROJECT / '00_Setup/02_Assembly/parts'
PARTS.mkdir(parents=True, exist_ok=True)

dur = float(subprocess.run(
    ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
     'stream=duration', '-of', 'csv=p=0', str(RENDER)],
    capture_output=True, text=True, check=True).stdout.strip())
chapters = json.loads((M / 'chapters_cards.json').read_text())
chapters.sort(key=lambda c: c['tc_sec'])

# блоки = границы глав, стык-в-стык, покрытие 0 → конец рендера
bs = []
for i, ch in enumerate(chapters):
    a = ch['tc_sec']
    b = chapters[i + 1]['tc_sec'] if i + 1 < len(chapters) else dur
    bs.append({'seg_id': f'b{i:02d}', 'source_in_sec': a, 'source_out_sec': b,
               'timeline_in_sec': a, 'timeline_out_sec': b,
               'color': ch.get('color', 'Green')})
gaps = [(x['timeline_out_sec'], y['timeline_in_sec']) for x, y in zip(bs, bs[1:])
        if abs(y['timeline_in_sec'] - x['timeline_out_sec']) > 0.02]
assert not gaps, f'дыры между блоками: {gaps}'
assert bs[0]['timeline_in_sec'] == 0.0, 'первый блок не с нуля'
assert abs(bs[-1]['timeline_out_sec'] - dur) < 0.02, 'последний блок не до конца'
print(f'покрытие: 0 → {dur:.2f}s ({int(dur // 60)}:{int(dur % 60):02d}), '
      f'блоков: {len(bs)}, дыр нет')

out = {
    'schema': 'ytai-part-v1',
    'part': {
        'code': 'YTCH11',
        'project_name': 'YTCH11_Liza_Vitalik',
        'name': 'Review_v2_full',
        'stage': 'Review',
        'fps': 25.0,
        'sequence_name': 'YTCH11_5_Review_v2_full',
        'build_model': 'review_cut',
        'seed_clip': '',
        'base_clip': RENDER.name,
        'base_clip_path': str(RENDER),
        'base_segments': bs,
        'chapter_markers': chapters,
        'markers': False,
        'bin': '05_Review',
        'note': 'Смотровой таймлайн: рендер v2 целиком, ничего не вырезано и не '
                'переставлено. V1 разбит по границам 15 глав-карточек (цвет = '
                'подсказка: Green ок / Yellow правки / Red разбить), маркеры глав '
                'со span-длительностью. Вставок нет — только отсмотр и навигация.',
        'created': datetime.now().isoformat(timespec='minutes'),
    },
    'segments': [],
    'tracks': 'V1/A1 = рендер (кат свободный) · V2/A2 = визуальные вставки (Cyan) '
              '· V3/A3 = речь исходников (Yellow)',
    'audio_policy': 'keep_audio у всех; аудио вставок на A2/A3, голос рендера на '
                    'A1 не трогается (builder никогда не пишет в A1)',
    'required_imports': [],
    'counts': {'base_segments': len(bs), 'segments': 0,
               'chapter_markers': len(chapters)},
}
dst = PARTS / 'YTCH11_part_Review_v2_full.json'
dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
print('→', dst)

lines = [f'# YTCH11_part_Review_v2_full — summary',
         '',
         f'Создан: {out["part"]["created"]} · рендер: {RENDER.name} '
         f'({dur:.1f}s = {int(dur // 60)}:{int(dur % 60):02d}, 25p)',
         f'Блоков: {len(bs)} (стык-в-стык, покрытие полное, БЕЗ разрезов контента '
         '— границы только по карточкам глав) · вставок: 0 · маркеров глав: '
         f'{len(chapters)}',
         '',
         'Сборка: панель v2.16.1+, вкладка Review → пикер. Медиа: только рендер '
         'v2, диск T7-Beige. После Build проверить лог: '
         f'«V1 rebuilt from {len(bs)} render segment(s)».',
         '',
         '| # | TC | Глава | Цвет |',
         '|---|----|-------|------|']
for i, ch in enumerate(chapters, 1):
    t = int(ch['tc_sec'])
    lines.append(f"| {i} | {t // 60}:{t % 60:02d} | {ch['name']} | {ch['color']} |")
(PARTS / 'YTCH11_part_Review_v2_full_summary.md').write_text('\n'.join(lines) + '\n')
print('→', PARTS / 'YTCH11_part_Review_v2_full_summary.md')
print('маркеров глав:', len(chapters), '| base_clip:', RENDER.name,
      '| created:', out['part']['created'])
