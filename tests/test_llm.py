"""PR11 gates: LLM client — OpenRouter primary, Pollinations fallback, offline-safe."""

import io
import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm import client as llm


class _FakeResp:
    def __init__(self, payload: bytes):
        self._p = payload

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, handler):
    monkeypatch.setattr(llm.urllib.request, "urlopen", handler)


def test_openrouter_primary_used_when_key_set(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "m")
    calls = []

    def fake(req, timeout=None):
        calls.append(req.full_url)
        return _FakeResp(json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode())

    _patch(monkeypatch, fake)
    assert llm.complete([{"role": "user", "content": "hi"}]) == "hello"
    assert calls and "openrouter" in calls[0]


def test_fallback_on_primary_failure(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    def fake(req, timeout=None):
        if "openrouter" in req.full_url:
            raise urllib.error.URLError("down")
        return _FakeResp(b"fallback text")

    _patch(monkeypatch, fake)
    assert llm.complete([{"role": "user", "content": "hi"}]) == "fallback text"


def test_none_when_all_fail_offline_safe(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    def fake(req, timeout=None):
        raise urllib.error.URLError("no network")

    _patch(monkeypatch, fake)
    assert llm.complete([{"role": "user", "content": "hi"}]) is None


def test_enhance_keeps_original_on_failure(monkeypatch):
    _patch(monkeypatch, lambda req, timeout=None: (_ for _ in ()).throw(
        urllib.error.URLError("x")))
    assert llm.enhance_summary("net diff 4200 [tds:04]", ["[tds:04]"]) == "net diff 4200 [tds:04]"


def test_backend_status_shape(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    s = llm.backend_status()
    assert s["primary"] == "openrouter:missing-key"
    assert s["fallback"] == "pollinations:available"
    assert s["enhance"] is False
