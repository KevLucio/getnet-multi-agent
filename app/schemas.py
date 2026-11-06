from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ChatRequest(BaseModel):
    message: str = Field(max_length=2000)
    user_id: str = Field(min_length=1, max_length=64)

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message no puede estar vacío")
        return value


class ChatResponse(BaseModel):
    response: str
    agents_used: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    escalated: bool = False
    trace_id: str


class Plan(BaseModel):
    """Decisión del router: qué hacer con el mensaje y en qué orden."""

    action: Literal["answer", "out_of_scope", "escalate"] = "answer"
    steps: list[Literal["knowledge", "support"]] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def answer_needs_steps(self):
        if self.action == "answer" and not self.steps:
            raise ValueError("action 'answer' requiere al menos un agente")
        return self


class AgentResult(BaseModel):
    """Lo que devuelve cada agente al orquestador."""

    text: str
    tools_used: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    needs_escalation: bool = False