import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.claude_agent import ClaudeAgent
from app.config import get_settings
from app.documents import (
    DOCX_MIME_TYPE,
    PDF_MIME_TYPE,
    XLS_MIME_TYPE,
    XLSX_MIME_TYPE,
    combined_attachment_text,
    create_docx_report,
    create_excel_from_text,
    create_pdf_report,
    clean_docx_document,
    edit_excel_workbook,
    has_excel_attachment,
)
from app.memory import ConversationMemory
from app.whatsapp import WhatsAppClient


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whatsapp-agent")

settings = get_settings()
memory = ConversationMemory(settings.database_path)
agent = ClaudeAgent(settings, memory)
whatsapp = WhatsAppClient(settings)

app = FastAPI(title="WhatsApp Claude Helper", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/debug/identity")
async def debug_identity() -> dict[str, str]:
    return {
        "assistant": "Aggie",
        "purpose": "stock-manager documents, reports, sheets, and workplace helper",
        "app_file": str(Path(__file__).resolve()),
    }


@app.get("/debug/config")
async def debug_config() -> dict[str, bool | str]:
    return {
        "assistant": "Aggie",
        "meta_verify_token_set": bool(settings.meta_verify_token),
        "meta_access_token_set": bool(settings.meta_access_token),
        "meta_phone_number_id_set": bool(settings.meta_phone_number_id),
        "anthropic_api_key_set": bool(settings.anthropic_api_key),
        "database_path": str(settings.database_path),
        "upload_dir": str(settings.upload_dir),
        "output_dir": str(settings.output_dir),
        "knowledge_dir": str(settings.knowledge_dir),
    }


@app.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> str:
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        return hub_challenge
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@app.post("/webhook")
async def receive_webhook(request: Request) -> dict[str, str]:
    payload = await request.json()
    for message in _iter_messages(payload):
        try:
            await _handle_message(message)
        except Exception:
            logger.exception("Failed to handle WhatsApp message")
    return {"status": "received"}


async def _handle_message(message: dict[str, Any]) -> None:
    wa_id = message["from"]
    message_type = message.get("type")
    text = _extract_text(message)
    attachments: list[dict[str, Any]] = []

    if message_type in {"image", "document"}:
        media = message[message_type]
        filename = media.get("filename")
        if message_type == "image":
            filename = filename or f"{media['id']}.jpg"
            text = text or media.get("caption", "")
        if message_type == "document":
            text = text or media.get("caption", "")
        attachments.append(await whatsapp.download_media(media["id"], filename))
        memory.set_pending_file(
            wa_id,
            media["id"],
            filename or attachments[-1].get("filename"),
            attachments[-1].get("mime_type"),
        )

    if message_type not in {"text", "image", "document"}:
        await whatsapp.send_text(
            wa_id,
            "I can help with text, images, PDFs, Word, Excel, and CSV files first. "
            "Send one of those and tell me what you want done.",
        )
        return

    if message_type == "text" and not attachments and _looks_like_file_action(text):
        pending_file = memory.get_pending_file(wa_id)
        if pending_file:
            try:
                attachments.append(
                    await whatsapp.download_media(
                        pending_file["media_id"],
                        pending_file.get("filename"),
                    )
                )
                if pending_file.get("filename"):
                    attachments[-1]["filename"] = pending_file["filename"]
                if pending_file.get("mime_type"):
                    attachments[-1]["mime_type"] = pending_file["mime_type"]
                if _looks_like_excel_action(text) and not _is_excel_path_or_mime(attachments[-1]):
                    attachments[-1]["filename"] = _ensure_xlsx_filename(
                        str(attachments[-1].get("filename") or Path(attachments[-1]["path"]).name)
                    )
                    attachments[-1]["mime_type"] = XLSX_MIME_TYPE
                memory.add_message(wa_id, "user", text)
            except Exception:
                logger.exception("Failed to reload pending WhatsApp file")
                memory.clear_pending_file(wa_id)
                await whatsapp.send_text(
                    wa_id,
                    "File ya mwanzo ime-expire kabla sijai-download tena. Nitume tena hiyo Excel na instruction pamoja.",
                )
                return

    if len(attachments) >= 2 and _wants_comparison(text):
        comparison_text = await agent.answer(
            wa_id=wa_id,
            user_text=(
                "Compare the attached documents carefully for a stock manager. "
                "Find matching items, missing items, quantity differences, price/total differences, "
                "date/document number differences, supplier/customer differences, and recommended action. "
                "Return clean markdown with sections: Summary, Matches, Differences, Missing Items, Risks, Recommended Action. "
                "Do not invent values.\n\n"
                f"User instruction: {text or 'Compare these documents'}"
            ),
            attachments=attachments,
        )
        if _wants_pdf(text):
            comparison_file = create_pdf_report(comparison_text, settings.output_dir, "Document Comparison")
            await whatsapp.send_document(
                wa_id,
                comparison_file,
                caption="Nimelinganisha documents na kuandaa PDF report.",
                mime_type=PDF_MIME_TYPE,
            )
        else:
            comparison_file = create_excel_from_text(comparison_text, settings.output_dir, "Document Comparison")
            await whatsapp.send_document(
                wa_id,
                comparison_file,
                caption="Nimelinganisha documents na kuandaa Excel comparison tracker.",
                mime_type=XLSX_MIME_TYPE,
            )
        await whatsapp.send_text(wa_id, "Done, nimelinganisha documents na nimetuma file hapo juu.")
        return

    if await _handle_excel_attachment(wa_id, text, attachments):
        return

    if attachments and _wants_invoice_or_business_document_processing(text):
        analysis_text = await agent.answer(
            wa_id=wa_id,
            user_text=(
                "Analyze the attached business document as an invoice, receipt, delivery note, "
                "purchase order, stock note, or stock document. Extract all useful data. "
                "Return clean markdown with these exact sections when possible:\n"
                "# Document Analysis\n"
                "## Key Fields\n"
                "Field | Value\n"
                "Document Type | \n"
                "Document Number | \n"
                "Date | \n"
                "Supplier/Customer | \n"
                "Currency | \n"
                "Subtotal | \n"
                "Tax/VAT | \n"
                "Total | \n"
                "Payment Status | \n\n"
                "## Line Items\n"
                "Item | Description | Quantity | Unit Price | Total | Remarks\n\n"
                "## Issues Or Checks\n"
                "- Missing fields, mismatched totals, unclear numbers, duplicate items, or anything suspicious.\n\n"
                "## Recommended Action\n"
                "- What the stock manager should do next.\n\n"
                "Do not invent missing values. Use 'Not clear' when unsure.\n"
                f"User instruction: {text or 'Analyze this document'}"
            ),
            attachments=attachments,
        )

        if _wants_pdf(text):
            report_file = create_pdf_report(analysis_text, settings.output_dir, "Document Analysis")
            await whatsapp.send_document(
                wa_id,
                report_file,
                caption="Nimechambua document na kuandaa PDF report.",
                mime_type=PDF_MIME_TYPE,
            )
        elif _wants_word(text):
            report_file = create_docx_report(analysis_text, settings.output_dir, "Document Analysis")
            await whatsapp.send_document(
                wa_id,
                report_file,
                caption="Nimechambua document na kuandaa Word report.",
                mime_type=DOCX_MIME_TYPE,
            )
        else:
            excel_file = create_excel_from_text(analysis_text, settings.output_dir, "Document Analysis")
            await whatsapp.send_document(
                wa_id,
                excel_file,
                caption="Nimeextract data kwenye Excel tracker. Unaweza ku-download hapa.",
                mime_type=XLSX_MIME_TYPE,
            )

        await whatsapp.send_text(
            wa_id,
            "Done. Nimechambua document, nimeextract key fields/line items, na nimekuwekea file hapo juu.",
        )
        return

    if attachments and _wants_report_file(text):
        report_text = await agent.answer(
            wa_id=wa_id,
            user_text=(
                "Create a clean final report from the attached content. "
                "Use clear headings, organized sections, tables where useful, totals/issues/remarks if available. "
                "Return only the report content, no explanation.\n\n"
                f"User instruction: {text or 'Prepare a clean report'}"
            ),
            attachments=attachments,
        )
        if _wants_pdf(text):
            report_file = create_pdf_report(report_text, settings.output_dir, _report_title(text))
            await whatsapp.send_document(
                wa_id,
                report_file,
                caption="Nimekuandalia PDF report. Unaweza ku-download hapa.",
                mime_type=PDF_MIME_TYPE,
            )
        else:
            report_file = create_docx_report(report_text, settings.output_dir, _report_title(text))
            await whatsapp.send_document(
                wa_id,
                report_file,
                caption="Nimekuandalia Word report. Unaweza ku-download hapa.",
                mime_type=DOCX_MIME_TYPE,
            )
        await whatsapp.send_text(wa_id, "Done, nimetuma report file hapo juu.")
        return

    if attachments and _wants_excel_output(text) and not has_excel_attachment(attachments):
        source_text = combined_attachment_text(attachments)
        if source_text:
            excel_file = create_excel_from_text(source_text, settings.output_dir, _report_title(text))
            await whatsapp.send_document(
                wa_id,
                excel_file,
                caption="Nimeorganize data kwenye Excel file. Unaweza ku-download hapa.",
                mime_type=XLSX_MIME_TYPE,
            )
            await whatsapp.send_text(wa_id, "Done, nimeconvert/organize data kuwa Excel.")
            return

    if attachments and _wants_word_cleanup(text):
        docx_attachment = next((item for item in attachments if _is_docx_path_or_mime(item)), None)
        if docx_attachment:
            cleaned_doc = clean_docx_document(
                Path(docx_attachment["path"]),
                settings.output_dir,
                instruction_text=text,
            )
            await whatsapp.send_document(
                wa_id,
                cleaned_doc,
                caption="Nime-clean na kuformat Word document. Unaweza ku-download hapa.",
                mime_type=DOCX_MIME_TYPE,
            )
            await whatsapp.send_text(wa_id, "Done, nimetuma Word document mpya hapo juu.")
            return

    if _looks_like_missing_file_followup(text):
        await whatsapp.send_text(
            wa_id,
            "Pole, nitumie ile Excel file tena hapa na nita-clean kisha nirudishe kama downloadable file. "
            "Vercel haihifadhi file ya zamani kwa muda mrefu, so nahitaji attachment tena.",
        )
        return

    reply = await agent.answer(wa_id=wa_id, user_text=text, attachments=attachments)
    await _send_reply_messages(wa_id, reply)


async def _handle_excel_attachment(
    wa_id: str,
    text: str,
    attachments: list[dict[str, Any]],
) -> bool:
    if not has_excel_attachment(attachments):
        if attachments and _looks_like_excel_action(text):
            attachments[0]["filename"] = _ensure_xlsx_filename(
                str(attachments[0].get("filename") or Path(attachments[0]["path"]).name)
            )
            attachments[0]["mime_type"] = XLSX_MIME_TYPE
        else:
            return False

    if not has_excel_attachment(attachments):
        return False

    excel_attachment = next(
        item for item in attachments if _is_excel_path_or_mime(item)
    )
    instruction_text = _effective_file_instruction(wa_id, text)
    if not instruction_text:
        await whatsapp.send_text(
            wa_id,
            "Nimeipokea Excel. Niambie nifanye nini kwenye file hii?",
        )
        return True

    await whatsapp.send_text(wa_id, "Nimeipata Excel. Naifanyia kazi sasa...")
    logger.info("Excel edit started for %s with file %s", wa_id, excel_attachment.get("filename"))
    try:
        plan = await agent.plan_excel_edits(wa_id, instruction_text, excel_attachment)
        if plan.get("can_execute") is False:
            await whatsapp.send_text(
                wa_id,
                str(plan.get("question") or "Sijaelewa vizuri nifanye edit gani kwenye Excel. Niambie nibadilishe nini?"),
            )
            return True

        edit_result = edit_excel_workbook(
            Path(excel_attachment["path"]),
            settings.output_dir,
            instruction_text=instruction_text,
            plan=plan,
        )
        requested_actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
        if requested_actions and not edit_result.applied:
            await whatsapp.send_text(
                wa_id,
                str(plan.get("question") or "Nimefungua Excel, lakini sijaweza kuapply hiyo edit. Niambie column au mabadiliko unayotaka exactly."),
            )
            return True

        cleaned_file = edit_result.path
        applied_text = "; ".join(edit_result.applied)
        summary = str(plan.get("summary") or "").strip()
        caption = (
            "Nime-edit Excel file. Unaweza ku-download hii version hapa."
            if applied_text
            else "Nimeformat Excel file na kuongeza heading/format safi. Unaweza ku-download hii version hapa."
        )
        await whatsapp.send_document(
            wa_id,
            cleaned_file,
            caption=caption,
            mime_type=XLSX_MIME_TYPE,
        )
        logger.info("Excel edit file sent to %s: %s", wa_id, cleaned_file.name)
    except Exception:
        logger.exception("Excel edit failed for %s", wa_id)
        await whatsapp.send_text(
            wa_id,
            "Nimejaribu ku-edit Excel lakini imeshindikana kwenye server. Nitume file hiyo hiyo tena pamoja na instruction kwenye caption moja.",
        )
        return True
    memory.add_message(
        wa_id,
        "assistant",
        f"Sent edited Excel file: {cleaned_file.name}. {applied_text or summary}",
    )
    if applied_text:
        await whatsapp.send_text(wa_id, f"Done, nimetuma file mpya. {applied_text}.")
    elif summary:
        await whatsapp.send_text(wa_id, f"Done, nimetuma file mpya. {summary}.")
    else:
        await whatsapp.send_text(
            wa_id,
            "Done, nimetuma file mpya. Nimeweka heading, filter, freeze pane, na columns zisomeke vizuri.",
        )
    memory.clear_pending_file(wa_id)
    return True


def _iter_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages.extend(value.get("messages", []))
    return messages


def _extract_text(message: dict[str, Any]) -> str:
    if message.get("type") == "text":
        return message.get("text", {}).get("body", "").strip()
    return ""


def _effective_file_instruction(wa_id: str, text: str) -> str:
    if text.strip():
        return text.strip()
    previous = memory.last_user_message(wa_id).strip()
    if previous.lower().startswith("attached files:"):
        return ""
    return previous


def _is_excel_path_or_mime(attachment: dict[str, Any]) -> bool:
    path = Path(attachment["path"])
    mime_type = attachment.get("mime_type") or ""
    filename = str(attachment.get("filename") or path.name).lower()
    return (
        path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}
        or filename.endswith((".xlsx", ".xlsm", ".xls"))
        or mime_type
        in {
            XLSX_MIME_TYPE,
            XLS_MIME_TYPE,
            "application/vnd.ms-excel.sheet.macroenabled.12",
        }
    )


def _looks_like_excel_action(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in ["excel", "xlsx", "xls", "spreadsheet", "workbook"])


def _ensure_xlsx_filename(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith((".xlsx", ".xlsm", ".xls")):
        return filename
    return f"{Path(filename).stem or 'attachment'}.xlsx"


def _is_docx_path_or_mime(attachment: dict[str, Any]) -> bool:
    path = Path(attachment["path"])
    mime_type = attachment.get("mime_type") or ""
    filename = str(attachment.get("filename") or path.name).lower()
    return (
        path.suffix.lower() == ".docx"
        or filename.endswith(".docx")
        or mime_type == DOCX_MIME_TYPE
    )


def _looks_like_missing_file_followup(text: str) -> bool:
    lowered = text.lower()
    if not lowered:
        return False
    mentions_file = any(word in lowered for word in ["file", "excel", "download", "attachment"])
    missing = any(
        phrase in lowered
        for phrase in [
            "sija",
            "sioni",
            "iko wapi",
            "wapi",
            "mbona",
            "not received",
            "didn't receive",
            "no file",
            "where",
        ]
    )
    return mentions_file and missing


def _looks_like_file_action(text: str) -> bool:
    lowered = text.lower()
    if not lowered.strip():
        return False
    return any(
        word in lowered
        for word in [
            "excel",
            "file",
            "column",
            "columns",
            "summary",
            "summar",
            "report",
            "delete",
            "remove",
            "futa",
            "ondoa",
            "quantity",
            "quantiti",
            "simu",
            "product",
            "stock",
            "panga",
            "safisha",
            "rekebisha",
            "format",
            "polish",
            "clean",
            "sort",
            "total",
            "jumla",
            "chini",
        ]
    )


def _wants_pdf(text: str) -> bool:
    lowered = text.lower()
    return "pdf" in lowered


def _wants_word(text: str) -> bool:
    lowered = text.lower()
    return "word" in lowered or "docx" in lowered


def _wants_invoice_or_business_document_processing(text: str) -> bool:
    lowered = text.lower()
    document_words = [
        "invoice",
        "receipt",
        "risiti",
        "ankara",
        "delivery note",
        "purchase order",
        "po",
        "grn",
        "goods received",
        "supplier",
        "stock note",
        "stakabadhi",
        "document",
        "doc",
    ]
    action_words = [
        "analyze",
        "analyse",
        "chambua",
        "angalia",
        "check",
        "review",
        "extract",
        "toa",
        "organize",
        "panga",
        "weka kwenye excel",
        "convert",
        "summary",
        "summarize",
        "report",
    ]
    return any(word in lowered for word in document_words) and any(
        word in lowered for word in action_words
    )


def _wants_comparison(text: str) -> bool:
    lowered = text.lower()
    return any(
        word in lowered
        for word in [
            "compare",
            "comparison",
            "linganisha",
            "tofauti",
            "difference",
            "match",
            "reconcile",
            "reconciliation",
            "hakiki",
        ]
    )


def _wants_word_cleanup(text: str) -> bool:
    lowered = text.lower()
    wants_word = "word" in lowered or "docx" in lowered or "document" in lowered
    wants_cleanup = any(
        word in lowered
        for word in [
            "clean",
            "format",
            "edit",
            "panga",
            "safisha",
            "rekebisha",
            "weka sawa",
        ]
    )
    return wants_word and wants_cleanup


def _wants_report_file(text: str) -> bool:
    lowered = text.lower()
    wants_report = any(
        word in lowered
        for word in [
            "report",
            "ripoti",
            "pdf",
            "word",
            "docx",
            "document",
            "andaa",
            "prepare",
            "summary",
            "summarize",
        ]
    )
    wants_excel = _wants_excel_output(text)
    return wants_report and not wants_excel


def _wants_excel_output(text: str) -> bool:
    lowered = text.lower()
    return any(
        word in lowered
        for word in [
            "excel",
            "xlsx",
            "spreadsheet",
            "table",
            "jedwali",
            "convert to excel",
            "weka kwenye excel",
        ]
    )


def _report_title(text: str) -> str:
    lowered = text.lower()
    if "stock" in lowered or "stoo" in lowered:
        return "Stock Report"
    if "daily" in lowered or "leo" in lowered:
        return "Daily Report"
    if "weekly" in lowered or "wiki" in lowered:
        return "Weekly Report"
    return "Aggie Report"


async def _send_reply_messages(wa_id: str, reply: str) -> None:
    parts = [part.strip() for part in reply.split("[NEXT_MESSAGE]", 1) if part.strip()]
    if not parts:
        await whatsapp.send_text(wa_id, "Nimekupata.")
        return
    for part in parts[:2]:
        await whatsapp.send_text(wa_id, part)
