from __future__ import annotations

import json
from typing import Any

from app.settings import load_settings
from models.client import Client
from models.document import DocumentType, UploadedDocument
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class OpenAIService:
    def __init__(self) -> None:
        self.settings = load_settings()

    def identify(self, document: UploadedDocument, clients: list[Client]) -> dict[str, Any] | None:
        if not self.settings.openai_is_configured:
            return None

        payload = {
            "arquivo": document.original_filename,
            "extensao": document.extension,
            "texto": document.extracted_text[: self.settings.max_text_chars_for_ai],
            "tipos_documento_permitidos": [item.value for item in DocumentType],
            "clientes": [
                {
                    "id": client.id,
                    "client_code": client.client_code,
                    "nome": client.name,
                    "cnpj": client.cnpj,
                    "aliases": client.aliases,
                }
                for client in clients
            ],
        }
        system_prompt = (
            "Voce identifica documentos contabeis para roteamento interno. "
            "Use apenas clientes da lista recebida. Se nao houver confianca, retorne cliente_id null. "
            "A competencia deve estar no formato YYYY-MM. "
            "Retorne somente JSON valido com as chaves: "
            "cliente_id, cliente_codigo, cliente_nome, cliente_cnpj, competencia, "
            "tipo_documento, instituicao, score."
        )

        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.settings.openai_api_key)
            if hasattr(client, "responses"):
                response = client.responses.create(
                    model=self.settings.openai_model,
                    input=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                )
                output_text = getattr(response, "output_text", "")
            else:
                response = client.chat.completions.create(
                    model=self.settings.openai_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    response_format={"type": "json_object"},
                )
                output_text = response.choices[0].message.content or "{}"
            parsed = json.loads(output_text or "{}")
            if not isinstance(parsed, dict):
                logger.info(
                    "Fallback OpenAI ignorado por retornar formato inesperado",
                    extra={"ctx_file_hash": document.file_hash, "ctx_response_type": type(parsed).__name__},
                )
                return None
            return parsed
        except Exception:
            logger.exception("Falha no fallback OpenAI", extra={"ctx_file_hash": document.file_hash})
            return None
