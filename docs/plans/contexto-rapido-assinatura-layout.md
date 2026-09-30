# Contexto rápido — Assinatura de Layout (DAG 3)

> **Cole este arquivo inteiro no início de uma nova conversa.** Ele substitui
> precisar reexplicar o projeto, reler `specs/`, `docs/architecture/` ou os
> ADRs inteiros. Se alguma decisão específica não estiver aqui, peça para ler
> o arquivo apontado na seção correspondente — não é necessário variar a
> pasta `docs/` inteira por padrão.

## O projeto em 3 frases

O Atlas transforma PDFs trimestrais (construtoras, bancos) em dados
estruturados e auditáveis. Ele separa **contrato semântico** (o que precisa
sair, `contratos/<dominio>/vX.Y.Z/`) de **layout signature** (onde achar cada
campo na extração Docling, `layouts/<dominio>/<entidade>/`). A resolução é
sempre determinística (DAG 2); a LLM só entra em fallback (DAG 3) para propor
um **layout signature candidato**, que só vira ativo depois de revalidação
determinística e nunca escreve valor final de negócio.

## A tarefa deste momento

Estamos implementando, uma fase por vez, o **Plano da Assinatura de Layout**:
decompor a chamada única de LLM que hoje monta o `layout_signature_candidato`
em fases mensuráveis, tirando da LLM tudo que pode ser derivado
deterministicamente do contrato semântico + identidade do documento.

**O plano completo (fases 0–7, status por item, roteiro em incrementos,
tabela de releases) está neste artifact, e é a fonte de verdade da tarefa:**

**https://claude.ai/artifact/1grpuXyA6Abu8AU6zFZoNN**

No início de uma sessão de trabalho nesta tarefa:

1. Leia o artifact (ferramenta Artifact, `action: read`) para ver o status
   atual de cada item e qual é o próximo "planejado"/"em andamento".
2. Confira as últimas entradas de `docs/guides/registro-de-releases.md` para
   saber qual é a release-base vigente e se algo foi revertido recentemente.
3. Implemente a fase, com testes, seguindo o desenvolvimento orientado a
   métricas abaixo.
4. Registre o lote em `docs/guides/registro-de-releases.md` **antes** de
   pedir para rodar (hipótese, métrica-alvo, guarda) e o resultado depois.
5. Atualize o artifact (republique com a mesma URL) marcando os itens como
   `feito`/`em andamento` e acrescentando a release na tabela de releases.

Regra de design que atravessa todas as fases: **nenhum código conhece nome de
campo, período ou rótulo de um domínio específico** (nem "construtoras", nem
"bancos"). O que não vier do contrato semântico ou do artefato de extração
fica com a LLM. Ver a coluna "Quem" de cada item do plano (`D` = derivável
sempre, `D*` = derivável se o contrato declarar o campo, `L` = decisão da
LLM).

## Desenvolvimento orientado a métricas (regra fixa do projeto)

Detalhe completo em
[`docs/guides/desenvolvimento-orientado-a-metricas.md`](../guides/desenvolvimento-orientado-a-metricas.md).
Resumo do ciclo:

```
1. declare a métrica-alvo antes de escrever código (uma frase: que número sobe/desce)
2. registre a linha de base (release atual)
3. implemente a mudança + testes (pytest)
4. rode com um release próprio: ATLAS_RELEASE=exp-... (nunca sem rótulo — vira dev-<branch>-<sha>)
5. compare: scripts/comparar_releases_langfuse.py --base <a> --novo <b>
6. decida: manter / ajustar / reverter
```

Métricas de guarda que **nunca podem cair**, mesmo quando não são o alvo da
mudança: `e2e_apto_para_bronze`, `resolucao_cobertura_obrigatorios`,
`revalidacao_gate_efetivo`, `validacao_cobertura_de_regras`. Para a assinatura
de layout especificamente, também: `assinatura_f0_selecao_revocacao`,
`assinatura_f1_cobertura_obrigatorios`, `assinatura_f3_arquivo_origem_correto`.

Duas releases foram reprovadas e revertidas por inteiro em 2026-09-18
(`exp-colecao-fragmento`, `exp-colecao-chave-coluna`) por ajustarem só prompt:
a cada rodada um documento trocava linha/artefato/filtro por escolha livre da
LLM. Lição fixada: a correção que dura é **código enumerando o que é
determinístico**, prompt sozinho não sustenta. É exatamente isso que o plano
da assinatura de layout faz, fase por fase.

## Registro de releases (obrigatório a cada mudança medida)

Arquivo: [`docs/guides/registro-de-releases.md`](../guides/registro-de-releases.md).
Cada lote de mudança ganha uma entrada com: rótulo da release, itens/commits,
hipótese, métrica-alvo, métricas de guarda, e depois o resultado da
comparação (aprovada / aprovada com ressalva / reprovada) com a leitura do
que aconteceu por documento. Esse arquivo é o histórico real do experimento —
não resuma de memória, leia as últimas entradas antes de propor a próxima
release.

## Onde mexer no código (mapa mínimo)

- `src/document_processing/domain/fallback/` — regras puras do fallback:
  `target_enumeration.py` (Fase 1 — lista fechada de chaves),
  `candidate_validation.py` (valida o candidato da LLM),
  `mapping_plan.py` (divide o contrato em unidades de mapeamento).
- `src/document_processing/domain/contracts/` — leitura do contrato semântico
  (`capabilities.py` = `chaves_de_item`/`derivacoes`, ADR 0011;
  `mapping_requirements.py` = `campos_obrigatorios`/`papeis`).
- `src/document_processing/application/use_cases/fallback/` — monta payloads
  e mensagens para a LLM (`context_builder.py`, `payload_assembly.py`,
  `candidate_json_generation.py`, `prompt_sets.py` + `candidate_prompts.py`).
- `src/document_processing/domain/observability/signature_evaluation.py` —
  métricas `assinatura_f<fase>_*` do harness.
- `scripts/avaliar_assinatura_layout.py` — roda o harness sobre uma release do
  Langfuse e grava os scores.
- `eval/gabaritos/<document_id>.json` — gabarito por documento (o que
  deveria ter sido ancorado), usado pelas fases 0 e 3.
- Arquitetura detalhada do fallback (se precisar de mais profundidade):
  [`docs/architecture/fallback-llm-e-geracao-layout-dag3.md`](../architecture/fallback-llm-e-geracao-layout-dag3.md).

## Comandos essenciais

```bash
# testes rápidos (não precisa de Airflow/Docling/portal)
PYTHONPATH=src python3 -m pytest tests/unit -q

# lint (o que o CI roda)
ruff check src tests/unit scripts/validate_repository_structure.py

# harness de métricas da assinatura de layout sobre uma release
python scripts/avaliar_assinatura_layout.py --release <release>

# comparar duas releases (pareado por execução)
python scripts/comparar_releases_langfuse.py --base <a> --novo <b>

# ver o que mudou entre o espelho de prompt no código e o Langfuse
python scripts/sincronizar_prompts_langfuse.py --verificar
```

## O que evitar

- Não leia `specs/`, `docs/architecture/` inteira ou todas as ADRs por
  padrão — este arquivo já resume o necessário para a tarefa. Vá direto ao
  arquivo apontado quando precisar de um detalhe específico.
- Não implemente uma fase sem antes checar o artifact do plano: pode já ter
  sido feita, estar em andamento, ou ter uma dependência de uma fase
  anterior ainda não fechada.
- Não rode outras DAGs sob o mesmo rótulo de release do experimento (polui a
  comparação — já aconteceu e está documentado no registro de releases).
- Não conclua uma fase sem: testes passando, registro em
  `registro-de-releases.md`, e o artifact do plano atualizado.
