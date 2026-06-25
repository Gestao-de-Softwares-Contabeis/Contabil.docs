from __future__ import annotations

from models.document import DocumentLogEntry, ProcessingStatus
from models.rule import DocumentRule, RuleType
from repositories.client_repository import ClientRepository
from repositories.log_repository import ProcessingLogRepository
from repositories.routing_repository import RoutingRepository
from repositories.rule_repository import RuleRepository
from utils.normalization import only_digits


class ParametrizationService:
    def __init__(
        self,
        client_repository: ClientRepository | None = None,
        rule_repository: RuleRepository | None = None,
        routing_repository: RoutingRepository | None = None,
        log_repository: ProcessingLogRepository | None = None,
    ) -> None:
        self.client_repository = client_repository or ClientRepository()
        self.rule_repository = rule_repository or RuleRepository()
        self.routing_repository = routing_repository or RoutingRepository()
        self.log_repository = log_repository or ProcessingLogRepository()

    def list_clients(self) -> list[tuple[str, str]]:
        return [
            (client.client_code or "", f"{client.client_code} - {client.name}")
            for client in self.client_repository.list_active()
            if client.client_code
        ]

    def create_client(
        self,
        name: str,
        cnpj: str | None,
        aliases_text: str,
        bank_accounts_text: str,
        user_name: str,
        user_department: str | None = None,
    ) -> None:
        aliases = [item.strip() for item in aliases_text.splitlines() if item.strip()]
        bank_accounts = self._parse_bank_accounts(bank_accounts_text)
        client = self.client_repository.create_client(name, cnpj, aliases, bank_accounts)
        self.log_repository.insert(
            DocumentLogEntry(
                user_name=user_name,
                user_department=user_department,
                action="CLIENTE_CRIADO",
                client_id=client.id,
                client_name=client.name,
                status=ProcessingStatus.RECEIVED.value,
                observation="Cliente criado para parametrizacao.",
            )
        )

    def create_rule(
        self,
        client_code: str,
        rule_type: RuleType | str,
        document_type: str,
        institution: str | None,
        pattern: dict[str, str],
        destination_folder: str,
        created_by: str,
        created_by_department: str | None = None,
        file_extension: str | None = None,
        notes: str | None = None,
        is_active: bool = True,
    ) -> DocumentRule:
        rule_type_value = rule_type.value if isinstance(rule_type, RuleType) else str(rule_type)
        rule = DocumentRule(
            client_code=client_code,
            file_extension=file_extension.lower().lstrip(".") if file_extension else None,
            rule_type=rule_type_value,
            document_type=document_type,
            rule_name=pattern.get("rule_name") or None,
            rule_value=pattern.get("rule_value") or None,
            bank_name=pattern.get("bank_name") or institution or None,
            agency=pattern.get("agency") or None,
            account_number=pattern.get("account_number") or None,
            sheet_name=pattern.get("sheet_name") or None,
            column_name=pattern.get("column_name") or None,
            row_number=int(pattern["row_number"]) if pattern.get("row_number", "").isdigit() else None,
            match_mode=pattern.get("match_mode") or "contains",
            is_active=is_active,
            created_by=created_by,
            notes=notes or None,
        )
        saved_rule = self.rule_repository.create(rule)
        self.log_repository.insert(
            DocumentLogEntry(
                user_name=created_by,
                user_department=created_by_department,
                action="REGRA_CRIADA",
                client_id=client_code,
                document_type=document_type,
                institution=institution,
                status=ProcessingStatus.WAITING_RULES.value,
                destination_folder=destination_folder or None,
                observation=f"Regra criada: {saved_rule.id}",
                metadata={
                    "rule_type": rule_type_value,
                    "pattern": pattern,
                    "file_extension": file_extension,
                    "notes": notes,
                    "is_active": is_active,
                },
            )
        )
        return saved_rule

    def toggle_rule(
        self,
        rule_id: str,
        active: bool,
        user_name: str,
        user_department: str | None = None,
    ) -> None:
        self.rule_repository.set_active(rule_id, active)
        self.log_repository.insert(
            DocumentLogEntry(
                user_name=user_name,
                user_department=user_department,
                action="REGRA_ATIVADA" if active else "REGRA_INATIVADA",
                status=ProcessingStatus.WAITING_RULES.value,
                observation=f"Regra {rule_id} alterada para active={active}.",
                metadata={"rule_id": rule_id, "active": active},
            )
        )

    def list_rules(self) -> list[DocumentRule]:
        return self.rule_repository.list_all(limit=2000)

    def _parse_bank_accounts(self, text: str) -> list[dict[str, str]]:
        accounts: list[dict[str, str]] = []
        for line in text.splitlines():
            parts = [part.strip() for part in line.split(";") if part.strip()]
            if len(parts) == 3:
                bank, agency, account = parts
            elif len(parts) == 2:
                bank, agency, account = "", parts[0], parts[1]
            elif len(parts) == 1:
                bank, agency, account = "", "", parts[0]
            else:
                continue
            if only_digits(account):
                accounts.append({"bank": bank, "agency": agency, "account": account})
        return accounts
