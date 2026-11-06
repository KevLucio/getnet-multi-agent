from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str = ""
    chat_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    log_level: str = "INFO"
    chroma_path: str = "chroma_db"
    rag_top_k: int = 4
    rag_max_distance: float = 0.6

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()