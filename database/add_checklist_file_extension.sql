alter table public.client_document_checklist
add column if not exists file_extension text;

alter table public.document_checklist_status
add column if not exists file_extension text;

create index if not exists idx_client_document_checklist_file_extension
on public.client_document_checklist (file_extension);

create index if not exists idx_document_checklist_status_file_extension
on public.document_checklist_status (file_extension);

notify pgrst, 'reload schema';
