# Portal de Experimentação de Documentos e Contratos Semânticos

## Objetivo

O portal e a interface de entrada e consulta do pipeline. Ele nao substitui o
Airflow, MinIO, OpenMetadata ou Langfuse: o portal organiza o upload manual,
o acompanhamento de execucoes e a consulta dos artefatos.

```text
Usuario -> Portal/API -> MinIO + Airflow -> extracao/resolucao/fallback
```

## Responsabilidades

| Componente | Papel |
| --- | --- |
| Portal | Upload, consulta e acompanhamento. |
| MinIO | PDFs, contratos, extracoes, layouts e resultados. |
| Airflow | Execucao das DAGs. |
| OpenMetadata | Governanca, catalogo e linhagem. |
| Langfuse | Observabilidade de LLM. |

OpenMetadata e Langfuse nao recebem PDFs nem editam contratos.

## Fluxo manual implementado

O usuario informa dominio, entidade, nome, versao publicada do contrato e PDF.
O portal valida PDF e slug, grava:

```text
documentos-origem/<dominio>/<entidade>/document_id=<hash>/
```

e cria `documento_origem.json` com checksum, linhagem e URI versionada do
contrato. Depois dispara `dag_extrai_documentos_origem`, sem depender da
coleta de RI das construtoras.

O servico `portal` oferece:

- `POST /api/documents`: upload e disparo de extracao;
- `GET /api/contracts?domain=...`: contratos publicados;
- `GET /api/executions?domain=...`: extracoes persistidas;
- `GET /api/executions/...`: manifesto e artefatos de uma execucao.

A pagina `/` e a interface inicial de upload. `PORTAL_API_TOKEN`, quando
configurado, protege as APIs com `Authorization: Bearer <token>`.

## Proximas telas

1. Enviar PDF.
2. Execucoes, com estado de DAG, contrato e layout.
3. Detalhe, com PDF, manifesto, extracao, validacao, auditoria, schema
   resolvido e traces LLM.

## Contratos e fallback

No MVP, contratos sao versionados em Git e tambem podem ser publicados pelo
portal em `contratos/<dominio>/vX.Y.Z/`. A publicacao valida JSON, tipo do
artefato, versao semantica, `contrato_semantico`, `schema_saida` e consistencia
entre dominio declarado e dominio selecionado. A versao e imutavel: uma nova
alteracao exige `vX.Y.Z` novo.

O PDF somente pode selecionar uma versao publicada dentro de seu proprio
dominio. Assim, um PDF de `abecip` nao pode usar um contrato em
`contratos/construtoras/`, mesmo que as versoes tenham o mesmo numero.

Antes do envio, o portal carrega e sugere os dominios que ja possuem contrato
publicado. Se o usuario informar um dominio inexistente, a propria interface
mostra os dominios disponiveis e orienta a publicar antes um contrato
semantico para o novo dominio. A API repete a validacao: nesse caso, nenhum
PDF e persistido nem encaminhado para a extracao.

Um layout candidato continua dependente da revalidacao deterministica da DAG 2
antes de se tornar ativo.
