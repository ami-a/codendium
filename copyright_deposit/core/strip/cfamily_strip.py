"""Hand-written comment scanner used when pygments cannot be trusted.

A single pass over the text tracks whether we are in code, a string, a
character literal, a raw/verbatim string, or a comment. Only regions
entered through a comment token are reported, so the scanner can never
classify code as a comment by accident.

The awkward cases it exists to survive:

* ``"/* not a comment */"`` and ``"// not a comment"`` inside strings
* C++11 raw strings ``R"tag( */ )tag"``
* C# verbatim strings ``@"C:\\path"`` with ``""`` escapes
* Rust ``r#"..."#``, Go and JavaScript backtick strings
* C line-splicing, where a ``\\`` continues a ``//`` comment onto the next line
* JavaScript regex literals such as ``/a\\/\\/b/`` that contain ``//``
"""

from __future__ import annotations

from ..languages import FAMILY_C, Language
from . import KIND_COMMENT, KIND_SHEBANG, Span

# After one of these, a '/' in JavaScript begins a regex literal rather
# than a division. This is the standard disambiguation heuristic.
_REGEX_PRECEDERS = set("(,=:[!&|?{};+-*%^~<>") | {""}
_REGEX_KEYWORDS = ("return", "typeof", "instanceof", "in", "of", "new", "delete", "case", "do", "else", "yield", "await")

_RAW_PREFIXES = ("u8R", "LR", "uR", "UR", "R")


def _line_comment_end(text: str, start: int, splice: bool) -> int:
    """End offset of a line comment (exclusive of the newline)."""
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\n":
            if splice and i > start and text[i - 1] == "\\":
                i += 1
                continue
            return i
        i += 1
    return n


def _skip_quoted(text: str, start: int, quote: str, escapes: bool) -> int:
    """End offset (exclusive) of a quoted run beginning at `start`."""
    i = start + 1
    n = len(text)
    while i < n:
        ch = text[i]
        if escapes and ch == "\\":
            i += 2
            continue
        if ch == quote:
            return i + 1
        i += 1
    return n


def _skip_cpp_raw(text: str, quote_pos: int) -> int | None:
    """Handle R"delim( ... )delim" starting at the quote character."""
    i = quote_pos + 1
    n = len(text)
    delim_start = i
    while i < n and text[i] not in "( \t\n\\":
        i += 1
    if i >= n or text[i] != "(":
        return None
    delim = text[delim_start:i]
    closer = ")" + delim + '"'
    end = text.find(closer, i + 1)
    return n if end == -1 else end + len(closer)


def _has_raw_prefix(text: str, quote_pos: int) -> bool:
    for prefix in _RAW_PREFIXES:
        start = quote_pos - len(prefix)
        if start < 0 or text[start:quote_pos] != prefix:
            continue
        before = text[start - 1] if start > 0 else ""
        if before.isalnum() or before == "_":
            continue
        return True
    return False


def _skip_rust_raw(text: str, r_pos: int) -> int | None:
    """Handle r"..." and r#"..."# starting at the 'r'."""
    i = r_pos + 1
    hashes = 0
    while i < len(text) and text[i] == "#":
        hashes += 1
        i += 1
    if i >= len(text) or text[i] != '"':
        return None
    closer = '"' + "#" * hashes
    end = text.find(closer, i + 1)
    return len(text) if end == -1 else end + len(closer)


def _skip_regex(text: str, start: int) -> int:
    """End offset of a JavaScript regex literal beginning at '/'."""
    i = start + 1
    n = len(text)
    in_class = False
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "\n":
            return start + 1  # unterminated: treat the '/' as ordinary
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            return i + 1
        i += 1
    return start + 1


def _regex_allowed(text: str, index: int) -> bool:
    j = index - 1
    while j >= 0 and text[j] in " \t\r\n":
        j -= 1
    if j < 0:
        return True
    ch = text[j]
    if ch in _REGEX_PRECEDERS:
        return True
    if ch.isalnum() or ch == "_":
        end = j + 1
        while j >= 0 and (text[j].isalnum() or text[j] == "_"):
            j -= 1
        return text[j + 1 : end] in _REGEX_KEYWORDS
    return False


def find_spans(text: str, language: Language) -> tuple[list[Span], list[str]]:
    alias = language.pygments_alias
    is_js = alias in {"javascript", "jsx", "typescript", "tsx"}
    is_cpp = language.raw_strings and alias in {"cpp", "cuda"}
    is_rust = alias == "rust"
    is_csharp = alias == "csharp"
    backticks = language.raw_strings or is_js or alias == "go"
    splice = language.family == FAMILY_C

    line_tokens = sorted(language.line_comments, key=len, reverse=True)
    block_tokens = language.block_comments

    spans: list[Span] = []
    warnings: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # --- comments -----------------------------------------------------
        matched = False
        for open_tok, close_tok in block_tokens:
            if text.startswith(open_tok, i):
                end = text.find(close_tok, i + len(open_tok))
                if end == -1:
                    end = n
                    warnings.append("Unterminated block comment; stripped to end of file.")
                else:
                    end += len(close_tok)
                spans.append((i, end, KIND_COMMENT))
                i = end
                matched = True
                break
        if matched:
            continue

        for tok in line_tokens:
            if not text.startswith(tok, i):
                continue
            end = _line_comment_end(text, i, splice)
            kind = KIND_SHEBANG if i == 0 and text.startswith("#!") else KIND_COMMENT
            spans.append((i, end, kind))
            i = end
            matched = True
            break
        if matched:
            continue

        # --- literals that must not be scanned for comment tokens ---------
        if ch == '"':
            if is_cpp and _has_raw_prefix(text, i):
                end = _skip_cpp_raw(text, i)
                i = end if end is not None else _skip_quoted(text, i, '"', True)
                continue
            if is_csharp and i > 0 and text[i - 1] == "@":
                j = i + 1
                while j < n:
                    if text[j] == '"':
                        if j + 1 < n and text[j + 1] == '"':
                            j += 2
                            continue
                        j += 1
                        break
                    j += 1
                i = j
                continue
            if text.startswith('"""', i):  # Java/Kotlin/Swift text blocks
                end = text.find('"""', i + 3)
                i = n if end == -1 else end + 3
                continue
            i = _skip_quoted(text, i, '"', True)
            continue

        if ch == "'" and language.char_literals:
            i = _skip_quoted(text, i, "'", True)
            continue

        if ch == "`" and backticks:
            i = _skip_quoted(text, i, "`", alias != "go")
            continue

        if is_rust and ch == "r":
            end = _skip_rust_raw(text, i)
            if end is not None:
                i = end
                continue

        if is_js and ch == "/" and _regex_allowed(text, i):
            i = _skip_regex(text, i)
            continue

        i += 1

    return spans, warnings
