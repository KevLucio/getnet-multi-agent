import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import orchestrator
from app.config import settings
from app.rag.ingestion import ensure_index
from app.schemas import ChatRequest, ChatResponse

logging.basicConfig(level=settings.log_level, format="%(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Construye el índice la primera vez; en los siguientes arranques ya existe
    await asyncio.to_thread(ensure_index)
    yield


app = FastAPI(title="Getnet Multi-Agent Support", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    return orchestrator.run(request.message, request.user_id)