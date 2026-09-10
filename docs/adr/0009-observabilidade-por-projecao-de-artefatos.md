# ADR 0009 — Observabilidade por projeção de artefatos

- Status: Aceito
- Data: 2026-09-05
- Fonte de verdade: `docs/architecture/observabilidade-e-metricas-langfuse.md`

## Responsáveis

Mateus de Castro

## Contexto

Uma execução de negócio do Atlas atravessa pelo menos dois `DagRun`s: a DAG 2
resolve, a DAG 3 gera um layout candidato e dispara a DAG 2 de novo em modo de
revalidação. O documento `realimentacao-entre-resolucao-e-fallback.md` já
registrava a "observabilidade distribuída" como risco aceito.

As únicas métricas existentes eram as de validação de layout gravadas em
`validacao_layout_signature.json` e `resultado_revalidacao_candidato.json`. Elas
respondem se uma execução isolada passou, mas não permitem série temporal,
comparação entre versões do projeto, nem medição por etapa ou por handoff.

Havia três formas possíveis de instrumentar:

1. **Instrumentação inline**: cada caso de uso recebe um tracer e emite eventos
   ao longo da execução.
2. **Decoradores nas tasks do Airflow**: um wrapper genérico observa entrada e
   saída de cada task.
3. **Projeção de artefatos**: uma task ao fim de cada DAG lê o que a execução
   gravou no MinIO e projeta para o Langfuse.

## Decisão

Adotar a **projeção de artefatos**.

Cada DAG termina com uma task que lê os artefatos daquela execução e emite
trace, spans, generations e métricas. O cálculo das métricas fica em
`document_processing/domain/observability`, como funções puras que não conhecem
Langfuse, MinIO nem Airflow.

A correlação entre os `DagRun`s é feita por `sessionId = document_id`, e o
pareamento entre versões do projeto por `metadata.execution_id` mais o rótulo
`release`.

## Justificativa

**Contra a instrumentação inline.** Ela alargaria as assinaturas dos casos de
uso e espalharia dependência de observabilidade pelo núcleo, contrariando a
ADR 0008 (núcleo independente). Também tornaria difícil garantir que uma falha
de rede no Langfuse não afetasse a resolução.

**Contra os decoradores de task.** Eles observam a mecânica do Airflow, não o
domínio. Produziriam latência e status por task, mas não cobertura de campos,
escopo de correção ou efetividade de gate — que são justamente as perguntas do
projeto.

**A favor da projeção.** Os artefatos já são a fonte de verdade auditável do
projeto, por decisão anterior (ADR 0001, ADR 0002). Medir a partir deles tem
três consequências que as outras opções não têm:

1. o caminho crítico não muda e nenhuma assinatura é alargada;
2. a mesma projeção serve para execuções novas e para backfill histórico, então
   a série temporal começa com base real em vez de vazia — foi assim que 80
   execuções históricas viraram linha de base;
3. observabilidade indisponível não quebra execução: as tasks usam
   `TriggerRule.ALL_DONE` e capturam toda exceção.

O custo aceito é latência: a métrica aparece no fim da DAG, não durante. Para as
perguntas que o projeto faz — comparar versões, medir cobertura, avaliar gates —
isso é irrelevante.

## Consequências

### Positivas

- métricas por etapa, por transição e de ponta a ponta sem tocar no núcleo;
- backfill histórico possível a qualquer momento, sobre qualquer recorte;
- o mesmo código projeta execução nova e execução antiga, então não há
  divergência entre o que se mede hoje e o que se mediu antes;
- comparação entre releases fica pareada por execução, não por média de
  conjuntos diferentes;
- nenhuma dependência nova na imagem do Airflow: o cliente de ingestão usa só
  `urllib` e `base64`.

### Negativas

- a métrica só existe depois que os artefatos foram gravados; uma DAG que morre
  antes de persistir não é observada;
- a projeção precisa acompanhar mudanças no formato dos artefatos, e uma
  mudança de nome de arquivo pode silenciar uma métrica;
- métricas de latência por etapa são reconstruídas a partir de `persistido_em`,
  o que é menos preciso do que cronometrar em execução.

### Mitigação

O nome das métricas é derivado de conceito, nunca de caminho de arquivo — regra
adotada depois de a primeira versão do backfill gerar nomes como
`fallback_entrada_llm_selecao_artefatos.json_..._tentativas`. As funções de
cálculo têm testes em `tests/unit/domain/test_observability_metrics.py`.

## Alternativa futura

Se latência por task e observação em tempo real virarem requisito, a projeção
pode conviver com OpenTelemetry nas DAGs: o OTel cobriria a mecânica de
execução e a projeção continuaria responsável pelas métricas de domínio. Não é
necessário agora.

## Referências

- `docs/architecture/observabilidade-e-metricas-langfuse.md`
- `docs/guides/desenvolvimento-orientado-a-metricas.md`
- `docs/architecture/realimentacao-entre-resolucao-e-fallback.md`
- ADR 0002 — publicação após revalidação determinística
- ADR 0008 — núcleo independente; Airflow como adaptador
