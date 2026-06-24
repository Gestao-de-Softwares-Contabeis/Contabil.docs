from __future__ import annotations

from utils.normalization import build_client_display_name, competence_to_mmyyyy, sanitize_filename_part


class FilenameBuilder:
    def build(
        self,
        client_name: str | None,
        institution: str | None,
        competence: str | None,
        document_type: str,
        extension: str,
        client_code: str | None = None,
    ) -> str | None:
        mmyyyy = competence_to_mmyyyy(competence)
        if not client_name or not mmyyyy:
            return None

        company = sanitize_filename_part(build_client_display_name(client_name, client_code), "CLIENTE")
        bank = sanitize_filename_part(institution, "INSTITUICAO")
        kind = sanitize_filename_part(document_type, "documento_diverso")
        ext = extension.lower().lstrip(".")
        return f"{company} - {bank} - {mmyyyy} - {kind}.{ext}"
