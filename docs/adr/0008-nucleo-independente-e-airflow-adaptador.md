# ADR 0008 — Núcleo independente; Airflow como adaptador

- Status: Aceito
- Data: 2026-08-23
- Fonte de verdade: `docs/plans/plano-reorganizacao-repositorio-arquitetura.md`

## Responsáveis

Mateus de Castro

## Contexto

Regras de domínio e casos de uso estavam acoplados a `airflow/plugins`, embora
não fossem extensões do Airflow. Isso dificulta testes, reuso pelo portal e
evolução de módulos grandes.

## Drivers da decisão

- Testabilidade sem Airflow;
- reuso pelo portal e por outros adaptadores;
- redução de acoplamento;
- migração incremental compatível.

## Alternativas consideradas

### Núcleo independente e Airflow como adaptador

**Vantagens**

- Regra de domínio pode ser testada sem runtime de orquestração;
- dependências concretas ficam na borda;
- portal e DAGs podem reutilizar casos de uso.

**Desvantagens**

- Exige portas, fábricas e transição de imports.

### Manter lógica em plugins do Airflow

**Vantagens**

- Menor mudança imediata.

**Desvantagens**

- “Plugins” falsos mantêm acoplamento e dificultam testes.

### Reescrever todo o pipeline de uma vez

**Vantagens**

- Estrutura final imediata.

**Desvantagens**

- Risco alto sobre DAGs e artefatos de produção.

## Decisão

O código reutilizável migra gradualmente para `src/document_processing`.
DAGs e serviços de infraestrutura passam a ser adaptadores de borda. Durante a
migração, shims preservam os imports públicos existentes.

## Consequências

- A lógica pode ser testada sem importar Airflow.
- A migração é incremental, com menor risco operacional.
- `airflow/plugins` será removido apenas quando não restarem extensões falsas
  ou imports legados.

## Riscos

- Shims podem se tornar permanentes;
- módulos movidos sem testes de fronteira podem manter dependências invertidas.

## Implementação

- Código reutilizável vive em `src/document_processing`;
- DAGs e infraestrutura são adaptadores de borda;
- fábricas Airflow compõem dependências concretas;
- shims permanecem por uma release estável e não aceitam novos consumidores.

## Critérios para reconsideração

Revisitar se Airflow deixar de ser o orquestrador, se outro runtime precisar
executar os mesmos casos de uso ou se a transição revelar fronteiras de domínio
inadequadas.

## Referências

- `docs/plans/plano-reorganizacao-repositorio-arquitetura.md`;
- `docs/plans/plano-fechamento-arquitetura-documentacao-governanca.md`;
- ADR 0003 e ADR 0004.
