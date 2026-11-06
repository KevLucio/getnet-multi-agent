import logging
import re

from app.config import settings
from app.llm import chat_json
from app.schemas import Plan

logger = logging.getLogger("router")

SYSTEM_PROMPT = """You are the router of a customer support system for Getnet, a Brazilian payments company. The users are merchants.
Decide how to handle the user's message. Reply ONLY with JSON: {"action": "answer" | "out_of_scope" | "escalate", "steps": [...]}

Agents available:
- "knowledge": answers questions about Getnet products and services (card machines, Pix, receivables advance, installments, Payment Link, fees) using the company documentation. It can also search the web for general public information such as weather or exchange rates.
- "support": looks up the merchant's own data: recent transactions, settlement dates and terminal status.

Rules:
- action "answer": "steps" has 1 or 2 agents in execution order. The second agent receives the output of the first one.
- Questions about the merchant's own money, sales or terminal: ["support"].
- General questions about products, how things work, weather or exchange rates: ["knowledge"].
- Use ["support", "knowledge"] only when the problem needs the merchant's data AND an explanation of what to do (terminal that won't connect, declined transaction).
- action "escalate" with steps []: the user asks for a human, reports fraud or has a serious financial problem.
- action "out_of_scope" with steps []: unrelated to payments or running a business, or unsafe or abusive requests.
- Messages can be in English, Spanish or Portuguese. Never answer the message yourself."""

# Respaldo cuando no hay API key o el modelo falla
ESCALATE_RE = re.compile(r"human|humano|real person|persona real|atendente|fraud|fraude", re.I)
TERMINAL_RE = re.compile(r"terminal|machine|máquina|maquina|maquininha", re.I)
PROBLEM_RE = re.compile(r"internet|connect|conex|decline|rechaz|recus|error|erro", re.I)
SUPPORT_RE = re.compile(r"deposit|depósit|yesterday|\bayer\b|\bontem\b", re.I)


def plan(message: str) -> Plan:
    """Función principal del router: intenta con el LLM y cae a palabras clave si falla."""
    if settings.openai_api_key:
        try:
            return _plan_with_llm(message)
        except Exception:
            logger.warning("El router no pudo usar el LLM, se usan palabras clave", exc_info=True)
    return plan_by_keywords(message)


def _plan_with_llm(message: str) -> Plan:
    return Plan.model_validate(chat_json(SYSTEM_PROMPT, message))


def plan_by_keywords(message: str) -> Plan:
    if ESCALATE_RE.search(message):
        return Plan(action="escalate")
    if TERMINAL_RE.search(message) and PROBLEM_RE.search(message):
        return Plan(steps=["support", "knowledge"])
    if SUPPORT_RE.search(message):
        return Plan(steps=["support"])
    return Plan(steps=["knowledge"])