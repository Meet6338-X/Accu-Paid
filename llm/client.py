"""LLM client — OpenRouter primary, Pollinations.ai fallback, offline-safe.

- Primary: OpenRouter OpenAI-compatible chat completions
  (needs OPENROUTER_API_KEY; model via LLM_MODEL, default "openrouter/auto").
- Fallback: Pollinations.ai free text endpoint (no key).
- No key + no network -> complete() returns None and the pipeline keeps its
  deterministic rule-based behavior. Evals never depend on the network.

Wire-up: agent/nodes.format_response calls enhance_summary() only when
ACCUPAID_LLM_ENHANCE=1. /health reports backend_status() (no network I/O).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request

log = logging.getLogger("accupaid.llm")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
POLLINATIONS_URL = "https://text.pollinations.ai"

_last: dict = {"backend": None, "ms": None, "ok": None, "at": None}


def _note(backend: str, ms: float, ok: bool) -> None:
    import time as _time

    _last.update({"backend": backend, "ms": round(ms, 1), "ok": ok,
                  "at": _time.strftime("%Y-%m-%dT%H:%M:%S")})
    log.info("llm %s ok=%s %.0fms", backend, ok, ms)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def backend_status() -> dict:
    return {
        "primary": "openrouter:" + ("configured" if _env("OPENROUTER_API_KEY") else "missing-key"),
        "fallback": "pollinations:available",
        "enhance": _env("ACCUPAID_LLM_ENHANCE") == "1",
        "last": dict(_last),
    }


def complete(messages: list[dict], max_tokens: int = 512, temperature: float = 0.2) -> str | None:
    """Try OpenRouter, then Pollinations. Returns text or None (offline-safe)."""
    import time as _time

    if _env("OPENROUTER_API_KEY"):
        t0 = _time.time()
        try:
            out = _openrouter(messages, max_tokens, temperature)
            _note("openrouter", (_time.time() - t0) * 1000, True)
            return out
        except Exception as e:  # noqa: BLE001 — fallback must survive anything
            _note("openrouter", (_time.time() - t0) * 1000, False)
            log.warning("openrouter failed, trying fallback: %s", e)
    t0 = _time.time()
    try:
        out = _pollinations(messages, max_tokens)
        _note("pollinations", (_time.time() - t0) * 1000, True)
        return out
    except Exception as e:  # noqa: BLE001
        _note("pollinations", (_time.time() - t0) * 1000, False)
        log.warning("pollinations fallback failed: %s", e)
        return None


def _openrouter(messages: list[dict], max_tokens: int, temperature: float) -> str:
    body = json.dumps({"model": _env("LLM_MODEL", "openrouter/auto"),
                       "messages": messages, "max_tokens": max_tokens,
                       "temperature": temperature}).encode()
    req = urllib.request.Request(
        OPENROUTER_URL, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {_env('OPENROUTER_API_KEY')}",
                 "HTTP-Referer": _env("LLM_REFERER", "http://127.0.0.1:8000"),
                 "X-Title": "AccuPaid"},
        method="POST")
    with urllib.request.urlopen(req, timeout=15) as res:
        data = json.loads(res.read().decode())
    return data["choices"][0]["message"]["content"].strip()


def _pollinations(messages: list[dict], max_tokens: int) -> str:
    prompt = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages)
    url = f"{POLLINATIONS_URL}/{urllib.parse.quote(prompt[:4000])}?model={_env('POLLINATIONS_MODEL', 'openai')}"
    req = urllib.request.Request(url, headers={"Accept": "text/plain"})
    with urllib.request.urlopen(req, timeout=20) as res:
        return res.read().decode().strip()[: max_tokens * 4]


def enhance_summary(summary: str, cites: list[str]) -> str:
    """Rewrite a result summary in plain Hinglish-friendly English.

    Numbers and [doc:chunk] cites must pass through untouched — the caller
    keeps the original on any failure or empty return.
    """
    if not summary:
        return summary
    out = complete([
        {"role": "system", "content": (
            "Rewrite the payroll-assistant result in 2-3 plain sentences. "
            "Keep every number, ID, date and [cite] EXACTLY as given. "
            "Never invent amounts. Reply with the rewrite only.")},
        {"role": "user", "content": f"{summary}\nCites: {'; '.join(cites[:5])}"},
    ])
    return out if out else summary
