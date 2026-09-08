# Copyright Deposit Builder

Builds US Copyright Office compliant source-code deposit PDFs from a source
tree — with an **exact** page count available before anything is rendered.

The Compendium (Third) imposes mechanical rules on a source-code deposit:
program title and version on the first page, monospaced type at roughly
9–10 pt, about 40 lines per page, continuous page numbers, clear file paths,
and — for a program over 50 pages — only the **first 25 and last 25 pages**
(§721.6). Assembling that by hand from a multi-file project is slow, and the
page count that decides which rule applies is invisible until the PDF exists.

## What it does

- Walks a folder recursively for Python, C/C++ and ~30 other languages.
- Orders files from your list, or suggests one from the dependency graph.
- Deposits whole files, or only the line ranges you choose — clearly marked.
- Strips comments and docstrings — verifiably, without touching code.
- Lays everything on a fixed, compliant page grid.
- Writes a **complete** PDF (your records) and a **deposit** PDF applying §721.6.
- Blacks out trade secrets under §721.7, with the 49 % limit checked.
- Warns about credentials and third-party code before you file.
- Records every build in a manifest and a reusable history.

## Install

```
py -m pip install -r requirements.txt      # add -r requirements-dev.txt for tests
```

Python 3.10+. The GUI needs PySide6; the CLI does not.

## Use

```
py -m copyright_deposit                    # GUI
```

```
py -m copyright_deposit estimate  <folder> --what-if
py -m copyright_deposit build     <folder> --name "My Program" --owner "Me" --revision auto
py -m copyright_deposit suggest-order <folder> --write order.txt
```

`build` writes four files:

| File | Purpose |
|---|---|
| `deposit_full.pdf` | the complete program, for your records |
| `deposit_deposit.pdf` | the filing copy, with §721.6 applied |
| `deposit_manifest.json` | every file, its SHA-256, and where it landed |
| `deposit_summary.txt` | readable audit trail + the statement for the Office |

## The idea that makes the estimate exact

The page grid is fixed, and the font is monospaced — so **page count is a pure
function of the character stream**. Estimating runs the same discovery,
stripping and layout the renderer uses and stops just before writing the PDF.

```
discover → order → transform → LAYOUT ─┬─→ estimate  (instant, no rendering)
                                        └─→ render    (reportlab → PDF)
```

The estimate is not a projection of the page count. It *is* the page count, and
the test suite asserts equality against the rendered file across seven layout
configurations.

`Compare policies` uses this to answer the question that actually matters:

```
Keep everything                   114 pages  (first 25 + last 25)
Strip comments                    111 pages  (first 25 + last 25)
Strip comments + docstrings       103 pages  (first 25 + last 25)
Strip all + collapse blanks        98 pages  (first 25 + last 25)
```

If a policy brings you to 50 pages or fewer you may deposit the whole program,
which is simpler than the split — so the tool shows you what it would take.

## Depositing only part of a file

Give any file a line range and only those lines are deposited. In the GUI this
is the **Deposit lines** column on the Files tab (blank = the whole file); on
the command line it is `--lines`:

```
py -m copyright_deposit build <folder> --lines "src/core.py=1-50,120-200"
```

Accepted forms: `1-50, 120-200` (blocks), `12` (one line), `305-` (to the end),
`-40` (from the start). Overlapping ranges are merged, out-of-range ones are
clamped or reported.

**Line numbers are the ones in your editor** — the original file's, not
positions after comments were stripped. So a range means what you'd expect
whatever the comment policy is.

An extract is marked twice, so no reader can mistake it for a whole file:

```
FILE: src/core.py
PARTIAL FILE - lines 1-50, 120-200 of 380 included
------------------------------------------------------------
def public_api(value):
    return _compute(value)
- - - - - - -  [ lines 51-119 omitted (69 lines) ]  - - - - - - -
def _compute(value):
```

The dashed rules are set in grey and name exactly which lines are missing; the
manifest and summary record every partial file and its omitted line count.

One thing the markers deliberately do *not* claim: lines removed by the comment
policy are **not** reported as omitted. If stripping deleted lines 1–2, you did
not omit them — so no marker appears. Elisions are computed from your ranges
against the file's true length, never from which lines happened to survive.

Note that this is independent of the §721.6 page rule, which operates on pages
after layout. Depositing fragments of files is a judgement call about whether
the deposit still represents the work; the tool makes the fact visible on every
affected page so that judgement is on the record.

## Stripping code without breaking it

Strippers never rewrite source. They *classify* byte ranges as comment or
docstring, and a shared routine removes those ranges — so the transform is
provably subtractive.

- **Python** — `tokenize` for comments, `ast` for docstrings. A `#` inside a
  string cannot be mistaken for a comment. Afterwards the original and stripped
  ASTs are compared; on any difference the file is kept verbatim and a warning
  is raised.
- **Everything else** — pygments, but only after its token stream is verified to
  reconstruct the source exactly. `Comment.Preproc` is never removed: C lexers
  classify `#include` and `#define` as comments, and deleting those would gut
  the deposit.
- **Fallback** — a hand-written C-family state machine handling raw strings
  (`R"tag( */ )tag"`), C# verbatim strings, Rust `r#"…"#`, template literals,
  line splicing, and JavaScript regex literals containing `//`.

A docstring that is the only statement in a function is never removed — that
would leave an empty suite and turn valid source into a syntax error.

## Safeguards

| Check | Why |
|---|---|
| Secret / PII scan | A deposit is a public record; anything left in the code is readable by anyone who inspects the filing. High-severity findings block the build until redacted or acknowledged. |
| Third-party detector | A registration covers only your own authorship. Flags foreign copyright holders, SPDX licences and generated files. Reads *only the comment layer*, so prose and code never trigger it. |
| Redaction (§721.7) | Blocked-out text is never written into the PDF — only a filled rectangle — so it cannot be copied or extracted. Line count is unchanged, so pagination cannot shift. |
| Reproducibility | Identical settings and sources produce a byte-identical PDF, so a re-run proves what was filed. |

## Page grid

Letter (or A4), 0.75 in margins, Courier 9.5 pt, 40 lines per page, 88 columns.
Courier is a PDF base-14 face: guaranteed monospaced, identical everywhere, no
embedding or redistribution question. Point `--font` at a monospaced `.ttf` to
override. Overlong lines wrap — never truncate — and the wrap is counted in the
estimate.

## Tests

```
py -m pytest
```

175 tests covering stripper correctness on adversarial input, AST equivalence,
grid compliance, the §721.6 branches, redaction non-extractability,
reproducibility, line-range selection and elision marking, order resolution,
scanner false positives, and settings / history round-trips.

---

This tool prepares a deposit. It is not legal advice.
