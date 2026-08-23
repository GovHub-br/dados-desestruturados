# ADR 0004 — Resolução determinística com fallback LLM controlado

- Status: Aceito
- Data: 2026-06-23
- Fonte de verdade: `specs/platform/SPEC.md`

## Responsáveis

Mateus de Castro

## Contexto

PDFs variam de layout, mas o resultado precisa ser repetível, auditável e
adequado a qualquer domínio definido por contrato semântico.

## Drivers da decisão

- Precisão e rastreabilidade;
- generalidade guiada por contrato;
- controle de custo de LLM;
- recuperação automática de layouts.

## Alternativas consideradas

### Resolução determinística e LLM apenas para propor layout

**Vantagens**

- Valores finais têm proveniência explícita;
- candidato pode ser revalidado antes de publicar;
- LLM fica limitada à descoberta/mapeamento.

**Desvantagens**

- Mais etapas e dependência da qualidade dos artefatos extraídos.

### LLM extrair diretamente o schema de saída

**Vantagens**

- Menos código inicial.

**Desvantagens**

- Piora auditoria, repetição, custo e correção localizada.

### Somente layouts manuais

**Vantagens**

- Máxima previsibilidade.

**Desvantagens**

- Não escala para novos documentos ou mudanças de layout.

## Decisão

A DAG 2 executa a resolução determinística a partir de contrato e layout. A
DAG 3 só é acionada diante de falha ou ausência de layout, seleciona evidências
e propõe um candidato que retorna à validação determinística.

## Consequências

- O custo e a incerteza da LLM ficam restritos a exceções.
- Os resultados finais têm origem explícita em artefatos de extração.
- O mesmo mecanismo atende novos domínios sem regras de negócio no código base.

## Riscos

- Contexto ou reasoning podem esgotar o orçamento da LLM;
- validação insuficiente pode aceitar fonte sem evidência adequada.

## Implementação

- A DAG 2 resolve contrato + layout e produz validação/auditoria;
- a DAG 3 classifica falhas, seleciona evidências e propõe candidato;
- respostas e metadados LLM são persistidos;
- publicação segue a ADR 0002.

## Critérios para reconsideração

Revisitar se fallback for predominante, se o custo impedir operação ou se outra
tecnologia fornecer descoberta auditável sem LLM.

## Referências

- `docs/architecture/resolucao-deterministica-schema-saida-dag2.md`;
- `docs/architecture/fallback-llm-e-geracao-layout-dag3.md`;
- ADR 0002 e ADR 0005.
