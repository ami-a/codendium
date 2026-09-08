"""Entry point.

With no arguments the GUI opens; with arguments the CLI runs, so the same
installation serves both an operator and a build script.
"""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) > 1:
        from .cli import main as cli_main

        return cli_main()

    try:
        from .gui.app import run
    except ImportError as exc:  # PySide6 missing
        print(
            "The GUI needs PySide6. Install it with:\n"
            "    py -m pip install PySide6\n"
            f"(import error: {exc})\n\n"
            "Or use the command line, for example:\n"
            "    py -m copyright_deposit estimate <folder> --what-if",
            file=sys.stderr,
        )
        return 1
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
