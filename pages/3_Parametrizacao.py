from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.session_state import update_document_result
from models.document import DocumentType
from models.document_queue import DocumentQueueItem
from models.rule import RuleType
from repositories.document_queue_repository import DocumentQueueRepository
from services.core_processor import CoreProcessor
from services.parametrization_service import ParametrizationService
from services.storage_service import SupabaseStorageService
from utils.structured_logging import get_logger
from utils.ui_formatting import client_code_sort_key, format_datetime


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


def _selected_queue_item() -> DocumentQueueItem | None:
    queue_id = st.session_state.get("parametrization_queue_id")
    if not queue_id:
        return None
    return DocumentQueueRepository().get_by_id(str(queue_id))


def _show_error(message: str, exc: Exception) -> None:
    logger.exception(message, extra={"ctx_error": str(exc)})
    st.error(message)


def _ordered_client_options(clients: list[tuple[str, str]]) -> dict[str, str]:
    return {label: code for code, label in sorted(clients, key=lambda item: client_code_sort_key(item[0]))}


def _document_text_source(result: object | None) -> str:
    if result is None:
        return ""
    summary = getattr(result, "extracted_summary", {}) or {}
    parts = [
        getattr(result, "original_file_name", ""),
        getattr(result, "new_file_name", ""),
        getattr(result, "detected_client_cnpj", ""),
        getattr(result, "institution", ""),
        getattr(result, "review_reason", ""),
        summary.get("text_preview") if isinstance(summary, dict) else "",
        " ".join(summary.get("terms_candidates") or []) if isinstance(summary, dict) else "",
    ]
    return " ".join(str(part).lower() for part in parts if part)


def _show_document_preview(result: object | None) -> None:
    if result is None:
        st.info("Selecione um documento em Documentos a verificar para preencher a parametrizacao automaticamente.")
        return

    summary = getattr(result, "extracted_summary", {}) or {}
    with st.expander("Preview do documento", expanded=True):
        st.write(f"Arquivo: {getattr(result, 'original_file_name', '')}")
        st.write(f"Status: {getattr(getattr(result, 'status', None), 'value', '')}")
        st.write(f"Cliente detectado: {getattr(result, 'detected_client_code', '') or '-'}")
        st.write(f"Tipo: {getattr(result, 'document_type', '') or '-'}")
        st.write(f"Instituicao: {getattr(result, 'institution', '') or '-'}")
        st.write(f"Agencia/conta: {getattr(result, 'extracted_agency', '') or '-'} / {getattr(result, 'extracted_account_number', '') or '-'}")
        text_preview = summary.get("text_preview") if isinstance(summary, dict) else None
        if text_preview:
            st.text_area("Texto extraido", value=str(text_preview)[:8000], height=180, disabled=True)


def _rule_help(rule_type: str) -> str:
    helps = {
        RuleType.BANK_ACCOUNT.value: "Use quando agencia/conta identificam o cliente.",
        RuleType.PARTNER_NAME.value: "Use quando o nome do socio aparece no documento.",
        RuleType.TEXT_TERM.value: "Use quando um termo do documento identifica o cliente.",
        RuleType.SPREADSHEET_TERM.value: "Use para termo em planilhas.",
        RuleType.CNPJ.value: "Use quando o CNPJ do cliente aparece no documento.",
        RuleType.FILENAME_TERM.value: "Use quando o nome do arquivo identifica o cliente.",
    }
    return helps.get(rule_type, "")


def _test_rule_against_document(rule_type: str, pattern: dict[str, str], result: object | None) -> tuple[bool, str]:
    if result is None:
        return False, "Nenhum documento selecionado para teste."
    text_source = _document_text_source(result)
    if rule_type == RuleType.BANK_ACCOUNT.value:
        agency = pattern.get("agency", "").strip()
        account = pattern.get("account_number", "").strip()
        result_agency = str(getattr(result, "extracted_agency", "") or "")
        result_account = str(getattr(result, "extracted_account_number", "") or "")
        hit = bool((not agency or agency == result_agency) and (not account or account == result_account))
        return hit, "Agencia/conta conferem." if hit else "Agencia/conta nao bateram neste documento."
    value = (pattern.get("rule_value") or "").strip().lower()
    if not value:
        return False, "Informe o valor da regra antes de testar."
    hit = value in text_source
    return hit, "Regra bateu neste documento." if hit else "Regra nao bateu neste documento."


st.title("Parametrizacao")
st.caption("Crie regras quando a identificacao automatica precisar de ajuda.")

service = ParametrizationService()
selected_queue_item = _selected_queue_item()
selected_doc = _selected_document()
selected_result = selected_queue_item.to_core_result() if selected_queue_item else selected_doc["result"] if selected_doc else None

if selected_result:
    result = selected_result
    st.info(f"Documento selecionado: {result.original_file_name} | status {result.status.value}")

_show_document_preview(selected_result)

clients = service.list_clients()
client_options = _ordered_client_options(clients)

if not client_options:
    st.warning("Nenhum cliente ativo encontrado no Supabase.")
    st.stop()

default_extension = selected_result.extension if selected_result else ""
default_document_type = selected_result.document_type if selected_result else DocumentType.OTHER.value

with st.form("rule_form"):
    selected_client_label = st.selectbox("Cliente", list(client_options.keys()))
    rule_type = st.selectbox("Tipo de regra", RULE_TYPES)
    if _rule_help(rule_type):
        st.caption(_rule_help(rule_type))

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
        institution = st.text_input("Banco", value=selected_result.extracted_bank_name or "" if selected_result else "")
        pattern["bank_name"] = institution
        pattern["agency"] = st.text_input("Agencia", value=selected_result.extracted_agency or "" if selected_result else "")
        pattern["account_number"] = st.text_input(
            "Conta",
            value=selected_result.extracted_account_number or "" if selected_result else "",
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
        test_rule = st.form_submit_button("Testar regra")
    with col2:
        save_rule = st.form_submit_button("Salvar regra", type="primary")
    save_and_reprocess = st.form_submit_button("Salvar e reprocessar")

if test_rule:
    filled_pattern = {key: value.strip() for key, value in pattern.items() if str(value).strip()}
    hit, message = _test_rule_against_document(rule_type, filled_pattern, selected_result)
    if hit:
        st.success(message)
    else:
        st.warning(message)

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
                if not selected_doc and not selected_queue_item:
                    st.warning("Nenhum documento selecionado para reprocessar.")
                elif selected_queue_item:
                    if not selected_queue_item.storage_path:
                        st.warning("Documento selecionado nao possui storage_path para reprocessamento.")
                    else:
                        storage_service = SupabaseStorageService()
                        content = storage_service.download_object(selected_queue_item.storage_path)
                        filename = selected_queue_item.original_file_name or selected_queue_item.storage_path.rsplit("/", 1)[-1]
                        new_result = CoreProcessor().analyze_file(filename, content, department="contabil")
                        DocumentQueueRepository().upsert_document_queue(
                            result=new_result,
                            uploaded_by=selected_queue_item.uploaded_by,
                            source_channel=selected_queue_item.source_channel,
                        )
                        if new_result.status.value == "PRONTO_ENVIO":
                            st.success("Regra salva e documento reprocessado com sucesso")
                        else:
                            st.warning("Regra salva, mas documento ainda precisa de revisão")
                        st.page_link("pages/2_Documentos_a_Verificar.py", label="Voltar para documentos")
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
            _show_error("Nao foi possivel salvar a regra.", exc)

st.divider()
st.subheader("Regras cadastradas")
try:
    rules = [rule for rule in service.list_rules() if rule.client_code == client_options.get(selected_client_label)]
    st.dataframe(
        [
            {
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
                "criado em": format_datetime(rule.created_at),
                "ultima utilizacao": format_datetime(rule.last_used_at),
                "acertos": rule.hit_count,
            }
            for rule in rules
        ],
        use_container_width=True,
        hide_index=True,
    )
except Exception as exc:
    _show_error("Nao foi possivel carregar as regras.", exc)
