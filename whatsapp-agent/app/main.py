import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.claude_agent import ClaudeAgent
from app import blob_store
from app.config import get_settings
from app.documents import (
    DOCX_MIME_TYPE,
    IMAGE_MIME_TYPES,
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
        "persistent_pending_file_store_set": bool(
            (settings.kv_rest_api_url and settings.kv_rest_api_token)
            or (settings.upstash_redis_rest_url and settings.upstash_redis_rest_token)
            or settings.blob_read_write_token
        ),
        "blob_store_set": bool(settings.blob_read_write_token),
    }


@app.get("/debug/jobs")
async def debug_jobs(wa_id: str | None = None, limit: int = 10) -> dict[str, Any]:
    return {"jobs": memory.recent_document_jobs(wa_id=wa_id, limit=limit)}


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
        message_id = message.get("id", "")
        if message_id and memory.is_message_processed(message_id):
            logger.info("Skipping duplicate message %s", message_id)
            continue
        try:
            await _handle_message(message)
        except Exception:
            logger.exception("Failed to handle WhatsApp message")
            continue
        if message_id:
            memory.mark_message_processed(message_id)
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
        source_blob_path = _store_attachment_blob(wa_id, attachments[-1])
        memory.set_pending_file(
            wa_id,
            media["id"],
            filename or attachments[-1].get("filename"),
            attachments[-1].get("mime_type"),
            source_blob_path,
        )
        if message_type == "document":
            memory.create_document_job(
                wa_id,
                media["id"],
                filename or attachments[-1].get("filename"),
                attachments[-1].get("mime_type"),
                instruction=text,
                source_blob_path=source_blob_path,
            )

    if message_type not in {"text", "image", "document"}:
        await whatsapp.send_text(
            wa_id,
            "I can help with text, images, PDFs, Word, Excel, and CSV files first. "
            "Send one of those and tell me what you want done.",
        )
        return

    if message_type == "text" and not attachments and _looks_like_file_action(text):
        pending_job = memory.latest_document_job(wa_id)
        pending_file = memory.get_pending_file(wa_id)
        if not pending_job and not pending_file:
            logger.info("No pending file for %s, falling through to chat", wa_id)
        else:
            if not _looks_like_confirmation(text):
                memory.set_pending_instruction(wa_id, text)
        if pending_job and pending_job.get("media_id"):
            try:
                attachment = await _reload_pending_attachment(pending_job)
                attachments.append(attachment)
                if pending_job.get("filename"):
                    attachments[-1]["filename"] = pending_job["filename"]
                if pending_job.get("mime_type"):
                    attachments[-1]["mime_type"] = pending_job["mime_type"]
                if _looks_like_excel_action(text) and not _is_excel_path_or_mime(attachments[-1]):
                    attachments[-1]["filename"] = _ensure_xlsx_filename(
                        str(attachments[-1].get("filename") or Path(attachments[-1]["path"]).name)
                    )
                    attachments[-1]["mime_type"] = XLSX_MIME_TYPE
                pending_job = memory.update_document_job(
                    pending_job,
                    status="instruction_received",
                    event="instruction_received",
                    detail=text,
                    instruction=text if not _looks_like_confirmation(text) else pending_job.get("instruction", ""),
                )
                attachments[-1]["job_id"] = pending_job["job_id"]
                memory.add_message(wa_id, "user", text)
            except Exception:
                logger.exception("Failed to reload pending WhatsApp file")
                memory.clear_pending_file(wa_id)
                await whatsapp.send_text(
                    wa_id,
                    "File ya mwanzo ime-expire kabla sijai-download tena. Nitume tena hiyo Excel na instruction pamoja.",
                )
                return
        elif pending_file:
            try:
                attachments.append(await _reload_pending_attachment(pending_file))
                memory.add_message(wa_id, "user", text)
            except Exception:
                logger.exception("Failed to reload pending WhatsApp file")
                memory.clear_pending_file(wa_id)
                await whatsapp.send_text(
                    wa_id,
                    "File ya mwanzo ime-expire kabla sijai-download tena. Nitume tena hiyo Excel na instruction pamoja.",
                )
                return
        else:
            logger.info("No pending file for %s, falling through to chat", wa_id)

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
        if not source_text:
            image_attachment = next(
                (a for a in attachments if (a.get("mime_type") or "") in IMAGE_MIME_TYPES),
                None,
            )
            if image_attachment:
                await whatsapp.send_text(wa_id, "Na extract data kutoka kwenye picha...")
                source_text = await agent.extract_data_from_image(
                    Path(image_attachment["path"]),
                    str(image_attachment.get("mime_type") or "image/jpeg"),
                    instruction=text,
                )
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
            non_image = next(
                (a for a in attachments if (a.get("mime_type") or "") not in IMAGE_MIME_TYPES),
                None,
            )
            if non_image:
                non_image["filename"] = _ensure_xlsx_filename(
                    str(non_image.get("filename") or Path(non_image["path"]).name)
                )
                non_image["mime_type"] = XLSX_MIME_TYPE
            else:
                return False
        else:
            return False

    if not has_excel_attachment(attachments):
        return False

    excel_attachment = next(
        item for item in attachments if _is_excel_path_or_mime(item)
    )
    job = _job_for_attachment(wa_id, excel_attachment)
    instruction_text = _effective_file_instruction(wa_id, text)
    if job and job.get("instruction") and not text.strip():
        instruction_text = str(job["instruction"])
    if not instruction_text:
        await whatsapp.send_text(
            wa_id,
            "Nimeipokea Excel. Niambie nifanye nini kwenye file hii?",
        )
        return True

    await whatsapp.send_text(wa_id, "Nimeipata Excel. Naifanyia kazi sasa...")
    logger.info("Excel edit started for %s with file %s", wa_id, excel_attachment.get("filename"))
    try:
        if job:
            job = memory.update_document_job(
                job,
                status="planning",
                event="planning",
                detail=instruction_text,
                instruction=instruction_text,
            )
        plan = await agent.plan_excel_edits(wa_id, instruction_text, excel_attachment)
        if plan.get("can_execute") is False:
            if job:
                memory.update_document_job(
                    job,
                    status="needs_clarification",
                    event="needs_clarification",
                    detail=str(plan.get("question") or ""),
                )
            await whatsapp.send_text(
                wa_id,
                str(plan.get("question") or "Sijaelewa vizuri nifanye edit gani kwenye Excel. Niambie nibadilishe nini?"),
            )
            return True

        if job:
            job = memory.update_document_job(job, status="executing", event="executing", detail=str(plan))
        edit_result = edit_excel_workbook(
            Path(excel_attachment["path"]),
            settings.output_dir,
            instruction_text=instruction_text,
            plan=plan,
        )
        if job:
            job = memory.update_document_job(
                job,
                status="verifying",
                event="verified" if edit_result.verified else "verification_failed",
                detail="; ".join(edit_result.verification_errors or []),
            )
        if not edit_result.verified:
            if job:
                memory.update_document_job(
                    job,
                    status="failed",
                    event="failed",
                    detail="; ".join(edit_result.verification_errors or []),
                    error="; ".join(edit_result.verification_errors or []),
                )
            await whatsapp.send_text(
                wa_id,
                "Nime-edit file lakini verification haijapita, kwa hiyo sijaituma kama imekamilika. Nitume file tena na instruction kwenye caption moja.",
            )
            return True
        requested_actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
        if requested_actions and not edit_result.applied:
            if job:
                memory.update_document_job(
                    job,
                    status="needs_clarification",
                    event="no_actions_applied",
                    detail=str(plan.get("question") or ""),
                )
            await whatsapp.send_text(
                wa_id,
                str(plan.get("question") or "Nimefungua Excel, lakini sijaweza kuapply hiyo edit. Niambie column au mabadiliko unayotaka exactly."),
            )
            return True

        cleaned_file = edit_result.path
        result_blob_path = ""
        if job:
            result_blob_path = _store_output_blob(wa_id, job["job_id"], cleaned_file, XLSX_MIME_TYPE)
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
        if job:
            job = memory.update_document_job(
                job,
                status="sent",
                event="sent",
                detail=cleaned_file.name,
                result_filename=cleaned_file.name,
                result_blob_path=result_blob_path,
            )
    except Exception:
        logger.exception("Excel edit failed for %s", wa_id)
        if job:
            memory.update_document_job(job, status="failed", event="failed", detail="exception", error="exception")
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
    memory.clear_pending_instruction(wa_id)
    return True


async def _reload_pending_attachment(record: dict[str, Any]) -> dict[str, Any]:
    filename = str(record.get("filename") or "attachment.xlsx")
    mime_type = str(record.get("mime_type") or "application/octet-stream")
    blob_path = str(record.get("source_blob_path") or record.get("blob_path") or "")
    if blob_path:
        target = settings.upload_dir / blob_store.safe_blob_name(filename)
        if blob_store.get_to_file(blob_path, target):
            return {
                "path": str(target),
                "filename": target.name,
                "mime_type": mime_type,
                "media_id": record.get("media_id", ""),
                "blob_path": blob_path,
            }

    return await whatsapp.download_media(str(record["media_id"]), filename)


def _store_attachment_blob(wa_id: str, attachment: dict[str, Any]) -> str:
    if not blob_store.is_configured():
        return ""
    path = Path(attachment["path"])
    filename = blob_store.safe_blob_name(str(attachment.get("filename") or path.name))
    media_id = blob_store.safe_blob_name(str(attachment.get("media_id") or "media"))
    pathname = f"uploads/{blob_store.safe_blob_name(wa_id)}/{media_id}-{filename}"
    return blob_store.put_file(path, pathname, str(attachment.get("mime_type") or "application/octet-stream")) or ""


def _store_output_blob(wa_id: str, job_id: str, path: Path, mime_type: str) -> str:
    if not blob_store.is_configured():
        return ""
    pathname = (
        f"outputs/{blob_store.safe_blob_name(wa_id)}/"
        f"{blob_store.safe_blob_name(job_id)}/{blob_store.safe_blob_name(path.name)}"
    )
    return blob_store.put_file(path, pathname, mime_type) or ""


def _job_for_attachment(wa_id: str, attachment: dict[str, Any]) -> dict[str, Any] | None:
    job_id = attachment.get("job_id")
    if job_id:
        job = memory.get_document_job(str(job_id))
        if job:
            return job
    latest = memory.latest_document_job(wa_id)
    if latest and latest.get("media_id") == attachment.get("media_id"):
        return latest
    return None


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
    if text.strip() and not _looks_like_confirmation(text):
        return text.strip()
    pending_instruction = memory.get_pending_instruction(wa_id).strip()
    if pending_instruction:
        memory.clear_pending_instruction(wa_id)
        return pending_instruction
    return ""


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
    has_file_ref = any(
        word in lowered
        for word in ["excel", "xlsx", "xls", "spreadsheet", "workbook", "file"]
    )
    has_action = any(
        word in lowered
        for word in [
            "column", "columns", "delete", "remove", "futa", "ondoa",
            "sort", "panga", "clean", "safisha", "rekebisha", "format",
            "summary", "summar", "product summary",
            "heading", "title", "kichwa",
            "quantity", "quantiti", "simu", "phone",
            "total", "jumla", "chini",
            "edit", "hariri", "tengeneza",
            "polish", "keep", "rename", "badilisha",
        ]
    )
    return has_file_ref or has_action


def _looks_like_confirmation(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered in {"yes", "yeah", "yap", "yep", "ok", "okay", "sawa", "ndio", "ndiyo", "poa"}


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
        "grn",
        "goods received",
        "supplier",
        "stock note",
        "stakabadhi",
        "document",
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
