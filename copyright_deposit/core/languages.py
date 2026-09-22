"""Language identification and comment syntax.

Drives three things: which stripper handles a file, how the third-party
scanner recognises a header comment, and which pygments lexer the
universal fallback should use.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Stripper families.
FAMILY_PYTHON = "python"
FAMILY_C = "c"  # C-like: // and /* */ with string/char literals
FAMILY_HASH = "hash"  # shell-style: # to end of line, no block comments
FAMILY_GENERIC = "generic"  # anything else -> pygments fallback


@dataclass(frozen=True)
class Language:
    name: str
    family: str
    line_comments: tuple[str, ...] = ()
    block_comments: tuple[tuple[str, str], ...] = ()
    pygments_alias: str = ""
    # C++11 raw strings R"tag(...)tag" and friends need special lexing.
    raw_strings: bool = False
    # Languages whose single-quote is a character literal, not a string.
    char_literals: bool = False


_C_LINE = ("//",)
_C_BLOCK = (("/*", "*/"),)


def _c_like(name: str, alias: str, *, raw: bool = False, chars: bool = True) -> Language:
    return Language(
        name=name,
        family=FAMILY_C,
        line_comments=_C_LINE,
        block_comments=_C_BLOCK,
        pygments_alias=alias,
        raw_strings=raw,
        char_literals=chars,
    )


def _hash_like(name: str, alias: str) -> Language:
    return Language(
        name=name,
        family=FAMILY_HASH,
        line_comments=("#",),
        pygments_alias=alias,
    )


PYTHON = Language(
    name="Python",
    family=FAMILY_PYTHON,
    line_comments=("#",),
    pygments_alias="python",
)

# Extension -> Language. Lower-cased keys; lookup lower-cases the suffix.
EXTENSION_MAP: dict[str, Language] = {
    ".py": PYTHON,
    ".pyi": PYTHON,
    ".pyx": PYTHON,
    ".pyw": PYTHON,
    ".c": _c_like("C", "c"),
    ".h": _c_like("C/C++ Header", "c"),
    ".cpp": _c_like("C++", "cpp", raw=True),
    ".cc": _c_like("C++", "cpp", raw=True),
    ".cxx": _c_like("C++", "cpp", raw=True),
    ".c++": _c_like("C++", "cpp", raw=True),
    ".hpp": _c_like("C++ Header", "cpp", raw=True),
    ".hh": _c_like("C++ Header", "cpp", raw=True),
    ".hxx": _c_like("C++ Header", "cpp", raw=True),
    ".inl": _c_like("C++ Inline", "cpp", raw=True),
    ".java": _c_like("Java", "java"),
    ".cs": _c_like("C#", "csharp"),
    ".js": _c_like("JavaScript", "javascript", chars=False),
    ".jsx": _c_like("JavaScript (JSX)", "jsx", chars=False),
    ".mjs": _c_like("JavaScript (ESM)", "javascript", chars=False),
    ".cjs": _c_like("JavaScript (CJS)", "javascript", chars=False),
    ".ts": _c_like("TypeScript", "typescript", chars=False),
    ".tsx": _c_like("TypeScript (TSX)", "tsx", chars=False),
    ".go": _c_like("Go", "go", raw=True),
    ".rs": _c_like("Rust", "rust", raw=True),
    ".swift": _c_like("Swift", "swift"),
    ".kt": _c_like("Kotlin", "kotlin"),
    ".kts": _c_like("Kotlin Script", "kotlin"),
    ".m": _c_like("Objective-C", "objective-c"),
    ".mm": _c_like("Objective-C++", "objective-c++"),
    ".scala": _c_like("Scala", "scala"),
    ".dart": _c_like("Dart", "dart"),
    ".php": _c_like("PHP", "php"),
    ".glsl": _c_like("GLSL", "glsl"),
    ".hlsl": _c_like("HLSL", "hlsl"),
    ".cu": _c_like("CUDA", "cuda", raw=True),
    ".sh": _hash_like("Shell", "bash"),
    ".bash": _hash_like("Bash", "bash"),
    ".zsh": _hash_like("Zsh", "bash"),
    ".rb": _hash_like("Ruby", "ruby"),
    ".pl": _hash_like("Perl", "perl"),
    ".pm": _hash_like("Perl Module", "perl"),
    ".r": _hash_like("R", "r"),
    ".jl": _hash_like("Julia", "julia"),
    ".yaml": _hash_like("YAML", "yaml"),
    ".yml": _hash_like("YAML", "yaml"),
    ".toml": _hash_like("TOML", "toml"),
    ".cmake": _hash_like("CMake", "cmake"),
    ".ps1": Language(
        name="PowerShell",
        family=FAMILY_GENERIC,
        line_comments=("#",),
        block_comments=(("<#", "#>"),),
        pygments_alias="powershell",
    ),
    ".sql": Language(
        name="SQL",
        family=FAMILY_GENERIC,
        line_comments=("--",),
        block_comments=_C_BLOCK,
        pygments_alias="sql",
    ),
    ".lua": Language(
        name="Lua",
        family=FAMILY_GENERIC,
        line_comments=("--",),
        block_comments=(("--[[", "]]"),),
        pygments_alias="lua",
    ),
    ".vb": Language(
        name="Visual Basic",
        family=FAMILY_GENERIC,
        line_comments=("'",),
        pygments_alias="vbnet",
    ),
    ".f90": Language(
        name="Fortran",
        family=FAMILY_GENERIC,
        line_comments=("!",),
        pygments_alias="fortran",
    ),
    ".html": Language(
        name="HTML",
        family=FAMILY_GENERIC,
        block_comments=(("<!--", "-->"),),
        pygments_alias="html",
    ),
    ".css": Language(
        name="CSS",
        family=FAMILY_GENERIC,
        block_comments=_C_BLOCK,
        pygments_alias="css",
    ),
    ".xml": Language(
        name="XML",
        family=FAMILY_GENERIC,
        block_comments=(("<!--", "-->"),),
        pygments_alias="xml",
    ),
}

# Files without a useful suffix.
FILENAME_MAP: dict[str, Language] = {
    "makefile": _hash_like("Makefile", "make"),
    "dockerfile": _hash_like("Dockerfile", "docker"),
    "cmakelists.txt": _hash_like("CMake", "cmake"),
}

UNKNOWN = Language(name="Unknown", family=FAMILY_GENERIC)


def detect(path: str | Path) -> Language:
    """Best-effort language for a path. Never raises."""
    p = Path(path)
    by_name = FILENAME_MAP.get(p.name.lower())
    if by_name is not None:
        return by_name
    return EXTENSION_MAP.get(p.suffix.lower(), UNKNOWN)


def is_supported_extension(path: str | Path, extensions: list[str]) -> bool:
    p = Path(path)
    if p.name.lower() in FILENAME_MAP:
        return True
    return p.suffix.lower() in {e.lower() for e in extensions}
