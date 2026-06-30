create table if not exists public.document_queue (
  id uuid primary key default gen_random_uuid(),
  file_hash text not null,
  original_file_name text,
  extension text,
  storage_path text,
  signed_url text,
  uploaded_by text,
  source_channel text,
  client_code text,
  client_name text,
  client_cnpj text,
  competence text,
  document_type text,
  institution text,
  confidence numeric,
  status text,
  review_reason text,
  destination_folder_id text,
  destination_path_readable text,
  new_file_name text,
  payload_json jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  sent_at timestamptz
);

create unique index if not exists ux_document_queue_file_hash_active
on public.document_queue (file_hash)
where status not in ('ENVIADO', 'DESCARTADO');

create index if not exists idx_document_queue_status
on public.document_queue (status);

create index if not exists idx_document_queue_file_hash
on public.document_queue (file_hash);

create index if not exists idx_document_queue_client_code
on public.document_queue (client_code);

create index if not exists idx_document_queue_created_at
on public.document_queue (created_at);

create index if not exists idx_document_queue_competence
on public.document_queue (competence);

alter table public.document_queue enable row level security;

drop policy if exists "service_role_all_document_queue" on public.document_queue;
create policy "service_role_all_document_queue"
on public.document_queue
for all
to service_role
using (true)
with check (true);

grant select, insert, update on public.document_queue to service_role;
