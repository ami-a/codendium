"""Pipeline orchestration.

Estimating and building share every stage up to and including layout, so
the page count shown in the GUI is the page count of the PDF - not an
approximation of it.

Results are cached on the file's SHA-256 plus the options that affect that
stage, which is what makes flipping a comment toggle re-estimate instantly
instead of re-reading and re-lexing the whole tree.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..config import BuildSettings, TransformOptions
from . import deposit as deposit_mod
from . import layout as layout_mod
from . import lineranges, metrics, ordering, redaction
from .discovery import DiscoveredFile, DiscoveryResult, discover
from .encoding import read_source
from .layout import FileBlock, LayoutResult
from .ordering import OrderPlan
from .scanning import Finding, ScanReport
from .scanning import secrets as secrets_mod
from .scanning import thirdparty as thirdparty_mod
from .strip import StripResult, comments_only_lines, strip_source

Progress = Callable[[str, int, int], None]


def _noop(stage: str, current: int, total: int) -> None:
    return None


@dataclass
class PreparedFile:
    rel_path: str
    abs_path: str
    original_text: str
    strip: StripResult
    redaction: redaction.FileRedaction
    selection: lineranges.Selection = field(default_factory=lineranges.Selection)
    range_spec: str = ""
    total_lines: int = 0
    language: str = ""
    encoding: str = ""
    sha256: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def lines(self) -> list:
        """The lines that actually reach the page."""
        return self.selection.lines


@dataclass
class EstimateResult:
    settings: BuildSettings
    discovery: DiscoveryResult
    plan: OrderPlan
    layout: LayoutResult
    selection: deposit_mod.DepositSelection
    scan: ScanReport
    redaction_report: redaction.RedactionReport
    prepared: list[PreparedFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    geometry_note: str = ""

    @property
    def page_count(self) -> int:
        return self.layout.page_count

    @property
    def deposit_pages(self) -> int:
        return self.selection.deposited_pages

    def omitted_files(self) -> list[str]:
        return deposit_mod.files_entirely_omitted(self.selection, self.layout.file_ranges)

    def split_files(self) -> list[str]:
        return deposit_mod.files_partially_shown(self.selection, self.layout.file_ranges)


@dataclass
class BuildResult:
    estimate: EstimateResult
    outputs: list[str] = field(default_factory=list)
    manifest_path: str = ""
    summary_path: str = ""
    blocked_by: list[Finding] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return bool(self.outputs)


# What-if variants shown in the estimate panel, cheapest disclosure last.
WHAT_IF_VARIANTS: tuple[tuple[str, dict], ...] = (
    ("Keep everything", {"strip_comments": False, "strip_docstrings": False, "collapse_blank_runs": False}),
    ("Strip comments", {"strip_comments": True, "strip_docstrings": False, "collapse_blank_runs": False}),
    ("Strip comments + docstrings", {"strip_comments": True, "strip_docstrings": True, "collapse_blank_runs": False}),
    ("Strip all + collapse blanks", {"strip_comments": True, "strip_docstrings": True, "collapse_blank_runs": True}),
)


class Pipeline:
    """Stateful across calls so repeated estimates stay cheap."""

    def __init__(self) -> None:
        self._discovery: dict[str, DiscoveryResult] = {}
        self._text: dict[str, tuple[str, str, list[str]]] = {}
        self._strip: dict[tuple[str, str], StripResult] = {}
        self._scan: dict[tuple[str, str], tuple[list[Finding], list[Finding]]] = {}

    # -- stages ------------------------------------------------------------

    def discover(self, settings: BuildSettings, refresh: bool = False) -> DiscoveryResult:
        key = settings.source_root + "|" + str(dataclasses.asdict(settings.discovery))
        if refresh or key not in self._discovery:
            self._discovery[key] = discover(settings.source_root, settings.discovery)
        return self._discovery[key]

    def read(self, file: DiscoveredFile) -> tuple[str, str, list[str]]:
        cached = self._text.get(file.sha256)
        if cached is None:
            decoded = read_source(file.abs_path)
            cached = (decoded.text, decoded.encoding, list(decoded.warnings))
            self._text[file.sha256] = cached
        return cached

    def strip(self, file: DiscoveredFile, text: str, options: TransformOptions) -> StripResult:
        key = (file.sha256, options.cache_key())
        result = self._strip.get(key)
        if result is None:
            result = strip_source(text, file.rel_path, options)
            self._strip[key] = result
        return result

    def scan(
        self,
        file: DiscoveredFile,
        text: str,
        owner: str,
        settings: BuildSettings,
        comment_spans: list,
    ) -> tuple[list[Finding], list[Finding]]:
        key = (file.sha256, owner)
        cached = self._scan.get(key)
        if cached is None:
            # Secrets hide in code, so that scan reads everything; licence
            # and authorship markers live in comments, so that scan reads
            # only the comment layer and stays free of prose false hits.
            found_secrets = secrets_mod.scan_text(file.rel_path, text) if settings.scan.scan_secrets else []
            found_third: list[Finding] = []
            if settings.scan.scan_third_party:
                comment_lines = comments_only_lines(text, comment_spans)
                found_third = thirdparty_mod.scan_text(file.rel_path, comment_lines, owner)
            cached = (found_secrets, found_third)
            self._scan[key] = cached
        return cached

    # -- estimate ----------------------------------------------------------

    def estimate(
        self,
        settings: BuildSettings,
        *,
        transform: TransformOptions | None = None,
        progress: Progress = _noop,
        refresh: bool = False,
        run_scans: bool = True,
    ) -> EstimateResult:
        transform = transform or settings.transform
        warnings: list[str] = []

        progress("Discovering files", 0, 1)
        found = self.discover(settings, refresh=refresh)
        warnings.extend(found.warnings)

        plan = ordering.resolve_order(
            settings.order_entries,
            found.files,
            include_unlisted=settings.include_unlisted,
            excluded=settings.excluded,
        )
        warnings.extend(plan.warnings)
        for entry in plan.unmatched:
            warnings.append(f"Order entry '{entry}' matched no file.")

        by_path = found.by_path()
        ordered_files = [by_path[p] for p in plan.paths if p in by_path]

        compiled, regex_warnings = redaction.compile_regexes(settings.redaction)
        warnings.extend(regex_warnings)
        manual = {m.replace("\\", "/") for m in settings.redaction.manual_lines}

        scan_report = ScanReport()
        redaction_report = redaction.RedactionReport()
        prepared: list[PreparedFile] = []

        total = len(ordered_files)
        for index, file in enumerate(ordered_files, start=1):
            progress("Reading and stripping", index, total)
            text, encoding, read_warnings = self.read(file)
            stripped = self.strip(file, text, transform)

            # Line selection happens after stripping (so ranges refer to the
            # editor's line numbers) and before redaction (so redaction
            # indices line up with what is actually rendered).
            range_spec = settings.line_ranges.get(file.rel_path, "")
            ranges, range_warnings = lineranges.parse_ranges(range_spec, file.raw_line_count)
            selection = lineranges.apply_selection(
                stripped.lines, ranges, file.raw_line_count
            )

            file_redaction = redaction.compute_file_redaction(
                file.rel_path, text, selection.lines, settings.redaction, compiled, manual
            )
            redaction_report.files.append(file_redaction)

            if run_scans:
                found_secrets, found_third = self.scan(
                    file,
                    text,
                    settings.header.copyright_owner,
                    settings,
                    stripped.comment_spans,
                )
                scan_report.secrets.extend(found_secrets)
                scan_report.third_party.extend(found_third)

            file_warnings = (
                list(read_warnings)
                + list(stripped.warnings)
                + range_warnings
                + selection.warnings
            )
            for message in file_warnings:
                warnings.append(f"{file.rel_path}: {message}")

            prepared.append(
                PreparedFile(
                    rel_path=file.rel_path,
                    abs_path=file.abs_path,
                    original_text=text,
                    strip=stripped,
                    redaction=file_redaction,
                    selection=selection,
                    range_spec=range_spec,
                    total_lines=file.raw_line_count,
                    language=file.language,
                    encoding=encoding,
                    sha256=file.sha256,
                    warnings=file_warnings,
                )
            )

        progress("Laying out pages", total, total)
        blocks = [
            FileBlock(
                rel_path=p.rel_path,
                lines=p.selection.lines,
                language=p.language,
                redactions=p.redaction.spans,
                elisions=p.selection.elisions,
                trailing_elision=p.selection.trailing,
                range_label=p.selection.label,
            )
            for p in prepared
        ]

        geometry = metrics.build_geometry(
            settings.layout, layout_mod.max_source_line_number(blocks)
        )
        warnings.extend(geometry.font.warnings)

        result_layout = layout_mod.build_layout(
            blocks, settings.header.lines(), settings.layout, geometry
        )
        warnings.extend(result_layout.warnings)

        selection = deposit_mod.select_pages(result_layout.page_count, settings.deposit)
        warnings.extend(redaction.check_compliance(redaction_report, selection.mode))

        return EstimateResult(
            settings=settings,
            discovery=found,
            plan=plan,
            layout=result_layout,
            selection=selection,
            scan=scan_report,
            redaction_report=redaction_report,
            prepared=prepared,
            warnings=warnings,
            geometry_note=metrics.describe(geometry),
        )

    def what_if(
        self,
        settings: BuildSettings,
        progress: Progress = _noop,
    ) -> list[tuple[str, int, str]]:
        """Page count under each comment policy.

        Answers the question that actually matters: what do I change to get
        under 50 pages and deposit the whole program?
        """
        rows: list[tuple[str, int, str]] = []
        for index, (label, overrides) in enumerate(WHAT_IF_VARIANTS, start=1):
            progress("Comparing policies", index, len(WHAT_IF_VARIANTS))
            variant = dataclasses.replace(settings.transform, **overrides)
            estimate = self.estimate(
                settings, transform=variant, progress=_noop, run_scans=False
            )
            mode = (
                "entire program"
                if estimate.selection.mode == deposit_mod.MODE_ENTIRE
                else "first 25 + last 25"
            )
            rows.append((label, estimate.page_count, mode))
        return rows

    # -- build -------------------------------------------------------------

    def build(
        self,
        settings: BuildSettings,
        *,
        progress: Progress = _noop,
        force: bool = False,
    ) -> BuildResult:
        from . import manifest as manifest_mod
        from .render import render_pdf

        estimate = self.estimate(settings, progress=progress)
        result = BuildResult(estimate=estimate)

        ignored = set(settings.scan.ignored_findings)
        blocking = estimate.scan.blocking(ignored)
        if blocking and settings.scan.block_on_secrets and not force:
            result.blocked_by = blocking
            return result

        out_dir = Path(settings.output_dir or ".")
        out_dir.mkdir(parents=True, exist_ok=True)
        base = settings.output_basename or "deposit"
        fingerprint = settings.content_fingerprint()

        if settings.write_full_pdf:
            progress("Rendering complete PDF", 1, 2)
            full_path = out_dir / f"{base}_full.pdf"
            render_pdf(
                estimate.layout,
                full_path,
                settings.header,
                settings.layout,
                fingerprint=fingerprint,
            )
            result.outputs.append(str(full_path))

        if settings.write_deposit_pdf:
            progress("Rendering deposit copy", 2, 2)
            deposit_path = out_dir / f"{base}_deposit.pdf"
            render_pdf(
                estimate.layout,
                deposit_path,
                settings.header,
                settings.layout,
                selection=estimate.selection,
                fingerprint=fingerprint,
                include_separator=settings.deposit.separator_page,
            )
            result.outputs.append(str(deposit_path))

        if settings.write_manifest:
            manifest_path, summary_path = manifest_mod.write_manifest(
                estimate, out_dir, base, result.outputs
            )
            result.manifest_path = manifest_path
            result.summary_path = summary_path

        return result
