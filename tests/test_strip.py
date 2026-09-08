"""Stripper correctness.

Deleting real code from a legal filing is the worst thing this tool could
do, so these cases are the adversarial ones: comment tokens inside string
literals, raw strings, regex literals and preprocessor lines.
"""

from __future__ import annotations

import ast

import pytest

from copyright_deposit.config import TransformOptions
from copyright_deposit.core import languages
from copyright_deposit.core.strip import comments_only_lines, strip_source
from copyright_deposit.core.strip import cfamily_strip


def rendered(text: str, path: str, **options) -> str:
    result = strip_source(text, path, TransformOptions(**options))
    return "\n".join(line.text for line in result.lines)


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


def test_hash_inside_string_is_not_a_comment():
    source = 's = "# not a comment"  # this one is\n'
    assert rendered(source, "a.py") == 's = "# not a comment"'


def test_module_and_function_docstrings_removed():
    source = '"""Module."""\n\n\ndef f():\n    """Doc."""\n    return 1\n'
    out = rendered(source, "a.py")
    assert "Module." not in out
    assert "Doc." not in out
    assert "return 1" in out


def test_sole_docstring_survives_so_the_suite_stays_valid():
    """Removing it would leave `def f():` with an empty body."""
    source = 'def f():\n    """Only statement."""\n'
    out = rendered(source, "a.py")
    assert "Only statement." in out
    ast.parse(out)


def test_docstrings_kept_when_toggled_off():
    source = '"""Module."""\nx = 1  # tail\n'
    out = rendered(source, "a.py", strip_docstrings=False)
    assert "Module." in out
    assert "# tail" not in out


def test_comments_kept_when_toggled_off():
    source = '"""Module."""\nx = 1  # tail\n'
    out = rendered(source, "a.py", strip_comments=False)
    assert "# tail" in out
    assert "Module." not in out


def test_shebang_preserved_by_default():
    source = "#!/usr/bin/env python\n# other\nx = 1\n"
    assert rendered(source, "a.py").splitlines()[0] == "#!/usr/bin/env python"
    assert "# other" not in rendered(source, "a.py")


def test_legal_header_can_be_preserved():
    source = "# Copyright (c) 2026 Someone\n# All rights reserved.\n# ordinary note\nx = 1\n"
    out = rendered(source, "a.py", preserve_legal_headers=True)
    assert "Copyright (c) 2026 Someone" in out
    assert "ordinary note" not in out


@pytest.mark.parametrize(
    "source",
    [
        'x = "#"\n',
        "def f(a, b):\n    return a if a > b else b  # pick\n",
        'class C:\n    """Doc."""\n\n    def m(self):\n        """Doc."""\n        return {"#": 1}\n',
        "async def g():\n    # note\n    await h()\n",
        'f = f"{x!r} # not a comment"\n',
        "x = 1 # comment with 'quote\ny = 2\n",
    ],
)
def test_stripping_never_changes_the_parse_tree(source):
    out = rendered(source, "a.py")
    original = ast.parse(source)
    stripped = ast.parse(out)
    from copyright_deposit.core.strip.python_strip import _strip_all_docstrings

    assert ast.dump(_strip_all_docstrings(original)) == ast.dump(_strip_all_docstrings(stripped))


def test_unparseable_python_falls_back_without_crashing():
    source = "def broken(:\n  # comment\n  pass\n"
    result = strip_source(source, "a.py", TransformOptions())
    assert result.lines  # something was produced
    assert "comment" not in "\n".join(line.text for line in result.lines)


# ---------------------------------------------------------------------------
# C family
# ---------------------------------------------------------------------------


CPP_SOURCE = """#include <stdio.h>
// a real comment
int main() {
    const char* s = "/* not a comment */";
    const char* t = "// also not a comment";
    char c = '/';  // real
    const char* r = R"tag( */ // still a string )tag";
    /* block
       comment */
    int x = /* inline */ 5;
    return x;
}
"""


def test_cpp_keeps_strings_raw_strings_and_preprocessor():
    out = rendered(CPP_SOURCE, "a.cpp")
    assert "#include <stdio.h>" in out
    assert '"/* not a comment */"' in out
    assert '"// also not a comment"' in out
    assert 'R"tag( */ // still a string )tag"' in out
    assert "a real comment" not in out
    assert "block" not in out
    assert "int x =  5;" in out


def test_state_machine_agrees_with_pygments_on_cpp():
    """The fallback scanner must reach the same answer as the lexer."""
    language = languages.detect("a.cpp")
    spans, _ = cfamily_strip.find_spans(CPP_SOURCE, language)
    kept = CPP_SOURCE
    for start, end, _kind in sorted(spans, reverse=True):
        kept = kept[:start] + kept[end:]
    assert "#include <stdio.h>" in kept
    assert 'R"tag( */ // still a string )tag"' in kept
    assert "a real comment" not in kept


def test_javascript_regex_literal_is_not_mistaken_for_a_comment():
    source = "const re = /a\\/\\/b/; // real\nconst t = `tick // inside`;\nlet y = 10 / 2; // div\n"
    out = rendered(source, "a.js")
    assert "/a\\/\\/b/" in out
    assert "`tick // inside`" in out
    assert "10 / 2" in out
    assert "real" not in out and "div" not in out


def test_csharp_verbatim_string():
    source = 'var p = @"C:\\path\\\\ // not a comment";  // real\n'
    out = rendered(source, "a.cs")
    assert "// not a comment" in out
    assert "real" not in out


def test_rust_raw_string():
    source = 'let s = r#"contains // and /* */"#; // real\n'
    out = rendered(source, "a.rs")
    assert "contains // and /* */" in out
    assert "real" not in out


def test_unterminated_block_comment_is_reported():
    source = "int a = 1;\n/* never closed\nint b = 2;\n"
    result = strip_source(source, "a.c", TransformOptions())
    assert "int a = 1;" in "\n".join(line.text for line in result.lines)
    assert "int b" not in "\n".join(line.text for line in result.lines)


# ---------------------------------------------------------------------------
# Line numbering, whitespace, comment isolation
# ---------------------------------------------------------------------------


def test_original_line_numbers_are_preserved():
    source = "# one\n# two\nx = 1\n\n\n\ny = 2\n"
    result = strip_source(source, "a.py", TransformOptions())
    numbers = [line.number for line in result.lines]
    assert numbers[0] == 3  # x = 1 was on line 3
    assert numbers[-1] == 7  # y = 2 was on line 7


def test_blank_runs_are_collapsed():
    source = "x = 1\n\n\n\n\ny = 2\n"
    out = rendered(source, "a.py")
    assert out == "x = 1\n\ny = 2"


def test_blank_runs_kept_when_toggled_off():
    source = "x = 1\n\n\n\n\ny = 2\n"
    out = rendered(source, "a.py", collapse_blank_runs=False)
    assert out.count("\n") == 5


def test_tabs_are_expanded_to_keep_the_grid():
    source = "def f():\n\treturn 1\n"
    out = rendered(source, "a.py", tab_width=4)
    assert "    return 1" in out
    assert "\t" not in out


def test_comments_only_lines_blanks_code_but_keeps_numbering():
    source = "x = 1  # note\ny = 2\n# lone\n"
    result = strip_source(source, "a.py", TransformOptions())
    lines = comments_only_lines(source, result.comment_spans)
    assert len(lines) == len(source.split("\n"))
    assert "x = 1" not in lines[0]
    assert "# note" in lines[0]
    assert lines[1].strip() == ""
    assert "# lone" in lines[2]
