# Getnet Multi-Agent Support

Servicio de soporte para comercios Getnet. Recibe una consulta por HTTP y decide si debe responder con información de productos, consultar los datos simulados del comercio o combinar ambos pasos.

## Requisitos

- Python 3.11 o superior.
- Una clave de OpenAI para generar respuestas y construir el índice RAG.
- Docker Desktop si se quiere ejecutar con Docker Compose.

La aplicación puede arrancar sin clave para probar el flujo y las consultas de soporte con datos simulados. Sin embargo, las respuestas de Knowledge no se generan sin un LLM. La búsqueda web requiere conexión a internet.

## Configuración

Desde la carpeta del proyecto, crea `.env` a partir del ejemplo.

En PowerShell:

```powershell
Copy-Item .env.example .env
```

En `.env`, agrega la clave:

```dotenv
OPENAI_API_KEY=tu_clave
CHAT_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small
LOG_LEVEL=INFO
```

No subas `.env` a Git. La aplicación también acepta `CHROMA_PATH`, `RAG_TOP_K` y `RAG_MAX_DISTANCE`; sus valores predeterminados están en `app/config.py`.

## Ejecutar localmente

Instala dependencias y levanta la API desde la raíz del proyecto:

```powershell
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload
```

La API queda disponible en `http://localhost:8000`. La documentación interactiva de FastAPI está en `http://localhost:8000/docs`.

En el primer arranque, si hay una clave configurada, la aplicación intenta descargar las páginas de Getnet y crear el índice de ChromaDB. Este paso puede tomar tiempo y necesita acceso a internet. Si falla, la API registra el error y continúa arrancando.

## Ejecutar con Docker Compose

Después de crear `.env` y encender Docker Desktop:

```powershell
docker compose up --build
```

Compose expone la API en el puerto `8000`. El volumen `chroma_data` conserva el índice entre reinicios y `app/data` se monta desde el proyecto para conservar los snapshots y tickets localmente.

## API

### `GET /health`

Indica si el proceso está disponible:

```json
{"status": "ok"}
```

### `POST /chat`

Solicitud:

```json
{
  "message": "My card machine won't connect to the internet. What should I do?",
  "user_id": "cliente1988"
}
```

Respuesta:

```json
{
  "response": "Respuesta del sistema",
  "agents_used": ["support", "knowledge"],
  "tools_used": ["get_terminal_status", "rag_search"],
  "sources": ["https://site.getnet.com.br/..."],
  "escalated": false,
  "trace_id": "uuid"
}
```

`message` no puede estar vacío y tiene un máximo de 2.000 caracteres. `user_id` es obligatorio y admite entre 1 y 64 caracteres. Si el cuerpo no cumple el esquema, FastAPI devuelve `422`.

Ejemplo para PowerShell:

```powershell
$body = @{
  message = "What is Pix?"
  user_id = "cliente1988"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri http://localhost:8000/chat `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

## Cómo se conectan los agentes

El flujo se coordina con llamadas directas a funciones; no se utiliza un framework de orquestación:

1. `app/main.py` valida la solicitud y llama a `app/orchestrator.py`.
2. El orquestador enmascara números de tarjeta antes de enviar el mensaje a otros módulos.
3. El Router propone una acción y uno o dos agentes. Con clave usa el LLM y valida el resultado con el esquema `Plan`; sin clave o ante un fallo usa reglas por palabras clave.
4. Support consulta las herramientas de datos simulados. Si el plan incluye Knowledge después de Support, recibe la respuesta anterior como contexto.
5. Knowledge busca primero en ChromaDB y, si no encuentra documentos relevantes, intenta una búsqueda web. Con las fuentes disponibles, el LLM redacta la respuesta.
6. El orquestador reúne la respuesta, los agentes, las herramientas y las fuentes utilizadas. Si un agente no puede resolver el caso, registra un ticket local y marca la respuesta como escalada.

El agente Support ofrece:

- `get_recent_transactions`: ventas recientes y estado de liquidación.
- `get_terminal_status`: modelo, estado y última información de conexión de la terminal.

Ambas herramientas reciben el `user_id` de la solicitud, no uno generado por el modelo, y solo consultan ese usuario en `app/data/customers.json`.

## RAG y fuentes

La ingesta en `app/rag/ingestion.py` descarga páginas públicas de Getnet, elimina elementos de navegación y scripts, divide el texto en fragmentos de aproximadamente 800 caracteres con 150 caracteres de solapamiento, obtiene embeddings y guarda los fragmentos en ChromaDB. El retriever busca los fragmentos más cercanos y descarta los que quedan fuera del umbral configurado.

Fuentes incluidas en la ingesta:

- `https://www.getnet.net/en`
- `https://www.getnet.net/en/our-solutions/in-person-payments`
- `https://site.getnet.com.br/todas-as-maquininhas/`
- `https://site.getnet.com.br/maquininha/get-smart/`
- `https://site.getnet.com.br/get-lite/`
- `https://site.getnet.com.br/get-tap/`
- `https://site.getnet.com.br/pix/`
- `https://site.getnet.com.br/link-de-pagamento/`
- `https://site.getnet.com.br/conta-digital/`
- `https://site.getnet.com.br/duvidas/`
- `https://site.getnet.com.br/boas-vindas/manual-maquinas/`

Si una descarga falla, la ingesta busca un snapshot correspondiente en `app/data/snapshots/`. No se incluyen snapshots en este repositorio, así que ese respaldo solo está disponible después de guardar allí archivos válidos.

Cuando no hay resultados del RAG, `app/tools/web_search.py` intenta obtener resultados públicos mediante DDGS. Los enlaces devueltos se incluyen en `sources`.

## Datos, guardrails y límites

- `app/data/customers.json` contiene registros ficticios para desarrollo y pruebas; no son datos de clientes reales.
- Los tickets se agregan en formato JSON Lines en `app/data/tickets.jsonl`. El archivo está excluido de Git.
- El enmascarado cubre secuencias de 13 a 19 dígitos, admitiendo espacios o guiones entre ellos; no reemplaza un sistema de cumplimiento o protección de datos.
- El `user_id` lo envía quien llama a la API. El proyecto no implementa autenticación ni verifica que quien lo envía sea el titular de esa cuenta. No conectes datos reales sin añadir autenticación y autorización.
- El fallback del Router usa un conjunto acotado de palabras clave; puede clasificar mal mensajes que no contemple.
- Sin `OPENAI_API_KEY`, la API puede probarse con las respuestas simuladas de Support, pero no ofrece respuestas generadas por el modelo. Si no puede responder con confianza, intenta escalar el caso.
- Los resultados de la búsqueda web y la disponibilidad de las páginas dependen de servicios externos.

## Pruebas

Instala las dependencias de desarrollo y ejecuta la suite desde la raíz:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Las pruebas cubren el enrutamiento por reglas, las herramientas y datos simulados, la validación de la API, la orquestación entre Support y Knowledge, el comportamiento de RAG y los fallos simulados del LLM, la búsqueda web y las descargas. Las llamadas a servicios externos se reemplazan por mocks o embeddings de prueba; por eso la suite no valida una clave real, la disponibilidad actual de Getnet o la calidad de respuestas de un modelo en producción.

En la última ejecución de esta suite en el entorno de desarrollo, las 54 pruebas pasaron.

## Estructura principal

```text
app/
  agents/       Router, Knowledge y Support
  data/         Datos simulados, snapshots y tickets
  rag/          Ingesta y recuperación con ChromaDB
  tools/        Consulta de datos del comercio y búsqueda web
  config.py     Configuración por variables de entorno
  guardrails.py Enmascarado y registro de tickets
  llm.py        Cliente de chat y embeddings
  main.py       API FastAPI
  orchestrator.py
tests/          Pruebas unitarias y de integración
specs/SPEC.md   Alcance y criterios del proyecto
```
