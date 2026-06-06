# ytuvi_companion_builder

Собирает **страницы-компаньоны для съёмки** по каждому видео YTUVI — то, что
Наталья Тузова (ген. директор UVI) и ведущие (Анастасия Атрашкевич, Юля) читают
прямо на площадке. На одной странице сведено всё по выпуску:

1. **Полный сценарий** (3-колоночная таблица: № / текст озвучки / монтаж) — то,
   что произносит ведущий, без сокращений.
2. **Факт-чек + комментарии** — по каждому утверждению вердикт (✅ проверено /
   ⚠️ уточнить / ❌ ошибка / 🎭 метафора / ❔ не подтверждено), пояснение,
   как правильно, ссылки на источники. Делается multi-agent факт-чек workflow.
3. **Шпаргалка** — что проверить перед камерой · что НЕ говорить как факт ·
   где нужна экспертная вставка Натальи (бизнес/инвест-угол = её USP).
4. **Глоссарий с произношением** + **прошлые источники** (цитаты эксперта с kickoff).

Self-contained HTML, тёмная/светлая тема (свет — для яркой студии), фильтр
«только блоки с проверками». Дизайн наследует портал yt.rya.ae (палитра 04).

## Pipeline (два шага)

```bash
# 1) multi-agent fetch + adversarial факт-чек → JSON в /tmp/ytuvi_build/{parsed,annotations}/
#    (запускается через Workflow tool: /tmp/ytuvi_build/wf_companion.js)

# 2) сборка страниц из JSON
python3 ~/YTAI/scripts/999_extra/ytuvi_companion_builder/build_companion.py \
  --codes 01,02,03,04,05
```

Выход: `<portal>/ytuvi/<NN>/index.html` (по умолчанию
`/Users/romansergeev/RYA/yt-rya-ae/web/ytuvi/<NN>/`).

## Входные данные (контракты JSON)

- `/tmp/ytuvi_build/parsed/<NN>_blocks.json` — распарсенный сценарий:
  `{code,title,subtitle,legend,blocks:[{idx,n,type:chapter|vo|note,chapter,vo,visual,onscreen[]}]}`
- `/tmp/ytuvi_build/annotations/<NN>.json` — аннотации:
  `{factchecks:[{block_idx,claim,verdict,confidence,note,correction,sources[]}],`
  `glossary:[{term,pron,meaning}], metaphors:[{block_idx,text,note}],`
  `expert_points:[{block_idx,note}], sources_map:[{topic,quote,who,tc}],`
  `cheatsheet:{must_check[],dont_assert[],expert_authority[]}}`

Если `annotations/<NN>.json` нет — страница соберётся только из скрипта (без
факт-чека). Если нет и `blocks.json` (напр. 05 Шпинель — сценария ещё нет) —
рендерится prep-заглушка со статусом.

## Источник истины

Скрипты живут в Google Docs (владелец `gaidstorm@`), список — в таблице
**YTUVI ContentList**
(`1yPVg3MvXglANpmigtmS_vOSDGOIwMGn7x1QQGEeXSo8`). Их id зашиты в `wf_companion.js`
и в `META` этого билдера. Обновился скрипт → перезапустить workflow (пере-fetch +
пере-факт-чек) → пересобрать страницы.

## Re-run policy

1. Сценарист обновил Google Doc → workflow заново тянет скрипт и факт-чекает.
2. Появился сценарий 05 (Шпинель) → добавить в `VIDEOS` (wf) и пересобрать.
3. Меняется дизайн/верстка → правка только в `build_companion.py`, JSON не трогаем.
