from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Collaborator(BaseModel):
    id: str | None = None
    name: str
    department: str
    status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None
