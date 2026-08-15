# Portal de Experimentacao de Documentos

## Objetivo

O portal e a interface de uso do pipeline de documentos. Ele nao substitui
Airflow, MinIO, OpenMetadata ou Langfuse: organiza a entrada manual de PDFs,
o acompanhamento das execucoes e a consulta dos resultados produzidos por
esses componentes.

```text
Usuario
  -> Portal web
  -> API do portal
  -> MinIO + Airflow
  -> extracao, resolucao e fallback
  -> resultados exibidos no portal
```

## Papel de cada componente

| Componente | Responsabilidade |
| --- | --- |
| Portal | Experiencia do usuario: envio, consulta e acompanhamento. |
| API do portal | Autorizacao, validacao de entrada, escrita controlada no MinIO e disparo de DAGs. |
| MinIO | Fonte operacional de PDFs, contratos versionados, artefatos, layouts e resultados. |
| Airflow | Execucao das etapas de extracao, resolucao e fallback. |
| OpenMetadata | Catalogo e governanca: dono, dominio, descricao, linhagem e classificacao. |
| Langfuse | Observabilidade das chamadas LLM: prompt, resposta, tokens, latencia e retries. |
| Postgres operacional | Estado resumido das execucoes e ponteiros para artefatos no MinIO. |

OpenMetadata e Langfuse nao devem ser usados como repositorio de PDFs ou como
editor de contratos. O primeiro governa os ativos; o segundo observa o uso da
LLM.

## Fluxo de envio manual

Na tela de envio, a pessoa informa:

- dominio documental, como `construtoras`, `abecip` ou `saude`;
- entidade, como `cury` ou `abecip`;
- arquivo PDF;
- versao publicada do contrato semantico.

A API valida tipo e tamanho do arquivo, persiste o PDF em um caminho como:

```text
documentos-origem/<dominio>/<entidade>/<document_id>/arquivo.pdf
```

Em seguida, registra a execucao e dispara a extracao. A entrada manual deve
ser independente da coleta automatica de PDFs em sites: a primeira recebe um
arquivo ja escolhido; a segunda continua sendo uma fonte automatizada.

## Telas iniciais

### 1. Enviar PDF

Permite criar uma nova execucao manual, selecionando dominio, entidade,
contrato e arquivo. Deve mostrar a versao do contrato antes da confirmacao.

### 2. Execucoes

Lista documentos processados e seu estado resumido.

| Documento | Contrato | Extracao | Resolucao | Layout | Resultado |
| --- | --- | --- | --- | --- | --- |
| relatorio.pdf | construtoras v1.7.0 | concluida | compativel | v4.0.0 | disponivel |
| boletim.pdf | abecip v2.0.1 | concluida | fallback LLM | candidato | em analise |

### 3. Detalhe da execucao

Centraliza a evidencia operacional, com visualizacao ou links para:

- PDF de origem;
- manifesto de execucao;
- artefatos de extracao;
- contrato e layout usados;
- validacao de layout;
- auditoria de resolucao;
- `schema_saida_resolvido.json`;
- entradas, respostas e erros do fallback LLM, quando houver.

## Contratos semanticos

No primeiro MVP, contratos sao versionados em Git e publicados de forma
imutavel no MinIO em `contratos/<dominio>/vX.Y.Z/`. O portal deve permitir
selecionar e consultar contratos publicados, mas nao precisa oferecer edicao
livre de JSON ainda.

Um usuario autorizado podera publicar nova versao somente apos validacao do
schema do contrato e revisao definida pela equipe. Um editor de contratos no
portal pode ser uma evolucao posterior.

## Fallback LLM

Quando a resolucao deterministica falhar, o portal deve exibir o motivo, os
artefatos selecionados, o candidato de layout e a revalidacao. O Langfuse
complementa essa tela com traces de LLM, sem se tornar a fonte operacional da
execucao.

A publicacao de um layout continua condicionada a revalidacao deterministica
da DAG 2. Uma revisao humana opcional pode ser adicionada antes da publicacao.

## Perfis iniciais

- **Administrador:** configura dominios, acessos e integracoes.
- **Autor de contrato:** prepara e solicita a publicacao de contratos.
- **Operador:** envia PDFs, dispara reprocessamentos e acompanha execucoes.
- **Leitor:** consulta resultados e auditorias sem alterar ativos.

