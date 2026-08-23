# ADR 0003 — Descoberta/download e extração são fluxos separados

- Status: Aceito
- Data: 2026-08-16
- Fonte de verdade: `docs/architecture/arquitetura-orquestracao-airflow.md`

## Responsáveis

Mateus de Castro

## Contexto

Nem todo PDF vem de um site de relações com investidores. Documentos podem ser
enviados pelo portal ou persistidos diretamente em documentos de origem.

## Drivers da decisão

- Generalidade para qualquer domínio documental;
- idempotência e reprocessamento;
- isolamento de falhas de fontes externas;
- reuso do pipeline de extração.

## Alternativas consideradas

### Separar aquisição e extração

Uma etapa persiste documentos de origem; outra consome somente documentos
elegíveis para extração.

**Vantagens**

- Uploads e documentos descobertos compartilham a mesma extração;
- reprocessar não exige novo download;
- conectores não contaminam Docling.

**Desvantagens**

- Requer manifestos e observabilidade de estado entre as etapas.

### Acoplar download e extração por fonte

**Vantagens**

- Menor implementação inicial.

**Desvantagens**

- Duplica regra e exclui facilmente PDFs manuais.

### Fazer o portal chamar Docling diretamente

**Vantagens**

- Menor latência aparente.

**Desvantagens**

- Transfere execução, credenciais e falhas operacionais ao portal.

## Decisão

A descoberta e o download são tratados como etapa de aquisição específica de
fonte. A extração consome documentos já persistidos e é genérica para qualquer
domínio documental.

## Consequências

- O pipeline Docling pode processar PDFs manuais e automatizados igualmente.
- Adaptadores de descoberta não contaminam a regra de extração.
- A idempotência é controlada pelo documento de origem e seu checksum.

## Riscos

- Uma varredura mal configurada pode selecionar documentos indevidos;
- a identidade/checksum deve impedir duplicação entre canais.

## Implementação

- A aquisição persiste PDF e metadados de origem;
- a extração cria manifesto e artefatos somente para documentos elegíveis;
- o portal usa o mesmo caminho de documentos de origem;
- adaptadores de RI permanecem fora do núcleo de extração.

## Critérios para reconsideração

Revisitar se a latência entre etapas se tornar inaceitável, se a extração passar
a exigir metadados ausentes do manifesto ou se eventos de armazenamento
substituírem a varredura.

## Referências

- `docs/architecture/docling-pipeline.md`;
- ADR 0008.
