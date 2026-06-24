from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date
import re
import unicodedata
from pathlib import Path
from typing import Any

from models.document import DocumentType


MONTHS_PT = {
    "janeiro": "01",
    "fevereiro": "02",
    "marco": "03",
    "abril": "04",
    "maio": "05",
    "junho": "06",
    "julho": "07",
    "agosto": "08",
    "setembro": "09",
    "outubro": "10",
    "novembro": "11",
    "dezembro": "12",
}


def only_digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def get_extension(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()

    for pattern in (
        r"(?<!\d)([0-3]\d)[/\-. ](0[1-9]|1[0-2])[/\-. ](20\d{2})(?!\d)",
        r"(?<!\d)(20\d{2})[/\-. ](0[1-9]|1[0-2])[/\-. ]([0-3]\d)(?!\d)",
    ):
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            if pattern.startswith("(?<!\\d)([0-3]"):
                return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None

    match = re.search(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])([0-3]\d)(?!\d)", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None

    return None


def _competence_from_date(value: date | None) -> str | None:
    if not value:
        return None
    return f"{value.year:04d}-{value.month:02d}"


def _previous_month_from_date(value: date | None) -> str | None:
    if not value:
        return None
    year = value.year
    month = value.month - 1
    if month == 0:
        year -= 1
        month = 12
    return f"{year:04d}-{month:02d}"


def _most_common_competence(dates: list[date]) -> str | None:
    if not dates:
        return None
    counter = Counter(_competence_from_date(item) for item in dates)
    competence, _ = counter.most_common(1)[0]
    return competence


def extract_due_date(text: str) -> date | None:
    patterns = [
        r"(?:vencimento|venc\.?|vcto\.?|data de vencimento)[^\d]{0,40}([0-3]\d[/\-. ](?:0[1-9]|1[0-2])[/\-. ]20\d{2})",
        r"(?:vencimento|venc\.?|vcto\.?|data de vencimento)[^\d]{0,40}((?:0[1-9]|1[0-2])[/\-. ]20\d{2})",
        r"(?:vencimento|venc\.?|vcto\.?|data de vencimento)[^\d]{0,40}((?:20\d{2})[/\-. ](?:0[1-9]|1[0-2]))",
        r"([0-3]\d[/\-. ](?:0[1-9]|1[0-2])[/\-. ]20\d{2})[^\n\r]{0,80}(?:vencimento|venc\.?|vcto\.?|data de vencimento)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1)
        parsed = _parse_date(value)
        if parsed:
            return parsed
        competence = normalize_competence(value)
        if competence:
            year, month = competence.split("-", 1)
            return date(int(year), int(month), 1)
    return None


def extract_issue_date(text: str) -> date | None:
    labelled_patterns = [
        r"(?:emiss[aã]o|emitido em|gera[cç][aã]o|gerado em|consulta|consultado em|atualiza[cç][aã]o|data do documento)[^\d]{0,40}([0-3]\d[/\-. ](?:0[1-9]|1[0-2])[/\-. ]20\d{2})",
        r"(?:emiss[aã]o|emitido em|gera[cç][aã]o|gerado em|consulta|consultado em|atualiza[cç][aã]o|data do documento)[^\d]{0,40}((?:20\d{2})[/\-. ](?:0[1-9]|1[0-2])[/\-. ][0-3]\d)",
    ]
    for pattern in labelled_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            parsed = _parse_date(match.group(1))
            if parsed:
                return parsed

    first_date = re.search(r"(?<!\d)([0-3]\d[/\-. ](?:0[1-9]|1[0-2])[/\-. ]20\d{2})(?!\d)", text[:1000])
    if first_date:
        return _parse_date(first_date.group(1))
    return None


def extract_period_dates(text: str) -> tuple[date | None, date | None]:
    ofx_start = re.search(r"<DTSTART>\s*(20\d{2})(0[1-9]|1[0-2])([0-3]\d)", text, flags=re.IGNORECASE)
    ofx_end = re.search(r"<DTEND>\s*(20\d{2})(0[1-9]|1[0-2])([0-3]\d)", text, flags=re.IGNORECASE)
    if ofx_start or ofx_end:
        start = _parse_date("".join(ofx_start.groups())) if ofx_start else None
        end = _parse_date("".join(ofx_end.groups())) if ofx_end else None
        return start, end

    pattern = (
        r"(?:periodo|período|lan[cç]amentos do per[ií]odo|de)"
        r"[^\n]{0,80}?([0-3]\d[/\-. ](?:0[1-9]|1[0-2])[/\-. ]20\d{2})"
        r"[^\n]{0,80}?(?:ate|até|a|-)"
        r"[^\n]{0,40}?([0-3]\d[/\-. ](?:0[1-9]|1[0-2])[/\-. ]20\d{2})"
    )
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match:
        return _parse_date(match.group(1)), _parse_date(match.group(2))
    return None, None


def extract_document_dates(filename: str, text: str) -> dict[str, Any]:
    source = f"{filename}\n{text[:12000]}"
    period_start, period_end = extract_period_dates(source)
    dates: list[date] = []
    for raw in re.findall(r"(?<!\d)([0-3]\d[/\-. ](?:0[1-9]|1[0-2])[/\-. ]20\d{2})(?!\d)", source):
        parsed = _parse_date(raw)
        if parsed:
            dates.append(parsed)
    for raw in re.findall(r"(?<!\d)((?:20\d{2})(?:0[1-9]|1[0-2])(?:[0-3]\d))(?!\d)", source):
        parsed = _parse_date(raw)
        if parsed:
            dates.append(parsed)
    return {
        "extracted_dates": dates,
        "issue_date": extract_issue_date(source),
        "due_date": extract_due_date(source),
        "period_start": period_start,
        "period_end": period_end,
    }


def resolve_competence(
    document_type: str | DocumentType,
    extracted_dates: list[date] | None = None,
    issue_date: date | None = None,
    due_date: date | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> str | None:
    doc_type = document_type.value if isinstance(document_type, DocumentType) else str(document_type or "")
    extracted_dates = extracted_dates or []

    if doc_type in {DocumentType.CREDIT_CARD_INVOICE.value, DocumentType.CARD_REPORT.value}:
        return _previous_month_from_date(due_date) or _competence_from_date(period_start) or _most_common_competence(extracted_dates)

    if doc_type in {DocumentType.INVESTMENT_POSITION.value, DocumentType.INVESTMENT_INCOME.value}:
        if period_start and period_end:
            return _competence_from_date(period_start)
        return _previous_month_from_date(issue_date) or _most_common_competence(extracted_dates)

    if doc_type in {
        DocumentType.FINANCIAL_REPORT.value,
        DocumentType.FINANCIAL_REPORT_PAID.value,
        DocumentType.FINANCIAL_REPORT_RECEIVED.value,
    }:
        return _competence_from_date(period_start) or _most_common_competence(extracted_dates)

    if period_start:
        return _competence_from_date(period_start)
    if period_end:
        return _competence_from_date(period_end)
    return _most_common_competence(extracted_dates)


def normalize_competence(value: str | None) -> str | None:
    if not value:
        return None

    source = value.strip()
    match = re.search(r"(?<!\d)(20\d{2})[\-/_. ]?(0[1-9]|1[0-2])(?!\d)", source)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    match = re.search(r"(?<!\d)(0[1-9]|1[0-2])[\-/_. ](20\d{2})(?!\d)", source)
    if match:
        return f"{match.group(2)}-{match.group(1)}"

    match = re.search(r"(?<!\d)(20\d{2})[\-/_. ](0[1-9]|1[0-2])(?!\d)", source)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    return None


def competence_to_mmyyyy(value: str | None) -> str | None:
    competence = normalize_competence(value)
    if not competence:
        return None
    year, month = competence.split("-", 1)
    return f"{month}{year}"


def extract_competence(filename: str, text: str) -> str | None:
    source = f"{filename}\n{text[:8000]}"
    normalized = normalize_text(source)
    document_type = detect_document_type(get_extension(filename), text, filename)
    dates = extract_document_dates(filename, text)
    resolved = resolve_competence(
        document_type=document_type,
        extracted_dates=dates["extracted_dates"],
        issue_date=dates["issue_date"],
        due_date=dates["due_date"],
        period_start=dates["period_start"],
        period_end=dates["period_end"],
    )
    if resolved:
        return resolved

    filename_competence = _extract_filename_competence(filename)
    if filename_competence:
        return filename_competence

    competence_match = re.search(
        r"(?:competencia|competência|referencia|referência)[^\d]{0,40}"
        r"((?:0[1-9]|1[0-2])[\-/_. ](?:20\d{2})|(?:20\d{2})[\-/_. ](?:0[1-9]|1[0-2]))",
        source,
        flags=re.IGNORECASE,
    )
    if competence_match:
        return normalize_competence(competence_match.group(1))

    for match in re.finditer(r"(?<!\d)(0[1-9]|1[0-2])[\-/_. ](20\d{2})(?!\d)", source):
        return f"{match.group(2)}-{match.group(1)}"

    for match in re.finditer(r"(?<!\d)(20\d{2})[\-/_. ](0[1-9]|1[0-2])(?!\d)", source):
        return f"{match.group(1)}-{match.group(2)}"

    for match in re.finditer(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(?!\d)", source):
        return f"{match.group(1)}-{match.group(2)}"

    for month, number in MONTHS_PT.items():
        pattern = rf"\b{month}\s+(20\d{{2}})\b"
        match = re.search(pattern, normalized)
        if match:
            return f"{match.group(1)}-{number}"

    return None


def _extract_filename_competence(filename: str) -> str | None:
    for match in re.finditer(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(?!\d)", filename):
        return f"{match.group(1)}-{match.group(2)}"

    for match in re.finditer(r"(?<!\d)(0[1-9]|1[0-2])[\-_ .](20\d{2})(?![\-_ .]?\d)", filename):
        return f"{match.group(2)}-{match.group(1)}"

    for match in re.finditer(r"(?<!\d)(20\d{2})[\-_ .](0[1-9]|1[0-2])(?![\-_ .]?\d)", filename):
        return f"{match.group(1)}-{match.group(2)}"

    return None


def extract_cnpjs(text: str) -> list[str]:
    formatted = re.findall(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b", text)
    cnpjs: list[str] = []
    for item in formatted:
        digits = only_digits(item)
        if len(digits) == 14 and digits not in cnpjs:
            cnpjs.append(digits)
    return cnpjs


def sanitize_filename_part(value: str | None, fallback: str) -> str:
    cleaned = (value or fallback).strip()
    cleaned = re.sub(r'[<>:"/\\|?*]+', " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or fallback


def build_client_display_name(client_name: str | None, client_code: str | None = None) -> str:
    fallback = client_code or "CLIENTE"
    cleaned = sanitize_filename_part(client_name, fallback)
    cleaned = re.sub(r"\s*-\s*", " ", cleaned)
    cleaned = re.sub(
        r"\b(?:LTDA\.?|ME|EPP|S\.?A\.?|SA|EIRELI)\b\.?",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")

    normalized = normalize_text(cleaned)
    if normalized.startswith("rz comercio de bijuterias"):
        return "RZ COMERCIO DE BIJUTERIAS"

    excessive_complements = [
        r"\s+E\s+ACESSORIOS\b.*$",
        r"\s+E\s+ACESSORIOS\s+FEMININOS\b.*$",
    ]
    for pattern in excessive_complements:
        shortened = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip(" .-")
        if shortened and len(shortened) >= 5:
            cleaned = shortened
            break

    return cleaned or fallback


def normalize_bank_number(value: str | None) -> str:
    digits = only_digits(value)
    if not digits:
        return ""
    return digits.lstrip("0") or "0"


def bank_number_variants(value: str | None, kind: str) -> list[str]:
    digits = only_digits(value)
    normalized = normalize_bank_number(value)
    variants = [item for item in [digits, normalized] if item]
    if kind == "agency" and len(digits) == 5:
        variants.append(digits[:4])
    return list(dict.fromkeys(variants))


def _first_regex_group(source: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            return next((group for group in match.groups() if group), None)
    return None


def extract_bank_account_signals(filename: str, text: str) -> dict[str, Any]:
    source = f"{filename}\n{text[:12000]}"
    bank_name = detect_institution(source, filename)
    ofx_bank = _first_regex_group(source, [r"<ORG>\s*([^<\r\n]+)", r"<BANKID>\s*([^<\r\n]+)"])
    if not bank_name and ofx_bank:
        bank_name = ofx_bank.strip()

    agency = None
    account = None

    agency_account = re.search(
        r"(?:ag[eê]ncia\s*e\s*conta|agencia\s*e\s*conta|ag/conta)[^\d]{0,20}"
        r"([0-9.\-]{3,8})\s*/\s*([0-9.\-]{4,16})",
        source,
        flags=re.IGNORECASE,
    )
    if agency_account:
        agency = agency_account.group(1)
        account = agency_account.group(2)

    agency = agency or _first_regex_group(
        source,
        [
            r"<BRANCHID>\s*([^<\r\n]+)",
            r"\b(?:ag[eê]ncia|agencia|ag\.)\s*[:;\-/ ]+\s*([0-9.\-]{3,8})",
            r"\bAgencia;([0-9.\-]{3,8})",
            r"\bAgência:;?([0-9.\-]{3,8})",
        ],
    )
    account = account or _first_regex_group(
        source,
        [
            r"<ACCTID>\s*([^<\r\n]+)",
            r"\b(?:conta\s*corrente|conta|account|acctid)\s*[:;\-/ ]+\s*([0-9.\-]{4,18})",
            r"\bConta corrente;([0-9.\-]{4,18})",
            r"\bConta:;?([0-9.\-]{4,18})",
        ],
    )

    account_digits = only_digits(account)
    if not agency and account_digits and len(account_digits) >= 9 and "<ACCTID>" in source.upper():
        agency = account_digits[:4]
        account = account_digits[4:]

    if not agency:
        filename_digits = re.findall(r"\d{10,16}", filename)
        filename_digits = [item for item in filename_digits if not item.startswith("20")]
        if filename_digits:
            compact = filename_digits[0]
            if compact.startswith("0") and len(compact) >= 10:
                agency = compact[:4]
                account = account or compact[4:]
            elif len(compact) >= 12:
                agency = compact[:5]
                account = account or compact[5:]

    return {
        "bank_name": bank_name,
        "agency": agency.strip() if isinstance(agency, str) else None,
        "agency_normalized": normalize_bank_number(agency),
        "agency_variants": bank_number_variants(agency, "agency"),
        "account_number": account.strip() if isinstance(account, str) else None,
        "account_number_normalized": normalize_bank_number(account),
        "account_number_variants": bank_number_variants(account, "account"),
    }


def extract_partner_candidates(text: str, partner_terms: list[str] | None = None) -> list[str]:
    if not partner_terms:
        return []
    normalized = normalize_text(text)
    found: list[str] = []
    for term in partner_terms:
        if term and normalize_text(term) in normalized:
            found.append(term)
    return list(dict.fromkeys(found))


def extract_terms_candidates(filename: str, text: str) -> list[str]:
    candidates: list[str] = []
    stem = Path(filename).stem.strip()
    if stem:
        candidates.append(stem)

    for pattern in [
        r"\bNome\s*[:;]\s*([^\n\r;]{5,100})",
        r"\bCliente\s*[-:;]\s*([^\n\r;]{5,100})",
        r"\bRaz[aã]o social\s*[:;]\s*([^\n\r;]{5,100})",
    ]:
        for match in re.finditer(pattern, text[:5000], flags=re.IGNORECASE):
            term = re.sub(r"\s+", " ", match.group(1)).strip()
            if term:
                candidates.append(term)

    return list(dict.fromkeys(candidates))[:10]


def detect_document_type(extension: str, text: str, filename: str = "") -> DocumentType:
    normalized = normalize_text(f"{filename} {text[:5000]}")
    normalized_filename = normalize_text(filename)
    if extension == "ofx" or "ofx" in normalized:
        return DocumentType.OFX
    if (
        "rendimentos" in normalized
        or "renda fixa" in normalized
        or "extrato consolidado renda fixa" in normalized
    ):
        return DocumentType.INVESTMENT_INCOME
    if (
        "posicao detalhada" in normalized
        or "posição detalhada" in normalized
        or "investimentos" in normalized
        or "cdb di" in normalized
        or "operacoes" in normalized and "posicao" in normalized
    ):
        return DocumentType.INVESTMENT_POSITION
    if "extrato financeiro" in normalized_filename or "extrato financeiro" in normalized:
        return DocumentType.FINANCIAL_REPORT
    if "fatura" in normalized:
        return DocumentType.CREDIT_CARD_INVOICE
    if "cartao" in normalized:
        return DocumentType.CARD_REPORT
    if (
        "extrato conta corrente" in normalized
        or "extrato de conta" in normalized
        or "conta corrente" in normalized
        or ("extrato" in normalized_filename and "extrato financeiro" not in normalized_filename)
    ):
        return DocumentType.BANK_STATEMENT
    if "contas pagas" in normalized or "pagamentos" in normalized:
        return DocumentType.FINANCIAL_REPORT_PAID
    if "contas recebidas" in normalized or "recebimentos" in normalized:
        return DocumentType.FINANCIAL_REPORT_RECEIVED
    if "comprovante" in normalized or "recibo" in normalized:
        return DocumentType.RECEIPT
    if "extrato" in normalized or "saldo" in normalized:
        return DocumentType.BANK_STATEMENT
    return DocumentType.OTHER


def detect_institution(text: str, filename: str = "") -> str | None:
    source = f"{filename} {text[:5000]}"
    normalized = f" {normalize_text(source)} "
    raw_upper = source.upper()

    deterministic_rules = [
        (
            "Banco do Brasil",
            [
                lambda: "BANCO DO BRASIL" in raw_upper,
                lambda: "OUROCARD" in raw_upper,
                lambda: "BB.COM.BR" in raw_upper,
                lambda: bool(re.search(r"\bBB\b", raw_upper)),
            ],
        ),
        ("Caixa Economica", [lambda: " caixa " in normalized, lambda: " caixa economica " in normalized, lambda: bool(re.search(r"\bCEF\b", raw_upper))]),
        ("Sicoob", [lambda: " sicoob " in normalized]),
        ("Sicredi", [lambda: " sicredi " in normalized]),
        ("Nubank", [lambda: " nubank " in normalized]),
        ("Santander", [lambda: " santander " in normalized]),
        ("PagBank", [lambda: " pagbank " in normalized]),
        ("Inter", [lambda: bool(re.search(r"\bINTER\b", raw_upper))]),
        ("Itau", [lambda: " itau " in normalized]),
        ("Bradesco", [lambda: " bradesco " in normalized]),
        ("Cora", [lambda: " cora " in normalized]),
    ]
    for label, checks in deterministic_rules:
        if any(check() for check in checks):
            return label
    return None
