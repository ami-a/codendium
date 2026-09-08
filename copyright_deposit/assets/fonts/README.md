# Optional deposit font

Codendium renders deposits in **Courier** by default. Courier is one of the PDF
base-14 faces, so it needs no embedding, is guaranteed monospaced, renders
identically in every viewer, and raises no font-redistribution question — which
is what you want in a document you are filing.

To use a different face, drop a monospaced TrueType file into this directory.
The first non-bold, non-italic `.ttf` here is picked up automatically
(`core.metrics._bundled_font`), embedded in the PDF, and used instead of
Courier. A `Foo-Bold.ttf` or `FooBd.ttf` beside `Foo.ttf` is used for the bold
banner lines.

You can also point at a font per build without copying anything here:

```
py -m copyright_deposit build <folder> --font "C:/path/to/DejaVuSansMono.ttf"
```

Two rules the tool enforces whichever font you choose:

- **It must be monospaced.** The page grid, the column count and therefore the
  page estimate all assume a fixed advance width. A proportional font is
  rejected at load time and Courier is used instead.
- **Missing glyphs are replaced, never dropped.** Characters the font cannot
  draw become `?` and the count is reported as a build warning, so nothing
  disappears from the deposit silently.

No font is committed here. Check the licence of any font you add — some
disallow embedding or redistribution, and this directory ships inside the
Python package.
