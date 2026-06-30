from __future__ import annotations

import re
from datetime import datetime
from typing import Any


STATUS_ORDER = {
    "ERRO_ENVIO": 0,
    "ERRO_IDENTIFICACAO": 0,
    "REVISAR": 1,
    "AGUARDANDO_PARAMETRIZACAO": 1,
    "PROCESSANDO": 2,
    "PRONTO_ENVIO": 3,
    "RECEBIDO": 4,
    "ENVIADO": 5,
    "DESCARTADO": 6,
}


def client_code_sort_key(value: str | None) -> tuple[int, str]:
    text = str(value or "").strip()
    match = re.match(r"\D*(\d+)", text)
    if not match:
        return (10**9, text.lower())
    return (int(match.group(1)), text.lower())


def status_sort_key(status: str | None) -> tuple[int, str]:
    text = str(status or "")
    return (STATUS_ORDER.get(text, 99), text)


def format_competence(value: str | None) -> str:
    text = str(value or "").strip()
    match = re.match(r"^(\d{4})-(\d{2})$", text)
    if match:
        return f"{match.group(2)}/{match.group(1)}"
    match = re.match(r"^(\d{2})/(\d{4})$", text)
    if match:
        return text
    return text


def format_score(value: float | int | None) -> str:
    if value is None:
        return ""
    number = float(value)
    if number <= 1:
        number *= 100
    return f"{number:.0f}%"


def format_datetime(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    return str(value)
