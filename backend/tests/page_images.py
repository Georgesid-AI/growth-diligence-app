"""Synthetic page images for the tests (CLAUDE.md rule 15: no client deck, no client page). A page image here is a small PNG drawn from
nothing but the page number, so two pages never share one."""
import io

from PIL import Image


def png(page: int = 1) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (16, 9), (page % 256, 40, 90)).save(out, format="PNG")
    return out.getvalue()


async def image_for(page: int) -> bytes:
    return png(page)
