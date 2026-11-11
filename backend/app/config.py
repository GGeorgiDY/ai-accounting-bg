from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://accountant:accountant@db:5432/accountant"

    ollama_url: str = "http://ollama:11434"
    llm_model: str = "qwen2.5:7b"
    llm_num_ctx: int = 8192
    llm_timeout_seconds: float = 900

    upload_dir: str = "/data/uploads"
    max_upload_mb: int = 25
    ocr_lang: str = "bul+eng"
    max_document_chars: int = 15000

    book_currency: str = "EUR"

    worker_poll_seconds: float = 2.0
    worker_max_attempts: int = 3
    stale_processing_minutes: int = 30


settings = Settings()
