# Exemplo ABECIP: DAG 3 criando um Layout Signature por Blocos

## Objetivo do exemplo

Este documento mostra, passo a passo, como a DAG 3 pode criar um
`layout_signature` para o boletim da ABECIP sem enviar todo o contrato e todos
os artefatos de extração em uma única chamada LLM.

ABECIP é somente o exemplo. A regra de divisão é genérica: ela é derivada dos
paths declarados no contrato semântico, sem `if` por domínio, entidade, PDF ou
nome de seção.

## Ponto de partida

O contrato ABECIP declara estes campos obrigatórios de mapeamento:

```text
financiamentos_imobiliarios.serie_mensal_sbpe
financiamentos_imobiliarios.serie_historica_anual
financiamentos_imobiliarios.por_modalidade_e_instituicao
poupanca_sbpe.saldos_mensais
poupanca_sbpe.captacoes_liquidas_mensais
recursos_livres.observacoes
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
    },
    {
      "id": "recursos_livres",
      "campos_saida": [
        "recursos_livres.observacoes"
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
financiamentos nem de recursos livres. Ela deve apenas identificar os artefatos
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
evidência aprovada e o erro da validação. Uma falha em `recursos_livres`, por
exemplo, não reenvia o contexto de `financiamentos_imobiliarios`.

## 5. O quebra-cabeça é montado deterministicamente

Depois de todas as unidades serem aprovadas, a DAG une seus
`mapeamento_canonico` sem pedir uma nova chamada à LLM:

```text
fragmento financiamentos_imobiliarios
                 +
fragmento poupanca_sbpe
                 +
fragmento recursos_livres
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

## Persistência esperada no MinIO

```text
fallback/abecip/abecip/document_id=<id>/execution_id=<dag3-id>/
  plano_mapeamento.json
  unidades/
    financiamentos_imobiliarios/
      entrada_llm_selecao_artefatos.json
      selecao_artefatos_layout.json
      entrada_llm_fragmento_layout_signature.json
      resposta_llm_fragmento_layout_signature.json
      fragmento_layout_signature.json
    poupanca_sbpe/
      ...
    recursos_livres/
      ...
  layout_signature_candidato_consolidado.json
  layout_signature_candidato.json
  revalidation/
    validacao_layout_signature.json
    schema_saida_resolvido.json
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
