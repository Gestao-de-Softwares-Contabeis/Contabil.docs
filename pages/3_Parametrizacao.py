from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.session_state import update_document_result
from models.document import DocumentType
from models.rule import RuleType
from services.core_processor import CoreProcessor
from services.parametrization_service import ParametrizationService
from utils.structured_logging import get_logger


logger = get_logger(__name__)
RULE_TYPES = [
    RuleType.BANK_ACCOUNT.value,
    RuleType.PARTNER_NAME.value,
    RuleType.TEXT_TERM.value,
    RuleType.SPREADSHEET_TERM.value,
    RuleType.CNPJ.value,
    RuleType.FILENAME_TERM.value,
]


def _selected_document() -> dict[str, object] | None:
    doc_id = st.session_state.get("parametrization_document_id")
    for item in st.session_state.get("analysis_results", []):
        if item.get("id") == doc_id:
            return item
    return None


def _show_error(message: str, exc: Exception) -> None:
    logger.exception(message)
    st.error(f"{message}: {exc}")


st.title("Parametrizacao")
st.caption("Crie regras vinculadas a client_code. Regras nunca sao apagadas; apenas ativadas ou inativadas.")

service = ParametrizationService()
selected_doc = _selected_document()

if selected_doc:
    result = selected_doc["result"]
    st.info(f"Documento selecionado: {result.original_file_name} | status {result.status.value}")

clients = service.list_clients()
client_options = {label: code for code, label in clients}

if not client_options:
    st.warning("Nenhum cliente ativo encontrado no Supabase.")
    st.stop()

default_extension = selected_doc["result"].extension if selected_doc else ""
default_document_type = selected_doc["result"].document_type if selected_doc else DocumentType.OTHER.value

with st.form("rule_form"):
    selected_client_label = st.selectbox("Cliente", list(client_options.keys()))
    rule_type = st.selectbox("Tipo de regra", RULE_TYPES)

    file_extension = st.text_input("Extensao do arquivo", value=default_extension)
    document_type = st.selectbox(
        "Tipo documento",
        [item.value for item in DocumentType],
        index=[item.value for item in DocumentType].index(default_document_type)
        if default_document_type in [item.value for item in DocumentType]
        else 0,
    )
    notes = st.text_area("Observacoes")
    is_active = st.checkbox("Regra ativa", value=True)

    pattern: dict[str, str] = {"match_mode": st.selectbox("Modo de comparacao", ["contains", "exact"])}
    institution = ""

    if rule_type == RuleType.BANK_ACCOUNT.value:
        institution = st.text_input("Banco", value=selected_doc["result"].extracted_bank_name or "" if selected_doc else "")
        pattern["bank_name"] = institution
        pattern["agency"] = st.text_input("Agencia", value=selected_doc["result"].extracted_agency or "" if selected_doc else "")
        pattern["account_number"] = st.text_input(
            "Conta",
            value=selected_doc["result"].extracted_account_number or "" if selected_doc else "",
        )
    elif rule_type == RuleType.PARTNER_NAME.value:
        pattern["rule_value"] = st.text_input("Nome do socio")
    elif rule_type in {RuleType.TEXT_TERM.value, RuleType.FILENAME_TERM.value}:
        pattern["rule_value"] = st.text_input("Termo")
    elif rule_type == RuleType.SPREADSHEET_TERM.value:
        pattern["rule_value"] = st.text_input("Termo")
        pattern["sheet_name"] = st.text_input("sheet_name")
        pattern["column_name"] = st.text_input("column_name")
        pattern["row_number"] = st.text_input("row_number")
    elif rule_type == RuleType.CNPJ.value:
        pattern["rule_value"] = st.text_input("CNPJ")

    col1, col2 = st.columns(2)
    with col1:
        save_rule = st.form_submit_button("Salvar regra", type="primary")
    with col2:
        save_and_reprocess = st.form_submit_button("Salvar regra e reprocessar documento")

if save_rule or save_and_reprocess:
    filled_pattern = {key: value.strip() for key, value in pattern.items() if str(value).strip()}
    useful_pattern = {key: value for key, value in filled_pattern.items() if key != "match_mode"}
    if not useful_pattern:
        st.warning("Informe ao menos um criterio da regra.")
    else:
        try:
            service.create_rule(
                client_code=client_options[selected_client_label],
                rule_type=rule_type,
                document_type=document_type,
                institution=institution.strip() or None,
                pattern=filled_pattern,
                destination_folder="",
                created_by="streamlit",
                file_extension=file_extension.strip() or None,
                notes=notes.strip() or None,
                is_active=is_active,
            )
            st.success("Regra salva.")

            if save_and_reprocess:
                if not selected_doc:
                    st.warning("Nenhum documento selecionado para reprocessar.")
                else:
                    temp_path = Path(selected_doc["temp_path"])
                    new_result = CoreProcessor().analyze_path(
                        temp_path,
                        department=selected_doc.get("sender_department") or "contabil",
                    )
                    update_document_result(str(selected_doc["id"]), new_result)
                    if new_result.status.value == "PRONTO_ENVIO":
                        st.success("Regra salva e documento reprocessado com sucesso")
                    else:
                        st.warning("Regra salva, mas documento ainda precisa de revisão")
                    st.page_link("pages/2_Documentos_a_Verificar.py", label="Voltar para documentos")
        except Exception as exc:
            _show_error("Falha ao salvar regra", exc)

st.divider()
st.subheader("Regras cadastradas")
try:
    rules = service.list_rules()
    st.dataframe(
        [
            {
                "id": rule.id,
                "cliente": rule.client_code,
                "tipo regra": rule.rule_type,
                "extensao": rule.file_extension,
                "tipo documento": rule.document_type,
                "valor": rule.rule_value,
                "banco": rule.bank_name,
                "agencia": rule.agency,
                "conta": rule.account_number,
                "ativa": rule.is_active,
                "criado por": rule.created_by,
                "criado em": rule.created_at,
                "ultima utilizacao": rule.last_used_at,
                "acertos": rule.hit_count,
            }
            for rule in rules
        ],
        use_container_width=True,
        hide_index=True,
    )
except Exception as exc:
    _show_error("Falha ao carregar regras", exc)
