from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from app.settings import get_n8n_webhook_debug_info
from app.session_state import (
    clear_pending_documents,
    ensure_document_state,
    get_documents,
    remove_sent_documents,
    update_document_result,
)
from models.document import CoreDocumentResult, CoreProcessingStatus
from services.core_processor import CoreProcessor
from utils.structured_logging import get_logger


logger = get_logger(__name__)

READY_STATUS = CoreProcessingStatus.READY_TO_SEND.value
REVIEW_STATUSES = {
    CoreProcessingStatus.REVIEW.value,
    CoreProcessingStatus.IDENTIFICATION_ERROR.value,
    "ERRO_ENVIO",
}

DISPLAY_COLUMNS = [
    "selecionar",
    "score",
    "motivo_revisao",
    "nome_arquivo",
    "extensao",
    "cliente_identificado",
    "cnpj",
    "competencia",
    "tipo_documento",
    "instituicao",
    "status",
    "caminho_destino",
    "novo_nome_arquivo",
]
ACTION_MESSAGES_KEY = "document_action_messages"


def _current_status(item: dict[str, Any]) -> str:
    if item.get("ui_status"):
        return str(item["ui_status"])
    result: CoreDocumentResult = item["result"]
    return result.status.value


def _review_reason(item: dict[str, Any]) -> str | None:
    if item.get("send_error"):
        return str(item["send_error"])
    result: CoreDocumentResult = item["result"]
    return result.review_reason


def _result_rows(documents: list[dict[str, Any]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in documents:
        result: CoreDocumentResult = item["result"]
        rows.append(
            {
                "selecionar": False,
                "score": result.confidence,
                "motivo_revisao": _review_reason(item),
                "nome_arquivo": result.original_file_name,
                "extensao": result.extension,
                "cliente_identificado": result.detected_client_name,
                "cnpj": result.detected_client_cnpj,
                "competencia": result.competence,
                "tipo_documento": result.document_type,
                "instituicao": result.institution,
                "status": _current_status(item),
                "caminho_destino": result.destination_path_readable,
                "novo_nome_arquivo": result.new_file_name,
            }
        )
    return rows


def _records_from_editor(edited_rows: object) -> list[dict[str, object]]:
    if hasattr(edited_rows, "to_dict"):
        return edited_rows.to_dict("records")  # type: ignore[no-any-return, attr-defined]
    return list(edited_rows)  # type: ignore[arg-type]


def _selected_items(edited_rows: object, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for index, row in enumerate(_records_from_editor(edited_rows)):
        if row.get("selecionar") and index < len(documents):
            selected.append(documents[index])
    return selected


def _show_error(message: str, exc: Exception) -> None:
    logger.exception(message)
    st.error(f"{message}: {exc}")


def _button_state(selected: list[dict[str, Any]]) -> tuple[bool, bool, bool]:
    if not selected:
        return True, True, True

    statuses = [_current_status(item) for item in selected]
    all_ready = all(status == READY_STATUS for status in statuses)
    has_review = any(status in REVIEW_STATUSES for status in statuses)

    confirm_disabled = not all_ready
    reprocess_disabled = False
    parametrize_disabled = not has_review
    return confirm_disabled, reprocess_disabled, parametrize_disabled


ensure_document_state()

st.title("Documentos a verificar")
st.caption("Somente documentos PRONTO_ENVIO podem ser confirmados para o n8n.")

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

documents = get_documents()
if not documents:
    st.info("Nenhum documento analisado nesta sessao.")
    st.page_link("pages/1_Upload.py", label="Ir para Upload")
    st.stop()

rows = _result_rows(documents)
edited = st.data_editor(
    rows,
    use_container_width=True,
    hide_index=True,
    disabled=[column for column in DISPLAY_COLUMNS if column != "selecionar"],
    column_order=DISPLAY_COLUMNS,
    column_config={
        "selecionar": st.column_config.CheckboxColumn("selecionar"),
        "score": st.column_config.NumberColumn("score", format="%.2f"),
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
        st.warning(str(exc))

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("Confirmar envio selecionados", type="primary", disabled=confirm_disabled):
        sent = 0
        failed = 0
        messages: list[dict[str, str]] = []
        for item in selected:
            result: CoreDocumentResult = item["result"]
            if _current_status(item) != READY_STATUS:
                continue

            try:
                if debug_n8n:
                    debug_info = get_n8n_webhook_debug_info()
                    messages.append(
                        {
                            "level": "info",
                            "text": f"Webhook n8n usado: {debug_info['variable']} -> {debug_info['endpoint']}",
                        }
                    )
                updated_result = CoreProcessor().confirm_and_send(
                    result,
                    user_name=item.get("sender_name") or "sistema",
                    user_department=item.get("sender_department"),
                    source_channel=item.get("origin_channel"),
                )
                item["result"] = updated_result
                send_ok = bool(updated_result.n8n_dispatch.get("send_ok"))
                if send_ok:
                    item["sent"] = True
                    item["confirmed"] = True
                    sent += 1
                    messages.append(
                        {
                            "level": "success",
                            "text": f"Documento enviado com sucesso: {updated_result.original_file_name}",
                        }
                    )
                else:
                    failed += 1
                    error = str(
                        updated_result.n8n_dispatch.get("error")
                        or updated_result.n8n_dispatch.get("n8n_response_body")
                        or "Falha sem detalhe retornado pelo n8n."
                    )
                    messages.append(
                        {
                            "level": "error",
                            "text": f"Falha ao enviar {updated_result.original_file_name}: {error}",
                        }
                    )
                    item["ui_status"] = "ERRO_ENVIO"
                    item["send_error"] = error
            except Exception as exc:
                failed += 1
                messages.append(
                    {
                        "level": "error",
                        "text": f"Falha ao confirmar {result.original_file_name}: {exc}",
                    }
                )
                item["ui_status"] = "ERRO_ENVIO"
                item["send_error"] = str(exc)
                logger.exception("Falha ao confirmar envio", extra={"ctx_file": result.original_file_name})

        removed = remove_sent_documents()
        if sent:
            messages.append(
                {
                    "level": "success",
                    "text": f"{sent} documento(s) enviado(s) e removido(s) da lista de verificacao.",
                }
            )
        if failed:
            messages.append(
                {
                    "level": "warning",
                    "text": f"{failed} documento(s) permaneceram na lista com erro de envio.",
                }
            )
        if removed or failed or messages:
            st.session_state[ACTION_MESSAGES_KEY] = messages
            st.rerun()

with col2:
    if st.button("Reprocessar selecionados", disabled=reprocess_disabled):
        reprocessed = 0
        ready = 0
        still_pending = 0
        for item in selected:
            try:
                temp_path = Path(str(item["temp_path"]))
                result = CoreProcessor().analyze_path(
                    temp_path,
                    department=item.get("sender_department") or "contabil",
                )
                update_document_result(str(item["id"]), result)
                reprocessed += 1
                if result.status == CoreProcessingStatus.READY_TO_SEND:
                    ready += 1
                else:
                    still_pending += 1
            except Exception as exc:
                still_pending += 1
                _show_error(f"Falha ao reprocessar {item['result'].original_file_name}", exc)

        if reprocessed:
            st.success(
                f"{reprocessed} reprocessado(s). {ready} pronto(s) para envio. "
                f"{still_pending} ainda com erro/revisao."
            )
            st.rerun()

with col3:
    if st.button("Parametrizar selecionado", disabled=parametrize_disabled):
        needs_param = [item for item in selected if _current_status(item) in REVIEW_STATUSES]
        if len(needs_param) != 1:
            st.warning("Selecione somente um documento em revisao/erro para parametrizar.")
        else:
            st.session_state["parametrization_document_id"] = needs_param[0]["id"]
            st.switch_page("pages/3_Parametrizacao.py")

if not selected:
    st.info("Selecione um ou mais documentos para liberar as acoes.")
elif confirm_disabled:
    st.info("Confirmar envio so fica habilitado quando 100% dos selecionados estao PRONTO_ENVIO.")

st.divider()
st.subheader("Limpeza")
confirm_cleanup = st.checkbox("Confirmo que desejo limpar os documentos pendentes desta sessao")
if st.button("Limpar documentos pendentes", disabled=not confirm_cleanup):
    stats = clear_pending_documents()
    st.success(
        "Pendentes limpos: "
        f"{stats['removed']} removido(s), "
        f"{stats['local_deleted']} temporario(s) local(is) apagado(s), "
        f"{stats['storage_deleted']} objeto(s) removido(s) do Storage."
    )
    if stats.get("storage_errors"):
        st.warning(f"{stats['storage_errors']} objeto(s) nao puderam ser removidos do Storage.")
    st.rerun()
