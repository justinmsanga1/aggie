import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHATSAPP_AGENT = ROOT / "whatsapp-agent"
if str(WHATSAPP_AGENT) not in sys.path:
    sys.path.insert(0, str(WHATSAPP_AGENT))

from app.main import app
