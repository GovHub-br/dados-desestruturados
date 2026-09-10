# Documentação da Plataforma de Inteligência Documental

- Status: vigente
- Responsável: Mateus de Castro
- Última revisão: 2026-08-23

Esta pasta explica como a plataforma recebe PDFs, extrai artefatos, resolve
dados a partir de contratos semânticos, usa fallback LLM quando necessário e
publica resultados rastreáveis. Ela foi organizada para que uma pessoa nova no
projeto consiga começar pelo objetivo do produto, entender as decisões e chegar
à operação sem depender do histórico oral da equipe.

## Por onde começar

1. Leia [`../specs/platform/CONTEXT.md`](../specs/platform/CONTEXT.md) para
   entender o vocabulário e o problema que a plataforma resolve.
2. Leia [`../specs/platform/SPEC.md`](../specs/platform/SPEC.md) para conhecer
   o comportamento esperado e os limites do produto.
3. Leia [Arquitetura](architecture/) para compreender o fluxo atual.
4. Leia [ADRs](adr/) para saber por que as decisões importantes foram tomadas.
5. Use [Operações](operations/) ao executar, implantar ou investigar incidentes.

## Mapa da documentação

### [Arquitetura](architecture/)

Descrição atual dos componentes e fluxos técnicos. Comece por
[`arquitetura-orquestracao-airflow.md`](architecture/arquitetura-orquestracao-airflow.md) para ver as
DAGs; depois consulte resolução determinística, fallback LLM, portal, Docling e
governança no OpenMetadata conforme a área em que for trabalhar. Para saber o
que o fluxo mede e como comparar versões, veja
[`observabilidade-e-metricas-langfuse.md`](architecture/observabilidade-e-metricas-langfuse.md).

### [ADRs](adr/)

Registros de decisões arquiteturais duradouras. Cada ADR apresenta contexto,
drivers, alternativas consideradas, decisão, consequências e critérios para
reconsiderá-la. Consulte o [índice de ADRs](adr/README.md) antes de propor uma
mudança que envolva contratos, layouts, Airflow, LLM, portal ou catálogo.

### [Guias](guides/)

Instruções reutilizáveis para quem cria ou revisa artefatos do produto. O guia
de contrato semântico e layout signature é o ponto de partida para adicionar um
novo tipo de PDF sem criar lógica específica na aplicação. O guia de
[desenvolvimento orientado a métricas](guides/desenvolvimento-orientado-a-metricas.md)
define como toda mudança de comportamento deve ser medida antes de permanecer, e
[Langfuse do zero](guides/langfuse-guia-do-zero.md) ensina a navegar a ferramenta
e a ler cada métrica para quem nunca a usou.

### [Referência](reference/)

Modelos estáveis, exemplos e formatos de integração: estrutura MinIO, schema
Postgres, artefatos Docling e exemplos completos de layouts. Use esta seção
para confirmar formatos, não para decidir arquitetura.

### [Operações](operations/)

Documentação para subir, configurar e manter os serviços: runtime Docling,
OpenMetadata e linha de base da reorganização. A matriz de migração documenta
origem, situação e substitutos de materiais que foram reorganizados.

### [Planos](plans/)

Trabalho futuro proposto ou aprovado. Planos não descrevem necessariamente o
comportamento atual; antes de implementar, confira sua situação e relacione a
mudança a uma SPEC e, quando necessário, a uma ADR.

### [Arquivo](archive/)

Análises experimentais, implementações já concluídas, documentação legada e
planos substituídos. Eles preservam contexto histórico, mas não são fonte de
verdade sem uma verificação explícita de documentos vigentes ou substitutos.

## Como manter esta pasta

- Alteração funcional relevante começa em `specs/` e ganha critério de aceite.
- Decisão arquitetural duradoura exige ADR; uma ADR nova substitui uma decisão,
  não reescreve silenciosamente seu histórico.
- Documento vigente deve informar status, responsável, data de revisão e fonte
  de verdade quando isso não estiver evidente pelo tipo de documento.
- Links devem ser relativos e permanecer válidos após mover ou renomear arquivos.
- Materiais históricos devem ir para `archive/` com indicação clara de que não
  representam o comportamento atual.

## O que não fica aqui

- Código e contratos executáveis ficam fora de `docs/`;
- resultados manuais de observabilidade de DAG 3 não são documentação canônica;
- logs detalhados de execução continuam em Airflow, MinIO e ferramentas de
  observabilidade, conforme a ADR 0006.
