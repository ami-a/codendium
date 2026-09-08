"""Order resolution and the suggested dependency order."""

from __future__ import annotations

from copyright_deposit.core.discovery import discover
from copyright_deposit.core.ordering import (
    SOURCE_UNLISTED,
    format_order_text,
    parse_order_text,
    resolve_order,
    suggest_order,
)
from copyright_deposit.config import DiscoveryOptions

TREE = {
    "main.py": "from pkg.core import run\n\nif __name__ == '__main__':\n    run()\n",
    "pkg/__init__.py": "",
    "pkg/core.py": "from pkg.util import helper\n\ndef run():\n    return helper()\n",
    "pkg/util.py": "def helper():\n    return 1\n",
    "extra/util.py": "def other():\n    return 2\n",
    "notes.md": "not source",
}


def files_for(root):
    return discover(root, DiscoveryOptions(respect_gitignore=False)).files


# ---------------------------------------------------------------------------
# Order-list text
# ---------------------------------------------------------------------------


def test_parse_ignores_blanks_and_comments():
    text = "# a comment\n\nmain.py\n  pkg/core.py  \n"
    assert parse_order_text(text) == ["main.py", "pkg/core.py"]


def test_backslash_paths_are_normalised():
    assert parse_order_text("pkg\\core.py\n") == ["pkg/core.py"]


def test_format_round_trips():
    paths = ["main.py", "pkg/core.py"]
    assert parse_order_text(format_order_text(paths)) == paths


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_exact_paths_are_placed_in_order(make_tree):
    files = files_for(make_tree(TREE))
    plan = resolve_order(["pkg/core.py", "main.py"], files)
    assert plan.paths[:2] == ["pkg/core.py", "main.py"]


def test_unlisted_files_are_appended_and_flagged(make_tree):
    files = files_for(make_tree(TREE))
    plan = resolve_order(["main.py"], files)
    assert plan.items[0].rel_path == "main.py"
    assert plan.items[0].source != SOURCE_UNLISTED
    assert all(item.source == SOURCE_UNLISTED for item in plan.items[1:])
    assert set(plan.paths) == {f.rel_path for f in files}


def test_unlisted_files_can_be_dropped(make_tree):
    files = files_for(make_tree(TREE))
    plan = resolve_order(["main.py"], files, include_unlisted=False)
    assert plan.paths == ["main.py"]


def test_bare_filename_resolves_when_unique(make_tree):
    files = files_for(make_tree(TREE))
    plan = resolve_order(["core.py"], files)
    assert plan.paths[0] == "pkg/core.py"
    assert not plan.ambiguities


def test_ambiguous_bare_name_is_reported_not_guessed(make_tree):
    files = files_for(make_tree(TREE))
    plan = resolve_order(["util.py"], files)
    assert len(plan.ambiguities) == 1
    ambiguity = plan.ambiguities[0]
    assert ambiguity.entry == "util.py"
    assert set(ambiguity.candidates) == {"pkg/util.py", "extra/util.py"}
    assert any("matches 2 files" in w for w in plan.warnings)


def test_ambiguity_can_be_resolved_explicitly(make_tree):
    files = files_for(make_tree(TREE))
    plan = resolve_order(["util.py"], files, disambiguations={"util.py": "pkg/util.py"})
    assert plan.paths[0] == "pkg/util.py"
    assert plan.ambiguities[0].chosen == "pkg/util.py"


def test_glob_entries_expand_in_path_order(make_tree):
    files = files_for(make_tree(TREE))
    plan = resolve_order(["pkg/*.py"], files, include_unlisted=False)
    # pkg/__init__.py is empty, so discovery skips it: an empty file
    # contributes nothing to the deposit.
    assert plan.paths == ["pkg/core.py", "pkg/util.py"]


def test_empty_files_are_skipped_with_a_reason(make_tree):
    from copyright_deposit.core.discovery import SKIP_EMPTY

    result = discover(make_tree(TREE), DiscoveryOptions(respect_gitignore=False))
    skipped = {s.rel_path: s.reason for s in result.skipped}
    assert skipped.get("pkg/__init__.py") == SKIP_EMPTY


def test_non_source_files_are_not_discovered(make_tree):
    paths = {f.rel_path for f in files_for(make_tree(TREE))}
    assert "notes.md" not in paths


def test_unmatched_entries_are_reported(make_tree):
    files = files_for(make_tree(TREE))
    plan = resolve_order(["nope.py"], files)
    assert plan.unmatched == ["nope.py"]


def test_excluded_files_never_appear(make_tree):
    files = files_for(make_tree(TREE))
    plan = resolve_order([], files, excluded=["extra/util.py"])
    assert "extra/util.py" not in plan.paths
    assert plan.excluded == ["extra/util.py"]


def test_a_file_is_never_placed_twice(make_tree):
    files = files_for(make_tree(TREE))
    plan = resolve_order(["main.py", "main.py"], files)
    assert plan.paths.count("main.py") == 1


# ---------------------------------------------------------------------------
# Suggested order
# ---------------------------------------------------------------------------


def test_suggested_order_starts_at_the_entry_point(make_tree):
    files = files_for(make_tree(TREE))
    order = suggest_order(files)
    assert order[0] == "main.py"
    assert set(order) == {f.rel_path for f in files}


def test_suggested_order_follows_imports(make_tree):
    files = files_for(make_tree(TREE))
    order = suggest_order(files)
    assert order.index("pkg/core.py") < order.index("pkg/util.py")


def test_suggested_order_puts_headers_before_implementations(make_tree):
    root = make_tree(
        {
            "main.cpp": '#include "engine.h"\nint main() { return 0; }\n',
            "engine.h": "#pragma once\nvoid go();\n",
            "engine.cpp": '#include "engine.h"\nvoid go() {}\n',
        }
    )
    order = suggest_order(files_for(root))
    assert order[0] == "main.cpp"
    assert order.index("engine.h") < order.index("engine.cpp")


def test_suggested_order_survives_an_import_cycle(make_tree):
    root = make_tree(
        {
            "main.py": "import a\n",
            "a.py": "import b\n",
            "b.py": "import a\n",
        }
    )
    order = suggest_order(files_for(root))
    assert sorted(order) == ["a.py", "b.py", "main.py"]
