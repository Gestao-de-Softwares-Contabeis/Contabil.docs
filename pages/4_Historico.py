from __future__ import annotations

from datetime import date, datetime, timedelta

import streamlit as st

from models.document import ProcessingStatus
from services.history_service import HistoryService
from services.parametrization_service import ParametrizationService
from utils.structured_logging import get_logger
from utils.ui_formatting import client_code_sort_key, format_competence, format_datetime


logger = get_logger(__name__)


def _show_error(message: str, exc: Exception) -> None:
    logger.exception(message, extra={"ctx_error": str(exc)})
    st.error(message)


st.title("Historico")
st.caption("Registro dos processamentos e envios.")

try:
    clients = sorted(ParametrizationService().list_clients(), key=lambda item: client_code_sort_key(item[0]))
    client_options = {"Todos": None, **{label: code for code, label in clients}}

    col1, col2, col3 = st.columns(3)
    with col1:
        start_date = st.date_input("Inicio", value=date.today() - timedelta(days=30))
    with col2:
        end_date = st.date_input("Fim", value=date.today())
    with col3:
        selected_client = st.selectbox("Cliente", list(client_options.keys()))

    col4, col5, col6 = st.columns(3)
    with col4:
        selected_status = st.selectbox("Status", ["Todos", *[item.value for item in ProcessingStatus]])
    with col5:
        uploaded_by = st.text_input("Quem enviou")
    with col6:
        source_channel = st.selectbox(
            "Canal de origem",
            ["Todos", "Onvio", "E-mail", "WhatsApp/Messenger", "Drive do cliente", "Outros"],
        )

    document_type = st.text_input("Tipo documento")

    service = HistoryService()
    logs = service.list_history(
        start_date=start_date,
        end_date=end_date,
        client_id=client_options[selected_client],
        user_name=uploaded_by.strip() or None,
        status=None if selected_status == "Todos" else selected_status,
    )

    if source_channel != "Todos":
        logs = [log for log in logs if log.origin_channel == source_channel]
    if document_type.strip():
        needle = document_type.strip().lower()
        logs = [log for log in logs if needle in (log.document_type or "").lower()]
    logs = sorted(logs, key=lambda log: log.created_at or datetime.min, reverse=True)

    rows = [
        {
            "data/hora": format_datetime(log.created_at),
            "usuario": log.user_name,
            "canal origem": log.origin_channel,
            "arquivo original": log.original_filename,
            "novo nome": (log.metadata or {}).get("new_file_name"),
            "cliente": log.client_name,
            "competencia": format_competence(log.competence),
            "tipo": log.document_type,
            "status": log.status,
            "mensagem": log.observation,
            "destino": log.destination_folder,
        }
        for log in logs
    ]

    st.info(f"{len(rows)} registro(s) encontrado(s).")
    st.dataframe(rows, use_container_width=True, hide_index=True)
    export_col1, export_col2 = st.columns(2)
    with export_col1:
        st.download_button(
            "Exportar CSV",
            data=service.to_csv(logs),
            file_name="historico_documentos.csv",
            mime="text/csv",
        )
    with export_col2:
        st.download_button(
            "Exportar TXT",
            data=service.to_txt(logs),
            file_name="historico_documentos.txt",
            mime="text/plain",
        )
except Exception as exc:
    _show_error("Nao foi possivel carregar o historico.", exc)
