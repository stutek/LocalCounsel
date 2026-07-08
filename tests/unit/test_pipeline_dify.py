"""Unit tests for Dify pipeline configuration and helpers."""

from __future__ import annotations

from pathlib import Path

from pipeline import config, provisioning


def test_dify_config_defaults():
    url, filename = config.get_dify_defaults()
    assert url == "https://github.com/langgenius/dify/archive/refs/tags/1.15.0.tar.gz"
    assert filename == "dify.tar.gz"
    assert config.DIFY_DIR.name == "dify"
    assert config.DIFY_SHA256 == "18c9a711ac715855bd3d0882966b14143692a48269181c1dd7f7bfcc702a66ba"


def test_find_dify(tmp_path, monkeypatch):
    fake_dify_dir = tmp_path / "dify"
    monkeypatch.setattr(config, "DIFY_DIR", fake_dify_dir)
    monkeypatch.setattr(provisioning, "DIFY_DIR", fake_dify_dir)

    assert provisioning.find_dify() is None

    docker_dir = fake_dify_dir / "dify-1.15.0" / "docker"
    docker_dir.mkdir(parents=True)
    compose_file = docker_dir / "docker-compose.yaml"
    compose_file.write_text("version: '3'\n")

    assert provisioning.find_dify() == docker_dir
