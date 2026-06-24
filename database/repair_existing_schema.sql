create extension if not exists pgcrypto;

drop view if exists active_document_rules;
drop view if exists document_routing_lookup;
drop view if exists client_lookup;

create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create table if not exists clients (
  id uuid primary key default gen_random_uuid(),
  name text not null
);

alter table clients add column if not exists name text;
alter table clients add column if not exists normalized_name text;
alter table clients add column if not exists cnpj text;
alter table clients add column if not exists aliases text[] default '{}';
alter table clients add column if not exists bank_accounts jsonb default '[]'::jsonb;
alter table clients add column if not exists active boolean default true;
alter table clients add column if not exists created_at timestamptz default now();
alter table clients add column if not exists updated_at timestamptz default now();
update clients
set
  name = coalesce(nullif(name, ''), id::text),
  normalized_name = coalesce(normalized_name, regexp_replace(lower(coalesce(name, '')), '[^a-z0-9]+', ' ', 'g')),
  aliases = coalesce(aliases, '{}'),
  bank_accounts = coalesce(bank_accounts, '[]'::jsonb),
  active = coalesce(active, true),
  created_at = coalesce(created_at, now()),
  updated_at = coalesce(updated_at, now());

create table if not exists collaborators (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  department text not null,
  status text not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists collaborators_status_name_idx
  on collaborators (status, name);

insert into collaborators (name, department, status)
values
  ('Erlane', 'contabil', 'active'),
  ('Alessandro Farias', 'contabil', 'active'),
  ('Heverton Costa', 'contabil', 'active'),
  ('Simone', 'contabil', 'active')
on conflict (name) do nothing;

create table if not exists storage_folder_map (
  id uuid primary key default gen_random_uuid(),
  client_id uuid,
  document_type text,
  destination_folder text
);

alter table storage_folder_map add column if not exists active boolean default true;
alter table storage_folder_map add column if not exists client_id uuid;
alter table storage_folder_map add column if not exists document_type text;
alter table storage_folder_map add column if not exists destination_folder text;
alter table storage_folder_map add column if not exists created_by text default 'sistema';
alter table storage_folder_map add column if not exists updated_by text;
alter table storage_folder_map add column if not exists created_at timestamptz default now();
alter table storage_folder_map add column if not exists updated_at timestamptz default now();
update storage_folder_map
set
  active = coalesce(active, true),
  created_by = coalesce(created_by, 'sistema'),
  created_at = coalesce(created_at, now()),
  updated_at = coalesce(updated_at, now());

create table if not exists document_rules (
  id uuid primary key default gen_random_uuid(),
  client_id uuid,
  rule_type text,
  document_type text
);

alter table document_rules add column if not exists institution text;
alter table document_rules add column if not exists client_id uuid;
alter table document_rules add column if not exists rule_type text;
alter table document_rules add column if not exists document_type text;
alter table document_rules add column if not exists pattern jsonb default '{}'::jsonb;
alter table document_rules add column if not exists active boolean default true;
alter table document_rules add column if not exists created_by text default 'sistema';
alter table document_rules add column if not exists created_at timestamptz default now();
alter table document_rules add column if not exists updated_at timestamptz default now();
alter table document_rules add column if not exists last_used_at timestamptz;
alter table document_rules add column if not exists hits_count integer default 0;
update document_rules
set
  pattern = coalesce(pattern, '{}'::jsonb),
  active = coalesce(active, true),
  created_by = coalesce(created_by, 'sistema'),
  created_at = coalesce(created_at, now()),
  updated_at = coalesce(updated_at, now()),
  hits_count = coalesce(hits_count, 0);

create table if not exists document_processing_log (
  id uuid primary key default gen_random_uuid()
);

alter table document_processing_log add column if not exists created_at timestamptz default now();
alter table document_processing_log add column if not exists user_name text default 'sistema';
alter table document_processing_log add column if not exists user_department text;
alter table document_processing_log add column if not exists action text default 'EVENTO_IMPORTADO';
alter table document_processing_log add column if not exists client_id uuid;
alter table document_processing_log add column if not exists client_name text;
alter table document_processing_log add column if not exists original_filename text;
alter table document_processing_log add column if not exists file_extension text;
alter table document_processing_log add column if not exists file_size_bytes bigint;
alter table document_processing_log add column if not exists file_hash text;
alter table document_processing_log add column if not exists competence text;
alter table document_processing_log add column if not exists document_type text;
alter table document_processing_log add column if not exists institution text;
alter table document_processing_log add column if not exists score integer;
alter table document_processing_log add column if not exists score_band text;
alter table document_processing_log add column if not exists matched_by text;
alter table document_processing_log add column if not exists ai_used boolean default false;
alter table document_processing_log add column if not exists sender_name text;
alter table document_processing_log add column if not exists sender_department text;
alter table document_processing_log add column if not exists origin_channel text;
alter table document_processing_log add column if not exists status text default 'RECEBIDO';
alter table document_processing_log add column if not exists destination_folder text;
alter table document_processing_log add column if not exists extracted_text text;
alter table document_processing_log add column if not exists observation text;
alter table document_processing_log add column if not exists metadata jsonb default '{}'::jsonb;
update document_processing_log
set
  created_at = coalesce(created_at, now()),
  user_name = coalesce(user_name, sender_name, 'sistema'),
  action = coalesce(action, 'EVENTO_IMPORTADO'),
  ai_used = coalesce(ai_used, false),
  status = coalesce(status, 'RECEBIDO'),
  metadata = coalesce(metadata, '{}'::jsonb);

create index if not exists clients_active_name_idx
  on clients (active, normalized_name);

create index if not exists storage_folder_map_lookup_idx
  on storage_folder_map (client_id, document_type, active);

create index if not exists document_rules_active_idx
  on document_rules (active, client_id, rule_type);

create index if not exists document_rules_pattern_gin_idx
  on document_rules using gin (pattern);

create index if not exists document_processing_log_file_hash_idx
  on document_processing_log (file_hash, created_at desc);

create index if not exists document_processing_log_status_idx
  on document_processing_log (status, created_at desc);

create index if not exists document_processing_log_filters_idx
  on document_processing_log (client_id, user_name, created_at desc);

create index if not exists document_processing_log_department_idx
  on document_processing_log (user_department, created_at desc);

drop trigger if exists clients_set_updated_at on clients;
create trigger clients_set_updated_at
before update on clients
for each row execute function set_updated_at();

drop trigger if exists collaborators_set_updated_at on collaborators;
create trigger collaborators_set_updated_at
before update on collaborators
for each row execute function set_updated_at();

drop trigger if exists storage_folder_map_set_updated_at on storage_folder_map;
create trigger storage_folder_map_set_updated_at
before update on storage_folder_map
for each row execute function set_updated_at();

drop trigger if exists document_rules_set_updated_at on document_rules;
create trigger document_rules_set_updated_at
before update on document_rules
for each row execute function set_updated_at();

create or replace view client_lookup as
select
  id,
  name,
  normalized_name,
  cnpj,
  aliases,
  bank_accounts,
  active,
  created_at,
  updated_at
from clients
where active = true;

create or replace view document_routing_lookup as
select
  sfm.id,
  sfm.client_id,
  c.name as client_name,
  sfm.document_type,
  sfm.destination_folder,
  sfm.active,
  sfm.created_at,
  sfm.updated_at
from storage_folder_map sfm
join clients c on c.id = sfm.client_id
where sfm.active = true
  and c.active = true;

create or replace view active_document_rules as
select
  dr.id,
  dr.client_id,
  c.name as client_name,
  dr.rule_type,
  dr.document_type,
  dr.institution,
  dr.pattern,
  dr.active,
  dr.created_by,
  dr.created_at,
  dr.updated_at,
  dr.last_used_at,
  dr.hits_count
from document_rules dr
join clients c on c.id = dr.client_id
where dr.active = true
  and c.active = true;

grant usage on schema public to service_role;

grant select on public.clients to service_role;
grant select on public.client_lookup to service_role;

grant select, insert, update on public.document_rules to service_role;
grant select on public.active_document_rules to service_role;

grant select, insert, update on public.storage_folder_map to service_role;
grant select on public.document_routing_lookup to service_role;

grant select, insert, update on public.document_processing_log to service_role;

grant select, insert, update on public.collaborators to service_role;

notify pgrst, 'reload schema';
