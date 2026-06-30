from __future__ import annotations

from typing import Any

import streamlit as st

from app.settings import get_n8n_webhook_debug_info
from models.document import CoreDocumentResult, CoreProcessingStatus
from models.document_queue import DocumentQueueItem, QUEUE_SEND_ERROR_STATUS, QUEUE_SENDING_STATUS
from repositories.document_queue_repository import DocumentQueueRepository
from services.checklist_service import ChecklistService
from services.core_processor import CoreProcessor
from services.storage_service import SupabaseStorageService
from utils.structured_logging import get_logger
from utils.ui_formatting import format_competence, format_score, status_sort_key


logger = get_logger(__name__)

READY_STATUS = CoreProcessingStatus.READY_TO_SEND.value
REVIEW_STATUSES = {
    CoreProcessingStatus.REVIEW.value,
    CoreProcessingStatus.IDENTIFICATION_ERROR.value,
    QUEUE_SEND_ERROR_STATUS,
}

DISPLAY_COLUMNS = [
    "selecionar",
    "score",
    "status",
    "motivo_revisao",
    "arquivo",
    "cliente",
    "cnpj",
    "competencia",
    "tipo",
    "extensao",
    "instituicao",
    "destino",
    "novo_nome",
]
ACTION_MESSAGES_KEY = "document_action_messages"


def _document_sort_key(item: DocumentQueueItem) -> tuple[int, float, str]:
    score = float(item.confidence or 0)
    return (*status_sort_key(item.status), score, str(item.original_file_name or ""))


def _result_rows(documents: list[DocumentQueueItem]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in documents:
        rows.append(
            {
                "selecionar": False,
                "score": format_score(item.confidence),
                "status": item.status,
                "motivo_revisao": item.review_reason,
                "arquivo": item.original_file_name,
                "cliente": item.client_name,
                "cnpj": item.client_cnpj,
                "competencia": format_competence(item.competence),
                "tipo": item.document_type,
                "extensao": item.extension,
                "instituicao": item.institution,
                "destino": item.destination_path_readable,
                "novo_nome": item.new_file_name,
            }
        )
    return rows


def _records_from_editor(edited_rows: object) -> list[dict[str, object]]:
    if hasattr(edited_rows, "to_dict"):
        return edited_rows.to_dict("records")  # type: ignore[no-any-return, attr-defined]
    return list(edited_rows)  # type: ignore[arg-type]


def _selected_items(edited_rows: object, documents: list[DocumentQueueItem]) -> list[DocumentQueueItem]:
    selected: list[DocumentQueueItem] = []
    for index, row in enumerate(_records_from_editor(edited_rows)):
        if row.get("selecionar") and index < len(documents):
            selected.append(documents[index])
    return selected


def _button_state(selected: list[DocumentQueueItem]) -> tuple[bool, bool, bool]:
    if not selected:
        return True, True, True

    statuses = [item.status for item in selected]
    all_ready = all(status == READY_STATUS for status in statuses)
    has_review = any(status in REVIEW_STATUSES for status in statuses)
    return not all_ready, False, not has_review


def _file_size_from_payload(item: DocumentQueueItem) -> int:
    payload = item.payload_json or {}
    summary = payload.get("extracted_summary") if isinstance(payload.get("extracted_summary"), dict) else {}
    return int(summary.get("file_size_bytes") or 0)


def _refresh_storage_for_send(item: DocumentQueueItem) -> CoreDocumentResult:
    if not item.storage_path:
        raise ValueError("Documento sem storage_path na fila; reenvie ou reprocesse o arquivo.")

    storage_service = SupabaseStorageService()
    signed = storage_service.sign_existing_object(item.storage_path, size_bytes=_file_size_from_payload(item))
    result = item.to_core_result()
    result.storage_upload = signed.model_dump(mode="json", exclude_none=True)
    result.extracted_summary["storage_upload"] = result.storage_upload
    DocumentQueueRepository().update_storage_url(str(item.id), signed.signed_url)
    return result


def _reprocess_item(item: DocumentQueueItem) -> CoreDocumentResult:
    if not item.storage_path:
        raise ValueError("Documento sem storage_path; nao e possivel reprocessar pela fila persistente.")

    storage_service = SupabaseStorageService()
    content = storage_service.download_object(item.storage_path)
    filename = item.original_file_name or item.storage_path.rsplit("/", 1)[-1]
    return CoreProcessor().analyze_file(filename, content, department="contabil")


def _queue_message(level: str, text: str) -> dict[str, str]:
    return {"level": level, "text": text}


st.title("Documentos a verificar")
st.caption("Revise pendencias e envie somente documentos prontos.")

for message in st.session_state.pop(ACTION_MESSAGES_KEY, []):
    level = message.get("level", "info")
    text = message.get("text", "")
    if level == "success":
        st.success(text)
    elif level == "warning":
        st.warning(text)
    elif level == "error":
        st.error(text)
    else:
        st.info(text)

repository = DocumentQueueRepository()
try:
    documents = sorted(repository.list_pending_documents(), key=_document_sort_key)
except Exception as exc:
    logger.exception("Falha ao carregar document_queue", extra={"ctx_error": str(exc)})
    st.error("Nao foi possivel carregar os documentos pendentes.")
    st.stop()

if not documents:
    st.info("Nenhum documento pendente na document_queue.")
    st.page_link("pages/1_Upload.py", label="Ir para Upload")
    st.stop()

status_totals = {
    "Prontos": sum(1 for item in documents if item.status == READY_STATUS),
    "Revisar": sum(1 for item in documents if item.status == CoreProcessingStatus.REVIEW.value),
    "Erro": sum(1 for item in documents if item.status in {CoreProcessingStatus.IDENTIFICATION_ERROR.value, QUEUE_SEND_ERROR_STATUS}),
}
metric_cols = st.columns(4)
metric_cols[0].metric("Pendentes", len(documents))
metric_cols[1].metric("Prontos", status_totals["Prontos"])
metric_cols[2].metric("Revisar", status_totals["Revisar"])
metric_cols[3].metric("Erro", status_totals["Erro"])

edited = st.data_editor(
    _result_rows(documents),
    use_container_width=True,
    hide_index=True,
    disabled=[column for column in DISPLAY_COLUMNS if column != "selecionar"],
    column_order=DISPLAY_COLUMNS,
    column_config={
        "selecionar": st.column_config.CheckboxColumn("Selecionar"),
        "score": st.column_config.TextColumn("Score"),
        "status": st.column_config.TextColumn("Status"),
        "motivo_revisao": st.column_config.TextColumn("Motivo"),
        "arquivo": st.column_config.TextColumn("Arquivo"),
        "cliente": st.column_config.TextColumn("Cliente"),
        "competencia": st.column_config.TextColumn("Competencia"),
        "tipo": st.column_config.TextColumn("Tipo"),
        "destino": st.column_config.TextColumn("Destino"),
        "novo_nome": st.column_config.TextColumn("Novo nome"),
    },
)

selected = _selected_items(edited, documents)
confirm_disabled, reprocess_disabled, parametrize_disabled = _button_state(selected)
debug_n8n = st.checkbox("Debug n8n antes do envio", value=False)

if debug_n8n:
    try:
        debug_info = get_n8n_webhook_debug_info()
        st.info(f"Webhook n8n: {debug_info['variable']} -> {debug_info['endpoint']}")
    except ValueError as exc:
        logger.warning("Webhook n8n nao configurado", extra={"ctx_error": str(exc)})
        st.warning("Webhook n8n nao configurado.")

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("Enviar selecionados", type="primary", disabled=confirm_disabled):
        sent = 0
        failed = 0
        messages: list[dict[str, str]] = []
        with st.spinner("Enviando documentos..."):
            for item in selected:
                if item.status != READY_STATUS or not item.id:
                    continue
                result: CoreDocumentResult | None = None
                try:
                    repository.update_document_status(str(item.id), QUEUE_SENDING_STATUS)
                    if debug_n8n:
                        debug_info = get_n8n_webhook_debug_info()
                        messages.append(
                            _queue_message("info", f"Webhook n8n usado: {debug_info['variable']} -> {debug_info['endpoint']}")
                        )

                    result = _refresh_storage_for_send(item)
                    updated_result = CoreProcessor().confirm_and_send(
                        result,
                        user_name=item.uploaded_by or "sistema",
                        user_department="contabil",
                        source_channel=item.source_channel,
                    )
                    send_ok = bool(updated_result.n8n_dispatch.get("send_ok"))
                    if send_ok:
                        sent_item = repository.mark_as_sent(str(item.id), updated_result)
                        try:
                            checklist_service = ChecklistService()
                            checklist_service.mark_received_after_send(sent_item)
                        except Exception as checklist_exc:
                            logger.warning(
                                "Falha ao atualizar checklist apos envio",
                                extra={"ctx_queue_id": item.id, "ctx_error": str(checklist_exc)},
                            )
                        sent += 1
                        messages.append(_queue_message("success", f"Documento enviado com sucesso: {item.original_file_name}"))
                    else:
                        failed += 1
                        error = str(
                            updated_result.n8n_dispatch.get("error")
                            or updated_result.n8n_dispatch.get("n8n_response_body")
                            or "Falha sem detalhe retornado pelo n8n."
                        )
                        repository.mark_as_error(str(item.id), error, updated_result)
                        logger.warning("Falha retornada pelo n8n", extra={"ctx_queue_id": item.id, "ctx_error": error})
                        messages.append(_queue_message("error", f"Nao foi possivel enviar {item.original_file_name}."))
                except Exception as exc:
                    failed += 1
                    repository.mark_as_error(str(item.id), str(exc), result)
                    logger.exception("Falha ao confirmar envio", extra={"ctx_queue_id": item.id, "ctx_error": str(exc)})
                    messages.append(_queue_message("error", f"Nao foi possivel enviar {item.original_file_name}."))

        if sent:
            messages.append(_queue_message("success", f"{sent} documento(s) enviado(s) e marcados como ENVIADO."))
        if failed:
            messages.append(_queue_message("warning", f"{failed} documento(s) permaneceram na fila com erro de envio."))
        st.session_state[ACTION_MESSAGES_KEY] = messages
        st.rerun()

with col2:
    if st.button("Reprocessar", disabled=reprocess_disabled):
        reprocessed = 0
        ready = 0
        still_pending = 0
        with st.spinner("Reprocessando documentos..."):
            for item in selected:
                try:
                    result = _reprocess_item(item)
                    repository.upsert_document_queue(
                        result=result,
                        uploaded_by=item.uploaded_by,
                        source_channel=item.source_channel,
                    )
                    reprocessed += 1
                    if result.status == CoreProcessingStatus.READY_TO_SEND:
                        ready += 1
                    else:
                        still_pending += 1
                except Exception as exc:
                    still_pending += 1
                    logger.exception("Falha ao reprocessar documento", extra={"ctx_queue_id": item.id, "ctx_error": str(exc)})
                    st.error(f"Nao foi possivel reprocessar {item.original_file_name}.")

        if reprocessed:
            st.success(
                f"{reprocessed} reprocessado(s). {ready} pronto(s) para envio. "
                f"{still_pending} ainda com erro/revisao."
            )
            st.rerun()

with col3:
    if st.button("Parametrizar", disabled=parametrize_disabled):
        needs_param = [item for item in selected if item.status in REVIEW_STATUSES]
        if len(needs_param) != 1:
            st.warning("Selecione somente um documento em revisao/erro para parametrizar.")
        else:
            st.session_state["parametrization_queue_id"] = needs_param[0].id
            st.switch_page("pages/3_Parametrizacao.py")

if not selected:
    st.info("Selecione um ou mais documentos para liberar as acoes.")
elif confirm_disabled:
    st.info("Confirmar envio so fica habilitado quando 100% dos selecionados estao PRONTO_ENVIO.")

st.divider()
with st.expander("Limpar pendentes"):
    confirm_cleanup = st.checkbox("Confirmo que desejo limpar os documentos pendentes da fila")
    if st.button("Limpar pendentes", disabled=not confirm_cleanup):
        storage_service = SupabaseStorageService()
        removed = 0
        storage_deleted = 0
        storage_errors = 0
        with st.spinner("Limpando pendentes..."):
            for item in documents:
                if not item.id:
                    continue
                if item.storage_path:
                    if storage_service.delete_object(item.storage_path):
                        storage_deleted += 1
                    else:
                        storage_errors += 1
                repository.discard_document(str(item.id))
                removed += 1

        st.success(f"Pendentes descartados: {removed}.")
        if storage_deleted:
            st.info(f"{storage_deleted} arquivo(s) removido(s) do Storage.")
        if storage_errors:
            st.warning(f"{storage_errors} arquivo(s) nao puderam ser removidos do Storage.")
        st.rerun()
