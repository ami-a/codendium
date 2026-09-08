"""Settings model.

Every knob the tool exposes lives here as a dataclass. The whole tree is
JSON round-trippable, so a build can be stored in history and reproduced
byte-for-byte later.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_EXTENSIONS: tuple[str, ...] = (
    ".py", ".pyi", ".pyx",
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".inl",
    ".java", ".cs", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".swift",
    ".kt", ".kts", ".m", ".mm", ".scala", ".php", ".rb", ".pl", ".lua",
    ".sql", ".sh", ".bash", ".ps1", ".r", ".jl", ".dart", ".vb", ".f90",
)

# Directory names never worth depositing: build output, dependencies,
# tool caches and vendored third-party code.
DEFAULT_IGNORE_DIRS: tuple[str, ...] = (
    ".git", ".hg", ".svn", ".idea", ".vs", ".vscode", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".eggs",
    "node_modules", "bower_components", "venv", ".venv", "env",
    "site-packages", "dist-packages", "vendor", "third_party", "thirdparty",
    "external", "extern", "build", "_build", "dist", "out", "bin", "obj",
    "target", "cmake-build-debug", "cmake-build-release", "coverage",
    "htmlcov", ".next", ".nuxt", ".gradle", "Pods", "DerivedData",
)

DEFAULT_IGNORE_GLOBS: tuple[str, ...] = (
    "*.min.js", "*.min.css", "*_pb2.py", "*_pb2_grpc.py", "*.pb.go",
    "*.pb.cc", "*.pb.h", "*.g.cs", "*.designer.cs", "*.generated.*",
    "*.lock", "package-lock.json",
)

LEGAL_HEADER_PATTERN = (
    r"copyright|\(c\)|©|licen[sc]e|SPDX-License-Identifier|all rights reserved"
)

MAX_FILE_BYTES = 2 * 1024 * 1024
MINIFIED_MEAN_LINE_LEN = 200

# Compendium section 721.6.
DEPOSIT_PAGE_THRESHOLD = 50
DEPOSIT_HEAD_PAGES = 25
DEPOSIT_TAIL_PAGES = 25

# Compendium section 721.7: blocked-out material may not exceed this share.
MAX_REDACTION_RATIO = 0.49


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class HeaderInfo:
    """The identification block the Office requires on the first page."""

    program_name: str = ""
    version: str = "1.0.0"
    release_date: str = field(default_factory=lambda: date.today().isoformat())
    revision: str = ""  # git short hash; optional but pins the exact deposit
    copyright_owner: str = ""
    copyright_year: str = field(default_factory=lambda: str(date.today().year))
    deposit_label: str = "Deposit Copy - Identifying Portions of Source Code"
    extra_notice: str = ""

    def lines(self) -> list[str]:
        """Render the block exactly as it appears at the top of page 1."""
        out = [self.program_name.strip() or "[PROGRAM NAME]"]
        out.append(f"Version: {self.version}".rstrip())
        if self.release_date:
            out.append(f"Release/build date: {self.release_date}")
        if self.revision:
            out.append(f"Source revision/commit: {self.revision}")
        owner = self.copyright_owner.strip() or "[copyright owner]"
        out.append(f"Copyright (c) {self.copyright_year} {owner}")
        if self.deposit_label:
            out.append(self.deposit_label)
        if self.extra_notice:
            out.extend(self.extra_notice.splitlines())
        return out

    def title_line(self) -> str:
        name = self.program_name.strip() or "[PROGRAM NAME]"
        return f"{name} v{self.version}" if self.version else name


@dataclass
class DiscoveryOptions:
    extensions: list[str] = field(default_factory=lambda: list(DEFAULT_EXTENSIONS))
    ignore_dirs: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_DIRS))
    ignore_globs: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_GLOBS))
    respect_gitignore: bool = True
    max_file_bytes: int = MAX_FILE_BYTES
    skip_minified: bool = True
    skip_empty: bool = True
    follow_symlinks: bool = False


@dataclass
class TransformOptions:
    """Comment/whitespace policy. Default is 'strip everything'."""

    strip_comments: bool = True
    strip_docstrings: bool = True
    preserve_legal_headers: bool = False
    preserve_shebang: bool = True
    collapse_blank_runs: bool = True
    max_blank_run: int = 1
    trim_trailing_whitespace: bool = True
    expand_tabs: bool = True
    tab_width: int = 4

    def cache_key(self) -> str:
        return json.dumps(dataclasses.asdict(self), sort_keys=True)


@dataclass
class LayoutOptions:
    page_size: str = "letter"  # "letter" | "a4"
    font_name: str = "Courier"  # base-14; or a .ttf path / bundled family name
    font_size: float = 9.5
    lines_per_page: int = 40
    margin: float = 54.0  # 0.75 inch
    show_line_numbers: bool = False
    show_file_banners: bool = True
    running_header: bool = True
    page_numbers: bool = True
    wrap_marker: str = ">> "
    file_gap_lines: int = 1  # blank lines before a file banner
    start_files_on_new_page: bool = False

    def cache_key(self) -> str:
        return json.dumps(dataclasses.asdict(self), sort_keys=True)


@dataclass
class RedactionRules:
    """Compendium 721.7 blocked-out material."""

    enabled: bool = False
    begin_marker: str = "COPYRIGHT-REDACT-BEGIN"
    end_marker: str = "COPYRIGHT-REDACT-END"
    regexes: list[str] = field(default_factory=list)
    # "relative/path.py:12" entries, typically queued from the secret scanner.
    manual_lines: list[str] = field(default_factory=list)

    def cache_key(self) -> str:
        return json.dumps(dataclasses.asdict(self), sort_keys=True)


@dataclass
class ScanOptions:
    scan_secrets: bool = True
    scan_third_party: bool = True
    block_on_secrets: bool = True
    ignored_findings: list[str] = field(default_factory=list)  # finding ids


@dataclass
class DepositOptions:
    apply_rule: bool = True
    threshold: int = DEPOSIT_PAGE_THRESHOLD
    head_pages: int = DEPOSIT_HEAD_PAGES
    tail_pages: int = DEPOSIT_TAIL_PAGES
    separator_page: bool = True
    keep_original_page_numbers: bool = True


@dataclass
class BuildSettings:
    source_root: str = ""
    output_dir: str = ""
    output_basename: str = "deposit"
    order_entries: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)  # relative paths
    # Optional per-file line selection: {"src/core.py": "1-50, 120-200"}.
    # An absent or empty entry means the whole file.
    line_ranges: dict[str, str] = field(default_factory=dict)
    include_unlisted: bool = True
    write_full_pdf: bool = True
    write_deposit_pdf: bool = True
    write_manifest: bool = True

    header: HeaderInfo = field(default_factory=HeaderInfo)
    discovery: DiscoveryOptions = field(default_factory=DiscoveryOptions)
    transform: TransformOptions = field(default_factory=TransformOptions)
    layout: LayoutOptions = field(default_factory=LayoutOptions)
    redaction: RedactionRules = field(default_factory=RedactionRules)
    scan: ScanOptions = field(default_factory=ScanOptions)
    deposit: DepositOptions = field(default_factory=DepositOptions)

    # -- serialisation ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BuildSettings":
        return _rebuild(cls, data)

    @classmethod
    def from_json(cls, text: str) -> "BuildSettings":
        return cls.from_dict(json.loads(text))

    def fingerprint(self) -> str:
        """Stable hash of every setting; identifies a run in the history."""
        return hashlib.sha256(self.to_json(indent=None).encode("utf-8")).hexdigest()

    def content_fingerprint(self) -> str:
        """Hash of only the settings that affect the rendered pages.

        Where the PDF is written, and which artifacts are produced, do not
        change a single glyph - so they must not change the fingerprint
        stamped into the file. Excluding them is what makes two runs of the
        same source byte-identical regardless of output folder.
        """
        data = self.to_dict()
        for key in ("output_dir", "output_basename", "write_full_pdf",
                    "write_deposit_pdf", "write_manifest"):
            data.pop(key, None)
        payload = json.dumps(data, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_NESTED: dict[str, type] = {
    "header": HeaderInfo,
    "discovery": DiscoveryOptions,
    "transform": TransformOptions,
    "layout": LayoutOptions,
    "redaction": RedactionRules,
    "scan": ScanOptions,
    "deposit": DepositOptions,
}


def _rebuild(cls: type, data: Any) -> Any:
    """Rebuild nested dataclasses, tolerating unknown or missing keys.

    Tolerance matters: history rows written by an older version of the tool
    must still load rather than crash the GUI.
    """
    if not isinstance(data, dict):
        return data
    kwargs: dict[str, Any] = {}
    known = {f.name for f in dataclasses.fields(cls)}
    for key, value in data.items():
        if key not in known:
            continue
        nested = _NESTED.get(key)
        kwargs[key] = _rebuild(nested, value) if nested is not None else value
    return cls(**kwargs)
