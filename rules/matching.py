from __future__ import annotations

from models.document import UploadedDocument
from models.rule import DocumentRule, RuleType
from utils.normalization import (
    bank_number_variants,
    extract_bank_account_signals,
    normalize_text,
    only_digits,
)


class RuleMatcher:
    def match(
        self,
        document: UploadedDocument,
        rules: list[DocumentRule],
        allowed_rule_types: set[str] | None = None,
    ) -> DocumentRule | None:
        source = f"{document.original_filename}\n{document.extracted_text}"
        for rule in rules:
            rule_type = str(rule.rule_type)
            if allowed_rule_types is not None and rule_type not in allowed_rule_types:
                continue
            if self._rule_matches_document_type(
                document.extension,
                rule.rule_type,
                rule.file_extension,
            ) and self._rule_matches(document, source, rule):
                return rule
        return None

    def matching_partner_rules(
        self,
        document: UploadedDocument,
        rules: list[DocumentRule],
    ) -> list[DocumentRule]:
        source = f"{document.original_filename}\n{document.extracted_text}"
        matches: list[DocumentRule] = []
        for rule in rules:
            if str(rule.rule_type) != RuleType.PARTNER_NAME.value:
                continue
            if self._rule_matches_document_type(
                document.extension,
                rule.rule_type,
                rule.file_extension,
            ) and self._partner_name_matches(source, rule.rule_value):
                matches.append(rule)
        return matches

    def _rule_matches_document_type(
        self,
        extension: str,
        rule_type: RuleType | str,
        file_extension: str | None = None,
    ) -> bool:
        if file_extension:
            return extension == file_extension.lower().lstrip(".")

        if isinstance(rule_type, str):
            try:
                rule_type = RuleType(rule_type)
            except ValueError:
                return False
        if rule_type in {
            RuleType.BANK_ACCOUNT,
            RuleType.PARTNER_NAME,
            RuleType.MANUAL_OVERRIDE,
            RuleType.TEXT_TERM,
            RuleType.SPREADSHEET_TERM,
            RuleType.CNPJ,
            RuleType.FILENAME_TERM,
        }:
            return True
        if rule_type == RuleType.OFX:
            return extension == "ofx"
        if rule_type == RuleType.PDF:
            return extension == "pdf"
        if rule_type == RuleType.SPREADSHEET:
            return extension in {"xls", "xlsx", "csv"}
        if rule_type == RuleType.TEXT:
            return extension == "txt"
        return False

    def _rule_matches(self, document: UploadedDocument, source: str, rule: DocumentRule) -> bool:
        rule_type = str(rule.rule_type)
        if rule_type == RuleType.BANK_ACCOUNT.value:
            return self._bank_account_matches(document, rule)
        if rule_type == RuleType.PARTNER_NAME.value:
            return self._partner_name_matches(source, rule.rule_value)
        if rule_type == RuleType.MANUAL_OVERRIDE.value:
            return self._matches(source, {"rule_value": rule.rule_value}, rule.match_mode)
        if rule_type == RuleType.CNPJ.value:
            return self._matches(source, {"cnpj": rule.rule_value}, rule.match_mode)
        if rule_type == RuleType.FILENAME_TERM.value:
            return self._matches(document.original_filename, {"filename_term": rule.rule_value}, rule.match_mode)
        if rule_type in {RuleType.TEXT_TERM.value, RuleType.SPREADSHEET_TERM.value}:
            return self._matches(source, {"rule_value": rule.rule_value}, rule.match_mode)
        return self._matches(source, rule.pattern, rule.match_mode)

    def _partner_name_matches(self, text: str, partner_name: str | None) -> bool:
        if not partner_name:
            return False
        normalized_text = normalize_text(text)
        normalized_name = normalize_text(partner_name)
        if normalized_name in normalized_text:
            return True
        parts = [
            part
            for part in normalized_name.split()
            if len(part) > 2 and part not in {"de", "da", "do", "das", "dos"}
        ]
        if len(parts) >= 2:
            return parts[0] in normalized_text and parts[-1] in normalized_text
        return False

    def _bank_account_matches(self, document: UploadedDocument, rule: DocumentRule) -> bool:
        signals = extract_bank_account_signals(document.original_filename, document.extracted_text)
        agency_rule_variants = bank_number_variants(rule.agency, "agency")
        account_rule_variants = bank_number_variants(rule.account_number, "account")
        agency_doc_variants = signals.get("agency_variants") or []
        account_doc_variants = signals.get("account_number_variants") or []

        if agency_rule_variants and not set(agency_rule_variants).intersection(set(agency_doc_variants)):
            return False
        if account_rule_variants and not set(account_rule_variants).intersection(set(account_doc_variants)):
            return False
        if rule.bank_name and signals.get("bank_name"):
            if normalize_text(rule.bank_name) not in normalize_text(str(signals.get("bank_name"))):
                return False
        return bool(agency_rule_variants or account_rule_variants)

    def _matches(self, text: str, pattern: dict[str, object], match_mode: str = "contains") -> bool:
        if not pattern:
            return False

        normalized_text = normalize_text(text)
        digits_text = only_digits(text)
        checks: list[bool] = []

        for key, raw_value in pattern.items():
            value = str(raw_value or "").strip()
            if not value:
                continue
            normalized_value = normalize_text(value)
            digit_value = only_digits(value)
            key_normalized = normalize_text(key)
            mode = normalize_text(match_mode)

            if key_normalized in {"cnpj", "agencia", "conta", "account", "account number", "account_number"} and digit_value:
                checks.append(digit_value == digits_text if mode == "exact" else digit_value in digits_text)
                continue

            if key_normalized in {"banco", "bank", "instituicao"}:
                checks.append(normalized_value == normalized_text if mode == "exact" else normalized_value in normalized_text)
                continue

            checks.append(normalized_value == normalized_text if mode == "exact" else normalized_value in normalized_text)

        return bool(checks) and all(checks)
