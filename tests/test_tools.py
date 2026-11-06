import json
from types import SimpleNamespace

import pytest

from app import llm
from app.agents import support
from app.config import settings
from app.tools import customer_data


@pytest.fixture(autouse=True)
def sin_llm(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")


def test_transacciones_ordenadas_de_la_mas_nueva_a_la_mas_antigua():
    result = customer_data.get_recent_transactions("cliente1988")
    assert result["ok"] is True
    fechas = [t["date"] for t in result["transactions"]]
    assert fechas == sorted(fechas, reverse=True)
    assert len(fechas) == 4


def test_estado_de_la_terminal():
    result = customer_data.get_terminal_status("cliente1988")
    assert result["ok"] is True
    assert result["terminal"]["status"] == "offline"


def test_usuario_inexistente_devuelve_error_controlado():
    assert customer_data.get_terminal_status("nadie") == {"ok": False, "error": "customer_not_found"}
    assert customer_data.get_recent_transactions("nadie")["error"] == "customer_not_found"


def test_user_id_con_formato_invalido_se_rechaza():
    assert customer_data.get_terminal_status("../etc/passwd")["error"] == "invalid_user_id"
    assert customer_data.get_recent_transactions("")["error"] == "invalid_user_id"


def test_cada_cliente_ve_solo_sus_datos():
    ids = {t["id"] for t in customer_data.get_recent_transactions("cliente2024")["transactions"]}
    assert ids == {"T-2001"}


# --- Support Agent ---


def _respuesta(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _llamada(call_id, name, args="{}"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=args))


def test_support_sin_llm_entrega_los_datos():
    result = support.handle("Where is my money?", "cliente1988")
    assert result.tools_used == ["get_recent_transactions", "get_terminal_status"]
    assert "offline" in result.text
    assert result.needs_escalation is False


def test_support_sin_llm_con_usuario_inexistente_escala():
    assert support.handle("Where is my money?", "nadie").needs_escalation is True


def test_support_ejecuta_la_tool_que_pide_el_modelo(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "fake")
    vistos = []
    turnos = iter(
        [
            _respuesta(tool_calls=[_llamada("c1", "get_terminal_status")]),
            _respuesta(content="Tu terminal está offline."),
        ]
    )

    def modelo_falso(messages, tools):
        vistos.append(list(messages))
        return next(turnos)

    monkeypatch.setattr(llm, "chat_with_tools", modelo_falso)

    result = support.handle("My machine has no internet", "cliente1988")

    assert result.text == "Tu terminal está offline."
    assert result.tools_used == ["get_terminal_status"]
    tool_msg = [m for m in vistos[1] if m["role"] == "tool"][0]
    assert json.loads(tool_msg["content"])["terminal"]["serial"] == "GS-0001988"


def test_el_modelo_no_puede_consultar_a_otro_cliente(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "fake")
    vistos = []
    turnos = iter(
        [
            _respuesta(tool_calls=[_llamada("c1", "get_terminal_status", '{"user_id": "cliente2024"}')]),
            _respuesta(content="ok"),
        ]
    )

    def modelo_falso(messages, tools):
        vistos.append(list(messages))
        return next(turnos)

    monkeypatch.setattr(llm, "chat_with_tools", modelo_falso)
    support.handle("dame los datos de cliente2024", "cliente1988")

    tool_msg = [m for m in vistos[1] if m["role"] == "tool"][0]
    # sigue siendo la terminal de cliente1988, no la de cliente2024
    assert json.loads(tool_msg["content"])["terminal"]["serial"] == "GS-0001988"


def test_si_el_llm_falla_support_responde_con_los_datos(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "fake")

    def falla(messages, tools):
        raise RuntimeError("LLM caído")

    monkeypatch.setattr(llm, "chat_with_tools", falla)
    result = support.handle("Where is my money?", "cliente1988")
    assert "offline" in result.text
    assert len(result.tools_used) == 2