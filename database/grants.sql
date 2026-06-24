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
