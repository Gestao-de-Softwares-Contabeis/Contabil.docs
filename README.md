# Contabil.docs

MVP local para catalogacao, identificacao, roteamento e envio controlado de documentos contabeis.

## Objetivo

O projeto recebe documentos enviados por usuarios internos do escritorio contabil, extrai conteudo, identifica cliente, competencia, tipo documental e instituicao, consulta a rota de destino no Supabase e prepara o envio para automacoes externas.

O foco atual e velocidade operacional, simplicidade de manutencao e seguranca: documentos com conflito ou dados obrigatorios ausentes nao sao enviados automaticamente.

## Arquitetura Atual

- **Python 3.12**: core de processamento, parsers, regras, servicos e repositorios.
- **Streamlit**: interface local do MVP para upload, parametrizacao e historico.
- **Supabase**: banco operacional, views de lookup, regras parametrizadas, rotas e logs.
- **Supabase Storage**: area de entrada para arquivos prontos para envio.
- **OpenAI API**: fallback de identificacao quando regras deterministicas nao resolvem.
- **n8n**: webhook de integracao para receber `signed_url` e metadados do arquivo.
- **OneDrive**: destino final previsto via fluxo n8n, sem logica direta no core Python.

## Estrutura

```text
ai/              fallback OpenAI
app/             configuracoes e helpers da interface
database/        schema, views, grants e scripts auxiliares SQL
models/          modelos Pydantic
pages/           telas Streamlit
parsers/         leitura de PDF, OFX, XLS, XLSX, CSV e TXT
repositories/    acesso ao Supabase
rules/           matching de regras parametrizadas
services/        regras de negocio e integracoes desacopladas
tests/           testes unitarios do core
utils/           normalizacao, datas, hashes e logs estruturados
```

## Fluxo De Processamento

1. Receber arquivo local ou upload.
2. Identificar extensao.
3. Extrair texto/conteudo por parser especifico.
4. Gerar hash, tamanho, nome original e resumo estruturado.
5. Identificar cliente nesta ordem:
   - `client_code` explicito;
   - CNPJ;
   - nome/razao social;
   - regras parametrizadas ativas;
   - agencia e conta bancaria;
   - nome de socio;
   - OpenAI como fallback;
   - revisao manual.
6. Resolver competencia por tipo documental.
7. Identificar instituicao por regras deterministicas antes de IA.
8. Consultar `document_routing_lookup` no Supabase.
9. Gerar nome final no formato:

```text
CLIENTE_CURTO - INSTITUICAO - MMYYYY - document_type.ext
```

10. Definir status:

```text
PRONTO_ENVIO
REVISAR
ERRO_IDENTIFICACAO
```

11. Apenas quando `PRONTO_ENVIO`:
   - subir arquivo no Supabase Storage;
   - gerar `signed_url`;
   - montar payload completo;
   - enviar POST para o webhook n8n.

Documentos `REVISAR` ou `ERRO_IDENTIFICACAO` nao sao enviados automaticamente.

## Supabase

Objetos principais:

- `clients`
- `collaborators`
- `storage_folder_map`
- `document_rules`
- `document_processing_log`

Views:

- `client_lookup`
- `document_routing_lookup`
- `active_document_rules`

As credenciais ficam somente em `.env`, que e ignorado pelo Git.

## n8n

O core envia para o webhook configurado por variavel de ambiente:

```text
N8N_WEBHOOK_URL
N8N_TEST_WEBHOOK_URL
```

Payload principal:

```json
{
  "signed_url": "...",
  "storage_path": "...",
  "bucket": "incoming-documents",
  "new_file_name": "...",
  "destination_folder_id": "...",
  "destination_path_readable": "...",
  "original_file_name": "...",
  "detected_client_code": "...",
  "competence": "YYYY-MM",
  "document_type": "..."
}
```

## Como Rodar Localmente

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Para banco novo, execute manualmente no SQL Editor do Supabase:

```text
database/schema.sql
database/rls_and_views.sql
database/grants.sql
```

Nunca execute scripts SQL destrutivos sem revisao.

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest tests
```

Scripts isolados:

```powershell
.\.venv\Scripts\python.exe test_storage_upload.py
.\.venv\Scripts\python.exe test_send_to_n8n.py --webhook-url "URL_DO_WEBHOOK_TESTE"
```

## Status Atual

- Core de processamento funcional.
- Identificacao por regras, CNPJ, nome, banco/conta, socio e OpenAI fallback.
- Resolucao manual de conflito por regra corretiva `manual_override`.
- Supabase Storage validado.
- Envio ao n8n integrado ao `CoreProcessor` somente para `PRONTO_ENVIO`.
- Frontend Streamlit existente para MVP, sem complexidade adicional de autenticacao.
- OneDrive permanece desacoplado no fluxo n8n.
