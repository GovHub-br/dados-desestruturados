# ADR 0003 — Descoberta/download e extração são fluxos separados

- Status: Aceito
- Data: 2026-08-23
- Fonte de verdade: `docs/architecture/airflow-orchestration.md`

## Contexto

Nem todo PDF vem de um site de relações com investidores. Documentos podem ser
enviados pelo portal ou persistidos diretamente em documentos de origem.

## Decisão

A descoberta e o download são tratados como etapa de aquisição específica de
fonte. A extração consome documentos já persistidos e é genérica para qualquer
domínio documental.

## Consequências

- O pipeline Docling pode processar PDFs manuais e automatizados igualmente.
- Adaptadores de descoberta não contaminam a regra de extração.
- A idempotência é controlada pelo documento de origem e seu checksum.

