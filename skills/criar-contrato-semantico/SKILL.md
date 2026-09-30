---
name: criar-contrato-semantico
description: Criar, revisar e evoluir contratos semânticos para famílias de PDFs e documentos desestruturados. Use ao definir quais dados brutos devem ser extraídos, o schema de saída, granularidades, períodos, unidades, campos obrigatórios, chaves de item, papéis e derivações, e a relação entre contrato, layout signature e resolução determinística da DAG 2/DAG 3.
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
- `docs/adr/0011-resolucao-dirigida-pelo-contrato-e-legado-por-ausencia.md` — os
  blocos opcionais que tiram regra de domínio do código (`chaves_de_item`,
  `derivacoes`, `papeis`); sem eles o contrato cai no caminho legado, sem erro;
- um contrato e um layout existentes da família mais próxima — `construtoras
  v1.9.1` (`infra/minio-bootstrap/contracts/construtoras/v1.9.1/`) é a
  referência mais completa hoje, com os quatro blocos declarados;
- `src/document_processing/application/use_cases/resolution/resolve_schema.py` se houver mudança
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

## Chaves de item, papéis e derivações (modo genérico)

Quatro blocos opcionais, todos em `contrato_semantico`, tiram do código (DAG 2)
e da LLM (DAG 3) decisões que o contrato já pode declarar sozinho. Nenhum é
exigido — um contrato sem eles segue o caminho legado, sem erro (ADR 0011) —
mas todo contrato novo deve declará-los quando o fato de negócio permitir,
porque é isso que faz o `layout_signature` ser resolvido/gerado
deterministicamente em vez de depender de a LLM acertar de novo a cada
documento.

### `chaves_de_item` — qual campo identifica o item de um array

```json
"chaves_de_item": {
  "balancos_das_empresas.lancamentos.dados": {
    "chave": "empresa",
    "origem_valor": "identidade_documento"
  },
  "balancos_das_empresas.lancamentos.dados.valores": {
    "chave": "papel_periodo",
    "origem_valor": "seletor_observacao"
  }
}
```

Um `path` por array do `schema_saida` (a presença deste bloco já liga o modo
genérico: `uses_generic_resolution = bool(chaves_de_item)`). `chave` é o campo
que identifica o item — nunca uma posição. `origem_valor` diz de onde vem o
valor do filtro quando o layout for construído, e isso decide quem resolve
cada array:

- `identidade_documento` — o valor é um atributo do próprio documento
  (entidade, período); o código copia. `atributo_identidade` (opcional)
  escolhe qual atributo preenche o filtro quando o nome não é óbvio pela
  chave (por padrão usa o atributo de mesmo nome da chave, senão a entidade).
- `seletor_observacao` — o valor é um dos `seletores` já declarados em
  `observacoes_obrigatorias` (ex.: um papel de período); o código enumera
  a partir da própria lista de observações obrigatórias.
- `evidencia` — só o documento diz (um rótulo que varia por publicação, sem
  regra fixa); fica com a LLM.

Declarar `origem_valor` errado ou deixar de declarar quando a informação é
determinística (mais comum: usar `evidencia` por hábito) é o motivo mais
comum de a LLM inventar um filtro plausível e errado — foi exatamente o caso
do `[empresa=identidade_documento]` que a Fase 1 do plano de assinatura de
layout fechou declarando `origem_valor=identidade_documento` em vez de deixar
a LLM decidir.

### `requisitos_mapeamento.papeis` — nomear os papéis de um seletor

```json
"papeis": {
  "papel_periodo": {
    "periodo_referencia": {
      "descricao": "Periodo a que o documento se refere.",
      "derivacao": { "origem": "identidade_documento.periodo" }
    },
    "periodo_comparativo_anterior": {
      "descricao": "Periodo imediatamente anterior, no mesmo escopo.",
      "derivacao": { "relacao": "anterior", "passo": 1 }
    },
    "mesmo_periodo_ano_anterior": {
      "descricao": "Mesmo periodo do ano anterior.",
      "derivacao": { "relacao": "mesmo_periodo_ano_anterior" }
    }
  }
}
```

Todo seletor usado em `observacoes_obrigatorias[].seletores` (ex.:
`papel_periodo`) precisa ter cada um dos seus valores possíveis declarado
aqui com `descricao` — a validação recusa o contrato se sobrar um papel usado
e não descrito, ou um papel descrito e nunca usado. `derivacao` é opcional e
tem duas formas: `{"origem": "identidade_documento.<atributo>"}` para o papel
base (copiado da identidade do documento) e `{"relacao": "anterior" |
"mesmo_periodo_ano_anterior", "passo": N}` para papéis relativos a ele.

Quando `derivacao` está presente, o código resolve sozinho **qual coluna da
tabela** corresponde a cada papel (Fase 2 do plano de assinatura de layout,
`domain/contracts/period_grammar.py` + `domain/fallback/column_roles.py`),
casando o rótulo do cabeçalho contra o período esperado — sem a LLM ler
"2T26 (a)" ou "1T26 UDM\*" e decidir. Isso só funciona quando o rótulo
publicado é reconhecível como período pela gramática genérica (trimestre,
semestre, mês ou ano — `2T26`, `2026-Q1`, `mar/26`, `2025`, com nota de
rodapé removida). Se o papel de um seletor **não** for período (ex.: cenário,
canal de venda, tipo de unidade), declare só `descricao`, sem `derivacao`: a
resolução da coluna continua com a LLM, e não há problema nisso.

### `campos_obrigatorios[].evidencia_esperada` — tipo de origem por campo

```json
"evidencia_esperada": { "valor": "celula_de_tabela", "periodo": "cabecalho_de_tabela" }
```

Mapa campo (terminal ou de contexto) → `tipo_origem` esperado, um dos valores
de `SupportedMappingOrigin`: `valor_fixo`, `campo_derivado`, `campo_json`,
`bloco_textual`, `registros_de_blocos_textuais`, `cabecalho_de_tabela`,
`celula_de_tabela`, `linhas_de_tabela`, `juncao_de_registros_json`. Diz à LLM
que tipo de artefato deve produzir aquele valor antes de ela escolher — some
o "acho que isso vem de um bloco de texto" quando o contrato já sabe que é
sempre célula de tabela.

### `derivacoes` — campos preenchidos sem LLM

```json
"derivacoes": [
  { "destino": "fonte", "origem": { "tipo": "contrato", "campo": "fonte" } },
  { "destino": "periodos_disponiveis.periodo_referencia",
    "origem": { "tipo": "observacao", "campo": "periodo",
                "seletor": { "papel_periodo": "periodo_referencia" } } }
]
```

Preenche folhas do `schema_saida` a partir de três origens — `contrato` (um
valor do próprio contrato semântico), `manifesto` (um campo do manifesto de
extração, como `entity_name`/`period_label`) ou `observacao` (o valor de uma
observação já resolvida, filtrado por `seletor`) — e nunca sobrescreve um
campo já preenchido por mapeamento direto. Use para qualquer campo de raiz
que seja só um espelho de uma observação ou do próprio contrato; não modele
como campo obrigatório de mapeamento algo que já pode ser derivado.

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
- Todo array com item identificável (empresa, período, instituição) declara
  `chaves_de_item` com o `origem_valor` certo — `identidade_documento` ou
  `seletor_observacao` sempre que a informação já é determinística, `evidencia`
  só quando de fato varia por documento sem regra?
- Todo seletor usado em `observacoes_obrigatorias` tem seus papéis descritos
  em `papeis`? Papéis de período que o documento publica de forma
  reconhecível (trimestre/semestre/mês/ano) declaram `derivacao`?
- Campos de raiz que só espelham o contrato, o manifesto ou uma observação já
  resolvida estão em `derivacoes`, não pedidos como mapeamento à LLM?
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

Adicionar ou corrigir `chaves_de_item`, `papeis`/`derivacao` ou `derivacoes`
também é mudança de contrato (muda o que a DAG 2 resolve e o que a DAG 3
resolve por código em vez de perguntar à LLM), mesmo quando o `schema_saida`
não muda uma folha — versione e publique como qualquer outra revisão de
significado.
