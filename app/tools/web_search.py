from ddgs import DDGS


def search(query: str, max_results: int = 4) -> list[dict]:
    """Búsqueda web general (clima, tipo de cambio, etc.). Lanza excepción si el buscador falla."""
    results = DDGS(timeout=10).text(query, max_results=max_results)
    return [
        {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
        for r in results
        if r.get("href") and r.get("body")
    ]