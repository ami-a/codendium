"""Comment and docstring removal.

Design
------
Strippers never rewrite code. They *classify* byte ranges of the original
text as comment/docstring, and a single shared routine removes those
ranges. Removal is therefore provably subtractive: nothing that was not
classified as a comment can ever be altered.

Dispatch, in order of trustworthiness:

* Python   -> ``tokenize`` + ``ast``. Authoritative, and the result is
  checked by comparing the ASTs of the original and stripped source.
* Others   -> pygments, whose token stream is verified to reconstruct the
  source exactly before it is trusted.
* Fallback -> a hand-written C-family state machine (also used when no
  lexer exists or the pygments round-trip fails).

The pygments path deliberately keeps ``Comment.Preproc`` tokens: C lexers
classify ``#include`` and ``#define`` as comments, and deleting those
would silently gut the deposit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...config import LEGAL_HEADER_PATTERN, TransformOptions
from .. import languages
from ..languages import FAMILY_C, FAMILY_HASH, FAMILY_PYTHON, Language

KIND_COMMENT = "comment"
KIND_DOCSTRING = "docstring"
KIND_SHEBANG = "shebang"

Span = tuple[int, int, str]  # (start offset, end offset, kind)

_LEGAL_RE = re.compile(LEGAL_HEADER_PATTERN, re.IGNORECASE)


@dataclass
class SourceLine:
    """One physical line of the stripped source."""

    number: int  # 1-based line number in the ORIGINAL file
    text: str


@dataclass
class StripResult:
    lines: list[SourceLine] = field(default_factory=list)
    method: str = "none"
    removed_lines: int = 0
    warnings: list[str] = field(default_factory=list)
    # Every classified comment/docstring span, before the keep-policy
    # toggles are applied. The third-party scanner reads these so it only
    # inspects real comments instead of matching prose inside code.
    comment_spans: list[Span] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return len(self.lines)


# ---------------------------------------------------------------------------
# Offset helpers
# ---------------------------------------------------------------------------


def line_start_offsets(text: str) -> list[int]:
    """Offset of the first character of each 1-based line (index 0 unused)."""
    starts = [0, 0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def rowcol_to_offset(starts: list[int], row: int, col: int) -> int:
    if row < 1 or row >= len(starts):
        return len(starts) and starts[-1]
    return starts[row] + col


# ---------------------------------------------------------------------------
# Span post-processing
# ---------------------------------------------------------------------------


def merge_spans(spans: list[Span]) -> list[Span]:
    """Sort and coalesce overlapping spans."""
    if not spans:
        return []
    spans = sorted(spans, key=lambda s: (s[0], s[1]))
    merged: list[Span] = [spans[0]]
    for start, end, kind in spans[1:]:
        last_start, last_end, last_kind = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end), last_kind or kind)
        else:
            merged.append((start, end, kind))
    return merged


def _filter_spans(text: str, spans: list[Span], options: TransformOptions) -> list[Span]:
    """Apply the keep-policy toggles to classified spans."""
    kept: list[Span] = []
    for start, end, kind in spans:
        if kind == KIND_SHEBANG:
            if options.preserve_shebang:
                continue
            if not options.strip_comments:
                continue
            kept.append((start, end, kind))
            continue
        if kind == KIND_DOCSTRING:
            if options.strip_docstrings:
                kept.append((start, end, kind))
            continue
        if options.strip_comments:
            kept.append((start, end, kind))
    if not options.preserve_legal_headers:
        return kept
    return _keep_legal_header(text, kept)


def _keep_legal_header(text: str, spans: list[Span]) -> list[Span]:
    """Drop the leading comment block from the kill list if it reads as legal.

    Only comments appearing before the first line of real code qualify: a
    licence notice buried mid-file is not the header the Office asks for.
    """
    if not spans:
        return spans
    result: list[Span] = []
    for index, (start, end, kind) in enumerate(spans):
        if kind == KIND_DOCSTRING and index > 0:
            result.append((start, end, kind))
            continue
        before = text[:start]
        # "Leading" means only whitespace and other comments precede it.
        stripped_before = before
        for prev_start, prev_end, _ in spans[:index]:
            stripped_before = (
                stripped_before[:prev_start] + " " * (prev_end - prev_start) + stripped_before[prev_end:]
            )
        if stripped_before.strip():
            result.append((start, end, kind))
            continue
        if _LEGAL_RE.search(text[start:end]):
            continue  # preserved
        result.append((start, end, kind))
    return result


# ---------------------------------------------------------------------------
# Removal
# ---------------------------------------------------------------------------


def apply_spans(text: str, spans: list[Span]) -> list[SourceLine]:
    """Remove the spans and rebuild lines, tracking original line numbers.

    Removal joins fragments across a multi-line comment, which is what a
    reader expects: ``int x = /* note\\n more */ 5;`` becomes ``int x =  5;``.
    """
    spans = merge_spans(spans)
    lines: list[SourceLine] = []
    buf: list[str] = []
    orig_line = 1
    line_started_at = 1
    span_index = 0
    i = 0
    length = len(text)

    while i < length:
        if span_index < len(spans) and i == spans[span_index][0]:
            _, end, _ = spans[span_index]
            # Count newlines swallowed by the comment so numbering stays true.
            orig_line += text.count("\n", i, end)
            i = end
            span_index += 1
            continue
        ch = text[i]
        if ch == "\n":
            lines.append(SourceLine(line_started_at, "".join(buf)))
            buf = []
            orig_line += 1
            line_started_at = orig_line
            i += 1
            continue
        buf.append(ch)
        i += 1

    if buf:
        lines.append(SourceLine(line_started_at, "".join(buf)))
    return lines


def comments_only_lines(text: str, spans: list[Span]) -> list[str]:
    """The file with every non-comment character blanked out.

    Line numbering is preserved exactly, so a scanner can report a hit at
    its true location while never seeing a character of actual code.
    """
    keep = bytearray(len(text))
    for start, end, _kind in spans:
        for i in range(max(0, start), min(len(text), end)):
            keep[i] = 1
    out = [
        ch if (ch == "\n" or keep[i]) else " "
        for i, ch in enumerate(text)
    ]
    return "".join(out).split("\n")


def _blank_original_lines(text: str) -> set[int]:
    return {n for n, raw in enumerate(text.split("\n"), start=1) if not raw.strip()}


def postprocess(
    lines: list[SourceLine],
    original_text: str,
    options: TransformOptions,
) -> list[SourceLine]:
    """Tabs, trailing whitespace, comment-only line removal, blank collapsing."""
    originally_blank = _blank_original_lines(original_text)

    staged: list[SourceLine] = []
    for line in lines:
        text = line.text
        if options.expand_tabs:
            text = text.expandtabs(options.tab_width)
        if options.trim_trailing_whitespace:
            text = text.rstrip()
        if not text.strip() and line.number not in originally_blank:
            # The line held nothing but a comment; drop it entirely.
            continue
        staged.append(SourceLine(line.number, text))

    if options.collapse_blank_runs:
        collapsed: list[SourceLine] = []
        run = 0
        for line in staged:
            if line.text.strip():
                run = 0
                collapsed.append(line)
                continue
            run += 1
            if run <= max(0, options.max_blank_run):
                collapsed.append(line)
        staged = collapsed

    while staged and not staged[0].text.strip():
        staged.pop(0)
    while staged and not staged[-1].text.strip():
        staged.pop()
    return staged


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def find_spans(text: str, language: Language) -> tuple[list[Span], str, list[str]]:
    """Classify comment/docstring ranges. Returns (spans, method, warnings)."""
    from . import cfamily_strip, pygments_strip, python_strip

    if language.family == FAMILY_PYTHON:
        spans, warnings = python_strip.find_spans(text)
        if spans is not None:
            return spans, "python-tokenize", warnings

    spans, warnings = pygments_strip.find_spans(text, language)
    if spans is not None:
        return spans, "pygments", warnings

    if language.family == FAMILY_C:
        spans, w2 = cfamily_strip.find_spans(text, language)
        return spans, "c-state-machine", warnings + w2

    if language.family in (FAMILY_HASH, FAMILY_PYTHON) or language.line_comments:
        spans, w2 = cfamily_strip.find_spans(text, language)
        return spans, "line-scanner", warnings + w2

    return [], "none", warnings + ["No comment syntax known; source kept verbatim."]


def strip_source(
    text: str,
    path: str,
    options: TransformOptions,
    language: Language | None = None,
) -> StripResult:
    """Strip `text` according to `options`, returning renderable lines."""
    language = language or languages.detect(path)
    result = StripResult()

    # Spans are always classified, even when nothing will be removed: the
    # third-party scanner needs to know which regions are comments.
    all_spans, method, warnings = find_spans(text, language)
    all_spans = merge_spans(all_spans)
    result.comment_spans = all_spans
    result.method = method
    result.warnings.extend(warnings)

    if not (options.strip_comments or options.strip_docstrings):
        result.method = "verbatim"
        raw_lines = [SourceLine(n, t) for n, t in enumerate(text.split("\n"), start=1)]
        result.lines = postprocess(raw_lines, text, options)
        return result

    spans = _filter_spans(text, all_spans, options)
    stripped_lines = apply_spans(text, spans)

    # Safety net: for Python the transform must not change the parse tree.
    if language.family == FAMILY_PYTHON and spans:
        from . import python_strip

        rebuilt = "\n".join(line.text for line in stripped_lines)
        ok, message = python_strip.verify_equivalent(text, rebuilt, options)
        if not ok:
            result.warnings.append(
                f"Comment removal changed the parse tree ({message}); "
                "the original source was kept for this file."
            )
            raw_lines = [SourceLine(n, t) for n, t in enumerate(text.split("\n"), start=1)]
            result.lines = postprocess(raw_lines, text, options)
            result.method = "verbatim (verification failed)"
            return result

    original_count = text.count("\n") + 1
    result.lines = postprocess(stripped_lines, text, options)
    result.removed_lines = max(0, original_count - len(result.lines))
    return result
