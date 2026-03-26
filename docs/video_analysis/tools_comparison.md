# Tools Comparison — TouchDesigner vs Python Pipeline

## Вердикт

**Python pipeline** — единственный правильный выбор для batch-анализа видео архива и создания поисковой B-roll библиотеки. TouchDesigner и другие инструменты рассмотрены и отклонены по объективным причинам.

## TouchDesigner (derivative.ca)

### Что это
Node-based visual programming environment для real-time interactive multimedia:
- Live VJ performances (audio-reactive visuals на концертах)
- Immersive art installations (projection mapping, interactive exhibits)
- Real-time generative art (LED walls, stage design)
- Interactive experiences (body tracking → triggered visuals)

### CV-возможности (технически есть)
- OpenCV 4.5.2 встроен
- ONNX model inference (YOLO, etc.)
- MediaPipe plugin (через WebSocket bridge)
- Blob tracking, colour keying

### Почему НЕ подходит

| Критерий | TouchDesigner | Python Pipeline |
|----------|---------------|----------------|
| **Batch processing** | Нет headless режима, нужен GUI | CLI, запустил и ушёл |
| **40+ проектов** | Ручная настройка per-project | Автосканирование и batch |
| **JSON output** | DAT tables → ручной экспорт | Нативный json.dumps() |
| **Version control** | Бинарные .toe файлы | Python в Git |
| **Стоимость** | $600+ коммерческая лицензия | Бесплатно (MIT/Apache) |
| **Модели ML** | Те же Python-библиотеки в обёртке | Нативный доступ |
| **Пайплайн интеграция** | Нет API для внешних скриптов | Часть YTAI pipeline |
| **Database output** | Нет нативного SQLite | SQLite + FTS5 |

### Где TouchDesigner полезен (не наш случай)
- Real-time визуализация на событии
- Интерактивная инсталляция с камерой
- VJ performance с body tracking
- Прототипирование visual effects

## Другие рассмотренные инструменты

### Twelve Labs (twelvelabs.io)
- **Что**: Облачный video intelligence API — полное понимание видео
- **Плюсы**: Мощнейшее понимание, natural language search, один API
- **Минусы**: Платная подписка (~$500+/мес для серьёзного объёма), данные в облаке, зависимость от сервиса
- **Вердикт**: Рассмотреть позже как дополнение. Для MVP — оверкилл

### Google Video Intelligence API
- **Что**: Shot detection, 20K+ object labels, scene classification
- **Плюсы**: Высокое качество, продакшн-ready
- **Минусы**: Платно ($0.05-0.10/мин видео), нужен GCP аккаунт, данные отправляются в облако
- **Вердикт**: Хорошая альтернатива для enterprise. Для соло-создателя — дорого на архив

### AWS Rekognition Video
- **Что**: Shot boundary, labels, face detection, celebrity recognition
- **Плюсы**: Продакшн-ready, интеграция с S3
- **Минусы**: Платно, требует AWS инфраструктуру
- **Вердикт**: Аналогично Google — оверкилл для локального пайплайна

### Gemini 2.5 Pro (нативное video understanding)
- **Что**: Загрузить целое видео → получить структурированный анализ
- **Плюсы**: Один API call заменяет все 14 модулей, контекстное понимание
- **Минусы**: $0.03-0.10/мин видео, отправка видео в облако, скорость зависит от API
- **Вердикт**: Отличный вариант для Phase 2 — обогащение результатов rich-описаниями. Для MVP — слишком дорого на весь архив

### Claude Vision (покадровый анализ)
- **Что**: Отправить keyframes → получить описания
- **Плюсы**: Уже есть API доступ, высокое качество описаний
- **Минусы**: $0.01-0.02 за группу из 6 кадров, ~$30-65 на весь архив
- **Вердикт**: Отличное дополнение к локальному пайплайну. Для Phase 2 — обогащение описаний на естественном языке поверх CLIP/YOLO тегов

### CLIFS (CLIP-based video search)
- **Что**: Индексация видео через CLIP embeddings, text-based search
- **Плюсы**: Предназначен для поиска по видео
- **Минусы**: 480 stars, менее гибкий чем прямой CLIP
- **Вердикт**: Может быть полезен для semantic search (Phase 3)

## Итоговое сравнение подходов

| Подход | Стоимость | Качество | Контроль | Скорость развёртывания |
|--------|----------|----------|----------|----------------------|
| **Python Pipeline (выбран)** | $0 | 8/10 | 10/10 | 2-3 дня |
| TouchDesigner | $600+ | 5/10 | 3/10 | Не применимо |
| Twelve Labs | $500+/мес | 10/10 | 3/10 | 1 день |
| Google/AWS API | $50-200 | 9/10 | 5/10 | 1-2 дня |
| Claude/Gemini Vision | $30-65 разово | 9/10 | 7/10 | 1 день |

## Рекомендация

### MVP (Phase 1): Python Pipeline
- PySceneDetect + CLIP + YOLOv8 + MediaPipe
- Бесплатно, локально, полный контроль
- 80% от качества облачных решений

### Обогащение (Phase 2): + Claude Vision API
- Добавить natural language описания поверх CLIP тегов
- ~$1-2 за новый проект
- 95% от качества

### Продвинутый поиск (Phase 3): + Vector embeddings
- Semantic search через CLIP embeddings или Voyage
- Поиск по визуальному сходству (найди кадры похожие на этот)
