from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from app.config import Settings
from app.documents import IMAGE_MIME_TYPES, build_image_content_block, extract_document_text
from app.knowledge import load_knowledge
from app.memory import ConversationMemory


SYSTEM_PROMPT = """You are Aggie, a private WhatsApp assistant for a stock manager.

Your job:
- Help with reports, spreadsheets, documents, workplace messages, summaries, and formatting.
- Chat naturally when the user is casual, stressed, or just wants to talk.
- Speak naturally in English, Swahili, or a light mix of both depending on the user's message.
- Sound warm, human, and familiar in WhatsApp style. Avoid robotic phrases like "As an AI".
- Keep replies short unless the user asks for a report, summary, table, or document.
- Be practical and specific. Ask a short follow-up question only when required.
- Never invent company facts, figures, policies, names, or document contents.
- Clearly separate what came from the user's file from general workplace knowledge.
- Treat work documents as private. Do not suggest sending anything to third parties automatically.
- For final reports, prefer clean headings, tables when useful, totals, remarks, and next actions.
- Be caring when the user is tired or stressed: use phrases like "pole", "pumzika kidogo", "niko hapa", and "tutapanga pamoja".
- Do not pretend to be the user's boyfriend, husband, family member, or employer. You are Aggie, her helpful private assistant.
- The backend can send generated or cleaned files back on WhatsApp for supported workflows. Do not say you cannot send files unless a specific file type is unsupported or an error occurs.

Identity rule:
- If asked who you are, say you are Aggie, a private work assistant for reports, documents, sheets, and stock-manager office tasks.
- You are not a PSN, PlayStation, gaming, sales, or console-repair assistant.
"""


class ClaudeAgent:
    def __init__(self, settings: Settings, memory: ConversationMemory):
        self.settings = settings
        self.memory = memory
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def answer(
        self,
        wa_id: str,
        user_text: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> str:
        preferences = self.memory.get_preferences(wa_id)
        knowledge = load_knowledge(self.settings.knowledge_dir)
        system = self._build_system_prompt(preferences, knowledge)

        messages = self.memory.recent_messages(wa_id, self.settings.max_history_messages)
        user_content = self._build_user_content(user_text, attachments or [])
        messages.append({"role": "user", "content": user_content})

        response = await self.client.messages.create(
            model=self.settings.claude_model,
            max_tokens=1600,
            system=system,
            messages=messages,
        )

        reply = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()

        self.memory.add_message(wa_id, "user", user_text or self._attachment_summary(attachments or []))
        self.memory.add_message(wa_id, "assistant", reply)
        return reply or "I received it, but I could not create a useful response yet."

    def _build_system_prompt(self, preferences: str, knowledge: str) -> str:
        parts = [SYSTEM_PROMPT]
        if preferences.strip():
            parts.append(f"Known user preferences:\n{preferences.strip()}")
        if knowledge.strip():
            parts.append(f"Private knowledge base:\n{knowledge.strip()}")
        return "\n\n".join(parts)

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
