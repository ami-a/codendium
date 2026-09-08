"""Settings serialisation and the history store."""

from __future__ import annotations

import pytest

from copyright_deposit.config import BuildSettings, HeaderInfo
from copyright_deposit.gui.history import HistoryStore


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_round_trip_through_json():
    settings = BuildSettings()
    settings.source_root = "C:/code"
    settings.header.program_name = "Thing"
    settings.transform.strip_docstrings = False
    settings.layout.lines_per_page = 35
    settings.redaction.regexes = ["secret.*"]
    settings.order_entries = ["a.py", "b.py"]

    restored = BuildSettings.from_json(settings.to_json())
    assert restored.to_dict() == settings.to_dict()


def test_unknown_keys_are_ignored_so_old_saves_still_load():
    data = BuildSettings().to_dict()
    data["a_setting_from_the_future"] = 1
    data["layout"]["another_new_one"] = True
    restored = BuildSettings.from_dict(data)
    assert restored.layout.lines_per_page == 40


def test_missing_sections_fall_back_to_defaults():
    restored = BuildSettings.from_dict({"source_root": "x"})
    assert restored.source_root == "x"
    assert restored.transform.strip_comments is True
    assert restored.deposit.threshold == 50


def test_fingerprint_changes_with_content_settings():
    a = BuildSettings()
    b = BuildSettings.from_json(a.to_json())
    assert a.content_fingerprint() == b.content_fingerprint()
    b.transform.strip_comments = False
    assert a.content_fingerprint() != b.content_fingerprint()


def test_header_block_renders_the_required_fields():
    header = HeaderInfo(
        program_name="Thing",
        version="2.0",
        release_date="2026-01-02",
        revision="deadbee",
        copyright_owner="Owner",
        copyright_year="2026",
    )
    lines = header.lines()
    assert lines[0] == "Thing"
    assert "Version: 2.0" in lines
    assert "Release/build date: 2026-01-02" in lines
    assert "Source revision/commit: deadbee" in lines
    assert "Copyright (c) 2026 Owner" in lines


def test_header_block_uses_placeholders_when_empty():
    lines = HeaderInfo().lines()
    assert lines[0] == "[PROGRAM NAME]"
    assert any("[copyright owner]" in line for line in lines)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    history = HistoryStore(tmp_path / "history.db")
    yield history
    history.close()


def test_profiles_round_trip(store):
    settings = BuildSettings()
    settings.header.program_name = "Saved"
    settings.layout.lines_per_page = 33
    store.save_profile("mine", settings)

    assert store.profile_names() == ["mine"]
    loaded = store.load_profile("mine")
    assert loaded is not None
    assert loaded.header.program_name == "Saved"
    assert loaded.layout.lines_per_page == 33


def test_saving_a_profile_twice_updates_it(store):
    settings = BuildSettings()
    store.save_profile("mine", settings)
    settings.header.program_name = "Changed"
    store.save_profile("mine", settings)
    assert store.profile_names() == ["mine"]
    assert store.load_profile("mine").header.program_name == "Changed"


def test_deleting_a_profile(store):
    store.save_profile("gone", BuildSettings())
    store.delete_profile("gone")
    assert store.profile_names() == []


def test_runs_are_recorded_and_replayable(store):
    settings = BuildSettings()
    settings.source_root = "C:/code"
    settings.header.program_name = "Recorded"
    store.record_run(settings, 137, 50, "head_tail", ["a.pdf", "b.pdf"], 2)

    runs = store.recent_runs()
    assert len(runs) == 1
    run = runs[0]
    assert run.total_pages == 137
    assert run.deposit_pages == 50
    assert run.outputs == ["a.pdf", "b.pdf"]
    assert run.settings().header.program_name == "Recorded"
    assert "Recorded" in run.label()


def test_recent_folders_are_deduplicated_most_recent_first(store):
    for root in ("C:/a", "C:/b", "C:/a"):
        settings = BuildSettings()
        settings.source_root = root
        store.record_run(settings, 1, 1, "entire", [], 0)
    assert store.recent_folders() == ["C:/a", "C:/b"]


def test_a_missing_profile_returns_none(store):
    assert store.load_profile("nope") is None
