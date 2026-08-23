# Plano de Escalabilidade da DAG 3: Layout Signature por Blocos

## Objetivo

Permitir a criacao de `layout_signature` para PDFs grandes e heterogeneos sem
enviar todo o contexto para uma unica chamada LLM. A DAG 3 deve decompor a
criacao em blocos semanticos, validar cada bloco de forma deterministica e
consolidar somente fragmentos aprovados.

Status: implementado na primeira versao. O fluxo atual de uma selecao de
artefatos seguida de uma unica geracao de candidato permanece valido para
documentos pequenos, contratos com uma unica raiz semantica e correcoes
parciais. A geracao por blocos e acionada para criacao inicial ou regeneracao
total quando o contrato possui mais de uma raiz semantica entre os campos
obrigatorios.

## Problema que resolve

Uma unica chamada para criar o layout completo pode receber:

- muitos artefatos de um PDF longo;
- toda a estrutura do contrato;
- exemplos de todos os tipos de origem;
- varios grupos de dados sem relacao direta.

Isso aumenta custo, contexto e chance de a LLM esgotar tokens de raciocinio
antes de emitir o JSON final. A solucao nao e dividir indiscriminadamente por
campo: isso perde a relacao entre colunas, linhas e periodos de uma mesma
tabela. A unidade correta e um bloco semantico coeso.

## Fluxo alvo

```text
contrato + inventario
        |
        v
plano de mapeamento por blocos
        |
        v
selecao de artefatos por bloco
        |
        v
geracao e validacao de fragmentos de layout
        |
        v
consolidacao deterministica do candidato
        |
        v
revalidacao integral pela DAG 2
```

## Conceitos

### Bloco semantico

Conjunto de campos obrigatorios que deve ser resolvido com o mesmo grupo de
artefatos. O bloco normalmente corresponde a uma colecao do schema de saida,
uma tabela, um grafico ou uma secao documental.

Exemplos:

- construtoras: `lancamentos` e `vendas`;
- ABECIP: `financiamentos_mensais`, `poupanca`, `instituicoes` e
  `recursos_livres`;
- outro dominio: os blocos sao derivados do contrato, nao de regras no codigo.

### Subesquema

Projecao deterministica do schema de saida limitada aos campos de um bloco.
Nao altera o contrato completo nem a saida final. Apenas limita o que a LLM
precisa entender na chamada daquele bloco.

Exemplo para `poupanca_sbpe.saldos_mensais`:

```json
{
  "campo_saida": "poupanca_sbpe.saldos_mensais",
  "tipo": "lista",
  "exige_seletor_por_observacao": true,
  "campos_do_item": {
    "periodo": {
      "rotulo_publicado": "string",
      "data_inicio": "string",
      "data_fim": "string"
    },
    "saldo_milhoes": "numero"
  }
}
```

## Contratos de dados propostos

### `plano_mapeamento.json`

Gerado pela DAG de modo deterministico a partir de
`requisitos_mapeamento.campos_obrigatorios`. A LLM nao escolhe agrupamentos:
a primeira versao usa a raiz do path como unidade (por exemplo,
`poupanca_sbpe.saldos_mensais` pertence a `poupanca_sbpe`). Isso evita que um
modelo misture ramos independentes e deixa o plano reproduzivel.

```json
{
  "tipo_artefato": "plano_mapeamento_layout",
  "versao": "1.0",
  "unidades": [
    {
      "id": "poupanca_sbpe",
      "campos_saida": [
        "poupanca_sbpe.saldos_mensais",
        "poupanca_sbpe.captacoes_liquidas_mensais"
      ],
      "subesquema": {},
      "status": "pendente"
    }
  ]
}
```

Regra inicial de agrupamento: usar o menor ancestral comum dos paths
obrigatorios, sem misturar ramos diferentes. O contrato podera futuramente
aceitar um agrupamento explicito somente se essa heuristica nao for suficiente.

### Selecao por bloco

O formato atual de `selecao_artefatos_layout` pode ser reutilizado, mas recebe
apenas os campos da unidade. A cobertura continua obrigatoria e baseada em
ancoras verificadas deterministicamente no conteudo real dos artefatos.

### Fragmento de layout

```json
{
  "tipo_artefato": "fragmento_layout_signature",
  "unidade_mapeamento": "poupanca_sbpe",
  "mapeamento_canonico": {},
  "fontes_relevantes": {},
  "metadados_estruturais_evidencia": {}
}
```

O fragmento nao contem `document_id`, `execution_id_origem`, contrato,
versionamento, valores fixos, regras operacionais ou publicacao. Esses dados
sao preenchidos deterministicamente no consolidado.

## Implementacao proposta

### Fase 1 — Projecao deterministica e plano — implementada

1. Criar um servico dedicado, por exemplo
   `fallback/mapping_plan.py`.
2. Ler `requisitos_mapeamento.campos_obrigatorios`.
3. Derivar subesquemas a partir de `schema_saida` e dos paths permitidos.
4. Criar unidades pela raiz semantica do path; uma unidade nao pode conter
   campos de ramos semanticamente independentes.
5. Persistir `plano_mapeamento.json` antes de qualquer chamada LLM.

Critério de aceite: cada campo obrigatorio aparece uma unica vez no plano e
cada unidade possui subesquema nao vazio.

### Fase 2 — Selecao e evidencia por unidade — implementada

1. Reutilizar `select_relevant_artifacts(...)` para cada unidade.
2. Passar somente inventario, campos da unidade e seu subesquema.
3. Manter validacao de paths, cobertura e ancoras.
4. Para JSONL, manter amostra curta e buscar deterministicamente no arquivo
   completo os registros que contenham as ancoras declaradas.
5. Persistir entradas, respostas, erros e evidencias sob o ID da unidade.

Critério de aceite: uma falha em uma unidade nao invalida nem repete selecoes
ja aprovadas de outras unidades.

### Fase 3 — Geracao de fragmento e retry localizado — implementada

1. Criar `generate_layout_fragment(...)` no orquestrador.
2. O payload contem somente subesquema, alvos mapeaveis e artefatos aprovados.
   O contrato Pydantic da resposta restringe a forma do fragmento; nao e
   reenviado um exemplo de layout completo.
3. Validar Pydantic, paths permitidos do bloco, filtros de arrays e arquivos
   existentes imediatamente apos a resposta.
4. Em caso de falha, reenviar somente o bloco reprovado, com erro e evidencia.
5. Se `finish_reason=length` e `content` estiver vazio, registrar diagnostico
   proprio e reduzir contexto; nao tratar como correcao de candidato inexistente.

Critério de aceite: retry de um bloco nao reenvia os artefatos nem o
subesquema dos demais blocos.

### Fase 4 — Consolidacao deterministica — implementada

1. Criar `merge_layout_fragments(...)`.
2. Montar o cabecalho e valores operacionais pelo esqueleto deterministico ja
   existente.
3. Unir `mapeamento_canonico`, `fontes_relevantes` e evidencias aprovadas.
4. Reprovar conflitos: mesmo path mapeado por unidades diferentes. A cobertura
   da selecao e validada antes da geracao de cada fragmento.
5. Garantir que todos os campos obrigatorios estejam presentes antes de criar
   `layout_signature_candidato.json`.

Critério de aceite: o consolidado contem apenas mappings provenientes de
fragmentos aprovados e pode seguir para a DAG 2 sem tratamento especial.

### Fase 5 — Orquestracao Airflow — primeira versao implementada

A primeira versao usa iteracao controlada no servico: cada unidade termina e
persiste sua evidencia antes da proxima. Isso reduz risco de saturar o provedor
LLM e torna os artefatos auditaveis. Dynamic task mapping, concorrencia
configuravel e retomada de unidades pendentes continuam evolucoes futuras.

## Persistencia MinIO

```text
fallback/<dominio>/<entidade>/document_id=<id>/execution_id=<dag3-id>/
  plano_mapeamento.json
  unidades/<id-unidade>/
    entrada_llm_selecao_artefatos.json
    selecao_artefatos_layout.json
    entrada_llm_selecao_artefatos[_tentativa_N].json
    resposta_llm_selecao_artefatos[_tentativa_N].json
    erro_llm_selecao_artefatos[_tentativa_N].json
    selecao_artefatos_layout.json
    entrada_llm_fragmento_layout_signature[_tentativa_N].json
    resposta_llm_fragmento_layout_signature[_tentativa_N].json
    erro_llm_fragmento_layout_signature[_tentativa_N].json
    fragmento_layout_signature.json
  layout_signature_candidato_consolidado.json
  validacao_consolidacao.json
```

## Regras de custo e qualidade

- Nunca enviar o PDF completo para a LLM.
- Nunca reenviar um bloco ja validado.
- Limitar artefatos e evidencias por unidade.
- Usar a DAG 2 como validacao final obrigatoria do layout consolidado.
- Persistir resposta bruta, erro e metadados da API por tentativa.
- Para erro de transporte, reutilizar o orcamento de retry da propria unidade;
  evitar retries HTTP multiplicados por retries LLM.

## Testes essenciais

1. Contrato com seis campos obrigatorios gera plano sem duplicidades.
2. Bloco com ancora no registro 19 de JSONL e aprovado sem enviar o arquivo
   completo a LLM.
3. Fragmento invalido causa retry apenas daquela unidade.
4. Dois fragmentos que mapeiam o mesmo path causam erro de consolidacao.
5. Consolidado incompleto nao e encaminhado para a DAG 2.
6. `finish_reason=length` com `content` vazio gera diagnostico explicito.
7. Layout consolidado aprovado continua sendo resolvido pela DAG 2 sem regra
   especifica de dominio.

## Limites atuais e proximos incrementos

- Uma raiz semantica muito grande ainda e uma unica unidade. O proximo
  incremento deve permitir subdivisao declarativa no contrato ou por limiar de
  tamanho de evidencia, mantendo a mesma regra deterministica.
- A execucao sequencial prioriza custo e rastreabilidade. Paralelismo so deve
  ser introduzido com limite explicito do provedor e idempotencia por unidade.
- A DAG 2 continua sendo a validacao integral obrigatoria: um consolidado por
  blocos nao e publicado sem a revalidacao final.

## Decisao de adocao

Adotar o fluxo por blocos quando o contrato possuir muitos grupos
independentes, quando os artefatos selecionados excederem o orcamento de
contexto definido ou quando a chamada unica encerrar por limite de tokens.
Para contratos pequenos, manter o caminho atual de uma unica geracao de
candidato para evitar complexidade operacional desnecessaria.
