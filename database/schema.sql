create extension if not exists pgcrypto;

create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create table if not exists clients (
  id uuid primary key default gen_random_uuid(),
  client_code text unique not null,
  client_name text not null,
  client_cnpj text,
  status text default 'active',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists clients_client_code_idx
  on clients (client_code);

create index if not exists clients_client_cnpj_idx
  on clients (client_cnpj);

create index if not exists clients_status_idx
  on clients (status);

drop trigger if exists clients_set_updated_at on clients;
create trigger clients_set_updated_at
before update on clients
for each row execute function set_updated_at();

create table if not exists collaborators (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  department text not null,
  status text default 'active',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists collaborators_status_idx
  on collaborators (status);

create index if not exists collaborators_department_idx
  on collaborators (department);

drop trigger if exists collaborators_set_updated_at on collaborators;
create trigger collaborators_set_updated_at
before update on collaborators
for each row execute function set_updated_at();

create table if not exists storage_folder_map (
  id uuid primary key default gen_random_uuid(),
  client_code text not null,
  client_name text,
  client_cnpj text,
  department text not null,
  competence text not null,
  onedrive_client_folder_id text,
  onedrive_department_folder_id text,
  onedrive_competence_folder_id text,
  client_folder_name text,
  department_folder_name text,
  competence_folder_name text,
  status text default 'active',
  last_synced_at timestamptz default now(),
  created_at timestamptz default now()
);

create index if not exists storage_folder_map_client_code_idx
  on storage_folder_map (client_code);

create index if not exists storage_folder_map_client_cnpj_idx
  on storage_folder_map (client_cnpj);

create index if not exists storage_folder_map_status_idx
  on storage_folder_map (status);

create index if not exists storage_folder_map_competence_idx
  on storage_folder_map (competence);

create index if not exists storage_folder_map_lookup_idx
  on storage_folder_map (client_code, department, competence, status);

create table if not exists document_rules (
  id uuid primary key default gen_random_uuid(),
  client_code text not null,
  file_extension text,
  document_type text,
  rule_type text not null,
  rule_name text,
  rule_value text,
  bank_name text,
  agency text,
  account_number text,
  sheet_name text,
  column_name text,
  row_number integer,
  match_mode text default 'contains',
  is_active boolean default true,
  created_by text,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  last_used_at timestamptz,
  hit_count integer default 0,
  notes text
);

create index if not exists document_rules_client_code_idx
  on document_rules (client_code);

create index if not exists document_rules_rule_type_idx
  on document_rules (rule_type);

create index if not exists document_rules_file_extension_idx
  on document_rules (file_extension);

create index if not exists document_rules_is_active_idx
  on document_rules (is_active);

create index if not exists document_rules_lookup_idx
  on document_rules (client_code, rule_type, file_extension, is_active);

drop trigger if exists document_rules_set_updated_at on document_rules;
create trigger document_rules_set_updated_at
before update on document_rules
for each row execute function set_updated_at();

create table if not exists document_processing_log (
  id uuid primary key default gen_random_uuid(),
  processed_at timestamptz default now(),
  uploaded_by text,
  source_channel text,
  original_file_name text,
  extension text,
  new_file_name text,
  client_code text,
  client_name text,
  client_cnpj text,
  competence text,
  document_type text,
  institution text,
  confidence numeric,
  status text,
  message text,
  destination_folder_id text,
  destination_path_readable text,
  payload_json jsonb
);

create index if not exists document_processing_log_client_code_idx
  on document_processing_log (client_code);

create index if not exists document_processing_log_client_cnpj_idx
  on document_processing_log (client_cnpj);

create index if not exists document_processing_log_status_idx
  on document_processing_log (status);

create index if not exists document_processing_log_competence_idx
  on document_processing_log (competence);

create index if not exists document_processing_log_extension_idx
  on document_processing_log (extension);

create index if not exists document_processing_log_processed_at_idx
  on document_processing_log (processed_at desc);

create or replace view client_lookup
with (security_invoker = true) as
select
  id,
  client_code,
  client_name,
  client_name as name,
  client_cnpj,
  client_cnpj as cnpj,
  status,
  case when status in ('active', 'activate') then true else false end as active,
  created_at,
  updated_at
from clients
where status in ('active', 'activate');

create or replace view document_routing_lookup
with (security_invoker = true) as
select
  id,
  client_code,
  client_name,
  client_cnpj,
  department,
  competence,
  onedrive_client_folder_id,
  onedrive_department_folder_id,
  onedrive_competence_folder_id,
  onedrive_competence_folder_id as destination_folder_id,
  client_folder_name,
  department_folder_name,
  competence_folder_name,
  concat_ws(
    '/',
    client_folder_name,
    department_folder_name,
    competence_folder_name
  ) as destination_path_readable,
  status,
  case when status in ('active', 'activate') then true else false end as active,
  last_synced_at,
  created_at
from storage_folder_map
where status in ('active', 'activate');

create or replace view active_document_rules
with (security_invoker = true) as
select
  id,
  client_code,
  file_extension,
  document_type,
  rule_type,
  rule_name,
  rule_value,
  bank_name,
  agency,
  account_number,
  sheet_name,
  column_name,
  row_number,
  match_mode,
  is_active,
  is_active as active,
  created_by,
  created_at,
  updated_at,
  last_used_at,
  hit_count,
  hit_count as hits_count,
  notes
from document_rules
where is_active = true;

alter table clients enable row level security;
alter table collaborators enable row level security;
alter table storage_folder_map enable row level security;
alter table document_rules enable row level security;
alter table document_processing_log enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'clients'
      and policyname = 'service_role_all_clients'
  ) then
    create policy service_role_all_clients
      on clients
      for all
      to service_role
      using (true)
      with check (true);
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'collaborators'
      and policyname = 'service_role_all_collaborators'
  ) then
    create policy service_role_all_collaborators
      on collaborators
      for all
      to service_role
      using (true)
      with check (true);
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'storage_folder_map'
      and policyname = 'service_role_all_storage_folder_map'
  ) then
    create policy service_role_all_storage_folder_map
      on storage_folder_map
      for all
      to service_role
      using (true)
      with check (true);
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'document_rules'
      and policyname = 'service_role_all_document_rules'
  ) then
    create policy service_role_all_document_rules
      on document_rules
      for all
      to service_role
      using (true)
      with check (true);
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'document_processing_log'
      and policyname = 'service_role_all_document_processing_log'
  ) then
    create policy service_role_all_document_processing_log
      on document_processing_log
      for all
      to service_role
      using (true)
      with check (true);
  end if;
end $$;

grant usage on schema public to service_role;

grant select, insert, update on clients to service_role;
grant select, insert, update on collaborators to service_role;
grant select, insert, update on storage_folder_map to service_role;
grant select, insert, update on document_rules to service_role;
grant select, insert, update on document_processing_log to service_role;

grant select on client_lookup to service_role;
grant select on document_routing_lookup to service_role;
grant select on active_document_rules to service_role;

notify pgrst, 'reload schema';
