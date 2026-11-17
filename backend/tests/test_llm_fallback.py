"""Gemini quota handling: fall back on 429, skip a cooling-down model, cache identical prompts."""
import io
import urllib.error

import pytest

import llm


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    llm._cache.clear()
    llm._cooldown.clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.6-flash")
    yield
    llm._cache.clear()
    llm._cooldown.clear()


def _http(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b'{"error":{"message":"quota"}}'))


def test_quota_error_falls_back_to_next_model(monkeypatch):
    calls = []

    def fake(model, prompt, key, timeout):
        calls.append(model)
        if model == "gemini-3.6-flash":
            raise _http(429)
        return "ok text"

    monkeypatch.setattr(llm, "_call", fake)
    assert llm.generate("hi") == "ok text"
    assert calls[0] == "gemini-3.6-flash" and len(calls) == 2
    assert llm.last_model() == calls[1]


def test_model_in_cooldown_is_skipped_next_time(monkeypatch):
    calls = []

    def fake(model, prompt, key, timeout):
        calls.append(model)
        if model == "gemini-3.6-flash":
            raise _http(429)
        return "ok " + prompt

    monkeypatch.setattr(llm, "_call", fake)
    llm.generate("first")
    calls.clear()
    llm.generate("second")           # different prompt, so not served from cache
    assert "gemini-3.6-flash" not in calls and len(calls) == 1


def test_identical_prompt_is_cached_and_bypassable(monkeypatch):
    calls = []

    def fake(model, prompt, key, timeout):
        calls.append(model)
        return "answer"

    monkeypatch.setattr(llm, "_call", fake)
    assert llm.generate("same") == "answer" and llm.generate("same") == "answer"
    assert len(calls) == 1
    llm.generate("same", cache=False)
    assert len(calls) == 2


def test_failures_are_not_cached(monkeypatch):
    monkeypatch.setattr(llm, "_call", lambda *a: (_ for _ in ()).throw(_http(403)))
    assert llm.generate("x") is None
    assert not llm._cache


def test_bad_key_does_not_retry(monkeypatch):
    calls = []

    def fake(model, prompt, key, timeout):
        calls.append(model)
        raise _http(403)

    monkeypatch.setattr(llm, "_call", fake)
    assert llm.generate("hi") is None and len(calls) == 1
