"""Unit tests for local_counsel.config — pure, no LLM, no network."""

from __future__ import annotations

from local_counsel import config
from local_counsel.config import Settings, load_settings

_ENV_VARS = (
    "LC_LLM_HOST",
    "LC_LLM_PORT",
    "LC_MODEL_NAME",
    "LC_LLM_API_KEY",
    "LC_LLM_TIMEOUT",
)


def test_load_settings_defaults(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    s = load_settings()
    assert s.host == "127.0.0.1"
    assert s.port == 8080
    assert s.model_name == "gemma"
    assert s.api_key == "local"
    assert s.timeout_s == 300.0


def test_load_settings_env_overrides(monkeypatch):
    monkeypatch.setenv("LC_LLM_HOST", "example.test")
    monkeypatch.setenv("LC_LLM_PORT", "9090")
    monkeypatch.setenv("LC_MODEL_NAME", "deepseek")
    monkeypatch.setenv("LC_LLM_API_KEY", "secret")
    monkeypatch.setenv("LC_LLM_TIMEOUT", "12.5")
    s = load_settings()
    assert s.host == "example.test"
    assert s.port == 9090
    assert s.model_name == "deepseek"
    assert s.api_key == "secret"
    assert s.timeout_s == 12.5


def test_base_url():
    s = Settings(
        host="h.example",
        port=1234,
        model_name="m",
        api_key="k",
        timeout_s=1.0,
    )
    assert s.base_url == "http://h.example:1234/v1"


def test_base_url_uses_default_host_port(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    assert config.load_settings().base_url == "http://127.0.0.1:8080/v1"
