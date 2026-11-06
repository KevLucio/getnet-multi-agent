import pytest

from app import llm
from app.agents import knowledge
from app.rag import retriever
from app.tools import web_search

DOC = {
    "text": "O Pix não cobra taxa de recebimento para o vendedor.",
    "source": "https://site.getnet.com.br/pix/",
    "title": "Pix",
    "distance": 0.3,
}
WEB = {"title": "Euro hoje", "url": "https://ejemplo.test/euro", "snippet": "Euro a R$ 6,10"}


class Espia:
    """Registra las llamadas y permite simular respuestas o fallos."""

    def __init__(self, resultado=None, error=None):
        self.resultado, self.error, self.llamadas = resultado, error, []

    def __call__(self, *args):
        self.llamadas.append(args)
        if self.error:
            raise self.error
        return self.resultado


@pytest.fixture
def modelo(monkeypatch):
    espia = Espia(resultado="respuesta del modelo")
    monkeypatch.setattr(llm, "chat_text", lambda system, user: espia(system, user))
    return espia


def test_con_documentacion_no_usa_web(monkeypatch, modelo):
    monkeypatch.setattr(retriever, "search", lambda q: [DOC])
    web = Espia(resultado=[WEB])
    monkeypatch.setattr(web_search, "search", lambda q: web(q))

    result = knowledge.handle("Do I need a bank account for Pix?", "cliente1988")

    assert result.text == "respuesta del modelo"
    assert result.tools_used == ["rag_search"]
    assert result.sources == [DOC["source"]]
    assert web.llamadas == []


def test_sin_documentacion_usa_busqueda_web(monkeypatch, modelo):
    monkeypatch.setattr(retriever, "search", lambda q: [])
    monkeypatch.setattr(web_search, "search", lambda q: [WEB])

    result = knowledge.handle("What's the euro exchange rate today?", "cliente1988")

    assert result.tools_used == ["rag_search", "web_search"]
    assert result.sources == [WEB["url"]]
    assert "(web)" in modelo.llamadas[0][1]


def test_sin_docs_ni_web_escala(monkeypatch, modelo):
    monkeypatch.setattr(retriever, "search", lambda q: [])
    monkeypatch.setattr(web_search, "search", lambda q: [])

    result = knowledge.handle("algo sin respuesta", "cliente1988")

    assert result.needs_escalation is True
    assert modelo.llamadas == []  # no se le pide al modelo que invente


def test_si_falla_el_rag_se_intenta_con_la_web(monkeypatch, modelo):
    def rag_caido(q):
        raise RuntimeError("chroma no disponible")

    monkeypatch.setattr(retriever, "search", rag_caido)
    monkeypatch.setattr(web_search, "search", lambda q: [WEB])

    result = knowledge.handle("euro hoy", "cliente1988")

    assert result.tools_used == ["web_search"]
    assert result.sources == [WEB["url"]]


def test_si_falla_la_web_y_no_hay_docs_escala(monkeypatch, modelo):
    def web_caida(q):
        raise ConnectionError("sin red")

    monkeypatch.setattr(retriever, "search", lambda q: [])
    monkeypatch.setattr(web_search, "search", web_caida)

    result = knowledge.handle("weather in Porto Alegre", "cliente1988")

    assert result.needs_escalation is True
    assert result.tools_used == ["rag_search"]


def test_si_falla_el_llm_entrega_el_fragmento_de_la_documentacion(monkeypatch):
    def llm_caido(system, user):
        raise RuntimeError("LLM caído")

    monkeypatch.setattr(retriever, "search", lambda q: [DOC])
    monkeypatch.setattr(llm, "chat_text", llm_caido)

    result = knowledge.handle("Pix", "cliente1988")

    assert result.needs_escalation is False
    assert "não cobra taxa" in result.text
    assert result.sources == [DOC["source"]]


def test_si_falla_el_llm_y_solo_hay_web_escala(monkeypatch):
    def llm_caido(system, user):
        raise RuntimeError("LLM caído")

    monkeypatch.setattr(retriever, "search", lambda q: [])
    monkeypatch.setattr(web_search, "search", lambda q: [WEB])
    monkeypatch.setattr(llm, "chat_text", llm_caido)

    assert knowledge.handle("euro hoy", "cliente1988").needs_escalation is True


def test_el_contexto_del_agente_anterior_llega_al_prompt(monkeypatch, modelo):
    monkeypatch.setattr(retriever, "search", lambda q: [DOC])

    knowledge.handle("My machine won't connect", "cliente1988", context="Terminal offline, error NO_NETWORK")

    prompt = modelo.llamadas[0][1]
    assert "Merchant data" in prompt
    assert "NO_NETWORK" in prompt
    assert "(docs)" in prompt


def test_web_search_normaliza_resultados(monkeypatch):
    class BuscadorFalso:
        def __init__(self, timeout):
            pass

        def text(self, query, max_results):
            return [
                {"title": "A", "href": "https://a.test", "body": "texto a"},
                {"title": "sin enlace", "body": "descartado"},
            ]

    monkeypatch.setattr(web_search, "DDGS", BuscadorFalso)
    assert web_search.search("algo") == [{"title": "A", "url": "https://a.test", "snippet": "texto a"}]