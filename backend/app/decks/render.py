"""One PNG of a whole deck page for the page reader (docs/design/page-image.md section 1).

The upload keeps the file's bytes (collection `deck_files`, in parts under the 16 MB document limit; removed with the deck and with
the audit). A PDF is rendered as it is; a .pptx or .docx is first turned into a PDF by LibreOffice (headless), once per read. Each
page is rendered whole, 1,568 px on the long edge, no crops. A deck whose rendering does not have as many pages as the parser read is
not drawn at all (hidden slides, or a Word page break that falls elsewhere): a wrong page image is worse than none, so the pages are
"not read" with the reason word below.
"""
import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("growth.decks")

COLLECTION = "deck_files"
LONG_EDGE = 1568                    # px of the page's long side
PART_BYTES = 8 * 1024 * 1024        # a part of the stored file, well under MongoDB's 16 MB document limit
CONVERT_TIMEOUT_SECONDS = 120
NO_FILE = "page image unavailable: file not stored"
NOT_RENDERED = "page image unavailable: file not rendered"
PAGE_COUNT_DIFFERS = "page image unavailable: page count differs"


class PageImageError(Exception):
    """A deck's page images cannot be made; `reason` is a closed text, never a file name or a page's text."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


async def save(db, audit_id: str, deck_id: str, content: bytes, fmt: str) -> None:
    """Keep the uploaded file's bytes for the page images, replacing any earlier parts of this deck."""
    await db[COLLECTION].delete_many({"audit_id": audit_id, "deck_id": deck_id})
    for part, start in enumerate(range(0, max(len(content), 1), PART_BYTES)):
        await db[COLLECTION].insert_one({"audit_id": audit_id, "deck_id": deck_id, "kind": "original", "format": fmt, "part": part,
                                         "data": content[start:start + PART_BYTES]})


async def _load(db, audit_id: str, deck_id: str, kind: str) -> Optional[bytes]:
    parts = await db[COLLECTION].find({"audit_id": audit_id, "deck_id": deck_id, "kind": kind}, {"_id": 0}).to_list(100000)
    if not parts:
        return None
    return b"".join(bytes(p["data"]) for p in sorted(parts, key=lambda p: p["part"]))


async def remove(db, audit_id: str, deck_ids: Optional[List[str]] = None) -> None:
    """Delete the stored files of one audit (every deck, or the decks named)."""
    where = {"audit_id": audit_id} if deck_ids is None else {"audit_id": audit_id, "deck_id": {"$in": list(deck_ids)}}
    await db[COLLECTION].delete_many(where)


def to_pdf(content: bytes, fmt: str) -> bytes:
    """The deck as PDF bytes: a PDF as it is, a .pptx or .docx through LibreOffice. PageImageError when it cannot be converted."""
    if fmt == "pdf":
        return content
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        logger.warning("page images: no converter for format=%s", fmt)
        raise PageImageError(NOT_RENDERED)
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / f"deck.{fmt}"
        source.write_bytes(content)
        try:
            subprocess.run([soffice, "--headless", "--norestore", f"-env:UserInstallation=file://{tmp}/profile", "--convert-to", "pdf",
                            "--outdir", tmp, str(source)], check=True, capture_output=True, timeout=CONVERT_TIMEOUT_SECONDS)
            return (Path(tmp) / "deck.pdf").read_bytes()
        except (subprocess.SubprocessError, OSError):
            logger.warning("page images: conversion failed for format=%s", fmt)
            raise PageImageError(NOT_RENDERED)


def page_count(pdf: bytes) -> int:
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(pdf)
    try:
        return len(document)
    finally:
        document.close()


def render_page(pdf: bytes, page: int) -> bytes:
    """The PNG of page `page` (1-based) of a PDF, whole, with its long edge at LONG_EDGE px."""
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(pdf)
    try:
        if not 1 <= page <= len(document):
            raise PageImageError(PAGE_COUNT_DIFFERS)
        sheet = document[page - 1]
        width, height = sheet.get_size()
        image = sheet.render(scale=LONG_EDGE / max(width, height)).to_pil().convert("RGB")
    except PageImageError:
        raise
    except Exception:
        raise PageImageError(NOT_RENDERED)
    finally:
        document.close()
    target = (LONG_EDGE, max(1, round(height * LONG_EDGE / width))) if width >= height else (max(1, round(width * LONG_EDGE / height)), LONG_EDGE)
    if image.size != target:
        image = image.resize(target)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


async def prepare(db, audit_id: str, deck_id: str, fmt: str, pages: Optional[int]) -> bytes:
    """The deck's PDF for rendering its pages, or PageImageError (NO_FILE, NOT_RENDERED, PAGE_COUNT_DIFFERS). `pages` is the page
    count the parser read; the PDF must have the same number."""
    import asyncio
    stored = await _load(db, audit_id, deck_id, "original")
    if stored is None:
        raise PageImageError(NO_FILE)
    pdf = await asyncio.to_thread(to_pdf, stored, fmt)
    try:
        count = await asyncio.to_thread(page_count, pdf)
    except Exception:
        raise PageImageError(NOT_RENDERED)
    if pages and count != pages:
        logger.warning("page images: format=%s rendered %d pages, parsed %d", fmt, count, pages)
        raise PageImageError(PAGE_COUNT_DIFFERS)
    return pdf
