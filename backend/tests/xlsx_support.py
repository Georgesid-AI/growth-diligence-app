"""Synthetic workbooks for the structure tests (CLAUDE.md rule 15: every name and figure is made up). openpyxl writes a formula with no cached value;
a real Excel file has one, and the reader's grid is built from it, so `to_bytes` writes the values the formulas would give."""
import re
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile


def to_bytes(wb, cached=None) -> bytes:
    """The workbook's bytes; `cached` is {(sheet title, "B4"): value} for the formula cells that should carry a cached value."""
    buf = BytesIO()
    wb.save(buf)
    if not cached:
        return buf.getvalue()
    out = BytesIO()
    with ZipFile(BytesIO(buf.getvalue())) as zin, ZipFile(out, "w", ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            m = re.fullmatch(r"xl/worksheets/sheet(\d+)\.xml", item.filename)
            if m:
                title = wb.sheetnames[int(m.group(1)) - 1]
                text = data.decode("utf-8")
                for (sheet, ref), value in cached.items():
                    if sheet == title:
                        text = re.sub(rf'(<c r="{ref}"[^>]*>)(<f>.*?</f>)<v></v>', lambda mm: f"{mm.group(1)}{mm.group(2)}<v>{value}</v>", text)
                data = text.encode("utf-8")
            zout.writestr(item, data)
    return out.getvalue()
