# Exemplo ABECIP: DAG 3 criando um Layout Signature por Blocos

## Objetivo do exemplo

Este documento mostra, passo a passo, como a DAG 3 pode criar um
`layout_signature` para o boletim da ABECIP sem enviar todo o contrato e todos
os artefatos de extração em uma única chamada LLM.

ABECIP é somente o exemplo. A regra de divisão é genérica: ela é derivada dos
paths declarados no contrato semântico, sem `if` por domínio, entidade, PDF ou
nome de seção.

## Ponto de partida

O contrato ABECIP v2.5.0 declara estes cinco campos obrigatórios de mapeamento:

```text
financiamentos_imobiliarios.serie_mensal_sbpe
financiamentos_imobiliarios.serie_historica_anual
financiamentos_imobiliarios.por_modalidade_e_instituicao
poupanca_sbpe.saldos_mensais
poupanca_sbpe.captacoes_liquidas_mensais
```

Os dados extraídos pela DAG 1 já estão no MinIO e o `inventory.json` informa
quais tabelas, gráficos, blocos textuais e outros artefatos existem para aquele
PDF.

## 1. A DAG monta o plano determinístico

Antes de chamar a LLM, a DAG lê
`contrato_semantico.requisitos_mapeamento.campos_obrigatorios` e agrupa os
paths pela raiz semântica — o primeiro segmento de cada path.

Para ABECIP, o resultado é o seguinte `plano_mapeamento.json` conceitual:

```json
{
  "tipo_artefato": "plano_mapeamento_layout",
  "versao": "1.0",
  "estrategia": "agrupamento_deterministico_por_raiz_semantica",
  "unidades": [
    {
      "id": "financiamentos_imobiliarios",
      "campos_saida": [
        "financiamentos_imobiliarios.serie_mensal_sbpe",
        "financiamentos_imobiliarios.serie_historica_anual",
        "financiamentos_imobiliarios.por_modalidade_e_instituicao"
      ]
    },
    {
      "id": "poupanca_sbpe",
      "campos_saida": [
        "poupanca_sbpe.saldos_mensais",
        "poupanca_sbpe.captacoes_liquidas_mensais"
      ]
    }
  ]
}
```

Essa é uma decisão da DAG, não da LLM. Portanto, duas execuções com o mesmo
contrato geram o mesmo plano, independentemente do modelo utilizado.

Cada unidade também recebe um subesquema: a projeção de
`estrutura_schema_saida` limitada aos seus paths permitidos, arrays que exigem
seletor e campos de contexto eventualmente requeridos pelo contrato.

## 2. Primeira chamada LLM: seleção de evidências de uma unidade

A DAG executa a seleção separadamente para cada unidade. A LLM recebe:

- o resumo completo do `inventory.json`;
- somente os campos obrigatórios daquela unidade;
- somente o subesquema daquela unidade;
- instruções para declarar caminhos existentes e âncoras literais verificáveis.

Por exemplo, na unidade `poupanca_sbpe`, ela não precisa receber os campos de
financiamentos. Ela deve apenas identificar os artefatos
que comprovem os saldos e as captações líquidas da poupança.

A resposta segue o contrato já usado pela seleção de artefatos:

```json
{
  "tipo_artefato": "selecao_artefatos_layout",
  "artifact_paths": [
    {
      "path": "tables/table003.json",
      "motivo": "Tabela com a série publicada de poupança SBPE.",
      "coberturas": [
        {
          "campo_saida": "poupanca_sbpe.saldos_mensais",
          "ancoras": ["Saldo", "Poupança SBPE"]
        },
        {
          "campo_saida": "poupanca_sbpe.captacoes_liquidas_mensais",
          "ancoras": ["Captação líquida", "Poupança SBPE"]
        }
      ]
    }
  ]
}
```

Os caminhos e as âncoras acima são apenas ilustrativos. Em uma execução real,
eles precisam existir literalmente na extração daquele PDF.

### Validação entre as duas chamadas

Antes de continuar, a DAG valida de forma determinística:

1. se todos os paths selecionados existem no inventário;
2. se cada cobertura aponta para um campo obrigatório daquela unidade;
3. se as âncoras declaradas aparecem no conteúdo carregado;
4. no caso de `.jsonl`, se uma âncora estiver fora da amostra inicial, a DAG
   procura o arquivo completo e adiciona somente os registros correspondentes
   à evidência da unidade.

Logo, a segunda chamada não depende de uma afirmação não comprovada da LLM.

## 3. Segunda chamada LLM: criação do fragmento do layout

Após uma seleção aprovada, a DAG carrega somente os artefatos escolhidos para a
unidade. A LLM recebe:

- a identificação mínima da execução;
- a unidade de mapeamento e seu subesquema;
- os alvos mapeáveis da unidade;
- os artefatos aprovados, incluindo evidências de âncoras quando necessário.

Ela não recebe o contrato completo de todos os ramos, o layout completo, os
artefatos de outras unidades, regras de publicação ou valores fixos do contrato.

Em vez de retornar um layout inteiro, a resposta contém um fragmento:

```json
{
  "tipo_artefato": "fragmento_layout_signature",
  "unidade_mapeamento": "poupanca_sbpe",
  "mapeamento_canonico": {
    "poupanca_sbpe.saldos_mensais": {
      "tipo_origem": "linhas_de_tabela",
      "arquivo_origem": "tables/table003.json",
      "linha_inicial": 0,
      "linha_final": 11,
      "indices_colunas": [0, 5],
      "obrigatorio": true
    },
    "poupanca_sbpe.captacoes_liquidas_mensais": {
      "tipo_origem": "linhas_de_tabela",
      "arquivo_origem": "tables/table003.json",
      "linha_inicial": 0,
      "linha_final": 11,
      "indices_colunas": [0, 11],
      "obrigatorio": true
    }
  },
  "fontes_relevantes": {},
  "metadados_estruturais_evidencia": {}
}
```

Os índices também são ilustrativos. O princípio é que a LLM produz apenas uma
instrução executável de extração para os paths daquele bloco.

## 4. Validação do fragmento

Cada fragmento é rejeitado imediatamente se, por exemplo:

- retornar um `unidade_mapeamento` diferente da solicitada;
- tentar mapear paths de outra unidade;
- omitir campos obrigatórios ou seus campos de contexto;
- atravessar um array sem seletor explícito;
- tentar mapear valor que o contrato já fixa deterministicamente;
- usar regex de cabeçalho em uma tabela, em vez de índices observados.

Quando a resposta é corrigível, o retry recebe somente o mesmo bloco, a
evidência aprovada e o erro da validação. Uma falha em `poupanca_sbpe`, por
exemplo, mantém o reparo limitado ao contexto dessa unidade.

## 5. O quebra-cabeça é montado deterministicamente

Depois de todas as unidades serem aprovadas, a DAG une seus
`mapeamento_canonico` sem pedir uma nova chamada à LLM:

```text
fragmento financiamentos_imobiliarios
                 +
fragmento poupanca_sbpe
                 |
                 v
layout_signature_candidato_consolidado
```

Durante essa união, a DAG:

1. reprova qualquer path duplicado entre fragmentos;
2. garante a cobertura de todos os campos obrigatórios do contrato completo;
3. monta `document_id`, `execution_id_origem`, escopo, referência de layout
   base e demais metadados operacionais;
4. mantém valores fixos fora da responsabilidade da LLM;
5. persiste o candidato consolidado.

O resultado já possui o mesmo formato de um
`layout_signature_candidato` tradicional. Portanto, não é necessário alterar a
DAG 2 para entender se a origem foi uma ou várias chamadas LLM.

## 6. Revalidação final pela DAG 2

A DAG 2 recebe o candidato consolidado e executa a resolução determinística
integral contra a extração real. Só se o schema de saída for compatível o layout
é publicado como nova versão e o ponteiro `current.json` é atualizado.

Essa etapa é indispensável: a validação de cada fragmento comprova a estrutura
do bloco, enquanto a DAG 2 comprova que o layout final funciona como um todo.

## Fluxo dos arquivos de cada unidade

O fluxo abaixo descreve o caminho por unidades implementado em
`mapping_unit_generation.py`. Na DAG, seleção e geração acontecem dentro da
tarefa `gerar_layout_candidato_llm`. Cada unidade percorre o ciclo completo
antes de começar a seguinte.

```text
Contrato da unidade + inventário do Docling
  → código procura candidatos                 → prefiltro_evidencia.json
  → prepara chamada de seleção                → entrada_llm_selecao_artefatos.json
  → LLM responde                              → resposta_llm_selecao_artefatos.json
  → código valida seleção e âncoras            → selecao_artefatos_layout.json
  → código avalia redução das evidências      → poda_evidencia.json
  → código lê estrutura das tabelas           → estrutura_tabelas.json
  → prepara chamada de mapeamento             → entrada_llm_fragmento_layout_signature.json
  → LLM propõe mapeamento                     → resposta_llm_fragmento_layout_signature.json
  → código valida e preenche faixas de linhas  → faixas_por_codigo.json
  → salva fragmento validado e ajustado        → fragmento_layout_signature.json
```

### O que cada arquivo registra

| Arquivo | Quem o produz e quando | Conteúdo e finalidade |
| --- | --- | --- |
| `prefiltro_evidencia.json` | Código, antes da chamada de seleção. | Deriva termos dos requisitos, indicadores, sinônimos e entidades do contrato. Procura no resumo do inventário e, quando necessário, no artefato completo. Registra candidatos por requisito e arquivos lidos. `excluidos_apos_leitura` identifica os arquivos lidos que ficaram fora da lista de candidatos do prefiltro. Se a lista de um requisito fica vazia, a seleção pela LLM ainda pode usar o inventário. |
| `entrada_llm_selecao_artefatos.json` | Código, ao preparar a primeira chamada. | Guarda `system_prompt`, `user_payload`, formato de resposta exigido, modelo, parâmetros e versões dos prompts. Permite inspecionar o contexto efetivamente enviado para escolher as fontes. |
| `resposta_llm_selecao_artefatos.json` | Código, ao receber o retorno da LLM. | Preserva a resposta textual em `raw_response`, o JSON interpretado em `parsed_response` quando disponível e os metadados da chamada. Registra o retorno anterior à aprovação da seleção. |
| `selecao_artefatos_layout.json` | Código, após validar a seleção. | Lista arquivos, motivos e coberturas por requisito. As âncoras são trechos literais cuja presença foi conferida na evidência. Caminhos precisam pertencer ao inventário e as coberturas precisam corresponder à unidade. |
| `poda_evidencia.json` | Código, após a seleção validada. | Registra `mantidos`, `descartados` e `motivo`. Compara âncoras verificadas com indicadores obrigatórios e sinônimos do contrato. Remove evidência genérica somente quando a específica cobre todos esses indicadores. Sem essa cobertura ou sem indicadores declarados no formato consumido pela regra, mantém o conjunto. |
| `estrutura_tabelas.json` | Código, ao preparar o contexto de mapeamento com tabelas. | Lê `schema` e `rows` do Docling. Registra cabeçalhos, coluna dos rótulos e papéis de período esperados quando o contrato permite resolvê-los. Cabeçalhos genéricos podem ser substituídos pela primeira linha quando ela satisfaz a heurística de cabeçalho. |
| `entrada_llm_fragmento_layout_signature.json` | Código, antes da segunda chamada. | Guarda em `messages` as instruções, o contrato limitado à unidade, os alvos e as evidências mantidas, além de modelo, parâmetros e versões dos prompts. A LLM recebe o necessário para propor o mapeamento. |
| `resposta_llm_fragmento_layout_signature.json` | Código, ao receber a proposta da LLM. | Registra texto recebido, JSON interpretado e metadados da chamada. Contém a proposta anterior ao preenchimento posterior de faixas pelo código. |
| `faixas_por_codigo.json` | Código, depois da validação do fragmento, quando há registro de processamento de faixas. | Localiza intervalos pelas linhas de dados ou pelos rótulos inicial/final propostos. Para tabela inteira, considera cabeçalhos, divisões, totais/subtotais e presença de números nas colunas lidas. Registra por instrução as faixas e a ação executada. |
| `fragmento_layout_signature.json` | Código, após validar o fragmento e processar suas faixas. | Guarda o mapeamento aprovado da unidade, com eventuais faixas preenchidas e campos sem mapeamento declarados. É o fragmento usado na consolidação. |

A existência de `estrutura_tabelas.json` depende de haver estrutura tabular no
contexto. A existência de `faixas_por_codigo.json` depende de haver registro de
processamento de faixas. Uma falha anterior pode impedir a criação dos arquivos
seguintes. Respostas corrigíveis podem gerar novas chamadas, arquivos de erro
e registros de tentativa.

### Exemplo observado no boletim de setembro de 2026

Na execução de 24/11/2026, com o contrato ABECIP v2.5.0, foram produzidas as
unidades `financiamentos_imobiliarios` e `poupanca_sbpe`.

- O prefiltro leu 20 artefatos e terminou com listas de candidatos vazias. A
  seleção pela LLM prosseguiu usando o inventário.
- A seleção de financiamentos escolheu `table002.json` a `table007.json`.
  A seleção de poupança escolheu `table002.json`.
- A poda manteve todos os arquivos, com o motivo
  `unidade sem indicador obrigatorio declarado`. O contrato tem requisitos
  obrigatórios de mapeamento, mas essa regra consulta indicadores obrigatórios
  declarados nos grupos de métricas.
- A estrutura registrou cabeçalhos e colunas de rótulos.
  `papeis_esperados` ficou vazio.
- Para as séries mensais, a LLM propôs `Jan` a `Set`, e o código localizou a
  faixa inclusiva `[0, 8]`. Os índices começam em zero.
- Os dois fragmentos foram consolidados e revalidados pela DAG 2. A publicação
  dessa execução gerou a versão de layout `v2.55.0`.

A seleção pode conter fontes adicionais que o fragmento final deixa de usar.
Neste exemplo, `table002.json` apareceu na seleção de financiamentos, mas o
mapeamento mensal de financiamentos usou `table003.json`.

### Responsabilidades e limites

Prefiltro, poda, leitura de estrutura e preenchimento das faixas executam regras
determinísticas em Python. Algumas entradas dessas regras vêm de decisões da
LLM, como fontes selecionadas, âncoras, colunas e rótulos. A qualidade da extração
do Docling também afeta o resultado. Uma âncora existente comprova presença
literal, mas a escolha semântica da fonte ainda precisa ser conferida pelo
mapeamento e pela revalidação.

O preenchimento das faixas pode excluir linhas de total/subtotal segundo o
rótulo. Essa regra tem impacto direto nas linhas entregues ao resolvedor.
Para uma parte da tabela, a LLM escolhe os rótulos e o código calcula os índices.

### Implementação e histórico

- [Orquestração por unidade](../../../src/document_processing/application/use_cases/fallback/mapping_unit_generation.py)
  e [seleção de artefatos](../../../src/document_processing/application/use_cases/fallback/artifact_selection.py).
- [Prefiltro](../../../src/document_processing/domain/fallback/evidence_prefilter.py)
  e [poda](../../../src/document_processing/domain/fallback/evidence_pruning.py).
- [Leitura de estrutura](../../../src/document_processing/domain/fallback/table_structure.py)
  e [faixas de linhas](../../../src/document_processing/domain/fallback/table_row_ranges.py).
- O Git registra a poda em 13/09/2026 (`b23c224`), o prefiltro em
  13/09/2026 (`938d2fa`, ampliado em 17/09 por `4fccdcf`), a estrutura em
  18/09/2026 (`a43f026`) e as faixas em 21/10/2026 (`4675ccf`).
  Os experimentos e as correções posteriores estão no
  [registro de releases](../../guides/registro-de-releases.md).

## Persistência esperada no MinIO

```text
fallback/abecip/abecip/document_id=<id>/execution_id=<dag3-id>/
  plano_mapeamento.json
  unidades/
    financiamentos_imobiliarios/
      prefiltro_evidencia.json
      entrada_llm_selecao_artefatos.json
      resposta_llm_selecao_artefatos.json
      selecao_artefatos_layout.json
      poda_evidencia.json
      estrutura_tabelas.json
      entrada_llm_fragmento_layout_signature.json
      resposta_llm_fragmento_layout_signature.json
      faixas_por_codigo.json
      fragmento_layout_signature.json
    poupanca_sbpe/
      ...
  layout_signature_candidato_consolidado.json
  layout_signature_candidato.json
  revalidation/
    validacao_layout_signature.json
    schema_saida_resolvido.json
    auditoria_resolucao.json
    resultado_revalidacao_candidato.json
  publicacao_layout_signature.json
```

Arquivos de erro e tentativas adicionais recebem o sufixo
`_tentativa_<n>.json` e permanecem no diretório da unidade correspondente.

## Por que este formato escala

Em um PDF grande, cada chamada lida somente com uma parte semanticamente coesa
do problema. Isso reduz o risco de esgotar tokens antes de produzir JSON e
mantém relações importantes dentro da mesma tabela, gráfico ou seção.

A divisão continua sendo controlada pelo contrato. Para qualquer novo domínio,
basta declarar os campos obrigatórios com paths semânticos consistentes. Não há
uma regra especial para boletins ABECIP, construtoras ou qualquer outro PDF.

O limite atual é deliberado: se muitos campos extensos estiverem sob a mesma
raiz semântica, eles continuarão na mesma unidade. Uma evolução futura pode
permitir subdivisões também declaradas no contrato, mantendo a divisão
determinística e sem incorporar regras de domínio ao código.
