"""Reading source files as text, deterministically.

A deposit PDF must be reproducible, so decoding must never depend on the
machine's locale. The order is: BOM -> UTF-8 -> charset_normalizer ->
cp1252 -> latin-1 (which cannot fail). Whatever happens, we return text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)

# Control characters that would corrupt the fixed line grid. Form feed in
# particular is a real page-break marker in older C sources.
_CONTROL_TRANSLATE = {
    0x00: None, 0x01: None, 0x02: None, 0x03: None, 0x04: None, 0x05: None,
    0x06: None, 0x07: None, 0x08: None, 0x0B: None, 0x0C: None, 0x0E: None,
    0x0F: None, 0x10: None, 0x11: None, 0x12: None, 0x13: None, 0x14: None,
    0x15: None, 0x16: None, 0x17: None, 0x18: None, 0x19: None, 0x1A: None,
    0x1B: None, 0x1C: None, 0x1D: None, 0x1E: None, 0x1F: None, 0x7F: None,
}


@dataclass
class DecodedFile:
    text: str
    encoding: str
    had_bom: bool = False
    line_ending: str = "lf"  # lf | crlf | cr | mixed
    warnings: list[str] = field(default_factory=list)


def detect_line_ending(raw: str) -> str:
    crlf = raw.count("\r\n")
    cr = raw.count("\r") - crlf
    lf = raw.count("\n") - crlf
    present = [name for name, count in (("crlf", crlf), ("cr", cr), ("lf", lf)) if count]
    if not present:
        return "lf"
    if len(present) > 1:
        return "mixed"
    return present[0]


def is_probably_binary(data: bytes) -> bool:
    """NUL byte in the first block is the classic, reliable sniff."""
    return b"\x00" in data[:8192]


def decode_bytes(data: bytes) -> DecodedFile:
    warnings: list[str] = []
    encoding = ""
    had_bom = False
    text: str | None = None

    for bom, enc in _BOMS:
        if data.startswith(bom):
            had_bom = True
            encoding = enc
            try:
                text = data.decode(enc)
            except UnicodeDecodeError:
                text = None
            break

    if text is None and not had_bom:
        try:
            text = data.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            pass

    if text is None:
        try:
            from charset_normalizer import from_bytes

            best = from_bytes(data).best()
            if best is not None:
                text = str(best)
                encoding = best.encoding
                warnings.append(f"Decoded with detected encoding '{encoding}'.")
        except Exception:  # detector is best-effort, never fatal
            pass

    if text is None:
        for enc in ("cp1252", "latin-1"):
            try:
                text = data.decode(enc)
                encoding = enc
                warnings.append(f"Fell back to '{enc}'; characters may be approximate.")
                break
            except UnicodeDecodeError:
                continue

    if text is None:  # latin-1 cannot fail, but be explicit
        text = data.decode("latin-1", errors="replace")
        encoding = "latin-1"
        warnings.append("Undecodable bytes were replaced.")

    line_ending = detect_line_ending(text)
    if line_ending == "mixed":
        warnings.append("Mixed line endings were normalised.")

    # Normalise newlines, then remove control characters that break the grid.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\x0c" in text:
        warnings.append("Form-feed page breaks were removed.")
    cleaned = text.translate(_CONTROL_TRANSLATE)
    if cleaned != text:
        text = cleaned

    return DecodedFile(
        text=text,
        encoding=encoding,
        had_bom=had_bom,
        line_ending=line_ending,
        warnings=warnings,
    )


def read_source(path: str | Path) -> DecodedFile:
    data = Path(path).read_bytes()
    return decode_bytes(data)


def expand_tabs(text: str, width: int) -> str:
    """Tab expansion must be per-line: str.expandtabs already is."""
    return text.expandtabs(width) if width > 0 else text
