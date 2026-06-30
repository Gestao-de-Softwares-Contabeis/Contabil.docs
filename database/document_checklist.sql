create table if not exists public.client_document_checklist (
  id uuid primary key default gen_random_uuid(),
  client_code text not null,
  document_type text not null,
  file_extension text,
  institution text,
  document_name_pattern text,
  description text,
  department text default 'contabil',
  is_required boolean default true,
  is_active boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists public.document_checklist_status (
  id uuid primary key default gen_random_uuid(),
  checklist_id uuid references public.client_document_checklist(id),
  client_code text not null,
  competence text not null,
  document_type text not null,
  file_extension text,
  institution text,
  status text default 'PENDENTE',
  matched_document_queue_id uuid,
  uploaded_by text,
  auto_matched boolean default true,
  received_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.client_document_checklist
add column if not exists document_name_pattern text;

alter table public.client_document_checklist
add column if not exists file_extension text;

alter table public.document_checklist_status
add column if not exists file_extension text;

alter table public.document_checklist_status
add column if not exists uploaded_by text;

alter table public.document_checklist_status
add column if not exists auto_matched boolean default true;

create unique index if not exists ux_document_checklist_status_month
on public.document_checklist_status (checklist_id, client_code, competence);

create index if not exists idx_client_document_checklist_client_code
on public.client_document_checklist (client_code);

create index if not exists idx_client_document_checklist_active
on public.client_document_checklist (is_active);

create index if not exists idx_client_document_checklist_document_type
on public.client_document_checklist (document_type);

create index if not exists idx_client_document_checklist_file_extension
on public.client_document_checklist (file_extension);

create index if not exists idx_document_checklist_status_client_code
on public.document_checklist_status (client_code);

create index if not exists idx_document_checklist_status_competence
on public.document_checklist_status (competence);

create index if not exists idx_document_checklist_status_status
on public.document_checklist_status (status);

create index if not exists idx_document_checklist_status_document_type
on public.document_checklist_status (document_type);

create index if not exists idx_document_checklist_status_file_extension
on public.document_checklist_status (file_extension);

create or replace view public.checklist_dashboard as
select
  client_code,
  competence,
  count(*) total,
  count(*) filter (where status = 'RECEBIDO') recebidos,
  count(*) filter (where status = 'PENDENTE') pendentes,
  count(*) filter (where status = 'DISPENSADO') dispensados
from public.document_checklist_status
group by client_code, competence;

alter table public.client_document_checklist enable row level security;
alter table public.document_checklist_status enable row level security;

drop policy if exists "service_role_all_client_document_checklist" on public.client_document_checklist;
create policy "service_role_all_client_document_checklist"
on public.client_document_checklist
for all
to service_role
using (true)
with check (true);

drop policy if exists "service_role_all_document_checklist_status" on public.document_checklist_status;
create policy "service_role_all_document_checklist_status"
on public.document_checklist_status
for all
to service_role
using (true)
with check (true);

grant select, insert, update on public.client_document_checklist to service_role;
grant select, insert, update on public.document_checklist_status to service_role;
grant select on public.checklist_dashboard to service_role;
