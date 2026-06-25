from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import streamlit as st

from models.document import CoreDocumentResult
from services.storage_service import SupabaseStorageService


ANALYSIS_STATE_KEY = "analysis_results"


def ensure_document_state() -> None:
    st.session_state.setdefault(ANALYSIS_STATE_KEY, [])


def get_documents() -> list[dict[str, Any]]:
    ensure_document_state()
    return st.session_state[ANALYSIS_STATE_KEY]


def result_hash(result: CoreDocumentResult) -> str:
    return str(result.extracted_summary.get("file_hash") or "")


def upsert_document(
    *,
    temp_path: Path,
    sender_name: str,
    sender_department: str | None,
    origin_channel: str,
    result: CoreDocumentResult,
) -> bool:
    documents = get_documents()
    file_hash = result_hash(result)
    for item in documents:
        if item.get("file_hash") and item.get("file_hash") == file_hash:
            cleanup_temp_file(item.get("temp_path"))
            item.update(
                {
                    "temp_path": str(temp_path),
                    "sender_name": sender_name,
                    "sender_department": sender_department,
                    "origin_channel": origin_channel,
                    "result": result,
                    "file_hash": file_hash,
                    "confirmed": False,
                    "sent": False,
                    "ui_status": None,
                    "send_error": None,
                }
            )
            return False

    documents.append(
        {
            "id": uuid.uuid4().hex,
            "temp_path": str(temp_path),
            "sender_name": sender_name,
            "sender_department": sender_department,
            "origin_channel": origin_channel,
            "result": result,
            "file_hash": file_hash,
            "confirmed": False,
            "sent": False,
            "ui_status": None,
            "send_error": None,
        }
    )
    return True


def update_document_result(item_id: str, result: CoreDocumentResult) -> None:
    for item in get_documents():
        if item.get("id") == item_id:
            item["result"] = result
            item["file_hash"] = result_hash(result)
            item["confirmed"] = False
            item["sent"] = False
            item["ui_status"] = None
            item["send_error"] = None
            return


def remove_sent_documents() -> int:
    documents = get_documents()
    remaining: list[dict[str, Any]] = []
    removed = 0
    for item in documents:
        if item.get("sent"):
            cleanup_temp_file(item.get("temp_path"))
            removed += 1
        else:
            remaining.append(item)
    st.session_state[ANALYSIS_STATE_KEY] = remaining
    return removed


def clear_pending_documents(storage_service: SupabaseStorageService | None = None) -> dict[str, int]:
    service = storage_service
    remaining: list[dict[str, Any]] = []
    stats = {"removed": 0, "local_deleted": 0, "storage_deleted": 0, "storage_errors": 0, "kept_sent": 0}
    for item in get_documents():
        if item.get("sent"):
            remaining.append(item)
            stats["kept_sent"] += 1
            continue

        result: CoreDocumentResult = item["result"]
        if cleanup_temp_file(item.get("temp_path")):
            stats["local_deleted"] += 1

        storage_path = result.storage_upload.get("storage_path") if result.storage_upload else None
        if storage_path:
            try:
                service = service or SupabaseStorageService()
                if service.delete_object(str(storage_path)):
                    stats["storage_deleted"] += 1
            except Exception:
                stats["storage_errors"] += 1

        stats["removed"] += 1

    st.session_state[ANALYSIS_STATE_KEY] = remaining
    return stats


def cleanup_temp_file(path_value: object) -> bool:
    if not path_value:
        return False
    path = Path(str(path_value))
    try:
        if path.exists() and path.is_file():
            path.unlink()
            return True
    except OSError:
        return False
    return False
