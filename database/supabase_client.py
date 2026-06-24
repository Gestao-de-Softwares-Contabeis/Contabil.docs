from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.settings import load_settings


class SupabaseConfigurationError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_supabase_client() -> Any:
    settings = load_settings()
    if not settings.supabase_is_configured:
        raise SupabaseConfigurationError("Supabase nao configurado no arquivo .env.")
    try:
        from supabase import create_client
    except ImportError as exc:
        raise SupabaseConfigurationError(
            "Pacote supabase nao instalado. Rode: pip install -r requirements.txt"
        ) from exc
    return create_client(settings.supabase_url, settings.supabase_key)
