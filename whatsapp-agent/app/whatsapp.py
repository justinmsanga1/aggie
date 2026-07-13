import asyncio
import logging
from pathlib import Path
from typing import Any
import mimetypes

import httpx

from app.config import Settings

logger = logging.getLogger("whatsapp-agent")


class WhatsAppClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = f"https://graph.facebook.com/{settings.meta_graph_version}"

    async def send_text(self, to: str, text: str) -> None:
        if not self.settings.meta_access_token or not self.settings.meta_phone_number_id:
            raise RuntimeError("Meta WhatsApp credentials are not configured.")

        url = f"{self.base_url}/{self.settings.meta_phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text[:4000]},
        }
        headers = {"Authorization": f"Bearer {self.settings.meta_access_token}"}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()

    async def upload_media(self, path: Path, mime_type: str | None = None) -> str:
        if not self.settings.meta_access_token or not self.settings.meta_phone_number_id:
            raise RuntimeError("Meta WhatsApp credentials are not configured.")

        resolved_mime = mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        url = f"{self.base_url}/{self.settings.meta_phone_number_id}/media"
        headers = {"Authorization": f"Bearer {self.settings.meta_access_token}"}
        data = {
            "messaging_product": "whatsapp",
            "type": resolved_mime,
        }
        with path.open("rb") as file:
            files = {"file": (path.name, file, resolved_mime)}
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(url, data=data, files=files, headers=headers)
                response.raise_for_status()
                return response.json()["id"]

    async def send_document(
        self,
        to: str,
        path: Path,
        caption: str | None = None,
        mime_type: str | None = None,
    ) -> None:
        media_id = await self.upload_media(path, mime_type)
        url = f"{self.base_url}/{self.settings.meta_phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "document",
            "document": {
                "id": media_id,
                "filename": path.name,
            },
        }
        if caption:
            payload["document"]["caption"] = caption[:1024]

        headers = {"Authorization": f"Bearer {self.settings.meta_access_token}"}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()

    async def get_media_metadata(self, media_id: str) -> dict[str, Any]:
        url = f"{self.base_url}/{media_id}"
        headers = {"Authorization": f"Bearer {self.settings.meta_access_token}"}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    async def download_media(self, media_id: str, filename: str | None = None) -> dict[str, Any]:
        metadata = await self.get_media_metadata(media_id)
        media_url = metadata.get("url")
        if not media_url:
            raise ValueError(f"Media URL not found for media_id={media_id} (file may have expired)")
        mime_type = metadata.get("mime_type") or "application/octet-stream"
        suffix = _suffix_for_mime(mime_type)
        safe_name = _safe_filename(filename or f"{media_id}{suffix}")
        target = self.settings.upload_dir / safe_name

        headers = {"Authorization": f"Bearer {self.settings.meta_access_token}"}
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                    response = await client.get(media_url, headers=headers)
                    response.raise_for_status()
                    content = response.content
                    if not content:
                        raise ValueError("Downloaded file is empty")
                    target.write_bytes(content)
                    return {
                        "path": str(target),
                        "filename": safe_name,
                        "mime_type": mime_type,
                        "media_id": media_id,
                    }
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code in (404, 410):
                    raise ValueError(
                        f"File ya WhatsApp imeshaiisha muda (expired). Tuma tena file."
                    ) from exc
                logger.warning("Download attempt %d failed: %s", attempt + 1, exc)
            except (httpx.RequestError, ValueError) as exc:
                last_error = exc
                logger.warning("Download attempt %d failed: %s", attempt + 1, exc)
            if attempt < 2:
                await asyncio.sleep(1 * (attempt + 1))
        raise RuntimeError(f"Failed to download media after 3 attempts: {last_error}")


def _safe_filename(filename: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in ".-_" else "_" for char in filename)
    return cleaned[:140] or "attachment.bin"


def _suffix_for_mime(mime_type: str) -> str:
    mapping = {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.ms-excel": ".xls",
        "text/csv": ".csv",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    return mapping.get(mime_type, ".bin")
