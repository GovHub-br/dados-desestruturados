---
name: criar-contrato-semantico
description: Criar, revisar e evoluir contratos semânticos para famílias de PDFs e documentos desestruturados. Use ao definir quais dados brutos devem ser extraídos, o schema de saída, granularidades, períodos, unidades, campos obrigatórios e a relação entre contrato, layout signature e resolução determinística da DAG 2.
---

# Criar Contrato Semântico

## Objetivo

Defina o significado e a forma estável da saída antes de localizar dados no
PDF. O contrato determina **o que** será entregue; o layout signature define
**onde e como** cada campo será encontrado em uma família documental.

Leia antes:

- `specs/platform/CONTEXT.md`;
- `specs/platform/SPEC.md`;
- `docs/architecture/arquitetura-orquestracao-airflow.md`;
- um contrato e um layout existentes da família mais próxima;
- `src/document_intelligence/application/use_cases/resolution/resolve_schema.py` se houver mudança
  que exija nova capacidade da DAG 2.

Para modelo e checklist detalhados, leia
`references/modelo-e-checklist.md`.

## Princípios obrigatórios

- Modele fatos de negócio, não títulos, páginas, índices de tabela ou nomes de
  arquivo.
- Mantenha chaves estáveis entre edições do mesmo tipo de documento. Períodos,
  empresa, modalidade e instituição são valores de observação, não sufixos de
  chave.
- Preserve valores observados e sua unidade publicada. Não esconda escala:
  `valor_bilhoes` e `quantidade_mil` não são equivalentes a milhões ou unidades.
- Deixe percentuais, participações, rankings e variações calculáveis para
  transformação posterior, salvo quando forem um fato de negócio explicitamente
  solicitado.
- Separe fatos com granularidades diferentes em coleções distintas. Uma série
  mensal não substitui um acumulado publicado, um histórico anual ou uma abertura
  por instituição.
- Não introduza no contrato inferências que dependam de uma empresa, de uma
  convenção de mês ou da aparência atual do PDF.

## Processo

1. Delimite a família documental e a pergunta de negócio. Declare documento,
   fonte, população, periodicidade esperada e quais fatos brutos serão usados
   depois.
2. Liste cada fato como uma observação: dimensões, medidas, unidade, escala e
   período. Identifique sua granularidade antes de escrever o JSON.
3. Decida a estrutura do `schema_saida`. Use objetos para contexto único do
   documento e listas para observações repetíveis. Cada lista deve ter uma
   granularidade clara.
4. Identifique o contrato no nível superior com `nome`, `dominio`, `entidade`,
   `fonte`, `tipo_documento`, `versao` e `descricao`. O domínio é a chave de
   seleção do contrato no MinIO; entidade identifica a fonte dentro dele.
5. Defina `contrato_semantico` com princípios, entidades reutilizáveis e
   `requisitos_mapeamento`. Defina `schema_saida` como o formato concreto que
   a DAG 2 deve preencher.
6. Marque o que é obrigatório. Só torne obrigatório um campo cujo não
   preenchimento realmente invalida o uso pretendido do documento.
7. Faça a prova de mapeabilidade: para cada campo final, diga qual artefato de
   extração poderá fornecê-lo. Só então construa o layout signature.
8. Revise com uma extração real e valide que o schema resolvido preserva os
   valores brutos, a unidade e a granularidade prometidas.

## Campos dinâmicos, literais e requisitos de mapeamento

A DAG interpreta cada folha de `schema_saida` de forma determinística:

- um descritor de tipo exato, como `string`, `number`, `integer`, `boolean` ou
  `string | null`, é **dinâmico**: seu valor pode vir de um artefato e precisa
  de mapeamento quando fizer parte do caso de uso;
- qualquer outro valor é um **literal do contrato**: a DAG 2 o reaplica no
  resultado e a LLM não deve procurá-lo nem mapeá-lo. Isso inclui, por exemplo,
  `"sbpe"`, `"mensal"`, `"unidades"` e um tipo documental estável.

Não use textos como `"mensal | acumulado_ano"` ou `"aquisicao | construcao"`
para descrever valores possíveis: eles são literais para o resolvedor. Declare
o campo como `string` e mantenha os valores permitidos em
`contrato_semantico.entidades` quando essa informação for útil.

Todo contrato usado pela DAG 3 precisa conter
`contrato_semantico.requisitos_mapeamento.campos_obrigatorios`. É uma lista
não vazia dos paths dinâmicos que precisam ter evidência. Cada `path` deve
existir no `schema_saida` e não pode apontar para uma folha literal.

Use o path da coleção quando a origem produz registros completos, como
`linhas_de_tabela` ou `juncao_de_registros_json`. Use uma folha quando a
origem resolve apenas aquele valor. Para exigir observações específicas de uma
lista, use `observacoes_obrigatorias` com `seletores` e, quando necessário,
`campos_contexto_obrigatorios`; esses campos de contexto são irmãos do valor
na mesma observação. Não declare seletores para períodos, entidades ou linhas
que ainda dependem do conteúdo de cada novo documento.

## Como o contrato orienta o layout

Construa `mapeamento_canonico` somente para campos presentes no
`schema_saida`. O formato do contrato decide o formato do mapeamento:

- valor dinâmico único do documento: `campo_json`, `bloco_textual` ou outra
  origem simples; valor constante pertence ao contrato e não ao mapeamento;
- série ou lista repetível: `linhas_de_tabela` com campos e seletores
  declarados no layout;
- uma observação composta por artefatos diferentes: declare fontes e chave de
  associação com `juncao_de_registros_json` no layout. Use isso apenas quando
  o contrato exige os valores no mesmo item; caso contrário, modele listas
  separadas no contrato.

O layout pode conhecer caminhos de arquivo, índices, rótulos aceitos e padrões
de mudança. O contrato não deve conter esses detalhes físicos.

## Revisão antes de aprovar

- Cada medida tem unidade e escala inequívocas?
- Cada observação possui o contexto de período necessário para não permitir
  somas incorretas?
- Há alguma métrica derivada que deveria sair do contrato de extração?
- Duas fontes de granularidade diferente foram misturadas numa mesma lista?
- Cada campo obrigatório é mapeável por artefato de extração ou metadado
  publicado anteriormente?
- `campos_obrigatorios` cobre somente campos dinâmicos essenciais e está
  consistente com os paths do `schema_saida`?
- Os valores fixos foram modelados como literais, e não como trabalho para a
  LLM ou como pseudo-enums separados por `|`?
- O layout pode mudar sem exigir mudança no contrato? Se não, a modelagem está
  provavelmente presa demais ao PDF atual.
- O schema final pode ser inserido em uma camada estruturada sem adivinhar a
  unidade, período ou dimensão do dado?

## Evolução

Versione o contrato quando alterar o significado, a estrutura de saída, a
unidade, a escala, a granularidade ou a obrigatoriedade. Alterações apenas de
posição, arquivo, seletor ou título pertencem ao layout signature. Não altere
um contrato ativo silenciosamente: publique a nova versão e revalide o layout
contra ela.
