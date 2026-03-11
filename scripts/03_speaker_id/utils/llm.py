#!/usr/bin/env python3
"""
YTAI Utils: LLM
Работа с Ollama API.
"""

import json
import re
import logging
from typing import Optional, Dict, Any

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ============================================================================
# Константы
# ============================================================================

OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
DEFAULT_LLM_MODEL = "qwen2.5:32b"
OLLAMA_TIMEOUT = 600  # 10 минут


# ============================================================================
# Проверка сервера
# ============================================================================

def check_ollama_server(logger: Optional[logging.Logger] = None) -> bool:
    """
    Проверить что Ollama сервер запущен.
    
    Returns:
        True если сервер доступен
    """
    if not HAS_REQUESTS:
        if logger:
            logger.error("Библиотека requests не установлена: pip install requests")
        return False
    
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            if logger:
                model_names = [m.get("name", "") for m in models]
                logger.debug(f"Доступные модели: {model_names}")
            return True
        return False
    except requests.exceptions.ConnectionError:
        if logger:
            logger.error("Ollama сервер не запущен. Запустите: ollama serve")
        return False
    except Exception as e:
        if logger:
            logger.error(f"Ошибка проверки Ollama: {e}")
        return False


def get_available_models() -> list:
    """Получить список доступных моделей."""
    if not HAS_REQUESTS:
        return []
    
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            return [m.get("name", "") for m in models]
    except Exception:
        pass
    
    return []


# ============================================================================
# Вызов API
# ============================================================================

def call_ollama(
    prompt: str,
    model: str = DEFAULT_LLM_MODEL,
    temperature: float = 0.3,
    max_tokens: int = 1000,
    timeout: int = OLLAMA_TIMEOUT,
    logger: Optional[logging.Logger] = None
) -> Optional[str]:
    """
    Отправить запрос в Ollama API.
    
    Args:
        prompt: Текст промпта
        model: Название модели
        temperature: Температура (0.0-1.0)
        max_tokens: Максимум токенов в ответе
        timeout: Таймаут в секундах
        logger: Опциональный логгер
        
    Returns:
        Текст ответа или None при ошибке
    """
    if not HAS_REQUESTS:
        if logger:
            logger.error("Библиотека requests не установлена")
        return None
    
    try:
        response = requests.post(
            OLLAMA_API_URL,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "num_ctx": 32768,  # Большой контекст для всех реплик
                }
            },
            timeout=timeout
        )
        
        if response.status_code == 200:
            return response.json().get("response", "")
        else:
            if logger:
                logger.warning(f"Ollama API ошибка: {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        if logger:
            logger.warning(f"Ollama таймаут ({timeout}s)")
        return None
    except requests.exceptions.ConnectionError:
        if logger:
            logger.error("Ollama сервер недоступен")
        return None
    except Exception as e:
        if logger:
            logger.error(f"Ollama ошибка: {e}")
        return None


# ============================================================================
# Парсинг JSON из ответа
# ============================================================================

def parse_json_response(response: str, logger: Optional[logging.Logger] = None) -> Optional[Dict[str, Any]]:
    """
    Извлечь JSON из ответа LLM.
    
    LLM может вернуть JSON внутри текста или markdown блока.
    
    Args:
        response: Текст ответа от LLM
        logger: Опциональный логгер
        
    Returns:
        Распарсенный dict или None
    """
    if not response:
        return None
    
    # Попробовать найти JSON в markdown блоке
    md_patterns = [
        r'```json\s*([\s\S]*?)\s*```',  # ```json ... ```
        r'```\s*([\s\S]*?)\s*```',       # ``` ... ```
    ]
    
    for pattern in md_patterns:
        match = re.search(pattern, response)
        if match:
            json_str = match.group(1).strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                continue
    
    # Попробовать найти JSON объект по скобкам (с учётом вложенности)
    # Ищем первую { и соответствующую ей }
    start_idx = response.find('{')
    if start_idx != -1:
        depth = 0
        for i, char in enumerate(response[start_idx:], start_idx):
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    json_str = response[start_idx:i+1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        break
    
    # Попробовать распарсить весь ответ как JSON
    try:
        return json.loads(response.strip())
    except json.JSONDecodeError:
        pass
    
    if logger:
        logger.warning(f"Не удалось распарсить JSON из ответа: {response[:200]}...")
    
    return None


# ============================================================================
# Хелперы для анализа спикеров
# ============================================================================

def build_speaker_analysis_prompt(
    speaker_id: str,
    utterances: list,
    channel_context: Optional[str] = None,
    guest_hint: Optional[str] = None
) -> str:
    """
    Построить промпт для анализа спикера.
    
    Args:
        speaker_id: ID спикера (SPEAKER_00)
        utterances: Список реплик [{"text": "...", "start": 0.0}, ...]
        channel_context: Контекст канала
        guest_hint: Подсказка имени гостя
        
    Returns:
        Текст промпта
    """
    total = len(utterances)
    
    # Форматировать реплики
    utterances_text = "\n".join([
        f'{i+1}. "{u["text"]}"' 
        for i, u in enumerate(utterances)
    ])
    
    # Контекст канала
    context_section = ""
    if channel_context:
        # Ограничить размер контекста
        if len(channel_context) > 2000:
            channel_context = channel_context[:2000] + "\n[...truncated]"
        context_section = f"""
CHANNEL CONTEXT:
{channel_context}
"""
    
    # Подсказка имени гостя
    hint_section = ""
    if guest_hint:
        hint_section = f"""
IMPORTANT HINT:
Project folder name suggests guest might be: "{guest_hint}"
If this speaker is the GUEST, their name is likely "{guest_hint.split()[0]}".
"""
    
    prompt = f"""Analyze these utterances from ONE person in a YouTube interview.
{context_section}
{hint_section}

YOUR TASK: Determine WHO this person is.

ALL UTTERANCES FROM {speaker_id} ({total} total):

{utterances_text}

=== ANALYSIS STEPS ===

1. SEARCH FOR EXPLICIT NAME in utterances:
   - "My name is X" / "I'm X" / "I am X"
   - Someone addresses them: "Thank you, X"
   
2. DETERMINE ROLE from speech patterns:
   - HOST: Asks questions ("Could you tell us?", "What do you think?")
   - GUEST: Talks about own business ("My company", "We started", "I founded")
   - EXPERT: Technical demonstrations
   - MINOR: Only short responses ("yeah", "okay")

3. ASSIGN NAME:
   - If name found → use it
   - If HOST but no name → use "Roman"
   - If GUEST but no name → check hint above or use "Guest"
   - If only short responses → use "Minor"

4. RATE CONFIDENCE:
   - HIGH: Name found OR clear role
   - MEDIUM: Role clear but no name
   - LOW: Uncertain

=== RESPOND WITH JSON ONLY ===

{{
  "assigned_name": "Hadi",
  "found_in_text": true,
  "name_evidence": "My name is Hadi and I started...",
  "role": "guest",
  "confidence": "high",
  "reasoning": "Explicit self-introduction found"
}}"""

    return prompt
