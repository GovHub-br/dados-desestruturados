# Classificacao Deterministica de Fallback da DAG 3

Este documento explica como a DAG 3 classifica uma falha da DAG 2 antes de
chamar qualquer LLM.

O metodo central e:

```python
FallbackLlmService.classify_fallback_scope(validation, audit)
```

Ele recebe dois artefatos da DAG 2:

- `validacao_layout_signature.json`;
- `auditoria_resolucao.json`.

A classificacao e deterministica. A LLM nao participa dessa decisao.

## Objetivo da Classificacao

A DAG 3 precisa decidir qual limite sera imposto para a futura chamada LLM.

Existem tres saidas possiveis:

- `correcao_parcial_mapeamento`;
- `regeneracao_total_mapeamento`;
- `falha_nao_suportada_para_fallback_automatico`.

Essa classificacao tambem preenche `llm_constraints`, que dira para as proximas
etapas se a LLM pode ser chamada e se ela pode propor apenas correcao parcial ou
regeneracao total.

## Passo 1: Validar Status da DAG 2

O metodo primeiro olha:

```json
status_compatibilidade.status
```

### Quando status e `compativel`

A DAG 3 recusa fallback.

Motivo: se a DAG 2 validou o layout como compativel, nao existe motivo para
chamar LLM.

Resultado esperado:

```text
RuntimeError: Fallback recusado: validacao compativel nao aciona DAG 3.
```

### Quando status e `incompativel`

A classificacao continua.

Nesse caso, a DAG 3 passa a analisar:

- regras deterministicas reprovadas;
- campos obrigatorios nao resolvidos;
- quantidade e tipo das falhas.

### Quando status e outro valor

Exemplo:

- `parcial`;
- `erro`;
- vazio;
- qualquer status desconhecido.

Classificacao:

```text
falha_nao_suportada_para_fallback_automatico
```

Motivo: o status da validacao nao e confiavel o suficiente para automatizar uma
correcao.

## Passo 2: Ler Regras Reprovadas

O metodo filtra:

```json
regras_executadas[].status == "reprovada"
```

Cada regra reprovada e interpretada pelo campo:

```json
tipo_teste
```

## Caso 1: Correcao Parcial de Mapeamento

Classificacao:

```text
correcao_parcial_mapeamento
```

Esse caso significa:

> O layout conhecido ainda parece valido em geral, mas alguns seletores ou
> pontos especificos quebraram.

A LLM podera propor uma alteracao pequena no `mapeamento_canonico`.

### Linha Critica Ausente

Origem:

```json
{
  "tipo_teste": "linha_existe_em_tabela",
  "status": "reprovada"
}
```

Tratamento:

```text
correcao_parcial_mapeamento
```

Motivo gerado:

```text
linha critica ausente em <id_regra>
```

Exemplo conceitual:

O layout esperava encontrar a linha `Numero de Unidades`, mas no PDF novo ela
veio como `Unidades Lancadas`.

Nesse caso, provavelmente nao precisamos reconstruir todo o layout. Basta pedir
para a LLM sugerir um novo seletor, alias ou rotulo aceito para aquela linha.

### Coluna Critica Ausente Sem Perda de Papeis de Periodo

Origem:

```json
{
  "tipo_teste": "perfil_colunas_periodo_existe_em_tabela",
  "status": "reprovada",
  "evidencia": {
    "papeis_periodo_resolvidos": [...]
  }
}
```

Tratamento:

```text
correcao_parcial_mapeamento
```

Isso acontece somente quando a regra falhou, mas o metodo nao detectou perda
clara de papeis de periodo.

Motivo gerado:

```text
coluna critica ausente em <id_regra>
```

Exemplo conceitual:

A tabela continua sendo a mesma, mas uma coluna mudou de posicao ou cabecalho de
forma leve. A LLM pode propor ajuste pontual no seletor da coluna.

### Valor Nao Normalizavel

Origem:

```json
{
  "tipo_teste": "valor_normalizavel",
  "status": "reprovada"
}
```

Tratamento:

```text
correcao_parcial_mapeamento
```

Motivo gerado:

```text
valor nao normalizavel em <id_regra>
```

Exemplo conceitual:

O seletor encontrou uma celula, mas o valor veio em formato inesperado para o
normalizador.

Pode ser caso de:

- separador numerico diferente;
- texto junto do numero;
- celula com nota de rodape;
- valor em branco onde o layout esperava numero.

A correcao tende a ser pontual: ajustar seletor, normalizacao ou regra de
leitura daquele campo.

### Poucos Campos Obrigatorios Nao Resolvidos

Origem:

```json
auditoria_resolucao[]
```

O metodo procura itens com:

```json
{
  "obrigatorio": true,
  "status_resolucao": "nao_resolvido"
}
```

ou status diferente de `resolvido`.

Tratamento:

```text
correcao_parcial_mapeamento
```

Condição atual:

```text
ate 2 campos obrigatorios nao resolvidos
```

Motivo gerado:

```text
poucos campos obrigatorios nao resolvidos
```

Exemplo conceitual:

Apenas `periodo_referencia` e um valor de tabela falharam. O restante do schema
foi resolvido. Isso indica que o layout ainda e aproveitavel.

### Campo Obrigatorio com Seletor Quebrado

Origem:

```json
{
  "obrigatorio": true,
  "status_resolucao": "erro"
}
```

Tratamento:

```text
correcao_parcial_mapeamento
```

Motivo gerado:

```text
campo obrigatorio com seletor quebrado
```

Exemplo conceitual:

O mapeamento apontou para uma fonte, mas a leitura gerou erro. A DAG 3 entende
que a LLM pode sugerir uma correcao localizada para esse seletor.

## Caso 2: Regeneracao Total de Mapeamento

Classificacao:

```text
regeneracao_total_mapeamento
```

Esse caso significa:

> A estrutura do documento mudou o suficiente para nao confiar mais em ajustes
> pontuais.

A LLM podera propor um mapeamento mais amplo, ainda limitado pelo contrato
semantico.

### Tabela ou Artefato Critico Ausente

Origem:

```json
{
  "tipo_teste": "arquivo_existe",
  "status": "reprovada"
}
```

Tratamento:

```text
regeneracao_total_mapeamento
```

Motivo gerado:

```text
tabela ou artefato critico ausente em <id_regra>
```

Exemplo conceitual:

O layout esperava `tables/table001.json`, mas esse artefato nao existe na nova
extracao. Talvez a tabela tenha mudado de pagina, sido quebrada em mais tabelas
ou extraida de outra forma.

Nesse caso, trocar um rotulo nao basta. O mapeamento precisa ser reconstruido
com base nos artefatos disponiveis.

### Secao Critica Ausente

Origem:

```json
{
  "tipo_teste": "secao_existe",
  "status": "reprovada"
}
```

Tratamento:

```text
regeneracao_total_mapeamento
```

Motivo gerado:

```text
secao critica ausente em <id_regra>
```

Exemplo conceitual:

A secao de lancamentos ou vendas nao foi encontrada. Isso pode indicar mudanca
estrutural no PDF, troca de titulo, agrupamento diferente ou erro de extracao.

Como a secao organiza o contexto dos dados, a DAG trata como ruptura ampla.

### Perfil Critico Declarado no Layout Nao Resolvido

Origem:

```json
{
  "tipo_teste": "perfil_colunas_periodo_existe_em_tabela",
  "status": "reprovada",
  "evidencia": {
    "itens_perfil_resolvidos": [
      {
        "papel": "campo_critico",
        "valor_encontrado": null,
        "ok": false
      }
    ]
  }
}
```

O nome da regra pode variar conforme o layout signature. O ponto importante e
que o layout declarou um perfil estrutural critico e algum item desse perfil nao
foi encontrado.

Tratamento:

```text
regeneracao_total_mapeamento
```

Motivo gerado:

```text
perfil critico declarado no layout nao resolvido em <id_regra>
```

Exemplo conceitual:

A DAG nao consegue identificar com seguranca itens estruturais que o layout
marcou como criticos, como colunas esperadas, marcadores de uma tabela, papeis
de um bloco ou outro perfil definido especificamente para aquele tipo de PDF.

Como os valores dependem desse perfil, a correcao parcial pode preencher dados
no lugar errado. Por isso vira regeneracao total.

### Multiplas Regras Criticas Reprovadas

Origem:

```text
len(regras_reprovadas) >= 3
```

Tratamento:

```text
regeneracao_total_mapeamento
```

Motivo gerado:

```text
multiplas regras deterministicas criticas reprovadas
```

Exemplo conceitual:

Falharam ao mesmo tempo:

- uma secao;
- uma tabela;
- uma linha;
- uma regra de valor.

Mesmo que uma dessas falhas isolada pudesse ser parcial, o conjunto indica que
o layout conhecido perdeu confiabilidade.

### Multiplos Campos Obrigatorios Nao Resolvidos

Origem:

```json
auditoria_resolucao[]
```

Condição atual:

```text
mais de 2 campos obrigatorios nao resolvidos
```

Tratamento:

```text
regeneracao_total_mapeamento
```

Motivo gerado:

```text
multiplos campos obrigatorios nao resolvidos
```

Exemplo conceitual:

Se muitos campos obrigatorios falham ao mesmo tempo, a DAG entende que nao e um
ajuste localizado. O mapeamento precisa ser reavaliado de forma ampla.

## Caso 3: Falha Nao Suportada Para Fallback Automatico

Classificacao:

```text
falha_nao_suportada_para_fallback_automatico
```

Esse caso significa:

> A DAG 3 nao tem evidencias estruturadas suficientes para automatizar a
> correcao com seguranca.

Nesse caso:

- `llm_permitida = false`;
- a task `classificar_falha_fallback` falha com erro claro;
- nenhuma proposta LLM deve ser gerada.

### Status de Validacao Desconhecido

Origem:

```json
{
  "status_compatibilidade": {
    "status": "..."
  }
}
```

Quando o status nao e `compativel` nem `incompativel`.

Tratamento:

```text
falha_nao_suportada_para_fallback_automatico
```

Motivo gerado:

```text
status_compatibilidade desconhecido: <status>
```

### Tipo de Regra Sem Classificador Automatico

Origem:

```json
{
  "tipo_teste": "algum_tipo_novo",
  "status": "reprovada"
}
```

Tratamento:

```text
falha_nao_suportada_para_fallback_automatico
```

Motivo gerado:

```text
tipo de regra reprovada sem classificador automatico: <tipo_teste>
```

Exemplo conceitual:

A DAG 2 passou a gerar um novo tipo de regra, mas a DAG 3 ainda nao sabe se essa
falha representa ajuste parcial, regeneracao total ou algo fora do escopo.

Nesse caso, a decisao correta e parar, documentar o tipo novo e implementar uma
regra de classificacao antes de automatizar.

### Validacao Incompativel Sem Falhas Classificaveis

Origem:

O status veio como:

```json
{
  "status": "incompativel"
}
```

mas nao ha:

- regras reprovadas classificaveis;
- campos obrigatorios nao resolvidos;

Tratamento:

```text
falha_nao_suportada_para_fallback_automatico
```

Motivo gerado:

```text
validacao incompativel sem falhas classificaveis para fallback automatico
```

Exemplo conceitual:

O relatorio diz que o layout esta incompativel, mas nao explica por que. A DAG 3
nao deve chamar LLM sem saber qual problema precisa ser corrigido.

## Prioridade Entre Classificacoes

Quando existem motivos de mais de uma classe, a prioridade atual e:

1. `regeneracao_total_mapeamento`;
2. `correcao_parcial_mapeamento`;
3. `falha_nao_suportada_para_fallback_automatico`.

Isso significa que, se houver uma falha parcial e uma falha estrutural ao mesmo
tempo, vence a regeneracao total.

Exemplo:

- uma linha critica ausente;
- uma secao critica ausente.

Resultado:

```text
regeneracao_total_mapeamento
```

Motivo: a secao ausente torna o layout amplo pouco confiavel.

## Formato de Saida

O metodo retorna um dicionario neste formato:

```json
{
  "fallback_scope": "correcao_parcial_mapeamento",
  "llm_permitida": true,
  "motivos": [
    "linha critica ausente em ROW_LANC_UNID_001"
  ],
  "codigos_falha": [
    "LINHA_CRITICA_AUSENTE"
  ],
  "metricas": {
    "regras_reprovadas": 1,
    "campos_obrigatorios_nao_resolvidos": 0
  },
  "evidencias": {
    "regras_reprovadas": [
      {
        "id_regra": "ROW_LANC_UNID_001",
        "tipo_teste": "linha_existe_em_tabela",
        "codigo_falha": "LINHA_CRITICA_AUSENTE",
        "arquivo_origem": "tables/table001.json"
      }
    ],
    "campos_obrigatorios_nao_resolvidos": []
  }
}
```

Esse resultado entra no `loaded_context` da DAG 3 como:

```json
{
  "fallback_scope": "...",
  "fallback_classification": {...},
  "llm_constraints": {
    "fallback_scope": "...",
    "chamar_llm": true,
    "permitir_correcao_parcial": true,
    "permitir_regeneracao_total": false
  }
}
```

## Como a DAG Usa Essa Classificacao

Na DAG:

```python
loaded_context = carregar_artefatos_fallback(fallback_context)
fallback_classification = classificar_falha_fallback(loaded_context)
```

A task `classificar_falha_fallback` faz a barreira operacional:

- se a classificacao permite LLM, a DAG segue;
- se for `falha_nao_suportada_para_fallback_automatico`, a DAG falha;
- se a validacao era compativel, a DAG ja foi recusada antes, na leitura do
  contexto.

## Resumo Mental

Use esta leitura rapida:

- falhou uma linha, coluna, valor ou poucos campos: correcao parcial;
- sumiu tabela, secao, perfil critico ou muitas coisas ao mesmo tempo: regeneracao total;
- status ou regra nao explicam a falha: sem fallback automatico.
