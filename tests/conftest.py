from __future__ import annotations

from pathlib import Path

import pytest

from copyright_deposit.config import BuildSettings


@pytest.fixture
def make_tree(tmp_path):
    """Write a dict of {relative path: text} into a temporary folder."""

    def _make(files: dict[str, str], name: str = "src") -> Path:
        root = tmp_path / name
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return root

    return _make


@pytest.fixture
def settings_for(tmp_path):
    def _settings(root: Path, **kwargs) -> BuildSettings:
        settings = BuildSettings()
        settings.source_root = str(root)
        settings.output_dir = str(tmp_path / "out")
        settings.header.program_name = "Test Program"
        settings.header.copyright_owner = "Test Owner"
        settings.header.release_date = "2026-01-01"
        settings.discovery.respect_gitignore = False
        for key, value in kwargs.items():
            setattr(settings, key, value)
        return settings

    return _settings


