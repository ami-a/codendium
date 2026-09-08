"""Audit trail for a build.

Writes a machine-readable manifest and a human-readable summary recording
exactly what went into the deposit: every file, its SHA-256, where it
landed in the PDF, and every warning raised along the way. The summary also
contains the sentence to give the Copyright Office describing the deposit.

Secret findings are recorded by masked excerpt only - the manifest must not
become a second copy of the credential.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import DISPLAY_NAME, __version__
from .deposit import MODE_ENTIRE
from .pipeline import EstimateResult


def build_manifest(estimate: EstimateResult, outputs: list[str]) -> dict:
    settings = estimate.settings
    layout = estimate.layout
    selection = estimate.selection
    ranges = {r.rel_path: r for r in layout.file_ranges}
    listed = {
        item.rel_path: item.source for item in estimate.plan.items
    }

    files = []
    for order, prepared in enumerate(estimate.prepared, start=1):
        page_range = ranges.get(prepared.rel_path)
        files.append(
            {
                "order": order,
                "path": prepared.rel_path,
                "sha256": prepared.sha256,
                "language": prepared.language,
                "encoding": prepared.encoding,
                "source_lines": len(prepared.lines),
                "total_lines_in_file": prepared.total_lines,
                "rendered_lines": page_range.rendered_lines if page_range else 0,
                "first_page": page_range.first_page if page_range else None,
                "last_page": page_range.last_page if page_range else None,
                "strip_method": prepared.strip.method,
                "lines_removed": prepared.strip.removed_lines,
                "partial": prepared.selection.partial,
                "line_ranges": prepared.range_spec,
                "line_range_label": prepared.selection.label,
                "lines_omitted_by_range": prepared.selection.omitted_lines,
                "redacted_chars": prepared.redaction.redacted_chars,
                "origin": listed.get(prepared.rel_path, "unlisted"),
                "warnings": prepared.warnings,
            }
        )

    return {
        "tool": {"name": DISPLAY_NAME, "version": __version__},
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "settings_fingerprint": settings.fingerprint(),
        "source_root": estimate.discovery.root,
        "identification": settings.header.lines(),
        "page_grid": estimate.geometry_note,
        "totals": {
            "files": len(estimate.prepared),
            "partial_files": sum(1 for p in estimate.prepared if p.selection.partial),
            "source_lines": layout.source_lines,
            "rendered_lines": layout.rendered_lines,
            "wrapped_lines": layout.wrapped_lines,
            "pages": layout.page_count,
            "glyph_replacements": layout.glyph_replacements,
        },
        "deposit": {
            "mode": selection.mode,
            "total_pages": selection.total_pages,
            "deposited_pages": selection.deposited_pages,
            "omitted_pages": list(selection.omitted) if selection.omitted else None,
            "filing_statement": selection.filing_statement(),
            "files_entirely_omitted": estimate.omitted_files(),
            "files_partially_shown": estimate.split_files(),
        },
        "redaction": {
            "enabled": settings.redaction.enabled,
            "redacted_chars": estimate.redaction_report.redacted_chars,
            "total_chars": estimate.redaction_report.total_chars,
            "ratio": round(estimate.redaction_report.ratio, 6),
            "within_721_7_limit": estimate.redaction_report.compliant,
        },
        "order": {
            "entries": settings.order_entries,
            "unmatched": estimate.plan.unmatched,
            "ambiguities": [
                {"entry": a.entry, "candidates": a.candidates, "chosen": a.chosen}
                for a in estimate.plan.ambiguities
            ],
            "excluded": estimate.plan.excluded,
        },
        "files": files,
        "skipped": [
            {"path": s.rel_path, "reason": s.reason, "size": s.size}
            for s in estimate.discovery.skipped
        ],
        "findings": {
            "secrets": [
                {
                    "id": f.id,
                    "location": f.location(),
                    "rule": f.rule,
                    "detail": f.detail,
                    "severity": f.severity,
                    "masked_excerpt": f.excerpt,
                }
                for f in estimate.scan.sorted_secrets()
            ],
            "third_party": [
                {
                    "id": f.id,
                    "location": f.location(),
                    "rule": f.rule,
                    "detail": f.detail,
                    "severity": f.severity,
                }
                for f in estimate.scan.sorted_third_party()
            ],
        },
        "warnings": estimate.warnings,
        "outputs": outputs,
        "settings": settings.to_dict(),
    }


def format_summary(manifest: dict) -> str:
    lines: list[str] = []
    add = lines.append

    add(f"{manifest['tool']['name'].upper()} - DEPOSIT BUILD SUMMARY")
    add("=" * 72)
    add(f"Generated : {manifest['generated_utc']}")
    add(f"Tool      : {manifest['tool']['name']} {manifest['tool']['version']}")
    add(f"Source    : {manifest['source_root']}")
    add(f"Page grid : {manifest['page_grid']}")
    add("")

    add("IDENTIFICATION BLOCK (first page of the deposit)")
    add("-" * 72)
    for line in manifest["identification"]:
        add(f"  {line}")
    add("")

    totals = manifest["totals"]
    deposit = manifest["deposit"]
    add("DEPOSIT")
    add("-" * 72)
    add(f"  Files included    : {totals['files']}")
    add(f"  Lines rendered    : {totals['rendered_lines']} ({totals['wrapped_lines']} wrapped)")
    add(f"  Complete program  : {deposit['total_pages']} page(s)")
    add(f"  Pages deposited   : {deposit['deposited_pages']}")
    if deposit["omitted_pages"]:
        first, last = deposit["omitted_pages"]
        add(f"  Pages omitted     : {first}-{last}")
    add("")
    add("  Statement for the application:")
    for chunk in _wrap(deposit["filing_statement"], 66):
        add(f"    {chunk}")
    add("")

    if deposit["files_entirely_omitted"]:
        add("  Files that fall entirely inside the omitted pages:")
        for path in deposit["files_entirely_omitted"]:
            add(f"    - {path}")
        add("")

    redaction = manifest["redaction"]
    if redaction["enabled"] and redaction["redacted_chars"]:
        add("REDACTION (Compendium sec. 721.7)")
        add("-" * 72)
        add(
            f"  Blocked out: {redaction['redacted_chars']} of {redaction['total_chars']} "
            f"characters ({redaction['ratio'] * 100:.1f}%)"
        )
        add(f"  Within the 49% limit: {'yes' if redaction['within_721_7_limit'] else 'NO'}")
        add("")

    add("FILE ORDER")
    add("-" * 72)
    add(f"  {'#':>3}  {'pages':>11}  {'lines':>6}  path")
    for entry in manifest["files"]:
        pages = (
            f"{entry['first_page']}-{entry['last_page']}"
            if entry["first_page"] is not None
            else "-"
        )
        marker = " " if entry["origin"] != "unlisted" else "*"
        suffix = "  [PARTIAL]" if entry.get("partial") else ""
        add(
            f"  {entry['order']:>3}{marker} {pages:>11}  {entry['rendered_lines']:>6}  "
            f"{entry['path']}{suffix}"
        )
    add("  (* = not named in the order list; appended automatically)")
    add("")

    partial = [entry for entry in manifest["files"] if entry.get("partial")]
    if partial:
        add("PARTIAL FILES (only the listed lines were deposited)")
        add("-" * 72)
        for entry in partial:
            add(f"  {entry['path']}")
            add(
                f"      lines {entry['line_range_label']} included; "
                f"{entry['lines_omitted_by_range']} line(s) omitted"
            )
        add("")

    secrets = manifest["findings"]["secrets"]
    third_party = manifest["findings"]["third_party"]
    if secrets:
        add("SECRET / PII FINDINGS")
        add("-" * 72)
        for finding in secrets:
            add(f"  [{finding['severity']:>6}] {finding['location']} - {finding['detail']} ({finding['masked_excerpt']})")
        add("")
    if third_party:
        add("THIRD-PARTY INDICATORS")
        add("-" * 72)
        for finding in third_party:
            add(f"  [{finding['severity']:>6}] {finding['location']} - {finding['detail']}")
        add("")

    if manifest["skipped"]:
        add("SKIPPED FILES")
        add("-" * 72)
        for entry in manifest["skipped"]:
            add(f"  {entry['path']} - {entry['reason']}")
        add("")

    if manifest["warnings"]:
        add("WARNINGS")
        add("-" * 72)
        for warning in manifest["warnings"]:
            add(f"  - {warning}")
        add("")

    add("OUTPUTS")
    add("-" * 72)
    for path in manifest["outputs"]:
        add(f"  {path}")
    add("")
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or [""]


def write_manifest(
    estimate: EstimateResult,
    out_dir: str | Path,
    base: str,
    outputs: list[str],
) -> tuple[str, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest(estimate, outputs)
    manifest_path = out_dir / f"{base}_manifest.json"
    summary_path = out_dir / f"{base}_summary.txt"

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    summary_path.write_text(format_summary(manifest), encoding="utf-8")
    return str(manifest_path), str(summary_path)
