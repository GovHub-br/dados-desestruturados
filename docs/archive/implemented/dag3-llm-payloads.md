# Plano de Payloads LLM da DAG 3

## Objetivo

Este documento descreve apenas a parte dos payloads enviados para a LLM na DAG 3
`dag_valida_e_fallback_llm`.

Ele separa:

- como o payload funciona hoje;
- por que o desenho atual ainda mistura coisas demais;
- como o fluxo deve ficar;
- quais payloads devem existir para cada tipo de fallback;
- quais mudanças de implementação serão necessárias.

A ideia central é simples: a LLM não deve receber um contexto genérico grande e
depois filtrado. Cada payload deve nascer pronto para a etapa e para o tipo de
fallback que está sendo executado.

## Estado Atual

Hoje a DAG 3 monta um contexto único chamado `fallback_problem_context`.

Esse contexto é criado em:

```text
airflow/plugins/services/fallback/context_builder.py
```

Depois ele é usado pelo orquestrador em:

```text
airflow/plugins/services/fallback/orchestrator.py
```

O fluxo atual é:

```text
DAG 3 carrega artefatos
  -> monta fallback_problem_context único
  -> se necessário, LLM seleciona artefatos pelo inventory.json
  -> DAG 3 carrega os artefatos selecionados
  -> LLM gera layout_signature_candidato
  -> DAG 3 valida o candidato
```

## Como o Payload Atual é Montado

O `FallbackProblemContextBuilder.build_fallback_problem_context(...)` monta um
payload com vários blocos:

```json
{
  "tipo_artefato": "fallback_problem_context",
  "status": "contexto_montado",
  "escopo_permitido": "...",
  "llm_constraints": {},
  "falha": {},
  "layout_signature_relevante": {},
  "contrato_semantico_relevante": {},
  "inventario_extracao": {},
  "manifesto_extracao_ref": {},
  "_manifesto_extracao_completo": {}
}
```

Depois, o `FallbackLlmService.load_fallback_context(...)` adiciona outros blocos
ao mesmo contexto:

```json
{
  "fallback_context": {},
  "layout_signature_base_ref": {},
  "layout_signature_base_editable_sections": {},
  "layout_signature_base_validation_context": {},
  "modo_criacao_inicial_layout": true
}
```

Na prática, esse contexto mistura três tipos de informação:

1. informação útil para a LLM;
2. metadado operacional da DAG;
3. metadado de debug/rastreabilidade.

## Payload Atual da Seleção de Artefatos

Quando a política exige ou recomenda inventário, a primeira chamada LLM é a
seleção de artefatos.

Hoje ela recebe quase o mesmo `fallback_problem_context`, removendo apenas:

- chaves internas iniciadas por `_`;
- `artefatos_contexto_llm`;
- `estado_chunking`;
- alguns metadados filtrados temporariamente por `_llm_visible_context`.

O objetivo dessa chamada é a LLM responder:

```json
{
  "tipo_artefato": "selecao_artefatos_layout",
  "artifact_paths": [
    {
      "path": "tables/table001.json",
      "motivo": "por que abrir este arquivo",
      "campos_saida": ["campo.do.schema"]
    }
  ]
}
```

Problema: a seleção de artefatos não precisa receber todo o contexto operacional
da DAG 3. Ela precisa entender:

- o que precisa ser encontrado;
- quais campos do contrato importam;
- quais falhas ou objetivos guiam a busca;
- quais artefatos existem no `inventory.json`.

## Payload Atual da Criação do Layout Candidato

Depois da seleção, a DAG 3 carrega os artefatos escolhidos e faz a chamada para
gerar o `layout_signature_candidato`.

Hoje o payload de geração é composto por:

- o contexto base;
- a linhagem do candidato;
- a seleção da LLM;
- os artefatos carregados;
- estado de chunking, quando existir.

Conceitualmente:

```json
{
  "escopo_permitido": "...",
  "llm_constraints": {},
  "falha": {},
  "layout_signature_relevante": {},
  "contrato_semantico_relevante": {},
  "inventario_extracao": {},
  "fallback_context": {},
  "layout_candidate_lineage": {},
  "selecao_artefatos_llm": {},
  "artefatos_contexto_llm": []
}
```

Problema: esse formato ainda tenta servir para todos os casos. Para correção
parcial ele faz sentido. Para criação inicial ou regeneração ampla, ele pode
conter informações antigas ou irrelevantes.

## Problema Principal do Desenho Atual

O desenho atual parte de um contexto único e depois tenta reduzir o payload antes
de enviar para a LLM.

Isso levou à função temporária:

```python
_llm_visible_context(fallback_problem_context)
```

Ela remove chaves como:

- `tipo_artefato`;
- `status`;
- `manifesto_extracao_ref`;
- `modo_criacao_inicial_layout`.

Essa função resolve o vazamento imediato de metadados, mas não é o desenho
ideal.

O ideal é o payload já nascer diferente conforme:

- o tipo de fallback;
- a etapa da LLM.

## Novo Fluxo Proposto

O novo desenho deve separar o fluxo em duas dimensões.

Primeira dimensão: tipo de fallback.

```text
correcao_parcial_mapeamento
criacao_inicial_layout
regeneracao_total_mapeamento
```

Segunda dimensão: etapa da LLM.

```text
selecao_de_artefatos
geracao_do_layout_candidato
```

Com isso, a DAG 3 passa a ter payloads específicos:

```text
FLUXO A
correcao_parcial + selecao_de_artefatos
correcao_parcial + geracao_do_layout_candidato

FLUXO B
criacao_inicial + selecao_de_artefatos
criacao_inicial + geracao_do_layout_candidato

FLUXO C
regeneracao_total + selecao_de_artefatos
regeneracao_total + geracao_do_layout_candidato
```

## Fluxo A: Correção Parcial de Layout Existente

Esse fluxo acontece quando a DAG 2 tentou usar um layout vigente e encontrou
uma falha localizada.

Exemplos:

- uma linha mudou de nome;
- uma coluna mudou de cabeçalho;
- poucos campos obrigatórios falharam;
- um seletor quebrou;
- o valor veio de fonte errada, mas a estrutura geral ainda existe.

Nesse caso, faz sentido a LLM receber o problema da DAG 2, porque a tarefa é
corrigir algo específico no layout existente.

### A1. Payload de Seleção de Artefatos

Objetivo da chamada:

```text
Escolher quais artefatos devem ser abertos para corrigir os campos quebrados.
```

Payload alvo:

```json
{
  "tipo_payload": "selecao_artefatos_correcao_parcial",
  "escopo_permitido": "correcao_parcial_mapeamento",
  "falha": {
    "codigos_falha": [],
    "campos_quebrados": [],
    "regras_reprovadas": [],
    "campos_obrigatorios_nao_resolvidos": []
  },
  "contrato_semantico_relevante": {
    "schema_saida_paths": [],
    "schema_saida_array_paths": [],
    "schema_saida_trechos_relevantes": {}
  },
  "layout_signature_relevante": {
    "mapeamento_canonico_relevante": {},
    "regras_deteccao_mudanca_relevantes": [],
    "fontes_relevantes": []
  },
  "inventario_extracao": {
    "politica_uso": {},
    "resumo": {}
  }
}
```

Não deve receber:

- manifesto completo;
- artefatos completos;
- metadados de debug;
- contadores operacionais;
- configuração interna da DAG;
- layout inteiro se só alguns campos falharam.

### A2. Payload de Geração do Layout Candidato

Objetivo da chamada:

```text
Gerar um layout_signature_candidato focado no patch das partes quebradas.
```

Payload alvo:

```json
{
  "tipo_payload": "layout_candidato_correcao_parcial",
  "escopo_permitido": "correcao_parcial_mapeamento",
  "layout_candidate_lineage": {
    "document_id": "...",
    "execution_id_origem": "...",
    "fallback_execution_id": "..."
  },
  "falha": {},
  "contrato_semantico_relevante": {},
  "layout_signature_base_ref": {},
  "layout_signature_relevante": {},
  "layout_signature_base_validation_context": {},
  "selecao_artefatos_llm": {},
  "artefatos_contexto_llm": []
}
```

Nesse fluxo, a LLM pode ver o layout anterior como fonte operacional forte,
porque a tarefa é corrigir parcialmente o layout já conhecido.

## Fluxo B: Criação Inicial de Layout

Esse fluxo acontece quando não existe `current.json` ou layout signature vigente
para a empresa/documento.

Aqui não existe layout quebrado. Existe uma extração e um contrato semântico.

Portanto, a LLM não deve receber contexto de patch.

Não faz sentido enviar:

- `layout_signature_relevante`;
- `layout_signature_base_editable_sections`;
- regras reprovadas de um layout anterior;
- campos quebrados derivados de mapeamento antigo;
- `modo_criacao_inicial_layout` como flag solta.

### B1. Payload de Seleção de Artefatos

Objetivo da chamada:

```text
Escolher quais artefatos da extração parecem cobrir os campos do contrato.
```

Payload alvo:

```json
{
  "tipo_payload": "selecao_artefatos_criacao_inicial",
  "escopo_permitido": "criacao_inicial_layout",
  "contrato_semantico_relevante": {
    "schema_saida_paths": [],
    "schema_saida_array_paths": [],
    "entidades": {},
    "metricas": {}
  },
  "inventario_extracao": {
    "inventario_completo_enviado": true,
    "resumo": {}
  },
  "objetivo": {
    "selecionar_fontes_para_criar_layout_signature": true,
    "nao_resolver_valores_finais": true
  }
}
```

### B2. Payload de Geração do Layout Candidato

Objetivo da chamada:

```text
Gerar o primeiro layout_signature_candidato completo para aquela empresa.
```

Payload alvo:

```json
{
  "tipo_payload": "layout_candidato_criacao_inicial",
  "escopo_permitido": "criacao_inicial_layout",
  "layout_candidate_lineage": {
    "document_id": "...",
    "execution_id_origem": "...",
    "fallback_execution_id": "..."
  },
  "contrato_semantico_relevante": {},
  "selecao_artefatos_llm": {},
  "artefatos_contexto_llm": [],
  "regras_de_saida": {
    "gerar_layout_signature_candidato": true,
    "base_layout_signature_deve_ser_null": true,
    "nao_gerar_schema_saida_resolvido": true,
    "nao_gerar_valores_finais": true
  }
}
```

Nesse fluxo, `base_layout_signature` deve ser `null`.

## Fluxo C: Regeneração Total de Layout

Esse fluxo acontece quando existe layout antigo, mas a ruptura é ampla demais
para tratar como patch.

Exemplos:

- tabela crítica sumiu;
- seção crítica mudou completamente;
- vários campos obrigatórios falharam;
- a representação mudou de tabela para texto/cards;
- o perfil estrutural esperado não existe mais.

Nesse caso, o layout anterior pode aparecer como referência histórica, mas não
como fonte de verdade.

### C1. Payload de Seleção de Artefatos

Objetivo da chamada:

```text
Redescobrir as fontes atuais no documento usando contrato + inventário.
```

Payload alvo:

```json
{
  "tipo_payload": "selecao_artefatos_regeneracao_total",
  "escopo_permitido": "regeneracao_total_mapeamento",
  "contrato_semantico_relevante": {
    "schema_saida_paths": [],
    "schema_saida_array_paths": [],
    "entidades": {},
    "metricas": {}
  },
  "inventario_extracao": {
    "politica_uso": {
      "uso_inventario": "obrigatorio"
    },
    "resumo": {}
  },
  "layout_anterior_como_referencia_fraca": {
    "empresa": "...",
    "tipo_documento": "...",
    "fontes_relevantes_antigas": [],
    "observacao": "usar apenas como pista; redescobrir fontes pelo inventario atual"
  },
  "falha_resumida": {
    "codigos_falha": [],
    "motivos": []
  }
}
```

Não deve receber:

- mapeamento canônico antigo inteiro como verdade;
- contexto de patch;
- campos quebrados como se fossem a única prioridade;
- regras antigas como contrato de validade.

### C2. Payload de Geração do Layout Candidato

Objetivo da chamada:

```text
Gerar um layout_signature_candidato completo, substituindo o mapeamento antigo.
```

Payload alvo:

```json
{
  "tipo_payload": "layout_candidato_regeneracao_total",
  "escopo_permitido": "regeneracao_total_mapeamento",
  "layout_candidate_lineage": {
    "document_id": "...",
    "execution_id_origem": "...",
    "fallback_execution_id": "..."
  },
  "contrato_semantico_relevante": {},
  "base_layout_signature": {
    "object_key": "...",
    "uso": "linhagem_e_referencia_fraca"
  },
  "selecao_artefatos_llm": {},
  "artefatos_contexto_llm": [],
  "regras_de_saida": {
    "gerar_layout_signature_candidato_completo": true,
    "nao_gerar_schema_saida_resolvido": true,
    "nao_gerar_valores_finais": true
  }
}
```

## Novo Fluxo Interno Proposto

O fluxo interno da DAG 3 deve ficar assim:

```text
1. DAG 3 carrega contexto operacional
2. DAG 3 classifica o fallback
3. DAG 3 monta debug_metadata separado
4. DAG 3 escolhe o construtor de payload pelo escopo
5. DAG 3 monta payload de seleção de artefatos
6. LLM seleciona artefatos
7. DAG 3 valida paths contra inventory.json
8. DAG 3 carrega artefatos selecionados
9. DAG 3 monta payload de geração do candidato
10. LLM gera layout_signature_candidato
11. DAG 3 valida candidato
12. DAG 3 persiste candidato
13. DAG 2 revalida
14. DAG 3 publica nova versão se a revalidação passar
```

## Mudanças de Implementação

### 1. Separar contexto operacional de payload LLM

Hoje o mesmo objeto serve para muitas coisas. O novo retorno deve separar:

```json
{
  "fallback_context": {},
  "debug_metadata": {},
  "loaded_artifacts": {},
  "llm_payloads": {}
}
```

### 2. Criar builders de payload por etapa

Criar funções ou métodos dedicados:

```python
build_artifact_selection_payload(...)
build_candidate_generation_payload(...)
```

### 3. Criar builders de payload por escopo

Criar variações por tipo de fallback:

```python
build_partial_artifact_selection_payload(...)
build_partial_candidate_payload(...)
build_initial_creation_artifact_selection_payload(...)
build_initial_creation_candidate_payload(...)
build_full_remap_artifact_selection_payload(...)
build_full_remap_candidate_payload(...)
```

### 4. Remover `_llm_visible_context`

Depois que os payloads nascerem corretos, remover:

```python
_llm_visible_context(fallback_problem_context)
```

Essa função não deve ser necessária no desenho final.

### 5. Ajustar `select_relevant_artifacts`

Hoje ela recebe o contexto grande.

Deve passar a receber:

```python
select_relevant_artifacts(selection_payload, fallback_context)
```

### 6. Ajustar `generate_candidate_layout`

Hoje ela monta o payload de geração internamente a partir do contexto grande.

Deve passar a receber ou montar explicitamente:

```python
candidate_payload = build_candidate_generation_payload(...)
```

Depois disso, chama a LLM com esse payload já pronto.

### 7. Persistir debug sem enviar para a LLM

Os artefatos de observabilidade devem continuar contendo tudo que ajuda a
debugar:

- object keys;
- contadores;
- escopo escolhido;
- política de inventário;
- contexto operacional;
- resposta bruta da LLM;
- erros de parse/validação.

Mas isso deve ficar fora de `user_payload` enviado à LLM, exceto quando for
necessário para a tarefa.

## Critérios de Aceite

- Cada chamada LLM tem um payload próprio e nomeado.
- O payload de seleção é diferente do payload de geração.
- O payload de correção parcial é diferente do payload de criação inicial.
- O payload de regeneração total trata o layout antigo apenas como referência
  fraca.
- `debug_metadata` é persistido, mas não enviado no prompt.
- `_llm_visible_context` é removida.
- Nenhum payload da LLM contém metadados puramente operacionais por acidente.
- A LLM continua impedida de gerar `schema_saida_resolvido` ou valores finais.

## Ordem Recomendada

1. Criar este novo contrato de payload em código, sem mudar a lógica da LLM.
2. Implementar primeiro o fluxo de `correcao_parcial_mapeamento`.
3. Implementar depois `criacao_inicial_layout`.
4. Implementar por último `regeneracao_total_mapeamento`.
5. Remover `_llm_visible_context`.
6. Atualizar testes para verificar exatamente o payload enviado à LLM em cada
   fluxo.
7. Rodar a DAG 3 manualmente e comparar os artefatos `entrada_llm_*.json`.

