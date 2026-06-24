from __future__ import annotations

from models.document import DocumentLogEntry
from models.rule import DocumentRule


def document_rows(logs: list[DocumentLogEntry]) -> list[dict[str, object]]:
    return [
        {
            "nome arquivo": item.original_filename,
            "cliente identificado": item.client_name,
            "competencia": item.competence,
            "tipo documento": item.document_type,
            "score": item.score,
            "faixa score": item.score_band,
            "responsavel envio": item.sender_name,
            "setor": item.sender_department,
            "canal origem": item.origin_channel,
            "status": item.status,
            "identificado por": item.matched_by,
            "hash": item.file_hash,
            "observacao": item.observation,
        }
        for item in logs
    ]


def history_rows(logs: list[DocumentLogEntry]) -> list[dict[str, object]]:
    return [
        {
            "data hora": item.created_at,
            "usuario": item.user_name,
            "setor usuario": item.user_department,
            "acao executada": item.action,
            "cliente": item.client_name,
            "documento": item.original_filename,
            "competencia": item.competence,
            "tipo documento": item.document_type,
            "score": item.score,
            "faixa score": item.score_band,
            "status": item.status,
            "identificado por": item.matched_by,
            "ia usada": item.ai_used,
            "observacao": item.observation,
        }
        for item in logs
    ]


def rule_rows(rules: list[DocumentRule]) -> list[dict[str, object]]:
    return [
        {
            "id": item.id,
            "cliente": item.client_name or item.client_code,
            "tipo regra": getattr(item.rule_type, "value", item.rule_type),
            "tipo documento": item.document_type,
            "regra": item.rule_name,
            "valor": item.rule_value,
            "banco": item.bank_name,
            "agencia": item.agency,
            "conta": item.account_number,
            "modo": item.match_mode,
            "ativa": item.active,
            "criado por": item.created_by,
            "criado em": item.created_at,
            "ultima utilizacao": item.last_used_at,
            "quantidade acertos": item.hits_count,
        }
        for item in rules
    ]
