# WhatsApp Claude Helper

Private WhatsApp assistant for a stock manager. It receives WhatsApp messages from Meta Cloud API, sends text and document content to Claude, then replies back on WhatsApp.

## What works in this MVP

- Meta webhook verification: `GET /webhook`
- Incoming WhatsApp messages: `POST /webhook`
- Claude replies with short conversation memory
- Private markdown knowledge base in `knowledge/`
- WhatsApp text replies
- Media download from Meta for images and documents
- Basic extraction for PDF, DOCX, XLSX, CSV, TXT/MD
- Image forwarding to Claude vision-capable models

## Setup

```powershell
cd "C:\Users\Administrator\Desktop\psn manager\whatsapp-agent"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and add:

- `META_VERIFY_TOKEN`
- `META_ACCESS_TOKEN`
- `META_PHONE_NUMBER_ID`
- `ANTHROPIC_API_KEY`
- `CLAUDE_MODEL`

## Run locally

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```powershell
curl http://127.0.0.1:8000/health
```

## Connect Meta during development

Meta requires a public HTTPS webhook URL. Use a tunnel during development, for example:

```powershell
ngrok http 8000
```

In Meta Developers, set the callback URL to:

```text
https://YOUR-TUNNEL-DOMAIN/webhook
```

Use the same value from `.env` for the verify token.

Subscribe the WhatsApp product webhook to `messages`.

## Permanent deployment

LocalTunnel/ngrok URLs are temporary. For a permanent webhook, deploy this folder to a host that gives a stable HTTPS URL.

### Vercel

Vercel is supported through Python Functions. The project includes:

- `api/index.py` as the Vercel FastAPI entrypoint
- `vercel.json` for routing all paths to FastAPI
- `.vercelignore` so local secrets, uploads, outputs, and chat imports are not deployed

Deploy from this folder:

```powershell
cd "C:\Users\Administrator\Desktop\psn manager\whatsapp-agent"
npx vercel
```

In Vercel project settings, add these environment variables:

```text
META_VERIFY_TOKEN=aggie-helper-webhook-2026
META_ACCESS_TOKEN=...
META_PHONE_NUMBER_ID=...
META_GRAPH_VERSION=v23.0
ANTHROPIC_API_KEY=...
CLAUDE_MODEL=claude-sonnet-4-5
DATABASE_PATH=/tmp/agent.sqlite3
UPLOAD_DIR=/tmp/uploads
OUTPUT_DIR=/tmp/outputs
KNOWLEDGE_DIR=./knowledge
```

Then set Meta callback URL to:

```text
https://YOUR-VERCEL-PROJECT.vercel.app/webhook
```

Vercel note: `/tmp` storage is temporary. That is fine for processing a WhatsApp file and sending it back immediately. For long-term memory/history, add a real hosted database later.

### Render

Recommended simple path:

1. Push the repo to GitHub.
2. Create a Render web service from the `whatsapp-agent` folder.
3. Use the included `render.yaml` or these commands:

```text
Build command: pip install -r requirements.txt
Start command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

4. Add these environment variables in Render:

```text
META_VERIFY_TOKEN
META_ACCESS_TOKEN
META_PHONE_NUMBER_ID
META_GRAPH_VERSION
ANTHROPIC_API_KEY
CLAUDE_MODEL
APP_BASE_URL
DATABASE_PATH
UPLOAD_DIR
OUTPUT_DIR
KNOWLEDGE_DIR
```

5. Set Meta callback URL to:

```text
https://YOUR-RENDER-SERVICE.onrender.com/webhook
```

Then keep `messages` subscribed.

## Notes

- Keep `.env`, `uploads/`, `outputs/`, and `data/` private.
- The assistant does not contact anyone except the WhatsApp user.
- It will not edit official company files unless we add that feature later.
