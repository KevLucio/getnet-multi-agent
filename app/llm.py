import json

from openai import OpenAI

from app.config import settings

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key, timeout=20, max_retries=1)
    return _client


def chat_json(system: str, user: str) -> dict:
    """Llamada al modelo que devuelve un JSON ya parseado."""
    response = get_client().chat.completions.create(
        model=settings.chat_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return json.loads(response.choices[0].message.content)


def chat_with_tools(messages: list, tools: list):
    """Una vuelta de conversación con tools. Devuelve el mensaje del modelo."""
    response = get_client().chat.completions.create(
        model=settings.chat_model,
        temperature=0,
        tools=tools,
        messages=messages,
    )
    return response.choices[0].message


def embed(texts: list[str]) -> list[list[float]]:
    """Genera embeddings en lotes de 100 textos."""
    vectors: list[list[float]] = []
    for i in range(0, len(texts), 100):
        response = get_client().embeddings.create(model=settings.embedding_model, input=texts[i : i + 100])
        vectors.extend(item.embedding for item in response.data)
    return vectors


def chat_text(system: str, user: str) -> str:
    """Respuesta de texto libre del modelo."""
    response = get_client().chat.completions.create(
        model=settings.chat_model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    text = response.choices[0].message.content
    if not text:
        raise RuntimeError("El modelo devolvió una respuesta vacía")
    return text