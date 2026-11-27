# Ingestão raw de ABECIP e construtoras

A `dag_ingere_raw` substitui a antiga `dag_ingere_bronze`, que era apenas um
planejamento. Ela lê as resoluções aprovadas no MinIO de artefatos e grava
registros tabulares em um destino S3 independente, compatível com RustFS.
Não executa extração, não lê PDFs e não chama LLM.

## Fluxo e aprovação

```text
MinIO de artefatos
  → descoberta de schemas por domínio, entidade e competência
  → validação compatível + auditoria concluída, sem falhas de mapeamento
  → fallback: conferir também candidato, publicação e layout publicado
  → conferir document_id e execution_id com o manifesto da extração
  → selecionar a aprovação mais recente por entidade e competência
  → transformar o schema resolvido em registros planos
  → ler destino e comparar conteúdo
  → simular OU gravar condicionalmente e registrar manifesto na origem
```

O `execution_id` nos registros é o da extração original. O identificador do
fallback ou da carga raw não substitui essa origem. O manifesto de carga liga
schema, validação, auditoria, manifesto de extração, contrato e layout publicado.
Manifestos antigos sem URI do contrato podem usar a referência com nome e versão
do contrato registrada no layout publicado. Nas resoluções canônicas antigas,
quando não há uma referência histórica de layout, sua versão permanece ausente;
a DAG não atribui a versão do ponteiro atual a uma execução antiga.

Na descoberta geral, origens bloqueadas/incompletas são ignoradas com aviso no
log. Se `schema_object_keys` for informado, qualquer origem inválida faz a tarefa
falhar. Uma lista sem aprovações produz zero grupos e nenhuma escrita.

A execução é manual. As DAGs de resolução e fallback ainda não disparam a raw
automaticamente. Execute-a após a publicação dos resultados que deseja carregar.

## Destino conferido em produção

`raw` é um prefixo do bucket `data-lake-mcid`, não o nome de um bucket.
Os arquivos existentes são **arrays JSON de objetos planos**, não JSONL.
Esse formato também é consumido pelo script de promoção para stage.

```text
data-lake-mcid/
  raw/
    abecip/YYYY-MM/
      financiamentos_sbpe_mensal.json
      financiamentos_historico_anual.json
      financiamentos_por_instituicao.json
      poupanca_saldos_mensais.json
      poupanca_captacoes_mensais.json
      recursos_livres.json
    construtoras/<slug>/
      lancamentos.json
      vendas.json
```

ABECIP: cada linha contém competência, documento, execução, chave do schema,
entidade e data da exportação. As medidas ficam em colunas numéricas e os períodos
em colunas simples (`ano`, `mes`, `periodo_rotulo`, `tipo_periodo`, conforme a tabela).
Schemas antigos com `ano`/`mes` e schemas atuais com `periodo.rotulo_publicado` são
aceitos. Quando o mês publicado não contém ano, usa-se o ano da competência do
manifesto. A transformação preserva os valores resolvidos e não corrige unidades
ou números durante a carga. Dados opcionais ausentes, como recursos livres,
geram `[]`. As coleções auxiliares `observacoes_publicadas*` não criam arquivos
adicionais: a exportação mantém as seis tabelas existentes no destino.

Construtoras: cada linha representa uma observação de lançamento ou venda e
contém empresa, indicador, unidade, tipo, operação, período observado, papel e
escopo do período, valor, período de referência e origem do PDF/schema.
Somente valores brutos de número de unidades são aceitos. Não são calculadas
variações ou percentuais. Campos de contexto não resolvidos permanecem nulos.

## Parâmetros da DAG

| Parâmetro | Padrão | Uso |
| --- | --- | --- |
| `dominio` | `ambos` | `abecip`, `construtoras` ou `ambos`. |
| `entidades` | `[]` | Slugs; vazio seleciona todas. Exemplos: `abecip`, `cury`, `tenda`. |
| `periodos` | `[]` | Competências `2026-09` ou `2T26`; vazio seleciona todas. |
| `schema_object_keys` | `[]` | Opcional: chaves exatas dos schemas aprovados. Os demais filtros continuam aplicados. |
| `simular` | `true` | Apenas leitura e plano de carga; `false` habilita escrita. |

Exemplo de simulação:

```json
{
  "dominio": "ambos",
  "entidades": [],
  "periodos": ["2026-09", "2T26"],
  "schema_object_keys": [],
  "simular": true
}
```

Para efetivar a carga, use `simular: false` após conferir o destino configurado.

## Configuração local e produção

A origem usa as variáveis `MINIO_*` habituais. O destino usa `UI_HOST`, `UI_PORT`,
`UI_ACCESS_USER` e `UI_SECRET_KEY` da `.env`. O endpoint precisa responder à API
S3; não basta ser uma página de console. O Compose base repassa essas variáveis
para os processos do Airflow, inclusive quando combinado com o Compose de produção.
É necessário recriar os contêineres para aplicar novas variáveis de ambiente.
O bucket de destino deve existir; a DAG não cria buckets.

Overrides opcionais: `RAW_TARGET_ENDPOINT` (`host:porta`),
`RAW_TARGET_ACCESS_KEY`, `RAW_TARGET_SECRET_KEY`, `RAW_TARGET_BUCKET`,
`RAW_TARGET_PREFIX`, `RAW_TARGET_REGION` e `RAW_TARGET_SECURE`.
O padrão de bucket/prefixo é `data-lake-mcid` / `raw`; HTTPS no endpoint habilita
TLS, salvo override explícito. Credenciais não são registradas no plano ou manifesto.

Para testar somente no Docker local, use os overrides com `minio:9000`, credenciais
do MinIO local, `RAW_TARGET_BUCKET=raw-ingestao-teste` e `RAW_TARGET_SECURE=false`.
O utilitário abaixo fixa esse destino local, verifica também a origem e cria
somente o bucket de teste. Reutiliza as resoluções já existentes, sem extração/LLM:

```bash
docker exec -w /opt/project/dados-desestruturados ocr_airflow_scheduler \
  python scripts/validar_ingestao_raw_local.py
```

Ele espera ABECIP `2026-09` e as cinco construtoras em `2T26` no ambiente local.
Para validar outros períodos, dispare a DAG com os parâmetros correspondentes.
Os scripts antigos `exportar_schema_abecip_para_minio.py` e
`exportar_schemas_construtoras_para_minio.py` permanecem como utilitários legados;
eles não são usados pela nova DAG e não oferecem os mesmos controles de carga.

## Repetição, histórico e falhas

ABECIP substitui somente os seis arquivos da competência selecionada.
Construtoras substituem as linhas do período de referência recebido e preservam
os demais períodos no mesmo arquivo. Notas como `2T26 (a)` pertencem à partição
`2T26`; o rótulo publicado continua preservado no registro.

Conteúdo igual, desconsiderando `exportado_em`, não causa nova gravação. A data
original de exportação é preservada. Escritas usam `If-Match` com o ETag lido ou
`If-None-Match: *` para objetos novos. Conflitos causam falha e podem ser
reexecutados, em vez de sobrescrever alterações concorrentes silenciosamente.

O manifesto fica no MinIO de origem em:

```text
ingestoes/raw/<dominio>/<entidade>/execution_id=<run_id>/manifesto_ingestao_raw.json
```

Registra estado, referências de origem, destino, quantidades e resumo do conteúdo
por arquivo. É atualizado após cada objeto e ao concluir/falhar. Simulação não
grava manifesto nem destino. Não há transação entre arquivos: uma falha pode
produzir carga parcial, registrada no manifesto; repetir conclui os objetos
pendentes sem duplicar linhas. A promoção para stage deve aguardar a conclusão
da carga. Não há integração nova com Postgres operacional ou Langfuse nesta etapa.

## Validação realizada

Foram conferidos caminhos e colunas em produção apenas com leitura. No MinIO
local, ABECIP `2026-09` e Cury, Direcional, Pacaembu, Plano & Plano e Tenda `2T26`
geraram 16 arquivos (104 registros), incluindo `recursos_livres.json` vazio.
A repetição preservou os objetos e o servidor rejeitou uma escrita com ETag
antigo. Testes automatizados cobrem aprovação, linhagem, dados legados, períodos,
simulação sem escrita, falha parcial e recuperação. O resultado da carga confirma
a transformação e entrega dos valores resolvidos; não revalida o conteúdo contra
os PDFs nem comprova a correção dos valores extraídos anteriormente.

A DAG completa também concluiu pelo Airflow para as seis fontes com destino
local. Outra execução com a configuração padrão simulou os seis grupos, sem
alterar os 16 objetos ou criar manifestos. A suíte completa passou com 527 testes,
e as sete DAGs foram carregadas sem erro pelo DagBag.
