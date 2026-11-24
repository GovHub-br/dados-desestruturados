# Carga histórica manual de PDFs

A DAG `dag_carga_historica_pdfs` coleta documentos antigos da ABECIP e prévias
operacionais das construtoras e encaminha as etapas pendentes ao fluxo existente.
Ela usa `schedule=None` e é disparada manualmente pelo Airflow.

## Parâmetros

| Campo | Valores e comportamento |
| --- | --- |
| `dominio` | `abecip`, `construtoras` ou `ambos`. |
| `data_inicial` | Data ISO `AAAA-MM-DD`, obrigatória. |
| `data_final` | Data ISO `AAAA-MM-DD`, obrigatória, igual ou posterior à inicial. |
| `construtoras` | Lista de slugs. `[]` seleciona todas as fontes cadastradas. Para `abecip`, use `[]`. |
| `executar_pipeline` | `true` por padrão. Com `false`, coleta e verifica PDFs e registra os encaminhamentos previstos, sem disparar as DAGs seguintes. |

As datas delimitam a **competência**. ABECIP usa o mês e construtoras usam o
trimestre. São incluídos os períodos que intersectam o intervalo, com os extremos
incluídos. A data de publicação pode ser posterior à competência.

As fontes de construtoras atualmente cadastradas são `cury`, `direcional`,
`pacaembu`, `plano-plano` e `tenda`. A descoberta utiliza os mesmos clientes
de RI da coleta periódica. Outros documentos de RI e outras empresas dependem
de ampliar o cadastro e os critérios da fonte.

## Exemplos de configuração

ABECIP em janeiro e fevereiro de 2025, com processamento completo.

```json
{
  "dominio": "abecip",
  "data_inicial": "2025-01-01",
  "data_final": "2025-02-28",
  "construtoras": [],
  "executar_pipeline": true
}
```

Somente a Cury, no segundo trimestre de 2026.

```json
{
  "dominio": "construtoras",
  "data_inicial": "2026-04-01",
  "data_final": "2026-06-30",
  "construtoras": ["cury"],
  "executar_pipeline": true
}
```

Teste de coleta para ABECIP e todas as construtoras, sem executar extração.

```json
{
  "dominio": "ambos",
  "data_inicial": "2026-04-01",
  "data_final": "2026-06-30",
  "construtoras": [],
  "executar_pipeline": false
}
```

## Descoberta e deduplicação

1. A ABECIP é consultada pela página oficial e pela paginação do botão
   carregar mais. O cliente percorre a listagem e filtra pela competência.
   Inconsistências entre a descrição e o nome do PDF ficam nos logs e metadados,
   seguindo a regra existente de preferência pela descrição.
2. As construtoras são consultadas por trimestre e por empresa selecionada.
3. Cada PDF é baixado para conferir o SHA-256. Esse download de verificação
   pode acontecer mesmo quando o arquivo já existe no MinIO.
4. O PDF existente é reutilizado pelo conteúdo, inclusive nos caminhos antigos
   e nas entradas feitas pelo portal. A origem ausente é gravada normalmente.
5. A extração é considerada completa quando há manifesto com uma lista de
   artefatos e todos os objetos referenciados existem no MinIO.
6. Uma extração existente segue diretamente para resolução quando ainda não
   há auditoria aprovada ou publicação de layout vinculada àquela extração.
   Documento já concluído é pulado.

O SHA-256 continua sendo registrado integralmente no manifesto. Uma interrupção
entre a gravação do PDF e a do manifesto pode ser recuperada pela próxima carga.
A carga histórica permite recuperar a extração de origens externas já existentes.

## Encadeamento

```text
DAG histórica
  → descoberta por domínio, empresa e competência
  → download de verificação e persistência no MinIO
  → escolha da próxima etapa
      PDF sem extração completa → dag_extrai_documentos_origem
      extração sem resolução    → dag_resolve_schema_saida
      documento concluído       → pular
  → DAG 2 encaminha criação inicial para dag_valida_e_fallback_llm
  → candidato retorna à DAG 2 para resolução e revalidação
  → DAG 3 publica o layout aprovado
```

Com `executar_pipeline=false`, o fluxo termina após a coleta e a preparação dos
encaminhamentos. Os logs de `preparar_extracao` e `preparar_resolucao` mostram
o que seria disparado. Os operadores de disparo ficam pulados por receberem
listas vazias. Esse modo grava PDFs e manifestos no MinIO.

Com `true`, as DAGs filhas precisam estar disponíveis e despausadas, com contrato,
runner e provedor LLM configurados. O sucesso da DAG histórica confirma coleta e
encaminhamento. O resultado completo é acompanhado nas execuções filhas e nos
artefatos de revalidação/publicação.

## IDs legíveis no MinIO

Novos documentos recebem data e hora da primeira entrada em UTC, com precisão
de segundos, seguidas dos primeiros 32 caracteres do SHA-256.

```text
document_id=2026-11-24_18-03-35Z__0123456789abcdef0123456789abcdef/
```

Essa data representa a entrada no armazenamento. O mês ou trimestre reportado
continua em `ano=` e `periodo=`. O mesmo ID acompanha extração, resolução e
fallback. Documentos antigos continuam reconhecidos por seus IDs e caminhos
originais.

Uma reserva por SHA-256 em
`identidades-documentos/<dominio>/<entidade>/sha256=<hash>.json` usa escrita
condicional no MinIO. Assim, produtores concorrentes recebem o mesmo ID.
A reserva pode existir antes do PDF em uma execução interrompida e é reutilizada
na retomada. A imagem do portal inclui o módulo compartilhado de identidade e
precisa ser reconstruída para usar esse formato nos novos uploads.

## Código

- [DAG manual](../../airflow/dags/coleta/dag_carga_historica_pdfs.py).
- [Caso de uso histórico](../../src/document_processing/application/use_cases/documents/historical_ingestion.py).
- [Cliente ABECIP](../../src/document_processing/infrastructure/abecip/informativos_gateway.py).
- [Cliente de RI](../../src/document_processing/infrastructure/ri/ri_results_gateway.py).
- [Reserva de identidade](../../src/document_processing/infrastructure/storage/document_identity_registry.py).

## Evidência do teste local em 24/11/2026

A execução `manual__2026-11-24T18:12:04.105356+00:00` terminou em
`success`, com `dominio=ambos`, intervalo de 01/04/2026 a 30/06/2026,
`construtoras=[]` e `executar_pipeline=false`.

| Fonte | Competência | Resultado da coleta |
| --- | --- | --- |
| ABECIP | 2026-04 | PDF existente, extração e resolução já concluídas. |
| ABECIP | 2026-05 | PDF existente, extração e resolução já concluídas. |
| ABECIP | 2026-06 | PDF oficial novo, gravado com ID por data, aguardando extração. |
| Cury | 2T26 | PDF existente, extração e resolução já concluídas. |
| Direcional | 2T26 | PDF existente, extração e resolução já concluídas. |
| Pacaembu | 2T26 | PDF existente, extração e resolução já concluídas. |
| Plano&Plano | 2T26 | PDF existente, extração e resolução já concluídas. |
| Tenda | 2T26 | PDF existente, extração e resolução já concluídas. |

Foram oito documentos, um novo e sete duplicados. Os oito passos de persistência
terminaram com sucesso. `disparar_extracao` e `disparar_resolucao` ficaram
`skipped`; a consulta ao banco do Airflow confirmou zero execuções filhas
durante os testes. A repetição da coleta de junho reutilizou o mesmo ID e PDF.
O SHA-256 do original gravado foi conferido.

O teste também identificou que a Tenda passou a usar MZIQ. O cadastro foi
atualizado para a empresa e a categoria oficiais atuais. O adaptador Sumaq/Next
continua disponível para fontes que utilizem esse backend.

A reserva de identidade foi testada no MinIO local com quatro produtores
concorrentes, que receberam o mesmo ID. O objeto temporário desse teste foi
removido. A suíte completa executada no contêiner terminou com 501 testes
aprovados.
