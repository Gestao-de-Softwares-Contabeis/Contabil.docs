from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from models.document import DocumentType
from models.document_checklist import ClientDocumentChecklist
from repositories.document_checklist_repository import DocumentChecklistRepository
from repositories.document_queue_repository import DocumentQueueRepository
from services.checklist_service import ChecklistService
from services.parametrization_service import ParametrizationService
from utils.normalization import normalize_competence
from utils.structured_logging import get_logger
from utils.ui_formatting import client_code_sort_key, format_competence


logger = get_logger(__name__)
FILE_EXTENSION_OPTIONS = ["pdf", "ofx", "xls", "xlsx", "csv", "txt"]
DOCUMENT_TYPE_OPTIONS = [item.value for item in DocumentType if item.value != "ofx"]
PERIOD_OPTIONS = [
    "Este mês",
    "Mês anterior",
    "Últimos 3 meses",
    "Últimos 6 meses",
    "Últimos 12 meses",
    "Período personalizado",
]
ADD_FORM_VERSION_KEY = "checklist_add_form_version"
EDIT_FORM_VERSION_KEY = "checklist_edit_form_version"
EDIT_SELECT_VERSION_KEY = "checklist_edit_select_version"


def _client_options() -> dict[str, str]:
    clients = sorted(ParametrizationService().list_clients(), key=lambda item: client_code_sort_key(item[0]))
    return {label: code for code, label in clients}


def _month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _add_months(competence: str, months: int) -> str:
    year, month = [int(part) for part in competence.split("-", 1)]
    month += months
    while month > 12:
        year += 1
        month -= 12
    while month < 1:
        year -= 1
        month += 12
    return f"{year:04d}-{month:02d}"


def _month_range(start: str, end: str) -> list[str]:
    months: list[str] = []
    current = start
    while current <= end:
        months.append(current)
        current = _add_months(current, 1)
    return months


def _competences_for_period(option: str, custom_start: str | None = None, custom_end: str | None = None) -> list[str]:
    current_month = _month_key(date.today())
    if option == "Este mês":
        return [current_month]
    if option == "Mês anterior":
        return [_add_months(current_month, -1)]
    if option == "Últimos 3 meses":
        return _month_range(_add_months(current_month, -2), current_month)
    if option == "Últimos 6 meses":
        return _month_range(_add_months(current_month, -5), current_month)
    if option == "Últimos 12 meses":
        return _month_range(_add_months(current_month, -11), current_month)

    start = normalize_competence(custom_start)
    end = normalize_competence(custom_end)
    if not start or not end:
        raise ValueError("Informe período personalizado no formato YYYY-MM ou MM/YYYY.")
    if start > end:
        raise ValueError("A competência inicial não pode ser maior que a final.")
    return _month_range(start, end)


def _document_type_index(value: str | None) -> int:
    return DOCUMENT_TYPE_OPTIONS.index(value) if value in DOCUMENT_TYPE_OPTIONS else 0


def _file_extension_index(value: str | None) -> int:
    if not value:
        return 0
    normalized = value.lower().lstrip(".")
    return FILE_EXTENSION_OPTIONS.index(normalized) if normalized in FILE_EXTENSION_OPTIONS else 0


def _display_matrix_rows(matrix_rows: list[dict[str, object]], competences: list[str]) -> list[dict[str, object]]:
    display_rows: list[dict[str, object]] = []
    for row in matrix_rows:
        display_row: dict[str, object] = {
            "Documento esperado": row.get("document_type"),
            "Instituicao": row.get("institution"),
            "Extensao": row.get("file_extension"),
            "Descricao": row.get("description"),
        }
        for competence in competences:
            display_row[format_competence(competence)] = row.get(competence)
        display_rows.append(display_row)
    return display_rows


def _display_summary_rows(summary_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            **row,
            "competencia": format_competence(str(row.get("competencia") or "")),
        }
        for row in summary_rows
    ]


def _matrix_style(rows: list[dict[str, object]]) -> object:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    def color_status(value: object) -> str:
        if value == "RECEBIDO":
            return "background-color: #dcfce7; color: #166534; font-weight: 600"
        if value == "PENDENTE":
            return "background-color: #fee2e2; color: #991b1b; font-weight: 600"
        return ""

    styler = frame.style
    if hasattr(styler, "map"):
        return styler.map(color_status)
    return styler.applymap(color_status)


def _item_label(item: ClientDocumentChecklist) -> str:
    return " | ".join(
        [
            item.document_type,
            item.file_extension or "-",
            item.institution or "-",
            item.document_name_pattern or "-",
            item.description or "-",
        ]
    )


def _bump_state_version(key: str) -> None:
    st.session_state[key] = int(st.session_state.get(key, 0)) + 1


st.title("Checklist mensal")
st.caption("Obrigacao fixa mensal por cliente, calculada direto dos documentos enviados.")

repository = DocumentChecklistRepository()
queue_repository = DocumentQueueRepository()
checklist_service = ChecklistService(repository)

try:
    client_options = _client_options()
except Exception as exc:
    logger.exception("Falha ao carregar clientes", extra={"ctx_error": str(exc)})
    st.error("Nao foi possivel carregar os clientes.")
    st.stop()

if not client_options:
    st.warning("Nenhum cliente ativo encontrado.")
    st.stop()

st.subheader("Acompanhamento")
filter_col1, filter_col2 = st.columns(2)
with filter_col1:
    client_label = st.selectbox("Cliente", list(client_options.keys()))
    client_code = client_options[client_label]
with filter_col2:
    period_option = st.selectbox("Período", PERIOD_OPTIONS)
custom_start = custom_end = None
if period_option == "Período personalizado":
    custom_col1, custom_col2 = st.columns(2)
    with custom_col1:
        custom_start = st.text_input("Competência inicial", value=_add_months(_month_key(date.today()), -2))
    with custom_col2:
        custom_end = st.text_input("Competência final", value=_month_key(date.today()))

try:
    competences = _competences_for_period(period_option, custom_start, custom_end)
except ValueError as exc:
    st.error(str(exc))
    st.stop()

try:
    fixed_items = repository.list_checklist(client_code=client_code)
    fixed_items = sorted(
        fixed_items,
        key=lambda item: (
            str(item.document_type or "").lower(),
            str(item.institution or "").lower(),
            str(item.file_extension or "").lower(),
            str(item.description or "").lower(),
        ),
    )
    sent_documents = queue_repository.list_sent_documents(client_code=client_code, competences=competences)
    received_statuses = repository.list_statuses_for_competences(client_code=client_code, competences=competences)
except Exception as exc:
    logger.exception("Falha ao carregar checklist", extra={"ctx_error": str(exc)})
    st.error("Nao foi possivel carregar o checklist.")
    st.stop()

matrix_rows = checklist_service.build_monthly_matrix(fixed_items, sent_documents, competences, received_statuses)
summary_rows = checklist_service.build_monthly_summary(matrix_rows, competences, client_code)
matrix_display_rows = _display_matrix_rows(matrix_rows, competences)

st.dataframe(_display_summary_rows(summary_rows), use_container_width=True, hide_index=True)
if matrix_display_rows:
    st.dataframe(_matrix_style(matrix_display_rows), use_container_width=True, hide_index=True)
else:
    st.info("Este cliente não possui itens no checklist fixo.")

st.divider()
st.subheader("Checklist fixo")

st.dataframe(
    [
        {
            "document_type": item.document_type,
            "institution": item.institution,
            "file_extension": item.file_extension,
            "document_name_pattern": item.document_name_pattern,
            "description": item.description,
        }
        for item in fixed_items
    ],
    use_container_width=True,
    hide_index=True,
)

st.markdown("**Adicionar item fixo**")
add_form_version = int(st.session_state.get(ADD_FORM_VERSION_KEY, 0))
with st.form(f"new_checklist_item_form_{add_form_version}"):
    new_document_type = st.selectbox("Tipo documento", DOCUMENT_TYPE_OPTIONS, key=f"new_document_type_{add_form_version}")
    new_file_extension = st.selectbox("Extensão esperada", FILE_EXTENSION_OPTIONS, key=f"new_file_extension_{add_form_version}")
    new_institution = st.text_input("Instituição (opcional)", key=f"new_institution_{add_form_version}")
    new_document_name_pattern = st.text_input(
        "Padrão no nome/texto (opcional)",
        key=f"new_document_name_pattern_{add_form_version}",
    )
    new_description = st.text_input("Descrição (opcional)", key=f"new_description_{add_form_version}")
    add_item = st.form_submit_button("Adicionar item", type="primary")

if add_item:
    try:
        repository.create_checklist_item(
            ClientDocumentChecklist(
                client_code=client_code,
                document_type=new_document_type,
                file_extension=new_file_extension,
                institution=new_institution.strip() or None,
                document_name_pattern=new_document_name_pattern.strip() or None,
                description=new_description.strip() or None,
                is_required=True,
                is_active=True,
            )
        )
        st.success("Item fixo adicionado.")
        _bump_state_version(ADD_FORM_VERSION_KEY)
        st.rerun()
    except ValueError as exc:
        st.warning(str(exc))
    except Exception as exc:
        logger.exception("Falha ao adicionar item fixo do checklist")
        st.error("Nao foi possivel adicionar o item.")

st.markdown("**Editar item fixo**")
editable_items = [item for item in fixed_items if item.id]
if not editable_items:
    st.info("Este cliente ainda não possui documentos cadastrados.")
else:
    item_by_id = {str(item.id): item for item in editable_items if item.id}
    edit_select_version = int(st.session_state.get(EDIT_SELECT_VERSION_KEY, 0))
    selected_item_id = st.selectbox(
        "Item fixo para editar",
        list(item_by_id.keys()),
        format_func=lambda item_id: _item_label(item_by_id[item_id]),
        key=f"checklist_edit_select_{edit_select_version}",
    )
    selected_item = item_by_id[selected_item_id]
    edit_form_version = int(st.session_state.get(EDIT_FORM_VERSION_KEY, 0))
    edit_key_suffix = f"{selected_item.id}_{edit_form_version}"

    with st.form(f"edit_checklist_item_form_{edit_key_suffix}"):
        edit_document_type = st.selectbox(
            "Tipo documento",
            DOCUMENT_TYPE_OPTIONS,
            index=_document_type_index(selected_item.document_type),
            key=f"edit_document_type_{edit_key_suffix}",
        )
        edit_file_extension = st.selectbox(
            "Extensão esperada",
            FILE_EXTENSION_OPTIONS,
            index=_file_extension_index(selected_item.file_extension),
            key=f"edit_file_extension_{edit_key_suffix}",
        )
        edit_institution = st.text_input(
            "Instituição (opcional)",
            value=selected_item.institution or "",
            key=f"edit_institution_{edit_key_suffix}",
        )
        edit_document_name_pattern = st.text_input(
            "Padrão no nome/texto (opcional)",
            value=selected_item.document_name_pattern or "",
            key=f"edit_document_name_pattern_{edit_key_suffix}",
        )
        edit_description = st.text_input(
            "Descrição (opcional)",
            value=selected_item.description or "",
            key=f"edit_description_{edit_key_suffix}",
        )
        save_changes = st.form_submit_button("Salvar alterações", type="primary")

    if save_changes:
        try:
            repository.update_checklist_item(
                str(selected_item.id),
                {
                    "document_type": edit_document_type,
                    "institution": edit_institution.strip() or None,
                    "file_extension": edit_file_extension,
                    "document_name_pattern": edit_document_name_pattern.strip() or None,
                    "description": edit_description.strip() or None,
                },
            )
            st.success("Item fixo atualizado.")
            _bump_state_version(EDIT_FORM_VERSION_KEY)
            _bump_state_version(EDIT_SELECT_VERSION_KEY)
            st.rerun()
        except ValueError as exc:
            st.warning(str(exc))
        except Exception as exc:
            logger.exception("Falha ao editar item fixo do checklist")
            st.error("Nao foi possivel editar o item.")

    st.markdown("**Excluir definitivamente**")
    st.warning("Isso remove apenas a obrigacao fixa futura. Documentos ja enviados permanecem no historico e na fila.")
    confirm_delete = st.checkbox(
        "Confirmo que quero excluir este documento do checklist fixo.",
        key=f"confirm_delete_{selected_item.id}",
    )
    if st.button("Excluir item", disabled=not confirm_delete, key=f"delete_checklist_item_{selected_item.id}"):
        try:
            deleted = repository.delete_checklist_item(str(selected_item.id))
            if deleted:
                st.success("Item fixo excluido definitivamente.")
                _bump_state_version(EDIT_FORM_VERSION_KEY)
                _bump_state_version(EDIT_SELECT_VERSION_KEY)
                st.rerun()
        except Exception as exc:
            logger.exception("Falha ao excluir item fixo do checklist")
            st.error("Nao foi possivel excluir o item.")
