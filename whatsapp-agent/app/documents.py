import base64
import csv
import re
from copy import copy
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME_TYPE = "application/pdf"
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


def clean_excel_workbook(source: Path, output_dir: Path, instruction_text: str = "") -> Path:
    """Create a lightly cleaned Excel copy without changing the source file."""
    workbook = load_workbook(str(source))
    heading = _extract_heading(instruction_text, source)
    for sheet in workbook.worksheets:
        _clean_sheet(sheet, heading)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_name = f"{source.stem}-cleaned-{timestamp}.xlsx"
    target = output_dir / output_name
    workbook.save(str(target))
    return target


def create_docx_report(content: str, output_dir: Path, title: str = "Aggie Report") -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = output_dir / f"aggie-report-{timestamp}.docx"
    doc = Document()
    doc.add_heading(title, 0)
    for block in _split_blocks(content):
        if block.startswith("# "):
            doc.add_heading(block[2:].strip(), level=1)
        elif block.startswith("## "):
            doc.add_heading(block[3:].strip(), level=2)
        elif _looks_like_table(block):
            _add_docx_table(doc, block)
        else:
            doc.add_paragraph(block)
    doc.save(str(target))
    return target


def clean_docx_document(source: Path, output_dir: Path, instruction_text: str = "") -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = output_dir / f"{source.stem}-cleaned-{timestamp}.docx"
    doc = Document(str(source))
    title = _clean_heading(_extract_heading(instruction_text, source)).title()
    if doc.paragraphs:
        first = doc.paragraphs[0]
        if first.text.strip().lower() != title.lower():
            first.insert_paragraph_before(title, style="Title")
    else:
        doc.add_heading(title, 0)

    for paragraph in doc.paragraphs:
        if not paragraph.text.strip():
            continue
        for run in paragraph.runs:
            run.font.name = "Calibri"
            run.font.size = None

    for table in doc.tables:
        table.style = "Table Grid"
        if table.rows:
            for cell in table.rows[0].cells:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True

    doc.save(str(target))
    return target


def create_pdf_report(content: str, output_dir: Path, title: str = "Aggie Report") -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = output_dir / f"aggie-report-{timestamp}.pdf"
    styles = getSampleStyleSheet()
    story: list[Any] = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
    for block in _split_blocks(content):
        if block.startswith("# "):
            story.append(Paragraph(block[2:].strip(), styles["Heading1"]))
        elif block.startswith("## "):
            story.append(Paragraph(block[3:].strip(), styles["Heading2"]))
        else:
            safe = block.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(safe.replace("\n", "<br/>"), styles["BodyText"]))
        story.append(Spacer(1, 8))
    SimpleDocTemplate(str(target), pagesize=A4).build(story)
    return target


def create_excel_from_text(content: str, output_dir: Path, title: str = "Organized Data") -> Path:
    from openpyxl import Workbook

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = output_dir / f"organized-data-{timestamp}.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Organized Data"
    rows = _text_to_rows(content)
    if not rows:
        rows = [["Content"], [content[:30000]]]
    for row in rows:
        sheet.append(row)
    _clean_sheet(sheet, title)
    _add_total_formulas(sheet)
    workbook.save(str(target))
    return target


def combined_attachment_text(attachments: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for attachment in attachments:
        path = Path(attachment["path"])
        mime_type = attachment.get("mime_type")
        text = extract_document_text(path, mime_type).strip()
        if text:
            chunks.append(f"--- {attachment.get('filename') or path.name} ---\n{text}")
    return "\n\n".join(chunks)


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
    return wants_edit and has_excel_attachment(attachments)


def has_excel_attachment(attachments: list[dict[str, Any]]) -> bool:
    return any(_is_excel_attachment(item) for item in attachments)


def _is_excel_attachment(attachment: dict[str, Any]) -> bool:
    path = Path(attachment["path"])
    mime_type = attachment.get("mime_type") or ""
    filename = str(attachment.get("filename") or path.name).lower()
    return (
        path.suffix.lower() in {".xlsx", ".xlsm"}
        or filename.endswith((".xlsx", ".xlsm"))
        or mime_type
        in {
            XLSX_MIME_TYPE,
            "application/vnd.ms-excel.sheet.macroenabled.12",
        }
    )


def _clean_sheet(sheet: Any, heading: str) -> None:
    _delete_empty_rows(sheet)
    _delete_empty_columns(sheet)
    _add_heading(sheet, heading)
    sheet.freeze_panes = "A3"

    for row in sheet.iter_rows():
        for cell in row:
            cell.fill = PatternFill(fill_type=None)
            cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            cell.font = Font(
                name=cell.font.name or "Calibri",
                size=cell.font.sz or 11,
                bold=cell.row in {1, 2},
                italic=cell.font.italic,
                color="000000",
            )

    _auto_size_columns(sheet)

    if sheet.max_row >= 2:
        for cell in sheet[2]:
            cell.font = copy(cell.font)
            cell.font = Font(name=cell.font.name or "Calibri", size=11, bold=True, color="000000")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.auto_filter.ref = f"A2:{get_column_letter(sheet.max_column)}{sheet.max_row}"
        _add_total_formulas(sheet)


def _extract_heading(instruction_text: str, source: Path) -> str:
    text = " ".join(instruction_text.split())
    patterns = [
        r"(?:heading|title|kichwa|header)\s*(?:ya|ni|is|:|-)?\s*['\"]?([^'\"]{3,80})",
        r"(?:weka|add|put)\s+(?:heading|title|kichwa)\s*(?:ya|as|:|-)?\s*['\"]?([^'\"]{3,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_heading(match.group(1))
    return _clean_heading(source.stem.replace("_", " ").replace("-", " "))


def _clean_heading(value: str) -> str:
    heading = re.split(r"\b(?:na|and|then|kisha|halafu|please|tafadhali)\b", value, flags=re.IGNORECASE)[0]
    heading = re.sub(r"\s+", " ", heading).strip(" .:-_")
    return (heading or "Stock Report").upper()


def _add_heading(sheet: Any, heading: str) -> None:
    if sheet.max_row == 0 or sheet.max_column == 0:
        return
    first_row_values = [sheet.cell(1, col_idx).value for col_idx in range(1, sheet.max_column + 1)]
    already_has_heading = (
        len([value for value in first_row_values if value not in (None, "")]) == 1
        and sheet.max_column > 1
    )
    if not already_has_heading:
        sheet.insert_rows(1)

    end_column = max(sheet.max_column, 1)
    if end_column > 1:
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=end_column)
    cell = sheet.cell(1, 1)
    cell.value = heading
    cell.font = Font(name="Calibri", size=15, bold=True, color="000000")
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.row_dimensions[1].height = 24


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


def _add_total_formulas(sheet: Any) -> None:
    if sheet.max_row < 3 or sheet.max_column < 2:
        return
    last_data_row = sheet.max_row
    total_row = last_data_row + 1
    sheet.cell(total_row, 1).value = "TOTAL"
    sheet.cell(total_row, 1).font = Font(name="Calibri", size=11, bold=True, color="000000")
    for col_idx in range(2, sheet.max_column + 1):
        numeric_count = 0
        for row_idx in range(3, sheet.max_row + 1):
            value = sheet.cell(row_idx, col_idx).value
            if isinstance(value, (int, float)):
                numeric_count += 1
        if numeric_count >= 2:
            letter = get_column_letter(col_idx)
            cell = sheet.cell(total_row, col_idx)
            cell.value = f"=SUM({letter}3:{letter}{last_data_row})"
            cell.font = Font(name="Calibri", size=11, bold=True, color="000000")
            cell.alignment = Alignment(horizontal="right", vertical="center")


def _split_blocks(content: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n\s*\n", content.strip()) if block.strip()]


def _looks_like_table(block: str) -> bool:
    lines = [line for line in block.splitlines() if line.strip()]
    return len(lines) >= 2 and all("|" in line for line in lines[:2])


def _add_docx_table(doc: Document, block: str) -> None:
    rows = _text_to_rows(block)
    if not rows:
        doc.add_paragraph(block)
        return
    table = doc.add_table(rows=len(rows), cols=max(len(row) for row in rows))
    table.style = "Table Grid"
    for row_idx, row in enumerate(rows):
        for col_idx, value in enumerate(row):
            cell = table.cell(row_idx, col_idx)
            cell.text = value
            if row_idx == 0:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True


def _text_to_rows(content: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in content.splitlines():
        cleaned = line.strip().strip("|")
        if not cleaned:
            continue
        if set(cleaned.replace("|", "").replace("-", "").replace(" ", "")) == set():
            continue
        if "|" in cleaned:
            row = [part.strip() for part in cleaned.split("|")]
        elif "," in cleaned:
            row = [part.strip() for part in next(csv.reader([cleaned]))]
        elif "\t" in cleaned:
            row = [part.strip() for part in cleaned.split("\t")]
        else:
            parts = re.split(r"\s{2,}", cleaned)
            row = parts if len(parts) > 1 else [cleaned]
        rows.append(row)
        if len(rows) >= 500:
            break
    return rows


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
