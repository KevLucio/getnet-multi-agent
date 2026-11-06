import json
import logging
import time
import uuid

from app import guardrails
from app.agents import knowledge, router, support
from app.schemas import ChatResponse

logger = logging.getLogger("orchestrator")

AGENTS = {"knowledge": knowledge, "support": support}

OUT_OF_SCOPE_MSG = (
    "Solo puedo ayudarte con temas de Getnet, pagos y tu negocio. "
    "¿Hay algo de eso en lo que te pueda ayudar?"
)
ESCALATION_MSG = (
    "Voy a pasar tu caso a una persona del equipo de Getnet para que lo revise. "
    "Tu número de seguimiento es {ticket_id}."
)


def run(message: str, user_id: str) -> ChatResponse:
    """Coordina el flujo: sanitiza, pide el plan al router y ejecuta los agentes en orden."""
    trace_id = str(uuid.uuid4())
    started = time.perf_counter()

    clean = guardrails.sanitize_input(message)
    plan = router.plan(clean)

    text = ""
    reason = None
    agents_used, tools_used, sources = [], [], []

    if plan.action == "out_of_scope":
        text = OUT_OF_SCOPE_MSG
    elif plan.action == "escalate":
        reason = "El usuario necesita atención humana"
    else:
        context = None
        for name in plan.steps:
            try:
                result = AGENTS[name].handle(clean, user_id, context)
            except Exception:
                logger.exception("Falló el agente %s", name)
                reason = f"Falló el agente {name}"
                break
            agents_used.append(name)
            tools_used += result.tools_used
            sources += result.sources
            text = result.text
            context = result.text  # el siguiente agente recibe esta salida
            if result.needs_escalation:
                reason = f"El agente {name} no pudo resolver con confianza"
                break

    escalated = reason is not None
    if escalated:
        ticket_id = guardrails.create_support_ticket(user_id, clean, reason)
        text = ESCALATION_MSG.format(ticket_id=ticket_id)

    logger.info(
        json.dumps(
            {
                "trace_id": trace_id,
                "user_id": user_id,
                "action": plan.action,
                "plan": plan.steps,
                "agents_used": agents_used,
                "tools_used": tools_used,
                "escalated": escalated,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        )
    )

    return ChatResponse(
        response=text,
        agents_used=agents_used,
        tools_used=tools_used,
        sources=list(dict.fromkeys(sources)),
        escalated=escalated,
        trace_id=trace_id,
    )