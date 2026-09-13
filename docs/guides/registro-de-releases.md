# Registro de releases de experimento

O campo `release` de cada trace no Langfuse e a **chave de agrupamento** usada por
`scripts/comparar_releases_langfuse.py` para separar duas condicoes experimentais.
Ele nao guarda o estado do codigo: e apenas um rotulo. Quem garante que o rotulo
significa alguma coisa e este registro.

Sem `ATLAS_RELEASE`, o rotulo sai de git (`dev-<branch>-<sha>[-dirty]`). Isso so
discrimina mudancas **commitadas**. Nao discrimina:

- arvore suja (o sufixo `-dirty` e booleano; 1 ou 17 arquivos alterados dao o mesmo rotulo);
- variavel de ambiente (`FALLBACK_LLM_FRAGMENT_MAX_TOKENS`, por exemplo);
- artefato externo (contrato semantico no MinIO, prompt no Langfuse).

Por isso todo experimento declara o rotulo a mao.

## Como rotular uma execucao

`ATLAS_RELEASE` e lido do ambiente do container e `resolve_release` e memoizada
com `lru_cache`. Exportar na shell depois que os servicos subiram nao tem efeito:
e preciso recriar os servicos.

```bash
ATLAS_RELEASE="exp-gramatica-seletor" docker compose up -d airflow-scheduler airflow-worker
docker compose exec -T airflow-scheduler bash -lc 'echo "$ATLAS_RELEASE"'   # confirme antes de disparar
```

Depois da execucao:

```bash
python scripts/comparar_releases_langfuse.py --base base-contrato-v2 --novo exp-gramatica-seletor
```

## Rotulos deste lote

Lote de 8 correcoes derivado da analise das execucoes de 2026-09-10 sobre Itau e
Santander 2T26. Cada rotulo isola uma hipotese; medir juntos responde "o lote
ajudou?" mas nao "qual dos oito ajudou?".

| rotulo | itens | hipotese | metrica-alvo | guarda |
| --- | --- | --- | --- | --- |
| `base-contrato-v2` | nenhum | linha de base do codigo anterior ao lote, sob o contrato `bancos/v2.0.0` | — | — |
| `exp-instrumentacao` | 6, 7, 8 | observabilidade nao muda decisao do pipeline | nenhuma: os deltas de pipeline devem dar 0,000 | todas |
| `exp-gramatica-seletor` | 1 | a LLM erra o path porque recebe `arrays_que_exigem_seletor` vazio | `avaliacao_igualdade_exata` | `resolucao_cobertura_obrigatorios` |
| `exp-mensagens-reparo` | 5 | o laco de reparo nao converge porque a mensagem nomeia o erro errado | `llm_tentativas` (menor e melhor) | `e2e_apto_para_bronze` |
| `exp-orcamento-llm` | 2, 3 | resposta vazia e orcamento mal repartido, nao falha do modelo | `llm_etapa_sucesso` | `e2e_tokens_llm` (nao pode explodir) |
| `exp-poda-evidencia` | 4 | evidencia superflua alonga o raciocinio e estoura a conclusao | `selecao_precisao` | `selecao_cobertura` |

## Lote 2: o que a execucao de 2026-09-11 (`exp-lote-completo`) ensinou

O Itau publicou layout com `regras_total: 0` e 29 campos `null`; o Santander
gastou 4 tentativas em gramatica de path. Tres causas, um rotulo, porque as tres
mexem no mesmo criterio de validacao e nao ha como executar uma sem as outras.

| rotulo | itens | hipotese | metrica-alvo | guarda |
| --- | --- | --- | --- | --- |
| `exp-linha-e-valores` | 9, 10, 11 | o candidato passa na validacao mas nao resolve: falta `valor_aceito`, `valores` sem seletor e `&` no filtro | `revalidacao_regras_executadas` (deixa de ser 0) e `avaliacao_igualdade_exata` | `llm_tentativas` (a validacao ficou mais estrita; nao pode explodir) |

- **9** — `celula_de_tabela` exige `seletor_linha.valor_aceito`. O resolvedor so
  aceita a linha pelo rotulo (`_find_row_index`); o indice e dica. Zero de 49
  instrucoes da LLM traziam o rotulo, e o proprio exemplo do prompt o omitia.
- **10** — `valores` exige seletor proprio, `valores[periodo=...]`. Sem ele o
  construtor de schema falha em "Caminho nao compativel com schema_saida". O
  gabarito usava `.valores.valor` e foi corrigido; os 4 itens
  `candidato::bancos::*` do dataset `atlas-fallback-layout-candidato` foram
  republicados em 2026-09-12 (metadata `nota_gramatica`). Sob esse gabarito, a
  resolucao local dos dois bancos da 23/23 e 19/19 instrucoes resolvidas, zero nulos.
- **11** — `&` dentro de um filtro e recusado pela gramatica e nomeado pela
  diagnose do reparo.

Linha de base para este rotulo: os traces `exp-lote-completo` de 2026-09-11
(Itau ao vivo `2646b269…`, Santander por backfill `befb9300…`).

## Linha de base

A execucao de 2026-09-10T23:24Z rodou o codigo anterior a este lote sob o contrato
`bancos/v2.0.0`. Ela ficou sob o rotulo automatico
`dev-feat-prep_realease-42fd719-dirty`, **misturada com outras duas execucoes** do
mesmo dia sob o contrato v1.0.0 — o rotulo nao as separa.

Enquanto essa poluicao existir, a linha de base confiavel nao e a media do rotulo:
sao os vinculos do dataset run `run-contrato-v2-2t26`, que apontam para a
observacao exata de cada etapa daquela execucao, com `avaliacao_*` ja pontuado
contra o gabarito.

Numeros de partida, para nao precisar recalcular:

| unidade | precisao | revocacao | igualdade exata | desfecho |
| --- | --- | --- | --- | --- |
| itau / percentuais | 1,00 | 0,50 | 0 | aceito |
| itau / monetarios | 0,00 | 0,00 | 0 | conteudo vazio, 1 tentativa |
| santander / percentuais | 0,00 | 0,00 | 0 | 4 tentativas, gramatica de path |
| santander / monetarios | — | — | — | nao executou |

Selecao de artefatos na mesma execucao: precisao 0,17 (percentuais) e 0,25
(monetarios); revocacao 0,50 e 1,00.

**Antes de medir o lote, rode a linha de base limpa** com
`ATLAS_RELEASE=base-contrato-v2` a partir do codigo anterior ao lote. Sem isso a
comparacao herda a mistura descrita acima.
