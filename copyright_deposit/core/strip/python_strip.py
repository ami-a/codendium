"""Python comment and docstring classification.

``tokenize`` is authoritative for comments: it cannot be fooled by a ``#``
inside a string literal, which is exactly where regex-based strippers go
wrong. ``ast`` supplies docstring positions.

One rule deserves emphasis: a docstring that is the *only* statement in a
function or class is never removed, because deleting it would leave an
empty suite and turn valid source into a syntax error. The deposit must
still be the program.
"""

from __future__ import annotations

import ast
import io
import tokenize

from . import KIND_COMMENT, KIND_DOCSTRING, KIND_SHEBANG, Span, line_start_offsets

_DOCSTRING_PARENTS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def find_spans(text: str) -> tuple[list[Span] | None, list[str]]:
    """Classify comments and docstrings.

    Returns ``(None, warnings)`` if the file cannot be tokenised, so the
    caller can fall back to a more forgiving lexer.
    """
    warnings: list[str] = []
    starts = line_start_offsets(text)
    spans: list[Span] = []

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError) as exc:
        return None, [f"Python tokenizer failed ({exc.__class__.__name__}); using fallback lexer."]

    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        start = starts[tok.start[0]] + tok.start[1]
        end = starts[tok.end[0]] + tok.end[1]
        kind = KIND_SHEBANG if tok.start[0] == 1 and tok.string.startswith("#!") else KIND_COMMENT
        spans.append((start, end, kind))

    doc_spans, doc_warnings = _docstring_spans(text, starts)
    spans.extend(doc_spans)
    warnings.extend(doc_warnings)
    return spans, warnings


def _docstring_spans(text: str, starts: list[int]) -> tuple[list[Span], list[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], [f"Could not parse for docstrings ({exc.msg}); docstrings kept."]

    spans: list[Span] = []
    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_PARENTS):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            continue
        # Removing the sole statement of a suite would break the syntax.
        if len(body) == 1 and not isinstance(node, ast.Module):
            continue
        if first.end_lineno is None or first.end_col_offset is None:
            continue
        start = starts[first.lineno] + first.col_offset
        end = starts[first.end_lineno] + first.end_col_offset
        spans.append((start, end, KIND_DOCSTRING))
    return spans, []


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _strip_all_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_PARENTS):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            rest = body[1:]
            # A module may legitimately become empty; a suite may not, so it
            # gets a Pass. Both sides of the comparison normalise the same
            # way, which keeps a docstring-only module from looking changed.
            node.body = rest if isinstance(node, ast.Module) else (rest or [ast.Pass()])
    return tree


def verify_equivalent(original: str, stripped: str, options) -> tuple[bool, str]:
    """Confirm stripping did not change the program.

    Compares ASTs with all docstrings normalised away, so the check is
    independent of the docstring policy. If the *original* does not parse
    there is nothing to verify against and the check passes.
    """
    try:
        original_tree = ast.parse(original)
    except SyntaxError:
        return True, "original not parseable; nothing to verify"

    try:
        stripped_tree = ast.parse(stripped)
    except SyntaxError as exc:
        return False, f"stripped source no longer parses: line {exc.lineno}"

    left = ast.dump(_strip_all_docstrings(original_tree), include_attributes=False)
    right = ast.dump(_strip_all_docstrings(stripped_tree), include_attributes=False)
    if left != right:
        return False, "abstract syntax trees differ"
    return True, "ok"
