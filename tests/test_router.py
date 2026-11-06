import pytest
from pydantic import ValidationError

from app.agents import router
from app.schemas import Plan

CASOS = [
    ("What's the difference between the Get Clássica and the Get Smart?", ["knowledge"]),
    ("What's the weather forecast in Porto Alegre tomorrow?", ["knowledge"]),
    ("When will the money from yesterday's sales be deposited?", ["support"]),
    ("Do I need a bank account to receive my sales via Pix?", ["knowledge"]),
    ("My card machine won't connect to the internet, what should I do?", ["support", "knowledge"]),
    ("How does receivables advance (antecipação) work with Getnet?", ["knowledge"]),
    ("What's the euro exchange rate today?", ["knowledge"]),
    ("My card machine is showing a transaction decline error.", ["support", "knowledge"]),
    ("How many installments can I split a sale into with the crediário?", ["knowledge"]),
    ("Can I sell through WhatsApp using the Payment Link?", ["knowledge"]),
]


@pytest.mark.parametrize("message,esperado", CASOS)
def test_palabras_clave_cubren_los_ejemplos_del_reto(message, esperado):
    plan = router.plan_by_keywords(message)
    assert plan.action == "answer"
    assert plan.steps == esperado


def test_pedido_de_humano_escala():
    assert router.plan_by_keywords("I want to talk to a human").action == "escalate"


def test_si_el_llm_falla_usa_palabras_clave(monkeypatch):
    monkeypatch.setattr(router.settings, "openai_api_key", "fake")

    def falla(message):
        raise RuntimeError("LLM caído")

    monkeypatch.setattr(router, "_plan_with_llm", falla)
    plan = router.plan("My card machine won't connect to the internet")
    assert plan.steps == ["support", "knowledge"]


def test_usa_el_plan_del_llm_cuando_responde(monkeypatch):
    monkeypatch.setattr(router.settings, "openai_api_key", "fake")
    monkeypatch.setattr(router, "_plan_with_llm", lambda m: Plan(action="out_of_scope"))
    assert router.plan("escríbeme un poema").action == "out_of_scope"


def test_plan_answer_sin_agentes_es_invalido():
    with pytest.raises(ValidationError):
        Plan(action="answer", steps=[])