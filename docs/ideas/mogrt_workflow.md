# MOGRT вместо PNG Screen Cues

Переход от статичных PNG-оверлеев к редактируемым Motion Graphics Templates.

---

## Текущий workflow (PNG)

```
Python (generate_screen_cues.py)
  → читает brief JSON (screens[])
  → генерирует PNG для каждого screen type
  → сохраняет в screen_cues/ папку

UXP Plugin (screenBuilder.js)
  → импортирует PNG файлы в Premiere
  → вставляет на V2 поверх Assembly
  → добавляет маркеры
```

**Минусы:**
- Текст нельзя редактировать в Premiere (нужна перегенерация)
- Нет анимации (появление, затухание)
- Зависимость от Python + шрифтов на машине
- Отдельный шаг в пайплайне

---

## Новый workflow (MOGRT)

```
After Effects (один раз)
  → создать 5 шаблонов .mogrt
  → параметризовать через Essential Graphics Panel

UXP Plugin (screenBuilder.js)
  → вставить .mogrt на V2
  → программно задать текст, цвет, длительность
  → переходы и анимация уже встроены в шаблон
```

**Плюсы:**
- Текст редактируется прямо в Premiere (Essential Graphics панель)
- Встроенная анимация (fade-in, slide, bounce)
- Один workflow (без Python)
- Шаблоны обновляются централизованно

---

## Как подготовить MOGRT шаблоны

### Шаг 1: Создать композицию в After Effects

Для каждого из 5 типов экранов создать отдельную AE-композицию:

| Тип | Размер | Описание |
|---|---|---|
| `full_overlay` | 3840×2160 | Полноэкранный градиент, текст по центру |
| `half_overlay` | 3840×2160 | Градиент левая половина, текст слева |
| `three_fifths_overlay` | 3840×2160 | Градиент 3/5 слева, текст слева |
| `chapter_bar` | 3840×2160 | Плашка снизу по центру |
| `lower_third` | 3840×2160 | Скруглённая плашка, нижняя треть |

**Важно:**
- Фон = прозрачный (Alpha канал)
- Все композиции 3840×2160 (UHD) — масштабируются автоматически
- Длительность = 10 секунд (default, подрезается в Premiere)

### Шаг 2: Параметризовать в Essential Graphics Panel

В After Effects → Window → Essential Graphics:

1. Перетащить текстовый слой → **Source Text** → "Title"
2. Перетащить подзаголовок → **Source Text** → "Subtitle" (если есть)
3. Цвет градиента → **Color** → "Background Color"
4. Opacity градиента → **Slider** → "Background Opacity"
5. Анимация → встроить в AE (In/Out keyframes)

**Рекомендуемые параметры для каждого шаблона:**

```
Общие:
  - Title (text)           — основной текст
  - Subtitle (text)        — подзаголовок (опционально)
  - Background Color       — цвет фона/градиента
  - Background Opacity     — прозрачность фона (0-100)
  - Text Color             — цвет текста

Опциональные:
  - Duration In (slider)   — длительность появления (frames)
  - Duration Out (slider)  — длительность исчезновения (frames)
  - Font Size (slider)     — размер шрифта
```

### Шаг 3: Экспорт .mogrt

After Effects → File → Export → Motion Graphics Template (.mogrt)

- Сохранить в папку проекта: `scripts/05_editing/0500_uxp/assets/mogrt/`
- Именование: `ytai_full_overlay.mogrt`, `ytai_chapter_bar.mogrt` и т.д.

### Шаг 4: UXP интеграция

```js
// Вставить MOGRT на V2
const mogrtPath = pluginFolder + '/assets/mogrt/ytai_full_overlay.mogrt';
const insertTime = new ppro.TickTime();
insertTime.setSecondsAsFraction(segmentStartSec);

// API для вставки MOGRT
sequence.createInsertMOGRTAction(
  mogrtPath,
  insertTime,
  1,  // video track index (V2)
  screen.title  // параметры
);
```

**Примечание:** Точный API для установки параметров MOGRT через UXP нужно проверить в документации. Возможно через `ComponentParam` после вставки.

---

## Альтернатива: MOGRT в Premiere Pro (без AE)

Для простых шаблонов (плашки с текстом) можно создать прямо в Premiere:

1. Graphics → New Layer → Rectangle / Text
2. Настроить дизайн в Program Monitor
3. Graphics → Export as Motion Graphics Template

**Ограничения:**
- Нет сложных анимаций (только simple fade)
- Нет выражений (expressions)
- Подходит для `chapter_bar` и `lower_third`

**Для `full_overlay` и сложных шаблонов — только через AE.**

---

## Структура файлов после перехода

```
scripts/05_editing/0500_uxp/
├── assets/
│   └── mogrt/
│       ├── ytai_full_overlay.mogrt
│       ├── ytai_half_overlay.mogrt
│       ├── ytai_three_fifths_overlay.mogrt
│       ├── ytai_chapter_bar.mogrt
│       └── ytai_lower_third.mogrt
└── src/
    └── screens/
        ├── screenBuilder.js    ← адаптировать: MOGRT вместо PNG
        └── screenParser.js     ← без изменений
```

---

## План перехода

1. **Подготовить шаблоны** — создать 5 .mogrt в AE (или начать с 2 простых в Premiere)
2. **Протестировать вручную** — вставить .mogrt в Premiere, проверить параметры
3. **Адаптировать screenBuilder.js** — заменить PNG import на MOGRT insert
4. **Убрать Python генерацию** — `generate_screen_cues.py` становится legacy
5. **Документировать** — как обновлять/создавать новые шаблоны

**Рекомендация:** Начать с `chapter_bar` (самый простой) — создать в Premiere Pro, проверить UXP API, потом перейти к сложным шаблонам через AE.
