from __future__ import annotations

import streamlit as st

from app.dataframes import rule_rows
from app.settings import load_settings
from app.supabase_lists import collaborator_department, collaborator_names, safe_active_collaborators
from database.supabase_client import SupabaseConfigurationError
from models.document import DocumentType
from models.rule import RuleType
from services.parametrization_service import ParametrizationService
from utils.structured_logging import get_logger


logger = get_logger(__name__)
settings = load_settings()
collaborators, collaborators_error = safe_active_collaborators()
collaborator_options = collaborator_names(collaborators)

st.set_page_config(page_title="Parametrizacao", page_icon="P", layout="wide")
st.title("Parametrizacao")


def show_error(message: str, exc: Exception) -> None:
    logger.exception(message)
    st.error(f"{message}: {exc}")


with st.sidebar:
    if collaborators_error:
        st.warning("Nao foi possivel carregar colaboradores do Supabase.")
    if collaborator_options:
        current_user = st.selectbox("Usuario atual", collaborator_options)
        current_user_department = collaborator_department(collaborators, current_user)
        st.caption(f"Setor: {current_user_department or '-'}")
    else:
        current_user = ""
        current_user_department = None
        st.warning("Cadastre a tabela collaborators no Supabase antes de operar.")

try:
    service = ParametrizationService()

    with st.expander("Cadastro rapido de cliente", expanded=False):
        with st.form("client_form"):
            client_name = st.text_input("Nome do cliente")
            cnpj = st.text_input("CNPJ")
            aliases = st.text_area("Aliases, um por linha")
            bank_accounts = st.text_area(
                "Contas bancarias",
                help="Uma por linha no formato banco;agencia;conta. Banco pode ficar vazio.",
            )
            save_client = st.form_submit_button("Criar cliente", disabled=not collaborator_options)
        if save_client:
            if not client_name.strip():
                st.warning("Informe o nome do cliente.")
            else:
                try:
                    service.create_client(
                        client_name,
                        cnpj,
                        aliases,
                        bank_accounts,
                        current_user,
                        current_user_department,
                    )
                    st.success("Cliente criado.")
                    st.rerun()
                except Exception as exc:
                    show_error("Falha ao criar cliente", exc)

    clients = service.list_clients()
    client_options = {label: client_code for client_code, label in clients}

    st.header("Nova regra")
    if not clients:
        st.warning("Cadastre ou importe clientes antes de criar regras.")
    else:
        with st.form("rule_form"):
            selected_client_name = st.selectbox("Cliente", list(client_options.keys()))
            rule_type = st.selectbox(
                "Tipo de regra",
                [
                    RuleType.BANK_ACCOUNT,
                    RuleType.PARTNER_NAME,
                    RuleType.TEXT_TERM,
                    RuleType.SPREADSHEET_TERM,
                    RuleType.CNPJ,
                    RuleType.FILENAME_TERM,
                    RuleType.OFX,
                    RuleType.PDF,
                    RuleType.SPREADSHEET,
                    RuleType.TEXT,
                ],
                format_func=lambda item: item.value,
            )
            document_type = st.selectbox(
                "Tipo de documento",
                list(DocumentType),
                format_func=lambda item: item.value,
            )
            institution = st.text_input("Instituicao")
            destination_folder = st.text_input("Pasta destino")

            pattern: dict[str, str] = {}
            pattern["match_mode"] = st.selectbox("Modo de comparacao", ["contains", "exact"])
            if rule_type == RuleType.BANK_ACCOUNT:
                pattern["bank_name"] = st.text_input("Banco")
                pattern["agency"] = st.text_input("Agencia")
                pattern["account_number"] = st.text_input("Conta")
                pattern["rule_value"] = "/".join(
                    item
                    for item in [
                        pattern.get("agency", "").strip(),
                        pattern.get("account_number", "").strip(),
                    ]
                    if item
                )
            elif rule_type == RuleType.PARTNER_NAME:
                pattern["rule_value"] = st.text_input("Nome do socio")
            elif rule_type == RuleType.CNPJ:
                pattern["rule_value"] = st.text_input("CNPJ")
            elif rule_type == RuleType.FILENAME_TERM:
                pattern["rule_value"] = st.text_input("Termo no nome do arquivo")
            elif rule_type in {RuleType.TEXT_TERM, RuleType.SPREADSHEET_TERM}:
                pattern["rule_value"] = st.text_input("Termo de identificacao")
            elif rule_type == RuleType.OFX:
                pattern["bank_name"] = st.text_input("Banco")
                pattern["agency"] = st.text_input("Agencia")
                pattern["account_number"] = st.text_input("Conta")
                pattern["rule_value"] = st.text_input("Termo adicional")
            elif rule_type == RuleType.PDF:
                pattern["rule_value"] = st.text_input("CNPJ, nome da empresa ou termo")
            else:
                pattern["rule_value"] = st.text_input("Termo de identificacao")

            save_rule = st.form_submit_button(
                "Criar regra",
                type="primary",
                disabled=not collaborator_options,
            )

        if save_rule:
            filled_pattern = {key: value.strip() for key, value in pattern.items() if value.strip()}
            useful_pattern = {
                key: value
                for key, value in filled_pattern.items()
                if key not in {"match_mode", "rule_name"}
            }
            if not useful_pattern:
                st.warning("Informe ao menos um criterio de identificacao.")
            else:
                try:
                    service.create_rule(
                        client_code=client_options[selected_client_name],
                        rule_type=rule_type,
                        document_type=document_type.value,
                        institution=institution.strip() or None,
                        pattern=filled_pattern,
                        destination_folder=destination_folder.strip(),
                        created_by=current_user,
                        created_by_department=current_user_department,
                    )
                    st.success("Regra criada.")
                    st.rerun()
                except Exception as exc:
                    show_error("Falha ao criar regra", exc)

    st.divider()
    st.header("Regras cadastradas")
    rules = service.list_rules()
    st.dataframe(rule_rows(rules), use_container_width=True, hide_index=True)

    if rules:
        rule_options = {
            f"{rule.client_name or rule.client_code or rule.client_id} | {getattr(rule.rule_type, 'value', rule.rule_type)} | {rule.id}": rule
            for rule in rules
        }
        selected_rule_label = st.selectbox("Regra para ativar/inativar", list(rule_options.keys()))
        selected_rule = rule_options[selected_rule_label]
        next_active = not selected_rule.active
        action_label = "Ativar regra" if next_active else "Inativar regra"
        if st.button(action_label, disabled=not collaborator_options):
            try:
                service.toggle_rule(
                    selected_rule.id or "",
                    next_active,
                    current_user,
                    current_user_department,
                )
                st.success("Regra atualizada.")
                st.rerun()
            except Exception as exc:
                show_error("Falha ao atualizar regra", exc)
except SupabaseConfigurationError as exc:
    st.warning(str(exc))
except Exception as exc:
    show_error("Falha ao carregar parametrizacao", exc)
