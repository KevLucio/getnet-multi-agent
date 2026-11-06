import pytest
from fastapi.testclient import TestClient

from app import guardrails
from app.agents import knowledge, support
from app.config import settings
from app.main import app
from app.schemas import AgentResult

client = TestClient(app)


def knowledge_falso(message, user_id, context=None):
    """Knowledge se prueba aparte en test_knowledge.py; aquí solo importa la orquestación."""
    return AgentResult(text=f"[knowledge] contexto: {context} | consulta: {message}")


@pytest.fixture(autouse=True)
def entorno_de_pruebas(monkeypatch, tmp_path):
    # Sin LLM real, con Knowledge simulado y los tickets en una carpeta temporal
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(guardrails, "TICKETS_FILE", tmp_path / "tickets.jsonl")
    monkeypatch.setattr(knowledge, "handle", knowledge_falso)
    monkeypatch.setattr(settings, "chroma_path", str(tmp_path / "chroma"))


def chat(message, user_id="cliente1988"):
    return client.post("/chat", json={"message": message, "user_id": user_id})


def test_chat_devuelve_estructura_esperada():
    r = chat("What is Pix?")
    assert r.status_code == 200
    body = r.json()
    for campo in ("response", "agents_used", "tools_used", "sources", "escalated", "trace_id"):
        assert campo in body


def test_mensaje_vacio_devuelve_422():
    assert chat("   ").status_code == 422


def test_falta_user_id_devuelve_422():
    r = client.post("/chat", json={"message": "hola"})
    assert r.status_code == 422


def test_cadena_support_knowledge_pasa_el_contexto():
    body = chat("My card machine won't connect to the internet, what should I do?").json()
    assert body["agents_used"] == ["support", "knowledge"]
    assert "get_terminal_status" in body["tools_used"]
    # el stub de knowledge incluye lo que le entregó support
    assert "offline" in body["response"]


def test_numero_de_tarjeta_se_enmascara():
    body = chat("Mi tarjeta es 4111 1111 1111 1111, ¿qué es Pix?").json()
    assert "4111" not in body["response"]
    assert "[TARJETA]" in body["response"]


def test_pedido_de_humano_crea_ticket():
    body = chat("I want to talk to a human").json()
    assert body["escalated"] is True
    assert "TKT-" in body["response"]
    assert guardrails.TICKETS_FILE.exists()


def test_si_un_agente_falla_la_api_responde_y_escala(monkeypatch):
    def falla(*args, **kwargs):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(support, "handle", falla)
    r = chat("When will my money be deposited?")
    assert r.status_code == 200
    assert r.json()["escalated"] is True


def test_usuario_inexistente_escala():
    body = chat("When will my money be deposited?", user_id="nadie").json()
    assert body["escalated"] is True
    assert "TKT-" in body["response"]


def test_la_app_arranca_con_lifespan_aunque_no_pueda_indexar():
    with TestClient(app) as c:
        assert c.get("/health").json() == {"status": "ok"}