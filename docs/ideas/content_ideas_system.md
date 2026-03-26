# Система сбора идей и мониторинга конкурентов

## Что это

Локальная система для управления идеями видео и отслеживания конкурентов по 4 каналам (YTCR, YTCG, YTRF, YTXX). Основана на Obsidian — программа для работы с заметками в формате markdown.

Всё хранится как файлы на Mac. Никаких серверов, баз данных, облаков.

---

## Зачем

Идеи теряются: в голове, в заметках телефона, в Telegram. Нет единого места где видно:
- Все идеи по каждому каналу
- На каком этапе каждая идея (только придумал / исследую / готов снимать)
- Что снимают конкуренты и что у них залетает
- Какие темы сейчас в тренде в нише

---

## Как работает

### Идеи

Каждая идея — отдельный файл. В начале файла — карточка с полями:
- Канал (YTCR / YTCG / YTRF)
- Статус (inbox → research → concept → scripted → planned → filming → published)
- Приоритет (1-10)
- Формат (интервью / туториал / влог / обзор рынка / shorts)
- Теги (golden_visa, roi, broker_life...)
- Длительность

Дальше — свободный текст: концепт, ключевые тезисы, варианты hook, идеи для B-roll.

Идею можно создать:
- Вручную в Obsidian (из шаблона, 10 секунд)
- Через Claude Code ("запиши идею для YTCR: ..." — скрипт создаст файл)
- Голосом (надиктовал → Whisper транскрибировал → Claude структурировал → файл)

### Анализ чужих видео

Видишь интересное видео на YouTube → кидаешь ссылку в Claude Code → скрипт:
1. Скачивает метаданные (title, views, duration, description)
2. Скачивает субтитры (автоматические)
3. Claude анализирует: какой hook, какая структура, почему набрало просмотры
4. Генерирует идеи для твоих каналов на основе этого видео
5. Сохраняет как файл в vault

### Мониторинг конкурентов

Добавляешь YouTube-канал конкурента → скрипт:
1. Раз в день проверяет новые видео через YouTube Data API
2. Считает "залётность": просмотры vs среднее по каналу
3. Если видео набирает в 2+ раза больше обычного — помечает как outlier
4. Раз в неделю — дайджест: топ видео конкурентов, trending topics, рекомендации

### Дашборды в Obsidian

- **Pipeline по каналу** — таблица всех идей, сгруппированных по статусу
- **Competitor Pulse** — видео конкурентов, отсортированные по залётности
- **Weekly Review** — что нового за неделю
- **Kanban доска** — визуальные карточки, перетаскиваешь между колонками

---

## Структура

### Obsidian vault (~/YTAI_Ideas/)

```
Ideas/          — идеи для видео, по папкам каналов (YTCR/, YTCG/, YTRF/)
Research/       — анализы чужих видео
Competitors/    — каналы конкурентов и их видео
Trends/         — еженедельные дайджесты
Channels/       — профили твоих каналов (копии из YTs/)
Dashboards/     — страницы с таблицами и фильтрами
Templates/      — шаблоны для быстрого создания заметок
```

### Python скрипты (scripts/09_ideas/)

```
add_idea.py              — текст/голос → файл идеи в vault
analyze_video.py         — YouTube URL → файл анализа в vault
add_competitor.py        — YouTube канал → начать мониторинг
monitor_competitors.py   — проверить все каналы (cron или вручную)
generate_digest.py       — собрать еженедельный дайджест
lib/vault.py             — чтение/запись markdown файлов с метаданными
lib/youtube.py           — yt-dlp + YouTube Data API
lib/claude_api.py        — Claude API для анализа
```

---

## Технологии

| Компонент | Что делает |
|-----------|------------|
| Obsidian | Просмотр, редактирование, дашборды, Kanban |
| Markdown + YAML | Формат хранения (просто текстовые файлы) |
| Dataview (плагин) | Таблицы и фильтры по полям файлов |
| Kanban (плагин) | Визуальная доска со столбцами |
| Templater (плагин) | Шаблоны для быстрого создания |
| Claude Code | Интерфейс для добавления идей и анализа видео |
| Claude API | Структурирование идей, анализ видео, дайджесты |
| yt-dlp | Метаданные и субтитры YouTube видео |
| YouTube Data API v3 | Поиск новых видео конкурентов (10K запросов/день бесплатно) |
| Whisper | Транскрипция голосовых заметок |
| iCloud | Синхронизация vault между Mac и iPhone |

---

## Почему Obsidian

1. **Файловый подход** — как весь YTAI (JSON, markdown, скрипты). Никакой новой парадигмы.
2. **Нуль инфраструктуры** — нет Docker, Postgres, n8n, серверов. Скачал → работаешь.
3. **Граф связей** — видишь как идеи связаны с видео конкурентов и трендами.
4. **Offline + sync** — iCloud между Mac и iPhone. Работает без интернета.
5. **Claude Code** — уже используется для Assembly briefs. Естественное расширение.
6. **Файлы навсегда** — если Obsidian исчезнет, файлы останутся. Это просто текст.

### Почему не другое:
- **n8n + Postgres (SPRUT):** Мощно, но 3 сервиса надо поддерживать. Overengineering для 1 человека.
- **Notion/Airtable:** Облако, vendor lock-in, нет интеграции с YTAI.
- **SQLite + CLI:** Нет визуализации, нет графа, нет Kanban.
- **Telegram bot:** Хорош для capture, плох для review и планирования.

---

## Этапы реализации

### 1. Obsidian + структура (30 мин)
Установить Obsidian, создать vault, плагины, шаблоны, дашборды.
Вручную добавить несколько идей, проверить что отображаются.

### 2. Добавление идей через Claude Code (2-3 часа)
Скрипт `add_idea.py`: говоришь Claude Code что за идея → файл в vault.

### 3. Анализ видео по ссылке (2-3 часа)
Скрипт `analyze_video.py`: YouTube URL → анализ формата, hook, структуры → файл в vault.

### 4. Мониторинг конкурентов (3-4 часа)
Скрипты `add_competitor.py` + `monitor_competitors.py`: добавляешь каналы, ежедневная проверка новых видео, outlier detection.

### 5. Автоматизация + дайджесты (1-2 часа)
Cron на Mac для ежедневного мониторинга. Еженедельный дайджест с трендами.

### 6. Связь с YTAI pipeline (1 час)
Идея → статус "filming" → project_code (YTCR03) → папка проекта.

---

## Пример файла идеи

```markdown
---
type: idea
id: YTCR-001
channel: YTCR
pillar: "Investor Education"
status: inbox
priority: 8
format: tutorial
target_duration: "15-20 min"
tags: [golden_visa, roi, investment]
source: text
created: 2026-03-25
---

# Golden Visa ROI: Real Numbers from 5 Investors

## Concept
Взять 5 реальных инвесторов Core Realty, показать их ROI за 1-3 года.
Конкретные цифры: вложили X → получили Y → доходность Z%.

## Key Points
- Минимальный порог 2M AED
- Off-plan vs ready ROI
- Скрытые расходы (DLD fee, service charges)
- Реальные кейсы

## Hook Ideas
- "I asked 5 Golden Visa investors: was it worth it?"
- "The real ROI nobody talks about"
```

## Пример файла анализа видео

```markdown
---
type: video_analysis
url: "https://youtube.com/watch?v=abc123"
title: "How Dubai Brokers Make 1M AED"
channel_name: "@DubaiPropertyKing"
views: 45000
duration: "18:32"
hook_type: story
format: tutorial
topics: [broker_income, commission, success_story]
performance: outlier
analyzed: 2026-03-25
---

# How Dubai Brokers Make 1M AED

## Analysis
**Hook:** Personal story — "3 years ago I was broke, now..."
**Structure:** Hook → Background → 5 income sources → Action steps → CTA
**Pacing:** Fast, lots of cuts, numbers on screen

## What Worked
- Specific numbers in title (not "a lot" but "1M AED")
- 45K views for 12K subs = 3.75x ratio (OUTLIER)

## Ideas This Inspires
- [[YTCR-001 Golden Visa ROI]] — similar format but with REAL client data
```

---

Дата: 2026-03-25
