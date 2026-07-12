import base64
import csv
from copy import copy
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pypdf import PdfReader


IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def extract_document_text(path: Path, mime_type: str | None = None) -> str:
    suffix = path.suffix.lower()

    if suffix == ".pdf" or mime_type == "application/pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix in {".xlsx", ".xlsm"}:
        return _extract_xlsx(path)
    if suffix == ".csv" or mime_type == "text/csv":
        return _extract_csv(path)
    if suffix in {".txt", ".md"} or (mime_type and mime_type.startswith("text/")):
        return path.read_text(encoding="utf-8", errors="replace")

    return ""


def build_image_content_block(path: Path, mime_type: str) -> dict[str, Any]:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": mime_type,
            "data": encoded,
        },
    }


def clean_excel_workbook(source: Path, output_dir: Path) -> Path:
    """Create a lightly cleaned Excel copy without changing the source file."""
    workbook = load_workbook(str(source))
    for sheet in workbook.worksheets:
        _clean_sheet(sheet)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_name = f"{source.stem}-cleaned-{timestamp}.xlsx"
    target = output_dir / output_name
    workbook.save(str(target))
    return target


def should_create_clean_excel(text: str, attachments: list[dict[str, Any]]) -> bool:
    lowered = text.lower()
    wants_edit = any(
        word in lowered
        for word in [
            "clean",
            "format",
            "edit",
            "arrange",
            "organize",
            "pang",
            "panga",
            "safisha",
            "tengeneza",
            "rekebisha",
            "weka sawa",
        ]
    )
    has_excel = any(Path(item["path"]).suffix.lower() in {".xlsx", ".xlsm"} for item in attachments)
    return wants_edit and has_excel


def _clean_sheet(sheet: Any) -> None:
    sheet.freeze_panes = "A2"

    for row in sheet.iter_rows():
        for cell in row:
            cell.fill = PatternFill(fill_type=None)
            cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            cell.font = Font(
                name=cell.font.name or "Calibri",
                size=cell.font.sz or 11,
                bold=cell.row == 1,
                italic=cell.font.italic,
                color="000000",
            )

    _delete_empty_rows(sheet)
    _delete_empty_columns(sheet)
    _auto_size_columns(sheet)

    if sheet.max_row >= 1:
        for cell in sheet[1]:
            cell.font = copy(cell.font)
            cell.font = Font(name=cell.font.name or "Calibri", size=11, bold=True, color="000000")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _delete_empty_rows(sheet: Any) -> None:
    for row_idx in range(sheet.max_row, 0, -1):
        if all(sheet.cell(row_idx, col_idx).value in (None, "") for col_idx in range(1, sheet.max_column + 1)):
            sheet.delete_rows(row_idx)


def _delete_empty_columns(sheet: Any) -> None:
    for col_idx in range(sheet.max_column, 0, -1):
        if all(sheet.cell(row_idx, col_idx).value in (None, "") for row_idx in range(1, sheet.max_row + 1)):
            sheet.delete_cols(col_idx)


def _auto_size_columns(sheet: Any) -> None:
    for col_idx in range(1, sheet.max_column + 1):
        letter = get_column_letter(col_idx)
        max_len = 10
        for cell in sheet[letter]:
            value = "" if cell.value is None else str(cell.value)
            max_len = max(max_len, min(len(value), 45))
        sheet.column_dimensions[letter].width = max_len + 2


def _extract_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"--- Page {index} ---\n{text.strip()}")
    return "\n\n".join(pages)


def _extract_docx(path: Path) -> str:
    doc = Document(str(path))
    lines: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            if any(cells):
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _extract_xlsx(path: Path) -> str:
    workbook = load_workbook(str(path), data_only=True, read_only=True)
    chunks: list[str] = []
    for sheet in workbook.worksheets:
        rows: list[str] = []
        for row in sheet.iter_rows(values_only=True):
            values = ["" if value is None else str(value) for value in row]
            if any(value.strip() for value in values):
                rows.append(" | ".join(values))
            if len(rows) >= 200:
                rows.append("[Sheet truncated after 200 non-empty rows]")
                break
        if rows:
            chunks.append(f"--- Sheet: {sheet.title} ---\n" + "\n".join(rows))
    return "\n\n".join(chunks)


def _extract_csv(path: Path) -> str:
    rows: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as file:
        reader = csv.reader(file)
        for row in reader:
            rows.append(" | ".join(row))
            if len(rows) >= 300:
                rows.append("[CSV truncated after 300 rows]")
                break
    return "\n".join(rows)
