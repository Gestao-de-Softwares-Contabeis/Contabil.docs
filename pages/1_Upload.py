from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import streamlit as st

from app.supabase_lists import collaborator_department, collaborator_names, safe_active_collaborators
from database.supabase_client import SupabaseConfigurationError
from models.document import CoreDocumentResult, CoreProcessingStatus
from parsers.document_parsers import DocumentParserService
from repositories.document_queue_repository import DocumentQueueRepository
from services.core_processor import CoreProcessor
from services.storage_service import SupabaseStorageService
from utils.structured_logging import get_logger


logger = get_logger(__name__)
ALLOWED_TYPES = ["pdf", "ofx", "xls", "xlsx", "csv", "txt"]
CHANNELS = ["Onvio", "E-mail", "WhatsApp/Messenger", "Drive do cliente", "Outros"]


def _save_temp_file(uploaded_file: object) -> tuple[Path, str, bytes]:
    temp_dir = Path(tempfile.gettempdir()) / "contabil_docs_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    original_file_name = str(uploaded_file.name)
    content = uploaded_file.getvalue()
    suffix = Path(original_file_name).suffix
    temp_path = temp_dir / f"{uuid.uuid4().hex}{suffix}"
    temp_path.write_bytes(content)
    return temp_path, original_file_name, content


def _analyze_and_upsert(
    original_file_name: str,
    content: bytes,
    sender_name: str,
    sender_department: str | None,
    origin_channel: str,
) -> tuple[bool, str]:
    result = CoreProcessor().analyze_file(
        filename=original_file_name,
        content=content,
        department=sender_department or "contabil",
    )
    _ensure_storage_upload(original_file_name, content, result)
    _, was_created = DocumentQueueRepository().upsert_document_queue(
        result=result,
        uploaded_by=sender_name,
        source_channel=origin_channel,
    )
    return was_created, result.status.value


def _ensure_storage_upload(original_file_name: str, content: bytes, result: CoreDocumentResult) -> None:
    if getattr(result, "storage_upload", None) and result.storage_upload.get("storage_path"):
        return
    uploaded = DocumentParserService().parse(original_file_name, content)
    storage_result = SupabaseStorageService().upload_and_sign(uploaded)
    result.storage_upload = storage_result.model_dump(mode="json", exclude_none=True)
    result.extracted_summary["storage_upload"] = result.storage_upload


def _show_error(message: str, exc: Exception) -> None:
    logger.exception(message, extra={"ctx_error": str(exc)})
    st.error(message)


def _ordered_collaborator_names() -> list[str]:
    return sorted(collaborator_names(collaborators), key=lambda name: name.lower())


st.title("Upload")
st.caption("Anexe os documentos e rode a analise. O envio acontece apenas na confirmacao.")

collaborators, collaborators_error = safe_active_collaborators()
collaborator_options = _ordered_collaborator_names()

with st.form("upload_form", clear_on_submit=False):
    if collaborators_error:
        st.warning("Nao foi possivel carregar colaboradores do Supabase.")

    top_col1, top_col2 = st.columns(2)
    with top_col1:
        sender_name = st.selectbox(
            "Quem enviou",
            collaborator_options,
            disabled=not collaborator_options,
        )
        sender_department = collaborator_department(collaborators, sender_name) if sender_name else None
    with top_col2:
        channel = st.selectbox("Canal de origem", CHANNELS)

    other_channel = st.text_input("Especificar origem") if channel == "Outros" else ""
    uploaded_files = st.file_uploader("Arquivos", type=ALLOWED_TYPES, accept_multiple_files=True)

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
        status_counts: dict[str, int] = {}
        with st.spinner("Analisando documentos..."):
            for index, uploaded_file in enumerate(uploaded_files, start=1):
                try:
                    _, original_file_name, content = _save_temp_file(uploaded_file)
                    was_created, status = _analyze_and_upsert(
                        original_file_name,
                        content,
                        sender_name,
                        sender_department,
                        origin_channel,
                    )
                    status_counts[status] = status_counts.get(status, 0) + 1
                    if was_created:
                        created += 1
                    else:
                        updated += 1
                except SupabaseConfigurationError as exc:
                    errors += 1
                    _show_error("Supabase nao esta configurado para analisar documentos.", exc)
                except Exception as exc:
                    errors += 1
                    _show_error(f"Nao foi possivel analisar {uploaded_file.name}.", exc)
                progress.progress(index / len(uploaded_files))

        total_processed = created + updated
        if total_processed:
            ready = status_counts.get(CoreProcessingStatus.READY_TO_SEND.value, 0)
            review = status_counts.get(CoreProcessingStatus.REVIEW.value, 0)
            identification_error = status_counts.get(CoreProcessingStatus.IDENTIFICATION_ERROR.value, 0)
            metric_cols = st.columns(4)
            metric_cols[0].metric("Analisados", total_processed)
            metric_cols[1].metric("Prontos", ready)
            metric_cols[2].metric("Revisar", review)
            metric_cols[3].metric("Erro", identification_error + errors)
            st.success(
                f"Analise concluida: {created} novo(s), {updated} atualizado(s) por hash."
            )
            st.page_link("pages/2_Documentos_a_Verificar.py", label="Ir para Documentos a verificar")
        if errors:
            st.warning(f"{errors} arquivo(s) com erro na analise.")

st.divider()
st.subheader("Fila operacional")
try:
    queue_count = len(DocumentQueueRepository().list_pending_documents(limit=1000))
    st.write(f"{queue_count} documento(s) pendente(s) em document_queue.")
except Exception as exc:
    logger.exception("Nao foi possivel consultar document_queue", extra={"ctx_error": str(exc)})
    st.warning("Nao foi possivel consultar a fila agora.")
