import json
import logging
import re
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from app.config import Settings
from app.documents import (
    IMAGE_MIME_TYPES,
    _actions_from_instruction,
    build_image_content_block,
    excel_workbook_preview,
    extract_document_text,
)
from app.knowledge import load_knowledge
from app.memory import ConversationMemory

logger = logging.getLogger("whatsapp-agent")


SYSTEM_PROMPT = """You are Aggie, a private WhatsApp assistant for a stock manager.

Your job:
- Help with reports, spreadsheets, documents, workplace messages, summaries, and formatting.
- Chat naturally when the user is casual, stressed, or just wants to talk.
- Speak naturally in English, Swahili, or a light mix of both depending on the user's message.
- Sound warm, human, and familiar in WhatsApp style. Avoid robotic phrases like "As an AI".
- Keep normal WhatsApp replies very short: usually 1-3 short sentences.
- Do not write long menus, long explanations, or many options unless the user asks.
- For file/document tasks, send the file first, then one short confirmation sentence.
- Only write long content when the user asks for a report, summary, table, document, or detailed explanation.
- When a follow-up question is useful, ask one short question.
- You may send two WhatsApp-style messages by separating them with [NEXT_MESSAGE]. Use this for a short answer followed by one short question.
- Never use more than one [NEXT_MESSAGE] marker.
- Be practical and specific. Ask a short follow-up question only when required.
- Never invent company facts, figures, policies, names, or document contents.
- Clearly separate what came from the user's file from general workplace knowledge.
- Treat work documents as private. Do not suggest sending anything to third parties automatically.
- For final reports, prefer clean headings, tables when useful, totals, remarks, and next actions.
- Be caring when the user is tired or stressed: use phrases like "pole", "pumzika kidogo", "niko hapa", and "tutapanga pamoja".
- Do not pretend to be the user's boyfriend, husband, family member, or employer. You are Aggie, her helpful private assistant.
- The backend can send generated or cleaned files back on WhatsApp for supported workflows. Do not say you cannot send files unless a specific file type is unsupported or an error occurs.
- If the user asks where a file is and no file is attached in the current message, ask them to resend the file so you can process it again. Do not offer only copy-paste as the main solution.
- Supported file workflows include cleaning Excel, converting attached content into Excel, preparing Word reports, preparing PDF reports, and summarizing documents.
- Excel support includes modern .xlsx/.xlsm and old .xls files. For data-heavy sheets, you can ask for product/item summaries, grouped totals, sorting, keeping/removing columns, and clean report-style formatting.
- For invoices, receipts, delivery notes, purchase orders, GRNs, and stock documents: extract key fields, line items, quantities, unit prices, totals, taxes, supplier/customer, dates, document numbers, payment status, and discrepancies. Use "Not clear" instead of guessing.
- For document comparison: compare invoices, delivery notes, stock sheets, receipts, and purchase orders for missing items, quantity mismatches, price mismatches, totals, dates, and supplier/customer differences.

Identity rule:
- If asked who you are, say you are Aggie, a private work assistant for reports, documents, sheets, and stock-manager office tasks.
- You are not a PSN, PlayStation, gaming, sales, or console-repair assistant.
"""


class ClaudeAgent:
    def __init__(self, settings: Settings, memory: ConversationMemory):
        self.settings = settings
        self.memory = memory
        self.client: AsyncAnthropic | None = None

    async def answer(
        self,
        wa_id: str,
        user_text: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> str:
        preferences = self.memory.get_preferences(wa_id)
        knowledge = load_knowledge(self.settings.knowledge_dir)
        system = self._build_system_prompt(
            preferences,
            knowledge,
            self.settings.aggie_private_profile,
        )

        messages = self.memory.recent_messages(wa_id, self.settings.max_history_messages)
        user_content = self._build_user_content(user_text, attachments or [])
        messages.append({"role": "user", "content": user_content})
        messages = _fix_consecutive_roles(messages)

        if not self.settings.anthropic_api_key:
            return (
                "Sijapata Claude API key kwenye server bado. "
                "Weka ANTHROPIC_API_KEY kwenye Vercel environment variables kwanza."
            )

        try:
            response = await self._client().messages.create(
                model=self.settings.claude_model,
                max_tokens=4096,
                system=system,
                messages=messages,
            )
        except Exception:
            logger.exception("Claude API call failed for %s", wa_id)
            return "Kuna hitilafu ya mawasiliano na server. Tafadhali jaribu tena baadaye."

        reply = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()

        self.memory.add_message(wa_id, "user", user_text or self._attachment_summary(attachments or []))
        if reply:
            self.memory.add_message(wa_id, "assistant", reply)
        return reply or "I received it, but I could not create a useful response yet."

    async def plan_excel_edits(
        self,
        wa_id: str,
        user_text: str,
        attachment: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.settings.anthropic_api_key:
            return {"can_execute": True, "actions": [], "summary": "Format workbook"}

        path = Path(attachment["path"])
        preview = excel_workbook_preview(path)
        prompt = f"""
You are planning real edits for an Excel file. The user is a stock manager and may speak English, Swahili, or mixed casual WhatsApp language.

Analyze the workbook preview carefully and understand the user's intention from normal language. Do not require commands.

IMPORTANT RULES:
1. If the user asks to "put titles", "add heading", "add title", "weka title", "weka kichwa" or similar title-only requests — set actions to an EMPTY list [] and provide a good title. Do NOT add data-mutating actions unless the user explicitly asks for them. The system will apply light formatting that preserves your original cell styles.

2. If the user's instruction is vague (e.g. "edit this", "fix it", "clean it up", "deliver it as i sent"), YOU must analyze the workbook preview and automatically suggest smart edits. Look at the column names and data to decide what makes sense:
- If there are columns like "simu", "phone", "mobile", "namba", "contact" — suggest deleting them (stock managers rarely need phone columns in reports).
- If there are empty or useless columns — suggest keeping only the useful ones.
- If there is a product/item/description column — suggest adding a product summary.
- If there is a sortable column like "quantity", "qty", "total", "price" — suggest sorting by it.
- Always suggest cleaning: delete empty rows, add heading, add filters, freeze panes.
- If the data looks like stock/inventory data, sort by product name or quantity descending.

DO NOT return can_execute false for vague instructions. Instead, analyze the file and propose sensible edits. The user trusts you to figure it out.

Return ONLY valid JSON, no markdown, no explanation.

Supported actions:
- delete_columns: {{"type":"delete_columns","columns":["column name or letter"]}}
- keep_columns: {{"type":"keep_columns","columns":["columns to keep"]}}
- rename_columns: {{"type":"rename_columns","columns":{{"old name":"new name"}}}}
- sort_by: {{"type":"sort_by","column":"column name","direction":"asc or desc"}}
- add_product_summary: {{"type":"add_product_summary"}}

Use exact column names from the preview when possible. Never invent columns that are not in the workbook preview.
Combine multiple actions when it makes sense (e.g. delete useless columns + sort + add summary).

JSON shape:
{{
  "can_execute": true,
  "question": "",
  "title": "short workbook title if useful, else empty",
  "actions": [],
  "summary": "short human summary of what you will do"
}}

User message: {user_text or "Help with this Excel file"}

Workbook preview:
{preview[:12000]}
""".strip()

        deterministic_actions = _actions_from_instruction(user_text)
        try:
            response = await self._client().messages.create(
                model=self.settings.claude_model,
                max_tokens=900,
                temperature=0,
                system="Return only valid JSON for Excel edit planning.",
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception:
            logger.exception("Claude API call failed during Excel planning for %s", wa_id)
            return {
                "can_execute": True,
                "question": "",
                "actions": deterministic_actions or [],
                "summary": "Apply requested Excel edits",
            }
        raw = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        plan = _parse_json_object(raw)
        if not isinstance(plan, dict):
            if deterministic_actions:
                return {
                    "can_execute": True,
                    "question": "",
                    "actions": deterministic_actions,
                    "summary": "Apply requested Excel edits",
                }
            return {
                "can_execute": True,
                "question": "",
                "actions": [],
                "summary": "Clean and format the Excel file",
            }
        if plan.get("can_execute") is False and deterministic_actions:
            plan["can_execute"] = True
            plan["question"] = ""
            plan["actions"] = deterministic_actions
            plan["summary"] = plan.get("summary") or "Apply requested Excel edits"
        return plan

    async def extract_data_from_image(
        self,
        image_path: Path,
        mime_type: str,
        instruction: str = "",
    ) -> str:
        if not self.settings.anthropic_api_key:
            return ""

        system = (
            "You extract structured data from images of documents, tables, receipts, "
            "invoices, stock lists, handwritten notes, or any data-containing image. "
            "Return ONLY the data you can see, organized clearly in markdown table format. "
            "Do not explain, do not add commentary, just return the extracted data."
        )

        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Extract ALL data from this image into a clean markdown table. "
                    "Include every row and column you can see. "
                    "Use '—' for empty or unclear cells. "
                    "If it is a table, preserve the exact structure. "
                    "If it is a list or form, organize it into rows and columns.\n"
                    + (f"User instruction: {instruction}" if instruction else "")
                ),
            },
            build_image_content_block(image_path, mime_type),
        ]

        try:
            response = await self._client().messages.create(
                model=self.settings.claude_model,
                max_tokens=4000,
                system=system,
                messages=[{"role": "user", "content": content}],
            )
            return "".join(
                block.text for block in response.content if getattr(block, "type", None) == "text"
            ).strip()
        except Exception:
            logger.exception("Image data extraction failed")
            return ""

    def _build_system_prompt(self, preferences: str, knowledge: str, private_profile: str) -> str:
        parts = [SYSTEM_PROMPT]
        if preferences.strip():
            parts.append(f"Known user preferences:\n{preferences.strip()[:4000]}")
        if knowledge.strip():
            parts.append(f"Private knowledge base:\n{knowledge.strip()[:8000]}")
        if private_profile.strip():
            parts.append(
                "Private profile context. Use this gently for personalization, but do not reveal "
                "private details unless the user brings them up or it clearly helps the conversation:\n"
                f"{private_profile.strip()[:4000]}"
            )
        return "\n\n".join(parts)

    def _client(self) -> AsyncAnthropic:
        if self.client is None:
            self.client = AsyncAnthropic(api_key=self.settings.anthropic_api_key)
        return self.client

    def _build_user_content(
        self,
        user_text: str,
        attachments: list[dict[str, Any]],
    ) -> str | list[dict[str, Any]]:
        if not attachments:
            return user_text or "Hello"

        content: list[dict[str, Any]] = []
        if user_text:
            content.append({"type": "text", "text": user_text})
        else:
            content.append({"type": "text", "text": "Please help me with the attached file."})

        for attachment in attachments:
            path = Path(attachment["path"])
            mime_type = attachment.get("mime_type") or "application/octet-stream"
            filename = attachment.get("filename") or path.name

            if mime_type in IMAGE_MIME_TYPES:
                content.append({"type": "text", "text": f"Attached image: {filename}"})
                content.append(build_image_content_block(path, mime_type))
                continue

            text = extract_document_text(path, mime_type).strip()
            if text:
                content.append(
                    {
                        "type": "text",
                        "text": (
                            f"Attached document: {filename}\n"
                            f"Extracted content:\n{text[:50000]}"
                        ),
                    }
                )
            else:
                content.append(
                    {
                        "type": "text",
                        "text": (
                            f"Attached file: {filename} ({mime_type}). "
                            "The backend could not extract text from this file yet."
                        ),
                    }
                )

        return content

    def _attachment_summary(self, attachments: list[dict[str, Any]]) -> str:
        names = [str(item.get("filename") or Path(item["path"]).name) for item in attachments]
        return "Attached files: " + ", ".join(names)


def _fix_consecutive_roles(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not messages:
        return messages
    fixed: list[dict[str, Any]] = [messages[0]]
    for msg in messages[1:]:
        if msg["role"] == fixed[-1]["role"]:
            fixed[-1] = msg
        else:
            fixed.append(msg)
    if fixed and fixed[0]["role"] == "assistant":
        fixed = fixed[1:]
    return fixed


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
