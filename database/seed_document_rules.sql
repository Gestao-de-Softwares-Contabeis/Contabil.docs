insert into document_rules (
  client_code,
  rule_type,
  rule_name,
  rule_value,
  bank_name,
  agency,
  account_number,
  match_mode,
  is_active,
  created_by,
  notes
)
select
  seed.client_code,
  seed.rule_type,
  seed.rule_name,
  seed.rule_value,
  seed.bank_name,
  seed.agency,
  seed.account_number,
  seed.match_mode,
  true,
  'codex',
  seed.notes
from (
  values
    (
      '147',
      'bank_account',
      'RZ COMERCIO DE BIJUTERIAS - Banco do Brasil',
      '34789/1388932',
      null,
      '34789',
      '1388932',
      'exact',
      'Regra inicial solicitada para RZ COMERCIO DE BIJUTERIAS.'
    ),
    (
      '141',
      'bank_account',
      'REZENDE E TEIXEIRA COMERCIO DE JOIAS - Itau',
      '542/984927',
      null,
      '542',
      '984927',
      'exact',
      'Regra inicial solicitada para REZENDE E TEIXEIRA COMERCIO DE JOIAS.'
    ),
    (
      '210',
      'bank_account',
      'TL ACADEMIA DE GINASTICA LTDA - Sicoob',
      '50040/11360828',
      null,
      '50040',
      '11360828',
      'exact',
      'Regra inicial solicitada para TL ACADEMIA DE GINASTICA LTDA.'
    ),
    (
      '147',
      'partner_name',
      'Socio - WALESKA DE OLIVEIRA GONCALVES REZENDE',
      'WALESKA DE OLIVEIRA GONCALVES REZENDE',
      null,
      null,
      null,
      'contains',
      'Regra inicial de socio parametrizavel.'
    ),
    (
      '141',
      'partner_name',
      'Socio - VANESSA CUNHA REZENDE',
      'VANESSA CUNHA REZENDE',
      null,
      null,
      null,
      'contains',
      'Regra inicial de socio parametrizavel.'
    ),
    (
      '210',
      'partner_name',
      'Socio - JURANDIR RIBEIRO DE LAVOR',
      'JURANDIR RIBEIRO DE LAVOR',
      null,
      null,
      null,
      'contains',
      'Regra inicial de socio parametrizavel.'
    )
) as seed (
  client_code,
  rule_type,
  rule_name,
  rule_value,
  bank_name,
  agency,
  account_number,
  match_mode,
  notes
)
where not exists (
  select 1
  from document_rules existing
  where existing.client_code = seed.client_code
    and existing.rule_type = seed.rule_type
    and coalesce(existing.rule_value, '') = coalesce(seed.rule_value, '')
    and coalesce(existing.agency, '') = coalesce(seed.agency, '')
    and coalesce(existing.account_number, '') = coalesce(seed.account_number, '')
    and existing.is_active = true
);

notify pgrst, 'reload schema';
