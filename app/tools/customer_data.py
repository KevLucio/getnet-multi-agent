import json
import re
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "customers.json"
USER_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _find_customer(user_id: str):
    """Devuelve (cliente, error). Solo se acepta un user_id con formato válido."""
    if not USER_ID_PATTERN.fullmatch(user_id):
        return None, "invalid_user_id"
    with DATA_FILE.open(encoding="utf-8") as f:
        customers = json.load(f)["customers"]
    customer = customers.get(user_id)
    if customer is None:
        return None, "customer_not_found"
    return customer, None


def get_recent_transactions(user_id: str, limit: int = 10) -> dict:
    """Ventas recientes del cliente, de la más nueva a la más antigua."""
    customer, error = _find_customer(user_id)
    if error:
        return {"ok": False, "error": error}
    transactions = sorted(customer["transactions"], key=lambda t: t["date"], reverse=True)
    return {"ok": True, "transactions": transactions[:limit]}


def get_terminal_status(user_id: str) -> dict:
    """Estado de la terminal registrada para el cliente."""
    customer, error = _find_customer(user_id)
    if error:
        return {"ok": False, "error": error}
    return {"ok": True, "terminal": customer["terminal"]}