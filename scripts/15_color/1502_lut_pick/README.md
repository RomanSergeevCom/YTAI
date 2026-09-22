# lut_face_score.py — какой LUT на какой КЛИП (скоринг по лицу)

Локальный пайплайн (ffmpeg + Apple Vision, без облака): для КАЖДОГО клипа в
`01_Source/{NN_Scene}/` берёт 1-3 сэмпл-кадра (по длительности), прогоняет через
все `.cube` из `01_Source/00_LUT/`, находит лицо (VNDetectFaceRectanglesRequest),
меряет по центру лица яркость/насыщенность/пережог и выбирает LUT с максимально
ярким лицом без клиппинга. Вердикт и выбор в HTML — по каждому клипу отдельно.

KB: **3.8 Scene LUTs** https://yt.rya.ae/kb/luts/ (нумерация 21.09.2026; раньше — раздел 7 страницы /kb/ingest/).

```bash
source ~/YTAI/environment/.venv_vlm/bin/activate   # pyobjc Vision + numpy + Pillow
python3 lut_face_score.py --project "/Volumes/T7-Beige-RYA/YTCH/YTCH13_Kirill_2"
```

Выход в `00_Setup/01_Ingest/`:
- `{CODE}_lut_review.html` (+ `_files/`) — side-by-side для проверки глазами;
- `{CODE}_lut_plan.json` — `{"сцена/клип.MP4" → lut}` для UXP-этапа
  adjustment-слоёв (`src/adjust/adjustmentBuilder.js → addAdjustmentPerClipFromPlan` (слой на КАЖДЫЙ клип; `addAdjustmentOverRanges` — старый режим «один слой на диапазон»)).

Скоринг: `score = luma + 0.55·255·sat − 900·clip_share` (яркость доминирует,
пережог убивает). Лицо не нашлось → метрики по ВСЕМУ кадру; флаг `noface` ставится КЛИПУ, и только если лица нет ни в одном сэмпле (иначе `face_partial`).

Имена LUT'ов — по сцене, ДЛЯ которой сделаны (не по результату): `03_dark_scene.cube`
для тёмных сцен ОСВЕТЛЯЕТ, `01_bright_scene.cube` для ярких — давит света.
18.08.2026 (вечер) набор переименован в `{01_bright,02_normal,03_dark}_scene.cube`
(префикс группирует тройку в дропдауне Lumetri Look) везде: бандл панели
`0500_uxp/LUTs/`, оба шаблона YTAI_Folder_Templates, Creative-папка Adobe
(`~/Library/.../Creative/YTAI/`), YTCH13. Старые bright/normal/dark →
`scripts/05_editing/Archive/LUTs_pre_ytai_20260818/`. ⚠️ Lumetri Look ссылается
на ИМЯ файла — Look'и, выбранные до переименования, битые; панель мигрирует их
сама (LEGACY_LUT_ALIASES, клоны). Порядок в review-HTML: bright | normal | dark
(normal в центре).

HTML интерактивный: клик по карточке/чипу = выбор LUT'а на КЛИП (на сцену — только заметка); фидбек вливается штатно: `pbpaste | python3 lut_face_score.py --project … --feedback -` (предвыбран
фаворит счёта), поле заметки на сцену, кнопка «Скопировать фидбек» внизу отдаёт
JSON `{type: lut_feedback, choices, notes}` — вставить в чат Claude, тот обновит
`{CODE}_lut_plan.json`.
