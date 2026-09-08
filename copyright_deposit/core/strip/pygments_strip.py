"""Universal comment classification via pygments.

Two safeguards make this trustworthy enough to be the default path for
non-Python languages:

1. **Round-trip verification.** The concatenated token values must equal
   the source exactly. If a lexer drops or rewrites anything, we refuse
   the result and the caller falls back to the state machine.
2. **Preprocessor tokens are never treated as comments.** pygments maps
   ``#include`` / ``#define`` to ``Comment.Preproc``; removing those would
   quietly delete real code from the deposit.
"""

from __future__ import annotations

from pygments.token import Comment, String, Token

from ..languages import Language
from . import KIND_COMMENT, KIND_DOCSTRING, KIND_SHEBANG, Span

_PREPROC = (Token.Comment.Preproc, Token.Comment.PreprocFile)


def _lexer_for(language: Language):
    from pygments.lexers import get_lexer_by_name

    if not language.pygments_alias:
        return None
    try:
        return get_lexer_by_name(language.pygments_alias, stripnl=False, ensurenl=False)
    except Exception:
        return None


def _is_preproc(ttype) -> bool:
    return any(ttype in p for p in _PREPROC)


def _classify(ttype) -> str | None:
    if ttype in Token.Comment.Hashbang:
        return KIND_SHEBANG
    if ttype in String.Doc:
        return KIND_DOCSTRING
    if ttype in Comment and not _is_preproc(ttype):
        return KIND_COMMENT
    return None


def find_spans(text: str, language: Language) -> tuple[list[Span] | None, list[str]]:
    """Return classified spans, or ``None`` if pygments cannot be trusted."""
    lexer = _lexer_for(language)
    if lexer is None:
        return None, []

    try:
        tokens = list(lexer.get_tokens_unprocessed(text))
    except Exception as exc:  # a lexer crash must never abort a build
        return None, [f"Lexer for {language.name} failed ({exc.__class__.__name__})."]

    # Round-trip check: the token stream must reconstruct the source.
    rebuilt_length = 0
    for index, _ttype, value in tokens:
        if index != rebuilt_length:
            return None, [
                f"Lexer output for {language.name} did not reconstruct the source; "
                "using the fallback comment scanner."
            ]
        rebuilt_length += len(value)
    if rebuilt_length != len(text):
        return None, [
            f"Lexer output for {language.name} was truncated; using the fallback scanner."
        ]

    spans: list[Span] = []
    for index, ttype, value in tokens:
        kind = _classify(ttype)
        if kind is None or not value:
            continue
        end = index + len(value)
        # A trailing newline belongs to the layout, not to the comment.
        while end > index and text[end - 1] == "\n":
            end -= 1
        if end > index:
            spans.append((index, end, kind))
    return spans, []
