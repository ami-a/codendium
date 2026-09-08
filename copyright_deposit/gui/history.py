"""Persistent history and reusable profiles.

Two things are remembered: named *profiles* (a complete settings snapshot
for one program, so the next version's registration starts where the last
one finished) and a log of *runs* (what was built, when, and with which
settings, so a filing can be reproduced or explained later).

Settings are stored as JSON and reloaded tolerantly, so a database written
by an older version of the tool still opens.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .. import APP_NAME
from ..config import BuildSettings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    name        TEXT PRIMARY KEY,
    settings    TEXT NOT NULL,
    updated_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started_utc    TEXT NOT NULL,
    program_name   TEXT NOT NULL DEFAULT '',
    source_root    TEXT NOT NULL DEFAULT '',
    settings       TEXT NOT NULL,
    total_pages    INTEGER NOT NULL DEFAULT 0,
    deposit_pages  INTEGER NOT NULL DEFAULT 0,
    deposit_mode   TEXT NOT NULL DEFAULT '',
    outputs        TEXT NOT NULL DEFAULT '[]',
    fingerprint    TEXT NOT NULL DEFAULT '',
    warning_count  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS runs_started ON runs (started_utc DESC);
"""


@dataclass
class RunRecord:
    id: int
    started_utc: str
    program_name: str
    source_root: str
    total_pages: int
    deposit_pages: int
    deposit_mode: str
    outputs: list[str]
    fingerprint: str
    warning_count: int
    settings_json: str

    def settings(self) -> BuildSettings:
        return BuildSettings.from_json(self.settings_json)

    def label(self) -> str:
        stamp = self.started_utc.replace("T", " ")[:16]
        name = self.program_name or Path(self.source_root).name or "(unnamed)"
        return f"{stamp}  -  {name}  -  {self.total_pages}p"


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


class HistoryStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else data_dir() / "history.db"
        self._connection = sqlite3.connect(str(self.path))
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    # -- profiles ---------------------------------------------------------

    def save_profile(self, name: str, settings: BuildSettings) -> None:
        self._connection.execute(
            "INSERT INTO profiles (name, settings, updated_utc) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET settings=excluded.settings, "
            "updated_utc=excluded.updated_utc",
            (name, settings.to_json(indent=None), _now()),
        )
        self._connection.commit()

    def profile_names(self) -> list[str]:
        rows = self._connection.execute(
            "SELECT name FROM profiles ORDER BY updated_utc DESC"
        ).fetchall()
        return [row["name"] for row in rows]

    def load_profile(self, name: str) -> BuildSettings | None:
        row = self._connection.execute(
            "SELECT settings FROM profiles WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        try:
            return BuildSettings.from_json(row["settings"])
        except (ValueError, TypeError):
            return None

    def delete_profile(self, name: str) -> None:
        self._connection.execute("DELETE FROM profiles WHERE name = ?", (name,))
        self._connection.commit()

    # -- runs -------------------------------------------------------------

    def record_run(
        self,
        settings: BuildSettings,
        total_pages: int,
        deposit_pages: int,
        deposit_mode: str,
        outputs: list[str],
        warning_count: int,
    ) -> int:
        cursor = self._connection.execute(
            "INSERT INTO runs (started_utc, program_name, source_root, settings, "
            "total_pages, deposit_pages, deposit_mode, outputs, fingerprint, warning_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _now(),
                settings.header.program_name,
                settings.source_root,
                settings.to_json(indent=None),
                total_pages,
                deposit_pages,
                deposit_mode,
                json.dumps(outputs),
                settings.content_fingerprint(),
                warning_count,
            ),
        )
        self._connection.commit()
        return int(cursor.lastrowid or 0)

    def recent_runs(self, limit: int = 50) -> list[RunRecord]:
        rows = self._connection.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_to_record(row) for row in rows]

    def delete_run(self, run_id: int) -> None:
        self._connection.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        self._connection.commit()

    def recent_folders(self, limit: int = 10) -> list[str]:
        rows = self._connection.execute(
            "SELECT source_root, MAX(id) AS latest FROM runs "
            "WHERE source_root <> '' GROUP BY source_root ORDER BY latest DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [row["source_root"] for row in rows]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_record(row: sqlite3.Row) -> RunRecord:
    try:
        outputs = json.loads(row["outputs"])
    except (ValueError, TypeError):
        outputs = []
    return RunRecord(
        id=row["id"],
        started_utc=row["started_utc"],
        program_name=row["program_name"],
        source_root=row["source_root"],
        total_pages=row["total_pages"],
        deposit_pages=row["deposit_pages"],
        deposit_mode=row["deposit_mode"],
        outputs=outputs,
        fingerprint=row["fingerprint"],
        warning_count=row["warning_count"],
        settings_json=row["settings"],
    )
