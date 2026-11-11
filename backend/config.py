"""Atlas configuration. Secret values are never exposed by status or errors."""

import os
from pathlib import Path
from functools import lru_cache
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


class Settings:
    def __init__(self):
        self.data_dir = Path(os.getenv("ATLAS_DATA_DIR", str(ROOT / "data")))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_url = os.getenv(
            "DATABASE_URL", "sqlite:///" + str(self.data_dir / "atlas.db")
        )
        if self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace(
                "postgres://", "postgresql+psycopg://", 1
            )
        elif self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace(
                "postgresql://", "postgresql+psycopg://", 1
            )
        self.api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = os.getenv("OPENAI_BASE_URL") or (
            "https://api.deepseek.com/v1"
            if not os.getenv("OPENAI_API_KEY") and os.getenv("DEEPSEEK_API_KEY")
            else "https://api.openai.com/v1"
        )
        self.model = (
            os.getenv("OPENAI_MODEL")
            or os.getenv("LLM_MODEL")
            or (
                "deepseek-flash"
                if not os.getenv("OPENAI_API_KEY") and os.getenv("DEEPSEEK_API_KEY")
                else "gpt-4o-mini"
            )
        )
        self.embedding_key = os.getenv("EMBEDDING_API_KEY") or self.api_key
        self.embedding_base_url = os.getenv("EMBEDDING_BASE_URL") or self.base_url
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "")
        self.tavily_key = os.getenv("TAVILY_API_KEY", "")
        self.checkpoint_path = os.getenv(
            "ATLAS_CHECKPOINT_PATH", str(self.data_dir / "checkpoints.db")
        )
        self.checkpoint_postgres_url = os.getenv("CHECKPOINT_DATABASE_URL", "")
        self.cookie_secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"
        self.worker_mode = os.getenv("WORKER_MODE", "embedded")
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.cors_origins = [
            x.strip()
            for x in os.getenv(
                "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
            ).split(",")
            if x.strip()
        ]
        self.max_upload_bytes = int(os.getenv("MAX_UPLOAD_MB", "12")) * 1024 * 1024
        self.app_name = "Atlas API"
        self.debug = False


@lru_cache
def get_settings():
    return Settings()
