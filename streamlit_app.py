from __future__ import annotations

import streamlit as st

from app.dataframes import document_rows
from app.settings import load_settings
from app.supabase_lists import collaborator_department, collaborator_names, safe_active_collaborators
from database.supabase_client import SupabaseConfigurationError
from models.document import ProcessingStatus
from services.connection_test_service import SupabaseConnectionTestService
from services.document_processing_service import DocumentProcessingService
from services.history_service import HistoryService
from utils.structured_logging import get_logger


logger = get_logger(__name__)


st.set_page_config(page_title="Catalogacao Documental", page_icon="D", layout="wide")

settings = load_settings()
collaborators, collaborators_error = safe_active_collaborators()
collaborator_options = collaborator_names(collaborators)


def show_error(message: str, exc: Exception) -> None:
    logger.exception(message)
    st.error(f"{message}: {exc}")


st.title("Catalogacao e roteamento de documentos contabeis")

with st.expander("Teste de conexao Supabase", expanded=False):
    if st.button("Testar conexao"):
        try:
            result = SupabaseConnectionTestService().test_connection()
            if result.ok:
                st.success("Conexao OK")
            else:
                st.error(result.message)
            st.write(
                {
                    "clientes": result.clients_count,
                    "regras": result.rules_count,
                    "rotas": result.routes_count,
                    "colaboradores": result.collaborators_count,
                }
            )
        except Exception as exc:
            show_error("Falha ao testar conexao", exc)

with st.sidebar:
    st.subheader("Operacao")
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
    st.caption("MVP local: n8n e OneDrive ainda nao conectados.")
    if settings.supabase_is_configured:
        st.success("Supabase configurado")
    else:
        st.error("Supabase nao configurado no .env")
st.header("Upload")

with st.form("upload_form", clear_on_submit=False):
    if collaborator_options:
        sender_name = st.selectbox("Quem enviou", collaborator_options)
        sender_department = collaborator_department(collaborators, sender_name)
        st.caption(f"Setor do envio: {sender_department or '-'}")
    else:
        sender_name = ""
        sender_department = None
        st.warning("Sem colaboradores ativos carregados do Supabase.")
    origin_channel = st.selectbox("Canal de origem", settings.origin_channels)

    pdf_files = st.file_uploader(
        "PDF",
        type=["pdf"],
        accept_multiple_files=True,
        key="pdf_files",
    )
    ofx_files = st.file_uploader(
        "OFX",
        type=["ofx"],
        accept_multiple_files=True,
        key="ofx_files",
    )
    spreadsheet_files = st.file_uploader(
        "Planilhas",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
        key="spreadsheet_files",
    )
    submitted = st.form_submit_button(
        "Processar documentos",
        type="primary",
        disabled=not collaborator_options,
    )

if submitted:
    upload_batches = [
        ("pdf", pdf_files or []),
        ("ofx", ofx_files or []),
        ("planilha", spreadsheet_files or []),
    ]
    selected_files = [
        (upload_group, uploaded_file)
        for upload_group, uploaded_files in upload_batches
        for uploaded_file in uploaded_files
    ]

    if not selected_files:
        st.warning("Selecione ao menos um arquivo.")
    else:
        try:
            service = DocumentProcessingService()
            results = []
            for upload_group, uploaded_file in selected_files:
                result = service.process_file(
                    filename=uploaded_file.name,
                    content=uploaded_file.getvalue(),
                    sender_name=sender_name,
                    sender_department=sender_department,
                    origin_channel=origin_channel,
                    upload_group=upload_group,
                )
                results.append(result)
            st.success(f"{len(results)} arquivo(s) processado(s).")
            for result in results:
                status = result.identification.status.value
                label = f"{result.uploaded.original_filename} | {status} | score {result.identification.score}"
                if status == ProcessingStatus.READY_TO_SEND.value:
                    st.success(label)
                else:
                    st.warning(f"{label} - {result.identification.observation}")
        except SupabaseConfigurationError as exc:
            st.error(str(exc))
        except Exception as exc:
            show_error("Falha ao processar upload", exc)

st.divider()
st.header("Documentos")

try:
    history_service = HistoryService()
    current_documents = history_service.list_current_documents()
    rows = document_rows(current_documents)
    st.dataframe(rows, use_container_width=True, hide_index=True)

    if current_documents:
        options = {
            f"{item.original_filename or 'sem nome'} | {item.status} | {(item.file_hash or '')[:10]}": item
            for item in current_documents
        }
        selected_label = st.selectbox("Documento para acao", list(options.keys()))
        selected_document = options[selected_label]

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Confirmar envio", type="primary"):
                try:
                    DocumentProcessingService().confirm_dispatch(
                        file_hash=selected_document.file_hash or "",
                        user_name=current_user,
                        user_department=current_user_department,
                    )
                    st.success("Envio confirmado no MVP local.")
                    st.rerun()
                except Exception as exc:
                    show_error("Envio bloqueado", exc)
        with col2:
            if st.button("Parametrizar documento"):
                try:
                    DocumentProcessingService().request_parametrization(
                        file_hash=selected_document.file_hash or "",
                        user_name=current_user,
                        user_department=current_user_department,
                    )
                    st.info("Documento marcado para parametrizacao. Abra a tela Parametrizacao.")
                except Exception as exc:
                    show_error("Falha ao solicitar parametrizacao", exc)
    else:
        st.info("Nenhum documento processado ainda.")
except SupabaseConfigurationError as exc:
    st.warning(str(exc))
except Exception as exc:
    show_error("Falha ao carregar documentos", exc)
