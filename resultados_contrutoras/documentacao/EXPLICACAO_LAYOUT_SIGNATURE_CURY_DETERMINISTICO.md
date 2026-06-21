# Explicação detalhada do `layout_signature_cury_deterministico.json`

## Objetivo deste documento

Este documento explica, em detalhe, o papel do arquivo:

- `layout_signature_cury_deterministico.json`

Ele descreve:

1. o que esse arquivo é;
2. o que cada bloco e cada chave representam;
3. o que já está preenchido com base real da extração da Cury;
4. o que ainda é regra operacional, e não dado final;
5. como as DAGs usam esse arquivo;
6. quando ele é suficiente;
7. quando precisa entrar fallback com LLM.


## O que este arquivo é

O `layout_signature_cury_deterministico.json` é um artefato estático de referência.

Ele não é:

- o resultado final da extração;
- o `schema_saida` resolvido;
- o relatório de compatibilidade da execução;
- a análise semântica da LLM.

Ele é:

- um mapa determinístico de leitura;
- uma referência operacional para a DAG saber onde procurar os campos do contrato semântico;
- um conjunto de regras objetivas para detectar quebra de layout;
- um guia mecânico de resolução dos campos do `schema_saida`.

Em termos simples:

- o contrato semântico diz **o que precisa existir**;
- o layout signature determinístico diz **onde está e como encontrar**;
- a DAG usa os dois para produzir o JSON final.


## O que já está preenchido com dados reais

Este arquivo já foi preenchido usando evidências reais da extração da Cury.

Ou seja, ele já contém:

- caminhos reais dos artefatos;
- `section_id` reais;
- `section_title` reais;
- `title_canonical` reais;
- páginas reais;
- `bbox` reais;
- cabeçalhos reais de tabelas;
- índices esperados de linha e coluna;
- nomes reais de linhas como `Número de Unidades`.

Exemplos reais que já estão no arquivo:

- `tables/table001.json` como fonte primária de `lancamentos`;
- `tables/table002.json` como fonte primária de `vendas`;
- página `4` para lançamentos;
- página `7` para vendas;
- cabeçalhos `4T25`, `1T25`, `1T26 UDM*`, `1T25 UDM*`.
- colunas observáveis de comparação como `%T/T` e `%A/A`, que ajudam a
  entender o layout mas não entram no `schema_saida_resolvido`.

O que ele não contém é o valor final já resolvido, por exemplo:

- `43`
- `9`
- `108.7`

Esses valores serão produzidos pela DAG em runtime.


## Estrutura geral do arquivo

O arquivo tem estes blocos principais:

1. `tipo_artefato`
2. `versao_artefato`
3. `tipo_documento`
4. `empresa`
5. `referencia_contrato_semantico`
6. `documento_origem`
7. `regras_execucao`
8. `fontes_relevantes`
9. `regras_deteccao_mudanca`
10. `mapeamento_canonico`


## 1. `tipo_artefato`

Exemplo:

```json
"tipo_artefato": "layout_signature_com_mapeamento_canonico_deterministico"
```

Essa chave classifica o arquivo.

Ela diz que este JSON:

- combina layout signature com mapeamento canônico;
- foi desenhado para execução determinística;
- não depende de texto aberto;
- não deve ser tratado como relatório narrativo.

Uso pela DAG:

- validar o tipo do artefato carregado;
- impedir uso indevido de um arquivo em formato diferente.


## 2. `versao_artefato`

Exemplo:

```json
"versao_artefato": "3.0.0"
```

Versiona o formato do próprio arquivo.

Ela não representa:

- a versão do PDF;
- a versão da extração;
- a versão do contrato.

Ela representa a versão da estrutura deste layout signature.

Uso pela DAG:

- saber se consegue interpretar esse formato;
- aplicar validações compatíveis com a versão.


## 3. `tipo_documento`

Exemplo:

```json
"tipo_documento": "relatorio_trimestral_construtora"
```

Classifica a família documental.

Uso pela DAG:

- garantir que o arquivo está sendo usado para o tipo certo de documento;
- apoiar seleção de layout signature quando houver mais de um modelo.


## 4. `empresa`

Exemplo:

```json
"empresa": "Cury"
```

Indica a empresa alvo do mapeamento.

Uso pela DAG:

- selecionar o layout signature correto;
- preencher estruturas do `schema_saida` com a empresa certa;
- evitar aplicar o mapeamento da Cury em outro PDF.


## 5. `referencia_contrato_semantico`

Exemplo:

```json
"referencia_contrato_semantico": {
  "arquivo": "contrato_semantico_construtora.json",
  "versao": "1.1.0"
}
```

Esse bloco liga o layout signature ao contrato semântico oficial.

Ele existe porque o layout signature não decide sozinho o que deve sair.
Ele precisa apontar para o contrato que define:

- o `schema_saida`;
- os campos esperados;
- obrigatoriedade;
- conceitos e sinônimos.

Uso pela DAG:

- carregar o contrato correspondente;
- validar se o mapeamento está alinhado ao contrato esperado.


## 6. `documento_origem`

Exemplo:

```json
"documento_origem": {
  "arquivo_pdf": "pdf_construturas/cury.pdf",
  "pdf_encontrado_em_pdf_construturas": true,
  "pasta_de_extracao": "dados-desestruturados/extraction_cury",
  "document_id": "cdce3fea-723b-5de2-b3e8-a3dbb90939ad"
}
```

Esse bloco identifica o documento e a extração usados para construir a referência.

### `arquivo_pdf`

Aponta qual PDF foi usado como base.

### `pdf_encontrado_em_pdf_construturas`

Informa se o PDF de referência está presente na pasta esperada.

### `pasta_de_extracao`

Aponta para a saída da extração usada como evidência estrutural.

### `document_id`

Identificador único da extração/documento.

Uso pela DAG:

- rastreabilidade;
- auditoria;
- reprodutibilidade.

Esse bloco não é usado para resolver valores diretamente, mas é importante para governança.


## Onde conferir no artefato de extração da Cury

Neste repositório, a extração real usada para conferência está em:

- `dados-desestruturados/extraction_cury/`

Ao validar se o `layout_signature_cury_deterministico.json` está mapeando corretamente, a ideia é sempre cruzar:

1. o que o layout signature declara;
2. o que realmente existe dentro da extração;
3. se os seletores de linha, coluna, seção e bloco batem com o artefato real.

Os lugares mais úteis para conferir isso são:

- `metadata.json`
- `sections/sections.jsonl`
- `blocks/blocks.jsonl`
- `tables/table001.json`
- `tables/table001/metadata.json`
- `tables/table001/cells.json`
- `tables/table001/normalized_rows.json`
- `tables/table002.json`
- `tables/table002/metadata.json`
- `tables/table002/cells.json`
- `tables/table002/normalized_rows.json`
- `text_candidates/text_candidates.jsonl`
- `text_structures/text_structures.jsonl`
- `cases/cases.jsonl`


## Exemplos práticos de conferência

### Exemplo 1: conferir `periodo_referencia`

No layout signature, `periodo_referencia` aponta para:

- `arquivo_origem = blocks/blocks.jsonl`
- `section_id = 9dbabb99-216d-576c-9488-c2a968b0eb98`
- `section_title = PRÉVIA OPERACIONAL`
- `block_id = 24b3231c-2232-54c9-b9e0-01c1cb23865d`
- `padrao = 1T[0-9]{2}`

Onde conferir:

- `dados-desestruturados/extraction_cury/blocks/blocks.jsonl`

O que você deve encontrar:

- um bloco com `block_id = 24b3231c-2232-54c9-b9e0-01c1cb23865d`
- `page_number = 2`
- `section_title = PRÉVIA OPERACIONAL`
- texto contendo `primeiro trimestre de 2026 (1T26)`

Conferência auxiliar:

- `dados-desestruturados/extraction_cury/text_candidates/text_candidates.jsonl`

Ali existe um candidato textual na mesma seção, com `matched_values` incluindo `1T26` e `1T25`.


### Exemplo 2: conferir a seção de lançamentos

No layout signature, a regra `SEC_LANC_001` aceita:

- `title_canonical = l_a_n_c_a_m_e_n_t_o_s`
- ou `title_canonical = r_26468_milhoes`
- nas páginas `4`, `5` e `6`

Onde conferir:

- `dados-desestruturados/extraction_cury/sections/sections.jsonl`

O que você deve encontrar:

- página `4` com `title_raw = / / L A N Ç A M E N T O S`
- página `4` com `title_raw = R$ 2.646,8 MILHÕES`
- página `5` com `title_raw = / / L A N Ç A M E N T O S`
- página `6` com `title_raw = / / L A N Ç A M E N T O S`

Isso confirma que a regra está ancorando a família correta de seções para `lancamentos`.


### Exemplo 3: conferir a tabela primária de lançamentos

No layout signature, `fontes_relevantes.tabelas_primarias[0]` informa:

- `arquivo = tables/table001.json`
- `arquivo_metadados = tables/table001/metadata.json`
- `table_id = f0f1e575-5a8e-5ad1-a589-ebfd43615a48`
- `page_number = 4`
- `section_id = 12097fa3-49c1-5fbc-91b2-4fdbabc67f64`
- `section_title = R$ 2.646,8 MILHÕES`

Onde conferir:

- `dados-desestruturados/extraction_cury/tables/table001.json`
- `dados-desestruturados/extraction_cury/tables/table001/metadata.json`

O que você deve encontrar:

- `schema` com:
  - `Lançamentos`
  - `1T26`
  - `4T25`
  - `%T/T`
  - `1T25`
  - `%A/A`
  - `1T26 UDM*`
  - `1T25 UDM*`
  - `%A/A`
- `row_count = 7`
- `column_count = 9`
- `bbox` igual ao registrado no layout signature


### Exemplo 4: conferir o mapeamento de lançamentos para `Número de Unidades`

No layout signature, os campos de valores brutos de lançamentos apontam para:

- `balancos_das_empresas.lancamentos.dados[empresa=Cury].valores[papel_periodo=periodo_referencia]`
- `balancos_das_empresas.lancamentos.dados[empresa=Cury].valores[papel_periodo=periodo_comparativo_anterior]`
- `balancos_das_empresas.lancamentos.dados[empresa=Cury].valores[papel_periodo=mesmo_periodo_ano_anterior]`
- `balancos_das_empresas.lancamentos.dados[empresa=Cury].valores[papel_periodo=periodo_12m_atual]`
- `balancos_das_empresas.lancamentos.dados[empresa=Cury].valores[papel_periodo=periodo_12m_anterior]`

aponta para:

- `tables/table001.json`
- linha `Número de Unidades`
- colunas de período bruto, como `1T26`, `4T25`, `1T25`, `1T26 UDM*` e `1T25 UDM*`
- `indice_linha_esperado = 2`
- `indice_coluna_esperado` conforme o papel de período

Onde conferir:

- `dados-desestruturados/extraction_cury/tables/table001/cells.json`
- `dados-desestruturados/extraction_cury/tables/table001/normalized_rows.json`

O que você deve encontrar em `cells.json`:

- `row_index = 2`, `column_index = 0`, `value_raw = Número de Unidades`
- valores brutos nas colunas dos períodos mapeados

O que você deve encontrar em `normalized_rows.json`:

- um registro com `attributes.lancamentos = Número de Unidades`
- medidas associadas aos cabeçalhos de período bruto

As colunas `%T/T` e `%A/A` podem aparecer na tabela como evidência estrutural
observável, mas não pertencem ao `schema_saida_resolvido` e não devem ser
prometidas pelo `mapeamento_canonico`.

Se isso bater, a DAG conseguiria resolver corretamente os valores brutos de
lançamentos por período.


### Exemplo 5: conferir os períodos comparativos em lançamentos

No layout signature, estes campos usam cabeçalhos de `table001`:

- `periodos_disponiveis.periodo_comparativo_anterior -> 4T25`
- `periodos_disponiveis.mesmo_periodo_ano_anterior -> 1T25`
- `periodos_disponiveis.periodo_12m_atual -> 1T26 UDM*`
- `periodos_disponiveis.periodo_12m_anterior -> 1T25 UDM*`

Onde conferir:

- `dados-desestruturados/extraction_cury/tables/table001.json`
- `dados-desestruturados/extraction_cury/tables/table001/metadata.json`

O que você deve encontrar:

- esses valores no `schema` da tabela;
- as mesmas colunas nas posições esperadas.


### Exemplo 6: conferir a tabela primária de vendas

No layout signature, `fontes_relevantes.tabelas_primarias[1]` informa:

- `arquivo = tables/table002.json`
- `arquivo_metadados = tables/table002/metadata.json`
- `table_id = 199923b8-996b-5fcd-a7ca-da62fea90867`
- `page_number = 7`
- `section_id = e0af7ca8-647e-531c-9ec8-84d5cf4255f0`
- `section_title = / / V E N D A S L Í Q U I D A S`

Onde conferir:

- `dados-desestruturados/extraction_cury/tables/table002.json`
- `dados-desestruturados/extraction_cury/tables/table002/metadata.json`

O que você deve encontrar:

- `schema` com:
  - `Vendas, %VSO`
  - `1T26`
  - `4T25`
  - `%T/T`
  - `1T25`
  - `%A/A`
  - `1T26 UDM*`
  - `1T25 UDM*`
  - `%A/A`
- `row_count = 13`
- `column_count = 9`
- `bbox` igual ao do layout signature


### Exemplo 7: conferir o mapeamento de vendas para `Número de Unidades`

No layout signature, os campos de valores brutos de vendas apontam para:

- `balancos_das_empresas.vendas.dados[empresa=Cury].valores[papel_periodo=periodo_referencia]`
- `balancos_das_empresas.vendas.dados[empresa=Cury].valores[papel_periodo=periodo_comparativo_anterior]`
- `balancos_das_empresas.vendas.dados[empresa=Cury].valores[papel_periodo=mesmo_periodo_ano_anterior]`
- `balancos_das_empresas.vendas.dados[empresa=Cury].valores[papel_periodo=periodo_12m_atual]`
- `balancos_das_empresas.vendas.dados[empresa=Cury].valores[papel_periodo=periodo_12m_anterior]`

aponta para:

- `tables/table002.json`
- linha `Número de Unidades`
- colunas de período bruto, como `1T26`, `4T25`, `1T25`, `1T26 UDM*` e `1T25 UDM*`
- `indice_linha_esperado = 1`
- `indice_coluna_esperado` conforme o papel de período

Onde conferir:

- `dados-desestruturados/extraction_cury/tables/table002/cells.json`
- `dados-desestruturados/extraction_cury/tables/table002/normalized_rows.json`

O que você deve encontrar em `cells.json`:

- `row_index = 1`, `column_index = 0`, `value_raw = Número de Unidades`
- valores brutos nas colunas dos períodos mapeados

O que você deve encontrar em `normalized_rows.json`:

- um registro com `attributes.vendas_vso = Número de Unidades`
- medidas associadas aos cabeçalhos de período bruto

As colunas `%T/T` e `%A/A` podem aparecer na tabela como evidência estrutural
observável, mas não pertencem ao `schema_saida_resolvido` e não devem ser
prometidas pelo `mapeamento_canonico`.

Se isso bater, a DAG conseguiria resolver corretamente os valores brutos de
vendas por período.


### Exemplo 8: conferir com artefatos textuais auxiliares

Mesmo quando o mapeamento principal é por tabela, vale conferir os artefatos textuais como respaldo.

Onde conferir:

- `dados-desestruturados/extraction_cury/text_candidates/text_candidates.jsonl`
- `dados-desestruturados/extraction_cury/text_structures/text_structures.jsonl`
- `dados-desestruturados/extraction_cury/cases/cases.jsonl`

Exemplo prático em vendas:

- a seção `e0af7ca8-647e-531c-9ec8-84d5cf4255f0`
- traz, em texto, `9,5% em relação ao 1T25`
- e `48,1% em comparação ao 4T25`
- além de `R$ 2.304,6 milhões`
- e `R$ 7.949,4 milhões`

Esses artefatos não são a fonte primária do mapeamento canônico atual, mas são ótimos para:

- auditoria;
- validação humana;
- fallback com LLM;
- proposta de novo mapeamento se a tabela quebrar.


### Exemplo 9: conferir por `metadata.json`

O arquivo:

- `dados-desestruturados/extraction_cury/metadata.json`

resume os itens detectados pela extração.

O que ele mostra de forma útil:

- `source_file = pdf_construturas/cury.pdf`
- `tables/table001.json` como tabela `R$ 2.646,8 MILHÕES`
- `tables/table002.json` como tabela `/ / V E N D A S L Í Q U I D A S`

É um ponto rápido para confirmar se os nomes e caminhos das tabelas do layout signature estão consistentes com a extração.


### Regra prática de validação humana

Para conferir se o layout signature está bom, a validação manual pode seguir este checklist:

1. a seção indicada existe em `sections/sections.jsonl`?
2. a tabela indicada existe em `tables/...`?
3. o `section_id` da tabela bate com o do layout signature?
4. o `schema` da tabela contém os cabeçalhos esperados?
5. a linha alvo existe no `cells.json` ou `normalized_rows.json`?
6. a coluna alvo existe na posição esperada?
7. o valor bruto encontrado é compatível com a normalização?
8. o valor normalizado faz sentido para o campo canônico?

Se essas respostas forem sim, o mapeamento está coerente.


## 7. `regras_execucao`

Exemplo:

```json
"regras_execucao": {
  "modo_resolucao": "deterministico",
  "permitir_aliases_do_contrato_semantico": true,
  "permitir_fontes_alternativas_sem_llm": true,
  "gerar_resultado_validacao_em_runtime": true,
  "acionar_llm_apenas_em_fallback": true,
  "codigos_que_podem_acionar_llm": [...]
}
```

Esse bloco define o comportamento esperado da DAG ao consumir o arquivo.

### `modo_resolucao`

Valor:

```json
"deterministico"
```

Significa que:

- a DAG primeiro usa regras fechadas;
- não há interpretação livre como etapa padrão;
- a LLM não participa do fluxo normal.

### `permitir_aliases_do_contrato_semantico`

Se `true`, a DAG pode tentar sinônimos previstos no contrato semântico antes de declarar falha.

Exemplo:

- `imoveis_vendidos`
- `unidades vendidas`
- `UH vendidas`

### `permitir_fontes_alternativas_sem_llm`

Se `true`, a DAG pode procurar o mesmo dado em outra fonte do mesmo documento, desde que a regra continue objetiva.

Exemplo:

- outra tabela;
- outro cabeçalho equivalente;
- outro bloco textual conhecido.

### `gerar_resultado_validacao_em_runtime`

Indica que compatibilidade não fica gravada aqui.
Ela será calculada a cada execução.

### `acionar_llm_apenas_em_fallback`

Confirma o desenho arquitetural:

- primeiro, resolução determinística;
- depois, somente se necessário, fallback com LLM.

### `codigos_que_podem_acionar_llm`

Lista fechada de códigos de falha que autorizam escalar para fallback.

Exemplos:

- `FALHA_CAMPO_OBRIGATORIO`
- `FALHA_TABELA_CRITICA_AUSENTE`
- `FALHA_SECAO_CRITICA_AUSENTE`
- `FALHA_LINHA_CRITICA_AUSENTE`
- `FALHA_COLUNA_CRITICA_AUSENTE`
- `FALHA_VALOR_NAO_NORMALIZAVEL`
- `FALHA_AMBIGUIDADE_DE_CANDIDATOS`

Uso pela DAG:

- decidir se tenta resolver localmente;
- decidir se precisa abrir fallback;
- manter regras de escalonamento objetivas.


## 8. `fontes_relevantes`

Esse bloco lista os artefatos de extração que a DAG deve considerar prioritários.

Exemplo:

```json
"fontes_relevantes": {
  "sections_path": "sections/sections.jsonl",
  "blocks_path": "blocks/blocks.jsonl",
  "text_candidates_path": "text_candidates/text_candidates.jsonl",
  "text_structures_path": "text_structures/text_structures.jsonl",
  "tabelas_primarias": [...]
}
```

### Arquivos base

- `sections_path`
- `blocks_path`
- `text_candidates_path`
- `text_structures_path`

Esses caminhos apontam para os artefatos brutos ou semiestruturados que a DAG pode consultar.

### `tabelas_primarias`

Esse é um dos pontos mais importantes do arquivo.

Ele lista as tabelas principais para os conceitos de negócio relevantes.

No caso da Cury:

1. tabela de `lancamentos`
2. tabela de `vendas`

Cada item informa:

- `conceito`
- `arquivo`
- `arquivo_metadados`
- `page_number`
- `section_id`
- `section_title`
- `title_canonical`

Isso ajuda a DAG a:

- ir direto às fontes mais prováveis;
- validar se as tabelas críticas ainda existem;
- entender qual tabela sustenta qual grupo do `schema_saida`.


## 9. `regras_deteccao_mudanca`

Esse bloco transforma a ideia de “mudança de PDF” em testes objetivos.

Ele é determinístico porque cada regra produz um resultado fechado:

- passou;
- falhou;
- código de falha.

### Tipos de regra usados

No arquivo da Cury aparecem:

- `secao_existe`
- `arquivo_existe`
- `linha_existe_em_tabela`
- `coluna_existe_em_tabela`
- `valor_normalizavel`

### Como cada tipo funciona

#### `secao_existe`

Exemplo:

- procurar `title_canonical` entre valores aceitos;
- restringir às páginas esperadas.

Isso detecta se a seção relevante ainda está presente.

#### `arquivo_existe`

Exemplo:

- verificar se `tables/table001.json` existe.

Isso detecta quebra estrutural na extração.

#### `linha_existe_em_tabela`

Exemplo:

- procurar a linha `Número de Unidades` na coluna de rótulo.

Isso detecta mudança semântica ou mudança da tabela.

#### `coluna_existe_em_tabela`

Exemplo:

- procurar cabeçalhos de períodos brutos, como `1T26`, `4T25`, `1T25` ou `1T26 UDM*`.

Isso detecta se o perfil temporal da tabela mudou. Colunas de comparação como
`%T/T` e `%A/A` podem ser observadas como parte do layout, mas não são campos do
`schema_saida_resolvido`.

#### `valor_normalizavel`

Exemplo:

- pegar o valor na célula esperada;
- testar se a normalização `numero_pt_br_para_numero` funciona.

Isso detecta mudança de formato no conteúdo bruto, mesmo quando a tabela continua existindo.

### Por que isso é importante

Sem esse bloco, a DAG tentaria resolver valores às cegas.

Com esse bloco, ela consegue responder objetivamente:

- o layout ainda está compatível?
- a fonte crítica existe?
- o seletor de linha e coluna ainda funciona?
- o conteúdo ainda é normalizável?

### O que a DAG faz com essas regras

A DAG executa cada regra e gera um artefato dinâmico como:

- `validacao_layout_signature.json`

Esse artefato conterá algo como:

- regra executada;
- resultado;
- arquivo analisado;
- valor observado;
- código de falha, quando houver.


## 10. `mapeamento_canonico`

Esse é o coração do arquivo.

Ele define, campo por campo, como preencher o `schema_saida`.

Cada chave desse bloco corresponde a um caminho lógico do schema de saída.

Exemplos:

- `fonte`
- `periodo_referencia`
- `periodos_disponiveis.periodo_comparativo_anterior`
- `balancos_das_empresas.lancamentos.dados[empresa=Cury].valores[papel_periodo=periodo_referencia]`

Em outras palavras:

- o contrato semântico define o formato do JSON final;
- o `mapeamento_canonico` ensina a DAG a preencher cada parte desse formato.


## Tipos de origem dentro do `mapeamento_canonico`

### `valor_fixo`

Usado quando o valor não precisa ser buscado no documento.

Exemplos:

- `fonte = "Balanços trimestrais das empresas"`
- `balancos_das_empresas.titulo = "Balanços das empresas"`
- `balancos_das_empresas.lancamentos.tipo = "valor_bruto"`

Uso pela DAG:

- preencher diretamente sem procurar em artefatos.


### `bloco_textual`

Usado quando o valor deve ser extraído de um bloco de texto.

Exemplo:

- `periodo_referencia`

Nesse caso, o arquivo informa:

- `arquivo_origem`
- `section_id`
- `section_title`
- `page_number`
- `block_id`
- `modo_extracao`
- `padrao`

Aqui o período de referência é buscado com regex, usando padrão:

```json
"padrao": "1T[0-9]{2}"
```

Uso pela DAG:

- localizar o bloco;
- aplicar regex;
- capturar o valor compatível.


### `campo_derivado`

Usado quando um campo depende de outro já resolvido.

Exemplo:

- `periodos_disponiveis.periodo_referencia`

Nesse caso:

- o valor não é buscado novamente;
- ele é derivado do campo `periodo_referencia`.

Uso pela DAG:

- reduzir duplicação;
- manter consistência entre campos iguais.


### `cabecalho_de_tabela`

Usado quando o valor esperado está no cabeçalho de uma tabela.

Exemplos:

- `periodos_disponiveis.periodo_comparativo_anterior`
- `periodos_disponiveis.mesmo_periodo_ano_anterior`
- `periodos_disponiveis.periodo_12m_atual`
- `periodos_disponiveis.periodo_12m_anterior`

Esses campos usam cabeçalhos reais como:

- `4T25`
- `1T25`
- `1T26 UDM*`
- `1T25 UDM*`

Uso pela DAG:

- abrir a tabela;
- ler o cabeçalho na coluna esperada;
- retornar esse valor como período comparativo.


### `celula_de_tabela`

Esse é o tipo mais importante para os indicadores principais.

Exemplo:

- `balancos_das_empresas.vendas.dados[empresa=Cury].valores[papel_periodo=periodo_referencia]`

Quando a origem é `celula_de_tabela`, o arquivo traz:

- `arquivo_origem`
- `arquivo_metadados`
- `page_number`
- `section_id`
- `section_title`
- `bbox`
- `seletor_linha`
- `seletor_coluna`
- `normalizacao`
- `obrigatorio`

### `seletor_linha`

Exemplo:

```json
"seletor_linha": {
  "tipo_match": "exato",
  "coluna_rotulo": 0,
  "valor_aceito": "Número de Unidades",
  "indice_linha_esperado": 1
}
```

Significa:

- a linha deve ser localizada pelo rótulo;
- esse rótulo está na coluna 0;
- o valor esperado é `Número de Unidades`;
- o índice esperado ajuda como referência adicional.

### `seletor_coluna`

Exemplo:

```json
"seletor_coluna": {
  "tipo_match": "exato",
  "cabecalho_aceito": "1T26",
  "indice_coluna_esperado": 1
}
```

Significa:

- a coluna deve ser localizada pelo cabeçalho;
- o cabeçalho esperado é um período bruto;
- o índice esperado ajuda como verificação.

### `normalizacao`

Exemplo:

```json
"normalizacao": "numero_pt_br_para_numero"
```

Significa:

- a célula pode vir como texto;
- a DAG deve converter o formato brasileiro para número.

Exemplo conceitual:

- `"4.633"` -> `4633`
- `"18.060"` -> `18060`

### `bbox`

Registra a posição visual da tabela no PDF.

Ela não é a principal forma de leitura, mas é útil para:

- auditoria;
- rastreabilidade;
- inspeção humana;
- comparação de mudança estrutural.


### `nao_mapeado_neste_documento`

Usado quando o campo existe no contrato, mas não foi encontrado neste PDF da empresa.

Exemplo:

- `periodos_disponiveis.periodo_12m_base`

Significa:

- o contrato admite esse campo;
- este documento específico não oferece evidência suficiente para resolvê-lo.

Uso pela DAG:

- não inventar valor;
- marcar o campo como ausente controlado;
- deixar claro que não se trata de aplicação da LLM, e sim de ausência documental.


### `nao_aplicavel_neste_pdf_individual`

Usado quando o campo do contrato não pertence ao escopo de um PDF individual da empresa.

Exemplo:

- `indicadores_consolidados.total_lancamentos.*`
- `indicadores_consolidados.total_vendas.*`

Significa:

- o campo existe no `schema_saida`;
- o PDF individual da Cury não é a fonte desse dado;
- esse campo precisa ser resolvido em outra etapa agregadora.

Uso pela DAG:

- não tratar isso como erro;
- não acionar fallback;
- apenas registrar como não aplicável.


## Como a DAG usaria esse arquivo na prática

## DAG 1: detectar PDF e extrair

Essa DAG não usa diretamente o layout signature para resolver os dados.

Ela:

- detecta novo PDF;
- executa o pipeline de extração;
- grava os artefatos em uma pasta como `dados-desestruturados/extraction_cury`.

Saída principal:

- tabelas;
- blocos;
- seções;
- candidatos textuais;
- metadados estruturais.


## DAG 2: validar layout e resolver `schema_saida`

Essa é a DAG que realmente consome o `layout_signature_cury_deterministico.json`.

### Passo 1: carregar referências

Ela carrega:

- `contrato_semantico_construtora.json`
- `layout_signature_cury_deterministico.json`
- artefatos da extração do PDF atual

### Passo 2: validar compatibilidade estrutural

Ela executa `regras_deteccao_mudanca`.

Exemplo:

- a seção de vendas existe?
- `tables/table002.json` existe?
- existe a linha `Número de Unidades`?
- existem as colunas de período bruto esperadas?
- o valor bruto da célula pode ser normalizado?

Se tudo isso passa, a DAG entende que ainda consegue usar o mapeamento com confiança.

### Passo 3: resolver cada campo do `schema_saida`

Ela percorre `mapeamento_canonico` e, para cada chave:

- resolve valor fixo;
- extrai via regex;
- deriva de campo anterior;
- lê cabeçalho de tabela;
- lê célula de tabela;
- marca como não mapeado;
- marca como não aplicável.

### Passo 4: gerar saídas

Saídas recomendadas:

- `validacao_layout_signature.json`
- `schema_saida_resolvido.json`
- `auditoria_resolucao.json`


## DAG 3: fallback com LLM

Essa DAG só entra quando a validação indicar falha crítica.

Exemplos:

- tabela crítica ausente;
- cabeçalho crítico ausente;
- linha crítica ausente;
- valor não normalizável;
- ambiguidade;
- campo obrigatório sem resolução.

### O que ela recebe

- `validacao_layout_signature.json`
- artefatos extraídos do PDF atual
- contrato semântico
- layout signature estático atual

### O que a LLM deve fazer primeiro

A recomendação é:

1. tentar regenerar apenas o trecho faltante ou quebrado do mapeamento;
2. só regenerar o mapeamento inteiro se a quebra estrutural for ampla.

### Por que não regenerar tudo sempre

Porque regenerar tudo:

- aumenta risco de regressão;
- dificulta auditoria;
- pode alterar campos que já estavam corretos;
- custa mais;
- reduz previsibilidade.

### Quando regenerar só parte do mapeamento

Exemplo:

- a tabela de vendas mudou de página;
- o cabeçalho `1T26 UDM*` virou `UDM 1T26`;
- a linha `Número de Unidades` virou `Unidades Vendidas`.

Nesses casos, a LLM pode sugerir somente atualização para:

- `balancos_das_empresas.vendas.*`
- ou apenas um subconjunto específico.

### Quando regenerar o mapeamento inteiro

Somente quando houver quebra ampla, por exemplo:

- nova estrutura de relatório;
- seções principais mudaram;
- tabelas deixaram de existir;
- dados migraram para gráficos ou blocos textuais;
- vários campos críticos ficaram sem origem confiável.

### Saídas esperadas da DAG de fallback

- `proposta_novo_mapeamento.json`
- `analise_semantica_llm.json`

Esses arquivos não devem sobrescrever automaticamente o estático base sem revisão ou validação.


## DAG 4: ingestão na bronze

Essa DAG não precisa entender o layout do PDF.

Ela consome o resultado já resolvido.

Entrada:

- `schema_saida_resolvido.json`

Função:

- transformar o JSON final em estrutura de banco;
- gravar na camada bronze;
- manter rastreabilidade para lineage e auditoria.


## Quais documentos cada DAG gera

## DAG 1

Gera artefatos de extração:

- `metadata.json`
- `tables/...`
- `sections/...`
- `blocks/...`
- `text_candidates/...`
- `text_structures/...`


## DAG 2

Gera artefatos de validação e resolução:

- `validacao_layout_signature.json`
- `schema_saida_resolvido.json`
- `auditoria_resolucao.json` opcional


## DAG 3

Gera artefatos de fallback:

- `proposta_novo_mapeamento.json`
- `analise_semantica_llm.json`


## DAG 4

Gera artefatos de ingestão, dependendo da arquitetura do banco:

- carga bronze;
- logs de ingestão;
- rastreabilidade de execução.


## Como os documentos se comunicam

O fluxo ideal de comunicação é este:

1. `contrato_semantico_construtora.json`
   define o alvo semântico e o `schema_saida`

2. `layout_signature_cury_deterministico.json`
   define como localizar os dados que preenchem esse alvo

3. artefatos da extração
   fornecem a evidência real do PDF atual

4. `validacao_layout_signature.json`
   registra se o mapeamento está funcionando neste novo documento

5. `schema_saida_resolvido.json`
   materializa os dados finais para relatório e ingestão

6. `proposta_novo_mapeamento.json`
   só aparece quando a DAG não consegue resolver com o mapeamento atual


## O que este arquivo não deve fazer

Para manter a arquitetura limpa, este arquivo não deve:

- carregar `status_compatibilidade` já preenchido;
- conter resumo narrativo;
- escrever `motivos_para_alerta` em linguagem aberta;
- conter análise textual de fallback;
- armazenar valores finais resolvidos da execução.

Tudo isso pertence a artefatos dinâmicos gerados pela DAG ou pela LLM.


## Resumo final

O `layout_signature_cury_deterministico.json` é um mapa estático, determinístico e já baseado em evidências reais da extração da Cury.

Ele serve para que a DAG:

- valide se o layout ainda é compatível;
- localize as fontes corretas;
- resolva os campos do `schema_saida`;
- saiba quando ainda consegue operar deterministicamente;
- saiba quando precisa escalar para fallback com LLM.

Ele não substitui:

- o contrato semântico;
- o `schema_saida` resolvido;
- o artefato de validação em runtime;
- a eventual análise semântica com LLM.

Ele é a ponte entre a extração do PDF e a materialização confiável dos dados de negócio.
