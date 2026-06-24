from __future__ import annotations

import csv
import io
from datetime import date

from models.document import DocumentLogEntry
from repositories.log_repository import ProcessingLogRepository


class HistoryService:
    def __init__(self, log_repository: ProcessingLogRepository | None = None) -> None:
        self.log_repository = log_repository or ProcessingLogRepository()

    def list_current_documents(self) -> list[DocumentLogEntry]:
        return self.log_repository.list_current_documents(limit=2000)

    def list_history(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        client_id: str | None = None,
        user_name: str | None = None,
        user_department: str | None = None,
        status: str | None = None,
    ) -> list[DocumentLogEntry]:
        return self.log_repository.list_logs(
            start_date=start_date,
            end_date=end_date,
            client_id=client_id,
            user_name=user_name,
            user_department=user_department,
            status=status,
            limit=5000,
        )

    def to_csv(self, logs: list[DocumentLogEntry]) -> str:
        output = io.StringIO()
        fieldnames = [
            "created_at",
            "user_name",
            "user_department",
            "action",
            "client_name",
            "original_filename",
            "competence",
            "document_type",
            "score",
            "score_band",
            "matched_by",
            "ai_used",
            "sender_name",
            "sender_department",
            "origin_channel",
            "status",
            "destination_folder",
            "extracted_text",
            "observation",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for item in logs:
            writer.writerow(item.model_dump(mode="json"))
        return output.getvalue()

    def to_txt(self, logs: list[DocumentLogEntry]) -> str:
        lines: list[str] = []
        for item in logs:
            lines.append(
                " | ".join(
                    [
                        str(item.created_at or ""),
                        item.user_name,
                        item.action,
                        item.client_name or "",
                        item.original_filename or "",
                        item.status,
                        item.observation or "",
                    ]
                )
            )
        return "\n".join(lines)
