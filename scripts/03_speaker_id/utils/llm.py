#!/usr/bin/env python3
"""
YTAI Utils: LLM
Ollama API integration.
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
# Constants
# ============================================================================

OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
DEFAULT_LLM_MODEL = "qwen2.5:32b"
OLLAMA_TIMEOUT = 600  # 10 minutes


# ============================================================================
# Server check
# ============================================================================

def check_ollama_server(logger: Optional[logging.Logger] = None) -> bool:
    """
    Check that the Ollama server is running.

    Returns:
        True if the server is reachable
    """
    if not HAS_REQUESTS:
        if logger:
            logger.error("requests library is not installed: pip install requests")
        return False
    
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            if logger:
                model_names = [m.get("name", "") for m in models]
                logger.debug(f"Available models: {model_names}")
            return True
        return False
    except requests.exceptions.ConnectionError:
        if logger:
            logger.error("Ollama server is not running. Start it with: ollama serve")
        return False
    except Exception as e:
        if logger:
            logger.error(f"Ollama check error: {e}")
        return False


def get_available_models() -> list:
    """Get the list of available models."""
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
# API call
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
    Send a request to the Ollama API.

    Args:
        prompt: Prompt text
        model: Model name
        temperature: Temperature (0.0-1.0)
        max_tokens: Maximum tokens in response
        timeout: Timeout in seconds
        logger: Optional logger

    Returns:
        Response text or None on error
    """
    if not HAS_REQUESTS:
        if logger:
            logger.error("requests library is not installed")
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
                    "num_ctx": 32768,  # Large context for all utterances
                }
            },
            timeout=timeout
        )
        
        if response.status_code == 200:
            return response.json().get("response", "")
        else:
            if logger:
                logger.warning(f"Ollama API error: {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        if logger:
            logger.warning(f"Ollama timeout ({timeout}s)")
        return None
    except requests.exceptions.ConnectionError:
        if logger:
            logger.error("Ollama server is unreachable")
        return None
    except Exception as e:
        if logger:
            logger.error(f"Ollama error: {e}")
        return None


# ============================================================================
# Parse JSON from response
# ============================================================================

def parse_json_response(response: str, logger: Optional[logging.Logger] = None) -> Optional[Dict[str, Any]]:
    """
    Extract JSON from an LLM response.

    The LLM may return JSON inside text or a markdown block.

    Args:
        response: Response text from the LLM
        logger: Optional logger

    Returns:
        Parsed dict or None
    """
    if not response:
        return None
    
    # Try to find JSON in a markdown block
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
    
    # Try to find a JSON object by braces (accounting for nesting)
    # Find the first { and its matching }
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
    
    # Try to parse the entire response as JSON
    try:
        return json.loads(response.strip())
    except json.JSONDecodeError:
        pass
    
    if logger:
        logger.warning(f"Failed to parse JSON from response: {response[:200]}...")
    
    return None


# ============================================================================
# Speaker analysis helpers
# ============================================================================

def build_speaker_analysis_prompt(
    speaker_id: str,
    utterances: list,
    channel_context: Optional[str] = None,
    guest_hint: Optional[str] = None
) -> str:
    """
    Build a prompt for speaker analysis.

    Args:
        speaker_id: Speaker ID (SPEAKER_00)
        utterances: List of utterances [{"text": "...", "start": 0.0}, ...]
        channel_context: Channel context
        guest_hint: Guest name hint

    Returns:
        Prompt text
    """
    total = len(utterances)
    
    # Format utterances
    utterances_text = "\n".join([
        f'{i+1}. "{u["text"]}"' 
        for i, u in enumerate(utterances)
    ])
    
    # Channel context
    context_section = ""
    if channel_context:
        # Limit context size
        if len(channel_context) > 2000:
            channel_context = channel_context[:2000] + "\n[...truncated]"
        context_section = f"""
CHANNEL CONTEXT:
{channel_context}
"""
    
    # Guest name hint
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
