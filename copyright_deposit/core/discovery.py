"""Recursive source discovery.

Every exclusion is recorded rather than silently applied: a deposit is a
legal filing, so the operator must be able to see exactly what the tool
decided to leave out and why.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ..config import DiscoveryOptions
from . import languages

SKIP_EXTENSION = "extension not selected"
SKIP_IGNORED_DIR = "inside an ignored directory"
SKIP_IGNORE_GLOB = "matches an ignore pattern"
SKIP_GITIGNORE = "ignored by .gitignore"
SKIP_TOO_LARGE = "larger than the size limit"
SKIP_BINARY = "binary content"
SKIP_MINIFIED = "appears to be minified or generated"
SKIP_EMPTY = "empty file"
SKIP_UNREADABLE = "could not be read"


@dataclass
class DiscoveredFile:
    rel_path: str  # posix-style, relative to the source root
    abs_path: str
    size: int
    sha256: str
    language: str
    family: str
    raw_line_count: int

    @property
    def name(self) -> str:
        return PurePosixPath(self.rel_path).name


@dataclass
class SkippedFile:
    rel_path: str
    reason: str
    size: int = 0


@dataclass
class DiscoveryResult:
    root: str
    files: list[DiscoveredFile] = field(default_factory=list)
    skipped: list[SkippedFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def by_path(self) -> dict[str, DiscoveredFile]:
        return {f.rel_path: f for f in self.files}


# ---------------------------------------------------------------------------
# .gitignore support
# ---------------------------------------------------------------------------


class _GitIgnoreStack:
    """Nested .gitignore matching.

    Each .gitignore governs its own directory subtree, so patterns are
    matched against the path relative to the file that declared them.
    """

    def __init__(self) -> None:
        self._specs: list[tuple[str, object]] = []

    def add_dir(self, dir_rel: str, dir_abs: Path) -> None:
        gi = dir_abs / ".gitignore"
        if not gi.is_file():
            return
        try:
            import pathspec

            lines = gi.read_text(encoding="utf-8", errors="replace").splitlines()
            spec = pathspec.PathSpec.from_lines("gitwildmatch", lines)
        except Exception:
            return
        self._specs.append((dir_rel, spec))

    def matches(self, rel_path: str, is_dir: bool = False) -> bool:
        candidate = rel_path + "/" if is_dir else rel_path
        for base, spec in self._specs:
            if base and not candidate.startswith(base + "/"):
                continue
            sub = candidate[len(base) + 1 :] if base else candidate
            if sub and spec.match_file(sub):  # type: ignore[attr-defined]
                return True
        return False


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _matches_any_glob(name: str, rel_path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_path, pattern):
            return True
    return False


def _inspect(data: bytes) -> tuple[bool, int, float]:
    """Return (is_binary, line_count, mean_line_length) without decoding."""
    is_binary = b"\x00" in data[:8192]
    line_count = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    mean = len(data) / line_count if line_count else float(len(data))
    return is_binary, line_count, mean


def discover(root: str | Path, options: DiscoveryOptions | None = None) -> DiscoveryResult:
    options = options or DiscoveryOptions()
    root_path = Path(root).resolve()
    result = DiscoveryResult(root=str(root_path))

    if not root_path.is_dir():
        result.warnings.append(f"Source folder does not exist: {root_path}")
        return result

    ignore_dirs = {d.lower() for d in options.ignore_dirs}
    gitignore = _GitIgnoreStack() if options.respect_gitignore else None

    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=options.follow_symlinks):
        current = Path(dirpath)
        dir_rel = current.relative_to(root_path).as_posix()
        dir_rel = "" if dir_rel == "." else dir_rel

        if gitignore is not None:
            gitignore.add_dir(dir_rel, current)

        # Prune in place so os.walk never descends into excluded trees.
        kept: list[str] = []
        for d in sorted(dirnames):
            child_rel = f"{dir_rel}/{d}" if dir_rel else d
            if d.lower() in ignore_dirs:
                continue
            if gitignore is not None and gitignore.matches(child_rel, is_dir=True):
                continue
            kept.append(d)
        dirnames[:] = kept

        for name in sorted(filenames):
            rel = f"{dir_rel}/{name}" if dir_rel else name
            abs_path = current / name

            if not languages.is_supported_extension(name, options.extensions):
                continue  # not a source file; not worth reporting as "skipped"

            if _matches_any_glob(name, rel, options.ignore_globs):
                result.skipped.append(SkippedFile(rel, SKIP_IGNORE_GLOB))
                continue
            if gitignore is not None and gitignore.matches(rel):
                result.skipped.append(SkippedFile(rel, SKIP_GITIGNORE))
                continue

            try:
                size = abs_path.stat().st_size
            except OSError:
                result.skipped.append(SkippedFile(rel, SKIP_UNREADABLE))
                continue

            if options.max_file_bytes and size > options.max_file_bytes:
                result.skipped.append(SkippedFile(rel, SKIP_TOO_LARGE, size))
                continue
            if options.skip_empty and size == 0:
                result.skipped.append(SkippedFile(rel, SKIP_EMPTY, size))
                continue

            try:
                data = abs_path.read_bytes()
            except OSError:
                result.skipped.append(SkippedFile(rel, SKIP_UNREADABLE, size))
                continue

            is_binary, line_count, mean_len = _inspect(data)
            if is_binary:
                result.skipped.append(SkippedFile(rel, SKIP_BINARY, size))
                continue
            if options.skip_minified and mean_len > 200 and line_count > 0:
                result.skipped.append(SkippedFile(rel, SKIP_MINIFIED, size))
                continue
            if options.skip_empty and not data.strip():
                result.skipped.append(SkippedFile(rel, SKIP_EMPTY, size))
                continue

            lang = languages.detect(name)
            result.files.append(
                DiscoveredFile(
                    rel_path=rel,
                    abs_path=str(abs_path),
                    size=size,
                    sha256=hashlib.sha256(data).hexdigest(),
                    language=lang.name,
                    family=lang.family,
                    raw_line_count=line_count,
                )
            )

    result.files.sort(key=default_sort_key)
    result.skipped.sort(key=lambda s: s.rel_path)
    return result


def default_sort_key(f: DiscoveredFile) -> tuple:
    """Deterministic fallback order: shallower directories first, then path.

    Shallow-first puts entry points and top-level modules near the front,
    which is usually what a reader expects at the beginning of a program.
    """
    parts = PurePosixPath(f.rel_path).parts
    return (len(parts) - 1, f.rel_path.lower())


# ---------------------------------------------------------------------------
# Git metadata (prefills the identification block)
# ---------------------------------------------------------------------------


def git_revision(root: str | Path) -> str:
    """Short commit hash for the source tree, or '' if not a git repo."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if out.returncode != 0:
        return ""
    rev = out.stdout.strip()
    if not rev:
        return ""
    try:
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if dirty.returncode == 0 and dirty.stdout.strip():
            rev += " (uncommitted changes present)"
    except (OSError, subprocess.SubprocessError):
        pass
    return rev
