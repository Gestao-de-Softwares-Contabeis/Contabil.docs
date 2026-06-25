from __future__ import annotations

import os
import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import BaseModel, Field


ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.lower().startswith("export "):
            stripped = stripped[7:].strip()
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_env() -> None:
    logging.getLogger("dotenv.main").setLevel(logging.ERROR)
    load_dotenv(ROOT_DIR / ".env", override=True)
    _load_env_file(ROOT_DIR / ".env")


def _first_env(names: list[str], default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return default


def get_n8n_webhook_url() -> str:
    load_env()
    url = _first_env(["N8N_WEBHOOK_URL", "N8N_TEST_WEBHOOK_URL"])
    if not url:
        raise ValueError(
            "Webhook n8n nao configurado. Defina N8N_WEBHOOK_URL ou N8N_TEST_WEBHOOK_URL no .env."
        )
    return url


def get_n8n_webhook_debug_info() -> dict[str, str]:
    load_env()
    for variable in ["N8N_WEBHOOK_URL", "N8N_TEST_WEBHOOK_URL"]:
        url = os.getenv(variable, "").strip()
        if url:
            parsed = urlparse(url)
            endpoint = f"{parsed.netloc}{parsed.path}" if parsed.netloc else parsed.path
            return {"variable": variable, "endpoint": endpoint}
    raise ValueError(
        "Webhook n8n nao configurado. Defina N8N_WEBHOOK_URL ou N8N_TEST_WEBHOOK_URL no .env."
    )


def _csv_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


class AppSettings(BaseModel):
    supabase_url: str = ""
    supabase_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    n8n_webhook_url: str = ""
    supabase_storage_bucket: str = "incoming-documents"
    supabase_storage_upload_prefix: str = "uploads"
    storage_signed_url_ttl_seconds: int = 600
    n8n_timeout_seconds: int = 30
    origin_channels: list[str] = Field(default_factory=list)
    app_log_path: Path = ROOT_DIR / "logs" / "app.log"
    max_text_chars_for_ai: int = 12000
    max_text_chars_to_store: int = 20000

    @property
    def supabase_is_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def openai_is_configured(self) -> bool:
        return bool(self.openai_api_key and self.openai_model)

    @property
    def n8n_is_configured(self) -> bool:
        return bool(self.n8n_webhook_url)


@lru_cache(maxsize=1)
def load_settings() -> AppSettings:
    load_env()
    return AppSettings(
        supabase_url=_first_env(["SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL", "link"]),
        supabase_key=_first_env(
            [
                "SUPABASE_SERVICE_ROLE_KEY",
                "service_role_key",
                "SUPABASE_KEY",
                "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
                "anon_public",
            ]
        ),
        openai_api_key=_first_env(["OPENAI_API_KEY"]),
        openai_model=_first_env(["OPENAI_MODEL"], "gpt-4.1-mini"),
        n8n_webhook_url=_first_env(
            [
                "N8N_WEBHOOK_URL",
                "N8N_TEST_WEBHOOK_URL",
            ]
        ),
        supabase_storage_bucket=_first_env(["SUPABASE_STORAGE_BUCKET"], "incoming-documents"),
        supabase_storage_upload_prefix=_first_env(["SUPABASE_STORAGE_UPLOAD_PREFIX"], "uploads"),
        storage_signed_url_ttl_seconds=int(_first_env(["STORAGE_SIGNED_URL_TTL_SECONDS"], "600")),
        n8n_timeout_seconds=int(_first_env(["N8N_TIMEOUT_SECONDS"], "30")),
        origin_channels=_csv_env(
            "ORIGIN_CHANNELS",
            ["Onvio", "E-mail", "Whatsapp/Messenger", "Drive do Cliente", "Outros"],
        ),
        max_text_chars_for_ai=int(_first_env(["MAX_TEXT_CHARS_FOR_AI"], "12000")),
        max_text_chars_to_store=int(_first_env(["MAX_TEXT_CHARS_TO_STORE"], "20000")),
    )
