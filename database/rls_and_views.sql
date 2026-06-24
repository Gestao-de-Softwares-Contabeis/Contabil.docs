drop view if exists active_document_rules;
drop view if exists document_routing_lookup;
drop view if exists client_lookup;

create view client_lookup
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

create view document_routing_lookup
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

create view active_document_rules
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
