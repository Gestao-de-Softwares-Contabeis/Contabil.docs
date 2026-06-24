from __future__ import annotations

import re
from collections import defaultdict

from models.client import Client
from models.document import (
    DocumentType,
    IdentificationResult,
    ProcessingStatus,
    ScoreBand,
    UploadedDocument,
)
from repositories.client_repository import ClientRepository
from repositories.routing_repository import RoutingRepository
from repositories.rule_repository import RuleRepository
from rules.matching import RuleMatcher
from ai.openai_service import OpenAIService
from utils.normalization import (
    detect_document_type,
    detect_institution,
    extract_bank_account_signals,
    extract_competence,
    extract_partner_candidates,
    extract_terms_candidates,
    normalize_competence,
    normalize_text,
    only_digits,
)
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class IdentificationService:
    def __init__(
        self,
        client_repository: ClientRepository | None = None,
        rule_repository: RuleRepository | None = None,
        routing_repository: RoutingRepository | None = None,
        ai_identifier: OpenAIService | None = None,
        record_rule_usage: bool = False,
    ) -> None:
        self.client_repository = client_repository or ClientRepository()
        self.rule_repository = rule_repository or RuleRepository()
        self.routing_repository = routing_repository or RoutingRepository()
        self.ai_identifier = ai_identifier or OpenAIService()
        self.record_rule_usage = record_rule_usage
        self.matcher = RuleMatcher()

    def identify(self, document: UploadedDocument, require_destination: bool = True) -> IdentificationResult:
        clients = self.client_repository.list_active()
        result = IdentificationResult(
            competence=extract_competence(document.original_filename, document.extracted_text),
            document_type=detect_document_type(
                document.extension,
                document.extracted_text,
                document.original_filename,
            ),
            institution=detect_institution(document.extracted_text, document.original_filename),
        )
        self._attach_extracted_signals(result, document)
        rules = self.rule_repository.list_active()
        partner_terms = [rule.rule_value for rule in rules if str(rule.rule_type) == "partner_name" and rule.rule_value]
        result.extracted_partner_candidates = extract_partner_candidates(document.extracted_text, partner_terms)
        if result.extracted_partner_candidates and not result.suggested_rule_type:
            result.suggested_rule_type = "partner_name"

        deterministic_signals = self._collect_deterministic_signals(document, clients, rules)
        result.identification_signals.update(
            {key: value for key, value in deterministic_signals.items() if key in result.identification_signals}
        )

        conflict_reason = self._detect_conflict(deterministic_signals)
        if conflict_reason:
            result.review_reason = conflict_reason
            result.score = 75
            result.matched_by = "conflito_sinais"
            result.observation = conflict_reason
            selected = self._first_signal_client(deterministic_signals)
            if selected:
                result = self._apply_client_match(result, selected, result.score, result.matched_by, result.observation)
        elif selected_signal := self._select_signal_by_priority(deterministic_signals):
            signal_name, client, score, observation = selected_signal
            result = self._apply_client_match(result, client, score, signal_name, observation)
        else:
            result.observation = "Codigo, CNPJ, nome, regras, agencia/conta e socio nao identificaram cliente."

        if self._should_use_ai(result, document):
            ai_result = self.ai_identifier.identify(document, clients)
            if ai_result:
                result = self._apply_ai_result(result, ai_result, clients)

        if not result.client_id and not result.client_code and not result.review_reason:
            result.score = 0
            result.matched_by = "revisao_manual"
            result.observation = (
                f"{result.observation} Identificacao automatica falhou; liberar parametrizacao manual."
            ).strip()
        return self._finalize(result, require_destination=require_destination)

    def _attach_extracted_signals(self, result: IdentificationResult, document: UploadedDocument) -> None:
        bank_account = extract_bank_account_signals(document.original_filename, document.extracted_text)
        result.extracted_bank_name = bank_account.get("bank_name")
        result.extracted_agency = bank_account.get("agency_normalized") or bank_account.get("agency")
        result.extracted_account_number = bank_account.get("account_number_normalized") or bank_account.get("account_number")
        result.extracted_terms_candidates = extract_terms_candidates(document.original_filename, document.extracted_text)
        if result.extracted_agency or result.extracted_account_number:
            result.suggested_rule_type = "bank_account"

    def _collect_deterministic_signals(
        self,
        document: UploadedDocument,
        clients: list[Client],
        rules: list[object],
    ) -> dict[str, object | None]:
        signals: dict[str, object | None] = {
            "manual_override": None,
            "client_code": None,
            "cnpj": None,
            "company_name": None,
            "rules": None,
            "bank_account": None,
            "partner_name": None,
            "openai": None,
        }

        if manual_rule := self.matcher.match(document, rules, allowed_rule_types={"manual_override"}):
            if client := self._client_for_rule(clients, manual_rule):
                signals["manual_override"] = self._signal(
                    client,
                    "manual_override",
                    100,
                    "Conflito resolvido por regra corretiva manual.",
                    {"rule_id": manual_rule.id},
                )

        if client_code_match := self._match_by_client_code(document, clients):
            signals["client_code"] = self._signal(client_code_match, "client_code", 99, "Identificado por codigo de cliente.")

        if cnpj_match := self._match_by_cnpj(document, clients):
            signals["cnpj"] = self._signal(cnpj_match, "cnpj", 94, "Identificado por CNPJ.")

        if name_match := self._match_by_name(document, clients):
            signals["company_name"] = self._signal(name_match, "nome_empresa", 84, "Identificado por nome ou razao social.")

        generic_rule_types = {
            "ofx",
            "pdf",
            "spreadsheet",
            "text",
            "text_term",
            "spreadsheet_term",
            "cnpj",
            "filename_term",
        }
        if matched_rule := self.matcher.match(document, rules, allowed_rule_types=generic_rule_types):
            if client := self._client_for_rule(clients, matched_rule):
                signals["rules"] = self._signal(
                    client,
                    f"regra:{matched_rule.rule_type}",
                    98,
                    "Identificado por regra parametrizada ativa.",
                )

        if bank_rule := self.matcher.match(document, rules, allowed_rule_types={"bank_account"}):
            if client := self._client_for_rule(clients, bank_rule):
                signals["bank_account"] = self._signal(
                    client,
                    "bank_account",
                    96,
                    "Identificado por agencia e conta bancaria.",
                )

        partner_rules = self.matcher.matching_partner_rules(document, rules)
        result_partners = [rule.rule_value for rule in partner_rules if rule.rule_value]
        if result_partners:
            grouped_client_codes: dict[str, set[str]] = defaultdict(set)
            for rule in partner_rules:
                if rule.rule_value and rule.client_code:
                    grouped_client_codes[normalize_text(rule.rule_value)].add(rule.client_code)
            duplicated_partner = next(
                (codes for codes in grouped_client_codes.values() if len(codes) > 1),
                None,
            )
            all_client_codes = {rule.client_code for rule in partner_rules if rule.client_code}
            if duplicated_partner:
                signals["partner_name"] = {
                    "conflict": True,
                    "reason": "Socio encontrado em multiplos clientes",
                    "client_codes": sorted(duplicated_partner),
                    "partners": result_partners,
                }
            elif len(all_client_codes) > 1:
                signals["partner_name"] = {
                    "conflict": True,
                    "reason": "Multiplas regras de socio encontradas no documento",
                    "client_codes": sorted(all_client_codes),
                    "partners": result_partners,
                }
            else:
                client = self._client_for_rule(clients, partner_rules[0])
                if client:
                    signals["partner_name"] = self._signal(
                        client,
                        "partner_name",
                        91,
                        "Identificado por regra de socio.",
                        {"partner_name": partner_rules[0].rule_value},
                    )
        return signals

    def _signal(
        self,
        client: Client,
        matched_by: str,
        score: int,
        observation: str,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "client_id": client.id,
            "client_code": client.client_code,
            "client_name": client.name,
            "client_cnpj": client.cnpj,
            "matched_by": matched_by,
            "score": score,
            "observation": observation,
        }
        if extra:
            payload.update(extra)
        return payload

    def _detect_conflict(self, signals: dict[str, object | None]) -> str | None:
        manual_override = signals.get("manual_override")
        if isinstance(manual_override, dict) and not manual_override.get("conflict"):
            return None

        strong_keys = ["client_code", "cnpj", "company_name", "bank_account", "partner_name"]
        client_codes: dict[str, list[str]] = {}
        for key in strong_keys:
            signal = signals.get(key)
            if not isinstance(signal, dict) or signal.get("conflict"):
                continue
            client_code = str(signal.get("client_code") or "")
            if client_code:
                client_codes.setdefault(client_code, []).append(key)
        if not client_codes and isinstance(signals.get("partner_name"), dict) and signals["partner_name"].get("conflict"):
            return str(signals["partner_name"].get("reason"))
        if len(client_codes) <= 1:
            return None

        parts = [f"{'/'.join(keys)} aponta cliente {code}" for code, keys in client_codes.items()]
        return "Conflito entre sinais fortes: " + "; ".join(parts)

    def _select_signal_by_priority(
        self,
        signals: dict[str, object | None],
    ) -> tuple[str, Client, int, str] | None:
        for key in ["manual_override", "client_code", "cnpj", "company_name", "rules", "bank_account", "partner_name"]:
            signal = signals.get(key)
            if not isinstance(signal, dict) or signal.get("conflict"):
                continue
            client = Client(
                id=signal.get("client_id"),
                client_code=signal.get("client_code"),
                name=str(signal.get("client_name") or ""),
                cnpj=signal.get("client_cnpj"),
            )
            return (
                str(signal.get("matched_by") or key),
                client,
                int(signal.get("score") or 0),
                str(signal.get("observation") or ""),
            )
        return None

    def _first_signal_client(self, signals: dict[str, object | None]) -> Client | None:
        selected = self._select_signal_by_priority(signals)
        if not selected:
            return None
        return selected[1]

    def _finalize(self, result: IdentificationResult, require_destination: bool = True) -> IdentificationResult:
        result.score = max(0, min(100, int(result.score or 0)))
        result.competence = normalize_competence(result.competence)
        if result.score >= 90:
            result.score_band = ScoreBand.READY_TO_SEND
        elif result.score >= 70:
            result.score_band = ScoreBand.REVIEW
        else:
            result.score_band = ScoreBand.PARAMETERIZE

        if require_destination and result.client_id:
            result.destination_folder = self.routing_repository.get_destination_folder(
                result.client_id,
                result.document_type.value,
            )

        missing_fields = []
        if not result.client_id and not result.client_code:
            missing_fields.append("cliente")
        if not result.competence:
            missing_fields.append("competencia")
        if require_destination and not result.destination_folder:
            missing_fields.append("pasta_destino")

        if missing_fields:
            result.status = ProcessingStatus.IDENTIFICATION_ERROR
            detail = "Campos obrigatorios ausentes: " + ", ".join(missing_fields)
            result.observation = f"{result.observation} {detail}".strip()
        elif result.score >= 70:
            result.status = ProcessingStatus.READY_TO_SEND
            if result.score < 90:
                result.observation = (
                    f"{result.observation} Revisar antes de confirmar envio; "
                    "parametrizacao manual nao obrigatoria."
                ).strip()
        else:
            result.status = ProcessingStatus.WAITING_RULES

        return result

    def _should_use_ai(self, result: IdentificationResult, document: UploadedDocument) -> bool:
        if result.review_reason:
            return False
        has_text = bool(document.extracted_text.strip())
        automatic_identification_incomplete = (
            (not result.client_id and not result.client_code)
            or not result.competence
        )
        return has_text and automatic_identification_incomplete

    def _apply_rule_result(
        self,
        result: IdentificationResult,
        matched_rule: object,
        clients: list[Client],
    ) -> IdentificationResult:
        client = self._client_by_code(clients, matched_rule.client_code or "") or self._client_by_id(
            clients,
            matched_rule.client_id or "",
        )
        result.client_id = client.id if client else matched_rule.client_id
        result.client_code = client.client_code if client else matched_rule.client_code
        result.client_name = client.name if client else matched_rule.client_name
        result.client_cnpj = client.cnpj if client else None
        result.document_type = self._document_type_or_default(matched_rule.document_type, result.document_type)
        result.institution = matched_rule.institution or matched_rule.bank_name or result.institution
        result.score = 98
        rule_type = getattr(matched_rule.rule_type, "value", matched_rule.rule_type)
        result.matched_by = f"regra:{rule_type}"
        result.observation = "Identificado por regra parametrizada ativa."
        if self.record_rule_usage and matched_rule.id:
            self.rule_repository.mark_used(matched_rule.id, matched_rule.hits_count)
        return result

    def _apply_client_match(
        self,
        result: IdentificationResult,
        client: Client,
        score: int,
        matched_by: str,
        observation: str,
    ) -> IdentificationResult:
        result.client_id = client.id
        result.client_code = client.client_code
        result.client_name = client.name
        result.client_cnpj = client.cnpj
        result.score = score
        result.matched_by = matched_by
        result.observation = observation
        return result

    def _client_by_id(self, clients: list[Client], client_id: str) -> Client | None:
        for client in clients:
            if client.id == client_id:
                return client
        return None

    def _client_for_rule(self, clients: list[Client], rule: object) -> Client | None:
        client_code = str(getattr(rule, "client_code", "") or "")
        client_id = str(getattr(rule, "client_id", "") or "")
        return self._client_by_code(clients, client_code) or self._client_by_id(clients, client_id)

    def _document_type_or_default(self, value: str | None, fallback: DocumentType) -> DocumentType:
        if not value:
            return fallback
        try:
            return DocumentType(value)
        except ValueError:
            logger.info("Tipo de documento invalido em regra", extra={"ctx_document_type": value})
            return fallback

    def _match_by_client_code(self, document: UploadedDocument, clients: list[Client]) -> Client | None:
        source = f"{document.original_filename}\n{document.extracted_text[:5000]}"
        normalized = normalize_text(source)
        best_client: Client | None = None
        best_length = 0
        for client in clients:
            if not client.client_code:
                continue
            code = re.escape(client.client_code)
            explicit_patterns = [
                rf"\bcliente\s*(?:codigo|c[oó]digo|cod\.?)?\s*[:#\- ]+\s*{code}\b",
                rf"\bcod(?:igo)?\s*cliente\s*[:#\- ]+\s*{code}\b",
                rf"^{code}[\s\-_]",
                rf"\b{code}\s*[-_]\s*{re.escape(normalize_text(client.name).split(' ')[0])}\b",
            ]
            if any(re.search(pattern, source, flags=re.IGNORECASE) for pattern in explicit_patterns):
                if len(client.client_code) > best_length:
                    best_client = client
                    best_length = len(client.client_code)
            elif f" cliente {client.client_code} " in f" {normalized} ":
                best_client = client
        return best_client

    def _match_by_cnpj(self, document: UploadedDocument, clients: list[Client]) -> Client | None:
        digits_text = only_digits(document.extracted_text)
        best_client: Client | None = None
        best_index: int | None = None
        for client in clients:
            cnpj = only_digits(client.cnpj)
            if len(cnpj) != 14:
                continue
            index = digits_text.find(cnpj)
            if index >= 0 and (best_index is None or index < best_index):
                best_client = client
                best_index = index
        return best_client

    def _match_by_name(self, document: UploadedDocument, clients: list[Client]) -> Client | None:
        text = normalize_text(f"{document.original_filename} {document.extracted_text}")
        best_client: Client | None = None
        best_length = 0
        for client in clients:
            terms = [client.name, *(client.aliases or [])]
            for term in terms:
                normalized = normalize_text(term)
                if len(normalized) >= 5 and normalized in text and len(normalized) > best_length:
                    best_client = client
                    best_length = len(normalized)
        return best_client

    def _apply_ai_result(
        self,
        result: IdentificationResult,
        ai_result: dict[str, object],
        clients: list[Client],
    ) -> IdentificationResult:
        client_id = self._clean_ai_text(ai_result.get("cliente_id"))
        client_code = self._clean_ai_text(ai_result.get("cliente_codigo") or ai_result.get("client_code"))
        client_name = self._clean_ai_text(ai_result.get("cliente_nome") or ai_result.get("cliente"))
        client_cnpj = self._clean_ai_text(ai_result.get("cliente_cnpj") or ai_result.get("cnpj"))
        client = (
            self._client_by_id(clients, client_id)
            or self._client_by_code(clients, client_code)
            or self._client_by_cnpj(clients, client_cnpj)
            or self._client_by_name(clients, client_name)
        )
        ai_score = self._parse_score(ai_result.get("score"))

        result.ai_used = True
        if result.client_id:
            result.matched_by = f"{result.matched_by}+openai"
        else:
            result.matched_by = "openai"
        if client:
            result.client_id = client.id
            result.client_code = client.client_code
            result.client_name = client.name
            result.client_cnpj = client.cnpj
            result.identification_signals["openai"] = self._signal(
                client,
                "openai",
                ai_score,
                "Identificado pela OpenAI.",
            )
        else:
            result.identification_signals["openai"] = {
                "accepted": False,
                "client_code": client_code or None,
                "client_name": client_name or None,
                "client_cnpj": client_cnpj or None,
                "score": ai_score,
                "reason": "Cliente retornado pela OpenAI nao cruzou com clients.",
            }
        if not result.competence:
            result.competence = normalize_competence(str(ai_result.get("competencia") or "")) or None
        ai_document_type = self._document_type_or_default(str(ai_result.get("tipo_documento") or ""), result.document_type)
        if ai_document_type != DocumentType.OTHER or result.document_type == DocumentType.OTHER:
            result.document_type = ai_document_type
        if not result.institution:
            result.institution = str(ai_result.get("instituicao") or "") or None
        result.score = max(result.score, ai_score)
        result.observation = f"{result.observation} OpenAI usada como fallback/complemento automatico.".strip()
        return result

    def _clean_ai_text(self, value: object) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if text.lower() in {"", "null", "none", "nan", "n/a", "nao identificado", "não identificado"}:
            return ""
        return text

    def _client_by_name(self, clients: list[Client], client_name: str) -> Client | None:
        normalized_name = normalize_text(client_name)
        for client in clients:
            if normalize_text(client.name) == normalized_name:
                return client
        return None

    def _client_by_code(self, clients: list[Client], client_code: str) -> Client | None:
        if not client_code:
            return None
        for client in clients:
            if client.client_code and client.client_code == client_code:
                return client
        return None

    def _client_by_cnpj(self, clients: list[Client], cnpj: str) -> Client | None:
        digits = only_digits(cnpj)
        if len(digits) != 14:
            return None
        for client in clients:
            if only_digits(client.cnpj) == digits:
                return client
        return None

    def _parse_score(self, value: object) -> int:
        try:
            numeric = float(value or 0)
            if 0 < numeric <= 1:
                numeric *= 100
            return max(0, min(100, int(numeric)))
        except (TypeError, ValueError):
            return 0
