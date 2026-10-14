from pathlib import Path
import os
import sys
import asyncio
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
# External tracing is a separate privacy decision; unrelated shell credentials cannot enable it.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    workspace_root: Path = ROOT / "data"
    checkpoint_backend: str = "postgres"
    langgraph_checkpoint_dsn: str = ""
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    qdrant_url: str = ""
    qdrant_key: str = ""
    embedding_path: str = ""
    embedding_provider: str = "local_bge"
    embedding_model: str = ""
    embedding_dimensions: int = Field(default=0, ge=0, le=4096)
    openai_api_key: str = Field(default="", repr=False)
    fireworks_api_key: str = Field(default="", repr=False)
    embedding_timeout: float = Field(default=10, ge=1, le=30)
    visual_embedding_provider: str = "disabled"
    visual_embedding_deployment: str = ""
    visual_embedding_dimensions: int = Field(default=1024, ge=1, le=2048)
    visual_embedding_enabled: bool = False
    voyage_api_key: str = Field(default="", repr=False)
    tokenizer_path: str = ""
    docling_artifacts_path: str = ""
    text_provider: str = "disabled"
    text_endpoint: str = "https://api.openai.com/v1"
    text_model: str = ""
    verifier_model: str = ""
    model_timeout: float = Field(default=90, ge=10, le=180)
    provider_key: str = Field(default="", repr=False)
    vision_enabled: bool = False
    vision_endpoint: str = ""
    upload_limit_mb: int = 50
    expanded_limit_mb: int = 512
    max_archive_entries: int = 10000
    max_pixels: int = 40_000_000
    max_pdf_pages: int = 2000
    tool_limit: int = 20
    round_limit: int = 3
    active_seconds: int = 120
    ingest_seconds: int = 1800
    strict_projections: bool = True

    @property
    def db_path(self) -> Path:
        return self.workspace_root / "catalog.sqlite"


settings = Settings()
