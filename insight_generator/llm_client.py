"""
LLM Client
==========
Thin OpenAI-compatible chat client for the GreenNode AI Platform (Qwen).

Uses `requests` (already a project dependency) instead of the OpenAI SDK to
keep the runtime image lean. The configured model (default Qwen 3.5 27B) is a
reasoning model: it returns its chain-of-thought in a separate `reasoning`
field and the final answer in `message.content`, so we read `content` only.

All failures (missing key, network error, bad JSON) are swallowed and surfaced
as `None` so callers can fall back to deterministic logic.
"""

import json
import logging
import re

import requests

import config

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(config.LLM_API_KEY)


def chat(
    messages,
    max_tokens: int = 4096,
    temperature: float = 0.2,
):
    """
    Call the chat-completions endpoint and return the assistant message
    content as a string, or None on any failure.
    """
    if not is_configured():
        logger.info("LLM not configured (LLM_API_KEY unset) — skipping LLM call.")
        return None

    url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {config.LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers,
                             timeout=config.LLM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"].get("content")
        if not content:
            logger.warning("LLM returned empty content (finish_reason=%s).",
                           data["choices"][0].get("finish_reason"))
            return None
        return content
    except Exception as exc:  # noqa: BLE001 - any failure → fallback
        logger.warning("LLM call failed: %s", exc)
        return None


def chat_json(messages, max_tokens: int = 4096, temperature: float = 0.2):
    """
    Like `chat`, but parses the assistant content as JSON. Tolerates models
    that wrap JSON in ``` fences or add prose around it. Returns the parsed
    object, or None on any failure.
    """
    content = chat(messages, max_tokens=max_tokens, temperature=temperature)
    if content is None:
        return None
    return _extract_json(content)


def _extract_json(text: str):
    """Best-effort JSON extraction from a possibly fenced/prose-wrapped reply."""
    # Strip ```json ... ``` or ``` ... ``` fences
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else text

    # Try direct parse first
    try:
        return json.loads(candidate)
    except (ValueError, json.JSONDecodeError):
        pass

    # Fall back to slicing from the first { or [ to its matching close
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = candidate.find(open_ch)
        end = candidate.rfind(close_ch)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(candidate[start:end + 1])
            except (ValueError, json.JSONDecodeError):
                continue

    logger.warning("Could not parse JSON from LLM reply.")
    return None
