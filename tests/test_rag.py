import re
import zlib

import pytest

from app import llm
from app.config import settings
from app.rag import ingestion, retriever

HTML_PIX = """<html><head><title>Pix - Getnet</title></head><body>
<nav>Menu Produtos Contato</nav>
<script>var x = 1;</script>
<main><h1>Venda mais com Pix</h1>
<p>Como habilitar o recebimento via Pix pelo aplicativo Getnet Brasil.</p>
<p>Como habilitar o recebimento via Pix pelo aplicativo Getnet Brasil.</p></main>
<footer>Todos os direitos reservados</footer></body></html>"""

HTML_LINK = """<html><head><title>Link de pagamento</title></head><body><main>
<h1>Link de Pagamento</h1>
<p>Venda pelo WhatsApp e redes sociais com link de pagamento personalizável.</p>
</main></body></html>"""

PAGINAS = {"https://ejemplo.test/pix": HTML_PIX, "https://ejemplo.test/link": HTML_LINK}


def embedding_falso(texts):
    """Bolsa de palabras con hash estable: textos con palabras en común quedan cerca."""
    vectores = []
    for text in texts:
        v = [0.0] * 512
        for palabra in re.findall(r"\w+", text.lower()):
            v[zlib.crc32(palabra.encode()) % 512] += 1.0
        vectores.append(v)
    return vectores


@pytest.fixture(autouse=True)
def entorno(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "chroma_path", str(tmp_path / "chroma"))
    monkeypatch.setattr(ingestion, "SNAPSHOT_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(ingestion, "URLS", list(PAGINAS))
    monkeypatch.setattr(ingestion, "MIN_TEXT_CHARS", 20)
    monkeypatch.setattr(ingestion, "fetch_page", lambda url: PAGINAS[url])
    monkeypatch.setattr(llm, "embed", embedding_falso)


def test_extract_text_quita_navegacion_scripts_y_repetidos():
    title, text = ingestion.extract_text(HTML_PIX)
    assert title == "Pix - Getnet"
    assert "Venda mais com Pix" in text
    assert "Menu Produtos" not in text
    assert "var x" not in text
    assert "direitos reservados" not in text
    assert text.count("Como habilitar") == 1


def test_chunk_text_respeta_tamano_y_solapa():
    texto = "\n".join(f"Línea número {i} con algo de contenido para rellenar" for i in range(60))
    chunks = ingestion.chunk_text(texto, size=300, overlap=60)
    assert len(chunks) > 3
    assert all(len(c) <= 300 for c in chunks)
    # el final de un chunk reaparece al inicio del siguiente
    assert chunks[0].splitlines()[-1] in chunks[1]


def test_chunk_text_vacio_o_corto():
    assert ingestion.chunk_text("") == []
    assert ingestion.chunk_text("hola mundo") == ["hola mundo"]


def test_ingesta_y_busqueda_devuelven_la_fuente_correcta():
    assert ingestion.ingest() >= 2
    hits = retriever.search("recebimento via Pix pelo aplicativo")
    assert hits
    assert hits[0]["source"] == "https://ejemplo.test/pix"
    assert hits[0]["distance"] < 0.6


def test_pregunta_sin_relacion_no_devuelve_fragmentos():
    ingestion.ingest()
    assert retriever.search("weather forecast tomorrow Porto Alegre") == []


def test_busqueda_con_indice_vacio_devuelve_lista_vacia():
    assert retriever.search("Pix") == []


def test_si_falla_la_descarga_se_usa_el_snapshot(monkeypatch):
    ingestion.ingest()  # guarda snapshots

    def sin_internet(url):
        raise ConnectionError("sin red")

    monkeypatch.setattr(ingestion, "fetch_page", sin_internet)
    assert ingestion.ingest() >= 2
    assert retriever.search("recebimento via Pix pelo aplicativo")


def test_sin_internet_ni_snapshots_falla_con_mensaje_claro(monkeypatch):
    def sin_internet(url):
        raise ConnectionError("sin red")

    monkeypatch.setattr(ingestion, "fetch_page", sin_internet)
    with pytest.raises(RuntimeError):
        ingestion.ingest()


# --- arranque ---


def test_ensure_index_indexa_si_esta_vacio(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "fake")
    ingestion.ensure_index()
    assert retriever.get_collection().count() > 0


def test_ensure_index_no_repite_si_ya_hay_datos(monkeypatch):
    ingestion.ingest()
    llamadas = []
    monkeypatch.setattr(settings, "openai_api_key", "fake")
    monkeypatch.setattr(ingestion, "ingest", lambda: llamadas.append(1))
    ingestion.ensure_index()
    assert llamadas == []


def test_ensure_index_sin_api_key_no_hace_nada(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    ingestion.ensure_index()
    assert retriever.get_collection().count() == 0


def test_ensure_index_no_tumba_el_arranque_si_falla(monkeypatch):
    def falla():
        raise RuntimeError("sin red")

    monkeypatch.setattr(settings, "openai_api_key", "fake")
    monkeypatch.setattr(ingestion, "ingest", falla)
    ingestion.ensure_index()  # no debe lanzar excepción