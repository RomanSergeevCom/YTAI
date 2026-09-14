#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Review_v4_full: смотровой таймлайн YTCH12 — рендер v4 ЦЕЛИКОМ (ничего не вырезано,
ничего не переставлено), V1/A1 в блоках по границам 23 смысловых глав (стык-в-стык,
только для навигации; карточек глав в кате нет), chapter-span маркеры с названиями глав.
База — лайт-версия 4K (кадр-в-кадр с мастером montage_1, 76137 кадров, HEVC 8 Мбит/с).
Главы: chapters_cards.json (цвет-подсказка и ⚠️-комментарий — из вердикта ревью).
Образец: YTCH11 make_review_v2_full.py. Канон хранения (07.09): 05_Review/{CODE}_review_*.json."""
import json
import subprocess
from datetime import datetime
from pathlib import Path

M = Path(__file__).parent
PROJECT = Path('/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta')
RENDER = Path('/Volumes/T9-Black-RYA/YTCH/YTCH12_Sveta/03_Exports/YTCH12_v4_light_4K.mp4')
OUTD = PROJECT / '00_Setup/05_Review'

dur = float(subprocess.run(
    ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
     'stream=duration', '-of', 'csv=p=0', str(RENDER)],
    capture_output=True, text=True, check=True).stdout.strip())
chapters = json.loads((M / 'chapters_cards.json').read_text())
chapters.sort(key=lambda c: c['tc_sec'])
markers = [{k: c[k] for k in ('tc_sec', 'name', 'comment', 'duration_sec', 'color')} for c in chapters]

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
off_grid = [x['timeline_in_sec'] for x in bs if abs(x['timeline_in_sec'] * 25 - round(x['timeline_in_sec'] * 25)) > 1e-6]
assert not off_grid, f'границы не на сетке 25p: {off_grid}'
print(f'покрытие: 0 → {dur:.2f}s ({int(dur // 60)}:{int(dur % 60):02d}), '
      f'блоков: {len(bs)}, дыр нет, сетка 25p')

out = {
    'schema': 'ytai-part-v1',
    'part': {
        'code': 'YTCH12',
        'project_name': 'YTCH12_Sveta',
        'name': 'Review_v4_full',
        'stage': 'Review',
        'fps': 25.0,
        'sequence_name': 'YTCH12_5_Review_v4_full',
        'build_model': 'review_cut',
        'seed_clip': '',
        'base_clip': RENDER.name,
        'base_clip_path': str(RENDER),
        'base_segments': bs,
        'chapter_markers': markers,
        'markers': False,
        'bin': '05_Review',
        'note': 'Смотровой таймлайн: монтаж v4 (montage_1 от 09.09) целиком, ничего не '
                'вырезано и не переставлено. База — лайт 4K (кадр-в-кадр с мастером). V1 разбит '
                'по границам 23 смысловых глав (цвет = подсказка: Green ок / Yellow правки / '
                'Red серьёзно), маркеры глав со span-длительностью и ⚠️-правками. Вставок нет.',
        'created': datetime.now().isoformat(timespec='minutes'),
    },
    'segments': [],
    'tracks': 'V1/A1 = рендер (кат свободный) · V2/A2 = визуальные вставки (Cyan) '
              '· V3/A3 = речь исходников (Yellow)',
    'audio_policy': 'keep_audio у всех; аудио вставок на A2/A3, голос рендера на '
                    'A1 не трогается (builder никогда не пишет в A1)',
    'required_imports': [],
    'counts': {'base_segments': len(bs), 'segments': 0, 'chapter_markers': len(markers)},
}
dst = OUTD / 'YTCH12_review_v4_full.json'
dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
print('→', dst)

lines = ['# YTCH12_review_v4_full — summary', '',
         f'Создан: {out["part"]["created"]} · рендер: {RENDER.name} '
         f'({dur:.2f}s = {int(dur // 60)}:{int(dur % 60):02d}, 25p, 3840×2160 лайт)',
         f'Блоков: {len(bs)} (стык-в-стык, покрытие полное, БЕЗ разрезов контента — границы '
         f'только по смысловым главам) · вставок: 0 · маркеров глав: {len(markers)}', '',
         'Сборка: панель UXP, вкладка Review → пикер → «YTCH12_review_v4_full». Медиа: только '
         'лайт-рендер v4, диск T9-Black. После Build проверить лог: '
         f'«V1 rebuilt from {len(bs)} render segment(s)» (при несмонтированном T9 билд молча '
         'деградирует в overlay).', '',
         '| # | TC | Глава | Цвет | ⚠️ |', '|---|----|-------|------|----|']
for i, ch in enumerate(chapters, 1):
    t = int(ch['tc_sec'])
    lines.append(f"| {i} | {t // 60}:{t % 60:02d} | {ch['name']} | {ch['color']} | "
                 f"{ch.get('comment', '').replace('|', '/')} |")
(OUTD / 'YTCH12_review_v4_full_summary.md').write_text('\n'.join(lines) + '\n')
print('→', OUTD / 'YTCH12_review_v4_full_summary.md')
