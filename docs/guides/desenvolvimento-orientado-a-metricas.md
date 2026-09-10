# Desenvolvimento Orientado a Métricas

- Status: vigente
- Responsável: Mateus de Castro
- Última revisão: 2026-09-05

## A regra

Toda mudança que afete extração, resolução, validação, fallback ou publicação
só permanece no projeto depois de ser medida contra a versão anterior sobre os
**mesmos documentos**. Se a métrica-alvo não subiu, ou se uma métrica de guarda
caiu, a mudança volta.

Isso vale para desenvolvimento, não só para produção. O objetivo não é
burocracia: é impedir que ajustes de prompt e de heurística sejam avaliados por
impressão a partir de um ou dois PDFs.

## Quando a regra se aplica

Aplica-se quando a mudança toca:

- prompts, payloads ou schemas de resposta da LLM;
- regras determinísticas ou tipos de origem do resolvedor;
- validação de candidato, gates de publicação ou classificação de escopo;
- inventário, seleção de artefatos ou projeção de contexto;
- contratos semânticos e layout signatures de referência.

Não se aplica a refatoração sem mudança de comportamento, documentação,
tipagem, renomeação interna ou infraestrutura — nesses casos, o esperado é
justamente que **nenhuma** métrica se mova, o que o comparador também confirma.

## O ciclo

```text
1. declare a métrica-alvo antes de escrever código
2. registre a linha de base           (release atual)
3. implemente a mudança
4. rode os testes                     (pytest)
5. execute o fluxo com novo release   (ATLAS_RELEASE=exp-...)
6. compare as duas releases           (scripts/comparar_releases_langfuse.py)
7. decida: manter, ajustar ou reverter
```

### 1. Declare a métrica-alvo antes

Antes de escrever código, responda em uma frase: **qual número deveria mudar, e
para que lado?** Se não houver resposta, não há como avaliar a mudança depois, e
o passo seguinte é criar a métrica, não o código.

Exemplos de alvo bem declarado:

- "subir `llm_acerto_1a_tentativa` da etapa `layout_signature_candidato` de 0,22";
- "subir `validacao_cobertura_de_regras` acima de zero para construtoras";
- "reduzir `llm_tokens_total` da seleção de artefatos sem derrubar `llm_etapa_sucesso`".

### 2. Registre a linha de base

```bash
python scripts/comparar_releases_langfuse.py --listar-releases
```

Se a versão atual ainda não tem execuções observadas, rode o fluxo uma vez com o
release atual antes de mudar o código. Sem linha de base não há comparação.

### 3 e 4. Implemente e teste

```bash
PYTHONPATH=src python -m pytest tests -q
```

Métrica nova exige teste de cálculo em
`tests/unit/domain/test_observability_metrics.py`. Uma métrica sem teste é uma
métrica em que não se pode confiar para reprovar o trabalho de alguém.

### 5. Execute com um release próprio

```bash
export ATLAS_RELEASE="exp-prompt-selecao-v2"
# dispare a DAG normalmente, ou reprojete execuções existentes:
python scripts/backfill_langfuse_atlas.py --release "$ATLAS_RELEASE"
```

Sem `ATLAS_RELEASE`, o rótulo sai de git: `dev-<branch>-<sha>[-dirty]`. Isso já
separa versões, mas nomear o experimento facilita a leitura depois.

### 6. Compare

```bash
python scripts/comparar_releases_langfuse.py \
  --base dev-main-42c4d1e \
  --novo exp-prompt-selecao-v2
```

A comparação é **pareada por execução**: só entram execuções presentes nas duas
releases, casadas por `document_id` + etapa + `execution_id`. Comparar médias de
conjuntos diferentes de PDFs produz variação que parece resultado e é só
composição de amostra.

O código de saída serve para automação:

| Saída | Significado |
| --- | --- |
| `0` | nenhuma métrica de guarda regrediu |
| `1` | regressão fora das métricas de guarda |
| `2` | **reprovado**: métrica de guarda regrediu |

### 7. Decida

| Resultado | Decisão |
| --- | --- |
| alvo subiu, nenhuma guarda caiu | mantém |
| alvo subiu, guarda caiu | reverte ou trata a guarda antes de seguir |
| alvo não se moveu | a hipótese estava errada; não mantenha código sem efeito |
| tudo estável em refatoração | comportamento preservado, como esperado |

## Métricas de guarda

Nunca podem regredir, mesmo quando não são o alvo:

- `e2e_apto_para_bronze`
- `resolucao_cobertura_obrigatorios`
- `revalidacao_gate_efetivo`
- `validacao_cobertura_de_regras`

São as que protegem o contrato com o consumidor dos dados: se elas caem, o
pipeline passou a publicar com menos evidência do que publicava antes, que é
exatamente o tipo de regressão difícil de perceber sem medir.

## Direção de cada métrica

O comparador conhece o sentido de cada métrica; ele não trata toda variação como
melhora. Ao criar uma métrica nova, classifique-a em
`scripts/comparar_releases_langfuse.py`:

- `MAIOR_MELHOR`: coberturas, taxas de sucesso, autonomia, gates;
- `MENOR_MELHOR`: tentativas, tokens, duração, campos não resolvidos,
  acionamento de fallback;
- não classificada: aparece como "métrica neutra" e não reprova nada.

Uma métrica sem direção declarada não participa da decisão. Isso é proposital:
métrica de diagnóstico e métrica de decisão têm pesos diferentes.

## Mudança de prompt

Prompt agora é versionado no Langfuse, um bloco por trecho de instrução
(ADR 0010). Isso muda o ciclo em dois pontos.

**O passo 5 pode não precisar de release nova.** Editar um bloco pela interface
já cria uma versão. A execução seguinte registra a combinação exata de versões em
`prompt_conjunto_versao`, então a comparação pode ser feita por versão de prompt
em vez de por release do projeto:

```bash
python scripts/sincronizar_prompts_langfuse.py --verificar   # o que mudou
```

No dashboard *Atlas - Fallback LLM*, o painel "Acerto por versão de prompt" corta
`llm_acerto_1a_tentativa` por `observationPromptVersion`.

**Mude um bloco por vez.** É a razão de existir a separação em 18 blocos. Alterar
`candidato-estrutura` e `candidato-final` na mesma leva devolve um número que não
diz qual dos dois funcionou — e a tentação seguinte é manter os dois.

Depois de decidir manter, atualize o espelho no repositório:

```bash
python scripts/sincronizar_prompts_langfuse.py --puxar
```

Enquanto o espelho não é atualizado, o repositório e o Langfuse divergem. Isso é
esperado, mas divergência antiga é dívida: se o Langfuse cair, a execução volta
para o texto do repositório, que é o texto que você já decidiu abandonar.

## Avaliação off-line por etapa

Nem toda mudança precisa do fluxo inteiro. Para mexer em uma etapa, use o
dataset correspondente e meça a etapa isolada:

| Mudança em | Dataset |
| --- | --- |
| prompt ou payload de seleção de evidências | `atlas-fallback-selecao-artefatos` |
| geração de mapeamento canônico | `atlas-fallback-layout-candidato` |
| classificação de escopo no handoff | `atlas-transicao-resolucao-fallback` |
| resolução, contratos, layouts | `atlas-e2e-regressao` |

Medir a etapa isolada evita atribuir a uma mudança de prompt uma variação que
veio da etapa seguinte.

Um dataset só produz resultado depois de ser executado — a aba Experiments vazia
significa "nenhuma execução", não "nada aqui":

```bash
# linha de base sem custo: liga os traces já projetados aos itens
python scripts/executar_datasets_langfuse_atlas.py --modo replay --release <release>

# avaliação de verdade: reexecuta a etapa e pontua contra o esperado
python scripts/executar_datasets_langfuse_atlas.py --modo executar \
    --dataset atlas-fallback-selecao-artefatos --limit 20
```

O modo `executar` pontua com `avaliacao_precisao`, `avaliacao_revocacao`,
`avaliacao_f1` e `avaliacao_igualdade_exata`. Precisão e revocação ficam
separadas de propósito: escolher 8 artefatos certos entre 10 e escolher os mesmos
8 entre 20 são resultados diferentes, e uma média só esconderia isso.

## Armadilhas já encontradas

Casos reais deste projeto, registrados para não se repetirem:

**Taxa com denominador zero.** `resolucao_cobertura_obrigatorios` marcava 0%
quando o contrato não declarava nenhum campo obrigatório — tudo tinha sido
resolvido. Hoje a métrica só é emitida quando há obrigatórios, e
`resolucao_campos_obrigatorios` mostra a ausência. **Distinga "não aplicável" de
"zero".**

**Aprovação sem evidência.** `status_compatibilidade` vira `compativel` sempre
que nenhuma regra reprova, inclusive quando não há regra alguma. Uma métrica de
resultado precisa de uma métrica de cobertura ao lado. **Meça também se a
verificação aconteceu.**

**Nome de métrica derivado de nome de arquivo.** A primeira versão do backfill
gerou nomes como `fallback_entrada_llm_selecao_artefatos.json_..._tentativas`,
inflando a contagem de tentativas porque cada tipo de artefato virou uma etapa.
**Nome de métrica é contrato; derive de conceito, não de caminho de arquivo.**

**Comparar conjuntos diferentes.** Comparar 80 traces contra 79 produziu uma
"regressão" de 0,006 que era só amostra desigual. **Pareie antes de comparar.**

**Widget que agrega o que o título diz separar.** O painel "Acerto na primeira
tentativa por etapa" ficou sem dimensão e mostrava uma média única de 0,575. Com
o corte por etapa, a seleção de artefatos acerta 0,89 e a geração de candidato
acerta 0,22 — dois problemas distintos escondidos atrás de um número médio.
**Confira se o gráfico separa o que o título promete.**

## Observabilidade não pode quebrar o pipeline

As tasks de observabilidade rodam com `TriggerRule.ALL_DONE` e capturam toda
exceção. Execuções que falharam são as que mais precisam ser medidas, e uma
falha de rede no Langfuse nunca pode reprovar uma DAG que resolveu o documento.

Ao acrescentar instrumentação, mantenha essa propriedade: nenhuma métrica vale
uma execução perdida.

## Referências

- [`../architecture/observabilidade-e-metricas-langfuse.md`](../architecture/observabilidade-e-metricas-langfuse.md)
- [`../../specs/platform/SPEC.md`](../../specs/platform/SPEC.md)
- [`../adr/0009-observabilidade-por-projecao-de-artefatos.md`](../adr/0009-observabilidade-por-projecao-de-artefatos.md)
