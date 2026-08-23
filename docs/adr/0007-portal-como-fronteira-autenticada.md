# ADR 0007 — Portal como fronteira autenticada

- Status: Aceito
- Data: 2026-08-23
- Fonte de verdade: `docs/architecture/portal.md`

## Contexto

Usuários precisam enviar PDFs e publicar contratos sem depender de acesso direto
a MinIO, Airflow ou detalhes internos da infraestrutura.

## Decisão

O portal valida domínio, versão, entidade e arquivos; o backend autenticado
persiste os artefatos e dispara os fluxos permitidos. O navegador não recebe
credenciais de MinIO nem de Airflow.

## Consequências

- A interface é uma superfície de produto, não um atalho administrativo.
- Autorização e validação ficam centralizadas no backend.
- A rastreabilidade apresentada ao usuário usa identificadores operacionais.

