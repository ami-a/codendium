"""Page geometry and font metrics.

The whole design rests on one property: with a monospaced font and a fixed
number of lines per page, **page count is a pure function of the character
stream**. Nothing here consults the renderer, so the estimator and the
renderer cannot disagree.

Font policy: Courier is a PDF base-14 face, so it needs no embedding, is
guaranteed monospaced, renders identically everywhere and carries no
redistribution question. A TrueType file may be supplied instead; drop one
in ``assets/fonts`` or name a path in the settings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from ..config import LayoutOptions

PAGE_SIZES: dict[str, tuple[float, float]] = {
    "letter": (612.0, 792.0),  # 8.5 x 11 in
    "a4": (595.276, 841.890),
}

BASE14_MONO = {"Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"}

HEADER_BAND = 20.0
FOOTER_BAND = 22.0

_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


@dataclass(frozen=True)
class FontSpec:
    regular: str
    bold: str
    size: float
    char_width: float
    embedded: bool
    warnings: tuple[str, ...] = ()

    def supports(self, ch: str) -> bool:
        return _font_supports(self.regular, ch)

    def sanitize(self, text: str) -> tuple[str, int]:
        """Replace glyphs the font cannot draw. Returns (text, replacements)."""
        if text.isascii():
            return text, 0
        out: list[str] = []
        replaced = 0
        for ch in text:
            if ch.isascii() or _font_supports(self.regular, ch):
                out.append(ch)
            else:
                out.append("?")
                replaced += 1
        return "".join(out), replaced


@dataclass(frozen=True)
class PageGeometry:
    width: float
    height: float
    margin: float
    lines_per_page: int
    leading: float
    text_top: float
    text_bottom: float
    total_columns: int
    gutter_columns: int
    font: FontSpec
    running_header: bool
    page_numbers: bool

    @property
    def code_columns(self) -> int:
        return max(8, self.total_columns - self.gutter_columns)

    def baseline(self, row: int) -> float:
        """Baseline y for the given 0-based row on a page."""
        return self.text_top - self.leading * row - self.font.size

    @property
    def text_left(self) -> float:
        return self.margin

    def column_x(self, column: int) -> float:
        return self.margin + column * self.font.char_width


# ---------------------------------------------------------------------------
# Font registration
# ---------------------------------------------------------------------------

_registered: dict[str, bool] = {}
_coverage_cache: dict[str, set[int] | None] = {}


def _register_ttf(path: Path) -> tuple[str, str] | None:
    """Register a TTF (and a bold sibling if present). Returns font names."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    family = path.stem
    if _registered.get(family):
        return family, _registered_bold(family)
    try:
        pdfmetrics.registerFont(TTFont(family, str(path)))
    except Exception:
        return None
    _registered[family] = True

    bold_name = family
    for candidate in (
        path.with_name(path.stem + "-Bold" + path.suffix),
        path.with_name(path.stem + "Bd" + path.suffix),
        path.with_name(path.stem.replace("-Regular", "") + "-Bold" + path.suffix),
    ):
        if candidate.is_file():
            try:
                pdfmetrics.registerFont(TTFont(family + "-Bold", str(candidate)))
                bold_name = family + "-Bold"
                _registered[family + "-Bold"] = True
                break
            except Exception:
                continue
    return family, bold_name


def _registered_bold(family: str) -> str:
    return family + "-Bold" if _registered.get(family + "-Bold") else family


def _bundled_font() -> Path | None:
    if not _ASSET_DIR.is_dir():
        return None
    for path in sorted(_ASSET_DIR.glob("*.ttf")):
        if "bold" not in path.stem.lower() and "italic" not in path.stem.lower():
            return path
    return None


def _font_supports(font_name: str, ch: str) -> bool:
    coverage = _coverage_cache.get(font_name)
    if coverage is None and font_name not in _coverage_cache:
        coverage = _load_coverage(font_name)
        _coverage_cache[font_name] = coverage
    if coverage is None:
        # Base-14 fonts use WinAnsi; cp1252 encodability is the real test.
        try:
            ch.encode("cp1252")
            return True
        except UnicodeEncodeError:
            return False
    return ord(ch) in coverage


def _load_coverage(font_name: str) -> set[int] | None:
    from reportlab.pdfbase import pdfmetrics

    try:
        font = pdfmetrics.getFont(font_name)
    except Exception:
        return None
    face = getattr(font, "face", None)
    char_to_glyph = getattr(face, "charToGlyph", None)
    if not char_to_glyph:
        return None
    return set(char_to_glyph.keys())


def resolve_font(options: LayoutOptions) -> FontSpec:
    """Pick the deposit font, preferring an explicit TTF, then a bundled one."""
    warnings: list[str] = []
    name = (options.font_name or "Courier").strip()
    regular = "Courier"
    bold = "Courier-Bold"
    embedded = False

    candidate: Path | None = None
    if name.lower().endswith(".ttf"):
        candidate = Path(name)
        if not candidate.is_file():
            warnings.append(f"Font file not found: {name}; using Courier.")
            candidate = None
    elif name in BASE14_MONO:
        candidate = None
    else:
        asset = _ASSET_DIR / f"{name}.ttf"
        candidate = asset if asset.is_file() else None
        if candidate is None and name not in BASE14_MONO:
            candidate = _bundled_font()

    if candidate is None and name in ("", "auto"):
        candidate = _bundled_font()

    if candidate is not None:
        registered = _register_ttf(candidate)
        if registered:
            regular, bold = registered
            embedded = True
        else:
            warnings.append(f"Could not embed {candidate.name}; using Courier.")

    from reportlab.pdfbase import pdfmetrics

    size = float(options.font_size)
    narrow = pdfmetrics.stringWidth("i", regular, size)
    wide = pdfmetrics.stringWidth("W", regular, size)
    if abs(narrow - wide) > 0.01:
        warnings.append(
            f"'{regular}' is not monospaced; the Copyright Office requires a "
            "monospaced face. Falling back to Courier."
        )
        regular, bold, embedded = "Courier", "Courier-Bold", False
        wide = pdfmetrics.stringWidth("W", regular, size)

    return FontSpec(
        regular=regular,
        bold=bold,
        size=size,
        char_width=wide,
        embedded=embedded,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def build_geometry(options: LayoutOptions, max_line_number: int = 0) -> PageGeometry:
    """Derive the fixed page grid from the layout options."""
    font = resolve_font(options)
    width, height = PAGE_SIZES.get(options.page_size.lower(), PAGE_SIZES["letter"])
    margin = float(options.margin)

    header_band = HEADER_BAND if options.running_header else 0.0
    footer_band = FOOTER_BAND if options.page_numbers else 0.0
    text_top = height - margin - header_band
    text_bottom = margin + footer_band

    lines_per_page = max(1, int(options.lines_per_page))
    leading = (text_top - text_bottom) / lines_per_page

    usable_width = width - 2 * margin
    total_columns = max(20, int(math.floor(usable_width / font.char_width + 1e-9)))

    gutter = 0
    if options.show_line_numbers:
        gutter = max(4, len(str(max(max_line_number, 1)))) + 1

    return PageGeometry(
        width=width,
        height=height,
        margin=margin,
        lines_per_page=lines_per_page,
        leading=leading,
        text_top=text_top,
        text_bottom=text_bottom,
        total_columns=total_columns,
        gutter_columns=gutter,
        font=font,
        running_header=options.running_header,
        page_numbers=options.page_numbers,
    )


def describe(geometry: PageGeometry) -> str:
    """One-line summary shown in the GUI and written to the manifest."""
    return (
        f"{geometry.font.regular} {geometry.font.size:g}pt, "
        f"{geometry.lines_per_page} lines/page, "
        f"{geometry.code_columns} columns, "
        f"leading {geometry.leading:.2f}pt"
    )
