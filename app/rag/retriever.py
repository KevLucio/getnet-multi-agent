import sys
from functools import lru_cache

import chromadb

from app import llm
from app.config import settings

COLLECTION_NAME = "getnet"


@lru_cache(maxsize=None)
def _client(path: str):
    return chromadb.PersistentClient(path=path)


def get_collection(reset: bool = False):
    """Colección de ChromaDB con distancia coseno. Con reset=True se vuelve a crear vacía."""
    client = _client(settings.chroma_path)
    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass  # no existía todavía
    return client.get_or_create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})


def search(query: str, top_k: int | None = None, max_distance: float | None = None) -> list[dict]:
    """Devuelve los fragmentos más cercanos a la consulta que superan el umbral de distancia.

    Una lista vacía significa que no hay nada suficientemente relevante.
    """
    top_k = top_k or settings.rag_top_k
    max_distance = settings.rag_max_distance if max_distance is None else max_distance

    collection = get_collection()
    if collection.count() == 0:
        return []

    query_embedding = llm.embed([query])[0]
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
    )

    hits = []
    for text, meta, distance in zip(
        result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        if distance <= max_distance:
            hits.append(
                {"text": text, "source": meta["source"], "title": meta["title"], "distance": distance}
            )
    return hits


if __name__ == "__main__":
    # Para calibrar el umbral: python -m app.rag.retriever "tu pregunta"
    question = " ".join(sys.argv[1:]) or "diferença entre Get Clássica e Get Smart"
    for hit in search(question, max_distance=2.0):
        print(f"{hit['distance']:.3f}  {hit['source']}")
        print(f"       {hit['text'][:140]!r}")