import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import httpx


logger = logging.getLogger("whatsapp-agent.blob")

BLOB_API_URL = "https://vercel.com/api/blob"
BLOB_API_VERSION = "12"


def is_configured() -> bool:
    return bool(_token())


def put_json(pathname: str, value: dict[str, Any]) -> str | None:
    body = json.dumps(value, ensure_ascii=False).encode("utf-8")
    return put_bytes(pathname, body, "application/json")


def get_json(pathname: str) -> dict[str, Any] | None:
    data = get_bytes(pathname)
    if not data:
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def put_file(source: Path, pathname: str, content_type: str | None = None) -> str | None:
    if not source.exists():
        return None
    return put_bytes(
        pathname,
        source.read_bytes(),
        content_type or "application/octet-stream",
    )


def get_to_file(pathname: str, target: Path) -> bool:
    data = get_bytes(pathname)
    if data is None:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return True


def put_bytes(pathname: str, body: bytes, content_type: str) -> str | None:
    config = _auth_config()
    if not config:
        return None
    token, store_id = config
    try:
        params = urlencode({"pathname": _clean_pathname(pathname)})
        headers = _api_headers(token, store_id)
        headers.update(
            {
                "x-vercel-blob-access": "private",
                "x-add-random-suffix": "0",
                "x-allow-overwrite": "1",
                "x-content-type": content_type,
            }
        )
        with httpx.Client(timeout=45) as client:
            response = client.put(
                f"{BLOB_API_URL}/?{params}",
                content=body,
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
            return str(payload.get("pathname") or pathname)
    except Exception:
        logger.exception("Failed to put blob %s", pathname)
        return None


def get_bytes(pathname: str) -> bytes | None:
    config = _auth_config()
    if not config:
        return None
    token, store_id = config
    try:
        url = _blob_url(store_id, _clean_pathname(pathname))
        with httpx.Client(timeout=45, follow_redirects=True) as client:
            response = client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.content
    except Exception:
        logger.exception("Failed to get blob %s", pathname)
        return None


def delete(pathname: str) -> None:
    config = _auth_config()
    if not config:
        return
    token, store_id = config
    try:
        with httpx.Client(timeout=20) as client:
            client.post(
                f"{BLOB_API_URL}/delete",
                headers={
                    **_api_headers(token, store_id),
                    "content-type": "application/json",
                },
                json={"urls": [_clean_pathname(pathname)]},
            )
    except Exception:
        logger.exception("Failed to delete blob %s", pathname)


def safe_blob_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in ".-_" else "_" for char in value)
    return cleaned[:140] or "file.bin"


def _auth_config() -> tuple[str, str] | None:
    token = _token()
    if not token:
        return None
    store_id = _store_id_from_token(token)
    if not store_id:
        return None
    return token, store_id


def _token() -> str:
    import os

    return os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip().strip("'\"")


def _store_id_from_token(token: str) -> str:
    parts = token.split("_")
    if len(parts) >= 4 and parts[3]:
        store_id = parts[3]
        return store_id[6:] if store_id.startswith("store_") else store_id
    return ""


def _api_headers(token: str, store_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "x-vercel-blob-store-id": store_id,
        "x-api-version": BLOB_API_VERSION,
    }


def _blob_url(store_id: str, pathname: str) -> str:
    parts = [quote(part, safe="") for part in pathname.split("/") if part]
    return f"https://{store_id}.private.blob.vercel-storage.com/{'/'.join(parts)}"


def _clean_pathname(pathname: str) -> str:
    return pathname.strip().strip("/").replace("//", "/")
