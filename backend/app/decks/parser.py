"""A .pptx, .pdf or .docx file -> text blocks, each with its source reference.

A block is one text line, one speaker-notes line or one table cell:

    {"slide": 5, "kind": "text", "text": "..."}                                  pptx
    {"page": 3, "kind": "table", "table": 1, "row": 2, "col": 4, "text": "..."}  pdf, docx

Text only. Pictures, charts saved as pictures and scanned pages hold pixels, not text, so
they are not read; a file with no readable text is refused, never guessed.
"""
import io
import re
from typing import Dict, List

MAX_BYTES = 50 * 1024 * 1024
MAX_PAGES = 200

NO_TEXT = ("No readable text found in this file. It may be scanned or made of images. "
           "Please upload a text-based version.")
TOO_LARGE = "This file is larger than 50 MB. Please upload a file of 50 MB or less."
TOO_MANY_PAGES = ("This file has {n} {unit}s. We read up to 200 slides or pages per file. "
                  "Please split it into smaller files.")
KEYNOTE = "We cannot read Keynote files. Please export it as PowerPoint or PDF first."
UNSUPPORTED = ("We read text from PowerPoint (.pptx), Word (.docx) and text-based PDF files. "
               "Please export this file as PowerPoint or PDF first.")
UNREADABLE = ("This file could not be opened as a {kind} file. It may be damaged or saved in another "
              "format. Please export it again as PowerPoint, Word or PDF.")

FORMATS = {".pptx": "pptx", ".pdf": "pdf", ".docx": "docx"}
_KIND_NAME = {"pptx": "PowerPoint", "pdf": "PDF", "docx": "Word"}


class DeckError(ValueError):
    """The file is refused; `message` is shown to the user as is."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def deck_format(filename: str) -> str:
    """'pptx' | 'pdf' | 'docx' from the file name, or DeckError with the reason."""
    name = (filename or "").lower().strip()
    for ext, fmt in FORMATS.items():
        if name.endswith(ext):
            return fmt
    raise DeckError(KEYNOTE if name.endswith(".key") else UNSUPPORTED)


def parse_deck(content: bytes, filename: str) -> Dict:
    """{"file", "format", "page_unit", "pages", "blocks"} or DeckError."""
    fmt = deck_format(filename)
    if len(content) > MAX_BYTES:
        raise DeckError(TOO_LARGE)
    reader = {"pptx": _pptx_blocks, "pdf": _pdf_blocks, "docx": _docx_blocks}[fmt]
    try:
        pages, blocks = reader(content)
    except DeckError:
        raise
    except Exception:
        # The library's message can quote file content, so it is neither shown nor logged.
        raise DeckError(UNREADABLE.format(kind=_KIND_NAME[fmt]))
    unit = "slide" if fmt == "pptx" else "page"
    if pages > MAX_PAGES:
        raise DeckError(TOO_MANY_PAGES.format(n=pages, unit=unit))
    if not any(re.search(r"\w", b["text"]) for b in blocks):
        raise DeckError(NO_TEXT)
    return {"file": filename, "format": fmt, "page_unit": unit, "pages": pages, "blocks": blocks}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _lines(text: str) -> List[str]:
    """Split on line and paragraph breaks (pptx writes a line break as \\v); drop blank lines."""
    return [line for line in (_clean(part) for part in re.split(r"[\n\r\v]+", text or "")) if line]


# ---------------------------------------------------------------------------
# pptx: text boxes (including grouped shapes and placeholders), tables, speaker notes
# ---------------------------------------------------------------------------
def _pptx_blocks(content: bytes):
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(io.BytesIO(content))
    slides = list(prs.slides)
    if len(slides) > MAX_PAGES:
        return len(slides), []

    def shapes(container):
        for shape in container:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from shapes(shape.shapes)
            else:
                yield shape

    blocks = []
    for n, slide in enumerate(slides, 1):
        tables = 0
        for shape in shapes(slide.shapes):
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    blocks += [{"slide": n, "kind": "text", "text": line} for line in _lines(para.text)]
            if shape.has_table:
                tables += 1
                for r, row in enumerate(shape.table.rows, 1):
                    for c, cell in enumerate(row.cells, 1):
                        if _clean(cell.text):
                            blocks.append({"slide": n, "kind": "table", "table": tables, "row": r, "col": c,
                                           "text": _clean(cell.text)})
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            for para in slide.notes_slide.notes_text_frame.paragraphs:
                blocks += [{"slide": n, "kind": "notes", "text": line} for line in _lines(para.text)]
    return len(slides), blocks


# ---------------------------------------------------------------------------
# pdf: text lines, plus ruled tables read cell by cell
# ---------------------------------------------------------------------------
def _is_grid(rows) -> bool:
    """A real table has at least two rows with two filled cells. Slide frames and chart
    gridlines that pdfplumber also reports as tables do not."""
    return sum(1 for row in rows if sum(1 for cell in row if _clean(cell)) >= 2) >= 2


def _pdf_blocks(content: bytes):
    import pdfplumber

    blocks = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        pages = len(pdf.pages)
        if pages > MAX_PAGES:
            return pages, []
        for n, page in enumerate(pdf.pages, 1):
            x0, top, x1, bottom = page.bbox
            grids = []
            for table in page.find_tables():
                rows = table.extract()
                if _is_grid(rows):
                    tx0, ttop, tx1, tbottom = table.bbox
                    grids.append(((max(tx0, x0), max(ttop, top), min(tx1, x1), min(tbottom, bottom)), rows))
            rest = page
            for bbox, _ in grids:
                rest = rest.outside_bbox(bbox)
            blocks += [{"page": n, "kind": "text", "text": line} for line in _lines(rest.extract_text() or "")]
            for t, (_, rows) in enumerate(grids, 1):
                for r, row in enumerate(rows, 1):
                    for c, cell in enumerate(row, 1):
                        if _clean(cell):
                            blocks.append({"page": n, "kind": "table", "table": t, "row": r, "col": c,
                                           "text": _clean(cell)})
    return pages, blocks


# ---------------------------------------------------------------------------
# docx: paragraphs, text boxes and tables in document order
# ---------------------------------------------------------------------------
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def _docx_blocks(content: bytes):
    """A .docx has no fixed pages, so the page number is counted from what Word wrote into the
    file: a hard page break, a rendered page break (w:lastRenderedPageBreak) and a section break
    that starts a new page. Signals with no text between them are one break, since Word writes a
    rendered break right after a hard one. A blank page between two pages of text is not counted."""
    import docx

    body = docx.Document(io.BytesIO(content)).element.body
    for fallback in list(body.iter(_MC_FALLBACK)):       # the same text box again, for old readers
        fallback.getparent().remove(fallback)
    section_types = []
    for sect in body.iter(_W + "sectPr"):
        start = sect.find(_W + "type")
        section_types.append(start.get(_W + "val") if start is not None else "nextPage")

    state = {"page": 1, "text_since_break": False, "section": 0}
    segments = {}       # (owner element, page) -> {"page", "kind", "parts", table ref...}, in order of appearance
    tables_on_page = {}

    def page_break():
        if state["text_since_break"]:
            state["page"] += 1
            state["text_since_break"] = False

    def owner_of(el):
        cell = para = None
        for anc in el.iterancestors():
            if para is None and anc.tag == _W + "p":
                para = anc
            if anc.tag == _W + "tc":
                cell = anc
                break
        return cell if cell is not None else para

    def segment(owner):
        key = (owner, state["page"])
        if key not in segments:
            seg = {"page": state["page"], "parts": []}
            if owner.tag == _W + "tc":
                row = owner.getparent()
                table = row.getparent()
                numbers = tables_on_page.setdefault(state["page"], {})
                seg.update(kind="table", table=numbers.setdefault(table, len(numbers) + 1),
                           row=[c for c in table if c.tag == _W + "tr"].index(row) + 1,
                           col=[c for c in row if c.tag == _W + "tc"].index(owner) + 1)
            else:
                seg["kind"] = "text"
            segments[key] = seg
        return segments[key]

    for top in body:
        for el in top.iter():
            tag = el.tag
            if tag == _W + "t" and el.text:
                owner = owner_of(el)
                if owner is not None:
                    segment(owner)["parts"].append(el.text)
                    state["text_since_break"] = state["text_since_break"] or bool(el.text.strip())
            elif tag == _W + "tab":
                owner = owner_of(el)
                if owner is not None:
                    segment(owner)["parts"].append("\t")
            elif tag in (_W + "br", _W + "cr"):
                if el.get(_W + "type") == "page":
                    page_break()
                else:
                    owner = owner_of(el)
                    if owner is not None:
                        segment(owner)["parts"].append("\n")
            elif tag == _W + "lastRenderedPageBreak":
                page_break()
            elif tag == _W + "p":
                owner = owner_of(el) if el is not top else None
                # A paragraph inside a table cell or a text box ends a line of its own.
                if owner is not None and owner.tag == _W + "tc":
                    segment(owner)["parts"].append("\n")
        # A section break sits in the last paragraph of its section; the next section's start
        # type says whether the following text begins on a new page.
        for sect in top.iter(_W + "sectPr"):
            if sect.getparent() is not None and sect.getparent().tag == _W + "pPr":
                state["section"] += 1
                following = section_types[state["section"]] if state["section"] < len(section_types) else "nextPage"
                if following != "continuous":
                    page_break()

    blocks = []
    for (owner, _), seg in segments.items():
        text = "".join(seg["parts"])
        if seg["kind"] == "table":
            if _clean(text):
                blocks.append({"page": seg["page"], "kind": "table", "table": seg["table"], "row": seg["row"],
                               "col": seg["col"], "text": _clean(text)})
        else:
            blocks += [{"page": seg["page"], "kind": "text", "text": line} for line in _lines(text)]
    return state["page"], blocks
