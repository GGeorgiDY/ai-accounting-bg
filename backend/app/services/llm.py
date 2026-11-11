"""Тънък клиент към локалния Ollama сървър. Сменим с друг backend (vLLM, llama.cpp) при нужда."""
import json
import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """Сървърът/моделът не е достъпен — задачата трябва да се опита отново по-късно."""


def _model_names(tags: dict) -> set[str]:
    names = set()
    for m in tags.get("models", []):
        for key in ("name", "model"):
            if m.get(key):
                names.add(m[key])
                if m[key].endswith(":latest"):
                    names.add(m[key][: -len(":latest")])
    return names


def status() -> dict:
    try:
        r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=5)
        r.raise_for_status()
        ready = settings.llm_model in _model_names(r.json())
        return {"reachable": True, "model": settings.llm_model, "model_ready": ready}
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "model": settings.llm_model, "model_ready": False, "error": str(exc)}


def chat_json(system: str, user: str, schema: dict) -> dict:
    """Извиква модела със structured output (JSON Schema) и връща парснат dict."""
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "format": schema,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": settings.llm_num_ctx},
    }
    try:
        r = httpx.post(
            f"{settings.ollama_url}/api/chat", json=payload, timeout=settings.llm_timeout_seconds
        )
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise LLMUnavailable(f"Ollama не е достъпен: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise LLMError(f"Моделът не отговори за {settings.llm_timeout_seconds}s") from exc

    if r.status_code == 404:
        raise LLMUnavailable(f"Моделът {settings.llm_model} още не е изтеглен")
    if r.status_code >= 400:
        raise LLMError(f"Ollama HTTP {r.status_code}: {r.text[:500]}")

    content = r.json().get("message", {}).get("content", "")
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Моделът върна невалиден JSON: {content[:300]}") from exc
