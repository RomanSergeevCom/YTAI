# Dependencies — Зависимости и установка

## Единая установка (все модули)

```bash
# Активировать venv
source ~/YTAI/environment/.venv_transcribe/bin/activate

# Core (модули 1-5)
pip install scenedetect[opencv]    # PySceneDetect + OpenCV (~50MB)
pip install ultralytics            # YOLOv8 (~20MB + torch)
pip install git+https://github.com/openai/CLIP.git  # CLIP
pip install mediapipe              # Pose/Face (~30MB)
pip install deepface               # Emotion recognition (~20MB)

# Extended (модули 6-10)
pip install easyocr                # OCR (~25MB + models ~200MB)
pip install pyloudnorm             # Audio loudness (~50KB)
# Silero VAD через torch.hub (скачается автоматически, 1.6MB)

# Уже установлены (от Whisper/других модулей):
# torch, torchvision, torchaudio
# opencv-python
# numpy
# scikit-learn
```

## Минимальная установка (только Core)

```bash
pip install scenedetect[opencv] ultralytics mediapipe deepface
pip install git+https://github.com/openai/CLIP.git
```

## Размеры моделей (скачиваются при первом запуске)

| Модель | Размер | Кеш |
|--------|--------|-----|
| CLIP ViT-B/32 | 350 MB | `~/.cache/clip/` |
| YOLOv8n | 6 MB | автоматически |
| MediaPipe Pose | ~15 MB | встроен |
| MediaPipe Face Mesh | ~10 MB | встроен |
| DeepFace emotion | ~100 MB | `~/.deepface/weights/` |
| EasyOCR EN + RU | ~200 MB | `~/.EasyOCR/` |
| Silero VAD | 1.6 MB | `~/.cache/torch/hub/` |
| **Итого** | **~680 MB** | |

## Без torch — уже установлен?

```bash
python -c "import torch; print(torch.__version__)"
```

Torch скорее всего уже установлен (от Whisper). Если нет:
```bash
pip install torch torchvision torchaudio
# Apple Silicon: ~400MB
```

## FFmpeg

FFmpeg уже установлен в YTAI pipeline. Проверка:
```bash
ffmpeg -version
```

## Python

Python 3.10+ (от YTAI venv). Проверка:
```bash
python --version
```

## macOS совместимость

| Библиотека | Intel Mac | Apple Silicon (M1+) | Примечание |
|-----------|-----------|-------|------------|
| PySceneDetect | OK | OK | CPU-only |
| CLIP | OK | OK + MPS | MPS даёт ~10x ускорение |
| YOLOv8 | OK | OK + MPS | MPS даёт ~5x ускорение |
| MediaPipe | OK | OK | CPU-only |
| DeepFace | OK | OK | CPU-only |
| EasyOCR | OK | OK | CPU, GPU limited |
| OpenCV | OK | OK | CPU-only |
| Silero VAD | OK | OK | CPU-only, очень быстрый |

## MPS (Apple Metal Performance Shaders)

Для ускорения CLIP и YOLO на Apple Silicon:

```python
import torch
device = "mps" if torch.backends.mps.is_available() else "cpu"
print(f"Using device: {device}")
```

MPS ускоряет:
- CLIP inference: ~10x (0.5 → 0.05 сек/кадр)
- YOLOv8 inference: ~5x (80 → 15 мс/кадр)
- Не влияет на: MediaPipe, OpenCV, EasyOCR (CPU-only)

## Возможные конфликты

### torch версии
Whisper может требовать конкретную версию torch. CLIP и YOLOv8 обычно совместимы с последней.

```bash
# Проверить установленную версию
pip show torch

# При конфликте — создать отдельный venv:
python -m venv ~/.ytai/venv_analysis
source ~/.ytai/venv_analysis/bin/activate
pip install scenedetect[opencv] ultralytics mediapipe deepface easyocr
pip install git+https://github.com/openai/CLIP.git
```

### OpenCV версии
PySceneDetect и EasyOCR могут тянуть разные opencv-python. Решение:
```bash
pip install opencv-python-headless  # без GUI (меньше конфликтов)
```

## Disk space

| Компонент | Размер |
|-----------|--------|
| Python packages | ~200 MB |
| Downloaded models | ~680 MB |
| Keyframes (40 projects) | ~200 MB |
| SQLite database | ~10 MB |
| **Итого** | **~1.1 GB** |
