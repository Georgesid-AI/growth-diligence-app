"""A one-page PDF drawn from text and ruled rectangles, written by hand (no PDF library, nothing to install): synthetic decks for the
tests of the PDF reader (CLAUDE.md rule 15: no client deck in the repository). Coordinates are points from the bottom left of a
792 x 612 page; text is WinAnsi (so the euro sign is \x80 in the stream)."""
PAGE_W, PAGE_H = 792, 612


def _escape(text: str) -> bytes:
    return text.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def pdf_page(texts, rects=()) -> bytes:
    """texts: (x, y, size, text); rects: (x, y, width, height) drawn as 1-point lines."""
    stream = b"1 w\n"
    for x, y, w, h in rects:
        stream += b"%g %g %g %g re S\n" % (x, y, w, h)
    for x, y, size, text in texts:
        stream += b"BT /F1 %g Tf %g %g Td (" % (size, x, y) + _escape(text) + b") Tj ET\n"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
               % (PAGE_W, PAGE_H),
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream"]
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)


def ruled_table(rows, x=50, top=492, col_widths=(200, 540), row_height=30, size=11):
    """(texts, rects) of a ruled table: one rectangle per cell, the cell's text inside it; an empty string leaves the cell blank."""
    texts, rects = [], []
    for r, row in enumerate(rows):
        y, left = top - row_height * r, x
        for width, cell in zip(col_widths, row):
            rects.append((left, y - row_height, width, row_height))
            if cell:
                texts.append((left + 4, y - row_height + 10, size, cell))
            left += width
    return texts, rects
