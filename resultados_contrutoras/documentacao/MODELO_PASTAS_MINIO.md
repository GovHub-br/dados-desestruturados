# Modelo de Pastas no MinIO

## Objetivo

Este documento propõe um modelo inicial de organizacao no MinIO para o pipeline de extracao e resolucao de PDFs.

O objetivo e separar com clareza:

- documentos de origem;
- artefatos brutos de extracao;
- artefatos resolvidos;
- artefatos de fallback;
- contratos e assinaturas de layout versionados.

O principio principal e: arquivos grandes e artefatos de execucao ficam no MinIO; controle, estado e linhagem ficam no Postgres.


## Principios

- caminhos devem ser previsiveis;
- cada execucao deve ser rastreavel;
- arquivos estaticos e dinamicos nao devem se misturar;
- reprocessamentos devem gerar novas execucoes, nao sobrescrever evidencias antigas;
- o path deve permitir localizar rapidamente empresa, tipo documental, documento e execucao.


## Estrutura Recomendada

Uma estrutura inicial simples e robusta pode ser:

```text
minio://ocr-cidades/
  contratos/
  layouts/
  documentos-origem/
  execucoes/
  fallback/
  curadoria/
```

### `contratos/`

Armazena contratos semanticos versionados.

Exemplo:

```text
contratos/
  construtoras/
    v1.2.0/
      contrato_semantico_construtora.json
  generico/
    v1.0.0/
      contrato_semantico_documento_generico.json
```

Uso:

- leitura pela DAG de resolucao;
- reprodutibilidade historica;
- auditoria de qual contrato foi usado em cada execucao.

### `layouts/`

Armazena layout signatures versionados.

Exemplo:

```text
layouts/
  construtoras/
    cury/
      v4.0.0/
        layout_signature_deterministico.json
    mrv/
      v1.0.0/
        layout_signature_deterministico.json
  generico/
    relatorio_trimestral/
      v1.0.0/
        layout_signature_deterministico.json
```

Uso:

- leitura pela DAG de resolucao;
- versionamento do mapa de leitura;
- comparacao entre versoes.

### `documentos-origem/`

Armazena os PDFs brutos recebidos.

Exemplo:

```text
documentos-origem/
  construtoras/
    cury/
      2026/
        2026-05-29_cury_previa_operacional_1t26.pdf
```

Boa pratica:

- nao sobrescrever o arquivo original;
- registrar checksum;
- registrar `document_id` no Postgres;
- manter nome legivel, mas nao depender dele como chave primaria.

### `execucoes/`

Armazena os artefatos gerados em cada execucao.

Exemplo:

```text
execucoes/
  construtoras/
    cury/
      document_id=cdce3fea-723b-5de2-b3e8-a3dbb90939ad/
        execution_id=20260602T103000Z_001/
          input/
            documento_origem.pdf
          extraction/
            metadata.json
            sections/
            blocks/
            tables/
            metrics/
            charts/
            text_candidates/
            text_structures/
          resolution/
            validacao_layout_signature.json
            schema_saida_resolvido.json
            auditoria_resolucao.json
          logs/
            airflow_task_log.txt
            diagnostics.log
```

Uso:

- guardar tudo que foi produzido numa execucao;
- permitir reproducao;
- facilitar troubleshooting;
- permitir comparacao entre execucoes do mesmo documento.

### `fallback/`

Armazena artefatos gerados quando a resolucao deterministica falha e a LLM precisa ajudar.

Exemplo:

```text
fallback/
  construtoras/
    cury/
      document_id=.../
        execution_id=.../
          proposta_novo_mapeamento.json
          analise_semantica_llm.json
```

Uso:

- separar claramente o caminho deterministico do caminho assistido por LLM;
- evitar contaminar a pasta de execucao normal com sugestoes ainda nao homologadas.

### `curadoria/`

Opcional. Armazena arquivos manuais de apoio.

Exemplo:

```text
curadoria/
  checklists/
  revisoes_humanas/
  homologacoes/
```

Uso:

- registrar aprovacoes humanas;
- anexar evidencias de curadoria;
- documentar mudancas de contrato ou layout.


## Convencoes de Identificacao

### `document_id`

Identificador estavel do documento logico.

Deve ser usado como pivô entre:

- documento no MinIO;
- execucoes;
- registros no Postgres;
- artefatos de fallback.

### `execution_id`

Identificador unico da execucao.

Formato recomendado:

```text
YYYYMMDDTHHMMSSZ_<sequencial>
```

Exemplo:

```text
20260602T103000Z_001
```

### `versao_contrato`

Deve apontar para a versao do contrato semanticamente aplicada.

### `versao_layout_signature`

Deve apontar para a versao do layout signature operacional usada na resolucao.


## O Que Nao Sobrescrever

Para manter rastreabilidade, nao sobrescrever:

- PDF de origem;
- artefatos brutos de extracao;
- artefatos resolvidos de execucao anterior;
- propostas de fallback.

Se houver reprocessamento, gerar nova pasta de `execution_id`.


## Caminho Minimo por Execucao

O conjunto minimo por execucao pode ser:

```text
execucoes/<dominio>/<entidade>/document_id=<id>/execution_id=<id>/
  extraction/
  resolution/
```

Onde:

- `extraction/` contem a saida do `docling_pipeline`;
- `resolution/` contem os artefatos finais do processo deterministico.


## Estrategia de Leitura pelas DAGs

### DAG de deteccao

Le:

- `documentos-origem/`

Escreve:

- `execucoes/.../input/`
- `execucoes/.../extraction/`

### DAG de resolucao

Le:

- `contratos/`
- `layouts/`
- `execucoes/.../extraction/`

Escreve:

- `execucoes/.../resolution/`

### DAG de fallback

Le:

- `execucoes/.../extraction/`
- `execucoes/.../resolution/validacao_layout_signature.json`
- `layouts/`
- `contratos/`

Escreve:

- `fallback/.../`


