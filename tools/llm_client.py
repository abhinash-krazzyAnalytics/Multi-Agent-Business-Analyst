"""
Thin wrapper around the local Ollama HTTP API.

Every agent prompt in this project asks the model to return JSON only.
This wrapper centralizes:
  - calling Ollama's /api/chat endpoint
  - stripping markdown code fences if the model adds them anyway
  - parsing JSON safely
  - detecting whether Ollama is reachable at all, so the app can fall
    back to deterministic demo agents (see agents/demo_fallback.py)
    when no local model is running.
"""

import json
import requests
from config.settings import OLLAMA_HOST


_OLLAMA_AVAILABLE = None  # cached after first check


def ollama_is_available() -> bool:
    global _OLLAMA_AVAILABLE
    if _OLLAMA_AVAILABLE is not None:
        return _OLLAMA_AVAILABLE
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=1.5)
        _OLLAMA_AVAILABLE = resp.status_code == 200
    except Exception:
        _OLLAMA_AVAILABLE = False
    return _OLLAMA_AVAILABLE


def call_ollama_json(model: str, system_prompt: str, user_content: str, timeout: int = 60) -> dict:
    """
    Calls Ollama chat completion and parses the response as JSON.
    Raises ValueError if the response cannot be parsed as JSON.
    """
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }

    resp = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    raw_text = data.get("message", {}).get("content", "")

    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON: {e}\nRaw output: {raw_text[:500]}")