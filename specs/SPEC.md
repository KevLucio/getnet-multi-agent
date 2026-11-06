# SPEC: Getnet Multi-Agent Support

## 1. Objetivo

Servicio HTTP en el que un Router analiza el mensaje de un comerciante de Getnet y lo delega a agentes especializados (Knowledge y Support), combinando sus resultados en una sola respuesta.

## 2. Alcance

**Incluye**
- Endpoint `POST /chat`.
- Tres agentes: Router, Knowledge y Support.
- RAG sobre páginas públicas de Getnet, con búsqueda web como complemento.
- Dos tools de soporte sobre datos simulados.
- Guardrails básicos, escalación a humano y logs estructurados.
- Dockerfile, docker-compose y pruebas.

**Fuera de alcance**
- Dashboards, alertas y autenticación real.
- Datos reales de clientes.
- Interfaz de usuario.

## 3. Contrato de la API

`POST /chat`

Request:

```json
{ "message": "texto del usuario", "user_id": "cliente1988" }
```

Response:

```json
{
  "response": "texto final",
  "agents_used": ["support", "knowledge"],
  "tools_used": ["get_terminal_status"],
  "sources": ["https://www.getnet.net/..."],
  "escalated": false,
  "trace_id": "uuid"
}
```

Errores: `422` si el payload es inválido o el mensaje está vacío. Si falla el LLM o la búsqueda web, responde `200` con un mensaje controlado y `escalated: true` cuando corresponda.

## 4. Agentes

| Agente | Responsabilidad |
|---|---|
| Router | Recibe el mensaje y devuelve un plan en JSON: lista ordenada de 1 a 2 agentes (`knowledge`, `support`), o `out_of_scope`, o `escalate`. Si el LLM falla, usa un fallback por palabras clave. |
| Knowledge | RAG sobre Getnet. Si la recuperación es débil, o la pregunta es general (clima, tipo de cambio), usa búsqueda web. Responde en el idioma del usuario y cita las fuentes. |
| Support | Usa tool calling con dos tools sobre datos simulados y redacta la respuesta con lo que devuelven. |

**Tools de Support**
- `get_recent_transactions(user_id)`: ventas recientes y su estado de liquidación.
- `get_terminal_status(user_id)`: estado de conexión y errores de la terminal registrada.

Ambas validan el `user_id`, leen solo los datos de ese usuario y devuelven un error controlado si no existe.

## 5. Orquestación

1. `main.py` recibe la solicitud y llama al orquestador.
2. El orquestador sanitiza la entrada y le pide el plan al Router.
3. Ejecuta los agentes del plan en orden. **El segundo agente recibe la salida del primero como contexto.**
4. Arma la respuesta final con agentes, tools y fuentes usadas.
5. Registra el log con `trace_id`.

El orquestador no contiene lógica de los agentes: solo coordina.

**Flujos esperados**

| Mensaje | Plan |
|---|---|
| Diferencia entre Get Clássica y Get Smart | knowledge |
| Pix, antecipação, crediário, Payment Link | knowledge |
| Clima en Porto Alegre, tipo de cambio del euro | knowledge (web) |
| Cuándo llega el depósito de ayer | support |
| Terminal sin conexión a internet | support → knowledge |
| Error de transacción rechazada | support → knowledge |
| Pregunta fuera de alcance | out_of_scope |
| Caso grave o sin confianza | escalate |

## 6. Pipeline RAG

1. **Ingesta:** descarga de URLs de getnet.net con `requests` y `BeautifulSoup`. Si falla la descarga, se usan los snapshots de `app/data/snapshots/`.
2. **Limpieza y chunking:** texto plano, fragmentos de ~800 caracteres con overlap.
3. **Embeddings:** modelo configurable por `EMBEDDING_MODEL`.
4. **Almacenamiento:** ChromaDB persistente en disco.
5. **Recuperación:** top-k con umbral de distancia. Si ningún fragmento lo supera, se considera recuperación débil.
6. **Generación:** el LLM responde solo con el contexto recuperado e incluye las fuentes. Si no hay información suficiente, lo dice.

## 7. Guardrails

- `sanitize_input()`: enmascara números de tarjeta y limpia espacios.
- El Router marca `out_of_scope` para temas ajenos a Getnet y a la consulta del comerciante.
- Recuperación débil, petición de un humano o caso financiero grave: `create_support_ticket()` registra el caso y la respuesta avisa que una persona continuará.
- Los agentes no inventan datos: si una tool no devuelve nada, se informa.

## 8. Observabilidad

Un `trace_id` por solicitud y un log JSON con: plan del Router, agentes, tools usadas, latencia y si hubo escalación. Dashboards y alertas se describen en el README como siguiente paso.

## 9. Requerimientos no funcionales

- Configuración por variables de entorno (`.env.example`).
- Modelos configurables: `CHAT_MODEL`, `EMBEDDING_MODEL`.
- Timeouts en llamadas externas.
- La caída de un servicio externo no tumba la API.
- Ejecución con `docker compose up`.

## 10. Testing

- **Unitarios** (LLM mockeado): Router, tools, guardrails.
- **Integración** (API en memoria): los 10 escenarios del reto como tabla parametrizada de ruta esperada.
- **Fallos:** LLM caído, búsqueda web caída, `user_id` inexistente, mensaje vacío.
- **Calidad de respuestas:** evaluada aparte con un dataset de preguntas, fuentes esperadas y revisión de groundedness. Se describe en el README.

## 11. Criterios de aceptación

| # | Criterio | Verificación |
|---|---|---|
| 1 | El Router clasifica consultas de conocimiento y de soporte | Test con LLM mockeado sobre los 10 ejemplos |
| 2 | Existe al menos una cadena de dos agentes y el segundo recibe la salida del primero | Test de integración con "terminal sin internet" |
| 3 | Knowledge recupera fragmentos relacionados con la pregunta | Consulta real sobre Get Clássica vs Get Smart, con fuentes |
| 4 | Support usa 2 tools y valida `user_id` | `test_tools.py`, incluido usuario inexistente |
| 5 | Si falla el LLM o la búsqueda web, la API responde con mensaje controlado | Tests con fallos simulados |
| 6 | `POST /chat` devuelve JSON con `response`, `agents_used`, `tools_used`, `trace_id` | `test_api.py` |
| 7 | `docker compose up` levanta el servicio y `/chat` responde 200 | Prueba manual con `curl` |

## 12. Decisiones técnicas

- **Python + FastAPI:** rápido de montar y con validación vía Pydantic.
- **SDK directo, sin framework de agentes:** el flujo se explica con llamadas a funciones y no hay abstracciones ocultas.
- **OpenAI como único proveedor:** una sola API key, modelo de chat económico y embeddings multilingües.
- **ChromaDB:** vector store local y persistente, sin servicios adicionales.
- **Escalación como función:** el reto pide tres agentes y un ticket no necesita razonamiento propio.
- **Cadena de máximo 2 agentes:** suficiente para mostrar colaboración sin complicar el flujo.