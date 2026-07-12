import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.claude_agent import ClaudeAgent
from app.config import get_settings
from app.documents import XLSX_MIME_TYPE, clean_excel_workbook, should_create_clean_excel
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

    if message_type not in {"text", "image", "document"}:
        await whatsapp.send_text(
            wa_id,
            "I can help with text, images, PDFs, Word, Excel, and CSV files first. "
            "Send one of those and tell me what you want done.",
        )
        return

    if should_create_clean_excel(text, attachments):
        excel_attachment = next(
            item for item in attachments if Path(item["path"]).suffix.lower() in {".xlsx", ".xlsm"}
        )
        cleaned_file = clean_excel_workbook(Path(excel_attachment["path"]), settings.output_dir)
        await whatsapp.send_document(
            wa_id,
            cleaned_file,
            caption="Nimekusafishia Excel file. Unaweza ku-download hii version hapa.",
            mime_type=XLSX_MIME_TYPE,
        )
        memory.add_message(
            wa_id,
            "assistant",
            f"Sent cleaned Excel file: {cleaned_file.name}",
        )
        await whatsapp.send_text(
            wa_id,
            "Done, nimetuma file mpya hapo juu. Nimeondoa styling nzito/rangi, nimepanga columns, na nimeweka sheet iwe rahisi kusoma.",
        )
        return

    reply = await agent.answer(wa_id=wa_id, user_text=text, attachments=attachments)
    await whatsapp.send_text(wa_id, reply)


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
