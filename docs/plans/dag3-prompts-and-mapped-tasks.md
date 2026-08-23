# Plano: prompts completos por unidade e mapped tasks na DAG 3

## Contexto e diagnostico

Na geracao escalavel, a DAG 3 divide deterministicamente os campos
obrigatorios do contrato em unidades semanticas. Cada unidade recebe somente o
subcontrato, os paths permitidos e os artefatos selecionados para ela. A decisao
de dividir e correta: reduz contexto sem delegar a divisao para a LLM.

O problema observado na execucao da ABECIP nao foi a divisao. A primeira unidade
selecionou corretamente `table004`, `table005` e `table006`, mas o prompt de
geracao do fragmento era apenas uma instrucao curta. A LLM respondeu com um DSL
proprio (`tabela`, `coluna`, `celula`) em vez das instrucoes executaveis aceitas
pela DAG 2 (`linhas_de_tabela`, `celula_de_tabela` etc.). No terceiro retry,
usou tipos validos, mas atravessou arrays sem seletor.

Para a LLM, uma unidade deve ser apresentada como **a tarefa completa desta
chamada**, e nao como um conceito interno de “fragmento”. Ela nao precisa saber
que outros resultados serao consolidados depois.

## Decisoes propostas

1. Manter a divisao deterministica por unidades definida pelo contrato.
2. Substituir os prompts compactos de fragmento pela mesma sequencia explicativa
   usada na geracao unica do candidato, com escopo reduzido aos paths da unidade.
3. No vocabulario enviado a LLM, chamar o resultado de `mapeamento da unidade`.
   O termo tecnico `fragmento_layout_signature` permanece apenas no contrato
   JSON e no codigo, pois e necessario para a consolidacao deterministica.
4. Transformar cada unidade em uma mapped task do Airflow. Isso melhora
   acompanhamento, retries e isolacao de falhas, mas nao muda a logica de
   selecao, validacao ou consolidacao.

## Novo formato de prompts por unidade

Cada chamada de geracao deve receber mensagens `system` na mesma ordem da
geracao unica. O conteudo e generico para qualquer PDF; o que muda por unidade
e somente o payload de dados.

1. **Papel e escopo**
   - explicar que a resposta deve mapear os campos do subcontrato recebido;
   - dizer que aqueles sao todos os campos desta chamada;
   - proibir inventar campos, valores finais, versao, publicacao ou lineage.

2. **Como interpretar o subcontrato e paths**
   - explicar `campos_obrigatorios`, `campos_contexto_obrigatorios`,
     `paths_permitidos` e valores fixos;
   - explicar que valores fixos nao devem ser mapeados;
   - explicar arrays e seletores com exemplos neutros, como
     `colecao.itens[codigo=observado].valor`;
   - nunca presumir empresa, trimestre, unidade, banco ou outro dominio.

3. **Contrato de resposta executavel**
   - enumerar literalmente os tipos aceitos:
     `valor_fixo`, `campo_derivado`, `campo_json`, `bloco_textual`,
     `cabecalho_de_tabela`, `celula_de_tabela`, `linhas_de_tabela` e
     `juncao_de_registros_json`;
   - explicar que `tabela`, `coluna`, `celula`, `fonte` e descricoes livres nao
     sao tipos de origem validos;
   - fornecer exemplos minimos e abstratos por origem de tabela:

```json
{
  "colecao.itens[codigo=observado].valor": {
    "tipo_origem": "celula_de_tabela",
    "arquivo_origem": "tables/table001.json",
    "indice_linha": 2,
    "indice_coluna": 4
  },
  "colecao.itens[codigo=observado]": {
    "tipo_origem": "linhas_de_tabela",
    "arquivo_origem": "tables/table002.json",
    "faixas_linhas": [{"linha_inicial": 1, "linha_final": 12}],
    "indices_colunas": [0, 3]
  }
}
```

   Os exemplos ilustram forma, nunca dados do documento.

4. **Como usar a evidencia**
   - explicar que os artefatos carregados sao a evidencia integral desta
     chamada;
   - exigir `arquivo_origem` presente no bloco recebido e indices observados;
   - reforcar que tabelas usam indices, sem regex de cabecalho.

5. **Exemplo de estrutura de resposta**
   - enviar uma projecao pequena do schema `LayoutSignatureFragment`;
   - deixar claro que os valores de `mapeamento_canonico` devem ser objetos
     executaveis completos, e nao uma descricao da tabela;
   - manter `tipo_artefato: "fragmento_layout_signature"` e
     `unidade_mapeamento` como campos tecnicos obrigatorios, sem explicar a
     consolidacao futura.

6. **Instrucao final**
   - recapitular: mapear todos e somente os paths permitidos desta chamada;
   - responder com um JSON estrito, sem Markdown nem envelope adicional.

O retry reutiliza a mesma sequencia e acrescenta, antes da instrucao final, o
erro deterministico e a resposta anterior. Assim ele nao perde as regras de
forma que faltaram nos retries atuais.

## Mapeamento do fluxo atual para mapped tasks

Hoje, `gerar_layout_candidato_llm` executa internamente um `for` com:

`selecao da unidade -> carga de artefatos -> geracao/validacao do fragmento`.

Isso aparece no Airflow como uma unica task longa. A proposta e expor essas
unidades sem alterar os contratos de MinIO nem a DAG 2:

```text
montar_plano_mapeamento
  -> selecionar_artefatos_unidade.expand(unidades)
  -> gerar_fragmento_unidade.expand(selecoes_aprovadas)
  -> consolidar_layout_por_unidades
  -> persistir candidato -> revalidar DAG 2 -> publicar
```

### 1. `montar_plano_mapeamento`

- Executa a mesma `MappingPlanService` existente.
- Persiste `plano_mapeamento.json`.
- Retorna apenas uma lista pequena de descritores de unidade: `id`, paths,
  subesquema e referencia ao contexto no MinIO.
- Se houver uma unica unidade ou o fluxo nao for escalavel, preserva o caminho
  atual de geracao unica.

### 2. `selecionar_artefatos_unidade.expand(...)`

- Uma instância Airflow por unidade.
- Recarrega o contexto minimo a partir das referencias, evitando XCom com
  manifesto ou artefatos grandes.
- Persiste os mesmos arquivos atuais em
  `unidades/<id>/selecao_artefatos/`.
- Retorna somente a referencia MinIO da selecao e da evidencia carregada.

### 3. `gerar_fragmento_unidade.expand(...)`

- Uma instância por seleção aprovada, com o mesmo `map_index` da unidade.
- Monta o payload restrito, envia a sequencia completa de prompts e aplica os
  tres retries localizados.
- Valida o `LayoutSignatureFragment` antes de concluir a task.
- Persiste entrada, resposta, erros e fragmento em
  `unidades/<id>/fragmento_layout_signature/`.
- Retorna apenas `unit_id` e a referência MinIO do fragmento validado.

### 4. `consolidar_layout_por_unidades`

- Lê os fragmentos validados do MinIO.
- Usa a consolidacao existente: colisao de path e ausencia de unidade sao erro;
  nao ha inferencia por LLM.
- Persiste o candidato consolidado e atualiza o plano para `concluido` ou
  `falhou`, incluindo a unidade e o erro em caso de falha.

## Requisitos de implementacao

- Não passar o `loaded_context` completo por XCom; passar referencias e
  recarregar objetos no worker mapeado.
- Manter idempotencia de object keys por `fallback_execution_id` e `unit_id`.
- Preservar os nomes de artefatos existentes para auditoria e compatibilidade.
- Tornar o status do plano explicito em falhas (`falhou`, `unidade_falha`,
  `erro`), hoje ele pode ficar em `em_execucao`.
- Definir retries Airflow por task mapeada independentemente dos tres retries
  internos de formato da LLM. Os internos corrigem JSON/contrato; os externos
  cobrem falha de worker, MinIO ou transporte.
- Garantir que `map_index` nunca seja usado como identidade persistida; a
  identidade e sempre `unit_id`, derivado deterministicamente do contrato.

## Ordem recomendada

1. Implementar e testar os prompts completos por unidade no fluxo atual em
   loop. Isso resolve a falha funcional observada com risco pequeno.
2. Executar ABECIP e validar que cada unidade produz fragmentos Pydantic
   validos antes da consolidacao.
3. Extrair as operacoes de plano, selecao, geracao e consolidacao do service em
   metodos publicos pequenos, sem mudar regras de negocio.
4. Adaptar a DAG para TaskFlow dynamic mapping e testar uma unidade, varias
   unidades e falha isolada.
5. Atualizar logs, plano de MinIO e documentacao operacional.

## Criterios de aceite

- A LLM nunca recebe o termo conceitual “fragmento” como unica explicacao da
  tarefa; recebe instrucoes completas de mapeamento e a forma JSON exigida.
- O candidato de cada unidade usa apenas paths permitidos e tipos de origem
  aceitos pelo resolvedor.
- Cada unidade e visivel no Airflow com estado, duracao, retries e logs
  independentes.
- O consolidado permanece 100% deterministico e a DAG 2 continua a autoridade
  final para validar e resolver o layout.
