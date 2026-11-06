import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

TICKETS_FILE = Path(__file__).parent / "data" / "tickets.jsonl"

# 13 a 19 dígitos, con espacios o guiones opcionales entre ellos
CARD_PATTERN = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")


def sanitize_input(message: str) -> str:
    """Enmascara números de tarjeta antes de que el mensaje llegue a cualquier agente."""
    return CARD_PATTERN.sub("[TARJETA]", message).strip()


def create_support_ticket(user_id: str, message: str, reason: str) -> str:
    """Registra el caso para seguimiento humano y devuelve el id del ticket."""
    ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
    ticket = {
        "ticket_id": ticket_id,
        "user_id": user_id,
        "message": message,
        "reason": reason,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    TICKETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TICKETS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ticket, ensure_ascii=False) + "\n")
    return ticket_id