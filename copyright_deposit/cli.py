"""Headless entry point.

Everything the GUI can do is available here, which keeps the pipeline
testable without Qt and makes builds reproducible from a script or CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import BuildSettings
from .core import lineranges, ordering
from .core.deposit import MODE_ENTIRE
from .core.discovery import git_revision
from .core.pipeline import Pipeline


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("root", help="folder containing the source code")
    parser.add_argument("-o", "--output", default="out", help="output folder (default: out)")
    parser.add_argument("--basename", default="deposit", help="output file prefix")
    parser.add_argument("--order-file", help="text file listing the deposit order, one path per line")
    parser.add_argument("--settings", help="load a saved settings JSON file")

    ident = parser.add_argument_group("identification block")
    ident.add_argument("--name", help="program name")
    ident.add_argument("--program-version", help="program version, e.g. 1.0.0")
    ident.add_argument("--owner", help="copyright owner")
    ident.add_argument("--year", help="copyright year")
    ident.add_argument("--date", help="release/build date (YYYY-MM-DD)")
    ident.add_argument("--revision", help="source revision; use 'auto' to read git HEAD")

    policy = parser.add_argument_group("comment policy")
    policy.add_argument("--keep-comments", action="store_true", help="do not strip comments")
    policy.add_argument("--keep-docstrings", action="store_true", help="do not strip docstrings")
    policy.add_argument(
        "--preserve-legal-headers",
        action="store_true",
        help="keep leading comment blocks that carry a copyright or licence notice",
    )
    policy.add_argument("--no-collapse-blanks", action="store_true", help="keep blank-line runs")

    page = parser.add_argument_group("page grid")
    page.add_argument("--page-size", choices=["letter", "a4"], help="default: letter")
    page.add_argument("--font-size", type=float, help="default: 9.5")
    page.add_argument("--lines-per-page", type=int, help="default: 40")
    page.add_argument("--line-numbers", action="store_true", help="show original source line numbers")
    page.add_argument("--font", help="'Courier' or a path to a monospaced .ttf")

    other = parser.add_argument_group("other")
    other.add_argument("--exclude", action="append", default=[], help="relative path to exclude (repeatable)")
    other.add_argument(
        "--lines",
        action="append",
        default=[],
        metavar="PATH=RANGES",
        help="deposit only part of a file, e.g. --lines src/core.py=1-50,120-200 (repeatable)",
    )
    other.add_argument("--no-unlisted", action="store_true", help="include only files named in the order list")
    other.add_argument("--redact", action="store_true", help="enable trade-secret redaction")
    other.add_argument("--redact-regex", action="append", default=[], help="redaction pattern (repeatable)")
    other.add_argument("--no-scan", action="store_true", help="skip the secret and third-party scans")


def _settings_from_args(args: argparse.Namespace) -> BuildSettings:
    if getattr(args, "settings", None):
        settings = BuildSettings.from_json(Path(args.settings).read_text(encoding="utf-8"))
    else:
        settings = BuildSettings()

    settings.source_root = str(Path(args.root).resolve())
    settings.output_dir = str(Path(args.output).resolve())
    settings.output_basename = args.basename

    if args.order_file:
        settings.order_entries = ordering.parse_order_text(
            Path(args.order_file).read_text(encoding="utf-8")
        )

    header = settings.header
    if args.name:
        header.program_name = args.name
    if args.program_version:
        header.version = args.program_version
    if args.owner:
        header.copyright_owner = args.owner
    if args.year:
        header.copyright_year = args.year
    if args.date:
        header.release_date = args.date
    if args.revision:
        header.revision = git_revision(settings.source_root) if args.revision == "auto" else args.revision

    transform = settings.transform
    if args.keep_comments:
        transform.strip_comments = False
    if args.keep_docstrings:
        transform.strip_docstrings = False
    if args.preserve_legal_headers:
        transform.preserve_legal_headers = True
    if args.no_collapse_blanks:
        transform.collapse_blank_runs = False

    layout = settings.layout
    if args.page_size:
        layout.page_size = args.page_size
    if args.font_size:
        layout.font_size = args.font_size
    if args.lines_per_page:
        layout.lines_per_page = args.lines_per_page
    if args.line_numbers:
        layout.show_line_numbers = True
    if args.font:
        layout.font_name = args.font

    settings.excluded = list(args.exclude)
    settings.include_unlisted = not args.no_unlisted

    for entry in args.lines:
        path, separator, spec = entry.partition("=")
        if not separator:
            raise SystemExit(f"error: --lines expects PATH=RANGES, got '{entry}'")
        path = path.strip().replace("\\", "/").lstrip("./")
        error = lineranges.validate(spec)
        if error:
            raise SystemExit(f"error: --lines {path}: {error}")
        settings.line_ranges[path] = spec.strip()
    if args.redact or args.redact_regex:
        settings.redaction.enabled = True
        settings.redaction.regexes.extend(args.redact_regex)
    if args.no_scan:
        settings.scan.scan_secrets = False
        settings.scan.scan_third_party = False

    return settings


def _progress(stage: str, current: int, total: int) -> None:
    if total <= 1:
        sys.stderr.write(f"\r{stage}...")
    else:
        sys.stderr.write(f"\r{stage}: {current}/{total}   ")
    sys.stderr.flush()


def _report(estimate, show_what_if: list | None = None) -> None:
    selection = estimate.selection
    print()
    print(f"Files included    : {len(estimate.prepared)}")
    print(f"Page grid         : {estimate.geometry_note}")
    print(f"Complete program  : {estimate.page_count} page(s)")
    if selection.mode == MODE_ENTIRE:
        print("Deposit rule      : 50 pages or fewer - the entire program is deposited")
    else:
        first, last = selection.omitted or (0, 0)
        print(
            f"Deposit rule      : over 50 pages - first {estimate.settings.deposit.head_pages} "
            f"and last {estimate.settings.deposit.tail_pages} pages "
            f"(pages {first}-{last} omitted)"
        )
    print(f"Pages deposited   : {selection.deposited_pages}")

    omitted_files = estimate.omitted_files()
    if omitted_files:
        print(f"\nFiles the Office will not see ({len(omitted_files)}):")
        for path in omitted_files[:10]:
            print(f"  - {path}")
        if len(omitted_files) > 10:
            print(f"  ... and {len(omitted_files) - 10} more")

    if show_what_if:
        print("\nPage count by comment policy:")
        for label, pages, mode in show_what_if:
            print(f"  {label:<30} {pages:>5} pages  ({mode})")

    secrets = estimate.scan.sorted_secrets()
    if secrets:
        print(f"\nSecret/PII findings ({len(secrets)}):")
        for finding in secrets[:10]:
            print(f"  [{finding.severity:>6}] {finding.location()} - {finding.detail} ({finding.excerpt})")
        if len(secrets) > 10:
            print(f"  ... and {len(secrets) - 10} more")

    third_party = estimate.scan.sorted_third_party()
    if third_party:
        print(f"\nThird-party indicators ({len(third_party)}):")
        for finding in third_party[:10]:
            print(f"  [{finding.severity:>6}] {finding.location()} - {finding.detail}")
        if len(third_party) > 10:
            print(f"  ... and {len(third_party) - 10} more")

    if estimate.warnings:
        print(f"\nWarnings ({len(estimate.warnings)}):")
        for warning in estimate.warnings[:15]:
            print(f"  - {warning}")
        if len(estimate.warnings) > 15:
            print(f"  ... and {len(estimate.warnings) - 15} more")


def cmd_estimate(args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)
    pipeline = Pipeline()
    estimate = pipeline.estimate(settings, progress=_progress)
    what_if = pipeline.what_if(settings, progress=_progress) if args.what_if else None
    _report(estimate, what_if)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)
    pipeline = Pipeline()
    result = pipeline.build(settings, progress=_progress, force=args.force)
    _report(result.estimate)

    if result.blocked_by:
        print("\nBUILD BLOCKED: possible credentials found in the selected files.")
        for finding in result.blocked_by:
            print(f"  {finding.location()} - {finding.detail} ({finding.excerpt})")
        print("\nRemove them, redact them with --redact, or re-run with --force.")
        return 2

    print("\nWritten:")
    for path in result.outputs:
        print(f"  {path}")
    if result.manifest_path:
        print(f"  {result.manifest_path}")
        print(f"  {result.summary_path}")
    print(f"\nStatement for the application:\n  {result.estimate.selection.filing_statement()}")
    return 0


def cmd_suggest_order(args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)
    pipeline = Pipeline()
    found = pipeline.discover(settings)
    suggested = ordering.suggest_order(found.files)
    text = ordering.format_order_text(suggested)
    if args.write:
        Path(args.write).write_text(text, encoding="utf-8")
        print(f"Wrote {len(suggested)} entries to {args.write}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_save_settings(args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)
    Path(args.write).write_text(settings.to_json(), encoding="utf-8")
    print(f"Wrote settings to {args.write}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="copyright-deposit",
        description="Build US Copyright Office compliant source-code deposit PDFs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    estimate = sub.add_parser("estimate", help="report the page count without rendering a PDF")
    _add_common(estimate)
    estimate.add_argument("--what-if", action="store_true", help="compare page counts across comment policies")
    estimate.set_defaults(func=cmd_estimate)

    build = sub.add_parser("build", help="render the deposit PDFs")
    _add_common(build)
    build.add_argument("--force", action="store_true", help="build even if credentials were found")
    build.set_defaults(func=cmd_build)

    suggest = sub.add_parser("suggest-order", help="propose a deposit order from the code structure")
    _add_common(suggest)
    suggest.add_argument("--write", help="write the order list to this file")
    suggest.set_defaults(func=cmd_suggest_order)

    save = sub.add_parser("save-settings", help="write the resolved settings to JSON")
    _add_common(save)
    save.add_argument("--write", required=True, help="destination JSON file")
    save.set_defaults(func=cmd_save_settings)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
