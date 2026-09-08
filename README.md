<div align="center">

<img src="https://raw.githubusercontent.com/ami-a/Codendium/main/docs/logo.svg" alt="Codendium" width="104">

# Codendium

**Turn a source tree into a US Copyright Office compliant deposit PDF — and know the page count before you render it.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Licence](https://img.shields.io/badge/Licence-Apache_2.0-D22128?style=flat-square&logo=apache&logoColor=white)](LICENSE)
[![GUI](https://img.shields.io/badge/GUI-PySide6-41CD52?style=flat-square&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)
[![PDF](https://img.shields.io/badge/PDF-ReportLab-005C9C?style=flat-square)](https://www.reportlab.com/)
[![Highlighting](https://img.shields.io/badge/Lexing-Pygments-FFD43B?style=flat-square&logoColor=black)](https://pygments.org/)
[![Tests](https://img.shields.io/badge/tests-175%20passing-2EA043?style=flat-square)](tests/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-64748B?style=flat-square)](#install)

</div>

---

## The problem this solves

To register software copyright in the United States you must deposit "identifying
portions" of your source code, and the Copyright Office is exacting about what
that means. The *Compendium of U.S. Copyright Office Practices* (Third) requires
the program title and version on the first page, monospaced type at roughly
9–10 pt, **about 40 lines per page**, continuous page numbering and clear file
paths. Then §721.6 adds the rule that governs everything else: if the program
runs to more than 50 pages, you deposit **the first 25 pages and the last 25**
— not a selection of your choosing.

Doing that by hand from a real multi-file project is slow and easy to get wrong.
Worse, the number that decides which rule applies — the page count — is
invisible until you have already built the PDF. So you build it, discover you
are at 62 pages, change something, and build it again.

**Codendium turns that into one step.** Point it at a folder; it discovers the
source, puts it in the order you want, optionally strips comments, lays it on a
compliant grid, and tells you the exact page count *before* rendering anything.
Then it writes both the complete PDF for your records and the filing copy with
§721.6 already applied, plus a manifest recording exactly what went in.

It is useful if you are an individual developer, a small studio or a law firm
preparing a software registration, and you would rather not assemble a
200-page deposit in a word processor.

---

## How it works

<div align="center">
<img src="https://raw.githubusercontent.com/ami-a/Codendium/main/docs/flow.svg" alt="Pipeline: discover, order, strip, then a shared layout stage feeding either the estimator or the renderer" width="100%">
</div>

The page grid is fixed and the font is monospaced, so **page count is a pure
function of the character stream**. Estimating runs the same discovery,
ordering, stripping and layout the renderer runs, and stops just before writing
the file. The estimate is therefore not a projection of the page count — it *is*
the page count, and the test suite asserts that equality against the rendered
PDF across seven different layout configurations.

---

## Install

```bash
git clone https://github.com/ami-a/Codendium.git
cd Codendium
pip install -r requirements.txt
```

Python 3.10 or newer. On Windows use the `py` launcher in place of `python`.

The GUI needs PySide6; **the CLI does not**, so on a headless machine or in CI
you can install just the four runtime dependencies from `pyproject.toml`.
For the test suite, `pip install -r requirements-dev.txt`.

---

## Quick start

```bash
python -m copyright_deposit                       # opens the GUI
```

Or from the command line:

```bash
# Propose an order from the code's own structure
python -m copyright_deposit suggest-order <folder> --write order.txt

# Exact page count, no PDF written, plus the comment-policy comparison
python -m copyright_deposit estimate <folder> --order-file order.txt --what-if

# Build it
python -m copyright_deposit build <folder> --order-file order.txt \
    --name "My Program" --program-version 1.2.0 \
    --owner "Jane Developer" --revision auto -o out
```

`build` exits non-zero and writes nothing if it finds credentials in the
selected files, which makes it safe to run unattended.

### What you get

| File | Purpose |
|---|---|
| `deposit_full.pdf` | The complete program, for your records |
| `deposit_deposit.pdf` | The filing copy, with §721.6 applied |
| `deposit_manifest.json` | Every file, its SHA-256, and the pages it landed on |
| `deposit_summary.txt` | Readable audit trail, plus the statement to give the Office |

---

## The application

<div align="center">
<img src="https://raw.githubusercontent.com/ami-a/Codendium/main/docs/screenshot-estimate.png" alt="The estimate tab: 205 pages, the §721.6 split, the statement for the application, and page counts under four comment policies" width="100%">
</div>

The estimate answers the question that actually matters — *what do I change to
get under 50 pages and deposit the whole program?*

```
Keep everything                   236 pages   (first 25 + last 25)
Strip comments                    229 pages   (first 25 + last 25)
Strip comments + docstrings       217 pages   (first 25 + last 25)
Strip all + collapse blanks       205 pages   (first 25 + last 25)
```

<div align="center">
<img src="https://raw.githubusercontent.com/ami-a/Codendium/main/docs/screenshot-files.png" alt="The files tab: drag-ordered file list with language, line counts, per-file line ranges and the pages each file occupies" width="100%">
</div>

The file list *is* the order list. Drag rows, or let **Suggest order** build one
from the entry points and the import/`#include` graph. Files nobody named are
appended and flagged, so an automatic decision never passes for a deliberate
one, and the Pages column shows which files fall inside the omitted middle —
code the Office will never see.

---

## Depositing only part of a file

Give any file a line range and only those lines are deposited — the **Deposit
lines** column in the GUI, or `--lines` on the command line:

```bash
python -m copyright_deposit build <folder> --lines "src/core.py=1-50,120-200"
```

Accepted forms: `1-50, 120-200` (blocks), `12` (one line), `305-` (to the end),
`-40` (from the start). Overlapping ranges are merged; out-of-range ones are
clamped or reported.

**Line numbers are the ones in your editor** — the original file's, not
positions after comments were stripped. An extract is then marked twice, so no
reader can mistake it for a whole file:

```
FILE: src/core.py
PARTIAL FILE - lines 1-50, 120-200 of 380 included
------------------------------------------------------------
def public_api(value):
    return _compute(value)
- - - - - -  [ lines 51-119 omitted (69 lines) ]  - - - - - -
def _compute(value):
```

One thing the markers deliberately do *not* claim: lines removed by the comment
policy are **not** reported as omitted. If stripping deleted lines 1–2, you did
not omit them — so no marker appears. Elisions are computed from your ranges
against the file's true length, never from which lines happened to survive.

---

## Stripping code without breaking it

Strippers never rewrite source. They *classify* byte ranges as comment or
docstring, and a shared routine removes those ranges — so the transform is
provably subtractive.

- **Python** — `tokenize` for comments, `ast` for docstrings, so a `#` inside a
  string cannot be mistaken for a comment. Afterwards the original and stripped
  ASTs are compared; on any difference the file is kept verbatim and a warning
  is raised.
- **Everything else** — Pygments, but only after its token stream is verified to
  reconstruct the source exactly. `Comment.Preproc` is never removed: C lexers
  classify `#include` and `#define` as comments, and deleting those would gut
  the deposit.
- **Fallback** — a hand-written C-family state machine handling raw strings
  (`R"tag( */ )tag"`), C# verbatim strings, Rust `r#"…"#`, template literals,
  line splicing, and JavaScript regex literals containing `//`.

A docstring that is the only statement in a function is never removed — that
would leave an empty suite and turn valid source into a syntax error.

---

## Safeguards

| Check | Why it exists |
|---|---|
| **Secret / PII scan** | A deposit becomes a public record. Anything left in the code is readable by anyone who inspects the filing, so high-severity findings block the build until redacted or acknowledged. |
| **Third-party detector** | A registration covers only your own authorship. Flags foreign copyright holders, SPDX licences and generated files — and reads *only the comment layer*, so prose and code never trigger it. |
| **Redaction (§721.7)** | Blocked-out text is never written into the PDF, only a filled rectangle, so it cannot be copied or extracted. Line count is unchanged, so pagination cannot shift. The 49 % limit is checked. |
| **Reproducibility** | Identical settings and sources produce a byte-identical PDF, so a re-run proves what was filed. |

---

## Page grid

Letter (or A4), 0.75 in margins, Courier 9.5 pt, 40 lines per page, 88 columns.

Courier is a PDF base-14 face: guaranteed monospaced, rendered identically by
every viewer, with no embedding or font-redistribution question — which is what
you want in a document you are filing. To use something else, point `--font` at
a monospaced `.ttf` or drop one in
[`copyright_deposit/assets/fonts/`](copyright_deposit/assets/fonts/). A
proportional font is rejected rather than silently breaking the grid, and
glyphs the font cannot draw become `?` with a warning rather than vanishing.

Overlong lines wrap — never truncate — and the wrap is counted in the estimate.

---

## Dependencies

| Package | Version | Licence | Used for |
|---|---|---|---|
| [reportlab](https://www.reportlab.com/) | ≥ 4.0 | BSD | PDF generation |
| [Pygments](https://pygments.org/) | ≥ 2.15 | BSD-2-Clause | Comment classification for ~30 languages |
| [charset-normalizer](https://github.com/jawah/charset_normalizer) | ≥ 3.2 | MIT | Deterministic source decoding |
| [pathspec](https://github.com/cpburnz/python-pathspec) | ≥ 0.11 | MPL-2.0 | `.gitignore` matching |
| [PySide6](https://doc.qt.io/qtforpython/) | ≥ 6.6 | LGPL-3.0 | GUI (optional) |

PySide6 is LGPL. That imposes nothing on you for source use or a normal
`pip install`, but it is worth knowing the day anyone freezes this into a
distributed binary.

---

## Tests

```bash
python -m pytest
```

175 tests covering stripper correctness on adversarial input, AST equivalence,
grid compliance, both §721.6 branches, redaction non-extractability, byte-level
reproducibility, line-range selection and elision marking, order resolution,
scanner false positives, and settings/history round-trips.

The estimate-equals-render property is asserted directly: the estimated page
count is compared against `len(PdfReader(...).pages)` of the file actually
written.

---

## Limitations

- The test-count badge is maintained by hand; there is no CI yet.
- Python 3.10–3.13 are declared, but only 3.11 is exercised regularly.
- Comment classification is verified for Python and validated for C-family and
  Pygments-supported languages; an unrecognised language is deposited verbatim
  rather than guessed at.

---

## Licence

[Apache License 2.0](LICENSE) — Copyright 2026 [ami-a](https://github.com/ami-a).

**Codendium prepares a deposit. It is not legal advice.** Whether a particular
deposit satisfies the Copyright Office for a particular work is a judgement for
you or your attorney to make.
