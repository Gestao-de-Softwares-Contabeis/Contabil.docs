from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import streamlit as st

from app.session_state import ensure_document_state, get_documents, upsert_document
from app.supabase_lists import collaborator_department, collaborator_names, safe_active_collaborators
from database.supabase_client import SupabaseConfigurationError
from services.core_processor import CoreProcessor
from utils.structured_logging import get_logger


logger = get_logger(__name__)
ALLOWED_TYPES = ["pdf", "ofx", "xls", "xlsx", "csv", "txt"]
CHANNELS = ["Onvio", "E-mail", "WhatsApp/Messenger", "Drive do cliente", "Outros"]


def _save_temp_file(uploaded_file: object) -> Path:
    temp_dir = Path(tempfile.gettempdir()) / "contabil_docs_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(uploaded_file.name).suffix
    temp_path = temp_dir / f"{uuid.uuid4().hex}{suffix}"
    temp_path.write_bytes(uploaded_file.getvalue())
    return temp_path


def _analyze_and_upsert(
    temp_path: Path,
    sender_name: str,
    sender_department: str | None,
    origin_channel: str,
) -> bool:
    result = CoreProcessor().analyze_path(temp_path, department=sender_department or "contabil")
    return upsert_document(
        temp_path=temp_path,
        sender_name=sender_name,
        sender_department=sender_department,
        origin_channel=origin_channel,
        result=result,
    )


def _show_error(message: str, exc: Exception) -> None:
    logger.exception(message)
    st.error(f"{message}: {exc}")


ensure_document_state()

st.title("Upload de documentos")
st.caption("Anexe os arquivos e rode somente a analise. O envio ao n8n acontece apenas na confirmacao.")

collaborators, collaborators_error = safe_active_collaborators()
collaborator_options = collaborator_names(collaborators)

with st.form("upload_form", clear_on_submit=False):
    if collaborators_error:
        st.warning("Nao foi possivel carregar colaboradores do Supabase.")

    sender_name = st.selectbox(
        "Quem esta enviando",
        collaborator_options,
        disabled=not collaborator_options,
    )
    sender_department = collaborator_department(collaborators, sender_name) if sender_name else None

    channel = st.selectbox("Canal de origem", CHANNELS)
    other_channel = ""
    if channel == "Outros":
        other_channel = st.text_input("Especificar origem")

    uploaded_files = st.file_uploader(
        "Arquivos",
        type=ALLOWED_TYPES,
        accept_multiple_files=True,
    )

    submitted = st.form_submit_button(
        "Analisar documentos",
        type="primary",
        disabled=not collaborator_options,
    )

if submitted:
    origin_channel = other_channel.strip() if channel == "Outros" and other_channel.strip() else channel
    if not uploaded_files:
        st.warning("Selecione ao menos um arquivo.")
    elif channel == "Outros" and not other_channel.strip():
        st.warning("Informe a origem quando o canal for Outros.")
    else:
        progress = st.progress(0)
        created = 0
        updated = 0
        errors = 0
        for index, uploaded_file in enumerate(uploaded_files, start=1):
            try:
                temp_path = _save_temp_file(uploaded_file)
                was_created = _analyze_and_upsert(temp_path, sender_name, sender_department, origin_channel)
                if was_created:
                    created += 1
                else:
                    updated += 1
            except SupabaseConfigurationError as exc:
                errors += 1
                st.error(str(exc))
            except Exception as exc:
                errors += 1
                _show_error(f"Falha ao analisar {uploaded_file.name}", exc)
            progress.progress(index / len(uploaded_files))

        total_processed = created + updated
        if total_processed:
            st.success(
                f"Analise concluida: {created} novo(s), {updated} atualizado(s) por hash."
            )
            st.page_link("pages/2_Documentos_a_Verificar.py", label="Ir para Documentos a verificar")
        if errors:
            st.warning(f"{errors} arquivo(s) com erro na analise.")

st.divider()
st.subheader("Resultados nesta sessao")
st.write(f"{len(get_documents())} documento(s) em verificacao.")
