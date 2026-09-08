"""File ordering: the user's list, resolved; or one suggested from the code.

Order matters legally. The Compendium asks for the first and last 25 pages
of the program, so whatever sits at the front of the deposit is what the
Office actually reads. The resolver therefore never guesses silently: an
entry that could mean two different files is reported as an ambiguity.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .discovery import DiscoveredFile, default_sort_key

SOURCE_LISTED = "listed"
SOURCE_GLOB = "glob"
SOURCE_UNLISTED = "unlisted"

_GLOB_CHARS = set("*?[")

# Filenames that conventionally begin a program.
_ENTRY_NAMES = (
    "__main__.py", "main.py", "app.py", "run.py", "manage.py", "cli.py",
    "main.cpp", "main.c", "main.cc", "winmain.cpp", "program.cs", "main.go",
    "main.rs", "index.js", "index.ts", "main.js", "main.ts", "main.java",
)
_ENTRY_PATTERNS = (
    re.compile(r"^\s*if\s+__name__\s*==\s*['\"]__main__['\"]", re.MULTILINE),
    re.compile(r"\b(?:int|void)\s+(?:main|WinMain|wmain)\s*\(", re.MULTILINE),
    re.compile(r"\bfunc\s+main\s*\(", re.MULTILINE),
    re.compile(r"\bfn\s+main\s*\(", re.MULTILINE),
    re.compile(r"\bstatic\s+void\s+Main\s*\(", re.MULTILINE),
)

_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)

_HEADER_SUFFIXES = (".h", ".hpp", ".hh", ".hxx")
_IMPL_SUFFIXES = (".c", ".cpp", ".cc", ".cxx", ".m", ".mm")


@dataclass
class OrderedItem:
    rel_path: str
    source: str = SOURCE_LISTED
    entry: str = ""  # the order-list line that produced it


@dataclass
class Ambiguity:
    entry: str
    candidates: list[str]
    chosen: str = ""


@dataclass
class OrderPlan:
    items: list[OrderedItem] = field(default_factory=list)
    ambiguities: list[Ambiguity] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def paths(self) -> list[str]:
        return [item.rel_path for item in self.items]


# ---------------------------------------------------------------------------
# Order-list text format
# ---------------------------------------------------------------------------


def parse_order_text(text: str) -> list[str]:
    """One entry per line; blank lines and '#' comments ignored."""
    entries: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(line.replace("\\", "/"))
    return entries


def format_order_text(paths: list[str], header: bool = True) -> str:
    lines: list[str] = []
    if header:
        lines.append("# Deposit file order - one path per line, top to bottom.")
        lines.append("# Blank lines and lines starting with '#' are ignored.")
        lines.append("")
    lines.extend(paths)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _match_entry(entry: str, files: list[DiscoveredFile]) -> tuple[list[str], str]:
    """Return (matching rel paths, match kind) for one order-list entry."""
    normalized = entry.strip().replace("\\", "/").lstrip("./")
    by_path = {f.rel_path: f for f in files}

    if normalized in by_path:
        return [normalized], SOURCE_LISTED

    lowered = normalized.lower()
    exact_ci = [f.rel_path for f in files if f.rel_path.lower() == lowered]
    if exact_ci:
        return exact_ci, SOURCE_LISTED

    if _GLOB_CHARS & set(normalized):
        import fnmatch

        hits = [f.rel_path for f in files if fnmatch.fnmatch(f.rel_path, normalized)]
        if not hits:
            hits = [f.rel_path for f in files if fnmatch.fnmatch(f.rel_path.lower(), lowered)]
        return sorted(hits), SOURCE_GLOB

    # Bare filename, or a trailing path fragment such as "core/layout.py".
    suffix = "/" + normalized
    hits = [
        f.rel_path
        for f in files
        if f.rel_path == normalized or f.rel_path.endswith(suffix)
    ]
    if not hits:
        hits = [
            f.rel_path
            for f in files
            if f.rel_path.lower() == lowered or f.rel_path.lower().endswith(suffix.lower())
        ]
    return sorted(hits), SOURCE_LISTED


def resolve_order(
    entries: list[str],
    files: list[DiscoveredFile],
    *,
    include_unlisted: bool = True,
    excluded: list[str] | None = None,
    disambiguations: dict[str, str] | None = None,
) -> OrderPlan:
    """Turn order-list entries plus discovered files into a final sequence."""
    plan = OrderPlan()
    excluded_set = {p.replace("\\", "/") for p in (excluded or [])}
    disambiguations = disambiguations or {}

    available = [f for f in files if f.rel_path not in excluded_set]
    plan.excluded = sorted(excluded_set & {f.rel_path for f in files})

    placed: set[str] = set()

    for entry in entries:
        hits, kind = _match_entry(entry, available)
        hits = [h for h in hits if h not in placed]
        if not hits:
            if any(_match_entry(entry, files)[0]):
                plan.warnings.append(f"Order entry '{entry}' matched only excluded or already-placed files.")
            else:
                plan.unmatched.append(entry)
            continue

        if len(hits) > 1 and kind != SOURCE_GLOB:
            chosen = disambiguations.get(entry)
            if chosen and chosen in hits:
                plan.ambiguities.append(Ambiguity(entry, hits, chosen))
                hits = [chosen]
            else:
                plan.ambiguities.append(Ambiguity(entry, hits))
                plan.warnings.append(
                    f"Order entry '{entry}' matches {len(hits)} files; all were included in path order."
                )

        for path in hits:
            if path in placed:
                continue
            placed.add(path)
            plan.items.append(OrderedItem(path, kind, entry))

    if include_unlisted:
        leftovers = [f for f in available if f.rel_path not in placed]
        for f in sorted(leftovers, key=default_sort_key):
            plan.items.append(OrderedItem(f.rel_path, SOURCE_UNLISTED))

    return plan


# ---------------------------------------------------------------------------
# Auto-suggested order
# ---------------------------------------------------------------------------


def _python_module_index(files: list[DiscoveredFile]) -> dict[str, str]:
    """Map dotted module names to relative paths."""
    index: dict[str, str] = {}
    for f in files:
        if not f.rel_path.endswith((".py", ".pyi")):
            continue
        parts = list(PurePosixPath(f.rel_path).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        if not parts:
            continue
        dotted = ".".join(parts)
        index.setdefault(dotted, f.rel_path)
        # Also index without the top-level package so 'core.layout' resolves
        # inside a src/ or package-rooted layout.
        for start in range(1, len(parts)):
            index.setdefault(".".join(parts[start:]), f.rel_path)
    return index


def _python_dependencies(text: str, rel_path: str, index: dict[str, str]) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    package_parts = list(PurePosixPath(rel_path).parent.parts)
    deps: list[str] = []

    def add(name: str) -> None:
        target = index.get(name)
        if target and target != rel_path and target not in deps:
            deps.append(target)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - node.level + 1]
                prefix = ".".join(base)
                module = f"{prefix}.{node.module}" if node.module else prefix
            else:
                module = node.module or ""
            if module:
                add(module)
            for alias in node.names:
                add(f"{module}.{alias.name}" if module else alias.name)
    return deps


def _include_dependencies(text: str, rel_path: str, files_by_path: dict[str, str]) -> list[str]:
    """Resolve #include "..." relative to the including file, then to the root."""
    here = PurePosixPath(rel_path).parent
    deps: list[str] = []
    for match in _INCLUDE_RE.finditer(text):
        target = match.group(1).replace("\\", "/")
        candidates = [str(here / target).replace("\\", "/").lstrip("./"), target]
        resolved = next((c for c in candidates if c in files_by_path), None)
        if resolved is None:
            suffix = "/" + PurePosixPath(target).name
            resolved = next(
                (p for p in files_by_path if p.endswith(suffix)),
                None,
            )
        if resolved and resolved != rel_path and resolved not in deps:
            deps.append(resolved)
    return deps


def _paired_header(rel_path: str, files_by_path: dict[str, str]) -> str | None:
    """The declaration that belongs with an implementation file."""
    p = PurePosixPath(rel_path)
    if p.suffix.lower() not in _IMPL_SUFFIXES:
        return None
    for suffix in _HEADER_SUFFIXES:
        candidate = str(p.with_suffix(suffix)).replace("\\", "/")
        if candidate in files_by_path:
            return candidate
    return None


def suggest_order(
    files: list[DiscoveredFile],
    read_text=None,
) -> list[str]:
    """Propose an order: entry points first, then their dependencies.

    Gives the deposit the 'objectively identifiable beginning and end' the
    Compendium asks for, instead of an arbitrary alphabetical walk.
    """
    if not files:
        return []
    if read_text is None:
        from .encoding import read_source

        def read_text(f: DiscoveredFile) -> str:  # type: ignore[misc]
            try:
                return read_source(f.abs_path).text
            except OSError:
                return ""

    files_by_path = {f.rel_path: f.abs_path for f in files}
    texts: dict[str, str] = {}
    for f in files:
        texts[f.rel_path] = read_text(f)

    module_index = _python_module_index(files)

    dependencies: dict[str, list[str]] = {}
    for f in files:
        text = texts.get(f.rel_path, "")
        if f.rel_path.endswith((".py", ".pyi")):
            dependencies[f.rel_path] = _python_dependencies(text, f.rel_path, module_index)
        else:
            dependencies[f.rel_path] = _include_dependencies(text, f.rel_path, files_by_path)

    # Rank entry points: known filenames first, then a main() signature.
    def entry_rank(f: DiscoveredFile) -> tuple[int, int, str]:
        name = PurePosixPath(f.rel_path).name.lower()
        depth = len(PurePosixPath(f.rel_path).parts) - 1
        if name in _ENTRY_NAMES:
            return (_ENTRY_NAMES.index(name), depth, f.rel_path.lower())
        text = texts.get(f.rel_path, "")
        if any(p.search(text) for p in _ENTRY_PATTERNS):
            return (len(_ENTRY_NAMES), depth, f.rel_path.lower())
        return (len(_ENTRY_NAMES) + 1, depth, f.rel_path.lower())

    ordered: list[str] = []
    seen: set[str] = set()

    def visit(path: str, stack: set[str]) -> None:
        if path in seen or path in stack:
            return
        stack.add(path)
        header = _paired_header(path, files_by_path)
        if header and header not in seen:
            visit(header, stack)
        seen.add(path)
        ordered.append(path)
        for dep in dependencies.get(path, []):
            visit(dep, stack)
        stack.discard(path)

    for f in sorted(files, key=entry_rank):
        visit(f.rel_path, set())

    # Anything unreachable (no entry point referenced it) keeps stable order.
    for f in sorted(files, key=default_sort_key):
        if f.rel_path not in seen:
            seen.add(f.rel_path)
            ordered.append(f.rel_path)
    return ordered
