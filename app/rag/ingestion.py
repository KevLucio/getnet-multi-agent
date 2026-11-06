import json
import logging
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from app import llm
from app.config import settings
from app.rag.retriever import get_collection

logger = logging.getLogger("ingestion")

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"
MIN_TEXT_CHARS = 200  # menos que esto suele ser una página vacía o renderizada con JavaScript

URLS = [
    "https://www.getnet.net/en",
    "https://www.getnet.net/en/our-solutions/in-person-payments",
    "https://site.getnet.com.br/todas-as-maquininhas/",
    "https://site.getnet.com.br/maquininha/get-smart/",
    "https://site.getnet.com.br/get-lite/",
    "https://site.getnet.com.br/get-tap/",
    "https://site.getnet.com.br/pix/",
    "https://site.getnet.com.br/link-de-pagamento/",
    "https://site.getnet.com.br/conta-digital/",
    "https://site.getnet.com.br/duvidas/",
    "https://site.getnet.com.br/boas-vindas/manual-maquinas/",
]


def slugify(url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"^https?://", "", url.lower())).strip("-")[:80]


def fetch_page(url: str) -> str:
    response = requests.get(
        url,
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0 (compatible; GetnetSupportBot/1.0)"},
    )
    response.raise_for_status()
    return response.text


def extract_text(html: str) -> tuple[str, str]:
    """Devuelve (título, texto limpio) de una página HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "header", "footer", "form"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""
    lines = []
    for raw in soup.get_text("\n").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if len(line) < 3 or (lines and line == lines[-1]):
            continue
        lines.append(line)
    return title, "\n".join(lines)


def chunk_text(text: str, size: int = 800, overlap: int = 150) -> list[str]:
    """Divide el texto en fragmentos de ~size caracteres, cortando en saltos de línea o espacios."""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind("\n", start + size // 2, end)
            if cut == -1:
                cut = text.rfind(" ", start + size // 2, end)
            if cut != -1:
                end = cut
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _snapshot_path(url: str) -> Path:
    return SNAPSHOT_DIR / f"{slugify(url)}.json"


def load_documents() -> list[dict]:
    """Descarga cada URL y guarda un snapshot. Si falla, usa el último snapshot disponible."""
    documents = []
    for url in URLS:
        try:
            title, text = extract_text(fetch_page(url))
            if len(text) < MIN_TEXT_CHARS:
                raise ValueError(f"contenido insuficiente ({len(text)} caracteres)")
            document = {"url": url, "title": title, "text": text}
            SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            _snapshot_path(url).write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Descargada: %s", url)
        except Exception as error:
            snapshot = _snapshot_path(url)
            if not snapshot.exists():
                logger.warning("Se omite %s: %s y no hay snapshot", url, error)
                continue
            logger.warning("Fallo la descarga de %s (%s), se usa el snapshot", url, error)
            document = json.loads(snapshot.read_text(encoding="utf-8"))
        documents.append(document)
    return documents


def ingest() -> int:
    """Función principal de ingesta: documentos -> chunks -> embeddings -> ChromaDB."""
    documents = load_documents()
    if not documents:
        raise RuntimeError("No se pudo obtener ningún documento para indexar")

    ids, texts, metadatas = [], [], []
    for document in documents:
        for i, chunk in enumerate(chunk_text(document["text"])):
            ids.append(f"{slugify(document['url'])}-{i}")
            texts.append(chunk)
            metadatas.append({"source": document["url"], "title": document["title"]})

    embeddings = llm.embed(texts)
    collection = get_collection(reset=True)
    collection.add(ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas)
    logger.info("Indexados %d fragmentos de %d páginas", len(texts), len(documents))
    return len(texts)


def ensure_index() -> None:
    """Se ejecuta al arrancar: indexa la documentación solo si la base vectorial está vacía."""
    if get_collection().count() > 0:
        logger.info("Índice existente, no se vuelve a indexar")
        return
    if not settings.openai_api_key:
        logger.warning("Sin OPENAI_API_KEY no se puede indexar; Knowledge usará solo la web")
        return
    try:
        ingest()
    except Exception:
        logger.exception("No se pudo construir el índice; la API arranca de todos modos")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(f"Fragmentos indexados: {ingest()}")