"""Fixture generators shared by the tests."""

from __future__ import annotations


def big_python_file(functions: int) -> str:
    """A file long enough to exercise the 50-page rule."""
    parts = ['"""Generated fixture."""', ""]
    for index in range(functions):
        parts.append(f"def function_{index:04d}(value):")
        parts.append(f"    # comment for {index}")
        parts.append(f'    """Docstring for {index}."""')
        parts.append(f"    total = value + {index}")
        parts.append("    return total")
        parts.append("")
    return "\n".join(parts)
