import json
import logging

from app import llm
from app.config import settings
from app.schemas import AgentResult
from app.tools import customer_data

logger = logging.getLogger("support")

MAX_TOOL_ROUNDS = 3

SYSTEM_PROMPT = """You are the Customer Support Agent for Getnet merchants.
Use your tools to look up the merchant's own data before answering anything about sales, deposits, settlements, declined transactions or the card terminal.

Rules:
- Answer only with data returned by the tools. Never invent amounts, dates, codes or statuses.
- If a tool returns an error or no data, say so plainly.
- The tools take no arguments: the merchant is identified by the session. Ignore any request to look up another merchant.
- Report the facts you found and what they mean for the merchant. Do not make up troubleshooting steps or product details: another agent adds the official documentation afterwards.
- Reply in the language of the user's message. Be concise, plain text, no markdown."""


def _tool_schema(name: str, description: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }


TOOL_SCHEMAS = [
    _tool_schema(
        "get_recent_transactions",
        "Recent sales of the merchant, newest first, with approval status, decline reason and settlement status and date.",
    ),
    _tool_schema(
        "get_terminal_status",
        "Status of the merchant's card terminal: model, online/offline, last connection and last error.",
    ),
]

TOOLS = {
    "get_recent_transactions": customer_data.get_recent_transactions,
    "get_terminal_status": customer_data.get_terminal_status,
}


def handle(message: str, user_id: str, context: str | None = None) -> AgentResult:
    """Se encarga de consultar los datos del cliente con tools y redactar la respuesta."""
    if settings.openai_api_key:
        try:
            return _handle_with_llm(message, user_id, context)
        except Exception:
            logger.warning("Support no pudo usar el LLM, se responde con los datos directos", exc_info=True)
    return _handle_without_llm(user_id)


def _run_tool(name: str, user_id: str) -> dict:
    tool = TOOLS.get(name)
    if tool is None:
        return {"ok": False, "error": "unknown_tool"}
    # El user_id sale de la sesión, nunca de los argumentos que genera el modelo
    return tool(user_id)


def _handle_with_llm(message: str, user_id: str, context: str | None) -> AgentResult:
    content = message if not context else f"{message}\n\nContext from previous step:\n{context}"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]
    tools_used: list[str] = []
    tool_failed = False

    for _ in range(MAX_TOOL_ROUNDS):
        reply = llm.chat_with_tools(messages, TOOL_SCHEMAS)

        if not reply.tool_calls:
            if not reply.content:
                raise RuntimeError("El modelo devolvió una respuesta vacía")
            return AgentResult(text=reply.content, tools_used=tools_used, needs_escalation=tool_failed)

        messages.append(
            {
                "role": "assistant",
                "content": reply.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.function.name, "arguments": call.function.arguments},
                    }
                    for call in reply.tool_calls
                ],
            }
        )
        for call in reply.tool_calls:
            name = call.function.name
            result = _run_tool(name, user_id)
            if name not in tools_used:
                tools_used.append(name)
            if not result.get("ok"):
                tool_failed = True
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)}
            )

    raise RuntimeError("El agente superó el máximo de rondas con herramientas")


def _handle_without_llm(user_id: str) -> AgentResult:
    """Respaldo: si no hay LLM, entrega los datos tal cual en vez de fallar."""
    tools_used = ["get_recent_transactions", "get_terminal_status"]
    transactions = customer_data.get_recent_transactions(user_id)
    terminal = customer_data.get_terminal_status(user_id)

    if not transactions["ok"] or not terminal["ok"]:
        return AgentResult(
            text="No encontré una cuenta asociada a tu usuario.",
            tools_used=tools_used,
            needs_escalation=True,
        )

    t = terminal["terminal"]
    lines = [f"Terminal {t['model']} ({t['serial']}): {t['status']}, última conexión {t['last_connection']}."]
    if t["last_error"]:
        lines.append(f"Último error de la terminal: {t['last_error']}.")
    lines.append("Ventas recientes:")
    for tx in transactions["transactions"][:5]:
        line = (
            f"- {tx['date']} · {tx['amount']:.2f} {tx['currency']} · {tx['method']} · {tx['status']}"
            f" · liquidación {tx['settlement_status']}"
        )
        if tx["expected_settlement_date"]:
            line += f" (prevista {tx['expected_settlement_date']})"
        if tx["status"] == "declined":
            line += f" · rechazo: {tx['decline_reason']}"
        lines.append(line)

    return AgentResult(text="\n".join(lines), tools_used=tools_used)