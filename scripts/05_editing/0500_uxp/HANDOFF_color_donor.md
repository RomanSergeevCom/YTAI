# HANDOFF · Цвет на таймлайн: проявка и look через донор, экспозиция на клоне

Для новой сессии, 25.09.2026. Файл самодостаточный. За хроникой — `HANDOFF_uxp_audit.md`
(панель, аудит закрыт, v2.29.2) и `~/YTAI/scripts/15_color/HANDOFF_color_system.md` (слой цвета, §7).

## Фраза для старта новой сессии

> Читай целиком ~/YTAI/scripts/05_editing/0500_uxp/HANDOFF_color_donor.md. Задача — чтобы
> выбранные в витрине луты легли на клипы в Premiere. Начни с шага 1: собери пробу донора
> и пришли мне инструкцию на 15 минут в Premiere.

## Где смотреть

| что | где |
|---|---|
| Панель UXP (код, тесты) | ~/YTAI/scripts/05_editing/0500_uxp/ |
| Кнопки Apply Color / Active Only | index.js `runColorFromPlan` :2829, привязки :12751–12752 |
| Запись параметра с чтением обратно | src/adjust/paramWrite.js (единственная — контракт-тест) |
| Цвет по индексу, дамп Lumetri | src/adjust/colorApply.js (`dumpComponentParams` :28, `setNamedSlot` :113, `applyColorToClip` :154) |
| Донор-путь поколения 1 (доказан на живой) | src/adjust/adjustmentBuilder.js: `addAdjustmentPerClipFromPlan` :646, `removeLayerItem` :936, `LUT_DONOR_SEQUENCE`/`LUT_DONOR_CLIPS` :975–978, `buildLutDonorSequence` :1012, `ensureLutDonorSequence` :1192, `probeDonorClone` :1300 |
| Раннеры поколения 1 (кнопки сняты 25.09, код жив) | index.js `runAdjustPerClipFromPlan` :2951, `runAdjustBuildDonor` :3047, `runAdjustProbeClone` :3097 |
| Донор-шаблон (один на все каналы — хардкод) | ~/YTAI/scripts/01_prepare/0101_init_folders/RYA_example.prproj, секвенция `YTAI_LUT_DONOR`; путь зашит в index.js :2988, :3058, :3108 |
| Слой цвета | ~/YTAI/scripts/15_color/ (README.md, HANDOFF_color_system.md) |
| Витрина YTEVO03 v37 (пересобрана 25.09) | file:///Volumes/T7-Beige-RYA/YTEVO/YTEVO03_Plechko_day/01_Source/00_LUT/_build/YTEVO03_lut_board.html |
| План YTEVO03 | /Volumes/T7-Beige-RYA/YTEVO/YTEVO03_Plechko_day/01_Source/00_LUT/_build/YTEVO03_color_plan.json |
| План YTUVIE01 | /Volumes/T7-Beige-RYA/YTUVIE-Folder/YTUVIE-Projects/YTUVIE01_Kickoff_Setup/01_Source/00_LUT/_build/YTUVIE01_color_plan.json |
| Кубы, которые видит Premiere | ~/Library/Application Support/Adobe/Common/LUTs/Input/YTAI (проявка) и …/Creative/YTAI (look) |
| Лог цвета после прогона | {проект}/99_Pipeline/logs/adjust_last.log |
| KB | yt.rya.ae/kb/luts/ (3.8), yt.rya.ae/kb/uxp-panel/ (4.7) |

## Контекст: что такое цвет в YTAI и где он рвётся

Цвет — три ступени, а не один куб (решение 22.09). Проявка — по камере и гамме,
look — один на канал (ДНК), экспозиция — число по каждому клипу, между ними:

```
клип (log) ─► Input LUT ─► Linearize ─► Exposure ─► Look ─► Rec.709
              проявка       гамма 2.4    стопы      ДНК канала
              └──────── Basic Correction ────────┘  └ Creative ┘
                         ОДИН Lumetri
```

Витрина → выбор → план работают и проверены 25.09. Рвётся последний шаг:

```
витрина ─► {CODE}_color_choice.json ─► color_apply.py ─► {CODE}_color_plan.json ─► панель Apply Color
   ✅              ✅                        ✅                     ✅                      │
                                                                                         ▼
                                                                          Lumetri НА КЛИПЕ
                                                          Exposure  [19]    ✅ ставится
                                                          Input LUT [6,7]   ✗ ─┐ числовое меню,
                                                          Look      [34,35] ✗ ─┘ куб живёт в Blob [0]
                                                          → «LUT+Look need donor»
```

Живое подтверждение — отчёт «Err» Романа, 25.09, панель v2.29.2, YTUVIE01:

```
[2026-09-25 17:21:51] [WARN] color: Input LUT и Look — числовые меню Lumetri, куб живёт в Blob;
                             значением они не ставятся ни в какой форме. Нужен донор-клон.  [color]
```

### Что доказано на живой Premiere

| дата | факт | где |
|---|---|---|
| 18.08 | клон adjustment layer из секвенции-донора в другую секвенцию работает: `CLONE OK`, Lumetri на клоне сохранился, **Look приехал** | YTCH13, `probeDonorClone`, `createCloneTrackItemAction` |
| 18.08 | слой над КАЖДЫМ клипом, клон-режим, точный трим, повтор = дозаполнить | YTCH13, 26/26, `addAdjustmentPerClipFromPlan` |
| 25.09 | дамп Lumetri: [0] Blob · [6][7] Input LUT = число 0 · [19] Exposure · [34][35] Look = число 0 | YTUVIE01 |
| 25.09 | Exposure: мутация `getStartValue()` коммитится и НЕ применяется (10/10), `createKeyframe` применяется | YTUVIE01, 10 клипов |
| 25.09 | Input LUT и Look значением не ставятся ничем — только донор | тикет `13_preprod/TICKET_uxp_audit.md`, пункт I |

### Чего никто не проверял

- везёт ли клон донора **Input LUT** (Look — да, 18.08; Input LUT лежит в том же Blob);
- ставится ли **Exposure на Lumetri клона** слоя (на клипе — да);
- множитель **стоп витрины → стоп Lumetri = 2,4** выведен из блоба шаблона, не замерен
  (`exposure_verified_against_premiere: false` в плане). Инструмент замера
  `15_color/lumetri_gamma.py` написан другой сессией, не закоммичен; папка проб
  `YTUVIE01…/_build/_premiere_probe` создана 25.09 09:34 и пуста.

### Данные, на которых работать

| проект | клипов в плане | проявки | look | утверждён |
|---|---|---|---|---|
| YTEVO03 | 162 (+1 Rec.709 без проявки) | sony legacy — 101, dji minus — 61 | newstar | roman |
| YTUVIE01 | 49 | sony legacy, dji minus | malibu | roman |

Пример записи плана (ключ `сцена/клип.MP4`, панель матчит по имени файла):

```
"01_Morning_Run/RYA-FX3-1212.MP4": {"develop": "sony__slog3_sgamut3cine__rec709__neutral__legacy",
                                   "exposure": 1.2, "look": "look__newstar"}
```

`exposure` в плане — уже **стопы Lumetri** (×2,4 от витрины), в пределах ±7.
YTEVO03 по витрине: 0 — 60 клипов, +0,5 — 33, +1 — 40, +1,5 — 8, +2 — 3, +2,5 — 6, −0,5 — 11, −1 — 1.

## Предлагаемая схема

```
V4  ┌─ AL-клон «sony…legacy» ───────────────┐   ← над клипом, по его границам
    │  Lumetri: Input LUT = sony legacy      │     (руками ОДИН раз в доноре)
    │           Exposure  = +1.2  ← панель   │     (API, paramWrite, по плану)
    │           Look      = newstar          │     (руками ОДИН раз в доноре)
    └────────────────────────────────────────┘
V1  RYA-FX3-1212.MP4  (log, собственный Lumetri — БЕЗ цвета)
```

- Донор: секвенция с одним adjustment layer на каждую проявку плана (YTEVO: 2 слоя).
  Имя слоя = id проявки. Роман в каждом ОДИН раз выбирает Input LUT и Look руками.
- Apply Color: на каждый клип плана — клон слоя его проявки над клипом, трим по клипу,
  Exposure — на Lumetri клона. Порядок «проявка → экспозиция → look» тогда верен,
  и множитель 2,4 работает ровно там, где выведен.
- ⚠️ Экспозицию, которую Apply Color v2.26+ уже положил в Lumetri самих клипов,
  обнулить: иначе она сработает до проявки и сложится с экспозицией клона.

## Задачи

### Шаг 1. Проба донора (Роман, 15 минут в Premiere)

Три вопроса одним прогоном, до любой большой правки:

1. везёт ли клон донора и Input LUT, и Look;
2. ставится ли Exposure на Lumetri клона и читается ли обратно;
3. как ложится слой при многокамерной раскладке (см. риск ниже).

Как: вернуть кнопку пробы поколения 1 в виде «Probe Color Donor». Донор берётся из
плана (id проявок), а не из трёх зашитых имён `01_bright/02_normal/03_dark_scene`.
Проба клонирует слой донора над первым клипом плана в активной секвенции, ставит
Exposure из плана через `paramWrite`, дампит Lumetri клона ДО и ПОСЛЕ
(`colorApply.dumpComponentParams`) и пишет всё в `adjust_last.log`.

Норма: на клоне [6]/[7] и [34]/[35] сохраняют то, что выбрано в доноре (Blob [0]
совпадает с донором), [19] = значение плана ±1e-4, картинка — как на витрине.

Роман пишет «нажал» — лог читать самому с диска, ничего не пересылать.

### Шаг 2. Донор поколения 2

- `buildLutDonorSequence` / `ensureLutDonorSequence`: имена слоёв — из
  `develops` плана, не константа `LUT_DONOR_CLIPS` (:978).
- `validate()` требует все имена набора — ослабить до нужных прогону, иначе
  старый донор роняет проект в legacy (см. HANDOFF_color_system.md §7).
- Донор свой на канал (решено 22.09): убрать абсолютный путь `RYA_example.prproj`
  (:2988, :3058, :3108).

### Шаг 3. Apply Color поколения 2

- `runColorFromPlan`: если донор есть — путь `addAdjustmentPerClipFromPlan` в
  клон-режиме (план → `{имя клипа: id проявки}`), затем Exposure на каждом клоне
  через `paramWrite.writeParamVerified`; нет донора — нынешнее поведение
  (экспозиция на клипе + «need donor»).
- `opts.retireNames` — снять слои прошлого поколения, иначе `findExisting` их не
  найдёт и новые лягут поверх.
- Гард `approved`: план без `"approved": "roman"` панель не раскладывает.
- Обнулить экспозицию на Lumetri самих клипов (см. предупреждение выше).
- Статус: `Color: N/N clips · develop+look via donor · exposure read back N`.
  Ошибка — красная строка, в «Err» со стеком (канал уже есть).

### Шаг 4. Тесты и контракты

- Мок: `createCloneTrackItemAction` уже даёт клону КОПИЮ цепочки; дописать Blob в
  копию, чтобы тест видел «Input LUT/Look приехали».
- Тесты: слой на каждый клип плана, трим по клипу, Exposure на клоне = план,
  повтор ничего не дублирует, клип без проявки в плане (экран) не получает слоя.
- Каждая правка кода — бамп `src/shared/version.js`: гейт на коммите иначе не пустит.

### Шаг 5. Приёмка на живой (Роман)

YTUVIE01 (49 клипов), затем YTEVO03 (162): кадр в Premiere совпадает с витриной
на 3 клипах (светлый, тёмный, лицо), экран без цвета, `adjust_last.log` без ✗.

## Риск: слой красит всё, что под ним

Adjustment layer действует на все дорожки ниже в своём отрезке времени. Раскладка
YTUVIE01: V1 FX3 · V2 ZV-E1 · V3 запись экрана · V4 ролики. Слой для клипа V1,
лёгший выше V3, покрасит и запись экрана.

```
V5  AL(FX3)   ← покрасит ВСЁ ниже, включая экран ✗
V3  экран
V1  FX3
```

Поколение 1 кладёт слой на дорожку сразу над клипом (тест
`places one named layer per matched clip on the track above`), но случай
перекрытия камер в одно время не проверен. Проба шага 1 обязана это показать; решение
(дорожка слоя строго над своим клипом со вставкой дорожек, или слой только у верхнего
видимого клипа) — до шага 3.

## Команды

```
cd ~/YTAI/scripts/05_editing/0500_uxp
npm test                                   # линтер + 583 теста + контракты; тот же гейт — на коммите

cd ~/YTAI && .venv_ytai/bin/python -m pytest scripts/15_color/tests -q      # 236 тестов слоя цвета

# витрина (окружение с Vision; другие питоны без PIL/Vision):
~/YTAI/environment/.venv_vlm/bin/python3 ~/YTAI/scripts/15_color/1502_lut_pick/lut_board.py \
  --project "/Volumes/T7-Beige-RYA/YTEVO/YTEVO03_Plechko_day" --jobs 6

# план, сухой прогон (ничего не пишет):
.venv_ytai/bin/python scripts/15_color/1503_color_apply/color_apply.py \
  --project "/Volumes/T7-Beige-RYA/YTEVO/YTEVO03_Plechko_day"
```

## Критерии приёмки

- на клипах плана стоит слой проявки и look, картинка совпадает с витриной (3 клипа, глазами);
- Exposure на клоне = план ±1e-4 по чтению обратно, у каждого клипа;
- экспозиция на Lumetri самих клипов = 0;
- клипы без проявки (экран, Rec.709) без слоя;
- повторный прогон ничего не дублирует;
- неутверждённый план не раскладывается;
- `npm test` и тесты 15_color зелёные, версия панели поднята, «Err» без ошибок после прогона.

## Открытые вопросы и риски

- многокамерная раскладка и слой — см. раздел «Риск»;
- множитель 2,4 не замерен на живой (инструмент `lumetri_gamma.py` — у другой сессии);
- `manifest.json` `featureFlags {uncaughtException, unhandledRejection}` — решение Романа
  (слушатели в коде уже есть, v2.29.2);
- проект сохраняется и при провале сборки ingest — решение Романа;
- мелочь: время записей в «Err» — UTC без пометки (отчёт 17:22 при 20:22 по часам);
  показать местное с поясом;
- в `YTEVO03_color_choice.json` блок `stage.artifacts` указывает старый адрес витрины
  (T9, `00_Setup/01_Ingest`) — исправится при следующем сохранении выбора.

## Состояние репозитория (25.09.2026, вечер)

- ветка `feat/color-lut-system`, всё запушено; последние коммиты сессии: `db05a7e`
  (15_color: выбор со старой витрины — отказ), `fb8af34` / `10fbe9a` / `5801c9b` (панель
  v2.29.2: ревью, гейт на коммите);
- гейт на коммите установлен в этот клон (`tools/pre-commit.sh`): правка
  index.js / index.html / src/ без бампа версии — отказ; `npm test` обязан быть зелёным;
- ⚠️ в 15_color чужие незакоммиченные правки (`color_media.py`, `README.md`,
  `lumetri_gamma.py`) — не сгребать, коммитить только свои пути; перед работой —
  `git status` и время правки файлов.
