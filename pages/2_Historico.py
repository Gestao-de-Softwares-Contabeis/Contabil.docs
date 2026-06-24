from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from app.dataframes import history_rows
from app.settings import load_settings
from app.supabase_lists import collaborator_names, safe_active_collaborators
from database.supabase_client import SupabaseConfigurationError
from models.document import ProcessingStatus
from services.history_service import HistoryService
from services.parametrization_service import ParametrizationService
from utils.structured_logging import get_logger


logger = get_logger(__name__)
settings = load_settings()
collaborators, collaborators_error = safe_active_collaborators()
collaborator_options = collaborator_names(collaborators)

st.set_page_config(page_title="Historico", page_icon="H", layout="wide")
st.title("Historico")


def show_error(message: str, exc: Exception) -> None:
    logger.exception(message)
    st.error(f"{message}: {exc}")


try:
    parametrization_service = ParametrizationService()
    clients = parametrization_service.list_clients()
    client_options = {"Todos": None, **{name: client_id for client_id, name in clients}}

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        start_date = st.date_input("Inicio", value=date.today() - timedelta(days=30))
    with col2:
        end_date = st.date_input("Fim", value=date.today())
    with col3:
        selected_client = st.selectbox("Cliente", list(client_options.keys()))
    with col4:
        if collaborators_error:
            st.warning("Nao foi possivel carregar colaboradores do Supabase.")
        selected_user = st.selectbox("Usuario", ["Todos", *collaborator_options])

    selected_department = st.selectbox(
        "Setor",
        ["Todos", *sorted({collaborator.department for collaborator in collaborators})],
    )

    selected_status = st.selectbox(
        "Status",
        ["Todos", *[status.value for status in ProcessingStatus]],
    )

    history_service = HistoryService()
    logs = history_service.list_history(
        start_date=start_date,
        end_date=end_date,
        client_id=client_options[selected_client],
        user_name=None if selected_user == "Todos" else selected_user,
        user_department=None if selected_department == "Todos" else selected_department,
        status=None if selected_status == "Todos" else selected_status,
    )

    st.dataframe(history_rows(logs), use_container_width=True, hide_index=True)
    st.download_button(
        "Exportar CSV",
        data=history_service.to_csv(logs),
        file_name="historico_documentos.csv",
        mime="text/csv",
    )
    st.download_button(
        "Exportar TXT",
        data=history_service.to_txt(logs),
        file_name="historico_documentos.txt",
        mime="text/plain",
    )
except SupabaseConfigurationError as exc:
    st.warning(str(exc))
except Exception as exc:
    show_error("Falha ao carregar historico", exc)
